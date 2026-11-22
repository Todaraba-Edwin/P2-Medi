import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readUiSetting, removeUiSetting, writeUiSetting } from "@/lib/ui-settings";
import { applyThemeMode, parseThemeMode, readThemeMode, saveThemeMode } from "./theme";
import { THEME_BOOT_SCRIPT } from "./theme-boot";

// 화면 모드 저장·적용(FE-12-03 B, FE-12-04 A: 기기 브라우저 저장소만)
let systemDark = false;

function stubSystemTheme(dark: boolean) {
  systemDark = dark;
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("dark") && systemDark,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  removeUiSetting("theme");
  delete document.documentElement.dataset.theme;
  stubSystemTheme(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("화면 모드 저장", () => {
  it("저장값이 없거나 알 수 없으면 시스템이다(기본값)", () => {
    expect(parseThemeMode(null)).toBe("system");
    expect(parseThemeMode("blue")).toBe("system");
    expect(readThemeMode()).toBe("system");
  });

  it("고른 값을 ppiyak:ui:theme에 저장하고 data-theme에 건다", () => {
    saveThemeMode("dark");
    expect(readUiSetting("theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(readThemeMode()).toBe("dark");
    saveThemeMode("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("시스템을 고르면 지금의 기기 설정을 따른다", () => {
    stubSystemTheme(true);
    applyThemeMode("system");
    expect(document.documentElement.dataset.theme).toBe("dark");
    stubSystemTheme(false);
    applyThemeMode("system");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("첫 화면 전 적용 스크립트(깜빡임 방지, FE-12-02 ④)", () => {
  // 서버 HTML이 만든 뒤 인라인 스크립트가 data-theme를 정하는지 실제로 실행해 본다
  const runBoot = () => new Function(THEME_BOOT_SCRIPT)();

  it("저장값이 dark면 dark, 시스템이면 기기 설정을 따른다", () => {
    writeUiSetting("theme", "dark");
    runBoot();
    expect(document.documentElement.dataset.theme).toBe("dark");

    removeUiSetting("theme");
    stubSystemTheme(true);
    runBoot();
    expect(document.documentElement.dataset.theme).toBe("dark");
    stubSystemTheme(false);
    runBoot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("저장값이 light면 기기 설정이 어두워도 light다", () => {
    writeUiSetting("theme", "light");
    stubSystemTheme(true);
    runBoot();
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
