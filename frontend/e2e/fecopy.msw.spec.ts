import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, openApp } from "./helpers";

// 로그인 제목 "간편 로그인"(FE-04-17 A, 2026-11-19). 계정 모달은 목 모드(msw-worker 프로젝트)에서 보인다(FE-04-02 A·FE-04-05 A).
// 캡처: `FECOPY_SHOT_DIR`을 주면 그 폴더에 `*-fecopy.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FECOPY_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fecopy.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");

for (const width of [393, 1280]) {
  test.describe(`로그인 제목 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("로그인 첫 화면의 소셜 묶음 제목은 '간편 로그인'이고 이전 글자는 남지 않는다", async ({ page }) => {
      await openApp(page);
      await page.getByTestId("login-entry").click();
      await expect(modal(page)).toHaveAttribute("data-step", "login");
      const social = modal(page).getByRole("group", { name: "간편 로그인" });
      await expect(social).toBeVisible();
      await expect(social.getByRole("heading", { level: 3 })).toHaveText("간편 로그인");
      await expect(social.getByRole("button")).toHaveText(["Google로 계속하기", "카카오 로그인"]);
      await expect(modal(page)).not.toContainText("다른 방법으로 로그인");
      // 게스트 입력창 고지는 모달 뒤 화면에 그대로 있다(모달 안에는 없다)
      await expect(modal(page).getByTestId("input-combined-notice")).toHaveCount(0);
      await expect(page.getByTestId("input-combined-notice")).toHaveCount(1);
      await expectNoHorizontalScroll(page);
      await shot(page, "login-title");
    });
  });
}
