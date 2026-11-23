// 계정·약관 동의·프로필 API를 감싸는 한 모듈(FE-04). 화면과 스토어는 이 파일의 함수만 부른다.
//
// 계약 원본은 백엔드 코드다(BE-11, develop `7158b39`): `backend/app/api/me.py`·`backend/app/api/account.py`.
// 응답·요청 모양은 `pnpm gen:api`가 만든 `./generated.ts`와 `contract-check.ts`(컴파일 시점 대조)로 맞춘다.
// 브라우저는 같은 출처의 `/api/*`만 부른다(rewrites 경유 백엔드: `/api/me` → 백엔드 `/me`).
//
// 백엔드에 **있는** 것(실제 계약)
// - `GET /api/legal/{doc_type}` → `LegalDocumentOut` (`doc_type`: `terms`·`privacy_policy`·`privacy_consent`·`sensitive_consent`·`age_14`, 게스트 허용).
//   `privacy_policy`는 고지 문서라 동의 대상이 아니다(체크 없음). `legal_review: "not_reviewed"`면 화면이 "초안·법률 검토 전" 표지를 그린다.
//   `age_14`(만 14세 이상 확인, PRD-17-12 A)는 첫 로그인 동의 화면의 **별도 필수 체크**다: 본문 카드가 아니라 체크 한 줄로 그리고 라벨은 화면 상수다
// - `GET /api/me` → `MeResponse`(온보딩 단계·문서별 동의 상태·`health_consent_active`). 토큰 없음 401 `AUTH_REQUIRED`
// - `POST /api/consents` `{items:[{doc_type, version, action: agree|withdraw}], channel}` → 201 `MeResponse`.
//   현재본과 버전이 다르면 409 `VERSION_MISMATCH`, 약관·만 14세 확인 철회는 409 `USE_ACCOUNT_DELETE`. 철회는 서버가 즉시 삭제한다
//   (`sensitive_consent` → 임신 여부·복용 약, `privacy_consent` → 프로필 전부). 필수 동의(`terms`·`privacy_consent`·`age_14`)가 없으면 프로필 쓰기는 403 `CONSENT_REQUIRED`
// - `GET /api/profiles` → `ProfileOut[]`, `POST /api/profiles`(201)·`PATCH /api/profiles/{profile_id}` → `ProfileOut`,
//   `DELETE /api/profiles/{profile_id}` → 204(본인 프로필은 409 `SELF_REQUIRED`). PATCH는 보낸 칸만 바꾸고 `medications`는 목록 전체 교체.
//   `sex`(성별, 선택: `female`·`male`·null = 미입력, FE-11-09 C·PRD-17-13 A)는 건강 정보 동의 없이도 저장되고 `/chat` 요청에는 싣지 않는다(S10)
// - `DELETE /api/me` → 204(탈퇴: 프로필·복용 약·동의 기록 즉시 파기)
// - `POST /api/drugs/search` `{q}`(앞뒤 공백 제거 뒤 1~100자) → `DrugSearchOut`(FE-04-13 A·FE-04-21 A, 백엔드 `drugs.py`, 2026-11-20).
//   로그인 필요. 후보는 제품 → 성분 순서로 최대 10개이고 질문 문자열은 되돌려 주지 않는다(`Cache-Control: no-store`).
//   **POST인 이유**: 질문을 URL 쿼리에 두면 서버 access 로그·브라우저 기록·프록시 로그에 경로째 남는다(결정 FE-04-21 A).
//   오류: 401 / 422 `INVALID_REQUEST`(fields=`q`) / 501 `NOT_IMPLEMENTED`(사전 공급자 없음) / 503 `DICT_UNAVAILABLE`·`AUTH_UNAVAILABLE`
// - 오류 본문은 `/chat`과 같은 `{code, fields}`(BE-11-21 A). 입력 값은 실려 오지 않는다. 코드:
//   401 `AUTH_REQUIRED`·`AUTH_INVALID` / 403 `CONSENT_REQUIRED`·`RECONSENT_REQUIRED`(fields=문서 종류) / 404 `NOT_FOUND` /
//   409 `VERSION_MISMATCH`·`USE_ACCOUNT_DELETE`·`SELF_EXISTS`·`SELF_REQUIRED`·`SELF_FIXED` /
//   422 `INVALID_REQUEST`·`PROFILE_LIMIT`·`MEDICATION_LIMIT`·`HEALTH_CONSENT_REQUIRED`(BE-11-25 A, fields=건강 정보 칸) /
//   501 `NOT_IMPLEMENTED`(검증기·저장소 미설정, 원격 스키마 적용 전. BE-11-23 A) / 503 `AUTH_UNAVAILABLE`(BE-11-20 A)·`ACCOUNT_UNAVAILABLE`
//
// 로그인(백엔드에 엔드포인트가 없다: Supabase Auth가 맡는다. PRD-01-09 A′·BE-11-18 A, `./auth.ts`)
// - Supabase 설정(`NEXT_PUBLIC_SUPABASE_URL`·`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`)이 있으면 `@supabase/ssr`로 로그인한다:
//   이메일(가입·로그인), Google·Kakao(`signInWithOAuth` → `/auth/callback`), 로그아웃. Naver는 준비 중이다
// - 인증 전달: 세션이 있으면 모든 계정 호출에 `Authorization: Bearer <access token>`을 붙인다(`call`). 토큰은 머리에만 쓰고 남기지 않는다
// - MSW 목 모드에서는 Supabase를 쓰지 않는다: `POST /api/auth/email/login`·`signup`·`POST /api/auth/logout`·`GET /api/auth/{provider}/start`
//   (`src/mocks/account-handlers.ts`, 핸들러 메모리의 세션)로 로그인 여부를 흉내 낸다. 이 주소들은 실제 백엔드에 없다
// - 계정 진입점은 목 모드이거나 Supabase 설정이 있을 때만 보인다(FE-04-02 A·FE-04-05 A, `isAccountEntryEnabled`)
import { z } from "zod";
import { AuthError, authMode, getAccessToken, getSocialIdentity, hasAuthSession, signInWithEmail, signInWithProvider, signOut, signUpWithEmail } from "./auth";
import { apiClient, resolveApiBase } from "./client";
import type { components } from "./generated";
import { ErrorBodySchema } from "./schemas";

type Gen = components["schemas"];

// ---------------------------------------------------------------- 모양(zod, 백엔드 응답 모델과 같은 칸. `contract-check.ts`가 생성 타입과 대조한다)
/**
 * 문서 종류 전체(계약: `account_repo.DocType`·`DOC_TYPES` 순서 그대로). `terms_guest`는 게스트판 이용약관(PRD-17-22 A, 2026-11-23 백엔드 추가)으로
 * **열람용**이며 동의 화면에 보이지도, `POST /consents`에 실리지도 않는다(`CONSENT_SCREEN_DOC_TYPES`·`CONSENT_DOC_TYPES`에 없다)
 */
export const LEGAL_DOC_TYPES = ["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14", "terms_guest"] as const;
export const LegalDocTypeSchema = z.enum(LEGAL_DOC_TYPES);
export type LegalDocType = z.infer<typeof LegalDocTypeSchema>;

/** 첫 로그인 동의 화면이 받아 보이는 문서(동의 대상 넷 + 고지 문서 `privacy_policy`). 순서는 화면 순서(`age_14`는 카드가 아니라 별도 체크). 게스트판은 없다 */
export const CONSENT_SCREEN_DOC_TYPES = ["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"] as const;
export type ConsentScreenDocType = (typeof CONSENT_SCREEN_DOC_TYPES)[number];

/** 동의 대상 문서(`account_repo.CONSENT_DOC_TYPES`). `privacy_policy`·`terms_guest`는 고지·열람 문서라 빠진다 */
export const CONSENT_DOC_TYPES = ["terms", "privacy_consent", "sensitive_consent", "age_14"] as const;
export const ConsentDocTypeSchema = z.enum(CONSENT_DOC_TYPES);
export type ConsentDocType = z.infer<typeof ConsentDocTypeSchema>;
export const isConsentDocType = (docType: string): docType is ConsentDocType => (CONSENT_DOC_TYPES as readonly string[]).includes(docType);

/** 건강 정보(임신 여부·복용 약) 입력·저장을 여는 선택 동의 */
export const HEALTH_CONSENT_DOC: ConsentDocType = "sensitive_consent";
/** 만 14세 이상 확인(`account_repo.AGE_14_DOC`, PRD-17-12 A): 첫 로그인 동의 화면의 별도 필수 체크. 철회는 탈퇴로만(409 `USE_ACCOUNT_DELETE`) */
export const AGE_14_DOC: ConsentDocType = "age_14";
/** 프로필을 쓰려면 있어야 하는 동의(`account_repo.REQUIRED_CONSENT_DOCS`) */
export const REQUIRED_CONSENT_DOCS: readonly ConsentDocType[] = ["terms", "privacy_consent", AGE_14_DOC];

export const LegalReviewSchema = z.enum(["not_reviewed", "reviewed"]);

export const LegalDocSchema = z.strictObject({
  doc_type: LegalDocTypeSchema,
  version: z.number().int().min(1),
  title: z.string().min(1),
  body_md: z.string(),
  required: z.boolean(),
  requires_reconsent: z.boolean(),
  effective_at: z.string(),
  legal_review: LegalReviewSchema,
  body_sha256: z.string(),
});
export type LegalDoc = z.infer<typeof LegalDocSchema>;

/** 문서 종류별 동의 상태(`GET /me`의 `consents[]`) */
export const ConsentStateSchema = z.strictObject({
  doc_type: ConsentDocTypeSchema,
  required: z.boolean(),
  agreed_version: z.number().int().nullable(),
  acted_at: z.string().nullable(),
  current_version: z.number().int(),
  needs_consent: z.boolean(),
  needs_reconsent: z.boolean(),
});
export type ConsentState = z.infer<typeof ConsentStateSchema>;

export const OnboardingStepSchema = z.enum(["consent", "profile_self", "family", "done"]);
export type OnboardingStep = z.infer<typeof OnboardingStepSchema>;

/** `GET /me`·`POST /consents` 응답. 이름·이메일 같은 로그인 정보는 실려 오지 않는다 */
export const MeSchema = z.strictObject({
  user_id: z.string().min(1),
  is_guest: z.boolean().default(false),
  onboarding_step: OnboardingStepSchema,
  onboarding_completed_at: z.string().nullable(),
  consents: z.array(ConsentStateSchema),
  health_consent_active: z.boolean(),
  profile_limit: z.number().int().default(4),
});
export type Me = z.infer<typeof MeSchema>;

export const RELATIONS = ["self", "child", "parent", "spouse", "other"] as const;
export const RelationSchema = z.enum(RELATIONS);
export type Relation = z.infer<typeof RelationSchema>;

/** `account_repo.AGE_BANDS` 11구간(BE-11-07 A). 화면 글자·나이 구간 대응은 설계 문서 4.8절 표 */
export const AGE_BANDS = ["m0_2", "m3_5", "m6_11", "y1", "y2", "y3_5", "y6_11", "y12_14", "y15_18", "y19_64", "y65_plus"] as const;
export const AgeBandSchema = z.enum(AGE_BANDS);
export type AgeBand = z.infer<typeof AgeBandSchema>;

export const PREGNANCY_STATUSES = ["unknown", "not_pregnant", "pregnant"] as const;
export const PregnancyStatusSchema = z.enum(PREGNANCY_STATUSES);
export type PregnancyStatus = z.infer<typeof PregnancyStatusSchema>;

/**
 * 성별(`account_repo.SEXES`, FE-11-09 C·PRD-17-13 A). 선택 입력이고 null = 미입력("기타" 칸은 없다).
 * 온보딩에서 사용자가 직접 고르며 간편 로그인(Google·Kakao) 공급자 정보로 채우지 않는다. 건강 정보가 아니라 건강 정보 동의 없이도 저장된다
 */
export const SEXES = ["female", "male"] as const;
export const SexSchema = z.enum(SEXES);
export type Sex = z.infer<typeof SexSchema>;

/** 복용 중인 약(응답): 사용자가 적은 글자 그대로(`input_text`). `item_seq`는 서버가 사전에서 확인한 것만 채운다 */
export const MedicationSchema = z.strictObject({
  medication_id: z.string().min(1),
  input_text: z.string().min(1),
  item_seq: z.string().nullable(),
  confirmed_at: z.string().nullable(),
});
export type Medication = z.infer<typeof MedicationSchema>;

/**
 * 프로필 병아리 배경색 8개(백엔드 `account_repo.AVATAR_COLORS` 순서 그대로, 2026-11-23 FE-17 U-01). 건강 정보가 아니다.
 * 응답 `ProfileOut.avatar_color`(늘 포함, 기본 `yellow`), 요청 `ProfileCreate`(기본 yellow)·`ProfileUpdate`(선택, null 거부)
 */
export const AVATAR_COLORS = ["yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray"] as const;
export const AvatarColorSchema = z.enum(AVATAR_COLORS);
export type AvatarColor = z.infer<typeof AvatarColorSchema>;
export const DEFAULT_AVATAR_COLOR: AvatarColor = "yellow";

export const ProfileSchema = z.strictObject({
  profile_id: z.string().min(1),
  relation: RelationSchema,
  label: z.string().nullable(),
  age_band: AgeBandSchema.nullable(),
  /** 성별(선택). 미입력이면 null */
  sex: SexSchema.nullable(),
  /** 건강 정보. 저장한 적이 없으면 null */
  pregnancy_status: PregnancyStatusSchema.nullable(),
  /** 병아리 배경색. 칸이 없거나(배포 순서 차이) 모르는 값이면 기본색으로 읽는다(화면이 깨지지 않게) */
  avatar_color: AvatarColorSchema.catch(DEFAULT_AVATAR_COLOR),
  sort_order: z.number().int(),
  medications: z.array(MedicationSchema),
});
export type Profile = z.infer<typeof ProfileSchema>;

/** 약 이름 검색 후보가 어느 사전에서 맞았는가(`drugs.py`): 제품 사전이면 `item_seq`가 있고, 성분 사전이면 없다 */
export const DRUG_MATCHED_BY = ["product_name", "ingredient_name"] as const;
export const DrugMatchedBySchema = z.enum(DRUG_MATCHED_BY);
export type DrugMatchedBy = z.infer<typeof DrugMatchedBySchema>;
/** 비슷한 이름(BM25)으로 찾은 후보의 `match_type`. 화면이 자동으로 확정하지 않는다(고르는 것은 늘 사용자다) */
export const DRUG_MATCH_SIMILAR = "bm25";

/**
 * 약 이름 검색 후보 한 건(`DrugCandidateOut`). `item_seq`가 null인 후보(성분명 일치, 허가번호 없는 행)는 골라도 글자만 저장된다.
 * `match_type`은 서버가 `exact`·`normalized`·`prefix`·`contains`·`bm25`를 쓰지만 목록이 늘 수 있어 문자열로 둔다
 */
export const DrugCandidateSchema = z.strictObject({
  name: z.string().min(1),
  item_seq: z.string().nullable(),
  entp_name: z.string().nullable(),
  prescription: z.string().nullable(),
  matched_by: DrugMatchedBySchema,
  match_type: z.string(),
});
export type DrugCandidate = z.infer<typeof DrugCandidateSchema>;

/** `POST /drugs/search` 응답(`DrugSearchOut`). 질문 문자열은 실려 오지 않는다 */
export const DrugSearchResultSchema = z.strictObject({
  candidates: z.array(DrugCandidateSchema),
  /** 후보가 여럿이거나 비슷한 이름일 때 true. 후보가 없으면 false */
  needs_confirmation: z.boolean(),
  dict_version: z.string(),
});
export type DrugSearchResult = z.infer<typeof DrugSearchResultSchema>;

// ---------------------------------------------------------------- 요청(생성 타입 그대로)
export type ConsentItem = Gen["ConsentItem"];
export type ConsentChannel = Gen["ConsentRequest"]["channel"];
export type MedicationInput = Gen["MedicationIn"];
export type ProfileCreateBody = Gen["ProfileCreate"];
export type ProfileUpdateBody = Gen["ProfileUpdate"];
export type DrugSearchBody = Gen["DrugSearchIn"];

/**
 * 화면이 만들거나 고칠 때 넘기는 값. `health`가 null이면 건강 정보 칸(임신 여부·복용 약)을 **요청에 싣지 않는다**
 * (건강 정보 동의가 없을 때. 실으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다. PATCH에서는 그 칸을 건드리지 않는다는 뜻이다).
 * `sex`는 건강 정보가 아니라 늘 싣는다(null = 미입력·지움). 폼에 늘 있는 칸이라 PATCH에도 폼 값을 그대로 보낸다
 */
export interface ProfileDraft {
  relation: Relation;
  label: string;
  age_band: AgeBand | null;
  sex: Sex | null;
  health: { pregnancy_status: PregnancyStatus | null; medications: MedicationInput[] } | null;
  /** 병아리 배경색(건강 정보 아님, 동의와 상관없이 늘 싣는다) */
  avatar_color: AvatarColor;
}

function profileBody(draft: ProfileDraft): ProfileCreateBody & ProfileUpdateBody {
  const base = { relation: draft.relation, label: draft.label, age_band: draft.age_band, sex: draft.sex, avatar_color: draft.avatar_color };
  return draft.health ? { ...base, pregnancy_status: draft.health.pregnancy_status, medications: draft.health.medications } : base;
}

/** 본인 1 + 가족 최대 3(`account_repo.PROFILE_LIMIT = 4`·`FAMILY_LIMIT = 3`, BE-11-01 B) */
export const SELF_PROFILE_MAX = 1;
export const FAMILY_PROFILE_MAX = 3;
/** 서버 상한과 같은 값(`account_repo.LABEL_MAX_CHARS`·`MEDICATION_TEXT_MAX_CHARS`·`MEDICATION_LIMIT`) */
export const PROFILE_LABEL_MAX_CHARS = 20;
export const MEDICATION_NAME_MAX_CHARS = 100;
export const MEDICATIONS_MAX = 10;
/** 같은 약인가: 품목 번호가 있으면 번호로, 없으면 적은 글자로 본다(프로필 복용 약 목록의 중복 규칙. 글자 입력·사진 등록이 같은 규칙을 쓴다) */
export const sameMedication = (a: MedicationInput, b: MedicationInput) => (a.item_seq && b.item_seq ? a.item_seq === b.item_seq : a.input_text === b.input_text);
/** 약 이름 검색(`DrugSearchIn.q`) 글자 상한·후보 상한(백엔드 `drugs.py`: 프로필 약 `input_text` 상한과 같다, 후보 최대 10) */
export const DRUG_QUERY_MAX_CHARS = MEDICATION_NAME_MAX_CHARS;
export const DRUG_CANDIDATES_MAX = 10;

export const SOCIAL_PROVIDERS = ["google", "kakao"] as const;
export type SocialProvider = (typeof SOCIAL_PROVIDERS)[number];

/** 본인 프로필 이름 칸의 초기값을 공급자 이름으로 채우는 로그인 공급자: 카카오 닉네임만(FE-04-28 B). 구글 실명은 가져오지 않는다 */
export const NAME_PREFILL_PROVIDER: SocialProvider = "kakao";

/**
 * 공급자가 준 닉네임을 이름(별명) 칸 규칙에 맞춘다(FE-04-28 B): 앞뒤 공백을 지우고 `PROFILE_LABEL_MAX_CHARS`(20자, 글자 단위)로 자른다.
 * 문자열이 아니거나 자르고 나서 비면 null(채우지 않는다). 순수 함수이며 값을 남기지 않는다
 */
export function selfNameFromNickname(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const name = [...value.trim()].slice(0, PROFILE_LABEL_MAX_CHARS).join("").trim();
  return name.length > 0 ? name : null;
}

// ---------------------------------------------------------------- 오류
export type AccountErrorKind = "network" | "http" | "invalid";

/** 계정 API 실패. 서버가 준 코드와 칸 이름만 싣고 입력 값(이메일·비밀번호·프로필)은 싣지 않는다 */
export class AccountApiError extends Error {
  constructor(
    readonly kind: AccountErrorKind,
    readonly status: number,
    readonly code: string | null,
    /** 오류 본문의 `fields`: 칸 이름이나 문서 종류(값이 아니다) */
    readonly fields: readonly string[] = [],
  ) {
    super(`account api ${kind} ${status}`);
    this.name = "AccountApiError";
  }
}

type Method = "get" | "post" | "patch" | "delete";

async function call(method: Method, path: string, json?: unknown, signal?: AbortSignal): Promise<Response> {
  // 로그인해 있으면 토큰을 붙인다(백엔드 `security/auth.py`가 JWKS로 검증한다). 게스트·목 모드는 붙이지 않는다
  const token = await getAccessToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response: Response;
  try {
    response = await apiClient(path, { method, prefix: resolveApiBase(), json, headers, signal });
  } catch (error) {
    // 부르는 쪽이 끊은 요청(검색어가 바뀌어 앞 검색을 버림)은 연결 실패가 아니다: 그대로 넘겨 호출자가 무시하게 한다
    if (signal?.aborted) throw error;
    throw new AccountApiError("network", 0, null);
  }
  return response;
}

async function fail(response: Response): Promise<never> {
  const body = ErrorBodySchema.safeParse(await response.json().catch(() => null));
  throw new AccountApiError("http", response.status, body.success ? body.data.code : null, body.success ? body.data.fields : []);
}

async function read<S extends z.ZodType>(response: Response, schema: S): Promise<z.infer<S>> {
  if (!response.ok) return fail(response);
  const parsed = schema.safeParse(await response.json().catch(() => null));
  if (!parsed.success) throw new AccountApiError("invalid", response.status, null);
  return parsed.data;
}

async function done(response: Response): Promise<void> {
  if (!response.ok) await fail(response);
}

// ---------------------------------------------------------------- 호출(백엔드에 있는 것)
/**
 * 로그인한 사용자. 비로그인(401)이면 null이다.
 * 501(검증기·저장소 미설정)·503(`AUTH_UNAVAILABLE`·`ACCOUNT_UNAVAILABLE`)은 로그아웃이 아니므로 null로 바꾸지 않고 던진다(BE-11-20 A).
 * Supabase 로그인 방식에서 세션이 없으면 게스트가 확실하므로 서버를 부르지 않는다(토큰 없는 호출은 늘 401이다).
 */
export async function fetchMe(): Promise<Me | null> {
  if (authMode() === "supabase" && !(await hasAuthSession())) return null;
  const response = await call("get", "me");
  if (response.status === 401) return null;
  return read(response, MeSchema);
}

/** 법적 문서 한 건(현재본). 본문은 서버 값 그대로 그린다(프런트에 문구를 두지 않는다) */
export async function fetchLegalDoc(docType: LegalDocType): Promise<LegalDoc> {
  return read(await call("get", `legal/${docType}`), LegalDocSchema);
}

/** 동의 화면에 보일 순서대로 다섯 문서를 받는다(동의 대상 넷 + 고지 문서 `privacy_policy`. `age_14`는 맨 뒤). 게스트판 `terms_guest`는 받지 않는다 */
export async function fetchLegalDocs(): Promise<LegalDoc[]> {
  return Promise.all(CONSENT_SCREEN_DOC_TYPES.map(fetchLegalDoc));
}

/**
 * 열람 목록용 문서 모양(2026-11-23 약관 열람 진입점): `doc_type`을 enum으로 묶지 않는다. 게스트용 문서 종류처럼 서버에 아직 없는 종류를
 * 목록에 둘 수 있게 하기 위해서다(목록은 `features/account/legal-menu.ts`). 나머지 칸은 `LegalDocSchema`와 같다
 */
export const LegalMenuDocSchema = LegalDocSchema.extend({ doc_type: z.string().min(1) });
export type LegalMenuDoc = z.infer<typeof LegalMenuDocSchema>;

/**
 * 열람용 문서 한 건. 서버가 그 종류를 모르거나(422 `INVALID_REQUEST`: enum 밖) 게시본이 없으면(404 `NOT_FOUND`) **null**을 돌려주고
 * 화면은 그 항목을 그리지 않는다("준비 중" 같은 글자를 두지 않는다). 그 밖의 실패(네트워크·5xx)는 그대로 던진다.
 * 읽기 전용이며 동의 기록을 만들지 않는다
 */
export async function fetchLegalDocIfPublished(docType: string): Promise<LegalMenuDoc | null> {
  try {
    return await read(await call("get", `legal/${encodeURIComponent(docType)}`), LegalMenuDocSchema);
  } catch (error) {
    if (error instanceof AccountApiError && error.kind === "http" && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
}

/** 동의·철회를 기록하고 갱신된 `Me`를 받는다. `items`는 1~4건(첫 로그인 4종 한 번에)이고 문서 종류가 겹치면 안 된다(서버 규칙) */
export async function postConsents(items: ConsentItem[], channel: ConsentChannel): Promise<Me> {
  const body: Gen["ConsentRequest"] = { items, channel };
  return read(await call("post", "consents", body), MeSchema);
}

export async function fetchProfiles(): Promise<Profile[]> {
  return read(await call("get", "profiles"), z.array(ProfileSchema));
}

export async function createProfile(draft: ProfileDraft): Promise<Profile> {
  const body: ProfileCreateBody = profileBody(draft);
  return read(await call("post", "profiles", body), ProfileSchema);
}

/** 보낸 칸만 바뀐다. `draft.health`가 null이면 임신 여부·복용 약은 그대로 둔다 */
export async function updateProfile(profileId: string, draft: ProfileDraft): Promise<Profile> {
  const body: ProfileUpdateBody = profileBody(draft);
  return read(await call("patch", `profiles/${encodeURIComponent(profileId)}`, body), ProfileSchema);
}

/**
 * 질문 화면의 임신 여부 토글로 대상 프로필의 임신 여부만 바꾼다(FE-11-13, 2026-11-20). PATCH는 보낸 칸만 바꾸므로 `pregnancy_status` 하나만 싣는다
 * (이름·관계·연령대·복용 약은 건드리지 않는다). 건강 정보 동의가 없으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다(FE-11-14 A: 화면은 이 대화에만 적용).
 */
export async function updateProfilePregnancy(profileId: string, status: PregnancyStatus): Promise<Profile> {
  const body: ProfileUpdateBody = { pregnancy_status: status };
  return read(await call("patch", `profiles/${encodeURIComponent(profileId)}`, body), ProfileSchema);
}

/** 가족 프로필 삭제. 본인 프로필은 서버가 409 `SELF_REQUIRED`로 막는다(계정을 지우려면 탈퇴) */
export async function deleteProfile(profileId: string): Promise<void> {
  await done(await call("delete", `profiles/${encodeURIComponent(profileId)}`));
}

/** 탈퇴. 서버가 프로필·복용 약·동의 기록을 지운 뒤 이 브라우저의 로그인 세션도 끝낸다 */
export async function deleteMe(): Promise<void> {
  await done(await call("delete", "me"));
  if (authMode() === "supabase") await signOut();
}

/**
 * 프로필 약 이름 검색(FE-04-13 A): 제품 → 성분 순서의 후보 최대 10개. 검색어는 본문(`{q}`)으로만 보내고(FE-04-21 A) 어디에도 남기지 않는다
 * (로그·콘솔·오류 객체·URL). 앞뒤 공백을 지운 1~100자가 아니면 서버가 422로 막으므로 부르기 전에 화면이 거른다.
 * `signal`로 끊으면(검색어가 바뀜) 끊김 오류가 그대로 던져진다(`AccountApiError`가 아니다): 호출자는 그 결과를 버린다.
 */
export async function searchDrugs(q: string, signal?: AbortSignal): Promise<DrugSearchResult> {
  const body: DrugSearchBody = { q };
  return read(await call("post", "drugs/search", body, signal), DrugSearchResultSchema);
}

// ---------------------------------------------------------------- 로그인(Supabase Auth. 목 모드에서는 MSW 목 주소)
/** 로그인 방식이 없다(목도 아니고 Supabase 설정도 없다). 계정 진입점이 숨어 있어 닿지 않는 길이다 */
const noAuth = () => new AccountApiError("http", 501, "NOT_IMPLEMENTED");

/** Supabase 로그인 실패를 계정 오류로 바꾼다: 코드만 싣고 입력 값은 싣지 않는다. 연결 실패(`status` 0)는 `network`다 */
async function viaSupabase<T>(task: () => Promise<T>): Promise<T> {
  try {
    return await task();
  } catch (error) {
    if (!(error instanceof AuthError)) throw new AccountApiError("network", 0, null);
    throw error.status === 0 && error.code === "AUTH_FAILED" ? new AccountApiError("network", 0, null) : new AccountApiError("http", error.status, error.code);
  }
}

export async function loginWithEmail(email: string, password: string): Promise<void> {
  const mode = authMode();
  if (mode === "supabase") return viaSupabase(() => signInWithEmail(email, password));
  if (mode === "none") throw noAuth();
  await done(await call("post", "auth/email/login", { email, password }));
}

/**
 * 이메일 가입. `confirm_email`이면 아직 로그인되지 않았다: 확인 메일의 링크를 눌러야 한다(Supabase 프로젝트가 이메일 확인을 요구할 때).
 * 목은 늘 바로 로그인된다.
 */
export async function signupWithEmail(email: string, password: string): Promise<"signed_in" | "confirm_email"> {
  const mode = authMode();
  if (mode === "supabase") return viaSupabase(() => signUpWithEmail(email, password));
  if (mode === "none") throw noAuth();
  await done(await call("post", "auth/email/signup", { email, password }));
  return "signed_in";
}

export async function logout(): Promise<void> {
  if (authMode() === "supabase") return signOut();
  await done(await call("post", "auth/logout"));
}

/** 목 전용: 소셜 로그인 시작 주소(실제 백엔드에는 없다) */
export function socialLoginUrl(provider: SocialProvider): string {
  return `${resolveApiBase().replace(/\/+$/, "")}/auth/${provider}/start`;
}

/**
 * 소셜 로그인(Google·Kakao)을 시작한다.
 * - Supabase: 공급자 동의 화면으로 페이지를 옮긴다(`redirected`). 동의가 끝나면 `/auth/callback`이 세션을 만들고 첫 화면으로 돌려보낸다
 * - MSW 목: 워커는 페이지 이동(navigate)을 가로채지 않으므로 목 주소를 fetch로 불러 목 세션만 만든다(`completed`)
 */
export async function startSocialLogin(provider: SocialProvider): Promise<"redirected" | "completed"> {
  const mode = authMode();
  if (mode === "supabase") {
    await viaSupabase(() => signInWithProvider(provider));
    return "redirected";
  }
  if (mode === "none") throw noAuth();
  await done(await call("get", `auth/${provider}/start`));
  return "completed";
}

/** 로그인 세션(Supabase)이 있는가. `GET /api/me`가 501·503이어도 로그인 여부는 이 값으로 안다. 목은 늘 false다 */
export async function hasSession(): Promise<boolean> {
  return hasAuthSession();
}

/**
 * 로그인돼 있을 가능성이 있는가(시작 때 서버를 부를지 정하는 값, FE-04 §3 "복귀 직후 `/me` 1회").
 * - Supabase: 세션 쿠키가 있을 때만 true. 없으면 게스트가 확실하므로 `/me`·`/profiles`를 부르지 않는다(토큰 없는 호출은 늘 401이다)
 * - MSW 목: 세션이 워커 메모리에만 있어 서버(`GET /api/me`)만 안다 → true
 * - 방식 없음(`none`): false(계정 진입점이 숨어 있다)
 */
export async function canHaveSession(): Promise<boolean> {
  const mode = authMode();
  if (mode === "none") return false;
  return mode === "mock" ? true : hasAuthSession();
}

/** 목 전용 응답(`GET /api/auth/identity`, 실제 백엔드에 없다): 공급자와 공급자가 준 표시 이름 */
const MockIdentitySchema = z.object({ provider: z.string().nullable(), name: z.string().nullable() });

/**
 * 본인 프로필을 **처음 만들 때** 이름(별명) 칸의 초기값(FE-04-28 B, 2026-11-22): 로그인 공급자가 카카오(`NAME_PREFILL_PROVIDER`)일 때만 카카오 닉네임을
 * 이름 규칙(`selfNameFromNickname`)에 맞춰 돌려준다. 구글·이메일·게스트·읽기 실패는 null(채우지 않는다).
 * - Supabase: 세션 쿠키의 사용자 정보(`app_metadata.provider`·`user_metadata.name`, `auth.ts` `getSocialIdentity`)만 읽는다(네트워크 0)
 * - MSW 목: 목 주소 `GET /api/auth/identity`
 * 값은 초기값일 뿐이다: 화면에서 고치거나 지울 수 있고, 저장 버튼을 누르기 전에는 서버로 가지 않으며 저장 요청에는 폼에 남은 값만 간다.
 * 닉네임은 어디에도 따로 저장하지 않는다(브라우저 저장소·스토어 영속화·로그·콘솔 금지). 성별 등 다른 칸은 공급자 정보로 채우지 않는다
 */
export async function fetchSelfNameDefault(): Promise<string | null> {
  const mode = authMode();
  if (mode === "none") return null;
  try {
    const identity = mode === "supabase" ? await getSocialIdentity() : MockIdentitySchema.parse(await (await call("get", "auth/identity")).json());
    if (identity?.provider !== NAME_PREFILL_PROVIDER) return null;
    return selfNameFromNickname(identity.name);
  } catch {
    return null;
  }
}

/**
 * 계정 진입점(`로그인/가입`·사이드바 계정 자리·시작 화면 진입 선택·`GET /api/me` 부트스트랩)을 켤지(FE-04-02 A·FE-04-05 A).
 * 로그인할 길이 있을 때만 켠다: 목 모드(`NEXT_PUBLIC_API_MOCKING=enabled`)이거나 Supabase 설정 두 값이 모두 있을 때다.
 * 둘 다 아니면 눌러도 로그인할 수 없으므로 숨긴다(질문은 입력창으로 바로 할 수 있다).
 */
export function isAccountEntryEnabled(): boolean {
  return authMode() !== "none";
}

/** 스토어가 받는 API 묶음(시험에서 바꿔 끼운다) */
export interface AccountApi {
  fetchMe: typeof fetchMe;
  fetchLegalDocs: typeof fetchLegalDocs;
  postConsents: typeof postConsents;
  fetchProfiles: typeof fetchProfiles;
  createProfile: typeof createProfile;
  updateProfile: typeof updateProfile;
  updateProfilePregnancy: typeof updateProfilePregnancy;
  deleteProfile: typeof deleteProfile;
  deleteMe: typeof deleteMe;
  loginWithEmail: typeof loginWithEmail;
  signupWithEmail: typeof signupWithEmail;
  logout: typeof logout;
  startSocialLogin: typeof startSocialLogin;
  hasSession: typeof hasSession;
  canHaveSession: typeof canHaveSession;
  fetchSelfNameDefault: typeof fetchSelfNameDefault;
}

export const accountApi: AccountApi = {
  fetchMe,
  fetchLegalDocs,
  postConsents,
  fetchProfiles,
  createProfile,
  updateProfile,
  updateProfilePregnancy,
  deleteProfile,
  deleteMe,
  loginWithEmail,
  signupWithEmail,
  logout,
  startSocialLogin,
  hasSession,
  canHaveSession,
  fetchSelfNameDefault,
};
