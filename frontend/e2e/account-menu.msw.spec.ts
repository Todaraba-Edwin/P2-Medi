import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, openAccountMenu, openApp } from "./helpers";

// 계정 메뉴 팝오버(2026-11-23 사용자 요구, 참고 ISSUE-027 = claude.ai 앱 사이드바 하단): 사이드바·드로어 아래 계정 버튼 하나를 누르면 메뉴가 위로 열린다.
// 회원: 프로필 관리 · 화면 모드(밝은·다크·시스템을 바로 고른다) · 약관·정책 · ─ · 로그아웃. 게스트: 로그인/가입 · 화면 모드 · 약관·정책.
// 따로 떠 있던 `프로필 관리`·`설정`·`로그아웃` 행은 없다(기능은 메뉴 안에서 그대로). 접근성: aria-haspopup/aria-expanded, 열면 첫 항목 초점, ↑↓·Esc·바깥 누름.
// 캡처: `FE_PROFILE_SETTINGS_SHOT_DIR`을 주면 `profile-settings-{width}-{scheme}.png`(회원, 메뉴 열림)·`profile-settings-guest-{width}-{scheme}.png`(게스트)를 남긴다.
const SHOT_DIR = process.env.FE_PROFILE_SETTINGS_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};

const button = (page: Page) => page.getByTestId("account-menu-button").first();
const itemNames = (page: Page) => page.getByTestId("account-menu").locator('[role="menuitem"], [role="menuitemradio"]').evaluateAll((items) => items.map((item) => item.textContent?.trim()));

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`계정 메뉴 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("회원: 버튼 하나(선택된 프로필, FE-17 U-06)와 메뉴 항목 순서, 별도 행 없음, 첫 항목 초점·↑↓·Esc·바깥 누름", async ({ page }) => {
        await openApp(page, "?mock_session=onboarded&account_menu=1");
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        if (width < 1024) await page.getByTestId("menu-button").click();
        const trigger = button(page);
        await expect(trigger).toHaveText("나"); // 로그인 직후 본인이 기본 대상: 선택된 프로필의 병아리 + 사용자가 적은 이름(이메일 등 새 값을 노출하지 않는다, FE-17 U-06)
        await expect(trigger).toHaveAttribute("aria-haspopup", "menu");
        await expect(trigger).toHaveAttribute("aria-expanded", "false");
        await expectTouchTarget(trigger, { widthToo: false });
        // 따로 떠 있던 행은 없다(사이드바·드로어 어디에도)
        const sidebarScope = width < 1024 ? page.getByTestId("menu-drawer") : page.getByTestId("sidebar");
        for (const name of ["프로필 관리", "설정", "로그아웃", "약관·정책"]) await expect(sidebarScope.getByRole("button", { name }), name).toHaveCount(0);

        await trigger.click();
        const menu = page.getByTestId("account-menu");
        await expect(menu).toBeVisible();
        await expect(trigger).toHaveAttribute("aria-expanded", "true");
        // 맨 위는 프로필 관리, 그 바로 아래(하위)가 대상 프로필 목록(FE-17 U-06: 게스트로 이용·본인·가족), 그 아래 기존 계정 메뉴
        expect(await itemNames(page)).toEqual(["프로필 관리", "게스트로 이용", "나", "첫째", "밝은 모드", "다크 모드", "시스템기기 설정을 따라요", "약관·정책", "로그아웃"]);
        await expect(menu.getByRole("separator")).toHaveCount(2);
        await expect(menu.getByRole("menuitem", { name: "프로필 관리" })).toBeFocused();
        for (const item of await menu.locator('[role="menuitem"], [role="menuitemradio"]').all()) await expectTouchTarget(item, { widthToo: false });
        // 메뉴는 버튼 위로 열리고 화면을 벗어나지 않는다
        const menuBox = (await menu.boundingBox())!;
        const triggerBox = (await trigger.boundingBox())!;
        expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(triggerBox.y + 0.5);
        expect(menuBox.y).toBeGreaterThanOrEqual(0);
        await expectNoHorizontalScroll(page);
        await shot(page, `profile-settings-${width}-${scheme}`);

        // 키보드: ↓로 옮기고 끝에서 처음으로 돈다. Esc로 닫히면 초점은 버튼으로
        await page.keyboard.press("ArrowDown");
        await expect(menu.getByRole("menuitemradio", { name: "게스트로 이용" })).toBeFocused();
        await page.keyboard.press("ArrowUp");
        await expect(menu.getByRole("menuitem", { name: "프로필 관리" })).toBeFocused(); // 초점 이동은 비동기라 한 번씩 기다린다
        await page.keyboard.press("ArrowUp");
        await expect(menu.getByRole("menuitem", { name: "로그아웃" })).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(menu).toHaveCount(0);
        await expect(trigger).toHaveAttribute("aria-expanded", "false");
        await expect(trigger).toBeFocused();
        if (width < 1024) await expect(page.getByTestId("menu-drawer")).toBeVisible(); // Esc 한 번에 메뉴만 닫힌다(드로어는 그대로)

        // 바깥을 누르면 닫힌다
        await trigger.click();
        await expect(menu).toBeVisible();
        await expect(menu.getByRole("menuitem", { name: "프로필 관리" })).toBeFocused(); // 첫 항목(프로필 관리). 열림이 끝난 뒤(바깥 누름 감지는 열린 다음 틱부터 돈다)
        await page.mouse.click(width < 1024 ? 200 : 700, 80);
        await expect(menu).toHaveCount(0);
      });

      test("회원: 화면 모드를 메뉴에서 바로 고르면 즉시 적용·저장되고(서버 호출 0) 메뉴는 열린 채, 프로필 관리·로그아웃은 메뉴 안에서 그대로 동작한다", async ({ page }) => {
        const writes: string[] = [];
        page.on("request", (request) => {
          const pathname = new URL(request.url()).pathname;
          if (request.method() !== "GET" && pathname.startsWith("/api/")) writes.push(`${request.method()} ${pathname}`);
        });
        await openApp(page, "?mock_session=onboarded&account_menu=1");
        const menu = await openAccountMenu(page);
        const other = scheme === "dark" ? "밝은 모드" : "다크 모드";
        await expect(menu.getByRole("menuitemradio", { name: /^시스템/ })).toHaveAttribute("aria-checked", "true");
        await menu.getByRole("menuitemradio", { name: other }).click();
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme === "dark" ? "light" : "dark");
        await expect(menu).toBeVisible();
        await expect(menu.getByRole("menuitemradio", { name: other })).toHaveAttribute("aria-checked", "true");
        expect(writes).toEqual([]);
        await page.keyboard.press("Escape");
        await page.reload();
        await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme === "dark" ? "light" : "dark");

        // 프로필 관리 → 계정 모달(프로필 화면). 드로어·메뉴는 닫힌다
        const menu2 = await openAccountMenu(page);
        await menu2.getByTestId("account-entry").click();
        await expect(menu2).toHaveCount(0);
        await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        await expect(page.getByTestId("account-modal")).toHaveAttribute("data-step", "profiles");
        await expect(page.getByTestId("account-modal").getByTestId("profile-item")).toHaveCount(2);
        await page.getByTestId("account-modal").getByRole("button", { name: "닫기" }).click();
        await expect(page.getByTestId("account-modal")).toHaveCount(0);

        // 로그아웃(기존 동작: 확인창 없음) → 게스트. 버튼은 `계정`이 되고 메뉴에 로그아웃이 없다
        const menu3 = await openAccountMenu(page);
        await menu3.getByTestId("account-logout").click();
        await expect(menu3).toHaveCount(0);
        await expect(button(page)).toHaveText("계정");
        expect(writes).toEqual(["POST /api/auth/logout"]);
        const menu4 = await openAccountMenu(page);
        expect(await itemNames(page)).toEqual(["로그인/가입", "밝은 모드", "다크 모드", "시스템기기 설정을 따라요", "약관·정책"]);
        await expect(menu4.getByTestId("account-logout")).toHaveCount(0);
      });

      test("게스트: 버튼 `계정` → 로그인/가입·화면 모드·약관·정책. 로그인/가입은 계정 모달(로그인)을 연다", async ({ page }) => {
        await openApp(page);
        if (width < 1024) await page.getByTestId("menu-button").click();
        const trigger = button(page);
        await expect(trigger).toHaveText("계정");
        const sidebarScope = width < 1024 ? page.getByTestId("menu-drawer") : page.getByTestId("sidebar");
        for (const name of ["로그인/가입", "설정", "약관·정책"]) await expect(sidebarScope.getByRole("button", { name }), name).toHaveCount(0);
        await trigger.click();
        const menu = page.getByTestId("account-menu");
        await expect(menu).toHaveAttribute("data-audience", "guest");
        expect(await itemNames(page)).toEqual(["로그인/가입", "밝은 모드", "다크 모드", "시스템기기 설정을 따라요", "약관·정책"]);
        await expect(menu.getByRole("menuitem", { name: "로그인/가입" })).toBeFocused();
        await expect(menu.getByRole("separator")).toHaveCount(0);
        await shot(page, `profile-settings-guest-${width}-${scheme}`);
        await page.keyboard.press("Enter");
        await expect(menu).toHaveCount(0);
        await expect(page.getByTestId("account-modal")).toHaveAttribute("data-step", "login");
      });
    });
  }
}

test.describe("접힌 사이드바 레일(1280)", () => {
  test.use({ viewport: { width: 1280, height: HEIGHT } });
  test("레일의 계정 아이콘 버튼도 같은 메뉴를 연다(게스트: 화면 모드·약관·정책 접근 유지)", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("sidebar-toggle").click();
    const rail = page.getByTestId("sidebar-rail");
    await expect(rail).toBeVisible();
    const trigger = rail.getByTestId("account-menu-button");
    await expect(trigger).toHaveAccessibleName("계정");
    await expectTouchTarget(trigger);
    await trigger.click();
    const menu = page.getByTestId("account-menu");
    await expect(menu).toBeVisible();
    expect(await itemNames(page)).toEqual(["로그인/가입", "밝은 모드", "다크 모드", "시스템기기 설정을 따라요", "약관·정책"]);
    await menu.getByTestId("legal-entry").click();
    await expect(page.getByTestId("legal-dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("legal-dialog")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});
