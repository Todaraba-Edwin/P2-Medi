import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, openAccountEntry, openApp, completeRequired } from "./helpers";

// FE-04-15 A(2026-11-19)·FE-04-26 A(2026-11-22, 문구 1안 승인) e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0):
// 프로필 저장이 끝나면 목록 화면 맨 위(설명 아래)에 완료 안내 한 줄(`role="status"`) + `질문하러 가기`. 버튼은 모달을 닫고 질문 입력창에 초점을 둔다.
// 저장 실패(422)는 폼에 남아 오류만 보이고 안내는 없다. 안내 글자 대비는 라이트·다크 AA 이상.
// 캡처: `L8_SHOT_DIR`을 주면 `l8-save-notice-*.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.L8_SHOT_DIR;
/** 승인 원문(2026-11-22, `frontend/src/features/account/copy.ts` `PROFILE_SAVED_NOTICE`). 바꾸면 이 글자도 같이 바꾼다 */
const NOTICE_DRAFT ="프로필을 저장했어요. 질문할 때 누가 먹는지 고를 수 있어요.";
const GO_ASK = "질문하러 가기";

const shot = async (page: Page, name: string, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l8-save-notice-${name}-${page.viewportSize()!.width}-${scheme}.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");
const notice = (page: Page) => modal(page).getByTestId("profile-saved-notice");

/** 카카오 로그인(목) → 필수 동의 → 본인 프로필 폼 */
async function openSelfForm(page: Page) {
  await openApp(page);
  await page.getByTestId("login-entry").click();
  await modal(page).getByTestId("social-kakao").click();
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await expect(notice(page)).toHaveCount(0); // 처음 목록에는 없다
  await modal(page).getByTestId("add-self").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
  await modal(page).getByLabel("이름(별명)").fill("나");
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`프로필 저장 완료 안내 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("저장 뒤 목록 맨 위에 안내(role=status, 초안)와 `질문하러 가기`(44px, 대비 AA). 버튼은 모달을 닫고 입력창에 초점. 다시 열면 없다", async ({ page }) => {
        await openSelfForm(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await completeRequired(modal(page));
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        const box = notice(page);
        await expect(box).toBeVisible();
        await expect(box).toHaveAttribute("role", "status");
        await expect(box).toContainText(NOTICE_DRAFT);
        const goAsk = box.getByRole("button", { name: GO_ASK });
        await expect(goAsk).toBeVisible();
        await expectTouchTarget(goAsk, { widthToo: false });
        // 제목 → 설명 → 안내 → 프로필 목록 순서. 초점은 제목
        const [descBox, noticeBox, itemBox] = await Promise.all([modal(page).getByText("본인과 가족 3명까지 저장할 수 있어요", { exact: false }).boundingBox(), box.boundingBox(), modal(page).getByTestId("profile-item").first().boundingBox()]);
        expect(descBox!.y + descBox!.height).toBeLessThanOrEqual(noticeBox!.y + 1);
        expect(noticeBox!.y + noticeBox!.height).toBeLessThanOrEqual(itemBox!.y + 1);
        await expect(modal(page).getByRole("heading", { name: "프로필" })).toBeFocused();
        await expect(box.locator("img, svg")).toHaveCount(0); // 마스코트 없음
        await expect(modal(page).getByTestId("account-error")).toHaveCount(0);
        // 대비(안내 글자·버튼 글자)
        const report = await measureContrast(page, '[data-testid="profile-saved-notice"]');
        expect(report.samples.length, `${scheme} ${width}: 안내 글자를 재지 못함`).toBeGreaterThan(0);
        expect(report.unmeasured, `${scheme} ${width}: 바탕색을 정할 수 없는 글자`).toEqual([]);
        for (const sample of report.samples) expect(sample.ratio, `${scheme} ${width}: ${sample.text} ${sample.ratio} (${sample.fg} on ${sample.bg})`).toBeGreaterThanOrEqual(AA_NORMAL);
        expect(failures(report)).toEqual([]);
        await expectNoHorizontalScroll(page);
        await shot(page, "shown", scheme);

        await goAsk.click();
        await expect(modal(page)).toHaveCount(0);
        await expect(page.locator("textarea")).toBeFocused();
        await shot(page, "closed", scheme);
        // 다시 열면(계정 메뉴의 프로필 관리: 넓은 폭은 사이드바, 좁은 폭은 ☰ 드로어) 안내는 없다
        await openAccountEntry(page);
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        await expect(notice(page)).toHaveCount(0);
      });
    });
  }
}

test.describe("저장 실패·수정 (393px)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("저장이 막히면(이름 비움: 필수 칸이라 저장 버튼 비활성, FE-17 U-07) 폼에 남고 완료 안내는 없다. 수정 저장 뒤에도 안내가 보이고, 취소로 돌아오면 없다", async ({ page }) => {
    await openSelfForm(page);
    // 서버 422 실패 길은 단위 시험(`account.test.tsx` 저장 완료 안내 절)이 본다. 여기서는 목이 거절할 본문을 화면에서 만들 수 없어 화면 검증 실패 길을 본다
    await modal(page).getByLabel("이름(별명)").fill("");
    await completeRequired(modal(page));
    await expect(modal(page).getByTestId("profile-save")).toBeDisabled();
    await modal(page).getByTestId("profile-save").click({ force: true });
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
    await expect(modal(page).getByTestId("profile-required-hint")).toHaveText("관계·이름·연령대·성별을 모두 고르면 저장할 수 있어요.");
    await expect(notice(page)).toHaveCount(0);
    // 저장 성공 → 안내. 수정 저장 뒤에도 안내
    await modal(page).getByLabel("이름(별명)").fill("나");
    await completeRequired(modal(page));
    await modal(page).getByTestId("profile-save").click();
    await expect(notice(page)).toBeVisible();
    await modal(page).getByRole("button", { name: "나 수정" }).click();
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
    await modal(page).getByLabel("이름(별명)").fill("나나");
    await completeRequired(modal(page));
    await modal(page).getByTestId("profile-save").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await expect(notice(page)).toBeVisible();
    await expect(modal(page).getByTestId("profile-item").first()).toContainText("나나");
    // 취소로 돌아오면 안내는 없다
    await modal(page).getByRole("button", { name: "나나 수정" }).click();
    await modal(page).getByRole("button", { name: "취소" }).click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await expect(notice(page)).toHaveCount(0);
  });
});
