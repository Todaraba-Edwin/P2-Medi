// 브라우저용 Supabase 클라이언트(`@supabase/ssr`). 세션은 이 패키지의 기본 동작(쿠키)으로만 둔다:
// 프런트 코드는 토큰·이메일을 브라우저 저장소·로그에 따로 남기지 않는다.
import type { SupabaseClient } from "@supabase/supabase-js";
import { supabaseConfig } from "./config";

let client: Promise<SupabaseClient> | null = null;

/**
 * 설정이 없거나 서버 렌더링이면 null. 패키지는 설정이 있을 때만 불러온다(목 모드·미설정 빌드의 첫 화면에 싣지 않는다).
 * 여러 번 불려도 클라이언트는 하나다.
 */
export function getBrowserSupabase(): Promise<SupabaseClient | null> {
  const config = supabaseConfig();
  if (!config || typeof window === "undefined") return Promise.resolve(null);
  client ??= import("@supabase/ssr").then(({ createBrowserClient }) => createBrowserClient(config.url, config.publishableKey));
  return client;
}
