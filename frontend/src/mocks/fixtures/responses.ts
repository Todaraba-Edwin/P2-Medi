// 합성 응답(f3 A, `chat_response@v1`). 제품명·성분·고시번호·날짜·요약 문장은 모두 가상 값이다. data/mock/을 복사하지 않았다.
// 문구는 phrases.ts(백엔드 상수 원문)만 쓴다. 지금 서버가 비워 보내는 칸(성분·나이 기준 값·판·쪽 등)도 화면 부품을 만들 수 있게 채운 예가 있다.
import { ChatResponseSchema } from "@/lib/api/schemas";
import type { ChatResponse, ChatResponseInput } from "@/lib/api/types";
import {
  BADGE_SOURCE_TAIL,
  CLARIFY_TAIL,
  DATASET_AGE,
  DATASET_CONTRA_PAIR,
  DATASET_DUR_INGR,
  DATASET_PREGNANCY,
  DATASET_PRMSN,
  DISCLAIMER,
  FIXED_NOTICE,
  PHRASES,
  PUBLISHER_KIDS,
  PUBLISHER_MFDS,
  REFUSE_DOSAGE,
  SOURCE_KIND_FILE,
} from "./phrases";

// 합성 약 이름·성분(실제 제품이 아니다)
const DRUG_A = "가나다정";
const DRUG_B = "라마바캡슐";
const DRUG_C = "사아자시럽";
const DRUG_AMBIGUOUS = "가나다";
const DRUG_UNKNOWN = "차카타파정";
const INGR_A = { code: "100001ATB", name: "가나성분" };
const INGR_B = { code: "200002ACH", name: "라마성분" };
const INGR_C = { code: "300003ASY", name: "사아성분" };

type Body = Omit<ChatResponseInput, "schema_version" | "fixed_notice" | "disclaimer">;
type DetailInput = NonNullable<Body["detail"]>[number];
type CitationInput = NonNullable<Body["citations"]>[number];

/** 고정 문구·고지를 붙이고 v1 zod를 통과시킨다(통과하지 못하면 가져오는 순간 실패한다). */
function make(body: Body, fixedNotice: string[] = [FIXED_NOTICE]): ChatResponse {
  return ChatResponseSchema.parse({
    schema_version: "chat_response@v1",
    ...body,
    fixed_notice: fixedNotice,
    disclaimer: DISCLAIMER,
  });
}

const pregnancyBadge = (grade: "1" | "2") => PHRASES.BADGE_PREGNANCY.replace("{grade}", grade);

// ---------------------------------------------------------------- 근거·출처 조각
const pairDates = [
  { label: "고시일", value: "2026-01-15" },
  { label: "기준일", value: "2026-07-31" },
] as const;

const pairDetail: DetailInput = {
  evidence_id: "ev-pair-1",
  kind: "contra_pair",
  status: "FOUND",
  source_kind: "FILE",
  dataset_key: "contra_pair",
  dataset: DATASET_CONTRA_PAIR,
  publisher: PUBLISHER_KIDS,
  dates: [...pairDates],
  rows: [{ notice_no: "20260001", notice_date: "2026-01-15", reason: "합성 사유 문장" }],
  drugs: [DRUG_A, DRUG_B],
};
const pairCitation: CitationInput = {
  publisher: PUBLISHER_KIDS,
  dataset: DATASET_CONTRA_PAIR,
  dates: [...pairDates],
  source_kind: "FILE",
  evidence_ids: ["ev-pair-1"],
  notice_nos: ["20260001"],
};

const pregDates = [
  { label: "고시일", value: "2025-03-02" },
  { label: "기준일", value: "2026-07-21" },
] as const;
const pregDetail = (status: "FOUND" | "NOT_LISTED", drug: string): DetailInput => ({
  evidence_id: "ev-preg-1",
  kind: "pregnancy",
  status,
  source_kind: "FILE",
  dataset_key: "pregnancy",
  dataset: DATASET_PREGNANCY,
  publisher: PUBLISHER_KIDS,
  dates: status === "FOUND" ? [...pregDates] : [{ label: "기준일", value: "2026-07-21" }],
  drug_name: drug,
  rows: status === "FOUND" ? [{ notice_no: "20250002", notice_date: "2025-03-02", grade: "2", detail: "합성 상세정보 문장" }] : [],
  drugs: [drug],
});
const pregCitation = (status: "FOUND" | "NOT_LISTED"): CitationInput => ({
  publisher: PUBLISHER_KIDS,
  dataset: DATASET_PREGNANCY,
  dates: status === "FOUND" ? [...pregDates] : [{ label: "기준일", value: "2026-07-21" }],
  source_kind: "FILE",
  evidence_ids: ["ev-preg-1"],
  notice_nos: status === "FOUND" ? ["20250002"] : [],
});

const pairFinding: NonNullable<Body["findings"]>[number] = {
  target: "pair",
  bucket: "found",
  evidence_id: "ev-pair-1",
  kind: "contra_pair",
  drug: `${DRUG_A} · ${DRUG_B}`,
  drugs: [DRUG_A, DRUG_B],
  text: PHRASES.BADGE_PAIR,
  badges: [{ kind: "contra_pair", text: PHRASES.BADGE_PAIR, evidence_id: "ev-pair-1" }],
  ingredients: [
    { ...INGR_A, contra_kinds: ["contra_pair"] },
    { ...INGR_B, contra_kinds: ["contra_pair"] },
  ],
  source_label: SOURCE_KIND_FILE,
  notice_nos: ["20260001"],
};

// ---------------------------------------------------------------- 응답
/** 정상: 병용금기 발견(쌍 줄 하나) */
export const foundResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
  findings: [pairFinding],
  detail: [pairDetail],
  citations: [pairCitation],
  sentence_refs: [{ evidence_id: "ev-pair-1", sentence_index: 0 }],
});

/** 목록에 없음(안전하다는 뜻이 아님): 제품 줄, 배지 없음 */
export const notListedResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}은 임부금기 목록에서 찾지 못했어요.`,
  findings: [
    {
      target: "product",
      bucket: "not_listed",
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      drug: DRUG_A,
      drugs: [DRUG_A],
      text: PHRASES.NOT_LISTED,
      ingredients: [INGR_A],
      source_label: SOURCE_KIND_FILE,
    },
  ],
  detail: [pregDetail("NOT_LISTED", DRUG_A)],
  citations: [pregCitation("NOT_LISTED")],
});

/** 임부금기 발견(제품 줄, 등급 배지 1개, 성분 칩) */
export const pregnancyResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_B}은 임부금기 목록에 올라 있어요.`,
  findings: [
    {
      target: "product",
      bucket: "found",
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      drug: DRUG_B,
      drugs: [DRUG_B],
      text: pregnancyBadge("2"),
      badges: [{ kind: "pregnancy", grade: "2", text: pregnancyBadge("2"), evidence_id: "ev-preg-1" }],
      ingredients: [
        { ...INGR_B, contra_kinds: ["pregnancy"] },
        { ...INGR_C, dup: true },
      ],
      source_label: SOURCE_KIND_FILE,
      grades: ["2"],
      notice_nos: ["20250002"],
    },
  ],
  detail: [pregDetail("FOUND", DRUG_B)],
  citations: [pregCitation("FOUND")],
  sentence_refs: [{ evidence_id: "ev-preg-1", sentence_index: 0 }],
});

/** 병용 + 임부가 함께: 쌍 줄 하나와 제품 줄 하나(배지는 줄마다 붙는다) */
export const pairAndPregnancyResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있고, ${DRUG_B}은 임부금기 목록에도 올라 있어요.`,
  findings: [pairFinding, ...pregnancyResponse.findings],
  detail: [pairDetail, pregDetail("FOUND", DRUG_B)],
  citations: [pairCitation, pregCitation("FOUND")],
});

/** 등급 불일치: 같은 줄에 파일·성분 API 배지 두 개(출처 꼬리, 파일 → 성분 API) */
export const gradeMismatchResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_B}은 임부금기 목록에 올라 있어요. 자료마다 등급이 달라 둘 다 적었어요.`,
  findings: [
    {
      target: "product",
      bucket: "found",
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      drug: DRUG_B,
      drugs: [DRUG_B],
      text: pregnancyBadge("2"),
      badges: [
        { kind: "pregnancy", grade: "2", source: "FILE", text: `${pregnancyBadge("2")} ${BADGE_SOURCE_TAIL.FILE}`, evidence_id: "ev-preg-1" },
        { kind: "pregnancy", grade: "1", source: "API_DIRECT", text: `${pregnancyBadge("1")} ${BADGE_SOURCE_TAIL.API_DIRECT}`, evidence_id: "ev-preg-api" },
      ],
      ingredients: [{ ...INGR_B, contra_kinds: ["pregnancy"] }],
      source_label: SOURCE_KIND_FILE,
      grades: ["2", "1"],
    },
  ],
  detail: [
    pregDetail("FOUND", DRUG_B),
    {
      evidence_id: "ev-preg-api",
      kind: "pregnancy",
      status: "FOUND",
      source_kind: "API_DIRECT",
      dataset_key: "dur_ingr",
      dataset: DATASET_DUR_INGR,
      publisher: PUBLISHER_MFDS,
      dates: [{ label: "조회", value: "2026-11-12" }],
      drug_name: DRUG_B,
      rows: [{ grade: "1", detail: "합성 상세정보 문장" }],
      drugs: [DRUG_B],
    },
  ],
  citations: [
    { publisher: PUBLISHER_MFDS, dataset: DATASET_DUR_INGR, dates: [{ label: "조회", value: "2026-11-12" }], source_kind: "API_DIRECT", evidence_ids: ["ev-preg-api"] },
    pregCitation("FOUND"),
  ],
});

/** 임부금기 M등급(배지에 덧붙임 글) */
export const pregnancyMResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_B}은 임부금기 목록에 올라 있어요.`,
  findings: [
    {
      target: "product",
      bucket: "found",
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      drug: DRUG_B,
      drugs: [DRUG_B],
      text: PHRASES.BADGE_PREGNANCY_M,
      badges: [{ kind: "pregnancy", grade: "M", text: PHRASES.BADGE_PREGNANCY_M, evidence_id: "ev-preg-1", note: PHRASES.BADGE_PREGNANCY_M_NOTE }],
      note: PHRASES.BADGE_PREGNANCY_M_NOTE,
      grades: ["M"],
    },
  ],
  detail: [pregDetail("FOUND", DRUG_B)],
  citations: [pregCitation("FOUND")],
});

/** 연령금기 발견(나이가 있어 판정한 경우) */
export const ageFoundResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_C}은 연령금기 목록에 올라 있어요.`,
  findings: [
    {
      target: "product",
      bucket: "found",
      evidence_id: "ev-age-1",
      kind: "age",
      drug: DRUG_C,
      drugs: [DRUG_C],
      text: PHRASES.BADGE_AGE,
      badges: [{ kind: "age", text: PHRASES.BADGE_AGE, evidence_id: "ev-age-1" }],
      ingredients: [{ ...INGR_C, contra_kinds: ["age"] }],
      source_label: SOURCE_KIND_FILE,
      age_criteria: ["12세 미만"],
    },
  ],
  detail: [
    {
      evidence_id: "ev-age-1",
      kind: "age",
      status: "FOUND",
      source_kind: "FILE",
      dataset_key: "age",
      dataset: DATASET_AGE,
      publisher: PUBLISHER_KIDS,
      dates: [{ label: "기준일", value: "2026-07-21" }],
      drug_name: DRUG_C,
      rows: [{ age_base: "12세 미만", detail: "합성 상세정보 문장" }],
      drugs: [DRUG_C],
    },
  ],
  citations: [{ publisher: PUBLISHER_KIDS, dataset: DATASET_AGE, dates: [{ label: "기준일", value: "2026-07-21" }], source_kind: "FILE", evidence_ids: ["ev-age-1"] }],
});

/** 미식별: 약을 찾지 못한 줄(입력 이름·찾아본 자료·다음 행동) */
export const unidentifiedResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "product",
        bucket: "unconfirmed",
        evidence_id: null,
        kind: "identify",
        drug: DRUG_UNKNOWN,
        text: PHRASES.UNIDENTIFIED,
        unresolved: true,
        input_name: DRUG_UNKNOWN,
        searched: [
          { dataset: DATASET_PRMSN, count: 0 },
          { dataset: DATASET_CONTRA_PAIR, count: 0 },
        ],
        retried: true,
        why: PHRASES.UNIDENTIFIED_WHY,
        next: PHRASES.UNIDENTIFIED_NEXT,
        retried_line: PHRASES.UNIDENTIFIED_RETRIED,
      },
    ],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 근거 원문 미확보: 미확보 문구(서버 상수)와 약사 확인 권고 줄(권고 → 고정) */
export const missingEvidenceResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
    findings: [pairFinding],
    detail: [
      pairDetail,
      {
        evidence_id: "ev-label-1",
        kind: "label",
        status: "NO_EVIDENCE",
        source_kind: null,
        dataset_key: "prmsn",
        dataset: DATASET_PRMSN,
        publisher: PUBLISHER_MFDS,
        dates: [{ label: "날짜 없음", value: null }],
        drug_name: DRUG_A,
        section: "상호작용",
        drugs: [DRUG_A],
        missing_reason: "SEARCH_MISS",
        missing_text: PHRASES.MISSING_SEARCH_MISS,
      },
    ],
    citations: [pairCitation],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

// ---------------------------------------------------------------- FE-IMPL-06 추가(지시서 A2: 미확보 나머지 원인·폴백 2종·허가사항 원문)
const labelMissing = (id: string, drug: string, section: string, reason: string, text: string): DetailInput => ({
  evidence_id: id,
  kind: "label",
  status: "NO_EVIDENCE",
  source_kind: null,
  dataset_key: "prmsn",
  dataset: DATASET_PRMSN,
  publisher: PUBLISHER_MFDS,
  dates: [{ label: "날짜 없음", value: null }],
  drug_name: drug,
  section,
  drugs: [drug],
  missing_reason: reason,
  missing_text: text,
});

/** 근거 원문 미확보의 나머지 세 원인(범위 밖·항목 없음·불러오지 못함)과 박스 안 약사 확인 권고 줄 */
export const missingCausesResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
    findings: [pairFinding],
    detail: [
      pairDetail,
      labelMissing("ev-label-oos", DRUG_A, "효능·효과", "OUT_OF_SCOPE", PHRASES.MISSING_OUT_OF_SCOPE.replace("{drug}", DRUG_A)),
      labelMissing("ev-label-absent", DRUG_B, "임부에 대한 투여", "ABSENT", PHRASES.MISSING_ABSENT.replace("{drug}", DRUG_B)),
      labelMissing("ev-label-fail", DRUG_B, "상호작용", "FETCH_FAIL", PHRASES.MISSING_FETCH_FAIL),
    ],
    citations: [pairCitation],
    pharmacist_advice: [PHRASES.PHARMACIST_ADVICE.replace("{drugs}", `${DRUG_A}·${DRUG_B}`)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 검증 폴백: 확인된 항목이 없을 때(요약 문구만, 판정 줄 없음) */
export const fallbackNoneResponse = make(
  { route: "AGENT", end_reason: "NORMAL", summary: PHRASES.FALLBACK_NONE_NO_SCOPE },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 검증 폴백: 확인된 항목만 보여 줄 때(요약 문구 + 확인된 판정 줄) */
export const fallbackSomeResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: PHRASES.FALLBACK_SOME_NO_DATE,
    findings: [pairFinding],
    detail: [pairDetail],
    citations: [pairCitation],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 허가사항 원문 인용(전문의약품 경로): 약 이름·항목과 원문 한 덩어리(합성 원문) */
export const rxPermitResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
  findings: [pairFinding],
  detail: [
    pairDetail,
    {
      evidence_id: "ev-permit-1",
      kind: "label",
      status: "FOUND",
      source_kind: "API_DIRECT",
      dataset_key: "prmsn",
      dataset: DATASET_PRMSN,
      publisher: PUBLISHER_MFDS,
      dates: [{ label: "조회", value: "2026-11-12" }],
      drug_name: DRUG_A,
      section: "사용상 주의사항",
      rows: [{ row_key: "ev-permit-1#0", text: "(합성 원문) 다른 약을 복용하고 있는 사람은 이 약을 복용하기 전에 의사 또는 약사와 상의하십시오." }],
      drugs: [DRUG_A],
    },
  ],
  citations: [
    { publisher: PUBLISHER_MFDS, dataset: DATASET_PRMSN, dates: [{ label: "조회", value: "2026-11-12" }], source_kind: "API_DIRECT", evidence_ids: ["ev-permit-1"] },
    pairCitation,
  ],
});

/** 쌍 확인 불가(Result-NoEvidence6c): 두 약을 함께 먹어도 되는지 확인하지 못한 쌍 줄. 배지 없음 */
export const pairNoEvidenceResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "pair",
        bucket: "unconfirmed",
        evidence_id: null,
        kind: "contra_pair",
        drug: `${DRUG_A} · ${DRUG_C}`,
        drugs: [DRUG_A, DRUG_C],
        text: PHRASES.NO_EVIDENCE,
        note: PHRASES.PAIR_NOT_CHECKED,
      },
    ],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 상한 도달: 상단 배너(`notice`)와 여기까지의 결과 */
export const limitResponse = make({
  route: "AGENT",
  end_reason: "LIMIT",
  notice: PHRASES.LIMIT_REACHED,
  summary: null,
  findings: [pairFinding],
  detail: [pairDetail],
  citations: [pairCitation],
});

/** 응급: 119 안내가 있고 금기 조회 결과가 이어진다 */
export const emergencyResponse = make({
  ...foundResponse,
  emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL },
});

/** 되묻기: 질문 한 개와 후보 목록(이름만, 먹어도 되는지는 말하지 않는다) */
export const clarifyResponse = make({
  route: "AGENT",
  end_reason: "CLARIFY",
  summary: `'${DRUG_AMBIGUOUS}'${CLARIFY_TAIL}`,
  candidates: [
    { input_name: DRUG_AMBIGUOUS, name: "가나다정 100밀리그램", item_seq: "200000001", entp_name: "합성제약(주)", prescription: "일반의약품", matched_by: "product_name" },
    { input_name: DRUG_AMBIGUOUS, name: "가나다정 500밀리그램", item_seq: "200000002", entp_name: "합성제약(주)", prescription: "전문의약품", matched_by: "product_name" },
    { input_name: DRUG_AMBIGUOUS, name: "가나다시럽", item_seq: "200000003", entp_name: "가상약품(주)", prescription: "일반의약품", matched_by: "product_name" },
  ],
});

/** 거절(복용량 결정 요청) */
export const refuseResponse = make({
  route: "REFUSE",
  end_reason: "REFUSE",
  summary: REFUSE_DOSAGE,
});

/** 미확보가 있어 약사 확인 권고 줄이 고정 문구 앞에 붙는 경우의 줄 순서(권고 → 고정) */
export const adviceFirstResponse = make(
  { route: "AGENT", end_reason: "NORMAL", summary: null },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);
