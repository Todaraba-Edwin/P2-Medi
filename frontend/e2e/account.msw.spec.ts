import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, ask, expectClickReaches, expectNoHorizontalScroll, expectOnTop, expectTouchTarget, input, layerTel, openApp } from "./helpers";

// 계정 흐름(FE-04) e2e. Playwright 프로젝트 `msw-worker`(파일 이름의 `msw.spec.ts`)가 `NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드에 붙는다.
// 서버는 브라우저 워커의 목(src/mocks/account-handlers.ts, BE-11 계약과 같은 모양)이고 실제 백엔드·원격 호출은 0이다.
// 계정 진입점은 목 모드이거나 Supabase 설정이 있을 때 보인다(FE-04-02 A·FE-04-05 A). 설정이 없는 실제 백엔드 모드에서 숨는 것은 `account-switch.spec.ts`(app 프로젝트)가 본다.
// 실제 OAuth 왕복(Google·Kakao 동의 화면)은 e2e에서 하지 않는다: 소셜 로그인은 목 세션으로, 콜백 실패는 `/auth/callback`에 오류 값을 붙여 들어가 본다.
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

/** 모달 상자의 크기(단계가 바뀌어도 같아야 한다) */
async function modalSize(page: Page) {
  const box = (await modal(page).boundingBox())!;
  return { width: Math.round(box.width), height: Math.round(box.height) };
}

/** 마우스를 올리면 계산된 값이 바뀐다(전환이 끝난 뒤의 값) */
async function expectHoverChanges(page: Page, target: Locator, property: "backgroundColor" | "filter" | "boxShadow") {
  const read = () => target.evaluate((el, name) => getComputedStyle(el)[name], property);
  await page.mouse.move(0, 0);
  const before = await read();
  await target.hover();
  await expect.poll(read).not.toBe(before);
  await page.mouse.move(0, 0);
  await expect.poll(read).toBe(before);
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
    expect(bodies).toEqual([{ question: "합성 질문", context: { age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [], took_today: null } }]);
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
      // ---- 버튼 호버 반응(사용자 지시 2026-11-19): 손가락 커서, 올리면 바탕이 바뀐다
      expect(await opener.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
      expect(await page.getByTestId("guest-start").evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
      await expectHoverChanges(page, opener, "backgroundColor");
      await expectHoverChanges(page, page.getByTestId("guest-start"), "filter");
      await opener.click();

      // ---- 로그인 첫 화면
      await expect(modal(page)).toHaveAttribute("data-step", "login");
      await expect(modal(page).getByRole("heading", { name: "프로필을 저장하려면 로그인하세요" })).toBeFocused();
      expect(await modal(page).locator("header, hr").count()).toBe(0); // ① header 띠·구분선 없음
      await expect(backButton(page)).toHaveCount(0); // ⑨ 첫 화면에는 `<`가 없다
      await expectTouchTarget(closeButton(page)); // ③
      expect(await closeButton(page).evaluate((el) => getComputedStyle(el).position)).toBe("absolute"); // ②
      await expectOnTop(closeButton(page));
      // 사양 변경(사용자 지시 2026-11-19·PRD-01-10 A): Naver와 이메일 로그인·가입은 화면에 없다. 소셜 로고 버튼 2개만 남는다
      await expect(modal(page).getByTestId("social-naver")).toHaveCount(0);
      await expect(modal(page).locator("input")).toHaveCount(0);
      await expect(modal(page).getByRole("button", { name: "이메일로 가입하기" })).toHaveCount(0);
      await expect(modal(page).getByRole("button", { name: "로그인", exact: true })).toHaveCount(0);
      await expect(modal(page).getByRole("button")).toHaveText(["닫기", "Google로 계속하기", "카카오 로그인", "로그인 없이 계속하기"]);
      // 제목은 "간편 로그인"(FE-04-17 A, 2026-11-19). 이전 글자 "다른 방법으로 로그인"은 남지 않는다
      await expect(modal(page)).not.toContainText("다른 방법으로 로그인");
      const social = modal(page).getByRole("group", { name: "간편 로그인" });
      const google = social.getByRole("button", { name: "Google로 계속하기" });
      const kakao = social.getByRole("button", { name: "카카오 로그인" });
      // 사양 변경(사용자 지시 2026-11-19 FE-04e): 가로로 꽉 찬 "공식 로고 + 글자" 버튼이 세로로 놓인다
      const groupBox = (await social.boundingBox())!;
      for (const button of [google, kakao]) {
        const logo = button.locator("img");
        await expect.poll(() => logo.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
        await expect(logo).toHaveAttribute("alt", "");
        const box = (await button.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(MIN_TOUCH);
        expect(Math.abs(box.width - groupBox.width)).toBeLessThanOrEqual(1); // 가로로 꽉 찬다
        expect(await button.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
        // 로고 18~20px·비율 1:1(바꾸지 않는다), 글자 왼쪽에 8px 이상 떨어져 있다
        const logoBox = (await logo.boundingBox())!;
        expect(logoBox.width).toBeGreaterThanOrEqual(18);
        expect(logoBox.width).toBeLessThanOrEqual(20);
        expect(logoBox.width / logoBox.height).toBeCloseTo(1, 2);
        const textLeft = await button.evaluate((el) => {
          const range = document.createRange();
          range.selectNodeContents(el.lastChild!);
          return range.getBoundingClientRect().left;
        });
        expect(textLeft - (logoBox.x + logoBox.width)).toBeGreaterThanOrEqual(8 - 0.5);
      }
      const googleBox = (await google.boundingBox())!;
      const kakaoBox = (await kakao.boundingBox())!;
      expect(kakaoBox.y).toBeGreaterThanOrEqual(googleBox.y + googleBox.height); // 세로 목록
      // 회사 가이드 색: Google 흰 바탕, Kakao 노랑 #FEE500 컨테이너·모서리 12px
      expect(await google.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");
      expect(await kakao.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(254, 229, 0)");
      expect(await kakao.evaluate((el) => getComputedStyle(el).borderRadius)).toBe("12px");
      await expectHoverChanges(page, google, "boxShadow");
      // 키보드로 가면 초점 윤곽선이 보인다(포커스 링 유지)
      await closeButton(page).focus();
      for (let presses = 0; presses < 4 && !(await google.evaluate((el) => el === document.activeElement)); presses++) await page.keyboard.press("Tab");
      await expect(google).toBeFocused();
      expect(await google.evaluate((el) => el.matches(":focus-visible") && getComputedStyle(el).outlineStyle !== "none" && parseFloat(getComputedStyle(el).outlineWidth) > 0)).toBe(true);
      // 2열(넓은 폭) / 1열(360): 소개와 로그인 방법의 배치
      const title = (await modal(page).getByRole("heading", { level: 2 }).boundingBox())!;
      const form = groupBox;
      const size = await modalSize(page); // 이 크기가 모든 단계에서 같아야 한다
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

      // ---- 소셜 로그인(목) → 동의: `<`가 생기고 같은 높이로 마주 본다(사양 변경: 가입 화면이 빠져 `<`가 생기는 첫 단계는 동의다)
      await kakao.click();
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      const back = (await backButton(page).boundingBox())!;
      const closeNow = (await closeButton(page).boundingBox())!;
      expect(back.y).toBeCloseTo(closeNow.y, 0);
      expect(back.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(back.width).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(back.x).toBeLessThan(closeNow.x);
      await expectHoverChanges(page, backButton(page), "backgroundColor");
      await expectHoverChanges(page, closeButton(page), "backgroundColor");
      await expect(modal(page).getByTestId("legal-doc")).toHaveCount(4);
      expect(await modalSize(page)).toEqual(size); // 단계가 바뀌어도 상자 크기가 같다
      // 넘치는 내용은 본문 안에서만 스크롤한다
      expect(await page.getByTestId("account-body").evaluate((el) => el.scrollHeight > el.clientHeight && getComputedStyle(el).overflowY === "auto")).toBe(true);
      await expect(modal(page).getByTestId("legal-doc").first()).toContainText("이용약관 (합성 목 문서)"); // 서버(목) 값 그대로
      const submit = modal(page).getByTestId("consent-submit");
      await expect(submit).toBeDisabled(); // 필수 미동의면 다음 불가
      await expectModalFits(page);
      await shot(page, "consent");
      const agree = (docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");
      // 고지 문서(처리방침: 외부 AI 전송 안내)는 체크 없는 고지다(FE-04-03 A). 동의 대상은 문서 셋 + 만 14세 확인 체크다
      await expect(agree("privacy_policy")).toHaveCount(0);
      await expect(modal(page).getByRole("checkbox")).toHaveCount(4);
      await expect(modal(page).getByTestId("legal-not-reviewed")).toHaveCount(4); // 초안·법률 검토 전 표지(문서 카드만)
      await agree("terms").check();
      await expect(submit).toBeDisabled();
      await agree("privacy_consent").check();
      await agree("sensitive_consent").check();
      await expect(submit).toBeDisabled(); // 만 14세 확인(별도 필수 체크, PRD-17-12 A)이 빠지면 진행 불가
      await agree("age_14").check();
      await expect(submit).toBeEnabled();
      await submit.click();

      // ---- 프로필: 본인 추가(연령대·임신 여부·복용 약)
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      expect(await modalSize(page)).toEqual(size);
      await modal(page).getByTestId("add-self").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
      expect(await modalSize(page)).toEqual(size);
      await modal(page).getByLabel("이름(별명)").fill("나");
      await modal(page).getByLabel("연령대").selectOption("y19_64");
      await modal(page).getByLabel("성별").selectOption("female"); // 성별(선택)은 `/chat` 요청에 실리지 않는다(아래 bodies)
      await modal(page).getByRole("radio", { name: "예" }).check();
      // 약은 후보를 고르지 않고 `추가`로 글자 그대로 넣는다(확인 안 된 약 표지가 붙는다). 후보 고르기는 `fedrug.msw.spec.ts`가 본다
      await modal(page).getByLabel("복용 중인 약(선택)").fill("가나다정 100밀리그램");
      await modal(page).getByTestId("medication-add").click();
      await expect(modal(page).getByTestId("medication-name")).toHaveText(["가나다정 100밀리그램"]);
      await expect(modal(page).getByTestId("medication-unconfirmed")).toHaveCount(1);
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
      expect(await modalSize(page)).toEqual(size);
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
      // 첫째로 되묻기 → 고른 약으로 다시 묻기: 이번 답은 confirmed_drugs, 답이 오면 이전 선택(prior_drugs)이 되어 다음 질문에 실린다(AG-21-02·03 A)
      await ask(page, "mock:되묻기 둘째 합성 질문");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("candidate-card")).toBeVisible();
      await page.locator('[data-turn="turn-2"]').getByTestId("candidate").nth(0).click();
      await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
      await expect(page.locator('[data-turn="turn-3"]').getByTestId("result-card")).toBeVisible();
      await ask(page, "둘째 합성 질문");
      await expect(page.locator('[data-turn="turn-4"]').getByTestId("result-card")).toBeVisible();
      // "누가 먹나요" 대상을 바꾸면 이전 선택을 비운다(다른 사람의 약을 같은 이름으로 확인하지 않게)
      await picker.getByText("선택 안 함", { exact: true }).click();
      await ask(page, "셋째 합성 질문");
      await expect(page.locator('[data-turn="turn-5"]').getByTestId("result-card")).toBeVisible();
      const pick = { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" };
      const child = { age: { lower: 6, upper: 11, unit: "세" }, pregnant: null };
      expect(bodies.map((body) => body.context)).toEqual([
        { age: { lower: 19, upper: 64, unit: "세" }, pregnant: true, confirmed_drugs: [], prior_drugs: [], took_today: null }, // 복용 약(입력 원문)은 싣지 않는다
        { ...child, confirmed_drugs: [], prior_drugs: [], took_today: null },
        { ...child, confirmed_drugs: [pick], prior_drugs: [], took_today: null },
        { ...child, confirmed_drugs: [], prior_drugs: [pick], took_today: null },
        { age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [], took_today: null },
      ]);
      expect(JSON.stringify(bodies)).not.toMatch(/sex|gender|female/); // 성별은 외부 AI로 가는 `/chat` 본문에 없다(S10)

      // ---- 로그인·프로필·건강 정보·질문을 브라우저 저장소·쿠키에 남기지 않는다
      const stored = await page.evaluate(async () => {
        const dump = (storage: Storage) => JSON.stringify(Object.fromEntries(Object.entries(storage)));
        const names = (await indexedDB.databases?.())?.map((db) => db.name) ?? [];
        // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
        // eslint-disable-next-line no-restricted-properties
        return { local: dump(window.localStorage), session: dump(window.sessionStorage), indexed: names };
      });
      for (const text of [stored.local, stored.session, JSON.stringify(await context.cookies())]) {
        for (const secret of ["가나다정", "첫째", "합성 질문", "y19_64", "pregnan", "00000000-0000-4000"]) expect(text).not.toContain(secret);
      }
      expect(stored.indexed).toEqual([]);
    });
  });
}

for (const width of [360, 1280]) {
  test.describe(`소셜 로그인(목)·콜백 실패 안내·건강 정보 동의 철회 확인 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("카카오 로그인(목) → 동의 → 건강 정보 저장 → 철회는 확인 모달을 거친다 → 로그아웃", async ({ page }) => {
      const consentPosts: unknown[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/consents")) consentPosts.push(request.postDataJSON());
      });
      await openApp(page);
      await page.getByTestId("login-entry").click();
      await expect(modal(page).getByTestId("social-google")).toBeEnabled();
      await modal(page).getByTestId("social-kakao").click(); // 목: 페이지를 옮기지 않고 목 세션만 만든다
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      const agree = (docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");
      for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await agree(docType).check();
      await modal(page).getByTestId("consent-submit").click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(page.getByTestId("confirm-dialog")).toHaveCount(0); // 새로 동의할 때는 확인 모달이 없다
      await modal(page).getByTestId("add-self").click();
      await modal(page).getByLabel("이름(별명)").fill("나");
      await modal(page).getByRole("radio", { name: "예" }).check();
      await modal(page).getByTestId("profile-save").click();
      await expect(modal(page).getByTestId("profile-item")).toContainText("임신 여부 예");

      // ---- 건강 정보 동의 철회: 확인 모달(FE-04-06 A)
      await modal(page).getByRole("button", { name: "동의 내용 보기" }).click();
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      await agree("sensitive_consent").uncheck();
      await expect(modal(page).getByTestId("health-withdraw-warning")).toBeVisible();
      await modal(page).getByTestId("consent-submit").click();
      const confirm = page.getByTestId("confirm-dialog");
      await expect(confirm).toBeVisible();
      await expect(confirm).toHaveAttribute("role", "alertdialog");
      await expect(confirm).toContainText("건강 정보 동의를 철회할까요?");
      await expect(confirm).toContainText("되돌릴 수 없어요");
      await expect(confirm.getByRole("button")).toHaveText(["취소", "철회하기"]);
      for (const button of await confirm.getByRole("button").all()) await expectTouchTarget(button);
      const box = (await confirm.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
      await expectNoHorizontalScroll(page);
      await shot(page, "health-withdraw-confirm");
      // 취소: 보내지 않고 동의 화면에 남는다
      await confirm.getByRole("button", { name: "취소" }).click();
      await expect(confirm).toHaveCount(0);
      await expect(modal(page)).toHaveAttribute("data-step", "consent");
      expect(consentPosts).toHaveLength(1);
      // 확인: 철회되고 건강 정보가 사라진다
      await modal(page).getByTestId("consent-submit").click();
      await page.getByTestId("confirm-dialog").getByRole("button", { name: "철회하기" }).click();
      await expect(modal(page)).toHaveAttribute("data-step", "profiles");
      await expect(page.getByTestId("confirm-dialog")).toHaveCount(0);
      expect(consentPosts).toHaveLength(2);
      expect(consentPosts[1]).toEqual({ channel: "settings", items: [{ doc_type: "sensitive_consent", version: 1, action: "withdraw" }] });
      await expect(modal(page).getByTestId("profile-item")).not.toContainText("임신 여부");
      await expect(modal(page).getByTestId("health-consent-notice")).toBeVisible();

      // ---- 로그아웃: 게스트로 돌아가고 모달이 닫힌다
      await modal(page).getByRole("button", { name: "로그아웃" }).click();
      await expect(modal(page)).toHaveCount(0);
      await expect(page.getByTestId("target-picker")).toHaveCount(0);
      await expect(page.getByTestId("login-entry")).toBeVisible();
    });

    test("이메일 없는 카카오계정으로 콜백이 돌아오면 로그인 화면에 고정 문구로 안내하고, 주소에서 표시를 지운다. 질문은 그대로 된다", async ({ page }) => {
      // Supabase가 콜백에 붙여 주는 오류 모양(값은 합성). 라우트가 짧은 표시(`auth_error`)로 줄여 첫 화면으로 돌려보낸다
      await page.goto("/auth/callback?error=server_error&error_code=unexpected_failure&error_description=Error+getting+user+email+from+external+provider");
      await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
      await expect(modal(page)).toHaveAttribute("data-step", "login");
      await expect(modal(page).getByTestId("account-error")).toHaveText("카카오계정에 이메일이 없거나 동의하지 않으면 로그인할 수 없어요. 다른 방법으로 로그인하거나 로그인 없이 쓰세요.");
      await expect.poll(() => page.url()).not.toContain("auth_error");
      expect(new URL(page.url()).pathname).toBe("/");
      await expectModalFits(page);
      await shot(page, "login-kakao-email-required");
      // 다른 방법이 열려 있다
      await expect(modal(page).getByTestId("social-google")).toBeEnabled();
      await modal(page).getByRole("button", { name: "로그인 없이 계속하기" }).click();
      await expect(modal(page)).toHaveCount(0);
      await ask(page, "합성 질문");
      await expect(page.getByTestId("result-card")).toBeVisible();
      // 새로고침해도 안내가 다시 뜨지 않는다
      await page.reload();
      await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
      await expect(modal(page)).toHaveCount(0);
    });

    test("그 밖의 콜백 실패(동의 취소 등)는 일반 안내다", async ({ page }) => {
      await page.goto("/auth/callback?error=access_denied&error_description=synthetic+denied");
      await expect(modal(page)).toHaveAttribute("data-step", "login");
      await expect(modal(page).getByTestId("account-error")).toHaveText("로그인을 마치지 못했어요. 다시 시도하거나 로그인 없이 쓰세요.");
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

    // 사양 변경(PRD-01-10 A): 이메일 로그인이 화면에서 빠져 목의 "이미 동의를 마친 사용자"(이메일로만 고를 수 있다)로는 들어갈 수 없다.
    // 대신 소셜 로그인(목)으로 동의·프로필을 마친 뒤 모달을 다시 열어, 동의를 마친 사용자는 프로필이 첫 화면이라 `<`가 없음을 본다
    // (목의 미리 만든 사용자로 바로 들어오는 경로는 스토어 단위 시험 `stores/account.test.ts`가 본다)
    await modal(page).getByTestId("social-google").click();
    await expect(modal(page)).toHaveAttribute("data-step", "consent");
    for (const docType of ["terms", "privacy_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
    await modal(page).getByTestId("consent-submit").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await modal(page).getByTestId("add-self").click();
    await modal(page).getByLabel("이름(별명)").fill("나");
    await modal(page).getByTestId("profile-save").click();
    await modal(page).getByTestId("add-family").click();
    await modal(page).getByLabel("이름(별명)").fill("첫째");
    await modal(page).getByTestId("profile-save").click();
    await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
    await closeButton(page).click();
    await expect(modal(page)).toHaveCount(0);
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    await page.getByTestId("menu-drawer").getByTestId("account-entry").click();
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
