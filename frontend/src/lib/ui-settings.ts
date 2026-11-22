// UI 설정만 localStorage에 저장한다(FE-01-08 A). 질문·대화·응답은 저장하지 않는다.
// localStorage·sessionStorage는 이 파일에서만 허용(eslint.config.mjs).
const PREFIX = "ppiyak:ui:";

export function readUiSetting(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function writeUiSetting(key: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + key, value);
  } catch {
    /* 저장 실패는 무시 */
  }
}

export function removeUiSetting(key: string): void {
  try {
    window.localStorage.removeItem(PREFIX + key);
  } catch {
    /* 지우기 실패는 무시 */
  }
}
