// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER, START_EMERGENCY_119, START_EXTERNAL_AI_NOTICE, NOTICE_API_FAIL),
//       backend/app/tools/provenance.py (FLAG_NOTES[API_FAIL·API_PAIR_INCOMPLETE], API_REASON_NOTES → API_FLAG_NOTES)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답을 받지 못한 화면뿐이다(f5 A, FE-01-19 A). 응답이 있으면 응답 값을 쓴다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내(질문을 보내기 전)
// - NOTICE_API_FAIL·API_FLAG_NOTES: 화면에 그리지 않는다. 응답의 `notice`·`findings[].notes[]`가 이 글자이면 본문이 아니라 근거 상세에만
//   둔다(FE-11-10 A "고지 배치는 화면 몫", `features/result/realtime-notice.ts`). 응답 글자가 바뀌면 이 값도 다시 만든다
export const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";
export const DISCLAIMER = "공공데이터 기반 정보 제공이며 진단·처방이 아님 · 금기 목록에 없다는 것이 안전하다는 뜻이 아님 · 요양기관의 DUR 점검을 대체하지 않음";
export const START_EMERGENCY_119 = "응급 상황이면 지금 바로 119에 전화하세요.";
export const START_EXTERNAL_AI_NOTICE = "질문과 입력한 프로필은 답을 만들기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 질문 내용을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
export const NOTICE_API_FAIL = "실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.";
export const API_FLAG_NOTES: readonly string[] = [
  "실시간 확인을 하지 못함(파일 기준 결과는 그대로예요)",
  "실시간 확인을 하지 못함(쌍의 한쪽 조회가 빠졌어요)",
  "실시간 확인을 하지 못함(이 성분은 실시간 조회에 쓸 코드가 없어요. 파일 기준 결과는 그대로예요)",
  "실시간 확인을 하지 못함(쌍의 한쪽 조회에 실패했어요. 파일 기준 결과는 그대로예요)",
  "실시간 확인을 일부만 함(성분이 많아 일부 성분만 조회했어요. 파일 기준 결과는 그대로예요)"
];
