import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { scenarios } from "../src/mocks/fixtures/scenarios";
import type { MockScenario, ScenarioName } from "../src/mocks/fixtures/scenarios";

// 첫 화면(/) 조립의 흐름·폭 시험(FE-IMPL-06). 통신은 mock 시나리오(src/mocks/fixtures)를 페이지 안의 fetch 대역이 **줄 단위 스트림**으로 낸다
// (MSW 핸들러와 같은 fixture. 이벤트 사이에서 멈출 수 있어 "119가 답보다 먼저"·"끊김"을 순서대로 확인한다).
// 실제 MSW 워커 연결은 맨 아래 묶음이 확인한다(E2E_MSW_BASE_URL을 줄 때만 돈다).

const MIN_TOUCH = 44;
const HEIGHT = 800;
const QUESTION = "합성 질문 가나다정과 라마바캡슐을 같이 먹어도 되나요";
const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";
const ADVICE_FIXED = "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.";
const EMERGENCY_TEXT = "응급 상황일 수 있어요. 지금 바로 119에 전화하세요.";

type Hold = "answer" | "progress";
type Step = ScenarioName | { name: ScenarioName; holdBefore: Hold };

interface Plan {
  kind: "stream" | "http";
  lines: string[];
  holdAt: number;
  ending: string;
  status: number;
  body: string;
}

function toPlan(step: Step): Plan {
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
async function mockChat(page: Page, ...steps: Step[]) {
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

type ChatWindow = { __chat: { requests: Array<{ question: string; context?: unknown }>; held: boolean; release: () => void } };
const requests = (page: Page) => page.evaluate(() => (window as unknown as ChatWindow).__chat.requests);
const waitHeld = (page: Page) => page.waitForFunction(() => (window as unknown as ChatWindow).__chat.held);
const release = (page: Page) => page.evaluate(() => (window as unknown as ChatWindow).__chat.release());

async function openApp(page: Page, base = "") {
  await page.goto(`${base}/`);
  await expect(page.getByTestId("app-shell")).toHaveAttribute("data-ready", "true");
}

async function ask(page: Page, question = QUESTION) {
  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: "보내기" }).click();
}

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

/** 요소가 스크롤 없이 첫 화면 안에 다 들어와 있는가 */
async function expectInFirstScreen(page: Page, target: Locator) {
  await expect(target).toBeVisible();
  const box = (await target.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 0.5);
}

async function expectTouchTarget(target: Locator, { widthToo = true } = {}) {
  const box = (await target.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(MIN_TOUCH);
  if (widthToo) expect(box.width).toBeGreaterThanOrEqual(MIN_TOUCH);
}

/** 요소의 가운데를 눌렀을 때 그 요소(또는 그 안)가 맞는가: 다른 것에 덮여 있지 않다 */
async function expectOnTop(target: Locator) {
  expect(
    await target.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return hit !== null && (hit === el || el.contains(hit));
    }),
  ).toBe(true);
}

/** 안의 요소들이 틀 밖으로 넘치거나 잘리지 않는가 */
async function expectContained(container: Locator, selector: string) {
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

const banner = (page: Page) => page.getByTestId("emergency-banner");
const dock = (page: Page) => page.getByTestId("dock");
const sheet = (page: Page) => page.getByRole("dialog", { name: "근거 상세" });
// 사이드바 오버레이가 열리면 뒤 요소는 보조기기에서 숨겨지므로(역할로 찾을 수 없다) 패널·입력창은 요소로 집는다
const panel = (page: Page) => page.locator('aside[data-testid="evidence-panel"][data-mode="panel"]');
const input = (page: Page) => page.locator("textarea");
const scrim = (page: Page) => page.getByTestId("sidebar-scrim");
const pushSidebar = (page: Page) => page.locator('[data-testid="sidebar"][data-presentation="push"]');
const overlaySidebar = (page: Page) => page.locator('[data-testid="sidebar"][data-presentation="overlay"]');
const rail = (page: Page) => page.getByTestId("sidebar-rail");
const tel = (page: Page) => page.locator('a[href="tel:119"]');

// ============================================================ 흐름(좁은 폭)
for (const width of [360, 320]) {
  test.describe(`흐름 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면: 입력창·고지·119 진입점이 첫 화면에 있고 가로 스크롤이 없다(F1)", async ({ page }) => {
      await openApp(page);
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Can I PPiyak");
      await expectInFirstScreen(page, input(page));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      const entry = page.getByTestId("emergency-entry");
      await expectInFirstScreen(page, entry);
      await expect(entry).toHaveAttribute("href", "tel:119");
      await expectTouchTarget(entry);
      await expect(tel(page)).toHaveCount(1);
      await expectTouchTarget(page.getByRole("button", { name: "메뉴 열기" }));
      await expectTouchTarget(page.getByRole("button", { name: "보내기" }));
      // 고지는 접히지 않는 영역에 있다
      expect(await page.getByTestId("legal-footer").evaluate((el) => el.closest("details, [role=dialog], [data-state=closed]") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("응급: 119가 답보다 먼저 첫 화면 맨 위에 뜨고, 금기 결과가 그 아래 이어진다(F7·F8·F13)", async ({ page }) => {
      await mockChat(page, { name: "emergency", holdBefore: "answer" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      // 답이 오기 전: 119 배너만 먼저 보인다
      await expect(banner(page)).toHaveAttribute("role", "alert");
      await expect(banner(page)).toContainText(EMERGENCY_TEXT);
      await expect(page.getByTestId("result-view")).toHaveCount(0);
      await expectInFirstScreen(page, banner(page));
      expect(await page.getByTestId("app-shell").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-row");
      await expect(page.getByRole("status", { name: "진행 상태" })).toBeVisible(); // 금기 조회는 막지 않는다
      await expect(page.getByTestId("mascot")).toHaveCount(0); // 119가 뜨면 진행 표시의 마스코트를 숨긴다
      // 119는 배너 하나뿐이다(머리줄 진입점·토스트와 겹치지 않는다)
      await expect(tel(page)).toHaveCount(1);
      await expectTouchTarget(tel(page));
      await release(page);
      // 답이 온 뒤: 결과가 배너 아래에 이어지고 배너는 그대로 맨 위다
      const result = page.getByTestId("result-view");
      await expect(result.getByTestId("result-card")).toBeVisible();
      expect((await result.boundingBox())!.y).toBeGreaterThan((await banner(page).boundingBox())!.y);
      await expectInFirstScreen(page, banner(page));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expect(page.getByText(EMERGENCY_TEXT)).toHaveCount(1);
      await expect(tel(page)).toHaveCount(1);
      await expect(page.locator("img")).toHaveCount(1); // 머리줄 로고 심볼뿐(마스코트 없음)
      await expect(page.locator("audio")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("일반 질문: 진행 표시 → 결과 → 근거 상세를 열고 닫으면 원래 결과로 돌아온다(F2·F6)", async ({ page }) => {
      await mockChat(page, { name: "found", holdBefore: "answer" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      const progress = page.getByRole("status", { name: "진행 상태" });
      await expect(progress.getByRole("listitem")).toHaveText(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
      await expect(page.getByTestId("result-view")).toHaveCount(0);
      await release(page);
      await expect(page.getByTestId("result-summary")).toHaveText("가나다정과 라마바캡슐은 병용금기 목록에 함께 올라 있어요.");
      await expect(page.getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, input(page));
      await expect(sheet(page)).toHaveCount(0); // 좁은 폭에서는 저절로 열리지 않는다
      const entry = page.getByTestId("evidence-entry");
      await expect(entry).toHaveText("근거 상세 보기");
      await expectTouchTarget(entry);
      await entry.click();
      await expect(sheet(page).getByTestId("evidence-section").first()).toBeVisible();
      await expect(sheet(page).getByTestId("fixed-notice")).toHaveCount(0); // 고정 안내는 시트 밖(접히지 않는 영역)
      await expect(sheet(page).getByTestId("source-table")).toBeVisible(); // 출처·기준일
      await expectTouchTarget(sheet(page).getByRole("button", { name: "닫기" }));
      await sheet(page).getByRole("button", { name: "닫기" }).click();
      await expect(sheet(page)).toHaveCount(0);
      await expect(entry).toBeFocused();
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectNoHorizontalScroll(page);
    });
  });
}

test.describe("흐름 360px", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("근거 상세는 들어온 결과에 고정된다: 다른 질문의 상세로 가지 않고, 닫으면 그 결과로 돌아온다", async ({ page }) => {
    await mockChat(page, "found", "pregnancy");
    await openApp(page);
    await ask(page, "첫 질문");
    await expect(page.getByTestId("result-card")).toHaveCount(1);
    await ask(page, "둘째 질문");
    await expect(page.getByTestId("result-card")).toHaveCount(2);
    // 지난 답의 고정 안내는 그 답 아래에 남고, 가장 최근 답의 것은 아래 고정 영역에 있다
    await expect(page.locator('[data-turn="turn-1"]').getByTestId("fixed-notice")).toHaveCount(1);
    await expect(page.locator('[data-turn="turn-2"]').getByTestId("fixed-notice")).toHaveCount(0);
    await expect(dock(page).getByTestId("fixed-notice")).toHaveCount(1);
    const firstEntry = page.locator('[data-turn="turn-1"]').getByTestId("evidence-entry");
    await firstEntry.click();
    await expect(sheet(page).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
    await expect(sheet(page)).not.toContainText("임부금기");
    await expect(firstEntry).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(sheet(page)).toHaveCount(0);
    await expect(firstEntry).toBeFocused();
    await expect(firstEntry).toBeInViewport();
    await page.locator('[data-turn="turn-2"]').getByTestId("evidence-entry").click();
    await expect(sheet(page).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급"]);
  });

  test("되묻기: 후보를 골라도 보내지 않고, 다시 묻기를 눌러야 고른 값을 붙여 같은 질문을 보낸다", async ({ page }) => {
    await mockChat(page, "clarify", "found");
    await openApp(page);
    await ask(page);
    const candidates = page.getByTestId("candidate");
    await expect(candidates).toHaveCount(3);
    await expect(page.getByTestId("result-summary")).toContainText("어떤 약인지 하나를 골라 주세요.");
    await expect(page.getByTestId("result-card")).toHaveCount(0); // 고르기 전에는 판정이 없다
    await expect(page.getByTestId("status-badge")).toHaveCount(0);
    await expectTouchTarget(candidates.first());
    await candidates.nth(1).click();
    await expect(page.getByTestId("picked-name")).toHaveText("가나다정 500밀리그램");
    // 후보는 선택 상태만 바꾼다(G-4)
    await expect(candidates.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(candidates.nth(0)).toHaveAttribute("aria-pressed", "false");
    // 고르기만 했다: 요청은 그대로 한 번, 대화도 한 차례다
    expect(await requests(page)).toHaveLength(1);
    await expect(page.locator("[data-turn]")).toHaveCount(1);
    await candidates.nth(0).click(); // 다시 고를 수 있다
    await expect(page.getByTestId("picked-name")).toHaveText("가나다정 100밀리그램");
    await expect(candidates.nth(0)).toHaveAttribute("aria-pressed", "true");
    await expect(candidates.nth(1)).toHaveAttribute("aria-pressed", "false");
    expect(await requests(page)).toHaveLength(1);
    const resend = page.getByRole("button", { name: "이 약으로 다시 묻기" });
    await expectTouchTarget(resend);
    await resend.click();
    await expect(page.getByTestId("result-card")).toBeVisible();
    const sent = await requests(page);
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual({
      question: QUESTION,
      context: { age: null, pregnant: null, confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] },
    });
    await expect(page.locator("[data-turn]")).toHaveCount(2);
    await expect(page.getByTestId("candidate")).toHaveCount(0); // 지난 되묻기의 후보는 더 고를 수 없다
    await expectNoHorizontalScroll(page);
  });

  test("되묻기: '직접 입력'은 입력창으로 간다", async ({ page }) => {
    await mockChat(page, "clarify");
    await openApp(page);
    await ask(page);
    await page.getByRole("button", { name: "목록에 없어요 · 직접 입력" }).click();
    await expect(page.getByRole("textbox")).toBeFocused();
    expect(await requests(page)).toHaveLength(1);
  });

  test("거절: 거절 문구와 고정 안내만 보이고 결과 카드·근거 상세 진입이 없다", async ({ page }) => {
    await mockChat(page, "refuse");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-summary")).toContainText("복용량은 정해 드릴 수 없어요.");
    await expect(page.getByTestId("result-view")).toHaveAttribute("data-end-reason", "REFUSE");
    await expect(page.getByTestId("result-card")).toHaveCount(0);
    await expect(page.getByTestId("evidence-entry")).toHaveCount(0);
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
    await expect(page.getByTestId("mascot")).toHaveCount(0);
    await expectNoHorizontalScroll(page);
  });

  test("오류: 스스로 다시 보내지 않고, '다시 시도'를 눌렀을 때만 다시 보낸다(F4)", async ({ page }) => {
    await mockChat(page, "http500", "found");
    await openApp(page);
    await ask(page);
    const error = page.getByTestId("error-state");
    await expect(error).toContainText("답을 만들지 못했어요");
    await expect(error.getByTestId("mascot")).toHaveCount(1); // 마스코트는 오류 안내 카드 안에만 있다
    await expect(page.getByTestId("mascot")).toHaveCount(1);
    await expect(error).toContainText(FIXED_NOTICE); // 응답 없는 오류 화면의 고정 안내
    await expect(page.getByTestId("emergency-entry")).toBeVisible(); // 119 접근
    await page.waitForTimeout(300);
    expect(await requests(page)).toHaveLength(1);
    const retry = page.getByRole("button", { name: "다시 시도" });
    await expectTouchTarget(retry);
    await retry.click();
    await expect(page.getByTestId("result-card")).toBeVisible();
    expect(await requests(page)).toHaveLength(2);
    await expect(page.locator("[data-turn]")).toHaveCount(1); // 같은 차례에서 다시 보냈다
    await expectNoHorizontalScroll(page);
  });

  test("오류: 아직 연결되지 않은 서버(501)는 승인 문구를, 형식 오류(422)는 다시 시도 없이 보인다", async ({ page }) => {
    await mockChat(page, "http501", "http422");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toContainText("아직 준비 중이라 답을 드릴 수 없어요. 급하면 약국·약사에게 확인하세요.");
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await ask(page, "둘째 질문");
    const second = page.locator('[data-turn="turn-2"]').getByTestId("error-state");
    await expect(second).toContainText("질문을 다시 적어 보내 주세요.");
    await expect(page.getByRole("button", { name: "다시 시도" })).toHaveCount(0);
  });

  test("끊김: 119는 그대로 남고 부분 결과는 보이지 않는다", async ({ page }) => {
    await mockChat(page, "emergencyCut");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toBeVisible();
    await expect(page.locator("[data-turn]")).toHaveAttribute("data-status", "interrupted");
    await expectInFirstScreen(page, banner(page));
    await expect(page.getByTestId("result-view")).toHaveCount(0);
    await expect(page.getByRole("status", { name: "진행 상태" })).toHaveCount(0);
    await expect(page.getByTestId("mascot")).toHaveCount(0); // 119가 떠 있으면 오류 카드의 마스코트도 숨긴다
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await expect(tel(page)).toHaveCount(1);
  });

  test("끊김(응급 아님): 진행 중에 끊기면 결과 없이 오류만 보인다", async ({ page }) => {
    await mockChat(page, "cutBeforeAnswer");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toBeVisible();
    await expect(page.getByTestId("result-view")).toHaveCount(0);
    await expect(banner(page)).toHaveCount(0);
  });

  test("새 질문: 대화·119를 비우고 시작 화면으로 돌아간다(드로어, 터치 영역 44px)", async ({ page }) => {
    await mockChat(page, "emergency");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    const drawer = page.getByTestId("menu-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("current-chat")).toHaveText(QUESTION);
    await expectTouchTarget(drawer.getByRole("button", { name: "메뉴 닫기" }));
    await expectTouchTarget(drawer.getByTestId("new-chat"));
    // 드로어가 열려 있어도 119 배너는 스크림 밖에 있고 누를 수 있다
    await expectInFirstScreen(page, banner(page));
    await expectOnTop(tel(page));
    const drawerBox = (await drawer.boundingBox())!;
    expect(drawerBox.y).toBeGreaterThanOrEqual((await banner(page).boundingBox())!.y + (await banner(page).boundingBox())!.height - 0.5);
    await drawer.getByTestId("new-chat").click();
    await expect(drawer).toHaveCount(0);
    await expect(page.getByTestId("home")).toBeVisible();
    await expect(banner(page)).toHaveCount(0);
    await expect(page.locator("[data-turn]")).toHaveCount(0);
  });

  test("질문·응답을 브라우저 저장소·쿠키에 남기지 않는다", async ({ page, context }) => {
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    const stored = await page.evaluate(async () => {
      const dump = (storage: Storage) => JSON.stringify(Object.fromEntries(Object.entries(storage)));
      const names = (await indexedDB.databases?.())?.map((db) => db.name) ?? [];
      // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
      // eslint-disable-next-line no-restricted-properties
      return { local: dump(window.localStorage), session: dump(window.sessionStorage), indexed: names };
    });
    for (const text of [stored.local, stored.session]) {
      expect(text).not.toContain("합성 질문");
      expect(text).not.toContain("가나다정");
    }
    expect(stored.indexed).toEqual([]);
    expect(JSON.stringify(await context.cookies())).not.toContain("가나다정");
  });
});

// ============================================================ 결과 모양(디자인 반영본 새 보드, 지시서 A2)
for (const width of [360, 320]) {
  test.describe(`결과 모양 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    const answered = async (page: Page, name: ScenarioName) => {
      await mockChat(page, name);
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-view")).toBeVisible();
    };

    test("배지 두 개(등급 불일치): 잘리지 않고 박스 안에 있다(F3)", async ({ page }) => {
      await answered(page, "gradeMismatch");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
      expect(await expectContained(card, '[data-testid="status-badge"], [data-testid="line-title"]')).toBe(3);
      await page.getByTestId("evidence-entry").click();
      await expectContained(sheet(page), '[data-testid="status-badge"], [data-testid="source-tag"], [data-testid="date-lines"] li');
      await expectNoHorizontalScroll(page);
    });

    test("병용 + 임부: 종류별 배지가 줄마다 보이고 응급 아닌 화면에 119 배너가 없다", async ({ page }) => {
      await answered(page, "pairAndPregnancy");
      await expect(page.getByTestId("status-badge")).toHaveText(["삐! 병용금기", "삐! 임부금기 2등급"]);
      await expect(banner(page)).toHaveCount(0);
      await expectContained(page.getByTestId("result-card"), '[data-testid="status-badge"], [data-testid="line-title"]');
      await expectNoHorizontalScroll(page);
    });

    test("미확보 세 원인: 응답 문구와 약사 확인 권고가 접히지 않고 보인다(Detail-Missing3)", async ({ page }) => {
      await answered(page, "missingCauses");
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]); // 받은 순서: 권고 → 고정
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page).getByTestId("missing-text")).toHaveText([
        "가나다정은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요",
        "라마바캡슐 허가사항에는 이 항목이 따로 적혀 있지 않아요",
        "지금은 허가사항을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요",
      ]);
      const advice = sheet(page).getByTestId("pharmacist-advice");
      await expect(advice).toHaveCount(3);
      await expect(advice.first()).toHaveText("복용 전에 꼭 약국·약사에게 가나다정·라마바캡슐을(를) 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.");
      expect(await sheet(page).locator("details").count()).toBe(0);
      await expect(sheet(page).getByTestId("mascot")).toHaveCount(0);
      await expectContained(sheet(page), '[data-testid="missing-text"], [data-testid="pharmacist-advice"]');
      await expectNoHorizontalScroll(page);
    });

    test("검증 폴백 두 가지: 요약 문구는 응답 값 그대로이고 권고 줄이 고정 영역에 있다(Result-FallbackNone·FallbackSome)", async ({ page }) => {
      await mockChat(page, "fallbackNone", "fallbackSome");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-summary")).toHaveText("검색한 자료에서는 확인하지 못했어요. 정확한 확인은 약국·약사에게 하세요.");
      await expect(page.getByTestId("result-card")).toHaveCount(0);
      await expect(page.getByTestId("evidence-entry")).toHaveCount(0);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await ask(page, "둘째 질문");
      const second = page.locator('[data-turn="turn-2"]');
      await expect(second.getByTestId("result-summary")).toHaveText(
        "공공 자료에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요.",
      );
      await expect(second.getByTestId("result-card")).toBeVisible();
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectNoHorizontalScroll(page);
    });

    test("허가사항 원문 인용: 머리 형식과 원문, 표 없음(Detail-RxPermit)", async ({ page }) => {
      await answered(page, "rxPermit");
      await page.getByTestId("evidence-entry").click();
      const permit = sheet(page).getByTestId("permit-text");
      await expect(permit.locator("b")).toHaveText("가나다정 허가사항 원문(사용상 주의사항)");
      await expect(permit.locator("q")).toContainText("(합성 원문)");
      expect(await permit.locator("table, dl, ul").count()).toBe(0);
      await expect(sheet(page).getByTestId("source-dataset")).toHaveText(["의약품 허가정보", "병용금기 파일"]); // 출처 행 순서 = 응답 순서
      await expectNoHorizontalScroll(page);
    });

    test("연령금기: 판정 줄과 나이 기준 값이 가려지지 않는다(Result-AgeContra, G-7)", async ({ page }) => {
      await answered(page, "ageFound");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 연령금기"]);
      await expect(card.getByText("12세 미만")).toBeVisible();
      expect(await card.evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("약을 찾지 못함: 찾아본 내용의 칸 이름이 한 줄이다(F11)", async ({ page }) => {
      await answered(page, "unidentified");
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await page.getByTestId("evidence-entry").click();
      const pairs = sheet(page).getByTestId("lookup-pairs");
      await expect(pairs).toBeVisible();
      // 칸 이름 글자가 한 줄인가(칸 높이는 옆 값 칸을 따라 늘어나므로 글자가 놓인 줄 수를 센다)
      const labels = await pairs.locator("dt").evaluateAll((els) =>
        els.map((el) => {
          const range = document.createRange();
          range.selectNodeContents(el);
          return { text: el.textContent, lines: new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size };
        }),
      );
      expect(labels).toEqual(["입력한 이름", "찾아본 곳", "못 찾은 이유", "다음에 해 보세요"].map((text) => ({ text, lines: 1 })));
      await expect(sheet(page)).not.toContainText("삐!");
      await expectNoHorizontalScroll(page);
    });

    test("쌍 확인 불가: 배지·'삐!' 없이 확인하지 못했다는 줄과 안전 아님 문장이 접히지 않고 보인다(Result-NoEvidence6c)", async ({ page }) => {
      await answered(page, "pairNoEvidence");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("line-title")).toHaveText("가나다정 · 사아자시럽");
      await expect(card.getByTestId("line-text")).toHaveText("근거 문장을 찾지 못함");
      await expect(card.getByText("이 약과 함께 먹어도 되는지는 식약처·한국의약품안전관리원 자료에서 확인하지 못했어요. 안전하다는 뜻이 아니에요.")).toBeVisible();
      await expect(card.getByTestId("status-badge")).toHaveCount(0);
      await expect(card).not.toContainText("삐!");
      expect(await card.evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("상한 도달·목록에 없음: 안내 줄과 '안전하다는 뜻이 아님'이 접히지 않고 보인다", async ({ page }) => {
      await mockChat(page, "limit", "notListed");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-notice")).toContainText("여기까지 확인한 결과만 보여 드려요.");
      await ask(page, "둘째 질문");
      const second = page.locator('[data-turn="turn-2"]');
      await expect(second.getByTestId("line-text")).toHaveText("금기 목록에 없음(안전하다는 뜻이 아님)");
      await expect(second.getByTestId("status-badge")).toHaveCount(0); // "삐!"는 금기 발견에만
      expect(await second.getByTestId("result-card").evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("글자색과 바탕색이 같지 않다(F5)", async ({ page }) => {
      await answered(page, "found");
      const colors = await page.evaluate(() => {
        const read = (el: Element) => getComputedStyle(el).color;
        return {
          body: getComputedStyle(document.body).backgroundColor,
          summary: read(document.querySelector('[data-testid="result-summary"]')!),
          input: read(document.querySelector("textarea")!),
        };
      });
      expect(colors.summary).not.toBe(colors.body);
      expect(colors.input).not.toBe(colors.body);
    });
  });
}

// ============================================================ 반응형 셸 폭 시험(FE-07-09 B)
const WIDTHS = [1280, 900, 700, 393, 360];
for (const width of WIDTHS) {
  const desktop = width >= 1024;
  test.describe(`셸 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면: 119 진입점·고지·입력창이 첫 화면에 있다(G-3)", async ({ page }) => {
      await openApp(page);
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectTouchTarget(page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      if (desktop) {
        await expect(pushSidebar(page)).toBeVisible();
        await expect(page.getByRole("button", { name: "메뉴 열기" })).toHaveCount(0);
      } else {
        await expect(page.getByTestId("sidebar")).toHaveCount(0);
        await expect(rail(page)).toHaveCount(0);
        await expectTouchTarget(page.getByRole("button", { name: "메뉴 열기" }));
      }
      // 겹침 없음: 119 진입점이 다른 요소에 덮이지 않는다
      await expectOnTop(page.getByTestId("emergency-entry"));
      await expectNoHorizontalScroll(page);
    });

    test("결과: 넓은 폭은 사이드바+가운데 열+우측 패널, 좁은 폭은 ☰ 드로어+시트(진입 글자 G-1)", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      const entry = page.getByTestId("evidence-entry");
      await expect(entry).toHaveText(width >= 700 ? "근거 상세 열기" : "근거 상세 보기");
      await expect(entry).not.toContainText("펼치기");
      if (desktop) {
        // 사이드바 + 가운데 열 + 우측 근거 패널이 겹치지 않고 나란히 있다
        await expect(panel(page)).toBeVisible();
        const side = (await pushSidebar(page).boundingBox())!;
        const mainBox = (await page.getByTestId("main").boundingBox())!;
        const panelBox = (await panel(page).boundingBox())!;
        expect(side.width).toBe(272);
        expect(panelBox.width).toBe(400);
        expect(mainBox.x).toBeGreaterThanOrEqual(side.x + side.width - 0.5);
        expect(panelBox.x).toBeGreaterThanOrEqual(mainBox.x + mainBox.width - 0.5);
        expect(mainBox.width).toBeGreaterThanOrEqual(560);
        await expect(entry).toHaveAttribute("aria-expanded", "true");
        await expect(panel(page).getByTestId("fixed-notice")).toHaveCount(0);
        await expectTouchTarget(panel(page).getByRole("button", { name: "닫기" }));
        await panel(page).getByRole("button", { name: "닫기" }).click();
        await expect(panel(page)).toHaveCount(0);
        await expect(entry).toBeFocused(); // 닫으면 들어온 결과로
        await entry.click();
        await expect(panel(page)).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(panel(page)).toHaveCount(0);
      } else {
        await expect(page.getByTestId("sidebar")).toHaveCount(0);
        await expect(sheet(page)).toHaveCount(0);
        await entry.click();
        await expect(sheet(page).getByTestId("evidence-section").first()).toBeVisible();
        const box = (await sheet(page).boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        await page.keyboard.press("Escape");
        await expect(sheet(page)).toHaveCount(0);
        // ☰ 드로어
        await page.getByRole("button", { name: "메뉴 열기" }).click();
        const drawer = page.getByTestId("menu-drawer");
        await expect(drawer).toBeVisible();
        expect((await drawer.boundingBox())!.width).toBeLessThanOrEqual(320);
        await page.keyboard.press("Escape");
        await expect(drawer).toHaveCount(0);
        await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeFocused();
      }
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, input(page));
      await expectNoHorizontalScroll(page);
    });

    test("응급: 어느 폭에서도 119 배너와 고정 안내가 첫 화면에 있다", async ({ page }) => {
      await mockChat(page, "emergency");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expectInFirstScreen(page, banner(page));
      await expectOnTop(tel(page));
      await expect(tel(page)).toHaveCount(1);
      await expect(page.getByText(EMERGENCY_TEXT)).toHaveCount(1);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      expect(await page.getByTestId("app-shell").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-row");
      await expectNoHorizontalScroll(page);
    });
  });
}

// ============================================================ 사이드바와 근거 상세(FE-07-19·22, 지시서 §8~§11)
/** 스크림이 DOM에 한 번이라도 나타났는지 센다(자동 열림 직후 한 프레임도 보이지 않아야 한다, §11 ⑦) */
async function watchScrim(page: Page) {
  await page.addInitScript(() => {
    const seen = { count: 0 };
    (window as unknown as { __scrim: typeof seen }).__scrim = seen;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node instanceof Element && (node.matches('[data-testid="sidebar-scrim"]') || node.querySelector('[data-testid="sidebar-scrim"]'))) seen.count += 1;
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
}
const scrimSeen = (page: Page) => page.evaluate(() => (window as unknown as { __scrim: { count: number } }).__scrim.count);

async function askAndAutoOpen(page: Page, question = QUESTION) {
  await ask(page, question);
  await expect(panel(page)).toBeVisible();
}

async function expectSafetyVisible(page: Page) {
  // 오버레이·밀기 어느 쪽이든 첫 화면 안에 있다
  await expectInFirstScreen(page, input(page));
  await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
  await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
}

const COLLAPSE_WIDTHS = [1024, 1100, 1180, 1231];
const KEEP_WIDTHS = [1232, 1240, 1279, 1280, 1400];

for (const width of COLLAPSE_WIDTHS) {
  test.describe(`사이드바 ${width}px(근거 상세가 열리면 접힘)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("자동 열림: 레일로 접히고 스크림은 한 번도 생기지 않는다. 다시 펼치면 오버레이+전체 스크림이다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await expect(pushSidebar(page)).toBeVisible(); // 첫 화면은 펼침
      await askAndAutoOpen(page);
      // ① 접힘, dim 없음
      await expect(rail(page)).toBeVisible();
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      await expect(scrim(page)).toHaveCount(0);
      expect(await scrimSeen(page)).toBe(0);
      expect((await rail(page).boundingBox())!.width).toBe(60); // F9
      expect((await panel(page).boundingBox())!.width).toBe(400);
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      expect(width - 60 - 400).toBeGreaterThanOrEqual(560);
      await expectSafetyVisible(page);

      // ② 직후 토글: 오버레이로 펼쳐지고 근거 상세는 닫히지 않는다
      const expand = page.getByRole("button", { name: "사이드바 펼치기" });
      await expectTouchTarget(expand);
      await expand.click();
      await expect(overlaySidebar(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      const scrimBox = (await scrim(page).boundingBox())!;
      const panelBox = (await panel(page).boundingBox())!;
      const body = (await page.getByTestId("shell-body").boundingBox())!;
      expect(scrimBox).toEqual(body); // 스크림이 패널까지 덮는다
      expect(scrimBox.x + scrimBox.width).toBeGreaterThanOrEqual(panelBox.x + panelBox.width - 0.5);
      // 뒤 요소는 조작할 수 없다
      await expect(page.getByTestId("main")).toHaveAttribute("inert", "");
      await expect(page.getByTestId("panel-column")).toHaveAttribute("inert", "");
      expect(await page.evaluate(() => document.elementFromPoint(window.innerWidth - 20, window.innerHeight / 2)?.getAttribute("data-testid"))).toBe("sidebar-scrim");
      // ③ 본문 칸은 그대로(레일 기준)이고 입력창·고정 안내·119가 첫 화면 안에 있다
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      await expectSafetyVisible(page);
      expect((await overlaySidebar(page).boundingBox())!.width).toBe(272);

      // Tab이 오버레이 뒤 요소에 닿지 않는다
      for (let i = 0; i < 6; i += 1) {
        await page.keyboard.press("Tab");
        expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="sidebar"]') !== null)).toBe(true);
      }
      // Esc: 사이드바만 닫히고 근거 상세는 그대로, 초점은 토글 버튼으로
      await page.keyboard.press("Escape");
      await expect(scrim(page)).toHaveCount(0);
      await expect(rail(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      await expect(expand).toBeFocused();
      await expect(page.getByTestId("main")).not.toHaveAttribute("inert", "");

      // 스크림 클릭(패널 위): 사이드바만 닫힌다
      await expand.click();
      await expect(scrim(page)).toBeVisible();
      await page.mouse.click(width - 30, HEIGHT / 2);
      await expect(scrim(page)).toHaveCount(0);
      await expect(panel(page)).toBeVisible();
      // 오버레이 안의 접기 버튼
      await expand.click();
      await expectTouchTarget(overlaySidebar(page).getByRole("button", { name: "사이드바 접기" }));
      await overlaySidebar(page).getByRole("button", { name: "사이드바 접기" }).click();
      await expect(scrim(page)).toHaveCount(0);
      await expect(panel(page)).toBeVisible();
      await expectNoHorizontalScroll(page);
    });

    test("E2: 닫고 사이드바를 펼친 뒤 다시 열면 다시 접힌다(스크림 없음)", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await askAndAutoOpen(page);
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(rail(page)).toBeVisible(); // 닫아도 사이드바는 그대로(접힘)
      await page.getByRole("button", { name: "사이드바 펼치기" }).click();
      await expect(pushSidebar(page)).toBeVisible(); // 패널이 없으면 밀어서 펼친다
      await expect(scrim(page)).toHaveCount(0);
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(rail(page)).toBeVisible();
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      expect(await scrimSeen(page)).toBe(0);
    });
  });
}

for (const width of KEEP_WIDTHS) {
  test.describe(`사이드바 ${width}px(펼침 유지)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("자동 열림: 펼침을 유지하고 밀어서 보인다. 토글은 근거 상세를 닫지 않는다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await askAndAutoOpen(page);
      await expect(pushSidebar(page)).toBeVisible();
      await expect(scrim(page)).toHaveCount(0);
      // 본문이 Wmin 이상이라 문장 중간에서 잘리지 않는다
      const mainBox = (await page.getByTestId("main").boundingBox())!;
      expect(mainBox.width).toBe(width - 272 - 400);
      expect(mainBox.width).toBeGreaterThanOrEqual(560);
      await expectContained(page.getByTestId("main"), '[data-testid="result-summary"], [data-testid="fixed-notice"], [data-testid="status-badge"]');
      await expectSafetyVisible(page);
      // 토글: 접기 → 레일, 펼치기 → 밀기. 근거 상세는 계속 열려 있다
      const collapse = page.getByRole("button", { name: "사이드바 접기" });
      await expectTouchTarget(collapse);
      await collapse.click();
      await expect(rail(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      await page.getByRole("button", { name: "사이드바 펼치기" }).click();
      await expect(pushSidebar(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      // 근거 상세를 닫았다 다시 열어도 사이드바는 그대로다(E2: 1232 이상 유지)
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(pushSidebar(page)).toBeVisible();
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(pushSidebar(page)).toBeVisible();
      expect(await scrimSeen(page)).toBe(0);
      await expectNoHorizontalScroll(page);
    });
  });
}

for (const width of [1100, 1280, 1400]) {
  test.describe(`사이드바 독립 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("사용자가 접어 둔 사이드바는 근거 상세를 열고 닫아도 접힌 그대로다", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await page.getByRole("button", { name: "사이드바 접기" }).click();
      await expect(rail(page)).toBeVisible();
      await askAndAutoOpen(page);
      await expect(rail(page)).toBeVisible();
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(rail(page)).toBeVisible();
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(rail(page)).toBeVisible();
      await expect(scrim(page)).toHaveCount(0);
    });

    test("E3: 근거 상세가 열린 채 연속 질문을 보내도 사이드바가 바뀌지 않고, 상세는 새 답으로 바뀐다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found", "pregnancy");
      await openApp(page);
      await askAndAutoOpen(page, "첫 질문");
      const before = await pushSidebar(page).count();
      await ask(page, "둘째 질문");
      await expect(panel(page).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급"]);
      expect(await pushSidebar(page).count()).toBe(before);
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("evidence-entry")).toHaveAttribute("aria-expanded", "true");
      await expect(page.locator('[data-turn="turn-1"]').getByTestId("evidence-entry")).toHaveAttribute("aria-expanded", "false");
      expect(await scrimSeen(page)).toBe(0);
    });
  });
}

test.describe("사이드바 엣지 1100px", () => {
  test.use({ viewport: { width: 1100, height: HEIGHT } });

  test("E4: '새 질문' 뒤 다음 답에서 다시 판정한다", async ({ page }) => {
    await watchScrim(page);
    await mockChat(page, "found");
    await openApp(page);
    await askAndAutoOpen(page);
    await expect(rail(page)).toBeVisible();
    await expectTouchTarget(rail(page).getByRole("button", { name: "새 질문" }));
    await rail(page).getByRole("button", { name: "새 질문" }).click();
    await expect(page.getByTestId("home")).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
    await page.getByRole("button", { name: "사이드바 펼치기" }).click();
    await expect(pushSidebar(page)).toBeVisible();
    await askAndAutoOpen(page);
    await expect(rail(page)).toBeVisible();
    expect(await scrimSeen(page)).toBe(0);
  });

  test("E7: 되묻기 답에서는 패널을 열지 않고 사이드바도 그대로다(패널에 넣을 응답 값이 없다)", async ({ page }) => {
    await mockChat(page, "clarify");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("candidate-card")).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
    await expect(pushSidebar(page)).toBeVisible();
    await expect(scrim(page)).toHaveCount(0);
  });

  test("응급 + 오버레이: 119 배너는 스크림 밖에 있어 가려지지 않고 누를 수 있다", async ({ page }) => {
    await mockChat(page, "emergency");
    await openApp(page);
    await askAndAutoOpen(page);
    await page.getByRole("button", { name: "사이드바 펼치기" }).click();
    await expect(scrim(page)).toBeVisible();
    await expectInFirstScreen(page, banner(page));
    await expectOnTop(tel(page));
    const bannerBox = (await banner(page).boundingBox())!;
    expect((await scrim(page).boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
    expect((await overlaySidebar(page).boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
    await expectInFirstScreen(page, input(page));
  });
});

test.describe("사이드바 엣지: 폭 변경", () => {
  test("E5: 근거 상세가 열린 채 1300 → 1100으로 줄이면 접지 않고 오버레이+스크림이 된다(스크림 클릭으로 사이드바만 닫힘)", async ({ page }) => {
    await page.setViewportSize({ width: 1300, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await askAndAutoOpen(page);
    await expect(pushSidebar(page)).toBeVisible();
    await page.setViewportSize({ width: 1100, height: HEIGHT });
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(scrim(page)).toBeVisible();
    await expect(panel(page)).toBeVisible();
    await page.mouse.click(1100 - 30, HEIGHT / 2);
    await expect(scrim(page)).toHaveCount(0);
    await expect(rail(page)).toBeVisible();
    await expect(panel(page)).toBeVisible();
    // 다시 넓혀도 사용자 상태(접힘)는 그대로다
    await page.setViewportSize({ width: 1300, height: HEIGHT });
    await expect(rail(page)).toBeVisible();
  });

  test("E6: 1000에서 근거 상세를 연 뒤 1100으로 넓히면 패널+오버레이가 되고 Esc로 사이드바만 닫힌다", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    await page.setViewportSize({ width: 1100, height: HEIGHT });
    await expect(panel(page)).toBeVisible();
    await expect(sheet(page)).toHaveCount(0);
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(scrim(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(scrim(page)).toHaveCount(0);
    await expect(panel(page)).toBeVisible();
    await expect(rail(page)).toBeVisible();
  });

  test("F10: 1023 ↔ 1024에서 드로어 ↔ 사이드바, 시트 ↔ 패널로 바뀌고 같은 요소(119·고정 안내·입력창·결과)가 양쪽에 있다", async ({ page }) => {
    await page.setViewportSize({ width: 1023, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    const same = async () => {
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expectNoHorizontalScroll(page);
    };
    // 1023: ☰ 드로어, 근거 상세는 시트
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeVisible();
    await expect(page.getByTestId("sidebar")).toHaveCount(0);
    await same();
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet(page)).toHaveCount(0);
    // 1024: 사이드바 칸, 근거 상세는 우측 패널
    await page.setViewportSize({ width: 1024, height: HEIGHT });
    await expect(pushSidebar(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toHaveCount(0);
    await same();
    await page.getByTestId("evidence-entry").click();
    await expect(panel(page)).toBeVisible();
    await expect(sheet(page)).toHaveCount(0);
    await expect(rail(page)).toBeVisible(); // 새로 열렸으므로 1024에서는 접힌다
    await panel(page).getByRole("button", { name: "닫기" }).click();
    // 다시 1023: 사이드바 칸이 사라지고 ☰로 돌아온다
    await page.setViewportSize({ width: 1023, height: HEIGHT });
    await expect(rail(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeVisible();
    await same();
  });

  test("1023 이하: 768~1023도 사이드바 없이 ☰ 드로어이고 본문이 화면 폭을 다 쓴다(참고 ③)", async ({ page }) => {
    await mockChat(page, "found");
    for (const width of [768, 831, 1023]) {
      await page.setViewportSize({ width, height: HEIGHT });
      await openApp(page);
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      await expect(rail(page)).toHaveCount(0);
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect(panel(page)).toHaveCount(0);
      await expectContained(page.getByTestId("main"), '[data-testid="result-summary"], [data-testid="fixed-notice"], [data-testid="status-badge"]');
      await expectNoHorizontalScroll(page);
    }
  });
});

// ============================================================ 실제 MSW 워커 연결(선택)
// `NEXT_PUBLIC_API_MOCKING=enabled`로 띄운 서버 주소를 E2E_MSW_BASE_URL로 주면 돈다. 질문의 표시 글자(`mock:`)로 시나리오를 고른다.
test.describe("MSW 워커 연결", () => {
  const base = process.env.E2E_MSW_BASE_URL ?? "";
  test.skip(base === "", "E2E_MSW_BASE_URL이 없으면 건너뛴다");
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("워커가 스트림으로 답한다: 응급은 119가 맨 위, 일반 질문은 결과와 근거 상세", async ({ page }) => {
    await openApp(page, base);
    await ask(page, "mock:응급 합성 질문");
    await expect(banner(page)).toBeVisible();
    await expect(page.getByTestId("result-card")).toBeVisible();
    await expectInFirstScreen(page, banner(page));
    await ask(page, "mock:미식별 합성 질문");
    await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
    await ask(page, "mock:501 합성 질문");
    await expect(page.getByTestId("error-state")).toContainText("아직 준비 중이라 답을 드릴 수 없어요.");
    expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  });
});
