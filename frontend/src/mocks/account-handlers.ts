// MSW 핸들러: 계정·약관 동의·프로필(임시 계약, `src/lib/api/account.ts` 머리 주석). 개발·시험 전용이다.
// 세션·동의·프로필은 이 핸들러 묶음의 메모리에만 있다(페이지를 새로 열면 사라진다. 실제 서버는 쿠키 세션을 쓴다는 가정).
import { HttpResponse, http } from "msw";
import { z } from "zod";
import {
  AgeBandSchema,
  FAMILY_PROFILE_MAX,
  HEALTH_CONSENT_DOC,
  LEGAL_DOC_TYPES,
  LegalDocTypeSchema,
  MedicationSchema,
  PregnancyStatusSchema,
  RelationSchema,
  SELF_PROFILE_MAX,
  SOCIAL_PROVIDERS,
} from "@/lib/api/account";
import type { ConsentRecord, Me, Profile } from "@/lib/api/account";
import { MOCK_LEGAL_DOCS, MOCK_LOGIN_FAIL_MARK, MOCK_ONBOARDED_MARK, MOCK_SIGNUP_TAKEN_MARK } from "./fixtures/account";

const CredentialsSchema = z.object({ email: z.string().min(1), password: z.string().min(1) });
const ConsentsSchema = z.object({ items: z.array(z.object({ doc_type: LegalDocTypeSchema, version: z.string(), agreed: z.boolean() })) });
const ProfileDraftSchema = z.object({
  relation: RelationSchema,
  label: z.string(),
  age_band: AgeBandSchema.nullable().default(null),
  pregnancy_status: PregnancyStatusSchema.default("unknown"),
  medications: z.array(MedicationSchema).default([]),
});

const NOW = "2026-11-18T00:00:00Z";
const error = (status: number, code: string) => HttpResponse.json({ code, fields: [] }, { status });
const noContent = () => new HttpResponse(null, { status: 204 });

export interface AccountMockState {
  me: Me | null;
  profiles: Profile[];
}

/** 핸들러 묶음 하나가 세션 하나를 갖는다(시험마다 새로 만들면 서로 섞이지 않는다) */
export function createAccountHandlers(state: AccountMockState = { me: null, profiles: [] }) {
  let sequence = 0;

  const login = (provider: string, email = "") => {
    const onboarded = email.includes(MOCK_ONBOARDED_MARK);
    const consents: ConsentRecord[] = onboarded
      ? LEGAL_DOC_TYPES.map((docType) => ({ doc_type: docType, version: MOCK_LEGAL_DOCS[docType].version, agreed_at: NOW }))
      : [];
    state.me = { user_id: "mock-user-1", display_name: "삐약 사용자", providers: [provider], onboarding_completed_at: onboarded ? NOW : null, consents };
    state.profiles = onboarded
      ? [
          { id: "mock-profile-self", relation: "self", label: "나", age_band: "adult", pregnancy_status: "no", medications: [] },
          { id: "mock-profile-child", relation: "child", label: "첫째", age_band: "child", pregnancy_status: "unknown", medications: [] },
        ]
      : [];
  };

  const healthConsent = () => state.me?.consents.some((consent) => consent.doc_type === HEALTH_CONSENT_DOC) ?? false;
  const hasHealthData = (draft: z.infer<typeof ProfileDraftSchema>) => draft.pregnancy_status !== "unknown" || draft.medications.length > 0;

  return [
    http.get("*/api/legal/:docType", ({ params }) => {
      const docType = LegalDocTypeSchema.safeParse(params.docType);
      return docType.success ? HttpResponse.json(MOCK_LEGAL_DOCS[docType.data]) : error(404, "NOT_FOUND");
    }),

    http.get("*/api/me", () => (state.me ? HttpResponse.json(state.me) : error(401, "UNAUTHENTICATED"))),

    http.delete("*/api/me", () => {
      if (!state.me) return error(401, "UNAUTHENTICATED");
      state.me = null;
      state.profiles = [];
      return noContent();
    }),

    http.post("*/api/auth/email/login", async ({ request }) => {
      const body = CredentialsSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      if (body.data.email.includes(MOCK_LOGIN_FAIL_MARK)) return error(401, "INVALID_CREDENTIALS");
      login("email", body.data.email);
      return noContent();
    }),

    http.post("*/api/auth/email/signup", async ({ request }) => {
      const body = CredentialsSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      if (body.data.email.includes(MOCK_SIGNUP_TAKEN_MARK)) return error(409, "EMAIL_TAKEN");
      login("email");
      return noContent();
    }),

    http.post("*/api/auth/logout", () => {
      state.me = null;
      state.profiles = [];
      return noContent();
    }),

    // 소셜 로그인 시작: 실제로는 페이지 이동이다. 목에서는 fetch로 불려 세션만 만든다(Naver는 준비 중이라 없다)
    http.get("*/api/auth/:provider/start", ({ params }) => {
      const provider = String(params.provider);
      if (!(SOCIAL_PROVIDERS as readonly string[]).includes(provider)) return error(404, "NOT_FOUND");
      login(provider);
      return noContent();
    }),

    http.post("*/api/consents", async ({ request }) => {
      if (!state.me) return error(401, "UNAUTHENTICATED");
      const body = ConsentsSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      const agreed = new Set(body.data.items.filter((item) => item.agreed && item.version === MOCK_LEGAL_DOCS[item.doc_type].version).map((item) => item.doc_type));
      if (LEGAL_DOC_TYPES.some((docType) => MOCK_LEGAL_DOCS[docType].required && !agreed.has(docType))) return error(422, "REQUIRED_CONSENT_MISSING");
      state.me = {
        ...state.me,
        onboarding_completed_at: state.me.onboarding_completed_at ?? NOW,
        consents: LEGAL_DOC_TYPES.filter((docType) => agreed.has(docType)).map((docType) => ({ doc_type: docType, version: MOCK_LEGAL_DOCS[docType].version, agreed_at: NOW })),
      };
      return noContent();
    }),

    http.get("*/api/profiles", () => (state.me ? HttpResponse.json(state.profiles) : error(401, "UNAUTHENTICATED"))),

    http.post("*/api/profiles", async ({ request }) => {
      if (!state.me) return error(401, "UNAUTHENTICATED");
      const body = ProfileDraftSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      const sameKind = state.profiles.filter((profile) => (profile.relation === "self") === (body.data.relation === "self")).length;
      // 본인 1 + 가족 3: 넘치면 422
      if (sameKind >= (body.data.relation === "self" ? SELF_PROFILE_MAX : FAMILY_PROFILE_MAX)) return error(422, "PROFILE_LIMIT");
      if (hasHealthData(body.data) && !healthConsent()) return error(422, "HEALTH_CONSENT_REQUIRED");
      sequence += 1;
      const profile: Profile = { id: `mock-profile-${sequence}`, ...body.data };
      state.profiles = [...state.profiles, profile];
      return HttpResponse.json(profile, { status: 201 });
    }),

    http.patch("*/api/profiles/:id", async ({ params, request }) => {
      if (!state.me) return error(401, "UNAUTHENTICATED");
      const body = ProfileDraftSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return error(422, "INVALID_REQUEST");
      if (!state.profiles.some((profile) => profile.id === params.id)) return error(404, "NOT_FOUND");
      if (hasHealthData(body.data) && !healthConsent()) return error(422, "HEALTH_CONSENT_REQUIRED");
      const profile: Profile = { id: String(params.id), ...body.data };
      state.profiles = state.profiles.map((item) => (item.id === profile.id ? profile : item));
      return HttpResponse.json(profile);
    }),

    http.delete("*/api/profiles/:id", ({ params }) => {
      if (!state.me) return error(401, "UNAUTHENTICATED");
      state.profiles = state.profiles.filter((profile) => profile.id !== params.id);
      return noContent();
    }),
  ];
}
