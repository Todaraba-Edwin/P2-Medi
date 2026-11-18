import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

// 결과 카드 부품 화면 시험(/dev/preview/result). PRD-15 §7 ①~⑥과 360·320px, 터치 영역 44px.
const NARROW = [
  { width: 360, height: 800 },
  { width: 320, height: 800 },
];
const WIDE = { width: 1280, height: 900 };
const MIN_TOUCH = 44;

const sample = (page: Page, id: string) => page.locator(`[data-sample="${id}"]`);

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

/** 제목 측정: 실제 폭, 한 줄로 폈을 때의 폭, 줄별 글자, 들어 있는 줄(판정 줄)의 안쪽 폭 */
async function measureTitles(scope: Locator) {
  return scope.getByTestId("line-title").evaluateAll((titles) =>
    titles.map((title) => {
      const el = title as HTMLElement;
      const width = el.getBoundingClientRect().width;
      const clone = el.cloneNode(true) as HTMLElement;
      clone.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;max-width:none;width:max-content";
      el.parentElement!.appendChild(clone);
      const natural = clone.getBoundingClientRect().width;
      clone.remove();
      const row = el.closest('[data-testid="product-line"]') as HTMLElement;
      const style = getComputedStyle(row);
      const inner = row.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      // 줄별 글자: 글자마다 위치를 재서 같은 높이끼리 묶는다
      const text = el.textContent ?? "";
      const node = el.firstChild!;
      const lines: string[] = [];
      let top = Number.NaN;
      for (let i = 0; i < text.length; i += 1) {
        const range = document.createRange();
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        const rect = range.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        if (Number.isNaN(top) || Math.abs(rect.top - top) > 2) {
          lines.push("");
          top = rect.top;
        }
        lines[lines.length - 1] += text[i];
      }
      return { text, width, natural, inner, lines };
    }),
  );
}

/** ① 제목이 한 글자 폭으로 쪼개지지 않는다: 줄바꿈은 띄어쓰기·× 위치에서만 */
function expectTitleBreaksOnlyAtSpaces(title: { text: string; lines: string[] }) {
  expect(title.lines.join("")).toBe(title.text);
  title.lines.slice(0, -1).forEach((lineText, index) => {
    const next = title.lines[index + 1];
    const atSpace = /\s$/.test(lineText) || /^\s/.test(next);
    expect(atSpace, `"${title.text}"가 "${lineText}" | "${next}"에서 끊겼다`).toBe(true);
  });
  for (const lineText of title.lines) expect(lineText.trim().length, `"${title.text}"의 한 글자 줄`).toBeGreaterThan(1);
}

/** ② 배지가 잘리지 않는다: 카드 안에 다 들어 있고, 넘침·말줄임이 없고, 글자가 모두 보인다 */
async function expectBadgesNotClipped(card: Locator) {
  const box = (await card.boundingBox())!;
  const badges = await card.locator('[data-testid="status-badge"], [data-testid="line-text"]').evaluateAll((els) =>
    els.map((el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        text: el.textContent ?? "",
        left: rect.left,
        right: rect.right,
        clipped: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1,
        ellipsis: style.textOverflow === "ellipsis",
        hidden: style.overflow === "hidden",
      };
    }),
  );
  expect(badges.length).toBeGreaterThan(0);
  for (const badge of badges) {
    expect(badge.text.length).toBeGreaterThan(0);
    expect(badge.left, badge.text).toBeGreaterThanOrEqual(box.x - 0.5);
    expect(badge.right, badge.text).toBeLessThanOrEqual(box.x + box.width + 0.5);
    expect(badge.clipped, badge.text).toBe(false);
    expect(badge.ellipsis || badge.hidden, badge.text).toBe(false);
  }
}

for (const viewport of NARROW) {
  test.describe(`결과 카드 ${viewport.width}px`, () => {
    test.use({ viewport });

    test("병용금기 사유 원문: 카드 보조줄에 `사유:`로 보이고 2줄을 넘지 않으며 가로 넘침이 없다(FE-02-06 A)", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const reasons = sample(page, "long-reason").locator('[data-slot="reason"]');
      await expect(reasons).toHaveCount(2);
      await expect(reasons.nth(1)).toHaveText("사유: 합성 둘째 사유 문장");
      const box = await reasons.nth(0).boundingBox();
      expect(box!.height).toBeLessThanOrEqual(2 * 17 + 1); // 2줄 말줄임(줄 높이 17px)
      await expect(reasons.nth(0)).toContainText("일부러 길게 적었습니다"); // 글자는 DOM에 그대로
      await expectNoHorizontalScroll(page);
    });

    test("①②③④ 모든 표본: 제목이 쪼개지지 않고, 배지가 잘리지 않고, 제목 줄이 유지되고, 가로 스크롤이 없다", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const cards = page.getByTestId("result-card");
      const count = await cards.count();
      expect(count).toBeGreaterThanOrEqual(14);
      for (let i = 0; i < count; i += 1) await expectBadgesNotClipped(cards.nth(i)); // ②
      const titles = await measureTitles(page.locator("main"));
      expect(titles.length).toBeGreaterThanOrEqual(count);
      for (const title of titles) {
        expectTitleBreaksOnlyAtSpaces(title); // ①
        expect(title.width, title.text).toBeGreaterThanOrEqual(Math.min(title.natural, title.inner) - 1); // ③
      }
      await expectNoHorizontalScroll(page); // ④
    });

    test("긴 제목 + 배지 셋: 제목은 띄어쓰기에서만 줄바꿈하고 배지는 제목 아래 줄에 가로로 놓인다", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const scope = sample(page, "long-title");
      const titles = await measureTitles(scope);
      expect(titles.some((t) => t.lines.length > 1)).toBe(true); // 실제로 줄바꿈이 일어나는 표본이다
      for (const title of titles) expectTitleBreaksOnlyAtSpaces(title);
      const line = scope.getByTestId("product-line").nth(1);
      const title = (await line.getByTestId("line-title").boundingBox())!;
      const badges = await line.getByTestId("status-badge").all();
      expect(badges).toHaveLength(3);
      for (const badge of badges) expect((await badge.boundingBox())!.y).toBeGreaterThanOrEqual(title.y + title.height - 1);
      await expectBadgesNotClipped(scope.getByTestId("result-card"));
    });

    test("⑥ 등급 불일치: 배지 개수·글자·순서가 응답 값과 같다(출처를 붙여 둘 다)", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const badges = sample(page, "grade-mismatch").getByTestId("status-badge");
      await expect(badges).toHaveText(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
      await expect(sample(page, "three-badges").getByTestId("status-badge")).toHaveText([
        "삐! 병용금기",
        "삐! 임부금기 2등급 (파일)",
        "삐! 임부금기 1등급 (성분 API)",
      ]);
    });

    test("'목록에 없음' 줄의 안전 아님 문구가 스크롤 없이 접히지 않은 채 보인다", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const text = sample(page, "not-listed").getByTestId("line-text");
      await text.scrollIntoViewIfNeeded();
      await expect(text).toBeVisible();
      await expect(text).toHaveText("금기 목록에 없음(안전하다는 뜻이 아님)");
      expect(await sample(page, "not-listed").locator("details").count()).toBe(0);
    });

    test("터치 영역 44px: '외 N개'와 되묻기 후보·직접 입력 버튼", async ({ page }) => {
      await page.goto("/dev/preview/result");
      const more = sample(page, "many-ingredients").getByRole("button", { name: "외 4개" });
      const moreBox = (await more.boundingBox())!;
      expect(moreBox.width).toBeGreaterThanOrEqual(MIN_TOUCH);
      expect(moreBox.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      await more.click();
      await expect(sample(page, "many-ingredients").getByTestId("ingredient-chip")).toHaveCount(6);
      await expectNoHorizontalScroll(page);

      const clarify = sample(page, "clarify");
      for (const button of await clarify.getByRole("button").all()) {
        expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH);
      }
      await clarify.getByTestId("candidate").nth(1).click();
      await expect(clarify.getByTestId("picked")).toContainText("가나다정 500밀리그램");
    });

    test("결과 카드에는 마스코트·이미지·날짜 줄이 없다", async ({ page }) => {
      await page.goto("/dev/preview/result");
      await expect(page.getByTestId("result-sample").first()).toBeVisible();
      await expect(page.locator("main img")).toHaveCount(0);
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expect(page.getByTestId("date-lines")).toHaveCount(0);
    });
  });
}

test.describe("결과 카드 넓은 폭", () => {
  test.use({ viewport: WIDE });

  test("⑤ 배지가 다 들어가면 제목 옆(같은 줄)에 있다", async ({ page }) => {
    await page.goto("/dev/preview/result");
    for (const id of ["pregnancy", "found", "grade-mismatch", "three-badges", "not-listed"]) {
      const line = sample(page, id).getByTestId("product-line").first();
      const title = (await line.getByTestId("line-title").boundingBox())!;
      const status = (await line.getByTestId("line-status").boundingBox())!;
      expect(status.y, id).toBeLessThan(title.y + title.height); // 같은 줄
      expect(status.x, id).toBeGreaterThanOrEqual(title.x + title.width - 1); // 제목 오른쪽
    }
    const titles = await measureTitles(page.locator("main"));
    for (const title of titles) expect(title.width, title.text).toBeGreaterThanOrEqual(Math.min(title.natural, title.inner) - 1);
    await expectNoHorizontalScroll(page);
  });
});
