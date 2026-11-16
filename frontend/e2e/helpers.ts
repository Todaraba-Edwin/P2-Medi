import { expect } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { scenarios } from "../src/mocks/fixtures/scenarios";
import type { MockScenario, ScenarioName } from "../src/mocks/fixtures/scenarios";

// 첫 화면(/) e2e 공용 도구(FE-IMPL-06에서 flows.spec.ts에 있던 것을 FE-IMPL-06b에서 옮겼다. msw.spec.ts도 쓴다).
// 통신 대역(`mockChat`)은 mock 시나리오(src/mocks/fixtures)를 페이지 안의 fetch 대역이 **줄 단위 스트림**으로 낸다
// (MSW 핸들러와 같은 fixture. 이벤트 사이에서 멈출 수 있어 "119가 답보다 먼저"·"끊김"을 순서대로 확인한다).
//
// "가려지지 않음" 규칙(사용자 결정 2026-11-16 반영, 지시서 FE-IMPL-06b §1-3):
// - 119(배너의 전화 링크, 배너가 없을 때의 진입점)는 어떤 오버레이·시트에서도 덮이지 않는다 → `expectOnTop` + `expectClickReaches`
// - 고정 안내는 사용자가 연 오버레이·시트 동안 흐려지거나 덮일 수 있으나 접히지 않고, 닫으면 그대로 위에 있다
//   → 층이 열려 있으면 `expectInFirstScreen(..., { underUserLayer: true })`(위치·접힘만), 닫힌 뒤에는 기본값(덮임까지)

export const MIN_TOUCH = 44;
export const HEIGHT = 800;
export const QUESTION = "합성 질문 가나다정과 라마바캡슐을 같이 먹어도 되나요";
export const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";
export const ADVICE_FIXED = "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.";
export const EMERGENCY_TEXT = "응급 상황일 수 있어요. 지금 바로 119에 전화하세요.";

export type Hold = "answer" | "progress";
export type Step = ScenarioName | { name: ScenarioName; holdBefore: Hold };

export interface Plan {
  kind: "stream" | "http";
  lines: string[];
  holdAt: number;
  ending: string;
  status: number;
  body: string;
}

export function toPlan(step: Step): Plan {
  const name = typeof step === "string" ? step : step.name;
  const scenario: MockScenario = scenarios[name];
  if (scenario.kind === "http") {
    const body = scenario.code ? JSON.stringify({ code: scenario.code, fields: scenario.fields ?? [] }) : "";
    return { kind: "http", lines: [], holdAt: -1, ending: "close", status: scenario.status, body };
  }
  const holdBefore = typeof step === "string" ? null : step.holdBefore;
  return {
    kind: "stream",
    lines: scenario.events.map((event) => JSON.stringify(event)),
    holdAt: holdBefore ? scenario.events.findIndex((event) => event.type === holdBefore) : -1,
    ending: scenario.ending,
    status: 200,
    body: "",
  };
}

/** 요청 순서대로 시나리오를 돌려준다(마지막 것은 되풀이). `holdBefore`를 주면 그 이벤트 앞에서 `release()`를 기다린다 */
export async function mockChat(page: Page, ...steps: Step[]) {
  await page.addInitScript((plans: Plan[]) => {
    const state = { requests: [] as unknown[], held: false, release: () => {} };
    (window as unknown as { __chat: typeof state }).__chat = state;
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (!new URL(request.url).pathname.endsWith("/api/chat")) return original(input, init);
      const index = state.requests.length;
      state.requests.push(JSON.parse(await request.clone().text()));
      const plan = plans[Math.min(index, plans.length - 1)];
      if (plan.kind === "http") return new Response(plan.body, { status: plan.status, headers: { "Content-Type": "application/json" } });
      const encoder = new TextEncoder();
      const body = new ReadableStream<Uint8Array>({
        async start(controller) {
          for (let i = 0; i < plan.lines.length; i += 1) {
            if (i === plan.holdAt) {
              state.held = true;
              await new Promise<void>((resolve) => {
                state.release = resolve;
              });
              state.held = false;
            }
            controller.enqueue(encoder.encode(`${plan.lines[i]}\n`)); // 한 줄씩 따로 보낸다
            await new Promise((resolve) => setTimeout(resolve, 10));
          }
          if (plan.ending === "close") controller.close();
          else if (plan.ending === "cut") controller.error(new TypeError("mock connection cut"));
        },
      });
      return new Response(body, { status: 200, headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } });
    };
  }, steps.map(toPlan));
}

export type ChatWindow = { __chat: { requests: Array<{ question: string; context?: unknown }>; held: boolean; release: () => void } };
export const requests = (page: Page) => page.evaluate(() => (window as unknown as ChatWindow).__chat.requests);
export const waitHeld = (page: Page) => page.waitForFunction(() => (window as unknown as ChatWindow).__chat.held);
export const release = (page: Page) => page.evaluate(() => (window as unknown as ChatWindow).__chat.release());

export async function openApp(page: Page, base = "") {
  await page.goto(`${base}/`);
  await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
}

export async function ask(page: Page, question = QUESTION) {
  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: "보내기" }).click();
}

export async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

/**
 * 요소가 스크롤 없이 첫 화면 안에 다 들어와 있고, 접혀 있지 않으며, 다른 것에 덮여 있지 않은가.
 * `underUserLayer`: 사용자가 연 오버레이·시트가 있는 동안이다. 고정 안내는 그 동안 덮일 수 있으므로 덮임은 보지 않는다(위치·접힘만).
 * 119에는 쓰지 않는다(119는 층이 열려 있어도 덮이면 안 된다).
 */
export async function expectInFirstScreen(page: Page, target: Locator, { underUserLayer = false } = {}) {
  await expect(target).toBeVisible();
  const box = (await target.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 0.5);
  // 접히는 틀(details·닫힌 상태) 안에 있지 않다
  expect(await target.evaluate((el) => el.closest("details:not([open]), [data-state=closed]") === null)).toBe(true);
  if (!underUserLayer) await expectOnTop(target);
}

export async function expectTouchTarget(target: Locator, { widthToo = true } = {}) {
  const box = (await target.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(MIN_TOUCH);
  if (widthToo) expect(box.width).toBeGreaterThanOrEqual(MIN_TOUCH);
}

/**
 * 덮임 검사: 요소 위 다섯 점(가운데와 25%·75% 네 점)에서 `elementFromPoint`가 그 요소(또는 그 안)인가.
 * 스크림·시트·다른 층이 한 점이라도 덮으면 실패한다.
 */
export async function expectOnTop(target: Locator) {
  const misses = await target.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const points = [
      [0.5, 0.5],
      [0.25, 0.25],
      [0.75, 0.25],
      [0.25, 0.75],
      [0.75, 0.75],
    ];
    return points
      .map(([fx, fy]) => {
        const hit = document.elementFromPoint(rect.left + rect.width * fx, rect.top + rect.height * fy);
        return hit !== null && (hit === el || el.contains(hit)) ? null : `${fx},${fy}: ${hit ? (hit.getAttribute("data-testid") ?? hit.tagName) : "null"}`;
      })
      .filter((miss) => miss !== null);
  });
  expect(misses).toEqual([]);
}

/**
 * 실제 클릭 대상 확인: 요소 가운데를 마우스로 누르면 브라우저가 낸 click 이벤트의 대상이 그 요소(또는 그 안)인가.
 * 덮개·`inert`·`pointer-events`를 모두 거친 결과다. `tel:` 이동은 막는다(시험에서 전화 앱을 열지 않는다).
 */
export async function expectClickReaches(page: Page, target: Locator) {
  await page.evaluate(() => {
    const w = window as unknown as { __clicked: EventTarget | null };
    w.__clicked = null;
    document.addEventListener(
      "click",
      (event) => {
        w.__clicked = event.target;
        if (event.target instanceof Element && event.target.closest('a[href^="tel:"]')) event.preventDefault();
      },
      { capture: true, once: true },
    );
  });
  const box = (await target.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  expect(
    await target.evaluate((el) => {
      const clicked = (window as unknown as { __clicked: EventTarget | null }).__clicked;
      return clicked instanceof Node && (clicked === el || el.contains(clicked));
    }),
  ).toBe(true);
}

/** 119 전화 링크가 누를 수 있는 상태인가: 첫 화면 안, `tel:119`, 44px, 덮이지 않음, 실제 클릭이 닿음 */
export async function expect119Reachable(page: Page, link: Locator) {
  await expect(link).toHaveAttribute("href", "tel:119");
  await expectInFirstScreen(page, link);
  await expectTouchTarget(link);
  await expectClickReaches(page, link);
}

/** 안의 요소들이 틀 밖으로 넘치거나 잘리지 않는가 */
export async function expectContained(container: Locator, selector: string) {
  const box = (await container.boundingBox())!;
  const items = await container.locator(selector).evaluateAll((els) =>
    els.map((el) => {
      const rect = el.getBoundingClientRect();
      return { text: el.textContent ?? "", left: rect.left, right: rect.right, clipped: el.scrollWidth > el.clientWidth + 1 };
    }),
  );
  for (const item of items) {
    expect(item.left, item.text).toBeGreaterThanOrEqual(box.x - 0.5);
    expect(item.right, item.text).toBeLessThanOrEqual(box.x + box.width + 0.5);
    expect(item.clipped, item.text).toBe(false);
  }
  return items.length;
}

export const banner = (page: Page) => page.getByTestId("emergency-banner");
export const dock = (page: Page) => page.getByTestId("dock");
export const sheet = (page: Page) => page.getByRole("dialog", { name: "근거 상세" });
// 사이드바 오버레이가 열리면 뒤 요소는 보조기기에서 숨겨지므로(역할로 찾을 수 없다) 패널·입력창은 요소로 집는다
export const panel = (page: Page) => page.locator('aside[data-testid="evidence-panel"][data-mode="panel"]');
export const input = (page: Page) => page.locator("textarea");
export const scrim = (page: Page) => page.getByTestId("sidebar-scrim");
export const pushSidebar = (page: Page) => page.locator('[data-testid="sidebar"][data-presentation="push"]');
export const overlaySidebar = (page: Page) => page.locator('[data-testid="sidebar"][data-presentation="overlay"]');
export const rail = (page: Page) => page.getByTestId("sidebar-rail");
export const tel = (page: Page) => page.locator('a[href="tel:119"]');
/** 배너의 전화 링크 */
export const bannerTel = (page: Page) => page.getByTestId("emergency-banner").locator('a[href="tel:119"]');
/** 머리줄을 덮는 층(드로어·사이드바 오버레이·근거 상세 시트) 안의 119 진입점 */
export const layerTel = (page: Page) => page.getByTestId("layer-emergency-entry");

