import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, expectNoHorizontalScroll, openApp } from "./helpers";

// 합성 데이터 데모 표시(BE-13-07 A, 원문 승인 2026-11-22). Playwright 프로젝트 `msw-worker`(`NEXT_PUBLIC_API_MOCKING=enabled` 운영 빌드)에서만 돈다:
// - 머리줄(top-bar) 바로 아래 한 줄, 승인 원문 그대로, 한 번만. 마스코트(img·svg) 없음
// - 라이트·다크(토큰 색만)에서 글자 대비 4.5:1 이상, 가로 스크롤 없음
// 실서버 모드(`app` 프로젝트)에서 DOM에 없는 것은 `demo-notice.spec.ts`가 본다.
// 캡처: `L6_SHOT_DIR`을 주면 `l6-demo-notice-{light|dark}-{폭}.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`)
const NOTICE = "합성 데이터 데모예요. 화면의 약 이름·판정은 실제 의약품 정보가 아니에요.";
const SHOT_DIR = process.env.L6_SHOT_DIR;

const notice = (page: Page) => page.getByTestId("demo-notice");

async function expectNoticeUnderHeader(page: Page) {
  await openApp(page);
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  await expect(notice(page)).toHaveCount(1);
  await expect(notice(page)).toBeVisible();
  await expect(notice(page)).toHaveText(NOTICE);
  await expect(notice(page)).toHaveAttribute("role", "note");
  await expect(notice(page).locator("img, svg")).toHaveCount(0);
  const [header, line] = await Promise.all([page.getByTestId("top-bar").boundingBox(), notice(page).boundingBox()]);
  expect(header!.y + header!.height).toBeLessThanOrEqual(line!.y + 1); // 머리줄 아래
  await expectNoHorizontalScroll(page);
}

/** `measureContrast`는 루트의 자손만 훑으므로 화면 전체를 재고 이 줄(`testId === "demo-notice"`)의 표본만 본다 */
async function expectAA(page: Page, label: string) {
  const report = await measureContrast(page);
  expect(report.unmeasured.filter((text) => NOTICE.startsWith(text)), `${label}: 바탕색을 정할 수 없는 글자`).toEqual([]);
  const mine = report.samples.filter((sample) => sample.testId === "demo-notice");
  expect(mine.length).toBeGreaterThan(0);
  expect(failures({ ...report, samples: mine }), `${label}: 기준(${AA_NORMAL}:1) 미달 글자`).toEqual([]);
}

const shot = async (page: Page, scheme: "light" | "dark") => {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, `l6-demo-notice-${scheme}-${page.viewportSize()!.width}.png`) });
};

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`합성 데이터 데모 표시 ${scheme} ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("목 빌드에서 머리줄 아래 승인 원문 한 줄이 보이고 글자 대비가 기준 이상이다", async ({ page }) => {
        await expectNoticeUnderHeader(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await expectAA(page, `${scheme} ${width}`);
        await shot(page, scheme);
      });
    });
  }
}
