// 계정·약관 동의·프로필 API를 감싸는 한 모듈(FE-04). 화면과 스토어는 이 파일의 함수만 부른다.
//
// ⚠ 이 계약은 **임시(가정)** 다. 백엔드 설계 문서(`P2-doc/PJ2-계정-프로필-데이터.md`)와 인증 방식(백엔드 경유 vs Supabase JS 직접)이
// 확정되기 전이라 MSW 목(`src/mocks/account-handlers.ts`)으로만 구현돼 있다. 계약이 확정되면 **이 파일만** 바꾼다.
// 브라우저는 같은 출처의 `/api/*`만 부르고(rewrites 경유 백엔드), `NEXT_PUBLIC_*`에 어떤 키도 넣지 않는다(Supabase JS를 브라우저에 직접 붙이지 않는다).
//
// 지시서가 준 임시 계약(2026-11-18 goal 지시서 그대로):
// - `GET /api/legal/{doc_type}` → `{doc_type, version, title, body_md, effective_at, required}`
//   (`doc_type`: `terms`·`privacy`·`sensitive_health`·`external_ai`)
// - `GET /api/me` → 비로그인 401 / 로그인 `{user_id, display_name, providers[], onboarding_completed_at, consents[{doc_type, version, agreed_at}]}`
// - `POST /api/consents` `{items:[{doc_type, version, agreed:boolean}]}`
// - `GET/POST/PATCH/DELETE /api/profiles` — `{id, relation, label, age_band, pregnancy_status, medications[{drug_name, item_seq|null}]}`,
//   본인 1 + 가족 최대 3(4개째 추가 시 서버 422 목)
// - `DELETE /api/me`(탈퇴)
// - 로그인 버튼은 `/api/auth/{provider}/start`로 이동
//
// 이 모듈이 더한 가정(지시서에 없어 구현하며 정한 것. 보고에 같은 목록이 있다):
// - `POST /api/auth/email/login` `{email, password}` → 2xx / 401, `POST /api/auth/email/signup` `{email, password}` → 2xx / 409, `POST /api/auth/logout` → 2xx
// - 세션은 서버가 쿠키로 들고 있고 화면은 `GET /api/me`로만 로그인 여부를 안다(토큰을 브라우저 저장소에 두지 않는다)
// - `GET /api/profiles`는 배열, `POST`는 만든 프로필, `PATCH /api/profiles/{id}`는 고친 프로필, `DELETE /api/profiles/{id}`는 본문 없음
// - `relation`: `self`·`child`·`parent`·`spouse`·`other`, `pregnancy_status`: `unknown`·`no`·`yes`
// - `age_band`: `infant`(만 2세 미만)·`child`(만 2~11세)·`teen`(만 12~18세)·`adult`(만 19~64세)·`senior`(만 65세 이상), 고르지 않으면 null
// - 법적 문서 응답의 선택 칸 `declined_notice`: 동의하지 않았을 때 화면에 보일 한 줄(있으면 그대로 쓴다)
// - 오류 본문은 `/chat`과 같은 `{code, fields}`. 목의 코드: `PROFILE_LIMIT`·`HEALTH_CONSENT_REQUIRED`·`REQUIRED_CONSENT_MISSING`·`EMAIL_TAKEN`·`INVALID_CREDENTIALS`
// - 필수 문서에 모두 동의하면 서버가 `onboarding_completed_at`을 채운다
import { z } from "zod";
import { isApiMockingEnabled } from "@/mocks";
import { apiClient, resolveApiBase } from "./client";

// ---------------------------------------------------------------- 모양(zod). 계약이 임시라 모르는 칸은 버린다(strict 아님)
export const LEGAL_DOC_TYPES = ["terms", "privacy", "sensitive_health", "external_ai"] as const;
export const LegalDocTypeSchema = z.enum(LEGAL_DOC_TYPES);
export type LegalDocType = z.infer<typeof LegalDocTypeSchema>;
/** 건강 정보(임신 여부·복용 약) 입력·저장을 여는 선택 동의 */
export const HEALTH_CONSENT_DOC: LegalDocType = "sensitive_health";

export const LegalDocSchema = z.object({
  doc_type: LegalDocTypeSchema,
  version: z.string().min(1),
  title: z.string().min(1),
  body_md: z.string(),
  effective_at: z.string(),
  required: z.boolean(),
  declined_notice: z.string().nullable().default(null),
});
export type LegalDoc = z.infer<typeof LegalDocSchema>;

export const ConsentRecordSchema = z.object({ doc_type: LegalDocTypeSchema, version: z.string(), agreed_at: z.string() });
export type ConsentRecord = z.infer<typeof ConsentRecordSchema>;

export const MeSchema = z.object({
  user_id: z.string().min(1),
  display_name: z.string(),
  providers: z.array(z.string()).default([]),
  onboarding_completed_at: z.string().nullable().default(null),
  consents: z.array(ConsentRecordSchema).default([]),
});
export type Me = z.infer<typeof MeSchema>;

export const RELATIONS = ["self", "child", "parent", "spouse", "other"] as const;
export const RelationSchema = z.enum(RELATIONS);
export type Relation = z.infer<typeof RelationSchema>;

export const AGE_BANDS = ["infant", "child", "teen", "adult", "senior"] as const;
export const AgeBandSchema = z.enum(AGE_BANDS);
export type AgeBand = z.infer<typeof AgeBandSchema>;

export const PREGNANCY_STATUSES = ["unknown", "no", "yes"] as const;
export const PregnancyStatusSchema = z.enum(PREGNANCY_STATUSES);
export type PregnancyStatus = z.infer<typeof PregnancyStatusSchema>;

/** 복용 중인 약: 사용자가 적은 글자 그대로(`drug_name`). 품목 번호는 서버가 붙일 수 있는 자리이고 화면은 null로 보낸다 */
export const MedicationSchema = z.object({ drug_name: z.string().min(1), item_seq: z.string().nullable().default(null) });
export type Medication = z.infer<typeof MedicationSchema>;

export const ProfileSchema = z.object({
  id: z.string().min(1),
  relation: RelationSchema,
  label: z.string(),
  age_band: AgeBandSchema.nullable().default(null),
  pregnancy_status: PregnancyStatusSchema.default("unknown"),
  medications: z.array(MedicationSchema).default([]),
});
export type Profile = z.infer<typeof ProfileSchema>;
/** 만들거나 고칠 때 보내는 값(id 없음) */
export type ProfileDraft = Omit<Profile, "id">;

export interface ConsentItem {
  doc_type: LegalDocType;
  version: string;
  agreed: boolean;
}

/** 본인 1 + 가족 최대 3(사용자 결정 2026-11-18) */
export const SELF_PROFILE_MAX = 1;
export const FAMILY_PROFILE_MAX = 3;
/** 화면 입력 상한(가정: 서버 상한이 정해지면 그 값으로 바꾼다) */
export const PROFILE_LABEL_MAX_CHARS = 20;
export const MEDICATION_NAME_MAX_CHARS = 60;
export const MEDICATIONS_MAX = 20;

export const SOCIAL_PROVIDERS = ["google", "kakao"] as const;
export type SocialProvider = (typeof SOCIAL_PROVIDERS)[number];

// ---------------------------------------------------------------- 오류
export type AccountErrorKind = "network" | "http" | "invalid";

/** 계정 API 실패. 입력 값(이메일·비밀번호·프로필)은 싣지 않는다 */
export class AccountApiError extends Error {
  constructor(
    readonly kind: AccountErrorKind,
    readonly status: number,
    readonly code: string | null,
  ) {
    super(`account api ${kind} ${status}`);
    this.name = "AccountApiError";
  }
}

const ErrorCodeBodySchema = z.object({ code: z.string() });

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
  const body = ErrorCodeBodySchema.safeParse(await response.json().catch(() => null));
  throw new AccountApiError("http", response.status, body.success ? body.data.code : null);
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

// ---------------------------------------------------------------- 호출
/** 로그인한 사용자. 비로그인(401)이면 null */
export async function fetchMe(): Promise<Me | null> {
  const response = await call("get", "me");
  if (response.status === 401) return null;
  return read(response, MeSchema);
}

/** 법적 문서 한 건(현재 버전). 본문은 서버 값 그대로 그린다(프런트에 문구를 두지 않는다) */
export async function fetchLegalDoc(docType: LegalDocType): Promise<LegalDoc> {
  return read(await call("get", `legal/${docType}`), LegalDocSchema);
}

/** 화면에 보일 순서대로 네 문서를 받는다 */
export async function fetchLegalDocs(): Promise<LegalDoc[]> {
  return Promise.all(LEGAL_DOC_TYPES.map(fetchLegalDoc));
}

export async function postConsents(items: ConsentItem[]): Promise<void> {
  await done(await call("post", "consents", { items }));
}

export async function fetchProfiles(): Promise<Profile[]> {
  return read(await call("get", "profiles"), z.array(ProfileSchema));
}

export async function createProfile(draft: ProfileDraft): Promise<Profile> {
  return read(await call("post", "profiles", draft), ProfileSchema);
}

export async function updateProfile(id: string, draft: ProfileDraft): Promise<Profile> {
  return read(await call("patch", `profiles/${encodeURIComponent(id)}`, draft), ProfileSchema);
}

export async function deleteProfile(id: string): Promise<void> {
  await done(await call("delete", `profiles/${encodeURIComponent(id)}`));
}

/** 탈퇴 */
export async function deleteMe(): Promise<void> {
  await done(await call("delete", "me"));
}

export async function loginWithEmail(email: string, password: string): Promise<void> {
  await done(await call("post", "auth/email/login", { email, password }));
}

export async function signupWithEmail(email: string, password: string): Promise<void> {
  await done(await call("post", "auth/email/signup", { email, password }));
}

export async function logout(): Promise<void> {
  await done(await call("post", "auth/logout"));
}

/** 소셜 로그인 시작 주소(rewrites 경유 백엔드). 화면은 이 주소로 **이동**한다 */
export function socialLoginUrl(provider: SocialProvider): string {
  return `${resolveApiBase().replace(/\/+$/, "")}/auth/${provider}/start`;
}

/**
 * 소셜 로그인을 시작한다.
 * - 실제: 시작 주소로 페이지를 옮긴다(`redirected`). 돌아온 뒤 화면이 `GET /api/me`로 로그인 상태를 읽는다.
 * - MSW 목: 워커는 페이지 이동(navigate)을 가로채지 않으므로 같은 주소를 fetch로 불러 목 세션만 만든다(`completed`).
 */
export async function startSocialLogin(provider: SocialProvider): Promise<"redirected" | "completed"> {
  if (isApiMockingEnabled()) {
    await done(await call("get", `auth/${provider}/start`));
    return "completed";
  }
  window.location.assign(socialLoginUrl(provider));
  return "redirected";
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
