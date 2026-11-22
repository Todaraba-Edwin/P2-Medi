import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, ask, mockChat, openApp, panel, sheet } from "./helpers";

// 다크 모드(FE-12 ③): 시스템 설정·수동 선택에 따라 바탕과 글자가 토큰대로 바뀌고, 결과 화면 글자 대비가 기준 이상이다.
// 캡처: `FE12_SHOT_DIR`을 주면 그 폴더에 `*-fe12.png`(5a 요소 시험은 `*-fe12-5a.png`)를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE12_SHOT_DIR;
const shot = async (page: Page, name: string, suffix = "fe12") => {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-${suffix}.png`) });
};

const BODY_BG = { light: "rgb(255, 255, 255)", dark: "rgb(23, 21, 15)" } as const; // --color-bg 라이트·다크(globals.css)
// 입력창 임신 여부 토글(GROUP-01 5a)의 토큰 값. 고른 칸은 노랑(--color-yellow, 양쪽 같음) + --color-on-yellow, 안 고른 칸은 --color-bg-soft + --color-mute
const YELLOW = "rgb(255, 204, 0)";
const ON_YELLOW = { light: "rgb(0, 0, 0)", dark: "rgb(23, 21, 15)" } as const;
const BG_SOFT = { light: "rgb(255, 248, 225)", dark: "rgb(34, 30, 21)" } as const;
const MUTE = { light: "rgb(107, 95, 63)", dark: "rgb(181, 169, 133)" } as const;
const style = (target: Locator, property: string) => target.evaluate((el, name) => getComputedStyle(el).getPropertyValue(name), property);

async function expectNoContrastFailure(page: Page, label: string, rootSelector?: string) {
  const report = await measureContrast(page, rootSelector);
  expect(report.unmeasured, `${label}: 바탕색을 정할 수 없는 글자`).toEqual([]);
  expect(report.samples.length, `${label}: 잰 글자가 있어야 한다`).toBeGreaterThan(0);
  expect(failures(report), `${label}: 기준(${AA_NORMAL}:1) 미달 글자`).toEqual([]);
  return report;
}

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

      // GROUP-01 5a에서 들어온 요소: 입력창 "일반인 | 임산부" 토글(고른 칸·안 고른 칸), 결과 카드 머리 "기준일 자료" 표지, FE-11-03 한 줄(pregnancy-pick-hint), 근거 상세의 실시간 확인 실패 배너
      test("5a 요소(임신 토글 두 상태·기준일 자료 표지·안내 줄·근거 상세 배너)가 토큰대로 그려지고 글자 대비가 기준 이상이다", async ({ page }) => {
        const desktop = width >= 1024;
        await mockChat(page, "apiFail");
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        const group = page.getByRole("radiogroup", { name: "임신 여부" });
        const general = group.getByRole("radio", { name: "일반인" });
        const pregnant = group.getByRole("radio", { name: "임산부" });
        await expect(group).toBeVisible();
        // 고른 칸: 노랑 바탕 + on-yellow 글자(다크에서 ink는 밝은 크림이라 쓰지 않는다). 안 고른 칸: bg-soft + mute
        expect(await style(general, "background-color")).toBe(YELLOW);
        expect(await style(general, "color")).toBe(ON_YELLOW[scheme]);
        expect(await style(pregnant, "background-color")).toBe(BG_SOFT[scheme]);
        expect(await style(pregnant, "color")).toBe(MUTE[scheme]);
        await ask(page);
        const card = page.getByTestId("result-card").first();
        await expect(card).toBeVisible();
        await expect(card.getByTestId("basis-file-tag")).toBeVisible();
        await expect(page.locator('[data-turn="turn-1"]').getByTestId("pregnancy-pick-hint")).toBeVisible();
        if (desktop) await expect(panel(page).getByTestId("evidence-api-fail-notice")).toBeVisible();
        await expectNoContrastFailure(page, `${scheme} ${width} 일반인`);
        await shot(page, `g1-5a-general-${scheme}`, "fe12-5a");
        // 반대 상태: 임산부를 고르면 칸 색이 바뀐다(전환이 끝난 값으로 본다)
        await pregnant.click();
        await expect(pregnant).toHaveAttribute("aria-checked", "true");
        await expect.poll(() => style(pregnant, "background-color")).toBe(YELLOW);
        await expect.poll(() => style(pregnant, "color")).toBe(ON_YELLOW[scheme]);
        await expect.poll(() => style(general, "background-color")).toBe(BG_SOFT[scheme]);
        await expect.poll(() => style(general, "color")).toBe(MUTE[scheme]);
        await expectNoContrastFailure(page, `${scheme} ${width} 임산부`);
        await shot(page, `g1-5a-pregnant-${scheme}`, "fe12-5a");
        // 좁은 폭: 근거 상세 시트를 열어 실시간 확인 실패 배너의 대비를 잰다(시트 안만)
        if (!desktop) {
          await page.getByTestId("evidence-entry").click();
          await expect(sheet(page).getByTestId("evidence-api-fail-notice")).toBeVisible();
          await expectNoContrastFailure(page, `${scheme} ${width} 근거 상세 시트`, '[role="dialog"]');
          await shot(page, `g1-5a-sheet-${scheme}`, "fe12-5a");
          await page.keyboard.press("Escape");
        }
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
