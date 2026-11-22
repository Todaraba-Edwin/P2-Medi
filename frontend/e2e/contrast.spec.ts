import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { ScenarioName } from "../src/mocks/fixtures/scenarios";
import { AA_NORMAL, failures, measureContrast, summarize } from "./contrast";
import type { ContrastReport } from "./contrast";
import { HEIGHT, ask, mockChat, openApp, panel, sheet } from "./helpers";

// 색 대비 측정(FE-02 §2 RFP-24-04, PRD-09-07·08 "글자·배경 대비비 4.5:1").
// 실제로 그린 화면의 계산된 색을 재서 WCAG AA(보통 글자 4.5:1, 큰 글자 3:1)에 못 미치는 글자가 없는지 본다. 측정 방법·한계는 contrast.ts 머리 주석.
// `CONTRAST_REPORT=<폴더>`를 주면 화면별 측정값을 JSON으로 남긴다(보고용, 기본은 남기지 않는다).

const save = (name: string, report: ContrastReport) => {
  const dir = process.env.CONTRAST_REPORT;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, `${name}.json`), JSON.stringify({ min: Math.min(...report.samples.map((s) => s.ratio)), count: report.samples.length, pairs: summarize(report), unmeasured: report.unmeasured }, null, 1));
};

async function check(page: Page, name: string, rootSelector = "body") {
  const report = await measureContrast(page, rootSelector);
  save(name, report);
  expect(report.samples.length, `${name}: 잰 글자가 있어야 한다`).toBeGreaterThan(0);
  expect(report.unmeasured, `${name}: 바탕색을 정할 수 없는 글자`).toEqual([]);
  expect(failures(report), `${name}: 대비비가 기준에 못 미치는 글자`).toEqual([]);
  return report;
}

const answered = async (page: Page, name: ScenarioName) => {
  await mockChat(page, name);
  await openApp(page);
  await ask(page);
  await expect(page.locator('[data-turn] [data-testid="result-view"], [data-turn] [data-testid="error-state"]').first()).toBeVisible();
};

test.describe("측정기 자체 확인", () => {
  test("알려진 색 쌍의 대비비를 WCAG 식대로 계산한다(검정/흰색 21, #767676/흰색 4.54, #777777/흰색 4.47)", async ({ page }) => {
    await page.setContent(`
      <body style="margin:0;background:#ffffff">
        <p id="a" style="color:#000000">검정 글자</p>
        <p id="b" style="color:#767676">회색 글자 통과</p>
        <p id="c" style="color:#777777">회색 글자 미달</p>
        <div style="background:#d70015"><p id="d" style="color:#ffffff">빨강 바탕 흰 글자</p></div>
        <div style="background:#000000"><div style="background:rgba(255,255,255,0.5)"><p id="e" style="color:#000000">반투명 바탕</p></div></div>
        <p id="f" style="color:#777777;font-size:24px">큰 글자</p>
        <button disabled style="color:#cccccc">비활성</button>
      </body>`);
    const report = await measureContrast(page);
    const by = (text: string) => report.samples.find((sample) => sample.text === text)!;
    expect(by("검정 글자").ratio).toBe(21);
    expect(by("회색 글자 통과").ratio).toBe(4.54);
    expect(by("회색 글자 미달").ratio).toBe(4.47);
    expect(by("빨강 바탕 흰 글자")).toMatchObject({ fg: "#ffffff", bg: "#d70015" });
    expect(by("반투명 바탕").bg).toBe("#808080"); // 검정 위에 50% 흰색
    expect(by("큰 글자").required).toBe(3);
    expect(report.samples.some((sample) => sample.text === "비활성")).toBe(false); // 비활성 컨트롤은 재지 않는다
    expect(failures(report).map((sample) => sample.text)).toEqual(["회색 글자 미달"]);
  });
});

for (const width of [360, 320]) {
  test.describe(`색 대비 ${width}px`, () => {
    test.use({ viewport: { width, height: HEIGHT } });

    test("시작 화면: 머리줄 119·예시 칩·119 안내 줄·고지·입력창 안내 글자(외부 AI 고지는 입력창 고지, PRD-17-10 A)", async ({ page }) => {
      await openApp(page);
      const report = await check(page, `start-${width}`);
      const ids = new Set(report.samples.map((sample) => sample.testId));
      for (const id of ["emergency-entry", "start-emergency", "input-notice", "legal-footer", "example-chip"]) expect(ids, id).toContain(id);
      expect(report.samples.some((sample) => sample.placeholder)).toBe(true);
    });

    // 결과 화면: 요약·판정 줄·배지·성분 칩·보조줄·고정 안내·고지
    const RESULTS: ScenarioName[] = ["found", "notListed", "pregnancy", "pairAndPregnancy", "gradeMismatch", "pregnancyM", "ageFound", "ageInfo", "unidentified", "missingEvidence", "pairNoEvidence", "notChecked", "apiFail", "codeNotLinked", "typoCorrected", "limit", "fallbackNone", "fallbackSome", "refuse"];
    for (const name of RESULTS) {
      test(`결과 화면(${name})`, async ({ page }) => {
        await answered(page, name);
        await check(page, `result-${name}-${width}`);
      });
    }

    test("금기 배지: 병용·임부·연령 배지 글자가 4.5:1 이상이다(PRD-09-07·08)", async ({ page }) => {
      const seen: Record<string, number> = {};
      for (const name of ["pairAndPregnancy", "gradeMismatch", "pregnancyM", "ageFound"] as const) {
        await answered(page, name);
        const report = await measureContrast(page, '[data-testid="result-card"]');
        const kinds = await page.getByTestId("result-card").getByTestId("status-badge").evaluateAll((els) => els.map((el) => ({ kind: el.getAttribute("data-kind")!, text: (el.textContent ?? "").slice(0, 40) })));
        expect(kinds.length).toBeGreaterThan(0);
        for (const { kind, text } of kinds) {
          const sample = report.samples.find((item) => item.testId === "status-badge" && item.text === text);
          expect(sample, `${name}: ${text}`).toBeDefined();
          expect(sample!.ratio, `${name}: ${text}`).toBeGreaterThanOrEqual(AA_NORMAL);
          seen[kind] = Math.min(seen[kind] ?? Infinity, sample!.ratio);
        }
      }
      expect(Object.keys(seen).sort()).toEqual(["age", "contra_pair", "pregnancy"]);
      const dir = process.env.CONTRAST_REPORT;
      if (dir) {
        mkdirSync(dir, { recursive: true });
        writeFileSync(path.join(dir, `badges-${width}.json`), JSON.stringify(seen));
      }
    });

    test("응급 화면: 119 배너(빨강 바탕)와 전화 링크, 그 아래 결과", async ({ page }) => {
      await answered(page, "emergency");
      const report = await check(page, `emergency-${width}`);
      const bannerSamples = report.samples.filter((sample) => sample.testId === "emergency-banner");
      expect(bannerSamples.length).toBeGreaterThanOrEqual(2); // 안내 문장 + 전화 링크
    });

    test("되묻기 화면: 질문·후보 카드·고른 후보와 다시 묻기 버튼", async ({ page }) => {
      await answered(page, "clarify");
      await page.getByTestId("candidate").nth(1).click();
      await expect(page.getByTestId("resend-pick")).toBeVisible();
      await check(page, `clarify-${width}`);
    });

    for (const name of ["http500", "http501", "http422", "serverError"] as const) {
      test(`오류 화면(${name}): 오류 카드·다시 시도·고정 안내·고지`, async ({ page }) => {
        await answered(page, name);
        await check(page, `error-${name}-${width}`);
      });
    }

    // 근거 상세 시트: 판정 박스·표지·사유 원문·허가사항·출처 표·미확보 박스·약사 권고
    const DETAILS: ScenarioName[] = ["found", "gradeMismatch", "unidentified", "missingCauses", "rxPermit", "ageInfo", "pairNoEvidence"];
    for (const name of DETAILS) {
      test(`근거 상세 시트(${name})`, async ({ page }) => {
        await answered(page, name);
        await page.getByTestId("evidence-entry").click();
        await expect(sheet(page)).toBeVisible();
        await page.waitForTimeout(400); // 시트가 올라오는 동안에는 덮임 판정이 흔들린다
        const report = await check(page, `sheet-${name}-${width}`, '[role="dialog"]');
        expect(report.samples.length).toBeGreaterThan(3);
      });
    }

    test("근거 상세 시트(등급 정의 블록을 펼친 상태): 제목·고시 원문·조항 출처 줄·미확보 문구", async ({ page }) => {
      await answered(page, "gradeDefs");
      await page.getByTestId("evidence-entry").click();
      await sheet(page).getByRole("button", { name: "임부금기 2등급이란?" }).click();
      const source = sheet(page).locator('[data-slot="grade-def-source"]');
      await expect(source).toBeVisible();
      await source.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const report = await check(page, `sheet-gradeDefs-${width}`, '[role="dialog"]');
      expect(report.samples.some((sample) => sample.text.startsWith("(합성 출처 줄) 「의약품 병용금기"))).toBe(true); // 조항 출처 줄도 쟀다(글자는 앞 40자만 남긴다)
    });

    test("☰ 드로어: 새 질문·지금 대화·저장 안내·119 진입점", async ({ page }) => {
      await answered(page, "found");
      await page.getByRole("button", { name: "메뉴 열기" }).click();
      await expect(page.getByTestId("new-chat")).toBeVisible();
      await page.waitForTimeout(400);
      await check(page, `drawer-${width}`, '[role="dialog"]');
    });
  });
}

test.describe("색 대비 1280px", () => {
  test.use({ viewport: { width: 1280, height: HEIGHT } });

  test("시작 화면(사이드바 포함)", async ({ page }) => {
    await openApp(page);
    await check(page, "start-1280");
  });

  for (const name of ["pairAndPregnancy", "emergency", "gradeDefs"] as const) {
    test(`결과 + 사이드바 + 근거 상세 패널(${name})`, async ({ page }) => {
      await answered(page, name);
      await expect(panel(page)).toBeVisible();
      await check(page, `desktop-${name}-1280`);
    });
  }
});
