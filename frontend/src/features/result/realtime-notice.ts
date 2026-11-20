// 실시간 확인 문장의 배치(FE-11-10 A, 2026-11-20 사용자 정책 "'실시간 확인을 하지 못함' 중복 정보는 근거 상세로 제한").
// 응답 계약·서버·평가는 그대로다: 서버가 `notice`에 `NOTICE_API_FAIL`을, 줄 `notes[]`에 `api_flag_note` 문구를 넣어 보내면
// 화면이 그 글자를 **본문에 그리지 않고 근거 상세에만** 둔다. 글자를 고치거나 조립하지 않으며, 어느 글자인지는 생성 상수
// (`lib/fixed/phrases.generated`, 백엔드 원문)와 같은지로만 가린다. "화면은 줄을 조합·재정렬하지 않는다"(FE-11-04 A)의 예외로
// "고지 배치는 화면 몫"을 여기 적어 둔다.
import type { ChatResponse, Finding } from "@/lib/api";
import { API_FLAG_NOTES, NOTICE_API_FAIL } from "@/lib/fixed/phrases.generated";

/** 응답 `notice`가 공공 API 실패 배너(`NOTICE_API_FAIL`)인가. 상한 도달 같은 다른 배너는 본문에 그대로 남는다 */
export const isApiFailNotice = (notice: string | null): boolean => notice === NOTICE_API_FAIL;

/** 줄의 보조줄 한 개가 실시간 확인 꼬리표 노트(`provenance.api_flag_note`)인가 */
export const isApiFlagNote = (note: string): boolean => API_FLAG_NOTES.includes(note);

/** 줄의 보조줄에서 실시간 확인 노트를 뺀 나머지(본문용). 받은 순서는 그대로다 */
export const notesWithoutApiFlag = (finding: Pick<Finding, "notes">): string[] => finding.notes.filter((note) => !isApiFlagNote(note));

/** 이 결과에 실시간 확인을 하지 못한 자료가 있는가(배너 또는 줄 노트). 결과 카드 머리의 "기준일 자료" 표지를 켜는 조건이다 */
export const hasApiFailInfo = (response: Pick<ChatResponse, "notice" | "findings">): boolean =>
  isApiFailNotice(response.notice) || response.findings.some((finding) => finding.notes.some(isApiFlagNote));
