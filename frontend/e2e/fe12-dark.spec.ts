import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, ask, mockChat, openApp } from "./helpers";

// 다크 모드(FE-12 ③): 시스템 설정·수동 선택에 따라 바탕과 글자가 토큰대로 바뀌고, 결과 화면 글자 대비가 기준 이상이다.
// 캡처: `FE12_SHOT_DIR`을 주면 그 폴더에 `*-fe12.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE12_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fe12.png`) });
};

const BODY_BG = { light: "rgb(255, 255, 255)", dark: "rgb(23, 21, 15)" } as const; // --color-bg 라이트·다크(globals.css)

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`다크 모드 · 기기 ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("기본은 시스템이라 기기 설정을 따르고, 결과 화면 글자 대비가 기준 이상이다", async ({ page }) => {
        await mockChat(page, "found");
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await expect(page.locator("body")).toHaveCSS("background-color", BODY_BG[scheme]);
        await ask(page);
        await expect(page.locator('[data-turn] [data-testid="result-view"]').first()).toBeVisible();
        const report = await measureContrast(page);
        expect(report.unmeasured).toEqual([]);
        expect(report.samples.length).toBeGreaterThan(0);
        expect(failures(report), `${scheme} ${width}: 기준(${AA_NORMAL}:1) 미달 글자`).toEqual([]);
        await shot(page, `result-${scheme}`);
      });
    });
  }
}

test.describe("화면 모드 선택 저장(1280·393)", () => {
  for (const width of [1280, 393]) {
    test(`${width}px: 설정에서 밝은 모드를 고르면 바로 바뀌고 새로고침 뒤에도 남는다(서버 저장 없음)`, async ({ page }) => {
      await page.setViewportSize({ width, height: HEIGHT });
      await page.emulateMedia({ colorScheme: "dark" });
      await openApp(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      if (width < 1024) await page.getByTestId("menu-button").click();
      await page.getByTestId("settings-entry").first().click();
      const dialog = page.getByTestId("settings-dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("radio", { name: "시스템" })).toHaveAttribute("aria-checked", "true");
      await dialog.getByRole("radio", { name: "밝은 모드" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      // 고른 칸은 노랑(#FFCC00)이 된다. 칸 색은 전환(transition-colors)으로 바뀌므로 끝날 때까지 기다린 뒤 찍는다
      await expect(dialog.getByRole("radio", { name: "밝은 모드" })).toHaveCSS("background-color", "rgb(255, 204, 0)");
      await shot(page, "settings-light");
      await page.reload();
      await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    });
  }
});
