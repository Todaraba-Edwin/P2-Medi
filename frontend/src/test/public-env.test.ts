import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");
const ALLOWED = new Set(["NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_API_MOCKING"]);

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
});
