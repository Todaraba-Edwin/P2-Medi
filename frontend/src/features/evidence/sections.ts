// 응답을 근거 상세의 구역(판정 → 사유 원문 → 허가사항 → 출처)으로 나눈다. 값을 만들거나 고치지 않고 받은 순서를 지킨다.
// (종류·상태 키 비교는 이 파일에 둔다: 내부 키 이름이 화면 부품 파일의 글자로 들어가지 않게)
import type { ChatResponse, Citation, DetailItem, Finding } from "@/lib/api";

const KIND_LABEL = "label"; // 허가사항·쉬운 설명 인용
const KIND_IDENTIFY = "identify"; // 약 식별
const DATASET_PERMIT = "prmsn"; // 의약품 허가정보(허가사항 원문). 그 밖의 인용(쉬운 설명 등)에는 "허가사항 원문" 머리를 쓰지 않는다
const ROW_TEXT_FIELDS = ["reason", "detail", "content", "remark", "text"] as const; // 원문 텍스트 칸(백엔드 quote_check.TEXT_FIELDS)

export interface JudgmentEntry {
  finding: Finding;
  /** 이 줄의 근거 항목(`evidence_id`가 같은 것). 없으면 null */
  item: DetailItem | null;
}

export interface EvidenceSections {
  judgments: JudgmentEntry[];
  /** 사유 원문이 있는 판정 근거 */
  reasons: DetailItem[];
  /** 판정 근거 중 원문을 확보하지 못한 것 */
  reasonsMissing: DetailItem[];
  /** 허가사항 구역(인용 또는 미확보) */
  labels: DetailItem[];
  citations: Citation[];
}

/** 근거 항목 한 개의 원문 문장들(받은 순서, 글자 그대로). 글자가 완전히 같은 문장은 한 번만 보인다 */
export function rowTexts(item: DetailItem): string[] {
  const out: string[] = [];
  for (const row of item.rows) {
    for (const field of ROW_TEXT_FIELDS) {
      const value = row[field];
      if (typeof value === "string" && value.trim() !== "" && !out.includes(value)) out.push(value);
    }
  }
  return out;
}

export const isLabelItem = (item: DetailItem) => item.kind === KIND_LABEL;
/** 허가정보(허가사항 원문) 인용인가. 쉬운 설명 인용에는 "허가사항 원문" 머리를 붙이지 않는다(PRD-11 §7.1) */
export const isPermitItem = (item: DetailItem) => item.dataset_key === DATASET_PERMIT;
/** 약을 찾지 못한 줄인가(찾아본 곳 표를 보인다) */
export const isLookupFinding = (finding: Finding) => finding.kind === KIND_IDENTIFY || finding.input_name !== null;

export function buildSections(response: ChatResponse): EvidenceSections {
  const byId = new Map(response.detail.filter((item) => item.evidence_id !== null).map((item) => [item.evidence_id, item]));
  const judgmentItems = response.detail.filter((item) => item.kind !== KIND_LABEL && item.kind !== KIND_IDENTIFY);
  return {
    judgments: response.findings.map((finding) => ({ finding, item: (finding.evidence_id && byId.get(finding.evidence_id)) || null })),
    reasons: judgmentItems.filter((item) => item.missing_text === null && rowTexts(item).length > 0),
    reasonsMissing: judgmentItems.filter((item) => item.missing_text !== null),
    labels: response.detail.filter(isLabelItem),
    citations: response.citations,
  };
}

export interface PublisherGroup {
  publisher: string;
  rows: Citation[];
}

/**
 * 출처 행을 기관별로 묶는다(PRD-12 §4: 기관은 한 번만, 그 아래에 자료 행).
 * 기관은 처음 나온 순서, 자료 행은 받은 순서 그대로다. 서버가 기관 순으로 보내므로 행의 순서는 바뀌지 않는다.
 */
export function groupByPublisher(citations: readonly Citation[]): PublisherGroup[] {
  const groups: PublisherGroup[] = [];
  for (const citation of citations) {
    const group = groups.find((g) => g.publisher === citation.publisher);
    if (group) group.rows.push(citation);
    else groups.push({ publisher: citation.publisher, rows: [citation] });
  }
  return groups;
}
