import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, QUESTION, ask, expectNoHorizontalScroll, expectTouchTarget, mockChat, openApp, requests } from "./helpers";

// 여러 약 되묻기(FE-09, ISSUE-020): 되묻는 이름이 둘이면 묶음마다 하나씩 고르고, 모두 골라야 확인 버튼이 켜지며 요청은 한 번만 간다.
// 통신 대역은 mock 시나리오 `clarifyMulti`(이름 둘, 묶음마다 후보 3개, `가나다시럽`이 두 묶음에 겹침)다.
// 캡처: `FE09_SHOT_DIR`을 주면 그 폴더에 `*-fe09.png`를 남긴다(로컬 전용 폴더. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE09_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fe09.png`) });
};

const MULTI_QUESTION = "'가나다', '가나다시럽'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?";
const group = (page: Page, index: number) => page.getByTestId("candidate-group").nth(index);
const resendButton = (page: Page) => page.getByTestId("resend-button");
const bubble = (page: Page, turn: number) => page.locator(`[data-turn="turn-${turn}"] p[data-side="me"]`);

for (const width of [393, 1280]) {
  test.describe(`여러 약 되묻기 ${width}px(FE-09)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("묶음마다 하나씩 고르고, 모두 골라야 버튼이 켜지며, 누르면 요청 한 번에 고른 약 둘이 실린다", async ({ page }) => {
      await mockChat(page, "clarifyMulti", "found");
      await openApp(page);
      await ask(page);
      // 질문 한 문장(승인 원문)과 이름별 묶음 둘
      await expect(page.getByTestId("result-summary")).toHaveText(MULTI_QUESTION);
      await expect(page.getByTestId("candidate-group")).toHaveCount(2);
      await expect(group(page, 0).getByTestId("candidate")).toHaveCount(3);
      await expect(group(page, 1).getByTestId("candidate")).toHaveCount(3);
      // 펼쳐진 묶음은 radiogroup이고 이름은 되묻는 약 이름 그대로다(FE-10: 표지 글자·후보 수는 이름에 섞이지 않는다)
      await expect(page.getByRole("radiogroup", { name: "가나다", exact: true })).toBeVisible();
      await expect(page.getByRole("radiogroup", { name: "가나다시럽", exact: true })).toBeVisible();
      await expect(page.getByTestId("result-card")).toHaveCount(0); // 고르기 전에는 판정이 없다
      // 처음에는 비활성: 남은 묶음 수를 알린다
      await expect(resendButton(page)).toHaveText("이 약들로 확인하기");
      await expect(resendButton(page)).toHaveAttribute("aria-disabled", "true");
      await expect(page.getByTestId("picks-remaining")).toHaveText("2개 더 골라 주세요");
      await expectTouchTarget(resendButton(page));
      await shot(page, "01-none");

      // 하나만 고른다(두 묶음에 겹치는 제품): 그 묶음은 한 줄로 접히고 버튼은 그대로 비활성이다
      await group(page, 0).getByTestId("candidate").nth(2).click();
      await expect(group(page, 0)).toHaveAttribute("data-collapsed", "true");
      await expect(group(page, 0).getByTestId("candidate-picked")).toContainText("가나다 → 가나다시럽");
      await expect(group(page, 0).getByTestId("candidate")).toHaveCount(0);
      await expect(page.getByTestId("picks-remaining")).toHaveText("1개 더 골라 주세요");
      await expect(resendButton(page)).toHaveAttribute("aria-disabled", "true");
      await resendButton(page).click({ force: true }); // 비활성(`aria-disabled`) 버튼은 눌러도 보내지 않는다(Playwright의 활성 대기를 건너뛰고 누른다)
      expect(await requests(page)).toHaveLength(1);
      await expect(page.locator("[data-turn]")).toHaveCount(1);
      // 겹치는 제품은 다른 묶음에서 고를 수 없고 이유가 보인다(FE-09-03 A)
      const overlap = group(page, 1).getByTestId("candidate").nth(0);
      await expect(overlap).toBeDisabled();
      await expect(overlap).toContainText("다른 약으로 이미 골랐어요");
      await expect(group(page, 1).getByTestId("candidate").nth(1)).toBeEnabled();
      await expectTouchTarget(group(page, 0).getByTestId("candidate-change"));
      await shot(page, "02-one-picked");

      // 둘 다 고르면 버튼이 켜진다
      await group(page, 1).getByTestId("candidate").nth(1).click();
      await expect(group(page, 1)).toHaveAttribute("data-collapsed", "true");
      await expect(resendButton(page)).not.toHaveAttribute("aria-disabled", "true");
      await expect(page.getByTestId("picks-remaining")).toHaveCount(0);
      // 고른 약은 쉼표 대신 캡슐 칸에 담긴다(FE-10): A칸·B칸에 글자와 이름
      await expect(page.getByTestId("capsule-cell")).toHaveText(["A가나다시럽", "B가나다시럽 키즈"]);
      await shot(page, "03-all-picked");

      // "바꾸기"로 다시 펼쳐 다른 제품으로 바꾼다(고른 값은 눌린 채 남아 있고, 버튼은 켜진 그대로다)
      await group(page, 0).getByRole("button", { name: "가나다 바꾸기" }).click();
      await expect(group(page, 0).getByTestId("candidate").nth(2)).toHaveAttribute("aria-checked", "true");
      await expect(resendButton(page)).not.toHaveAttribute("aria-disabled", "true");
      await group(page, 0).getByTestId("candidate").nth(0).click();
      await expect(group(page, 0).getByTestId("candidate-picked")).toContainText("가나다 → 가나다정 100밀리그램");
      // 후보 카드·확인 줄에는 가부로 읽힐 글자가 없다
      await expect(page.getByTestId("candidate-card")).not.toContainText(/삐!|금기|안전|먹어도|드셔도/);
      // 확인 줄의 첫 행은 서버 안내 문장(응답 값, "금기를 확인해 드려요")이다(FE-10). 프런트가 만든 캡슐·남은 수 글자에는 가부 글자가 없다
      await expect(page.getByTestId("resend-pick").getByTestId("candidates-line")).toHaveText("어느 제품인지 고르면 금기를 확인해 드려요.");
      await expect(page.getByTestId("candidates-line")).toHaveCount(1); // 안내 문장은 한 번만 보인다
      await expect(page.getByTestId("picked-capsule")).not.toContainText(/삐!|금기|안전|먹어도|드셔도/);
      await expect(resendButton(page)).not.toContainText(/삐!|금기|안전|먹어도|드셔도/);
      expect(await requests(page)).toHaveLength(1); // 고르기만 했다

      // 한 번 눌러 한 번 보낸다: 원 질문 + 고른 약 둘
      await resendButton(page).click();
      const turn2 = page.locator('[data-turn="turn-2"]');
      await expect(turn2.getByTestId("result-card")).toBeVisible();
      const sent = await requests(page);
      expect(sent).toHaveLength(2);
      expect(sent[1]).toEqual({
        question: QUESTION,
        context: {
          age: null,
          pregnant: false,
          confirmed_drugs: [
            { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" },
            { name: "가나다시럽 키즈", item_seq: "200000004", input_name: "가나다시럽" },
          ],
          prior_drugs: [],
          took_today: null,
        },
      });
      // 말풍선: 처음 차례는 원 질문, 다시 물은 차례는 말풍선 없이 지난 답의 고른 줄 요약 다음에 바로 답이 이어진다(FE-17 U-17이 FE-09-04 A의 표시용 말풍선을 대체)
      await expect(bubble(page, 1)).toHaveText(QUESTION);
      await expect(bubble(page, 2)).toHaveCount(0);
      await expect(page.getByText(/고른 약: /)).toHaveCount(0);
      await expect(page.locator("[data-turn]")).toHaveCount(2);
      // 지난 되묻기(FE-17 U-05·U-17): 고른 줄 요약(A 입력 → 고른 제품)은 남고 고를 수 없으며 `바꾸기`는 숨고, 안내 줄·확인 줄도 숨는다
      const turn1 = page.locator('[data-turn="turn-1"]');
      await expect(turn1.getByTestId("candidate-card")).toHaveAttribute("data-readonly", "true");
      await expect(turn1.getByTestId("candidate-picked")).toHaveText([/^\s*A?\s*가나다\s*→\s*가나다정 100밀리그램\s*$/, /^\s*B?\s*가나다시럽\s*→\s*가나다시럽 키즈\s*$/]);
      await expect(turn1.getByTestId("candidate-change")).toHaveCount(0);
      await expect(turn1.getByTestId("candidate")).toHaveCount(0); // 지난 되묻기의 후보는 더 고를 수 없다
      await expect(turn1.getByTestId("candidates-line")).toHaveCount(0);
      await expect(turn1.getByTestId("resend-pick")).toHaveCount(0);
      await expect(turn1.getByTestId("fixed-notice")).toBeVisible(); // 고정 안내는 그대로(코드 강제)
      await expect(page.getByTestId("candidate-card")).toHaveCount(1);
      await expect(page.getByTestId("resend-pick")).toHaveCount(0);
      // 대화는 저장하지 않는다: 표시용 글자도 브라우저 저장소에 없다
      const stored = await page.evaluate(() => {
        // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
        // eslint-disable-next-line no-restricted-properties
        return JSON.stringify([Object.entries(window.localStorage), Object.entries(window.sessionStorage), document.cookie]);
      });
      expect(stored).not.toContain("고른 약");
      expect(stored).not.toContain("가나다");
      await expectNoHorizontalScroll(page);
      await shot(page, "04-resent");
    });

    test("키보드: 고르면 초점이 '바꾸기'로 가고, 비활성 버튼은 초점을 받지만 Enter로 보내지 않는다", async ({ page }) => {
      await mockChat(page, "clarifyMulti", "found");
      await openApp(page);
      await ask(page);
      await group(page, 0).getByTestId("candidate").first().focus();
      await page.keyboard.press("Enter");
      await expect(group(page, 0).getByTestId("candidate-change")).toBeFocused();
      await resendButton(page).focus();
      await expect(resendButton(page)).toBeFocused();
      await page.keyboard.press("Enter");
      expect(await requests(page)).toHaveLength(1);
      await group(page, 1).getByTestId("candidate").nth(2).focus();
      await page.keyboard.press("Enter");
      await resendButton(page).focus();
      await page.keyboard.press("Enter");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      expect((await requests(page))[1]).toMatchObject({
        context: {
          confirmed_drugs: [
            { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" },
            { name: "가나다시럽 플러스", item_seq: "200000005", input_name: "가나다시럽" },
          ],
        },
      });
    });

    test("'직접 입력'은 묶음마다 있고 입력창으로 간다: 그 묶음은 고른 것으로 치지 않아 버튼은 비활성 그대로다", async ({ page }) => {
      await mockChat(page, "clarifyMulti");
      await openApp(page);
      await ask(page);
      await expect(page.getByRole("button", { name: "목록에 없어요 · 직접 입력" })).toHaveCount(2);
      await group(page, 0).getByTestId("candidate").first().click();
      await group(page, 1).getByRole("button", { name: "목록에 없어요 · 직접 입력" }).click();
      await expect(page.getByRole("textbox")).toBeFocused();
      await expect(group(page, 1)).not.toHaveAttribute("data-collapsed", "true");
      await expect(page.getByTestId("picks-remaining")).toHaveText("1개 더 골라 주세요");
      await expect(resendButton(page)).toHaveAttribute("aria-disabled", "true");
      expect(await requests(page)).toHaveLength(1);
    });
  });
}

test.describe("단일 묶음 되묻기 회귀(FE-09)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("묶음이 하나면 접지 않고 기존 글자 그대로이며, 다시 물은 말풍선만 표시용 글자다", async ({ page }) => {
    await mockChat(page, "clarify", "found");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("resend-pick")).toHaveCount(0); // 고르기 전에는 확인 줄이 없다
    await page.getByTestId("candidate").nth(2).click();
    await expect(page.getByTestId("candidate")).toHaveCount(3); // 접히지 않는다
    await expect(page.getByTestId("candidate-change")).toHaveCount(0);
    await expect(page.getByTestId("candidate").nth(2)).toHaveAttribute("aria-checked", "true");
    await expect(resendButton(page)).toHaveText("이 약으로 다시 묻기");
    await expect(resendButton(page)).not.toHaveAttribute("aria-disabled", "true");
    await resendButton(page).click();
    await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
    const sent = await requests(page);
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual({
      question: QUESTION,
      context: { age: null, pregnant: false, confirmed_drugs: [{ name: "가나다시럽", item_seq: "200000003", input_name: "가나다" }], prior_drugs: [], took_today: null },
    });
    await expect(bubble(page, 2)).toHaveCount(0); // 다시 물은 차례는 말풍선이 없다(FE-17 U-17)
    await expect(page.getByText(/고른 약: /)).toHaveCount(0);
  });

  test("같은 이름을 다시 되물으면 이번에 고른 약만 confirmed_drugs로 가고, 앞서 고른 약은 prior_drugs로 따로 간다(AG-21-02 A; input_name당 하나, FE-09-05 A)", async ({ page }) => {
    await mockChat(page, "clarify", "clarify", "found");
    await openApp(page);
    await ask(page);
    await page.getByTestId("candidate").nth(0).click();
    await resendButton(page).click();
    const turn2 = page.locator('[data-turn="turn-2"]');
    await expect(turn2.getByTestId("candidate-card")).toBeVisible();
    await turn2.getByTestId("candidate").nth(1).click();
    await turn2.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
    await expect(page.locator('[data-turn="turn-3"]').getByTestId("result-card")).toBeVisible();
    const sent = await requests(page);
    expect(sent).toHaveLength(3);
    expect(sent[2]).toEqual({
      question: QUESTION,
      context: {
        age: null,
        pregnant: false,
        confirmed_drugs: [{ name: "가나다정 500밀리그램", item_seq: "200000002", input_name: "가나다" }],
        prior_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" }],
        took_today: null,
      },
    });
  });
});
