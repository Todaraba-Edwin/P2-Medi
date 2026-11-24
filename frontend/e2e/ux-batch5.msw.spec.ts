import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page, Request } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, ask, expectNoHorizontalScroll, input, mockChat, openAccountMenu, openApp, pickTarget } from "./helpers";

// FE-17 UI/UX 다듬기 5차(U-19 후속·U-20~U-23)를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-19 후속: 근거 상세 사유 원문에서 같은 내용(종류·제목·표지·원문)의 박스를 하나로 묶고 "같은 내용 N건"(합성 30건 → 3박스, 글자가 다른 원문은 따로)
// - U-20: 입력창 `일반인|임산부` 토글과 프로필 칩 글자의 글꼴 상자가 잘림 상자 안에 있다(예전 칩 말줄임 칸이 위 2px·아래 1px 잘랐다). 배율 100·110·125%
// - U-21: 로그인 + `게스트로 이용`이면 계정 버튼이 게스트 모드 표시(점선 원 병아리 + 게스트로 이용), 로그인 상태는 메뉴 안에서 구분
// - U-22: 게스트 상태 시작 안내 "…질문해요. 변경", `변경`은 칩과 같은 프로필 목록을 연다(포커스·Esc·고르면 서버 저장)
// - U-23: 프로필 상태 시작 안내의 세 번째 문장 중간 `게스트로 이용` 링크(44px 누르는 영역·키보드)
// 캡처: `FE_UX_BATCH5_SHOT_DIR`을 주면 `ux-batch5-{width}-{scheme}.png`(시작 화면 프로필 상태·입력창)와 `ux-batch5-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH5_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  if (target) await target.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
  else await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
const box = async (locator: Locator) => (await locator.boundingBox())!;
const isDefaultTargetPut = (request: Request) => request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/api/me/default-target");

/** 글자 노드마다 글꼴 상자(Range 사각형)가 가장 가까운 overflow 잘림 조상의 상자 밖으로 나간 px(위·아래 중 큰 값). 0이면 잘리지 않는다 */
async function glyphOverflow(target: Locator) {
  return target.evaluate((el) => {
    let worst = 0;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const glyph = range.getBoundingClientRect();
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const computed = getComputedStyle(parent);
        if (computed.overflowX === "visible" && computed.overflowY === "visible") continue;
        const clip = parent.getBoundingClientRect();
        worst = Math.max(worst, clip.top - glyph.top, glyph.bottom - clip.bottom);
        break;
      }
    }
    return Math.round(worst * 100) / 100;
  });
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 5 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const mobile = width < 1024;
      const base = `ux-batch5-${width}-${scheme}`;

      test("U-19 후속: 같은 내용의 사유 원문 박스는 하나로 묶이고 '같은 내용 N건', 다른 글자는 따로", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "doseDup");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-view")).toBeVisible();
        if (mobile) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        await expect(detail).toBeVisible();
        const boxes = detail.getByTestId("reason-box");
        // 묶기 전 30박스(6 + 1 + 23) → 묶음 3개. 기대값 갱신(2026-11-24, FE-17 U-25): 판정 종류(용량주의) 박스 하나 안의 사유 원문 묶음 3개이고
        // 건수 표기는 "같은 내용 N건" 대신 "제형유형 N건"이다(묶는 규칙·글자·근거 ID 보존은 그대로)
        await expect(boxes).toHaveCount(1);
        const groups = detail.getByTestId("reason-group");
        await expect(groups).toHaveCount(3);
        await expect(groups.getByTestId("reason-text")).toHaveText(["가나성분으로 4,000mg", "가나성분으로써 4000mg", "라마성분 3,200mg"]);
        await expect(groups.getByTestId("reason-form-count")).toHaveText(["제형유형 6건", "제형유형 1건", "제형유형 23건"]);
        await expect(detail.getByTestId("reason-same-count")).toHaveCount(0);
        // 근거 ID는 접어서 보존(30개 모두, 겹치지 않음). 출처 표는 그대로
        const ids = (await boxes.evaluateAll((els) => els.flatMap((el) => (el.getAttribute("data-evidence-ids") ?? "").split(" ")))).filter(Boolean);
        expect(ids).toHaveLength(30);
        expect(new Set(ids).size).toBe(30);
        await expect(detail.getByTestId("evidence-section")).toHaveCount(3);
        // 박스 안 글자·표지가 박스 밖으로 나가지 않고 가로 스크롤이 없다
        for (const reasonBox of await boxes.all()) {
          const outer = await box(reasonBox);
          for (const child of await reasonBox.locator('[data-testid="source-tag"], [data-testid="reason-form-count"], p').all()) {
            const inner = await box(child);
            expect(inner.x).toBeGreaterThanOrEqual(outer.x - 0.5);
            expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + 0.5);
          }
        }
        await expectNoHorizontalScroll(page);
        await detail.locator('[data-section="reason"]').scrollIntoViewIfNeeded();
        await shot(page, `${base}-u19-after`);
      });

      test("U-20 토글·칩 글자 잘림 없음(배율 100·110·125%), U-23 프로필 상태 안내 문장 중간 링크", async ({ page }) => {
        test.setTimeout(90_000);
        const puts: unknown[] = [];
        page.on("request", (request) => {
          if (isDefaultTargetPut(request)) puts.push(request.postDataJSON());
        });
        await openApp(page, "?mock_session=onboarded&ux_batch5=1");

        // U-20: 토글 두 칸·칩의 글꼴 상자가 잘림 상자 안(0px). 브라우저 배율은 CSS zoom으로 흉내 낸다
        const toggleFrame = page.getByTestId("pregnancy-toggle").locator("> div");
        const face = page.getByTestId("target-chip-face");
        for (const zoom of ["1", "1.1", "1.25"]) {
          await page.evaluate((z) => (document.documentElement.style.zoom = z), zoom);
          for (const target of [page.getByTestId("pregnancy-general"), page.getByTestId("pregnancy-pregnant"), face]) {
            expect(await glyphOverflow(target), `${zoom} ${await target.getAttribute("data-testid")}`).toBeLessThanOrEqual(0);
          }
        }
        await page.evaluate(() => (document.documentElement.style.zoom = ""));
        // 같은 크기·같은 글자 모양 유지(U-10), 누르는 영역 44px
        const [frameBox, faceBox] = [await box(toggleFrame), await box(face)];
        expect(Math.round(faceBox.height)).toBe(28);
        expect(Math.round(frameBox.height)).toBe(28);
        const keys = ["font-size", "line-height"];
        const styleOf = (locator: Locator) => locator.evaluate((el, names) => names.map((name) => getComputedStyle(el).getPropertyValue(name)), keys);
        expect(await styleOf(face)).toEqual(await styleOf(page.getByTestId("pregnancy-general")));
        expect(await styleOf(face)).toEqual(["12px", "16px"]);
        expect(Math.round((await box(page.getByTestId("target-chip"))).height)).toBeGreaterThanOrEqual(MIN_TOUCH);
        expect(Math.round((await box(page.getByTestId("input-target-row"))).height)).toBe(MIN_TOUCH);
        await shot(page, `${base}-u20-input`, page.getByTestId("input-target-row"));

        // U-23: 사용자 지정 문장 그대로, 링크는 세 번째 문장 중간
        const start = page.getByTestId("start-target");
        await expect(start).toHaveText("나 프로필로 확인해요. 이 프로필의 연령대·임신 여부가 답변에 쓰여요. 프로필 없이 질문을 이어가시려면 게스트로 이용으로 프로필을 변경해주세요.");
        await expect(start).not.toContainText("안전");
        const link = start.getByRole("button", { name: "게스트로 이용" });
        expect(await link.evaluate((el) => el.nextSibling?.textContent)).toBe("으로 프로필을 변경해주세요.");
        expect(await link.evaluate((el) => getComputedStyle(el).textDecorationLine)).toContain("underline");
        // 누르는 영역: 가운데 ±21px 안을 누르면 링크다(문장 중간·줄 끝에 걸려도)
        const linkBox = await box(link);
        const hits = await page.evaluate(
          ({ x, y }) => [-21, 0, 21].map((dy) => document.elementFromPoint(x, y + dy)?.closest('[data-testid="start-target-guest"]') !== null),
          { x: linkBox.x + linkBox.width / 2, y: linkBox.y + linkBox.height / 2 },
        );
        expect(hits).toEqual([true, true, true]);
        await expectNoHorizontalScroll(page);
        await shot(page, base);

        // 키보드: Tab 순서상 링크에 초점이 오고 Enter로 고른다 → 게스트, 서버 저장, 초점은 질문 칸
        const saved = page.waitForRequest(isDefaultTargetPut);
        await link.focus();
        await expect(link).toBeFocused();
        expect(await link.evaluate((el) => el.matches(":focus-visible"))).toBe(true);
        await page.keyboard.press("Enter");
        await saved;
        await expect(start).toHaveText("게스트로 이용 중이에요. 저장한 프로필 값 없이 질문해요. 변경");
        await expect(input(page)).toBeFocused();
        expect(puts).toEqual([{ target: "guest" }]);
      });

      test("U-22 게스트 상태 `변경`: 칩과 같은 목록을 열고 고르면 저장, U-21 계정 버튼 게스트 모드 표시", async ({ page }) => {
        test.setTimeout(90_000);
        const puts: unknown[] = [];
        page.on("request", (request) => {
          if (isDefaultTargetPut(request)) puts.push(request.postDataJSON());
        });
        await openApp(page, "?mock_session=onboarded&ux_batch5=1");
        // 입력창 칩으로 게스트를 고른다(서버 저장)
        await pickTarget(page, "게스트로 이용");
        const start = page.getByTestId("start-target");
        await expect(start).toHaveText("게스트로 이용 중이에요. 저장한 프로필 값 없이 질문해요. 변경");
        const change = start.getByRole("button", { name: "변경" });
        // 링크 모양(밑줄·같은 글자 크기), 누르는 영역 가로·세로 44px 이상
        const styles = await change.evaluate((el) => [getComputedStyle(el).fontSize, getComputedStyle(el).textDecorationLine, getComputedStyle(el.parentElement!).fontSize]);
        expect(styles[0]).toBe(styles[2]);
        expect(styles[1]).toContain("underline");
        const changeBox = await box(change);
        const cx = changeBox.x + changeBox.width / 2;
        const cy = changeBox.y + changeBox.height / 2;
        const hits = await page.evaluate(
          ({ x, y }) =>
            [
              [0, -21],
              [0, 21],
              [-21, 0],
              [21, 0],
            ].map(([dx, dy]) => document.elementFromPoint(x + dx, y + dy)?.closest('[data-testid="start-target-change"]') !== null),
          { x: cx, y: cy },
        );
        expect(hits).toEqual([true, true, true, true]);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-start-guest`);

        // 키보드로 연다 → 칩과 같은 목록, 첫 항목 초점, Esc로 닫으면 `변경`으로 초점
        await change.focus();
        await page.keyboard.press("Enter");
        const menu = page.getByTestId("start-target-menu");
        await expect(menu).toBeVisible();
        await expect(menu.getByRole("menuitemradio")).toHaveText(["게스트로 이용", "나", "첫째"]);
        await expect(menu.getByRole("menuitemradio").first()).toBeFocused();
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-start-change-menu`);
        await page.keyboard.press("Escape");
        await expect(menu).toHaveCount(0);
        await expect(change).toBeFocused();

        // U-21: 계정 버튼은 게스트 모드 표시. 메뉴 안의 프로필 관리·로그아웃이 로그인 상태를 알린다
        if (mobile) await page.getByTestId("menu-button").click();
        const button = page.getByTestId("account-menu-button").first();
        await expect(button).toHaveText("게스트로 이용");
        await expect(button).toHaveAttribute("data-target", "guest");
        await expect(button.getByTestId("profile-avatar")).toHaveAttribute("data-color", "none");
        expect(await button.getByTestId("profile-avatar").evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("dashed");
        await shot(page, `${base}-u21-account-guest`);
        const accountMenu = await openAccountMenu(page);
        await expect(accountMenu.getByTestId("account-entry")).toHaveText("프로필 관리");
        await expect(accountMenu.getByTestId("account-logout")).toBeVisible();
        await shot(page, `${base}-u21-account-menu`);
        await page.keyboard.press("Escape");
        await expect(accountMenu).toHaveCount(0);
        if (mobile) {
          await page.keyboard.press("Escape");
          await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        }

        // 눌러서 열고 가족을 고른다 → 안내·칩·계정 버튼이 같이 바뀌고 서버 저장, 초점은 질문 칸
        const savedChild = page.waitForRequest(isDefaultTargetPut);
        await change.click();
        await menu.getByRole("menuitemradio", { name: "첫째" }).click();
        await savedChild;
        await expect(menu).toHaveCount(0);
        await expect(start.getByTestId("start-target-heading")).toHaveText("첫째 프로필로 확인해요");
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 첫째");
        await expect(input(page)).toBeFocused();
        expect(puts).toHaveLength(2);
        expect(puts[0]).toEqual({ target: "guest" });
        expect(JSON.stringify(puts[1])).toMatch(/^\{"target":"[0-9a-f-]{36}"\}$/);
        // 이름·건강 정보는 URL·브라우저 저장소에 새로 남지 않는다
        expect(page.url()).not.toContain("첫째");
        const stored = await page.evaluate(() => {
          // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
          // eslint-disable-next-line no-restricted-properties
          return JSON.stringify([Object.entries(window.localStorage), Object.entries(window.sessionStorage), document.cookie]);
        });
        expect(stored).not.toMatch(/첫째|나 프로필/);
        await shot(page, `${base}-start-profile-after-change`);
      });
    });
  }
}
