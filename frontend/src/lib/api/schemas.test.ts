import { describe, expect, it } from "vitest";
import * as responses from "@/mocks/fixtures/responses";
import { foundResponse, pregnancyResponse } from "@/mocks/fixtures/responses";
import {
  ChatEventSchema,
  ChatRequestSchema,
  ChatResponseSchema,
  DateLineSchema,
  DetailItemSchema,
  ErrorBodySchema,
  FindingSchema,
  GradeDefSchema,
  NameCorrectionSchema,
} from "./schemas";

const valid = () => structuredClone(foundResponse) as Record<string, unknown>;
const finding = (patch: Record<string, unknown>, from = foundResponse) => {
  const body = structuredClone(from) as unknown as { findings: Record<string, unknown>[] };
  Object.assign(body.findings[0], patch);
  return body;
};

describe("ChatResponse v1 zod", () => {
  it.each(Object.entries(responses))("fixture %s를 그대로 통과시킨다", (_name, response) => {
    expect(ChatResponseSchema.parse(structuredClone(response))).toEqual(response);
  });

  it("기본값 칸이 빠져도 채운다", () => {
    const parsed = ChatResponseSchema.parse({
      schema_version: "chat_response@v1",
      route: "AGENT",
      summary: null,
      findings: [{ bucket: "not_listed", evidence_id: null, kind: null, drug: "가나다정", text: "줄 글자" }],
      fixed_notice: ["고정 줄"],
      disclaimer: "고지",
    });
    expect(parsed).toMatchObject({ end_reason: null, emergency: null, notice: null, candidates: [], detail: [], citations: [] });
    expect(parsed.findings[0]).toMatchObject({ target: "product", drugs: [], badges: [], ingredients: [], retried: null, age_criteria: [], age_info_line: null, reasons: [] });
  });

  it("성분의 원인·중복 칸이 없거나 null이면 모름(null)으로 남기고 `[]`·`false`(원인 아님)로 채우지 않는다(BE-06-40 A)", () => {
    const parse = (ingredient: Record<string, unknown>) => ChatResponseSchema.parse(finding({ ingredients: [ingredient] })).findings[0].ingredients[0];
    expect(parse({ name: "가나성분" })).toMatchObject({ contra_kinds: null, dup: null, state_labels: [] });
    expect(parse({ name: "가나성분", contra_kinds: null, dup: null })).toMatchObject({ contra_kinds: null, dup: null });
    expect(parse({ name: "가나성분", contra_kinds: [], dup: false })).toMatchObject({ contra_kinds: [], dup: false });
    expect(parse({ name: "가나성분", contra_kinds: ["pregnancy"], dup: true })).toMatchObject({ contra_kinds: ["pregnancy"], dup: true });
  });

  it("권고 줄 종류(pharmacist_advice_kinds): 칸이 없으면 빈 목록, 값은 missing·grade_def만 받는다(AG-08-28 A)", () => {
    expect(ChatResponseSchema.parse(valid()).pharmacist_advice_kinds).toEqual([]);
    const withKinds = { ...valid(), pharmacist_advice: ["받은 권고 하나", "받은 권고 둘"], pharmacist_advice_kinds: ["missing", "grade_def"] };
    expect(ChatResponseSchema.parse(withKinds).pharmacist_advice_kinds).toEqual(["missing", "grade_def"]);
    expect(ChatResponseSchema.safeParse({ ...withKinds, pharmacist_advice_kinds: ["missing", "other"] }).success).toBe(false);
    expect(ChatResponseSchema.safeParse({ ...withKinds, pharmacist_advice_kinds: "missing" }).success).toBe(false);
  });

  it("제품 줄의 evidence_id·kind가 null이어도 받는다: 한 응답에 null 줄이 여럿이어도 된다(BE-06-41 A)", () => {
    const parsed = ChatResponseSchema.parse(structuredClone(responses.productRowsResponse));
    const productRows = parsed.findings.filter((f) => f.target === "product");
    expect(productRows.length).toBeGreaterThan(1);
    for (const row of productRows) expect(row).toMatchObject({ evidence_id: null, kind: null });
    expect(productRows.flatMap((row) => row.badges).every((badge) => badge.evidence_id !== null)).toBe(true);
  });

  it.each([
    ["v0 문서(schema_version)", { schema_version: "chat_response@v0" }],
    ["v0의 최상위 badges", { badges: [] }],
    ["모르는 칸(extra=forbid)", { extra_field: 1 }],
    ["조회 시각 같은 칸(v1에 없음)", { queried_at: "2026-11-12T01:00:00Z" }],
    ["fixed_notice 0줄", { fixed_notice: [] }],
    ["fixed_notice 빈 줄", { fixed_notice: ["  "] }],
    ["disclaimer 빈 글자", { disclaimer: "" }],
    ["모르는 route", { route: "OTHER" }],
    ["모르는 end_reason", { end_reason: "OTHER" }],
    ["응급을 end_reason으로(값 없음)", { end_reason: "EMERGENCY" }],
    ["tel 없는 emergency", { emergency: { text: "문구" } }],
    ["되묻기가 아닌데 candidates", { candidates: [{ input_name: "가나다", name: "가나다정" }] }],
    ["보정 고지에 text 없음", { name_corrections: [{ input: "가나다졍", name: "가나다정" }] }],
    ["보정 고지에 input 빈 글자", { name_corrections: [{ input: "", name: "가나다정", text: "고지" }] }],
    ["보정 고지 안의 모르는 칸", { name_corrections: [{ input: "가나다졍", name: "가나다정", text: "고지", grade: "1" }] }],
    ["되묻기인데 name_corrections", { end_reason: "CLARIFY", name_corrections: [{ input: "가나다졍", name: "가나다정", text: "고지" }] }],
  ])("%s는 거절한다", (_name, patch) => {
    expect(ChatResponseSchema.safeParse({ ...valid(), ...patch }).success).toBe(false);
  });

  it("v0 fixture 모양(최상위 badges, target·drugs 없음) 전체도 거절한다", () => {
    const v0 = {
      schema_version: "chat_response@v0",
      route: "AGENT",
      end_reason: "NORMAL",
      summary: "요약",
      findings: [{ bucket: "found", evidence_id: "ev-1", kind: "contra_pair", drug: "가나다정 · 라마바캡슐", text: "줄 글자" }],
      badges: [{ kind: "contra_pair", grade: null, text: "배지", evidence_id: "ev-1", note: null }],
      fixed_notice: ["고정 줄"],
      disclaimer: "고지",
    };
    expect(ChatResponseSchema.safeParse(v0).success).toBe(false);
    expect(ChatResponseSchema.safeParse({ ...v0, schema_version: "chat_response@v1" }).success).toBe(false); // 버전만 바꿔도 badges 때문에 거절
  });

  it.each([
    ["쌍 줄인데 약이 하나", { drugs: ["가나다정"] }, false],
    ["쌍 줄인데 약이 셋", { drugs: ["가", "나", "다"] }, false],
    ["모르는 target", { target: "triple" }, false],
    ["금기 발견이 아닌 줄의 배지", { bucket: "not_listed" }, false],
    ["배지 등급 값 밖", { badges: [{ kind: "pregnancy", grade: "3", text: "배지" }] }, false],
    ["배지 글자 없음", { badges: [{ kind: "pregnancy", text: "" }] }, false],
    ["배지 kind 없음", { badges: [{ kind: null, text: "배지" }] }, false],
    ["배지 안의 모르는 칸", { badges: [{ kind: "pregnancy", text: "배지", color: "red" }] }, false],
    ["searched 개수 음수", { searched: [{ dataset: "자료", count: -1 }] }, false],
    ["성분 이름 없음", { ingredients: [{ code: "100001ATB" }] }, false],
    ["나이 기준 값 줄", { age_criteria: ["12세 미만", "6개월 미만"] }, true],
    ["retried 값", { retried: false }, true],
    ["사유 원문 줄(reasons)", { reasons: ["합성 사유 문장"] }, true],
    ["사유 칸이 문자열이 아님", { reasons: [1] }, false],
    // BE-06-40 A: 성분의 원인·중복 칸은 지금 서버 모양(`[]`·`false`)과 모름(`null`·칸 없음)을 모두 받는다
    ["성분 원인·중복 칸: 지금 서버 모양", { ingredients: [{ name: "가나성분", contra_kinds: [], dup: false }] }, true],
    ["성분 원인·중복 칸: null(모름)", { ingredients: [{ name: "가나성분", contra_kinds: null, dup: null }] }, true],
    ["성분 원인·중복 칸: 칸 없음(모름)", { ingredients: [{ name: "가나성분" }] }, true],
    ["성분 원인 칸이 목록이 아님", { ingredients: [{ name: "가나성분", contra_kinds: "pregnancy" }] }, false],
    ["성분 중복 칸이 참·거짓이 아님", { ingredients: [{ name: "가나성분", dup: "yes" }] }, false],
  ])("판정 줄: %s", (_name, patch, ok) => {
    expect(ChatResponseSchema.safeParse(finding(patch)).success).toBe(ok);
  });

  it("배지·성분·출처 행은 받은 순서를 바꾸지 않는다", () => {
    const parsed = ChatResponseSchema.parse(structuredClone(responses.gradeMismatchResponse));
    expect(parsed.findings[0].badges.map((b) => b.source)).toEqual(["FILE", "API_DIRECT"]);
    expect(parsed.citations.map((c) => c.dataset)).toEqual(responses.gradeMismatchResponse.citations.map((c) => c.dataset));
    expect(pregnancyResponse.findings[0].ingredients.map((i) => i.name)).toEqual(["라마성분", "사아성분"]);
  });

  it("미확보 문구는 사유가 있을 때만 온다", () => {
    const body = structuredClone(responses.missingEvidenceResponse) as unknown as { detail: Record<string, unknown>[] };
    body.detail[1].missing_reason = null;
    expect(ChatResponseSchema.safeParse(body).success).toBe(false);
  });
});

describe("DateLine", () => {
  it.each([
    [{ label: "고시일", value: "2026-01-15" }, true],
    [{ label: "발간일", value: "2026-06" }, true],
    [{ label: "기준일", value: "2026-07-31" }, true],
    [{ label: "기준일", value: "2026-06" }, true],
    [{ label: "조회", value: "2026-11-12" }, true],
    [{ label: "날짜 없음", value: null }, true],
    [{ label: "조회", value: "2026-11" }, false], // 조회는 하루 단위만
    [{ label: "날짜 없음", value: "2026-01-15" }, false],
    [{ label: "고시일", value: null }, false],
    [{ label: "고시일", value: "2026.01.15" }, false],
    [{ label: "고시일", value: "2026-13-45" }, false], // 없는 날짜
    [{ label: "고시일", value: "2026-02-30" }, false],
    [{ label: "기준일", value: "2026-13" }, false],
    [{ label: "고시일", value: "2026-01-15T00:00:00" }, false], // 시각 없음
    [{ label: "자료 기준일", value: "2026-01-15" }, false],
  ])("%j → %s", (line, ok) => {
    expect(DateLineSchema.safeParse(line).success).toBe(ok);
  });
});

describe("ChatEvent v1 zod", () => {
  const base = { seq: 0, schema_version: "chat_event@v1" };

  it.each([
    [{ ...base, type: "progress", stage: "drug_lookup", label: "약 찾는 중" }, true],
    [{ ...base, type: "emergency", emergency: { text: "t", tel: "tel:119", wide_text: "w" } }, true],
    [{ ...base, type: "emergency", emergency: { text: "t", tel: "tel:119" } }, false], // 넓은 폭 보조 문장은 항상 온다
    [{ ...base, type: "answer", response: foundResponse }, true],
    [{ ...base, type: "error", code: "INTERNAL_ERROR", message: null }, false], // 오류 문구는 항상 문자열이다
    [{ ...base, type: "error", code: "TIMEOUT" }, false],
    [{ ...base, type: "error", code: "TIMEOUT", message: "받은 문구" }, true],
    [{ ...base, type: "error", code: "UPSTREAM_UNAVAILABLE", message: "받은 문구" }, true],
    [{ ...base, type: "done" }, true],
    [{ ...base, type: "done", end_reason: "NORMAL" }, true],
    [{ ...base, type: "progress", stage: "drug_lookup" }, false], // label 필수
    [{ ...base, type: "progress", stage: "drug_lookup", label: "" }, false],
    [{ ...base, type: "progress", stage: "unknown_stage", label: "문구" }, false],
    [{ ...base, type: "error", code: "MOCK_SERVER_ERROR", message: null }, false], // 코드 목록 밖
    [{ ...base, type: "error", message: "문구" }, false],
    [{ ...base, type: "emergency", emergency: { text: "t" } }, false], // tel 필수
    [{ ...base, type: "unknown" }, false],
    [{ ...base, schema_version: "chat_event@v0", type: "done" }, false],
    [{ ...base, seq: -1, type: "done" }, false],
    [{ ...base, type: "done", extra: 1 }, false],
    [{ ...base, type: "answer", response: { ...foundResponse, schema_version: "chat_response@v0" } }, false],
  ])("%j → %s", (event, ok) => {
    expect(ChatEventSchema.safeParse(event).success).toBe(ok);
  });
});

describe("ChatRequest·ErrorBody zod", () => {
  it("질문만 주면 빈 묶음이 채워진다", () => {
    expect(ChatRequestSchema.parse({ question: "질문" })).toEqual({ question: "질문", context: { age: null, pregnant: null, confirmed_drugs: [] } });
  });

  it.each([
    [{ question: "질문", context: { age: { lower: 3, upper: 5, unit: "개월" }, pregnant: true } }, true],
    [{ question: "가".repeat(1000) }, true],
    [{ question: "" }, false],
    [{ question: "  " }, false],
    [{ question: "가".repeat(1001) }, false],
    [{ question: "질문", extra: 1 }, false],
    [{ question: "질문", context: { age: "5세" } }, false], // 자유 글 나이는 싣지 않는다
    [{ question: "질문", context: { age: { lower: 5, upper: 5, unit: "살" } } }, false],
    [{ question: "질문", context: { age: { lower: -1, upper: 5 } } }, false],
    [{ question: "질문", context: { confirmed_drugs: [{ name: " " }] } }, false],
    [{ question: "질문", context: { confirmed_drugs: [{ name: "가".repeat(101) }] } }, false],
    [{ question: "질문", context: { confirmedDrugs: [] } }, false], // 칸 이름은 snake_case
  ])("%j → %s", (request, ok) => {
    expect(ChatRequestSchema.safeParse(request).success).toBe(ok);
  });

  it("오류 본문은 code와 fields뿐이다", () => {
    expect(ErrorBodySchema.parse({ code: "INVALID_REQUEST" })).toEqual({ code: "INVALID_REQUEST", fields: [] });
    expect(ErrorBodySchema.safeParse({ code: "INVALID_REQUEST", fields: ["question"], input: "질문" }).success).toBe(false);
  });
});

describe("AG-08·BE-06-13~17 새 칸", () => {
  const base = { schema_version: "chat_response@v1", route: "AGENT", summary: null, fixed_notice: ["줄"], disclaimer: "고지" };
  const ok = (extra: object) => ChatResponseSchema.safeParse({ ...base, ...extra }).success;

  it("새 칸이 빠져도 기본값으로 채운다", () => {
    const parsed = ChatResponseSchema.parse(base);
    expect(parsed).toMatchObject({ candidates_line: null, not_checked_lines: [], grade_defs: [], name_corrections: [] });
    const finding = FindingSchema.parse({ bucket: "found", evidence_id: null, kind: null, drug: "d", text: "t", ingredients: [{ name: "성분" }] });
    expect(finding).toMatchObject({ sub_line: null, age_info_line: null });
    expect(finding.ingredients[0]).toMatchObject({ state_labels: [], code_missing_text: null });
    const detail = DetailItemSchema.parse({ evidence_id: null, kind: null, status: null, source_kind: null, dataset_key: null, dataset: null, publisher: null, dates: [] });
    expect(detail).toMatchObject({ source_kind_label: null, label_help: null, easy_text_missing_line: null, quote_notice: null });
  });

  it("새 칸에 값이 와도 받는다(모르는 칸으로 거절하지 않는다)", () => {
    expect(ok({ not_checked_lines: ["줄"], grade_defs: [{ grade: "2", title: "제목", text: "원문", source: "출처" }] })).toBe(true);
    expect(ok({ end_reason: "CLARIFY", candidates: [{ input_name: "가", name: "가나" }], candidates_line: "안내" })).toBe(true);
    expect(ok({ emergency: { text: "t", tel: "tel:119", wide_text: "w" } })).toBe(true);
  });

  it("되묻기 안내는 후보가 있을 때만, 119 보조 문장은 항상 온다", () => {
    expect(ok({ candidates_line: "안내" })).toBe(false);
    expect(ok({ emergency: { text: "t", tel: "tel:119" } })).toBe(false);
  });

  it("보정 고지(FE-02): 받은 순서·글자 그대로 받고, 되묻기 응답에는 올 수 없다", () => {
    const corrections = [
      { input: "가나다졍", name: "가나다정", text: "받은 고지 하나" },
      { input: "라마바캅슐", name: "라마바캡슐", text: "받은 고지 둘" },
    ];
    expect(ChatResponseSchema.parse({ ...base, name_corrections: corrections }).name_corrections).toEqual(corrections);
    expect(ok({ end_reason: "NORMAL", name_corrections: corrections })).toBe(true);
    expect(ok({ end_reason: "CLARIFY", candidates: [{ input_name: "가", name: "가나" }], name_corrections: corrections })).toBe(false);
    expect(ok({ end_reason: "CLARIFY", candidates: [{ input_name: "가", name: "가나" }], name_corrections: [] })).toBe(true);
    expect(NameCorrectionSchema.safeParse({ input: "가나다졍", name: "가나다정", text: "" }).success).toBe(false);
    expect(NameCorrectionSchema.safeParse({ input: "가나다졍", text: "고지" }).success).toBe(false);
  });

  it.each([
    [{ grade: "2", title: "제목", text: "원문", source: "출처" }, true],
    [{ grade: "1", title: "제목", missing_reason: "FETCH_FAIL", missing_text: "문구" }, true],
    [{ grade: "M", title: "제목", missing_reason: "OUT_OF_SCOPE", missing_text: "문구" }, true],
    [{ grade: "2", title: "제목" }, false], // 원문도 미확보 사유도 없음
    [{ grade: "2", title: "제목", text: "원문", missing_reason: "FETCH_FAIL" }, false], // 둘 다 있음
    [{ grade: "2", title: "제목", source: "출처", missing_reason: "FETCH_FAIL", missing_text: "문구" }, false], // 원문 없는 블록에 출처 줄
    [{ grade: "2", title: "제목", missing_reason: "SEARCH_MISS", missing_text: "문구" }, false], // 사유 목록 밖
    [{ grade: "3", title: "제목", text: "원문" }, false],
    [{ grade: "2", title: "제목", text: "원문", extra: 1 }, false],
  ])("등급 정의 블록 %j → %s", (def, expected) => {
    expect(GradeDefSchema.safeParse(def).success).toBe(expected);
  });
});
