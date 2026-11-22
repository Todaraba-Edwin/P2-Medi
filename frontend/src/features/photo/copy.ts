// 사진 입력 화면(FE-05, 사진 부분만. 음성은 AG-10-09 A로 축소)에서 프런트가 쓰는 UI 글자는 이 파일 한 곳에 둔다. 줄마다 근거를 적는다.
// 고정 안내·판정·119 문구는 여기 두지 않는다(서버 값을 받은 그대로 쓴다. 사진 응답의 `emergency`도 서버 상수 그대로다).
// P1~P9는 계획 보고(로컬 `data/mock/briefs/reports/photo-ag15-plan.md` §5 표)의 초안을 **원문 승인(2026-11-22, 사용자 "P1~P9 승인")**한 글자 그대로다.
// 보조기기 전용 이름(화면에 보이지 않는 라벨)은 아래 "자리표시" 절에 따로 두고, 보이는 새 글자를 더할 때는 승인을 받는다.

// ---------------------------------------------------------------- 승인 문구 P1~P9(원문 승인 2026-11-22)
/** P1 개인정보 가림 안내: 사진 고르기 위에 접히지 않게 둔다(PJ2-PRD.md 15.4 "개인정보 가림 안내" 행, PRD-08-04 A) */
export const PHOTO_PRIVACY_NOTICE = "환자 이름·병원·약국은 가리고 찍어도 돼요. 사진은 저장하지 않아요.";
/** P2 외부 AI 전송 고지(사진): 고지이지 동의 관문이 아니다(NFR-05, PRD-08-04 A). 제공자는 OpenAI 하나다 */
export const PHOTO_EXTERNAL_AI_NOTICE =
  "올린 사진은 약 이름을 읽기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 사진을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
/** P3 인식 중(15.4 "인식 중" 행 "약 이름을 읽는 중") */
export const PHOTO_READING = "사진에서 약 이름을 읽는 중이에요";
/** P4 인식 실패(`UNREADABLE`, 15.4 "인식 실패" 행) */
export const PHOTO_FAILED = "사진에서 약 이름을 읽지 못했어요. 다시 찍거나 약 이름을 글자로 입력해 주세요.";
/** P5 확인 카드 안내(확인 전 판정 없음, H19) */
export const PHOTO_CONFIRM_GUIDE = "사진에서 읽은 글자예요. 실제 약과 다를 수 있으니 봉투와 비교해 고치거나 지워 주세요. 확인을 누르기 전에는 금기를 찾아보지 않아요.";
/** P6 사전 후보 안내(기본 선택 없음, PRD-08-06 A) */
export const PHOTO_CANDIDATES_GUIDE = "비슷한 이름의 약이에요. 맞는 약이 있으면 골라 주세요. 고르지 않으면 적힌 글자로 찾아봐요.";
/** P7 형식·크기 안내(JPEG·PNG, 서버 상한 8MB) */
export const PHOTO_FORMAT_NOTE = "JPG·PNG 사진만, 8MB까지 올릴 수 있어요.";
/** P8 상한 도달(`UNAVAILABLE`) */
export const PHOTO_UNAVAILABLE = "지금은 사진으로 약 이름을 읽을 수 없어요. 약 이름을 글자로 입력해 주세요.";
/** P9 버튼 글자 여섯 개 */
export const PHOTO_ENTRY_LABEL = "사진으로 약 이름 읽기";
export const PHOTO_RETAKE_LABEL = "다시 찍기";
export const PHOTO_TYPE_INSTEAD_LABEL = "글자로 입력";
export const PHOTO_ADD_DRUG_LABEL = "약 추가";
export const PHOTO_CONFIRM_LABEL = "이대로 확인";
/** `닫기`는 승인 없이 버리는 동작이며 `/chat`을 부르지 않는다(PRD-13-03 A, H19). 계정 모달의 `CLOSE_LABEL`과 같은 글자다 */
export const PHOTO_CLOSE_LABEL = "닫기";

// ---------------------------------------------------------------- 공용 고지(원본은 계정 화면 copy. 두 화면이 한 상수를 쓴다)
/** 자료 밖 약 고지(FE-04-25 A, 원문 승인 2026-11-22). 원본은 `@/features/account/copy`의 `DRUG_DATA_SCOPE_NOTICE`이고 여기서는 다시 내보내기만 한다 */
export { DRUG_DATA_SCOPE_NOTICE } from "@/features/account/copy";

// ---------------------------------------------------------------- 자리표시(보조기기 전용 이름. 화면에 보이지 않는다. 승인 전)
/** 읽은 약 이름 입력칸의 이름(sr-only). 칸 자체는 읽은 글자로 채워져 보인다 */
export const PHOTO_READ_NAME_LABEL = "읽은 약 이름";
/** 약 목록 영역의 이름(보조기기용) */
export const PHOTO_DRUG_LIST_LABEL = "읽은 약 목록";
/** 항목 삭제 버튼의 이름: 글자는 계정 화면 `DELETE_LABEL`("삭제", 승인됨)과 같고 앞에 그 항목의 이름을 붙인다 */
export const photoDeleteRowLabel = (name: string) => `${name.trim() || "빈 항목"} 삭제`;
/** 질문 입력칸의 보이는 라벨. 입력창의 `INPUT_LABEL`("질문 입력")과 같은 글자다(보조기기가 읽는 이름이자 칸 위 작은 글자) */
export const PHOTO_QUESTION_LABEL = "질문 입력";
/** 후보 묶음의 이름(보조기기용, 결과 카드의 `CANDIDATES_LABEL`과 같은 글자) */
export const PHOTO_CANDIDATES_LABEL = "후보";
/** 인식 중 사진 미리보기의 대체 글자는 비운다(장식. 보조기기에는 P3이 읽힌다) */
export const PHOTO_PREVIEW_ALT = "";
