import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import * as button from "./button";
import { CHIP_CLASS } from "./chip";

// 버튼 호버 반응(사용자 지시 2026-11-19): 누를 수 있는 것은 마우스를 올리면 눈에 보이게 반응한다.
describe("버튼 공통 상수의 호버·누름 반응", () => {
  const classes = Object.entries(button);

  it("공통 버튼 상수마다 전환과 호버·누름 상태가 있고, 비활성 버튼에는 반응이 없다(enabled:)", () => {
    for (const name of ["PRIMARY_BUTTON", "SECONDARY_BUTTON", "TEXT_BUTTON", "DANGER_TEXT_BUTTON", "DANGER_BUTTON", "ICON_BUTTON", "SOCIAL_BUTTON"] as const) {
      const value = button[name];
      expect(value, name).toMatch(/(^| )transition-/);
      expect(value, name).toMatch(/(^| )enabled:hover:/);
      expect(value, name).toMatch(/(^| )enabled:active:/);
    }
    expect(CHIP_CLASS).toMatch(/(^| )enabled:hover:/);
    // 어느 상수에도 `enabled:` 없는 hover·active가 없다(비활성 버튼이 반응하지 않게)
    for (const [name, value] of classes) for (const token of value.split(" ")) if (/hover:|active:/.test(token)) expect(token, name).toMatch(/^(enabled:|group-enabled:)/);
  });

  it("주 버튼은 바탕이 진해지고 보조 버튼은 바탕·테두리가 바뀐다. 소셜 버튼은 로고 색을 건드리지 않고 그림자·밝기만 바뀐다", () => {
    expect(button.PRIMARY_BUTTON).toContain("enabled:hover:brightness-95");
    expect(button.SECONDARY_BUTTON).toContain("enabled:hover:bg-bg-soft");
    expect(button.SECONDARY_BUTTON).toContain("enabled:hover:border-faint");
    expect(button.TEXT_BUTTON).toContain("enabled:hover:bg-bg-soft");
    expect(button.SOCIAL_BUTTON).toContain("enabled:hover:shadow-md");
    expect(button.SOCIAL_BUTTON).not.toMatch(/hover:(bg|text|border)-/);
    // 초점 윤곽선(브라우저 기본 focus-visible)을 지우지 않는다
    for (const [name, value] of classes) expect(value, name).not.toMatch(/outline-none|outline-0/);
  });

  it("커서는 전역 스타일이 한 번에 준다: 누를 수 있으면 pointer, 비활성은 not-allowed", () => {
    const css = readFileSync(path.join(__dirname, "../styles/globals.css"), "utf8").replace(/\s+/g, " ");
    expect(css).toContain('@layer base { button:not(:disabled), [role="button"]:not([aria-disabled="true"]), a[href] { cursor: pointer; }');
    expect(css).toContain('button:disabled, [role="button"][aria-disabled="true"] { cursor: not-allowed; }');
  });
});
