// 로그인(Supabase Auth, `@supabase/ssr`)을 감싸는 모듈(FE-04 S1, PRD-01-09 A′·BE-11-18 A).
// `account.ts`만 이 파일을 부른다. 화면·스토어는 `account.ts`의 함수만 쓴다.
//
// - 방식 고르기(`authMode`): MSW 목이 켜져 있으면 `mock`(목 핸들러의 가짜 세션), Supabase 설정이 있으면 `supabase`, 둘 다 아니면 `none`(계정 진입점 숨김)
// - 세션은 `@supabase/ssr` 기본 동작(쿠키)으로만 둔다. 이 모듈은 토큰·이메일·비밀번호를 로그·브라우저 저장소에 남기지 않고, 오류에도 싣지 않는다
// - 실패는 코드만 싣는다(`AuthError.code`). 화면 문구는 `features/account/copy.ts`에 있다
import { isApiMockingEnabled } from "@/mocks";
import { getBrowserSupabase } from "@/lib/supabase/browser";
import { isSupabaseConfigured } from "@/lib/supabase/config";

export type AuthMode = "mock" | "supabase" | "none";

export function authMode(): AuthMode {
  if (isApiMockingEnabled()) return "mock";
  return isSupabaseConfigured() ? "supabase" : "none";
}

/** 로그인 실패 코드(Supabase Auth 오류 코드를 화면이 아는 몇 가지로 줄인 것) */
export type AuthErrorCode = "INVALID_CREDENTIALS" | "EMAIL_NOT_CONFIRMED" | "EMAIL_TAKEN" | "WEAK_PASSWORD" | "EMAIL_SEND_FAILED" | "AUTH_RATE_LIMITED" | "AUTH_FAILED";

/** 로그인 실패. 코드와 상태만 싣는다(입력 값·Supabase 문구는 싣지 않는다). `status` 0은 연결 실패다 */
export class AuthError extends Error {
  constructor(
    readonly code: AuthErrorCode,
    readonly status: number,
  ) {
    super(`auth ${code}`);
    this.name = "AuthError";
  }
}

/** Supabase Auth 오류 코드 → 화면 코드. 목록에 없으면 `AUTH_FAILED` */
const CODE_MAP: Readonly<Record<string, AuthErrorCode>> = {
  invalid_credentials: "INVALID_CREDENTIALS",
  email_not_confirmed: "EMAIL_NOT_CONFIRMED",
  user_already_exists: "EMAIL_TAKEN",
  email_exists: "EMAIL_TAKEN",
  weak_password: "WEAK_PASSWORD",
  // 확인 메일을 보내지 못했다: 메일 한도(기본 SMTP)·허용되지 않은 수신 주소(기본 SMTP는 프로젝트 구성원 주소로만 보낸다)
  over_email_send_rate_limit: "EMAIL_SEND_FAILED",
  email_address_not_authorized: "EMAIL_SEND_FAILED",
  over_request_rate_limit: "AUTH_RATE_LIMITED",
};

interface AuthFailureLike {
  code?: string | null;
  status?: number | null;
}

function toAuthError(error: AuthFailureLike | null | undefined): AuthError {
  const status = typeof error?.status === "number" ? error.status : 0;
  return new AuthError((error?.code ? CODE_MAP[error.code] : undefined) ?? "AUTH_FAILED", status);
}

async function client() {
  const supabase = await getBrowserSupabase().catch(() => null);
  if (!supabase) throw new AuthError("AUTH_FAILED", 0);
  return supabase;
}

/** 콜백 주소: Supabase Redirect URL에 등록한 `/auth/callback`(지금 출처 기준) */
export const authCallbackUrl = (): string => `${window.location.origin}/auth/callback`;

/**
 * 지금 세션의 access token. 없거나 읽지 못하면 null이다(목·미설정도 null).
 * 만료가 가까우면 Supabase 클라이언트가 갱신한 값을 준다. 반환값은 `Authorization` 머리에만 쓴다.
 */
export async function getAccessToken(): Promise<string | null> {
  if (authMode() !== "supabase") return null;
  try {
    const supabase = await getBrowserSupabase();
    const { data } = (await supabase?.auth.getSession()) ?? { data: { session: null } };
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

/** Supabase 세션이 있는가(목·미설정은 늘 false: 목의 로그인 여부는 `GET /api/me`만 안다) */
export async function hasAuthSession(): Promise<boolean> {
  return (await getAccessToken()) !== null;
}

export async function signInWithEmail(email: string, password: string): Promise<void> {
  const supabase = await client();
  const { error } = await supabase.auth.signInWithPassword({ email, password }).catch(() => ({ error: { code: null, status: 0 } }));
  if (error) throw toAuthError(error);
}

/**
 * 이메일 가입. 프로젝트가 이메일 확인을 요구하면 세션 없이 끝난다(`confirm_email`: 메일의 링크가 `/auth/callback`으로 돌아온다).
 * 이미 가입한 주소여도 Supabase는 같은 모양으로 답한다(주소가 가입돼 있는지 알려 주지 않는다).
 */
export async function signUpWithEmail(email: string, password: string): Promise<"signed_in" | "confirm_email"> {
  const supabase = await client();
  const { data, error } = await supabase.auth
    .signUp({ email, password, options: { emailRedirectTo: authCallbackUrl() } })
    .catch(() => ({ data: { session: null }, error: { code: null, status: 0 } }));
  if (error) throw toAuthError(error);
  return data.session ? "signed_in" : "confirm_email";
}

/** 소셜 로그인(Google·Kakao)을 시작한다. 성공하면 Supabase 클라이언트가 공급자 동의 화면으로 페이지를 옮긴다 */
export async function signInWithProvider(provider: "google" | "kakao"): Promise<void> {
  const supabase = await client();
  const { error } = await supabase.auth.signInWithOAuth({ provider, options: { redirectTo: authCallbackUrl() } }).catch(() => ({ error: { code: null, status: 0 } }));
  if (error) throw toAuthError(error);
}

/** 이 브라우저의 세션만 끝낸다(다른 기기는 그대로). 서버에 닿지 못해도 이 브라우저의 세션 쿠키는 지워진다 */
export async function signOut(): Promise<void> {
  const supabase = await getBrowserSupabase().catch(() => null);
  await supabase?.auth.signOut({ scope: "local" }).catch(() => undefined);
}
