import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// 디자인 토큰 시험(FE-12-05 A: FE-01-10 A의 "다크모드 없음"을 대체. 약화가 아니라 "다크 값 있음·대비 통과"로 바꾼다).
const css = readFileSync(path.resolve(__dirname, "../styles/globals.css"), "utf8");

/** `selector { ... }` 블록 본문에서 `--name: value;`를 뽑는다 */
function blockVars(source: string, opener: RegExp): Record<string, string> {
  const start = source.search(opener);
  if (start < 0) return {};
  const open = source.indexOf("{", start);
  const close = source.indexOf("}", open);
  const body = source.slice(open + 1, close);
  const vars: Record<string, string> = {};
  for (const match of body.matchAll(/(--color-[a-z0-9-]+):\s*([^;]+);/g)) vars[match[1]] = match[2].trim().toLowerCase();
  return vars;
}

const light = blockVars(css, /@theme\s*\{/);
const darkMedia = blockVars(css, /:root:not\(\[data-theme="light"\]\)\s*\{/);
const darkAttr = blockVars(css, /:root\[data-theme="dark"\]\s*\{/);

/** `#000` 같은 짧은 표기를 `#000000`으로 펼친다 */
const full = (hex: string) => (/^#[0-9a-f]{3}$/.test(hex) ? `#${[...hex.slice(1)].map((c) => c + c).join("")}` : hex);

/** WCAG 상대 휘도 대비비 */
function luminance(hex: string): number {
  const v = [1, 3, 5].map((i) => parseInt(full(hex).slice(i, i + 2), 16) / 255);
  const [r, g, b] = v.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// 글자 대비 쌍(글자 토큰, 바탕 토큰). 화면 부품이 실제로 올리는 조합이다(FE-12-02 ③, 보고 fe12-design §2·§3)
const TEXT_PAIRS: [string, string][] = [
  ["ink", "bg"], ["ink", "bg-soft"], ["ink", "bg-softer"], ["ink", "tint"], ["ink", "fixed"], ["ink", "bubble-me"],
  ["ink-2", "bg"], ["ink-2", "bg-soft"], ["ink-2", "bg-softer"], ["ink-2", "tint"], ["ink-2", "fixed"], ["ink-2", "yellow-2"],
  ["mute", "bg"], ["mute", "bg-soft"], ["mute", "bg-softer"], ["mute", "fixed"],
  ["link", "bg"], ["link", "bg-soft"],
  ["red-ink", "bg"], ["red-ink", "bg-soft"], ["red-ink", "bg-softer"], ["red-ink", "tint"], ["red-ink", "combo-bg"],
  ["on-solid", "red"], ["on-solid", "preg"], ["on-yellow", "yellow"],
  ["warn-ink", "warn-bg"], ["blue-ink", "blue-bg"], ["ok-ink", "bg"], ["blue-ink", "bg"], ["preg-ink", "preg-bg"], ["capsule-blue-ink", "capsule-blue"],
  ["bg", "ink"],
];
// 비글자 쌍(3:1 이상): 캡슐 테두리와 바탕. 안전 고지 띠 테두리는 다크에서만 그린다(라이트에서는 바탕과 같은 색이라 안 보인다)
// 프로필 폼 진행바 막대(FE-17 U-07): 마친 필수 단계(ok-ink)·선택 단계(blue-ink)는 바탕과 3:1 이상
const NON_TEXT_PAIRS: [string, string][] = [["capsule-line", "bg"], ["ok-ink", "bg"], ["blue-ink", "bg"]];
const DARK_ONLY_NON_TEXT_PAIRS: [string, string][] = [["fixed-edge", "fixed"]];

describe("디자인 토큰", () => {
  it("색 토큰 41개와 --font-sans가 @theme에 있다(FE-12: 짙은 바탕 글자·스크림·고지 띠 테두리 4개, 2026-11-23: 프로필 병아리 배경 8색·진행바 마친 단계 1색)", () => {
    expect(Object.keys(light)).toHaveLength(41);
    expect(light["--color-capsule-line"]).toBe("#4e3a2c");
    expect(light["--color-capsule-blue"]).toBe("#c9daec");
    expect(light["--color-capsule-blue-ink"]).toBe("#1f3a5f");
    expect(css).toMatch(/--font-sans:/);
  });

  it("모든 토큰에 다크 값이 있다: 시스템 분기와 data-theme 분기의 값이 같다", () => {
    for (const name of Object.keys(light)) {
      expect(darkMedia[name], `${name} 시스템 다크`).toBeDefined();
      expect(darkAttr[name], `${name} 수동 다크`).toBeDefined();
      expect(darkAttr[name]).toBe(darkMedia[name]);
    }
    expect(Object.keys(darkMedia).sort()).toEqual(Object.keys(light).sort());
  });

  it("다크 값은 라이트와 다르다(바탕·글자 토큰만 본다: 같은 값이면 다크가 빠진 것이다)", () => {
    for (const name of ["--color-bg", "--color-ink", "--color-bg-soft", "--color-line"]) expect(darkAttr[name]).not.toBe(light[name]);
  });

  it.each([
    ["라이트", light],
    ["다크", darkAttr],
  ])("%s: 글자 조합이 4.5:1 이상이다", (_, vars) => {
    const failed = TEXT_PAIRS.filter(([fg, bg]) => contrast(vars[`--color-${fg}`], vars[`--color-${bg}`]) < 4.5).map(([fg, bg]) => `${fg}/${bg}`);
    expect(failed).toEqual([]);
  });

  it.each([
    ["라이트", light],
    ["다크", darkAttr],
  ])("%s: 비글자 조합(캡슐 테두리)이 3:1 이상이다", (_, vars) => {
    const failed = NON_TEXT_PAIRS.filter(([fg, bg]) => contrast(vars[`--color-${fg}`], vars[`--color-${bg}`]) < 3).map(([fg, bg]) => `${fg}/${bg}`);
    expect(failed).toEqual([]);
  });

  // 입력창 임신 여부 토글(GROUP-01 5a, PregnancyToggle.tsx): 고른 칸 on-yellow/yellow, 안 고른 칸 mute/bg-soft
  it.each([
    ["라이트", light],
    ["다크", darkAttr],
  ])("%s: 임신 여부 토글의 고른 칸·안 고른 칸 글자가 4.5:1 이상이고, 고른 칸은 ink가 아니라 on-yellow를 쓴다", (_, vars) => {
    const pair = (fg: string, bg: string) => contrast(vars[`--color-${fg}`], vars[`--color-${bg}`]);
    expect(pair("on-yellow", "yellow")).toBeGreaterThanOrEqual(4.5);
    expect(pair("mute", "bg-soft")).toBeGreaterThanOrEqual(4.5);
  });
  it("다크: 노랑 바탕에 ink 글자를 올리면 안 보인다(토글이 on-yellow를 써야 하는 이유)", () => {
    expect(contrast(darkAttr["--color-ink"], darkAttr["--color-yellow"])).toBeLessThan(4.5);
  });

  it("다크: 안전 고지 띠 테두리가 바탕과 구분된다(3:1 이상)", () => {
    const failed = DARK_ONLY_NON_TEXT_PAIRS.filter(([fg, bg]) => contrast(darkAttr[`--color-${fg}`], darkAttr[`--color-${bg}`]) < 3).map(([fg, bg]) => `${fg}/${bg}`);
    expect(failed).toEqual([]);
  });

  // 프로필 병아리 배경 8색(2026-11-23): 병아리가 바탕 위에서 보여야 한다(비글자 3:1). 라이트는 갈색 윤곽, 다크는 노랑 몸통이 기준이다
  // (그림 `public/brand/face.png`에서 뽑은 색: 윤곽 #412519, 몸통 #FEE26E). 8색은 서로 다른 값이다(색으로 사람을 구분한다)
  const AVATAR_KEYS = ["yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray"];
  const CHICK_OUTLINE = "#412519";
  const CHICK_FILL = "#fee26e";
  it.each([
    ["라이트", light, CHICK_OUTLINE],
    ["다크", darkAttr, CHICK_FILL],
  ])("%s: 프로필 배경 8색 위에서 병아리가 3:1 이상으로 보이고 8색이 모두 다르다", (_, vars, chick) => {
    const colors = AVATAR_KEYS.map((key) => vars[`--color-avatar-${key}`]);
    expect(colors.every((color) => typeof color === "string")).toBe(true);
    expect(new Set(colors).size).toBe(8);
    const failed = AVATAR_KEYS.filter((key) => contrast(chick, vars[`--color-avatar-${key}`]) < 3);
    expect(failed).toEqual([]);
  });
});
