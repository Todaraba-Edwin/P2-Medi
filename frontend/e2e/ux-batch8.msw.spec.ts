import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { HEIGHT, ask, dock, expectNoHorizontalScroll, mockChat, openApp, panel, release, waitHeld } from "./helpers";

// FE-17 UI/UX 다듬기 8차(2026-11-24 "FE 모아서 진행")를 목(MSW) 워커로 본다. 393·1280·1920 × 라이트·다크.
// - U-27: 스크롤 컨테이너(`home`·`chat-thread`)는 본문(main) 전체 폭이라 스크롤바가 본문 오른쪽 가장자리(근거 상세가 열리면 패널 왼쪽)에 붙고,
//   휠 스크롤도 880px 열 밖(본문 여백)에서 된다. 내용 폭 제한(넓은 폭 880px, 좁은 폭 760px, 좌우 여백 포함)은 안쪽 열(`home-column`·`chat-column`)과
//   입력 영역(`dock`)이 같은 값으로 갖는다. 393px은 보이는 위치가 전과 같다(차례 x=14·폭 365, 입력창 x=12·폭 369)
// - U-24 수정-3: 진행 중 글자 쉬머의 띠가 지나가는 전 구간에서 글자 대비 4.5:1 이상(라이트 띠 faint → mute)
// 캡처: `FE_UX_BATCH8_SHOT_DIR`을 주면 `ux-batch8-{width}-{scheme}-{장면}.png`를 남긴다(쉬머는 정지 프레임)
const SHOT_DIR = process.env.FE_UX_BATCH8_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  if (target) await target.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
  else await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
const freezeShimmer = (page: Page) =>
  page.addStyleTag({ content: ".progress-shimmer{animation-play-state:paused!important;animation-delay:-0.75s!important}.animate-spin{animation-play-state:paused!important}" });
const box = async (locator: Locator) => (await locator.boundingBox())!;
const main = (page: Page) => page.getByTestId("main");
const thread = (page: Page) => page.getByTestId("chat-thread");
const column = (page: Page) => page.getByTestId("chat-column");
const progress = (page: Page) => page.getByRole("status", { name: "진행 상태" });
const scrollState = (target: Locator) => target.evaluate((el: HTMLElement) => ({ top: el.scrollTop, max: el.scrollHeight - el.clientHeight, scrollbar: el.offsetWidth - el.clientWidth, overflowY: getComputedStyle(el).overflowY }));
/** 넓은 폭의 내용 열 최대 폭(좌우 여백 24px 포함), 좁은 폭(1024 미만)은 760px */
const columnMax = (width: number) => (width >= 1024 ? 880 : 760);
const PAD = (width: number) => (width >= 1024 ? 24 : 12);
/** 대화 영역 아래 여백(`pb-3`, Conversation.tsx). 진행 중 따라가기의 끝 표지는 이 여백 위에 있다 */
const PADDING_BOTTOM = 12;

/** 스크롤 컨테이너가 본문 전체 폭이고(좌우 가장자리가 본문과 같다), 안쪽 열은 min(최대 폭, 본문 폭)으로 가운데이며, 입력 영역이 같은 열에 있다 */
async function expectSplit(page: Page, scroller: Locator, inner: Locator, width: number) {
  const m = await box(main(page));
  const s = await box(scroller);
  const c = await box(inner);
  const d = await box(dock(page));
  const { scrollbar } = await scrollState(scroller);
  expect(Math.abs(s.x - m.x)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(s.x + s.width - (m.x + m.width))).toBeLessThanOrEqual(0.5); // 스크롤바 자리(오른쪽 가장자리)가 본문 오른쪽 가장자리
  const expected = Math.min(columnMax(width), m.width - scrollbar);
  expect(Math.abs(c.width - expected)).toBeLessThanOrEqual(0.5);
  // 가운데 정렬(스크롤바가 자리를 차지하는 브라우저면 그만큼 왼쪽으로 치우친다)
  expect(Math.abs(c.x + c.width / 2 - (s.x + (s.width - scrollbar) / 2))).toBeLessThanOrEqual(0.5);
  // 입력 영역: 같은 최대 폭·가운데(스크롤하지 않는 고정 영역이라 스크롤바 몫은 없다)
  expect(Math.abs(d.width - Math.min(columnMax(width), m.width))).toBeLessThanOrEqual(0.5);
  expect(Math.abs(d.x + d.width / 2 - (m.x + m.width / 2))).toBeLessThanOrEqual(0.5);
  expect(d.y).toBeGreaterThanOrEqual(s.y + s.height - 0.5); // 스크롤 영역 아래
  return { m, s, c, d, scrollbar };
}

/** 대화가 영역보다 길어질 때까지 묻는다(마지막 답까지 받는다) */
async function longConversation(page: Page, times = 3) {
  await mockChat(page, "found");
  await openApp(page);
  for (let i = 1; i <= times; i += 1) {
    await ask(page);
    await expect(page.getByTestId("result-card")).toHaveCount(i);
  }
  await expect.poll(async () => (await scrollState(thread(page))).max).toBeGreaterThan(0);
}

/** sRGB 선형 보간 색의 WCAG 대비(페이지 안 계산된 색으로) */
const shimmerContrast = (target: Locator) =>
  target.evaluate((el) => {
    const rgb = (value: string) => {
      const probe = document.createElement("i");
      probe.style.color = value;
      document.body.append(probe);
      const parts = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number);
      probe.remove();
      return parts;
    };
    const lum = ([r, g, b]: number[]) => {
      const [R, G, B] = [r, g, b].map((v) => v / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
      return 0.2126 * R + 0.7152 * G + 0.0722 * B;
    };
    const ratio = (a: number[], b: number[]) => {
      const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };
    const style = getComputedStyle(el);
    const base = rgb(style.getPropertyValue("--shimmer-base").trim());
    const hi = rgb(style.getPropertyValue("--shimmer-hi").trim());
    // 진행 표시가 놓인 바탕: 위로 올라가며 처음 만나는 불투명 배경
    let node: Element | null = el;
    let surface = [255, 255, 255];
    while (node) {
      const bg = getComputedStyle(node).backgroundColor;
      const parts = bg.match(/[\d.]+/g)?.map(Number) ?? [];
      if (parts.length >= 3 && (parts.length < 4 || parts[3] === 1)) {
        surface = parts.slice(0, 3);
        break;
      }
      node = node.parentElement;
    }
    const steps = Array.from({ length: 41 }, (_, i) => base.map((c, k) => c + (hi[k] - c) * (i / 40)));
    return { min: Math.min(...steps.map((color) => ratio(color, surface))), center: ratio(hi, surface), band: ratio(base, hi) };
  });

for (const width of [393, 1280, 1920]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 8 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch8-${width}-${scheme}`;
      const desktop = width >= 1024;

      test("U-27-1·4: 시작 화면 스크롤 영역은 본문 전체 폭, 내용 열·입력 영역은 같은 최대 폭으로 가운데", async ({ page }) => {
        await openApp(page);
        const home = page.getByTestId("home");
        await expect(home).toBeVisible();
        expect((await scrollState(home)).overflowY).toBe("auto");
        await expectSplit(page, home, page.getByTestId("home-column"), width);
        // 병아리 이미지는 여전히 내용 열 가운데
        const hero = await box(home.getByRole("heading", { level: 1 }));
        const homeColumn = await box(page.getByTestId("home-column"));
        expect(hero.x).toBeGreaterThanOrEqual(homeColumn.x + PAD(width) - 0.5);
        expect(hero.x + hero.width).toBeLessThanOrEqual(homeColumn.x + homeColumn.width - PAD(width) + 0.5);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-home`);
      });

      test("U-27-1·2·3: 긴 대화의 스크롤바는 본문 오른쪽 가장자리, 내용은 최대 폭 가운데, 입력 영역 폭 그대로. 근거 상세를 열고 닫아도 같다", async ({ page }) => {
        test.setTimeout(90_000);
        await longConversation(page);
        if (desktop) {
          // 넓은 폭은 판정 줄이 있는 답이 오면 근거 상세가 열린다: 스크롤 영역 오른쪽 = 본문 오른쪽 = 패널 왼쪽
          await expect(panel(page)).toBeVisible();
          const opened = await expectSplit(page, thread(page), column(page), width);
          const panelBox = await box(page.getByTestId("panel-column"));
          expect(Math.abs(opened.s.x + opened.s.width - panelBox.x)).toBeLessThanOrEqual(0.5);
          await shot(page, `${base}-thread-panel`);
          await panel(page).getByRole("button", { name: "닫기" }).click();
          await expect(panel(page)).toHaveCount(0);
        }
        const closed = await expectSplit(page, thread(page), column(page), width);
        if (desktop) expect(Math.abs(closed.s.x + closed.s.width - width)).toBeLessThanOrEqual(0.5); // 패널이 닫히면 화면 오른쪽 가장자리
        // 393은 보이는 위치가 전과 같다: 차례 x=12+2, 폭 393-28 / 입력창(입력 영역의 첫 자식) x=12, 폭 369
        const turn = await box(page.locator("[data-turn]").first());
        expect(Math.abs(turn.x - (closed.c.x + PAD(width) + 2))).toBeLessThanOrEqual(0.5);
        expect(Math.abs(turn.width - (closed.c.width - 2 * (PAD(width) + 2)))).toBeLessThanOrEqual(0.5);
        if (!desktop) {
          expect(Math.round(turn.x)).toBe(14);
          expect(Math.round(turn.width)).toBe(365);
          const input = await box(dock(page).locator(":scope > *").first());
          expect(Math.round(input.x)).toBe(12);
          expect(Math.round(input.width)).toBe(369);
        }
        // 스크롤 가능 영역이 본문 전체 폭이다: 내용 열 밖(본문 왼쪽 여백)에서 휠을 굴려도 대화가 스크롤한다(넓은 폭에서 여백이 있을 때)
        const gutter = closed.c.x - closed.s.x;
        const before = await scrollState(thread(page));
        expect(before.max).toBeGreaterThan(0);
        const x = gutter > 40 ? closed.s.x + gutter / 2 : closed.c.x + closed.c.width / 2;
        await page.mouse.move(x, closed.s.y + closed.s.height / 2);
        await page.mouse.wheel(0, -400);
        await expect.poll(async () => (await scrollState(thread(page))).top).toBeLessThan(before.top);
        if (width === 1920) expect(gutter).toBeGreaterThan(40); // 1920에서는 실제로 열 밖에서 굴린 것이다
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-thread`);
      });

      test("U-27-3: 긴 대화에서 새 질문의 진행 표시 동안 맨 아래를 따라가고, 답이 오면 답의 맨 위가 대화 영역 위쪽에 온다. 사용자가 올린 위치는 그대로다", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "found", "found", "found", { name: "found", holdBefore: "answer" }, { name: "found", holdBefore: "answer" });
        await openApp(page);
        for (let i = 1; i <= 3; i += 1) {
          await ask(page);
          await expect(page.getByTestId("result-card")).toHaveCount(i);
        }
        if (desktop && (await panel(page).count()) > 0) await panel(page).getByRole("button", { name: "닫기" }).click();
        // 4번째: 진행 표시 동안 맨 아래(끝 표지는 아래 여백 12px 위에 있다, fe02-scroll과 같은 기준)
        await ask(page);
        await waitHeld(page);
        await expect(progress(page)).toBeVisible();
        await expect.poll(async () => {
          const state = await scrollState(thread(page));
          return state.max > 0 && Math.abs(state.top - state.max) <= PADDING_BOTTOM + 1;
        }).toBe(true);
        await release(page);
        await expect(page.getByTestId("result-card")).toHaveCount(4);
        await expect.poll(async () => {
          const s = await box(thread(page));
          const answer = await box(page.getByTestId("turn-answer").last());
          const state = await scrollState(thread(page));
          return Math.abs(state.top - state.max) <= 1 ? answer.y >= s.y + 8 - 1 : Math.abs(answer.y - (s.y + 8)) <= 1;
        }).toBe(true);
        if (desktop && (await panel(page).count()) > 0) await panel(page).getByRole("button", { name: "닫기" }).click();
        // 5번째: 진행 중 사용자가 위로 올리면 답이 와도 옮기지 않는다
        await ask(page);
        await waitHeld(page);
        const s = await box(thread(page));
        await page.mouse.move(s.x + s.width / 2, s.y + s.height / 2);
        await page.mouse.wheel(0, -600);
        await expect.poll(async () => {
          const state = await scrollState(thread(page));
          return state.max - state.top;
        }).toBeGreaterThan(100);
        const held = (await scrollState(thread(page))).top;
        await release(page);
        await expect(page.getByTestId("result-card")).toHaveCount(5);
        // 답이 붙어 높이가 늘어도 사용자가 둔 위치(scrollTop)는 그대로다
        expect(Math.abs((await scrollState(thread(page))).top - held)).toBeLessThanOrEqual(1);
      });

      test("U-24 수정-3: 진행 중 글자 쉬머는 띠가 지나가는 전 구간에서 바탕과 4.5:1 이상이고 띠는 바탕 글자와 구분된다", async ({ page }) => {
        await mockChat(page, { name: "typoCorrected", holdBefore: "answer" });
        await openApp(page);
        await ask(page);
        await waitHeld(page);
        const now = progress(page).locator('li[data-state="now"]').getByTestId("progress-step-text");
        await expect(now).toBeVisible();
        expect(await now.evaluate((el) => getComputedStyle(el).animationName)).toBe("progress-shimmer");
        const { min, center, band } = await shimmerContrast(now);
        expect(min).toBeGreaterThanOrEqual(4.5);
        expect(center).toBeGreaterThanOrEqual(4.5);
        expect(band).toBeGreaterThanOrEqual(1.5);
        await freezeShimmer(page);
        await shot(page, `${base}-progress`);
        await shot(page, `${base}-progress-close`, progress(page));
      });
    });
  }
}
