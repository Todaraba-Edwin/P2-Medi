import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { ScenarioName } from "../src/mocks/fixtures/scenarios";
import {
  ADVICE_FIXED,
  EMERGENCY_TEXT,
  FIXED_NOTICE,
  HEIGHT,
  QUESTION,
  ask,
  banner,
  bannerTel,
  dock,
  expect119Reachable,
  expectContained,
  expectInFirstScreen,
  expectNoHorizontalScroll,
  expectOnTop,
  expectTouchTarget,
  input,
  layerTel,
  mockChat,
  openApp,
  overlaySidebar,
  panel,
  pushSidebar,
  rail,
  release,
  requests,
  scrim,
  sheet,
  tel,
  waitHeld,
} from "./helpers";

// 첫 화면(/) 조립의 흐름·폭 시험(FE-IMPL-06, 06b 보완). 통신 대역·덮임 검사 규칙은 helpers.ts 머리 주석.
// 실제 MSW 워커 연결은 msw.spec.ts(Playwright 프로젝트 `msw-worker`)가 확인한다.
// ============================================================ 흐름(좁은 폭)
for (const width of [360, 320]) {
  test.describe(`흐름 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면: 입력창·고지·119 진입점이 첫 화면에 있고 가로 스크롤이 없다(F1)", async ({ page }) => {
      await openApp(page);
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Can I PPiyak");
      await expectInFirstScreen(page, input(page));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      const entry = page.getByTestId("emergency-entry");
      await expectInFirstScreen(page, entry);
      await expect(entry).toHaveAttribute("href", "tel:119");
      await expectTouchTarget(entry);
      // 시작 화면의 119: 머리줄 진입점 + 119 안내 줄(FE-01-19 A·FE-01-24 A), 둘뿐이다
      await expect(tel(page)).toHaveCount(2);
      await expectTouchTarget(page.getByRole("button", { name: "메뉴 열기" }));
      await expectTouchTarget(page.getByRole("button", { name: "보내기" }));
      // 고지는 접히지 않는 영역에 있다
      expect(await page.getByTestId("legal-footer").evaluate((el) => el.closest("details, [role=dialog], [data-state=closed]") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("응급: 119가 답보다 먼저 첫 화면 맨 위에 뜨고, 금기 결과가 그 아래 이어진다(F7·F8·F13)", async ({ page }) => {
      await mockChat(page, { name: "emergency", holdBefore: "answer" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      // 답이 오기 전: 119 배너만 먼저 보인다
      await expect(banner(page)).toHaveAttribute("role", "alert");
      await expect(banner(page)).toContainText(EMERGENCY_TEXT);
      await expect(page.getByTestId("result-view")).toHaveCount(0);
      await expectInFirstScreen(page, banner(page));
      expect(await page.getByTestId("app-shell").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-row");
      await expect(page.getByRole("status", { name: "진행 상태" })).toBeVisible(); // 금기 조회는 막지 않는다
      await expect(page.getByTestId("mascot")).toHaveCount(0); // 119가 뜨면 진행 표시의 마스코트를 숨긴다
      // 119는 배너 하나뿐이다(머리줄 진입점·토스트와 겹치지 않는다)
      await expect(tel(page)).toHaveCount(1);
      await expectTouchTarget(tel(page));
      await release(page);
      // 답이 온 뒤: 결과가 배너 아래에 이어지고 배너는 그대로 맨 위다
      const result = page.getByTestId("result-view");
      await expect(result.getByTestId("result-card")).toBeVisible();
      expect((await result.boundingBox())!.y).toBeGreaterThan((await banner(page).boundingBox())!.y);
      await expectInFirstScreen(page, banner(page));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expect(page.getByText(EMERGENCY_TEXT)).toHaveCount(1);
      await expect(tel(page)).toHaveCount(1);
      await expect(page.locator("img")).toHaveCount(1); // 머리줄 로고 심볼뿐(마스코트 없음)
      await expect(page.locator("audio")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("일반 질문: 진행 표시 → 결과 → 근거 상세를 열고 닫으면 원래 결과로 돌아온다(F2·F6)", async ({ page }) => {
      await mockChat(page, { name: "found", holdBefore: "answer" });
      await openApp(page);
      await ask(page);
      await waitHeld(page);
      const progress = page.getByRole("status", { name: "진행 상태" });
      await expect(progress.getByRole("listitem")).toHaveText(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
      await expect(page.getByTestId("result-view")).toHaveCount(0);
      await release(page);
      await expect(page.getByTestId("result-summary")).toHaveText("가나다정과 라마바캡슐은 병용금기 목록에 함께 올라 있어요.");
      await expect(page.getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, input(page));
      await expect(sheet(page)).toHaveCount(0); // 좁은 폭에서는 저절로 열리지 않는다
      const entry = page.getByTestId("evidence-entry");
      await expect(entry).toHaveText("근거 상세 보기");
      await expectTouchTarget(entry);
      await entry.click();
      await expect(sheet(page).getByTestId("evidence-section").first()).toBeVisible();
      await expect(sheet(page).getByTestId("fixed-notice")).toHaveCount(0); // 고정 안내는 시트 밖(접히지 않는 영역)
      await expect(sheet(page).getByTestId("source-table")).toBeVisible(); // 출처·기준일
      await expectTouchTarget(sheet(page).getByRole("button", { name: "닫기" }));
      await sheet(page).getByRole("button", { name: "닫기" }).click();
      await expect(sheet(page)).toHaveCount(0);
      await expect(entry).toBeFocused();
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectNoHorizontalScroll(page);
    });
  });
}

test.describe("흐름 360px", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("근거 상세는 들어온 결과에 고정된다: 다른 질문의 상세로 가지 않고, 닫으면 그 결과로 돌아온다", async ({ page }) => {
    await mockChat(page, "found", "pregnancy");
    await openApp(page);
    await ask(page, "첫 질문");
    await expect(page.getByTestId("result-card")).toHaveCount(1);
    await ask(page, "둘째 질문");
    await expect(page.getByTestId("result-card")).toHaveCount(2);
    // 지난 답의 고정 안내는 그 답 아래에 남고, 가장 최근 답의 것은 아래 고정 영역에 있다
    await expect(page.locator('[data-turn="turn-1"]').getByTestId("fixed-notice")).toHaveCount(1);
    await expect(page.locator('[data-turn="turn-2"]').getByTestId("fixed-notice")).toHaveCount(0);
    await expect(dock(page).getByTestId("fixed-notice")).toHaveCount(1);
    const firstEntry = page.locator('[data-turn="turn-1"]').getByTestId("evidence-entry");
    await firstEntry.click();
    await expect(sheet(page).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
    await expect(sheet(page)).not.toContainText("임부금기");
    await expect(firstEntry).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(sheet(page)).toHaveCount(0);
    await expect(firstEntry).toBeFocused();
    await expect(firstEntry).toBeInViewport();
    await page.locator('[data-turn="turn-2"]').getByTestId("evidence-entry").click();
    await expect(sheet(page).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급"]);
  });

  test("되묻기: 후보를 골라도 보내지 않고, 다시 묻기를 눌러야 고른 값을 붙여 같은 질문을 보낸다", async ({ page }) => {
    await mockChat(page, "clarify", "found");
    await openApp(page);
    await ask(page);
    const candidates = page.getByTestId("candidate");
    await expect(candidates).toHaveCount(3);
    await expect(page.getByTestId("result-summary")).toContainText("어떤 약인지 하나를 골라 주세요.");
    await expect(page.getByTestId("result-card")).toHaveCount(0); // 고르기 전에는 판정이 없다
    await expect(page.getByTestId("status-badge")).toHaveCount(0);
    await expect(page.getByTestId("candidates-line")).toHaveText("어느 제품인지 고르면 금기를 확인해 드려요."); // 되묻기 안내(응답 값)
    await expectTouchTarget(candidates.first());
    await candidates.nth(1).click();
    await expect(page.getByTestId("picked-name")).toHaveText("가나다정 500밀리그램");
    // 후보는 선택 상태만 바꾼다(G-4)
    await expect(candidates.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(candidates.nth(0)).toHaveAttribute("aria-pressed", "false");
    // 고르기만 했다: 요청은 그대로 한 번, 대화도 한 차례다
    expect(await requests(page)).toHaveLength(1);
    await expect(page.locator("[data-turn]")).toHaveCount(1);
    await candidates.nth(0).click(); // 다시 고를 수 있다
    await expect(page.getByTestId("picked-name")).toHaveText("가나다정 100밀리그램");
    await expect(candidates.nth(0)).toHaveAttribute("aria-pressed", "true");
    await expect(candidates.nth(1)).toHaveAttribute("aria-pressed", "false");
    expect(await requests(page)).toHaveLength(1);
    const resend = page.getByRole("button", { name: "이 약으로 다시 묻기" });
    await expectTouchTarget(resend);
    await resend.click();
    await expect(page.getByTestId("result-card")).toBeVisible();
    const sent = await requests(page);
    expect(sent).toHaveLength(2);
    expect(sent[1]).toEqual({
      question: QUESTION,
      context: { age: null, pregnant: null, confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] },
    });
    await expect(page.locator("[data-turn]")).toHaveCount(2);
    await expect(page.getByTestId("candidate")).toHaveCount(0); // 지난 되묻기의 후보는 더 고를 수 없다
    await expectNoHorizontalScroll(page);
  });

  test("되묻기: '직접 입력'은 입력창으로 간다", async ({ page }) => {
    await mockChat(page, "clarify");
    await openApp(page);
    await ask(page);
    await page.getByRole("button", { name: "목록에 없어요 · 직접 입력" }).click();
    await expect(page.getByRole("textbox")).toBeFocused();
    expect(await requests(page)).toHaveLength(1);
  });

  test("거절: 거절 문구와 고정 안내만 보이고 결과 카드·근거 상세 진입이 없다", async ({ page }) => {
    await mockChat(page, "refuse");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-summary")).toContainText("복용량은 정해 드릴 수 없어요.");
    await expect(page.getByTestId("result-view")).toHaveAttribute("data-end-reason", "REFUSE");
    await expect(page.getByTestId("result-card")).toHaveCount(0);
    await expect(page.getByTestId("evidence-entry")).toHaveCount(0);
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
    await expect(page.getByTestId("mascot")).toHaveCount(0);
    await expectNoHorizontalScroll(page);
  });

  test("오류: 스스로 다시 보내지 않고, '다시 시도'를 눌렀을 때만 다시 보낸다(F4)", async ({ page }) => {
    await mockChat(page, "http500", "found");
    await openApp(page);
    await ask(page);
    const error = page.getByTestId("error-state");
    await expect(error).toContainText("답을 만들지 못했어요");
    await expect(error.getByTestId("mascot")).toHaveCount(1); // 마스코트는 오류 안내 카드 안에만 있다
    await expect(page.getByTestId("mascot")).toHaveCount(1);
    await expect(error).toContainText(FIXED_NOTICE); // 응답 없는 오류 화면의 고정 안내
    await expect(page.getByTestId("emergency-entry")).toBeVisible(); // 119 접근
    await page.waitForTimeout(300);
    expect(await requests(page)).toHaveLength(1);
    const retry = page.getByRole("button", { name: "다시 시도" });
    await expectTouchTarget(retry);
    await retry.click();
    await expect(page.getByTestId("result-card")).toBeVisible();
    expect(await requests(page)).toHaveLength(2);
    await expect(page.locator("[data-turn]")).toHaveCount(1); // 같은 차례에서 다시 보냈다
    await expectNoHorizontalScroll(page);
  });

  test("오류: 아직 연결되지 않은 서버(501)는 승인 문구를, 형식 오류(422)는 다시 시도 없이 보인다", async ({ page }) => {
    await mockChat(page, "http501", "http422");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toContainText("아직 준비 중이라 답을 드릴 수 없어요. 급하면 약국·약사에게 확인하세요.");
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await ask(page, "둘째 질문");
    const second = page.locator('[data-turn="turn-2"]').getByTestId("error-state");
    await expect(second).toContainText("질문을 다시 적어 보내 주세요.");
    await expect(page.getByRole("button", { name: "다시 시도" })).toHaveCount(0);
  });

  test("서버 오류 이벤트: 받은 오류 문구를 그대로 보이고 다시 시도를 둔다", async ({ page }) => {
    await mockChat(page, "serverErrorNoMessage");
    await openApp(page);
    await ask(page);
    const error = page.getByTestId("error-state");
    await expect(error).toContainText("지금은 확인에 필요한 곳에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.");
    await expect(error).not.toContainText("보낸 질문은 그대로 있어요."); // 화면 상수가 아니라 받은 문구다
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await expect(page.getByTestId("result-view")).toHaveCount(0);
  });

  test("끊김: 119는 그대로 남고 부분 결과는 보이지 않는다", async ({ page }) => {
    await mockChat(page, "emergencyCut");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toBeVisible();
    await expect(page.locator("[data-turn]")).toHaveAttribute("data-status", "interrupted");
    await expectInFirstScreen(page, banner(page));
    await expect(page.getByTestId("result-view")).toHaveCount(0);
    await expect(page.getByRole("status", { name: "진행 상태" })).toHaveCount(0);
    await expect(page.getByTestId("mascot")).toHaveCount(0); // 119가 떠 있으면 오류 카드의 마스코트도 숨긴다
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await expect(tel(page)).toHaveCount(1);
  });

  test("끊김(응급 아님): 진행 중에 끊기면 결과 없이 오류만 보인다", async ({ page }) => {
    await mockChat(page, "cutBeforeAnswer");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("error-state")).toBeVisible();
    await expect(page.getByTestId("result-view")).toHaveCount(0);
    await expect(banner(page)).toHaveCount(0);
  });

  test("새 질문: 대화·119를 비우고 시작 화면으로 돌아간다(드로어, 터치 영역 44px)", async ({ page }) => {
    await mockChat(page, "emergency");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    const drawer = page.getByTestId("menu-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("current-chat")).toHaveText(QUESTION);
    await expectTouchTarget(drawer.getByRole("button", { name: "메뉴 닫기" }));
    await expectTouchTarget(drawer.getByTestId("new-chat"));
    // 드로어가 열려 있어도 119 배너는 스크림 밖에 있고 덮이지 않는다(배너가 있으니 드로어 안 진입점은 없다)
    await expectInFirstScreen(page, banner(page));
    await expectOnTop(bannerTel(page));
    await expect(layerTel(page)).toHaveCount(0);
    const drawerBox = (await drawer.boundingBox())!;
    expect(drawerBox.y).toBeGreaterThanOrEqual((await banner(page).boundingBox())!.y + (await banner(page).boundingBox())!.height - 0.5);
    await drawer.getByTestId("new-chat").click();
    await expect(drawer).toHaveCount(0);
    await expect(page.getByTestId("home")).toBeVisible();
    await expect(banner(page)).toHaveCount(0);
    await expect(page.locator("[data-turn]")).toHaveCount(0);
  });

  test("질문·응답을 브라우저 저장소·쿠키에 남기지 않는다", async ({ page, context }) => {
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    const stored = await page.evaluate(async () => {
      const dump = (storage: Storage) => JSON.stringify(Object.fromEntries(Object.entries(storage)));
      const names = (await indexedDB.databases?.())?.map((db) => db.name) ?? [];
      // 저장소를 들여다보는 시험이라 이 줄만 규칙을 끈다
      // eslint-disable-next-line no-restricted-properties
      return { local: dump(window.localStorage), session: dump(window.sessionStorage), indexed: names };
    });
    for (const text of [stored.local, stored.session]) {
      expect(text).not.toContain("합성 질문");
      expect(text).not.toContain("가나다정");
    }
    expect(stored.indexed).toEqual([]);
    expect(JSON.stringify(await context.cookies())).not.toContain("가나다정");
  });
});

// ============================================================ 결과 모양(디자인 반영본 새 보드, 지시서 A2)
for (const width of [360, 320]) {
  test.describe(`결과 모양 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    const answered = async (page: Page, name: ScenarioName) => {
      await mockChat(page, name);
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-view")).toBeVisible();
    };

    test("배지 두 개(등급 불일치): 잘리지 않고 박스 안에 있다(F3)", async ({ page }) => {
      await answered(page, "gradeMismatch");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
      expect(await expectContained(card, '[data-testid="status-badge"], [data-testid="line-title"]')).toBe(3);
      await page.getByTestId("evidence-entry").click();
      await expectContained(sheet(page), '[data-testid="status-badge"], [data-testid="source-tag"], [data-testid="date-lines"] li');
      await expectNoHorizontalScroll(page);
    });

    test("병용 + 임부: 종류별 배지가 줄마다 보이고 응급 아닌 화면에 119 배너가 없다", async ({ page }) => {
      await answered(page, "pairAndPregnancy");
      await expect(page.getByTestId("status-badge")).toHaveText(["삐! 병용금기", "삐! 임부금기 2등급"]);
      await expect(banner(page)).toHaveCount(0);
      await expectContained(page.getByTestId("result-card"), '[data-testid="status-badge"], [data-testid="line-title"]');
      await expectNoHorizontalScroll(page);
    });

    test("미확보 세 원인: 응답 문구와 약사 확인 권고가 접히지 않고 보인다(Detail-Missing3)", async ({ page }) => {
      await answered(page, "missingCauses");
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]); // 받은 순서: 권고 → 고정
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page).getByTestId("missing-text")).toHaveText([
        "가나다정은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요",
        "라마바캡슐 허가사항에는 이 항목이 따로 적혀 있지 않아요",
        "지금은 허가사항을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요",
      ]);
      // 권고는 구역마다 1개(FE-02-05 A): 허가사항 구역의 미확보 묶음 하나. 항목 3개는 그 아래 목록이다
      const advice = sheet(page).getByTestId("pharmacist-advice");
      await expect(advice).toHaveCount(1);
      await expect(sheet(page).getByTestId("missing-group")).toHaveCount(1);
      await expect(sheet(page).getByTestId("missing-box")).toHaveCount(3);
      // 약 이름은 서버처럼 " · "로 잇는다(finalize.py 291행, FE-IMPL-06b fixture 정정)
      await expect(advice.first()).toHaveText("복용 전에 꼭 약국·약사에게 가나다정 · 라마바캡슐을 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.");
      expect(await sheet(page).locator("details").count()).toBe(0);
      await expect(sheet(page).getByTestId("mascot")).toHaveCount(0);
      await expectContained(sheet(page), '[data-testid="missing-text"], [data-testid="pharmacist-advice"]');
      await expectNoHorizontalScroll(page);
    });

    test("등급 정의 미확보 + 허가사항 미확보: 권고가 구역마다 그 종류의 줄만 보인다(AG-08-28 A)", async ({ page }) => {
      await answered(page, "gradeDefAndMissing");
      await page.getByTestId("evidence-entry").click();
      const missingAdvice = "복용 전에 꼭 약국·약사에게 라마바캡슐을 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.";
      const gradeDefAdvice = "등급의 뜻이 궁금하면 약국·약사에게 물어보세요.";
      // 등급 정의 블록(판정 구역): 등급 뜻 권고만. 허가사항 미확보 묶음: 약 조합 권고만. 두 구역에 같은 줄이 섞이지 않는다
      await expect(sheet(page).getByTestId("grade-def-missing").getByTestId("pharmacist-advice").locator("p")).toHaveText([gradeDefAdvice]);
      await expect(sheet(page).getByTestId("missing-group").getByTestId("pharmacist-advice").locator("p")).toHaveText([missingAdvice]);
      await expect(sheet(page).getByTestId("pharmacist-advice")).toHaveCount(2);
      await expect(sheet(page).getByTestId("missing-box")).toHaveCount(1);
      expect(await sheet(page).locator("details").count()).toBe(0);
      await expect(sheet(page).getByTestId("mascot")).toHaveCount(0);
      await expectContained(sheet(page), '[data-testid="missing-text"], [data-testid="pharmacist-advice"], [data-testid="grade-def-missing"]');
      await expectNoHorizontalScroll(page);
    });

    test("제품 줄 묶음: evidence_id가 없는 줄들도 근거 상세가 열리고, 복합제 칩은 모름으로 이름만 보인다(BE-06-40·41 A)", async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(error.message));
      await answered(page, "productRows");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("line-title")).toHaveText(["가나다정", "라마바캡슐", "가나다정 · 라마바캡슐"]);
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 병용금기", "삐! 병용금기", "삐! 임부금기 2등급", "삐! 병용금기"]);
      // 복합제 줄(첫 줄): 원인·중복 칸이 없는 칩은 모름이고 상태 글자가 없다
      const comboChips = card.getByTestId("product-line").first().getByTestId("ingredient-chip");
      await expect(comboChips).toHaveText(["가나성분", "사아성분"]);
      for (const chip of await comboChips.all()) await expect(chip).toHaveAttribute("data-state", "unknown");
      await expectContained(card, '[data-testid="status-badge"], [data-testid="line-title"], [data-testid="ingredient-chip"]');
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page).getByTestId("judgment-box")).toHaveCount(3);
      await expect(sheet(page).getByTestId("reason-box")).toHaveCount(2);
      await expectContained(sheet(page), '[data-testid="status-badge"], [data-testid="source-tag"], [data-testid="ingredient-chip"]');
      await expectNoHorizontalScroll(page);
      expect(errors.filter((text) => /key|Each child/i.test(text))).toEqual([]);
    });

    test("검증 폴백 두 가지: 요약 문구와 고정 영역 줄이 응답 값 그대로다(Result-FallbackNone·FallbackSome)", async ({ page }) => {
      await mockChat(page, "fallbackNone", "fallbackSome");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-summary")).toHaveText("검색한 자료에서는 확인하지 못했어요. 정확한 확인은 약국·약사에게 하세요.");
      await expect(page.getByTestId("result-card")).toHaveCount(0);
      await expect(page.getByTestId("evidence-entry")).toHaveCount(0);
      // 확인하지 못한 줄이 없으면 서버는 권고 줄을 붙이지 않는다(finalize: unresolved일 때만, FE-IMPL-06b fixture 정정)
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
      await ask(page, "둘째 질문");
      const second = page.locator('[data-turn="turn-2"]');
      await expect(second.getByTestId("result-summary")).toHaveText(
        "병용금기 파일(기준일 2026-07-31)에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요.",
      );
      await expect(second.getByTestId("result-card")).toBeVisible();
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectNoHorizontalScroll(page);
    });

    test("허가사항 원문 인용: 머리 형식과 원문, 표 없음(Detail-RxPermit)", async ({ page }) => {
      await answered(page, "rxPermit");
      await page.getByTestId("evidence-entry").click();
      const permit = sheet(page).getByTestId("permit-text");
      await expect(permit.locator("b")).toHaveText(["가나다정 허가사항 원문(사용상 주의사항)", "가나다정 허가사항 원문(용법용량)"]);
      await expect(permit.locator("q")).toContainText(["(합성 원문)", "(합성 원문)"]);
      expect(await permit.locator("table, dl, ul").count()).toBe(0);
      // 서버 상수 줄(BE-06-15, UI-611): 한 줄 설명은 구역에 한 번, 전문의약품 안내 줄은 그 근거에만, 인용 고지는 용법용량 인용 아래에만
      await expect(sheet(page).getByTestId("label-help")).toHaveText(["허가사항: 식약처가 의약품을 허가할 때 정한 효능·효과, 용법·용량, 사용상 주의사항이에요."]);
      await expect(permit.nth(0).getByTestId("easy-text-missing")).toHaveText("가나다정은 전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요");
      await expect(permit.nth(1).getByTestId("easy-text-missing")).toHaveCount(0);
      await expect(permit.nth(0).getByTestId("quote-notice")).toHaveCount(0);
      await expect(permit.nth(1).getByTestId("quote-notice")).toHaveText("허가사항 원문 인용이며 복용 지시가 아닙니다. 복용량은 약사·의사에게 확인하세요.");
      await expect(permit.first().getByTestId("source-tag")).toHaveText("공식 자료 · 의약품 허가정보");
      await expectContained(sheet(page), '[data-testid="label-help"], [data-testid="easy-text-missing"], [data-testid="quote-notice"], [data-testid="source-tag"]');
      await expect(sheet(page).getByTestId("source-dataset")).toHaveText(["의약품 허가정보", "병용금기 파일"]); // 출처 행 순서 = 응답 순서
      await expectNoHorizontalScroll(page);
    });

    test("연령금기: 판정 줄과 나이 기준 값이 가려지지 않는다(Result-AgeContra, G-7)", async ({ page }) => {
      await answered(page, "ageFound");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 연령금기"]);
      await expect(card.getByText("12세 미만")).toBeVisible();
      expect(await card.evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("약을 찾지 못함: 찾아본 내용의 칸 이름이 한 줄이다(F11)", async ({ page }) => {
      await answered(page, "unidentified");
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await page.getByTestId("evidence-entry").click();
      const pairs = sheet(page).getByTestId("lookup-pairs");
      await expect(pairs).toBeVisible();
      // 칸 이름 글자가 한 줄인가(칸 높이는 옆 값 칸을 따라 늘어나므로 글자가 놓인 줄 수를 센다)
      const labels = await pairs.locator("dt").evaluateAll((els) =>
        els.map((el) => {
          const range = document.createRange();
          range.selectNodeContents(el);
          return { text: el.textContent, lines: new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size };
        }),
      );
      expect(labels).toEqual(["입력한 이름", "찾아본 곳", "못 찾은 이유", "다음에 해 보세요"].map((text) => ({ text, lines: 1 })));
      await expect(sheet(page)).not.toContainText("삐!");
      await expectNoHorizontalScroll(page);
    });

    test("쌍 확인 불가: 확인하지 못했다는 문장이 한 번만, 식별된 약은 `찾음`과 성분 이름으로 보인다(Result-NoEvidence6c)", async ({ page }) => {
      // fixture = AG-08 병합 뒤 backend finalize → to_chat_response 출력 모양(쌍 줄의 notes·why·next 없음, 식별된 약 줄은 찾음 + 보조줄)
      const PAIR_NOT_CHECKED = "이 약과 함께 먹어도 되는지는 식약처·한국의약품안전관리원 자료에서 확인하지 못했어요. 안전하다는 뜻이 아니에요.";
      await answered(page, "pairNoEvidence");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("line-title")).toHaveText(["가나다정", "가나다정 · 사아자시럽"]);
      await expect(card.getByTestId("line-text")).toHaveText(["찾음", PAIR_NOT_CHECKED]);
      await expect(card.getByText(PAIR_NOT_CHECKED)).toHaveCount(1); // 같은 문장이 두 번 보이지 않는다
      const lines = card.getByTestId("product-line");
      await expect(lines.nth(0).locator('[data-slot="sub-line"]')).toHaveText("가나성분 · 사아성분");
      await expect(lines.nth(0).getByTestId("ingredient-chip")).toHaveCount(0);
      await expect(lines.nth(0)).not.toContainText("금기 목록에 없음");
      await expect(lines.nth(1).locator('[data-slot="notes"], [data-slot="why"], [data-slot="next"]')).toHaveCount(0);
      await expect(card.getByTestId("status-badge")).toHaveCount(0);
      await expect(card).not.toContainText("삐!");
      expect(await card.evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("나이를 특정할 수 없을 때: 판정 대신 안내 줄과 나이별 기준 값이 접히지 않고 보인다(Result-Infant)", async ({ page }) => {
      const AGE_INFO_LINE = "나이를 특정할 수 없어 판정하지 않고, 이 약의 나이별 연령금기 기준을 원문 그대로 보여 드려요.";
      await answered(page, "ageInfo");
      const card = page.getByTestId("result-card");
      const age = card.getByTestId("product-line").nth(0);
      await expect(age.getByTestId("line-title")).toHaveText("사아자시럽");
      // 안내 줄(서버 상수) → 나이 기준 값(원문, 한 값에 한 줄). 받은 순서 그대로
      await expect(age.locator('[data-slot="age-info"], [data-slot="age-criteria"]')).toHaveText([AGE_INFO_LINE, "12세 미만", "6개월 미만"]);
      await expect(age.getByTestId("status-badge")).toHaveCount(0); // 판정 배지("삐!")가 없다
      await expect(age).not.toContainText("삐!");
      // 성분 칩 상태 글자는 응답 값 그대로
      await expect(age.getByTestId("ingredient-chip")).toHaveText(["사아성분 · 중복"]);
      // 성분 중복 줄(주의 종류)의 글자도 받은 그대로
      await expect(card.getByTestId("product-line").nth(1).getByTestId("line-text")).toHaveText("성분 중복");
      expect(await card.evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expect(age.locator('[data-slot="age-info"]')).toBeVisible();
      await expectContained(card, '[data-slot="age-info"], [data-slot="age-criteria"], [data-testid="line-text"], [data-testid="ingredient-chip"]');
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("나이를 특정할 수 없을 때의 근거 상세: 판정 박스에 같은 안내·기준 값과 출처 종류 글자가 보인다(Detail-Infant)", async ({ page }) => {
      const AGE_INFO_LINE = "나이를 특정할 수 없어 판정하지 않고, 이 약의 나이별 연령금기 기준을 원문 그대로 보여 드려요.";
      await answered(page, "ageInfo");
      await page.getByTestId("evidence-entry").click();
      const box = sheet(page).getByTestId("judgment-box").nth(0);
      await expect(box.locator('[data-slot="age-info"], [data-slot="age-criteria"]')).toHaveText([AGE_INFO_LINE, "12세 미만", "6개월 미만"]);
      await expect(box.getByTestId("source-tag")).toHaveText("공식 파일 · 연령금기 파일"); // 종류 글자 · 자료 이름(받은 값)
      await expect(sheet(page).getByTestId("source-dataset")).toHaveText(["연령금기 파일"]); // 출처 표의 자료 열과 같은 글자
      await expect(box.getByTestId("status-badge")).toHaveCount(0);
      await expect(sheet(page)).not.toContainText("삐!");
      expect(await sheet(page).locator("details").count()).toBe(0);
      await expect(sheet(page).getByTestId("mascot")).toHaveCount(0);
      await expect(sheet(page).getByTestId("fixed-notice")).toHaveCount(0); // 고정 안내는 시트 밖
      await expectContained(sheet(page), '[data-slot="age-info"], [data-slot="age-criteria"], [data-testid="source-tag"], [data-testid="date-lines"] li');
      await expectNoHorizontalScroll(page);
    });

    test("성분 칩 상태 글자·출처 종류 글자: 받은 글자 그대로 보인다(BE-06-13·14)", async ({ page }) => {
      await answered(page, "pregnancy");
      await expect(page.getByTestId("result-card").getByTestId("ingredient-chip")).toHaveText(["라마성분 · 금기 원인", "사아성분 · 중복"]);
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page).getByTestId("source-tag").first()).toHaveText("공식 파일 · 임부금기 파일");
      await expectContained(sheet(page), '[data-testid="ingredient-chip"], [data-testid="source-tag"]');
      await expectNoHorizontalScroll(page);
    });

    test("등급 정의 블록: 원문 블록은 접혀 있고 미확보 문구·약사 권고는 접힘 밖에 보인다(BE-06-16·17)", async ({ page }) => {
      await answered(page, "gradeDefs");
      await page.getByTestId("evidence-entry").click();
      const block = sheet(page).getByTestId("grade-def");
      const trigger = block.getByRole("button", { name: "임부금기 2등급이란?" });
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await expectTouchTarget(trigger, { widthToo: false });
      const missing = block.getByTestId("grade-def-missing");
      await expect(missing.locator(":scope > p")).toHaveText(["지금은 임부금기 1등급의 뜻(고시 원문)을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요."]);
      await expect(missing.getByTestId("pharmacist-advice")).toHaveText("등급의 뜻이 궁금하면 약국·약사에게 물어보세요.");
      await expect(block.getByRole("button", { name: "임부금기 1등급이란?" })).toHaveCount(0);
      await trigger.click();
      await expect(block.locator("blockquote")).toHaveText("(합성 고시 원문) 사람에서 태아에 대한 위해성이 나타날 수 있어 원칙적으로 사용금지.");
      // 조항 글자(FE-02 §2 FR-04): 고시 이름과 조·호·목이 받은 글자 그대로, 원문 인용 바로 아래에 보인다
      const clause = block.locator('[data-slot="grade-def-source"]');
      await expect(clause).toHaveCount(1);
      await expect(clause).toHaveText("(합성 출처 줄) 「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 나목");
      await expect(clause).toBeVisible();
      expect(await clause.evaluate((el) => el.previousElementSibling?.tagName)).toBe("BLOCKQUOTE");
      await expectContained(sheet(page), '[data-slot="grade-def-source"]');
      await expect(sheet(page).getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("코드가 이어지지 않은 줄: 바뀐 안내 문구가 받은 그대로 한 번 보이고 판정 배지가 없다", async ({ page }) => {
      const NOTE = "금기 목록에서 확인하지 못했지만, 안전하다는 뜻이 아니에요. 약사에게 확인하세요";
      await answered(page, "codeNotLinked");
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("line-text")).toHaveText("약을 찾지 못해 확인하지 못함");
      await expect(card.locator('[data-slot="notes"]')).toHaveText([NOTE]);
      await expect(card.getByText(NOTE)).toHaveCount(1);
      await expect(card.getByTestId("status-badge")).toHaveCount(0);
      await expect(card).not.toContainText("금기 목록에 없음");
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("확인하지 못한 종류의 줄·공공 API 실패 배너: 받은 글자 그대로 접히지 않고 보인다", async ({ page }) => {
      await mockChat(page, "notChecked", "apiFail");
      await openApp(page);
      await ask(page);
      const lines = page.getByTestId("not-checked-lines").locator("li");
      await expect(lines).toHaveText(["임신 여부를 알 수 없어 임부금기는 확인하지 못했어요."]);
      await expect(lines.first()).toBeVisible();
      expect(await page.getByTestId("not-checked-lines").evaluate((el) => el.closest("details, [data-state=closed]") === null)).toBe(true);
      await expect(page.getByTestId("status-badge")).toHaveCount(0);
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await ask(page, "둘째 질문");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-notice")).toHaveText("실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.");
      await expect(page.getByTestId("mascot")).toHaveCount(0);
      await expectNoHorizontalScroll(page);
    });

    test("상한 도달·목록에 없음: 안내 줄과 '안전하다는 뜻이 아님'이 접히지 않고 보인다", async ({ page }) => {
      await mockChat(page, "limit", "notListed");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-notice")).toContainText("여기까지 확인한 결과만 보여 드려요.");
      await ask(page, "둘째 질문");
      const second = page.locator('[data-turn="turn-2"]');
      await expect(second.getByTestId("line-text")).toHaveText("금기 목록에 없음(안전하다는 뜻이 아님)");
      await expect(second.getByTestId("status-badge")).toHaveCount(0); // "삐!"는 금기 발견에만
      expect(await second.getByTestId("result-card").evaluate((el) => el.querySelector("details") === null)).toBe(true);
      await expectNoHorizontalScroll(page);
    });

    test("글자색과 바탕색이 같지 않다(F5)", async ({ page }) => {
      await answered(page, "found");
      const colors = await page.evaluate(() => {
        const read = (el: Element) => getComputedStyle(el).color;
        return {
          body: getComputedStyle(document.body).backgroundColor,
          summary: read(document.querySelector('[data-testid="result-summary"]')!),
          input: read(document.querySelector("textarea")!),
        };
      });
      expect(colors.summary).not.toBe(colors.body);
      expect(colors.input).not.toBe(colors.body);
    });
  });
}

// ============================================================ 반응형 셸 폭 시험(FE-07-09 B)
const WIDTHS = [1280, 900, 700, 393, 360];
for (const width of WIDTHS) {
  const desktop = width >= 1024;
  test.describe(`셸 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면: 119 진입점·고지·입력창이 첫 화면에 있다(G-3)", async ({ page }) => {
      await openApp(page);
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectTouchTarget(page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      if (desktop) {
        await expect(pushSidebar(page)).toBeVisible();
        await expect(page.getByRole("button", { name: "메뉴 열기" })).toHaveCount(0);
      } else {
        await expect(page.getByTestId("sidebar")).toHaveCount(0);
        await expect(rail(page)).toHaveCount(0);
        await expectTouchTarget(page.getByRole("button", { name: "메뉴 열기" }));
      }
      // 겹침 없음: 119 진입점이 다른 요소에 덮이지 않는다
      await expectOnTop(page.getByTestId("emergency-entry"));
      await expectNoHorizontalScroll(page);
    });

    test("결과: 넓은 폭은 사이드바+가운데 열+우측 패널, 좁은 폭은 ☰ 드로어+시트(진입 글자 G-1)", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      const entry = page.getByTestId("evidence-entry");
      await expect(entry).toHaveText(width >= 700 ? "근거 상세 열기" : "근거 상세 보기");
      await expect(entry).not.toContainText("펼치기");
      if (desktop) {
        // 사이드바 + 가운데 열 + 우측 근거 패널이 겹치지 않고 나란히 있다
        await expect(panel(page)).toBeVisible();
        const side = (await pushSidebar(page).boundingBox())!;
        const mainBox = (await page.getByTestId("main").boundingBox())!;
        const panelBox = (await panel(page).boundingBox())!;
        expect(side.width).toBe(272);
        expect(panelBox.width).toBe(400);
        expect(mainBox.x).toBeGreaterThanOrEqual(side.x + side.width - 0.5);
        expect(panelBox.x).toBeGreaterThanOrEqual(mainBox.x + mainBox.width - 0.5);
        expect(mainBox.width).toBeGreaterThanOrEqual(560);
        await expect(entry).toHaveAttribute("aria-expanded", "true");
        await expect(panel(page).getByTestId("fixed-notice")).toHaveCount(0);
        await expectTouchTarget(panel(page).getByRole("button", { name: "닫기" }));
        await panel(page).getByRole("button", { name: "닫기" }).click();
        await expect(panel(page)).toHaveCount(0);
        await expect(entry).toBeFocused(); // 닫으면 들어온 결과로
        await entry.click();
        await expect(panel(page)).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(panel(page)).toHaveCount(0);
      } else {
        await expect(page.getByTestId("sidebar")).toHaveCount(0);
        await expect(sheet(page)).toHaveCount(0);
        await entry.click();
        await expect(sheet(page).getByTestId("evidence-section").first()).toBeVisible();
        const box = (await sheet(page).boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        await page.keyboard.press("Escape");
        await expect(sheet(page)).toHaveCount(0);
        // ☰ 드로어
        await page.getByRole("button", { name: "메뉴 열기" }).click();
        const drawer = page.getByTestId("menu-drawer");
        await expect(drawer).toBeVisible();
        expect((await drawer.boundingBox())!.width).toBeLessThanOrEqual(320);
        await page.keyboard.press("Escape");
        await expect(drawer).toHaveCount(0);
        await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeFocused();
      }
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, input(page));
      await expectNoHorizontalScroll(page);
    });

    test("응급: 어느 폭에서도 119 배너와 고정 안내가 첫 화면에 있다", async ({ page }) => {
      await mockChat(page, "emergency");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expectInFirstScreen(page, banner(page));
      await expectOnTop(tel(page));
      await expect(tel(page)).toHaveCount(1);
      await expect(page.getByText(EMERGENCY_TEXT)).toHaveCount(1);
      // 넓은 폭 보조 문장(FE-07-15): 응답 값 그대로, 1024 이상에서만 보인다. 연락처가 아니므로 전화 링크는 하나 그대로다
      const wide = banner(page).getByTestId("emergency-wide");
      await expect(wide).toHaveText("컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요.");
      if (desktop) {
        await expect(wide).toBeVisible();
        await expectInFirstScreen(page, wide);
      } else {
        await expect(wide).toBeHidden();
      }
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      expect(await page.getByTestId("app-shell").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"))).toBe("emergency-row");
      await expectNoHorizontalScroll(page);
    });
  });
}

// ============================================================ 사이드바와 근거 상세(FE-07-19·22, 지시서 §8~§11)
/** 스크림이 DOM에 한 번이라도 나타났는지 센다(자동 열림 직후 한 프레임도 보이지 않아야 한다, §11 ⑦) */
async function watchScrim(page: Page) {
  await page.addInitScript(() => {
    const seen = { count: 0 };
    (window as unknown as { __scrim: typeof seen }).__scrim = seen;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node instanceof Element && (node.matches('[data-testid="sidebar-scrim"]') || node.querySelector('[data-testid="sidebar-scrim"]'))) seen.count += 1;
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
}
const scrimSeen = (page: Page) => page.evaluate(() => (window as unknown as { __scrim: { count: number } }).__scrim.count);

async function askAndAutoOpen(page: Page, question = QUESTION) {
  await ask(page, question);
  await expect(panel(page)).toBeVisible();
}

/**
 * 입력창·고정 안내·119. 오버레이가 열려 있으면(사용자가 연 층) 입력창·고정 안내는 스크림 아래에서 흐려질 수 있으나 접히지 않고 첫 화면에 있으며,
 * 119는 머리줄이 덮이므로 오버레이 안의 진입점이 덮이지 않고 눌린다. 닫힌 상태면 셋 다 덮임 없이 위에 있다.
 */
async function expectSafetyVisible(page: Page, { overlayOpen = false } = {}) {
  await expectInFirstScreen(page, input(page), { underUserLayer: overlayOpen });
  await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"), { underUserLayer: overlayOpen });
  if (overlayOpen) {
    await expect(overlaySidebar(page).getByTestId("layer-emergency-entry")).toHaveCount(1);
    await expectInFirstScreen(page, layerTel(page));
    await expectOnTop(layerTel(page));
  } else {
    await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
  }
}

const COLLAPSE_WIDTHS = [1024, 1100, 1180, 1231];
const KEEP_WIDTHS = [1232, 1240, 1279, 1280, 1400];

for (const width of COLLAPSE_WIDTHS) {
  test.describe(`사이드바 ${width}px(근거 상세가 열리면 접힘)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("자동 열림: 레일로 접히고 스크림은 한 번도 생기지 않는다. 다시 펼치면 오버레이+전체 스크림이다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await expect(pushSidebar(page)).toBeVisible(); // 첫 화면은 펼침
      await askAndAutoOpen(page);
      // ① 접힘, dim 없음
      await expect(rail(page)).toBeVisible();
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      await expect(scrim(page)).toHaveCount(0);
      expect(await scrimSeen(page)).toBe(0);
      expect((await rail(page).boundingBox())!.width).toBe(60); // F9
      expect((await panel(page).boundingBox())!.width).toBe(400);
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      expect(width - 60 - 400).toBeGreaterThanOrEqual(560);
      await expectSafetyVisible(page);

      // ② 직후 토글: 오버레이로 펼쳐지고 근거 상세는 닫히지 않는다
      const expand = page.getByRole("button", { name: "사이드바 펼치기" });
      await expectTouchTarget(expand);
      await expand.click();
      await expect(overlaySidebar(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      const scrimBox = (await scrim(page).boundingBox())!;
      const panelBox = (await panel(page).boundingBox())!;
      const body = (await page.getByTestId("shell-body").boundingBox())!;
      expect(scrimBox).toEqual(body); // 스크림이 패널까지 덮는다
      expect(scrimBox.x + scrimBox.width).toBeGreaterThanOrEqual(panelBox.x + panelBox.width - 0.5);
      // 뒤 요소는 조작할 수 없다
      await expect(page.getByTestId("main")).toHaveAttribute("inert", "");
      await expect(page.getByTestId("panel-column")).toHaveAttribute("inert", "");
      expect(await page.evaluate(() => document.elementFromPoint(window.innerWidth - 20, window.innerHeight / 2)?.getAttribute("data-testid"))).toBe("sidebar-scrim");
      // ③ 본문 칸은 그대로(레일 기준)이고 입력창·고정 안내가 첫 화면 안(접히지 않음), 119는 오버레이 안에서 덮이지 않는다
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      await expectSafetyVisible(page, { overlayOpen: true });
      expect((await overlaySidebar(page).boundingBox())!.width).toBe(272);

      // Tab이 오버레이 뒤 요소에 닿지 않는다
      for (let i = 0; i < 6; i += 1) {
        await page.keyboard.press("Tab");
        expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="sidebar"]') !== null)).toBe(true);
      }
      // Esc: 사이드바만 닫히고 근거 상세는 그대로, 초점은 토글 버튼으로
      await page.keyboard.press("Escape");
      await expect(scrim(page)).toHaveCount(0);
      await expect(rail(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      await expect(expand).toBeFocused();
      await expect(page.getByTestId("main")).not.toHaveAttribute("inert", "");
      await expectSafetyVisible(page); // 닫으면 고정 안내·입력창·머리줄 119가 다시 덮임 없이 위에 있다

      // 스크림 클릭(패널 위): 사이드바만 닫힌다
      await expand.click();
      await expect(scrim(page)).toBeVisible();
      await page.mouse.click(width - 30, HEIGHT / 2);
      await expect(scrim(page)).toHaveCount(0);
      await expect(panel(page)).toBeVisible();
      // 오버레이 안의 접기 버튼
      await expand.click();
      await expectTouchTarget(overlaySidebar(page).getByRole("button", { name: "사이드바 접기" }));
      await overlaySidebar(page).getByRole("button", { name: "사이드바 접기" }).click();
      await expect(scrim(page)).toHaveCount(0);
      await expect(panel(page)).toBeVisible();
      await expectNoHorizontalScroll(page);
    });

    test("E2: 닫고 사이드바를 펼친 뒤 다시 열면 다시 접힌다(스크림 없음)", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await askAndAutoOpen(page);
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(rail(page)).toBeVisible(); // 닫아도 사이드바는 그대로(접힘)
      await page.getByRole("button", { name: "사이드바 펼치기" }).click();
      await expect(pushSidebar(page)).toBeVisible(); // 패널이 없으면 밀어서 펼친다
      await expect(scrim(page)).toHaveCount(0);
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(rail(page)).toBeVisible();
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      expect(await scrimSeen(page)).toBe(0);
    });
  });
}

for (const width of KEEP_WIDTHS) {
  test.describe(`사이드바 ${width}px(펼침 유지)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("자동 열림: 펼침을 유지하고 밀어서 보인다. 토글은 근거 상세를 닫지 않는다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found");
      await openApp(page);
      await askAndAutoOpen(page);
      await expect(pushSidebar(page)).toBeVisible();
      await expect(scrim(page)).toHaveCount(0);
      // 본문이 Wmin 이상이라 문장 중간에서 잘리지 않는다
      const mainBox = (await page.getByTestId("main").boundingBox())!;
      expect(mainBox.width).toBe(width - 272 - 400);
      expect(mainBox.width).toBeGreaterThanOrEqual(560);
      await expectContained(page.getByTestId("main"), '[data-testid="result-summary"], [data-testid="fixed-notice"], [data-testid="status-badge"]');
      await expectSafetyVisible(page);
      // 토글: 접기 → 레일, 펼치기 → 밀기. 근거 상세는 계속 열려 있다
      const collapse = page.getByRole("button", { name: "사이드바 접기" });
      await expectTouchTarget(collapse);
      await collapse.click();
      await expect(rail(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width - 60 - 400);
      await page.getByRole("button", { name: "사이드바 펼치기" }).click();
      await expect(pushSidebar(page)).toBeVisible();
      await expect(panel(page)).toBeVisible();
      // 근거 상세를 닫았다 다시 열어도 사이드바는 그대로다(E2: 1232 이상 유지)
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(pushSidebar(page)).toBeVisible();
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(pushSidebar(page)).toBeVisible();
      expect(await scrimSeen(page)).toBe(0);
      await expectNoHorizontalScroll(page);
    });
  });
}

for (const width of [1100, 1280, 1400]) {
  test.describe(`사이드바 독립 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("사용자가 접어 둔 사이드바는 근거 상세를 열고 닫아도 접힌 그대로다", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await page.getByRole("button", { name: "사이드바 접기" }).click();
      await expect(rail(page)).toBeVisible();
      await askAndAutoOpen(page);
      await expect(rail(page)).toBeVisible();
      await panel(page).getByRole("button", { name: "닫기" }).click();
      await expect(rail(page)).toBeVisible();
      await page.getByTestId("evidence-entry").click();
      await expect(panel(page)).toBeVisible();
      await expect(rail(page)).toBeVisible();
      await expect(scrim(page)).toHaveCount(0);
    });

    test("E3: 근거 상세가 열린 채 연속 질문을 보내도 사이드바가 바뀌지 않고, 상세는 새 답으로 바뀐다", async ({ page }) => {
      await watchScrim(page);
      await mockChat(page, "found", "pregnancy");
      await openApp(page);
      await askAndAutoOpen(page, "첫 질문");
      const before = await pushSidebar(page).count();
      await ask(page, "둘째 질문");
      await expect(panel(page).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급"]);
      expect(await pushSidebar(page).count()).toBe(before);
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("evidence-entry")).toHaveAttribute("aria-expanded", "true");
      await expect(page.locator('[data-turn="turn-1"]').getByTestId("evidence-entry")).toHaveAttribute("aria-expanded", "false");
      expect(await scrimSeen(page)).toBe(0);
    });
  });
}

test.describe("사이드바 엣지 1100px", () => {
  test.use({ viewport: { width: 1100, height: HEIGHT } });

  test("E4: '새 질문' 뒤 다음 답에서 다시 판정한다", async ({ page }) => {
    await watchScrim(page);
    await mockChat(page, "found");
    await openApp(page);
    await askAndAutoOpen(page);
    await expect(rail(page)).toBeVisible();
    await expectTouchTarget(rail(page).getByRole("button", { name: "새 질문" }));
    await rail(page).getByRole("button", { name: "새 질문" }).click();
    await expect(page.getByTestId("home")).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
    await page.getByRole("button", { name: "사이드바 펼치기" }).click();
    await expect(pushSidebar(page)).toBeVisible();
    await askAndAutoOpen(page);
    await expect(rail(page)).toBeVisible();
    expect(await scrimSeen(page)).toBe(0);
  });

  test("E7(사용자 결정 2026-11-16 후보 1 A): 되묻기 답에서는 근거 패널을 열지 않고 사이드바도 그대로다", async ({ page }) => {
    await mockChat(page, "clarify");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("candidate-card")).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
    await expect(pushSidebar(page)).toBeVisible();
    await expect(scrim(page)).toHaveCount(0);
  });

  test("응급 + 오버레이: 119 배너는 스크림 밖에 있어 가려지지 않고 누를 수 있다", async ({ page }) => {
    await mockChat(page, "emergency");
    await openApp(page);
    await askAndAutoOpen(page);
    await page.getByRole("button", { name: "사이드바 펼치기" }).click();
    await expect(scrim(page)).toBeVisible();
    await expectInFirstScreen(page, banner(page));
    const bannerBox = (await banner(page).boundingBox())!;
    expect((await scrim(page).boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
    expect((await overlaySidebar(page).boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
    // 배너가 있으면 119는 배너 하나뿐이다(오버레이 안 진입점 없음)
    await expect(layerTel(page)).toHaveCount(0);
    await expect(tel(page)).toHaveCount(1);
    // 고정 안내·입력창은 사용자가 연 층 동안 흐려질 수 있으나 접히지 않고 첫 화면에 있다
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"), { underUserLayer: true });
    await expectInFirstScreen(page, input(page), { underUserLayer: true });
    await expect119Reachable(page, bannerTel(page)); // 실제 클릭이 배너 링크에 닿는다(스크림·오버레이를 지나지 않는다)
    await expect(overlaySidebar(page)).toHaveCount(0); // 바깥 누름이라 오버레이는 닫힌다(Radix)
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
  });
});

test.describe("사이드바 엣지: 폭 변경", () => {
  test("E5: 근거 상세가 열린 채 1300 → 1100으로 줄이면 접지 않고 오버레이+스크림이 된다(스크림 클릭으로 사이드바만 닫힘)", async ({ page }) => {
    await page.setViewportSize({ width: 1300, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await askAndAutoOpen(page);
    await expect(pushSidebar(page)).toBeVisible();
    await page.setViewportSize({ width: 1100, height: HEIGHT });
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(scrim(page)).toBeVisible();
    await expect(panel(page)).toBeVisible();
    await page.mouse.click(1100 - 30, HEIGHT / 2);
    await expect(scrim(page)).toHaveCount(0);
    await expect(rail(page)).toBeVisible();
    await expect(panel(page)).toBeVisible();
    // 다시 넓혀도 사용자 상태(접힘)는 그대로다
    await page.setViewportSize({ width: 1300, height: HEIGHT });
    await expect(rail(page)).toBeVisible();
  });

  test("E6: 1000에서 근거 상세를 연 뒤 1100으로 넓히면 패널+오버레이가 되고 Esc로 사이드바만 닫힌다", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    await page.setViewportSize({ width: 1100, height: HEIGHT });
    await expect(panel(page)).toBeVisible();
    await expect(sheet(page)).toHaveCount(0);
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(scrim(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(scrim(page)).toHaveCount(0);
    await expect(panel(page)).toBeVisible();
    await expect(rail(page)).toBeVisible();
  });

  test("F10: 1023 ↔ 1024에서 드로어 ↔ 사이드바, 시트 ↔ 패널로 바뀌고 같은 요소(119·고정 안내·입력창·결과)가 양쪽에 있다", async ({ page }) => {
    await page.setViewportSize({ width: 1023, height: HEIGHT });
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    const same = async () => {
      await expectInFirstScreen(page, page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expectNoHorizontalScroll(page);
    };
    // 1023: ☰ 드로어, 근거 상세는 시트
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeVisible();
    await expect(page.getByTestId("sidebar")).toHaveCount(0);
    await same();
    await page.getByTestId("evidence-entry").click();
    await expect(sheet(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet(page)).toHaveCount(0);
    // 1024: 사이드바 칸, 근거 상세는 우측 패널
    await page.setViewportSize({ width: 1024, height: HEIGHT });
    await expect(pushSidebar(page)).toBeVisible();
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toHaveCount(0);
    await same();
    await page.getByTestId("evidence-entry").click();
    await expect(panel(page)).toBeVisible();
    await expect(sheet(page)).toHaveCount(0);
    await expect(rail(page)).toBeVisible(); // 새로 열렸으므로 1024에서는 접힌다
    await panel(page).getByRole("button", { name: "닫기" }).click();
    // 다시 1023: 사이드바 칸이 사라지고 ☰로 돌아온다
    await page.setViewportSize({ width: 1023, height: HEIGHT });
    await expect(rail(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeVisible();
    await same();
  });

  test("1023 이하: 768~1023도 사이드바 없이 ☰ 드로어이고 본문이 화면 폭을 다 쓴다(참고 ③)", async ({ page }) => {
    await mockChat(page, "found");
    for (const width of [768, 831, 1023]) {
      await page.setViewportSize({ width, height: HEIGHT });
      await openApp(page);
      await expect(page.getByTestId("sidebar")).toHaveCount(0);
      await expect(rail(page)).toHaveCount(0);
      expect((await page.getByTestId("main").boundingBox())!.width).toBe(width);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect(panel(page)).toHaveCount(0);
      await expectContained(page.getByTestId("main"), '[data-testid="result-summary"], [data-testid="fixed-notice"], [data-testid="status-badge"]');
      await expectNoHorizontalScroll(page);
    }
  });
});

// ============================================================ 119 덮임 방지(FE-IMPL-06b 할 일 1·2·3)
// 규칙: 119는 어떤 오버레이·시트에서도 덮이지 않는다. 배너가 없으면 머리줄을 덮는 층 안에 같은 진입점이 있고,
// 배너가 있으면 층은 배너 아래 영역에만 그려진다(사용자 결정 2026-11-16 후보 5 B). 고정 안내는 층 동안 덮일 수 있으나 닫으면 그대로다.
const sheetScrim = (page: Page) => page.getByTestId("sheet-scrim");
const drawer = (page: Page) => page.getByTestId("menu-drawer");

async function expectBelowBanner(page: Page, layer: ReturnType<Page["getByTestId"]>) {
  const bannerBox = (await banner(page).boundingBox())!;
  expect((await layer.boundingBox())!.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height - 0.5);
}

for (const width of [360, 320]) {
  test.describe(`119 덮임 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("드로어(배너 없음): 드로어 안 119 진입점이 덮이지 않고 눌린다(G-3)", async ({ page }) => {
      await openApp(page);
      await page.getByRole("button", { name: "메뉴 열기" }).click();
      await expect(drawer(page)).toBeVisible();
      await expect(drawer(page).getByTestId("layer-emergency-entry")).toHaveText("119 전화");
      await expect119Reachable(page, layerTel(page));
      await expect(drawer(page)).toBeVisible(); // 층 안의 링크라 눌러도 드로어는 그대로다
      // 머리줄 진입점은 드로어 스크림 아래다(그래서 층 안에 진입점을 둔다)
      expect(
        await page.getByTestId("emergency-entry").evaluate((el) => {
          const rect = el.getBoundingClientRect();
          const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
          return hit !== null && el.contains(hit);
        }),
      ).toBe(false);
      await page.keyboard.press("Escape");
      await expect(drawer(page)).toHaveCount(0);
      await expect(layerTel(page)).toHaveCount(0);
      await expect119Reachable(page, page.getByTestId("emergency-entry"));
    });

    test("근거 상세 시트(배너 없음): 시트 안 119 진입점이 덮이지 않고 눌린다. 고정 안내는 닫으면 그대로 위에 있다", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      await ask(page);
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page)).toBeVisible();
      // 응급이 아닐 때 시트·스크림은 화면 전체다(기존 동작)
      expect((await sheetScrim(page).boundingBox())!.y).toBe(0);
      await expect(sheet(page).getByTestId("layer-emergency-entry")).toHaveCount(1);
      await expect119Reachable(page, layerTel(page));
      await expect(sheet(page)).toBeVisible();
      // 시트 동안 고정 안내는 스크림 아래에서 흐려지지만 접히지 않고 첫 화면에 있다
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"), { underUserLayer: true });
      await sheet(page).getByRole("button", { name: "닫기" }).click();
      await expect(sheet(page)).toHaveCount(0);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect119Reachable(page, page.getByTestId("emergency-entry"));
    });

    test("응급 + 근거 상세 시트(결정 5 B): 시트와 스크림이 배너 아래에만 그려져 119 배너가 덮이지 않고 눌린다", async ({ page }) => {
      await mockChat(page, "emergency");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await page.getByTestId("evidence-entry").click();
      await expect(sheet(page).getByTestId("evidence-section").first()).toBeVisible();
      await expectBelowBanner(page, sheetScrim(page));
      await expectBelowBanner(page, sheet(page));
      const body = (await page.getByTestId("shell-body").boundingBox())!;
      expect(await sheetScrim(page).boundingBox()).toEqual(body); // 스크림 = 배너 아래 영역 전체
      await expect(layerTel(page)).toHaveCount(0); // 배너가 있으면 119는 배너 하나뿐
      await expect(tel(page)).toHaveCount(1);
      await expectInFirstScreen(page, banner(page));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"), { underUserLayer: true });
      await expectNoHorizontalScroll(page);
      await expect119Reachable(page, bannerTel(page));
      // 배너는 시트 바깥이라 누르면 시트가 닫힌다(Radix 바깥 누름). 고정 안내는 다시 덮임 없이 위에 있다
      await expect(sheet(page)).toHaveCount(0);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, banner(page));
    });

    test("응급 + 드로어: 배너 링크가 덮이지 않고 실제 클릭이 닿는다", async ({ page }) => {
      await mockChat(page, "emergency");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await page.getByRole("button", { name: "메뉴 열기" }).click();
      await expect(drawer(page)).toBeVisible();
      await expectBelowBanner(page, page.getByTestId("drawer-scrim"));
      await expect(layerTel(page)).toHaveCount(0);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"), { underUserLayer: true });
      await expect119Reachable(page, bannerTel(page));
      await expect(drawer(page)).toHaveCount(0);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
    });
  });
}

test.describe("119 덮임 1100px(사이드바 오버레이)", () => {
  test.use({ viewport: { width: 1100, height: HEIGHT } });

  test("오버레이(배너 없음): 오버레이 안 119 진입점이 덮이지 않고 눌린다", async ({ page }) => {
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await expect(panel(page)).toBeVisible();
    await page.getByRole("button", { name: "사이드바 펼치기" }).click();
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(overlaySidebar(page).getByTestId("layer-emergency-entry")).toHaveCount(1);
    await expect119Reachable(page, layerTel(page));
    await expect(overlaySidebar(page)).toBeVisible();
    await expect(page.getByTestId("main")).toHaveAttribute("inert", ""); // 머리줄 진입점은 오버레이 동안 쓸 수 없다
    await page.keyboard.press("Escape");
    await expect(overlaySidebar(page)).toHaveCount(0);
    await expect119Reachable(page, page.getByTestId("emergency-entry"));
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
  });
});

test.describe("119 덮임 1280px(패널)", () => {
  test.use({ viewport: { width: 1280, height: HEIGHT } });

  for (const name of ["found", "emergency"] as const) {
    test(`근거 패널이 열린 채(${name}): 119와 고정 안내가 덮이지 않고 119 클릭이 닿는다`, async ({ page }) => {
      await mockChat(page, name);
      await openApp(page);
      await ask(page);
      await expect(panel(page)).toBeVisible();
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect119Reachable(page, name === "emergency" ? bannerTel(page) : page.getByTestId("emergency-entry"));
    });
  }
});

// ============================================================ 작은 폭·높이(FE-IMPL-06b 할 일 7)
for (const viewport of [
  { width: 360, height: 640 },
  { width: 320, height: 568 },
]) {
  test.describe(`작은 화면 ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("응급 첫 화면: 119 배너·고정 안내·고지·입력창이 스크롤 없이 덮임 없이 들어온다", async ({ page }) => {
      await mockChat(page, "emergency");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      await expect119Reachable(page, bannerTel(page));
      await expectInFirstScreen(page, banner(page));
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expectNoHorizontalScroll(page);
    });

    test("시작 화면: 119 진입점·고지·입력창이 첫 화면에 있다", async ({ page }) => {
      await openApp(page);
      await expect119Reachable(page, page.getByTestId("emergency-entry"));
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
    });
  });
}

// ============================================================ 약한 단언 보강(FE-IMPL-06b 할 일 8)
test.describe("단언 보강 360px", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("결과 요약이 첫 화면에 있다(일반·응급)", async ({ page }) => {
    await mockChat(page, "found", "emergency");
    await openApp(page);
    await ask(page);
    await expectInFirstScreen(page, page.getByTestId("result-summary"));
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    await page.getByTestId("new-chat").click();
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await expectInFirstScreen(page, page.getByTestId("result-summary"));
  });

  test("근거 상세 출처 표: 기관·자료·고시 번호·날짜 줄이 받은 값 그대로다", async ({ page }) => {
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await page.getByTestId("evidence-entry").click();
    const table = sheet(page).getByTestId("source-table");
    await expect(table.getByTestId("source-publisher")).toHaveText(["한국의약품안전관리원"]);
    await expect(table.getByTestId("source-dataset")).toHaveText(["병용금기 파일"]);
    // 고시 번호(조항 칸): 이름과 값이 따로, 값은 받은 그대로
    await expect(table.locator('[data-slot="source-extra"] span')).toHaveText(["고시 번호", "20260001"]);
    // 날짜 줄: 한 날짜 = 한 줄, 라벨과 값이 받은 그대로(순서 포함)
    const lines = table.getByTestId("date-lines").locator("li");
    await expect(lines).toHaveCount(2);
    await expect(lines.nth(0).locator("span")).toHaveText(["고시일", "2026-01-15"]);
    await expect(lines.nth(1).locator("span")).toHaveText(["기준일", "2026-07-31"]);
  });

  test("되묻기 화면: 고정 안내와 고지가 접히지 않는 영역에 응답 값 그대로 있다", async ({ page }) => {
    await mockChat(page, "clarify");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("candidate-card")).toBeVisible();
    await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
    await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
    await expect(page.getByTestId("legal-footer")).toContainText("공공데이터 기반 정보 제공이며 진단·처방이 아님");
    await expectInFirstScreen(page, page.getByTestId("legal-footer"));
    await expect119Reachable(page, page.getByTestId("emergency-entry"));
  });
});

// ============================================================ FE-02·FE-01 남은 항목 보강(2026-11-18 goal)
const START_EMERGENCY = "응급 상황이면 지금 바로 119에 전화하세요.";
const EXTERNAL_AI =
  "질문과 입력한 프로필은 답을 만들기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 질문 내용을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
/** 칩의 크기·폰트를 정하는 계산된 값 */
const chipStyle = (target: ReturnType<Page["getByTestId"]>) =>
  target.evaluate((el) => {
    const style = getComputedStyle(el);
    return {
      fontSize: style.fontSize,
      fontFamily: style.fontFamily,
      fontWeight: style.fontWeight,
      lineHeight: style.lineHeight,
      paddingTop: style.paddingTop,
      paddingBottom: style.paddingBottom,
      paddingLeft: style.paddingLeft,
      paddingRight: style.paddingRight,
      minHeight: style.minHeight,
      borderTopWidth: style.borderTopWidth,
      borderTopLeftRadius: style.borderTopLeftRadius,
      color: style.color,
      backgroundColor: style.backgroundColor,
    };
  });

for (const viewport of [
  { width: 360, height: HEIGHT },
  { width: 320, height: HEIGHT },
  { width: 360, height: 640 },
  { width: 320, height: 568 },
  { width: 1280, height: HEIGHT },
]) {
  test.describe(`시작 화면 안내 ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("119 안내 줄과 외부 AI 전송 고지가 질문을 보내기 전 첫 화면에, 입력창 가까이 접히지 않고 보인다(RFP-24-01, FE-01-24 A)", async ({ page }) => {
      await mockChat(page, "found");
      await openApp(page);
      const start119 = dock(page).getByTestId("start-emergency");
      const notice = dock(page).getByTestId("external-ai-notice");
      // 글자는 백엔드 상수에서 생성한 값 그대로다
      await expect(start119).toHaveText(START_EMERGENCY);
      await expect(notice).toHaveText(EXTERNAL_AI);
      await expect119Reachable(page, start119);
      await expectTouchTarget(start119);
      await expectInFirstScreen(page, notice);
      await expectInFirstScreen(page, page.getByTestId("legal-footer"));
      await expectInFirstScreen(page, input(page));
      await expect119Reachable(page, page.getByTestId("emergency-entry")); // 머리줄 119도 그대로 누를 수 있다
      // 입력창 가까이: 고지 아래 끝에서 입력창 위 끝까지가 화면 높이의 1/4 안이고, 입력창보다 위에 있다
      const noticeBox = (await notice.boundingBox())!;
      const inputBox = (await input(page).boundingBox())!;
      expect(noticeBox.y + noticeBox.height).toBeLessThanOrEqual(inputBox.y);
      expect(inputBox.y - (noticeBox.y + noticeBox.height)).toBeLessThanOrEqual(viewport.height / 4);
      // 접히는 틀 밖이고 동의 관문이 아니다(체크·버튼 없음): 고지를 건드리지 않고 바로 질문을 보낼 수 있다
      expect(await notice.evaluate((el) => el.closest("details, [role=dialog], [data-state=closed]") === null)).toBe(true);
      await expect(dock(page).locator("input[type=checkbox]")).toHaveCount(0);
      await expect(notice.locator("button, a")).toHaveCount(0);
      // 119 영역·고지에 마스코트가 없다
      await expect(dock(page).getByTestId("mascot")).toHaveCount(0);
      // 글자 크기가 읽을 수 있는 크기다(12px 이상)
      expect(await notice.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
      expect(await start119.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
      await expectNoHorizontalScroll(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      expect(await requests(page)).toHaveLength(1);
      // 질문을 보낸 뒤에는 시작 화면 안내가 내려가고 응답의 고정 안내·고지가 그 자리에 온다(119는 머리줄 진입점)
      await expect(page.getByTestId("start-emergency")).toHaveCount(0);
      await expect(page.getByTestId("external-ai-notice")).toHaveCount(0);
      await expect(dock(page).getByTestId("fixed-notice")).toBeVisible();
      await expect(tel(page)).toHaveCount(1);
    });
  });
}

test.describe("시작 화면 안내 360px: 새 질문", () => {
  test.use({ viewport: { width: 360, height: HEIGHT } });

  test("'새 질문'으로 시작 화면에 돌아오면 안내 2종이 다시 보인다", async ({ page }) => {
    await mockChat(page, "found");
    await openApp(page);
    await ask(page);
    await expect(page.getByTestId("result-card")).toBeVisible();
    await page.getByRole("button", { name: "메뉴 열기" }).click();
    await page.getByTestId("new-chat").click();
    await expect(page.getByTestId("home")).toBeVisible();
    await expect(page.getByTestId("start-emergency")).toHaveText(START_EMERGENCY);
    await expect(page.getByTestId("external-ai-notice")).toHaveText(EXTERNAL_AI);
  });

  test("응급 답을 받은 뒤에는 119가 배너 하나뿐이다(시작 화면 119 줄이 남지 않는다)", async ({ page }) => {
    await mockChat(page, "emergency");
    await openApp(page);
    await ask(page);
    await expect(banner(page)).toBeVisible();
    await expect(tel(page)).toHaveCount(1);
    await expect(page.getByTestId("start-emergency")).toHaveCount(0);
  });
});

for (const width of [360, 320, 1280]) {
  test.describe(`미식별 결과 아래 동작 칩 ${width}px(PRD-14-03)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("`이름 다시 입력`이 결과 카드 아래에 예시 질문 칩과 같은 크기·폰트로 있고, 누르면 입력창으로 간다. `약 사진 올리기`는 없다", async ({ page }) => {
      await mockChat(page, "unidentified");
      await openApp(page);
      const example = await chipStyle(page.getByTestId("example-chip").first());
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      const actions = page.getByTestId("retry-actions");
      const retry = actions.getByRole("button", { name: "이름 다시 입력" });
      await expect(retry).toBeVisible();
      // 미식별 결과의 진입 글자에는 `· 찾아본 곳`이 붙는다(PRD-14, 성분코드가 아니라 찾아본 곳을 연다)
      await expect(page.getByTestId("evidence-entry")).toHaveText(width >= 1024 ? "근거 상세 열기 · 찾아본 곳" : "근거 상세 보기 · 찾아본 곳");
      await expectTouchTarget(page.getByTestId("evidence-entry"), { widthToo: false });
      // ⑤ 크기·폰트가 시나리오(예시 질문) 칩과 같다
      expect(await chipStyle(page.getByTestId("retry-name"))).toEqual(example);
      // 결과 카드 아래(카드 밖), 줄 전체를 채우지 않는 칩 폭
      const card = (await page.getByTestId("result-card").boundingBox())!;
      const chip = (await retry.boundingBox())!;
      expect(chip.y).toBeGreaterThanOrEqual(card.y + card.height);
      expect(chip.x).toBeGreaterThanOrEqual(card.x - 0.5);
      expect(chip.width).toBeLessThan(card.width * 0.6);
      await expectTouchTarget(retry); // 터치 영역 44px 이상
      // 버튼이 늘어도 넘치지 않게 줄바꿈하는 줄이다(360px 줄바꿈 규칙)
      expect(await actions.evaluate((el) => getComputedStyle(el).flexWrap)).toBe("wrap");
      await expectContained(actions, "button");
      // ⑥ 사진 입력이 없는 구성: `약 사진 올리기`가 DOM에 없다
      await expect(page.getByText("약 사진 올리기")).toHaveCount(0);
      await expect(actions.locator("button")).toHaveCount(1);
      await expect(page.locator("input[type=file]")).toHaveCount(0);
      // 고정 안내·119를 밀어내지 않는다
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([ADVICE_FIXED, FIXED_NOTICE]);
      await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
      await expect119Reachable(page, page.getByTestId("emergency-entry"));
      // 동작 줄에 판정·안전 글자·마스코트가 없다
      await expect(actions).not.toContainText(/삐!|금기|안전/);
      await expect(actions.getByTestId("mascot")).toHaveCount(0);
      await retry.click();
      await expect(page.getByRole("textbox")).toBeFocused();
      expect(await requests(page)).toHaveLength(1); // 누르는 것만으로 다시 보내지 않는다
      await expectNoHorizontalScroll(page);
    });

    test("근거 상세(미식별 박스)에는 동작 칩을 두지 않는다", async ({ page }) => {
      await mockChat(page, "unidentified");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card")).toBeVisible();
      if (width < 1024) await page.getByTestId("evidence-entry").click();
      const detail = page.getByTestId("evidence-detail");
      await expect(detail.getByTestId("lookup-pairs")).toBeVisible();
      // 이유·다음 행동·재검색 줄은 박스 안에서 한 번씩만 보인다(줄과 표에 두 번 나오지 않는다)
      const box = detail.getByTestId("judgment-box").first();
      for (const once of ["식약처·한국의약품안전관리원 자료에서 찾지 못했어요", "봉투나 상자에 적힌 제품명을 그대로 다시 알려 주세요", "표기를 바꿔 한 번 더 찾아봤어요"]) {
        await expect(box.getByText(once, { exact: true })).toHaveCount(1);
      }
      await expect(detail.getByTestId("retry-actions")).toHaveCount(0);
      await expect(detail.getByRole("button", { name: "이름 다시 입력" })).toHaveCount(0);
    });

    test("약을 찾은 결과와 지난 차례에는 동작 칩이 없다", async ({ page }) => {
      await mockChat(page, "unidentified", "found");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("retry-actions")).toHaveCount(1);
      await ask(page);
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      await expect(page.getByTestId("retry-actions")).toHaveCount(0); // 지난 차례의 칩은 내려가고, 약을 찾은 답에는 없다
    });
  });
}

for (const width of [360, 320]) {
  test.describe(`되묻기 ${width}px: 가부 미표시(PRD-01-01, FR-10)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("질문 1개와 후보만 보이고, 후보를 고르기 전·고른 뒤 모두 판정 표지·결과 카드가 없다. 다시 묻기 뒤에야 결과가 온다", async ({ page }) => {
      await mockChat(page, "clarify", "found");
      await openApp(page);
      await ask(page);
      const turn1 = page.locator('[data-turn="turn-1"]');
      await expect(turn1.getByTestId("candidate")).toHaveCount(3);
      // 질문은 한 문장 자리 하나뿐이다
      await expect(turn1.getByTestId("result-summary")).toHaveCount(1);
      await expect(turn1.getByTestId("result-summary")).toHaveText("'가나다'에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요.");
      const noVerdict = async ({ cardShown = true } = {}) => {
        await expect(turn1.getByTestId("result-card")).toHaveCount(0);
        await expect(turn1.getByTestId("product-line")).toHaveCount(0);
        await expect(turn1.getByTestId("status-badge")).toHaveCount(0);
        await expect(turn1.getByTestId("evidence-entry")).toHaveCount(0);
        if (cardShown) await expect(turn1.getByTestId("candidate-card")).not.toContainText(/삐!|금기|안전|먹어도|드셔도/);
        else await expect(turn1.getByTestId("candidate-card")).toHaveCount(0); // 지난 되묻기의 후보는 더 고를 수 없다
        await expect(turn1.getByTestId("result-view")).not.toContainText(/삐!|먹어도 돼|먹어도 됩|안전해요|안전합니다/);
      };
      await noVerdict();
      // 되묻기 화면에도 고정 안내는 접히지 않는 영역에 있다
      await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
      await page.getByTestId("candidate").nth(2).click();
      await expect(page.getByTestId("picked-name")).toHaveText("가나다시럽");
      await noVerdict(); // 고른 것만으로는 판정이 생기지 않는다
      expect(await requests(page)).toHaveLength(1);
      await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
      const turn2 = page.locator('[data-turn="turn-2"]');
      await expect(turn2.getByTestId("result-card")).toBeVisible();
      const sent = await requests(page);
      expect(sent).toHaveLength(2);
      expect(sent[1]).toEqual({ question: QUESTION, context: { age: null, pregnant: null, confirmed_drugs: [{ name: "가나다시럽", item_seq: "200000003" }] } });
      // 판정은 다시 물은 답(둘째 차례)에만 있다
      await expect(turn2.getByTestId("status-badge").first()).toBeVisible();
      await noVerdict({ cardShown: false });
      await expectNoHorizontalScroll(page);
    });

    test("키보드로도 후보를 고르고 다시 물을 수 있다(Enter)", async ({ page }) => {
      await mockChat(page, "clarify", "found");
      await openApp(page);
      await ask(page);
      await page.getByTestId("candidate").first().focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("candidate").first()).toHaveAttribute("aria-pressed", "true");
      expect(await requests(page)).toHaveLength(1);
      await page.getByRole("button", { name: "이 약으로 다시 묻기" }).focus();
      await page.keyboard.press("Enter");
      await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
      expect((await requests(page))[1]).toMatchObject({ context: { confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] } });
    });
  });
}

for (const width of [360, 320]) {
  test.describe(`판정 표지 규칙 ${width}px(PRD-09-01~04)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    for (const name of ["pregnancy", "gradeMismatch", "pregnancyM", "pairAndPregnancy", "gradeDefs"] as const) {
      test(`${name}: 등급은 표지(배지)에만 있고 화면에 '단계' 글자가 없다(결과 카드·근거 상세)`, async ({ page }) => {
        await mockChat(page, name);
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        /** 배지를 뺀 판정 줄의 글자 */
        const outsideBadges = (scope: ReturnType<Page["getByTestId"]>) =>
          scope.getByTestId("product-line").evaluateAll((rows) =>
            rows.map((row) => {
              const copyRow = row.cloneNode(true) as Element;
              for (const badge of copyRow.querySelectorAll('[data-testid="status-badge"]')) badge.remove();
              return copyRow.textContent ?? "";
            }),
          );
        const pregnancyBadges = page.getByTestId("result-card").locator('[data-testid="status-badge"][data-kind="pregnancy"]');
        expect(await pregnancyBadges.count()).toBeGreaterThan(0);
        for (const text of await pregnancyBadges.allTextContents()) expect(text).toMatch(/^삐! 임부금기 (1|2|M)등급/);
        for (const text of await outsideBadges(page.getByTestId("result-card"))) expect(text).not.toMatch(/(1|2|M)등급/);
        await expect(page.getByTestId("app-shell")).not.toContainText("단계");
        await page.getByTestId("evidence-entry").click();
        await expect(sheet(page)).toBeVisible();
        for (const text of await outsideBadges(sheet(page).getByTestId("evidence-detail"))) expect(text).not.toMatch(/(1|2|M)등급/);
        await expect(sheet(page)).not.toContainText("단계");
        await expectNoHorizontalScroll(page);
      });
    }

    test("M등급: 표지는 'M등급', 덧붙임 글은 보조줄에 한 번", async ({ page }) => {
      await mockChat(page, "pregnancyM");
      await openApp(page);
      await ask(page);
      const card = page.getByTestId("result-card");
      await expect(card.getByTestId("status-badge")).toHaveText(["삐! 임부금기 M등급"]);
      await expect(card.getByText("적응증에 따라 등급이 달라요")).toHaveCount(1);
    });
  });
}

for (const width of [360, 320]) {
  test.describe(`등급 정의 블록 보강 ${width}px(PRD-15-03, PRD-09 §7.3)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("미확보(사유 OUT_OF_SCOPE): 두 등급의 상수 문구와 약사 권고만 접힘 밖에 보이고 접힘 블록·조항 줄이 없다", async ({ page }) => {
      await mockChat(page, "gradeDefsOutOfScope");
      await openApp(page);
      await ask(page);
      await page.getByTestId("evidence-entry").click();
      const block = sheet(page).getByTestId("grade-def");
      await expect(block.getByTestId("grade-def-missing").locator(":scope > p")).toHaveText([
        "임부금기 2등급의 뜻(고시 원문)을 아직 준비하지 못했어요.",
        "임부금기 1등급의 뜻(고시 원문)을 아직 준비하지 못했어요.",
      ]);
      await expect(block.getByTestId("pharmacist-advice")).toHaveText("등급의 뜻이 궁금하면 약국·약사에게 물어보세요.");
      await expect(block.getByRole("button")).toHaveCount(0);
      await expect(block.locator('[data-slot="grade-def-source"]')).toHaveCount(0);
      await expect(sheet(page)).not.toContainText("근거 문장을 찾지 못했어요");
      // 등급 불일치 배지 둘은 그대로 잘리지 않고 보인다(ISSUE-011)
      await expect(sheet(page).getByTestId("status-badge")).toHaveText(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
      await expectContained(sheet(page), '[data-testid="status-badge"], [data-testid="line-title"]');
      await expectNoHorizontalScroll(page);
    });

    test("M등급 정의 블록: 제목 '임부금기 M등급이란?'을 펴면 원문과 출처 줄(판·표·쪽)이 받은 글자 그대로 보인다", async ({ page }) => {
      await mockChat(page, "pregnancyMDef");
      await openApp(page);
      await ask(page);
      await expect(page.getByTestId("result-card").getByTestId("status-badge")).toHaveText(["삐! 임부금기 M등급"]);
      await page.getByTestId("evidence-entry").click();
      const block = sheet(page).getByTestId("grade-def");
      const trigger = block.getByRole("button", { name: "임부금기 M등급이란?" });
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await trigger.click();
      await expect(block.locator("blockquote")).toHaveText("(합성 심평원 설명) 상병에 따른 1등급 또는 2등급 여부에 따라 처방·조제 사유 기재");
      await expect(block.locator('[data-slot="grade-def-source"]')).toHaveText("(합성 출처 줄) 건강보험심사평가원 「기능과 역할」 2026년판 표4.3-5, 인쇄 638쪽");
      await expectContained(sheet(page), '[data-slot="grade-def-source"]');
      await expectNoHorizontalScroll(page);
    });
  });
}
