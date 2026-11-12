import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { scenarios } from "../src/mocks/fixtures/scenarios";
import type { ScenarioName } from "../src/mocks/fixtures/scenarios";

// 브랜드 이미지가 실제로 불러와지는지, 금지 영역에 마스코트가 없는지(통신은 Playwright가 합성 fixture로 대신 답한다).
const VIEWPORTS = [
  { width: 360, height: 800 },
  { width: 320, height: 800 },
];

async function mockChat(page: Page, name: ScenarioName, delayMs = 0) {
  await page.route("**/api/chat", async (route) => {
    const scenario = scenarios[name];
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (scenario.kind === "http") return route.fulfill({ status: scenario.status, body: "" });
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body: scenario.events.map((event) => `${JSON.stringify(event)}\n`).join(""),
    });
  });
}

async function expectLoaded(image: Locator) {
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(0);
}

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

async function ask(page: Page, question: string) {
  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: "보내기" }).click();
}

for (const viewport of VIEWPORTS) {
  test.describe(`브랜드 ${viewport.width}px`, () => {
    test.use({ viewport });

    test("시작 화면: 마스코트와 로고 심볼이 보이고 가로 스크롤이 없다", async ({ page }) => {
      await page.goto("/dev/preview/chat");
      const mascot = page.getByTestId("mascot");
      await expect(mascot).toHaveAttribute("data-variant", "question");
      await expectLoaded(mascot);
      await expectLoaded(page.getByTestId("brand-logo").locator("img"));
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Can I PPiyak");
      const input = await page.getByRole("textbox").boundingBox();
      expect(input!.y + input!.height).toBeLessThanOrEqual(viewport.height); // 그림이 들어가도 입력창은 첫 화면
      await expectNoHorizontalScroll(page);
    });

    test("진행 표시: 답을 기다리는 동안 돋보기 마스코트가 보이고, 결과가 오면 사라진다", async ({ page }) => {
      await mockChat(page, "found", 1200);
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문");
      const mascot = page.getByRole("status").getByTestId("mascot");
      await expect(mascot).toHaveAttribute("data-variant", "search");
      await expectLoaded(mascot);
      await expect(page.getByTestId("result-slot")).toBeVisible();
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expect(page.getByTestId("result-slot").locator("img")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("응급: 119 영역 안에 마스코트가 없고 진행 표시 마스코트도 사라진다", async ({ page }) => {
      await mockChat(page, "emergency", 600);
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문");
      await expect(page.getByRole("status").getByTestId("mascot")).toBeVisible(); // 119가 오기 전
      const alert = page.getByTestId("emergency-slot");
      await expect(alert).toBeVisible();
      await expect(alert.locator("img")).toHaveCount(0);
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("오류: 안내 카드에만 마스코트가 있고 고정 안내 영역에는 없다", async ({ page }) => {
      await mockChat(page, "http500");
      await page.goto("/dev/preview/chat");
      await ask(page, "합성 질문");
      const error = page.getByTestId("error-state");
      await expect(error).toBeVisible();
      await expect(error.getByTestId("mascot")).toHaveCount(1);
      await expectLoaded(error.getByTestId("mascot"));
      await expectNoHorizontalScroll(page);
    });
  });
}

test("브랜드 미리보기: 모든 이미지가 불러와지고 금지 영역 시연에는 의약품 아이콘만 있다", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dev/preview/brand");
  await expect(page.getByTestId("brand-row")).toHaveCount(4);
  // 화면 밖 그림은 늦게 불러오므로 하나씩 화면에 들여 불러오게 한다(속성을 바꾸면 hydration 경고가 난다)
  const images = page.locator("img");
  const count = await images.count();
  expect(count).toBeGreaterThan(60);
  for (let i = 0; i < count; i += 1) await images.nth(i).scrollIntoViewIfNeeded();
  await expect
    .poll(() => page.evaluate(() => [...document.querySelectorAll("img")].filter((img) => !img.complete || img.naturalWidth === 0).map((img) => img.getAttribute("src"))))
    .toEqual([]);
  const broken: string[] = [];
  expect(broken).toEqual([]);
  const demo = page.getByTestId("no-mascot-demo");
  await expect(demo.getByTestId("mascot")).toHaveCount(0);
  await expect(demo.getByTestId("med-icon")).toHaveCount(2);
  await expectNoHorizontalScroll(page);
});

test("favicon·앱 아이콘·manifest가 제공된다", async ({ page, request }) => {
  await page.goto("/");
  const icon = await page.locator('link[rel="icon"]').first().getAttribute("href");
  const apple = await page.locator('link[rel="apple-touch-icon"]').first().getAttribute("href");
  const manifest = await page.locator('link[rel="manifest"]').first().getAttribute("href");
  for (const href of [icon, apple]) {
    const response = await request.get(href!);
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/png");
  }
  const body = await (await request.get(manifest!)).json();
  expect(body.name).toBe("Can I PPiyak");
  expect(body.icons.map((i: { sizes: string }) => i.sizes)).toEqual(["192x192", "512x512"]);
  for (const item of body.icons) expect((await request.get(item.src)).ok()).toBe(true);
});
