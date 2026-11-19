// 계정(시작 선택·로그인·동의·프로필·대상 선택) 화면에서 프런트가 쓰는 UI 글자. 줄마다 근거를 적는다.
// 약관·개인정보·민감정보 문서의 제목·본문은 여기 두지 않는다(`GET /api/legal/*` 값을 그대로 그린다, 사용자 결정 2026-11-18).
// 고정 안내·판정·119 문장도 두지 않는다(S1). 문서·디자인에 원문이 없던 글자는 문구 검토에서 승인됐다(Recap 44, 2026-11-19).
// 그 뒤 로그인 연결(FE-04c)에서 생긴 안내·오류 문구 7줄은 FE-04-08 A(2026-11-19)로 승인됐다. 이메일 숨김(PRD-01-10 A) 문구 4줄만
// "승인 전(FE-04c)" 표시를 남겨 두고 이메일 로그인 재검토 때 다시 묻는다. 로그인 제목은 FE-04-17 A(2026-11-19) "간편 로그인"이다.
// 약관 문서 자체는 법률 검토 전이라 `LEGAL_NOT_REVIEWED_TAG` 표지는 그대로 붙인다.
import type { AgeBand, DrugMatchedBy, PregnancyStatus, Profile, Relation, SocialProvider } from "@/lib/api/account";

// ---------------------------------------------------------------- 시작 화면 진입(할 일 1)
/** 주 버튼(지시서 할 일 1, tickets/frontend/FE-04.md §2 "게스트로 시작") */
export const GUEST_START_LABEL = "게스트로 시작";
/** 보조 버튼(지시서 할 일 1 "로그인/가입") */
export const LOGIN_ENTRY_LABEL = "로그인/가입";
/** 진입 선택 영역 이름(보조기기용) */
export const ENTRY_GROUP_LABEL = "시작 방법";

// ---------------------------------------------------------------- 모달 코너 버튼(PRD-13-04 A)
/** `닫기`는 글자 그대로, `<`의 접근 가능한 이름은 `뒤로`(tickets/doc/PRD-13.md §4.6) */
export const CLOSE_LABEL = "닫기";
export const BACK_LABEL = "뒤로";

// ---------------------------------------------------------------- 로그인·가입(할 일 2)
/** 모달 제목·설명(tickets/doc/PRD-13.md §1 ISSUE-006 화면 글자) */
export const LOGIN_TITLE = "프로필을 저장하려면 로그인하세요";
export const LOGIN_DESCRIPTION = "나이·임신 여부·먹는 약을 저장해 두면 질문할 때 다시 적지 않아도 돼요. 로그인하지 않아도 모든 질문은 할 수 있어요.";
// PRD-01-10 A(2026-11-19): 이메일 로그인·가입은 화면에서 숨겼다. 아래 이메일 글자는 메일 인증을 갖춘 뒤 재검토할 때 다시 쓴다(지우지 않는다)
/** 폼 머리(ISSUE-006 "이메일로 로그인") */
export const EMAIL_LOGIN_HEADING = "이메일로 로그인";
export const EMAIL_LABEL = "이메일";
export const PASSWORD_LABEL = "비밀번호";
/** 버튼(ISSUE-006 "로그인"·"이메일로 가입하기"·"로그인 없이 계속하기") */
export const LOGIN_SUBMIT_LABEL = "로그인";
export const SIGNUP_ENTRY_LABEL = "이메일로 가입하기";
export const CONTINUE_AS_GUEST_LABEL = "로그인 없이 계속하기";
/** 가입 화면 제목·버튼 */
export const SIGNUP_TITLE = "이메일로 가입";
export const SIGNUP_SUBMIT_LABEL = "가입하기";
/** 소셜 로그인 묶음 이름(FE-04-17 A, 2026-11-19 원문 승인 "간편 로그인": 이메일을 숨겨 "다른 방법"이 맞지 않는다) */
export const SOCIAL_HEADING = "간편 로그인";
/**
 * 소셜 로그인 버튼의 보이는 글자(사용자 결정 2026-11-18: Google·Kakao, Apple 없음). 글자 앞에 공식 로고가 붙는다(FE-04e).
 * - Google: FE-04d 이전 글자 그대로. Google 가이드의 권장 문구 "Continue with Google"의 한국어 표현이다(현지화 허용)
 * - Kakao: 카카오 디자인 가이드가 레이블을 "카카오 로그인"(완성형)·"로그인"(축약형)으로만 두어 이전 글자 "카카오로 계속하기"를 쓰지 않는다. 승인 전(FE-04e)
 */
export const SOCIAL_LABELS: Readonly<Record<SocialProvider, string>> = {
  google: "Google로 계속하기",
  kakao: "카카오 로그인",
};
// Naver 버튼은 S2(연동 방식 확인 뒤)에서 다시 넣는다. 그때까지 화면에 두지 않는다(사용자 지시 2026-11-19)
/** MSW 목일 때만 보이는 줄(ISSUE-006 "프로토타입이라 실제로 가입되지 않아요.") */
export const MOCK_NOTE = "프로토타입이라 실제로 가입되지 않아요.";
/** 이메일 확인이 필요한 가입 뒤의 안내 한 줄(아직 로그인되지 않았다). 승인 전(FE-04c) */
export const SIGNUP_CONFIRM_NOTICE = "확인 메일을 보냈어요. 메일의 링크를 누르면 가입이 끝나요. 메일이 오지 않으면 다른 방법으로 로그인하거나 로그인 없이 쓰세요.";

// ---------------------------------------------------------------- 약관 동의(할 일 3)
/** 동의 화면 제목·설명 */
export const CONSENT_TITLE = "약관 동의";
export const CONSENT_DESCRIPTION = "필수 항목에 동의해야 프로필을 저장할 수 있어요. 선택 항목은 동의하지 않아도 돼요.";
/** 필수·선택 표지(지시서 할 일 3 "필수"·"선택") */
export const REQUIRED_TAG = "필수";
export const OPTIONAL_TAG = "선택";
/** 고지 문서(`privacy_policy`: 동의 대상이 아니라 체크가 없다) 표지(FE-04-07 A) */
export const NOTICE_TAG = "안내";
/** `legal_review: "not_reviewed"`인 문서에 붙는 표지(백엔드 `LegalDocumentOut` 설명·설계 문서 9.3절의 글자 그대로) */
export const LEGAL_NOT_REVIEWED_TAG = "초안·법률 검토 전";
/** 문서 머리의 버전·시행일 줄(값은 서버 값: 버전은 정수, 시행일은 일시의 날짜 부분만) */
export const docVersionLine = (version: number, effectiveAt: string) => `버전 ${version} · 시행일 ${effectiveAt.slice(0, 10)}`;
/** 동의해 둔 건강 정보 동의의 체크를 껐을 때의 한 줄(철회하면 서버가 즉시 지운다, 설계 문서 6.3절) */
export const HEALTH_WITHDRAW_WARNING = "건강 정보 동의를 철회하면 저장해 둔 임신 여부와 복용 중인 약이 바로 삭제돼요.";
/** 건강 정보 동의 철회 확인 모달(FE-04-06 A: 삭제·탈퇴와 같은 무게, 되돌릴 수 없음을 밝힌다). 원문 승인(FE-04-08 A, 2026-11-19) */
export const HEALTH_WITHDRAW_CONFIRM_TITLE = "건강 정보 동의를 철회할까요?";
export const HEALTH_WITHDRAW_CONFIRM_BODY = "저장해 둔 임신 여부와 복용 중인 약이 바로 삭제되고 되돌릴 수 없어요.";
export const HEALTH_WITHDRAW_CONFIRM_LABEL = "철회하기";
/** 문서별 체크 글자. 제목은 서버 값 그대로다 */
export const agreeLabel = (title: string) => `${title}에 동의해요`;
export const CONSENT_SUBMIT_LABEL = "동의하고 계속";
/** 필수 항목을 다 고르지 않았을 때의 한 줄 */
export const CONSENT_REQUIRED_HINT = "필수 항목에 모두 동의해야 다음으로 갈 수 있어요.";
export const LEGAL_LOADING = "문서를 불러오는 중이에요.";
export const LEGAL_LOAD_FAILED = "문서를 불러오지 못했어요.";
export const RETRY_LOAD_LABEL = "다시 불러오기";

// ---------------------------------------------------------------- 프로필(할 일 4)
/** 프로필 화면 제목·설명 */
export const PROFILES_TITLE = "프로필";
export const PROFILES_DESCRIPTION = "본인과 가족 3명까지 저장할 수 있어요. 질문할 때 누가 먹는지 고를 수 있어요.";
export const PROFILES_EMPTY = "아직 저장한 프로필이 없어요.";
export const ADD_SELF_LABEL = "내 프로필 추가";
export const addFamilyLabel = (count: number, max: number) => `가족 추가 (${count}/${max})`;
/** 가족이 3명이라 더 추가할 수 없을 때의 한 줄 */
export const FAMILY_FULL_NOTE = "가족은 3명까지 저장할 수 있어요.";
export const EDIT_LABEL = "수정";
export const DELETE_LABEL = "삭제";
export const editProfileLabel = (label: string) => `${label} 수정`;
export const deleteProfileLabel = (label: string) => `${label} 삭제`;
export const REVIEW_CONSENT_LABEL = "동의 내용 보기";
export const LOGOUT_LABEL = "로그아웃";
export const WITHDRAW_LABEL = "탈퇴";

/** 관계(사용자 결정 2026-11-18: 본인·자녀·부모·배우자·기타) */
export const RELATION_LABELS: Readonly<Record<Relation, string>> = { self: "본인", child: "자녀", parent: "부모", spouse: "배우자", other: "기타" };
/** 연령대 11구간의 화면 표시(설계 문서 `P2-doc/PJ2-계정-프로필-데이터.md` 4.8절 표의 "화면 표시" 열 그대로) */
export const AGE_BAND_LABELS: Readonly<Record<AgeBand, string>> = {
  m0_2: "생후 3개월 미만",
  m3_5: "생후 3~5개월",
  m6_11: "생후 6~11개월",
  y1: "만 1세",
  y2: "만 2세",
  y3_5: "만 3~5세",
  y6_11: "만 6~11세",
  y12_14: "만 12~14세",
  y15_18: "만 15~18세",
  y19_64: "만 19~64세",
  y65_plus: "만 65세 이상",
};
/** 임신 여부(사용자 결정 2026-11-18: 모름·아니오·예) */
export const PREGNANCY_LABELS: Readonly<Record<PregnancyStatus, string>> = { unknown: "모름", not_pregnant: "아니오", pregnant: "예" };
/** 프로필에 보일 이름: 별명이 없으면(서버는 null을 허용한다) 관계 글자 */
export const profileName = (profile: Pick<Profile, "label" | "relation">) => profile.label ?? RELATION_LABELS[profile.relation];

/** 프로필 폼 */
export const PROFILE_FORM_NEW_TITLE = "프로필 추가";
export const PROFILE_FORM_EDIT_TITLE = "프로필 수정";
export const PROFILE_NAME_LABEL = "이름(별명)";
export const PROFILE_NAME_HINT = "질문할 때 보일 이름이에요. 예: 나, 엄마, 첫째";
export const RELATION_LABEL = "관계";
export const AGE_BAND_LABEL = "연령대";
export const NOT_SELECTED = "선택 안 함";
export const PREGNANCY_LABEL = "임신 여부";
export const MEDICATIONS_LABEL = "복용 중인 약(선택)";
export const MEDICATION_HINT = "봉투나 상자에 적힌 이름을 그대로 적어 주세요.";
export const MEDICATION_ADD_LABEL = "추가";
export const removeMedicationLabel = (name: string) => `${name} 삭제`;
export const medicationCount = (count: number) => `약 ${count}개`;

// ---- 프로필 약 검색 후보 고르기(FE-04-13 A·FE-04-20 A, 2026-11-20 fedrug). 아래 글자는 모두 **원문 승인(2026-11-20 사용자 "문구 승인")**
/** 입력 칸 아래 한 줄(기존 `MEDICATION_HINT` 뒤에 이어 보인다). 원문 승인(2026-11-20) */
export const MEDICATION_SEARCH_HINT = "한 글자 이상 적으면 자료에서 찾은 제품명·성분명 후보가 보여요. 후보에 없으면 적은 글자 그대로 저장할 수 있어요.";
/** 후보를 찾는 동안(보조기기가 읽는다). 원문 승인(2026-11-20) */
export const MEDICATION_SEARCHING = "후보를 찾는 중이에요.";
/** 후보 목록의 이름과 개수 한 줄(보조기기가 읽는다). 원문 승인(2026-11-20) */
export const medicationCandidatesLabel = (count: number) => `후보 ${count}개`;
/** 후보가 하나도 없을 때(FE-04-20 A: 제품 → 성분 사전 모두 없음). 원문 승인(2026-11-20) */
export const MEDICATION_NO_CANDIDATES = "자료에서 찾지 못했어요. 그대로 추가하면 확인 안 된 약으로 저장돼요. 약봉투의 제품명·성분명을 확인해 보세요.";
/** 후보의 종류 표지: 제품 사전·성분 사전(백엔드 `matched_by`). 원문 승인(2026-11-20) */
export const MEDICATION_KIND_LABELS: Readonly<Record<DrugMatchedBy, string>> = { product_name: "제품명", ingredient_name: "성분명" };
/** 비슷한 이름(`match_type: bm25`)으로 찾은 후보의 표지: 이름이 같지 않으니 확인하고 고른다. 원문 승인(2026-11-20) */
export const MEDICATION_SIMILAR_TAG = "비슷한 이름";
/** 사전 후보 없이 글자만 저장한 약(`item_seq` null, FE-04-20 A "확인 안 된 약")의 표지. 원문 승인(2026-11-20) */
export const MEDICATION_UNCONFIRMED_TAG = "확인 안 된 약";
/** 확인 안 된 약이 목록에 있을 때 목록 아래 한 줄. 원문 승인(2026-11-20) */
export const MEDICATION_UNCONFIRMED_NOTE = "확인 안 된 약은 금기 확인에서 빠져요. 약봉투의 제품명·성분명을 약사에게 확인하세요.";
/** 검색이 로그인 만료(401)로 실패했을 때: 입력은 그대로 두고 글자 저장은 할 수 있다. 원문 승인(2026-11-20) */
export const MEDICATION_SEARCH_AUTH_EXPIRED = "로그인이 만료돼 후보를 찾지 못했어요. 적은 글자는 그대로 추가할 수 있어요.";
/** 검색이 그 밖의 이유(422·네트워크·5xx)로 실패했을 때. 원문 승인(2026-11-20) */
export const MEDICATION_SEARCH_FAILED = "지금은 후보를 찾지 못했어요. 적은 글자는 그대로 추가할 수 있어요.";
/** 약이 10개라 더 넣을 수 없을 때는 기존 승인 글자 `ERROR_MEDICATION_LIMIT`를 그대로 쓴다 */
/**
 * 질문 때 고정 문구 **초안**(FE-04-20 A: 프로필의 확인 안 된 약은 금기 확인에서 빠진다고 알린다). 원문 승인(2026-11-20), 채팅 쪽 적용은 S3 연동 때.
 * 이번 범위(fedrug)에서는 채팅 쪽에 붙이지 않았다. 고정 문구는 코드로 강제하는 원칙(CLAUDE.md 1장)이라 승인되면 백엔드 고정 문구
 * (`pnpm gen:fixed` → `lib/fixed/phrases.generated`)로 옮기고 이 상수는 지운다. 화면 코드는 아직 이 상수를 쓰지 않는다
 */
export const MEDICATION_UNCONFIRMED_ASK_NOTICE_DRAFT = "이 약은 자료에서 찾지 못해 금기 확인에서 빠져요. 약봉투의 제품명·성분명을 약사에게 확인하세요.";
export const SAVE_LABEL = "저장";
export const CANCEL_LABEL = "취소";
/** 건강 정보 동의가 없을 때의 이유 한 줄(서버는 이 문구를 주지 않는다). 422 `HEALTH_CONSENT_REQUIRED`의 화면 문구로도 쓴다 */
export const HEALTH_CONSENT_REQUIRED_FALLBACK = "건강 정보 동의를 해야 임신 여부와 복용 중인 약을 입력할 수 있어요.";

/** 확인 모달(삭제·탈퇴) */
export const deleteProfileConfirm = (label: string) => `${label} 프로필을 삭제할까요?`;
export const DELETE_PROFILE_BODY = "삭제하면 되돌릴 수 없어요.";
export const WITHDRAW_CONFIRM_TITLE = "탈퇴할까요?";
export const WITHDRAW_CONFIRM_BODY = "계정과 저장한 프로필·동의 기록이 모두 삭제되고 되돌릴 수 없어요.";
export const WITHDRAW_CONFIRM_LABEL = "탈퇴하기";

// ---------------------------------------------------------------- 대상 선택(할 일 5)
/** 질문 입력 위 대상 선택(tickets/frontend/FE-04.md §2 "누가 먹나요") */
export const TARGET_LABEL = "누가 먹나요";

// ---------------------------------------------------------------- 사이드바 계정 자리
/** 로그인한 사용자의 계정 메뉴 */
export const ACCOUNT_LABEL = "계정";
/** 계정 자리의 상태 글자(서버가 이름·이메일을 주지 않아 이름 대신 보인다) */
export const ACCOUNT_SIGNED_IN = "로그인됨";
export const MANAGE_PROFILES_LABEL = "프로필 관리";

// ---------------------------------------------------------------- 오류(서버 오류 본문에는 문구가 없다: `{code, fields}`, BE-11-21 A)
/** 로그인·가입(Supabase Auth·목 로그인. 백엔드 코드가 아니다) */
export const ERROR_INVALID_CREDENTIALS = "이메일이나 비밀번호가 맞지 않아요.";
export const ERROR_EMAIL_TAKEN = "이미 가입한 이메일이에요. 로그인해 주세요.";
/** 로그인 연결에서 새로 생긴 로그인·가입 오류. 아래 이메일 3줄은 화면에서 숨겨져(PRD-01-10 A) 승인 전(FE-04c)이고, 그 아래 2줄은 원문 승인(FE-04-08 A, 2026-11-19) */
/** 가입은 했지만 확인 메일의 링크를 아직 누르지 않았다 */
export const ERROR_EMAIL_NOT_CONFIRMED = "이메일 확인이 끝나지 않았어요. 받은 메일의 링크를 누른 뒤 다시 로그인해 주세요.";
export const ERROR_WEAK_PASSWORD = "비밀번호가 너무 짧거나 단순해요. 더 길게 바꿔 주세요.";
/** 확인 메일을 보내지 못했다(메일 발송 한도·수신 제한) */
export const ERROR_EMAIL_SEND_FAILED = "지금은 확인 메일을 보내지 못했어요. 잠시 뒤 다시 시도하거나 다른 방법으로 로그인해 주세요.";
/** 원문 승인(FE-04-08 A, 2026-11-19) */
export const ERROR_AUTH_RATE_LIMITED = "요청이 너무 많았어요. 잠시 뒤 다시 시도해 주세요.";
export const ERROR_AUTH_FAILED = "로그인하지 못했어요. 잠시 뒤 다시 시도해 주세요. 로그인하지 않아도 질문은 할 수 있어요.";
/** 소셜 로그인 콜백: 이메일 없는 카카오계정·이메일 미동의(BE-11-16 B: 이메일 필수). 문구는 지시서(2026-11-19 FE-04c) 할 일 4, 원문 승인(FE-04-08 A, 2026-11-19) */
export const ERROR_OAUTH_EMAIL_REQUIRED = "카카오계정에 이메일이 없거나 동의하지 않으면 로그인할 수 없어요. 다른 방법으로 로그인하거나 로그인 없이 쓰세요.";
/** 소셜 로그인 콜백: 그 밖의 실패(동의 취소 등). 원문 승인(FE-04-08 A, 2026-11-19) */
export const ERROR_OAUTH_FAILED = "로그인을 마치지 못했어요. 다시 시도하거나 로그인 없이 쓰세요.";
/** 401 `AUTH_REQUIRED`·`AUTH_INVALID` */
export const ERROR_AUTH_REQUIRED = "로그인이 필요해요. 다시 로그인해 주세요.";
/** 403 `CONSENT_REQUIRED`(필수 동의 없음)·`RECONSENT_REQUIRED`(문서가 바뀌어 다시 동의 필요) */
export const ERROR_REQUIRED_CONSENT = CONSENT_REQUIRED_HINT;
export const ERROR_RECONSENT_REQUIRED = "약관이 바뀌었어요. 동의 내용을 다시 확인해 주세요.";
/** 404 `NOT_FOUND` */
export const ERROR_NOT_FOUND = "찾을 수 없어요. 이미 삭제됐을 수 있어요.";
/** 409 `VERSION_MISMATCH`: 화면에 뜬 문서가 옛 버전이다(스토어가 새 본문을 다시 받는다) */
export const ERROR_VERSION_MISMATCH = "문서가 새 버전으로 바뀌었어요. 내용을 다시 확인하고 동의해 주세요.";
/** 409 `USE_ACCOUNT_DELETE`: 이용약관 동의는 철회가 아니라 탈퇴로만 거둔다 */
export const ERROR_USE_ACCOUNT_DELETE = "이용약관 동의는 탈퇴로만 철회할 수 있어요.";
/** 409 `SELF_REQUIRED`·`SELF_EXISTS`·`SELF_FIXED` */
export const ERROR_SELF_REQUIRED = "본인 프로필은 삭제할 수 없어요. 계정을 지우려면 탈퇴를 이용해 주세요.";
export const ERROR_SELF_EXISTS = "본인 프로필은 1개만 만들 수 있어요.";
export const ERROR_SELF_FIXED = "본인 프로필의 관계는 바꿀 수 없어요.";
/** 422 `PROFILE_LIMIT`·`MEDICATION_LIMIT`·`INVALID_REQUEST` */
export const ERROR_PROFILE_LIMIT = "프로필은 본인 1명과 가족 3명까지 저장할 수 있어요.";
export const ERROR_MEDICATION_LIMIT = "복용 중인 약은 10개까지 저장할 수 있어요.";
export const ERROR_INVALID_REQUEST = "입력한 내용을 확인해 주세요.";
/** 501 `NOT_IMPLEMENTED`: 서버에 계정 기능이 아직 연결되지 않았다(원격 스키마 적용 전, BE-11-23 A) */
export const ERROR_NOT_IMPLEMENTED = "계정 기능은 아직 준비 중이에요. 로그인하지 않아도 질문은 할 수 있어요.";
/** 503 `AUTH_UNAVAILABLE`(BE-11-20 A)·`ACCOUNT_UNAVAILABLE`: 사용자 잘못이 아니며 로그아웃시키지 않는다 */
export const ERROR_AUTH_UNAVAILABLE = "지금은 로그인 상태를 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요. 로그인하지 않아도 질문은 할 수 있어요.";
export const ERROR_ACCOUNT_UNAVAILABLE = "지금은 계정 정보를 불러오거나 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
export const ERROR_NETWORK = "연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
export const ERROR_GENERIC = "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
export const ERROR_EMAIL_FORMAT = "이메일 주소를 확인해 주세요.";
export const ERROR_PASSWORD_EMPTY = "비밀번호를 입력해 주세요.";
export const ERROR_NAME_EMPTY = "이름(별명)을 입력해 주세요.";
