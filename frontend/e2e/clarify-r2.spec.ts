import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { AA_NORMAL, failures, measureContrast } from "./contrast";
import { HEIGHT, ask, expectNoHorizontalScroll, expectTouchTarget, mockChat, openApp } from "./helpers";

// 여러 약 되묻기 카드 2차(FE-10, 디자인 "FE-09 r2"): 2열(카드 칸 640px 이상)·글자 위계·이어 붙인 캡슐 A/B 표지·확인 줄.
// 통신 대역은 mock 시나리오 `clarifyMulti`(묶음 둘)·`clarifyTriple`(묶음 셋)이다. 동작(요청·초점)은 clarify-multi.spec.ts가 본다.
// 캡처: `FE10_SHOT_DIR`을 주면 그 폴더에 `*-fe10.png`를 남긴다(로컬 전용 폴더. 주지 않으면 찍지 않는다).
const SHOT_DIR = process.env.FE10_SHOT_DIR;
const shot = async (page: Page, name: string, target?: Locator) => {
  if (!SHOT_DIR) return;
  if (target) await target.evaluate((el) => el.scrollIntoView({ block: "end" }));
  await page.waitForFunction(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0));
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${page.viewportSize()!.width}-fe10.png`) });
};

/** 2열 전환 기준(FE-10-04 A): 카드가 놓인 칸의 폭 */
const TWO_COLUMN_MIN = 640;
const card = (page: Page) => page.getByTestId("candidate-card");
const group = (page: Page, index: number) => page.getByTestId("candidate-group").nth(index);
const cells = (page: Page) => page.getByTestId("capsule-cell");
const capsule = (page: Page) => page.getByTestId("picked-capsule");
const resendButton = (page: Page) => page.getByTestId("resend-button");
const box = async (target: Locator) => (await target.boundingBox())!;
/** 카드가 놓인 칸(컨테이너)의 폭 */
const slotWidth = (page: Page) => card(page).evaluate((el) => el.parentElement!.getBoundingClientRect().width);
const style = (target: Locator, property: string) => target.evaluate((el, name) => getComputedStyle(el).getPropertyValue(name), property);

async function open(page: Page, scenario: "clarifyMulti" | "clarifyTriple" = "clarifyMulti") {
  await mockChat(page, scenario, "found");
  await openApp(page);
  await ask(page);
  await expect(card(page)).toBeVisible();
}

/** 묶음 둘이 나란한가(왼쪽 A·오른쪽 B, 위쪽 정렬) */
async function isTwoColumn(page: Page) {
  const [a, b] = [await box(group(page, 0)), await box(group(page, 1))];
  return Math.abs(a.y - b.y) < 1 && b.x >= a.x + a.width - 1;
}

async function pickBoth(page: Page) {
  await group(page, 0).getByTestId("candidate").nth(2).click();
  await group(page, 1).getByTestId("candidate").nth(1).click();
  await expect(resendButton(page)).not.toHaveAttribute("aria-disabled", "true");
}

for (const width of [1280, 1024]) {
  test.describe(`여러 약 되묻기 2차 ${width}px: 2열(FE-10)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("카드 칸이 640px 이상이라 묶음이 2열(A 왼쪽·B 오른쪽, 위쪽 정렬)이고, 확인 줄은 캡슐 가로 + 오른쪽 버튼이다", async ({ page }) => {
      await open(page);
      expect(await slotWidth(page)).toBeGreaterThanOrEqual(TWO_COLUMN_MIN);
      expect(await isTwoColumn(page)).toBe(true);
      const [a, b] = [await box(group(page, 0)), await box(group(page, 1))];
      expect(Math.abs(a.width - b.width)).toBeLessThan(2); // 1fr 1fr
      // 묶음 머리: A(흰, 왼쪽 둥근)·B(파랑, 오른쪽 둥근) 표지 + 이름 16px 굵게 + "제품 N개" 12px
      const tags = page.getByTestId("group-tag");
      await expect(tags).toHaveText(["A", "B"]);
      expect(await style(tags.nth(0), "border-top-left-radius")).toBe("12px");
      expect(await style(tags.nth(0), "border-top-right-radius")).toBe("0px");
      expect(await style(tags.nth(1), "border-top-right-radius")).toBe("12px");
      expect(await style(tags.nth(1), "border-top-left-radius")).toBe("0px");
      expect((await box(tags.nth(0))).height).toBe(24);
      const head = group(page, 0).locator("header");
      expect(await style(head, "font-size")).toBe("16px");
      expect(await style(head, "font-weight")).toBe("700");
      await expect(head.locator('[data-slot="group-count"]')).toHaveText("제품 3개");
      expect(await style(head.locator('[data-slot="group-count"]'), "font-size")).toBe("12px");
      // 글자 위계(FE-10-01 B): 머리 16px 굵게 > 후보 이름 15px 반굵게 > 보조줄 12px
      const first = group(page, 0).getByTestId("candidate").first();
      expect(await style(first.locator('[data-part="candidate-name"]'), "font-size")).toBe("15px");
      expect(await style(first.locator('[data-part="candidate-name"]'), "font-weight")).toBe("600");
      expect(await style(first.locator('[data-part="candidate-sub"]'), "font-size")).toBe("12px");
      await expectTouchTarget(first);
      // 확인 줄: 첫 행 심볼 + 안내 문장(15px), 다음 행 점선 빈 칸 둘 + 남은 수 + 꺼진 버튼
      const line = page.getByTestId("resend-pick").getByTestId("candidates-line");
      await expect(line).toHaveText("어느 제품인지 고르면 금기를 확인해 드려요.");
      expect(await style(line, "font-size")).toBe("15px");
      await expect(line.locator("img")).toHaveAttribute("alt", "");
      expect((await box(line.locator("img"))).height).toBe(18);
      await expect(cells(page)).toHaveText(["A 고르기 전", "B 고르기 전"]);
      expect(await style(cells(page).nth(0), "outline-style")).toBe("dashed");
      await expect(page.getByTestId("picks-remaining")).toHaveText("2개 더 골라 주세요");
      await expect(resendButton(page)).toHaveAttribute("aria-disabled", "true");
      await shot(page, "01-none");

      // 둘 다 고르면: 접힌 줄 앞에 표지, 캡슐 칸에 이름(A 흰·B 파랑), 가로로 나란히, 버튼은 같은 행 오른쪽
      await pickBoth(page);
      expect(await isTwoColumn(page)).toBe(true); // 접힌 줄도 2열
      await expect(page.getByTestId("candidate-picked").getByTestId("group-tag")).toHaveText(["A", "B"]);
      await expect(cells(page)).toHaveText(["A가나다시럽", "B가나다시럽 키즈"]);
      const [cellA, cellB, button, pill] = [await box(cells(page).nth(0)), await box(cells(page).nth(1)), await box(resendButton(page)), await box(capsule(page))];
      expect(Math.abs(cellA.y - cellB.y)).toBeLessThan(1);
      expect(cellB.x).toBeGreaterThan(cellA.x);
      expect(button.x).toBeGreaterThanOrEqual(pill.x + pill.width);
      expect(button.y).toBeLessThan(pill.y + pill.height);
      expect(await style(cells(page).nth(0), "font-size")).toBe("15px");
      expect(await style(cells(page).nth(0), "font-weight")).toBe("600");
      expect(await style(cells(page).nth(1), "border-left-width")).toBe("2px"); // 칸 사이 경계선
      expect(parseFloat(await style(capsule(page), "border-top-left-radius"))).toBeGreaterThanOrEqual(pill.height / 2); // 양 끝만 둥글다(캡슐 틀이 자른다)
      expect(await style(capsule(page), "overflow-x")).toBe("hidden");
      await expectTouchTarget(resendButton(page));
      await expectNoHorizontalScroll(page);
      await shot(page, "02-both");
    });
  });
}

test.describe("여러 약 되묻기 2차 393px: 한 열·캡슐 세로(FE-10)", () => {
  test.use({ viewport: { width: 393, height: HEIGHT } });

  test("카드 칸이 640px 미만이라 묶음이 한 열이고, 캡슐은 세로로 쌓이며 버튼은 그 아래다", async ({ page }) => {
    await open(page);
    expect(await slotWidth(page)).toBeLessThan(TWO_COLUMN_MIN);
    expect(await isTwoColumn(page)).toBe(false);
    const [a, b] = [await box(group(page, 0)), await box(group(page, 1))];
    expect(b.y).toBeGreaterThanOrEqual(a.y + a.height - 1);
    await expect(page.getByTestId("group-tag")).toHaveText(["A", "B"]);
    await expect(cells(page)).toHaveText(["A 고르기 전", "B 고르기 전"]);
    await shot(page, "01-none");
    await shot(page, "01-none-confirm", page.getByTestId("resend-pick"));

    await pickBoth(page);
    await expect(cells(page)).toHaveText(["A가나다시럽", "B가나다시럽 키즈"]);
    const [cellA, cellB, button, pill] = [await box(cells(page).nth(0)), await box(cells(page).nth(1)), await box(resendButton(page)), await box(capsule(page))];
    expect(cellB.y).toBeGreaterThanOrEqual(cellA.y + cellA.height - 1); // 세로 쌓기
    expect(Math.abs(cellA.width - cellB.width)).toBeLessThan(1);
    expect(await style(cells(page).nth(1), "border-top-width")).toBe("2px");
    expect(await style(cells(page).nth(1), "border-left-width")).toBe("0px");
    expect(await style(capsule(page), "border-top-left-radius")).toBe("22px"); // 맨 위·맨 아래 칸만 둥글다(캡슐 틀이 자른다)
    expect(await style(capsule(page), "border-bottom-right-radius")).toBe("22px");
    expect(await style(capsule(page), "overflow-y")).toBe("hidden");
    expect(button.y).toBeGreaterThanOrEqual(pill.y + pill.height); // 버튼은 아래
    await expectTouchTarget(resendButton(page));
    await expectNoHorizontalScroll(page);
    await shot(page, "02-both", page.getByTestId("resend-pick"));
  });

  test("긴 제품 이름은 캡슐 칸 안에서 줄바꿈되고 잘리지 않는다(말줄임 없음)", async ({ page }) => {
    await open(page);
    await pickBoth(page);
    const text = cells(page).nth(1).locator('[data-slot="cell-text"]');
    // 받은 이름을 화면에서만 길게 바꿔 본다(칸 폭을 넘는 길이)
    await text.evaluate((el) => {
      el.textContent = "아주긴합성제품이름정 500밀리그램 서방형 필름코팅정 어린이용 딸기맛 현탁액";
    });
    const cell = await box(cells(page).nth(1));
    expect(cell.height).toBeGreaterThan(40); // 두 줄 이상
    expect(await text.evaluate((el) => el.scrollWidth <= el.clientWidth + 1 || getComputedStyle(el).display === "inline")).toBe(true);
    expect(await style(text, "text-overflow")).not.toBe("ellipsis");
    expect(await style(text, "white-space")).not.toBe("nowrap");
    await expectNoHorizontalScroll(page);
  });
});

test.describe("여러 약 되묻기 2차: 2열 기준은 화면 폭이 아니라 카드 칸의 폭이다(FE-10-02 A·FE-10-04 A)", () => {
  test("화면 폭을 바꿔 가며 '카드 칸 640px 이상 ⇔ 2열'을 확인한다(1024·1023 부근 포함)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: HEIGHT });
    await open(page);
    const seen: Array<{ viewport: number; slot: number; two: boolean }> = [];
    for (const viewport of [1280, 1024, 1023, 960, 900, 800, 720, 680, 660, 640, 600, 393]) {
      await page.setViewportSize({ width: viewport, height: HEIGHT });
      await expect(card(page)).toBeVisible();
      // 칸 폭과 배치를 한 번에(같은 레이아웃에서) 읽는다. 폭을 바꾼 직후에는 사이드바 전환으로 칸 폭이 움직이므로 값이 멈출 때까지 기다린다
      const measure = () =>
        page.evaluate(() => {
          const section = document.querySelector('[data-testid="candidate-card"]')!;
          const [a, b] = [...section.querySelectorAll('[data-testid="candidate-group"]')].map((el) => el.getBoundingClientRect());
          return { slot: section.parentElement!.getBoundingClientRect().width, two: Math.abs(a.top - b.top) < 1 && b.left >= a.right - 1 };
        });
      let last = await measure();
      await expect
        .poll(async () => {
          const next = await measure();
          const settled = next.slot === last.slot && next.two === last.two;
          last = next;
          return settled;
        })
        .toBe(true);
      const { slot, two } = last;
      seen.push({ viewport, slot, two });
      expect(two, `화면 ${viewport}px, 카드 칸 ${slot}px`).toBe(slot >= TWO_COLUMN_MIN);
    }
    // 기준의 양쪽이 모두 시험됐다
    expect(seen.some((item) => item.two)).toBe(true);
    expect(seen.some((item) => !item.two)).toBe(true);
    expect(seen.find((item) => item.viewport === 1024)!.two).toBe(true);
    expect(seen.find((item) => item.viewport === 393)!.two).toBe(false);
    test.info().annotations.push({ type: "slot-widths", description: JSON.stringify(seen) });
  });
});

test.describe("여러 약 되묻기 2차 1280px: 묶음 3개(FE-10)", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("3개면 2열로 줄바꿈하고(C는 둘째 줄 왼쪽), 표지·캡슐은 흰|파|흰이며 가운데 칸은 직각이다", async ({ page }) => {
    await open(page, "clarifyTriple");
    await expect(page.getByTestId("candidate-group")).toHaveCount(3);
    const [a, b, c] = [await box(group(page, 0)), await box(group(page, 1)), await box(group(page, 2))];
    expect(Math.abs(a.y - b.y)).toBeLessThan(1);
    expect(b.x).toBeGreaterThanOrEqual(a.x + a.width - 1);
    expect(Math.abs(c.x - a.x)).toBeLessThan(1);
    expect(c.y).toBeGreaterThanOrEqual(Math.max(a.y + a.height, b.y + b.height) - 1);
    const tags = page.getByTestId("group-tag");
    await expect(tags).toHaveText(["A", "B", "C"]);
    expect(await tags.evaluateAll((els) => els.map((el) => [el.getAttribute("data-tone"), el.getAttribute("data-shape")]))).toEqual([
      ["white", "left"],
      ["blue", "middle"],
      ["white", "right"],
    ]);
    for (const corner of ["border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius"]) {
      expect(await style(tags.nth(1), corner)).toBe("0px");
    }
    await expect(cells(page)).toHaveText(["A 고르기 전", "B 고르기 전", "C 고르기 전"]);
    await expect(page.getByTestId("picks-remaining")).toHaveText("3개 더 골라 주세요");
    // 셋째만 고른다: C칸만 채워지고(흰) 버튼은 꺼진 그대로다
    await group(page, 2).getByTestId("candidate").nth(0).click();
    await expect(cells(page)).toHaveText(["A 고르기 전", "B 고르기 전", "C라마바캡슐 10밀리그램"]);
    await expect(cells(page).nth(2)).toHaveAttribute("data-tone", "white");
    await expect(page.getByTestId("picks-remaining")).toHaveText("2개 더 골라 주세요");
    await expect(resendButton(page)).toHaveAttribute("aria-disabled", "true");
    await shot(page, "03-three-one-picked");
    // 모두 고르면 흰|파|흰 세 칸이 한 줄로 이어진다
    await group(page, 0).getByTestId("candidate").nth(0).click();
    await group(page, 1).getByTestId("candidate").nth(1).click();
    await expect(cells(page)).toHaveText(["A가나다정 100밀리그램", "B가나다시럽 키즈", "C라마바캡슐 10밀리그램"]);
    expect(await cells(page).evaluateAll((els) => els.map((el) => el.getAttribute("data-tone")))).toEqual(["white", "blue", "white"]);
    const ys = await cells(page).evaluateAll((els) => els.map((el) => el.getBoundingClientRect().top));
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(1);
    await expect(resendButton(page)).not.toHaveAttribute("aria-disabled", "true");
    await expectNoHorizontalScroll(page);
    await shot(page, "04-three-all-picked");
  });
});

for (const width of [393, 1280]) {
  test.describe(`여러 약 되묻기 2차 ${width}px: 색 대비(FE-10)`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("묶음 머리·표지·후보 줄·캡슐 칸·확인 줄 글자가 모두 4.5:1 이상이다(계산된 색으로 잰다)", async ({ page }) => {
      await open(page);
      // 하나만 고른 상태: 펼쳐진 묶음(머리·후보)·접힌 줄·고른 칸(A 흰)·빈 칸이 함께 있다
      await group(page, 0).getByTestId("candidate").nth(0).click();
      const before = [await measureContrast(page, '[data-testid="candidate-card"]'), await measureContrast(page, '[data-testid="resend-pick"]')];
      // 둘 다 고른 상태: 파랑 칸(B)
      await group(page, 1).getByTestId("candidate").nth(1).click();
      await expect(cells(page).nth(1)).toHaveAttribute("data-tone", "blue");
      const after = [await measureContrast(page, '[data-testid="candidate-card"]'), await measureContrast(page, '[data-testid="resend-pick"]')];
      const samples = [...before, ...after].flatMap((report) => report.samples);
      for (const report of [...before, ...after]) {
        expect(report.unmeasured).toEqual([]);
        expect(failures(report)).toEqual([]);
      }
      const ratio = (fg: string, bg: string) => {
        const sample = samples.find((item) => item.fg === fg && item.bg === bg);
        expect(sample, `${fg} on ${bg}`).toBeDefined();
        return sample!.ratio;
      };
      // 묶음 머리(노랑 바탕): 이름 #3D3524, 후보 수 #6B5F3F
      expect(ratio("#3d3524", "#ffe58f")).toBeGreaterThanOrEqual(AA_NORMAL);
      expect(ratio("#6b5f3f", "#ffe58f")).toBeGreaterThanOrEqual(AA_NORMAL);
      // 캡슐 파랑 칸(FE-10-03 A): 글자 #1F3A5F / 바탕 #C9DAEC
      expect(ratio("#1f3a5f", "#c9daec")).toBeGreaterThanOrEqual(AA_NORMAL);
      // 캡슐 흰 칸: 글자 #3D3524 / 흰 바탕, 빈 칸 글자 #6B5F3F / 흰 바탕
      expect(ratio("#3d3524", "#ffffff")).toBeGreaterThanOrEqual(AA_NORMAL);
      expect(ratio("#6b5f3f", "#ffffff")).toBeGreaterThanOrEqual(AA_NORMAL);
      // 확인 줄 첫 행(안내 문장): 글자 #3D3524 / 바탕 #FFFDF5
      expect(ratio("#3d3524", "#fffdf5")).toBeGreaterThanOrEqual(AA_NORMAL);
      test.info().annotations.push({
        type: "contrast",
        description: JSON.stringify(
          [
            ["#3d3524", "#ffe58f"],
            ["#6b5f3f", "#ffe58f"],
            ["#1f3a5f", "#c9daec"],
            ["#3d3524", "#ffffff"],
            ["#6b5f3f", "#ffffff"],
            ["#3d3524", "#fffdf5"],
          ].map(([fg, bg]) => ({ fg, bg, ratio: ratio(fg, bg) })),
        ),
      });
    });
  });
}
