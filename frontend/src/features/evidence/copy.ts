// 근거 상세에서 프런트가 쓰는 UI 글자(소제목·열 이름·버튼 이름). 줄마다 근거를 적는다.
// 판정·사유·미확보·권고·출처 종류 문구는 여기 두지 않는다(응답 값을 그대로 그린다, S1).

/** 패널 제목(FE-02 완료 조건 "근거 상세", 디자인 반영본) */
export const EVIDENCE_TITLE = "근거 상세";
/** 닫기 버튼 이름(디자인 반영본 근거 상세 보드 "닫기") */
export const CLOSE_LABEL = "닫기";

/**
 * 진입 버튼 글자(지시서 G-1: 시트면 "근거 상세 보기", 모달·패널이면 "근거 상세 열기". 이 둘뿐이고 "펼치기"는 쓰지 않는다).
 * 어느 배치인지는 조립하는 쪽(FE-IMPL-06)이 폭으로 정해 `mode`로 준다.
 */
export const ENTRY_LABELS = { sheet: "근거 상세 보기", panel: "근거 상세 열기" } as const;

/** 구역 소제목(tickets/doc/PRD-11.md §4.1 판정 → 사유 원문 → 허가사항 → 출처. PRD-10-03: 13자 이내 짧은 명사형) */
export const SECTION_TITLES = { judgment: "판정", reason: "사유 원문", label: "허가사항", sources: "출처" } as const;

/** 미식별 박스의 칸 이름(FE-02 완료 조건 PRD-14-01: 입력한 이름·찾아본 곳(건수)·못 찾은 이유·다음에 해 보세요) */
export const LOOKUP_LABELS = { input: "입력한 이름", searched: "찾아본 곳", why: "못 찾은 이유", next: "다음에 해 보세요" } as const;
/** 찾아본 곳의 건수 표기(PRD-14-01 "찾아본 곳(건수)", 디자인 반영본 "0건"). 숫자는 응답 값이다 */
export const countLabel = (count: number) => `${count}건`;

/** 출처 표 머리(tickets/doc/PRD-12.md §4.3 기관 머리줄 + 자료 행, 디자인 반영본 "출처 · 자료" / "기준일·고시일") */
export const SOURCE_HEADERS = { name: "출처 · 자료", dates: "기준일·고시일" } as const;
/** 출처 행의 덧붙임 칸 이름(BE-06-05 A: 고시 번호·판·쪽은 출처 행에 둔다. 값이 있을 때만 그린다) */
export const SOURCE_EXTRA_LABELS = { noticeNos: "고시 번호", edition: "판", pages: "쪽" } as const;

/** 허가사항 인용 머리(FE-02 완료 조건 PRD-10-04, 지시서 G-6: `{약 이름} 허가사항 원문({항목})`). 약 이름·항목은 응답 값이다 */
export const permitHeading = (drugName: string | null, section: string | null) =>
  `${drugName ? `${drugName} ` : ""}허가사항 원문${section ? `(${section})` : ""}`;
