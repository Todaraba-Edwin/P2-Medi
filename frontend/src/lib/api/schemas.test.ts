import { describe, expect, it } from "vitest";
import { foundResponse } from "@/mocks/fixtures/responses";
import { ChatEventSchema, ChatResponseSchema, DateLineSchema } from "./schemas";

const valid = () => structuredClone(foundResponse) as Record<string, unknown>;

describe("ChatResponse v0 zod", () => {
  it("fixture를 그대로 통과시킨다", () => {
    expect(ChatResponseSchema.parse(valid())).toEqual(foundResponse);
  });

  it("기본값 칸이 빠져도 채운다", () => {
    const parsed = ChatResponseSchema.parse({
      schema_version: "chat_response@v0",
      route: "AGENT",
      summary: null,
      fixed_notice: ["고정 줄"],
      disclaimer: "고지",
    });
    expect(parsed.findings).toEqual([]);
    expect(parsed.end_reason).toBeNull();
    expect(parsed.emergency).toBeNull();
  });

  it.each([
    ["다른 schema_version", { schema_version: "chat_response@v1" }],
    ["모르는 칸(extra=forbid)", { extra_field: 1 }],
    ["fixed_notice 0줄", { fixed_notice: [] }],
    ["fixed_notice 빈 줄", { fixed_notice: ["  "] }],
    ["disclaimer 빈 글자", { disclaimer: "" }],
    ["모르는 route", { route: "OTHER" }],
    ["모르는 end_reason", { end_reason: "OTHER" }],
  ])("%s는 거절한다", (_name, patch) => {
    expect(ChatResponseSchema.safeParse({ ...valid(), ...patch }).success).toBe(false);
  });

  it("안쪽 객체의 모르는 칸도 거절한다", () => {
    const body = valid();
    (body.badges as Record<string, unknown>[])[0].color = "red";
    expect(ChatResponseSchema.safeParse(body).success).toBe(false);
  });
});

describe("DateLine", () => {
  it.each([
    [{ label: "고시일", value: "2026-01-15" }, true],
    [{ label: "기준일", value: "2026-07-31" }, true],
    [{ label: "조회", value: "2026-11-12" }, true],
    [{ label: "날짜 없음", value: null }, true],
    [{ label: "날짜 없음", value: "2026-01-15" }, false],
    [{ label: "고시일", value: null }, false],
    [{ label: "고시일", value: "2026.01.15" }, false],
    [{ label: "고시일", value: "2026-01-15T00:00:00" }, false],
    [{ label: "자료 기준일", value: "2026-01-15" }, false],
  ])("%j → %s", (line, ok) => {
    expect(DateLineSchema.safeParse(line).success).toBe(ok);
  });
});

describe("ChatEvent zod", () => {
  const base = { seq: 0, schema_version: "chat_event@v0" };

  it.each([
    [{ ...base, type: "progress", stage: "drug_lookup" }, true],
    [{ ...base, type: "emergency", emergency: { text: "t", tel: "tel:119" } }, true],
    [{ ...base, type: "answer", response: foundResponse }, true],
    [{ ...base, type: "error", code: "X", message: "m" }, true],
    [{ ...base, type: "done" }, true],
    [{ ...base, type: "done", end_reason: "NORMAL" }, true],
    [{ ...base, type: "progress", stage: "unknown_stage" }, false],
    [{ ...base, type: "progress", stage: "drug_lookup", label: "약 찾는 중" }, false],
    [{ ...base, type: "unknown" }, false],
    [{ ...base, schema_version: "chat_event@v1", type: "done" }, false],
    [{ ...base, seq: -1, type: "done" }, false],
    [{ ...base, type: "answer", response: { ...foundResponse, schema_version: "chat_response@v1" } }, false],
    [{ ...base, type: "error", code: "X" }, false],
  ])("%j → %s", (event, ok) => {
    expect(ChatEventSchema.safeParse(event).success).toBe(ok);
  });
});
