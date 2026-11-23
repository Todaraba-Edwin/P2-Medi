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

/**
 * 사유 원문 박스 하나(FE-17 U-19 후속, UX 안 B). 종류·박스 제목·표지·원문 문장·덧붙임 줄이 모두 같은 근거 항목을 한 박스로 묶는다.
 * 값을 만들거나 바꾸지 않는다: 보이는 글자는 첫 항목(`item`)의 것 그대로이고, 묶인 항목의 근거 ID는 받은 순서대로 `evidenceIds`에 접어 둔다
 */
export interface ReasonGroup {
  /** 박스에 그리는 항목(묶인 것 중 처음 받은 것) */
  item: DetailItem;
  /** 묶인 항목 전부(받은 순서) */
  items: DetailItem[];
  /** 묶인 항목의 근거 ID(받은 순서, `null`은 뺀다) */
  evidenceIds: string[];
}

export interface EvidenceSections {
  judgments: JudgmentEntry[];
  /** 사유 원문이 있는 판정 근거. 같은 내용의 항목은 한 박스로 묶었다(`ReasonGroup`) */
  reasons: ReasonGroup[];
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

/**
 * 사유 박스의 "같은 내용" 열쇠: 박스에 보이는 것 전부(종류, 박스 제목, 표지, 원문 문장, 덧붙임 줄).
 * 하나라도 다르면 다른 박스다(글자가 조금이라도 다른 원문·다른 약·다른 자료는 묶지 않는다)
 */
function reasonKey(item: DetailItem): string {
  return JSON.stringify([
    item.kind,
    item.drugs && item.drugs.length > 0 ? item.drugs : null,
    item.drugs && item.drugs.length > 0 ? null : (item.drug_name ?? null),
    item.dataset,
    item.source_kind,
    item.source_kind_label ?? null,
    rowTexts(item),
    item.notes,
  ]);
}

/**
 * 같은 내용의 사유 원문 항목을 한 박스로 묶는다(FE-17 U-19 후속). 성분 이름으로 찾은 약은 제형 코드마다 용량주의 항목이 따로 와서
 * 같은 문장 박스가 여러 개 보였다. 묶음 순서는 처음 나온 순서, 묶음 안의 순서는 받은 순서 그대로다
 */
export function groupReasons(items: readonly DetailItem[]): ReasonGroup[] {
  const groups = new Map<string, ReasonGroup>();
  for (const item of items) {
    const key = reasonKey(item);
    const group = groups.get(key);
    if (group) group.items.push(item);
    else groups.set(key, { item, items: [item], evidenceIds: [] });
  }
  return [...groups.values()].map((group) => ({ ...group, evidenceIds: group.items.flatMap((item) => (item.evidence_id === null ? [] : [item.evidence_id])) }));
}

export function buildSections(response: ChatResponse): EvidenceSections {
  const byId = new Map(response.detail.filter((item) => item.evidence_id !== null).map((item) => [item.evidence_id, item]));
  const judgmentItems = response.detail.filter((item) => item.kind !== KIND_LABEL && item.kind !== KIND_IDENTIFY);
  return {
    judgments: response.findings.map((finding) => ({ finding, item: (finding.evidence_id && byId.get(finding.evidence_id)) || null })),
    reasons: groupReasons(judgmentItems.filter((item) => item.missing_text === null && rowTexts(item).length > 0)),
    reasonsMissing: judgmentItems.filter((item) => item.missing_text !== null),
    labels: response.detail.filter(isLabelItem),
    citations: response.citations,
  };
}

const ADVICE_MISSING = "missing"; // 미확보 항목 권고(허가사항·사유 원문 구역의 미확보 묶음)
const ADVICE_GRADE_DEF = "grade_def"; // 등급 정의 권고(등급 정의 블록)

export interface AdviceByZone {
  /** 미확보 묶음(`MissingGroup`)에 보일 권고 줄 */
  missing: string[];
  /** 등급 정의 블록(`GradeDefBlock`)에 보일 권고 줄 */
  gradeDef: string[];
}

/**
 * 약사 확인 권고 줄을 구역별로 고른다(AG-08-28 A). 서버가 준 종류 칸(`pharmacist_advice_kinds`, 같은 길이·순서)만 보고 고르며
 * 문구를 비교하지 않는다. 받은 글자·순서는 그대로다.
 * 종류 칸이 없거나(옛 응답) 길이가 어긋나면 고르지 않고 두 구역 모두에 전부 보인다(권고를 숨기지 않는 쪽으로 물러선다).
 */
export function adviceOf(response: Pick<ChatResponse, "pharmacist_advice" | "pharmacist_advice_kinds">): AdviceByZone {
  const lines = response.pharmacist_advice;
  const kinds = response.pharmacist_advice_kinds;
  if (kinds.length === 0 || kinds.length !== lines.length) return { missing: lines, gradeDef: lines };
  return {
    missing: lines.filter((_, index) => kinds[index] === ADVICE_MISSING),
    gradeDef: lines.filter((_, index) => kinds[index] === ADVICE_GRADE_DEF),
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
