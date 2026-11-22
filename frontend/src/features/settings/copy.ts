// 설정 화면과 계정 메뉴의 글자. 새 글자 8건은 사용자 승인(2026-11-20, tickets/frontend/FE-12.md §5 메모, 디자인 보고 fe12-design §4).
// 이 밖의 글자(닫기·로그인/가입·프로필 관리·로그아웃·계정)는 기존 계정 글자(features/account/copy.ts)를 그대로 쓴다.
import type { ThemeMode } from "@/lib/theme";

/** 사이드바 계정 메뉴 항목·게스트 설정 줄·설정 화면 제목 (승인) */
export const SETTINGS_LABEL = "설정";
/** 계정 줄 메뉴 묶음의 이름(보조기기용, 승인) */
export const ACCOUNT_MENU_LABEL = "계정 메뉴";
/** 설정 화면의 "화면 모드" 묶음 제목·radiogroup 이름 (승인) */
export const SCREEN_MODE_LABEL = "화면 모드";
/** 세 칸 선택지 (승인) */
export const THEME_LABELS: Readonly<Record<ThemeMode, string>> = {
  light: "밝은 모드",
  dark: "다크 모드",
  system: "시스템",
};
/** 시스템 칸 아래 작은 설명 (승인) */
export const SYSTEM_MODE_HINT = "기기 설정을 따라요";
/** 게스트의 설정 화면 계정 묶음 두 번째 문장 (승인). 앞 문장 "로그인하지 않아도 모든 질문을 할 수 있어요."는 기존 글자다 */
export const GUEST_SAVE_NOTICE = "프로필을 저장하려면 로그인하세요.";
