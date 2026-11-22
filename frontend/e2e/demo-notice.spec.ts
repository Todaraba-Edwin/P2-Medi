import { expect, test } from "@playwright/test";
import { openApp } from "./helpers";

// 합성 데이터 데모 표시(BE-13-07 A)는 목(MSW) 빌드에서만 보인다. 이 파일은 Playwright 프로젝트 `app`(실서버 모드, `NEXT_PUBLIC_API_MOCKING` 빈 값)에서 돌며
// 표시가 DOM에 없는 것을 고정한다. 목 빌드에서 보이는 것은 `demo-notice.msw.spec.ts`가 본다.
test("실서버 모드에서는 합성 데이터 데모 표시가 DOM에 없다", async ({ page }) => {
  await openApp(page);
  await expect(page.getByTestId("demo-notice")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("합성 데이터 데모");
});
