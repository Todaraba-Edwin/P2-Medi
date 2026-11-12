// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답(fixed_notice)을 받지 못한 오류 화면 하나뿐이다(f5 A). 응답이 있으면 응답 값을 쓴다.
export const FIXED_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요.";
export const DISCLAIMER = "공공데이터 기반 정보 제공이며 진단·처방이 아님 · 금기 목록에 없다는 것이 안전하다는 뜻이 아님 · 요양기관의 DUR 점검을 대체하지 않음";
