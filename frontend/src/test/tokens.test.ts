import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.resolve(__dirname, "../styles/globals.css"), "utf8");

describe("디자인 토큰", () => {
  it("다크모드 변수·분기가 없다(FE-01-10 A)", () => {
    expect(css).not.toMatch(/prefers-color-scheme|\.dark\b|@custom-variant\s+dark/);
  });

  it("색 토큰 25개와 --font-sans가 @theme에 있다", () => {
    expect(css.match(/--color-[a-z0-9-]+:/g)).toHaveLength(25);
    expect(css).toMatch(/--font-sans:/);
  });
});
