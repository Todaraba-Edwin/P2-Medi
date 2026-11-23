import path from "node:path";
import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, openApp, completeRequired, fillName } from "./helpers";

// 2026-11-23 사용자 결정 "아스피린 A" e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목. 실제 백엔드·원격 호출 0, 실제 사진 0):
// 확인 카드에서 `약 추가` → "아스피린장용정" 입력 → 입력이 멈춘 뒤 게스트 허용 `POST /api/ingest/drugs/search`(토큰 없음) → 그 행에 판독 행과 같은 라디오 목록(기본 선택 없음)
// → 선택 → `이대로 확인` → `/chat` 본문 `confirmed_drugs[].item_seq`(승인 전 `/chat` 0회, H19). 프로필 `사진으로 등록` 길에서도 같은 카드·같은 검색이 돈다.
// 후보 이름의 제조사·번호는 합성 사전(`src/mocks/fixtures/account.ts`)의 값이다.
// 캡처: `L10_SHOT_DIR`을 주면 `l10-card-search-{폭}-{light|dark}.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다)
const SHOT_DIR = process.env.L10_SHOT_DIR;
const OK_PNG_WIDTH = 64; // `PHOTO_SCENARIO_PNG_WIDTH.ok`
const TYPED = "아스피린장용정";
const PICKED = "아스피린장용정 100밀리그램";
const PICKED_SEQ = "200000201";
const QUESTION = "같이 먹어도 돼요?";
const P6 = "비슷한 이름의 약이에요. 맞는 약이 있으면 골라 주세요. 고르지 않으면 적힌 글자로 찾아봐요.";

// ---------------------------------------------------------------- 합성 PNG(노란 단색, 8비트 RGB). `photo.msw.spec.ts`의 `makePng`와 같은 규칙(spec 파일을 import하면 그 시험이 다시 등록되므로 옮겨 적었다)
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

const photoModal = (page: Page) => page.getByTestId("photo-modal");
const card = (page: Page) => photoModal(page).getByTestId("photo-confirm-card");
const accountModal = (page: Page) => page.getByTestId("account-modal");

type SearchCall = { authorization: string | null; body: { q?: string } };
function watch(page: Page) {
  const log = { chat: [] as { context: { confirmed_drugs: unknown[] } }[], searches: [] as SearchCall[], saves: [] as { medications?: unknown[] }[] };
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "POST") return;
    if (pathname.endsWith("/api/chat")) log.chat.push(request.postDataJSON());
    if (pathname.endsWith("/api/ingest/drugs/search")) log.searches.push({ authorization: request.headers()["authorization"] ?? null, body: request.postDataJSON() });
    if (/\/api\/profiles(\/|$)/.test(pathname)) log.saves.push(request.postDataJSON());
  });
  return log;
}
const shot = async (page: Page, scheme: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `l10-card-search-${page.viewportSize()!.width}-${scheme}.png`) });
};
async function pickOk(page: Page) {
  await expect(photoModal(page)).toBeVisible();
  await expect(photoModal(page)).toHaveCSS("pointer-events", "auto");
  await photoModal(page)
    .getByTestId("photo-file")
    .setInputFiles({ name: "pouch.png", mimeType: "image/png", buffer: makePng(OK_PNG_WIDTH, 48) });
  await expect(card(page)).toBeVisible();
  await expect(card(page).getByTestId("photo-row")).toHaveCount(2);
}
/** `약 추가` → 새 행에 글자 입력 → 그 행에 후보 라디오가 붙는다(기본 선택 없음). 고른 라디오를 돌려준다 */
async function addRowAndPick(page: Page, log: ReturnType<typeof watch>) {
  await card(page).getByTestId("photo-add-row").click();
  const row = card(page).getByTestId("photo-row").nth(2);
  await expect(row.getByRole("radio")).toHaveCount(0);
  await row.getByTestId("photo-read-name").pressSequentially(TYPED, { delay: 30 });
  const radios = row.getByRole("radio");
  await expect(radios).toHaveCount(2);
  await expect(row.getByRole("radiogroup")).toHaveCount(1);
  await expect(row.getByTestId("photo-candidates-guide")).toHaveText(P6); // 판독 행과 같은 안내 글자
  for (let index = 0; index < 2; index += 1) await expect(radios.nth(index)).toHaveAttribute("aria-checked", "false");
  await expect(radios.nth(0)).toContainText(PICKED);
  // 글자마다 부르지 않는다: 입력이 멈춘 뒤 마지막 글자로 한 번(디바운스). 토큰 없음(게스트)
  expect(log.searches).toHaveLength(1);
  expect(log.searches[0]).toEqual({ authorization: null, body: { q: TYPED } });
  // 판독 행의 후보는 그대로(다시 찾지 않았다)
  await expect(card(page).getByTestId("photo-row").nth(0).getByRole("radio")).toHaveCount(2);
  await radios.nth(0).click();
  await expect(radios.nth(0)).toHaveAttribute("aria-checked", "true");
  return radios.nth(0);
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`확인 카드 직접 추가 행 검색 ${width}px ${scheme}`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("게스트: `약 추가` → 입력 → 후보 목록(토큰 없이 한 번 검색) → 선택 → 확인 → /chat 본문에 item_seq(승인 전 0회)", async ({ page }) => {
        const log = watch(page);
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await expect(page.getByTestId("login-entry")).toBeVisible(); // 로그인하지 않은 상태
        await page.getByTestId("photo-entry").click();
        await pickOk(page);
        await addRowAndPick(page, log);
        await card(page).getByTestId("photo-question").fill(QUESTION);
        await expectNoHorizontalScroll(page);
        await shot(page, scheme);
        expect(log.chat).toHaveLength(0);

        await card(page).getByTestId("photo-confirm").click();
        await expect(photoModal(page)).toHaveCount(0);
        await expect(page.getByTestId("result-card")).toBeVisible();
        await expect.poll(() => log.chat.length).toBe(1);
        expect(log.chat[0].context.confirmed_drugs).toEqual([{ name: PICKED, item_seq: PICKED_SEQ, input_name: PICKED }]);
        expect(log.searches).toHaveLength(1);
      });
    });
  }
}

test.describe("프로필 `사진으로 등록`·미선택 행 (393px)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("프로필 폼의 `사진으로 등록` 카드에서도 `약 추가` 행에 후보가 붙고, 고른 약은 확인된 약으로 목록에 들어간다. /chat 0회", async ({ page }) => {
    const log = watch(page);
    await openApp(page);
    await page.getByTestId("login-entry").click();
    await accountModal(page).getByTestId("social-kakao").click();
    await expect(accountModal(page)).toHaveAttribute("data-step", "consent");
    for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) await accountModal(page).locator(`[data-doc-type="${docType}"]`).getByRole("checkbox").check();
    await accountModal(page).getByTestId("consent-submit").click();
    await accountModal(page).getByTestId("add-self").click();
    await expect(accountModal(page)).toHaveAttribute("data-step", "profile-form");
    await fillName(accountModal(page), "나");
    await accountModal(page).getByTestId("medication-photo").click();
    await pickOk(page);
    await expect(card(page)).toHaveAttribute("data-destination", "profile");
    await addRowAndPick(page, log);
    await card(page).getByTestId("photo-confirm").click();
    await expect(photoModal(page)).toHaveCount(0);
    const chips = accountModal(page).getByTestId("medication");
    await expect(chips).toHaveCount(3);
    await expect(chips.nth(2).getByTestId("medication-name")).toHaveText(PICKED);
    await expect(chips.nth(2)).toHaveAttribute("data-confirmed", "true");
    await completeRequired(accountModal(page));
    await accountModal(page).getByTestId("profile-save").click();
    await expect(accountModal(page)).toHaveAttribute("data-step", "profiles");
    expect(log.saves).toHaveLength(1);
    expect(log.saves[0].medications).toContainEqual({ input_text: PICKED, item_seq: PICKED_SEQ });
    expect(log.chat).toHaveLength(0);
  });

  test("후보를 고르지 않으면 적힌 글자 그대로 확인 안 된 약으로 간다. 2글자 미만은 검색하지 않는다", async ({ page }) => {
    const log = watch(page);
    await openApp(page);
    await page.getByTestId("photo-entry").click();
    await pickOk(page);
    await card(page).getByTestId("photo-add-row").click();
    const row = card(page).getByTestId("photo-row").nth(2);
    const input = row.getByTestId("photo-read-name");
    await input.pressSequentially("아", { delay: 30 });
    await page.waitForTimeout(700);
    expect(log.searches).toHaveLength(0);
    await input.pressSequentially(TYPED.slice(1), { delay: 30 });
    await expect(row.getByRole("radio")).toHaveCount(2);
    await card(page).getByTestId("photo-question").fill(QUESTION);
    await card(page).getByTestId("photo-confirm").click();
    await expect.poll(() => log.chat.length).toBe(1);
    expect(log.chat[0]).toMatchObject({ question: `가나다정, 라마바캡슐, ${TYPED} ${QUESTION}`, context: { confirmed_drugs: [] } });
  });
});
