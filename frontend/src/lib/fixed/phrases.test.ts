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

  it("시작 화면 안내 2종은 원본의 한 줄 글자 그대로이고 승인 전 초안(DRAFT_KEYS)이 아니다(FE-01-19 A·FE-01-24 A)", () => {
    expect(constant("START_EMERGENCY_119")).toBeTruthy();
    expect(constant("START_EXTERNAL_AI_NOTICE")).toBeTruthy();
    expect(generated.START_EMERGENCY_119).toBe(constant("START_EMERGENCY_119"));
    expect(generated.START_EXTERNAL_AI_NOTICE).toBe(constant("START_EXTERNAL_AI_NOTICE"));
    const drafts = /^DRAFT_KEYS[^\n]*$/m.exec(py)?.[0] ?? "";
    expect(drafts).not.toBe("");
    expect(drafts).not.toContain("START_EMERGENCY_119");
    expect(drafts).not.toContain("START_EXTERNAL_AI_NOTICE");
  });

  it("외부 AI 전송 고지는 전송·제공자 쪽 보관을 알리고 학습 사용 여부를 단정하지 않는다(RFP-24-01, PRD-07-02)", () => {
    const notice = generated.START_EXTERNAL_AI_NOTICE;
    expect(notice).toContain("질문과 입력한 프로필");
    expect(notice).toContain("외부 AI");
    expect(notice).toMatch(/제공자의 정책에 따라 일정 기간 보관될 수 있/);
    expect(notice).not.toMatch(/학습/);
  });

  it("시작 화면 119 안내에는 119 말고 다른 연락처가 없다", () => {
    expect(generated.START_EMERGENCY_119).toContain("119");
    expect(generated.START_EMERGENCY_119.replace(/119/g, "")).not.toMatch(/\d/);
  });

  it("생성 파일에는 이 네 상수만 있다", () => {
    expect(Object.keys(generated).sort()).toEqual(["DISCLAIMER", "FIXED_NOTICE", "START_EMERGENCY_119", "START_EXTERNAL_AI_NOTICE"]);
  });
});
