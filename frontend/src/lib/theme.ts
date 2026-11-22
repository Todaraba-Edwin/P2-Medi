// 화면 모드(밝은·다크·시스템)를 기기 브라우저 저장소에만 둔다(FE-12-04 A: 서버 저장 없음, 질문·대화는 저장하지 않는다).
// 저장 키는 UI 설정 접두(`ppiyak:ui:`, `ui-settings.ts`)를 쓴다. 첫 화면을 그리기 전 적용은 `theme-boot.ts`가 같은 규칙으로 한다.
import { readUiSetting, writeUiSetting } from "./ui-settings";

export const THEME_KEY = "theme";
export const THEME_MODES = ["light", "dark", "system"] as const;
export type ThemeMode = (typeof THEME_MODES)[number];

/** 저장값이 없거나 알 수 없는 값이면 "시스템"이다(FE-12-03 B: 기본은 시스템) */
export function parseThemeMode(value: string | null): ThemeMode {
  return value === "light" || value === "dark" ? value : "system";
}

export function readThemeMode(): ThemeMode {
  return parseThemeMode(readUiSetting(THEME_KEY));
}

/** 선택한 모드를 `<html data-theme>`에 건다. "시스템"은 지금의 기기 설정을 따라 `light`·`dark`로 정한다 */
export function applyThemeMode(mode: ThemeMode): void {
  const dark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = mode === "system" ? (dark ? "dark" : "light") : mode;
}

export function saveThemeMode(mode: ThemeMode): void {
  writeUiSetting(THEME_KEY, mode);
  applyThemeMode(mode);
}
