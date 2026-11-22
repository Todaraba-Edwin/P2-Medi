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
// 사이드바의 긴 저장 안내("대화는 이 화면에만 있고 저장하지 않아요. …")는 PRD-17-08 A(2026-11-19)로 삭제했다.
// 같은 말은 입력창 아래 고지(`features/chat/copy.ts` INPUT_NOTICE, PRD-17-07 A) 한 곳에서만 한다.
/** 머리줄의 짧은 안내(디자인 반영본 머리줄 "대화는 저장하지 않아요". PRD-17-08 A: 유지) */
export const NOT_SAVED_SHORT = "대화는 저장하지 않아요";

/**
 * 합성 데이터 데모 표시(BE-13-07 A, 원문 승인 2026-11-22). **목(MSW) 모드(`NEXT_PUBLIC_API_MOCKING=enabled`)일 때만** 머리줄 아래 한 줄로 보이고
 * 실서버 모드에서는 그리지 않는다. 마스코트 없음, 색은 토큰만. 글자는 이 상수 한 곳이다.
 */
export const SYNTHETIC_DEMO_NOTICE = "합성 데이터 데모예요. 화면의 약 이름·판정은 실제 의약품 정보가 아니에요.";

/**
 * 되묻기에서 고른 후보로 다시 묻는 버튼. **초안이다(승인 필요)**: 디자인 반영본에 재전송 버튼이 없다.
 * 근거: PJ2-PRD.md 15.3 (4) 3행 "선택값으로 같은 질문을 다시 보냄", 지시서 G-4 "재전송은 별도 조작".
 */
export const RESEND_WITH_PICK_LABEL = "이 약으로 다시 묻기";

/**
 * 되묻는 약 이름이 둘 이상일 때의 확인 버튼(FE-09-01 A "모두 고르면 '이 약들로 확인하기' 활성화"). 묶음이 하나면 위 글자를 그대로 쓴다.
 */
export const RESEND_WITH_PICKS_LABEL = "이 약들로 확인하기";

/**
 * 아직 고르지 않은 묶음 수 안내(FE-09-01 A, 확인 버튼이 비활성일 때). 원문 승인(FE-09-10 A, 2026-11-19).
 */
export const remainingPicksHint = (count: number) => `${count}개 더 골라 주세요`;

/** 마지막 한글 글자에 받침이 있고 ㄹ이 아니면 "으로", 아니면 "로"(한글이 없으면 "로") */
function directionJosa(word: string): string {
  for (let index = word.length - 1; index >= 0; index -= 1) {
    const code = word.charCodeAt(index);
    if (code < 0xac00 || code > 0xd7a3) continue;
    const batchim = (code - 0xac00) % 28;
    return batchim !== 0 && batchim !== 8 ? "으로" : "로";
  }
  return "로";
}

/**
 * 고른 약으로 다시 물을 때 내 말풍선에 보일 표시용 글자(FE-09-04 A "고른 약: A, B로 다시 확인"). 약 이름은 고른 제품명(응답 값) 그대로다.
 * 서버로는 이 글자가 아니라 원 질문을 보낸다.
 */
export const resendBubbleText = (names: readonly string[]) => {
  const joined = names.join(", ");
  return `고른 약: ${joined}${directionJosa(joined)} 다시 확인`;
};
