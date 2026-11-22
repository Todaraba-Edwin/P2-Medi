// MSW 핸들러: 계정·약관 동의·프로필. 개발·시험 전용이다.
// 응답·오류 모양과 규칙은 백엔드 코드(`backend/app/api/me.py`·`account.py`, BE-11)를 따른다: 경로, `MeResponse`·`ProfileOut`,
// 오류 본문 `{code, fields}`와 코드, 본인 1 + 가족 3, 건강 정보 동의, 철회 시 즉시 삭제.
// **백엔드 없음**: `/api/auth/*`(이메일 로그인·가입, 로그아웃, 소셜 시작)과 세션. 실제는 Bearer 토큰이고 여기서는 핸들러 메모리의 세션으로 흉내 낸다
// (세션·동의·프로필은 이 핸들러 묶음의 메모리에만 있다. 페이지를 새로 열면 사라진다).
import { HttpResponse, delay, http } from "msw";
import { z } from "zod";
import {
  AGE_14_DOC,
  AgeBandSchema,
  CONSENT_DOC_TYPES,
  ConsentDocTypeSchema,
  FAMILY_PROFILE_MAX,
  HEALTH_CONSENT_DOC,
  LegalDocTypeSchema,
  MEDICATIONS_MAX,
  MEDICATION_NAME_MAX_CHARS,
  PROFILE_LABEL_MAX_CHARS,
  PregnancyStatusSchema,
  REQUIRED_CONSENT_DOCS,
  RelationSchema,
  SOCIAL_PROVIDERS,
  SexSchema,
} from "@/lib/api/account";
import type { ConsentDocType, ConsentState, Me, Medication, OnboardingStep, Profile, SocialProvider } from "@/lib/api/account";
import {
  MOCK_DRUG_ITEM_SEQS,
  MOCK_DRUG_SEARCH_ERRORS,
  MOCK_DRUG_SEARCH_SLOW_MARK,
  MOCK_DRUG_SEARCH_SLOW_MS,
  MOCK_GOOGLE_NAME,
  MOCK_KAKAO_NICKNAME,
  MOCK_LEGAL_DOCS,
  MOCK_LOGIN_FAIL_MARK,
  MOCK_ONBOARDED_MARK,
  MOCK_SIGNUP_TAKEN_MARK,
  searchMockDrugs,
} from "./fixtures/account";

const CredentialsSchema = z.object({ email: z.string().min(1), password: z.string().min(1) });
/** `DrugSearchIn`(백엔드 `drugs.py`): 앞뒤 공백 제거 뒤 1~100자, 다른 칸은 422 */
const DrugSearchInSchema = z.strictObject({ q: z.string().trim().min(1).max(MEDICATION_NAME_MAX_CHARS) });
// 요청 모델(백엔드 `_Strict`: 모르는 칸은 422)
const ConsentRequestSchema = z.strictObject({
  items: z
    .array(z.strictObject({ doc_type: ConsentDocTypeSchema, version: z.number().int().min(1), action: z.enum(["agree", "withdraw"]) }))
    .min(1)
    .max(CONSENT_DOC_TYPES.length) // 첫 로그인 4종을 한 번에
    .refine((items) => new Set(items.map((item) => item.doc_type)).size === items.length),
  channel: z.enum(["onboarding", "settings", "reconsent"]),
});
const MedicationInSchema = z.strictObject({ input_text: z.string().trim().min(1).max(MEDICATION_NAME_MAX_CHARS), item_seq: z.string().regex(/^\d{9}$/).nullable().optional() });
const profileFields = {
  label: z.string().trim().min(1).max(PROFILE_LABEL_MAX_CHARS).nullable().optional(),
  age_band: AgeBandSchema.nullable().optional(),
  /** 성별(선택, 건강 정보 아님): 잘못된 값은 백엔드처럼 422 `INVALID_REQUEST`(fields=["sex"], 값은 되돌려 주지 않는다) */
  sex: SexSchema.nullable().optional(),
  pregnancy_status: PregnancyStatusSchema.nullable().optional(),
};
/** 본문 전체가 422일 때 백엔드처럼 칸 이름만 돌려준다(`sex`가 잘못됐으면 `["sex"]`, 그 밖은 `["body"]`) */
const invalidFields = (issues: z.ZodError["issues"]) => (issues.some((issue) => issue.path[0] === "sex") ? ["sex"] : ["body"]);
const ProfileCreateSchema = z.strictObject({ relation: RelationSchema, ...profileFields, medications: z.array(MedicationInSchema).max(MEDICATIONS_MAX).optional() });
// `relation`·`medications`는 보낼 수는 있지만 null일 수 없다(백엔드 `_no_null_required`)
const ProfileUpdateSchema = z.strictObject({ relation: RelationSchema.optional(), ...profileFields, medications: z.array(MedicationInSchema).max(MEDICATIONS_MAX).optional() });
const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const NOW = "2026-11-18T00:00:00Z";
const NO_STORE = { "Cache-Control": "no-store" };
const error = (status: number, code: string, fields: string[] = []) => HttpResponse.json({ code, fields }, { status, headers: NO_STORE });
const noContent = () => new HttpResponse(null, { status: 204, headers: NO_STORE });
/** 합성 UUID(모양만 맞춘 값) */
const mockId = (group: number, sequence: number) => `00000000-0000-4000-8000-${String(group).padStart(4, "0")}${String(sequence).padStart(8, "0")}`;
const MOCK_USER_ID = mockId(0, 1);

interface ConsentRecord {
  action: "agree" | "withdraw";
  version: number;
  acted_at: string;
}

/** 목 세션의 로그인 공급자(실제는 Supabase `app_metadata.provider`). 이메일 로그인·가입은 `email` */
export type MockProvider = SocialProvider | "email";

interface Session {
  provider: MockProvider;
  step: OnboardingStep;
  completedAt: string | null;
  consents: Partial<Record<ConsentDocType, ConsentRecord>>;
  profiles: Profile[];
}

export interface AccountMockState {
  /** 로그인한 목 세션. 없으면 게스트다(실제의 "토큰 없음"에 해당) */
  session: Session | null;
}

/** 목 세션의 시작 상태: `new`는 막 로그인해 동의 전, `onboarded`는 동의·프로필을 마친 사용자 */
export type MockSessionKind = "new" | "onboarded";

/** 페이지를 열 때 목 세션을 미리 만드는 주소 표시(브라우저 워커 전용, `browser.ts`): `?mock_session=new|onboarded`. 로그인 콜백 복귀 e2e가 쓴다 */
export const MOCK_SESSION_PARAM = "mock_session";
/** 미리 만드는 목 세션의 공급자 `?mock_provider=google|kakao`(없으면 `email`). 카카오 닉네임 초기값(FE-04-28 B) e2e가 쓴다 */
export const MOCK_PROVIDER_PARAM = "mock_provider";

export function mockSession(kind: MockSessionKind, provider: MockProvider = "email"): Session {
  const session: Session = { provider, step: "consent", completedAt: null, consents: {}, profiles: [] };
  if (kind === "onboarded") {
    for (const docType of CONSENT_DOC_TYPES) session.consents[docType] = { action: "agree", version: MOCK_LEGAL_DOCS[docType].version, acted_at: NOW };
    // 성별은 로그인 공급자 정보가 아니라 사용자가 고른 값이다(목에서는 미리 저장돼 있던 값으로 둔다)
    session.profiles = [
      { profile_id: mockId(1, 9001), relation: "self", label: "나", age_band: "y19_64", sex: "female", pregnancy_status: "not_pregnant", sort_order: 0, medications: [] },
      { profile_id: mockId(1, 9002), relation: "child", label: "첫째", age_band: "y6_11", sex: null, pregnancy_status: null, sort_order: 1, medications: [] },
    ];
  }
  return session;
}

/** 주소의 `mock_session` 값으로 시작 세션을 정한다. 없거나 모르는 값이면 게스트 */
export function initialMockAccountState(search: string): AccountMockState {
  const params = new URLSearchParams(search);
  const value = params.get(MOCK_SESSION_PARAM);
  const provider = params.get(MOCK_PROVIDER_PARAM);
  const mockProvider: MockProvider = (SOCIAL_PROVIDERS as readonly string[]).includes(provider ?? "") ? (provider as SocialProvider) : "email";
  return { session: value === "new" || value === "onboarded" ? mockSession(value, mockProvider) : null };
}

/** 핸들러 묶음 하나가 세션 하나를 갖는다(시험마다 새로 만들면 서로 섞이지 않는다) */
export function createAccountHandlers(state: AccountMockState = { session: null }) {
  let sequence = 0;
  const nextId = (group: number) => mockId(group, (sequence += 1));

  const consentStates = (session: Session): ConsentState[] =>
    CONSENT_DOC_TYPES.map((docType) => {
      const record = session.consents[docType];
      const agreed = record?.action === "agree";
      const current = MOCK_LEGAL_DOCS[docType];
      return {
        doc_type: docType,
        required: current.required,
        agreed_version: agreed ? record.version : null,
        acted_at: record?.acted_at ?? null,
        current_version: current.version,
        needs_consent: !agreed,
        needs_reconsent: false, // 목 문서는 버전이 하나뿐이다
      };
    });
  const agreedTo = (session: Session, docType: ConsentDocType) => session.consents[docType]?.action === "agree";
  /** 백엔드 `required_ok`: 약관·개인정보·만 14세 확인(`REQUIRED_CONSENT_DOCS`)에 모두 동의해야 동의 단계를 지난다 */
  const requiredOk = (session: Session) => REQUIRED_CONSENT_DOCS.every((docType) => agreedTo(session, docType));
  const healthOk = (session: Session) => agreedTo(session, HEALTH_CONSENT_DOC);

  /** 백엔드 `next_step`과 같은 규칙 */
  const syncOnboarding = (session: Session) => {
    const hasSelf = session.profiles.some((profile) => profile.relation === "self");
    const family = session.profiles.filter((profile) => profile.relation !== "self").length;
    const step: OnboardingStep = !requiredOk(session)
      ? "consent"
      : !hasSelf
        ? "profile_self"
        : family >= FAMILY_PROFILE_MAX
          ? "done"
          : session.step === "consent" || session.step === "profile_self"
            ? "family"
            : session.step;
    session.step = step;
    session.completedAt = step === "done" ? (session.completedAt ?? NOW) : null;
  };

  const me = (session: Session): Me => {
    syncOnboarding(session);
    return {
      user_id: MOCK_USER_ID,
      is_guest: false,
      onboarding_step: session.step,
      onboarding_completed_at: session.completedAt,
      consents: consentStates(session),
      health_consent_active: healthOk(session),
      profile_limit: 1 + FAMILY_PROFILE_MAX,
    };
  };

  const medications = (items: z.infer<typeof MedicationInSchema>[]): Medication[] =>
    // 백엔드 `dict_item_seq_checker`처럼 사전에 있는 품목 번호만 남기고(확인 시각을 붙인다) 없는 번호는 버려 원문만 저장한다
    items.map((item) => {
      const confirmed = item.item_seq != null && MOCK_DRUG_ITEM_SEQS.has(item.item_seq);
      return { medication_id: nextId(2), input_text: item.input_text, item_seq: confirmed ? item.item_seq! : null, confirmed_at: confirmed ? NOW : null };
    });

  const login = (email = "", provider: MockProvider = "email") => {
    state.session = mockSession(email.includes(MOCK_ONBOARDED_MARK) ? "onboarded" : "new", provider);
  };

  /** 프로필 쓰기 앞의 필수 동의 검사(백엔드 `gate_consents`: 약관·개인정보·만 14세 확인) */
  const gate = (session: Session) => {
    const missing = REQUIRED_CONSENT_DOCS.filter((docType) => !agreedTo(session, docType));
    return missing.length > 0 ? error(403, "CONSENT_REQUIRED", [...missing]) : null;
  };

  return [
    // 약관·동의 문서 현재본(게스트 허용)
    http.get("*/api/legal/:docType", ({ params }) => {
      const docType = LegalDocTypeSchema.safeParse(params.docType);
      if (!docType.success) return error(422, "INVALID_REQUEST", ["doc_type"]);
      return HttpResponse.json(MOCK_LEGAL_DOCS[docType.data], { headers: { "Cache-Control": "public, max-age=300" } });
    }),

    http.get("*/api/me", () => (state.session ? HttpResponse.json(me(state.session), { headers: NO_STORE }) : error(401, "AUTH_REQUIRED"))),

    http.delete("*/api/me", () => {
      if (!state.session) return error(401, "AUTH_REQUIRED");
      state.session = null;
      return noContent();
    }),

    // ---- 백엔드 없음: 로그인·가입·로그아웃·소셜 시작(Supabase Auth가 맡을 자리)
    http.post("*/api/auth/email/login", async ({ request }) => {
      const body = CredentialsSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      if (body.data.email.includes(MOCK_LOGIN_FAIL_MARK)) return error(401, "INVALID_CREDENTIALS");
      login(body.data.email);
      return noContent();
    }),

    http.post("*/api/auth/email/signup", async ({ request }) => {
      const body = CredentialsSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      if (body.data.email.includes(MOCK_SIGNUP_TAKEN_MARK)) return error(409, "EMAIL_TAKEN");
      login();
      return noContent();
    }),

    http.post("*/api/auth/logout", () => {
      state.session = null;
      return noContent();
    }),

    // 소셜 로그인 시작: 실제로는 페이지 이동이다. 목에서는 fetch로 불려 세션만 만든다(Naver는 준비 중이라 없다)
    http.get("*/api/auth/:provider/start", ({ params }) => {
      if (!(SOCIAL_PROVIDERS as readonly string[]).includes(String(params.provider))) return error(404, "NOT_FOUND");
      login("", params.provider as SocialProvider);
      return noContent();
    }),

    // 목 전용(실제 백엔드에 없다): 로그인 공급자와 공급자가 준 표시 이름. 실제는 Supabase 세션의 `app_metadata.provider`·`user_metadata.name`이다.
    // 카카오만 닉네임을 본인 프로필 이름 칸 초기값으로 쓰는 규칙(FE-04-28 B)은 여기가 아니라 `lib/api/account.ts`에 있다(구글 이름도 돌려주되 화면은 쓰지 않는다)
    http.get("*/api/auth/identity", () => {
      const session = state.session;
      if (!session) return error(401, "AUTH_REQUIRED");
      const name = session.provider === "kakao" ? MOCK_KAKAO_NICKNAME : session.provider === "google" ? MOCK_GOOGLE_NAME : null;
      return HttpResponse.json({ provider: session.provider, name }, { headers: NO_STORE });
    }),

    // ---- 동의·철회 기록 → 201 Me
    http.post("*/api/consents", async ({ request }) => {
      const session = state.session;
      if (!session) return error(401, "AUTH_REQUIRED");
      const body = ConsentRequestSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST", ["body"]);
      for (const item of body.data.items) {
        if (MOCK_LEGAL_DOCS[item.doc_type].version !== item.version) return error(409, "VERSION_MISMATCH", [item.doc_type]);
        // 약관·만 14세 확인 철회는 탈퇴로만(백엔드 `WITHDRAW_BLOCKED_DOCS`)
        if (item.action === "withdraw" && (item.doc_type === "terms" || item.doc_type === AGE_14_DOC)) return error(409, "USE_ACCOUNT_DELETE", [item.doc_type]);
      }
      for (const item of body.data.items) {
        session.consents[item.doc_type] = { action: item.action, version: item.version, acted_at: NOW };
        if (item.action !== "withdraw") continue;
        // 철회는 즉시 삭제를 일으킨다(설계 6.3절): 건강 동의 → 임신 여부·복용 약(성별은 건강 정보가 아니라 남는다), 개인정보 동의 → 프로필 전부
        if (item.doc_type === HEALTH_CONSENT_DOC) session.profiles = session.profiles.map((profile) => ({ ...profile, pregnancy_status: null, medications: [] }));
        if (item.doc_type === "privacy_consent") session.profiles = [];
      }
      return HttpResponse.json(me(session), { status: 201, headers: NO_STORE });
    }),

    // ---- 프로필 약 이름 검색(FE-04-13 A·FE-04-21 A: POST 본문 `{q}`, 로그인 필요, 질문은 되돌려 주지 않는다). GET은 405(백엔드와 같다)
    http.post("*/api/drugs/search", async ({ request }) => {
      if (!state.session) return error(401, "AUTH_REQUIRED");
      const body = DrugSearchInSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST", ["q"]);
      const forced = MOCK_DRUG_SEARCH_ERRORS.find(([mark]) => body.data.q.includes(mark));
      if (forced) return error(forced[1], forced[2], forced[2] === "INVALID_REQUEST" ? ["q"] : []);
      if (body.data.q.includes(MOCK_DRUG_SEARCH_SLOW_MARK)) await delay(MOCK_DRUG_SEARCH_SLOW_MS); // 느린 서버 흉내(FE-04-24 A e2e)
      return HttpResponse.json(searchMockDrugs(body.data.q), { headers: NO_STORE });
    }),
    http.get("*/api/drugs/search", () => new HttpResponse(null, { status: 405, headers: NO_STORE })),

    http.get("*/api/profiles", () => (state.session ? HttpResponse.json(state.session.profiles, { headers: NO_STORE }) : error(401, "AUTH_REQUIRED"))),

    http.post("*/api/profiles", async ({ request }) => {
      const session = state.session;
      if (!session) return error(401, "AUTH_REQUIRED");
      const body = ProfileCreateSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST", invalidFields(body.error.issues));
      const blocked = gate(session);
      if (blocked) return blocked;
      const draft = body.data;
      const meds = draft.medications ?? [];
      const health = [...(draft.pregnancy_status != null ? ["pregnancy_status"] : []), ...(meds.length > 0 ? ["medications"] : [])];
      if (health.length > 0 && !healthOk(session)) return error(422, "HEALTH_CONSENT_REQUIRED", health);
      // 본인 1 + 가족 3: 본인 2개째는 409, 가족 4명째는 422
      if (draft.relation === "self" && session.profiles.some((profile) => profile.relation === "self")) return error(409, "SELF_EXISTS", ["relation"]);
      if (draft.relation !== "self" && session.profiles.filter((profile) => profile.relation !== "self").length >= FAMILY_PROFILE_MAX) return error(422, "PROFILE_LIMIT", ["relation"]);
      const profile: Profile = {
        profile_id: nextId(1),
        relation: draft.relation,
        label: draft.label ?? null,
        age_band: draft.age_band ?? null,
        sex: draft.sex ?? null,
        pregnancy_status: draft.pregnancy_status ?? null,
        sort_order: session.profiles.length,
        medications: medications(meds),
      };
      session.profiles = [...session.profiles, profile];
      return HttpResponse.json(profile, { status: 201, headers: NO_STORE });
    }),

    // 보낸 칸만 바꾼다. null은 지움. `medications`를 보내면 목록 전체 교체
    http.patch("*/api/profiles/:profileId", async ({ params, request }) => {
      const session = state.session;
      if (!session) return error(401, "AUTH_REQUIRED");
      const profileId = String(params.profileId);
      if (!UUID_SHAPE.test(profileId)) return error(422, "INVALID_REQUEST", ["profile_id"]);
      const body = ProfileUpdateSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST", invalidFields(body.error.issues));
      const current = session.profiles.find((profile) => profile.profile_id === profileId);
      if (!current) return error(404, "NOT_FOUND");
      const blocked = gate(session);
      if (blocked) return blocked;
      const patch = body.data;
      if (patch.relation !== undefined && patch.relation !== current.relation && (patch.relation === "self" || current.relation === "self")) return error(409, "SELF_FIXED", ["relation"]);
      const health = [
        ...(patch.pregnancy_status != null && patch.pregnancy_status !== current.pregnancy_status ? ["pregnancy_status"] : []),
        ...(patch.medications !== undefined && patch.medications.length > 0 ? ["medications"] : []),
      ];
      if (health.length > 0 && !healthOk(session)) return error(422, "HEALTH_CONSENT_REQUIRED", health);
      const next: Profile = {
        ...current,
        relation: patch.relation ?? current.relation,
        label: patch.label !== undefined ? patch.label : current.label,
        age_band: patch.age_band !== undefined ? patch.age_band : current.age_band,
        sex: patch.sex !== undefined ? patch.sex : current.sex, // 보낸 경우에만 바뀐다. null = 지움
        pregnancy_status: patch.pregnancy_status !== undefined ? patch.pregnancy_status : current.pregnancy_status,
        medications: patch.medications !== undefined ? medications(patch.medications) : current.medications,
      };
      session.profiles = session.profiles.map((profile) => (profile.profile_id === profileId ? next : profile));
      return HttpResponse.json(next, { headers: NO_STORE });
    }),

    http.delete("*/api/profiles/:profileId", ({ params }) => {
      const session = state.session;
      if (!session) return error(401, "AUTH_REQUIRED");
      const profileId = String(params.profileId);
      if (!UUID_SHAPE.test(profileId)) return error(422, "INVALID_REQUEST", ["profile_id"]);
      const current = session.profiles.find((profile) => profile.profile_id === profileId);
      if (!current) return error(404, "NOT_FOUND");
      if (current.relation === "self") return error(409, "SELF_REQUIRED"); // 본인 프로필은 지우지 않는다(계정 삭제는 탈퇴)
      session.profiles = session.profiles.filter((profile) => profile.profile_id !== profileId);
      return noContent();
    }),
  ];
}
