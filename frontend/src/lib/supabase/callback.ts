// 로그인 콜백(`/auth/callback`)이 화면에 넘기는 표시 두 가지. 주소에는 짧은 값만 싣고 공급자 오류 문구·이메일·토큰은 싣지 않는다.
// - 실패: `auth_error=<종류>`
// - 성공(세션 교환 완료): `auth_resume=1`. 소셜 로그인은 전체 페이지 이동이라 로그인 모달의 메모리 상태가 사라지므로,
//   화면이 이 표시를 한 번 읽어 온보딩(동의 → 프로필)이 남았으면 모달을 그 단계로 다시 연다(2026-11-22 사용자 보고).
//   브라우저 저장소를 쓰지 않고(FE-01-08 A) 주소 표시만 쓰며, 읽는 즉시 주소에서 지워 새로고침·공유 때 다시 열리지 않는다.
export const AUTH_ERROR_PARAM = "auth_error";
export const AUTH_RESUME_PARAM = "auth_resume";

export const AUTH_CALLBACK_ERRORS = ["email_required", "failed"] as const;
export type AuthCallbackError = (typeof AUTH_CALLBACK_ERRORS)[number];

/** 화면이 문구를 고르는 코드(`features/account/parts.tsx`의 `CODE_MESSAGES`) */
export const AUTH_CALLBACK_ERROR_CODES: Readonly<Record<AuthCallbackError, string>> = {
  email_required: "OAUTH_EMAIL_REQUIRED",
  failed: "OAUTH_FAILED",
};

/**
 * Supabase가 콜백에 붙여 준 오류(`error`·`error_code`·`error_description`)를 화면용 종류로 줄인다.
 * 이메일 없는 카카오계정(BE-11-16 B: `account_email` 필수 동의, "Allow users without an email" OFF)은
 * "Error getting user email from external provider"로 돌아온다(문구는 Supabase Auth 서버 값이라 바뀔 수 있어 넓게 본다).
 */
export function classifyCallbackError(errorCode: string | null, description: string | null): AuthCallbackError {
  const text = `${errorCode ?? ""} ${description ?? ""}`;
  return /getting user email|email[\s_]*(address[\s_]*)?(is[\s_]*)?(not[\s_]*provided|missing|required)/i.test(text) ? "email_required" : "failed";
}

/** 주소의 `auth_error` 값을 읽는다. 모르는 값이면 null */
export function parseAuthError(value: string | null): AuthCallbackError | null {
  return (AUTH_CALLBACK_ERRORS as readonly string[]).includes(value ?? "") ? (value as AuthCallbackError) : null;
}

/**
 * 지금 주소의 표시 하나를 한 번 읽고 주소에서 지운다(새로고침·공유 때 다시 뜨지 않게). 없으면 null.
 * 이력만 고치고 페이지를 옮기지 않는다.
 */
function takeParamFromLocation(name: string): string | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  if (!url.searchParams.has(name)) return null;
  const value = url.searchParams.get(name);
  url.searchParams.delete(name);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  return value;
}

/** 지금 주소에 실린 로그인 실패 표시를 한 번 읽고 주소에서 지운다 */
export function takeAuthErrorFromLocation(): AuthCallbackError | null {
  const value = takeParamFromLocation(AUTH_ERROR_PARAM);
  return value === null ? null : parseAuthError(value);
}

/**
 * 로그인 콜백에서 막 돌아왔는가(`auth_resume=1`). 한 번 읽고 주소에서 지우므로 같은 로그인에 대해 두 번 true가 되지 않는다.
 * 값은 표시일 뿐이고 로그인 여부·온보딩 단계는 서버(`GET /api/me`)가 말한다.
 */
export function takeAuthResumeFromLocation(): boolean {
  return takeParamFromLocation(AUTH_RESUME_PARAM) !== null;
}
