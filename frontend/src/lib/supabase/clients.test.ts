import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTH_COOKIE_MAX_AGE_S } from "./cookies";

// 쿠키를 만드는 모든 클라이언트 생성 경로(브라우저·서버)가 같은 7일 수명을 받는지 본다.
// `@supabase/ssr`를 가짜로 바꿔 호출 인자만 검사한다(실제 Supabase 호출 0). 값은 모두 합성이다.
const SSR_DEFAULT_MAX_AGE_S = 400 * 24 * 60 * 60;
const createBrowserClient = vi.fn(() => ({ kind: "browser" }));
const createServerClient = vi.fn(() => ({ kind: "server" }));
vi.mock("@supabase/ssr", () => ({ createBrowserClient, createServerClient }));

const storeSet = vi.fn();
const storeGetAll = vi.fn(() => [{ name: "sb-x-auth-token", value: "old" }]);
vi.mock("next/headers", () => ({ cookies: async () => ({ getAll: storeGetAll, set: storeSet }) }));

type CookieArg = { name: string; value: string; options: Record<string, unknown> };
type CreateOptions = { cookieOptions?: { maxAge?: number }; cookies: { getAll: () => unknown; setAll: (items: CookieArg[]) => void } };
const lastOptions = (fn: { mock: { calls: unknown[][] } }) => fn.mock.calls.at(-1)?.[2] as CreateOptions;
const ssrSetCookie = (name: string, value: string): CookieArg => ({ name, value, options: { path: "/", sameSite: "lax", httpOnly: false, maxAge: SSR_DEFAULT_MAX_AGE_S } });
const ssrRemoveCookie = (name: string): CookieArg => ({ name, value: "", options: { path: "/", sameSite: "lax", httpOnly: false, maxAge: 0 } });

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://synthetic.supabase.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_synthetic");
  createBrowserClient.mockClear();
  createServerClient.mockClear();
  storeSet.mockClear();
  document.cookie.split(";").forEach((pair) => {
    const name = pair.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("모든 클라이언트 생성 경로가 같은 쿠키 수명을 받는다", () => {
  it("브라우저·서버 생성 함수가 같은 cookieOptions.maxAge(7일)를 받는다", async () => {
    const { getBrowserSupabase } = await import("./browser");
    const { createRouteSupabase } = await import("./server");
    await getBrowserSupabase();
    await createRouteSupabase();
    expect(createBrowserClient).toHaveBeenCalledTimes(1);
    expect(createServerClient).toHaveBeenCalledTimes(1);
    const browserOptions = lastOptions(createBrowserClient);
    const serverOptions = lastOptions(createServerClient);
    expect(browserOptions.cookieOptions?.maxAge).toBe(AUTH_COOKIE_MAX_AGE_S);
    expect(serverOptions.cookieOptions?.maxAge).toBe(AUTH_COOKIE_MAX_AGE_S);
    expect(browserOptions.cookieOptions).toEqual(serverOptions.cookieOptions);
  });

  it("서버 setAll: 패키지가 400일로 넘겨도 7일로 쓰고, 이름·path·sameSite는 그대로, 지우기(maxAge 0)는 그대로", async () => {
    const { createRouteSupabase } = await import("./server");
    await createRouteSupabase();
    const { cookies } = lastOptions(createServerClient);
    cookies.setAll([ssrSetCookie("sb-x-auth-token", "new"), ssrRemoveCookie("sb-x-auth-token.1")]);
    expect(storeSet).toHaveBeenNthCalledWith(1, "sb-x-auth-token", "new", { path: "/", sameSite: "lax", httpOnly: false, maxAge: AUTH_COOKIE_MAX_AGE_S });
    expect(storeSet).toHaveBeenNthCalledWith(2, "sb-x-auth-token.1", "", { path: "/", sameSite: "lax", httpOnly: false, maxAge: 0 });
    expect(cookies.getAll()).toEqual([{ name: "sb-x-auth-token", value: "old" }]);
  });

  it("브라우저 setAll: document.cookie에 7일(Max-Age=604800)로 쓰고 getAll로 되읽는다", async () => {
    const { getBrowserSupabase } = await import("./browser");
    await getBrowserSupabase();
    const { cookies } = lastOptions(createBrowserClient);
    const { browserAuthCookieStore } = await import("./cookies");
    expect(cookies).toBe(browserAuthCookieStore); // 브라우저 쿠키 저장소는 `cookies.ts` 한 곳이다
    const written: string[] = [];
    const descriptor = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => descriptor?.get?.call(document) ?? "",
      set: (line: string) => {
        written.push(line);
        descriptor?.set?.call(document, line);
      },
    });
    try {
      cookies.setAll([ssrSetCookie("sb-x-auth-token", "new"), ssrRemoveCookie("sb-x-auth-token.1")]);
    } finally {
      Object.defineProperty(document, "cookie", descriptor as PropertyDescriptor);
    }
    expect(written[0]).toBe(`sb-x-auth-token=new; Max-Age=${AUTH_COOKIE_MAX_AGE_S}; Path=/; SameSite=Lax`);
    expect(written[0]).not.toContain(String(SSR_DEFAULT_MAX_AGE_S));
    expect(written[1]).toBe("sb-x-auth-token.1=; Max-Age=0; Path=/; SameSite=Lax");
    expect(cookies.getAll()).toEqual([{ name: "sb-x-auth-token", value: "new" }]);
  });

  it("설정이 없으면(목 모드) 어느 경로도 클라이언트를 만들지 않는다", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    const { getBrowserSupabase } = await import("./browser");
    const { createRouteSupabase } = await import("./server");
    expect(await getBrowserSupabase()).toBeNull();
    expect(await createRouteSupabase()).toBeNull();
    expect(createBrowserClient).not.toHaveBeenCalled();
    expect(createServerClient).not.toHaveBeenCalled();
  });
});
