import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, openAccountMenu, openApp } from "./helpers";

// 약관·정책 열람 진입점(2026-11-23 사용자 요구): 게스트·로그인 모두 계정 메뉴(팝오버)의 `약관·정책` 항목 → 열람 화면(`legal-dialog`)에서 현재 적용 문서를 읽는다.
// 서버는 브라우저 워커의 목(src/mocks/account-handlers.ts). 게스트 목록은 `terms_guest`(게스트용, 목에 있음)·공통 2종(처리방침은 공통, PRD-17-23 A),
// 회원 목록은 동의 화면과 같은 5종이다(`src/features/account/legal-menu.ts`). 열람은 읽기 전용이라 `POST /api/consents`가 나가지 않는다.
// "서버에 없는 종류 숨김"은 `?mock_legal_missing=terms_guest`(목 핸들러가 404)로 본다(실서버에서 `terms_guest`가 게시되기 전 상태와 같다).
// 캡처: `FE_LEGAL_MENU_SHOT_DIR`을 주면 `legal-menu-{width}-{scheme}.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`).
const SHOT_DIR = process.env.FE_LEGAL_MENU_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};

const GUEST_DOCS = ["terms_guest", "terms", "privacy_policy"];
const MEMBER_DOCS = ["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"];

const dialog = (page: Page) => page.getByTestId("legal-dialog");
const menu = (page: Page) => dialog(page).getByTestId("legal-menu");
const docTypes = (page: Page) => menu(page).getByTestId("legal-menu-item").evaluateAll((items) => items.map((item) => (item as HTMLElement).dataset.docType));

/** 계정 메뉴(팝오버)의 `약관·정책` 항목으로 연다(좁은 폭은 드로어 안 버튼) */
async function openLegalMenu(page: Page, _width: number, member = false) {
  const accountMenu = await openAccountMenu(page);
  // 로그인 상태는 `/me` 부트스트랩이 끝나 메뉴가 회원용이 된 뒤에 연다
  if (member) await expect(accountMenu).toHaveAttribute("data-audience", "member");
  const entry = accountMenu.getByTestId("legal-entry");
  await expectTouchTarget(entry, { widthToo: false });
  await entry.click();
  await expect(accountMenu).toHaveCount(0); // 항목을 고르면 메뉴는 닫힌다
  await expect(page.getByTestId("menu-drawer")).toHaveCount(0); // 드로어도 닫히고 열람 화면만 남는다
  await expect(dialog(page)).toBeVisible();
  await expect(menu(page)).toBeVisible();
  // 문서 목록이 온 뒤(불러오는 중 글자가 사라진 뒤)
  await expect(menu(page).getByTestId("legal-menu-item").first()).toBeVisible();
}

function watchConsents(page: Page) {
  const posts: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && pathname.endsWith("/api/consents")) posts.push(pathname);
  });
  return posts;
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`약관·정책 열람 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("게스트: 약관·정책 항목 → 열람 화면 제목에 초점, 게스트 목록(없는 종류는 숨김), 펼쳐 읽기, Esc로 닫히면 초점은 계정 버튼, 동의 호출 0", async ({ page }) => {
        const posts = watchConsents(page);
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await openLegalMenu(page, width);
        // 열리면 초점은 화면 제목이다. 제목은 하나뿐이다(묶음 안에 같은 제목을 두 번 두지 않는다)
        await expect(dialog(page).getByRole("heading", { name: "약관·정책" })).toBeFocused();
        await expect(dialog(page).getByRole("heading")).toHaveCount(1);
        expect(await docTypes(page)).toEqual(GUEST_DOCS);
        await expect(menu(page).getByText(/준비 중/)).toHaveCount(0);
        await expect(dialog(page).getByRole("checkbox")).toHaveCount(0);

        // 첫 항목(게스트용 문서, 제목은 서버 값)을 펼친다
        const first = menu(page).locator('[data-doc-type="terms_guest"]').getByRole("button");
        await expect(first).toContainText("게스트 이용 안내 (합성 목 문서)");
        await expect(first).toContainText("버전 1 · 시행일 2026-11-18");
        await expect(first).not.toContainText("법률 검토 전"); // 표지 없음(PRD-17-26 A, 목 문서는 not_reviewed)
        await expect(menu(page).getByTestId("legal-not-reviewed")).toHaveCount(0);
        await expectTouchTarget(first, { widthToo: false });
        await first.click();
        await expect(first).toHaveAttribute("aria-expanded", "true");
        const body = menu(page).getByRole("group", { name: "게스트 이용 안내 (합성 목 문서)" });
        await expect(body).toBeVisible();
        await expect(body).toContainText("제1조 (게스트 이용)");
        // 긴 본문도 상자·화면 안에서만 스크롤한다(가로 넘침 없음)
        await expectNoHorizontalScroll(page);
        expect(await body.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        await shot(page, `legal-menu-${width}-${scheme}`);

        // 처리방침(표가 든 긴 본문)을 열면 앞 항목은 접히고 본문은 상자 안에서 세로 스크롤한다
        const policy = menu(page).locator('[data-doc-type="privacy_policy"]').getByRole("button");
        await policy.click();
        await expect(first).toHaveAttribute("aria-expanded", "false");
        const policyBody = menu(page).getByRole("group", { name: "개인정보 처리방침 (합성 목 문서)" });
        await expect(policyBody.locator("table")).toHaveCount(1);
        expect(await policyBody.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
        await expectNoHorizontalScroll(page);

        // 키보드: 본문 상자는 Tab으로 닿는다(초점을 받아 화살표로 내려 읽는다)
        await policy.focus();
        await page.keyboard.press("Tab");
        await expect(policyBody).toBeFocused();
        // Esc로 닫히고 초점은 연 계정 버튼(좁은 폭: 드로어가 닫혔으니 ☰)으로 돌아간다
        await page.keyboard.press("Escape");
        await expect(dialog(page)).toHaveCount(0);
        await expect(page.getByTestId(width < 1024 ? "menu-button" : "account-menu-button").first()).toBeFocused();
        expect(posts).toEqual([]);
      });

      test("로그인(목): 같은 항목에서 회원 목록 5종(동의서·만 14세 포함)을 읽는다", async ({ page }) => {
        const posts = watchConsents(page);
        // 목 세션(브라우저 워커 전용 표시). `openApp`의 base는 앞에 붙는 값이라 뒤에 `/`가 와도 값이 깨지지 않게 다른 키를 하나 더 둔다
        await openApp(page, "?mock_session=onboarded&legal_menu=1");
        await openLegalMenu(page, width, true);
        await expect(menu(page)).toHaveAttribute("data-audience", "member");
        expect(await docTypes(page)).toEqual(MEMBER_DOCS);
        const age = menu(page).locator('[data-doc-type="age_14"]').getByRole("button");
        await expect(age).toContainText("만 14세 이상입니다.");
        await age.click();
        await expect(menu(page).getByRole("group", { name: "만 14세 이상입니다." })).toContainText("만 14세 이상입니다.");
        await dialog(page).getByRole("button", { name: "닫기" }).click();
        await expect(dialog(page)).toHaveCount(0);
        expect(posts).toEqual([]);
      });
    });
  }
}

test.describe("서버에 없는 문서 종류", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });
  test("게스트용 문서가 게시 전(404)이면 그 항목만 빠지고 안내 글자 없이 공통 2종만 보인다", async ({ page }) => {
    await openApp(page, "?mock_legal_missing=terms_guest&legal_menu=1");
    await openLegalMenu(page, 393);
    expect(await docTypes(page)).toEqual(["terms", "privacy_policy"]);
    await expect(menu(page).locator('[data-doc-type="terms_guest"]')).toHaveCount(0);
    await expect(menu(page).getByText(/준비 중/)).toHaveCount(0);
    await expect(menu(page).getByRole("alert")).toHaveCount(0);
  });
});
