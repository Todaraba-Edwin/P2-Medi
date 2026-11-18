import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { ask, banner, bannerTel, dock, expect119Reachable, expectInFirstScreen, expectNoHorizontalScroll, openApp, sheet } from "../e2e/helpers";

// 가짜 서버 끝단 연결(R5): 실제 HTTP·NDJSON 스트림 경로를 Next rewrites 프록시로 끝까지 본다(설정·실행법은 playwright.fake.config.ts).
// 통신 대역(MSW·페이지 안 fetch 대역)이 없다. 질문 문장은 `backend/scripts/dev_fake_server.py`의 시나리오 표 그대로다(합성 자원, 평가 문항 아님).
// 응답의 글자는 서버가 정한다. 여기서는 화면이 그 응답을 검증(zod)해 그려 냈는지와 흐름(진행 → 결과, 119 먼저, 되묻기 재전송)을 본다.

const AZI = "이지렉트정1.0밀리그램";
const COLD = "타이레놀콜드-에스정";
const T500 = "타이레놀정500밀리그람";
const Q = {
  found: `엄마가 ${AZI}을 드시는데 감기라서 ${COLD}을 사 왔어요. 같이 먹어도 되나요?`,
  notFound: `${T500}이랑 ${AZI} 같이 먹어도 되나요?`,
  clarify: `타이레놀이랑 ${AZI} 같이 먹어도 되나요?`,
  typo: `이지랙트정1.0밀리그램이랑 ${COLD} 같이 먹어도 되나요?`,
  emergency: `숨쉬기 힘들어요. ${AZI}이랑 ${COLD}을 같이 먹었어요`,
  refuse: `${AZI} 처방해 줘`,
  serverError: `서버오류 시험: ${AZI}이랑 ${COLD} 같이 먹어도 돼요?`,
  slow: `느린응답 시험: ${AZI}이랑 ${COLD} 같이 먹어도 돼요?`,
};
const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";

interface Seen {
  status: number;
  contentType: string;
  body: { question: string; context?: { confirmed_drugs?: { name: string; item_seq: string | null }[] } };
}

/** `/api/chat` 요청·응답을 기록한다(가로채지 않는다). 실제 네트워크로 나갔는지 확인하는 용도 */
function watchChat(page: Page): Seen[] {
  const seen: Seen[] = [];
  page.on("response", (response) => {
    const request = response.request();
    if (request.method() !== "POST" || !new URL(request.url()).pathname.endsWith("/api/chat")) return;
    seen.push({ status: response.status(), contentType: response.headers()["content-type"] ?? "", body: request.postDataJSON() });
  });
  return seen;
}

async function open(page: Page) {
  await openApp(page);
  // 서비스 워커(MSW)가 없다: 요청이 프록시를 거쳐 가짜 서버로 간다
  expect(await page.evaluate(() => navigator.serviceWorker?.controller ?? null)).toBeNull();
}

const lines = (page: Page, turn = 1) => page.locator(`[data-turn="turn-${turn}"]`).getByTestId("product-line");

test("프록시: /api/health가 가짜 서버의 응답을 돌려준다", async ({ request }) => {
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ok" });
});

test("정상(병용금기 1건): 진행 → 결과 카드·배지·확인하지 못한 줄·고정 안내, 근거 상세에 출처 표", async ({ page }) => {
  const seen = watchChat(page);
  await open(page);
  await ask(page, Q.found);
  await expect(page.getByTestId("result-card")).toBeVisible();
  expect(seen).toHaveLength(1);
  expect(seen[0].status).toBe(200);
  expect(seen[0].contentType).toContain("application/x-ndjson");
  expect(seen[0].body.question).toBe(Q.found);
  await expect(page.locator('[data-turn="turn-1"]')).toHaveAttribute("data-status", "done");
  // 판정 줄: 쌍 줄(병용금기 배지) + 식별된 약 두 줄
  await expect(lines(page)).toHaveCount(3);
  await expect(lines(page).nth(0)).toHaveAttribute("data-bucket", "found");
  await expect(lines(page).nth(0).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
  await expect(lines(page).nth(0).getByTestId("line-title")).toHaveText(`${AZI} · ${COLD}`);
  await expect(lines(page).nth(1)).toHaveAttribute("data-bucket", "identified");
  await expect(lines(page).nth(2)).toHaveAttribute("data-bucket", "identified");
  await expect(page.getByTestId("result-summary")).toContainText("병용금기");
  // 실시간 확인을 못 했다는 배너와 임신 여부를 몰라 확인하지 못한 줄(서버 값 그대로)
  await expect(page.getByTestId("result-notice")).toHaveText("실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.");
  await expect(page.getByTestId("not-checked-lines").locator("li")).toHaveText(["임신 여부를 알 수 없어 임부금기는 확인하지 못했어요."]);
  // 고정 안내는 접히지 않는 영역에 서버가 준 순서대로(권고 → 고정)
  await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText(["확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.", FIXED_NOTICE]);
  await expect(page.getByTestId("legal-footer")).toContainText("공공데이터 기반 정보 제공이며 진단·처방이 아님");
  await expect(page.getByTestId("name-corrections")).toHaveCount(0);
  await expect(banner(page)).toHaveCount(0);
  await expect(page.getByTestId("mascot")).toHaveCount(0); // 결과가 오면 진행 표시 마스코트가 사라진다
  // 근거 상세: 판정 박스와 출처 표(기관·자료·날짜 줄)
  await page.getByTestId("evidence-entry").click();
  await expect(sheet(page).getByTestId("judgment-box").first()).toBeVisible();
  const table = sheet(page).getByTestId("source-table");
  await expect(table).toBeVisible();
  expect(await table.getByTestId("source-row").count()).toBeGreaterThan(0);
  expect(await table.getByTestId("date-lines").locator("li").count()).toBeGreaterThan(0);
  await expect(sheet(page)).not.toContainText("단계");
  await expectNoHorizontalScroll(page);
});

test("금기 목록에 없음: 배지 없이 '안전하다는 뜻이 아님' 줄이 접히지 않고 보인다", async ({ page }) => {
  await open(page);
  await ask(page, Q.notFound);
  await expect(page.getByTestId("result-card")).toBeVisible();
  await expect(page.getByTestId("status-badge")).toHaveCount(0);
  const notListed = page.locator('[data-testid="product-line"][data-bucket="not_listed"]');
  expect(await notListed.count()).toBeGreaterThan(0);
  await expect(notListed.first()).toContainText("안전하다는 뜻이 아님");
  expect(await notListed.first().evaluate((el) => el.closest("details, [data-state=closed]") === null)).toBe(true);
  await expect(dock(page).getByTestId("fixed-notice")).toContainText(FIXED_NOTICE);
  await expectNoHorizontalScroll(page);
});

test("되묻기 → 후보 선택 → 다시 묻기: 고른 약(item_seq)이 실려 나가고 서버가 결과로 답한다", async ({ page }) => {
  const seen = watchChat(page);
  await open(page);
  await ask(page, Q.clarify);
  const candidates = page.getByTestId("candidate");
  await expect(candidates).toHaveCount(2);
  await expect(candidates.locator("b")).toHaveText([COLD, T500]);
  await expect(page.getByTestId("result-summary")).toHaveText("'타이레놀'에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요.");
  // 가부 미표시: 고르기 전에는 판정이 없다
  await expect(page.getByTestId("result-card")).toHaveCount(0);
  await expect(page.getByTestId("status-badge")).toHaveCount(0);
  await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
  await candidates.nth(0).click();
  await expect(page.getByTestId("picked-name")).toHaveText(COLD);
  expect(seen).toHaveLength(1); // 고른 것만으로는 보내지 않는다
  await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
  await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toBeVisible();
  expect(seen).toHaveLength(2);
  expect(seen[1].body.question).toBe(Q.clarify);
  expect(seen[1].body.context?.confirmed_drugs).toEqual([{ name: COLD, item_seq: "202106954" }]);
  // 콜드-에스정으로 확정 → 병용금기 1건
  await expect(lines(page, 2).nth(0).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
  await expect(page.getByTestId("candidate")).toHaveCount(0);
});

test("오탈자(`이지랙트정`): 서버 설정대로 그린다 — 보정이 꺼져 있으면 되묻기(후보 1개), 켜져 있으면 보정 고지 + 결과", async ({ page }, testInfo) => {
  // 서비스 오탈자 보정은 BE-06-35 A로 기본 꺼짐이라 지금은 되묻기가 온다(가짜 서버도 서비스 배선을 쓴다).
  // 백엔드가 기본을 켜면 같은 질문이 `name_corrections` 1건 + 병용금기 1건으로 온다. 두 경우 모두 화면이 받은 값을 그대로 그리는지 본다.
  await open(page);
  await ask(page, Q.typo);
  await expect(page.locator('[data-turn="turn-1"]')).toHaveAttribute("data-status", "done");
  const corrections = page.getByTestId("name-corrections");
  if ((await corrections.count()) > 0) {
    testInfo.annotations.push({ type: "typo", description: "보정 켜짐: name_corrections 고지 + 결과" });
    await expect(corrections.locator("li")).toHaveCount(1);
    await expect(corrections).toContainText("이지랙트정1.0밀리그램");
    await expect(corrections).toContainText(AZI);
    await expect(page.getByTestId("result-card")).toBeVisible();
    // 고지는 요약보다 먼저
    const [noticeY, summaryY] = await Promise.all([corrections.boundingBox(), page.getByTestId("result-summary").boundingBox()]).then((boxes) => boxes.map((box) => box!.y));
    expect(noticeY).toBeLessThan(summaryY);
  } else {
    testInfo.annotations.push({ type: "typo", description: "보정 꺼짐(BE-06-35 A): 되묻기 후보 1개" });
    await expect(page.getByTestId("candidate").locator("b")).toHaveText([AZI]);
    await expect(page.getByTestId("result-summary")).toContainText("비슷한 약이 있어요");
    await expect(page.getByTestId("result-card")).toHaveCount(0);
    await expect(page.getByTestId("status-badge")).toHaveCount(0);
    // 후보를 골라 다시 물으면 결과가 온다
    await page.getByTestId("candidate").first().click();
    await page.getByRole("button", { name: "이 약으로 다시 묻기" }).click();
    await expect(lines(page, 2).nth(0).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
  }
});

test("응급: 119 배너가 맨 위에 뜨고 전화 링크가 눌리며, 금기 결과가 그 아래 이어진다", async ({ page }) => {
  await open(page);
  await ask(page, Q.emergency);
  await expect(banner(page)).toBeVisible();
  await expect(banner(page)).toContainText("응급 상황일 수 있어요. 지금 바로 119에 전화하세요.");
  await expect(page.getByTestId("result-card")).toBeVisible(); // 응급이어도 금기 조회를 막지 않는다
  await expect119Reachable(page, bannerTel(page));
  await expectInFirstScreen(page, banner(page));
  const [bannerBox, cardBox] = [await banner(page).boundingBox(), await page.getByTestId("result-card").boundingBox()];
  expect(bannerBox!.y).toBeLessThan(cardBox!.y);
  await expect(lines(page).nth(0).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
  await expect(page.locator('a[href="tel:119"]')).toHaveCount(1); // 119는 배너 하나뿐
  await expect(page.getByTestId("mascot")).toHaveCount(0);
  await expectInFirstScreen(page, dock(page).getByTestId("fixed-notice"));
});

test("거절(처방 요청): 거절 문구와 고정 안내만 보이고 결과 카드·근거 상세 진입이 없다", async ({ page }) => {
  await open(page);
  await ask(page, Q.refuse);
  await expect(page.getByTestId("result-view")).toHaveAttribute("data-end-reason", "REFUSE");
  await expect(page.getByTestId("result-summary")).toHaveText("처방은 할 수 없어요. 처방은 의사가 해요. 가진 약의 금기 여부는 공공 자료로 확인해 드려요.");
  await expect(page.getByTestId("result-card")).toHaveCount(0);
  await expect(page.getByTestId("evidence-entry")).toHaveCount(0);
  await expect(page.getByTestId("status-badge")).toHaveCount(0);
  await expect(dock(page).getByTestId("fixed-notice").locator("p")).toHaveText([FIXED_NOTICE]);
});

test("서버 오류 이벤트(HTTP 200 안의 error): 받은 오류 문구와 다시 시도, 고정 안내가 보이고 스스로 다시 보내지 않는다", async ({ page }) => {
  const seen = watchChat(page);
  await open(page);
  await ask(page, Q.serverError);
  const error = page.getByTestId("error-state");
  await expect(error).toBeVisible();
  expect(seen[0].status).toBe(200);
  await expect(error.getByRole("button", { name: "다시 시도" })).toBeVisible();
  await expect(error).toContainText(FIXED_NOTICE);
  await expect(page.getByTestId("result-card")).toHaveCount(0);
  await page.waitForTimeout(1500);
  expect(seen).toHaveLength(1);
});

test("느린 응답: 첫 이벤트 전의 하트비트(빈 줄)를 건너뛰고 기다렸다가 결과를 그린다", async ({ page }) => {
  await open(page);
  await ask(page, Q.slow);
  const progress = page.getByRole("status", { name: "진행 상태" });
  await expect(progress).toBeVisible(); // 기다리는 동안 진행 표시
  const started = Date.now();
  await page.waitForTimeout(8000);
  await expect(page.getByTestId("error-state")).toHaveCount(0); // 침묵을 오류로 보지 않는다
  await expect(progress).toBeVisible();
  await expect(page.getByTestId("result-card")).toBeVisible({ timeout: 40_000 });
  expect(Date.now() - started).toBeGreaterThan(14_000); // 서버가 실제로 하트비트 간격(15초)보다 오래 침묵했다(설정 17초)
  await expect(lines(page).nth(0).getByTestId("status-badge")).toHaveText(["삐! 병용금기"]);
});
