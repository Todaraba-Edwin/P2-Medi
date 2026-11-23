import path from "node:path";
import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, ask, expect119Reachable, expectNoHorizontalScroll, expectTouchTarget, openApp } from "./helpers";

// FE-05 사진 입력(사진 부분만) e2e(Playwright 프로젝트 `msw-worker`, 브라우저 워커의 목 `src/mocks/photo-handlers.ts`. 실제 백엔드·원격 호출 0, 실제 사진 0):
// - 사진 고르기(P1·P2가 버튼 위) → 인식 중(P3) → 확인·수정 카드(후보 기본 선택 없음, 질문 비면 비활성) → 후보 고르기 → `이대로 확인`
//   → `/chat` 1회·요청 본문 `confirmed_drugs[].item_seq`. 승인 전 `/chat` 0회(H19, 〔D7〕A)
// - 인식 실패(P4)·상한(P8)·응답 `emergency`(카드 맨 위 119)·`닫기`(버림)
// - 〔D5〕A: 입구는 입력창 옆 하나. 미식별 결과 아래 `약 사진 올리기`는 DOM에 없다
// 사진은 시험 안에서 만든 합성 PNG다. 워커는 PNG 가로 픽셀 수로 시나리오를 고른다(`PHOTO_SCENARIO_PNG_WIDTH`와 같은 값. 이 파일은 `@/` 별칭을 못 풀어 값을 옮겨 적었다;
// 단위 시험 `photo.test.tsx`가 그 표를 검사한다).
// 캡처: `FE05_SHOT_DIR`을 주면 그 폴더에 `*-fe05.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`)
const SCENARIO_WIDTH = { ok: 64, unreadable: 65, unavailable: 66, emergency: 67 } as const;
type Scenario = keyof typeof SCENARIO_WIDTH;
const SHOT_DIR = process.env.FE05_SHOT_DIR;

const QUESTION = "같이 먹어도 돼요?";
const P1 = "환자 이름·병원·약국은 가리고 찍어도 돼요. 사진은 저장하지 않아요.";
const P2 = "올린 사진은 약 이름을 읽기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 사진을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
const P3 = "사진에서 약 이름을 읽는 중이에요";
const P4 = "사진에서 약 이름을 읽지 못했어요. 다시 찍거나 약 이름을 글자로 입력해 주세요.";
const P7 = "JPG·PNG 사진만, 8MB까지 올릴 수 있어요.";
const P8 = "지금은 사진으로 약 이름을 읽을 수 없어요. 약 이름을 글자로 입력해 주세요.";
const EMERGENCY_TEXT = "응급 상황일 수 있어요. 지금 바로 119에 전화하세요.";

// ---------------------------------------------------------------- 합성 PNG(노란 단색, 8비트 RGB)
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
export function makePng(width: number, height: number): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // RGB
  const stride = 1 + width * 3;
  const raw = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * stride] = 0; // filter: none
    for (let x = 0; x < width; x += 1) raw.set([0xff, 0xcc, 0x00], y * stride + 1 + x * 3);
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

// ---------------------------------------------------------------- 도구
const modal = (page: Page) => page.getByTestId("photo-modal");
const card = (page: Page) => modal(page).getByTestId("photo-confirm-card");
type ChatBody = { question: string; context: { confirmed_drugs: unknown[]; prior_drugs: unknown[] } };
function watchChat(page: Page) {
  const bodies: ChatBody[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat")) bodies.push(request.postDataJSON());
  });
  return bodies;
}
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fe05.png`) });
};
async function start(page: Page) {
  await openApp(page);
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  await expect(page.getByTestId("photo-entry")).toHaveCount(1);
  await page.getByTestId("photo-entry").click();
  await expect(modal(page)).toBeVisible();
  // Radix DismissableLayer는 mount 뒤 effect에서 body에 `pointer-events:none`을 걸고 재렌더로 Content에 `auto`를 붙인다.
  // 그 사이(부하가 크면 수십 ms) 모달 글자는 `elementFromPoint`에서 스크림에 가려진 것으로 잡혀 대비 측정 표본이 0이 된다.
  // "열렸다"는 상호작용이 되는 상태까지 포함하므로 여기서 기다린다
  await expect(modal(page)).toHaveCSS("pointer-events", "auto");
}
async function pickFile(page: Page, scenario: Scenario) {
  await modal(page)
    .getByTestId("photo-file")
    .setInputFiles({ name: "pouch.png", mimeType: "image/png", buffer: makePng(SCENARIO_WIDTH[scenario], 48) });
}

for (const width of [393, 1280, 360]) {
  test.describe(`사진 입력 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("고르기(P1·P2 위) → 인식 중 → 카드(기본 선택 없음·질문 비면 비활성) → 후보 → 확인 → /chat 1회(승인 전 0회), 두 번째 입구 없음", async ({ page }) => {
      const bodies = watchChat(page);
      await start(page);
      await expectNoHorizontalScroll(page);
      const box = modal(page);
      const privacy = box.getByTestId("photo-privacy-notice");
      const external = box.getByTestId("photo-external-ai-notice");
      const pick = box.getByTestId("photo-pick");
      await expect(privacy).toHaveText(P1);
      await expect(external).toHaveText(P2);
      await expect(pick).toBeVisible();
      const [p, e, b] = await Promise.all([privacy.boundingBox(), external.boundingBox(), pick.boundingBox()]);
      expect(p!.y + p!.height).toBeLessThanOrEqual(e!.y + 1);
      expect(e!.y + e!.height).toBeLessThanOrEqual(b!.y + 1);
      await expect(box.getByTestId("photo-format-note")).toBeVisible();
      await expectTouchTarget(box.getByTestId("photo-close"));
      await expect(box.getByRole("button", { name: "뒤로" })).toHaveCount(0);
      await expect119Reachable(page, box.getByTestId("layer-emergency-entry"));
      await shot(page, "photo-pick");

      await pickFile(page, "ok");
      await expect(box.getByTestId("photo-reading")).toContainText(P3);
      await shot(page, "photo-reading");

      await expect(card(page)).toBeVisible();
      await expect(card(page).getByTestId("photo-row")).toHaveCount(2);
      const radios = card(page).getByRole("radio");
      await expect(radios).toHaveCount(2);
      for (let index = 0; index < 2; index += 1) await expect(radios.nth(index)).toHaveAttribute("aria-checked", "false");
      await expect(card(page).getByTestId("photo-confirm")).toBeDisabled();
      await expect(card(page).getByTestId("photo-read-name").nth(1)).toHaveValue("라마바캡슐");
      expect(bodies).toHaveLength(0);
      await radios.nth(0).click();
      await expect(radios.nth(0)).toHaveAttribute("aria-checked", "true");
      await expect(card(page).getByTestId("photo-confirm")).toBeDisabled(); // 질문이 비어 있다
      await card(page).getByTestId("photo-question").fill(QUESTION);
      await expect(card(page).getByTestId("photo-confirm")).toBeEnabled();
      await expectNoHorizontalScroll(page);
      await shot(page, "photo-confirm");
      expect(bodies).toHaveLength(0); // 승인 전 /chat 0회

      await card(page).getByTestId("photo-confirm").click();
      await expect(modal(page)).toHaveCount(0);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect.poll(() => bodies.length).toBe(1);
      expect(bodies[0].question).toBe(`가나다정 100밀리그램, 라마바캡슐 ${QUESTION}`);
      expect(bodies[0].context.confirmed_drugs).toEqual([{ name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다정 100밀리그램" }]);
      await shot(page, "photo-result");

      // 〔D5〕A: 미식별 결과 아래 두 번째 입구는 없다. 입구는 입력창 옆 하나뿐
      await ask(page, "mock:미식별 합성 질문");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      await expect(page.getByRole("button", { name: "약 사진 올리기" })).toHaveCount(0);
      await expect(page.getByTestId("photo-entry")).toHaveCount(1);
      await expectNoHorizontalScroll(page);
    });
  });
}

test.describe("인식 실패·상한·응급·닫기 (360px)", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("UNREADABLE → P4와 `다시 찍기`·`글자로 입력`. `글자로 입력`은 닫고 입력창으로. /chat 0회", async ({ page }) => {
    const bodies = watchChat(page);
    await start(page);
    await pickFile(page, "unreadable");
    const failed = modal(page).getByTestId("photo-failed");
    await expect(failed).toHaveText(P4);
    await expect(modal(page).getByTestId("photo-retake")).toHaveText("다시 찍기");
    await expect(modal(page).getByTestId("photo-type-instead")).toHaveText("글자로 입력");
    await expect119Reachable(page, modal(page).getByTestId("layer-emergency-entry"));
    await expectNoHorizontalScroll(page);
    await shot(page, "photo-failed");
    await modal(page).getByTestId("photo-type-instead").click();
    await expect(modal(page)).toHaveCount(0);
    await expect(page.locator("textarea")).toBeFocused();
    expect(bodies).toHaveLength(0);
  });

  test("HEIC 파일(BE-14-08 A): 파일 선택이 HEIC를 받고, 디코드하지 못하는 브라우저(Chromium)는 보내지 않고 P7을 강조한다", async ({ page }) => {
    // 실제 HEIC 사진은 쓰지 않는다: `ftypheic` 머리만 있는 합성 바이트. Chromium에는 HEIC 디코더가 없어 변환이 실패하고 기존 형식 안내(P7)로 떨어진다
    const ingest: string[] = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.endsWith("/api/ingest/image")) ingest.push(request.method());
    });
    const bodies = watchChat(page);
    await start(page);
    const box = modal(page);
    const accept = (await box.getByTestId("photo-file").getAttribute("accept")) ?? "";
    expect(accept.split(",")).toEqual(expect.arrayContaining(["image/heic", "image/heif", ".heic", ".heif"]));
    const heic = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from("ftypheic", "ascii"), Buffer.alloc(32)]);
    await box.getByTestId("photo-file").setInputFiles({ name: "pouch.heic", mimeType: "image/heic", buffer: heic });
    const note = box.getByTestId("photo-format-note");
    await expect(note).toHaveAttribute("data-rejected", "true");
    await expect(note).toHaveAttribute("role", "alert");
    await expect(note).toHaveText(P7);
    await expect(box).toHaveAttribute("data-step", "pick");
    expect(ingest).toHaveLength(0);
    expect(bodies).toHaveLength(0);
  });

  test("UNAVAILABLE(상한) → P8", async ({ page }) => {
    await start(page);
    await pickFile(page, "unavailable");
    await expect(modal(page).getByTestId("photo-failed")).toHaveText(P8);
    await expect(modal(page).getByTestId("photo-failed")).toHaveAttribute("data-kind", "unavailable");
    await shot(page, "photo-unavailable");
  });

  test("응답에 emergency가 있으면 카드 맨 위에 119 배너(전화 링크가 눌린다)", async ({ page }) => {
    await start(page);
    await pickFile(page, "emergency");
    await expect(card(page)).toBeVisible();
    const banner = card(page).getByTestId("emergency-banner");
    await expect(banner).toContainText(EMERGENCY_TEXT);
    const [bannerBox, guideBox] = await Promise.all([banner.boundingBox(), card(page).getByTestId("photo-confirm-guide").boundingBox()]);
    expect(bannerBox!.y + bannerBox!.height).toBeLessThanOrEqual(guideBox!.y + 1);
    await expect119Reachable(page, banner.locator('a[href="tel:119"]'));
    await shot(page, "photo-emergency");
  });

  test("`닫기`·Esc는 승인 없이 버린다: /chat 0회, 초점은 사진 버튼으로", async ({ page }) => {
    const bodies = watchChat(page);
    await start(page);
    await pickFile(page, "ok");
    await expect(card(page)).toBeVisible();
    await card(page).getByTestId("photo-question").fill(QUESTION);
    await modal(page).getByTestId("photo-close").click();
    await expect(modal(page)).toHaveCount(0);
    await expect(page.getByTestId("photo-entry")).toBeFocused();
    await page.getByTestId("photo-entry").click();
    await expect(modal(page)).toHaveAttribute("data-step", "pick"); // 다시 열면 처음부터(목록은 메모리에서 사라졌다)
    await page.keyboard.press("Escape");
    await expect(modal(page)).toHaveCount(0);
    expect(bodies).toHaveLength(0);
    await expect(page.getByTestId("result-card")).toHaveCount(0);
  });
});

// 다크 모드(FE-12 병합 뒤): 사진 시트·확인 카드가 토큰(--color-bg 등)대로 어두운 바탕에 그려지고, 시트 안 글자 대비가 기준 이상이다.
// 캡처는 `photo-dark-*-{폭}-fe05.png`
const DARK_BG = "rgb(23, 21, 15)"; // --color-bg 다크(globals.css)
for (const width of [393, 1280]) {
  test.describe(`사진 입력 다크 모드 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT }, colorScheme: "dark" });

    test("시트(고르기)·확인 카드가 다크 토큰으로 그려지고 글자 대비가 기준 이상이다", async ({ page }) => {
      await start(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      const box = modal(page);
      await expect(box).toHaveCSS("background-color", DARK_BG);
      const pick = await measureContrast(page, '[data-testid="photo-modal"]');
      expect(pick.unmeasured, `다크 ${width} 고르기: 바탕색을 정할 수 없는 글자`).toEqual([]);
      expect(pick.samples.length).toBeGreaterThan(0);
      expect(failures(pick), `다크 ${width} 고르기: 기준(${AA_NORMAL}:1) 미달 글자`).toEqual([]);
      await shot(page, "photo-dark-pick");

      await pickFile(page, "ok");
      await expect(card(page)).toBeVisible();
      await card(page).getByRole("radio").nth(0).click();
      await card(page).getByTestId("photo-question").fill(QUESTION);
      await expect(card(page).getByTestId("photo-confirm")).toBeEnabled();
      const confirm = await measureContrast(page, '[data-testid="photo-modal"]');
      expect(confirm.unmeasured, `다크 ${width} 확인 카드: 바탕색을 정할 수 없는 글자`).toEqual([]);
      expect(confirm.samples.length).toBeGreaterThan(0);
      expect(failures(confirm), `다크 ${width} 확인 카드: 기준(${AA_NORMAL}:1) 미달 글자`).toEqual([]);
      await expectNoHorizontalScroll(page);
      await shot(page, "photo-dark-confirm");
    });
  });
}
