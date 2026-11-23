import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page, Request } from "@playwright/test";
import { HEIGHT, MIN_TOUCH, completeRequired, expectNoHorizontalScroll, expectTouchTarget, input, notice, openAccountMenu, openApp } from "./helpers";

// FE-17 UI/UX 다듬기 4차(U-10~U-16)를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-10: 입력창 아래 줄 프로필 칩의 보이는 크기·글자 크기·둥근 정도가 `일반인|임산부` 토글 틀과 같다(누르는 영역 44px 유지)
// - U-11: 시작 화면 기본 대상 안내가 `<p>` 한 단락(통합 고지와 같은 글자 디자인), `게스트로 이용`은 문장 끝 밑줄 링크 모양
// - U-12: 계정 메뉴 `누가 먹나요`가 `화면 모드`와 같은 독립 섹션(들여쓴 하위 묶음 없음, 구분선 구획)
// - U-13: 계정 버튼은 마우스를 올려도 열리지 않고 클릭·탭·키보드로만 열린다(입력창 칩의 호버 열림은 그대로)
// - U-14: 프로필 폼에서 색(과 다른 버튼)을 눌러도 모달 상자·본문의 높이와 스크롤 위치가 변하지 않는다(ISSUE-031 회귀)
// - U-15: 프로필 색이 폼의 첫 번째 입력이고, 고르면 머리 병아리 배경색이 바로 바뀐다
// - U-16: 프로필 관리 화면의 `동의 내용 보기`·`로그아웃`·`탈퇴`가 모달 바닥에 고정되고 목록 영역만 스크롤한다
// - U-17: 제품을 골라 다시 물으면 지난 고른 줄 요약의 `바꾸기`가 숨고, `고른 약: …로 다시 확인` 말풍선 없이 진행 표시가 다음 항목으로 나온다
// - U-18: 창 폭이 사이드바 기준선(1024px)을 가로지를 때만 좁아지면 닫히고 넓어지면 펼쳐진다(같은 구간 안의 수동 토글은 그대로)
// 캡처: `FE_UX_BATCH4_SHOT_DIR`을 주면 `ux-batch4-{width}-{scheme}.png`(시작 화면·입력창)와 `ux-batch4-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH4_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
const box = async (locator: Locator) => (await locator.boundingBox())!;
const style = (locator: Locator, ...names: string[]) =>
  locator.evaluate((el, keys) => {
    const computed = getComputedStyle(el);
    return Object.fromEntries(keys.map((key) => [key, computed.getPropertyValue(key)]));
  }, names);
const isDefaultTargetPut = (request: Request) => request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/api/me/default-target");
const modal = (page: Page) => page.getByTestId("account-modal");

/** 모달 상자·본문·코너 버튼의 위치와 스크롤 값(U-14: 눌러도 바뀌지 않아야 한다) */
async function modalGeometry(page: Page) {
  return page.evaluate(() => {
    const content = document.querySelector<HTMLElement>('[data-testid="account-modal"]')!;
    const body = document.querySelector<HTMLElement>('[data-testid="account-body"]')!;
    const close = document.querySelector<HTMLElement>('[data-testid="account-close"]')!;
    const rect = (el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      return { top: Math.round(r.top), height: Math.round(r.height) };
    };
    return { modal: rect(content), modalScrollTop: content.scrollTop, body: rect(body), bodyScrollTop: Math.round(body.scrollTop), close: rect(close) };
  });
}

async function openProfiles(page: Page) {
  const menu = await openAccountMenu(page);
  await menu.getByTestId("account-entry").click();
  await expect(modal(page)).toHaveAttribute("data-step", "profiles");
}

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 4 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const mobile = width < 1024;
      const base = `ux-batch4-${width}-${scheme}`;

      test("U-10 칩 크기 = 토글, U-11 시작 안내는 한 단락 문장 + 밑줄 링크", async ({ page }) => {
        test.setTimeout(90_000);
        const puts: unknown[] = [];
        page.on("request", (request) => {
          if (isDefaultTargetPut(request)) puts.push(request.postDataJSON());
        });
        await openApp(page, "?mock_session=onboarded&ux_batch4=1");

        // U-10: 보이는 칩 = 토글 틀(높이·글자 크기·완전히 둥근 모양), 같은 줄 가운데, 누르는 영역 44px
        const frame = page.getByTestId("pregnancy-toggle").locator("> div");
        const face = page.getByTestId("target-chip-face");
        const [frameBox, faceBox] = [await box(frame), await box(face)];
        expect(Math.round(faceBox.height)).toBe(Math.round(frameBox.height));
        expect(Math.round(frameBox.height)).toBe(28);
        expect(Math.abs(faceBox.y + faceBox.height / 2 - (frameBox.y + frameBox.height / 2))).toBeLessThanOrEqual(1);
        const toggleText = await style(page.getByTestId("pregnancy-general"), "font-size");
        const chipText = await style(face, "font-size", "border-top-left-radius");
        expect(chipText["font-size"]).toBe(toggleText["font-size"]);
        expect(parseFloat(chipText["border-top-left-radius"])).toBeGreaterThanOrEqual(faceBox.height / 2);
        await expectTouchTarget(page.getByTestId("target-chip"), { widthToo: false });
        // 한 줄(줄바꿈 없음): 사진·토글·칩·보내기가 같은 줄
        const row = await box(page.getByTestId("input-target-row"));
        expect(Math.round(row.height)).toBe(MIN_TOUCH);
        await expectNoHorizontalScroll(page);

        // U-11: 한 단락(<p>), 통합 고지와 같은 글자 디자인, 카드·아바타·버튼 모양 없음
        const start = page.getByTestId("start-target");
        await expect(start).toBeVisible();
        expect(await start.evaluate((el) => el.tagName)).toBe("P");
        await expect(start).toHaveText("나 프로필로 확인해요. 이 프로필의 연령대·임신 여부가 답변에 쓰여요. 프로필 없이도 확인할 수 있어요. 게스트로 이용");
        await expect(start.getByTestId("profile-avatar")).toHaveCount(0);
        const keys = ["font-size", "line-height", "color", "font-weight"];
        expect(await style(start, ...keys)).toEqual(await style(notice(page), ...keys));
        expect((await style(start, "border-top-width", "background-color"))["border-top-width"]).toBe("0px");
        await expect(start).not.toContainText("안전");
        // 링크 모양: 같은 글자 크기, 밑줄, 문장 끝(같은 단락 안). 동작은 버튼(대상 변경)
        const link = start.getByRole("button", { name: "게스트로 이용" });
        const linkStyle = await style(link, "font-size", "text-decoration-line", "border-top-width", "background-color");
        expect(linkStyle["font-size"]).toBe((await style(start, "font-size"))["font-size"]);
        expect(linkStyle["text-decoration-line"]).toContain("underline");
        expect(linkStyle["border-top-width"]).toBe("0px");
        expect(linkStyle["background-color"]).toBe("rgba(0, 0, 0, 0)");
        // 누르는 영역: 보이는 줄 높이는 그대로, 위아래로 넓힌 투명 영역까지 합쳐 44px 이상(가운데 ±22px 안을 누르면 링크다)
        const linkBox = await box(link);
        const hits = await page.evaluate(
          ({ x, y }) => [-21, 0, 21].map((dy) => document.elementFromPoint(x, y + dy)?.closest('[data-testid="start-target-guest"]') !== null),
          { x: linkBox.x + linkBox.width / 2, y: linkBox.y + linkBox.height / 2 },
        );
        expect(hits).toEqual([true, true, true]);
        await expectNoHorizontalScroll(page);
        await shot(page, base);

        // 키보드: Tab으로 링크에 오고 Enter로 고른다 → 대상 = 게스트로 이용, 서버 저장, 초점은 질문 칸
        const saved = page.waitForRequest(isDefaultTargetPut);
        await link.focus();
        await expect(link).toBeFocused();
        await page.keyboard.press("Enter");
        await saved;
        await expect(start.getByTestId("start-target-heading")).toHaveText("게스트로 이용 중이에요");
        await expect(start).toHaveText("게스트로 이용 중이에요. 저장한 프로필 값 없이 확인해요.");
        await expect(start.getByRole("button")).toHaveCount(0);
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 게스트로 이용");
        await expect(input(page)).toBeFocused();
        expect(puts).toEqual([{ target: "guest" }]);
        await shot(page, `${base}-start-guest`);
      });

      test("U-12 누가 먹나요 독립 섹션, U-13 계정 버튼은 클릭으로만 열림(칩 호버는 그대로)", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page, "?mock_session=onboarded&ux_batch4=1");
        if (!mobile) {
          // 입력창 칩의 호버 열림은 그대로다(확인 대기 항목, 이번 지시 범위 밖): 올리면 열리고 입력창 초점은 그대로, 내리면 닫힌다
          await input(page).focus();
          await page.getByTestId("target-chip").hover();
          await expect(page.getByTestId("target-menu")).toBeVisible();
          await expect(input(page)).toBeFocused();
          await page.mouse.move(0, 0);
          await expect(page.getByTestId("target-menu")).toHaveCount(0);
        }
        if (mobile) await page.getByTestId("menu-button").click();
        const button = page.getByTestId("account-menu-button").first();
        const menu = page.getByTestId("account-menu");
        await expect(button).toHaveAttribute("aria-haspopup", "menu");

        // U-13: 마우스를 올려도 열리지 않는다(예전 호버 열림 지연 120ms보다 넉넉히 기다린다)
        await button.hover();
        await page.waitForTimeout(600);
        await expect(menu).toHaveCount(0);
        await expect(button).toHaveAttribute("aria-expanded", "false");
        // 클릭하면 열리고, 다시 클릭하면 닫힌다
        await button.click();
        await expect(menu).toBeVisible();
        await expect(button).toHaveAttribute("aria-expanded", "true");
        await expect(menu.getByRole("menuitem", { name: "프로필 관리" })).toBeFocused();

        // U-12: 순서 = 프로필 관리 → ─ → 누가 먹나요 → ─ → 화면 모드 → 약관·정책 → ─ → 로그아웃
        const names = await menu.locator('[role="menuitem"], [role="menuitemradio"], [role="separator"]').evaluateAll((items) => items.map((item) => (item.getAttribute("role") === "separator" ? "─" : item.textContent?.trim())));
        expect(names).toEqual(["프로필 관리", "─", "게스트로 이용", "나", "첫째", "─", "밝은 모드", "다크 모드", "시스템기기 설정을 따라요", "약관·정책", "─", "로그아웃"]);
        await expect(menu.getByTestId("target-choice-nested")).toHaveCount(0);
        // 섹션 제목·항목의 들여쓰기·폭·높이가 `화면 모드`와 같다
        const targetGroup = menu.getByRole("group", { name: "누가 먹나요" });
        const [guestItem, lightItem] = [await box(menu.getByRole("menuitemradio", { name: "게스트로 이용" })), await box(menu.getByRole("menuitemradio", { name: "밝은 모드" }))];
        expect(guestItem.x).toBeCloseTo(lightItem.x, 0);
        expect(guestItem.width).toBeCloseTo(lightItem.width, 0);
        expect(guestItem.height).toBeCloseTo(lightItem.height, 0);
        const [targetLabel, themeLabel] = [await box(menu.getByText("누가 먹나요", { exact: true })), await box(menu.getByText("화면 모드", { exact: true }))];
        expect(targetLabel.x).toBeCloseTo(themeLabel.x, 0);
        expect(await style(menu.getByText("누가 먹나요", { exact: true }), "font-size", "font-weight", "color")).toEqual(await style(menu.getByText("화면 모드", { exact: true }), "font-size", "font-weight", "color"));
        // 고른 표시(체크)의 자리도 같다
        await expect(menu.getByRole("menuitemradio", { name: "나" })).toHaveAttribute("aria-checked", "true");
        const [targetCheck, themeCheck] = [await box(menu.getByRole("menuitemradio", { name: "나" }).locator("svg").last()), await box(menu.locator('[role="menuitemradio"][aria-checked="true"]').filter({ hasNotText: "나" }).locator("svg").last())];
        expect(targetCheck.x).toBeCloseTo(themeCheck.x, 0);
        await expect(targetGroup).toBeVisible();
        // 메뉴는 화면 안(위로 열림)
        const menuBox = await box(menu);
        expect(menuBox.y).toBeGreaterThanOrEqual(0);
        expect(menuBox.y + menuBox.height).toBeLessThanOrEqual((await box(button)).y + 0.5);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-account-menu`);

        // 키보드: ↓로 섹션 항목으로, 고르면 기본 대상 변경(메뉴 닫힘), Esc 닫기는 버튼으로 초점
        await page.keyboard.press("ArrowDown");
        await expect(menu.getByRole("menuitemradio", { name: "게스트로 이용" })).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(menu).toHaveCount(0);
        await expect(button).toBeFocused();
        await page.keyboard.press("Enter");
        await expect(menu).toBeVisible();
        await menu.getByRole("menuitemradio", { name: "첫째" }).click();
        await expect(menu).toHaveCount(0);
        await expect(button).toHaveText("첫째");
        // 다시 클릭으로 열고 같은 버튼 클릭으로 닫힌다
        await button.click();
        await expect(menu).toBeVisible();
        await button.click();
        await expect(menu).toHaveCount(0);
        await expect(button).toHaveAttribute("aria-expanded", "false");
        await expect(button).toBeFocused(); // 닫히면 초점은 버튼으로(Radix). 그다음 입력창으로 옮긴다
        if (mobile) {
          await page.keyboard.press("Escape");
          await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
        }
      });

      test("U-14 색·버튼을 눌러도 모달 높이·스크롤 위치 그대로, U-15 색이 첫 번째 입력이고 머리 병아리 배경이 바로 바뀜", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page, "?mock_session=onboarded&ux_batch4=form");
        await openProfiles(page);
        await modal(page).getByTestId("add-family").click();
        await expect(modal(page)).toHaveAttribute("data-step", "profile-form");
        const form = modal(page).getByTestId("profile-form");
        const colors = form.getByRole("radiogroup", { name: "프로필 색" });
        const head = form.getByTestId("profile-form-head");

        // U-15: 색이 제목 바로 아래 첫 입력(진행바 다음, 관계보다 앞)
        const colorBox = await box(colors);
        expect(colorBox.y).toBeGreaterThan((await box(form.getByTestId("profile-progress"))).y);
        expect(colorBox.y).toBeLessThan((await box(form.getByRole("radiogroup", { name: "관계", exact: true }))).y);
        const firstField = await form.locator("form").evaluate((el) => el.querySelector('[role="radiogroup"], input:not([type="radio"])')?.getAttribute("data-testid"));
        expect(firstField).toBe("avatar-color-picker");
        // 진행바 사양은 그대로(필수 4 → 선택 2, 색은 맨 뒤)
        await expect(form.getByTestId("profile-step")).toHaveCount(6);
        expect(await form.getByTestId("profile-step").evaluateAll((items) => items.map((item) => item.getAttribute("data-step")))).toEqual(["relation", "name", "age", "sex", "medications", "color"]);
        await expect(form.getByTestId("profile-save")).toBeDisabled();
        await expect(colors.getByRole("radio", { name: "노랑" })).toBeChecked();
        await expect(head.getByTestId("profile-avatar")).toHaveAttribute("data-color", "yellow");

        // U-14: 누르기 전 값
        const before = await modalGeometry(page);
        expect(before.modalScrollTop).toBe(0);
        for (const color of ["coral", "pink", "teal"] as const) {
          await colors.locator(`[data-testid="avatar-color-option"][data-color="${color}"]`).click();
          await expect(head.getByTestId("profile-avatar")).toHaveAttribute("data-color", color); // U-15: 머리 병아리 배경이 바로 바뀐다
          expect(await modalGeometry(page)).toEqual(before);
        }
        await shot(page, `${base}-form-color-first`);
        // 키보드로 옮겨도(→) 같다
        await colors.getByRole("radio", { name: "청록" }).focus();
        await page.keyboard.press("ArrowRight");
        await expect(colors.getByRole("radio", { name: "초록" })).toBeChecked();
        await expect(head.getByTestId("profile-avatar")).toHaveAttribute("data-color", "green");
        expect((await modalGeometry(page)).modalScrollTop).toBe(0);

        // 본문을 아래로 내린 뒤 다른 버튼(관계·연령대·성별)을 눌러도 상자는 스크롤되지 않고 본문 스크롤 위치만 사용자가 둔 곳이다
        await form.getByLabel("이름(별명)").fill("셋째");
        await completeRequired(form);
        await expect(form.getByTestId("profile-save")).toBeEnabled();
        const afterFill = await modalGeometry(page);
        expect(afterFill.modal).toEqual(before.modal);
        expect(afterFill.modalScrollTop).toBe(0);
        for (const [group, option] of [["관계", "부모"], ["연령대", "만 65세 이상"], ["성별", "여성"]] as const) {
          const radio = form.getByRole("radiogroup", { name: group, exact: true }).getByRole("radio", { name: option, exact: true });
          await radio.scrollIntoViewIfNeeded();
          const prior = await modalGeometry(page);
          await radio.click();
          await expect(radio).toHaveAttribute("aria-checked", "true");
          expect(await modalGeometry(page), `${group} ${option}`).toEqual(prior);
        }
        // 맨 위로 올려 색을 눌러도 같다
        await page.getByTestId("account-body").evaluate((el) => el.scrollTo({ top: 0 }));
        const top = await modalGeometry(page);
        await colors.locator('[data-testid="avatar-color-option"][data-color="blue"]').click();
        expect(await modalGeometry(page)).toEqual(top);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-form-after-click`);
      });

      test("U-17 고른 뒤 다시 확인: 바꾸기 숨김, 말풍선 없음, 진행 표시가 요약 카드 다음 항목", async ({ page }) => {
        test.setTimeout(90_000);
        await openApp(page);
        await input(page).fill("mock:되묻기여러 합성 질문");
        await page.getByRole("button", { name: "보내기" }).click();
        const turn1 = page.locator('[data-turn="turn-1"]');
        await expect(turn1.getByTestId("candidate-card")).toBeVisible();
        for (const group of await turn1.getByTestId("candidate-group").all()) await group.getByTestId("candidate").first().click();
        await expect(turn1.getByTestId("candidate-change")).toHaveCount(2); // 고르는 중에는 바꾸기가 있다
        await page.getByTestId("resend-button").click();
        const turn2 = page.locator('[data-turn="turn-2"]');
        const progress = turn2.getByRole("status", { name: "진행 상태" });
        await expect(progress).toBeVisible();
        await expect(turn1.getByTestId("candidate-picked")).toHaveCount(2);
        await expect(turn1.getByTestId("candidate-change")).toHaveCount(0);
        await expect(page.getByText(/고른 약: /)).toHaveCount(0);
        await expect(turn2.locator('p[data-side="me"]')).toHaveCount(0);
        const cardBox = await box(turn1.getByTestId("candidate-card"));
        expect((await box(progress)).y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height - 0.5);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-u17-progress`);
        await expect(turn2.getByTestId("result-card").first()).toBeVisible();
        await expect(turn1.getByTestId("candidate-change")).toHaveCount(0);
        await shot(page, `${base}-u17-done`);
      });

      test("U-16 프로필 관리: 동의 내용 보기·로그아웃·탈퇴가 모달 바닥에 고정, 목록 영역만 스크롤", async ({ page }) => {
        test.setTimeout(120_000);
        await openApp(page, "?mock_session=onboarded&ux_batch4=list");
        await openProfiles(page);
        // 가족을 3명으로 채운다(본인 + 가족 3)
        for (const name of ["둘째", "셋째"]) {
          await modal(page).getByTestId("add-family").click();
          const form = modal(page).getByTestId("profile-form");
          await form.getByLabel("이름(별명)").fill(name);
          await completeRequired(form);
          await form.getByTestId("profile-save").click();
          await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        }
        await expect(modal(page).getByTestId("profile-item")).toHaveCount(4);
        await expect(modal(page).getByTestId("add-family")).toBeDisabled();
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-profile-actions`);
        // 목록이 넘치는 높이(480px)로 줄여 "목록 영역만 스크롤"을 본다(393·1280 모두)
        await page.setViewportSize({ width, height: 480 });

        const actions = modal(page).getByTestId("profile-list-actions");
        const scroller = modal(page).getByTestId("profile-list-scroll");
        const modalBox = await box(modal(page));
        const actionsBox = await box(actions);
        // 바닥 고정: 아래 줄의 아래 끝 = 모달 상자 아래 끝, 세 동작이 이 줄 안에 있다
        expect(Math.abs(actionsBox.y + actionsBox.height - (modalBox.y + modalBox.height))).toBeLessThanOrEqual(1);
        for (const name of ["동의 내용 보기", "로그아웃", "탈퇴"]) {
          const action = actions.getByRole("button", { name, exact: true });
          await expect(action).toBeVisible();
          await expectTouchTarget(action, { widthToo: false });
        }
        await expect(modal(page).getByTestId("profile-list-scroll").getByRole("button", { name: "탈퇴" })).toHaveCount(0);
        // 탈퇴는 다른 동작과 시각적으로 구분된다(위험 글자 색이 다르다)
        const withdrawColor = (await style(actions.getByTestId("withdraw"), "color")).color;
        expect(withdrawColor).not.toBe((await style(actions.getByRole("button", { name: "로그아웃" }), "color")).color);
        // 본문(account-body)은 넘치지 않고, 넘치면 목록 영역만 스크롤한다
        expect(await page.getByTestId("account-body").evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
        expect(await scroller.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
        expect(await scroller.evaluate((el) => el.scrollHeight > el.clientHeight + 1)).toBe(true); // 본인 + 가족 3명이면 넘친다
        await scroller.evaluate((el) => el.scrollTo({ top: el.scrollHeight }));
        await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
        expect(await box(actions)).toEqual(actionsBox); // 아래 줄은 움직이지 않는다
        await expect(modal(page).getByTestId("family-full")).toBeInViewport();
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-profile-actions-scrolled`);

        // 동작은 그대로: 탈퇴는 확인창(취소 먼저), 동의 내용 보기는 동의 화면
        await actions.getByTestId("withdraw").click();
        const confirm = page.getByTestId("confirm-dialog");
        await expect(confirm).toBeVisible();
        await confirm.getByRole("button", { name: "취소" }).click();
        await expect(confirm).toHaveCount(0);
        await expect(modal(page)).toHaveAttribute("data-step", "profiles");
        await actions.getByRole("button", { name: "동의 내용 보기" }).click();
        await expect(modal(page)).toHaveAttribute("data-step", "consent");

        // U-12 확인 대기 항목: 가족 3명이면 계정 메뉴의 `누가 먹나요` 섹션이 5칸이고, 메뉴는 화면 안에 있으며 넘치면 메뉴 안에서 스크롤해 끝 항목(로그아웃)까지 닿는다
        await page.setViewportSize({ width, height: HEIGHT });
        await page.keyboard.press("Escape");
        await expect(modal(page)).toHaveCount(0);
        const menu = await openAccountMenu(page);
        await expect(menu.getByTestId("target-option")).toHaveText(["게스트로 이용", "나", "첫째", "둘째", "셋째"]);
        const menuBox = await box(menu);
        expect(menuBox.y).toBeGreaterThanOrEqual(0);
        expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(HEIGHT);
        const logout = menu.getByRole("menuitem", { name: "로그아웃" });
        await logout.scrollIntoViewIfNeeded();
        await expect(logout).toBeInViewport();
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-account-menu-family3`);
      });
    });
  }
}

test.describe("FE-17 UX 묶음 4 · U-18 창 크기 자동 열고 닫기", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme}: 1280 → 393 닫힘, 393 → 1280 펼침, 같은 구간 안 수동 접기는 그대로`, async ({ page }) => {
      test.setTimeout(90_000);
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1280, height: HEIGHT });
      await openApp(page, "?ux_batch4=resize");
      const sidebar = page.locator('[data-testid="sidebar"][data-presentation="push"]');
      const rail = page.getByTestId("sidebar-rail");
      await expect(sidebar).toBeVisible();
      await input(page).fill("입력 중인 글자");
      // 같은 구간(넓은 폭)에서 접고 폭만 바꾸면 그대로
      await page.getByTestId("sidebar-toggle").click();
      await expect(rail).toBeVisible();
      await page.setViewportSize({ width: 1100, height: HEIGHT });
      await expect(rail).toBeVisible();
      await expect(sidebar).toHaveCount(0);
      // 기준선 아래로 → 닫힘(☰)
      await page.setViewportSize({ width: 393, height: HEIGHT });
      await expect(rail).toHaveCount(0);
      await expect(page.getByTestId("menu-button")).toBeVisible();
      await shot(page, `ux-batch4-u18-393-${scheme}`);
      // 드로어를 연 채 넓히면 드로어는 닫히고 사이드바가 펼쳐진다, 초점은 사이드바 토글
      await page.getByTestId("menu-button").click();
      await expect(page.getByTestId("menu-drawer")).toBeVisible();
      await page.setViewportSize({ width: 1280, height: HEIGHT });
      await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
      await expect(sidebar).toBeVisible();
      await expect(page.getByTestId("sidebar-toggle")).toBeFocused();
      await expect(input(page)).toHaveValue("입력 중인 글자");
      await expectNoHorizontalScroll(page);
      await shot(page, `ux-batch4-u18-1280-${scheme}`);
      // 펼친 채 기준선 아래로 → 닫힘, 다시 넓히면 펼침
      await page.setViewportSize({ width: 1023, height: HEIGHT });
      await expect(sidebar).toHaveCount(0);
      await expect(page.getByTestId("menu-drawer")).toHaveCount(0);
      await page.setViewportSize({ width: 1024, height: HEIGHT });
      await expect(sidebar).toBeVisible();
      await expect(input(page)).toHaveValue("입력 중인 글자");
    });
  }
});
