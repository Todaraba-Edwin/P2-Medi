import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { scenarios } from "../src/mocks/fixtures/scenarios";
import type { ScenarioName } from "../src/mocks/fixtures/scenarios";

// 채팅 미리보기(/dev/preview/chat)의 폭 시험. 통신은 Playwright가 합성 fixture로 대신 답한다(MSW 스위치와 무관).
const VIEWPORTS = [
  { width: 360, height: 800 },
  { width: 320, height: 800 },
];
const MIN_TOUCH = 44;

async function mockChat(page: Page, name: ScenarioName) {
  await page.route("**/api/chat", async (route) => {
    const scenario = scenarios[name];
    if (scenario.kind === "http") return route.fulfill({ status: scenario.status, body: "" });
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body: scenario.events.map((event) => `${JSON.stringify(event)}\n`).join(""),
    });
  });
}

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

/** 요소가 스크롤 없이 첫 화면 안에 다 들어와 있는가 */
async function expectInFirstScreen(page: Page, selector: ReturnType<Page["locator"]>) {
  const box = await selector.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
}

async function ask(page: Page, question: string) {
  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: "보내기" }).click();
}

for (const viewport of VIEWPORTS) {
  test.describe(`채팅 ${viewport.width}px`, () => {
    test.use({ viewport });

    test("시작 화면: 입력창이 첫 화면에 있고 가로 스크롤이 없다", async ({ page }) => {
      await page.goto("/dev/preview/chat");
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Can I PPiyak");
      await expectInFirstScreen(page, page.getByRole("textbox"));
      const send = await page.getByRole("button", { name: "보내기" }).boundingBox();
      expect(send!.width).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(send!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      for (const chip of await page.getByRole("list").getByRole("button").all()) {
        expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      }
      await expectNoHorizontalScroll(page);
    });

    test("질문 뒤: 결과 자리가 보이고 입력창은 첫 화면에 남는다", async ({ page }) => {
      await mockChat(page, "found");
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문 가나다정과 라마바캡슐을 같이 먹어도 되나요 아주 긴 질문 문장을 넣어 줄바꿈을 확인한다");
      await expect(page.getByTestId("result-slot")).toBeVisible();
      await expectInFirstScreen(page, page.getByRole("textbox"));
      await expectNoHorizontalScroll(page);
    });

    test("응급: 119 자리가 스크롤 없이 첫 화면 맨 위에 있다", async ({ page }) => {
      await mockChat(page, "emergency");
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문");
      // Next.js의 경로 안내 요소도 role=alert라서 자리 부품은 testid로 집는다
      const alert = page.getByTestId("emergency-slot");
      await expect(alert).toBeVisible();
      await expect(alert).toHaveAttribute("role", "alert");
      await expectInFirstScreen(page, alert);
      const link = alert.getByRole("link");
      await expect(link).toHaveAttribute("href", "tel:119");
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      const thread = await page.getByTestId("chat-thread").boundingBox();
      expect((await alert.boundingBox())!.y).toBeLessThan(thread!.y); // 대화보다 위
      await expectInFirstScreen(page, page.getByRole("textbox"));
      await expectNoHorizontalScroll(page);
    });

    test("오류: 다시 시도 버튼이 44px 이상이고 가로 스크롤이 없다", async ({ page }) => {
      await mockChat(page, "http500");
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문");
      await expect(page.getByTestId("error-state")).toBeVisible();
      const retry = await page.getByRole("button", { name: "다시 시도" }).boundingBox();
      expect(retry!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      await expectInFirstScreen(page, page.getByRole("textbox"));
      await expectNoHorizontalScroll(page);
    });
  });
}
