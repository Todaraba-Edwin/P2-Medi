import { expect, test } from "@playwright/test";
import { HEIGHT, ask, banner, expectInFirstScreen, openApp } from "./helpers";

// 실제 MSW 워커 연결(FE-IMPL-06b: 공식 e2e에 포함). Playwright 프로젝트 `msw-worker`가 `NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드(3110)에 붙는다.
// 페이지 안 fetch 대역 없이 브라우저 워커(src/mocks/handlers.ts)가 답한다. 질문의 표시 글자(`mock:`)로 시나리오를 고른다.
test.use({ viewport: { width: 360, height: HEIGHT } });

test("워커가 스트림으로 답한다: 응급은 119가 맨 위, 일반 질문은 결과와 근거 상세", async ({ page }) => {
  await openApp(page);
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  await ask(page, "mock:응급 합성 질문");
  await expect(banner(page)).toBeVisible();
  await expect(page.getByTestId("result-card")).toBeVisible();
  await expectInFirstScreen(page, banner(page));
  await ask(page, "mock:미식별 합성 질문");
  await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
  await ask(page, "mock:501 합성 질문");
  await expect(page.getByTestId("error-state")).toContainText("아직 준비 중이라 답을 드릴 수 없어요.");
});

test("되묻기 → 후보 선택 → 다시 묻기: 워커가 confirmed_drugs를 보고 되묻기 대신 결과로 답한다", async ({ page }) => {
  const bodies: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat")) bodies.push(request.postDataJSON());
  });
  await openApp(page);
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  const question = "mock:되묻기 합성 질문";
  await ask(page, question);
  const candidates = page.getByTestId("candidate");
  await expect(candidates).toHaveCount(3);
  await candidates.nth(0).click();
  await expect(candidates.nth(0)).toHaveAttribute("aria-pressed", "true");
  expect(bodies).toHaveLength(1); // 고르기만 하면 보내지 않는다
  await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
  const second = page.locator('[data-turn="turn-2"]');
  await expect(second.getByTestId("result-card")).toBeVisible();
  await expect(second.getByTestId("candidate-card")).toHaveCount(0); // 되묻기가 되풀이되지 않는다
  await expect(second.getByTestId("result-view")).toHaveAttribute("data-end-reason", "NORMAL");
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual({
    question,
    context: { age: null, pregnant: null, confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] },
  });
});

test("여러 약 되묻기(FE-09): 워커가 이름별 묶음 둘을 주고, 둘 다 골라 한 번 보내면 결과로 답한다", async ({ page }) => {
  const bodies: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat")) bodies.push(request.postDataJSON());
  });
  await openApp(page);
  const question = "mock:되묻기여러 합성 질문";
  await ask(page, question);
  const groups = page.getByTestId("candidate-group");
  await expect(groups).toHaveCount(2);
  const resend = page.getByRole("button", { name: "이 약들로 확인하기" });
  await expect(resend).toHaveAttribute("aria-disabled", "true");
  await groups.nth(0).getByTestId("candidate").nth(0).click();
  await expect(resend).toHaveAttribute("aria-disabled", "true");
  await groups.nth(1).getByTestId("candidate").nth(1).click();
  await expect(resend).not.toHaveAttribute("aria-disabled", "true");
  expect(bodies).toHaveLength(1); // 고르기만 하면 보내지 않는다
  await resend.click();
  const second = page.locator('[data-turn="turn-2"]');
  await expect(second.getByTestId("result-card")).toBeVisible();
  await expect(second.getByTestId("result-view")).toHaveAttribute("data-end-reason", "NORMAL");
  expect(bodies).toHaveLength(2); // 요청은 한 번 더뿐이다
  expect(bodies[1]).toEqual({
    question,
    context: {
      age: null,
      pregnant: null,
      confirmed_drugs: [
        { name: "가나다정 100밀리그램", item_seq: "200000001" },
        { name: "가나다시럽 키즈", item_seq: "200000004" },
      ],
    },
  });
});
