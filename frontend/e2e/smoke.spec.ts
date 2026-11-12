import { expect, test } from "@playwright/test";

const VIEWPORTS = [
  { width: 360, height: 800 },
  { width: 320, height: 800 },
];

for (const viewport of VIEWPORTS) {
  for (const path of ["/", "/dev/preview"]) {
    test(`${path} ${viewport.width}px 가로 스크롤 없음`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto(path);
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
    });
  }
}
