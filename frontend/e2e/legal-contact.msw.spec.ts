import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { MOCK_LEGAL_DOCS } from "../src/mocks/fixtures/account";
import type { LegalDoc } from "../src/lib/api/account";
import { HEIGHT, expectNoHorizontalScroll, openApp } from "./helpers";

// 실제 시드 v2 본문(backend/app/db/seed_legal_v2.sql, 읽기만)으로 동의 화면을 그린다(사용자 보고 2026-11-22: 실서버 §6·§7 연락처 줄의 줄바꿈,
// §1·§3 표 깨짐). 시드의 `{{PRIVACY_CONTACT}}`는 원격 적용(account_repo_pg.render_privacy_contact)과 같은 꼴의 **가짜** 값으로 채운다
// (실제 이름·이메일은 저장소·시험에 넣지 않는다). 본문은 페이지 안 fetch 대역으로 넣는다(helpers.mockChat과 같은 방식. MSW 워커는 그대로 두고
// `/api/legal/terms`·`/api/legal/privacy_policy`만 바꾼다).
// 캡처: `FE_LEGAL_SHOT_DIR`을 주면 `legal-contact-{scheme}-{width}.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`).
const SHOT_DIR = process.env.FE_LEGAL_SHOT_DIR;
const CONTACT = "개인정보 보호책임자: 홍길동, 문의: privacy@example.com";
const SEED = readFileSync(path.resolve(__dirname, "../../backend/app/db/seed_legal_v2.sql"), "utf8");

function seedDoc(docType: "terms" | "privacy_policy"): LegalDoc {
  const match = new RegExp(`\\('${docType}',\\s*(\\d+),\\s*'([^']*)',\\s*\\$md\\$([\\s\\S]*?)\\$md\\$`).exec(SEED);
  if (!match) throw new Error(`seed_legal_v2.sql에서 ${docType}를 찾지 못했다`);
  return { ...MOCK_LEGAL_DOCS[docType], version: Number(match[1]), title: match[2], body_md: match[3].replaceAll("{{PRIVACY_CONTACT}}", CONTACT) };
}

const modal = (page: Page) => page.getByTestId("account-modal");

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`실제 시드 v2 본문 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });

      test("§1·§3 표가 table로, 머리 안내가 blockquote로, 연락처 줄의 이메일이 끊기지 않게 그려진다", async ({ page }) => {
        const docs = { terms: seedDoc("terms"), privacy_policy: seedDoc("privacy_policy") };
        await page.addInitScript((served: Record<string, LegalDoc>) => {
          const original = window.fetch.bind(window);
          window.fetch = async (input, init) => {
            const request = input instanceof Request ? input : new Request(input, init);
            const docType = /\/api\/legal\/(\w+)$/.exec(new URL(request.url).pathname)?.[1];
            if (!docType || !served[docType]) return original(input, init);
            return new Response(JSON.stringify(served[docType]), { status: 200, headers: { "Content-Type": "application/json" } });
          };
        }, docs);
        await openApp(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
        await page.getByTestId("login-entry").click();
        await modal(page).getByRole("group", { name: "간편 로그인" }).getByRole("button", { name: "카카오 로그인" }).click();
        await expect(modal(page)).toHaveAttribute("data-step", "consent");

        const policy = modal(page).locator('[data-doc-type="privacy_policy"]');
        await expect(policy.getByRole("heading", { level: 3 })).toContainText(docs.privacy_policy.title); // 서버 값 그대로
        const body = policy.getByTestId("legal-body");
        await expect(body.locator("p").filter({ hasText: /^\s*\|/ })).toHaveCount(0);
        await expect(body).not.toContainText("|---|");
        await expect(body.locator("blockquote")).toHaveCount(1);
        await expect(body.locator("blockquote")).toContainText("초안·법률 검토 전입니다.");
        await expect(body.locator("table")).toHaveCount(2);
        await expect(body.locator("table").first().locator('thead th[scope="col"]')).toHaveText(["항목", "목적", "언제"]);
        await expect(body.locator("table").first().locator("tbody tr")).toHaveCount(5);
        await expect(body.locator("table").nth(1).locator('thead th[scope="col"]')).toHaveCount(6);
        await expect(body.locator("table").nth(1).locator("tbody tr")).toHaveCount(2);

        // 연락처 줄(§7): 서버 본문이 한 줄이라 한 문단이다. 이메일은 한 줄 안에 통째로 있다(줄 사각형 1개)
        const docBox = policy.getByRole("group", { name: docs.privacy_policy.title });
        const email = body.locator("p").getByTestId("legal-email").filter({ hasText: "privacy@example.com" }); // 표 안의 위탁처 이메일은 뺀다
        await expect(email).toHaveText("privacy@example.com");
        await email.scrollIntoViewIfNeeded();
        expect(await email.evaluate((el) => el.getClientRects().length)).toBe(1);
        await expect(email.locator("xpath=ancestor::p[1]")).toHaveText(`Can I PPiyak 운영자(개발자) · ${CONTACT}`);
        await expectNoHorizontalScroll(page);
        expect(await page.getByTestId("account-body").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        expect(await docBox.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        // 이용약관 §6 문의 줄도 같다
        const terms = modal(page).locator('[data-doc-type="terms"]');
        const termsEmail = terms.getByTestId("legal-email");
        await expect(termsEmail).toHaveText("privacy@example.com");
        await termsEmail.scrollIntoViewIfNeeded();
        expect(await termsEmail.evaluate((el) => el.getClientRects().length)).toBe(1);
        if (SHOT_DIR) {
          // 처리방침 상자를 §7 연락처 줄까지 내린 채로 찍는다
          await email.scrollIntoViewIfNeeded();
          await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
          await page.screenshot({ path: path.join(SHOT_DIR, `legal-contact-${scheme}-${width}.png`) });
        }
      });
    });
  }
}
