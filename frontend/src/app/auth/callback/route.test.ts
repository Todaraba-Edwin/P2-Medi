// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

// Next의 `cookies()`·요청 저장소는 `globalThis.AsyncLocalStorage`를 쓴다(서버가 띄울 때 넣어 준다). 시험에서는 여기서 넣는다(Next 모듈을 읽기 전).
await vi.hoisted(async () => {
  const { AsyncLocalStorage } = await import("node:async_hooks");
  (globalThis as unknown as { AsyncLocalStorage?: unknown }).AsyncLocalStorage ??= AsyncLocalStorage;
});

import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { createRequestStoreForAPI } from "next/dist/server/async-storage/request-store";
import { workAsyncStorage } from "next/dist/server/app-render/work-async-storage.external";
import type { WorkStore } from "next/dist/server/app-render/work-async-storage.external";
import { workUnitAsyncStorage } from "next/dist/server/app-render/work-unit-async-storage.external";
import { appendMutableCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { classifyCallbackError, parseAuthError } from "@/lib/supabase/callback";
import { GET } from "./route";

// 로그인 콜백 라우트를 가짜 Supabase 서버 클라이언트로 본다(실제 Supabase 호출 0). 값은 모두 합성이다.
const exchangeCodeForSession = vi.fn();
let configured = true;
vi.mock("@/lib/supabase/server", () => ({
  createRouteSupabase: async () => (configured ? { auth: { exchangeCodeForSession } } : null),
}));

// 아이패드가 LAN의 Mac 개발 서버로 접속한 상황(2026-11-23 실기기 보고). 개발 서버의 `request.nextUrl.origin`은 요청한 호스트가 아니라
// `localhost:3000`이 되므로, 절대 주소를 만들면 다른 기기의 localhost로 가 버린다. 그래서 `Location`은 상대 경로여야 한다.
const LAN_ORIGIN = "http://192.168.0.47:3000";
const LAN_HOST = "192.168.0.47:3000";
const call = async (query: string, origin = LAN_ORIGIN) => {
  const response = await GET(new NextRequest(`${origin}/auth/callback${query}`, { headers: { host: new URL(origin).host } }));
  return { status: response.status, location: response.headers.get("location") };
};

beforeEach(() => {
  configured = true;
  exchangeCodeForSession.mockReset();
  exchangeCodeForSession.mockResolvedValue({ data: {}, error: null });
});

describe("GET /auth/callback", () => {
  it("code가 있으면 세션으로 바꾸고 첫 화면으로 돌려보낸다(주소에 코드를 남기지 않고 복귀 표시 `auth_resume=1`만 붙인다)", async () => {
    const { status, location } = await call("?code=synthetic-code");
    expect(exchangeCodeForSession).toHaveBeenCalledWith("synthetic-code");
    expect(status).toBe(302);
    expect(location).toBe("/?auth_resume=1");
    expect(location).not.toContain("synthetic-code");
  });

  it("Location은 상대 경로다: 요청 호스트가 LAN 주소여도 절대 주소(localhost 포함)를 만들지 않는다(성공·오류·code 없음 모두)", async () => {
    for (const [query, expected] of [
      ["?code=synthetic-code", "/?auth_resume=1"],
      ["?error=access_denied&error_description=synthetic", "/?auth_error=failed"],
      ["", "/"],
    ] as const) {
      const { status, location } = await call(query, LAN_ORIGIN);
      expect(status).toBe(302);
      expect(location).toBe(expected);
      expect(location).not.toMatch(/^[a-z]+:\/\//i);
      expect(location).not.toContain("localhost");
      expect(location).not.toContain(LAN_HOST);
    }
    // 서버가 요청을 localhost로 인식해도 결과는 같다(호스트·포트를 코드가 만지지 않는다)
    expect((await call("?code=synthetic-code", "http://localhost:3000")).location).toBe("/?auth_resume=1");
  });

  it("핸들러 안에서 쓴 세션 쿠키(`cookies().set`)가 상대 리다이렉트 응답에 실린다(Next 라우트 모듈의 finalizeResponse 병합과 같은 방식)", async () => {
    // `@supabase/ssr`의 `setAll`은 `createRouteSupabase`의 `cookies()` 저장소에 쓴다. 그 저장소가 응답 헤더로 합쳐지는지 본다.
    exchangeCodeForSession.mockImplementation(async () => {
      (await cookies()).set("sb-synthetic-auth-token", "synthetic-session", { path: "/", maxAge: 60 });
      return { data: {}, error: null };
    });
    const request = new NextRequest(`${LAN_ORIGIN}/auth/callback?code=synthetic-code`, { headers: { host: LAN_HOST } });
    const store = createRequestStoreForAPI(request, request.nextUrl, { tags: [], expirationsByCacheKind: new Map() }, undefined, undefined, undefined);
    // `cookies()`는 work store(라우트 정보)와 request store(요청 저장소)가 둘 다 있어야 한다. 라우트 모듈이 넣는 최소 항목만 흉내 낸다.
    const workStore = { page: "/auth/callback/route", route: "/auth/callback", forceStatic: false, dynamicShouldError: false } as unknown as WorkStore;
    const response = await workAsyncStorage.run(workStore, () => workUnitAsyncStorage.run(store, () => GET(request)));
    const headers = new Headers(response.headers);
    expect(appendMutableCookies(headers, store.mutableCookies)).toBe(true);
    expect(response.headers.get("location")).toBe("/?auth_resume=1");
    const setCookie = headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("sb-synthetic-auth-token=synthetic-session");
    expect(setCookie).toContain("Path=/");
  });

  it("이메일 없는 카카오계정(Supabase 오류)이면 교환하지 않고 email_required 표시만 넘긴다", async () => {
    const { location } = await call("?error=server_error&error_code=unexpected_failure&error_description=Error+getting+user+email+from+external+provider");
    expect(location).toBe("/?auth_error=email_required");
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
  });

  it("그 밖의 공급자 오류(동의 취소 등)는 failed다. 오류 문구는 주소에 싣지 않는다", async () => {
    const { location } = await call("?error=access_denied&error_description=synthetic+user+denied");
    expect(location).toBe("/?auth_error=failed");
  });

  it("코드 교환이 실패하거나 던지면 failed다", async () => {
    exchangeCodeForSession.mockResolvedValue({ data: {}, error: { code: "flow_state_not_found", message: "synthetic" } });
    expect((await call("?code=synthetic-code")).location).toBe("/?auth_error=failed");
    exchangeCodeForSession.mockRejectedValue(new TypeError("fetch failed"));
    expect((await call("?code=synthetic-code")).location).toBe("/?auth_error=failed");
  });

  it("Supabase 설정이 없으면 코드가 와도 failed다. 아무것도 없으면 그냥 첫 화면이다", async () => {
    configured = false;
    expect((await call("?code=synthetic-code")).location).toBe("/?auth_error=failed");
    expect((await call("")).location).toBe("/");
  });

  it("주소로 받은 값으로 이동 대상을 바꾸지 못한다(늘 첫 화면 `/`)", async () => {
    const { location } = await call("?code=synthetic-code&next=https://example.com/&redirect_to=//example.com");
    expect(location).toBe("/?auth_resume=1");
    // 실패 복귀에는 성공 표시가 붙지 않는다(둘이 같이 가지 않는다)
    expect((await call("?error=access_denied")).location).not.toContain("auth_resume");
  });
});

describe("콜백 오류 분류", () => {
  it.each([
    [null, "Error getting user email from external provider", "email_required"],
    ["unexpected_failure", "Error getting user email from external provider", "email_required"],
    ["email_address_not_provided", null, "email_required"],
    [null, "Email is required", "email_required"],
    ["access_denied", "User denied access", "failed"],
    ["provider_email_needs_verification", "Unverified email with kakao", "failed"],
    [null, null, "failed"],
  ] as const)("%s / %s → %s", (code, description, expected) => {
    expect(classifyCallbackError(code, description)).toBe(expected);
  });

  it("주소의 auth_error는 아는 값만 받는다", () => {
    expect(parseAuthError("email_required")).toBe("email_required");
    expect(parseAuthError("failed")).toBe("failed");
    for (const value of [null, "", "<script>", "EMAIL_REQUIRED"]) expect(parseAuthError(value)).toBeNull();
  });
});
