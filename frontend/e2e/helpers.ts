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

/**
 * 사이드바 아래 계정 메뉴(버튼 하나 → 위로 열리는 팝오버, 2026-11-23)를 연다. 좁은 폭(1024 미만)은 ☰ 드로어 안 버튼이다.
 * 열린 메뉴(`account-menu`)를 돌려준다. 항목: `account-entry`(로그인/가입·프로필 관리)·`theme-*`·`legal-entry`·`account-logout`(회원)
 */
export async function openAccountMenu(page: Page) {
  // 좁은 폭: 드로어가 아직 닫혀 있을 때만 ☰을 누른다(로그아웃처럼 드로어를 닫지 않는 항목 뒤에는 열린 채다)
  if (page.viewportSize()!.width < 1024 && (await page.getByTestId("menu-drawer").count()) === 0) await page.getByTestId("menu-button").click();
  const button = page.getByTestId("account-menu-button").first();
  await button.click();
  const menu = page.getByTestId("account-menu");
  await expect(menu).toBeVisible();
  return menu;
}

/**
 * 입력창 안 대상 프로필 칩(2026-11-23, 본문 "누가 먹나요" 선택 줄 대신)을 눌러 위로 열린 목록에서 대상을 고른다. 고르면 목록이 닫힌다.
 * 같은 값을 계정 버튼 메뉴 맨 위 목록도 쓴다(`openAccountMenu`)
 */
export async function pickTarget(page: Page, name: string) {
  await page.getByTestId("target-chip").click();
  const menu = page.getByTestId("target-menu");
  await expect(menu).toBeVisible();
  await menu.getByRole("menuitemradio", { name, exact: true }).click();
  await expect(menu).toHaveCount(0);
}

/** 대상 프로필 목록(입력창 칩을 눌러 연다)의 항목 글자. 열어 읽고 Esc로 닫는다 */
export async function targetOptionTexts(page: Page): Promise<string[]> {
  await page.getByTestId("target-chip").click();
  const menu = page.getByTestId("target-menu");
  await expect(menu).toBeVisible();
  const texts = await menu.getByTestId("target-option").allTextContents();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  return texts;
}

/**
 * 프로필 폼의 버튼 선택 묶음(FE-17 U-07: 관계·연령대·성별은 select가 아니라 radiogroup)에서 보이는 글자로 고른다.
 * 예: `pickChoice(modal, "성별", "여성")`, `pickChoice(modal, "연령대", "만 19~64세")`
 */
export async function pickChoice(scope: Locator, group: string, option: string) {
  const radio = scope.getByRole("radiogroup", { name: group, exact: true }).getByRole("radio", { name: option, exact: true });
  await radio.click();
  await expect(radio).toHaveAttribute("aria-checked", "true");
}

/**
 * 프로필 폼의 이름(별명) 칸에 `name`을 적고, 칸 값이 정확히 `name`이 될 때까지 다시 적는다(빈 값 `""`도 같다).
 * 왜 필요한가(백로그 플래키, 2026-11-23 재현): 카카오 로그인으로 새 본인 프로필을 열면 닉네임 초기값(FE-04-28 B)이 비동기로 도착한다.
 * Playwright `fill`은 칸을 `select()`한 뒤 **별도 왕복**으로 글자를 넣는데, 그 사이 초기값이 들어오면 커서가 끝으로 가서
 * 글자가 뒤에 붙는다("삐약이" + "나" = "삐약이나"). 앱은 사용자가 적은 뒤 도착한 초기값으로 칸을 덮지 않으므로(`ProfileForm`의 `typed`)
 * 한 번 `name`이 들어가면 그대로 남는다. 단언은 약하게 하지 않는다: 적은 직후 값이 `name`과 정확히 같아야 통과한다
 */
export async function fillName(scope: Locator, name: string) {
  const field = scope.getByLabel("이름(별명)");
  await expect(async () => {
    await field.fill(name);
    expect(await field.inputValue()).toBe(name);
  }).toPass({ intervals: [100, 250, 500], timeout: 5_000 });
}

/**
 * 프로필 폼의 비어 있는 필수 칸만 채운다(FE-17 U-07: 관계·이름·연령대·성별을 채워야 `저장`이 눌린다). 이름은 시험이 직접 적는다.
 * 이미 고른 칸은 그대로 둔다. 기본: 관계 `자녀`(가족), 연령대 `만 19~64세`, 성별 `남성`(예전 미입력과 같이 임신 여부가 아니오로 저장된다)
 */
export async function completeRequired(scope: Locator, { relation = "자녀", age = "만 19~64세", sex = "남성" }: { relation?: string; age?: string; sex?: string } = {}) {
  for (const [group, option] of [["관계", relation], ["연령대", age], ["성별", sex]] as const) {
    const checked = scope.getByRole("radiogroup", { name: group, exact: true }).locator('[role="radio"][aria-checked="true"]');
    if ((await checked.count()) === 0) await pickChoice(scope, group, option);
  }
}

/** 계정 메뉴의 `프로필 관리`(게스트: `로그인/가입`)로 계정 모달을 연다 */
export async function openAccountEntry(page: Page) {
  const menu = await openAccountMenu(page);
  await menu.getByTestId("account-entry").click();
  await expect(page.getByTestId("account-modal")).toBeVisible();
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

/**
 * 가장 최근 답 아래의 고정 안내(서버 `fixed_notice`). FE-17 U-26-1(2026-11-24 사용자 "입력시에 INPUT 위에 … 문구 제거")로
 * 입력창 위 고정 영역(`dock`)에서 각 답 아래(대화 영역)로 옮겼고, 같은 줄은 대화에서 가장 최근 답 한 곳에만 보인다
 */
export const fixedNotice = (page: Page) => page.getByTestId("chat-thread").getByTestId("fixed-notice").last();

/**
 * 고정 안내가 결과 화면(대화 영역) 안 접히지 않는 자리에 있고, 그 자리로 스크롤하면 보이며 다른 것에 덮이지 않는가(FE-17 U-26-1).
 * 예전 `expectInFirstScreen(dock 고정 안내)`("스크롤 없이 첫 화면")을 대신한다: 입력창 위 상시 표시를 없앤 사용자 지시라 첫 화면 보장은 더 이상 요구가 아니다.
 * `underUserLayer`: 사용자가 연 오버레이·시트가 있는 동안이다(덮임은 보지 않는다)
 */
export async function expectNoticeInResult(page: Page, target: Locator, { underUserLayer = false } = {}) {
  await expect(target).toBeAttached();
  await target.evaluate((el) => el.scrollIntoView({ block: "nearest" }));
  await expect(target).toBeVisible();
  expect(await target.evaluate((el) => el.closest('[data-testid="chat-thread"]') !== null)).toBe(true);
  expect(await target.evaluate((el) => el.closest("details:not([open]), [data-state=closed], [role=dialog]") === null)).toBe(true);
  await expect(target).toContainText(FIXED_NOTICE);
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
/** 옛 층 안 119 진입점(FE-17 U-04로 제거). 없어졌는지 확인할 때만 쓴다 */
export const layerTel = (page: Page) => page.getByTestId("layer-emergency-entry");
/** 입력창 아래 통합 고지 한 단락(FE-17 U-02: 법적 고지 + 저장 안 함·외부 AI 전송 고지) */
export const notice = (page: Page) => page.getByTestId("input-combined-notice");

