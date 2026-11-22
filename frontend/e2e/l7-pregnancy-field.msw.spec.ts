import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, expectNoHorizontalScroll } from "./helpers";

// 프로필 폼의 임신 여부(작업 B, 사용자 지시 2026-11-22): 성별이 여성일 때만 선택 버튼 "예 | 아니오 | 모름"이 나타난다(처음에는 숨김).
// 목(MSW) 모드에서 `?mock_session=new`로 막 로그인한 세션을 만들고 동의 뒤 프로필 추가 폼을 본다. 실제 백엔드·원격 호출은 0이다.
// 캡처: `L7_SHOT_DIR`을 주면 `l7-pregnancy-field-*.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.L7_SHOT_DIR;
const shot = async (page: Page, name: string, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l7-pregnancy-field-${name}-${page.viewportSize()!.width}-${scheme}.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const field = (page: Page) => modal(page).getByTestId("pregnancy-field");
const group = (page: Page) => modal(page).getByRole("radiogroup", { name: "임신 여부" });
const option = (page: Page, name: "예" | "아니오" | "모름") => group(page).getByRole("radio", { name });

/** 막 로그인한 목 세션으로 동의(건강 정보 포함)를 마치고 본인 프로필 추가 폼을 연다 */
async function openSelfForm(page: Page) {
  await page.goto("/?mock_session=new&auth_resume=1");
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await modal(page).getByTestId("add-self").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`프로필 임신 여부 칸 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("성별을 여성으로 고르면 칸이 나타나고(예 | 아니오 | 모름), 남성·선택 안 함이면 사라진다. 여성이 아니면 아니오로 저장된다(작업 C, 2026-11-22)", async ({ page }) => {
        const bodies: Record<string, unknown>[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/profiles")) bodies.push(request.postDataJSON());
        });
        await openSelfForm(page);
        await expect(field(page)).toHaveCount(0); // 처음(성별 선택 안 함)에는 없다
        await shot(page, "hidden", scheme);
        await modal(page).getByLabel("성별").selectOption("female");
        await expect(field(page)).toBeVisible();
        await expect(group(page).getByRole("radio")).toHaveText(["예", "아니오", "모름"]);
        await expect(option(page, "모름")).toHaveAttribute("aria-checked", "true");
        // 선택 버튼: 고른 칸은 노랑 바탕 + 굵게 + 체크, 안 고른 칸은 크림. 누르는 영역 44px
        for (const name of ["예", "아니오", "모름"] as const) {
          const box = (await option(page, name).boundingBox())!;
          expect(box.height).toBeGreaterThanOrEqual(MIN_TOUCH - 4); // 칸 40px + 틀 여백 = 44px 틀
        }
        expect((await group(page).boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
        await option(page, "예").click();
        await expect(option(page, "예")).toHaveAttribute("aria-checked", "true");
        await expect(option(page, "예")).toHaveCSS("background-color", "rgb(255, 204, 0)"); // --color-yellow(전환이 끝난 값)
        await expect.poll(() => option(page, "예").evaluate((el) => parseInt(getComputedStyle(el).fontWeight, 10))).toBeGreaterThanOrEqual(700);
        await expect(option(page, "예").locator("svg")).toHaveCount(1);
        await expect(option(page, "아니오").locator("svg")).toHaveCount(0);
        await expectNoHorizontalScroll(page);
        await shot(page, "shown", scheme);
        // 남성으로 바꾸면 사라지고, 다시 여성으로 돌려도 모름이다(숨겨질 때 초기화)
        await modal(page).getByLabel("성별").selectOption("male");
        await expect(field(page)).toHaveCount(0);
        await modal(page).getByLabel("성별").selectOption("female");
        await expect(option(page, "모름")).toHaveAttribute("aria-checked", "true");
        await modal(page).getByLabel("성별").selectOption("");
        await expect(field(page)).toHaveCount(0);
        // 남성으로 저장하면 아니오로 간다(사용자 결정 2026-11-22: 여성이 아니면 '아니오' 저장)
        await modal(page).getByLabel("이름(별명)").fill("나");
        await modal(page).getByLabel("성별").selectOption("male");
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
        expect(bodies).toHaveLength(1);
        expect(bodies[0]).toMatchObject({ sex: "male", pregnancy_status: "not_pregnant" });
        await expect(modal(page).getByTestId("profile-item")).toContainText("임신 여부 아니오");
        // 성별 미입력 가족 프로필도 아니오(2026-11-22 정정 '미입력도 아니오로 저장')
        await modal(page).getByTestId("add-family").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await modal(page).getByLabel("이름(별명)").fill("첫째");
        await expect(field(page)).toHaveCount(0);
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
        expect(bodies).toHaveLength(2);
        expect(bodies[1]).toMatchObject({ sex: null, pregnancy_status: "not_pregnant" });
      });

      test("키보드: 여성을 고른 뒤 ←/→로 옮기며 선택·초점이 따라가고, 여성 프로필의 '예'가 저장돼 수정 화면에 다시 채워진다", async ({ page }) => {
        await openSelfForm(page);
        await modal(page).getByLabel("이름(별명)").fill("나");
        await modal(page).getByLabel("성별").selectOption("female");
        await option(page, "모름").focus();
        await page.keyboard.press("ArrowLeft");
        await expect(option(page, "아니오")).toHaveAttribute("aria-checked", "true");
        await expect(option(page, "아니오")).toBeFocused();
        await page.keyboard.press("ArrowLeft");
        await expect(option(page, "예")).toHaveAttribute("aria-checked", "true");
        await expect(option(page, "예")).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect(option(page, "아니오")).toHaveAttribute("aria-checked", "true");
        await page.keyboard.press("ArrowLeft");
        await expect(option(page, "예")).toHaveAttribute("aria-checked", "true");
        // 초점 링이 보인다
        expect(await option(page, "예").evaluate((el) => el.matches(":focus-visible") && getComputedStyle(el).outlineStyle !== "none")).toBe(true);
        await expect(option(page, "예")).toHaveCSS("background-color", "rgb(255, 204, 0)"); // 색 전환이 끝난 뒤 캡처
        await shot(page, "keyboard", scheme);
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toContainText("여성 · 임신 여부 예");
        await modal(page).getByRole("button", { name: "나 수정" }).click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await expect(field(page)).toBeVisible();
        await expect(option(page, "예")).toHaveAttribute("aria-checked", "true");
        // 가족 프로필은 독립: 새 폼은 다시 숨김에서 시작한다
        await modal(page).getByRole("button", { name: "취소" }).click();
        await modal(page).getByTestId("add-family").click();
        await expect(field(page)).toHaveCount(0);
        await modal(page).getByLabel("성별").selectOption("female");
        await expect(option(page, "모름")).toHaveAttribute("aria-checked", "true");
      });
    });
  }
}
