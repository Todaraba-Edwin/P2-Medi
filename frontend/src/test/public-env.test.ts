import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");
// Supabase 두 이름은 공개용 주소와 publishable 키다(BE-11-18 A, RLS 전제). 이 밖의 이름은 더하지 않는다
const ALLOWED = new Set(["NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_API_MOCKING", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"]);

function listFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return listFiles(full);
    return /\.(ts|tsx)$/.test(name) && full !== __filename ? [full] : [];
  });
}

describe("NEXT_PUBLIC_* 허용 목록", () => {
  it("src/에서 쓰는 NEXT_PUBLIC_ 변수는 허용된 이름뿐이다", () => {
    const used = new Set<string>();
    for (const file of listFiles(SRC)) {
      for (const m of readFileSync(file, "utf8").matchAll(/process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)/g)) used.add(m[1]);
    }
    expect([...used].filter((name) => !ALLOWED.has(name))).toEqual([]);
  });

  it("서버 전용 Supabase 키(SUPABASE_SECRET_KEY·service_role)를 프런트 코드에서 읽지 않는다", () => {
    for (const file of listFiles(SRC)) {
      const code = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ""); // 주석 제외
      expect(code, file).not.toMatch(/SUPABASE_SECRET_KEY|SUPABASE_SERVICE|service_role/i);
    }
  });

  it("Supabase 설정 값은 설정 모듈 한 곳에서만 읽는다", () => {
    const readers = listFiles(SRC).filter((file) => /process\.env\.NEXT_PUBLIC_SUPABASE_/.test(readFileSync(file, "utf8")));
    expect(readers.map((file) => path.relative(SRC, file))).toEqual(["lib/supabase/config.ts"]);
  });
});
