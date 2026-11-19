// 계정·약관 동의·프로필 API를 감싸는 한 모듈(FE-04). 화면과 스토어는 이 파일의 함수만 부른다.
//
// 계약 원본은 백엔드 코드다(BE-11, develop `7158b39`): `backend/app/api/me.py`·`backend/app/api/account.py`.
// 응답·요청 모양은 `pnpm gen:api`가 만든 `./generated.ts`와 `contract-check.ts`(컴파일 시점 대조)로 맞춘다.
// 브라우저는 같은 출처의 `/api/*`만 부른다(rewrites 경유 백엔드: `/api/me` → 백엔드 `/me`).
//
// 백엔드에 **있는** 것(실제 계약)
// - `GET /api/legal/{doc_type}` → `LegalDocumentOut` (`doc_type`: `terms`·`privacy_policy`·`privacy_consent`·`sensitive_consent`, 게스트 허용).
//   `privacy_policy`는 고지 문서라 동의 대상이 아니다(체크 없음). `legal_review: "not_reviewed"`면 화면이 "초안·법률 검토 전" 표지를 그린다
// - `GET /api/me` → `MeResponse`(온보딩 단계·문서별 동의 상태·`health_consent_active`). 토큰 없음 401 `AUTH_REQUIRED`
// - `POST /api/consents` `{items:[{doc_type, version, action: agree|withdraw}], channel}` → 201 `MeResponse`.
//   현재본과 버전이 다르면 409 `VERSION_MISMATCH`, 약관 철회는 409 `USE_ACCOUNT_DELETE`. 철회는 서버가 즉시 삭제한다
//   (`sensitive_consent` → 임신 여부·복용 약, `privacy_consent` → 프로필 전부)
// - `GET /api/profiles` → `ProfileOut[]`, `POST /api/profiles`(201)·`PATCH /api/profiles/{profile_id}` → `ProfileOut`,
//   `DELETE /api/profiles/{profile_id}` → 204(본인 프로필은 409 `SELF_REQUIRED`). PATCH는 보낸 칸만 바꾸고 `medications`는 목록 전체 교체
// - `DELETE /api/me` → 204(탈퇴: 프로필·복용 약·동의 기록 즉시 파기)
// - 오류 본문은 `/chat`과 같은 `{code, fields}`(BE-11-21 A). 입력 값은 실려 오지 않는다. 코드:
//   401 `AUTH_REQUIRED`·`AUTH_INVALID` / 403 `CONSENT_REQUIRED`·`RECONSENT_REQUIRED`(fields=문서 종류) / 404 `NOT_FOUND` /
//   409 `VERSION_MISMATCH`·`USE_ACCOUNT_DELETE`·`SELF_EXISTS`·`SELF_REQUIRED`·`SELF_FIXED` /
//   422 `INVALID_REQUEST`·`PROFILE_LIMIT`·`MEDICATION_LIMIT`·`HEALTH_CONSENT_REQUIRED`(BE-11-25 A, fields=건강 정보 칸) /
//   501 `NOT_IMPLEMENTED`(검증기·저장소 미설정, 원격 스키마 적용 전. BE-11-23 A) / 503 `AUTH_UNAVAILABLE`(BE-11-20 A)·`ACCOUNT_UNAVAILABLE`
//
// 백엔드에 **없는** 것(MSW 목으로만 있다. `src/mocks/account-handlers.ts`)
// - 백엔드 없음: `POST /api/auth/email/login`·`POST /api/auth/email/signup`·`POST /api/auth/logout`·`GET /api/auth/{provider}/start`.
//   로그인은 Supabase Auth가 맡을 자리이고(`@supabase/ssr` 전환은 별도 지시, 지시서 할 일 5) 그때 이 네 함수만 바꾼다
// - 백엔드 없음: 인증 전달. 실제 계약은 `Authorization: Bearer <Supabase access token>`인데 이 모듈은 아직 토큰을 붙이지 않는다.
//   그래서 실제 백엔드 모드에서는 `GET /api/me`가 늘 401이고(게스트), 계정 진입점은 목 모드에서만 보인다(FE-04-02 A, `isAccountEntryEnabled`).
//   목은 핸들러 메모리의 세션으로 로그인 여부를 흉내 낸다
// `NEXT_PUBLIC_*`에는 어떤 키도 더하지 않았다(Supabase JS를 브라우저에 직접 붙이지 않는다).
import { z } from "zod";
import { isApiMockingEnabled } from "@/mocks";
import { apiClient, resolveApiBase } from "./client";
import type { components } from "./generated";
import { ErrorBodySchema } from "./schemas";

type Gen = components["schemas"];

// ---------------------------------------------------------------- 모양(zod, 백엔드 응답 모델과 같은 칸. `contract-check.ts`가 생성 타입과 대조한다)
/** `account_repo.DOC_TYPES` 순서 그대로(화면에 보이는 순서) */
export const LEGAL_DOC_TYPES = ["terms", "privacy_policy", "privacy_consent", "sensitive_consent"] as const;
export const LegalDocTypeSchema = z.enum(LEGAL_DOC_TYPES);
export type LegalDocType = z.infer<typeof LegalDocTypeSchema>;

/** 동의 대상 문서(`account_repo.CONSENT_DOC_TYPES`). `privacy_policy`는 고지 문서라 빠진다 */
export const CONSENT_DOC_TYPES = ["terms", "privacy_consent", "sensitive_consent"] as const;
export const ConsentDocTypeSchema = z.enum(CONSENT_DOC_TYPES);
export type ConsentDocType = z.infer<typeof ConsentDocTypeSchema>;
export const isConsentDocType = (docType: string): docType is ConsentDocType => (CONSENT_DOC_TYPES as readonly string[]).includes(docType);

/** 건강 정보(임신 여부·복용 약) 입력·저장을 여는 선택 동의 */
export const HEALTH_CONSENT_DOC: ConsentDocType = "sensitive_consent";

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

/** 복용 중인 약(응답): 사용자가 적은 글자 그대로(`input_text`). `item_seq`는 서버가 사전에서 확인한 것만 채운다 */
export const MedicationSchema = z.strictObject({
  medication_id: z.string().min(1),
  input_text: z.string().min(1),
  item_seq: z.string().nullable(),
  confirmed_at: z.string().nullable(),
});
export type Medication = z.infer<typeof MedicationSchema>;

export const ProfileSchema = z.strictObject({
  profile_id: z.string().min(1),
  relation: RelationSchema,
  label: z.string().nullable(),
  age_band: AgeBandSchema.nullable(),
  /** 건강 정보. 저장한 적이 없으면 null */
  pregnancy_status: PregnancyStatusSchema.nullable(),
  sort_order: z.number().int(),
  medications: z.array(MedicationSchema),
});
export type Profile = z.infer<typeof ProfileSchema>;

// ---------------------------------------------------------------- 요청(생성 타입 그대로)
export type ConsentItem = Gen["ConsentItem"];
export type ConsentChannel = Gen["ConsentRequest"]["channel"];
export type MedicationInput = Gen["MedicationIn"];
export type ProfileCreateBody = Gen["ProfileCreate"];
export type ProfileUpdateBody = Gen["ProfileUpdate"];

/**
 * 화면이 만들거나 고칠 때 넘기는 값. `health`가 null이면 건강 정보 칸(임신 여부·복용 약)을 **요청에 싣지 않는다**
 * (건강 정보 동의가 없을 때. 실으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다. PATCH에서는 그 칸을 건드리지 않는다는 뜻이다).
 */
export interface ProfileDraft {
  relation: Relation;
  label: string;
  age_band: AgeBand | null;
  health: { pregnancy_status: PregnancyStatus | null; medications: MedicationInput[] } | null;
}

function profileBody(draft: ProfileDraft): ProfileCreateBody & ProfileUpdateBody {
  const base = { relation: draft.relation, label: draft.label, age_band: draft.age_band };
  return draft.health ? { ...base, pregnancy_status: draft.health.pregnancy_status, medications: draft.health.medications } : base;
}

/** 본인 1 + 가족 최대 3(`account_repo.PROFILE_LIMIT = 4`·`FAMILY_LIMIT = 3`, BE-11-01 B) */
export const SELF_PROFILE_MAX = 1;
export const FAMILY_PROFILE_MAX = 3;
/** 서버 상한과 같은 값(`account_repo.LABEL_MAX_CHARS`·`MEDICATION_TEXT_MAX_CHARS`·`MEDICATION_LIMIT`) */
export const PROFILE_LABEL_MAX_CHARS = 20;
export const MEDICATION_NAME_MAX_CHARS = 100;
export const MEDICATIONS_MAX = 10;

export const SOCIAL_PROVIDERS = ["google", "kakao"] as const;
export type SocialProvider = (typeof SOCIAL_PROVIDERS)[number];

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

async function call(method: Method, path: string, json?: unknown): Promise<Response> {
  let response: Response;
  try {
    response = await apiClient(path, { method, prefix: resolveApiBase(), json, headers: { Accept: "application/json" } });
  } catch {
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
 */
export async function fetchMe(): Promise<Me | null> {
  const response = await call("get", "me");
  if (response.status === 401) return null;
  return read(response, MeSchema);
}

/** 법적 문서 한 건(현재본). 본문은 서버 값 그대로 그린다(프런트에 문구를 두지 않는다) */
export async function fetchLegalDoc(docType: LegalDocType): Promise<LegalDoc> {
  return read(await call("get", `legal/${docType}`), LegalDocSchema);
}

/** 화면에 보일 순서대로 네 문서를 받는다(동의 대상 셋 + 고지 문서 `privacy_policy`) */
export async function fetchLegalDocs(): Promise<LegalDoc[]> {
  return Promise.all(LEGAL_DOC_TYPES.map(fetchLegalDoc));
}

/** 동의·철회를 기록하고 갱신된 `Me`를 받는다. `items`는 1~3건이고 문서 종류가 겹치면 안 된다(서버 규칙) */
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

/** 가족 프로필 삭제. 본인 프로필은 서버가 409 `SELF_REQUIRED`로 막는다(계정을 지우려면 탈퇴) */
export async function deleteProfile(profileId: string): Promise<void> {
  await done(await call("delete", `profiles/${encodeURIComponent(profileId)}`));
}

/** 탈퇴 */
export async function deleteMe(): Promise<void> {
  await done(await call("delete", "me"));
}

// ---------------------------------------------------------------- 호출(백엔드 없음: MSW 목 전용. 로그인 전환 때 이 묶음만 바꾼다)
/** 백엔드 없음(목) */
export async function loginWithEmail(email: string, password: string): Promise<void> {
  await done(await call("post", "auth/email/login", { email, password }));
}

/** 백엔드 없음(목) */
export async function signupWithEmail(email: string, password: string): Promise<void> {
  await done(await call("post", "auth/email/signup", { email, password }));
}

/** 백엔드 없음(목) */
export async function logout(): Promise<void> {
  await done(await call("post", "auth/logout"));
}

/** 백엔드 없음(목): 소셜 로그인 시작 주소 */
export function socialLoginUrl(provider: SocialProvider): string {
  return `${resolveApiBase().replace(/\/+$/, "")}/auth/${provider}/start`;
}

/**
 * 백엔드 없음(목): 소셜 로그인을 시작한다.
 * - MSW 목: 워커는 페이지 이동(navigate)을 가로채지 않으므로 같은 주소를 fetch로 불러 목 세션만 만든다(`completed`).
 * - 그 밖: 시작 주소로 페이지를 옮긴다(`redirected`). 실제 백엔드에는 이 주소가 없고, 계정 진입점이 목 모드에서만 보이므로 닿지 않는 길이다.
 */
export async function startSocialLogin(provider: SocialProvider): Promise<"redirected" | "completed"> {
  if (isApiMockingEnabled()) {
    await done(await call("get", `auth/${provider}/start`));
    return "completed";
  }
  window.location.assign(socialLoginUrl(provider));
  return "redirected";
}

/**
 * 계정 진입점(`로그인/가입`·사이드바 계정 자리·`GET /api/me` 부트스트랩)을 켤지(FE-04-02 A, 사용자 결정 2026-11-19).
 * 목 모드(`NEXT_PUBLIC_API_MOCKING=enabled`)에서만 켠다: 실제 백엔드에는 아직 로그인 길이 없어 눌러도 로그인할 수 없기 때문이다.
 */
export function isAccountEntryEnabled(): boolean {
  return isApiMockingEnabled();
}

/** 스토어가 받는 API 묶음(시험에서 바꿔 끼운다) */
export interface AccountApi {
  fetchMe: typeof fetchMe;
  fetchLegalDocs: typeof fetchLegalDocs;
  postConsents: typeof postConsents;
  fetchProfiles: typeof fetchProfiles;
  createProfile: typeof createProfile;
  updateProfile: typeof updateProfile;
  deleteProfile: typeof deleteProfile;
  deleteMe: typeof deleteMe;
  loginWithEmail: typeof loginWithEmail;
  signupWithEmail: typeof signupWithEmail;
  logout: typeof logout;
  startSocialLogin: typeof startSocialLogin;
}

export const accountApi: AccountApi = {
  fetchMe,
  fetchLegalDocs,
  postConsents,
  fetchProfiles,
  createProfile,
  updateProfile,
  deleteProfile,
  deleteMe,
  loginWithEmail,
  signupWithEmail,
  logout,
  startSocialLogin,
};
