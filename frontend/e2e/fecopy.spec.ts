import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, dock, expectInFirstScreen, expectNoHorizontalScroll, input, mockChat, openApp, overlaySidebar, pushSidebar } from "./helpers";

// 문구·화면 정리(2026-11-20 F1): 입력창 아래 고지(PRD-17-07 A)와 사이드바 저장 안내 삭제(PRD-17-08 A). 로그인 제목은 fecopy.msw.spec.ts.
// 캡처: `FECOPY_SHOT_DIR`을 주면 그 폴더에 `*-fecopy.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FECOPY_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fecopy.png`) });
};

/** 승인 원문(PRD-17-07 A, 2026-11-19) */
const INPUT_NOTICE = "질문은 이 탭에만 있고 저장하지 않아요. 새로고침하거나 탭을 닫으면 사라져요. 답변을 만들기 위해 질문은 외부 AI(OpenAI)로 전송돼요.";
/** 삭제한 사이드바 문구(PRD-17-08 A) */
const REMOVED_SIDEBAR_NOTE = "대화는 이 화면에만 있고 저장하지 않아요. 새로고침하거나 닫으면 사라져요.";
const notice = (page: Page) => page.getByTestId("input-notice");

/** 고지가 입력창 바로 아래(겹치지 않고 가깝게), 고정 안내·법적 고지는 입력창 위에 있어 서로 겹치지 않는다 */
async function expectNoticeUnderInput(page: Page) {
  await expect(notice(page)).toHaveText(INPUT_NOTICE);
  await expectInFirstScreen(page, notice(page));
  const inputBox = (await input(page).boundingBox())!;
  const noticeBox = (await notice(page).boundingBox())!;
  expect(noticeBox.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height - 0.5);
  expect(noticeBox.y - (inputBox.y + inputBox.height)).toBeLessThanOrEqual(24);
  const footer = (await page.getByTestId("legal-footer").boundingBox())!;
  expect(footer.y + footer.height).toBeLessThanOrEqual(inputBox.y + 0.5);
  // 안내이지 관문이 아니다: 체크·버튼 없음, 접히는 틀 밖, 마스코트 없음, 읽을 수 있는 크기
  await expect(notice(page).locator("button, a, input")).toHaveCount(0);
  expect(await notice(page).evaluate((el) => el.closest("details, [role=dialog], [data-state=closed]") === null)).toBe(true);
  await expect(dock(page).getByTestId("mascot")).toHaveCount(0);
  expect(await notice(page).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
  await expect(input(page)).toHaveAttribute("aria-describedby", (await notice(page).getAttribute("id")) ?? "");
  await expectNoHorizontalScroll(page);
}

for (const width of [393, 1280]) {
  const desktop = width >= 1024;
  test.describe(`문구 정리 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면(게스트): 입력창 아래 고지가 승인 원문 그대로 보이고 기존 안내와 겹치지 않는다", async ({ page }) => {
      await openApp(page);
      await expectNoticeUnderInput(page);
      // 시작 화면 안내 2종(119 줄·외부 AI 고지)과 법적 고지는 입력창 위, 새 고지는 입력창 아래: 세로로 나란하고 겹치지 않는다
      const external = (await page.getByTestId("external-ai-notice").boundingBox())!;
      const noticeBox = (await notice(page).boundingBox())!;
      expect(external.y + external.height).toBeLessThanOrEqual(noticeBox.y);
      await shot(page, "start-notice");
    });

    test("답을 받은 뒤: 고정 안내·고지 아래 입력창, 그 아래 고지가 그대로 있고 사이드바·드로어에 저장 안내가 없다", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expectNoticeUnderInput(page);
      const fixed = (await dock(page).getByTestId("fixed-notice").boundingBox())!;
      const inputBox = (await input(page).boundingBox())!;
      expect(fixed.y + fixed.height).toBeLessThanOrEqual(inputBox.y + 0.5);
      if (desktop) {
        // 넓은 폭: 펼친 사이드바(근거 패널이 열리면 오버레이·레일일 수 있다)에 긴 저장 안내가 없다. 머리줄 짧은 안내는 유지
        if ((await pushSidebar(page).count()) === 0 && (await overlaySidebar(page).count()) === 0) await page.getByTestId("sidebar-toggle").click();
        const sidebar = page.getByTestId("sidebar");
        await expect(sidebar).toBeVisible();
        await expect(sidebar.getByTestId("current-chat")).toBeVisible();
        await expect(sidebar).not.toContainText(REMOVED_SIDEBAR_NOTE);
        await expect(sidebar).not.toContainText("저장하지 않아요");
        await shot(page, "answered-sidebar");
        // 패널을 닫으면 머리줄에 짧은 안내 "대화는 저장하지 않아요"가 보인다(PRD-17-08 A: 유지)
        const closePanel = page.locator('aside[data-testid="evidence-panel"]').getByRole("button", { name: "닫기" });
        if ((await closePanel.count()) > 0) await closePanel.click();
        await expect(page.getByTestId("top-bar")).toContainText("대화는 저장하지 않아요");
        await expect(page.getByTestId("top-bar")).not.toContainText("이 화면에만");
      } else {
        await page.getByRole("button", { name: "메뉴 열기" }).click();
        const drawer = page.getByTestId("menu-drawer");
        await expect(drawer).toBeVisible();
        await expect(drawer.getByTestId("current-chat")).toBeVisible();
        await expect(drawer).not.toContainText(REMOVED_SIDEBAR_NOTE);
        await expect(drawer).not.toContainText("저장하지 않아요");
        await shot(page, "answered-drawer");
      }
      // 화면 전체에서 삭제한 문구는 어디에도 없다
      await expect(page.locator("body")).not.toContainText(REMOVED_SIDEBAR_NOTE);
    });
  });
}
