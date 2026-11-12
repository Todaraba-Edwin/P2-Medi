// 합성 응답(f3 A). 제품명·고시번호·날짜는 모두 가상 값이다. data/mock/을 복사하지 않았다.
import { ChatResponseSchema } from "@/lib/api/schemas";
import type { ChatResponse, ChatResponseInput } from "@/lib/api/types";
import {
  CLARIFY_TAIL,
  DATASET_CONTRA_PAIR,
  DATASET_PREGNANCY,
  DISCLAIMER,
  FIXED_NOTICE,
  PHRASES,
  PUBLISHER_KIDS,
  REFUSE_DOSAGE,
  SOURCE_KIND_FILE,
} from "./phrases";

// 합성 약 이름(실제 제품이 아니다)
const DRUG_A = "가나다정";
const DRUG_B = "라마바캡슐";
const DRUG_AMBIGUOUS = "가나다";

type Body = Omit<ChatResponseInput, "schema_version" | "fixed_notice" | "disclaimer">;

/** 고정 문구·고지를 붙이고 v0 zod를 통과시킨다(통과하지 못하면 가져오는 순간 실패한다). */
function make(body: Body, fixedNotice: string[] = [FIXED_NOTICE]): ChatResponse {
  return ChatResponseSchema.parse({
    schema_version: "chat_response@v0",
    ...body,
    fixed_notice: fixedNotice,
    disclaimer: DISCLAIMER,
  });
}

const pairDates = [
  { label: "고시일", value: "2026-01-15" },
  { label: "기준일", value: "2026-07-31" },
] as const;

/** 정상: 병용금기 발견 */
export const foundResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}과 ${DRUG_B}은 병용금기 목록에 함께 올라 있어요.`,
  findings: [
    {
      bucket: "found",
      evidence_id: "ev-pair-1",
      kind: "contra_pair",
      drug: `${DRUG_A} · ${DRUG_B}`,
      text: PHRASES.BADGE_PAIR,
      source_label: SOURCE_KIND_FILE,
      notice_nos: ["20260001"],
    },
  ],
  badges: [{ kind: "contra_pair", grade: null, text: PHRASES.BADGE_PAIR, evidence_id: "ev-pair-1" }],
  detail: [
    {
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
    },
  ],
  citations: [
    {
      publisher: PUBLISHER_KIDS,
      dataset: DATASET_CONTRA_PAIR,
      dates: [...pairDates],
      source_kind: "FILE",
      evidence_ids: ["ev-pair-1"],
    },
  ],
  sentence_refs: [{ evidence_id: "ev-pair-1", sentence_index: 0 }],
});

/** 목록에 없음(안전하다는 뜻이 아님) */
export const notListedResponse = make({
  route: "AGENT",
  end_reason: "NORMAL",
  summary: `${DRUG_A}은 임부금기 목록에서 찾지 못했어요.`,
  findings: [
    {
      bucket: "not_listed",
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      drug: DRUG_A,
      text: PHRASES.NOT_LISTED,
      source_label: SOURCE_KIND_FILE,
    },
  ],
  detail: [
    {
      evidence_id: "ev-preg-1",
      kind: "pregnancy",
      status: "NOT_LISTED",
      source_kind: "FILE",
      dataset_key: "pregnancy",
      dataset: DATASET_PREGNANCY,
      publisher: PUBLISHER_KIDS,
      dates: [{ label: "기준일", value: "2026-07-21" }],
      drugs: [DRUG_A],
    },
  ],
  citations: [
    {
      publisher: PUBLISHER_KIDS,
      dataset: DATASET_PREGNANCY,
      dates: [{ label: "기준일", value: "2026-07-21" }],
      source_kind: "FILE",
      evidence_ids: ["ev-preg-1"],
    },
  ],
});

/** 응급: 119 안내가 있고 금기 조회 결과가 이어진다 */
export const emergencyResponse = make({
  ...foundResponse,
  emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL },
});

/** 되묻기. v0에는 후보 목록 칸이 없다(b3, BE-06 v1) */
export const clarifyResponse = make({
  route: "AGENT",
  end_reason: "CLARIFY",
  summary: `'${DRUG_AMBIGUOUS}'${CLARIFY_TAIL}`,
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
