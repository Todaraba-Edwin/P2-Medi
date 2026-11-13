// 셸(사이드바·머리줄·조립)에서 프런트가 쓰는 UI 글자. 줄마다 근거를 적는다.
// 고정 안내·판정·119 문장은 여기 두지 않는다(응답 값 또는 백엔드 상수에서 생성한 값을 쓴다, S1).
// "디자인 반영본"은 2026-11-12 after5 스냅샷(프로토타입 번들·보드)의 글자다.

/** 사이드바 영역 이름(디자인 반영본 `aside aria-label="사이드바"`) */
export const SIDEBAR_LABEL = "사이드바";
/** 접힌 레일 영역 이름(디자인 반영본 `aria-label="접힌 사이드바"`) */
export const RAIL_LABEL = "접힌 사이드바";
/** 사이드바 토글(디자인 반영본 "사이드바 접기"·"사이드바 펼치기") */
export const SIDEBAR_COLLAPSE_LABEL = "사이드바 접기";
export const SIDEBAR_EXPAND_LABEL = "사이드바 펼치기";
/** 좁은 폭 ☰ 드로어(디자인 반영본 "메뉴 열기"·"메뉴 닫기", `nav aria-label="메뉴"`) */
export const MENU_LABEL = "메뉴";
export const MENU_OPEN_LABEL = "메뉴 열기";
export const MENU_CLOSE_LABEL = "메뉴 닫기";

/** 새 대화 버튼(디자인 반영본 사이드바 "새 질문") */
export const NEW_CHAT_LABEL = "새 질문";
/** 지금 대화 머리글과 빈 상태(디자인 반영본 사이드바) */
export const CURRENT_CHAT_HEADING = "지금 대화";
export const CURRENT_CHAT_EMPTY = "아직 질문이 없어요.";
/** 저장하지 않는다는 안내(디자인 반영본 사이드바. FE-01-08 A: 대화는 메모리에만 둔다) */
export const NOT_SAVED_NOTE = "대화는 이 화면에만 있고 저장하지 않아요. 새로고침하거나 닫으면 사라져요.";
/** 머리줄의 짧은 안내(디자인 반영본 머리줄 "대화는 저장하지 않아요") */
export const NOT_SAVED_SHORT = "대화는 저장하지 않아요";

/**
 * 되묻기에서 고른 후보로 다시 묻는 버튼. **초안이다(승인 필요)**: 디자인 반영본에 재전송 버튼이 없다.
 * 근거: PJ2-PRD.md 15.3 (4) 3행 "선택값으로 같은 질문을 다시 보냄", 지시서 G-4 "재전송은 별도 조작".
 */
export const RESEND_WITH_PICK_LABEL = "이 약으로 다시 묻기";
