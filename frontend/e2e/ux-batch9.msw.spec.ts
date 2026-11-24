import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { HEIGHT, QUESTION, ask, expectNoHorizontalScroll, mockChat, openApp, pickTarget, release, waitHeld } from "./helpers";

// FE-17 UI/UX 다듬기 9차(2026-11-24 "진행 중인 FE 다음으로 바로 이어서 진행")를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-28(FE 몫, ISSUE-034): 같은 약의 허가사항 항목 줄(`{약} · 주의사항`)이 본문 결과 카드에서 그 약의 판정 행 하나 안 덧붙임 줄(`하루 최대량 주의 성분 포함` 다음)로,
//   근거 상세 판정 구역에서도 같은 약 박스 안으로 들어간다. 사용자에게 보이는 문장 맨 앞의 품목 기준 코드(`209900001 · `)는 화면에서만 숨긴다
// - U-29: `새 질문`을 눌러도 이번 탭의 이전 대화가 사이드바 `지금 대화`에 남고, 누르면 질문·답·근거 상세가 돌아온다. 새로고침하면 비고,
//   브라우저 저장소(localStorage·sessionStorage·IndexedDB)에 질문·답이 없다. 대상을 바꿔 연 새 대화에서도 이전 대화가 남는다. 받는 중 옮겨도 답은 그 대화에 쌓인다
// 캡처: `FE_UX_BATCH9_SHOT_DIR`을 주면 `ux-batch9-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH9_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForTimeout(300); // 강조가 바뀐 항목의 색 전환(transition-colors 150ms)이 끝난 뒤 찍는다
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
/** `openApp`가 주소 끝에 `/`를 붙이므로 마지막 값이 그것을 받는다 */
const LOGGED_IN = "?mock_session=onboarded&ux_batch9=1";
/** 합성 labelMerge의 값(fixtures `responses.ts`) */
const DRUG = "가나다정";
const CODE = "209900001";
const LABEL_TEXT = "주의사항은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요";
const CAUTION_DOSE = "하루 최대량 주의 성분 포함";
const SECOND_QUESTION = "합성 둘째 질문 라마바캡슐만 먹어도 되나요";
const items = (scope: Locator) => scope.locator("[data-chat-id]");

/** 사이드바 목록이 있는 곳: 넓은 폭은 펼친 사이드바, 좁은 폭은 ☰ 드로어(닫혀 있으면 연다) */
async function chatList(page: Page, mobile: boolean): Promise<Locator> {
  if (!mobile) return page.locator('[data-testid="sidebar"][data-presentation="push"]');
  if ((await page.getByTestId("menu-drawer").count()) === 0) await page.getByTestId("menu-button").click();
  const drawer = page.getByTestId("menu-drawer");
  await expect(drawer).toBeVisible();
  return drawer;
}

async function newChat(page: Page, mobile: boolean) {
  await (await chatList(page, mobile)).getByTestId("new-chat").click();
  await expect(page.getByTestId("home")).toBeVisible();
}

/** 브라우저 저장소 전부(localStorage·sessionStorage·IndexedDB 모든 DB의 모든 저장소 값)를 글자로 */
const dumpStorage = (page: Page) =>
  page.evaluate(async () => {
    // 저장소를 직접 들여다보는 시험이라 이 줄만 저장소 접근 금지 규칙을 끈다
    // eslint-disable-next-line no-restricted-properties
    const out: unknown[] = [{ ...window.localStorage }, { ...window.sessionStorage }, document.cookie];
    const databases = (await indexedDB.databases?.()) ?? [];
    for (const info of databases) {
      if (!info.name) continue;
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(info.name!);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      for (const name of [...db.objectStoreNames]) {
        const values = await new Promise<unknown[]>((resolve) => {
          const request = db.transaction(name, "readonly").objectStore(name).getAll();
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => resolve([]);
        });
        out.push({ db: info.name, store: name, values });
      }
      db.close();
    }
    return { text: JSON.stringify(out), databases: databases.map((db) => db.name) };
  });

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 9 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch9-${width}-${scheme}`;
      const mobile = width < 1024;

      test("U-28: 같은 약은 결과 카드에서 행 하나이고, 주의사항 문장은 `하루 최대량 주의 성분 포함` 다음 덧붙임 줄이다. 품목 기준 코드는 보이지 않는다", async ({ page }) => {
        await mockChat(page, "labelMerge");
        await openApp(page);
        await ask(page);
        const card = page.getByTestId("chat-thread").getByTestId("result-card");
        await expect(card).toBeVisible();
        const lines = card.getByTestId("product-line");
        await expect(lines).toHaveCount(1);
        await expect(lines.getByTestId("line-title")).toHaveText(DRUG);
        await expect(lines.locator('[data-slot="notes"]')).toHaveText([CAUTION_DOSE, LABEL_TEXT]);
        const merged = lines.locator('[data-merged="label"]');
        await expect(merged).toHaveAttribute("data-evidence-ids", "ev-label-u28");
        await expect(merged).toHaveAttribute("data-item-code", CODE);
        // 덧붙임 줄과 같은 글자 모양(12px/17px, mute)
        const style = (target: Locator) => target.evaluate((el) => [getComputedStyle(el).fontSize, getComputedStyle(el).lineHeight, getComputedStyle(el).color].join(" "));
        expect(await style(merged)).toBe(await style(lines.locator('[data-slot="notes"]').first()));
        await expect(card).not.toContainText(CODE);
        await expect(card).not.toContainText(`${DRUG} · 주의사항`);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-u28-result`);
      });

      test("U-28: 근거 상세 판정 구역에도 `· 주의사항` 카드가 따로 없고 같은 약 박스 안에 있으며, 허가사항 미확보 카드의 문구 앞 코드도 보이지 않는다", async ({ page }) => {
        await mockChat(page, "labelMerge");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        if (mobile) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        await expect(detail).toBeVisible();
        const judgment = detail.locator('[data-testid="evidence-section"][data-section="judgment"]');
        await expect(judgment.getByTestId("judgment-drug-group")).toHaveCount(1);
        const boxes = judgment.getByTestId("judgment-box");
        await expect(boxes).toHaveCount(1);
        await expect(boxes).toHaveAttribute("data-evidence-ids", "ev-preg-1 ev-label-u28");
        await expect(judgment.getByTestId("line-title")).toHaveText([DRUG]);
        await expect(boxes.locator('[data-slot="notes"]').last()).toHaveText(LABEL_TEXT);
        await expect(judgment).not.toContainText(CODE);
        await expect(detail.getByTestId("missing-text")).toHaveText(LABEL_TEXT);
        await expect(detail.getByTestId("reason-form-count")).toHaveText(["제형유형 2건"]);
        // 서버 몫(하지 않음, U-28 (d)): 권고 줄 가운데의 `{코드} · 주의사항을…`은 서버 글자 그대로다
        await expect(detail.getByTestId("missing-group")).toContainText(`${CODE} · 주의사항을`);
        await shot(page, `${base}-u28-evidence`);
      });

      test("U-29: 새 질문을 눌러도 앞 대화가 목록에 남고, 앞 항목을 누르면 질문·답·근거 상세가 돌아온다. 새로고침하면 비고 브라우저 저장소에 질문·답이 없다", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "found", "judgmentDup");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        if (!mobile) await expect(page.getByTestId("panel-column")).toBeVisible();
        await newChat(page, mobile);
        await expect(page.getByTestId("panel-column")).toHaveCount(0);
        await ask(page, SECOND_QUESTION);
        await expect(page.getByTestId("result-card")).toHaveCount(1);
        let list = await chatList(page, mobile);
        await expect(items(list)).toHaveText([SECOND_QUESTION, QUESTION]);
        await expect(list.getByTestId("current-chat")).toHaveText(SECOND_QUESTION);
        await expect(list.getByTestId("current-chat")).toHaveAttribute("aria-current", "true");
        for (const item of await items(list).all()) expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await shot(page, `${base}-u29-list`);
        // 앞 항목으로
        await list.getByTestId("chat-session").click();
        if (mobile) await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        const thread = page.getByTestId("chat-thread");
        await expect(thread.locator("[data-turn]")).toHaveCount(1);
        await expect(thread).toContainText(QUESTION);
        await expect(thread).not.toContainText(SECOND_QUESTION);
        await expect(thread.getByTestId("result-card")).toBeVisible();
        if (!mobile) await expect(page.getByTestId("panel-column")).toBeVisible(); // 떠날 때 열려 있던 근거 상세
        list = await chatList(page, mobile);
        await expect(list.getByTestId("current-chat")).toHaveText(QUESTION);
        await shot(page, `${base}-u29-restored`);
        if (mobile) await page.getByTestId("menu-drawer").getByRole("button", { name: "메뉴 닫기" }).click();
        // 새로고침 전: 저장소에 질문·답이 없다
        const summaries = await page.getByTestId("result-summary").allTextContents();
        let dump = await dumpStorage(page);
        for (const text of [QUESTION, SECOND_QUESTION, ...summaries]) expect(dump.text).not.toContain(text);
        // 새로고침하면 모두 사라진다
        await page.reload();
        await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
        await expect(page.getByTestId("home")).toBeVisible();
        list = await chatList(page, mobile);
        await expect(items(list)).toHaveCount(0);
        await expect(list).toContainText("아직 질문이 없어요.");
        dump = await dumpStorage(page);
        for (const text of [QUESTION, SECOND_QUESTION, ...summaries]) expect(dump.text).not.toContain(text);
      });

      test("U-29: 대상(프로필)을 바꿔 새 대화가 열려도 앞 대화가 목록에 남고, 누르면 그 대화의 대상으로 돌아간다", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "found");
        await openApp(page, LOGGED_IN);
        await expect(page.getByTestId("target-chip")).toBeVisible();
        await pickTarget(page, "첫째");
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        await pickTarget(page, "나"); // 다른 대상 → 새 대화(U-21)
        await expect(page.getByTestId("home")).toBeVisible();
        const list = await chatList(page, mobile);
        await expect(items(list)).toHaveText([QUESTION]);
        await expect(list.getByTestId("current-chat")).toHaveCount(0); // 지금은 빈 새 대화
        await list.getByTestId("chat-session").click();
        await expect(page.getByTestId("chat-thread")).toContainText(QUESTION);
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 첫째");
      });

      test("U-29: 답을 받는 중에 새 질문을 눌러도 응답은 끊기지 않고 그 대화에 쌓여, 돌아가면 결과가 보인다", async ({ page }) => {
        await mockChat(page, { name: "found", holdBefore: "answer" }, "judgmentDup");
        await openApp(page);
        await ask(page);
        await waitHeld(page);
        await newChat(page, mobile);
        await release(page);
        await expect(page.getByTestId("home")).toBeVisible(); // 지금 화면(새 대화)은 그대로
        await expect(page.getByTestId("panel-column")).toHaveCount(0);
        const list = await chatList(page, mobile);
        await list.getByTestId("chat-session").click();
        await expect(page.getByTestId("chat-thread").getByTestId("result-card")).toBeVisible();
        if (!mobile) await expect(page.getByTestId("panel-column")).toBeVisible(); // 넓은 폭은 뒤에서 온 답의 근거 상세가 열린다
      });
    });
  }
}
