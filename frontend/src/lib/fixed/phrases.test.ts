import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import * as generated from "./phrases.generated";

// 원문 대조: 시험 때 백엔드 원본을 다시 읽는다. 백엔드 문구가 바뀌면 실패한다 → node scripts/gen-fixed-phrases.mjs
const py = readFileSync(path.resolve(__dirname, "../../../../backend/app/agent/fixed_phrases.py"), "utf8");
const prov = readFileSync(path.resolve(__dirname, "../../../../backend/app/tools/provenance.py"), "utf8");
const constant = (name: string) => new RegExp(`^${name}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, "m").exec(py)?.[1];
/** 파이썬 dict 블록 안의 `KEY: "..."` 한 줄 값 */
const dictValue = (source: string, dict: string, key: string) => {
  const block = new RegExp(`^${dict}\\s*=\\s*\\{([\\s\\S]*?)\\n\\}`, "m").exec(source)?.[1] ?? "";
  return new RegExp(`^\\s*${key}\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"\\s*,`, "m").exec(block)?.[1];
};

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

  it("시작 화면 119 안내는 원본의 한 줄 글자 그대로이고 승인 전 초안(DRAFT_KEYS)이 아니다(FE-01-19 A·FE-01-24 A)", () => {
    expect(constant("START_EMERGENCY_119")).toBeTruthy();
    expect(generated.START_EMERGENCY_119).toBe(constant("START_EMERGENCY_119"));
    const drafts = /^DRAFT_KEYS[^\n]*$/m.exec(py)?.[0] ?? "";
    expect(drafts).not.toBe("");
    expect(drafts).not.toContain("START_EMERGENCY_119");
  });

  it("시작 화면 외부 AI 고지는 원본에도 생성 파일에도 없다(PRD-17-10 A: 외부 AI 고지는 입력창 고지 하나)", () => {
    expect(constant("START_EXTERNAL_AI_NOTICE")).toBeUndefined();
    expect("START_EXTERNAL_AI_NOTICE" in generated).toBe(false);
    expect(generated.START_EMERGENCY_119).not.toMatch(/외부 AI|OpenAI/);
  });

  it("시작 화면 119 안내에는 119 말고 다른 연락처가 없다", () => {
    expect(generated.START_EMERGENCY_119).toContain("119");
    expect(generated.START_EMERGENCY_119.replace(/119/g, "")).not.toMatch(/\d/);
  });

  it("실시간 확인 실패 배너·줄 노트(판별용, FE-11-10 A)는 fixed_phrases.NOTICE_API_FAIL과 provenance.FLAG_NOTES·API_REASON_NOTES 원문 그대로다", () => {
    expect(constant("NOTICE_API_FAIL")).toBeTruthy();
    expect(generated.NOTICE_API_FAIL).toBe(constant("NOTICE_API_FAIL"));
    // 서버 조립: finalize._notes → provenance.api_flag_note(꼬리표·사유) = FLAG_NOTES[꼬리표] 또는 API_REASON_NOTES[사유]
    expect(py).toContain("from app.tools.provenance import API_REASON_NOTES as _API_REASON_NOTES");
    expect(py).toContain("API_REASON_NOTES = dict(_API_REASON_NOTES)");
    const expected = [
      dictValue(prov, "FLAG_NOTES", '"API_FAIL"'),
      dictValue(prov, "FLAG_NOTES", '"API_PAIR_INCOMPLETE"'),
      dictValue(prov, "API_REASON_NOTES", "API_REASON_NO_CODE"),
      dictValue(prov, "API_REASON_NOTES", "API_REASON_PARTIAL"),
      dictValue(prov, "API_REASON_NOTES", "API_REASON_TRUNCATED"),
    ];
    for (const text of expected) expect(text).toBeTruthy();
    expect([...generated.API_FLAG_NOTES]).toEqual(expected);
    // 판별 대상 문장은 모두 "실시간 확인"으로 시작한다(본문 0회 시험이 이 글자를 센다)
    for (const text of [generated.NOTICE_API_FAIL, ...generated.API_FLAG_NOTES]) expect(text).toMatch(/^실시간 확인/);
  });

  it("결과 화면 표시 가공의 판별용 원문(FE-17 U-30)은 provenance.FLAG_NOTES·fixed_phrases.NOT_LISTED·CAUTION_LABELS 원문 그대로다", () => {
    expect(dictValue(prov, "FLAG_NOTES", '"API_SAME"')).toBeTruthy();
    expect(generated.API_SAME_NOTE).toBe(dictValue(prov, "FLAG_NOTES", '"API_SAME"'));
    expect(constant("NOT_LISTED")).toBeTruthy();
    expect(generated.NOT_LISTED).toBe(constant("NOT_LISTED"));
    const dose = /^CAUTION_LABELS\s*=\s*\{[^\n}]*"dose":\s*"((?:[^"\\]|\\.)*)"/m.exec(py)?.[1];
    expect(dose).toBeTruthy();
    expect(generated.CAUTION_DOSE_LABEL).toBe(dose);
    // 괄호 안내를 떼는 규칙은 "목록에 없음(…)" 꼴일 때만 의미가 있다(떼고 남는 글자가 비지 않는다)
    expect(generated.NOT_LISTED).toMatch(/^[^(]+\([^()]+\)$/);
  });

  // 기대값 갱신(2026-11-24, FE-17 U-30): 표시 가공 판별용 3개(API_SAME_NOTE·NOT_LISTED·CAUTION_DOSE_LABEL)를 더했다. 그 밖의 상수는 여전히 더하지 않는다
  it("생성 파일에는 이 여덟 상수만 있다", () => {
    expect(Object.keys(generated).sort()).toEqual([
      "API_FLAG_NOTES",
      "API_SAME_NOTE",
      "CAUTION_DOSE_LABEL",
      "DISCLAIMER",
      "FIXED_NOTICE",
      "NOTICE_API_FAIL",
      "NOT_LISTED",
      "START_EMERGENCY_119",
    ]);
  });
});
