import path from "node:path";
import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expect119Reachable, expectNoHorizontalScroll, expectTouchTarget, openApp } from "./helpers";

// FE-04-27 A(2026-11-22 사용자 승인) e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0, 실제 사진 0):
// 온보딩·프로필 폼의 "복용 중인 약(선택)" 아래 `사진으로 등록` → 기존 사진 모달(프로필 목적지: 질문칸 없음) → 확인 카드 → `이대로 확인`
// → 고른 후보는 확인된 약, 글자만 있는 약은 확인 안 된 약으로 **지금 편집 중인 프로필**의 목록에 들어간다. /chat 0회, 사진·이미지는 저장 요청에 없다.
// 취소(`닫기`·Esc)는 목록을 바꾸지 않고 폼 입력을 지킨다. 온보딩(로그인 복귀 `?mock_session=new&auth_resume=1`) 길에서도 같다.
// 캡처: `L8_SHOT_DIR`을 주면 `l8-photo-register-*.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.L8_SHOT_DIR;
const PHOTO_LABEL = "사진으로 등록";
const P1 = "환자 이름·병원·약국은 가리고 찍어도 돼요. 사진은 저장하지 않아요.";
const P2 = "올린 사진은 약 이름을 읽기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 사진을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
/** 사진 목이 `ok` 시나리오를 고르는 PNG 가로 픽셀 수(`src/mocks/photo-handlers.ts`의 `PHOTO_SCENARIO_PNG_WIDTH.ok`. 단위 시험이 그 표를 검사한다) */
const OK_PNG_WIDTH = 64;

const shot = async (page: Page, name: string, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l8-photo-register-${name}-${page.viewportSize()!.width}-${scheme}.png`) });
};

// ---------------------------------------------------------------- 합성 PNG(노란 단색, 8비트 RGB). `photo.msw.spec.ts`의 `makePng`와 같은 규칙
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    let c = (crc ^ byte) & 0xff;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}
function makePng(width: number, height: number): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const stride = 1 + width * 3;
  const raw = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * stride] = 0;
    for (let x = 0; x < width; x += 1) raw.set([0xff, 0xcc, 0x00], y * stride + 1 + x * 3);
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

// ---------------------------------------------------------------- 도구
const modal = (page: Page) => page.getByTestId("account-modal");
const photoModal = (page: Page) => page.getByTestId("photo-modal");
const card = (page: Page) => photoModal(page).getByTestId("photo-confirm-card");
const photoButton = (page: Page) => modal(page).getByTestId("medication-photo");
const chips = (page: Page) => modal(page).getByTestId("medication");

/** 요청 기록: 프로필 저장 본문(원문 글자 포함)·/chat 횟수·/ingest 횟수 */
function watch(page: Page) {
  const log = { chat: 0, ingest: 0, saves: [] as { medications?: { input_text: string; item_seq?: string | null }[] }[], raw: [] as string[] };
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/api/chat")) log.chat += 1;
    if (pathname.endsWith("/api/ingest/image")) log.ingest += 1;
    if (/\/api\/profiles(\/|$)/.test(pathname) && request.method() !== "GET") {
      log.raw.push(request.postData() ?? "");
      if (request.method() === "POST") log.saves.push(request.postDataJSON());
    }
  });
  return log;
}

/** 동의(건강 정보 포함) → 본인 프로필 추가 폼 */
async function consentToSelfForm(page: Page) {
  await expect(modal(page)).toHaveAttribute("data-step", "consent");
  for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
  await modal(page).getByTestId("consent-submit").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
  await modal(page).getByTestId("add-self").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
  await modal(page).getByLabel("이름(별명)").fill("나");
}
/** 카카오 로그인(목) → 동의 → 본인 프로필 폼(프로필 관리 길) */
async function openSelfForm(page: Page) {
  await openApp(page);
  await page.getByTestId("login-entry").click();
  await modal(page).getByTestId("social-kakao").click();
  await consentToSelfForm(page);
}
/** `사진으로 등록` → 합성 PNG(ok) → 확인 카드 */
async function openCard(page: Page) {
  await photoButton(page).click();
  await expect(photoModal(page)).toBeVisible();
  await expect(photoModal(page)).toHaveCSS("pointer-events", "auto");
  await photoModal(page)
    .getByTestId("photo-file")
    .setInputFiles({ name: "pouch.png", mimeType: "image/png", buffer: makePng(OK_PNG_WIDTH, 48) });
  await expect(card(page)).toBeVisible();
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`복용 약 사진으로 등록 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("프로필 편집: `사진으로 등록` → 사진 모달(프로필 목적지, 고지 그대로, 119) → 확인 카드(질문칸 없음) → 고른 약은 확인된 약·글자만은 확인 안 된 약 → 저장 본문에 이름만", async ({ page }) => {
        const log = watch(page);
        await openSelfForm(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        const button = photoButton(page);
        await expect(button).toHaveText(PHOTO_LABEL);
        await expect(button).toBeEnabled();
        await expectTouchTarget(button, { widthToo: false });
        // 약 입력 아래, 고지 위
        const [inputBox, buttonBox, noticeBox] = await Promise.all([
          modal(page).getByRole("combobox", { name: "복용 중인 약(선택)" }).boundingBox(),
          button.boundingBox(),
          modal(page).getByTestId("drug-data-scope-notice").boundingBox(),
        ]);
        expect(inputBox!.y + inputBox!.height).toBeLessThanOrEqual(buttonBox!.y + 1);
        expect(buttonBox!.y + buttonBox!.height).toBeLessThanOrEqual(noticeBox!.y + 1);
        await shot(page, "entry", scheme);

        await button.click();
        const box = photoModal(page);
        await expect(box).toBeVisible();
        await expect(box).toHaveAttribute("data-destination", "profile");
        await expect(box).toHaveAttribute("data-step", "pick");
        await expect(box.getByTestId("photo-privacy-notice")).toHaveText(P1);
        await expect(box.getByTestId("photo-external-ai-notice")).toHaveText(P2);
        await expect(modal(page)).toBeVisible(); // 계정 모달은 아래에 그대로
        await expect(box).toHaveCSS("pointer-events", "auto");
        await expect119Reachable(page, box.getByTestId("layer-emergency-entry"));
        await expectNoHorizontalScroll(page);
        await shot(page, "pick", scheme);

        await box.getByTestId("photo-file").setInputFiles({ name: "pouch.png", mimeType: "image/png", buffer: makePng(OK_PNG_WIDTH, 48) });
        await expect(card(page)).toBeVisible();
        await expect(card(page)).toHaveAttribute("data-destination", "profile");
        await expect(card(page).getByTestId("photo-question")).toHaveCount(0);
        await expect(card(page).getByTestId("photo-row")).toHaveCount(2);
        const radios = card(page).getByRole("radio");
        for (let index = 0; index < 2; index += 1) await expect(radios.nth(index)).toHaveAttribute("aria-checked", "false");
        await expect(card(page).getByTestId("photo-confirm")).toBeEnabled(); // 읽은 줄이 있으면 질문 없이 켜진다
        await radios.nth(0).click();
        await expectNoHorizontalScroll(page);
        await shot(page, "card", scheme);
        expect(log.chat).toBe(0);

        await card(page).getByTestId("photo-confirm").click();
        await expect(photoModal(page)).toHaveCount(0);
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await expect(chips(page)).toHaveCount(2);
        await expect(chips(page).nth(0).getByTestId("medication-name")).toHaveText("가나다정 100밀리그램");
        await expect(chips(page).nth(0)).toHaveAttribute("data-confirmed", "true");
        await expect(chips(page).nth(1).getByTestId("medication-name")).toHaveText("라마바캡슐");
        await expect(chips(page).nth(1)).toHaveAttribute("data-confirmed", "false");
        await expect(chips(page).nth(1).getByTestId("medication-unconfirmed")).toHaveText("확인 안 된 약");
        await expect(modal(page).getByTestId("medication-unconfirmed-note")).toBeVisible();
        await expect(button).toBeFocused(); // 닫힌 뒤 초점은 버튼으로
        await expect(modal(page).getByLabel("이름(별명)")).toHaveValue("나");
        await expectNoHorizontalScroll(page);
        await shot(page, "added", scheme);
        expect(log.saves).toHaveLength(0); // 아직 저장하지 않았다

        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        expect(log.saves).toHaveLength(1);
        expect(log.saves[0].medications).toEqual([
          { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
          { input_text: "라마바캡슐", item_seq: null },
        ]);
        for (const body of log.raw) expect(body).not.toMatch(/data:image|base64|가나다성분|100mg|image/);
        expect(log).toMatchObject({ chat: 0, ingest: 1 });
      });
    });
  }
}

test.describe("취소·온보딩·가족 프로필 (393px)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("`닫기`·Esc는 목록을 바꾸지 않고 폼 입력(이름·이미 넣은 약)을 지킨다. Esc 한 번에 사진 모달만 닫힌다. /chat 0회", async ({ page }) => {
    const log = watch(page);
    await openSelfForm(page);
    const input = modal(page).getByRole("combobox", { name: "복용 중인 약(선택)" });
    await input.fill("없는약");
    await expect(modal(page).getByTestId("medication-no-candidates")).toBeVisible();
    await modal(page).getByTestId("medication-add").click();
    await expect(chips(page)).toHaveCount(1);
    // 닫기
    await openCard(page);
    await card(page).getByRole("radio").nth(0).click();
    await photoModal(page).getByTestId("photo-close").click();
    await expect(photoModal(page)).toHaveCount(0);
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
    await expect(chips(page)).toHaveCount(1);
    await expect(modal(page).getByLabel("이름(별명)")).toHaveValue("나");
    await expect(photoButton(page)).toBeFocused();
    // Esc
    await openCard(page);
    await page.keyboard.press("Escape");
    await expect(photoModal(page)).toHaveCount(0);
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form"); // 계정 모달은 남는다
    await expect(chips(page)).toHaveCount(1);
    // 다시 열면 처음부터(읽은 목록은 메모리에서 사라졌다)
    await photoButton(page).click();
    await expect(photoModal(page)).toHaveAttribute("data-step", "pick");
    await page.keyboard.press("Escape");
    await expect(photoModal(page)).toHaveCount(0);
    expect(log).toMatchObject({ chat: 0, saves: [] });
  });

  test("온보딩(소셜 로그인 복귀 → 동의 → 본인 프로필)에서도 같은 버튼으로 등록되고, 가족 프로필 폼은 비어서 시작해 그 프로필에만 저장된다", async ({ page }) => {
    const log = watch(page);
    await page.goto("/?mock_session=new&auth_resume=1");
    await consentToSelfForm(page);
    await openCard(page);
    await card(page).getByRole("radio").nth(0).click();
    await card(page).getByTestId("photo-confirm").click();
    await expect(photoModal(page)).toHaveCount(0);
    await expect(chips(page)).toHaveCount(2);
    await modal(page).getByTestId("profile-save").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await expect(modal(page).getByTestId("profile-item")).toHaveCount(1);
    await expect(modal(page).getByTestId("profile-item").first()).toContainText("약 2개");
    // 가족 프로필: 독립
    await modal(page).getByTestId("add-family").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
    await expect(chips(page)).toHaveCount(0);
    await modal(page).getByLabel("이름(별명)").fill("첫째");
    await openCard(page);
    await card(page).getByRole("radio").nth(1).click(); // 500밀리그램
    await card(page).getByTestId("photo-row-remove").nth(1).click(); // 라마바캡슐 줄은 지운다
    await card(page).getByTestId("photo-confirm").click();
    await expect(photoModal(page)).toHaveCount(0);
    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).nth(0).getByTestId("medication-name")).toHaveText("가나다정 500밀리그램");
    await modal(page).getByTestId("profile-save").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profiles");
    await expect(modal(page).getByTestId("profile-item")).toHaveCount(2);
    expect(log.saves.map((save) => save.medications)).toEqual([
      [
        { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
        { input_text: "라마바캡슐", item_seq: null },
      ],
      [{ input_text: "가나다정 500밀리그램", item_seq: "200000002" }],
    ]);
    expect(log.chat).toBe(0);
  });

  test("건강 정보 동의가 없으면 버튼이 비활성이다(묶음이 막힌다)", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("login-entry").click();
    await modal(page).getByTestId("social-kakao").click();
    await expect(modal(page)).toHaveAttribute("data-step", "consent");
    for (const docType of ["terms", "privacy_consent", "age_14"]) await modal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
    await modal(page).getByTestId("consent-submit").click();
    await modal(page).getByTestId("add-self").click();
    await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
    await expect(photoButton(page)).toBeDisabled();
    await expect(modal(page).getByTestId("health-consent-notice")).toBeVisible();
  });
});
