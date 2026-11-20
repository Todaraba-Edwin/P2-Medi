import { readFileSync } from "node:fs";
import path from "node:path";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AGE_BANDS,
  AccountApiError,
  CONSENT_DOC_TYPES,
  FAMILY_PROFILE_MAX,
  LEGAL_DOC_TYPES,
  MEDICATIONS_MAX,
  MEDICATION_NAME_MAX_CHARS,
  PREGNANCY_STATUSES,
  PROFILE_LABEL_MAX_CHARS,
  RELATIONS,
  accountApi,
  createProfile,
  deleteProfile,
  fetchLegalDocs,
  fetchMe,
  fetchProfiles,
  isAccountEntryEnabled,
  postConsents,
  socialLoginUrl,
  updateProfile,
} from "@/lib/api/account";
import type { Me, Profile, ProfileDraft } from "@/lib/api/account";
import { AGE_BAND_LABELS } from "@/features/account/copy";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_LEGAL_DOCS, MOCK_LOGIN_FAIL_MARK, MOCK_ONBOARDED_MARK } from "@/mocks/fixtures/account";
import { canAddFamily, canAddSelf, consentChannel, consentItems, createAccountStore, hasHealthConsent, needsConsentStep, requiredAgreed, selectTargetProfile } from "./account";
import type { ConsentChoices } from "./account";
import { buildChatRequest, emptyConversationContext } from "./conversation-context";
import { AGE_BAND_RANGE, profileToContext } from "./profile-context";

// 계정 스토어 + API 모듈(BE-11 계약) + MSW 목을 함께 본다(실제 서버 호출 0). 시험마다 목 세션을 새로 만든다.
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  server.use(...createAccountHandlers());
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled"); // 소셜 로그인을 페이지 이동이 아니라 목 호출로
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());

const ALL: ConsentChoices = { terms: true, privacy_consent: true, sensitive_consent: true };
const REQUIRED_ONLY: ConsentChoices = { terms: true, privacy_consent: true, sensitive_consent: false };
const NO_HEALTH = { pregnancy_status: null, medications: [] };
const family = (label: string, extra: Partial<ProfileDraft> = {}): ProfileDraft => ({ relation: "child", label, age_band: "y6_11", health: null, ...extra });
const selfDraft = (extra: Partial<ProfileDraft> = {}): ProfileDraft => ({ relation: "self", label: "나", age_band: "y19_64", health: null, ...extra });
const med = (text: string) => ({ input_text: text, item_seq: null });
const consentOf = (me: Me | null, docType: string) => me?.consents.find((consent) => consent.doc_type === docType);

async function loggedIn(agreed: ConsentChoices = ALL) {
  const store = createAccountStore();
  store.getState().open();
  expect(await store.getState().loginEmail("user@example.com", "pw")).toBe(true);
  await store.getState().loadLegalDocs();
  expect(await store.getState().submitConsents(agreed)).toBe(true);
  return store;
}

describe("계약 값은 백엔드 코드와 같다(읽기만)", () => {
  const repo = readFileSync(path.resolve(__dirname, "../../../backend/app/db/account_repo.py"), "utf8");
  const literal = (name: string) => [...(new RegExp(`^${name} = Literal\\[([^\\]]*)\\]`, "m").exec(repo)?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  const final = (name: string) => Number(new RegExp(`^${name}: Final = (\\d+)`, "m").exec(repo)?.[1]);

  it("문서 종류·관계·연령대·임신 여부 값 목록", () => {
    expect(literal("DocType")).toEqual([...LEGAL_DOC_TYPES]);
    expect(literal("ConsentDocType")).toEqual([...CONSENT_DOC_TYPES]);
    expect(literal("Relation")).toEqual([...RELATIONS]);
    expect(literal("AgeBand")).toEqual([...AGE_BANDS]);
    expect(literal("PregnancyStatus").sort()).toEqual([...PREGNANCY_STATUSES].sort());
    expect(Object.keys(AGE_BAND_RANGE)).toEqual([...AGE_BANDS]);
  });

  it("상한: 가족 3명·별명 20자·약 100자·약 10개", () => {
    expect(final("FAMILY_LIMIT")).toBe(FAMILY_PROFILE_MAX);
    expect(final("PROFILE_LIMIT")).toBe(1 + FAMILY_PROFILE_MAX);
    expect(final("LABEL_MAX_CHARS")).toBe(PROFILE_LABEL_MAX_CHARS);
    expect(final("MEDICATION_TEXT_MAX_CHARS")).toBe(MEDICATION_NAME_MAX_CHARS);
    expect(final("MEDICATION_LIMIT")).toBe(MEDICATIONS_MAX);
  });

  it("화면이 문구로 바꾸는 오류 코드는 백엔드에 있는 코드다", () => {
    const api = readFileSync(path.resolve(__dirname, "../../../backend/app/api/account.py"), "utf8") + readFileSync(path.resolve(__dirname, "../../../backend/app/security/auth.py"), "utf8");
    const parts = readFileSync(path.resolve(__dirname, "../features/account/parts.tsx"), "utf8");
    const mapped = [...(/const CODE_MESSAGES[^{]*\{([\s\S]*?)\n\};/.exec(parts)?.[1] ?? "").matchAll(/^\s+([A-Z_]+):/gm)].map((match) => match[1]);
    // 로그인·가입·소셜 콜백 코드는 백엔드가 아니라 로그인 모듈이 만든다(`lib/api/auth.ts`·`lib/supabase/callback.ts`, 목 로그인 포함)
    const authOnly = ["INVALID_CREDENTIALS", "EMAIL_TAKEN", "EMAIL_NOT_CONFIRMED", "WEAK_PASSWORD", "EMAIL_SEND_FAILED", "AUTH_RATE_LIMITED", "AUTH_FAILED", "OAUTH_EMAIL_REQUIRED", "OAUTH_FAILED"];
    const authSources = readFileSync(path.resolve(__dirname, "../lib/api/auth.ts"), "utf8") + readFileSync(path.resolve(__dirname, "../lib/supabase/callback.ts"), "utf8");
    for (const code of authOnly) {
      expect(mapped, code).toContain(code);
      expect(authSources, code).toContain(`"${code}"`);
    }
    expect(mapped).toEqual(expect.arrayContaining(["HEALTH_CONSENT_REQUIRED", "PROFILE_LIMIT", "MEDICATION_LIMIT", "SELF_REQUIRED", "NOT_IMPLEMENTED", "AUTH_UNAVAILABLE"]));
    for (const code of mapped.filter((name) => !authOnly.includes(name))) expect(api, code).toContain(`"${code}"`);
  });
});

describe("흐름: 게스트 → 로그인 → 동의 → 프로필", () => {
  it("처음은 게스트이고 서버 세션이 없으면(401 AUTH_REQUIRED) bootstrap 뒤에도 게스트다", async () => {
    const store = createAccountStore();
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "guest", me: null, profiles: [], flow: [] });
  });

  it("bootstrap은 서버가 없어도(네트워크 실패) 조용히 게스트로 둔다", async () => {
    const store = createAccountStore({ api: { ...accountApi, fetchMe: () => Promise.reject(new AccountApiError("network", 0, null)) } });
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "guest", failure: null });
  });

  it.each([
    [501, "NOT_IMPLEMENTED"],
    [503, "AUTH_UNAVAILABLE"],
  ])("/api/me가 %i %s면 fetchMe는 null(로그아웃)로 바꾸지 않고 던지고, bootstrap은 지금 상태를 그대로 둔다", async (status, code) => {
    const store = await loggedIn();
    server.use(http.get("*/api/me", () => HttpResponse.json({ code, fields: [] }, { status })));
    await expect(fetchMe()).rejects.toMatchObject({ kind: "http", status, code });
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "member", failure: null }); // 검증 서버 장애로 로그아웃시키지 않는다(BE-11-20 A)
  });

  it("게스트가 열면 로그인 화면이고 뒤로 갈 곳이 없다(flow 1개)", () => {
    const store = createAccountStore();
    store.getState().open();
    expect(store.getState().flow).toEqual(["login"]);
    store.getState().back();
    expect(store.getState().flow).toEqual(["login"]);
  });

  it("이메일 로그인 성공 → /api/me 반영 → 동의 → 프로필. 뒤로는 이전 단계로 간다", async () => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail("user@example.com", "pw")).toBe(true);
    expect(store.getState()).toMatchObject({ status: "member", flow: ["login", "consent"] });
    const before = store.getState().me;
    expect(before).toMatchObject({ is_guest: false, onboarding_step: "consent", onboarding_completed_at: null, health_consent_active: false, profile_limit: 4 });
    expect(before?.consents.map((consent) => [consent.doc_type, consent.required, consent.needs_consent])).toEqual([
      ["terms", true, true],
      ["privacy_consent", true, true],
      ["sensitive_consent", false, true],
    ]);
    expect(needsConsentStep(before)).toBe(true);
    await store.getState().loadLegalDocs();
    expect(await store.getState().submitConsents(ALL)).toBe(true);
    expect(store.getState().flow).toEqual(["login", "consent", "profiles"]);
    expect(store.getState().me).toMatchObject({ onboarding_step: "profile_self", health_consent_active: true });
    expect(consentOf(store.getState().me, "terms")).toMatchObject({ agreed_version: 1, current_version: 1, needs_consent: false, needs_reconsent: false });
    store.getState().back();
    expect(store.getState().flow).toEqual(["login", "consent"]);
  });

  it("온보딩 단계는 서버가 계산한다: 본인 프로필 → family, 가족 3명 → done(완료 시각)", async () => {
    const store = await loggedIn();
    await createProfile(selfDraft());
    expect((await fetchMe())?.onboarding_step).toBe("family");
    for (const label of ["첫째", "둘째", "셋째"]) await createProfile(family(label));
    expect(await fetchMe()).toMatchObject({ onboarding_step: "done", onboarding_completed_at: expect.any(String) });
    expect(store.getState().status).toBe("member");
  });

  it("가입 화면은 로그인에서 들어가고 뒤로 가면 로그인이다", () => {
    const store = createAccountStore();
    store.getState().open();
    store.getState().go("signup");
    expect(store.getState().flow).toEqual(["login", "signup"]);
    store.getState().back();
    expect(store.getState().flow).toEqual(["login"]);
  });

  it.each(["google", "kakao"] as const)("소셜 로그인(%s) 목: 세션이 생기고 동의 화면으로 간다", async (provider) => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginSocial(provider)).toBe(true);
    expect(store.getState()).toMatchObject({ status: "member", flow: ["login", "consent"] });
  });

  it("소셜 로그인 시작 주소(목 전용)는 /api/auth/{provider}/start이고 Naver·Apple 목은 없다", async () => {
    expect(socialLoginUrl("google")).toMatch(/\/api\/auth\/google\/start$/);
    expect(socialLoginUrl("kakao")).toMatch(/\/api\/auth\/kakao\/start$/);
    for (const provider of ["naver", "apple"]) expect((await fetch(`http://localhost:3000/api/auth/${provider}/start`)).status).toBe(404);
  });

  it("로그인 실패는 게스트 그대로이고 실패 코드만 남는다(입력 값은 남기지 않는다)", async () => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail(`${MOCK_LOGIN_FAIL_MARK}@example.com`, "secret-pw")).toBe(false);
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login"], failure: { kind: "http", status: 401, code: "INVALID_CREDENTIALS", fields: [] } });
    expect(JSON.stringify(store.getState())).not.toContain("secret-pw");
    expect(JSON.stringify(store.getState())).not.toContain("example.com");
  });

  it("이미 동의를 마친 사용자는 로그인하면 프로필로 가고, 다시 열면 프로필이 첫 화면이다(뒤로 없음)", async () => {
    const store = createAccountStore();
    store.getState().open();
    await store.getState().loginEmail(`${MOCK_ONBOARDED_MARK}@example.com`, "pw");
    expect(store.getState().flow).toEqual(["profiles"]);
    expect(store.getState().profiles).toHaveLength(2);
    store.getState().close();
    store.getState().open();
    expect(store.getState().flow).toEqual(["profiles"]);
  });

  it("로그인했지만 동의 전이면 다시 열 때 동의가 첫 화면이다", async () => {
    const store = createAccountStore();
    store.getState().open();
    await store.getState().loginEmail("user@example.com", "pw");
    store.getState().close();
    store.getState().open();
    expect(store.getState().flow).toEqual(["consent"]);
  });

  it("로그아웃·탈퇴하면 게스트로 돌아가고 프로필·대상 선택이 비워진다", async () => {
    for (const action of ["logout", "withdraw"] as const) {
      const store = await loggedIn();
      store.getState().editProfile({ profileId: null, self: true });
      await store.getState().saveProfile(selfDraft({ health: { pregnancy_status: "pregnant", medications: [] } }));
      store.getState().setTarget(store.getState().profiles[0].profile_id);
      expect(await store.getState()[action]()).toBe(true);
      expect(store.getState()).toMatchObject({ status: "guest", me: null, profiles: [], targetProfileId: null, flow: [] });
      expect(await fetchMe()).toBeNull();
    }
  });
});

describe("약관 동의", () => {
  it("문서는 API 값 그대로이고 네 종류(동의 대상 셋 + 고지 문서)를 정해진 순서로 받는다", async () => {
    const docs = await fetchLegalDocs();
    expect(docs.map((doc) => doc.doc_type)).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent"]);
    expect(docs.map((doc) => doc.required)).toEqual([true, false, true, false]);
    for (const doc of docs) expect(doc).toEqual(MOCK_LEGAL_DOCS[doc.doc_type]);
  });

  it("고지 문서(privacy_policy)는 동의 항목이 아니다: 요청에 싣지 않고 필수 판정에도 넣지 않는다(FE-04-03 A)", async () => {
    const docs = await fetchLegalDocs();
    const items = consentItems(docs, null, { ...ALL, privacy_policy: true } as ConsentChoices);
    expect(items.map((item) => item.doc_type)).toEqual(["terms", "privacy_consent", "sensitive_consent"]);
    expect(requiredAgreed(docs, { terms: true, privacy_consent: true })).toBe(true);
    // 고지 문서에 서버가 필수 표시를 달아도 체크가 없으니 관문이 되지 않는다
    expect(requiredAgreed(docs.map((doc) => (doc.doc_type === "privacy_policy" ? { ...doc, required: true } : doc)), { terms: true, privacy_consent: true })).toBe(true);
    await createAccountStore().getState().loginEmail("user@example.com", "pw"); // 로그인한 뒤에도 서버(목)는 고지 문서의 동의를 받지 않는다
    await expect(postConsents([{ doc_type: "privacy_policy" as "terms", version: 1, action: "agree" }], "onboarding")).rejects.toMatchObject({ status: 422, code: "INVALID_REQUEST" });
  });

  it("필수 문서를 하나라도 동의하지 않으면 보내지 않고 다음으로 가지 않는다", async () => {
    const post = vi.fn(accountApi.postConsents);
    const store = createAccountStore({ api: { ...accountApi, postConsents: post } });
    store.getState().open();
    await store.getState().loginEmail("user@example.com", "pw");
    await store.getState().loadLegalDocs();
    for (const agreed of [{}, { terms: true }, { privacy_consent: true, sensitive_consent: true }] as ConsentChoices[]) {
      expect(requiredAgreed(store.getState().legalDocs, agreed)).toBe(false);
      expect(await store.getState().submitConsents(agreed)).toBe(false);
    }
    expect(post).not.toHaveBeenCalled();
    expect(store.getState().flow).toEqual(["login", "consent"]);
    expect(requiredAgreed([], ALL)).toBe(false); // 문서를 받지 못했으면 통과시키지 않는다
  });

  it("요청 모양: {items:[{doc_type, version, action}], channel}. 첫 동의는 onboarding, 나중에 바꾸면 settings, 달라진 것만 보낸다", async () => {
    const post = vi.fn(accountApi.postConsents);
    const store = createAccountStore({ api: { ...accountApi, postConsents: post } });
    store.getState().open();
    await store.getState().loginEmail("user@example.com", "pw");
    await store.getState().loadLegalDocs();
    expect(await store.getState().submitConsents(REQUIRED_ONLY)).toBe(true);
    expect(post).toHaveBeenLastCalledWith(
      [
        { doc_type: "terms", version: 1, action: "agree" },
        { doc_type: "privacy_consent", version: 1, action: "agree" },
      ],
      "onboarding",
    );
    expect(await store.getState().submitConsents(ALL)).toBe(true);
    expect(post).toHaveBeenLastCalledWith([{ doc_type: "sensitive_consent", version: 1, action: "agree" }], "settings");
    // 달라진 것이 없으면 보내지 않는다(서버는 빈 items를 받지 않는다)
    expect(await store.getState().submitConsents(ALL)).toBe(true);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("재동의가 필요한 문서가 섞이면 channel은 reconsent다", () => {
    const state = { doc_type: "terms", required: true, agreed_version: 1, acted_at: "2026-11-18T00:00:00Z", current_version: 2, needs_consent: false, needs_reconsent: true } as const;
    const me: Me = { user_id: "u", is_guest: false, onboarding_step: "consent", onboarding_completed_at: null, consents: [state], health_consent_active: false, profile_limit: 4 };
    const docs = [{ ...MOCK_LEGAL_DOCS.terms, version: 2 }];
    const items = consentItems(docs, me, { terms: true });
    expect(items).toEqual([{ doc_type: "terms", version: 2, action: "agree" }]);
    expect(consentChannel(me, items)).toBe("reconsent");
  });

  it("선택 문서는 동의하지 않아도 되고, 건강 정보 저장 가능 여부는 서버 값(health_consent_active)이다", async () => {
    expect(hasHealthConsent((await loggedIn(REQUIRED_ONLY)).getState().me)).toBe(false);
    server.resetHandlers(...createAccountHandlers());
    expect(hasHealthConsent((await loggedIn(ALL)).getState().me)).toBe(true);
    expect(hasHealthConsent(null)).toBe(false);
  });

  it("프로필에서 동의를 다시 보고 바꾸면 프로필로 돌아간다", async () => {
    const store = await loggedIn(REQUIRED_ONLY);
    store.getState().go("consent");
    expect(store.getState().flow).toEqual(["login", "consent", "profiles", "consent"]);
    expect(await store.getState().submitConsents(ALL)).toBe(true);
    expect(store.getState().flow).toEqual(["login", "consent", "profiles"]);
    expect(hasHealthConsent(store.getState().me)).toBe(true);
  });

  it("건강 정보 동의를 철회하면 서버가 임신 여부·복용 약을 즉시 지우고 화면 상태에도 남지 않는다", async () => {
    const store = await loggedIn(ALL);
    store.getState().editProfile({ profileId: null, self: true });
    expect(await store.getState().saveProfile(selfDraft({ health: { pregnancy_status: "pregnant", medications: [med("가나다정")] } }))).toBe(true);
    expect(store.getState().profiles[0]).toMatchObject({ pregnancy_status: "pregnant", medications: [{ input_text: "가나다정" }] });
    expect(await store.getState().submitConsents(REQUIRED_ONLY)).toBe(true);
    expect(consentOf(store.getState().me, "sensitive_consent")).toMatchObject({ needs_consent: true, agreed_version: null });
    expect(hasHealthConsent(store.getState().me)).toBe(false);
    expect(store.getState().profiles[0]).toMatchObject({ label: "나", pregnancy_status: null, medications: [] });
    expect(JSON.stringify(store.getState())).not.toContain("가나다정");
  });

  it("버전이 다르면 409 VERSION_MISMATCH: 화면에 남고 문서를 다시 받는다. 약관 철회는 409 USE_ACCOUNT_DELETE", async () => {
    const fetchDocs = vi.fn(accountApi.fetchLegalDocs);
    const store = createAccountStore({ api: { ...accountApi, fetchLegalDocs: fetchDocs } });
    store.getState().open();
    await store.getState().loginEmail("user@example.com", "pw");
    await store.getState().loadLegalDocs();
    server.use(http.post("*/api/consents", () => HttpResponse.json({ code: "VERSION_MISMATCH", fields: ["terms"] }, { status: 409 })));
    expect(await store.getState().submitConsents(ALL)).toBe(false);
    expect(store.getState().failure).toEqual({ kind: "http", status: 409, code: "VERSION_MISMATCH", fields: ["terms"] });
    expect(store.getState().flow).toEqual(["login", "consent"]);
    await vi.waitFor(() => expect(fetchDocs).toHaveBeenCalledTimes(2));
    server.resetHandlers(...createAccountHandlers());
    await loggedIn();
    await expect(postConsents([{ doc_type: "terms", version: 2, action: "agree" }], "settings")).rejects.toMatchObject({ status: 409, code: "VERSION_MISMATCH", fields: ["terms"] });
    await expect(postConsents([{ doc_type: "terms", version: 1, action: "withdraw" }], "settings")).rejects.toMatchObject({ status: 409, code: "USE_ACCOUNT_DELETE", fields: ["terms"] });
  });
});

describe("프로필: 본인 1 + 가족 최대 3", () => {
  it("추가·수정이 되고 저장하면 목록으로 돌아간다. 응답은 ProfileOut 모양이다", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    expect(store.getState().flow.at(-1)).toBe("profile-form");
    expect(await store.getState().saveProfile(selfDraft({ health: { pregnancy_status: "not_pregnant", medications: [med("가나다정")] } }))).toBe(true);
    expect(store.getState().flow.at(-1)).toBe("profiles");
    const self = store.getState().profiles[0];
    expect(self).toEqual({
      profile_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      relation: "self",
      label: "나",
      age_band: "y19_64",
      pregnancy_status: "not_pregnant",
      sort_order: 0,
      medications: [{ medication_id: expect.any(String), input_text: "가나다정", item_seq: null, confirmed_at: null }],
    });
    store.getState().editProfile({ profileId: self.profile_id, self: true });
    await store.getState().saveProfile(selfDraft({ label: "본인", age_band: "y65_plus", health: { pregnancy_status: "not_pregnant", medications: [med("가나다정")] } }));
    expect(store.getState().profiles).toHaveLength(1);
    expect(store.getState().profiles[0]).toMatchObject({ profile_id: self.profile_id, label: "본인", age_band: "y65_plus", medications: [{ input_text: "가나다정" }] });
  });

  it("PATCH는 보낸 칸만 바꾼다: 건강 정보 칸을 싣지 않으면(health null) 임신 여부·복용 약은 그대로다", async () => {
    await loggedIn();
    const created = await createProfile(selfDraft({ health: { pregnancy_status: "pregnant", medications: [med("가나다정")] } }));
    const patched = await updateProfile(created.profile_id, selfDraft({ label: "본인", age_band: null }));
    expect(patched).toMatchObject({ label: "본인", age_band: null, pregnancy_status: "pregnant", medications: [{ input_text: "가나다정" }] });
    // 건강 정보 칸을 실으면 약은 목록 전체가 바뀐다
    const replaced = await updateProfile(created.profile_id, selfDraft({ health: { pregnancy_status: null, medications: [med("라마바캡슐")] } }));
    expect(replaced).toMatchObject({ pregnancy_status: null, medications: [{ input_text: "라마바캡슐" }] });
  });

  it("가족 프로필은 지울 수 있고, 본인 프로필 삭제는 서버가 409 SELF_REQUIRED로 막는다", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    await store.getState().saveProfile(selfDraft());
    store.getState().editProfile({ profileId: null, self: false });
    await store.getState().saveProfile(family("첫째"));
    const [self, child] = store.getState().profiles;
    store.getState().setTarget(child.profile_id);
    expect(await store.getState().removeProfile(child.profile_id)).toBe(true);
    expect(store.getState()).toMatchObject({ profiles: [self], targetProfileId: null });
    expect(await store.getState().removeProfile(self.profile_id)).toBe(false);
    expect(store.getState().failure).toEqual({ kind: "http", status: 409, code: "SELF_REQUIRED", fields: [] });
    expect(store.getState().profiles).toEqual([self]);
    await expect(deleteProfile(child.profile_id)).rejects.toMatchObject({ status: 404, code: "NOT_FOUND" }); // 이미 지운 프로필
  });

  it("가족은 3명까지: 4번째는 화면이 막고(canAddFamily false) 서버도 422 PROFILE_LIMIT다", async () => {
    const store = await loggedIn();
    for (let index = 1; index <= FAMILY_PROFILE_MAX; index += 1) {
      expect(canAddFamily(store.getState().profiles)).toBe(true);
      store.getState().editProfile({ profileId: null, self: false });
      expect(await store.getState().saveProfile(family(`가족${index}`))).toBe(true);
    }
    expect(canAddFamily(store.getState().profiles)).toBe(false);
    expect(canAddSelf(store.getState().profiles)).toBe(true); // 본인 자리는 따로다
    store.getState().editProfile({ profileId: null, self: false });
    expect(await store.getState().saveProfile(family("가족4"))).toBe(false);
    expect(store.getState().failure).toEqual({ kind: "http", status: 422, code: "PROFILE_LIMIT", fields: ["relation"] });
    expect(store.getState().profiles).toHaveLength(FAMILY_PROFILE_MAX);
    expect(store.getState().flow.at(-1)).toBe("profile-form"); // 실패하면 폼에 남는다
  });

  it("본인 프로필은 1개까지다: 2개째는 409 SELF_EXISTS, 가족을 본인으로 바꾸는 것은 409 SELF_FIXED", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    await store.getState().saveProfile(selfDraft({ age_band: null }));
    expect(canAddSelf(store.getState().profiles)).toBe(false);
    await expect(createProfile(selfDraft({ label: "또 나" }))).rejects.toMatchObject({ status: 409, code: "SELF_EXISTS", fields: ["relation"] });
    const child = await createProfile(family("첫째"));
    await expect(updateProfile(child.profile_id, { ...family("첫째"), relation: "self" })).rejects.toMatchObject({ status: 409, code: "SELF_FIXED" });
  });

  it("건강 정보 동의가 없으면 서버가 임신 여부·복용 약 저장을 422 HEALTH_CONSENT_REQUIRED로 막는다(fields=막힌 칸)", async () => {
    const store = await loggedIn(REQUIRED_ONLY);
    store.getState().editProfile({ profileId: null, self: false });
    expect(await store.getState().saveProfile(family("첫째", { health: { pregnancy_status: "pregnant", medications: [] } }))).toBe(false);
    expect(store.getState().failure).toEqual({ kind: "http", status: 422, code: "HEALTH_CONSENT_REQUIRED", fields: ["pregnancy_status"] });
    expect(await store.getState().saveProfile(family("첫째", { health: { pregnancy_status: null, medications: [med("가나다정")] } }))).toBe(false);
    expect(store.getState().failure?.fields).toEqual(["medications"]);
    expect(JSON.stringify(store.getState().failure)).not.toContain("가나다정"); // 입력 값은 실려 오지 않는다
    expect(await store.getState().saveProfile(family("첫째", { health: NO_HEALTH }))).toBe(true); // 빈 건강 칸은 건강 정보가 아니다
    expect(await store.getState().saveProfile(family("둘째"))).toBe(false); // 폼이 닫힌 뒤에는 저장 대상이 없다
  });

  it("필수 동의 없이 프로필을 쓰면 403 CONSENT_REQUIRED(fields=문서 종류), 로그인 없이 부르면 401 AUTH_REQUIRED", async () => {
    await expect(fetchProfiles()).rejects.toMatchObject({ status: 401, code: "AUTH_REQUIRED" });
    const store = createAccountStore();
    await store.getState().loginEmail("user@example.com", "pw");
    await expect(createProfile(family("첫째"))).rejects.toMatchObject({ status: 403, code: "CONSENT_REQUIRED", fields: ["terms", "privacy_consent"] });
  });

  it("요청 본문은 ProfileCreate 칸만 싣는다(건강 정보 동의가 없으면 건강 칸이 아예 없다)", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post("*/api/profiles", async ({ request }) => {
        bodies.push(await request.json());
        const profile: Profile = { profile_id: "00000000-0000-4000-8000-000000000001", relation: "child", label: "첫째", age_band: null, pregnancy_status: null, sort_order: 0, medications: [] };
        return HttpResponse.json(profile, { status: 201 });
      }),
    );
    await createProfile(family("첫째"));
    await createProfile(family("첫째", { health: { pregnancy_status: "unknown", medications: [med("가나다정")] } }));
    expect(bodies).toEqual([
      { relation: "child", label: "첫째", age_band: "y6_11" },
      { relation: "child", label: "첫째", age_band: "y6_11", pregnancy_status: "unknown", medications: [{ input_text: "가나다정", item_seq: null }] },
    ]);
  });

  it("응답에 모르는 칸이 있으면(계약과 다르면) invalid로 막는다", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ user_id: "u", display_name: "옛 계약" })));
    await expect(fetchMe()).rejects.toMatchObject({ kind: "invalid" });
  });
});

describe("질문 화면 임신 여부 토글의 프로필 저장(FE-11-13·14 A)", () => {
  it("pregnancy_status 한 칸만 PATCH하고 성공하면 프로필 목록을 갱신하며 모달 상태(pending·failure)는 건드리지 않는다. 양방향", async () => {
    const store = await loggedIn(ALL);
    store.getState().editProfile({ profileId: null, self: true });
    expect(await store.getState().saveProfile(selfDraft({ health: { pregnancy_status: "not_pregnant", medications: [med("가나다정")] } }))).toBe(true);
    const profileId = store.getState().profiles[0].profile_id;
    const seen: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PATCH") seen.push(await request.clone().json());
    });
    expect(await store.getState().savePregnancy(profileId, "pregnant")).toBeNull();
    expect(seen).toEqual([{ pregnancy_status: "pregnant" }]);
    expect(store.getState().profiles[0]).toMatchObject({ pregnancy_status: "pregnant", label: "나", medications: [{ input_text: "가나다정" }] }); // 다른 칸은 그대로
    expect(await store.getState().savePregnancy(profileId, "not_pregnant")).toBeNull();
    expect(store.getState().profiles[0].pregnancy_status).toBe("not_pregnant");
    expect(store.getState()).toMatchObject({ pending: false, failure: null });
  });

  it("건강 정보 동의가 없으면 서버가 422 HEALTH_CONSENT_REQUIRED로 막고 실패를 돌려준다(프로필은 그대로)", async () => {
    const store = await loggedIn(REQUIRED_ONLY);
    store.getState().editProfile({ profileId: null, self: true });
    expect(await store.getState().saveProfile(selfDraft())).toBe(true);
    const profileId = store.getState().profiles[0].profile_id;
    const failure = await store.getState().savePregnancy(profileId, "pregnant");
    expect(failure).toMatchObject({ kind: "http", status: 422, code: "HEALTH_CONSENT_REQUIRED", fields: ["pregnancy_status"] });
    expect(store.getState().profiles[0].pregnancy_status).toBeNull();
    expect(store.getState().failure).toBeNull();
  });

  it("연결 실패는 network 실패로 돌려준다", async () => {
    const store = createAccountStore({ api: { ...accountApi, updateProfilePregnancy: () => Promise.reject(new AccountApiError("network", 0, null)) } });
    expect(await store.getState().savePregnancy("p", "pregnant")).toEqual({ kind: "network", status: 0, code: null, fields: [] });
  });
});

describe("계정 진입점 스위치(FE-04-02 A·FE-04-05 A)", () => {
  it("목 모드(NEXT_PUBLIC_API_MOCKING=enabled)이면 켜진다. 실제 백엔드 모드에서는 Supabase 설정 두 값이 다 있을 때만 켜진다", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "");
    expect(isAccountEntryEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "");
    expect(isAccountEntryEnabled()).toBe(false); // 로그인할 길이 없으면 숨긴다
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "true"); // "enabled"만 켠다
    expect(isAccountEntryEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "http://127.0.0.1:54399"); // 합성 값
    expect(isAccountEntryEnabled()).toBe(false); // 하나만 있으면 설정된 것이 아니다
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "synthetic-publishable-key");
    expect(isAccountEntryEnabled()).toBe(true);
  });

  it("로그인 콜백 실패(failLogin)는 로그인 화면을 열고 실패 코드만 남긴다. 닫으면 지워진다", () => {
    const store = createAccountStore();
    store.getState().failLogin("OAUTH_EMAIL_REQUIRED");
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login"], failure: { kind: "http", code: "OAUTH_EMAIL_REQUIRED", fields: [] } });
    store.getState().close();
    expect(store.getState()).toMatchObject({ flow: [], failure: null });
  });
});

describe("대상 선택 → 요청 context", () => {
  it("고른 프로필의 연령대·임신 여부가 buildChatRequest의 context로 간다(약은 싣지 않는다)", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    await store.getState().saveProfile(selfDraft({ health: { pregnancy_status: "pregnant", medications: [med("가나다정")] } }));
    expect(selectTargetProfile(store.getState())).toBeNull(); // 고르기 전
    store.getState().setTarget(store.getState().profiles[0].profile_id);
    const context = profileToContext(selectTargetProfile(store.getState()), hasHealthConsent(store.getState().me));
    expect(buildChatRequest("질문", { ...emptyConversationContext, ...context })).toEqual({
      question: "질문",
      context: { age: { lower: 19, upper: 64, unit: "세" }, pregnant: true, confirmed_drugs: [], prior_drugs: [], took_today: null },
    });
  });

  it("연령대·임신 여부 변환: 고르지 않음·모름·null은 null, 건강 정보 동의가 없으면 임신 여부를 보내지 않는다", () => {
    const profile: Profile = { profile_id: "p", relation: "child", label: "첫째", age_band: "m6_11", pregnancy_status: "pregnant", sort_order: 0, medications: [] };
    expect(profileToContext(null, true)).toEqual({ age: null, pregnant: null });
    expect(profileToContext(profile, true)).toEqual({ age: AGE_BAND_RANGE.m6_11, pregnant: true });
    expect(profileToContext(profile, false)).toEqual({ age: { lower: 6, upper: 11, unit: "개월" }, pregnant: null });
    expect(profileToContext({ ...profile, age_band: null, pregnancy_status: "unknown" }, true)).toEqual({ age: null, pregnant: null });
    expect(profileToContext({ ...profile, pregnancy_status: null }, true).pregnant).toBeNull();
    expect(profileToContext({ ...profile, pregnancy_status: "not_pregnant" }, true).pregnant).toBe(false);
  });

  it("연령대 11구간은 설계 문서 4.8절 표와 같고 /chat 나이 상한(150세)을 넘지 않는다", () => {
    const doc = readFileSync(path.resolve(__dirname, "../../../P2-doc/PJ2-계정-프로필-데이터.md"), "utf8");
    for (const [band, range] of Object.entries(AGE_BAND_RANGE)) {
      const label = AGE_BAND_LABELS[band as keyof typeof AGE_BAND_LABELS];
      expect(doc, band).toContain(`| \`${band}\` | ${label} | ${range.lower} | ${range.upper} | ${range.unit} |`);
      expect(range.lower).toBeLessThanOrEqual(range.upper);
      expect(range.unit === "개월" ? range.upper / 12 : range.upper).toBeLessThanOrEqual(150);
    }
  });

  it("게스트는 대상이 없다", () => {
    const store = createAccountStore();
    store.getState().setTarget("anything");
    expect(selectTargetProfile(store.getState())).toBeNull();
  });
});
