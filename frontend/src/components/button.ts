/**
 * 버튼의 공통 모양과 호버·누름 반응(사용자 지시 2026-11-19: 마우스를 올렸을 때 눈에 보이게 반응해야 누를 수 있는 것임을 안다).
 * - 커서(pointer·not-allowed)는 `src/styles/globals.css`의 `@layer base`가 한 번에 준다
 * - 호버·누름은 여기 상수에만 둔다. 화면 부품은 이 상수를 쓰고 `hover:`를 따로 흩어 쓰지 않는다
 * - 비활성 버튼은 반응하지 않는다(`enabled:`). 초점 표시(브라우저 기본 `focus-visible` 윤곽선)는 건드리지 않는다
 * - 색은 기존 토큰만 쓴다(토큰을 더하지 않는다). 노랑보다 진한 토큰이 없어 주 버튼은 밝기(`brightness`)로 한 단계씩 진하게 한다
 */

/** 주 버튼(노랑 바탕): 바탕이 한 단계씩 진해진다 */
export const HOVER_PRIMARY = "transition-[filter] enabled:hover:brightness-95 enabled:active:brightness-90";
/** 보조 버튼(테두리): 바탕이 옅은 노랑이 되고 테두리가 진해진다 */
export const HOVER_SECONDARY = "transition-colors enabled:hover:border-faint enabled:hover:bg-bg-soft enabled:active:bg-tint";
/** 글자 버튼·목록 줄: 바탕이 깔린다 */
export const HOVER_TEXT = "transition-colors enabled:hover:bg-bg-soft enabled:active:bg-tint";
/** 옅은 노랑 바탕 위의 줄·아이콘 버튼(사이드바·패널 머리) */
export const HOVER_ROW = "transition-colors enabled:hover:bg-tint enabled:active:bg-yellow-2";
/** 빨강 글자 버튼(탈퇴) */
export const HOVER_TEXT_DANGER = "transition-colors enabled:hover:bg-combo-bg enabled:active:bg-combo-bg";
/** 빨강 바탕 버튼(삭제·탈퇴·철회 확인) */
export const HOVER_DANGER = "transition-[filter] enabled:hover:brightness-95 enabled:active:brightness-90";
/** 칩(예시 질문·동작 칩) */
export const HOVER_CHIP = "transition-colors enabled:hover:border-line-2 enabled:hover:bg-bg-soft enabled:active:bg-tint";
/** 회사가 바탕색을 정한 소셜 로그인 버튼: 바탕·글자·로고 색은 바꾸지 않고 그림자·밝기만 조금 바뀐다 */
export const HOVER_SOCIAL = "transition-[box-shadow,filter] enabled:hover:shadow-md enabled:hover:brightness-95 enabled:active:brightness-90";
/** 누르는 영역(버튼)보다 보이는 면(안쪽 요소)이 작은 버튼: 버튼에 `group`을 주고 안쪽 요소에 붙인다 */
export const HOVER_INNER_PRIMARY = "transition-[filter] group-enabled:group-hover:brightness-95 group-enabled:group-active:brightness-90";
export const HOVER_INNER_TEXT = "transition-colors group-enabled:group-hover:bg-bg-soft group-enabled:group-active:bg-tint";

export const PRIMARY_BUTTON = `min-h-11 rounded-full bg-yellow px-4 text-sm font-bold text-on-yellow disabled:bg-line disabled:text-faint ${HOVER_PRIMARY}`;
export const SECONDARY_BUTTON = `min-h-11 rounded-full border border-line-2 bg-bg px-4 text-sm font-bold text-ink-2 disabled:text-faint ${HOVER_SECONDARY}`;
export const TEXT_BUTTON = `min-h-11 rounded-full px-3 text-sm font-bold text-link disabled:text-faint ${HOVER_TEXT}`;
export const DANGER_TEXT_BUTTON = `min-h-11 rounded-full px-3 text-sm font-bold text-red-ink ${HOVER_TEXT_DANGER}`;
export const DANGER_BUTTON = `min-h-11 rounded-full bg-red px-3 text-sm font-bold text-on-solid disabled:opacity-60 ${HOVER_DANGER}`;
/** 아이콘만 있는 둥근 버튼(닫기·지우기). 누르는 영역 44×44 */
export const ICON_BUTTON = `grid size-11 flex-none place-items-center rounded-full ${HOVER_ROW}`;
/** 소셜 로그인 버튼: 가로로 꽉 찬 "로고 + 글자" 버튼(높이 48px, 모서리 12px). 바탕·테두리·글자 색은 회사 가이드 값이라 쓰는 곳이 준다. 처리 중에는 흐려진다 */
export const SOCIAL_BUTTON = `flex min-h-12 w-full items-center justify-center rounded-xl px-4 text-sm font-bold disabled:opacity-50 ${HOVER_SOCIAL}`;
