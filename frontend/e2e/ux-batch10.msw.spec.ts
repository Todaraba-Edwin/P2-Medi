import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { FIXED_NOTICE, HEIGHT, ask, dock, expectNoHorizontalScroll, expectNoticeInResult, expectOnTop, fixedNotice, input, mockChat, notice, openApp, panel } from "./helpers";

// FE-17 UI/UX 다듬기 10차(2026-11-24 "FE 모아서 진행")를 목(MSW) 워커로 본다. 393·1280 × 라이트·다크.
// - U-27 추가 지시 2: 대화 중에는 스크롤 컨테이너(`chat-thread`)가 본문 영역(`main-body`) 전체 높이를 차지해 스크롤 영역이 위~아래 끝까지 이어지고,
//   입력 영역(`dock`: 입력 폼 + 하단 고지)은 같은 영역 하단에 겹쳐 고정되어 대화가 그 뒤로 스크롤한다. 마지막 답은 입력창에 가려지지 않고(아래 여백 = 입력 영역 높이 + 20px),
//   입력창이 여러 줄로 커져도 맨 아래를 지킨다. 시작 화면은 입력창 위치가 그대로(겹치지 않음)
// - U-30(ISSUE-035 모양 합성 응답 `u30`): 출처만 다른 배지 하나로, 같은 약 줄 한 행, 병용 줄 맨 위 + 두 약의 하루 최대량 주의, `금기 목록에 없음` 괄호 안내·
//   `파일과 실시간 조회 결과가 같아요` 정리, 근거 상세 판정·사유 원문 한 구역, 같은 내용 문장 하나로, 반복 노트 묶음당 한 번. "안전하다는 뜻이 아니에요" 안내는 최소 1회 남는다
// 캡처: `FE_UX_BATCH10_SHOT_DIR`을 주면 `ux-batch10-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH10_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  await page.waitForTimeout(200);
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  if (target) await target.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
  else await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
const box = async (locator: Locator) => (await locator.boundingBox())!;
const thread = (page: Page) => page.getByTestId("chat-thread");
const body = (page: Page) => page.getByTestId("main-body");
const scrollState = (target: Locator) => target.evaluate((el: HTMLElement) => ({ top: el.scrollTop, max: el.scrollHeight - el.clientHeight, padBottom: parseFloat(getComputedStyle(el).paddingBottom) }));
const toBottom = (target: Locator) =>
  target.evaluate(async (el: HTMLElement) => {
    el.scrollTop = el.scrollHeight;
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
/** 대화 영역 아래 여백 = 입력 영역 높이 + 20px(Conversation.tsx `DOCK_GAP`). 입력 영역 위 페이드는 16px */
const DOCK_GAP = 20;
const FADE = 16;

/** 합성 u30의 값(fixtures `responses.ts`) */
const TY = "가나다정500밀리그람(가나성분)";
const IB = "라마성분";
const CAUTION_DOSE = "하루 최대량 주의 성분 포함";
const API_SAME = "파일과 실시간 조회 결과가 같아요";
const MISMATCH_NEXT = "파일과 실시간 조회 결과 모두 보여드려요. 자료 고시 시점에 따라서 등급이 다르게 보일 수 있어요.";

/** 대화가 영역보다 길어질 때까지 묻는다 */
async function longConversation(page: Page, times = 3) {
  await mockChat(page, "found");
  await openApp(page);
  for (let i = 1; i <= times; i += 1) {
    await ask(page);
    await expect(page.getByTestId("result-card")).toHaveCount(i);
  }
  await expect.poll(async () => (await scrollState(thread(page))).max).toBeGreaterThan(0);
}

/** 대화 중 구조: 스크롤 영역이 본문 영역 위~아래 끝, 입력 영역은 같은 영역 하단에 겹쳐 있고 아래 여백이 입력 영역 높이를 따른다 */
async function expectOverlay(page: Page) {
  // 폭이 바뀐 직후(근거 상세 닫힘·창 크기 변경)에는 입력 영역 높이 측정이 한 프레임 늦을 수 있어 아래 여백이 따라올 때까지 기다린다
  await expect.poll(async () => Math.abs((await scrollState(thread(page))).padBottom - ((await box(dock(page))).height + DOCK_GAP))).toBeLessThanOrEqual(1);
  const b = await box(body(page));
  const t = await box(thread(page));
  const d = await box(dock(page));
  expect(Math.abs(t.y - b.y)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(t.y + t.height - (b.y + b.height))).toBeLessThanOrEqual(0.5); // 스크롤 영역이 아래 끝까지
  expect(Math.abs(d.y + d.height - (b.y + b.height))).toBeLessThanOrEqual(0.5); // 입력 영역은 하단 고정
  expect(d.y).toBeLessThan(t.y + t.height - 1); // 겹친다(입력 영역이 스크롤 영역 안쪽 아래)
  const state = await scrollState(thread(page));
  expect(Math.abs(state.padBottom - (d.height + DOCK_GAP))).toBeLessThanOrEqual(1);
  return { b, t, d };
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 10 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch10-${width}-${scheme}`;
      const desktop = width >= 1024;

      test("U-27-5: 시작 화면은 입력창이 흐름 안 그대로이고, 대화 중에는 스크롤 영역이 본문 위~아래 끝까지 이어지며 입력 영역이 그 하단에 겹쳐 대화가 뒤로 스크롤한다", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page);
        const home = page.getByTestId("home");
        await expect(home).toBeVisible();
        const h = await box(home);
        const d0 = await box(dock(page));
        expect(d0.y).toBeGreaterThanOrEqual(h.y + h.height - 0.5); // 시작 화면: 입력 영역은 스크롤 영역 아래(겹치지 않음)
        await expect(dock(page)).not.toHaveAttribute("data-overlay");
        await longConversation(page);
        if (desktop && (await panel(page).count()) > 0) await panel(page).getByRole("button", { name: "닫기" }).click();
        const { d } = await expectOverlay(page);
        // 대화가 입력 영역 뒤로 지나간다: 위로 조금 올린 상태에서 입력 영역 자리의 맨 위 요소는 입력 영역(단색 배경)이고, 그 뒤에 대화 내용이 있다
        await thread(page).evaluate((el: HTMLElement) => {
          el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight - 200);
        });
        await expectOnTop(input(page));
        const behind = await page.evaluate(({ x, y }) => document.elementsFromPoint(x, y).map((el) => el.getAttribute("data-testid")), { x: d.x + d.width / 2, y: d.y + 4 });
        expect(behind[0] === "dock" || behind.indexOf("dock") < behind.indexOf("chat-thread")).toBe(true);
        expect(behind).toContain("chat-thread");
        // 입력 영역은 단색 배경 + 위쪽 페이드(16px)
        const fade = dock(page).getByTestId("dock-fade");
        await expect(fade).toHaveAttribute("aria-hidden", "true");
        expect(Math.round((await box(fade)).height)).toBe(FADE);
        expect(await dock(page).evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(await page.getByTestId("main").evaluate((el) => getComputedStyle(el).backgroundColor));
        // 하단 고지는 지금 문구 그대로, 입력창 아래
        await expect(notice(page)).toHaveCount(1);
        expect((await box(notice(page))).y).toBeGreaterThan((await box(input(page))).y);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-u27-overlay`);
      });

      test("U-27-6: 긴 대화의 맨 아래까지 내리면 마지막 답(고정 안내 포함)이 입력창·페이드에 가려지지 않는다", async ({ page }) => {
        test.setTimeout(90_000);
        await longConversation(page);
        if (desktop && (await panel(page).count()) > 0) await panel(page).getByRole("button", { name: "닫기" }).click();
        await toBottom(thread(page));
        const state = await scrollState(thread(page));
        expect(Math.abs(state.top - state.max)).toBeLessThanOrEqual(1);
        const last = fixedNotice(page);
        const l = await box(last);
        const d = await box(dock(page));
        expect(l.y + l.height).toBeLessThanOrEqual(d.y - FADE + 0.5);
        await expectOnTop(last);
        await expectNoticeInResult(page, last);
        await shot(page, `${base}-u27-bottom`);
      });

      // 지금 입력창(`textarea rows=1`, `max-h-32`)은 글자에 맞춰 스스로 커지지 않는다(여러 줄은 칸 안에서 스크롤). 입력 영역 높이가 바뀌는 경우(입력창이 최대 높이까지 커짐,
      // 고지·안내 줄 줄바꿈)를 대역으로 만들기 위해 입력창 높이를 최대 높이(128px)로 키우고, 아래 여백·맨 아래 유지가 따라가는지 본다
      test("U-27-7: 입력 영역이 커져도(입력창 최대 높이 대역) 맨 아래를 지켜 마지막 줄이 가려지지 않는다(아래 여백이 입력 영역 높이를 따라간다)", async ({ page }) => {
        test.setTimeout(90_000);
        await longConversation(page);
        if (desktop && (await panel(page).count()) > 0) await panel(page).getByRole("button", { name: "닫기" }).click();
        await expectOverlay(page);
        await toBottom(thread(page));
        const before = await box(dock(page));
        await input(page).fill(["첫째 줄", "둘째 줄", "셋째 줄", "넷째 줄", "다섯째 줄", "여섯째 줄"].join("\n"));
        await page.addStyleTag({ content: 'textarea{height:128px!important}' });
        await expect.poll(async () => (await box(dock(page))).height).toBeGreaterThan(before.height + 20);
        // 아래 여백이 커진 입력 영역 높이를 따라가고, 맨 아래가 유지된다
        await expect.poll(async () => {
          const state = await scrollState(thread(page));
          const d = await box(dock(page));
          return Math.abs(state.padBottom - (d.height + DOCK_GAP)) <= 1 && Math.abs(state.top - state.max) <= 1;
        }).toBe(true);
        const l = await box(fixedNotice(page));
        const d = await box(dock(page));
        expect(l.y + l.height).toBeLessThanOrEqual(d.y - FADE + 0.5);
        await expectOnTop(fixedNotice(page));
        await shot(page, `${base}-u27-multiline`);
      });

      test("U-27-8: 입력창·하단 고지가 화면 안에서 잘리지 않고(아래 안전 영역 여백 14px 이상), 화면 높이가 줄어도(모바일 키보드 대역) 그대로 보인다", async ({ page }) => {
        test.setTimeout(90_000);
        await longConversation(page, 2);
        for (const height of [HEIGHT, 520]) {
          await page.setViewportSize({ width, height });
          await expect.poll(async () => (await box(dock(page))).y + (await box(dock(page))).height).toBeLessThanOrEqual(height + 0.5);
          const n = await box(notice(page));
          const i = await box(input(page));
          expect(n.y + n.height).toBeLessThanOrEqual(height + 0.5);
          expect(i.y).toBeGreaterThanOrEqual(0);
          expect(parseFloat(await dock(page).evaluate((el) => getComputedStyle(el).paddingBottom))).toBeGreaterThanOrEqual(14);
          await expectOnTop(input(page));
          await expectOverlay(page);
        }
        await expectNoHorizontalScroll(page);
      });

      if (desktop) {
        test("U-27-5: 근거 상세가 열려 있어도 같은 구조(스크롤 영역 오른쪽 = 패널 왼쪽, 입력 영역은 하단 겹침)", async ({ page }) => {
          test.setTimeout(90_000);
          await longConversation(page);
          await expect(panel(page)).toBeVisible();
          const { t } = await expectOverlay(page);
          const p = await box(page.getByTestId("panel-column"));
          expect(Math.abs(t.x + t.width - p.x)).toBeLessThanOrEqual(0.5);
          const d = await box(dock(page));
          expect(d.x + d.width).toBeLessThanOrEqual(p.x + 0.5);
          await shot(page, `${base}-u27-panel`);
        });
      }

      test("U-30 본문: 병용 줄 맨 위(두 약의 하루 최대량 주의), 출처만 다른 배지 하나, 같은 약 한 행, `금기 목록에 없음`·`파일과 실시간…` 정리, 안전 안내는 1회 이상", async ({ page }) => {
        await mockChat(page, "u30");
        await openApp(page);
        await ask(page, "합성 질문 가나다정500 먹고 라마성분도 먹어도 돼요?");
        const card = thread(page).getByTestId("result-card");
        await expect(card).toBeVisible();
        const lines = card.getByTestId("product-line");
        await expect(lines).toHaveCount(3);
        await expect(lines.getByTestId("line-title")).toHaveText([`${TY} · ${IB}`, IB, TY]);
        // (c)(d) 병용 줄이 맨 위이고 그 안에 두 약의 하루 최대량 주의
        const pairLine = lines.nth(0);
        await expect(pairLine).toHaveAttribute("data-target", "pair");
        await expect(pairLine.getByTestId("line-text")).toHaveText("금기 목록에 없음");
        await expect(pairLine.locator('[data-slot="pair-dose"]')).toHaveText([`${TY} - ${CAUTION_DOSE}`, `${IB} - ${CAUTION_DOSE}`]);
        // (a) 배지 묶음
        await expect(lines.nth(1).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일, 성분 API)", "삐! 임부금기 1등급 (성분 API)"]);
        // (b) 같은 약 한 행: 표지 둘·출처 둘
        await expect(lines.nth(2)).toHaveAttribute("data-merged-rows", "2");
        await expect(lines.nth(2).getByTestId("line-text")).toHaveText([CAUTION_DOSE, "금기 목록에 없음"]);
        await expect(lines.nth(2).locator('[data-slot="source"]')).toHaveText(["공식 파일 · 용량주의 파일", "공식 파일 · 임부금기 파일"]);
        // (e)(f) 줄마다 반복되던 안내 정리
        await expect(card).not.toContainText("(안전하다는 뜻이 아님)");
        await expect(thread(page)).not.toContainText(API_SAME);
        // 불변 조건: 결과 화면에 "안전하다는 뜻이 아니에요" 안내가 최소 1회(고정 안내, 접히지 않는 자리)
        const shown = (await thread(page).textContent()) ?? "";
        expect(shown.match(/안전하다는 뜻이 아니/g)?.length ?? 0).toBeGreaterThanOrEqual(1);
        await expectNoticeInResult(page, fixedNotice(page));
        await expect(fixedNotice(page)).toContainText(FIXED_NOTICE);
        await expectNoHorizontalScroll(page);
        await card.scrollIntoViewIfNeeded();
        await shot(page, `${base}-u30-result`);
      });

      test("U-30 근거 상세: 판정·사유 원문 한 구역(병용 카드 맨 위), 같은 내용 문장 하나로, 다른 내용(외용)은 따로, 반복 노트는 카드마다 한 번", async ({ page }) => {
        await mockChat(page, "u30");
        await openApp(page);
        await ask(page, "합성 질문 가나다정500 먹고 라마성분도 먹어도 돼요?");
        await expect(page.getByTestId("result-card")).toBeVisible();
        if (!desktop) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        await expect(detail).toBeVisible();
        await expect(detail.getByTestId("evidence-section")).toHaveCount(2);
        await expect(detail.locator("h3")).toHaveText(["판정 · 사유 원문", "출처"]);
        const cards = detail.getByTestId("verdict-group");
        await expect(cards).toHaveCount(3);
        expect(await cards.evaluateAll((els) => els.map((el) => el.getAttribute("data-kind")))).toEqual(["contra_pair", "pregnancy", "dose"]);
        // (g) 병용 카드: `금기 목록에 없음` + 두 약의 하루 최대량 주의
        await expect(cards.nth(0).getByTestId("line-text")).toHaveText("금기 목록에 없음");
        await expect(cards.nth(0).locator('[data-slot="pair-dose"]')).toHaveCount(2);
        // (h) 임부금기 카드: 판정 줄 → 사유 원문(파일 칸·성분 API 칸)
        const preg = cards.nth(1);
        await expect(preg.getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일, 성분 API)", "삐! 임부금기 1등급 (성분 API)"]);
        const reasonBoxes = preg.getByTestId("reason-box");
        await expect(reasonBoxes.getByTestId("source-tag")).toHaveText(["공식 파일 · 임부금기 파일", "공식 자료 · DUR 성분정보 API"]);
        // (i) 같은 내용은 하나(11건), 다른 내용(외용)은 따로(2건)
        await expect(reasonBoxes.nth(0).getByTestId("reason-drug")).toHaveText([`${IB} - 같은 내용 11건`, `${IB} - 같은 내용 2건`]);
        // (j) 반복 노트는 카드마다 한 번, `파일과 실시간…`은 없다
        await expect(preg.locator('[data-testid="reason-box"] [data-slot="notes"]')).toHaveText([MISMATCH_NEXT]);
        await expect(detail).not.toContainText(API_SAME);
        await expect(detail).not.toContainText("(안전하다는 뜻이 아님)");
        // 용량주의 카드: 사유 원문 → 약 이름 - 제형유형 N건(U-25 그대로, 글자가 다른 문장은 따로)
        await expect(cards.nth(2).getByTestId("reason-drug")).toHaveText([`${TY} - 제형유형 6건`, `${IB} - 제형유형 23건`, `${IB} - 제형유형 1건`]);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-u30-evidence`);
        await shot(page, `${base}-u30-evidence-detail`, detail);
      });
    });
  }
}
