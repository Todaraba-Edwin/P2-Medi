import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MOCK_LEGAL_DOCS } from "@/mocks/fixtures/account";
import { createAccountStore } from "@/stores/account";
import { accountApi, deleteMe, fetchLegalDoc, fetchMe, fetchProfiles, fetchSelfNameDefault, isAccountEntryEnabled, loginWithEmail, logout, signupWithEmail, startSocialLogin } from "./account";
import type { Me } from "./account";
import { authMode, getAccessToken, getSocialIdentity } from "./auth";

// 실제 로그인 방식(Supabase, MSW 목 꺼짐)을 가짜 Supabase 클라이언트로 본다. 실제 Supabase·백엔드 호출은 0이다.
// 값은 모두 합성이다(주소·키·토큰·이메일).
const TOKEN = "synthetic-access-token";
const EMAIL = "synthetic-user@example.com";
const PASSWORD = "synthetic-pw-1234";

const auth = {
  getSession: vi.fn(),
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signInWithOAuth: vi.fn(),
  signOut: vi.fn(),
};
let session: { access_token: string; user: { email: string } } | null = null;

vi.mock("@/lib/supabase/browser", () => ({ getBrowserSupabase: () => Promise.resolve({ auth }) }));

const server = setupServer();
/** 백엔드가 받은 계정 호출: `METHOD 경로`와 Authorization 머리 */
let seen: { call: string; authorization: string | null }[] = [];
const record = (request: Request) => seen.push({ call: `${request.method} ${new URL(request.url).pathname}`, authorization: request.headers.get("authorization") });

const ME: Me = {
  user_id: "00000000-0000-4000-8000-0000000000aa",
  is_guest: false,
  onboarding_step: "consent",
  onboarding_completed_at: null,
  consents: [],
  health_consent_active: false,
  profile_limit: 4,
};

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "http://127.0.0.1:54399");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "synthetic-publishable-key");
  session = null;
  seen = [];
  auth.getSession.mockImplementation(async () => ({ data: { session }, error: null }));
  auth.signInWithPassword.mockImplementation(async () => {
    session = { access_token: TOKEN, user: { email: EMAIL } };
    return { data: { session }, error: null };
  });
  auth.signUp.mockImplementation(async () => ({ data: { session: null, user: {} }, error: null }));
  auth.signInWithOAuth.mockImplementation(async () => ({ data: { provider: "kakao", url: "http://127.0.0.1:54399/auth/v1/authorize" }, error: null }));
  auth.signOut.mockImplementation(async () => {
    session = null;
    return { error: null };
  });
  server.use(
    http.get("*/api/me", ({ request }) => {
      record(request);
      return request.headers.get("authorization") === `Bearer ${TOKEN}` ? HttpResponse.json(ME) : HttpResponse.json({ code: "AUTH_REQUIRED", fields: [] }, { status: 401 });
    }),
    http.get("*/api/profiles", ({ request }) => {
      record(request);
      return HttpResponse.json([]);
    }),
    http.delete("*/api/me", ({ request }) => {
      record(request);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("*/api/legal/:docType", ({ request }) => {
      record(request);
      return HttpResponse.json(MOCK_LEGAL_DOCS.terms);
    }),
  );
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});
afterAll(() => server.close());

/** `/api/me`가 계정 서버 미설정(501)으로 답하게 한다(원격 스키마 적용 전, BE-11-23 A) */
const meNotImplemented = () =>
  server.use(
    http.get("*/api/me", ({ request }) => {
      record(request);
      return HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 });
    }),
  );

describe("로그인 방식 고르기·계정 진입점(FE-04-02 A·FE-04-05 A)", () => {
  it("목이 켜져 있으면 mock, Supabase 설정 두 값이 다 있으면 supabase, 둘 다 아니면 none(진입점 숨김)", () => {
    expect(authMode()).toBe("supabase");
    expect(isAccountEntryEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled"); // 목이 먼저다(목 빌드에서는 Supabase를 부르지 않는다)
    expect(authMode()).toBe("mock");
    expect(isAccountEntryEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "");
    for (const [url, key] of [
      ["", "synthetic-publishable-key"],
      ["http://127.0.0.1:54399", ""],
      ["   ", "synthetic-publishable-key"],
      ["", ""],
    ]) {
      vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", url);
      vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", key);
      expect(authMode(), `${url}|${key}`).toBe("none");
      expect(isAccountEntryEnabled(), `${url}|${key}`).toBe(false);
    }
  });

  it("로그인 방식이 없으면(none) 로그인 호출은 501 NOT_IMPLEMENTED로 막히고 Supabase·서버를 부르지 않는다", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    await expect(loginWithEmail(EMAIL, PASSWORD)).rejects.toMatchObject({ status: 501, code: "NOT_IMPLEMENTED" });
    await expect(signupWithEmail(EMAIL, PASSWORD)).rejects.toMatchObject({ status: 501, code: "NOT_IMPLEMENTED" });
    await expect(startSocialLogin("google")).rejects.toMatchObject({ status: 501, code: "NOT_IMPLEMENTED" });
    expect(await getAccessToken()).toBeNull();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
    expect(auth.getSession).not.toHaveBeenCalled();
    expect(seen).toEqual([]);
  });

  it("목 모드에서는 세션이 있어도 토큰을 읽지 않는다(Supabase 클라이언트를 건드리지 않는다)", async () => {
    session = { access_token: TOKEN, user: { email: EMAIL } };
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
    expect(await getAccessToken()).toBeNull();
    expect(auth.getSession).not.toHaveBeenCalled();
  });
});

describe("토큰 전달(Authorization: Bearer)", () => {
  it("세션이 없으면 게스트다: /api/me를 부르지 않고 null, 다른 호출에는 Authorization이 없다", async () => {
    expect(await fetchMe()).toBeNull();
    expect(seen).toEqual([]);
    await fetchLegalDoc("terms"); // 게스트도 읽는 문서
    expect(seen).toEqual([{ call: "GET /api/legal/terms", authorization: null }]);
  });

  it("로그인해 있으면 계정 호출마다 세션의 access token을 붙인다", async () => {
    await loginWithEmail(EMAIL, PASSWORD);
    expect(await fetchMe()).toEqual(ME);
    await fetchProfiles();
    await fetchLegalDoc("terms");
    expect(seen).toEqual([
      { call: "GET /api/me", authorization: `Bearer ${TOKEN}` },
      { call: "GET /api/profiles", authorization: `Bearer ${TOKEN}` },
      { call: "GET /api/legal/terms", authorization: `Bearer ${TOKEN}` },
    ]);
  });

  it("세션을 읽다 실패해도 호출은 토큰 없이 나간다(던지지 않는다)", async () => {
    auth.getSession.mockRejectedValue(new Error("synthetic"));
    expect(await getAccessToken()).toBeNull();
    await fetchLegalDoc("terms");
    expect(seen).toEqual([{ call: "GET /api/legal/terms", authorization: null }]);
  });
});

describe("이메일 로그인·가입(Supabase)", () => {
  it("로그인: signInWithPassword에 입력을 넘기고, 스토어는 /api/me를 읽어 동의 단계로 간다", async () => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail(EMAIL, PASSWORD)).toBe(true);
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: EMAIL, password: PASSWORD });
    expect(store.getState()).toMatchObject({ status: "member", me: ME, flow: ["login", "consent"], failure: null });
  });

  it.each([
    ["invalid_credentials", 400, "INVALID_CREDENTIALS"],
    ["email_not_confirmed", 400, "EMAIL_NOT_CONFIRMED"],
    ["over_request_rate_limit", 429, "AUTH_RATE_LIMITED"],
    ["something_new", 500, "AUTH_FAILED"],
  ])("로그인 실패 %s → 코드 %s만 남는다(입력 값·Supabase 문구는 남기지 않는다)", async (code, status, expected) => {
    auth.signInWithPassword.mockResolvedValue({ data: { session: null }, error: { code, status, message: `synthetic message ${EMAIL}` } });
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail(EMAIL, PASSWORD)).toBe(false);
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login"], failure: { kind: "http", status, code: expected, fields: [] } });
    const dump = JSON.stringify(store.getState());
    for (const secret of [EMAIL, PASSWORD, "synthetic message"]) expect(dump).not.toContain(secret);
    expect(seen).toEqual([]);
  });

  it("연결 실패(Supabase에 닿지 못함)는 network 실패다", async () => {
    auth.signInWithPassword.mockResolvedValue({ data: { session: null }, error: { status: 0, message: "Failed to fetch" } });
    await expect(loginWithEmail(EMAIL, PASSWORD)).rejects.toMatchObject({ kind: "network", status: 0, code: null });
    auth.signInWithPassword.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(loginWithEmail(EMAIL, PASSWORD)).rejects.toMatchObject({ kind: "network", status: 0, code: null });
  });

  it("가입: 이메일 확인이 필요하면(세션 없음) 로그인하지 않고 가입 화면에 안내만 남긴다. 확인 링크는 /auth/callback으로 돌아온다", async () => {
    const store = createAccountStore();
    store.getState().open();
    store.getState().go("signup");
    expect(await store.getState().signupEmail(EMAIL, PASSWORD)).toBe(true);
    expect(auth.signUp).toHaveBeenCalledWith({ email: EMAIL, password: PASSWORD, options: { emailRedirectTo: `${window.location.origin}/auth/callback` } });
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login", "signup"], notice: "signup-confirm", failure: null });
    expect(seen).toEqual([]);
    store.getState().back(); // 단계를 옮기면 안내는 지운다
    expect(store.getState().notice).toBeNull();
  });

  it("가입: 세션이 바로 오면(이메일 확인을 끈 프로젝트) 로그인 상태가 된다", async () => {
    auth.signUp.mockImplementation(async () => {
      session = { access_token: TOKEN, user: { email: EMAIL } };
      return { data: { session }, error: null };
    });
    const store = createAccountStore();
    store.getState().open();
    store.getState().go("signup");
    expect(await store.getState().signupEmail(EMAIL, PASSWORD)).toBe(true);
    expect(store.getState()).toMatchObject({ status: "member", notice: null, flow: ["login", "signup", "consent"] });
  });

  it.each([
    ["user_already_exists", 422, "EMAIL_TAKEN"],
    ["weak_password", 422, "WEAK_PASSWORD"],
    ["over_email_send_rate_limit", 429, "EMAIL_SEND_FAILED"],
    ["email_address_not_authorized", 400, "EMAIL_SEND_FAILED"],
  ])("가입 실패 %s → %s", async (code, status, expected) => {
    auth.signUp.mockResolvedValue({ data: { session: null, user: null }, error: { code, status } });
    await expect(signupWithEmail(EMAIL, PASSWORD)).rejects.toMatchObject({ kind: "http", status, code: expected });
  });
});

describe("소셜 로그인·로그아웃·탈퇴(Supabase)", () => {
  it.each(["google", "kakao"] as const)("%s: signInWithOAuth에 redirectTo(지금 출처의 /auth/callback)를 넘긴다. 페이지가 옮겨 가므로 로그인 상태는 돌아온 뒤에 읽는다", async (provider) => {
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginSocial(provider)).toBe(true);
    expect(auth.signInWithOAuth).toHaveBeenCalledWith({ provider, options: { redirectTo: `${window.location.origin}/auth/callback` } });
    expect(store.getState()).toMatchObject({ status: "guest", flow: ["login"] });
    expect(seen).toEqual([]); // 목 주소(/api/auth/*)를 부르지 않는다
  });

  it("소셜 로그인을 시작하지 못하면 실패 코드가 남는다", async () => {
    auth.signInWithOAuth.mockResolvedValue({ data: { provider: "kakao", url: null }, error: { code: "provider_disabled", status: 400 } });
    await expect(startSocialLogin("kakao")).rejects.toMatchObject({ kind: "http", status: 400, code: "AUTH_FAILED" });
  });

  it("로그아웃은 이 브라우저의 세션만 끝내고(scope local) 서버 목 주소를 부르지 않는다. 그 뒤 호출에는 토큰이 없다", async () => {
    const store = createAccountStore();
    store.getState().open();
    await store.getState().loginEmail(EMAIL, PASSWORD);
    seen = [];
    expect(await store.getState().logout()).toBe(true);
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(store.getState()).toMatchObject({ status: "guest", me: null, profiles: [], flow: [] });
    expect(await fetchMe()).toBeNull();
    expect(seen).toEqual([]);
  });

  it("로그아웃 요청이 실패해도 던지지 않는다(화면은 게스트로 돌아간다)", async () => {
    auth.signOut.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(logout()).resolves.toBeUndefined();
  });

  it("탈퇴는 토큰을 붙여 DELETE /api/me를 부른 뒤 로그인 세션도 끝낸다", async () => {
    await loginWithEmail(EMAIL, PASSWORD);
    await deleteMe();
    expect(seen).toEqual([{ call: "DELETE /api/me", authorization: `Bearer ${TOKEN}` }]);
    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });

  it("탈퇴가 서버에서 막히면 로그인 세션은 그대로 둔다", async () => {
    await loginWithEmail(EMAIL, PASSWORD);
    server.use(http.delete("*/api/me", () => HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 })));
    await expect(deleteMe()).rejects.toMatchObject({ status: 501 });
    expect(auth.signOut).not.toHaveBeenCalled();
  });
});

describe("계정 서버가 준비 전(501)·장애(503)일 때: 화면이 깨지지 않는다(BE-11-20 A·BE-11-23 A)", () => {
  it("세션이 있고 /api/me가 501이면 bootstrap은 오류 없이 로그인 상태만 만든다(me 없음). 로그아웃은 된다", async () => {
    session = { access_token: TOKEN, user: { email: EMAIL } };
    meNotImplemented();
    const store = createAccountStore();
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "member", me: null, profiles: [], failure: null, flow: [] });
    expect(seen).toEqual([{ call: "GET /api/me", authorization: `Bearer ${TOKEN}` }]);
    // 모달을 열면 프로필 화면이고(동의 화면으로 보내지 않는다) 서버 값을 한 번 더 읽어 본다
    store.getState().open();
    expect(store.getState().flow).toEqual(["profiles"]);
    await vi.waitFor(() => expect(seen).toHaveLength(2));
    expect(await store.getState().logout()).toBe(true);
    expect(store.getState().status).toBe("guest");
  });

  it("그 사이 계정 서버가 준비되면 모달을 열 때 서버 값이 채워진다", async () => {
    session = { access_token: TOKEN, user: { email: EMAIL } };
    meNotImplemented();
    const store = createAccountStore();
    await store.getState().bootstrap();
    server.resetHandlers(
      http.get("*/api/me", () => HttpResponse.json(ME)),
      http.get("*/api/profiles", () => HttpResponse.json([])),
    );
    store.getState().open();
    await vi.waitFor(() => expect(store.getState().me).toEqual(ME));
  });

  it("세션이 없으면 501이어도 게스트 그대로다(서버를 부르지도 않는다)", async () => {
    meNotImplemented();
    const store = createAccountStore();
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "guest", failure: null });
    expect(seen).toEqual([]);
  });

  it.each([
    [501, "NOT_IMPLEMENTED"],
    [503, "AUTH_UNAVAILABLE"],
  ])("이메일 로그인 직후 /api/me가 %i %s면 로그인 상태로 프로필 화면에 가고 준비 중 실패 코드를 보인다(로그인 화면에 붙잡지 않는다)", async (status, code) => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ code, fields: [] }, { status })));
    const store = createAccountStore();
    store.getState().open();
    expect(await store.getState().loginEmail(EMAIL, PASSWORD)).toBe(false);
    expect(store.getState()).toMatchObject({ status: "member", me: null, flow: ["profiles"], failure: { kind: "http", status, code } });
  });

  it("토큰이 거절되면(401) 게스트로 본다", async () => {
    session = { access_token: "synthetic-expired-token", user: { email: EMAIL } };
    const store = createAccountStore();
    await store.getState().bootstrap();
    expect(store.getState().status).toBe("guest");
  });

  it("스토어가 받는 API 묶음에 세션 확인이 들어 있다", async () => {
    expect(await accountApi.hasSession()).toBe(false);
    session = { access_token: TOKEN, user: { email: EMAIL } };
    expect(await accountApi.hasSession()).toBe(true);
  });
});

describe("토큰·이메일을 남기지 않는다", () => {
  it("로그인 → 호출 → 로그아웃까지 스토어 상태·브라우저 저장소·콘솔에 토큰·이메일·비밀번호가 없다", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => {}));
    const store = createAccountStore();
    store.getState().open();
    await store.getState().loginEmail(EMAIL, PASSWORD);
    const dump = JSON.stringify(store.getState());
    for (const secret of [TOKEN, EMAIL, PASSWORD]) expect(dump).not.toContain(secret);
    await store.getState().logout();
    expect(setItem).not.toHaveBeenCalled();
    for (const log of logs) expect(log).not.toHaveBeenCalled();
    expect(document.cookie).toBe(""); // 세션 쿠키는 `@supabase/ssr` 클라이언트만 쓴다(여기서는 가짜 클라이언트라 없다)
    vi.restoreAllMocks();
  });
});

describe("본인 프로필 이름 초기값(FE-04-28 B): Supabase 세션의 공급자·이름만 읽는다", () => {
  type Session = { access_token: string; user: { email: string; app_metadata?: Record<string, unknown>; user_metadata?: Record<string, unknown> } };
  const withUser = (user: Session["user"]) => auth.getSession.mockImplementation(async () => ({ data: { session: { access_token: TOKEN, user } }, error: null }));

  it("카카오(app_metadata.provider) + user_metadata.name → 닉네임(이름 규칙에 맞춰 자름). 네트워크 호출 0", async () => {
    withUser({ email: EMAIL, app_metadata: { provider: "kakao", providers: ["kakao"] }, user_metadata: { name: "  삐약이 ", full_name: "삐약이", preferred_username: "삐약이" } });
    expect(await getSocialIdentity()).toEqual({ provider: "kakao", name: "  삐약이 " });
    expect(await fetchSelfNameDefault()).toBe("삐약이");
    withUser({ email: EMAIL, app_metadata: { provider: "kakao" }, user_metadata: { name: "가".repeat(30) } });
    expect(await fetchSelfNameDefault()).toBe("가".repeat(20));
    expect(seen).toEqual([]);
  });

  it("구글·이메일·이름 없음·이름이 문자열 아님·세션 없음 → null(구글 실명은 가져오지 않는다)", async () => {
    withUser({ email: EMAIL, app_metadata: { provider: "google" }, user_metadata: { name: "Google Real Name", full_name: "Google Real Name" } });
    expect(await getSocialIdentity()).toEqual({ provider: "google", name: "Google Real Name" });
    expect(await fetchSelfNameDefault()).toBeNull();
    withUser({ email: EMAIL, app_metadata: { provider: "email" }, user_metadata: {} });
    expect(await fetchSelfNameDefault()).toBeNull();
    withUser({ email: EMAIL, app_metadata: { provider: "kakao" }, user_metadata: {} });
    expect(await getSocialIdentity()).toEqual({ provider: "kakao", name: null });
    expect(await fetchSelfNameDefault()).toBeNull();
    withUser({ email: EMAIL, app_metadata: { provider: "kakao" }, user_metadata: { name: 7 } });
    expect(await fetchSelfNameDefault()).toBeNull();
    withUser({ email: EMAIL, app_metadata: { provider: "kakao" }, user_metadata: { name: "   " } });
    expect(await fetchSelfNameDefault()).toBeNull();
    session = null;
    auth.getSession.mockImplementation(async () => ({ data: { session }, error: null }));
    expect(await getSocialIdentity()).toBeNull();
    expect(await fetchSelfNameDefault()).toBeNull();
    auth.getSession.mockRejectedValueOnce(new Error("synthetic"));
    expect(await getSocialIdentity()).toBeNull();
  });

  it("로그인 방식이 없으면(none) 아무것도 읽지 않고 null", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    expect(await fetchSelfNameDefault()).toBeNull();
    expect(auth.getSession).not.toHaveBeenCalled();
  });
});
