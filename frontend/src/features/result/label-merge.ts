// 같은 약의 허가사항 항목 줄(`kind: "label"`)을 그 약의 판정 줄 안으로 합친다(FE-17 U-28, 2026-11-24 사용자 ISSUE-034).
// 서버는 허가사항 미확보 항목마다 "확인하지 못함" 줄을 하나씩 따로 보내고(`finalize` 항목 = 줄), 줄 머리를 `{약 이름} · {항목 이름}`
// (예 `…정 · 주의사항`, `…정 · 경고`)으로 만든다. 같은 약의 판정 줄이 이미 있으면 본문·근거 상세에서 그 줄 하나 안의 덧붙임 줄로 보인다.
// 값은 만들지 않는다: 합친 줄의 글자는 그 항목 줄이 받은 글자 그대로이고, 줄 순서는 받은 순서(합쳐진 항목 줄만 빠진다)다.
// 표시 단계의 예외 하나(U-28 (c), 사용자 확인 대기): 허가사항 항목 문장 맨 앞의 품목 기준 코드(`202106954 · ` 꼴)는 화면 글자에서만 숨긴다
// (`hideItemCode`). 서버 문구·근거 ID는 그대로이고, 숨긴 코드는 화면 글자가 아닌 `data-item-code`에 남긴다.
import type { Finding } from "@/lib/api";

const KIND_LABEL = "label"; // 허가사항·쉬운 설명 인용(근거 상세 `sections.ts`와 같은 키)
const TARGET_PRODUCT = "product";
/** 줄 머리의 약 이름과 항목 이름 사이 이음(서버 `_drug`의 `" · ".join`) */
const TITLE_JOIN = " · ";
/** 문장 맨 앞의 품목 기준 코드(숫자 6자리 이상) + 이음(U-28 (c)) */
const ITEM_CODE_PREFIX = /^(\d{6,})\s·\s/;

/** 허가사항 항목 줄인가(제품 줄) */
export const isLabelFinding = (finding: Pick<Finding, "kind" | "target">): boolean => finding.kind === KIND_LABEL && finding.target === TARGET_PRODUCT;

/**
 * 허가사항 항목 줄의 머리가 `{약 이름} · {항목 이름}` 꼴이면 그 약 이름(`ownerName`)인지 본다. 항목 이름은 비어 있지 않고 이음을 더 갖지 않는다
 * (쌍 이름 `가 · 나`가 우연히 맞는 경우를 막는다)
 */
export function isLabelOf(label: Pick<Finding, "drug">, ownerName: string): boolean {
  if (ownerName === "" || !label.drug.startsWith(ownerName + TITLE_JOIN)) return false;
  const section = label.drug.slice(ownerName.length + TITLE_JOIN.length);
  return section.trim() !== "" && !section.includes(TITLE_JOIN);
}

/** 판정 줄 하나 + 그 안으로 합쳐진 같은 약의 허가사항 항목 줄(받은 순서) */
export interface MergedFinding {
  finding: Finding;
  labels: Finding[];
}

/**
 * 받은 줄을 화면 줄로 바꾼다(FE-17 U-28 (a)·(b)). 허가사항 항목 줄의 머리가 다른 제품 판정 줄(허가사항 항목 줄이 아닌 것)의 `{약 이름} · ` 접두면
 * 그 판정 줄(같은 약의 첫 줄)에 붙이고 제 자리에서는 뺀다. 같은 약의 판정 줄이 없으면 지금처럼 제 자리의 줄 하나로 남는다.
 * 판정 줄이 항목 줄보다 뒤에 와도 붙는다(받은 순서에서 그 판정 줄이 놓인 자리 그대로)
 */
export function mergeLabelFindings(findings: readonly Finding[]): MergedFinding[] {
  const owners = findings.filter((finding) => finding.target === TARGET_PRODUCT && !isLabelFinding(finding));
  const ownerOf = new Map<Finding, Finding>();
  for (const finding of findings) {
    if (!isLabelFinding(finding)) continue;
    const owner = owners.find((candidate) => isLabelOf(finding, candidate.drug));
    if (owner) ownerOf.set(finding, owner);
  }
  const merged: MergedFinding[] = [];
  const byOwner = new Map<Finding, MergedFinding>();
  for (const finding of findings) {
    if (ownerOf.has(finding)) continue;
    const entry = { finding, labels: [] as Finding[] };
    merged.push(entry);
    if (!byOwner.has(finding)) byOwner.set(finding, entry);
  }
  for (const finding of findings) {
    const owner = ownerOf.get(finding);
    if (owner) byOwner.get(owner)!.labels.push(finding);
  }
  return merged;
}

/** 품목 기준 코드를 숨긴 화면 글자와 숨긴 코드(없으면 null). 코드가 문장 맨 앞이 아니면 바꾸지 않는다 */
export function splitItemCode(text: string): { text: string; code: string | null } {
  const match = ITEM_CODE_PREFIX.exec(text);
  if (!match || match[0].length === text.length) return { text, code: null };
  return { text: text.slice(match[0].length), code: match[1] };
}

/** 화면 글자만: 문장 맨 앞 품목 기준 코드를 숨긴다(U-28 (c)) */
export const hideItemCode = (text: string): string => splitItemCode(text).text;

/**
 * 합쳐진 허가사항 항목 줄이 판정 줄 안에 보일 덧붙임 줄들: 줄 글자(`text`) → 덧붙임(`note`) → 보조줄(`notes`), 받은 글자 그대로(코드만 숨김).
 * 판정 줄이 이미 가진 덧붙임 줄과 글자가 같은 것, 앞에서 이미 넣은 것은 한 번만 보인다
 */
export function labelLines(label: Finding, existing: readonly string[], notes: readonly string[] = label.notes): { text: string; code: string | null }[] {
  const seen = new Set(existing);
  const out: { text: string; code: string | null }[] = [];
  for (const raw of [label.text, ...(label.note ? [label.note] : []), ...notes]) {
    const line = splitItemCode(raw);
    if (line.text.trim() === "" || seen.has(line.text)) continue;
    seen.add(line.text);
    out.push(line);
  }
  return out;
}
