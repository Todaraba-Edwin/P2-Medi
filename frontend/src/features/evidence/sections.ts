// 응답을 근거 상세의 구역(판정 → 사유 원문 → 허가사항 → 출처)으로 나눈다. 값을 만들거나 고치지 않고 받은 순서를 지킨다.
// (종류·상태 키 비교는 이 파일에 둔다: 내부 키 이름이 화면 부품 파일의 글자로 들어가지 않게)
import type { ChatResponse, Citation, DetailItem, Finding } from "@/lib/api";
import { mergeLabelFindings } from "@/features/result/label-merge";

const KIND_LABEL = "label"; // 허가사항·쉬운 설명 인용
const KIND_IDENTIFY = "identify"; // 약 식별
const DATASET_PERMIT = "prmsn"; // 의약품 허가정보(허가사항 원문). 그 밖의 인용(쉬운 설명 등)에는 "허가사항 원문" 머리를 쓰지 않는다
const ROW_TEXT_FIELDS = ["reason", "detail", "content", "remark", "text"] as const; // 원문 텍스트 칸(백엔드 quote_check.TEXT_FIELDS)
const KIND_DOSE = "dose"; // 용량주의(하루 최대량은 성분 속성): 사유 원문 문장별 → 약 이름 + 제형유형 N건(FE-17 U-25)
const KIND_CONTRA_PAIR = "contra_pair"; // 병용금기 쌍
const STATUS_NOT_LISTED = "NOT_LISTED"; // 조회는 됐고 금기 목록에 없음(안전하다는 뜻이 아님)
const BUCKET_NOT_LISTED = "not_listed"; // 판정 줄 묶음 키(같은 뜻)

export interface JudgmentEntry {
  finding: Finding;
  /** 이 줄의 근거 항목(`evidence_id`가 같은 것). 없으면 null */
  item: DetailItem | null;
  /** 이 줄 안으로 합친 같은 약의 허가사항 항목 줄(FE-17 U-28, `mergeLabelFindings`). 없으면 빈 목록 */
  labels?: Finding[];
}

/**
 * 판정 박스 하나(FE-17 U-26-6, 2026-11-24): 화면에 보이는 것(줄 전부 + 박스 표지)이 완전히 같은 판정 줄은 한 박스로 묶는다
 * (예: 같은 약 이름 "약을 찾지 못해 확인하지 못함" + 같은 안내 줄이 두 번 온 경우). 글자는 첫 줄 그대로이고 근거 ID는 접어 둔다
 */
export interface JudgmentBox extends JudgmentEntry {
  /** 묶인 줄 수(2 이상이면 "같은 내용 N건") */
  count: number;
  /** 묶인 줄들의 근거 ID(받은 순서, null은 뺀다) */
  evidenceIds: string[];
}

/** 같은 약(줄 머리 약 이름이 같은 것)의 판정 박스 묶음(FE-17 U-26-5): 서버가 종류별로 흩어 보낸 같은 약의 줄을 붙여 한 묶음으로 보인다 */
export interface JudgmentDrugGroup {
  /** 줄 머리 약 이름(쌍이면 두 이름). 묶는 열쇠이고 화면 글자는 각 줄 부품이 그린다 */
  drug: string;
  boxes: JudgmentBox[];
}

/** 판정 줄이 화면에 보이는 모든 값(근거 ID와 짝 참조 ID는 빼고) + 박스 표지. 하나라도 다르면 다른 박스다 */
function judgmentKey({ finding, item, labels = [] }: JudgmentEntry): string {
  // 근거 ID는 화면 글자가 아니므로 비교에서 뺀다(같은 내용이 다른 근거 ID로 두 번 온 경우를 묶는다)
  const visible = { ...finding, evidence_id: null, pair_ref: null, badges: finding.badges.map((badge) => ({ ...badge, evidence_id: null })) };
  const { pair_ref } = finding;
  return JSON.stringify([
    visible,
    pair_ref ? { ...pair_ref, evidence_ids: [] } : null,
    item ? [item.dataset, item.source_kind, item.source_kind_label ?? null] : null,
    // 합친 허가사항 항목 줄(FE-17 U-28)도 박스에 보이는 값이다(근거 ID는 뺀다)
    labels.map((label) => ({ ...label, evidence_id: null })),
  ]);
}

/**
 * 판정 구역 묶기(FE-17 U-26-5·6). ① 보이는 것이 같은 줄은 한 박스로(같은 내용 N건) ② 같은 약 이름의 박스는 처음 나온 자리에 붙여 한 묶음으로.
 * 약 묶음의 순서는 그 약이 처음 나온 순서, 묶음 안 박스의 순서는 받은 순서다. 값은 만들거나 고치지 않는다
 */
export function groupJudgments(entries: readonly JudgmentEntry[]): JudgmentDrugGroup[] {
  const boxes = new Map<string, JudgmentBox & { drug: string }>();
  for (const entry of entries) {
    const key = judgmentKey(entry);
    // 줄의 근거 ID 다음에 합친 허가사항 항목 줄의 근거 ID(받은 순서)
    const ids = [entry.finding.evidence_id, ...(entry.labels ?? []).map((label) => label.evidence_id)].filter((id): id is string => id !== null);
    const box = boxes.get(key);
    if (box) {
      box.count += 1;
      box.evidenceIds.push(...ids);
    } else {
      const drug = entry.finding.drugs.length > 0 ? entry.finding.drugs.join(" · ") : entry.finding.drug;
      boxes.set(key, { ...entry, drug, count: 1, evidenceIds: ids });
    }
  }
  const groups = new Map<string, JudgmentDrugGroup>();
  for (const { drug, ...box } of boxes.values()) {
    const group = groups.get(drug);
    if (group) group.boxes.push(box);
    else groups.set(drug, { drug, boxes: [box] });
  }
  return [...groups.values()];
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

/** 용량주의 사유 원문 묶음 안의 약 이름 줄(FE-17 U-25): 같은 사유 원문 + 같은 약의 항목(= 제형 코드) 수가 `제형유형 N건`의 N이다 */
export interface ReasonDrugLine {
  /** 줄에 보일 약 이름(받은 글자 그대로, 여럿이면 순서대로) */
  names: string[];
  /** 묶인 항목(받은 순서) */
  items: DetailItem[];
  evidenceIds: string[];
}

/** 사유 원문 구역의 하위 묶음 하나(FE-17 U-25). 종류 묶음(`ReasonKindGroup`) 안에서 받은 순서대로 놓인다 */
export type ReasonEntry =
  /** 용량주의: 사유 원문 문장(제목처럼) → 그 문장을 가진 약 이름 줄들 */
  | { type: "text"; texts: string[]; notes: string[]; drugs: ReasonDrugLine[]; evidenceIds: string[] }
  /** 그 밖의 종류(병용·임부 등, 현행 구조): 약 이름(쌍) → 사유 원문. 같은 내용은 한 묶음(`groupReasons`, "같은 내용 N건") */
  | { type: "pair"; group: ReasonGroup }
  /** 병용금기 쌍이 금기 목록에 없음: 약 이름 쌍 → 판정 줄의 고정 문구(서버 값 그대로, 프런트가 짓지 않는다) */
  | { type: "notListed"; item: DetailItem; names: string[]; text: string; evidenceIds: string[] };

/** 사유 원문 구역의 판정 종류 묶음(FE-17 U-25): 종류·자료·출처 종류가 같은 근거를 한 박스로. 표지는 첫 항목의 것 그대로다 */
export interface ReasonKindGroup {
  /** 표지(`SourceTag`)를 그릴 항목(처음 받은 것) */
  item: DetailItem;
  entries: ReasonEntry[];
  /** 이 박스에 든 근거 항목 수 */
  count: number;
  /** 이 박스에 든 근거 ID 전부(받은 순서) */
  evidenceIds: string[];
}

export interface EvidenceSections {
  judgments: JudgmentEntry[];
  /** 판정 구역의 화면 구조(FE-17 U-26-5·6): 같은 약 묶음 → 같은 내용 박스 */
  judgmentGroups: JudgmentDrugGroup[];
  /** 사유 원문이 있는 판정 근거. 같은 내용의 항목은 한 박스로 묶었다(`ReasonGroup`) */
  reasons: ReasonGroup[];
  /**
   * 사유 원문 구역의 화면 구조(FE-17 U-25): 판정 종류 묶음 → (용량주의) 사유 원문 → 약 이름 + 제형유형 N건 / (그 밖) 약 이름(쌍) → 사유 원문.
   * 병용금기 쌍의 "금기 목록에 없음"도 같은 종류 묶음에 든다. 값은 받은 글자 그대로이고 묶기만 한다
   */
  reasonKinds: ReasonKindGroup[];
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

const idsOf = (items: readonly DetailItem[]) => items.flatMap((item) => (item.evidence_id === null ? [] : [item.evidence_id]));
/** 근거 항목의 약 이름(받은 글자 그대로): 쌍·여럿이면 `drugs`, 아니면 `drug_name` */
export const drugNamesOf = (item: DetailItem): string[] => (item.drugs && item.drugs.length > 0 ? item.drugs : item.drug_name ? [item.drug_name] : []);
/** 판정 종류 묶음 열쇠: 종류·자료·출처 종류(키와 글자). 박스 표지(`SourceTag`)가 같은 근거끼리 묶인다 */
const kindKey = (item: DetailItem) => JSON.stringify([item.kind, item.dataset, item.source_kind, item.source_kind_label ?? null]);

/**
 * 사유 원문 구역을 판정 종류 → 하위 묶음으로 나눈다(FE-17 U-25, U-19 후속 통합). 값을 만들거나 고치지 않는다.
 * - `items`: 원문을 확보한 판정 근거와 금기 목록에 없는 병용금기 쌍(받은 순서). `notListedText`에 있는 항목은 그 판정 줄 글자와 함께 "금기 목록에 없음" 묶음이 된다
 * - 용량주의는 사유 원문 문장(+ 덧붙임 줄)이 같은 항목을 한 묶음으로, 그 안에서 약 이름이 같은 항목을 한 줄로 모은다(줄의 항목 수 = 제형 코드 수).
 *   글자가 조금이라도 다른 원문(예 "으로 4,000mg"과 "으로써 4000mg")은 다른 묶음이다
 * - 그 밖의 종류는 기존 묶음(`groupReasons`: 약 이름·원문·덧붙임 줄이 같으면 하나)을 하위 묶음으로 둔다
 * 종류 묶음·하위 묶음·줄의 순서는 모두 처음 나온 순서다
 */
export function groupReasonKinds(items: readonly DetailItem[], notListedText: ReadonlyMap<DetailItem, string> = new Map()): ReasonKindGroup[] {
  type Slot = { type: "text"; key: string } | { type: "pair"; key: string } | { type: "notListed"; item: DetailItem; text: string };
  const kinds = new Map<string, { item: DetailItem; slots: Slot[]; items: DetailItem[] }>();
  const textGroups = new Map<string, { texts: string[]; notes: string[]; lines: Map<string, ReasonDrugLine>; items: DetailItem[] }>();
  const pairItems = new Map<string, DetailItem[]>();
  for (const item of items) {
    const key = kindKey(item);
    let kind = kinds.get(key);
    if (!kind) kinds.set(key, (kind = { item, slots: [], items: [] }));
    kind.items.push(item);
    const text = notListedText.get(item);
    if (text !== undefined) {
      kind.slots.push({ type: "notListed", item, text });
      continue;
    }
    if (item.kind === KIND_DOSE) {
      const textKey = JSON.stringify([key, rowTexts(item), item.notes]);
      let group = textGroups.get(textKey);
      if (!group) {
        textGroups.set(textKey, (group = { texts: rowTexts(item), notes: item.notes, lines: new Map(), items: [] }));
        kind.slots.push({ type: "text", key: textKey });
      }
      group.items.push(item);
      const names = drugNamesOf(item);
      const lineKey = JSON.stringify(names);
      const line = group.lines.get(lineKey);
      if (line) line.items.push(item);
      else group.lines.set(lineKey, { names, items: [item], evidenceIds: [] });
      continue;
    }
    const pairKey = JSON.stringify([key, reasonKey(item)]);
    const same = pairItems.get(pairKey);
    if (same) same.push(item);
    else {
      pairItems.set(pairKey, [item]);
      kind.slots.push({ type: "pair", key: pairKey });
    }
  }
  return [...kinds.values()].map(({ item, slots, items: kindItems }) => ({
    item,
    count: kindItems.length,
    evidenceIds: idsOf(kindItems),
    entries: slots.map((slot): ReasonEntry => {
      if (slot.type === "text") {
        const group = textGroups.get(slot.key)!;
        const drugs = [...group.lines.values()].map((line) => ({ ...line, evidenceIds: idsOf(line.items) }));
        return { type: "text", texts: group.texts, notes: group.notes, drugs, evidenceIds: idsOf(group.items) };
      }
      if (slot.type === "pair") return { type: "pair", group: groupReasons(pairItems.get(slot.key)!)[0] };
      return { type: "notListed", item: slot.item, names: drugNamesOf(slot.item), text: slot.text, evidenceIds: idsOf([slot.item]) };
    }),
  }));
}

/**
 * 금기 목록에 없는 병용금기 쌍(FE-17 U-25 "병용금기 묶음에 약 이름 쌍 + 고정 문구"): 원문이 없는 `NOT_LISTED` 근거와 그 근거를 가리키는 판정 줄의 글자.
 * 글자는 판정 줄(`findings[].text`, 서버 고정 문구)을 그대로 쓴다. 가리키는 줄이 없으면 글자를 지을 수 없으므로 넣지 않는다
 */
function notListedPairs(response: ChatResponse, judgmentItems: readonly DetailItem[]): Map<DetailItem, string> {
  const out = new Map<DetailItem, string>();
  for (const item of judgmentItems) {
    if (item.kind !== KIND_CONTRA_PAIR || item.status !== STATUS_NOT_LISTED || item.missing_text !== null || rowTexts(item).length > 0 || item.evidence_id === null) continue;
    const finding = response.findings.find((f) => f.evidence_id === item.evidence_id && f.bucket === BUCKET_NOT_LISTED);
    if (finding) out.set(item, finding.text);
  }
  return out;
}

export function buildSections(response: ChatResponse): EvidenceSections {
  const byId = new Map(response.detail.filter((item) => item.evidence_id !== null).map((item) => [item.evidence_id, item]));
  const judgmentItems = response.detail.filter((item) => item.kind !== KIND_LABEL && item.kind !== KIND_IDENTIFY);
  const reasonItems = judgmentItems.filter((item) => item.missing_text === null && rowTexts(item).length > 0);
  const notListed = notListedPairs(response, judgmentItems);
  // 같은 약의 허가사항 항목 줄은 그 약의 판정 줄 안으로 합친다(FE-17 U-28 (b), 본문 결과 카드와 같은 규칙): 판정 구역에 따로 박스를 두지 않는다
  const judgments = mergeLabelFindings(response.findings).map(({ finding, labels }) => ({
    finding,
    item: (finding.evidence_id && byId.get(finding.evidence_id)) || null,
    labels,
  }));
  return {
    judgments,
    judgmentGroups: groupJudgments(judgments),
    reasons: groupReasons(reasonItems),
    // 받은 순서 그대로: 원문 근거와 금기 목록에 없는 쌍이 detail 안에서 놓인 순서다
    reasonKinds: groupReasonKinds(judgmentItems.filter((item) => notListed.has(item) || reasonItems.includes(item)), notListed),
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
