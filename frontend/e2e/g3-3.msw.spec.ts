import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, expectNoHorizontalScroll, input, openApp, pickTarget, pickChoice, completeRequired, fillName } from "./helpers";

// GROUP-03 3단계(FE-11-09 C·FE-11-12 A, 2026-11-22) 성별 숨김 e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0):
// - 대상 프로필의 성별이 **남성일 때만** 입력창 안 "일반인 | 임산부" 토글이 숨고 `/chat` `context.pregnant`는 false다
// - 여성·성별 미입력·게스트·게스트로 이용(FE-17 U-06, 예전 선택 안 함)은 토글이 보인다. 로그인 직후 기본 대상은 본인이다(FE-17 U-06). 가족 프로필을 고르면 그 프로필의 성별을 따른다
// - 토글이 빠져도 입력창 틀의 높이는 같다(레이아웃 흔들림 없음). 가로 스크롤 없음
// 기존 `g1-5a.msw.spec.ts`(토글 저장 연동)·`sex-age14.msw.spec.ts`(성별 입력)는 건드리지 않고 여기에 따로 둔다.
// 캡처: `L4_SHOT_DIR`을 주면 그 폴더에 `l4-b-*.png`를 남긴다. 주지 않으면 로컬 전용 `data/mock/fe-issue-shots`를 저장소 루트에서 찾고 없으면 찍지 않는다.
const SHOT_DIR = process.env.L4_SHOT_DIR ?? [path.resolve(__dirname, "../../data/mock/fe-issue-shots"), path.resolve(__dirname, "../../../P2-Medi/data/mock/fe-issue-shots")].find((dir) => existsSync(dir));

const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  const scheme = await page.locator("html").getAttribute("data-theme");
  await page.screenshot({ path: path.join(SHOT_DIR, `l4-b-${name}-${scheme}-${page.viewportSize()!.width}.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const toggle = (page: Page) => page.getByRole("radiogroup", { name: "임신 여부" });
const radio = (page: Page, name: "일반인" | "임산부") => toggle(page).getByRole("radio", { name });
/** 대상 고르기의 한 칸(라디오 입력은 sr-only라 글자(label)를 누른다, g1-5a와 같은 방식) */
/** 입력창 틀(토글·textarea·버튼을 감싸는 form) */
const inputForm = (page: Page) => input(page).locator("xpath=ancestor::form[1]");

function watch(page: Page) {
  const chats: { question: string; context: { pregnant: boolean | null } }[] = [];
  const patches: { path: string; body: unknown }[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && pathname.endsWith("/api/chat")) chats.push(request.postDataJSON());
    if (request.method() === "PATCH") patches.push({ path: pathname, body: request.postDataJSON() });
  });
  return { chats, patches };
}

/** 카카오 로그인(목) → 건강 정보까지 동의 → 본인(남성) + 첫째(여성, 임신 예) 저장 → 모달 닫기 */
async function loginWithMaleSelfAndFemaleChild(page: Page) {
  await page.getByTestId("login-entry").click();
  await modal(page).getByTestId("social-kakao").click();
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await modal(page).getByTestId("add-self").click();
  await fillName(modal(page), "나");
  await pickChoice(modal(page), "성별", "남성");
  await completeRequired(modal(page));
  await modal(page).getByTestId("profile-save").click();
  await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
  await modal(page).getByTestId("add-family").click();
  await modal(page).getByLabel("이름(별명)").fill("첫째");
  await pickChoice(modal(page), "연령대", "만 19~64세");
  await pickChoice(modal(page), "성별", "여성");
  await modal(page).getByRole("radio", { name: "예" }).check(); // 임신 여부 예(건강 정보 동의 있음)
  await completeRequired(modal(page));
  await modal(page).getByTestId("profile-save").click();
  await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
  await modal(page).getByRole("button", { name: "닫기" }).click();
  await expect(modal(page)).toHaveCount(0);
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`GROUP-03 3단계 성별 숨김 ${scheme} ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("남성 대상만 토글 숨김·pregnant=false, 여성·게스트로 이용·게스트는 보임, 입력창 높이는 그대로", async ({ page }) => {
        const { chats, patches } = watch(page);
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);

        // ---- 게스트: 토글이 보이고 기본 일반인
        await expect(toggle(page)).toBeVisible();
        await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true");
        const guestFormBox = (await inputForm(page).boundingBox())!;

        await loginWithMaleSelfAndFemaleChild(page);
        await expect(page.getByTestId("target-chip")).toBeVisible();
        await expect(toggle(page)).toHaveCount(0); // 로그인 직후 기본 대상은 본인(남성): 숨김(FE-17 U-06)
        await pickTarget(page, "게스트로 이용");
        await expect(toggle(page)).toBeVisible(); // 게스트로 이용: 보인다
        // 로그인 + 프로필이면 입력창 아래 줄이 "사진 → 토글 · 프로필 칩"(FE-17 U-07 좌하단), 게스트도 같은 두 줄 배치다(FE-17 U-09, 칩만 없다). 토글이 빠져도 높이가 그대로인지는 이 틀을 기준으로 본다
        const memberFormBox = (await inputForm(page).boundingBox())!;
        expect(Math.abs(memberFormBox.height - guestFormBox.height)).toBeLessThanOrEqual(1); // 게스트와 같은 높이(같은 배치)

        // ---- 남성(나): 토글이 없다. 입력창 틀 높이는 게스트 때와 같다(흔들림 없음)
        await pickTarget(page, "나");
        await expect(toggle(page)).toHaveCount(0);
        await expect(page.getByTestId("pregnancy-hint")).toHaveCount(0);
        const maleFormBox = (await inputForm(page).boundingBox())!;
        expect(Math.abs(maleFormBox.height - memberFormBox.height)).toBeLessThanOrEqual(1);
        await expectNoHorizontalScroll(page);
        await shot(page, "male-hidden");
        await ask(page, "합성 질문 가나다정 먹어도 돼요");
        await expect(page.getByTestId("result-card")).toHaveCount(1);
        expect(chats).toHaveLength(1);
        expect(chats[0].context.pregnant).toBe(false);
        expect(JSON.stringify(chats[0])).not.toMatch(/sex|gender|male/);
        expect(patches).toEqual([]);
        await expect(toggle(page)).toHaveCount(0); // 답을 받은 뒤에도 그대로 숨김

        // ---- 여성(첫째): 토글이 보이고 저장된 임신 값(예)으로 시작한다(§7.1 규칙 ①·②)
        await pickTarget(page, "첫째");
        await expect(toggle(page)).toBeVisible();
        await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "true");
        const femaleFormBox = (await inputForm(page).boundingBox())!;
        expect(Math.abs(femaleFormBox.height - memberFormBox.height)).toBeLessThanOrEqual(1);
        await expectNoHorizontalScroll(page);
        await shot(page, "female-shown");
        // 기대값 갱신(2026-11-24, FE-17 U-21 추가 "프로필을 변경하면 … 새글이 열리도록"): 대상을 바꾸면 새 대화라 이전 결과는 없고 이번 결과 1개다
        await expect(page.getByTestId("home")).toBeVisible();
        await ask(page, "합성 질문 가나다정 먹어도 돼요");
        await expect(page.getByTestId("result-card")).toHaveCount(1);
        expect(chats[1].context.pregnant).toBe(true);

        // ---- 다시 남성(나): 숨김·false. 여성 쪽에서 임산부였어도 남성 대상에는 싣지 않는다
        await pickTarget(page, "나");
        await expect(toggle(page)).toHaveCount(0);
        await expect(page.getByTestId("home")).toBeVisible(); // 새 대화(U-21 추가)
        await ask(page, "합성 질문 가나다정 먹어도 돼요");
        await expect(page.getByTestId("result-card")).toHaveCount(1);
        expect(chats[2].context.pregnant).toBe(false);

        // ---- 게스트로 이용: 다시 보이고 일반인
        await pickTarget(page, "게스트로 이용");
        await expect(toggle(page)).toBeVisible();
        await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true");
        expect(patches).toEqual([]); // 대상 변경만으로는 저장하지 않는다
      });
    });
  }
}
