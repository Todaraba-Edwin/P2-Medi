// 서버(라우트 핸들러)용 Supabase 클라이언트. 요청마다 새로 만든다(쿠키 저장소가 요청에 묶여 있다).
// publishable 키만 쓴다. 서버 전용 키(`SUPABASE_SECRET_KEY`)는 프런트 서버에서도 쓰지 않는다.
// 쿠키를 쓰는 `setAll`에서 수명을 7일로 제한한다(`./cookies.ts`, 2026-11-22 사용자 결정). 쿠키 이름·다른 속성은 패키지 값 그대로다.
import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";
import { supabaseConfig } from "./config";
import { AUTH_COOKIE_OPTIONS, limitAuthCookieOptions } from "./cookies";

/** 설정이 없으면 null */
export async function createRouteSupabase(): Promise<SupabaseClient | null> {
  const config = supabaseConfig();
  if (!config) return null;
  const store = await cookies();
  return createServerClient(config.url, config.publishableKey, {
    cookieOptions: AUTH_COOKIE_OPTIONS,
    cookies: {
      getAll: () => store.getAll(),
      setAll: (items) => {
        for (const { name, value, options } of items) store.set(name, value, limitAuthCookieOptions(options));
      },
    },
  });
}
