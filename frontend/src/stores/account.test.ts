import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountApiError, FAMILY_PROFILE_MAX, accountApi, createProfile, fetchLegalDocs, fetchMe, socialLoginUrl } from "@/lib/api/account";
import type { LegalDocType, ProfileDraft } from "@/lib/api/account";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_LEGAL_DOCS, MOCK_LOGIN_FAIL_MARK, MOCK_ONBOARDED_MARK } from "@/mocks/fixtures/account";
import { canAddFamily, canAddSelf, createAccountStore, hasHealthConsent, requiredAgreed, selectTargetProfile } from "./account";
import { buildChatRequest, emptyConversationContext } from "./conversation-context";
import { AGE_BAND_RANGE, profileToContext } from "./profile-context";

// 계정 스토어 + 임시 계약 API 모듈 + MSW 목을 함께 본다(실제 서버 호출 0). 시험마다 목 세션을 새로 만든다.
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

const ALL: Record<LegalDocType, boolean> = { terms: true, privacy: true, sensitive_health: true, external_ai: true };
const REQUIRED_ONLY: Record<LegalDocType, boolean> = { terms: true, privacy: true, sensitive_health: false, external_ai: false };
const family = (label: string, extra: Partial<ProfileDraft> = {}): ProfileDraft => ({ relation: "child", label, age_band: "child", pregnancy_status: "unknown", medications: [], ...extra });

async function loggedIn(agreed: Record<LegalDocType, boolean> = ALL) {
  const store = createAccountStore();
  store.getState().open();
  expect(await store.getState().loginEmail("user@example.com", "pw")).toBe(true);
  await store.getState().loadLegalDocs();
  expect(await store.getState().submitConsents(agreed)).toBe(true);
  return store;
}

describe("흐름: 게스트 → 로그인 → 동의 → 프로필", () => {
  it("처음은 게스트이고 서버 세션이 없으면 bootstrap 뒤에도 게스트다", async () => {
    const store = createAccountStore();
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "guest", me: null, profiles: [], flow: [] });
  });

  it("bootstrap은 서버가 없어도(네트워크 실패) 조용히 게스트로 둔다", async () => {
    const store = createAccountStore({ api: { ...accountApi, fetchMe: () => Promise.reject(new AccountApiError("network", 0, null)) } });
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "guest", failure: null });
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
    expect(store.getState().me).toMatchObject({ providers: ["email"], onboarding_completed_at: null, consents: [] });
    await store.getState().loadLegalDocs();
    expect(await store.getState().submitConsents(ALL)).toBe(true);
    expect(store.getState().flow).toEqual(["login", "consent", "profiles"]);
    expect(store.getState().me?.onboarding_completed_at).not.toBeNull();
    store.getState().back();
    expect(store.getState().flow).toEqual(["login", "consent"]);
  });

  it("가입 화면은 로그인에서 들어가고 뒤로 가면 로그인이다", () => {
    const store = createAccountStore();
    store.getState().open();
    store.getState().go("signup");
    expect(store.getState().flow).toEqual(["login", "signup"]);
    store.getState().back();
    expect(store.getState().flow).toEqual(["login"]);
  });

  it.each(["google", "kakao"] as const)("소셜 로그인(%s) 목: 세션이 생기고 /api/me에 제공자가 실린다", async (provider) => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginSocial(provider)).toBe(true);
    expect(store.getState().me?.providers).toEqual([provider]);
    expect(store.getState().flow).toEqual(["login", "consent"]);
  });

  it("소셜 로그인 시작 주소는 /api/auth/{provider}/start이고 Naver·Apple 목은 없다", async () => {
    expect(socialLoginUrl("google")).toMatch(/\/api\/auth\/google\/start$/);
    expect(socialLoginUrl("kakao")).toMatch(/\/api\/auth\/kakao\/start$/);
    for (const provider of ["naver", "apple"]) expect((await fetch(`http://localhost:3000/api/auth/${provider}/start`)).status).toBe(404);
  });

  it("로그인 실패는 게스트 그대로이고 실패 코드만 남는다(입력 값은 남기지 않는다)", async () => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail(`${MOCK_LOGIN_FAIL_MARK}@example.com`, "secret-pw")).toBe(false);
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login"], failure: { kind: "http", status: 401, code: "INVALID_CREDENTIALS" } });
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
      await store.getState().saveProfile({ relation: "self", label: "나", age_band: "adult", pregnancy_status: "yes", medications: [] });
      store.getState().setTarget(store.getState().profiles[0].id);
      expect(await store.getState()[action]()).toBe(true);
      expect(store.getState()).toMatchObject({ status: "guest", me: null, profiles: [], targetProfileId: null, flow: [] });
      expect(await fetchMe()).toBeNull();
    }
  });
});

describe("약관 동의", () => {
  it("문서는 API 값 그대로이고 네 종류를 정해진 순서로 받는다", async () => {
    const docs = await fetchLegalDocs();
    expect(docs.map((doc) => doc.doc_type)).toEqual(["terms", "privacy", "sensitive_health", "external_ai"]);
    expect(docs.map((doc) => doc.required)).toEqual([true, true, false, false]);
    for (const doc of docs) expect(doc).toMatchObject({ title: MOCK_LEGAL_DOCS[doc.doc_type].title, body_md: MOCK_LEGAL_DOCS[doc.doc_type].body_md, version: MOCK_LEGAL_DOCS[doc.doc_type].version });
  });

  it("필수 문서를 하나라도 동의하지 않으면 보내지 않고 다음으로 가지 않는다", async () => {
    const post = vi.fn(accountApi.postConsents);
    const store = createAccountStore({ api: { ...accountApi, postConsents: post } });
    store.getState().open();
    await store.getState().loginEmail("user@example.com", "pw");
    await store.getState().loadLegalDocs();
    for (const agreed of [{}, { terms: true }, { privacy: true, sensitive_health: true, external_ai: true }]) {
      expect(requiredAgreed(store.getState().legalDocs, agreed)).toBe(false);
      expect(await store.getState().submitConsents(agreed)).toBe(false);
    }
    expect(post).not.toHaveBeenCalled();
    expect(store.getState().flow).toEqual(["login", "consent"]);
    expect(requiredAgreed([], ALL)).toBe(false); // 문서를 받지 못했으면 통과시키지 않는다
  });

  it("서버도 필수 동의가 빠지면 422로 막는다(목)", async () => {
    const store = createAccountStore();
    await store.getState().loginEmail("user@example.com", "pw");
    await expect(accountApi.postConsents([{ doc_type: "terms", version: MOCK_LEGAL_DOCS.terms.version, agreed: true }])).rejects.toMatchObject({ status: 422, code: "REQUIRED_CONSENT_MISSING" });
  });

  it("선택 문서는 동의하지 않아도 되고, 건강 정보 동의 여부가 me.consents에 반영된다", async () => {
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
});

describe("프로필: 본인 1 + 가족 최대 3", () => {
  it("추가·수정·삭제가 되고 저장하면 목록으로 돌아간다", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    expect(store.getState().flow.at(-1)).toBe("profile-form");
    expect(await store.getState().saveProfile({ relation: "self", label: "나", age_band: "adult", pregnancy_status: "no", medications: [{ drug_name: "가나다정", item_seq: null }] })).toBe(true);
    expect(store.getState().flow.at(-1)).toBe("profiles");
    const self = store.getState().profiles[0];
    expect(self).toMatchObject({ relation: "self", label: "나", medications: [{ drug_name: "가나다정", item_seq: null }] });
    store.getState().editProfile({ profileId: self.id, self: true });
    await store.getState().saveProfile({ ...self, label: "본인", age_band: "senior" });
    expect(store.getState().profiles).toEqual([{ ...self, label: "본인", age_band: "senior" }]);
    store.getState().setTarget(self.id);
    expect(await store.getState().removeProfile(self.id)).toBe(true);
    expect(store.getState()).toMatchObject({ profiles: [], targetProfileId: null });
  });

  it("가족은 3명까지: 4번째는 화면이 막고(canAddFamily false) 서버도 422다", async () => {
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
    expect(store.getState().failure).toMatchObject({ status: 422, code: "PROFILE_LIMIT" });
    expect(store.getState().profiles).toHaveLength(FAMILY_PROFILE_MAX);
    expect(store.getState().flow.at(-1)).toBe("profile-form"); // 실패하면 폼에 남는다
  });

  it("본인 프로필은 1개까지다", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    await store.getState().saveProfile({ relation: "self", label: "나", age_band: null, pregnancy_status: "unknown", medications: [] });
    expect(canAddSelf(store.getState().profiles)).toBe(false);
    await expect(createProfile({ relation: "self", label: "또 나", age_band: null, pregnancy_status: "unknown", medications: [] })).rejects.toMatchObject({ status: 422, code: "PROFILE_LIMIT" });
  });

  it("건강 정보 동의가 없으면 서버가 임신 여부·복용 약 저장을 막는다(목)", async () => {
    const store = await loggedIn(REQUIRED_ONLY);
    store.getState().editProfile({ profileId: null, self: false });
    expect(await store.getState().saveProfile(family("첫째", { pregnancy_status: "yes" }))).toBe(false);
    expect(store.getState().failure).toMatchObject({ status: 422, code: "HEALTH_CONSENT_REQUIRED" });
    expect(await store.getState().saveProfile(family("첫째", { medications: [{ drug_name: "가나다정", item_seq: null }] }))).toBe(false);
    expect(await store.getState().saveProfile(family("첫째"))).toBe(true);
  });
});

describe("대상 선택 → 요청 context", () => {
  it("고른 프로필의 연령대·임신 여부가 buildChatRequest의 context로 간다(약은 싣지 않는다)", async () => {
    const store = await loggedIn();
    store.getState().editProfile({ profileId: null, self: true });
    await store.getState().saveProfile({ relation: "self", label: "나", age_band: "adult", pregnancy_status: "yes", medications: [{ drug_name: "가나다정", item_seq: null }] });
    expect(selectTargetProfile(store.getState())).toBeNull(); // 고르기 전
    store.getState().setTarget(store.getState().profiles[0].id);
    const context = profileToContext(selectTargetProfile(store.getState()), hasHealthConsent(store.getState().me));
    expect(buildChatRequest("질문", { ...emptyConversationContext, ...context })).toEqual({
      question: "질문",
      context: { age: { lower: 19, upper: 64, unit: "세" }, pregnant: true, confirmed_drugs: [] },
    });
  });

  it("연령대·임신 여부 변환: 고르지 않음·모름은 null, 건강 정보 동의가 없으면 임신 여부를 보내지 않는다", () => {
    const profile = { id: "p", relation: "child", label: "첫째", age_band: "infant", pregnancy_status: "yes", medications: [] } as const;
    expect(profileToContext(null, true)).toEqual({ age: null, pregnant: null });
    expect(profileToContext({ ...profile, medications: [] }, true)).toEqual({ age: AGE_BAND_RANGE.infant, pregnant: true });
    expect(profileToContext({ ...profile, medications: [] }, false)).toEqual({ age: { lower: 0, upper: 23, unit: "개월" }, pregnant: null });
    expect(profileToContext({ ...profile, medications: [], age_band: null, pregnancy_status: "unknown" }, true)).toEqual({ age: null, pregnant: null });
    expect(profileToContext({ ...profile, medications: [], pregnancy_status: "no" }, true).pregnant).toBe(false);
    for (const range of Object.values(AGE_BAND_RANGE)) expect(range.lower).toBeLessThanOrEqual(range.upper);
  });

  it("게스트는 대상이 없다", () => {
    const store = createAccountStore();
    store.getState().setTarget("anything");
    expect(selectTargetProfile(store.getState())).toBeNull();
  });
});
