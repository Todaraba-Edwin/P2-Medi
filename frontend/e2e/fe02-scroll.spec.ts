import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, banner, expectInFirstScreen, mockChat, openApp, release, waitHeld } from "./helpers";

// FE-02 §3 "긴 결과 카드 윗부분이 첫 화면 밖"(w2 점검 재현, 2026-11-20 사용자 지시 "스크롤 수정"). Playwright 프로젝트 `app`(페이지 안 fetch 대역).
// 규칙: 최종 답변이 오면 그 답변 블록의 맨 위(요약 시작)가 대화 영역 위쪽에 온다 → "삐! 병용금기" 판정 줄·요약이 첫 화면 안.
// 진행 표시 동안은 맨 아래를 따라가고, 사용자가 직접 스크롤한 뒤에는 옮기지 않는다. 119 배너는 대화 영역 밖(맨 위 고정) 그대로다.
// 캡처: `FE02_SHOT_DIR`을 주면 그 폴더에, 아니면 로컬 전용 `data/mock/fe-issue-shots`(저장소 루트, worktree 옆 메인 저장소, `.claude/worktrees/` 안 worktree의 메인 저장소 순)에
// `*-scroll.png`를 남긴다. 둘 다 없으면 찍지 않는다.
const SHOT_DIR =
  process.env.FE02_SHOT_DIR ??
  ["../../data/mock/fe-issue-shots", "../../../P2-Medi/data/mock/fe-issue-shots", "../../../../../data/mock/fe-issue-shots"].map((dir) => path.resolve(__dirname, dir)).find((dir) => existsSync(dir));
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-scroll.png`) });
};

/** 대화 영역 위 여백(`pt-2`, Conversation.tsx `THREAD_PADDING_TOP`) */
const PADDING_TOP = 8;
/** 대화 영역 아래 여백(`pb-3`). 진행 중 따라가기의 끝 표지(`end`)는 이 여백 위에 있다 */
const PADDING_BOTTOM = 12;
const thread = (page: Page) => page.getByTestId("chat-thread");
const lastAnswer = (page: Page) => page.getByTestId("turn-answer").last();
const metrics = (page: Page) => thread(page).evaluate((el) => ({ top: el.scrollTop, height: el.clientHeight, scrollHeight: el.scrollHeight }));

/**
 * 마지막 답변 블록의 위가 대화 영역 위쪽(여백만큼 아래)에 있고, 그 안의 첫 판정 줄과 요약이 첫 화면·영역 안에 있다.
 * 답변 블록이 영역보다 짧으면 스크롤이 끝까지 가도 위에 못 닿는다(브라우저가 범위 안으로 자른다) → 그때는 맨 아래이고 답변이 영역 안에서 시작하면 된다
 */
async function expectAnswerAtTop(page: Page) {
  const box = (await thread(page).boundingBox())!;
  const answer = (await lastAnswer(page).boundingBox())!;
  const { top, height, scrollHeight } = await metrics(page);
  const atMax = Math.abs(top - (scrollHeight - height)) <= 1;
  if (!atMax) expect(Math.abs(answer.y - (box.y + PADDING_TOP))).toBeLessThanOrEqual(1);
  else expect(answer.y).toBeGreaterThanOrEqual(box.y + PADDING_TOP - 1);
  const summary = lastAnswer(page).getByTestId("result-summary");
  const badge = lastAnswer(page).getByTestId("status-badge").first();
  for (const target of [summary, badge]) {
    await expectInFirstScreen(page, target);
    const rect = (await target.boundingBox())!;
    expect(rect.y).toBeGreaterThanOrEqual(box.y - 0.5);
    expect(rect.y + rect.height).toBeLessThanOrEqual(box.y + box.height + 0.5);
  }
}

for (const width of [393, 1280]) {
  test.describe(`답변 도착 스크롤 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("일반 결과 → 응급 결과: 답변이 오면 요약·'삐!' 판정 줄이 첫 화면 안, 119 배너는 맨 위 그대로. 사용자가 스크롤한 뒤에는 옮기지 않는다", async ({ page }) => {
      await mockChat(page, "found", "emergency", { name: "found", holdBefore: "answer" });
      await openApp(page);
      // 1) 첫 답변: 답변 블록 맨 위가 영역 위쪽(영역이 넘칠 때만 의미가 있고, 넘치지 않으면 위치는 자연히 안이다)
      await ask(page);
      await expect(lastAnswer(page).getByTestId("result-card")).toBeVisible();
      const first = await metrics(page);
      if (first.scrollHeight > first.height + 1) await expectAnswerAtTop(page);
      await expectInFirstScreen(page, lastAnswer(page).getByTestId("result-summary"));
      await expectInFirstScreen(page, lastAnswer(page).getByTestId("status-badge").first());
      await shot(page, "general-answer");
      // 2) 두 번째 질문(응급): 영역은 반드시 넘친다. 119 배너가 맨 위, 그 아래 대화 영역에는 두 번째 답변의 요약부터
      await ask(page);
      await expect(page.getByTestId("turn-answer")).toHaveCount(2);
      await expect(lastAnswer(page).getByTestId("result-card")).toBeVisible();
      const second = await metrics(page);
      expect(second.scrollHeight).toBeGreaterThan(second.height + 1);
      expect(second.top).toBeGreaterThan(0);
      await expectAnswerAtTop(page);
      await expectInFirstScreen(page, banner(page));
      expect(await page.getByTestId("app-shell").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-row");
      expect((await thread(page).boundingBox())!.y).toBeGreaterThanOrEqual((await banner(page).boundingBox())!.y);
      await shot(page, "emergency-answer");
      // 3) 세 번째 질문: 진행 표시 동안은 맨 아래를 따라간다. 사용자가 위로 올리면 답변이 와도 옮기지 않는다
      await ask(page);
      await waitHeld(page);
      await expect(page.getByRole("status", { name: "진행 상태" })).toBeVisible();
      const during = await metrics(page);
      expect(Math.abs(during.top - (during.scrollHeight - during.height))).toBeLessThanOrEqual(PADDING_BOTTOM + 1); // 맨 아래(끝 표지는 아래 여백 위에 있다)
      // 사용자 스크롤(scroll 이벤트는 다음 렌더링 프레임에 나가므로 두 프레임 기다린다. 실제 손 스크롤은 답변보다 훨씬 앞서 프레임을 지난다)
      await thread(page).evaluate(async (el) => {
        el.scrollTop = 0;
        await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      });
      await expect.poll(() => metrics(page).then((m) => m.top)).toBe(0);
      await release(page);
      await expect(page.getByTestId("turn-answer")).toHaveCount(3);
      await expect(lastAnswer(page).getByTestId("result-card")).toBeAttached();
      await page.waitForTimeout(200);
      expect((await metrics(page)).top).toBe(0);
      await shot(page, "user-scrolled");
    });
  });
}
