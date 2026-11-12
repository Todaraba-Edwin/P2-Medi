// zod 런타임 검증(FE-01-11 A). 원본: backend/app/api/schemas.py(`chat_response@v0` 골격)를 손으로 옮겼다.
// v1 이행은 FE-IMPL-03이 한다. 이벤트 형식은 PJ2-프론트-기술스택.md 4장 (4) 초안이며 BE-06이 확정한다.
import { z } from "zod";

export const CHAT_RESPONSE_SCHEMA_VERSION = "chat_response@v0";
export const CHAT_EVENT_SCHEMA_VERSION = "chat_event@v0";

// ---------------------------------------------------------------- ChatResponse v0
// 날짜 라벨 4종(schemas.py DATE_LINE_LABELS). 화면은 이 값을 조립하지 않고 받은 그대로 쓴다.
export const DATE_LINE_LABELS = ["고시일", "기준일", "조회", "날짜 없음"] as const;
const DATE_LABEL_NONE = "날짜 없음";
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const nullableString = z.string().nullable();
const optionalNullableString = z.string().nullable().default(null);
const stringList = z.array(z.string()).default([]);
const looseRows = z.array(z.record(z.string(), z.unknown())).default([]);

export const RouteSchema = z.enum(["AGENT", "REFUSE"]);
export const EndReasonSchema = z.enum(["NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"]);
export const SourceKindSchema = z.enum(["API_DIRECT", "FILE", "CORPUS_QUOTE"]);
export const BucketSchema = z.enum(["found", "not_listed", "identified", "unconfirmed"]);

export const DateLineSchema = z
  .strictObject({ label: z.enum(DATE_LINE_LABELS), value: nullableString })
  .superRefine((line, ctx) => {
    if (line.label === DATE_LABEL_NONE) {
      if (line.value !== null) ctx.addIssue({ code: "custom", message: "'날짜 없음' 줄은 value가 없어야 한다" });
    } else if (line.value === null || !DATE_RE.test(line.value)) {
      ctx.addIssue({ code: "custom", message: "날짜 값은 YYYY-MM-DD여야 한다" });
    }
  });

export const CitationSchema = z.strictObject({
  publisher: z.string().min(1), // 공식 기관 목록 검사는 백엔드 몫(목록을 프런트에 복사하지 않는다)
  dataset: z.string(),
  dates: z.array(DateLineSchema).min(1),
  source_kind: SourceKindSchema.nullable().default(null),
  evidence_ids: stringList,
});

export const QuoteSchema = z.strictObject({ start: z.number().int(), end: z.number().int(), text: z.string() });

export const SentenceRefSchema = z.strictObject({
  evidence_id: z.string(),
  sentence_index: z.number().int(),
  row_key: optionalNullableString,
  quotes: z.array(QuoteSchema).default([]),
});

export const DetailItemSchema = z.strictObject({
  evidence_id: nullableString,
  kind: nullableString,
  status: nullableString,
  source_kind: SourceKindSchema.nullable(),
  dataset_key: nullableString,
  dataset: nullableString,
  publisher: nullableString,
  dates: z.array(DateLineSchema),
  flags: stringList,
  notes: stringList,
  rows: looseRows,
  drugs: z.array(z.string()).nullable().default(null),
  item_seq: optionalNullableString,
  section: optionalNullableString,
  label_source: optionalNullableString,
  missing_reason: optionalNullableString,
});

export const FindingSchema = z.strictObject({
  bucket: BucketSchema,
  evidence_id: nullableString,
  kind: nullableString,
  drug: z.string(),
  text: z.string(),
  notes: stringList,
  source_label: optionalNullableString,
  unresolved: z.boolean().default(false),
  grades: stringList,
  notice_nos: stringList,
  note: optionalNullableString,
  input_name: optionalNullableString,
  why: optionalNullableString,
  next: optionalNullableString,
  retried_line: optionalNullableString,
  reference_line: optionalNullableString,
  searched: looseRows,
});

export const BadgeSchema = z.strictObject({
  kind: nullableString,
  grade: nullableString,
  text: z.string(),
  evidence_id: nullableString,
  note: optionalNullableString,
});

export const EmergencySchema = z.strictObject({ text: z.string(), tel: optionalNullableString });

export const ChatResponseSchema = z.strictObject({
  schema_version: z.literal(CHAT_RESPONSE_SCHEMA_VERSION),
  route: RouteSchema,
  end_reason: EndReasonSchema.nullable().default(null),
  emergency: EmergencySchema.nullable().default(null),
  notice: optionalNullableString,
  summary: nullableString,
  findings: z.array(FindingSchema).default([]),
  badges: z.array(BadgeSchema).default([]),
  detail: z.array(DetailItemSchema).default([]),
  citations: z.array(CitationSchema).default([]),
  sentence_refs: z.array(SentenceRefSchema).default([]),
  grade_def_missing: stringList,
  pharmacist_advice: stringList,
  // 줄 목록: 1줄 이상, 빈 줄 불가
  fixed_notice: z.array(z.string().refine((s) => s.trim().length > 0, "fixed_notice 줄은 비어 있을 수 없다")).min(1),
  disclaimer: z.string().min(1),
});

// ---------------------------------------------------------------- 요청(초안)
// 가정: 요청 모델은 BE-06 v1에서 정한다(대화 상태 한 묶음·확인된 약 목록·대상). 지금은 질문 한 칸만 둔다.
export const ChatRequestSchema = z.object({ question: z.string().min(1) });

// ---------------------------------------------------------------- ChatEvent(초안, 4장 (4))
export const ProgressStageSchema = z.enum(["drug_lookup", "contraindication_check", "evidence_search"]);

const eventBase = {
  seq: z.number().int().nonnegative(),
  schema_version: z.literal(CHAT_EVENT_SCHEMA_VERSION),
};

export const ProgressEventSchema = z.strictObject({ type: z.literal("progress"), ...eventBase, stage: ProgressStageSchema });
export const EmergencyEventSchema = z.strictObject({ type: z.literal("emergency"), ...eventBase, emergency: EmergencySchema });
export const AnswerEventSchema = z.strictObject({ type: z.literal("answer"), ...eventBase, response: ChatResponseSchema });
export const ErrorEventSchema = z.strictObject({
  type: z.literal("error"),
  ...eventBase,
  code: z.string().min(1),
  message: z.string().min(1),
});
export const DoneEventSchema = z.strictObject({
  type: z.literal("done"),
  ...eventBase,
  end_reason: EndReasonSchema.nullable().default(null),
});

export const ChatEventSchema = z.discriminatedUnion("type", [
  ProgressEventSchema,
  EmergencyEventSchema,
  AnswerEventSchema,
  ErrorEventSchema,
  DoneEventSchema,
]);
