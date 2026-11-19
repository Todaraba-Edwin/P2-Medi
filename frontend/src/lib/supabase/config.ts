// Supabase 로그인 설정(BE-11-18 A). 공개용 주소와 publishable 키 두 이름만 읽는다(RLS 전제).
// 서버 전용 키(`SUPABASE_SECRET_KEY`)는 프런트에서 쓰지 않는다. 값은 로그·화면에 남기지 않는다.
export interface SupabaseConfig {
  url: string;
  publishableKey: string;
}

/** 두 값이 모두 있어야 설정된 것이다. 하나라도 비면 null(로그인 진입점을 숨긴다) */
export function supabaseConfig(): SupabaseConfig | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim();
  return url && publishableKey ? { url, publishableKey } : null;
}

export const isSupabaseConfigured = (): boolean => supabaseConfig() !== null;
