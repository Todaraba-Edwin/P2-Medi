import { describe, expect, it } from "vitest";
import { AUTH_COOKIE_MAX_AGE_S, AUTH_COOKIE_OPTIONS, limitAuthCookieOptions, parseDocumentCookies, serializeCookie } from "./cookies";

// 로그인 상태 유지 쿠키 수명 7일(2026-11-22 사용자 결정). 값은 모두 합성이다.
const SSR_DEFAULT_MAX_AGE_S = 400 * 24 * 60 * 60; // `@supabase/ssr` 기본값(`dist/main/utils/constants.js`)

describe("AUTH_COOKIE_MAX_AGE_S", () => {
  it("7일(604800초)이고 생성 옵션도 같은 값을 든다", () => {
    expect(AUTH_COOKIE_MAX_AGE_S).toBe(604800);
    expect(AUTH_COOKIE_MAX_AGE_S).toBe(7 * 24 * 60 * 60);
    expect(AUTH_COOKIE_OPTIONS).toEqual({ maxAge: AUTH_COOKIE_MAX_AGE_S });
    expect(AUTH_COOKIE_MAX_AGE_S).toBeLessThan(SSR_DEFAULT_MAX_AGE_S);
  });
});

describe("limitAuthCookieOptions", () => {
  it("패키지가 준 400일 수명을 7일로 바꾸고 다른 속성은 그대로 둔다", () => {
    const given = { path: "/", sameSite: "lax" as const, httpOnly: false, secure: true, domain: "example.test", maxAge: SSR_DEFAULT_MAX_AGE_S };
    expect(limitAuthCookieOptions(given)).toEqual({ ...given, maxAge: AUTH_COOKIE_MAX_AGE_S });
  });

  it("지우는 쿠키(maxAge 0)는 건드리지 않는다", () => {
    const removal = { path: "/", sameSite: "lax" as const, maxAge: 0 };
    expect(limitAuthCookieOptions(removal)).toEqual(removal);
  });

  it("옵션이 없어도 7일을 준다", () => {
    expect(limitAuthCookieOptions(undefined)).toEqual({ maxAge: AUTH_COOKIE_MAX_AGE_S });
  });

  it("expires가 함께 오면 7일 뒤로 맞춘다", () => {
    const now = Date.UTC(2026, 10, 22);
    const out = limitAuthCookieOptions({ maxAge: SSR_DEFAULT_MAX_AGE_S, expires: new Date(now + SSR_DEFAULT_MAX_AGE_S * 1000) }, now);
    expect(out.expires?.getTime()).toBe(now + AUTH_COOKIE_MAX_AGE_S * 1000);
  });
});

describe("serializeCookie / parseDocumentCookies", () => {
  it("브라우저 쿠키 한 줄에 Max-Age·Path·SameSite·Secure를 싣는다", () => {
    const line = serializeCookie("sb-x-auth-token", "a b", { maxAge: AUTH_COOKIE_MAX_AGE_S, path: "/", sameSite: "lax", secure: true, httpOnly: false });
    expect(line).toBe("sb-x-auth-token=a%20b; Max-Age=604800; Path=/; Secure; SameSite=Lax");
  });

  it("값을 되읽는다(디코딩 포함)", () => {
    expect(parseDocumentCookies("a=1; sb-x=hello%20world; junk; =empty")).toEqual([
      { name: "a", value: "1" },
      { name: "sb-x", value: "hello world" },
    ]);
    expect(parseDocumentCookies("")).toEqual([]);
  });
});
