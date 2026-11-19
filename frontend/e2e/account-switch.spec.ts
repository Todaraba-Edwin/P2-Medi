import { expect, test } from "@playwright/test";
import { HEIGHT, QUESTION, ask, input, mockChat, openApp } from "./helpers";

// 계정 진입점 스위치(FE-04-02 A·FE-04-05 A, 사용자 결정 2026-11-19). 이 파일은 Playwright 프로젝트 `app`(MSW 꺼짐 = 실제 백엔드 모드)에서 돈다.
// 이 서버는 Supabase 로그인 설정을 비워 두었다(`playwright.config.ts`의 `NO_SUPABASE`): 로그인할 길이 없으므로
// `로그인/가입`·계정 자리를 그리지 않고 `/api/me`도 부르지 않는다. 설정이 있으면 보이는 쪽은 단위 시험(`src/lib/api/auth.test.ts`)이,
// 목 모드에서 보이는 쪽은 `account.msw.spec.ts`(프로젝트 `msw-worker`)가 본다.
for (const width of [360, 1280]) {
  test.describe(`로그인 설정이 없는 실제 백엔드 모드에서는 계정 진입점이 없다 ${width}px`, () => {
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

    test("로그인 콜백 주소로 들어와도(실패 표시 포함) 첫 화면으로 돌아와 그대로 쓸 수 있고 계정 화면은 뜨지 않는다", async ({ page }) => {
      await mockChat(page, "found");
      for (const query of ["", "?code=synthetic-code", "?error=access_denied&error_description=synthetic"]) {
        await page.goto(`/auth/callback${query}`);
        await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
        expect(new URL(page.url()).pathname).toBe("/");
        await expect(page.getByTestId("account-modal")).toHaveCount(0);
        await expect(input(page)).toBeVisible();
      }
    });
  });
}
