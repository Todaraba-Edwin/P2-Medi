import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, ask, expectNoHorizontalScroll, mockChat, openApp, release, waitHeld } from "./helpers";

// 첫 `progress` 이벤트 전(`stage=null`) 대기 표시(BE-17-04 A): 단계 줄 밖의 글자 없는 스피너, 움직임 줄이기에서는 멈춘 점.
// 통신 대역은 mock 시나리오를 첫 `progress` 앞(`holdBefore: "progress"`)이나 답 앞에서 멈춘 것이다. 전이의 단위 시험은 parts.test.tsx.
// 캡처: `BE17_SHOT_DIR`을 주면 그 폴더에 `*-be17.png`를 남긴다(로컬 전용 폴더. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.BE17_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-be17.png`) });
};

const progress = (page: Page) => page.getByRole("status", { name: "진행 상태" });
const waiting = (page: Page) => page.getByTestId("progress-waiting");
const spinner = (page: Page) => page.getByTestId("progress-waiting-spinner");
const still = (page: Page) => page.getByTestId("progress-waiting-still");
const states = (page: Page) => progress(page).getByRole("listitem").evaluateAll((items) => items.map((li) => li.getAttribute("data-state")));
const animation = (page: Page, testId: string) => page.getByTestId(testId).evaluate((el) => getComputedStyle(el).animationName);

for (const width of [393, 1280]) {
  test.describe(`대기 표시 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("첫 진행 이벤트 전: 단계 줄은 모두 대기, 줄 밖에서 스피너가 돈다", async ({ page }) => {
      await mockChat(page, { name: "found", holdBefore: "progress" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      await expect(spinner(page)).toBeVisible();
      await expect(still(page)).toBeHidden();
      expect(await animation(page, "progress-waiting-spinner")).toBe("spin");
      expect(await states(page)).toEqual(["todo", "todo", "todo"]); // 어느 단계도 주장하지 않는다
      await expect(progress(page).getByRole("listitem")).toHaveText(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
      await expect(waiting(page)).toHaveText(""); // 새 글자 없음
      expect(await waiting(page).evaluate((el) => el.closest("ol") === null && el.querySelector("img") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
      await shot(page, "progress-wait-null");
      await release(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect(waiting(page)).toHaveCount(0);
    });

    test("움직임 줄이기: 스피너 대신 멈춘 점 3개", async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await mockChat(page, { name: "found", holdBefore: "progress" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      await expect(still(page)).toBeVisible();
      await expect(spinner(page)).toBeHidden();
      await expect(still(page).locator("span")).toHaveCount(3);
      expect(await animation(page, "progress-waiting-still")).toBe("none");
      await shot(page, "progress-wait-null-reduced");
    });

    test("진행 이벤트가 온 뒤: 대기 표시는 없고 지금 줄에만 스피너가 있다", async ({ page }) => {
      await mockChat(page, { name: "found", holdBefore: "answer" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      await expect(progress(page)).toBeVisible();
      await expect(waiting(page)).toHaveCount(0);
      expect(await states(page)).toEqual(["done", "done", "now"]);
      await expect(progress(page).locator("li[data-state=now] .animate-spin")).toHaveCount(1);
    });

    test("119 안내가 먼저 와도(마스코트 숨김) 대기 표시는 보이고 마스코트는 없다", async ({ page }) => {
      await mockChat(page, { name: "emergency", holdBefore: "progress" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      await expect(spinner(page)).toBeVisible();
      await expect(page.getByTestId("mascot")).toHaveCount(0);
    });
  });
}
