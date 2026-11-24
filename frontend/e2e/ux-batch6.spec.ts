import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { HEIGHT, ask, expectNoHorizontalScroll, mockChat, openApp, waitHeld } from "./helpers";

// FE-17 UI/UX 다듬기 6차(U-24, U-18 추가 지시)를 목 통신 대역으로 본다. 393·1280 × 라이트·다크(+ 360 좁은 폭).
// - U-24: 진행 표시 세 단계가 병아리 오른쪽 세로 목록, 바깥 노란 상자 없음, 완료 = 체크 그대로·진행 중 = 굵은 글자 + 글자 쉬머·예정 = 불투명도 55%.
//   움직임 줄이기면 쉬머·스피너가 멈춘다. 통신은 `typoCorrected`(진행 2개 → 답)를 답 앞에서 멈춰 `완료·진행 중·예정`을 한 화면에 둔다
// - U-18 추가: 1280에서 열린 근거 상세가 900으로 줄면 닫히고(시트로 본문을 덮지 않음), 다시 1280으로 넓혀도 닫힌 채
// 캡처: `FE_UX_BATCH6_SHOT_DIR`을 주면 `ux-batch6-{width}-{scheme}-{장면}.png`를 남긴다(쉬머는 가운데 지점에서 멈춘 정지 프레임)
const SHOT_DIR = process.env.FE_UX_BATCH6_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  if (target) await target.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
  else await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
/** 쉬머를 띠가 글자 가운데를 지나는 순간에 멈춘다(정지 프레임 캡처용). 스피너도 멈춘다 */
const freezeShimmer = (page: Page) =>
  page.addStyleTag({ content: ".progress-shimmer{animation-play-state:paused!important;animation-delay:-0.9s!important}.animate-spin{animation-play-state:paused!important}" });

const progress = (page: Page) => page.getByRole("status", { name: "진행 상태" });
const steps = (page: Page) => progress(page).getByRole("listitem");
const box = async (locator: Locator) => (await locator.boundingBox())!;
const panel = (page: Page) => page.getByTestId("panel-column");
const sheet = (page: Page) => page.getByRole("dialog", { name: "근거 상세" });

/** 진행 표시를 `완료·진행 중·예정`으로 멈춘다 */
async function holdMidProgress(page: Page) {
  await mockChat(page, { name: "typoCorrected", holdBefore: "answer" });
  await openApp(page);
  await ask(page);
  await waitHeld(page);
  await expect(progress(page)).toBeVisible();
  await expect.poll(() => steps(page).evaluateAll((items) => items.map((li) => li.getAttribute("data-state")))).toEqual(["done", "now", "todo"]);
}

/** U-24 배치 검사: 마스코트 오른쪽·세로·한 줄·상자 없음·가로 넘침 없음 */
async function expectSideLayout(page: Page) {
  const root = progress(page);
  const mascot = await box(root.getByTestId("mascot"));
  const list = root.getByTestId("progress-step-list");
  const listBox = await box(list);
  expect(listBox.x).toBeGreaterThanOrEqual(mascot.x + mascot.width); // 오른쪽
  // 세로 중앙 정렬(자연스러운 범위: 중심 차이 12px 이내)
  expect(Math.abs(listBox.y + listBox.height / 2 - (mascot.y + mascot.height / 2))).toBeLessThanOrEqual(12);
  const rows = await Promise.all((await steps(page).all()).map(box));
  for (let i = 1; i < rows.length; i++) expect(rows[i].y).toBeGreaterThan(rows[i - 1].y + rows[i - 1].height - 1); // 세로로 쌓임
  for (const row of rows) expect(row.height).toBeLessThanOrEqual(26); // 줄바꿈 없음(한 줄 20~22px)
  // 바깥 상자 없음: 목록과 진행 표시 뿌리 모두 바탕·테두리가 없다
  for (const target of [root, list]) {
    const style = await target.evaluate((el) => {
      const s = getComputedStyle(el);
      return { bg: s.backgroundColor, border: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth].join(" ") };
    });
    expect(style.bg).toBe("rgba(0, 0, 0, 0)");
    expect(style.border).toBe("0px 0px 0px 0px");
  }
  // 단계 줄이 화면 안에 다 들어온다
  const viewport = page.viewportSize()!;
  for (const row of rows) expect(row.x + row.width).toBeLessThanOrEqual(viewport.width);
  await expectNoHorizontalScroll(page);
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 6 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch6-${width}-${scheme}`;

      test("U-24: 세 단계는 병아리 오른쪽 세로 목록이고 노란 상자가 없다. 완료·진행 중·예정이 구분된다", async ({ page }) => {
        await holdMidProgress(page);
        await expectSideLayout(page);
        const [done, now, todo] = await steps(page).all();
        // 완료: 기존 체크 표시(노란 원 + 체크), 불투명도 1
        await expect(done.locator(".bg-yellow svg")).toHaveCount(1);
        expect(await done.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
        // 진행 중: 굵은 글자 + 줄 스피너 + 글자 쉬머(움직임)
        const nowText = now.getByTestId("progress-step-text");
        expect(Number(await now.evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(700);
        expect(await nowText.evaluate((el) => getComputedStyle(el).animationName)).toBe("progress-shimmer");
        expect(await now.locator(".animate-spin").evaluate((el) => getComputedStyle(el).animationName)).not.toBe("none");
        expect(await now.getAttribute("aria-current")).toBe("step");
        // 예정: 낮은 불투명도
        expect(await todo.evaluate((el) => getComputedStyle(el).opacity)).toBe("0.55");
        expect(await todo.getByTestId("progress-step-text").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
        // 새 글자 없음
        expect(await steps(page).allTextContents()).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
        await freezeShimmer(page);
        await shot(page, `${base}-progress`);
        await shot(page, `${base}-progress-close`, progress(page));
      });

      test("U-24: 움직임 줄이기에서는 쉬머·스피너가 멈추고 굵은 글자·표지로 구분한다", async ({ page }) => {
        await page.emulateMedia({ reducedMotion: "reduce" });
        await holdMidProgress(page);
        const now = steps(page).nth(1);
        const nowText = now.getByTestId("progress-step-text");
        expect(await nowText.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
        // 글자는 투명이 아니라 본문색으로 보인다
        expect(await nowText.evaluate((el) => getComputedStyle(el).webkitTextFillColor)).not.toBe("rgba(0, 0, 0, 0)");
        expect(await now.locator(".animate-spin").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
        expect(Number(await now.evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(700);
        await expectSideLayout(page);
        await shot(page, `${base}-progress-reduced`, progress(page));
      });

      if (width === 1280) {
        test("U-18 추가: 근거 상세가 열린 채 1280 → 900이면 닫히고, 다시 1280으로 넓혀도 닫힌 채다(nav는 다시 펼쳐짐)", async ({ page }) => {
          await mockChat(page, "found");
          await openApp(page);
          await ask(page);
          await expect(panel(page)).toBeVisible(); // 넓은 폭에서 판정 답이 오면 자동으로 열린다
          await shot(page, `${base}-evidence-open`);
          await page.setViewportSize({ width: 900, height: HEIGHT });
          await expect(panel(page)).toHaveCount(0);
          await expect(sheet(page)).toHaveCount(0); // 시트로 본문을 덮지 않는다
          await expect(page.getByTestId("result-card")).toBeVisible();
          await expectNoHorizontalScroll(page);
          await shot(page, `${base}-evidence-auto-closed-900`);
          await page.setViewportSize({ width: 1280, height: HEIGHT });
          await expect(page.getByTestId("sidebar")).toBeVisible(); // nav는 넓어지면 다시 펼쳐진다(기존 U-18)
          await expect(panel(page)).toHaveCount(0); // 근거 상세는 OFF 유지
          await expect(sheet(page)).toHaveCount(0);
          await shot(page, `${base}-evidence-stays-closed-1280`);
          // 사용자가 직접 다시 열 수 있다
          await page.getByTestId("evidence-entry").click();
          await expect(panel(page)).toBeVisible();
        });

        test("U-18 추가: 좁은 폭에서 직접 연 근거 상세 시트는 폭이 더 변해도 닫지 않는다(넓어지면 우측 패널)", async ({ page }) => {
          await page.setViewportSize({ width: 900, height: HEIGHT });
          await mockChat(page, "found");
          await openApp(page);
          await ask(page);
          await page.getByTestId("evidence-entry").click();
          await expect(sheet(page)).toBeVisible();
          await page.setViewportSize({ width: 700, height: HEIGHT });
          await expect(sheet(page)).toBeVisible();
          await page.setViewportSize({ width: 1280, height: HEIGHT });
          await expect(panel(page)).toBeVisible();
          await expect(sheet(page)).toHaveCount(0);
        });
      }
    });
  }
}

test.describe("FE-17 UX 묶음 6 · 360px", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });
  test("U-24: 360px에서도 줄바꿈·가로 넘침 없이 병아리 오른쪽에 세 단계가 있다", async ({ page }) => {
    await holdMidProgress(page);
    await expectSideLayout(page);
    await freezeShimmer(page);
    await shot(page, "ux-batch6-360-light-progress");
  });
});
