import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, expectNoHorizontalScroll, layerTel, openAccountEntry, targetOptionTexts, completeRequired } from "./helpers";

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
/** 사이드바 계정 메뉴(1280: 펼친 칸, 393: ☰ 드로어)의 `프로필 관리` */
async function openProfileManage(page: Page) {
  await openAccountEntry(page);
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
        // 119 진입점은 머리줄·응급 배너 두 곳뿐이다(FE-17 U-04): 자동으로 열린 모달 안에는 없다
        await expect(layerTel(page)).toHaveCount(0);
        await expect(modal(page).locator('a[href="tel:119"]')).toHaveCount(0); // 119는 머리줄·응급 배너 두 곳뿐, 층 안에는 없다(FE-17 U-04)
        await expectNoHorizontalScroll(page);
        await page.getByTestId("account-body").evaluate((el) => el.scrollTo({ top: 0 })); // 캡처는 동의 화면 머리부터
        await shot(page, "consent", scheme);
        for (const docType of ["terms", "privacy_consent", "age_14"]) await agree(page, docType).check();
        await modal(page).getByTestId("consent-submit").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        await modal(page).getByTestId("add-self").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await modal(page).getByLabel("이름(별명)").fill("나");
        await completeRequired(modal(page));
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
        await shot(page, "profiles", scheme);
        await modal(page).getByRole("button", { name: "닫기" }).click();
        await expect(modal(page)).toHaveCount(0);
        expect(await targetOptionTexts(page)).toEqual(["게스트로 이용", "나"]);
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
        await expect(page.getByTestId("target-chip")).toBeVisible();
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

// 복귀 직후 계정 호출 수(FE-04 §3 "복귀 직후 `/me`를 세션이 준비된 뒤 한 번만", 2026-11-23). 워커가 잡은 요청을 페이지 안에서 센다.
test.describe("로그인 복귀 직후 계정 호출 수", () => {
  test.use({ viewport: { width: 1280, height: HEIGHT } });

  /** 페이지가 보낸 계정 호출(`/api/me`·`/api/profiles`·`/api/legal/*`·`/api/consents`)과 응답 상태를 순서대로 모은다 */
  function watch(page: Page) {
    const seen: { call: string; status: number }[] = [];
    page.on("response", (response) => {
      const request = response.request();
      const pathname = new URL(request.url()).pathname;
      if (/^\/api\/(me|profiles|legal\/|consents)/.test(pathname)) seen.push({ call: `${request.method()} ${pathname}`, status: response.status() });
    });
    return {
      count: (call: string) => seen.filter((entry) => entry.call === call).length,
      legal: () => seen.filter((entry) => entry.call.startsWith("GET /api/legal/")).length,
      statuses: () => seen.map((entry) => entry.status),
      all: () => seen,
    };
  }

  test("복귀(동의 전) → 모달 자동 재개까지: /api/me 1회·/api/profiles 1회·약관 5회, 401 없음. 동의 → 프로필 추가는 그대로 된다", async ({ page }) => {
    const seen = watch(page);
    await openApp(page, "?mock_session=new&auth_resume=1");
    await expect(modal(page)).toHaveAttribute("data-step", "consent");
    await expect(modal(page).locator('[data-doc-type="terms"]')).toBeVisible(); // 약관 본문이 그려졌다(선반입)
    expect(seen.count("GET /api/me")).toBe(1);
    expect(seen.count("GET /api/profiles")).toBe(1);
    expect(seen.legal()).toBe(5);
    expect(seen.statuses().filter((status) => status === 401)).toHaveLength(0);
    // 약관은 `/profiles` 응답을 기다리지 않고 `/me` 응답 직후 받기 시작한다: 응답 순서상 /legal/* 첫 건이 /profiles보다 뒤에 올 수도 있으나 /me보다는 뒤다
    const order = seen.all().map((entry) => entry.call);
    expect(order.indexOf("GET /api/me")).toBeLessThan(order.findIndex((call) => call.startsWith("GET /api/legal/")));
    for (const docType of ["terms", "privacy_consent", "age_14"]) await agree(page, docType).check();
    await modal(page).getByTestId("consent-submit").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    expect(seen.count("POST /api/consents")).toBe(1);
    expect(seen.count("GET /api/me")).toBe(1); // 동의 뒤에도 `/me`를 다시 읽지 않는다(응답이 갱신된 Me다)
    expect(seen.legal()).toBe(5); // 동의 화면이 떠도 다시 받지 않는다
    await modal(page).getByTestId("add-self").click();
    await modal(page).getByLabel("이름(별명)").fill("나");
    await completeRequired(modal(page));
    await modal(page).getByTestId("profile-save").click();
    await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
    expect(seen.count("POST /api/profiles")).toBe(1);
    expect(seen.statuses().filter((status) => status === 401)).toHaveLength(0);
  });

  test("온보딩을 마친 사용자의 복귀·새로고침: /api/me 1회·/api/profiles 1회, 약관은 받지 않는다", async ({ page }) => {
    const onboarded = watch(page);
    await openApp(page, "?mock_session=onboarded&auth_resume=1");
    await expect(page.getByTestId("target-chip")).toBeVisible();
    expect(onboarded.count("GET /api/me")).toBe(1);
    expect(onboarded.count("GET /api/profiles")).toBe(1);
    expect(onboarded.legal()).toBe(0);
    expect(onboarded.statuses().filter((status) => status === 401)).toHaveLength(0);
  });
});
