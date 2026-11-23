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

/** 승인 원문(PRD-17-07 A, 2026-11-19; 마지막 문장은 원문 승인 2026-11-22, PRD-17-10 후속, RFP-24-01 요소 보강) */
/** 입력창 아래 통합 고지(FE-17 U-02 초안 그대로, **승인 대기**): 법적 고지 + 저장 안 함·외부 AI 전송·보관 */
const COMBINED_NOTICE =
  "공공데이터 기반 정보 제공이며 진단·처방이 아니에요. 금기 목록에 없어도 안전하다는 뜻은 아니고, 요양기관의 DUR 점검을 대체하지 않아요. 질문은 저장하지 않고 탭을 닫으면 사라지지만, 답변을 만들기 위해 질문과 선택한 프로필 값이 외부 AI(OpenAI)로 전송되며 제공자 정책에 따라 일정 기간 보관될 수 있어요.";
/** 삭제한 사이드바 문구(PRD-17-08 A) */
const REMOVED_SIDEBAR_NOTE = "대화는 이 화면에만 있고 저장하지 않아요. 새로고침하거나 닫으면 사라져요.";
const notice = (page: Page) => page.getByTestId("input-combined-notice");

/**
 * 고지가 입력창 바로 아래(겹치지 않고 가깝게) 한 단락이다(FE-17 U-02: 예전 `legal-footer`·`input-notice` 두 줄은 없다).
 * 고정 안내는 입력창 위에 있어 서로 겹치지 않는다
 */
async function expectNoticeUnderInput(page: Page) {
  await expect(notice(page)).toHaveText(COMBINED_NOTICE);
  await expect(notice(page)).toHaveAttribute("role", "note");
  await expect(page.getByTestId("input-notice")).toHaveCount(0);
  await expect(page.getByTestId("legal-footer")).toHaveCount(0);
  await expectInFirstScreen(page, notice(page));
  const inputBox = (await input(page).boundingBox())!;
  const noticeBox = (await notice(page).boundingBox())!;
  // 입력창 틀(form) 바로 아래다. 질문 칸 아래에는 사진·토글 줄이 있어(FE-17 U-07·U-09, 게스트 포함) 거리는 틀에서 잰다
  const formBox = (await input(page).locator("xpath=ancestor::form").boundingBox())!;
  expect(noticeBox.y).toBeGreaterThanOrEqual(formBox.y + formBox.height - 0.5);
  expect(noticeBox.y - (formBox.y + formBox.height)).toBeLessThanOrEqual(24);
  const fixed = dock(page).getByTestId("fixed-notice");
  if (await fixed.count()) expect((await fixed.boundingBox())!.y + (await fixed.boundingBox())!.height).toBeLessThanOrEqual(inputBox.y + 0.5); // 고정 안내는 입력창 위
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

    test("시작 화면(게스트): 입력창 아래 통합 고지가 상수 그대로 한 단락으로 보이고 기존 안내와 겹치지 않는다", async ({ page }) => {
      await openApp(page);
      await expectNoticeUnderInput(page);
      // 시작 화면 119 줄은 없다(FE-17 U-04). 외부 AI 전송 고지는 통합 고지 1회뿐이다
      await expect(page.getByTestId("start-emergency")).toHaveCount(0);
      await expect(page.getByTestId("external-ai-notice")).toHaveCount(0);
      expect(await page.locator("body").evaluate((el) => (el.textContent?.match(/외부 AI/g) ?? []).length)).toBe(1);
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
