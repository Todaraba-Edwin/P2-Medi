import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { MOCK_KAKAO_NICKNAME } from "../src/mocks/fixtures/account";
import { HEIGHT, expectNoHorizontalScroll } from "./helpers";

// 본인 프로필 이름 초기값 = 카카오 닉네임(FE-04-28 B, 2026-11-22 사용자 결정, l9).
// 실제 OAuth 왕복은 하지 않는다. 목(MSW) 모드에서 `?mock_session=new&mock_provider=kakao|google`(브라우저 워커 전용)로
// "카카오(구글)로 로그인해 돌아온 페이지"를 흉내 내고 `auth_resume=1`로 온보딩 모달을 연다. 실제 백엔드·원격 호출은 0이다.
// 확인: 카카오면 이름 칸에 닉네임이 보인다 → 저장 전에는 프로필 쓰기 요청이 없다 → 고쳐서 저장하면 고친 값만 요청에 실린다.
// 구글·가족 추가는 비어 있다. 성별·연령대는 공급자 정보로 채우지 않는다.
// 캡처: `L9_SHOT_DIR`을 주면 `l9-nickname-prefill-*.png`를 남긴다(없으면 로컬 전용 `data/mock/fe-issue-shots`가 있을 때만 그곳에).
const SHOT_DIR = process.env.L9_SHOT_DIR ?? [path.resolve(__dirname, "../../data/mock/fe-issue-shots"), path.resolve(__dirname, "../../../P2-Medi/data/mock/fe-issue-shots")].find((dir) => existsSync(dir));
const shot = async (page: Page, name: string, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l9-nickname-prefill-${name}-${page.viewportSize()!.width}-${scheme}.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const nameField = (page: Page) => modal(page).getByLabel("이름(별명)");
const agree = (page: Page, docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");

/** 소셜 로그인에서 막 돌아온 상태로 열고 필수 동의를 마쳐 프로필 화면까지 간다 */
async function openProfiles(page: Page, provider: "kakao" | "google") {
  await page.goto(`/?mock_session=new&mock_provider=${provider}&auth_resume=1`);
  await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "age_14"]) await agree(page, docType).check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
}

/** 페이지가 보낸 프로필 쓰기 요청(POST·PATCH /api/profiles*)의 본문 `label`들 */
async function recordProfileWrites(page: Page) {
  const labels: unknown[] = [];
  page.on("request", (request) => {
    if (/\/api\/profiles/.test(request.url()) && (request.method() === "POST" || request.method() === "PATCH")) labels.push(request.postDataJSON()?.label);
  });
  return labels;
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`카카오 닉네임 초기값 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("카카오 → 본인 프로필 만들기: 이름 칸에 닉네임이 보이고, 저장 전에는 요청이 없으며, 고쳐서 저장하면 고친 값이 실린다", async ({ page }) => {
        const writes = await recordProfileWrites(page);
        await openProfiles(page, "kakao");
        await modal(page).getByTestId("add-self").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await expect(nameField(page)).toHaveValue(MOCK_KAKAO_NICKNAME);
        await expect(modal(page).getByTestId("profile-sex")).toHaveValue(""); // 다른 칸은 채우지 않는다
        await expect(modal(page).getByLabel("연령대")).toHaveValue("");
        await expectNoHorizontalScroll(page);
        await shot(page, "self-form", scheme);
        expect(writes).toEqual([]); // 초기값은 서버로 가지 않았다
        await nameField(page).fill("나");
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
        await expect(modal(page).getByTestId("profile-item")).toContainText("나");
        expect(writes).toEqual(["나"]); // 고친 값만
        // 본인 수정 화면은 저장된 값이다(닉네임으로 되돌리지 않는다)
        await modal(page).getByRole("button", { name: "나 수정" }).click();
        await expect(nameField(page)).toHaveValue("나");
      });

      test("카카오여도 가족 프로필 추가는 비어 있다. 지운 뒤 저장하면 기존 검증(이름 입력) 그대로", async ({ page }) => {
        const writes = await recordProfileWrites(page);
        await openProfiles(page, "kakao");
        await modal(page).getByTestId("add-family").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await expect(nameField(page)).toHaveValue("");
        await modal(page).getByRole("button", { name: "취소" }).click();
        await modal(page).getByTestId("add-self").click();
        await expect(nameField(page)).toHaveValue(MOCK_KAKAO_NICKNAME);
        await nameField(page).fill("");
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page).getByRole("alert")).toContainText("이름(별명)을 입력해 주세요.");
        expect(writes).toEqual([]);
      });

      test("구글 로그인은 비어 있다(구글 실명은 가져오지 않는다)", async ({ page }) => {
        await openProfiles(page, "google");
        await modal(page).getByTestId("add-self").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await page.waitForTimeout(300); // 초기값 읽기가 끝날 시간을 주고도 비어 있어야 한다
        await expect(nameField(page)).toHaveValue("");
      });
    });
  }
}
