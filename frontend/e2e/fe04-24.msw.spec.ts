import { existsSync } from "node:fs";
import path from "node:path";
import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, openApp, completeRequired } from "./helpers";

// FE-04-24 A·FE-04-25 A(2026-11-22 사용자 답) e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0):
// - FE-04-24 A 프로필 약 입력: 검색 중(디바운스 대기·요청 중)에는 `그대로 추가`가 비활성, 후보가 있으면 Enter는 첫 후보로 활성만(저장 없음),
//   버튼 글자 "그대로 추가"를 누르면 확인 안 된 약(`item_seq` null)으로 저장, 후보를 고르면 `item_seq`가 붙는다
// - FE-04-25 A 자료 밖 약 고지 한 줄(승인 원문)이 프로필 복용 약 입력과 사진 확인 카드 두 곳에 같은 글자로 보이고, 라이트·다크 대비가 AA 이상이다
// 기존 `fedrug.msw.spec.ts`(후보 고르기 전반)·`photo.msw.spec.ts`(사진 흐름, 다른 작업자 수정 중)는 건드리지 않고 여기에 따로 둔다.
// 캡처: `FE0424_SHOT_DIR`을 주면 그 폴더에 `fe04-24-*.png`를 남긴다. 주지 않으면 로컬 전용 `data/mock/fe-issue-shots`를 저장소 루트에서 찾고 없으면 찍지 않는다.
const SHOT_DIR = process.env.FE0424_SHOT_DIR ?? [path.resolve(__dirname, "../../data/mock/fe-issue-shots"), path.resolve(__dirname, "../../../P2-Medi/data/mock/fe-issue-shots")].find((dir) => existsSync(dir));
const NOTICE = "국내 허가 의약품 자료만 확인할 수 있어요. 조제약·해외 약 등 자료에 없는 약은 금기를 확인하지 못하니, 이름을 그대로 적고 약사에게 확인하세요.";
const ADD_LABEL = "그대로 추가";
const SEARCHING = "후보를 찾는 중이에요.";
const QUESTION = "같이 먹어도 돼요?";
/** 사진 목이 `ok` 시나리오를 고르는 PNG 가로 픽셀 수(`src/mocks/photo-handlers.ts`의 `PHOTO_SCENARIO_PNG_WIDTH.ok`와 같은 값. 단위 시험이 그 표를 검사한다) */
const OK_PNG_WIDTH = 64;

const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  const scheme = await page.locator("html").getAttribute("data-theme");
  await page.screenshot({ path: path.join(SHOT_DIR, `fe04-24-${name}-${scheme}-${page.viewportSize()!.width}.png`) });
};

// ---------------------------------------------------------------- 합성 PNG(노란 단색, 8비트 RGB). `photo.msw.spec.ts`의 `makePng`와 같은 규칙(그 파일은 수정 금지라 옮겨 적었다)
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
const medicationInput = (page: Page) => modal(page).getByRole("combobox", { name: "복용 중인 약(선택)" });
const addButton = (page: Page) => modal(page).getByTestId("medication-add");
const candidates = (page: Page) => modal(page).getByTestId("medication-candidate");
const chips = (page: Page) => modal(page).getByTestId("medication");
const photoModal = (page: Page) => page.getByTestId("photo-modal");

/** 프로필 저장 본문을 모은다 */
function watchSaves(page: Page) {
  const saves: { medications?: { input_text: string; item_seq?: string | null }[] }[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/profiles")) saves.push(request.postDataJSON());
  });
  return saves;
}

/** 카카오 로그인(목) → 건강 정보까지 동의 → 본인 프로필 폼(`fedrug.msw.spec.ts`와 같은 길) */
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
  await modal(page).getByLabel("이름(별명)").fill("나");
}

/** 사진 입구 → 합성 PNG(ok) → 확인 카드 */
async function openPhotoCard(page: Page) {
  await openApp(page);
  await page.getByTestId("photo-entry").click();
  await expect(photoModal(page)).toBeVisible();
  await photoModal(page)
    .getByTestId("photo-file")
    .setInputFiles({ name: "pouch.png", mimeType: "image/png", buffer: makePng(OK_PNG_WIDTH, 48) });
  await expect(photoModal(page).getByTestId("photo-confirm-card")).toBeVisible();
}

async function expectNoticeContrast(page: Page, rootSelector: string, label: string) {
  const report = await measureContrast(page, rootSelector);
  const notice = report.samples.filter((sample) => sample.testId === "drug-data-scope-notice");
  expect(notice.length, `${label}: 고지 글자를 재지 못함`).toBeGreaterThan(0);
  for (const sample of notice) expect(sample.ratio, `${label}: 고지 대비 ${sample.ratio} (${sample.fg} on ${sample.bg})`).toBeGreaterThanOrEqual(AA_NORMAL);
  expect(failures(report).filter((sample) => sample.testId === "drug-data-scope-notice"), `${label}: 기준 미달`).toEqual([]);
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-04-24·25 ${scheme} ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("프로필 약 입력: 검색 중 저장 막힘, 후보가 있으면 Enter는 첫 후보로 이동만, `그대로 추가`는 확인 안 된 약, 고지 한 줄(대비 AA)", async ({ page }) => {
        const saves = watchSaves(page);
        await openSelfForm(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        const input = medicationInput(page);
        const add = addButton(page);

        // ---- 버튼 글자·고지 원문(FE-04-25 A)·터치 44px
        await expect(add).toHaveText(ADD_LABEL);
        await expect(modal(page).getByRole("button", { name: ADD_LABEL })).toHaveCount(1);
        const notice = modal(page).getByTestId("drug-data-scope-notice");
        await expect(notice).toHaveText(NOTICE);
        await expect(notice).toBeVisible();
        await expectTouchTarget(add);
        await notice.scrollIntoViewIfNeeded(); // 모달 본문이 스크롤되므로 화면 안에 들여놓고 잰다(측정기는 보이는 글자만 잰다)
        await expectNoticeContrast(page, '[data-testid="account-modal"]', `프로필 ${scheme} ${width}`);
        await expectNoHorizontalScroll(page);
        await shot(page, "profile-notice");

        // ---- 검색 중: 느린 목 응답(`mock-slow`, 1.5초) 동안 `그대로 추가`가 비활성이고 Enter도 저장하지 않는다. 결과(후보 없음)가 오면 켜진다
        await input.fill("가나다 mock-slow");
        await expect(add).toBeDisabled();
        await expect(modal(page).getByTestId("medication-searching")).toHaveText(SEARCHING);
        await page.keyboard.press("Enter");
        await expect(chips(page)).toHaveCount(0);
        await expect(input).toHaveValue("가나다 mock-slow");
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        await shot(page, "profile-searching");
        await expect(modal(page).getByTestId("medication-no-candidates")).toBeVisible();
        await expect(add).toBeEnabled();
        await expect(chips(page)).toHaveCount(0); // 검색 중에 누른 Enter가 뒤늦게 저장되지 않는다

        // ---- 후보가 있는 글자로
        await input.fill("가나다");
        await expect(input).toHaveAttribute("aria-expanded", "true");
        await expect(candidates(page)).toHaveCount(6);
        await expect(add).toBeEnabled();

        // ---- 후보가 있는데 고르지 않은 Enter: 첫 후보로 활성만, 저장 없음
        await expect(input).not.toHaveAttribute("aria-activedescendant", /.+/);
        await page.keyboard.press("Enter");
        await expect(chips(page)).toHaveCount(0);
        await expect(input).toHaveValue("가나다");
        await expect(candidates(page).first()).toHaveAttribute("aria-selected", "true");
        await expect(input).toHaveAttribute("aria-activedescendant", (await candidates(page).first().getAttribute("id"))!);
        await expect(input).toBeFocused();
        await shot(page, "profile-enter-first");
        // 한 번 더 Enter: 첫 후보가 확인된 약으로 들어간다
        await page.keyboard.press("Enter");
        await expect(chips(page)).toHaveCount(1);
        await expect(chips(page).first().getByTestId("medication-name")).toHaveText("가나다정 100밀리그램");
        await expect(chips(page).first()).toHaveAttribute("data-confirmed", "true");
        await expect(input).toHaveValue("");

        // ---- 후보가 떠 있어도 `그대로 추가`를 누르면 확인 안 된 약
        await input.fill("라마바");
        await expect(candidates(page)).toHaveCount(3); // 제품 2 + 성분 1(라마바펜)
        await expect(add).toBeEnabled();
        await add.click();
        await expect(chips(page)).toHaveCount(2);
        await expect(chips(page).nth(1).getByTestId("medication-name")).toHaveText("라마바");
        await expect(chips(page).nth(1)).toHaveAttribute("data-confirmed", "false");
        await expect(chips(page).nth(1).getByTestId("medication-unconfirmed")).toHaveText("확인 안 된 약");
        await expect(modal(page).getByTestId("medication-unconfirmed-note")).toBeVisible();
        await expectNoHorizontalScroll(page);
        await shot(page, "profile-as-is");

        // ---- 저장 모양: 고른 후보 `{input_text, item_seq}`, 그대로 추가한 약 `item_seq` null
        await completeRequired(modal(page));
        await modal(page).getByTestId("profile-save").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        expect(saves).toHaveLength(1);
        expect(saves[0].medications).toEqual([
          { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
          { input_text: "라마바", item_seq: null },
        ]);
      });

      test("사진 확인 카드: 같은 고지 한 줄이 안내 아래에 보이고 대비가 AA 이상이다", async ({ page }) => {
        await openPhotoCard(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        const card = photoModal(page).getByTestId("photo-confirm-card");
        const notice = card.getByTestId("drug-data-scope-notice");
        await expect(notice).toHaveText(NOTICE);
        await expect(notice).toBeVisible();
        await expect(card.getByTestId("drug-data-scope-notice")).toHaveCount(1);
        const [guide, box, firstRow] = await Promise.all([card.getByTestId("photo-confirm-guide").boundingBox(), notice.boundingBox(), card.getByTestId("photo-row").first().boundingBox()]);
        expect(guide!.y + guide!.height).toBeLessThanOrEqual(box!.y + 1);
        expect(box!.y + box!.height).toBeLessThanOrEqual(firstRow!.y + 1);
        await expectNoticeContrast(page, '[data-testid="photo-modal"]', `사진 ${scheme} ${width}`);
        await card.getByTestId("photo-question").fill(QUESTION);
        await expectNoHorizontalScroll(page);
        await shot(page, "photo-notice");
      });
    });
  }
}
