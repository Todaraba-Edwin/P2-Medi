// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER, START_EMERGENCY_119, START_EXTERNAL_AI_NOTICE)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답을 받지 못한 화면뿐이다(f5 A, FE-01-19 A). 응답이 있으면 응답 값을 쓴다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내(질문을 보내기 전)
export const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";
export const DISCLAIMER = "공공데이터 기반 정보 제공이며 진단·처방이 아님 · 금기 목록에 없다는 것이 안전하다는 뜻이 아님 · 요양기관의 DUR 점검을 대체하지 않음";
export const START_EMERGENCY_119 = "응급 상황이면 지금 바로 119에 전화하세요.";
export const START_EXTERNAL_AI_NOTICE = "질문과 입력한 프로필은 답을 만들기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 질문 내용을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
