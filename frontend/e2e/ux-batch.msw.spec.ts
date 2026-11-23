import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, input, notice, openApp, pickTarget } from "./helpers";

// FE-17 UI/UX 다듬기(U-01·U-02·U-04·U-05)를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-01: 계정 버튼 = 고른 프로필의 병아리 + 이름, 마우스를 올리면 위로 프로필 목록(초점은 입력창에 그대로), 입력창 칩도 같은 값, 가족 추가 색 8칸
// - U-02: 입력창 아래 통합 고지 한 단락 / U-04: 119는 머리줄 하나 / U-05: 다시 물은 뒤 고른 줄 요약 유지 + 진행 표시
// 캡처: `FE_UX_BATCH_SHOT_DIR`을 주면 `ux-batch-{width}-{scheme}.png`(입력창 칩·통합 고지·계정 버튼)와 `ux-batch-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  // 보이는 그림만 기다린다(닫힌 층 안의 늦게 불러오는 그림은 영영 오지 않는다)
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const mobile = width < 1024;
      const base = `ux-batch-${width}-${scheme}`;

      test("U-01 계정 버튼·프로필 목록·입력창 칩·색 고르기, U-02 통합 고지, U-04 119 한 곳", async ({ page }) => {
        test.setTimeout(90_000); // 한 흐름에 장면이 여럿이다
        await openApp(page, "?mock_session=onboarded&ux_batch=1"); // openApp은 뒤에 "/"를 붙인다: 마지막 값이 흡수하게 둔다
        const chip = page.getByTestId("target-chip");
        await expect(chip).toBeVisible();
        await expectTouchTarget(chip, { widthToo: false });
        await expect(page.getByRole("radiogroup", { name: "누가 먹나요" })).toHaveCount(0); // 본문 선택 줄 없음
        // U-04: 평상시 119는 머리줄 하나
        await expect(page.locator('a[href="tel:119"]')).toHaveCount(1);
        await expect(page.getByTestId("emergency-entry")).toBeVisible();
        // U-02: 통합 고지 한 단락, 입력창 바로 아래
        await expect(notice(page)).toHaveCount(1);
        await expect(notice(page)).toHaveAttribute("role", "note");
        await expect(page.getByTestId("legal-footer")).toHaveCount(0);
        await expect(page.getByTestId("input-notice")).toHaveCount(0);
        const inputBox = (await input(page).boundingBox())!;
        expect((await notice(page).boundingBox())!.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height - 0.5);
        // 입력창 칩에서 첫째(파랑)를 고른다 → 칩·계정 버튼이 같이 바뀐다
        await pickTarget(page, "첫째");
        await expect(chip).toHaveAccessibleName("누가 먹나요 첫째");
        await expect(chip.getByTestId("profile-avatar")).toHaveAttribute("data-color", "blue");
        await expectNoHorizontalScroll(page);
        if (mobile) await page.getByTestId("menu-button").click();
        const button = page.getByTestId("account-menu-button").first();
        await expect(button).toHaveText("첫째");
        await expect(button.getByTestId("profile-avatar")).toHaveAttribute("data-color", "blue");
        await shot(page, base);

        // 계정 버튼 → 위로 열린 메뉴 맨 위 프로필 목록. 넓은 폭은 마우스를 올리기만 해도 열리고 입력창 초점은 그대로다
        const menu = page.getByTestId("account-menu");
        if (!mobile) {
          await input(page).focus();
          await button.hover();
          await expect(menu).toBeVisible();
          await expect(input(page)).toBeFocused();
        } else {
          await button.click();
          await expect(menu).toBeVisible();
        }
        await expect(menu.getByTestId("target-option")).toHaveText(["게스트로 이용", "나", "첫째"]);
        await expect(menu.getByRole("menuitemradio", { name: "첫째" })).toHaveAttribute("aria-checked", "true");
        const menuBox = (await menu.boundingBox())!;
        expect(menuBox.y + menuBox.height).toBeLessThanOrEqual((await button.boundingBox())!.y + 0.5); // 위로 열린다
        await shot(page, `${base}-profile-menu`);
        await menu.getByRole("menuitemradio", { name: "나" }).click();
        await expect(menu).toHaveCount(0);
        await expect(button).toHaveText("나");
        if (mobile) {
          await page.keyboard.press("Escape");
          await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        }
        await expect(chip).toHaveAccessibleName("누가 먹나요 나");

        // 입력창 칩: 위로 열린 목록
        await chip.click();
        const chipMenu = page.getByTestId("target-menu");
        await expect(chipMenu).toBeVisible();
        expect((await chipMenu.boundingBox())!.y + (await chipMenu.boundingBox())!.height).toBeLessThanOrEqual((await chip.boundingBox())!.y + 0.5);
        await shot(page, `${base}-chip-menu`);
        await page.keyboard.press("Escape");
        await expect(chipMenu).toHaveCount(0);
        await expect(chip).toBeFocused();

        // 가족 추가: 색 8칸, 기본 노랑이 골라져 있다(FE-17 U-07이 U-01의 '안 쓴 첫 색 제안'을 대체)
        if (mobile) await page.getByTestId("menu-button").click();
        await page.getByTestId("account-menu-button").first().click();
        await page.getByTestId("account-entry").click();
        const modal = page.getByTestId("account-modal");
        await modal.getByTestId("add-family").click();
        const colors = modal.getByRole("radiogroup", { name: "프로필 색" });
        await expect(colors.getByRole("radio")).toHaveCount(8);
        await expect(colors.getByRole("radio", { name: "노랑" })).toBeChecked();
        for (const option of await colors.getByTestId("avatar-color-option").all()) await expectTouchTarget(option);
        await colors.locator('[data-testid="avatar-color-option"][data-color="purple"]').click(); // 칸(label)을 누른다(라디오 자체는 화면에서 숨긴 입력)
        await expect(colors.getByRole("radio", { name: "보라" })).toBeChecked();
        await shot(page, `${base}-color-picker`);
      });

      test("U-05 제품 고르기 뒤: 고른 줄 요약은 남고 안내 줄은 숨으며 말풍선 다음에 진행 표시가 이어진다", async ({ page }) => {
        await openApp(page);
        await input(page).fill("mock:되묻기여러 합성 질문");
        await page.getByRole("button", { name: "보내기" }).click();
        const turn1 = page.locator('[data-turn="turn-1"]');
        await expect(turn1.getByTestId("candidate-card")).toBeVisible();
        for (const group of await turn1.getByTestId("candidate-group").all()) await group.getByTestId("candidate").first().click();
        await expect(turn1.getByTestId("candidate-picked")).toHaveCount(2);
        await page.getByTestId("resend-button").click();
        const turn2 = page.locator('[data-turn="turn-2"]');
        await expect(turn2.getByText(/^고른 약: .+다시 확인$/)).toBeVisible();
        await expect(turn2.getByRole("status", { name: "진행 상태" })).toBeVisible(); // 기존 진행 표시(약 찾는 중 → 금기 확인 중 → 근거 찾는 중)
        await expect(turn1.getByTestId("candidate-picked")).toHaveCount(2);
        await expect(turn1.getByTestId("candidates-line")).toHaveCount(0);
        await expect(turn1.getByTestId("resend-pick")).toHaveCount(0);
        await shot(page, `${base}-u05-progress`);
        await expect(turn2.getByTestId("result-card").first()).toBeVisible();
        await expect(turn1.getByTestId("candidate-picked")).toHaveCount(2);
        await expect(turn1.getByTestId("fixed-notice")).toBeVisible();
        await turn1.scrollIntoViewIfNeeded();
        await shot(page, `${base}-u05-done`);
      });
    });
  }
}
