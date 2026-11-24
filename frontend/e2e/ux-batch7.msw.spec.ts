import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { FIXED_NOTICE as FIXED_NOTICE_TEXT, HEIGHT, ask, expectNoHorizontalScroll, mockChat, openApp, pickTarget, release, waitHeld } from "./helpers";

// FE-17 UI/UX 다듬기 7차(2026-11-24 "모아서 진행")를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-24 수정: 병아리 ↔ 단계 목록 간격 +12px(24px), 진행 중 글자 쉬머는 더 밝은 띠가 왼쪽 → 오른쪽으로 계속 지나간다(움직임 줄이기에서 멈춤)
// - U-18 추가 지시 2: 1280(근거 상세 + 펼친 사이드바) → 1231로 줄이면 사이드바가 레일로 접혀 dim이 없다. 넓혀도 레일. 직접 펼친 오버레이는 그대로
// - U-21 추가: 질문이 오간 대화에서 다른 대상을 고르면 새 대화, 같은 대상은 그대로, 스트리밍 중이면 새 대화(응답은 이전 대화에 남음, U-29로 변경)
// - U-22 추가: 로그인 상태 새로고침(느린 CPU·네트워크)에서 `게스트로 시작`·`로그인/가입`이 한 프레임도 그려지지 않는다
// - U-25: 근거 상세 사유 원문이 판정 종류 박스 → (용량주의) 사유 원문 → 약 이름 - 제형유형 N건 / (병용금기) 약 이름 쌍 → 고정 문구, 줄 글자 13px/19px
// - U-26-1: 입력창 위 고정 안내 제거, 같은 고정 안내 줄은 가장 최근 답 아래 한 번(결과 화면에 반드시 한 번 남음)
// - U-26-3: 결과 카드 머리 `기준일 자료` 표지 제거(기준일은 근거 상세에 그대로)
// - U-26-5·6: 근거 상세 판정 구역에서 같은 약 박스 묶음, 보이는 것이 같은 줄은 한 박스(같은 내용 N건)
// 캡처: `FE_UX_BATCH7_SHOT_DIR`을 주면 `ux-batch7-{width}-{scheme}-{장면}.png`를 남긴다(쉬머는 정지 프레임)
const SHOT_DIR = process.env.FE_UX_BATCH7_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  if (target) await target.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
  else await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
/** 쉬머를 띠가 글자 가운데쯤 지나는 순간에 멈춘다(정지 프레임 캡처용). 스피너도 멈춘다 */
const freezeShimmer = (page: Page) =>
  page.addStyleTag({ content: ".progress-shimmer{animation-play-state:paused!important;animation-delay:-0.8s!important}.animate-spin{animation-play-state:paused!important}" });
const box = async (locator: Locator) => (await locator.boundingBox())!;
const progress = (page: Page) => page.getByRole("status", { name: "진행 상태" });
const steps = (page: Page) => progress(page).getByRole("listitem");
const panel = (page: Page) => page.getByTestId("panel-column");
/** `openApp`가 주소 끝에 `/`를 붙이므로 마지막 값(`ux_batch7=1`)이 그것을 받는다(앞의 값이 망가지지 않게) */
const LOGGED_IN = "?mock_session=onboarded&ux_batch7=1";
const LOGGED_IN_GUEST_TARGET = "?mock_session=onboarded&mock_default_target=guest&ux_batch7=1";

async function holdMidProgress(page: Page) {
  await mockChat(page, { name: "typoCorrected", holdBefore: "answer" });
  await openApp(page);
  await ask(page);
  await waitHeld(page);
  await expect.poll(() => steps(page).evaluateAll((items) => items.map((li) => li.getAttribute("data-state")))).toEqual(["done", "now", "todo"]);
}

/** 진행 중 글자의 쉬머 애니메이션을 시각 `ms`로 옮겼을 때 배경 위치(x, %) */
const shimmerPositionAt = (target: Locator, ms: number) =>
  target.evaluate((el, at) => {
    const animation = el.getAnimations().find((a) => (a as CSSAnimation).animationName === "progress-shimmer")!;
    animation.pause();
    animation.currentTime = at;
    return parseFloat(getComputedStyle(el).backgroundPositionX);
  }, ms);

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 7 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch7-${width}-${scheme}`;
      const mobile = width < 1024;

      test("U-24 수정: 병아리와 단계 목록 사이가 24px(기존 12 + 12)이고, 진행 중 글자 위로 더 밝은 띠가 왼쪽 → 오른쪽으로 계속 지나간다", async ({ page }) => {
        await holdMidProgress(page);
        const mascot = await box(progress(page).getByTestId("mascot"));
        const list = await box(page.getByTestId("progress-step-list"));
        expect(Math.round(list.x - (mascot.x + mascot.width))).toBe(24);
        const now = steps(page).nth(1).getByTestId("progress-step-text");
        const style = await now.evaluate((el) => {
          const s = getComputedStyle(el);
          return { name: s.animationName, iteration: s.animationIterationCount, duration: s.animationDuration, base: s.getPropertyValue("--shimmer-base").trim(), hi: s.getPropertyValue("--shimmer-hi").trim() };
        });
        expect(style).toMatchObject({ name: "progress-shimmer", iteration: "infinite", duration: "1.5s" });
        // 띠 색이 바탕 글자색보다 밝다(라이트: 검정 위 옅은 갈색, 다크: mute 위 ink)
        const luminance = (color: string) =>
          page.evaluate((c) => {
            const probe = document.createElement("i");
            probe.style.color = c;
            document.body.append(probe);
            const [r, g, b] = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number);
            probe.remove();
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
          }, color);
        expect(await luminance(style.hi)).toBeGreaterThan((await luminance(style.base)) + 40);
        // 방향: 배경 위치가 100% → 0%로 줄어든다(배경이 글자보다 넓으므로 띠는 왼쪽 밖에서 오른쪽 밖으로 간다)
        const start = await shimmerPositionAt(now, 0);
        const mid = await shimmerPositionAt(now, 750);
        const end = await shimmerPositionAt(now, 1490);
        expect(start).toBeCloseTo(100, 0);
        expect(mid).toBeLessThan(start);
        expect(end).toBeLessThan(mid);
        await freezeShimmer(page);
        await shot(page, `${base}-progress`);
        await shot(page, `${base}-progress-close`, progress(page));
      });

      test("U-24 수정: 움직임 줄이기에서는 쉬머가 멈추고 글자는 본문색 그대로다(간격 24px 유지)", async ({ page }) => {
        await page.emulateMedia({ reducedMotion: "reduce" });
        await holdMidProgress(page);
        const now = steps(page).nth(1).getByTestId("progress-step-text");
        expect(await now.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
        expect(await now.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe("none");
        const mascot = await box(progress(page).getByTestId("mascot"));
        const list = await box(page.getByTestId("progress-step-list"));
        expect(Math.round(list.x - (mascot.x + mascot.width))).toBe(24);
      });

      test("U-25: 근거 상세 사유 원문은 판정 종류 박스(용량주의 파일·병용금기 파일) → 사유 원문 → 약 이름 - 제형유형 N건 / 약 이름 쌍 → 고정 문구이고, 줄 글자가 13px/19px로 같다", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "doseCombo");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-view")).toBeVisible();
        if (mobile) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        await expect(detail).toBeVisible();
        const boxes = detail.getByTestId("reason-box");
        await expect(boxes).toHaveCount(2);
        await expect(boxes.getByTestId("source-tag")).toHaveText(["공식 파일 · 용량주의 파일", "공식 파일 · 병용금기 파일"]);
        const dose = boxes.nth(0).getByTestId("reason-group");
        await expect(dose.getByTestId("reason-text")).toHaveText(["가나성분으로 4,000mg", "가나성분으로써 4000mg", "라마성분 3,200mg"]);
        await expect(dose.getByTestId("reason-drug")).toHaveText(["가나다정 - 제형유형 6건", "가나다정 - 제형유형 1건", "라마바캡슐 - 제형유형 23건"]);
        await expect(boxes.nth(1).getByTestId("reason-drug")).toHaveText("가나다정 · 라마바캡슐");
        await expect(boxes.nth(1).getByTestId("reason-not-listed")).toHaveText("금기 목록에 없음(안전하다는 뜻이 아님)");
        // 근거 ID 31개 보존
        const ids = (await boxes.evaluateAll((els) => els.flatMap((el) => (el.getAttribute("data-evidence-ids") ?? "").split(" ")))).filter(Boolean);
        expect(new Set(ids).size).toBe(31);
        // 스타일 통일: 사유 원문·약 이름·고정 문구 줄이 모두 13px / 19px
        const metrics = await detail.locator('[data-testid="reason-box"] p').evaluateAll((els) => els.map((el) => `${getComputedStyle(el).fontSize}/${getComputedStyle(el).lineHeight}`));
        expect(new Set(metrics)).toEqual(new Set(["13px/19px"]));
        // 박스 안 글자가 박스 밖으로 나가지 않고 가로 스크롤이 없다
        for (const reasonBox of await boxes.all()) {
          const outer = await box(reasonBox);
          for (const child of await reasonBox.locator("p, [data-testid='source-tag']").all()) {
            const inner = await box(child);
            expect(inner.x).toBeGreaterThanOrEqual(outer.x - 0.5);
            expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + 0.5);
          }
        }
        await expectNoHorizontalScroll(page);
        await detail.locator('[data-section="reason"]').scrollIntoViewIfNeeded();
        await shot(page, `${base}-u25-reason`);
        await shot(page, `${base}-u25-reason-close`, detail.locator('[data-section="reason"]'));
      });

      test("U-21 추가: 질문이 오간 대화에서 다른 대상을 고르면 새 대화가 열리고, 같은 대상은 대화가 그대로다", async ({ page }) => {
        test.setTimeout(90_000);
        await mockChat(page, "found");
        await openApp(page, LOGGED_IN);
        await expect(page.getByTestId("target-chip")).toBeVisible();
        await pickTarget(page, "첫째");
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        await pickTarget(page, "첫째"); // 같은 대상
        await expect(page.getByTestId("result-card")).toBeVisible();
        await expect(page.getByTestId("home")).toHaveCount(0);
        await shot(page, `${base}-u21-before`);
        await pickTarget(page, "나"); // 다른 대상 → 새 대화
        await expect(page.getByTestId("home")).toBeVisible();
        await expect(page.getByTestId("result-card")).toHaveCount(0);
        await expect(panel(page)).toHaveCount(0);
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 나");
        await expect(page.getByTestId("start-target-heading")).toHaveText("나 프로필로 확인해요");
        await shot(page, `${base}-u21-new-chat`);
      });

      // FE-17 U-29(2026-11-24)로 기대를 바꿨다: 예전에는 진행 응답을 끊었지만 이제 이전 대화는 이번 탭의 목록에 남고 응답은 그 대화에 계속 쌓인다.
      // "새 대화가 열리고 지금 화면에 이전 대화(진행 표시·결과)가 이어지지 않는다"는 의도는 그대로 본다
      test("U-21 추가: 답을 받는 중(스트리밍)에 다른 대상을 고르면 새 대화를 열고, 진행 응답은 이전 대화에 남는다(U-29)", async ({ page }) => {
        await mockChat(page, { name: "found", holdBefore: "answer" });
        await openApp(page, LOGGED_IN);
        await expect(page.getByTestId("target-chip")).toBeVisible();
        await ask(page);
        await waitHeld(page);
        await expect(progress(page)).toBeVisible();
        await pickTarget(page, "첫째");
        await expect(page.getByTestId("home")).toBeVisible();
        await expect(progress(page)).toHaveCount(0);
        await expect(page.getByTestId("result-card")).toHaveCount(0);
        await release(page);
        if (width < 1024) await page.getByTestId("menu-button").click();
        await page.getByTestId("chat-session").click();
        await expect(page.getByTestId("result-card")).toBeVisible();
      });

      test("U-26-1: 입력창 위 고정 안내가 없고, `금기 목록에 없다는 것이 안전하다는 뜻이 아니에요…`는 결과 화면(답 아래)에 정확히 한 번 남는다. 두 번째 답 뒤에도 한 번이다", async ({ page }) => {
        await mockChat(page, "found", "judgmentDup");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-card")).toHaveCount(1);
        const main = page.getByTestId("main");
        await expect(page.getByTestId("dock").getByTestId("fixed-notice")).toHaveCount(0);
        await expect(main.getByText(FIXED_NOTICE_TEXT, { exact: true })).toHaveCount(1);
        await ask(page, "합성 둘째 질문");
        await expect(page.getByTestId("result-card")).toHaveCount(2);
        await expect(page.getByTestId("dock").getByTestId("fixed-notice")).toHaveCount(0);
        await expect(main.getByText(FIXED_NOTICE_TEXT, { exact: true })).toHaveCount(1);
        const last = page.locator('[data-turn="turn-2"]').getByTestId("fixed-notice");
        await expect(last.locator("p")).toHaveText(["확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.", FIXED_NOTICE_TEXT]);
        await expect(page.locator('[data-turn="turn-1"]').getByTestId("fixed-notice")).toHaveCount(0);
        // 판정 줄·쌍 칸의 "안전하다는 뜻이 아니에요" 계열 문구는 그대로다(받은 글자)
        await expect(page.locator('[data-turn="turn-2"]').getByTestId("result-card")).toContainText("금기 목록에 없음(안전하다는 뜻이 아님)");
        await last.evaluate((el) => el.scrollIntoView({ block: "nearest" }));
        await expect(last).toBeVisible();
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-u26-1-notice`);
      });

      test("U-26-3: 실시간 확인 실패 결과의 카드 머리에 `기준일 자료` 표지가 없고, 기준일 정보는 근거 상세 안내·출처 표에 그대로 있다", async ({ page }) => {
        await mockChat(page, "apiFail");
        await openApp(page);
        await ask(page);
        const card = page.getByTestId("result-card");
        await expect(card).toBeVisible();
        await expect(card.getByTestId("basis-file-tag")).toHaveCount(0);
        await expect(card.locator("header")).toHaveText("금기 확인 결과");
        if (mobile) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        await expect(detail.getByTestId("evidence-api-fail-notice")).toHaveText("실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.");
        await expect(detail.locator('[data-section="sources"]')).toContainText("기준일");
        await shot(page, `${base}-u26-3-card`, card);
      });

      test("U-26-5·6: 근거 상세 판정 구역에서 같은 약의 박스가 한 묶음으로 붙고, 같은 내용(약을 찾지 못한 같은 줄 2개)은 한 박스 `같은 내용 2건`이다", async ({ page }) => {
        await mockChat(page, "judgmentDup");
        await openApp(page);
        await ask(page);
        await expect(page.getByTestId("result-card")).toBeVisible();
        if (mobile) await page.getByTestId("evidence-entry").click();
        const detail = page.getByTestId("evidence-detail");
        const groups = detail.getByTestId("judgment-drug-group");
        await expect(groups).toHaveCount(4);
        expect(await groups.evaluateAll((els) => els.map((el) => el.getAttribute("data-count")))).toEqual(["2", "1", "1", "1"]);
        await expect(groups.nth(0).getByTestId("line-title")).toHaveText(["가나다정", "가나다정"]);
        // 묶음 안 박스는 테두리를 이어 한 카드처럼(사이 간격 없음)
        const [top, bottom] = await groups.nth(0).getByTestId("judgment-box").all();
        const topBox = (await top.boundingBox())!;
        const bottomBox = (await bottom.boundingBox())!;
        expect(Math.abs(bottomBox.y - (topBox.y + topBox.height))).toBeLessThanOrEqual(1.5);
        const dup = groups.nth(2).getByTestId("judgment-box");
        await expect(dup).toHaveCount(1);
        await expect(dup.getByTestId("judgment-same-count")).toHaveText("같은 내용 2건");
        await expect(detail.getByTestId("judgment-box")).toHaveCount(5);
        await expectNoHorizontalScroll(page);
        await detail.locator('[data-section="judgment"]').scrollIntoViewIfNeeded();
        await shot(page, `${base}-u26-5-6-judgment`, detail.locator('[data-section="judgment"]'));
      });

      if (width === 1280) {
        test("U-18 추가 2: 근거 상세 + 펼친 사이드바인 1280에서 1231로 줄이면 사이드바가 레일로 접혀 dim이 없고, 1280으로 넓혀도 레일이다", async ({ page }) => {
          await mockChat(page, "found");
          await openApp(page);
          await ask(page);
          await expect(panel(page)).toBeVisible();
          await expect(page.locator('[data-testid="sidebar"][data-presentation="push"]')).toBeVisible();
          await page.setViewportSize({ width: 1232, height: HEIGHT });
          await expect(page.locator('[data-testid="sidebar"][data-presentation="push"]')).toBeVisible(); // 1232는 밀 수 있다
          await page.setViewportSize({ width: 1231, height: HEIGHT });
          await expect(page.getByTestId("sidebar-rail")).toBeVisible();
          await expect(page.getByTestId("sidebar-scrim")).toHaveCount(0);
          await expect(page.getByTestId("main")).not.toHaveAttribute("inert", /.*/);
          await expect(panel(page)).toBeVisible();
          await expectNoHorizontalScroll(page);
          await shot(page, `${base}-u18-1231-rail`);
          await page.setViewportSize({ width: 1280, height: HEIGHT });
          await expect(page.getByTestId("sidebar-rail")).toBeVisible();
          await expect(page.getByTestId("sidebar")).toHaveCount(0);
        });

        test("U-18 추가 2: 1231에서 사용자가 직접 펼친 사이드바는 지금처럼 오버레이(dim)로 열린다", async ({ page }) => {
          await page.setViewportSize({ width: 1231, height: HEIGHT });
          await mockChat(page, "found");
          await openApp(page);
          await ask(page);
          await expect(panel(page)).toBeVisible();
          await expect(page.getByTestId("sidebar-rail")).toBeVisible(); // 열리는 순간 접힘(§11 ⑦)
          await page.getByTestId("sidebar-toggle").click();
          await expect(page.getByTestId("sidebar-scrim")).toBeVisible();
          await expect(page.locator('[data-testid="sidebar"][data-presentation="overlay"]')).toBeVisible();
        });
      }
    });
  }
}

test.describe("FE-17 UX 묶음 7 · U-22 추가 로그인 새로고침 깜박임", () => {
  test.use({ viewport: { width: 1280, height: HEIGHT } });

  /** 페이지가 뜨는 동안 DOM에 한 번이라도 나타난 것을 적는다(MutationObserver, 문서가 만들어지기 전에 건다) */
  async function watchFlicker(page: Page) {
    await page.addInitScript(() => {
      const seen = { entry: false, guestStart: false, login: false, pending: false };
      (window as unknown as { __u22: typeof seen }).__u22 = seen;
      const check = () => {
        if (document.querySelector('[data-testid="entry-choice"]')) seen.entry = true;
        if (document.querySelector('[data-testid="guest-start"]')) seen.guestStart = true;
        if (document.querySelector('[data-testid="login-entry"]')) seen.login = true;
        if (document.querySelector('[data-testid="start-account-pending"]')) seen.pending = true;
      };
      new MutationObserver(check).observe(document, { childList: true, subtree: true, attributes: true });
    });
  }
  const seen = (page: Page) => page.evaluate(() => (window as unknown as { __u22: Record<string, boolean> }).__u22);

  /** 느린 CPU(6배)·느린 네트워크(Slow 3G 근사: 지연 400ms, 50KB/s) */
  async function slowDown(page: Page) {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 6 });
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 400, downloadThroughput: 50 * 1024, uploadThroughput: 50 * 1024 });
  }

  test("로그인(게스트로 이용 상태) 새로고침을 여러 번 해도 `게스트로 시작`·`로그인/가입`이 한 번도 그려지지 않고, 확정 전에는 빈 자리만 있다", async ({ page }) => {
    test.setTimeout(240_000);
    await watchFlicker(page);
    await openApp(page, LOGGED_IN_GUEST_TARGET);
    await expect(page.getByTestId("start-target")).toHaveAttribute("data-target", "guest");
    await slowDown(page);
    for (let i = 0; i < 3; i += 1) {
      await page.reload();
      await expect(page.getByTestId("start-target")).toHaveAttribute("data-target", "guest", { timeout: 60_000 });
      await expect(page.getByTestId("start-target-lead")).toHaveText("저장한 프로필 값 없이 질문해요.");
      const record = await seen(page);
      expect(record).toMatchObject({ entry: false, guestStart: false, login: false });
      expect(record.pending).toBe(true); // 확정 전 빈 자리가 실제로 있었다(시험이 그 구간을 보았다)
      await expect(page.getByTestId("start-account-pending")).toHaveCount(0);
    }
    await shot(page, "ux-batch7-1280-light-u22-member-reload");
  });

  test("비로그인(세션 없음)은 지금처럼 진입 선택이 보인다(대조군: 감시 스크립트가 진입 선택을 잡아낸다)", async ({ page }) => {
    await watchFlicker(page);
    await openApp(page);
    await expect(page.getByTestId("entry-choice")).toBeVisible();
    expect((await seen(page)).entry).toBe(true);
    await expect(page.getByTestId("start-account-pending")).toHaveCount(0);
  });
});
