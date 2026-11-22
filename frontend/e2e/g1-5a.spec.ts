import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { FIXED_NOTICE, HEIGHT, ask, dock, expectInFirstScreen, expectNoHorizontalScroll, expectTouchTarget, input, mockChat, openApp, panel, requests, sheet } from "./helpers";

// GROUP-01 5a(FE-11, 2026-11-20) 게스트 화면 e2e(Playwright 프로젝트 `app`, 페이지 안 fetch 대역):
// - F2: 입력창 안 왼쪽 임신 여부 토글 "일반인 | 임산부"(FE-11 §7.1 최종 디자인 `Rdd-Toggle`): 위치·글자·색 토큰·굵기·28px/44px·키보드·요청 `context.pregnant`(FE-11-12 A)
// - FE-11-03 A: 일반인 결과 아래 한 줄. FE-11-14 A: 게스트가 토글을 바꾸면 안내 한 줄(초안 글자)
// - F3(FE-11-10 A): 실시간 확인 배너·줄 노트는 본문 0회·근거 상세에만, 결과 카드 머리 "기준일 자료" 표지, 안전·법적·입력창 고지 1회
// 로그인·프로필 연동(FE-11-13)은 g1-5a.msw.spec.ts. 캡처: `G15A_SHOT_DIR`을 주면 그 폴더에 `*-g1-5a.png`를 남긴다(로컬 전용 `data/mock/fe-issue-shots`)
const SHOT_DIR = process.env.G15A_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-g1-5a.png`) });
};

const DISCLAIMER = "공공데이터 기반 정보 제공이며 진단·처방이 아님 · 금기 목록에 없다는 것이 안전하다는 뜻이 아님 · 요양기관의 DUR 점검을 대체하지 않음";
/** 승인 원문(PRD-17-07 A; 마지막 문장은 원문 승인 2026-11-22, PRD-17-10 후속, RFP-24-01 요소 보강) */
const INPUT_NOTICE = "질문은 이 탭에만 있고 저장하지 않아요. 새로고침하거나 탭을 닫으면 사라져요. 답변을 만들기 위해 질문과 선택한 프로필 값은 외부 AI(OpenAI)로 전송되며, 제공자 정책에 따라 일정 기간 보관될 수 있어요.";
const NOTICE_API_FAIL = "실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.";
const API_NOTE = "실시간 확인을 하지 못함(이 성분은 실시간 조회에 쓸 코드가 없어요. 파일 기준 결과는 그대로예요)";
const PICK_HINT = "임부금기는 '임산부'를 고르면 확인해요";
const SAVE_HINT = "프로필에 저장하려면 건강 정보 동의가 필요해요";
// 디자인 값(FE-11 §7.1): 고른 칸 #FFCC00 = --color-yellow, 안 고른 칸 #FFF8E1 = --color-bg-soft, 안 고른 글자 #6B5F3F = --color-mute
const YELLOW = "rgb(255, 204, 0)";
const CREAM = "rgb(255, 248, 225)";
const MUTE = "rgb(107, 95, 63)";

const toggle = (page: Page) => page.getByRole("radiogroup", { name: "임신 여부" });
const radio = (page: Page, name: "일반인" | "임산부") => toggle(page).getByRole("radio", { name });
const main = (page: Page) => page.getByTestId("main");
/** 글자가 몇 번 보이는가(본문 `main`의 textContent 기준) */
const countIn = (scope: Locator, text: string) => scope.evaluate((el, t) => (el.textContent ?? "").split(t).length - 1, text);
const style = (target: Locator, property: string) => target.evaluate((el, name) => getComputedStyle(el).getPropertyValue(name), property);

for (const width of [393, 1280]) {
  const desktop = width >= 1024;
  test.describe(`임신 여부 토글·고지 배치 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("토글은 입력창 안 왼쪽에 '일반인 | 임산부' 두 칸이 늘 보이고 기본 일반인이다. 색 토큰·굵기·28px 칸·44px 누르는 영역·←/→", async ({ page }) => {
      await openApp(page);
      const group = toggle(page);
      await expect(group).toBeVisible();
      await expect(group.getByRole("radio")).toHaveText(["일반인", "임산부"]);
      await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true");
      await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "false");
      // 입력창(textarea가 든 form) 안, 텍스트 영역 왼쪽, 보내기 버튼보다 앞
      const form = input(page).locator("xpath=ancestor::form");
      expect(await form.locator('[role="radiogroup"]').count()).toBe(1);
      const groupBox = (await group.boundingBox())!;
      const inputBox = (await input(page).boundingBox())!;
      const formBox = (await form.boundingBox())!;
      expect(groupBox.x + groupBox.width).toBeLessThanOrEqual(inputBox.x + 0.5);
      expect(groupBox.x).toBeGreaterThanOrEqual(formBox.x);
      expect(groupBox.y).toBeGreaterThanOrEqual(formBox.y);
      expect(groupBox.y + groupBox.height).toBeLessThanOrEqual(formBox.y + formBox.height + 0.5);
      // 칸 28px 틀, 누르는 영역 44px(가로는 글자 폭이라 세로만)
      const frame = radio(page, "일반인").locator("xpath=..");
      expect(Math.round((await frame.boundingBox())!.height)).toBe(28);
      for (const name of ["일반인", "임산부"] as const) {
        const cell = radio(page, name);
        const hit = await cell.evaluate((el) => {
          const before = getComputedStyle(el, "::before");
          const rect = el.getBoundingClientRect();
          return { height: rect.height, top: parseFloat(before.top), bottom: parseFloat(before.bottom), position: before.position };
        });
        expect(Math.round(hit.height)).toBe(24);
        expect(hit.position).toBe("absolute");
        expect(Math.round(hit.height - hit.top - hit.bottom)).toBeGreaterThanOrEqual(44); // -10px 위아래 확장
        expect(await cell.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
      }
      await expectTouchTarget(group, { widthToo: false });
      // 색만으로 구분하지 않는다: 고른 칸 노랑 + 800, 안 고른 칸 크림 + 보통 글자색 mute
      expect(await style(radio(page, "일반인"), "background-color")).toBe(YELLOW);
      expect(await style(radio(page, "일반인"), "font-weight")).toBe("800");
      expect(await style(radio(page, "임산부"), "background-color")).toBe(CREAM);
      expect(await style(radio(page, "임산부"), "color")).toBe(MUTE);
      expect(await style(radio(page, "임산부"), "font-weight")).toBe("400");
      await shot(page, "toggle-start");
      // 키보드: 고른 칸에 초점 → → 로 임산부, ← 로 일반인. 초점 링 3px
      await radio(page, "일반인").focus();
      await page.keyboard.press("ArrowRight");
      await expect(radio(page, "임산부")).toHaveAttribute("aria-checked", "true");
      await expect(radio(page, "임산부")).toBeFocused();
      expect(await style(radio(page, "임산부"), "outline-width")).toBe("3px");
      // 바탕색은 전환(transition-colors)이 끝난 값으로 본다
      await expect.poll(() => style(radio(page, "임산부"), "background-color")).toBe(YELLOW);
      await expect.poll(() => style(radio(page, "일반인"), "background-color")).toBe(CREAM);
      await page.keyboard.press("ArrowLeft");
      await expect(radio(page, "일반인")).toHaveAttribute("aria-checked", "true");
      await expect(radio(page, "일반인")).toBeFocused();
      // 게스트가 토글을 바꾸면 근처에 안내 한 줄(초안 글자, FE-11-14 A). 입력창 고지는 그대로 1회
      await expect(page.getByTestId("pregnancy-hint")).toHaveText(SAVE_HINT);
      await expect(page.getByTestId("input-notice")).toHaveCount(1);
      await expectNoHorizontalScroll(page);
    });

    test("일반인이면 context.pregnant=false와 결과 아래 '임산부를 고르면 확인' 한 줄, 임산부면 true이고 한 줄이 없다. 점선 상자는 임산부 + 확인 못 함일 때만", async ({ page }) => {
      await mockChat(page, "found", "pregnancy", "notChecked");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      expect((await requests(page))[0].context).toMatchObject({ pregnant: false, age: null });
      const hint = page.locator('[data-turn="turn-1"]').getByTestId("pregnancy-pick-hint");
      await expect(hint).toHaveText(PICK_HINT);
      await expect(hint).toBeVisible();
      // 결과 카드 아래(카드보다 뒤), 접히지 않는 자리
      expect(await hint.evaluate((el) => el.closest("details, [data-state=closed]") === null)).toBe(true);
      const cardBox = (await page.locator('[data-turn="turn-1"]').getByTestId("result-card").boundingBox())!;
      expect((await hint.boundingBox())!.y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height - 0.5);
      await expect(page.getByTestId("not-checked-lines")).toHaveCount(0);
      await shot(page, "toggle-result-general");
      await radio(page, "임산부").click();
      await expect(page.getByTestId("pregnancy-hint")).toHaveText(SAVE_HINT);
      await ask(page, "임산부 질문");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      expect((await requests(page))[1].context).toMatchObject({ pregnant: true });
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("pregnancy-pick-hint")).toHaveCount(0);
      await expect(page.locator('[data-turn="turn-1"]').getByTestId("pregnancy-pick-hint")).toHaveCount(1); // 지난 차례는 그대로
      // 임산부인데 서버가 확인하지 못한 경우에만 점선 상자(서버 줄)
      await ask(page, "셋째 질문");
      const dashed = page.locator('[data-turn="turn-3"]').getByTestId("not-checked-lines").locator("li");
      await expect(dashed).toHaveText(["임신 여부를 알 수 없어 임부금기는 확인하지 못했어요."]);
      await expect(page.locator('[data-turn="turn-3"]').getByTestId("pregnancy-pick-hint")).toHaveCount(0);
      await shot(page, "toggle-result-pregnant");
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("실시간 확인 실패: 본문은 '실시간 확인' 0회·안전 고지 1회·법적 고지 1회·입력창 고지 1회, 카드 머리 '기준일 자료' 표지, 근거 상세에 배너·줄 노트", async ({ page }) => {
      await mockChat(page, "apiFail", "limit");
      await openApp(page);
      await ask(page);
      const card = page.getByTestId("result-card");
      await expect(card).toBeVisible();
      await expect(page.getByTestId("result-notice")).toHaveCount(0);
      const tag = card.getByTestId("basis-file-tag");
      await expect(tag).toHaveText("기준일 자료");
      await expect(tag).toBeVisible();
      expect(await tag.evaluate((el) => el.closest("header") !== null)).toBe(true);
      expect(await countIn(main(page), "실시간 확인")).toBe(0);
      expect(await countIn(main(page), FIXED_NOTICE)).toBe(1);
      expect(await countIn(main(page), DISCLAIMER)).toBe(1);
      expect(await countIn(main(page), INPUT_NOTICE)).toBe(1);
      await expect(dock(page).getByTestId("fixed-notice")).toHaveCount(1);
      await expect(page.getByTestId("input-notice")).toHaveCount(1);
      await expect(page.getByTestId("legal-footer")).toHaveCount(1);
      await expectInFirstScreen(page, tag, { underUserLayer: desktop });
      // 근거 상세: 넓은 폭은 패널이 자동으로 열려 있고, 좁은 폭은 진입 버튼으로 시트를 연다
      if (!desktop) await page.getByTestId("evidence-entry").click();
      const detail = desktop ? panel(page) : sheet(page);
      const banner = detail.getByTestId("evidence-api-fail-notice");
      await expect(banner).toHaveText(NOTICE_API_FAIL);
      await expect(banner).toBeVisible();
      expect(await detail.evaluate((el) => (el.textContent ?? "").includes("실시간 확인을 하지 못함(이 성분은"))).toBe(true);
      expect(await countIn(detail, API_NOTE)).toBe(1);
      expect(await countIn(detail, "실시간 확인")).toBe(2);
      expect(await countIn(detail, FIXED_NOTICE)).toBe(0);
      await shot(page, "apifail");
      if (!desktop) await page.keyboard.press("Escape");
      // 다른 배너(상한 도달)는 본문 그대로, 표지 없음
      await ask(page, "둘째 질문");
      const second = page.locator('[data-turn="turn-2"]');
      await expect(second.getByTestId("result-notice")).toContainText("여기까지 확인한 결과만 보여 드려요.");
      await expect(second.getByTestId("basis-file-tag")).toHaveCount(0);
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });
  });
}
