// zod 런타임 검증(FE-01-11 A). 원본: backend/app/api/{schemas,events,request}.py(`chat_response@v1`·`chat_event@v1`·`ChatRequest`).
// 컴파일 시점 대조는 contract-check.ts가 생성 타입(generated.ts, `pnpm gen:api`)과 한다.
// 프런트는 **형식**만 본다. 문구 상수 일치(고정 문구·고지·119·진행 문구·공식 기관 목록)와 배지 순서는 백엔드 스키마가 강제하며
// 그 목록을 프런트에 복사하지 않는다. 화면은 받은 값을 받은 순서대로 그린다(S1).
import { z } from "zod";

export const CHAT_RESPONSE_SCHEMA_VERSION = "chat_response@v1";
export const CHAT_EVENT_SCHEMA_VERSION = "chat_event@v1";

// ---------------------------------------------------------------- 공통
const nullableString = z.string().nullable();
const optionalNullableString = z.string().nullable().default(null);
const stringList = z.array(z.string()).default([]);
const looseRows = z.array(z.record(z.string(), z.unknown())).default([]);

export const RouteSchema = z.enum(["AGENT", "REFUSE"]);
/** 끝난 이유. 응급 값은 없다(응급은 `emergency` 필드로만 온다, BE-06-02 A) */
export const EndReasonSchema = z.enum(["NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"]);
export const SourceKindSchema = z.enum(["API_DIRECT", "FILE", "CORPUS_QUOTE"]);
export const BucketSchema = z.enum(["found", "not_listed", "identified", "unconfirmed"]);
export const TargetSchema = z.enum(["product", "pair"]);
export const GradeSchema = z.enum(["1", "2", "M"]);

// ---------------------------------------------------------------- 날짜 줄
// 라벨 5종(schemas.py DATE_LINE_LABELS). 화면은 이 값을 조립하지 않고 받은 그대로 쓴다.
export const DATE_LINE_LABELS = ["고시일", "발간일", "기준일", "조회", "날짜 없음"] as const;
const DATE_LABEL_NONE = "날짜 없음";
const DATE_LABEL_QUERIED = "조회"; // 조회만 하루 단위(월 단위 값 없음)
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const MONTH_RE = /^\d{4}-(\d{2})$/;

function isRealDate(value: string): boolean {
  const m = DATE_RE.exec(value);
  if (!m) return false;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function isMonth(value: string): boolean {
  const m = MONTH_RE.exec(value);
  return m !== null && Number(m[1]) >= 1 && Number(m[1]) <= 12;
}

/** 날짜 한 줄(한 날짜 = 한 항목). 값은 `YYYY-MM-DD` 또는 `YYYY-MM`(조회 제외), `날짜 없음`만 null */
export const DateLineSchema = z
  .strictObject({ label: z.enum(DATE_LINE_LABELS), value: nullableString })
  .superRefine((line, ctx) => {
    if (line.label === DATE_LABEL_NONE) {
      if (line.value !== null) ctx.addIssue({ code: "custom", message: "'날짜 없음' 줄은 value가 없어야 한다" });
      return;
    }
    const ok = line.value !== null && (isRealDate(line.value) || (line.label !== DATE_LABEL_QUERIED && isMonth(line.value)));
    if (!ok) ctx.addIssue({ code: "custom", message: "날짜 값은 YYYY-MM-DD(조회 외에는 YYYY-MM도)여야 한다" });
  });

// ---------------------------------------------------------------- ChatResponse v1
/** 출처 표 한 행(1출처 = 1행). 행 순서는 서버가 정한다 */
export const CitationSchema = z.strictObject({
  publisher: z.string().min(1),
  dataset: z.string(),
  dates: z.array(DateLineSchema).min(1),
  source_kind: SourceKindSchema.nullable().default(null),
  evidence_ids: stringList,
  notice_nos: stringList, // 고시 번호(원문 그대로)
  edition: optionalNullableString, // 판
  pages: stringList, // 쪽(원문 표기 그대로)
});

export const QuoteSchema = z.strictObject({ start: z.number().int(), end: z.number().int(), text: z.string() });

export const SentenceRefSchema = z.strictObject({
  evidence_id: z.string(),
  sentence_index: z.number().int(),
  row_key: optionalNullableString,
  quotes: z.array(QuoteSchema).default([]),
});

/** 근거 상세 한 박스. LLM 문장 없음. 원문 인용은 `rows[]`의 원문 칸 그대로(표 구조 없음) */
export const DetailItemSchema = z
  .strictObject({
    evidence_id: nullableString,
    kind: nullableString,
    status: nullableString,
    source_kind: SourceKindSchema.nullable(),
    dataset_key: nullableString,
    dataset: nullableString,
    publisher: nullableString,
    dates: z.array(DateLineSchema),
    drug_name: optionalNullableString, // 한 약의 근거일 때의 약 이름
    section: optionalNullableString, // 항목명
    flags: stringList,
    notes: stringList,
    rows: looseRows,
    drugs: z.array(z.string()).nullable().default(null),
    item_seq: optionalNullableString,
    label_source: optionalNullableString,
    missing_reason: optionalNullableString,
    missing_text: optionalNullableString, // 미확보 문구(서버 상수). 화면 상수를 쓰지 않는다
  })
  .refine((item) => item.missing_text === null || item.missing_reason !== null, "missing_text는 missing_reason이 있을 때만 온다");

/** 제품 줄의 성분 하나 */
export const IngredientSchema = z.strictObject({
  code: optionalNullableString,
  name: z.string(),
  contra_kinds: stringList, // 이 성분이 걸린 금기 종류 키
  dup: z.boolean().default(false),
});

/** 판정 줄의 배지 하나. `source`는 등급 불일치일 때만 온다 */
export const BadgeSchema = z.strictObject({
  kind: z.string(),
  grade: GradeSchema.nullable().default(null),
  source: SourceKindSchema.nullable().default(null),
  text: z.string().min(1),
  evidence_id: optionalNullableString,
  note: optionalNullableString,
});

export const SearchedSchema = z.strictObject({
  dataset: nullableString,
  count: z.number().int().nonnegative().nullable().default(null),
});

/** 판정 줄. 제품 줄(`product`) 또는 쌍 줄(`pair`, `drugs` 두 약). 배지는 그 줄에 붙고 순서는 서버가 정한다 */
export const FindingSchema = z
  .strictObject({
    target: TargetSchema.default("product"),
    bucket: BucketSchema,
    evidence_id: nullableString,
    kind: nullableString,
    drug: z.string(), // 줄 머리 표시
    drugs: stringList,
    text: z.string(),
    badges: z.array(BadgeSchema).default([]),
    ingredients: z.array(IngredientSchema).default([]),
    notes: stringList,
    source_label: optionalNullableString,
    unresolved: z.boolean().default(false),
    grades: stringList,
    notice_nos: stringList,
    note: optionalNullableString,
    // 미식별
    input_name: optionalNullableString,
    searched: z.array(SearchedSchema).default([]),
    retried: z.boolean().nullable().default(null),
    why: optionalNullableString,
    next: optionalNullableString,
    retried_line: optionalNullableString,
    reference_line: optionalNullableString,
    // 연령금기 나이 기준 값(원문 그대로). 나이를 특정할 수 없을 때 판정 대신 보이는 정보
    age_criteria: stringList,
    age_info_line: optionalNullableString, // 문구 승인 전이라 지금 서버는 항상 null을 보낸다
  })
  .superRefine((finding, ctx) => {
    if (finding.target === "pair" && finding.drugs.length !== 2) ctx.addIssue({ code: "custom", message: "쌍 줄은 drugs에 두 약을 담는다" });
    if (finding.badges.length > 0 && finding.bucket !== "found") ctx.addIssue({ code: "custom", message: "배지는 금기 발견 줄에만 붙는다" });
  });

/** 되묻기 후보 하나(`end_reason == CLARIFY`일 때만) */
export const CandidateSchema = z.strictObject({
  input_name: z.string(),
  name: z.string(),
  item_seq: optionalNullableString,
  entp_name: optionalNullableString,
  prescription: optionalNullableString,
  matched_by: optionalNullableString,
});

/** 119 안내. 문구·전화 링크는 서버 상수 그대로 온다 */
export const EmergencySchema = z.strictObject({ text: z.string().min(1), tel: z.string().min(1) });

export const ChatResponseSchema = z
  .strictObject({
    schema_version: z.literal(CHAT_RESPONSE_SCHEMA_VERSION),
    route: RouteSchema,
    end_reason: EndReasonSchema.nullable().default(null),
    emergency: EmergencySchema.nullable().default(null),
    notice: optionalNullableString, // 상단 배너(서버 상수)
    summary: nullableString,
    findings: z.array(FindingSchema).default([]),
    candidates: z.array(CandidateSchema).default([]),
    detail: z.array(DetailItemSchema).default([]),
    citations: z.array(CitationSchema).default([]),
    sentence_refs: z.array(SentenceRefSchema).default([]),
    grade_def_missing: stringList,
    pharmacist_advice: stringList,
    // 줄 목록: 1줄 이상, 빈 줄 불가. 줄 순서는 서버가 준 그대로 그린다
    fixed_notice: z.array(z.string().refine((s) => s.trim().length > 0, "fixed_notice 줄은 비어 있을 수 없다")).min(1),
    disclaimer: z.string().min(1),
  })
  .refine((response) => response.candidates.length === 0 || response.end_reason === "CLARIFY", "candidates는 되묻기 응답에만 온다");

// ---------------------------------------------------------------- 요청(`ChatRequest`, request.py)
export const QUESTION_MAX_CHARS = 1000;
export const CONFIRMED_DRUGS_MAX = 10;
export const DRUG_NAME_MAX_CHARS = 100;
const notBlank = (s: string) => s.trim().length > 0;

export const AgeUnitSchema = z.enum(["세", "개월", "주"]);

/** 먹는 사람의 나이 구간. 한 나이면 두 값이 같다. 확정 값만 싣는다(자유 글 나이는 싣지 않는다) */
export const AgeInputSchema = z
  .strictObject({ lower: z.number().nonnegative(), upper: z.number().nonnegative(), unit: AgeUnitSchema.default("세") })
  .refine((age) => age.lower <= age.upper, "lower는 upper보다 클 수 없다");

export const ConfirmedDrugSchema = z.strictObject({
  name: z.string().min(1).max(DRUG_NAME_MAX_CHARS).refine(notBlank, "약 이름이 비어 있다"),
  item_seq: z
    .string()
    .regex(/^\d{9}$/)
    .nullable()
    .default(null),
});

/** 같은 대화 안에서 이미 말한 값(한 입력 묶음). 서버는 저장·로그하지 않는다 */
export const RequestContextSchema = z.strictObject({
  age: AgeInputSchema.nullable().default(null),
  pregnant: z.boolean().nullable().default(null),
  confirmed_drugs: z.array(ConfirmedDrugSchema).max(CONFIRMED_DRUGS_MAX).default([]),
});

export const ChatRequestSchema = z.strictObject({
  question: z.string().min(1).max(QUESTION_MAX_CHARS).refine(notBlank, "질문이 비어 있다"),
  context: RequestContextSchema.prefault({}),
});

/** 4xx·5xx JSON 본문. 입력 값·문구는 실려 오지 않는다(화면 문구는 화면 상수) */
export const ErrorBodySchema = z.strictObject({ code: z.string(), fields: stringList });

// ---------------------------------------------------------------- ChatEvent v1(events.py)
export const ProgressStageSchema = z.enum(["drug_lookup", "contraindication_check", "evidence_search"]);
export const ErrorCodeSchema = z.enum(["INTERNAL_ERROR", "TIMEOUT", "UPSTREAM_UNAVAILABLE"]);

const eventBase = {
  seq: z.number().int().nonnegative(),
  schema_version: z.literal(CHAT_EVENT_SCHEMA_VERSION),
};

/** `label`은 서버 상수 문구다. 화면은 그대로 보이고 문구를 만들지 않는다(BE-06-09 A) */
export const ProgressEventSchema = z.strictObject({
  type: z.literal("progress"),
  ...eventBase,
  stage: ProgressStageSchema,
  label: z.string().min(1),
});
export const EmergencyEventSchema = z.strictObject({ type: z.literal("emergency"), ...eventBase, emergency: EmergencySchema });
export const AnswerEventSchema = z.strictObject({ type: z.literal("answer"), ...eventBase, response: ChatResponseSchema });
/** `message`는 서버 오류 문구 상수. 문구 승인 전에는 null이며 그때는 화면 상수를 쓴다 */
export const ErrorEventSchema = z.strictObject({
  type: z.literal("error"),
  ...eventBase,
  code: ErrorCodeSchema,
  message: z.string().min(1).nullable().default(null),
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
