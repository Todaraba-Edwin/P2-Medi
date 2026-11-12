import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import * as generated from "./phrases.generated";

// 원문 대조: 시험 때 백엔드 원본을 다시 읽는다. 백엔드 문구가 바뀌면 실패한다 → node scripts/gen-fixed-phrases.mjs
const py = readFileSync(path.resolve(__dirname, "../../../../backend/app/agent/fixed_phrases.py"), "utf8");
const constant = (name: string) => new RegExp(`^${name}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, "m").exec(py)?.[1];

describe("생성한 고정 문구는 fixed_phrases.py 원문과 같다", () => {
  it("FIXED_NOTICE = NOT_SAFE_NOTICE + 공백 + PHARMACIST_CHECK_NOTICE", () => {
    expect(py).toContain('FIXED_NOTICE = f"{NOT_SAFE_NOTICE} {PHARMACIST_CHECK_NOTICE}"');
    expect(constant("NOT_SAFE_NOTICE")).toBeTruthy();
    expect(constant("PHARMACIST_CHECK_NOTICE")).toBeTruthy();
    expect(generated.FIXED_NOTICE).toBe(`${constant("NOT_SAFE_NOTICE")} ${constant("PHARMACIST_CHECK_NOTICE")}`);
  });

  it("DISCLAIMER = DISCLAIMER_PARTS를 ' · '로 이은 것", () => {
    expect(py).toContain('DISCLAIMER = " · ".join(DISCLAIMER_PARTS)');
    const block = /^DISCLAIMER_PARTS\s*=\s*\(([\s\S]*?)\n\)/m.exec(py)?.[1] ?? "";
    const parts = [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(parts.length).toBeGreaterThan(0);
    expect(generated.DISCLAIMER).toBe(parts.join(" · "));
  });

  it("생성 파일에는 이 두 상수만 있다", () => {
    expect(Object.keys(generated).sort()).toEqual(["DISCLAIMER", "FIXED_NOTICE"]);
  });
});
