import type { NextRequest } from "next/server";
import { AUTH_ERROR_PARAM, AUTH_RESUME_PARAM, classifyCallbackError } from "@/lib/supabase/callback";
import type { AuthCallbackError } from "@/lib/supabase/callback";
import { createRouteSupabase } from "@/lib/supabase/server";

/**
 * 로그인 콜백(Supabase Redirect URL `/auth/callback`). Google·Kakao 동의와 이메일 확인 링크가 여기로 돌아온다.
 * - `code`가 있으면 세션으로 바꾼다(PKCE. 세션 쿠키는 `@supabase/ssr`가 쓴다). 성공하면 첫 화면에 `auth_resume=1`을 붙여
 *   화면이 온보딩(동의 → 프로필)이 남았을 때 계정 모달을 그 단계로 다시 열게 한다(소셜 로그인은 페이지 이동이라 모달 상태가 사라진다)
 * - 공급자 오류(이메일 없는 카카오계정 등)나 교환 실패는 첫 화면에 짧은 종류 값만 넘긴다. 화면이 고정 문구로 안내한다
 * 어느 경우든 첫 화면(`/`)으로만 돌려보낸다(주소로 받은 값으로 이동 대상을 정하지 않는다). 코드·오류 문구는 로그에 남기지 않는다.
 *
 * 돌려보내는 `Location`은 **상대 경로**다(`/?auth_resume=1` 등). 절대 주소를 만들면 개발 서버에서 `request.nextUrl.origin`이
 * 요청한 호스트(LAN의 `192.168.x.x:3000`)가 아니라 서버가 아는 `localhost:3000`이 되어 다른 기기(아이패드)가 자기 localhost로
 * 가 버린다(2026-11-23 실기기 보고. Next `router-utils/resolve-routes.js`가 `initURL`을 `hostname || 'localhost'`로 만든다).
 * 상대 경로면 브라우저가 지금 접속한 호스트에 붙여 이동하므로 코드가 호스트·포트를 만지지 않는다.
 * `NextResponse.redirect`는 절대 주소만 받으므로 평범한 `Response`를 쓴다. 핸들러 안에서 `cookies().set`으로 쓴 세션 쿠키는
 * Next가 반환된 Response에 합쳐 준다(`route-modules/app-route/module.js` `finalizeResponse` → `appendMutableCookies`).
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const home = (outcome?: AuthCallbackError | "signed_in") => {
    const query = new URLSearchParams();
    if (outcome === "signed_in") query.set(AUTH_RESUME_PARAM, "1");
    else if (outcome) query.set(AUTH_ERROR_PARAM, outcome);
    const search = query.toString();
    return new Response(null, { status: 302, headers: { Location: search ? `/?${search}` : "/" } });
  };

  if (params.has("error") || params.has("error_code")) return home(classifyCallbackError(params.get("error_code"), params.get("error_description")));

  const code = params.get("code");
  if (!code) return home();

  const supabase = await createRouteSupabase();
  if (!supabase) return home("failed");
  try {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    return error ? home(classifyCallbackError(error.code ?? null, error.message)) : home("signed_in");
  } catch {
    return home("failed");
  }
}
