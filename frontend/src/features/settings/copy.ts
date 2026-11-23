// 화면 모드와 계정 메뉴의 글자. 글자 8건은 사용자 승인(2026-11-20, tickets/frontend/FE-12.md §5 메모, 디자인 보고 fe12-design §4).
// 2026-11-23 계정 메뉴 팝오버 통합으로 별도 "설정" 화면이 없어져 `설정`·`계정 메뉴`·`프로필을 저장하려면 로그인하세요.`는 더 쓰지 않는다
// (승인 글자이나 미사용. 메뉴의 접근 가능한 이름은 Radix가 버튼 글자로 단다). 이 밖의 글자(닫기·로그인/가입·프로필 관리·로그아웃·계정·약관·정책)는
// 기존 계정 글자(features/account/copy.ts)를 그대로 쓴다.
import type { ThemeMode } from "@/lib/theme";

/** 계정 메뉴 안 "화면 모드" 묶음 제목 (승인) */
export const SCREEN_MODE_LABEL = "화면 모드";
/** 세 칸 선택지 (승인) */
export const THEME_LABELS: Readonly<Record<ThemeMode, string>> = {
  light: "밝은 모드",
  dark: "다크 모드",
  system: "시스템",
};
/** 시스템 칸 아래 작은 설명 (승인) */
export const SYSTEM_MODE_HINT = "기기 설정을 따라요";
