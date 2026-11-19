// 로그인 콜백(`/auth/callback`)이 화면에 넘기는 실패 종류. 주소에는 이 짧은 값만 싣고 공급자 오류 문구·이메일은 싣지 않는다.
export const AUTH_ERROR_PARAM = "auth_error";

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
 * 지금 주소에 실린 로그인 실패 표시를 한 번 읽고 주소에서 지운다(새로고침·공유 때 다시 뜨지 않게).
 * 이력만 고치고 페이지를 옮기지 않는다.
 */
export function takeAuthErrorFromLocation(): AuthCallbackError | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  if (!url.searchParams.has(AUTH_ERROR_PARAM)) return null;
  const error = parseAuthError(url.searchParams.get(AUTH_ERROR_PARAM));
  url.searchParams.delete(AUTH_ERROR_PARAM);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  return error;
}
