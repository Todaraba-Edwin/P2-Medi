// 로그인 상태 유지 쿠키(`sb-…-auth-token`)의 수명을 한 곳에서 정한다(2026-11-22 사용자 결정: 400일은 너무 길다, 1주일로 제한).
// `@supabase/ssr`(0.12.7)는 기본 400일이고, `cookieOptions.maxAge`를 넘겨도 쿠키를 쓸 때 기본값으로 덮어쓴다
// (`dist/main/cookies.js`의 `setCookieOptions`가 `...cookieOptions` 뒤에 `maxAge: DEFAULT_COOKIE_OPTIONS.maxAge`를 둔다).
// 그래서 브라우저·서버 클라이언트 모두 쿠키를 실제로 쓰는 `setAll`에서 이 모듈의 `limitAuthCookieOptions`로 수명을 다시 정한다.
// 다른 옵션(이름·`path`·`sameSite`·`secure`·`httpOnly`)은 패키지가 준 그대로 둔다.
import type { CookieOptions } from "@supabase/ssr";

/** 로그인 상태 유지 쿠키 수명(초). 7일. 토큰이 갱신될 때마다 쿠키를 다시 쓰므로 "마지막 갱신으로부터 7일"이다 */
export const AUTH_COOKIE_MAX_AGE_S = 7 * 24 * 60 * 60;

/** 클라이언트 생성에 넘기는 `cookieOptions`. 패키지가 `maxAge`는 덮어쓰지만 의도를 한 곳에 적어 둔다(생성 경로마다 같은 값) */
export const AUTH_COOKIE_OPTIONS: Readonly<CookieOptions> = Object.freeze({ maxAge: AUTH_COOKIE_MAX_AGE_S });

/**
 * 쿠키를 쓰기 직전에 수명만 7일로 바꾼다. 지우는 쿠키(`maxAge: 0`)는 그대로 둔다.
 * `expires`가 같이 오면 `maxAge`가 우선이지만(RFC 6265) 혼동을 막기 위해 함께 7일 뒤로 맞춘다.
 */
export function limitAuthCookieOptions(options: CookieOptions | undefined, now: number = Date.now()): CookieOptions {
  const base = options ?? {};
  if (base.maxAge !== undefined && base.maxAge <= 0) return base;
  const limited: CookieOptions = { ...base, maxAge: AUTH_COOKIE_MAX_AGE_S };
  if (base.expires !== undefined) limited.expires = new Date(now + AUTH_COOKIE_MAX_AGE_S * 1000);
  return limited;
}

/**
 * 브라우저 클라이언트의 쿠키 저장소. `@supabase/ssr`의 기본 브라우저 동작(`document.cookie` 읽기·쓰기)과 같되 쓰기 수명만 7일로 제한한다.
 * 프런트 코드에서 `document.cookie`를 만지는 곳은 이 모듈뿐이다(`features/account/account.test.tsx`의 저장소 미사용 검사가 이를 고정한다).
 * 토큰·이메일 값을 읽어 다른 곳에 남기지 않는다.
 */
export const browserAuthCookieStore = {
  getAll: (): { name: string; value: string }[] => parseDocumentCookies(document.cookie),
  setAll: (items: { name: string; value: string; options: CookieOptions }[]): void => {
    for (const { name, value, options } of items) document.cookie = serializeCookie(name, value, limitAuthCookieOptions(options));
  },
};

/** 쿠키 헤더 문자열(`document.cookie` 형식)을 `{ name, value }` 목록으로 읽는다(값은 URL 디코딩) */
export function parseDocumentCookies(raw: string): { name: string; value: string }[] {
  if (!raw) return [];
  const out: { name: string; value: string }[] = [];
  for (const pair of raw.split(";")) {
    const index = pair.indexOf("=");
    if (index < 0) continue;
    const name = pair.slice(0, index).trim();
    if (!name) continue;
    const encoded = pair.slice(index + 1).trim();
    let value = encoded;
    try {
      value = decodeURIComponent(encoded);
    } catch {
      // 디코딩이 안 되는 값은 그대로 둔다
    }
    out.push({ name, value });
  }
  return out;
}

/** 브라우저 `document.cookie`에 쓸 한 줄. `@supabase/ssr`가 쓰는 `cookie.serialize`와 같은 속성만 다룬다 */
export function serializeCookie(name: string, value: string, options: CookieOptions = {}): string {
  const parts = [`${name}=${encodeURIComponent(value)}`];
  if (options.maxAge !== undefined) parts.push(`Max-Age=${Math.floor(options.maxAge)}`);
  if (options.domain) parts.push(`Domain=${options.domain}`);
  if (options.path) parts.push(`Path=${options.path}`);
  if (options.expires) parts.push(`Expires=${options.expires.toUTCString()}`);
  if (options.httpOnly) parts.push("HttpOnly");
  if (options.secure) parts.push("Secure");
  if (options.partitioned) parts.push("Partitioned");
  if (options.priority) parts.push(`Priority=${options.priority.charAt(0).toUpperCase()}${options.priority.slice(1).toLowerCase()}`);
  if (options.sameSite !== undefined) {
    const sameSite = options.sameSite === true ? "Strict" : options.sameSite === false ? null : options.sameSite;
    if (sameSite) parts.push(`SameSite=${sameSite.charAt(0).toUpperCase()}${sameSite.slice(1).toLowerCase()}`);
  }
  return parts.join("; ");
}

/** `@supabase/ssr`의 세션 쿠키 이름(`sb-<프로젝트>-auth-token`, 길면 `.0`·`.1`로 나뉜다) */
const AUTH_COOKIE_NAME = /^sb-.+-auth-token(\.\d+)?$/;

/**
 * 이 브라우저에 로그인 세션 쿠키가 **있는가**(FE-17 U-22 추가, 2026-11-24). 첫 그리기에서 "로그인돼 있을 수 있는지"를 기다리지 않고 알기 위해
 * 쿠키 **이름만** 본다(값·토큰은 읽어 남기지 않는다). 있다고 로그인이 확정되지는 않는다(만료 등): 확정은 `bootstrap()`이 한다.
 * 서버 렌더링(문서 없음)에서는 false
 */
export function hasAuthCookie(): boolean {
  if (typeof document === "undefined") return false;
  return parseDocumentCookies(document.cookie).some(({ name }) => AUTH_COOKIE_NAME.test(name));
}
