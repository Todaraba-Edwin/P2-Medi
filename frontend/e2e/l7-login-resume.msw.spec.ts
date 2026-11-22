import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, expectClickReaches, expectNoHorizontalScroll, expectTouchTarget, layerTel } from "./helpers";

// 로그인 콜백 복귀(2026-11-22 사용자 보고, l7): 소셜 로그인은 전체 페이지 이동이라 돌아오면 로그인 모달이 닫혀 있었다.
// 이제 콜백 라우트가 `/?auth_resume=1`로 돌려보내고, 화면이 그 표시를 한 번 읽어 온보딩(동의 → 프로필)이 남았을 때만 모달을 그 단계로 다시 연다.
// 실제 OAuth 왕복은 e2e에서 하지 않는다. 목(MSW) 모드에서는 세션이 페이지 메모리에만 있어 `?mock_session=new|onboarded`(브라우저 워커 전용)로
// "세션 쿠키가 있는 채 돌아온 페이지"를 흉내 낸다(`src/mocks/browser.ts`). 실제 백엔드·원격 호출은 0이다.
// 캡처: `L7_SHOT_DIR`을 주면 `l7-login-resume-*.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.L7_SHOT_DIR;
const shot = async (page: Page, name: string, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l7-login-resume-${name}-${page.viewportSize()!.width}-${scheme}.png`) });
};

/** 첫 화면을 주소 표시와 함께 연다(콜백 라우트가 `/?auth_resume=1`로 돌려보낸 상태) */
async function openApp(page: Page, search: string) {
  await page.goto(`/${search}`);
  await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
}

const modal = (page: Page) => page.getByTestId("account-modal");
const agree = (page: Page, docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");
/** 사이드바 계정 자리(1280: 펼친 칸, 393: ☰ 드로어)의 `프로필 관리` */
async function openProfileManage(page: Page) {
  if (page.viewportSize()!.width < 1024) await page.getByRole("button", { name: "메뉴 열기" }).click();
  await page.getByTestId("account-entry").first().click();
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`로그인 복귀 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("복귀 → 모달이 동의 화면으로 자동으로 열려 닫히지 않고 → 동의 → 프로필 추가 → 닫으면 채팅(대상 선택)", async ({ page }) => {
        await openApp(page, "?mock_session=new&auth_resume=1");
        await expect(modal(page)).toHaveAttribute("data-step", "consent");
        await expect.poll(() => page.url()).not.toContain("auth_resume"); // 표시는 한 번 읽고 지운다
        expect(new URL(page.url()).pathname).toBe("/");
        await expect(page.getByTestId("entry-choice")).toHaveCount(0); // 로그인 상태
        // 자동으로 열린 모달에서도 119 진입점은 누를 수 있다(동의 화면에서는 본문 맨 아래라 본문 안에서 내려서 누른다)
        await expect(layerTel(page)).toHaveAttribute("href", "tel:119");
        await expectTouchTarget(layerTel(page));
        await layerTel(page).scrollIntoViewIfNeeded();
        await expectClickReaches(page, layerTel(page));
        await expectNoHorizontalScroll(page);
        await page.getByTestId("account-body").evaluate((el) => el.scrollTo({ top: 0 })); // 캡처는 동의 화면 머리부터
        await shot(page, "consent", scheme);
        for (const docType of ["terms", "privacy_consent", "age_14"]) await agree(page, docType).check();
        await modal(page).getByTestId("consent-submit").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        await modal(page).getByTestId("add-self").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await modal(page).getByLabel("이름(별명)").fill("나");
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
        await shot(page, "profiles", scheme);
        await modal(page).getByRole("button", { name: "닫기" }).click();
        await expect(modal(page)).toHaveCount(0);
        await expect(page.getByTestId("target-picker").getByTestId("target-option")).toHaveText(["선택 안 함", "나"]);
        await ask(page, "합성 질문");
        await expect(page.getByTestId("result-card")).toBeVisible();
      });

      test("자동으로 열린 모달을 닫으면 다시 열리지 않고, 사이드바 `프로필 관리`에서 같은 단계(동의)로 이어 간다", async ({ page }) => {
        await openApp(page, "?mock_session=new&auth_resume=1");
        await expect(modal(page)).toHaveAttribute("data-step", "consent");
        await page.keyboard.press("Escape");
        await expect(modal(page)).toHaveCount(0);
        await ask(page, "합성 질문"); // 질문은 그대로 된다
        await expect(page.getByTestId("result-card")).toBeVisible();
        await expect(modal(page)).toHaveCount(0); // 그 사이 다시 열리지 않는다
        await openProfileManage(page);
        await expect(modal(page)).toHaveAttribute("data-step", "consent");
        await shot(page, "resume-from-menu", scheme);
      });

      test("온보딩을 마친 사용자는 모달 없이 바로 채팅이고, 표시 없이 들어오면(새로고침) 세션이 있어도 열지 않는다. 게스트는 그대로다", async ({ page }) => {
        await openApp(page, "?mock_session=onboarded&auth_resume=1");
        await expect(page.getByTestId("target-picker")).toBeVisible();
        await expect(modal(page)).toHaveCount(0);
        await expect.poll(() => page.url()).not.toContain("auth_resume");
        await openApp(page, "?mock_session=new");
        await expect(page.getByTestId("entry-choice")).toHaveCount(0); // 로그인 상태(동의 전)지만 자동으로 열지 않는다
        await expect(modal(page)).toHaveCount(0);
        await openApp(page, "?auth_resume=1"); // 세션 없이 표시만 있으면 게스트 그대로
        await expect(page.getByTestId("entry-choice")).toBeVisible();
        await expect(modal(page)).toHaveCount(0);
        await ask(page, "mock:응급 합성 질문"); // 게스트 경로·119
        await expect(page.getByTestId("emergency-banner")).toBeVisible();
      });
    });
  }
}
