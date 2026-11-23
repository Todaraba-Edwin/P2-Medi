import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, input, notice, openApp, pickChoice, pickTarget } from "./helpers";

// FE-17 UI/UX 다듬기 2차(U-06·U-07)를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-06: 로그인 직후 본인이 기본 대상 → 계정 버튼에 선택된 프로필(병아리 + 이름), 메뉴의 `누가 먹나요`는 `프로필 관리` 아래 하위, `게스트로 이용`
// - U-07: 입력창 묶음(사진 → 일반인|임산부 → 프로필 칩)이 질문 칸 아래 좌하단, 프로필 추가 폼(제목·보조 문구·6단계 진행바·버튼 선택·필수 4칸 저장 제어·색 체크 위치)
// 캡처: `FE_UX_BATCH2_SHOT_DIR`을 주면 `ux-batch2-{width}-{scheme}.png`(입력창 묶음·계정 버튼)와 `ux-batch2-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH2_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 2 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const mobile = width < 1024;
      const base = `ux-batch2-${width}-${scheme}`;

      test("U-06 기본 대상 본인·프로필 관리 아래 누가 먹나요·게스트로 이용, U-07 입력창 좌하단 묶음", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page, "?mock_session=onboarded&ux_batch2=1");
        const chip = page.getByTestId("target-chip");
        await expect(chip).toBeVisible();
        // U-06 ①: 고르지 않아도 본인(나)이 대상이다
        await expect(chip).toHaveAccessibleName("누가 먹나요 나");

        // U-07 입력창: 질문 칸(첫 줄) 아래 줄 왼쪽에 사진 → 토글 → 칩 묶음, 보내기는 같은 줄 오른쪽 끝
        const row = page.getByTestId("input-target-row");
        const box = async (locator: ReturnType<Page["locator"]>) => (await locator.boundingBox())!;
        const textBox = await box(input(page));
        const rowBox = await box(row);
        const photoBox = await box(row.getByTestId("photo-entry"));
        const chipBox = await box(chip);
        const sendBox = await box(page.getByRole("button", { name: "보내기" }));
        const formBox = await box(input(page).locator("xpath=ancestor::form"));
        expect(rowBox.y).toBeGreaterThanOrEqual(textBox.y + textBox.height - 0.5); // 질문 칸 아래
        expect(photoBox.x).toBeLessThan(chipBox.x); // 사진이 맨 앞
        expect(photoBox.x - formBox.x).toBeLessThanOrEqual(16); // 왼쪽 끝(좌하단)
        expect(Math.abs(photoBox.y + photoBox.height - (formBox.y + formBox.height))).toBeLessThanOrEqual(8); // 아래 끝
        expect(sendBox.x).toBeGreaterThan(chipBox.x + chipBox.width - 0.5); // 보내기와 겹치지 않는다
        expect(Math.abs(sendBox.y - photoBox.y)).toBeLessThanOrEqual(2); // 같은 줄
        await expectTouchTarget(row.getByTestId("photo-entry"));
        await expectTouchTarget(chip, { widthToo: false });
        await expect(page.getByTestId("photo-entry")).toHaveCount(1);
        // 통합 고지는 그대로 입력창 바로 아래
        expect((await box(notice(page))).y).toBeGreaterThanOrEqual(formBox.y + formBox.height - 0.5);
        await expectNoHorizontalScroll(page);
        // 질문을 여러 줄 적어도 묶음은 아래에 남는다
        await input(page).fill("첫 줄\n둘째 줄\n셋째 줄");
        expect((await box(row)).y).toBeGreaterThanOrEqual((await box(input(page))).y + (await box(input(page))).height - 0.5);
        await input(page).fill("");

        // 계정 버튼: 선택된 프로필
        if (mobile) await page.getByTestId("menu-button").click();
        const button = page.getByTestId("account-menu-button").first();
        await expect(button).toHaveText("나");
        await expect(button.getByTestId("profile-avatar")).toBeVisible();
        await shot(page, base);

        // 메뉴: 프로필 관리 → (하위) 누가 먹나요 목록. 넓은 폭은 마우스를 올리기만 해도 열린다
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
        const manageBox = await box(menu.getByTestId("account-entry"));
        const nested = menu.getByTestId("target-choice-nested");
        const nestedBox = await box(nested);
        expect(nestedBox.y).toBeGreaterThanOrEqual(manageBox.y + manageBox.height - 0.5); // 프로필 관리 아래
        expect(nestedBox.x).toBeGreaterThan(manageBox.x + 8); // 들여쓴 하위
        await expect(menu.getByText("선택 안 함")).toHaveCount(0);
        await shot(page, `${base}-profile-menu`);

        // 게스트로 이용: 칩은 그 글자, 계정 버튼은 로그인 상태 글자(비로그인 `계정`과 다르다)
        await menu.getByRole("menuitemradio", { name: "게스트로 이용" }).click();
        await expect(menu).toHaveCount(0);
        await expect(button).toHaveText("로그인됨");
        if (mobile) {
          await page.keyboard.press("Escape");
          await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        }
        await expect(chip).toHaveAccessibleName("누가 먹나요 게스트로 이용");
        await expect(chip).toHaveText("게스트로 이용");
        await expect(chip.getByTestId("profile-avatar")).toHaveAttribute("data-color", "none");
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-guest-use`);
        await pickTarget(page, "나");
        await expect(chip).toHaveAccessibleName("누가 먹나요 나");
      });

      test("U-07 프로필 추가 폼: 제목·보조 문구, 6단계 진행바(필수 초록·선택 파랑), 필수 4칸 전 저장 비활성, 버튼 선택, 색 체크가 원 안", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page, "?mock_session=onboarded&ux_batch2=form");
        if (mobile) await page.getByTestId("menu-button").click();
        await page.getByTestId("account-menu-button").first().click();
        await page.getByTestId("account-entry").click();
        const modal = page.getByTestId("account-modal");
        await modal.getByTestId("add-family").click();
        await expect(modal.getByRole("heading", { name: "누구의 프로필인가요?" })).toBeVisible();
        await expect(modal.getByText("본인과 가족 3명까지 만들 수 있어요", { exact: true })).toBeVisible();
        const steps = modal.getByTestId("profile-step");
        await expect(steps).toHaveCount(6);
        const states = async () => steps.evaluateAll((items) => items.map((item) => item.getAttribute("data-state")));
        expect(await states()).toEqual(["todo", "todo", "todo", "todo", "optional", "optional"]);
        const save = modal.getByTestId("profile-save");
        await expect(save).toBeDisabled();
        await expect(modal.getByTestId("profile-required-hint")).toBeVisible();
        // select 없음: 관계·연령대·성별은 버튼 묶음
        await expect(modal.locator("select")).toHaveCount(0);
        for (const group of ["관계", "연령대", "성별"]) for (const option of await modal.getByRole("radiogroup", { name: group }).getByRole("radio").all()) await expectTouchTarget(option, { widthToo: false });
        await expect(modal.locator('a[href="tel:119"]')).toHaveCount(0); // 와이어프레임 119 링크는 넣지 않는다(U-04)
        // 진행바 색: 마친 필수 = 초록, 선택 = 파랑, 남은 필수 = 회색(막대 배경색이 서로 다르다)
        const barColor = (index: number) => steps.nth(index).locator("span").first().evaluate((el) => getComputedStyle(el).backgroundColor);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-form-empty`);

        // 키보드로 관계를 고른다(Tab 한 번 → 첫 칸, → 로 다음)
        const relation = modal.getByRole("radiogroup", { name: "관계" });
        await relation.getByRole("radio", { name: "자녀", exact: true }).focus();
        await page.keyboard.press("ArrowRight");
        await expect(relation.getByRole("radio", { name: "부모", exact: true })).toHaveAttribute("aria-checked", "true");
        await expect(relation.getByRole("radio", { name: "부모", exact: true })).toBeFocused();
        await modal.getByLabel("이름(별명)").fill("엄마");
        await pickChoice(modal, "연령대", "만 65세 이상");
        await expect(save).toBeDisabled();
        await pickChoice(modal, "성별", "여성");
        expect(await states()).toEqual(["done", "done", "done", "done", "optional", "optional"]);
        await expect(save).toBeEnabled();
        await expect(modal.getByTestId("profile-required-hint")).toHaveCount(0);
        const [done, optional] = [await barColor(0), await barColor(4)];
        expect(done).not.toBe(optional);
        await expect(modal.getByRole("progressbar", { name: "필수" })).toHaveAttribute("aria-valuenow", "4");
        await modal.getByTestId("profile-progress").scrollIntoViewIfNeeded();
        await shot(page, `${base}-form-required-done`);

        // 프로필 색: 기본 노랑, 체크 표시가 고른 원 안 가운데
        const colors = modal.getByRole("radiogroup", { name: "프로필 색" });
        await expect(colors.getByRole("radio", { name: "노랑" })).toBeChecked();
        await colors.locator('[data-testid="avatar-color-option"][data-color="pink"]').click();
        await expect(colors.getByRole("radio", { name: "분홍" })).toBeChecked();
        const swatch = (await colors.locator('[data-color="pink"] [data-testid="avatar-color-swatch"]').boundingBox())!;
        const check = (await colors.getByTestId("avatar-color-check").boundingBox())!;
        expect(check.x).toBeGreaterThanOrEqual(swatch.x);
        expect(check.y).toBeGreaterThanOrEqual(swatch.y);
        expect(check.x + check.width).toBeLessThanOrEqual(swatch.x + swatch.width);
        expect(check.y + check.height).toBeLessThanOrEqual(swatch.y + swatch.height);
        expect(Math.abs(check.x + check.width / 2 - (swatch.x + swatch.width / 2))).toBeLessThanOrEqual(1.5); // 가운데
        expect(Math.abs(check.y + check.height / 2 - (swatch.y + swatch.height / 2))).toBeLessThanOrEqual(1.5);
        await colors.scrollIntoViewIfNeeded();
        await shot(page, `${base}-color-check`);

        await save.click();
        await expect(modal.getByTestId("profile-saved-notice")).toBeVisible();
        await expect(modal.getByTestId("profile-item")).toHaveCount(3);
      });
    });
  }
}
