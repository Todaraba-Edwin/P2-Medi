// 결과 카드에서 프런트가 쓰는 UI 글자는 이 파일 한 곳에 둔다. 줄마다 근거를 적는다.
// 판정·배지·성분 상태·안내 문구는 여기 두지 않는다(응답 값을 받은 그대로 그린다, S1).

/** 결과 카드 머리글(tickets/doc/PRD-09.md §7.1 "금기 확인 결과 · 임신 기준"의 앞부분). 뒤의 기준 글자는 조립하는 쪽이 준다 */
export const RESULT_HEADING = "금기 확인 결과";

/** 성분 칩 줄의 머리 글자(PRD-09 §7.1 "주성분 [표시명 · 상태] …") */
export const INGREDIENTS_LABEL = "주성분";

/** 성분이 5개 이상일 때 접힌 나머지를 여는 칩(FE-02 완료 조건 PRD-09-05, 디자인 반영본 "외 N개"). 개수만 넣는다 */
export const moreIngredientsLabel = (count: number) => `외 ${count}개`;

/** 되묻기 후보 목록의 이름(PJ2-PRD.md 15.4 되묻기 카드 행 "후보 표". 화면에 안 보이고 보조기기가 읽는다) */
export const CANDIDATES_LABEL = "후보";

/** 후보에 찾는 약이 없을 때의 동작 버튼(디자인 반영본 되묻기 보드) */
export const CANDIDATE_OTHER_LABEL = "목록에 없어요 · 직접 입력";

/** 고른 묶음을 한 줄로 접었을 때 다시 펼치는 버튼(FE-09-01 A "타이레놀 → 타이레놀정500밀리그람 · 바꾸기") */
export const CANDIDATE_CHANGE_LABEL = "바꾸기";

/** 접힌 한 줄에서 입력한 이름과 고른 제품 사이의 표시(FE-09-01 A). 보조기기에는 읽히지 않게 그린다 */
export const CANDIDATE_PICKED_ARROW = "→";

/** 다른 묶음에서 이미 고른 제품이라 이 묶음에서 고를 수 없는 이유(FE-09-03 A). 원문 승인(FE-09-10 A, 2026-11-19) */
export const CANDIDATE_TAKEN_NOTE = "다른 약으로 이미 골랐어요";

/**
 * 묶음 머리 오른쪽의 후보 수(FE-10 디자인 "FE-09 r2" `.gh small` "제품 4개"). 개수만 넣는다. **초안이다(승인 필요)**
 */
export const candidateCountLabel = (count: number) => `제품 ${count}개`;

/**
 * 확인 줄 캡슐에서 아직 고르지 않은 칸의 글자(FE-10 디자인 "FE-09 r2" `.cell.empty` "A 고르기 전"). 묶음 표지 글자만 넣는다. **초안이다(승인 필요)**
 */
export const pickPendingLabel = (letter: string) => `${letter} 고르기 전`;

/** 약을 찾지 못한 결과 카드 아래의 동작 칩(tickets/doc/PRD-14.md §5.4 PRD-14-03 A "이름 다시 입력", 1차). 누르면 입력창으로 간다 */
export const RETRY_NAME_LABEL = "이름 다시 입력";

/**
 * 임신 여부를 "일반인"으로 두고 받은 결과 아래의 작은 한 줄(FE-11-03 A, 2026-11-20): 임부금기는 확인하지 않았음을 알린다(안전 방향).
 * 서버는 임신 여부 선택 상태를 모르므로 화면이 둔다. 원문 승인(FE-11-11 A, FE-11-03이 A일 때 같은 승인에 포함)
 */
export const PREGNANCY_PICK_HINT = "임부금기는 '임산부'를 고르면 확인해요";
