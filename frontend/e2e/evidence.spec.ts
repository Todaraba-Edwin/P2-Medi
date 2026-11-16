import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

// 근거 상세·안전 영역 부품 화면 시험(/dev/preview/evidence). PRD-15 §7 ④(근거 상세 쪽), PRD-12 날짜 줄, 터치 영역 44px.
const NARROW = [
  { width: 360, height: 800 },
  { width: 320, height: 800 },
];
const MIN_TOUCH = 44;
const sample = (page: Page, id: string) => page.locator(`[data-sample="${id}"]`);

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

/** 요소가 스크롤 없이 첫 화면 안에 다 들어와 있는가 */
async function expectInFirstScreen(page: Page, target: Locator) {
  const box = (await target.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
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

for (const viewport of NARROW) {
  test.describe(`근거 상세 ${viewport.width}px`, () => {
    test.use({ viewport });

    test("응급 화면: 119 배너와 고정 안내·고지가 스크롤 없이 첫 화면에 있고 119가 맨 위다", async ({ page }) => {
      await page.goto("/dev/preview/evidence/screen");
      const banner = page.getByTestId("emergency-banner");
      await expect(banner).toHaveAttribute("role", "alert");
      await expectInFirstScreen(page, banner);
      await expectInFirstScreen(page, page.getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      expect(await page.getByTestId("emergency-screen").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-banner");
      const link = banner.getByRole("link", { name: "119 전화" });
      await expect(link).toHaveAttribute("href", "tel:119");
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      // 고정 안내 줄은 받은 순서(약사 확인 권고 → 고정 문구)
      await expect(page.getByTestId("fixed-notice").locator("p")).toHaveText([
        "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.",
        "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.",
      ]);
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expect(page.locator("img")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("응급 화면: 근거 상세 시트를 열고 닫아도 119·고정 안내는 그대로이고 버튼은 44px 이상이다", async ({ page }) => {
      await page.goto("/dev/preview/evidence/screen");
      const entry = page.getByTestId("evidence-entry");
      await expect(entry).toHaveText("근거 상세 보기");
      expect((await entry.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      await entry.click();
      const sheet = page.getByRole("dialog", { name: "근거 상세" });
      await expect(sheet).toBeVisible();
      await expect(sheet.getByTestId("evidence-section").first()).toBeVisible();
      await expect(sheet.getByTestId("fixed-notice")).toHaveCount(0); // 고정 안내는 시트 안이 아니라 밖(접히지 않는 영역)에 있다
      const close = sheet.getByRole("button", { name: "닫기" });
      const closeBox = (await close.boundingBox())!;
      expect(closeBox.width).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(closeBox.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      const sheetBox = (await sheet.boundingBox())!;
      expect(sheetBox.x).toBeGreaterThanOrEqual(0);
      expect(sheetBox.x + sheetBox.width).toBeLessThanOrEqual(viewport.width);
      await close.click();
      await expect(sheet).toHaveCount(0);
      await expectInFirstScreen(page, page.getByTestId("emergency-banner"));
      await expectInFirstScreen(page, page.getByTestId("fixed-notice"));
      await expectNoHorizontalScroll(page);
    });

    test("모든 표본: 가로 스크롤이 없고 배지·표지·날짜 줄이 잘리지 않는다(PRD-15 §7 ④ 근거 상세 쪽)", async ({ page }) => {
      await page.goto("/dev/preview/evidence");
      const details = page.getByTestId("evidence-detail");
      const count = await details.count();
      expect(count).toBeGreaterThanOrEqual(12);
      let checked = 0;
      for (let i = 0; i < count; i += 1) {
        checked += await expectContained(
          details.nth(i),
          '[data-testid="status-badge"], [data-testid="line-text"], [data-testid="source-tag"], [data-testid="line-title"], [data-testid="date-lines"] li, [data-testid="source-dataset"], [data-testid="source-publisher"]',
        );
      }
      expect(checked).toBeGreaterThan(80);
      await expectNoHorizontalScroll(page);
    });

    test("출처 표: 날짜 한 줄은 중간에서 끊기지 않고, 기관은 한 번씩이며, 좁은 폭에서도 묶음이 유지된다", async ({ page }) => {
      await page.goto("/dev/preview/evidence");
      const table = sample(page, "rich-sources").getByTestId("source-table");
      await table.scrollIntoViewIfNeeded();
      await expect(table.getByTestId("source-publisher")).toHaveText(["식약처", "한국의약품안전관리원"]);
      await expect(table.getByTestId("source-dataset")).toHaveText(["DUR 성분정보 API", "의약품 허가정보", "임부금기 파일"]);
      const lines = await table.locator('[data-testid="date-lines"] li').evaluateAll((els) =>
        els.map((el) => ({ text: el.textContent, height: el.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(el).lineHeight) })),
      );
      expect(lines.length).toBe(7);
      for (const line of lines) expect(line.height, line.text ?? "").toBeLessThanOrEqual(line.lineHeight + 1); // 한 줄
      // 기관·자료 이름이 글자 단위로 쪼개지지 않는다: 이름의 높이가 두 줄을 넘지 않는다
      const names = await table.locator('[data-testid="source-dataset"], [data-testid="source-publisher"]').evaluateAll((els) =>
        els.map((el) => ({ text: el.textContent, height: el.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(el).lineHeight) })),
      );
      for (const name of names) expect(name.height, name.text ?? "").toBeLessThanOrEqual(name.lineHeight + 1);
      // 묶음: 한국의약품안전관리원 행은 그 기관 머리 아래에 있다
      const groups = table.getByTestId("source-group");
      await expect(groups).toHaveCount(2);
      await expect(groups.nth(0).getByTestId("source-row")).toHaveCount(2);
      await expect(groups.nth(1).getByTestId("source-row")).toHaveCount(1);
    });

    test("미확보 박스: 응답 문구가 접히지 않고 보이고, 약사 확인 권고 줄은 접히지 않는 고정 안내에 받은 순서로 있다", async ({ page }) => {
      await page.goto("/dev/preview/evidence");
      const scope = sample(page, "missing");
      const box = scope.getByTestId("missing-box");
      await box.scrollIntoViewIfNeeded();
      await expect(box.getByTestId("missing-text")).toHaveText("허가사항에서 관련 문장을 찾지 못했어요");
      await expect(box.locator("b").first()).toHaveText("가나다정 · 상호작용");
      expect(await scope.locator("details").count()).toBe(0);
      // 박스 안 권고는 응답의 pharmacist_advice 줄 그대로다(FE-IMPL-06b: 서버처럼 미확보가 있으면 권고 줄이 실려 오게 fixture를 맞췄다).
      // 고정 안내의 권고 줄(응답 값)은 접히지 않는 영역에 그대로 있다
      await expect(box.getByTestId("pharmacist-advice")).toHaveText([
        "복용 전에 꼭 약국·약사에게 가나다정을 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.",
      ]);
      await expect(scope.getByTestId("fixed-notice").locator("p")).toHaveText([
        "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.",
        "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.",
      ]);
      await expectContained(scope, '[data-testid="missing-box"], [data-testid="fixed-notice"]');
    });

    test("허가사항 인용: 머리 형식과 인용부호, 표 없음", async ({ page }) => {
      await page.goto("/dev/preview/evidence");
      const permits = sample(page, "permit").getByTestId("permit-text");
      await expect(permits).toHaveCount(2);
      await expect(permits.nth(0).locator("b")).toHaveText("가나다정 허가사항 원문(사용상 주의사항)");
      await expect(permits.nth(1).locator("b")).toHaveText("라마바캡슐 허가사항 원문(용법·용량)");
      expect(await permits.nth(1).locator("table, dl, ul").count()).toBe(0);
      const quote = await permits.nth(0).locator("q").evaluate((el) => [getComputedStyle(el, "::before").content, getComputedStyle(el).quotes]);
      expect(quote).toEqual(["open-quote", '"“" "”"']); // 인용부호는 q 요소가 그린다(원문 글자에 덧붙이지 않는다)
    });

    test("표본 화면에 마스코트·이미지가 없다", async ({ page }) => {
      await page.goto("/dev/preview/evidence");
      await expect(page.getByTestId("evidence-sample").first()).toBeVisible();
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expect(page.locator("main img")).toHaveCount(0);
    });
  });
}

test.describe("근거 상세 넓은 폭", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("패널 배치: '근거 상세 열기'로 열고 닫기 버튼(44px)으로 닫는다", async ({ page }) => {
    await page.goto("/dev/preview/evidence");
    const entries = sample(page, "grade-mismatch").getByTestId("evidence-entry");
    await expect(entries).toHaveText(["근거 상세 보기", "근거 상세 열기"]);
    await entries.nth(1).click();
    const panel = page.getByRole("complementary", { name: "근거 상세" });
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
    const close = panel.getByRole("button", { name: "닫기" });
    const box = (await close.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(MIN_TOUCH);
    expect(box.height).toBeGreaterThanOrEqual(MIN_TOUCH);
    await expectContained(panel, '[data-testid="status-badge"], [data-testid="source-tag"], [data-testid="date-lines"] li');
    await close.click();
    await expect(panel).toHaveCount(0);
    await expectNoHorizontalScroll(page);
  });
});
