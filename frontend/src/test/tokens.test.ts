import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.resolve(__dirname, "../styles/globals.css"), "utf8");

describe("디자인 토큰", () => {
  it("다크모드 변수·분기가 없다(FE-01-10 A)", () => {
    expect(css).not.toMatch(/prefers-color-scheme|\.dark\b|@custom-variant\s+dark/);
  });

  it("색 토큰 28개와 --font-sans가 @theme에 있다", () => {
    // 25개 + 이어 붙인 캡슐 표지 3개(FE-10-03 A: capsule-line·capsule-blue·capsule-blue-ink)
    expect(css.match(/--color-[a-z0-9-]+:/g)).toHaveLength(28);
    expect(css).toMatch(/--color-capsule-line: #4e3a2c;/);
    expect(css).toMatch(/--color-capsule-blue: #c9daec;/);
    expect(css).toMatch(/--color-capsule-blue-ink: #1f3a5f;/);
    expect(css).toMatch(/--font-sans:/);
  });
});
