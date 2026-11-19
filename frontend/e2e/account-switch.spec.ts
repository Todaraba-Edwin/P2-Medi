import { expect, test } from "@playwright/test";
import { HEIGHT, QUESTION, ask, input, mockChat, openApp } from "./helpers";

// 계정 진입점 스위치(FE-04-02 A, 사용자 결정 2026-11-19). 이 파일은 Playwright 프로젝트 `app`(MSW 꺼짐 = 실제 백엔드 모드)에서 돈다.
// 실제 백엔드에는 아직 로그인 길이 없으므로 `로그인/가입`·계정 자리를 그리지 않고 `/api/me`도 부르지 않는다.
// 목 모드에서 보이는 쪽은 `account.msw.spec.ts`(프로젝트 `msw-worker`)가 본다.
for (const width of [360, 1280]) {
  test.describe(`실제 백엔드 모드에서는 계정 진입점이 없다 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면·사이드바·드로어에 로그인/가입이 없고 계정 API를 부르지 않는다. 질문은 그대로 된다", async ({ page }) => {
      const accountCalls: string[] = [];
      page.on("request", (request) => {
        const { pathname } = new URL(request.url());
        if (/\/api\/(me|profiles|consents|legal|auth)(\/|$)/.test(pathname)) accountCalls.push(`${request.method()} ${pathname}`);
      });
      await mockChat(page, "found");
      await openApp(page);
      await expect(input(page)).toBeVisible();
      for (const testId of ["entry-choice", "login-entry", "guest-start", "account-entry", "account-menu", "account-modal", "target-picker"]) {
        await expect(page.getByTestId(testId), testId).toHaveCount(0);
      }
      await expect(page.getByRole("button", { name: "로그인/가입" })).toHaveCount(0);
      if (width < 1024) {
        await page.getByRole("button", { name: "메뉴 열기" }).click();
        await expect(page.getByTestId("menu-drawer")).toBeVisible();
        await expect(page.getByTestId("menu-drawer").getByTestId("account-entry")).toHaveCount(0);
        await expect(page.getByText("로그인/가입")).toHaveCount(0);
        await page.keyboard.press("Escape");
        await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
      }
      await ask(page, QUESTION);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect(page.getByTestId("target-picker")).toHaveCount(0);
      expect(accountCalls).toEqual([]);
    });
  });
}
