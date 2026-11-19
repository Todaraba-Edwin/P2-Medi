// 합성 응답(f3 A, `chat_response@v1`). 제품명·성분·고시번호·날짜·요약 문장은 모두 가상 값이다. data/mock/을 복사하지 않았다.
// 문구는 phrases.ts(백엔드 상수 원문)만 쓴다. 지금 서버가 비워 보내는 칸(성분·나이 기준 값·판·쪽 등)도 화면 부품을 만들 수 있게 채운 예가 있다.
import { ChatResponseSchema } from "@/lib/api/schemas";
import type { ChatResponse, ChatResponseInput } from "@/lib/api/types";
import {
  BADGE_SOURCE_TAIL,
  CAUTION_DUP_INGREDIENT,
  CLARIFY_TAIL,
  CODE_NOT_LINKED,
  DATASET_AGE,
  DATASET_CONTRA_PAIR,
  DATASET_DUR_INGR,
  DATASET_PREGNANCY,
  DATASET_PRMSN,
  DISCLAIMER,
  DOSE_SECTION,
  FIXED_NOTICE,
  GRADE_DEF_MISSING_FETCH_FAIL,
  GRADE_DEF_MISSING_OUT_OF_SCOPE,
  NAME_JOIN,
  PHRASES,
  PUBLISHER_KIDS,
  PUBLISHER_MFDS,
  REFUSE_DOSAGE,
  SOURCE_KIND_PREFIX,
  SOURCE_PREFIX_FILE,
  fillCorrection,
  clarifyMultiQuestion,
  fillJosa,
  fillPriorPick,
  ingredientStateLabels,
  resultSummaryFound,
} from "./phrases";

// 합성 약 이름·성분(실제 제품이 아니다)
const DRUG_A = "가나다정";
const DRUG_A_TYPO = "가나다졍"; // `DRUG_A`에서 모음 하나만 다른 합성 오탈자(백엔드 가짜 서버 `typo` 시나리오와 같은 꼴)
const DRUG_B = "라마바캡슐";
const DRUG_C = "사아자시럽";
const DRUG_AMBIGUOUS = "가나다";
const DRUG_AMBIGUOUS_2 = "가나다시럽";
const DRUG_AMBIGUOUS_3 = "라마바";
const DRUG_UNKNOWN = "차카타파정";
// 원인·중복 칸은 지금 서버처럼 `[]`·`false`(원인·중복 아님)를 분명히 싣는다. 칸이 없으면 "모름"이다(BE-06-40 A)
const INGR_A = { code: "100001ATB", name: "가나성분", contra_kinds: [] as string[], dup: false };
const INGR_B = { code: "200002ACH", name: "라마성분", contra_kinds: [] as string[], dup: false };
const INGR_C = { code: "300003ASY", name: "사아성분", contra_kinds: [] as string[], dup: false };

type Body = Omit<ChatResponseInput, "schema_version" | "fixed_notice" | "disclaimer">;
type DetailInput = NonNullable<Body["detail"]>[number];
type CitationInput = NonNullable<Body["citations"]>[number];

/**
 * 서버가 스스로 채우는 상수 글자 칸을 같은 규칙으로 채운다(backend/app/api/schemas.py의 검증기·`_detail_item`):
 * 성분 칩 상태 글자(`state_labels`), 출처 종류 글자(`source_kind_label`), 허가사항 한 줄 설명(`label_help`, 허가정보 원문 근거에만),
 * 용법용량 인용 고지(`quote_notice`), 되묻기 안내(`candidates_line`, 후보가 있을 때만).
 */
function serverFill(body: Body): Body {
  return {
    ...body,
    candidates_line: body.candidates && body.candidates.length > 0 ? PHRASES.CLARIFY_PICK_LINE : null,
    findings: body.findings?.map((finding) => ({
      ...finding,
      ingredients: finding.ingredients?.map((ingredient) => ({
        ...ingredient,
        state_labels: ingredientStateLabels(ingredient.contra_kinds ?? [], ingredient.dup ?? false),
      })),
    })),
    detail: body.detail?.map((item) => ({
      ...item,
      source_kind_label: item.source_kind ? SOURCE_KIND_PREFIX[item.source_kind] : null,
      label_help: item.source_kind && item.dataset_key === "prmsn" ? PHRASES.LABEL_ONE_LINE : null,
      quote_notice: item.section === DOSE_SECTION && (item.rows?.length ?? 0) > 0 ? PHRASES.DOSE_QUOTE_NOTICE : null,
    })),
  };
}

/** 고정 문구·고지를 붙이고 v1 zod를 통과시킨다(통과하지 못하면 가져오는 순간 실패한다). */
function make(body: Body, fixedNotice: string[] = [FIXED_NOTICE]): ChatResponse {
  return ChatResponseSchema.parse({
    schema_version: "chat_response@v1",
    ...serverFill(body),
    fixed_notice: fixedNotice,
    disclaimer: DISCLAIMER,
  });
}

const pregnancyBadge = (grade: "1" | "2") => PHRASES.BADGE_PREGNANCY.replace("{grade}", grade);
/** 판정 줄의 출처 표지: 서버 `finalize._source_label` → `provenance.badge` = `{종류} · {자료 약칭}`(FE-IMPL-06b: 서버와 일치) */
const fileLabel = (dataset: string) => `${SOURCE_PREFIX_FILE} · ${dataset}`;
/** 약사 확인 권고 줄: 확인하지 못한 줄의 약 이름을 `" · "`로 잇는다(finalize.py 291행, 같은 이름은 한 번) */
const adviceFor = (...drugs: string[]) => fillJosa(PHRASES.PHARMACIST_ADVICE, "drugs", [...new Set(drugs)].join(NAME_JOIN));
const EMERGENCY = { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL, wide_text: PHRASES.EMERGENCY_119_WIDE };

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
  source_label: fileLabel(DATASET_CONTRA_PAIR),
  notice_nos: ["20260001"],
  // 서버 `Finding.reasons`(FE-02-06 A): 근거 `rows[].reason` 원문 그대로, 중복 제거
  reasons: ["합성 사유 문장"],
};

/** 미확보 근거 항목(허가사항)의 "확인하지 못함" 제품 줄: 서버 `_finding`이 내는 모양(배지·출처 표지 없음) */
const labelFinding = (id: string, drug: string, text: string): NonNullable<Body["findings"]>[number] => ({
  target: "product",
  bucket: "unconfirmed",
  evidence_id: id,
  kind: "label",
  drug,
  drugs: [drug],
  text,
  unresolved: true,
});

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
      source_label: fileLabel(DATASET_PREGNANCY),
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
      source_label: fileLabel(DATASET_PREGNANCY),
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
      source_label: fileLabel(DATASET_PREGNANCY),
      grades: ["2", "1"],
    },
  ],
  detail: [
    // 등급이 다르다는 안내는 그 근거의 `notes`에 한 번만 온다(GRADE_MISMATCH_NOTE)
    { ...pregDetail("FOUND", DRUG_B), notes: [PHRASES.GRADE_MISMATCH_NOTE] },
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
      source_label: fileLabel(DATASET_PREGNANCY),
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
      source_label: fileLabel(DATASET_AGE),
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
        sub_line: fillJosa(PHRASES.UNIDENTIFIED_SUB_LINE, "drug", DRUG_UNKNOWN),
      },
    ],
    pharmacist_advice: [adviceFor(DRUG_UNKNOWN)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/**
 * 약 하나는 찾고 하나는 못 찾은 질문(PRD-14-04 A, PRD-14 §6 ⑦): 못 찾은 약 줄 + 찾은 약의 요약 한 줄(`찾음` + 성분 이름).
 * 찾은 약 줄에는 판정(목록에 없음 등)이 없다: 다른 약을 못 찾아 쌍을 확인하지 못했기 때문이다. 줄 모양은 서버 `finalize` 출력과 같다
 */
export const unidentifiedMixedResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      unidentifiedResponse.findings[0],
      {
        target: "product",
        bucket: "identified",
        evidence_id: null,
        kind: "identify",
        drug: DRUG_A,
        drugs: [DRUG_A],
        text: PHRASES.IDENTIFIED_LINE,
        // 지금 서버는 원인·중복 칸을 `[]`·`false`로 싣는다(이름만 든 성분, 코드 없음)
        ingredients: [
          { name: INGR_A.name, contra_kinds: [], dup: false },
          { name: INGR_C.name, contra_kinds: [], dup: false },
        ],
        sub_line: [INGR_A.name, INGR_C.name].join(PHRASES.IDENTIFIED_SUB_SEP),
      },
    ],
    pharmacist_advice: [adviceFor(DRUG_UNKNOWN)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 근거 원문 미확보: 미확보 문구(서버 상수)와 약사 확인 권고 줄(권고 → 고정) */
export const missingEvidenceResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
    // 미확보 근거 항목도 finalize 항목이라 "확인하지 못함" 줄이 하나 생긴다(줄 글자 = MISSING_TEXT[사유], finalize._missing_text)
    findings: [pairFinding, labelFinding("ev-label-1", DRUG_A, PHRASES.MISSING_SEARCH_MISS)],
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
    pharmacist_advice: [adviceFor(DRUG_A)],
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
    findings: [
      pairFinding,
      labelFinding("ev-label-oos", DRUG_A, PHRASES.MISSING_OUT_OF_SCOPE.replace("{drug}", DRUG_A)),
      labelFinding("ev-label-absent", DRUG_B, PHRASES.MISSING_ABSENT.replace("{drug}", DRUG_B)),
      labelFinding("ev-label-fail", DRUG_B, PHRASES.MISSING_FETCH_FAIL),
    ],
    detail: [
      pairDetail,
      labelMissing("ev-label-oos", DRUG_A, "효능·효과", "OUT_OF_SCOPE", PHRASES.MISSING_OUT_OF_SCOPE.replace("{drug}", DRUG_A)),
      labelMissing("ev-label-absent", DRUG_B, "임부에 대한 투여", "ABSENT", PHRASES.MISSING_ABSENT.replace("{drug}", DRUG_B)),
      labelMissing("ev-label-fail", DRUG_B, "상호작용", "FETCH_FAIL", PHRASES.MISSING_FETCH_FAIL),
    ],
    citations: [pairCitation],
    pharmacist_advice: [adviceFor(DRUG_A, DRUG_B, DRUG_B)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/**
 * 검증 폴백: 확인된 항목이 없을 때(요약 문구만, 판정 줄 없음). 항목이 없으면 확인하지 못한 줄도 없으므로
 * 서버는 고정 영역에 권고 줄(`PHARMACIST_ADVICE_FIXED`)을 붙이지 않는다(finalize: `unresolved`일 때만)
 */
export const fallbackNoneResponse = make({ route: "AGENT", end_reason: "NORMAL", summary: PHRASES.FALLBACK_NONE_NO_SCOPE });

/**
 * 검증 폴백: 확인된 항목만 보여 줄 때(요약 문구 + 확인된 판정 줄). 자료 이름이 있으면 서버는 `FALLBACK_SOME_CONFIRMED`에
 * 자료마다 `{label}(기준일 {doc_date})`를 채운다(`fallback_summary`). 확인하지 못한 줄이 없으니 권고 줄도 없다
 */
export const fallbackSomeResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: PHRASES.FALLBACK_SOME_CONFIRMED.replace(
    "{datasets}",
    PHRASES.FALLBACK_SOME_DATASET_DATED.replace("{label}", DATASET_CONTRA_PAIR).replace("{doc_date}", "2026-07-31"),
  ),
  findings: [pairFinding],
  detail: [pairDetail],
  citations: [pairCitation],
});

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
      flags: ["EASY_TEXT_MISSING"],
      rows: [{ row_key: "ev-permit-1#0", text: "(합성 원문) 다른 약을 복용하고 있는 사람은 이 약을 복용하기 전에 의사 또는 약사와 상의하십시오." }],
      drugs: [DRUG_A],
      easy_text_missing_line: PHRASES.EASY_TEXT_MISSING.replace("{drug}", DRUG_A),
    },
    {
      // 용법용량 원문 인용: 바로 아래에 인용 고지(`quote_notice`)가 온다(표로 쪼개지 않는다)
      evidence_id: "ev-permit-2",
      kind: "label",
      status: "FOUND",
      source_kind: "API_DIRECT",
      dataset_key: "prmsn",
      dataset: DATASET_PRMSN,
      publisher: PUBLISHER_MFDS,
      dates: [{ label: "조회", value: "2026-11-12" }],
      drug_name: DRUG_A,
      section: DOSE_SECTION,
      rows: [{ row_key: "ev-permit-2#0", text: "(합성 원문) 성인 1회 1정을 복용한다." }],
      drugs: [DRUG_A],
    },
  ],
  citations: [
    { publisher: PUBLISHER_MFDS, dataset: DATASET_PRMSN, dates: [{ label: "조회", value: "2026-11-12" }], source_kind: "API_DIRECT", evidence_ids: ["ev-permit-1", "ev-permit-2"] },
    pairCitation,
  ],
});

/**
 * 쌍 확인 불가(Result-NoEvidence6c): 식별된 약 줄(`찾음` + 성분 이름 보조줄)과 식별하지 못한 약이 든 쌍 줄.
 * 서버 모양 그대로다(2026-11-16 AG-08 병합 뒤 `finalize` → `to_chat_response`를 합성 항목으로 돌려 확인):
 * 쌍 줄은 줄 글자 한 번뿐이고 `notes[]`에 같은 문장·`why`·`next`가 오지 않는다. 식별된 약 줄의 성분은 이름만 온다.
 */
export const pairNoEvidenceResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "product",
        bucket: "identified",
        evidence_id: "ev-ident-a",
        kind: "identify",
        drug: DRUG_A,
        drugs: [DRUG_A],
        text: PHRASES.IDENTIFIED_LINE,
        // 지금 서버는 원인·중복 칸을 `[]`·`false`로 싣는다(이름만 든 성분, 코드 없음)
        ingredients: [
          { name: INGR_A.name, contra_kinds: [], dup: false },
          { name: INGR_C.name, contra_kinds: [], dup: false },
        ],
        source_label: `${SOURCE_PREFIX_FILE} · ${DATASET_PRMSN}`,
        sub_line: [INGR_A.name, INGR_C.name].join(PHRASES.IDENTIFIED_SUB_SEP),
      },
      {
        target: "pair",
        bucket: "unconfirmed",
        evidence_id: "ev-pair-nc",
        kind: "contra_pair",
        drug: `${DRUG_A}${NAME_JOIN}${DRUG_C}`,
        drugs: [DRUG_A, DRUG_C],
        text: PHRASES.PAIR_NOT_CHECKED,
        unresolved: true,
      },
    ],
    detail: [
      {
        evidence_id: "ev-ident-a",
        kind: "identify",
        status: "FOUND",
        source_kind: "FILE",
        dataset_key: "identify",
        dataset: DATASET_PRMSN,
        publisher: PUBLISHER_MFDS,
        dates: [{ label: "기준일", value: "2026-11-01" }],
        drug_name: DRUG_A,
      },
      {
        evidence_id: "ev-pair-nc",
        kind: "contra_pair",
        status: "UNIDENTIFIED",
        source_kind: null,
        dataset_key: null,
        dataset: null,
        publisher: null,
        dates: [{ label: "날짜 없음", value: null }],
        flags: ["PAIR_NOT_CHECKED"],
        drugs: [DRUG_A, DRUG_C],
      },
    ],
    citations: [{ publisher: PUBLISHER_MFDS, dataset: DATASET_PRMSN, dates: [{ label: "기준일", value: "2026-11-01" }], source_kind: "FILE", evidence_ids: ["ev-ident-a"] }],
    pharmacist_advice: [adviceFor(`${DRUG_A}${NAME_JOIN}${DRUG_C}`)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

// ---------------------------------------------------------------- FE-IMPL-08 추가(AG-08·BE-06-13~17의 새 칸)
/**
 * 나이를 특정할 수 없을 때(Result-Infant·Detail-Infant): 판정 대신 나이별 연령금기 원문 값과 안내 줄(`age_info_line`),
 * 그리고 성분 중복 줄. **서버에는 아직 이 줄을 만드는 경로가 없다**(AG-02 대기). 모양은 백엔드 스키마 시험
 * (`test_0e_age_info_line_is_constant_and_needs_criteria`)의 것을 따랐다: 확인하지 못한 연령 줄 + 나이 기준 값 + 안내 문구.
 */
export const ageInfoResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "product",
        bucket: "unconfirmed",
        evidence_id: "ev-age-1",
        kind: "age",
        drug: DRUG_C,
        drugs: [DRUG_C],
        text: PHRASES.NO_EVIDENCE,
        ingredients: [{ ...INGR_C, dup: true }],
        source_label: fileLabel(DATASET_AGE),
        unresolved: true,
        age_criteria: ["12세 미만", "6개월 미만"],
        age_info_line: PHRASES.AGE_INFO_LINE,
      },
      {
        target: "pair",
        bucket: "found",
        evidence_id: null,
        kind: "dup_ingredient",
        drug: `${DRUG_B}${NAME_JOIN}${DRUG_C}`,
        drugs: [DRUG_B, DRUG_C],
        text: CAUTION_DUP_INGREDIENT,
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
        rows: [{ row_key: "r0" }, { row_key: "r1" }],
        drugs: [DRUG_C],
      },
    ],
    citations: [{ publisher: PUBLISHER_KIDS, dataset: DATASET_AGE, dates: [{ label: "기준일", value: "2026-07-21" }], source_kind: "FILE", evidence_ids: ["ev-age-1"] }],
    pharmacist_advice: [adviceFor(DRUG_C)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 등급 정의 블록(BE-06-16): 원문이 있는 블록(제목·원문·출처 줄)과 미확보 블록(문구만, 출처 줄 없음) + 약사 권고 */
export const gradeDefsResponse = make({
  ...pregnancyResponse,
  grade_defs: [
    {
      grade: "2",
      title: PHRASES.GRADE_DEF_TITLE.replace("{grade}", "2"),
      text: "(합성 고시 원문) 사람에서 태아에 대한 위해성이 나타날 수 있어 원칙적으로 사용금지.",
      source: "(합성 출처 줄) 「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 나목",
    },
    {
      grade: "1",
      title: PHRASES.GRADE_DEF_TITLE.replace("{grade}", "1"),
      missing_reason: "FETCH_FAIL",
      missing_text: GRADE_DEF_MISSING_FETCH_FAIL.replace("{grade}", "1"),
    },
  ],
  grade_def_missing: [GRADE_DEF_MISSING_FETCH_FAIL.replace("{grade}", "1")],
  pharmacist_advice: [PHRASES.GRADE_DEF_PHARMACIST_ADVICE],
});

/**
 * 등급 정의 블록 미확보, 사유 `OUT_OF_SCOPE`(원문 자료가 아직 준비되지 않음, PRD-15-03): 등급 불일치 응답의 1·2등급 블록이 둘 다 미확보다.
 * 블록마다 그 사유의 상수 문구만 있고 출처 줄이 없다. 한쪽만 빈 상태(ISSUE-011)를 만들지 않는다
 */
export const gradeDefsOutOfScopeResponse = make({
  ...gradeMismatchResponse,
  grade_defs: (["2", "1"] as const).map((grade) => ({
    grade,
    title: PHRASES.GRADE_DEF_TITLE.replace("{grade}", grade),
    missing_reason: "OUT_OF_SCOPE" as const,
    missing_text: GRADE_DEF_MISSING_OUT_OF_SCOPE.replace("{grade}", grade),
  })),
  grade_def_missing: (["2", "1"] as const).map((grade) => GRADE_DEF_MISSING_OUT_OF_SCOPE.replace("{grade}", grade)),
  pharmacist_advice: [PHRASES.GRADE_DEF_PHARMACIST_ADVICE],
});

/**
 * 등급 정의 미확보 + 허가사항 원문 미확보가 한 응답에 함께(AG-08-28 A). 권고 줄이 두 종류(약 조합 권고 → 등급 뜻 권고, finalize 순서)이고
 * 서버가 줄 종류(`pharmacist_advice_kinds`, 같은 길이·순서)를 함께 준다: 화면은 이 값으로 미확보 묶음에는 `missing` 줄만,
 * 등급 정의 블록에는 `grade_def` 줄만 그린다. 종류 칸을 뺀 모양(옛 응답)은 시험이 이 응답에서 칸만 지워 만든다
 */
export const gradeDefAndMissingResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: `${DRUG_B}은 임부금기 목록에 올라 있어요.`,
    findings: [...pregnancyResponse.findings, labelFinding("ev-label-1", DRUG_B, PHRASES.MISSING_SEARCH_MISS)],
    detail: [pregDetail("FOUND", DRUG_B), labelMissing("ev-label-1", DRUG_B, "임부에 대한 투여", "SEARCH_MISS", PHRASES.MISSING_SEARCH_MISS)],
    citations: [pregCitation("FOUND")],
    grade_defs: gradeDefsResponse.grade_defs,
    grade_def_missing: gradeDefsResponse.grade_def_missing,
    pharmacist_advice: [adviceFor(DRUG_B), PHRASES.GRADE_DEF_PHARMACIST_ADVICE],
    pharmacist_advice_kinds: ["missing", "grade_def"],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/**
 * 제품 줄 묶음(BE-06-39~41, AG-08 `product_rows` 연결 뒤의 모양, 합성): 약마다 제품 줄 하나에 배지가 모이고 쌍 줄은 그대로 남는다(AG-08-29 A).
 * - 제품 줄의 `evidence_id`·`kind`는 `null`이다(근거 연결은 배지마다 `evidence_id`, BE-06-41 A). 한 응답에 `null` 줄이 여럿이다
 * - 복합제(성분 둘 이상) 칩은 `contra_kinds`·`dup` 칸이 없다 = 모름(BE-06-40 A). 성분 하나인 줄은 칸이 있다
 * **서버는 아직 이 모양을 내지 않는다**(밤사이 BE 구현 대상). 화면이 먼저 받을 수 있는지 보는 표본이다
 */
export const productRowsResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있고, ${DRUG_B}은 임부금기 목록에도 올라 있어요.`,
  findings: [
    {
      target: "product",
      bucket: "found",
      evidence_id: null,
      kind: null,
      drug: DRUG_A,
      drugs: [DRUG_A],
      text: PHRASES.BADGE_PAIR,
      badges: [{ kind: "contra_pair", text: PHRASES.BADGE_PAIR, evidence_id: "ev-pair-1" }],
      // 복합제: 어느 성분이 원인인지 가리지 못해 원인·중복 칸이 없다(모름)
      ingredients: [
        { code: INGR_A.code, name: INGR_A.name },
        { code: INGR_C.code, name: INGR_C.name },
      ],
    },
    {
      target: "product",
      bucket: "found",
      evidence_id: null,
      kind: null,
      drug: DRUG_B,
      drugs: [DRUG_B],
      text: PHRASES.BADGE_PAIR,
      badges: [
        { kind: "contra_pair", text: PHRASES.BADGE_PAIR, evidence_id: "ev-pair-1" },
        { kind: "pregnancy", grade: "2", text: pregnancyBadge("2"), evidence_id: "ev-preg-1" },
      ],
      ingredients: [{ ...INGR_B, contra_kinds: ["contra_pair", "pregnancy"] }],
    },
    pairFinding,
  ],
  detail: [pairDetail, pregDetail("FOUND", DRUG_B)],
  citations: [pairCitation, pregCitation("FOUND")],
});

/**
 * 임부금기 M등급 + 등급 정의 블록(PRD-09 §7.3): M은 고시에 없어 원문이 심평원 설명이고 출처 줄에 판·표·쪽이 온다.
 * 화면 확인용 합성 값이다. **서버는 아직 M 블록을 만들지 않는다**(backend grade_defs.py "M: 블록을 만들지 않는다, 규칙 미정").
 * 블록의 제목·원문·출처 줄은 다른 등급과 같은 칸(`grade_defs[]`)이라 화면은 받은 글자를 그대로 그린다
 */
export const pregnancyMDefResponse = make({
  ...pregnancyMResponse,
  grade_defs: [
    {
      grade: "M",
      title: PHRASES.GRADE_DEF_TITLE.replace("{grade}", "M"),
      text: "(합성 심평원 설명) 상병에 따른 1등급 또는 2등급 여부에 따라 처방·조제 사유 기재",
      source: "(합성 출처 줄) 건강보험심사평가원 「기능과 역할」 2026년판 표4.3-5, 인쇄 638쪽",
    },
  ],
});

/** 정보가 없어 확인하지 못한 종류의 줄(`not_checked_lines[]`): 임신 여부를 몰라 임부금기를 확인하지 못함. 권고 줄이 고정 문구 앞에 온다 */
export const notCheckedResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "pair",
        bucket: "not_listed",
        evidence_id: "ev-pair-1",
        kind: "contra_pair",
        drug: `${DRUG_A}${NAME_JOIN}${DRUG_B}`,
        drugs: [DRUG_A, DRUG_B],
        text: PHRASES.NOT_LISTED,
        source_label: fileLabel(DATASET_CONTRA_PAIR),
      },
    ],
    not_checked_lines: [PHRASES.PREGNANCY_NOT_CHECKED],
    detail: [{ ...pairDetail, status: "NOT_LISTED", dates: [{ label: "기준일", value: "2026-07-31" }], rows: [] }],
    citations: [{ ...pairCitation, dates: [{ label: "기준일", value: "2026-07-31" }], notice_nos: [] }],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/**
 * 코드가 이어지지 않아 확인하지 못한 쌍 줄(꼬리표 CODE_NOT_LINKED). 서버 모양 그대로다(`finalize` → `to_chat_response` 표본):
 * 줄 글자는 "약을 찾지 못해 확인하지 못함", 안내(`notes[]`)는 바뀐 문구 한 줄, 미식별 줄의 `why`·`next`가 붙는다.
 */
export const codeNotLinkedResponse = make(
  {
    route: "AGENT",
    end_reason: "NORMAL",
    summary: null,
    findings: [
      {
        target: "pair",
        bucket: "unconfirmed",
        evidence_id: "ev-pair-1",
        kind: "contra_pair",
        drug: `${DRUG_A}${NAME_JOIN}${DRUG_B}`,
        drugs: [DRUG_A, DRUG_B],
        text: PHRASES.UNIDENTIFIED,
        notes: [CODE_NOT_LINKED],
        unresolved: true,
        why: PHRASES.UNIDENTIFIED_WHY,
        next: PHRASES.UNIDENTIFIED_NEXT,
      },
    ],
    detail: [{ ...pairDetail, status: "UNIDENTIFIED", dates: [{ label: "기준일", value: "2026-07-31" }], rows: [], flags: ["CODE_NOT_LINKED"] }],
    citations: [{ ...pairCitation, dates: [{ label: "기준일", value: "2026-07-31" }], notice_nos: [] }],
    pharmacist_advice: [adviceFor(`${DRUG_A}${NAME_JOIN}${DRUG_B}`)],
  },
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 공공 API 실패: 상단 배너(`notice`의 새 값)와 파일 기준 결과 */
export const apiFailResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  notice: PHRASES.NOTICE_API_FAIL,
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
  findings: [pairFinding],
  detail: [pairDetail],
  citations: [pairCitation],
});

/**
 * 오탈자 보정 고지(AG-10-02 A, FE-02): 질문의 한 글자 틀린 이름을 사전 이름으로 보정해 확인한 결과. 고지 한 줄이 요약보다 먼저 온다.
 * 백엔드 가짜 서버(`dev_fake_server.py`) `typo` 시나리오와 같은 모양: 보정 1건 + 병용금기 1건, `NORMAL`
 */
export const typoCorrectedResponse = make({
  ...foundResponse,
  name_corrections: [fillCorrection(DRUG_A_TYPO, DRUG_A)],
});

/** 상한 도달: 상단 배너(`notice`)와 여기까지의 결과 */
export const limitResponse = make(
  {
    route: "AGENT",
    end_reason: "LIMIT",
    notice: PHRASES.LIMIT_REACHED,
    summary: null,
    findings: [pairFinding],
    detail: [pairDetail],
    citations: [pairCitation],
  },
  // 상한 도달은 확인하지 못한 항목이 있는 것으로 본다(finalize: `unresolved = ... or limit_reached`)
  [PHRASES.PHARMACIST_ADVICE_FIXED, FIXED_NOTICE],
);

/** 응급: 119 안내가 있고 금기 조회 결과가 이어진다 */
export const emergencyResponse = make({
  ...foundResponse,
  emergency: EMERGENCY,
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

/**
 * 되묻기(이름 둘이 모두 모호, FE-09): 질문 한 개와 이름별 후보 묶음 둘. `가나다시럽`(200000003)은 두 묶음에 모두 든다(겹치는 제품).
 * 질문은 FE-09-02 A 승인 원문이다(물음표 1개)
 */
export const clarifyMultiResponse = make({
  route: "AGENT",
  end_reason: "CLARIFY",
  summary: clarifyMultiQuestion([DRUG_AMBIGUOUS, DRUG_AMBIGUOUS_2]),
  candidates: [
    ...clarifyResponse.candidates,
    { input_name: DRUG_AMBIGUOUS_2, name: "가나다시럽", item_seq: "200000003", entp_name: "가상약품(주)", prescription: "일반의약품", matched_by: "product_name" },
    { input_name: DRUG_AMBIGUOUS_2, name: "가나다시럽 키즈", item_seq: "200000004", entp_name: "가상약품(주)", prescription: "일반의약품", matched_by: "product_name" },
    { input_name: DRUG_AMBIGUOUS_2, name: "가나다시럽 플러스", item_seq: "200000005", entp_name: "합성제약(주)", prescription: "전문의약품", matched_by: "product_name" },
  ],
});

/**
 * 되묻기(이름 셋이 모두 모호, FE-10): 묶음 셋(A·B·C). 2열 줄바꿈과 캡슐 3칸(흰|파|흰)을 보는 화면 시험용이다.
 * 앞의 두 묶음은 `clarifyMultiResponse`와 같고, 셋째 묶음은 다른 제품 둘이다
 */
export const clarifyTripleResponse = make({
  route: "AGENT",
  end_reason: "CLARIFY",
  summary: clarifyMultiQuestion([DRUG_AMBIGUOUS, DRUG_AMBIGUOUS_2, DRUG_AMBIGUOUS_3]),
  candidates: [
    ...clarifyMultiResponse.candidates,
    { input_name: DRUG_AMBIGUOUS_3, name: "라마바캡슐 10밀리그램", item_seq: "200000006", entp_name: "합성제약(주)", prescription: "일반의약품", matched_by: "product_name" },
    { input_name: DRUG_AMBIGUOUS_3, name: "라마바캡슐 20밀리그램", item_seq: "200000007", entp_name: "가상약품(주)", prescription: "전문의약품", matched_by: "product_name" },
  ],
});

/**
 * 되묻기(이전 차례의 선택 확인, AG-21): 앞 차례에서 `가나다정 100밀리그램`을 골랐는데 같은 이름 `가나다`가 다시 나왔다.
 * 질문은 `CLARIFY_PRIOR_PICK`에 **사전 제품명**을 채운 문장이고, 그 약이 첫 후보다(후보 목록은 `clarifyResponse`와 같다)
 */
export const clarifyPriorResponse = make({
  route: "AGENT",
  end_reason: "CLARIFY",
  summary: fillPriorPick(clarifyResponse.candidates[0].name),
  candidates: clarifyResponse.candidates,
});

/** 재복용·추가 복용 질문(AG-22-01 A): 결과는 그대로이고 `redose_notice` 한 줄이 `summary` 밖 별도 칸으로 온다 */
export const redoseResponse = make({
  ...foundResponse,
  redose_notice: PHRASES.REDOSE_NOTICE,
});

/**
 * 약 3개 결과 묶음(GROUP-01 3단계 계약, g1s3 §4 모양): 서버가 구역 순서(핵심 → 나머지)로 정렬한 판정 줄, 제품 줄의 짝 참조(병용 배지 대신),
 * 묶음 요약(`result_summary`, 약 3개라 `pair_only_notice`가 있다), 나머지 접힘 줄(`rest_fold`, 서버가 센 건수).
 * 화면은 지금 요약 줄만 그리고 구역·짝 참조·접힘은 4단계 디자인 뒤에 그린다(타입·fixture만 먼저)
 */
export const resultSummaryResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요. ${DRUG_C}은 두 약과 짝으로 오른 기록이 없어요.`,
  result_summary: {
    n_drugs: 3,
    n_pairs: 3,
    pairs_found: [{ drugs: [DRUG_A, DRUG_B], evidence_ids: ["ev-pair-1"] }],
    n_pairs_unchecked: 0,
    text: resultSummaryFound(3, [[DRUG_A, DRUG_B]]),
    pair_only_notice: PHRASES.PAIR_ONLY_NOTICE,
  },
  rest_fold: { count: 2, text: PHRASES.REST_FOLD_LINE.replace("{n}", "2"), open_label: PHRASES.REST_FOLD_OPEN, close_label: PHRASES.REST_FOLD_CLOSE },
  findings: [
    { ...pairFinding, section: "core" },
    {
      target: "product",
      bucket: "identified",
      evidence_id: null,
      kind: "identify",
      drug: DRUG_A,
      drugs: [DRUG_A],
      text: PHRASES.IDENTIFIED_LINE,
      sub_line: INGR_A.name,
      ingredients: [{ ...INGR_A, contra_kinds: ["contra_pair"] }],
      section: "core",
      pair_ref: { count: 1, evidence_ids: ["ev-pair-1"], text: PHRASES.PAIR_REF_LINE.replace("{n}", "1") },
    },
    {
      target: "product",
      bucket: "identified",
      evidence_id: null,
      kind: "identify",
      drug: DRUG_B,
      drugs: [DRUG_B],
      text: PHRASES.IDENTIFIED_LINE,
      sub_line: INGR_B.name,
      ingredients: [{ ...INGR_B, contra_kinds: ["contra_pair"] }],
      section: "core",
      pair_ref: { count: 1, evidence_ids: ["ev-pair-1"], text: PHRASES.PAIR_REF_LINE.replace("{n}", "1") },
    },
    { target: "pair", bucket: "not_listed", evidence_id: "ev-pair-2", kind: "contra_pair", drug: `${DRUG_A} · ${DRUG_C}`, drugs: [DRUG_A, DRUG_C], text: PHRASES.NOT_LISTED, section: "rest" },
    { target: "pair", bucket: "not_listed", evidence_id: "ev-pair-3", kind: "contra_pair", drug: `${DRUG_B} · ${DRUG_C}`, drugs: [DRUG_B, DRUG_C], text: PHRASES.NOT_LISTED, section: "rest" },
  ],
  detail: [pairDetail],
  citations: [pairCitation],
  sentence_refs: [{ evidence_id: "ev-pair-1", sentence_index: 0 }],
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
