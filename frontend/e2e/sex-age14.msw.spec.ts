import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, ask, expectNoHorizontalScroll, expectTouchTarget, openApp, pickTarget, pickChoice, completeRequired, fillName } from "./helpers";

// GROUP-03 2단계 F1(FE-04, 2026-11-20): 프로필 성별(선택) 입력 + 첫 로그인 동의 화면의 "만 14세 이상입니다." 별도 필수 체크.
// Playwright 프로젝트 `msw-worker`(파일 이름의 `msw.spec.ts`)가 `NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드에 붙는다. 실제 백엔드·원격 호출 0.
// 캡처: `G3F1_SHOT_DIR`을 주면 그 폴더에 `*-{폭}-g3f1.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.G3F1_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-g3f1.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const agree = (page: Page, docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");

function watchChat(page: Page) {
  const bodies: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat")) bodies.push(request.postDataJSON());
  });
  return bodies;
}

function watchProfiles(page: Page) {
  const bodies: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if ((request.method() === "POST" || request.method() === "PATCH") && new URL(request.url()).pathname.includes("/api/profiles")) bodies.push(request.postDataJSON());
  });
  return bodies;
}

for (const width of [393, 1280]) {
  test.describe(`성별(선택)·만 14세 필수 체크 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("만 14세 체크 없이는 진행 불가 → 성별은 연령대 아래 선택 칸, 건강 동의 없이 저장·수정·지우기 → /chat 본문에 성별 없음", async ({ page }) => {
      const chatBodies = watchChat(page);
      const profileBodies = watchProfiles(page);
      const consentPosts: unknown[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/consents")) consentPosts.push(request.postDataJSON());
      });
      await openApp(page);
      await page.getByTestId("login-entry").click();
      await modal(page).getByTestId("social-kakao").click(); // 목: 페이지를 옮기지 않고 목 세션만 만든다
      await expect(modal(page)).toHaveAttribute("data-step", "consent");

      // ---- 동의 화면: 문서 카드 4 + 별도 체크 1(본문·버전 줄 없음). 문서 카드 뒤, 버튼 앞
      await expect(modal(page).getByTestId("legal-doc")).toHaveCount(4);
      const age = modal(page).getByTestId("age-14-check");
      await expect(age).toBeVisible();
      await expect(age).toHaveAttribute("data-required", "true");
      await expect(age).toContainText("[필수] 만 14세 이상입니다.");
      await expect(age).not.toContainText("버전");
      await expect(age.getByRole("heading")).toHaveCount(0);
      const ageLabel = age.locator("label");
      await expectTouchTarget(ageLabel, { widthToo: false });
      const ageBox = (await age.boundingBox())!;
      const lastDocBox = (await modal(page).getByTestId("legal-doc").last().boundingBox())!;
      expect(ageBox.y).toBeGreaterThanOrEqual(lastDocBox.y + lastDocBox.height - 0.5);
      const submit = modal(page).getByTestId("consent-submit");
      await expect(submit).toBeDisabled();
      await agree(page, "terms").check();
      await agree(page, "privacy_consent").check();
      await expect(submit).toBeDisabled(); // 필수 문서 둘만으로는 안 된다(만 14세 확인 필요)
      await expect(modal(page).getByTestId("consent-hint")).toBeVisible();
      await age.scrollIntoViewIfNeeded();
      await expectNoHorizontalScroll(page);
      await shot(page, "consent-age14");
      await submit.click({ force: true }); // 비활성 버튼을 억지로 눌러도 보내지 않는다
      expect(consentPosts).toEqual([]);
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      await agree(page, "age_14").check();
      await expect(submit).toBeEnabled();
      await submit.click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      expect(consentPosts).toEqual([
        {
          channel: "onboarding",
          items: [
            { doc_type: "terms", version: 1, action: "agree" },
            { doc_type: "privacy_consent", version: 1, action: "agree" },
            { doc_type: "age_14", version: 1, action: "agree" },
          ],
        },
      ]);

      // ---- 프로필 폼: 성별(FE-17 U-07부터 필수, 여성|남성 버튼)은 연령대 아래, 건강 정보 묶음 밖. 처음엔 고르지 않은 상태(로그인 정보로 채우지 않는다)
      await modal(page).getByTestId("add-self").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
      const sex = modal(page).getByRole("radiogroup", { name: "성별", exact: true });
      for (const radio of await sex.getByRole("radio").all()) await expect(radio).toBeEnabled(); // 건강 정보 동의가 없어도 고를 수 있다
      // 건강 정보 묶음은 비활성이다(fieldset은 Playwright가 disabled 판정을 하지 않으므로 안의 라디오·약 입력으로 본다)
      for (const radio of await modal(page).getByTestId("health-fields").getByRole("radio").all()) await expect(radio).toBeDisabled(); // 프로필 색(건강 정보 아님)은 묶음 밖
      await expect(modal(page).getByLabel("복용 중인 약(선택)")).toBeDisabled();
      await expect(sex.locator('[aria-checked="true"]')).toHaveCount(0);
      await expect(sex.getByRole("radio")).toHaveText(["여성", "남성"]);
      expect(await sex.evaluate((el) => el.closest('[data-testid="health-fields"]'))).toBeNull();
      const ageBandBox = (await modal(page).getByRole("radiogroup", { name: "연령대", exact: true }).boundingBox())!;
      const sexBox = (await sex.boundingBox())!;
      expect(sexBox.y).toBeGreaterThanOrEqual(ageBandBox.y + ageBandBox.height - 0.5);
      expect(sexBox.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      const healthBox = (await modal(page).getByTestId("health-fields").boundingBox())!;
      expect(healthBox.y).toBeGreaterThanOrEqual(sexBox.y + sexBox.height - 0.5);
      // 글자 색은 토큰이다(하드코딩 색 없음): 버튼이 계산된 색을 갖고 배경과 다르다
      const colors = await sex.getByRole("radio").first().evaluate((el) => ({ fg: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
      expect(colors.fg).not.toBe(colors.bg);
      await fillName(modal(page), "나");
      await pickChoice(modal(page), "연령대", "만 19~64세");
      await pickChoice(modal(page), "성별", "여성");
      await expectNoHorizontalScroll(page);
      await shot(page, "profile-form-sex");
      await completeRequired(modal(page));
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(modal(page).getByTestId("profile-item")).toContainText("본인 · 만 19~64세 · 여성");
      await shot(page, "profiles-sex");
      // 수정: 저장된 값이 골라져 있고 남성으로 바꾼다(필수라 지우기는 없다)
      await modal(page).getByRole("button", { name: "나 수정" }).click();
      await expect(sex.getByRole("radio", { name: "여성", exact: true })).toHaveAttribute("aria-checked", "true");
      await pickChoice(modal(page), "성별", "남성");
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(modal(page).getByTestId("profile-item")).toContainText("본인 · 만 19~64세 · 남성");
      // 가족 프로필에도 같은 칸
      await modal(page).getByTestId("add-family").click();
      await modal(page).getByLabel("이름(별명)").fill("첫째");
      await pickChoice(modal(page), "성별", "남성");
      await completeRequired(modal(page));
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
      await expect(modal(page).getByTestId("profile-item").nth(1)).toContainText("자녀 · 만 19~64세 · 남성");
      expect(profileBodies.map((body) => body.sex)).toEqual(["female", "male", "male"]);
      for (const body of profileBodies) expect(Object.keys(body)).toEqual(["relation", "label", "age_band", "sex", "avatar_color"]); // 건강 칸은 없다(병아리 배경색은 건강 정보가 아니라 늘 실린다, FE-17 U-01)
      // 다시 성별을 넣고 질문: `/chat` 본문에는 성별이 없다
      await modal(page).getByRole("button", { name: "나 수정" }).click();
      await pickChoice(modal(page), "성별", "여성");
      await completeRequired(modal(page));
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await modal(page).getByRole("button", { name: "닫기" }).click();
      await expect(modal(page)).toHaveCount(0);
      await pickTarget(page, "나");
      await ask(page, "합성 질문");
      await expect(page.getByTestId("result-card")).toBeVisible();
      // 건강 동의 없이 저장한 프로필은 pregnancy_status가 null이라 입력창 토글 기본값 "일반인"(FE-11-12 A, g1-5a)이 실려 pregnant=false다
      expect(chatBodies).toEqual([{ question: "합성 질문", context: { age: { lower: 19, upper: 64, unit: "세" }, pregnant: false, confirmed_drugs: [], prior_drugs: [], took_today: null } }]);
      expect(JSON.stringify(chatBodies)).not.toMatch(/sex|gender|female|male/);
    });
  });
}
