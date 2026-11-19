import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_ERROR_PARAM, classifyCallbackError } from "@/lib/supabase/callback";
import type { AuthCallbackError } from "@/lib/supabase/callback";
import { createRouteSupabase } from "@/lib/supabase/server";

/**
 * 로그인 콜백(Supabase Redirect URL `/auth/callback`). Google·Kakao 동의와 이메일 확인 링크가 여기로 돌아온다.
 * - `code`가 있으면 세션으로 바꾼다(PKCE. 세션 쿠키는 `@supabase/ssr`가 쓴다)
 * - 공급자 오류(이메일 없는 카카오계정 등)나 교환 실패는 첫 화면에 짧은 종류 값만 넘긴다. 화면이 고정 문구로 안내한다
 * 어느 경우든 첫 화면(`/`)으로만 돌려보낸다(주소로 받은 값으로 이동 대상을 정하지 않는다). 코드·오류 문구는 로그에 남기지 않는다.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const home = (error?: AuthCallbackError) => {
    const target = request.nextUrl.clone();
    target.pathname = "/";
    target.search = "";
    if (error) target.searchParams.set(AUTH_ERROR_PARAM, error);
    return NextResponse.redirect(target);
  };

  if (params.has("error") || params.has("error_code")) return home(classifyCallbackError(params.get("error_code"), params.get("error_description")));

  const code = params.get("code");
  if (!code) return home();

  const supabase = await createRouteSupabase();
  if (!supabase) return home("failed");
  try {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    return error ? home(classifyCallbackError(error.code ?? null, error.message)) : home();
  } catch {
    return home("failed");
  }
}
