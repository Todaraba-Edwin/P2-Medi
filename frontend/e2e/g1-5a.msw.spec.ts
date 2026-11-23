import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, expectNoHorizontalScroll, openAccountEntry, openApp, pickTarget } from "./helpers";

// GROUP-01 5a(FE-11, 2026-11-20) 로그인 흐름 e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0):
// - FE-11-13: 건강 정보 동의 + 대상 프로필이면 토글 변경이 그 프로필 `pregnancy_status`를 PATCH(양방향)하고 프로필 화면에 바뀐 값이 보인다.
//   온보딩에서 임신으로 체크한 프로필을 고르면 토글이 '임산부'로 시작한다
// - FE-11-14 A: 건강 정보 동의가 없으면 PATCH 없이 이 대화에만 적용하고 토글 근처 안내 한 줄
// 캡처: `G15A_SHOT_DIR`을 주면 그 폴더에 `*-g1-5a.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`)
const SHOT_DIR = process.env.G15A_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-g1-5a.png`) });
};

const SAVE_HINT = "프로필에 저장하려면 건강 정보 동의가 필요해요";
const modal = (page: Page) => page.getByTestId("account-modal");
const toggle = (page: Page) => page.getByRole("radiogroup", { name: "임신 여부" });
const radio = (page: Page, name: "일반인" | "임산부") => toggle(page).getByRole("radio", { name });
/** 대상 고르기의 한 칸(라디오 입력은 sr-only라 글자(label)를 누른다, account.msw.spec과 같은 방식) */

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

/** 카카오 로그인(목) → 동의(건강 정보 동의는 선택) → 본인 프로필 저장(임신 여부는 건강 동의가 있을 때만 고른다) → 모달 닫기 */
async function loginAndSaveSelf(page: Page, { healthConsent, pregnancy }: { healthConsent: boolean; pregnancy?: "예" | "아니오" }) {
  await openApp(page);
  await page.getByTestId("login-entry").click();
  await modal(page).getByTestId("social-kakao").click();
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  const agree = (docType: string) => modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox");
  for (const docType of ["terms", "privacy_consent", ...(healthConsent ? ["sensitive_consent"] : [])]) await agree(docType).check();
  // 만 14세 이상 확인(`age_14`, GROUP-03 F1·PRD-17-12 A)은 병합 뒤 필수 체크가 하나 더 있다: 있으면 같이 체크한다(이 가지에는 아직 없다)
  if ((await agree("age_14").count()) > 0) await agree("age_14").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await modal(page).getByTestId("add-self").click();
  await modal(page).getByLabel("이름(별명)").fill("나");
  if (pregnancy) {
    await modal(page).getByLabel("성별").selectOption("female"); // 임신 여부 칸은 여성일 때만 보인다(작업 B, 2026-11-22)
    await modal(page).getByRole("radio", { name: pregnancy }).check();
  }
  await modal(page).getByTestId("profile-save").click();
  await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
  await modal(page).getByRole("button", { name: "닫기" }).click();
  await expect(modal(page)).toHaveCount(0);
}

/** 프로필 화면(계정 모달)을 연다: 계정 메뉴(넓은 폭은 사이드바, 좁은 폭은 ☰ 드로어 안)의 `프로필 관리` */
async function openProfiles(page: Page) {
  await openAccountEntry(page);
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
}

for (const width of [393, 1280]) {
  test.describe(`임신 여부 토글 ↔ 프로필 연동 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("건강 정보 동의 + 대상 프로필: 토글 변경이 pregnancy_status를 PATCH(양방향)하고 프로필 화면에 보인다. 임신 중 프로필을 고르면 임산부로 시작", async ({ page }) => {
      const { chats, patches } = watch(page);
      await loginAndSaveSelf(page, { healthConsent: true, pregnancy: "아니오" });
      await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true"); // 대상을 고르기 전
      await pickTarget(page, "나");
      await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true"); // 프로필 "아니오"
      await radio(page, "임산부").click();
      await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "true");
      await expect.poll(() => patches.length).toBe(1);
      expect(patches[0].body).toEqual({ pregnancy_status: "pregnant" });
      expect(patches[0].path).toMatch(/\/api\/profiles\/[0-9a-f-]+$/);
      await expect(page.getByTestId("pregnancy-hint")).toHaveCount(0);
      await expect(page.getByTestId("pregnancy-save-error")).toHaveCount(0);
      await ask(page, "합성 질문");
      await expect(page.getByTestId("result-card")).toBeVisible();
      expect(chats[0].context).toMatchObject({ pregnant: true });
      await expect(page.getByTestId("pregnancy-pick-hint")).toHaveCount(0);
      await shot(page, "profile-sync-chat");
      // 프로필 화면에서 바뀐 값이 보인다
      await openProfiles(page);
      await expect(modal(page).getByTestId("profile-item")).toContainText("임신 여부 예");
      await shot(page, "profile-sync-profiles");
      await modal(page).getByRole("button", { name: "닫기" }).click();
      // 양방향: 일반인으로 돌리면 not_pregnant
      await radio(page, "일반인").click();
      await expect.poll(() => patches.length).toBe(2);
      expect(patches[1].body).toEqual({ pregnancy_status: "not_pregnant" });
      await openProfiles(page);
      await expect(modal(page).getByTestId("profile-item")).toContainText("임신 여부 아니오");
      await modal(page).getByRole("button", { name: "닫기" }).click();
      // 다시 임산부로 저장해 두고 대상을 바꿨다 돌아오면 임산부로 시작한다(§7.1 규칙 ①·②). 대상 변경은 저장하지 않는다
      await radio(page, "임산부").click();
      await expect.poll(() => patches.length).toBe(3);
      await pickTarget(page, "선택 안 함");
      await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true");
      await pickTarget(page, "나");
      await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "true");
      expect(patches).toHaveLength(3);
      // 병아리는 입력창 프로필 칩의 아바타(보조 자리, FE-17 U-01)에만 있고 그 밖(토글·고지·결과)에는 없다
      await expect(page.locator('[data-testid="mascot"]:not([data-testid="profile-avatar"] *)')).toHaveCount(0);
      await expect(page.getByTestId("dock").getByTestId("input-combined-notice").getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("건강 정보 동의가 없으면 PATCH 없이 이 대화에만 적용하고 토글 근처 안내 한 줄이 보인다. 프로필에는 임신 여부가 남지 않는다", async ({ page }) => {
      const { chats, patches } = watch(page);
      await loginAndSaveSelf(page, { healthConsent: false });
      await pickTarget(page, "나");
      await radio(page, "임산부").click();
      await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "true");
      const hint = page.getByTestId("pregnancy-hint");
      await expect(hint).toHaveText(SAVE_HINT);
      await expect(hint).toBeVisible();
      await ask(page, "합성 질문");
      await expect(page.getByTestId("result-card")).toBeVisible();
      expect(chats[0].context).toMatchObject({ pregnant: true });
      expect(patches).toEqual([]);
      await shot(page, "no-consent-hint");
      await openProfiles(page);
      await expect(modal(page).getByTestId("profile-item")).not.toContainText("임신 여부");
      await expectNoHorizontalScroll(page);
    });
  });
}
