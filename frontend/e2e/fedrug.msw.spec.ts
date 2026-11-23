import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, openApp, completeRequired, fillName } from "./helpers";

// 프로필 약 검색 후보 고르기(FE-04-13 A·FE-04-20 A·FE-04-21 A, 2026-11-20 fedrug). Playwright 프로젝트 `msw-worker`(파일 이름의 `msw.spec.ts`)가
// `NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드에 붙는다. 서버는 브라우저 워커의 목(`src/mocks/account-handlers.ts`의 `POST /api/drugs/search`,
// 합성 사전 `src/mocks/fixtures/account.ts`)이고 실제 백엔드·원격 호출은 0이다.
// 캡처: `FEDRUG_SHOT_DIR`을 주면 그 폴더에 `*-fedrug.png`를 남긴다. 주지 않으면 로컬 전용 캡처 폴더 `data/mock/fe-issue-shots`를
// 저장소 루트(`frontend/..`)에서, 없으면 worktree 옆의 메인 저장소(`P2-Medi`)에서 찾고, 둘 다 없으면 찍지 않는다.
const SHOT_DIR = process.env.FEDRUG_SHOT_DIR ?? [path.resolve(__dirname, "../../data/mock/fe-issue-shots"), path.resolve(__dirname, "../../../P2-Medi/data/mock/fe-issue-shots")].find((dir) => existsSync(dir));
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fedrug.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const medicationInput = (page: Page) => modal(page).getByRole("combobox", { name: "복용 중인 약(선택)" });
const candidates = (page: Page) => modal(page).getByTestId("medication-candidate");
const chips = (page: Page) => modal(page).getByTestId("medication");

/** 검색 요청(주소·방식·본문)과 프로필 저장 본문을 모은다. 검색어가 URL에 실리지 않는지 본다 */
function watch(page: Page) {
  const searches: { url: string; method: string; body: { q?: string } }[] = [];
  const saves: { medications?: { input_text: string; item_seq?: string | null }[] }[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/api/drugs/search")) searches.push({ url: request.url(), method: request.method(), body: request.postDataJSON() });
    if (request.method() === "POST" && pathname.endsWith("/api/profiles")) saves.push(request.postDataJSON());
  });
  return { searches, saves };
}

/** 모달이 화면 안에 있고 본문이 가로로 넘치지 않는다 */
async function expectModalFits(page: Page) {
  const box = (await modal(page).boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 0.5);
  expect(await page.getByTestId("account-body").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expectNoHorizontalScroll(page);
}

/** 카카오 로그인(목) → 건강 정보까지 동의 → 본인 프로필 폼 */
async function openSelfForm(page: Page) {
  await openApp(page);
  await page.getByTestId("login-entry").click();
  await modal(page).getByTestId("social-kakao").click();
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await modal(page).getByTestId("add-self").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
  await fillName(modal(page), "나");
}

for (const width of [393, 1280]) {
  test.describe(`프로필 약 검색 후보 고르기 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("후보(제품 → 성분, 최대 10)를 키보드·마우스로 고르고, 없으면 확인 안 된 약으로 저장한다. 검색은 POST 본문이고 검색어는 URL·콘솔에 없다", async ({ page }) => {
      const consoleLines: string[] = [];
      page.on("console", (message) => consoleLines.push(message.text()));
      const { searches, saves } = watch(page);
      await openSelfForm(page);
      const input = medicationInput(page);
      await expect(input).toHaveAttribute("aria-expanded", "false");
      await expect(input).toHaveAttribute("aria-autocomplete", "list");
      await expectTouchTarget(input, { widthToo: false });
      await expectTouchTarget(modal(page).getByTestId("medication-add"));

      // ---- 입력 → 300ms 뒤 한 번 검색 → 후보 목록(제품명 5 + 성분명 1)
      await input.fill("가나다");
      await expect(input).toHaveAttribute("aria-expanded", "true");
      await expect(candidates(page)).toHaveCount(6);
      expect(searches).toHaveLength(1);
      expect(searches[0].method).toBe("POST");
      expect(searches[0].body).toEqual({ q: "가나다" });
      expect(new URL(searches[0].url).search).toBe("");
      await expect(candidates(page).first()).toContainText("가나다정 100밀리그램");
      await expect(candidates(page).first()).toContainText("제품명");
      await expect(candidates(page).last()).toContainText("가나다마이신");
      await expect(candidates(page).last()).toContainText("성분명");
      for (const option of await candidates(page).all()) await expectTouchTarget(option, { widthToo: false });
      await expectModalFits(page);
      await shot(page, "drug-candidates");

      // ---- 키보드: ↓↓ → 둘째 후보가 활성(aria-activedescendant) → Enter로 고른다. 입력은 비고 목록은 닫힌다
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      const second = candidates(page).nth(1);
      await expect(second).toHaveAttribute("aria-selected", "true");
      await expect(input).toHaveAttribute("aria-activedescendant", (await second.getAttribute("id"))!);
      await page.keyboard.press("Enter");
      await expect(modal(page)).toHaveAttribute("data-step", "profile-form"); // Enter는 저장이 아니다
      await expect(chips(page)).toHaveCount(1);
      await expect(chips(page).first().getByTestId("medication-name")).toHaveText("가나다정 500밀리그램");
      await expect(chips(page).first()).toHaveAttribute("data-confirmed", "true");
      await expect(modal(page).getByTestId("medication-unconfirmed")).toHaveCount(0);
      await expect(input).toHaveValue("");
      await expect(input).toHaveAttribute("aria-expanded", "false");
      await expect(input).toBeFocused();

      // ---- 사전에 없는 약: 안내가 보이고 `추가`로 글자 그대로(확인 안 된 약) 넣는다
      await input.fill("없는약");
      await expect(modal(page).getByTestId("medication-no-candidates")).toBeVisible();
      await expect(input).toHaveAttribute("aria-expanded", "false");
      await expectModalFits(page);
      await shot(page, "drug-none");
      await modal(page).getByTestId("medication-add").click();
      await expect(chips(page)).toHaveCount(2);
      await expect(chips(page).nth(1)).toHaveAttribute("data-confirmed", "false");
      await expect(chips(page).nth(1).getByTestId("medication-unconfirmed")).toHaveText("확인 안 된 약");
      await expect(modal(page).getByTestId("medication-unconfirmed-note")).toBeVisible();

      // ---- 성분명 후보를 마우스로 고르면 번호가 없어 확인 안 된 약이다
      await input.fill("라마바펜");
      await expect(candidates(page)).toHaveCount(1);
      await expect(candidates(page).first()).toContainText("성분명");
      await candidates(page).first().click();
      await expect(chips(page)).toHaveCount(3);
      await expect(chips(page).nth(2).getByTestId("medication-name")).toHaveText("라마바펜");
      await expect(chips(page).nth(2)).toHaveAttribute("data-confirmed", "false");

      // ---- 후보 상한 10, Esc는 목록만 닫는다(모달은 남는다)
      await input.fill("다목");
      await expect(candidates(page)).toHaveCount(10);
      await page.keyboard.press("Escape");
      await expect(input).toHaveAttribute("aria-expanded", "false");
      await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
      await expect(input).toHaveValue("다목");
      await input.fill("");
      await expectModalFits(page);
      await shot(page, "drug-picked");

      // ---- 저장 모양: 고른 후보 `{input_text, item_seq}`, 확인 안 된 약 `item_seq` null
      await completeRequired(modal(page));
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(modal(page).getByTestId("profile-item")).toContainText("약 3개");
      expect(saves).toHaveLength(1);
      expect(saves[0].medications).toEqual([
        { input_text: "가나다정 500밀리그램", item_seq: "200000002" },
        { input_text: "없는약", item_seq: null },
        { input_text: "라마바펜", item_seq: null },
      ]);
      // 수정 폼을 다시 열면 확인됨·확인 안 됨이 그대로 보인다
      await modal(page).getByRole("button", { name: "나 수정" }).click();
      await expect(chips(page)).toHaveCount(3);
      expect(await chips(page).evaluateAll((els) => els.map((el) => el.getAttribute("data-confirmed")))).toEqual(["true", "false", "false"]);

      // ---- 검색어는 URL·콘솔에 남지 않는다
      expect(searches.every((request) => request.method === "POST" && new URL(request.url).search === "")).toBe(true);
      for (const secret of ["가나다", "없는약", "라마바펜", "다목"]) expect(consoleLines.join("\n")).not.toContain(secret);
    });

    test("검색이 실패해도(401 로그인 만료·503) 입력은 그대로 남고 글자 그대로 추가할 수 있다", async ({ page }) => {
      await openSelfForm(page);
      const input = medicationInput(page);
      await input.fill("mock-401");
      await expect(modal(page).getByTestId("medication-search-error")).toContainText("로그인이 만료돼");
      await expect(input).toHaveValue("mock-401");
      await expect(input).toHaveAttribute("aria-expanded", "false");
      const box = (await modal(page).getByTestId("medication-search-error").boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
      await expectModalFits(page);
      await shot(page, "drug-search-error");
      await modal(page).getByTestId("medication-add").click();
      await expect(chips(page)).toHaveCount(1);
      await expect(chips(page).first()).toHaveAttribute("data-confirmed", "false");
      await input.fill("mock-503");
      await expect(modal(page).getByTestId("medication-search-error")).toContainText("지금은 후보를 찾지 못했어요");
      await page.keyboard.press("Enter");
      await expect(chips(page)).toHaveCount(2);
      await expect(modal(page).getByTestId("medication-search-error")).toHaveCount(0);
    });
  });
}
