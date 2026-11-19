import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { NEW_CHAT_LABEL } from "../src/app/(shell)/copy";
import { PHRASES, fillPriorPick } from "../src/mocks/fixtures/phrases";
import { HEIGHT, QUESTION, ask, expectNoHorizontalScroll, mockChat, openApp, requests } from "./helpers";

// 이전 차례 선택 힌트(AG-21-02·03 A, GROUP-01 5단계 일부): q1 되묻기 → q2 고른 약으로 다시 묻기(결과) → q3 같은 이름을 새 질문으로.
// 요청 본문은 이번 질문의 답(`confirmed_drugs`)과 이전 차례의 선택(`prior_drugs`)을 나눠 싣는다. 통신 대역은 mock 시나리오(src/mocks/fixtures)다.
// 새 응답 칸(`redose_notice`)의 임시 표시도 여기서 본다. 구역 접기·짝 참조·용량 되묻기 카드는 4단계 디자인 뒤라 아직 없다.

const PICK = { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" };
const EMPTY = { age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [], took_today: null };
const bubble = (page: Page, turn: number) => page.locator(`[data-turn="turn-${turn}"] p[data-side="me"]`);
const turn = (page: Page, n: number) => page.locator(`[data-turn="turn-${n}"]`);

for (const width of [393, 1280]) {
  test.describe(`이전 선택 힌트 ${width}px(AG-21)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("q1 되묻기 → q2 재전송(confirmed) → q3 새 질문(prior만) → 확인 되묻기에서 첫 후보가 이전 선택이고, 고르면 confirmed·prior가 나뉘어 실린다", async ({ page }) => {
      await mockChat(page, "clarify", "found", "clarifyPrior", "found");
      await openApp(page);
      // q1: 되묻기. 요청에는 아무 약도 없다
      await ask(page);
      await expect(turn(page, 1).getByTestId("candidate-card")).toBeVisible();
      expect((await requests(page))[0]).toEqual({ question: QUESTION, context: EMPTY });
      // q2: 첫 후보를 골라 다시 묻기 → 이번 질문의 답만 confirmed_drugs로
      await turn(page, 1).getByTestId("candidate").nth(0).click();
      await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
      await expect(turn(page, 2).getByTestId("result-card")).toBeVisible();
      expect((await requests(page))[1]).toEqual({ question: QUESTION, context: { ...EMPTY, confirmed_drugs: [PICK] } });
      await expect(bubble(page, 2)).toHaveText("고른 약: 가나다정 100밀리그램으로 다시 확인");

      // q3: 같은 이름이 든 새 질문. 답이 왔으므로 고른 약은 이전 선택(prior_drugs)이 되고 confirmed_drugs는 비어 간다
      await ask(page, `다시 ${QUESTION}`);
      await expect(turn(page, 3).getByTestId("candidate-card")).toBeVisible();
      const sent = await requests(page);
      expect(sent).toHaveLength(3);
      expect(sent[2]).toEqual({ question: `다시 ${QUESTION}`, context: { ...EMPTY, prior_drugs: [PICK] } });
      // 확인 되묻기: 질문은 서버 상수(`CLARIFY_PRIOR_PICK`)에 사전 제품명을 채운 문장, 첫 후보가 이전 선택. 화면은 받은 값 그대로 그린다
      await expect(turn(page, 3).getByTestId("result-summary")).toHaveText(fillPriorPick(PICK.name));
      await expect(turn(page, 3).getByTestId("candidate").first().locator("b")).toHaveText(PICK.name);
      await expect(turn(page, 3).getByTestId("result-card")).toHaveCount(0); // 고르기 전에는 판정이 없다
      await expect(turn(page, 3).getByTestId("result-view")).not.toContainText(/삐!|먹어도 돼|안전해요/);
      await expect(bubble(page, 3)).toHaveText(`다시 ${QUESTION}`); // 새 질문의 말풍선은 원 질문이다

      // 확인: 첫 후보(이전 선택)를 다시 고르면 confirmed_drugs = 지금 고른 것, prior_drugs = 이전 선택(둘 다 실린다. 서버는 confirmed로만 확정한다)
      await turn(page, 3).getByTestId("candidate").nth(0).click();
      await turn(page, 3).getByRole("button", { name: "이 약으로 다시 묻기" }).click();
      await expect(turn(page, 4).getByTestId("result-card")).toBeVisible();
      const all = await requests(page);
      expect(all).toHaveLength(4);
      expect(all[3]).toEqual({ question: `다시 ${QUESTION}`, context: { ...EMPTY, confirmed_drugs: [PICK], prior_drugs: [PICK] } });
      await expect(page.locator("[data-turn]")).toHaveCount(4);

      // 대화는 저장하지 않는다: 이전 선택도 브라우저 저장소·쿠키에 없다
      const stored = await page.evaluate(() => {
        // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
        // eslint-disable-next-line no-restricted-properties
        return JSON.stringify([Object.entries(window.localStorage), Object.entries(window.sessionStorage), document.cookie]);
      });
      expect(stored).not.toContain("가나다");
      await expectNoHorizontalScroll(page);
    });

    test("새 대화를 시작하면 이전 선택이 비어 같은 이름을 물어도 처음 되묻기가 온다", async ({ page }) => {
      await mockChat(page, "clarify", "found", "clarify");
      await openApp(page);
      await ask(page);
      await turn(page, 1).getByTestId("candidate").nth(0).click();
      await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
      await expect(turn(page, 2).getByTestId("result-card")).toBeVisible();
      // 새 대화(사이드바·드로어의 "새 질문"): 좁은 폭은 드로어를 먼저 연다
      if (width < 1024) await page.getByRole("button", { name: "메뉴 열기" }).click();
      await page.getByRole("button", { name: NEW_CHAT_LABEL }).first().click();
      await expect(page.getByTestId("home")).toBeVisible();
      await ask(page);
      // 차례 번호는 대화를 비워도 이어진다(스토어 `sequence`): 새 대화의 첫 차례는 turn-3
      await expect(turn(page, 3).getByTestId("candidate-card")).toBeVisible();
      await expect(page.locator("[data-turn]")).toHaveCount(1);
      const sent = await requests(page);
      expect(sent).toHaveLength(3);
      expect(sent[2]).toEqual({ question: QUESTION, context: EMPTY }); // prior_drugs가 비었다
      await expect(turn(page, 3).getByTestId("result-summary")).toHaveText(`'가나다'${PHRASES.CLARIFY_MANY_CANDIDATES.slice("'{drug}'".length)}`);
    });
  });
}

test.describe("새 응답 칸의 임시 표시(AG-22, 디자인 전)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("재복용 질문 고지(redose_notice)는 요약 아래·결과 카드 위의 안내 띠로 받은 글자 그대로 보인다", async ({ page }) => {
    await mockChat(page, "redose");
    await openApp(page);
    await ask(page, "합성 질문 가나다정을 아침에 먹었는데 또 먹어도 되나요");
    await expect(page.getByTestId("result-card")).toBeVisible();
    const band = page.getByTestId("redose-notice");
    await expect(band).toHaveText(PHRASES.REDOSE_NOTICE);
    const [summary, notice, card] = await Promise.all([page.getByTestId("result-summary").boundingBox(), band.boundingBox(), page.getByTestId("result-card").boundingBox()]);
    expect(summary!.y).toBeLessThan(notice!.y);
    expect(notice!.y).toBeLessThan(card!.y);
    await expect(page.getByTestId("dose-notice")).toHaveCount(0);
    await expectNoHorizontalScroll(page);
  });

  test("약 3개 묶음 요약(result_summary)은 결과 카드 바로 위 한 줄이고, 구역·짝 참조·접힘·용량 되묻기는 아직 그리지 않는다", async ({ page }) => {
    await mockChat(page, "resultSummary");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    const line = page.getByTestId("result-summary-line");
    await expect(line).toContainText("약 3개를 함께 먹을 때: 병용금기 1건(가나다정 + 라마바캡슐)");
    await expect(page.getByTestId("pair-only-notice")).toHaveText(PHRASES.PAIR_ONLY_NOTICE);
    const [lineBox, card] = await Promise.all([line.boundingBox(), page.getByTestId("result-card").boundingBox()]);
    expect(lineBox!.y + lineBox!.height).toBeLessThanOrEqual(card!.y + 0.5);
    // 판정 줄은 받은 순서(핵심 → 나머지) 그대로 5줄, 배지는 쌍 줄 하나뿐
    await expect(page.getByTestId("product-line")).toHaveCount(5);
    await expect(page.getByTestId("status-badge")).toHaveCount(1);
    await expect(page.getByTestId("result-view")).not.toContainText(/펼치기|접기|짝 1건에 포함|이미 드셨나요/);
    await expectNoHorizontalScroll(page);
  });
});
