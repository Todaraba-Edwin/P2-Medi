import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, openApp } from "./helpers";

// 동의 화면 법적 문서 본문의 표(사용자 보고 2026-11-22: 실서버 처리방침 §1 파이프 표가 글자 그대로 이어 붙어 깨짐).
// 목 처리방침(src/mocks/fixtures/account.ts)은 시드 v2와 같은 모양의 인용·파이프 표를 담고, 화면은 `table`·`th[scope=col]`로 그린다.
// 393·1280 × 라이트·다크에서 표가 표로 보이고 페이지·모달 본문에 가로 스크롤이 생기지 않는다(표 상자 안에서만 민다).
// 캡처: `FE_LEGAL_SHOT_DIR`을 주면 그 폴더에 `legal-table-{scheme}-{width}.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE_LEGAL_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}.png`) });
};

const modal = (page: Page) => page.getByTestId("account-modal");

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`동의 화면 처리방침 표 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("파이프 표가 table로 보이고 인용은 blockquote이며 페이지 가로 스크롤이 없다", async ({ page }) => {
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await page.getByTestId("login-entry").click();
        await modal(page).getByRole("group", { name: "간편 로그인" }).getByRole("button", { name: "카카오 로그인" }).click();
        await expect(modal(page)).toHaveAttribute("data-step", "consent");

        const policy = modal(page).locator('[data-doc-type="privacy_policy"]');
        const body = policy.getByTestId("legal-body");
        // `|`로 시작하는 글자가 문단으로 남지 않는다
        await expect(body.locator("p").filter({ hasText: /^\s*\|/ })).toHaveCount(0);
        await expect(body).not.toContainText("|---|");
        // 인용(머리 안내)
        await expect(body.locator("blockquote")).toHaveCount(1);
        await expect(body.locator("blockquote")).toContainText("초안·법률 검토 전입니다(합성 목 문서).");
        // 표: 머리 3칸(scope=col), 본문 2행, 칸 안 굵게
        const table = body.locator("table");
        await expect(table).toHaveCount(1);
        await expect(table.locator('thead th[scope="col"]')).toHaveText(["항목", "목적", "언제"]);
        await expect(table.locator("tbody tr")).toHaveCount(2);
        await expect(table.locator("tbody td strong")).toHaveText("연령금기");

        // 표를 상자 안에서 보이게 내린 뒤: 페이지·모달 본문·문서 상자(세로 스크롤 상자)에 가로 넘침이 없다. 넘치면 표 상자(overflow-x-auto) 안에서만 민다
        await table.scrollIntoViewIfNeeded();
        await expectNoHorizontalScroll(page);
        expect(await page.getByTestId("account-body").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        const docBox = policy.getByRole("group", { name: "개인정보 처리방침 (합성 목 문서)" });
        expect(await docBox.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        const wrapper = body.getByTestId("legal-table");
        expect(await wrapper.evaluate((el) => getComputedStyle(el).overflowX)).toBe("auto");
        const wrapperBox = (await wrapper.boundingBox())!;
        const docBoxRect = (await docBox.boundingBox())!;
        expect(wrapperBox.x).toBeGreaterThanOrEqual(docBoxRect.x - 0.5);
        expect(wrapperBox.x + wrapperBox.width).toBeLessThanOrEqual(docBoxRect.x + docBoxRect.width + 0.5);
        // 칸 글자는 줄 바꿈을 허용한다(한 줄로 늘어나 상자를 밀지 않는다)
        const firstCell = table.locator("tbody td").first();
        expect(await firstCell.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("normal");
        // 머리 칸·본문 칸 색은 토큰(라이트·다크)이다: 머리 바탕 --color-bg-soft, 머리 글자 --color-ink, 본문 글자 --color-ink-2
        const token = (name: string) => page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
        const asRgb = (hex: string) => {
          const full = hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join("")}` : hex;
          const [r, g, b] = [1, 3, 5].map((i) => parseInt(full.slice(i, i + 2), 16));
          return `rgb(${r}, ${g}, ${b})`;
        };
        const th = table.locator("thead th").first();
        expect(await th.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(asRgb(await token("--color-bg-soft")));
        expect(await th.evaluate((el) => getComputedStyle(el).color)).toBe(asRgb(await token("--color-ink")));
        expect(await firstCell.evaluate((el) => getComputedStyle(el).color)).toBe(asRgb(await token("--color-ink-2")));
        await shot(page, `legal-table-${scheme}`);
      });
    });
  }
}
