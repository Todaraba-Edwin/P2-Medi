// 채팅 화면에서 프런트가 쓰는 UI 글자는 이 파일 한 곳에 둔다. 줄마다 근거를 적는다.
// 고정 안내·판정·119 문구는 여기 두지 않는다(백엔드 값을 받은 그대로 쓴다. S1).
// "디자인 반영본"은 2026-11-12 after5 스냅샷(프로토타입 모바일·데스크톱)의 글자다.
import { BRAND_NAME } from "@/components/brand/name";
import type { ProgressStage } from "@/lib/api";

/** 표시 이름(PRD-06-01: 화면에는 Can I PPiyak, 한글 삐약 병기) */
export const APP_NAME = BRAND_NAME;
export const APP_NAME_KO = "삐약";

/** 시작 화면 한 줄 소개(PJ2-PRD.md 15.4 시작·질문 입력 행, 디자인 반영본 홈 히어로) */
export const HERO_TAGLINE = "함께 먹으면 안 되는 약인지 확인해요";

/** 예시 질문 머리글(PJ2-PRD.md 15.4 시작 행 "예시 질문", 디자인 반영본) */
export const EXAMPLES_HEADING = "이렇게 물어보세요";

/** 예시 질문(PJ2-PRD.md 15.4 시작 행 "예시 질문", 디자인 반영본 홈 칩 3개 그대로) */
export const EXAMPLE_QUESTIONS: readonly string[] = [
  "타이레놀정500 먹고 이부프로펜도 먹어도 돼요?",
  "임신 중인데 열이 나요. 집에 타이레놀정500이랑 콜드-에스가 있는데 먹어도 되나요?",
  "엄마가 이지렉트정 드시는데 감기약 같이 드려도 돼요?",
];

/** 입력창 라벨(PJ2-PRD.md 15.4 "시작·질문 입력" 상태 이름, 화면에는 보이지 않고 보조기기가 읽는다) */
export const INPUT_LABEL = "질문 입력";
/** 입력창 안내 글자(디자인 반영본 입력창) */
export const INPUT_PLACEHOLDER = "삐약에게 물어보기";
/** 전송 버튼 이름(디자인 반영본 입력창) */
export const SEND_LABEL = "보내기";
/**
 * 입력창 아래 고지(PRD-17-07 A, 2026-11-19 원문 승인. PRD-17-03 A: 게스트 포함, 어디에 저장하지 않는지(이 탭)와 외부 전송을 한 번에 말한다).
 * 안내이지 동의 관문이 아니다: 체크·버튼이 없고 질문을 막지 않는다. 사이드바의 긴 저장 안내는 PRD-17-08 A로 지우고 이 한 줄로 대체했다.
 * 마지막 문장은 원문 승인(2026-11-22, PRD-17-10 후속, RFP-24-01 요소 보강): 전송 대상에 "선택한 프로필 값"을, 제공자 정책에 따른 보관 가능성을 더했다.
 */
export const INPUT_NOTICE = "질문은 이 탭에만 있고 저장하지 않아요. 새로고침하거나 탭을 닫으면 사라져요. 답변을 만들기 위해 질문과 선택한 프로필 값은 외부 AI(OpenAI)로 전송되며, 제공자 정책에 따라 일정 기간 보관될 수 있어요.";

/**
 * 입력창 안 왼쪽의 임신 여부 선택(tickets/frontend/FE-11.md §7.1 최종 디자인 `Rdd-Toggle`, 2026-11-20). 묶음 이름(aria-label)과 두 칸 글자.
 * 원문 승인(FE-11-11 A, 2026-11-20): "임신 여부"·"일반인"·"임산부". 기본값은 "일반인"이고 값은 요청 `context.pregnant`(일반인 false·임산부 true, FE-11-12 A)
 */
export const PREGNANCY_TOGGLE_LABEL = "임신 여부";
export const PREGNANCY_OPTION_GENERAL = "일반인";
export const PREGNANCY_OPTION_PREGNANT = "임산부";
/**
 * 건강 정보 동의가 없거나 게스트일 때 토글을 바꾸면 그 근처에 보이는 한 줄(FE-11-14 A, 2026-11-20): 이 대화에만 적용하고 프로필에 저장하지 않는다.
 * 원문 승인(2026-11-20, FE-11-14 A): 티켓 결정의 예시 문구 그대로 사용자가 승인했다
 */
export const PREGNANCY_SAVE_CONSENT_HINT = "프로필에 저장하려면 건강 정보 동의가 필요해요";

/** 진행 표시 영역 이름(PJ2-PRD.md 15.4 로딩 행 "진행 상태", NFR-06) */
export const PROGRESS_LABEL = "진행 상태";
/** 진행 문구 세 가지(PJ2-PRD.md 15.4 로딩 행: 약 찾는 중·금기 확인 중·근거 찾는 중). 이벤트에 label이 오면 그 값을 쓴다 */
export const STAGE_LABELS: Record<ProgressStage, string> = {
  drug_lookup: "약 찾는 중",
  contraindication_check: "금기 확인 중",
  evidence_search: "근거 찾는 중",
};

/** 오류 제목(디자인 반영본 오류 카드. PJ2-프론트-기술스택.md 4장 (3) "오류 상태를 보인다") */
export const ERROR_TITLE = "답을 만들지 못했어요";
/** 오류 본문: 다시 시도할 수 있을 때(디자인 반영본 오류 카드). 서버가 오류 문구를 보내면 그 값을 대신 쓴다 */
export const ERROR_BODY_RETRY = "잠시 뒤 다시 시도해 주세요. 보낸 질문은 그대로 있어요.";
/** 오류 본문: 다시 보내도 같은 경우(4xx). 초안이다: 문서·디자인에 문구가 없어 승인이 필요하다 */
export const ERROR_BODY_NO_RETRY = "질문을 다시 적어 보내 주세요.";
/** 오류 본문: `/chat`이 아직 연결되지 않았을 때(501). 승인 문구 4-2 원문 그대로(tickets/agent/AG-08.md §5 승인 문구 표, 2026-11-12 0-E) */
export const ERROR_BODY_NOT_READY = "아직 준비 중이라 답을 드릴 수 없어요. 급하면 약국·약사에게 확인하세요.";
/** 다시 시도 버튼(디자인 반영본 오류 카드. 4장 (3) "다시 시도" 버튼) */
export const RETRY_LABEL = "다시 시도";

/** 여는 화면 이름(디자인 반영본 스플래시) */
export const SPLASH_LABEL = "Can I PPiyak 여는 중 · 누르면 바로 시작";

/** 119 전화 링크 주소(S2: href="tel:119"). 글자가 아니라 주소다 */
export const EMERGENCY_TEL_HREF = "tel:119";
/** 119 전화 링크에 보이는 번호(문장이 아니라 번호만 둔다. 배너 문구는 응답 값이고 배너 부품은 FE-IMPL-05가 만든다) */
export const EMERGENCY_TEL_TEXT = "119";
