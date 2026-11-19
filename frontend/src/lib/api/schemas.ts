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
    // 서버 상수 글자 칸: 화면은 받은 글자를 그대로 그린다(BE-06-14·15)
    source_kind_label: optionalNullableString, // 출처 종류 글자(`공식 파일` 등). 출처 종류가 있으면 항상 온다
    label_help: optionalNullableString, // 허가사항 한 줄 설명. 허가정보 원문 근거에만
    easy_text_missing_line: optionalNullableString, // 전문의약품 안내 줄
    quote_notice: optionalNullableString, // 용법용량 원문 인용 고지. 인용 바로 아래에 둔다
  })
  .refine((item) => item.missing_text === null || item.missing_reason !== null, "missing_text는 missing_reason이 있을 때만 온다");

/** 제품 줄의 성분 하나 */
export const IngredientSchema = z.strictObject({
  code: optionalNullableString,
  name: z.string(),
  // 이 성분이 걸린 금기 종류 키·같은 성분 중복 여부. `null`(또는 칸 없음) = **모름**(복합제처럼 어느 성분이 원인인지 가리지 못한 줄, BE-06-40 A),
  // `[]`·`false` = 원인·중복 아님. 화면은 모름을 "원인 아님"으로 바꾸지 않는다(기본값을 `[]`·`false`로 채우지 않는다)
  contra_kinds: z.array(z.string()).nullable().default(null),
  dup: z.boolean().nullable().default(null),
  state_labels: stringList, // 상태 글자(서버 상수, BE-06-13). 받은 순서 그대로 그린다
  code_missing_text: optionalNullableString, // 성분코드 미확보 안내(서버 상수). 코드가 없을 때만
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

// ---------------------------------------------------------------- 결과 구역·요약(GROUP-01 3단계, FE-11-04~08 A·AG-22-07 A)
// 서버가 판정 줄마다 구역을 정하고 순서도 정한다(`schemas.py _section_sorted`). 화면은 받은 순서 그대로 그린다.
// 칸이 없는 줄(`null`)은 검색 근거 줄이다(근거 상세에만, FE-11-07 B). 구역별 그리기·접기는 4단계 디자인 뒤 5단계 본 작업이다(지금은 타입만)
export const SectionSchema = z.enum(["core", "caution", "rest", "unconfirmed"]);

/** 제품 줄의 병용금기 짝 참조(FE-11-05 A). `text`는 서버 상수(`PAIR_REF_LINE`)에 건수를 넣은 글자 그대로 */
export const PairRefSchema = z.strictObject({
  count: z.number().int().min(1),
  evidence_ids: z.array(z.string()).min(1),
  text: z.string().min(1),
});

/** 요약에 든 걸린 짝 하나(두 약 표시 이름) */
export const PairFoundSchema = z.strictObject({
  drugs: z.array(z.string()).length(2),
  evidence_ids: stringList,
});

/** 약 2개 이상 결과의 맨 위 요약(문구 ④⑤). LLM `summary`와 별개의 코드 칸. 화면은 `text`·`pair_only_notice`만 그대로 그린다 */
export const ResultSummarySchema = z.strictObject({
  n_drugs: z.number().int().min(2),
  n_pairs: z.number().int().min(1),
  pairs_found: z.array(PairFoundSchema).default([]),
  n_pairs_unchecked: z.number().int().nonnegative(),
  text: z.string().min(1),
  pair_only_notice: optionalNullableString, // 약 3개 이상일 때만 온다(서버 상수)
});

/** 나머지 구역 접힘 줄(문구 ⑥). 건수·글자·버튼 글자 모두 서버 값이다(화면은 세지 않는다) */
export const RestFoldSchema = z.strictObject({
  count: z.number().int().min(1),
  text: z.string().min(1),
  open_label: z.string().min(1),
  close_label: z.string().min(1),
});

/** 용량주의 되묻기(AG-22-02 B·05 A). 고르면 같은 질문을 `context.took_today`와 함께 다시 보낸다(카드는 4단계 디자인 뒤) */
export const DoseCheckSchema = z.strictObject({
  question: z.string().min(1),
  options: z.array(z.string().min(1)).min(1),
  drugs: stringList,
  evidence_ids: stringList,
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
    age_info_line: optionalNullableString, // 나이 기준 값의 안내 문구(서버 상수). 나이 기준 값이 있을 때만 온다
    sub_line: optionalNullableString, // 표지 아래 보조줄(서버가 만든 값: 식별된 약의 성분 이름 등)
    // 병용금기 쌍 줄의 금기 사유 원문(FE-02-06 A, 서버 `Finding.reasons`). 원문 그대로·중복 제거, 용량 숫자가 걸리는 사유는 서버가 뺀다.
    // 서버가 칸을 주기 전에도 깨지지 않게 기본값은 빈 목록이다
    reasons: stringList,
    // ---- 결과 구역(GROUP-01 3단계). 모두 선택 칸: 없으면 null(검색 근거 줄·이전 서버)
    section: SectionSchema.nullable().default(null),
    pair_ref: PairRefSchema.nullable().default(null), // 제품 줄에만. 병용 배지 대신 붙는 짝 참조
    caution_desc: optionalNullableString, // 용량주의 줄 아래 설명(서버 상수 `DOSE_CAUTION_DESC`)
  })
  .superRefine((finding, ctx) => {
    if (finding.target === "pair" && finding.drugs.length !== 2) ctx.addIssue({ code: "custom", message: "쌍 줄은 drugs에 두 약을 담는다" });
    if (finding.badges.length > 0 && finding.bucket !== "found") ctx.addIssue({ code: "custom", message: "배지는 금기 발견 줄에만 붙는다" });
    if (finding.pair_ref !== null && finding.target !== "product") ctx.addIssue({ code: "custom", message: "짝 참조는 제품 줄에만 붙는다" });
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
export const EmergencySchema = z.strictObject({
  text: z.string().min(1),
  tel: z.string().min(1),
  wide_text: z.string().min(1), // 넓은 폭에서만 보이는 보조 문장(FE-07-15). 항상 온다
});

/** 약사 확인 권고 줄의 종류(AG-08-28 A): 미확보 항목 권고 / 등급 정의 권고 */
export const AdviceKindSchema = z.enum(["missing", "grade_def"]);

export const GradeMissingReasonSchema = z.enum(["FETCH_FAIL", "OUT_OF_SCOPE"]);

/** 등급 정의 블록 하나(BE-06-16). 원문(`text`)과 미확보 사유는 둘 중 하나만 있다. 원문이 없으면 출처 줄도 없다 */
export const GradeDefSchema = z
  .strictObject({
    grade: GradeSchema,
    title: z.string().min(1), // 블록 제목(서버 상수)
    text: optionalNullableString, // 고시 원문(서버가 읽은 글자 그대로)
    source: optionalNullableString, // 조항 출처 줄
    missing_reason: GradeMissingReasonSchema.nullable().default(null),
    missing_text: optionalNullableString, // 미확보 문구(서버 상수)
  })
  .superRefine((def, ctx) => {
    if ((def.text === null) === (def.missing_reason === null)) ctx.addIssue({ code: "custom", message: "등급 정의 블록은 원문과 미확보 사유 중 하나만 가진다" });
    if (def.missing_reason !== null && def.source !== null) ctx.addIssue({ code: "custom", message: "원문이 없는 등급 정의 블록에는 출처 줄이 없다" });
  });

/**
 * 오탈자 보정 고지 한 줄(AG-10-02 A, FE-02). 질문에 적힌 이름 조각(`input`)을 비슷한 사전 이름(`name`) 하나로 보고 확인했다는 표시다.
 * `text`는 서버가 상수 `TYPO_CORRECTED_LINE`에 두 이름을 넣어 완성한 문장이다: 화면은 `text`를 그대로 보이고 다시 조립하지 않는다. 판정이 아니다
 */
export const NameCorrectionSchema = z.strictObject({
  input: z.string().min(1),
  name: z.string().min(1),
  text: z.string().min(1),
});

export const ChatResponseSchema = z
  .strictObject({
    schema_version: z.literal(CHAT_RESPONSE_SCHEMA_VERSION),
    route: RouteSchema,
    end_reason: EndReasonSchema.nullable().default(null),
    emergency: EmergencySchema.nullable().default(null),
    notice: optionalNullableString, // 상단 배너(서버 상수)
    // 보정 고지(요약보다 먼저 보인다). 보정이 없으면 서버는 키 자체를 싣지 않으므로 기본 빈 목록(events.py `exclude`)
    name_corrections: z.array(NameCorrectionSchema).default([]),
    summary: nullableString,
    findings: z.array(FindingSchema).default([]),
    candidates: z.array(CandidateSchema).default([]),
    candidates_line: optionalNullableString, // 되묻기 카드 안내(서버 상수). 후보가 있을 때만
    not_checked_lines: stringList, // 정보가 없어 확인하지 못한 종류의 줄(서버 상수)
    detail: z.array(DetailItemSchema).default([]),
    citations: z.array(CitationSchema).default([]),
    sentence_refs: z.array(SentenceRefSchema).default([]),
    grade_def_missing: stringList,
    grade_defs: z.array(GradeDefSchema).default([]), // 등급 정의 블록(구조). 위 줄 목록도 그대로 온다
    pharmacist_advice: stringList, // 미확보 항목이 있으면 비지 않는다(BE-06-17, 서버가 강제)
    // 권고 줄마다의 종류(AG-08-28 A). `pharmacist_advice`와 같은 길이·순서이고(서버가 강제), 비어 있으면 서버가 키를 싣지 않으므로 기본 빈 목록.
    // 근거 상세가 이 값으로 구역별 권고를 고른다(sections.ts `adviceOf`). 길이가 어긋나면 고르지 않고 전부 보인다(권고를 숨기지 않는 쪽)
    pharmacist_advice_kinds: z.array(AdviceKindSchema).default([]),
    // 줄 목록: 1줄 이상, 빈 줄 불가. 줄 순서는 서버가 준 그대로 그린다
    fixed_notice: z.array(z.string().refine((s) => s.trim().length > 0, "fixed_notice 줄은 비어 있을 수 없다")).min(1),
    disclaimer: z.string().min(1),
    // ---- 결과 묶음 요약·되묻기·고지(GROUP-01 3단계, AG-22·FE-11). 모두 선택 칸: 값이 없으면 서버가 키를 싣지 않으므로 기본 null.
    // 글자는 서버 상수이고 화면은 그대로 그린다. 구역별 접기·용량 되묻기 카드는 4단계 디자인 뒤(지금은 타입만)
    result_summary: ResultSummarySchema.nullable().default(null),
    rest_fold: RestFoldSchema.nullable().default(null),
    dose_check: DoseCheckSchema.nullable().default(null),
    dose_notice: optionalNullableString, // "예" 답일 때 맨 위 강조 고지(`notice`와 별개)
    redose_notice: optionalNullableString, // 재복용 질문 고지(`summary` 밖)
  })
  .refine((response) => response.candidates.length === 0 || response.end_reason === "CLARIFY", "candidates는 되묻기 응답에만 온다")
  .refine((response) => response.candidates_line === null || response.candidates.length > 0, "candidates_line은 후보가 있을 때만 온다")
  .refine((response) => response.name_corrections.length === 0 || response.end_reason !== "CLARIFY", "name_corrections는 조회 결과를 보이는 응답에만 온다(되묻기에는 없다)")
  .refine((response) => response.dose_check === null || response.dose_notice === null, "dose_check와 dose_notice는 함께 오지 않는다");

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
  // 그 약을 고른 되묻기 묶음의 이름(응답 `candidates[].input_name` 그대로, 선택 칸, FE-09-05 A). 있으면 서버가 질문 속 그 이름의 약에만 확정한다
  input_name: z.string().min(1).max(DRUG_NAME_MAX_CHARS).refine(notBlank, "입력 이름이 비어 있다").nullable().default(null),
});

/**
 * 같은 대화 안에서 이미 말한 값(한 입력 묶음). 서버는 저장·로그하지 않는다.
 * - `confirmed_drugs`: **이번 질문의 되묻기 답**(같은 질문을 다시 보낼 때만 채운다, AG-21-02 A). 서버가 바로 확정한다
 * - `prior_drugs`: **이전 차례에서 고른 약**(같은 모양, 상한 같음). 확정에 쓰지 않고 같은 이름이 다시 나오면 확인 되묻기에만 쓴다
 * - `took_today`: 용량주의 되묻기 답(예 `true`/아니요 `false`, 답하지 않았으면 null). 서버는 엄격한 불리언만 받는다(AG-22-05 A)
 */
export const RequestContextSchema = z.strictObject({
  age: AgeInputSchema.nullable().default(null),
  pregnant: z.boolean().nullable().default(null),
  confirmed_drugs: z.array(ConfirmedDrugSchema).max(CONFIRMED_DRUGS_MAX).default([]),
  prior_drugs: z.array(ConfirmedDrugSchema).max(CONFIRMED_DRUGS_MAX).default([]),
  took_today: z.boolean().nullable().default(null),
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
/** `message`는 서버 오류 문구 상수이고 항상 온다(2026-11-12 승인 뒤). 화면은 받은 글자를 그대로 보인다 */
export const ErrorEventSchema = z.strictObject({
  type: z.literal("error"),
  ...eventBase,
  code: ErrorCodeSchema,
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
