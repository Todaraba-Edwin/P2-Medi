import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, ask, expectClickReaches, expectNoHorizontalScroll, expectOnTop, expectTouchTarget, input, layerTel, openApp } from "./helpers";

// 계정 흐름(FE-04) e2e. Playwright 프로젝트 `msw-worker`(파일 이름의 `msw.spec.ts`)가 `NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드에 붙는다.
// 서버는 브라우저 워커의 목(src/mocks/account-handlers.ts, BE-11 계약과 같은 모양)이고 실제 백엔드·원격 호출은 0이다.
// 계정 진입점은 이 목 모드에서만 보인다(FE-04-02 A). 실제 백엔드 모드에서 숨는 것은 `account-switch.spec.ts`(app 프로젝트)가 본다.
// 캡처: `FE04_SHOT_DIR`을 주면 그 폴더에 `*-fe04.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE04_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  // 그림(마스코트·로고)이 다 뜬 뒤에 찍는다
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fe04.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const closeButton = (page: Page) => modal(page).getByRole("button", { name: "닫기" });
const backButton = (page: Page) => modal(page).getByRole("button", { name: "뒤로" });

function watchChat(page: Page) {
  const bodies: { question: string; context: unknown }[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat")) bodies.push(request.postDataJSON());
  });
  return bodies;
}

/** 모달이 화면 안에 있고 본문이 가로로 넘치지 않는다 */
async function expectModalFits(page: Page) {
  const box = (await modal(page).boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 0.5);
  const body = page.getByTestId("account-body");
  expect(await body.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expectNoHorizontalScroll(page);
}

test.describe("게스트 시작 360px", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("게스트로 시작 → 질문: 로그인·프로필 없이 답을 받고 대상 선택은 없다", async ({ page }) => {
    const bodies = watchChat(page);
    await openApp(page);
    const choice = page.getByTestId("entry-choice");
    await expect(choice.getByRole("button")).toHaveText(["게스트로 시작", "로그인/가입"]); // 게스트가 먼저
    await expectTouchTarget(page.getByTestId("guest-start"));
    await expectTouchTarget(page.getByTestId("login-entry"));
    await expectNoHorizontalScroll(page);
    await shot(page, "start");
    await page.getByTestId("guest-start").click();
    await expect(choice).toHaveCount(0);
    await expect(input(page)).toBeFocused();
    await expect(page.getByTestId("target-picker")).toHaveCount(0);
    await ask(page, "합성 질문");
    await expect(page.getByTestId("result-card")).toBeVisible();
    expect(bodies).toEqual([{ question: "합성 질문", context: { age: null, pregnant: null, confirmed_drugs: [] } }]);
    await expect(page.getByTestId("account-modal")).toHaveCount(0);
  });

  test("진입 선택을 누르지 않아도 바로 질문할 수 있다(응급)", async ({ page }) => {
    await openApp(page);
    await expect(page.getByTestId("entry-choice")).toBeVisible();
    await ask(page, "mock:응급 합성 질문");
    await expect(page.getByTestId("emergency-banner")).toBeVisible();
    await expect(page.getByTestId("result-card")).toBeVisible();
  });
});

for (const width of [360, 1280]) {
  test.describe(`로그인 → 동의 → 프로필 → 질문 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("모달 배치(PRD-13)와 전체 흐름, 질문할 때 고른 대상이 요청 context로 간다", async ({ page, context }) => {
      const bodies = watchChat(page);
      await openApp(page);
      const opener = page.getByTestId("login-entry");
      await opener.click();

      // ---- 로그인 첫 화면
      await expect(modal(page)).toHaveAttribute("data-step", "login");
      await expect(modal(page).getByRole("heading", { name: "프로필을 저장하려면 로그인하세요" })).toBeFocused();
      expect(await modal(page).locator("header, hr").count()).toBe(0); // ① header 띠·구분선 없음
      await expect(backButton(page)).toHaveCount(0); // ⑨ 첫 화면에는 `<`가 없다
      await expectTouchTarget(closeButton(page)); // ③
      expect(await closeButton(page).evaluate((el) => getComputedStyle(el).position)).toBe("absolute"); // ②
      await expectOnTop(closeButton(page));
      await expect(modal(page).getByTestId("social-naver")).toBeDisabled();
      await expect(modal(page).getByTestId("social-naver")).toContainText("준비 중");
      // 2열(넓은 폭) / 1열(360): 소개와 폼의 배치
      const title = (await modal(page).getByRole("heading", { level: 2 }).boundingBox())!;
      const form = (await modal(page).getByTestId("login-form").boundingBox())!;
      if (width >= 1024) expect(form.x).toBeGreaterThan(title.x + title.width - 1);
      else expect(form.y).toBeGreaterThan(title.y + title.height - 1);
      // ⑦ 코너 버튼이 제목·마스코트와 겹치지 않는다(본문 첫 요소는 버튼 아래에서 시작한다)
      const close = (await closeButton(page).boundingBox())!;
      const mascot = (await modal(page).getByTestId("mascot").boundingBox())!;
      expect(mascot.y).toBeGreaterThanOrEqual(close.y + close.height - 0.5);
      // ⑧ 모달이 머리줄을 덮는 동안에도 119 진입점을 누를 수 있다
      await expect(layerTel(page)).toHaveAttribute("href", "tel:119");
      await expectTouchTarget(layerTel(page));
      await expectClickReaches(page, layerTel(page));
      await expectModalFits(page);
      await shot(page, "login");

      // ④ Esc로 닫히고 초점이 연 버튼으로 돌아온다
      await page.keyboard.press("Escape");
      await expect(modal(page)).toHaveCount(0);
      await expect(opener).toBeFocused();
      await opener.click();

      // ---- 가입 화면: `<`가 생기고 같은 높이로 마주 본다
      await modal(page).getByRole("button", { name: "이메일로 가입하기" }).click();
      await expect(modal(page)).toHaveAttribute("data-step", "signup");
      const back = (await backButton(page).boundingBox())!;
      const closeNow = (await closeButton(page).boundingBox())!;
      expect(back.y).toBeCloseTo(closeNow.y, 0);
      expect(back.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(back.width).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(back.x).toBeLessThan(closeNow.x);
      await backButton(page).click();
      await expect(modal(page)).toHaveAttribute("data-step", "login");

      // ---- 이메일 로그인(목) → 동의
      await modal(page).getByLabel("이메일").fill("user@example.com");
      await modal(page).getByLabel("비밀번호").fill("pw-1234");
      await modal(page).getByRole("button", { name: "로그인", exact: true }).click();
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      await expect(modal(page).getByTestId("legal-doc")).toHaveCount(4);
      await expect(modal(page).getByTestId("legal-doc").first()).toContainText("이용약관 (합성 목 문서)"); // 서버(목) 값 그대로
      const submit = modal(page).getByTestId("consent-submit");
      await expect(submit).toBeDisabled(); // 필수 미동의면 다음 불가
      await expectModalFits(page);
      await shot(page, "consent");
      const agree = (docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");
      // 고지 문서(처리방침: 외부 AI 전송 안내)는 체크 없는 고지다(FE-04-03 A). 동의 대상은 셋뿐이다
      await expect(agree("privacy_policy")).toHaveCount(0);
      await expect(modal(page).getByRole("checkbox")).toHaveCount(3);
      await expect(modal(page).getByTestId("legal-not-reviewed")).toHaveCount(4); // 초안·법률 검토 전 표지
      await agree("terms").check();
      await expect(submit).toBeDisabled();
      await agree("privacy_consent").check();
      await agree("sensitive_consent").check();
      await expect(submit).toBeEnabled();
      await submit.click();

      // ---- 프로필: 본인 추가(연령대·임신 여부·복용 약)
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await modal(page).getByTestId("add-self").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
      await modal(page).getByLabel("이름(별명)").fill("나");
      await modal(page).getByLabel("연령대").selectOption("y19_64");
      await modal(page).getByRole("radio", { name: "예" }).check();
      await modal(page).getByLabel("복용 중인 약(선택)").fill("가나다정 100밀리그램");
      await modal(page).getByTestId("medication-add").click();
      await expect(modal(page).getByTestId("medication")).toHaveText(["가나다정 100밀리그램"]);
      await expectModalFits(page);
      await shot(page, "profile-form");
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
      // 가족 한 명 더
      await modal(page).getByTestId("add-family").click();
      await modal(page).getByLabel("이름(별명)").fill("첫째");
      await modal(page).getByLabel("연령대").selectOption("y6_11");
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
      await expectModalFits(page);
      await shot(page, "profiles");
      await closeButton(page).click();
      await expect(modal(page)).toHaveCount(0);

      // ---- 채팅: 로그인하면 진입 선택은 사라지고 "누가 먹나요"가 입력창 위에 보인다
      await expect(page.getByTestId("entry-choice")).toHaveCount(0);
      const picker = page.getByTestId("target-picker");
      await expect(picker.getByTestId("target-option")).toHaveText(["선택 안 함", "나", "첫째"]);
      for (const option of await picker.getByTestId("target-option").all()) await expectTouchTarget(option, { widthToo: false });
      const pickerBox = (await picker.boundingBox())!;
      expect(pickerBox.y + pickerBox.height).toBeLessThanOrEqual((await input(page).boundingBox())!.y + 0.5); // 입력창 위
      await expectNoHorizontalScroll(page);
      await picker.getByText("나", { exact: true }).click();
      await shot(page, "target");
      await ask(page, "합성 질문");
      await expect(page.getByTestId("result-card")).toBeVisible();
      await shot(page, "answer");
      await picker.getByText("첫째", { exact: true }).click();
      await ask(page, "둘째 합성 질문");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      await picker.getByText("선택 안 함", { exact: true }).click();
      await ask(page, "셋째 합성 질문");
      await expect(page.locator('[data-turn="turn-3"]').getByTestId("result-card")).toBeVisible();
      expect(bodies.map((body) => body.context)).toEqual([
        { age: { lower: 19, upper: 64, unit: "세" }, pregnant: true, confirmed_drugs: [] }, // 복용 약(입력 원문)은 싣지 않는다
        { age: { lower: 6, upper: 11, unit: "세" }, pregnant: null, confirmed_drugs: [] },
        { age: null, pregnant: null, confirmed_drugs: [] },
      ]);

      // ---- 로그인·프로필·건강 정보·질문을 브라우저 저장소·쿠키에 남기지 않는다
      const stored = await page.evaluate(async () => {
        const dump = (storage: Storage) => JSON.stringify(Object.fromEntries(Object.entries(storage)));
        const names = (await indexedDB.databases?.())?.map((db) => db.name) ?? [];
        // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
        // eslint-disable-next-line no-restricted-properties
        return { local: dump(window.localStorage), session: dump(window.sessionStorage), indexed: names };
      });
      for (const text of [stored.local, stored.session, JSON.stringify(await context.cookies())]) {
        for (const secret of ["user@example.com", "pw-1234", "가나다정", "첫째", "합성 질문", "y19_64", "pregnan", "00000000-0000-4000"]) expect(text).not.toContain(secret);
      }
      expect(stored.indexed).toEqual([]);
    });
  });
}

test.describe("금기 결과 위에서 여는 계정 모달 360px(ISSUE-006 상태)", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("응급 답 뒤에는 119 배너를 덮지 않고 마스코트 없이 뜬다. 탈퇴는 확인을 거친다", async ({ page }) => {
    await openApp(page);
    await ask(page, "mock:응급 합성 질문");
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    await page.getByTestId("menu-drawer").getByTestId("account-entry").click();
    await expect(page.getByTestId("menu-drawer")).toHaveCount(0); // 드로어는 닫히고 모달만 남는다
    await expect(modal(page)).toHaveAttribute("data-step", "login");
    // 119 배너는 모달·스크림 밖(위)에 있고 누를 수 있다. 배너가 있으니 모달 안 진입점과 마스코트는 없다
    const bannerLink = page.getByTestId("emergency-banner").locator('a[href="tel:119"]');
    const bannerBox = (await page.getByTestId("emergency-banner").boundingBox())!;
    expect((await page.getByTestId("account-scrim").boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
    await expectOnTop(bannerLink);
    await expectClickReaches(page, bannerLink);
    await expect(layerTel(page)).toHaveCount(0);
    await expect(modal(page).getByTestId("mascot")).toHaveCount(0);
    await expectModalFits(page);
    await shot(page, "login-over-result");

    // 이미 동의를 마친 사용자(목): 프로필이 첫 화면이라 `<`가 없다
    await modal(page).getByLabel("이메일").fill("mock-onboarded@example.com");
    await modal(page).getByLabel("비밀번호").fill("pw-1234");
    await modal(page).getByRole("button", { name: "로그인", exact: true }).click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await expect(backButton(page)).toHaveCount(0);
    await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
    await modal(page).getByTestId("withdraw").click();
    const confirm = page.getByTestId("confirm-dialog");
    await expect(confirm).toBeVisible();
    await shot(page, "withdraw-confirm");
    await confirm.getByRole("button", { name: "탈퇴하기" }).click();
    await expect(modal(page)).toHaveCount(0);
    await expect(page.getByTestId("target-picker")).toHaveCount(0); // 게스트로 돌아왔다
    await expect(page.getByTestId("result-card")).toBeVisible(); // 대화는 그대로다
  });
});
