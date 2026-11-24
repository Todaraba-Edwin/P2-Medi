// 결과 화면의 줄 표시 가공(FE-17 U-30, 2026-11-24 사용자 "타이레놀정500 먹고 이부프로펜도 먹어도 돼요?" 결과·근거 상세 지적, ISSUE-035).
// 서버가 보낸 판정·글자는 바꾸지 않고, 보이는 자리만 정리한다. 새 글자는 없다(괄호·쉼표·이음 글자만 쓴다).
// - (a) 같은 판정 종류·같은 등급인데 출처 꼬리(`(파일)`·`(성분 API)`)만 다른 배지는 하나로: `삐! 임부금기 2등급 (파일, 성분 API)`
// - (b) 같은 약(줄 머리 약 이름이 같은 제품 줄)의 줄은 본문에서 한 행으로
// - (c) 병용(쌍) 줄을 맨 위로(병용을 물은 질문에서 가장 중요한 정보)
// - (d) 쌍의 두 약이 모두 하루 최대량 주의 성분을 가졌으면 쌍 줄 안에 약 이름별로 같은 글자(`CAUTION_LABELS["dose"]`)를 다시 보인다
// - (e) 판정 줄 글자가 `NOT_LISTED`(`금기 목록에 없음(안전하다는 뜻이 아님)`)이면 괄호 안내를 떼어 `금기 목록에 없음`으로 보인다.
//   같은 뜻은 결과 화면의 고정 안내(`금기 목록에 없다는 것이 안전하다는 뜻이 아니에요…`, 가장 최근 답 아래 접히지 않는 자리)와 묶음 요약 줄이 보인다(하네스 원칙: 최소 1회)
// - (f) 줄 노트 `파일과 실시간 조회 결과가 같아요`(`FLAG_NOTES["API_SAME"]`)는 본문·근거 상세 모두에서 뺀다(같다는 사실은 판정이 이미 보인다)
// 판별 글자는 백엔드 원문에서 만든 생성 상수(`lib/fixed/phrases.generated`)와 같은지로만 가린다(값을 짓지 않는다).
import type { Badge, Finding } from "@/lib/api";
import { API_SAME_NOTE, CAUTION_DOSE_LABEL, NOT_LISTED } from "@/lib/fixed/phrases.generated";
import { mergeLabelFindings } from "./label-merge";
import type { MergedFinding } from "./label-merge";

const TARGET_PAIR = "pair";
const TARGET_PRODUCT = "product";
const KIND_DOSE = "dose";
/** 출처 꼬리 `{배지 글자} ({출처})`(서버 `finalize._badges`: `f"{text} {tail}"`, 꼬리는 `BADGE_SOURCE_TAIL` 괄호 글자) */
const SOURCE_TAIL = /^(.*\S) \(([^()]+)\)$/;
/** 합친 출처 꼬리 사이 글자 */
const TAIL_JOIN = ", ";

/** 화면에 그릴 배지 하나: 받은 배지 + 합쳐진 배지들(출처 꼬리만 다른 같은 배지) */
export interface DisplayBadge extends Badge {
  /** 이 배지로 합쳐진 받은 배지(받은 순서). 합치지 않았으면 자기 하나 */
  merged: Badge[];
}

/**
 * (a) 출처 꼬리만 다른 같은 배지(같은 종류·같은 등급, 둘 다 `source`가 있음, 꼬리 앞 글자가 같음)를 하나로 합친다.
 * 글자는 `{꼬리 앞 글자} ({꼬리1}, {꼬리2})`(받은 꼬리 글자 그대로, 받은 순서)이고 자리는 처음 나온 자리다. 등급이 다르면 합치지 않는다
 */
export function mergeSourceBadges(badges: readonly Badge[]): DisplayBadge[] {
  const out: { badge: DisplayBadge; tails: string[]; base: string | null }[] = [];
  for (const badge of badges) {
    const match = badge.source !== null ? SOURCE_TAIL.exec(badge.text) : null;
    if (match) {
      const [, base, tail] = match;
      const same = out.find((entry) => entry.base === base && entry.badge.kind === badge.kind && entry.badge.grade === badge.grade);
      if (same) {
        if (!same.tails.includes(tail)) same.tails.push(tail);
        same.badge.merged.push(badge);
        same.badge.text = `${base} (${same.tails.join(TAIL_JOIN)})`;
        continue;
      }
      out.push({ badge: { ...badge, merged: [badge] }, tails: [tail], base });
      continue;
    }
    out.push({ badge: { ...badge, merged: [badge] }, tails: [], base: null });
  }
  return out.map((entry) => entry.badge);
}

/** (e) 판정 줄 글자의 화면 글자: `NOT_LISTED`와 같으면 괄호 안내를 뗀 글자, 아니면 받은 글자 그대로 */
export function shortStatusText(text: string): string {
  if (text !== NOT_LISTED) return text;
  const open = NOT_LISTED.lastIndexOf("(");
  return open > 0 ? NOT_LISTED.slice(0, open) : text;
}

/** (f) `파일과 실시간 조회 결과가 같아요` 노트인가 */
export const isApiSameNote = (note: string): boolean => note === API_SAME_NOTE;
/** (f) 그 노트를 뺀 나머지(받은 순서 그대로) */
export const withoutApiSame = (notes: readonly string[]): string[] => notes.filter((note) => !isApiSameNote(note));

/** 줄이 하루 최대량 주의 성분을 가졌는가: 용량주의 줄 글자이거나(배지 없는 주의 줄) 덧붙임 줄에 같은 글자가 있다 */
const hasDoseCaution = (finding: Finding): boolean =>
  (finding.kind === KIND_DOSE && finding.text === CAUTION_DOSE_LABEL) || finding.notes.includes(CAUTION_DOSE_LABEL) || finding.note === CAUTION_DOSE_LABEL;

/** 그 약의 제품 줄(줄 머리 약 이름이 같은 것) */
const productRowsOf = (findings: readonly Finding[], drug: string) => findings.filter((finding) => finding.target === TARGET_PRODUCT && finding.drug === drug);

/** 쌍 줄 안의 약별 주의 줄 하나(d): 약 이름(받은 글자) + 서버 상수 글자 */
export interface PairDoseLine {
  drug: string;
  text: string;
}

/**
 * (d) 쌍 줄의 두 약이 **모두** 하루 최대량 주의 성분을 가졌으면 약 이름별 줄 두 개, 아니면 빈 목록.
 * 병용금기 목록에 없는 짝이어도 두 제품을 함께 먹으면 하루 최대량 주의 성분이 겹칠 수 있음을 병용 줄에서 보이려는 것이다(사용자 지시). 글자는 새로 짓지 않는다
 */
export function pairDoseLines(pair: Finding, findings: readonly Finding[]): PairDoseLine[] {
  if (pair.target !== TARGET_PAIR || pair.drugs.length !== 2) return [];
  const lines = pair.drugs.map((drug) => (productRowsOf(findings, drug).some(hasDoseCaution) ? { drug, text: CAUTION_DOSE_LABEL } : null));
  return lines.every((line) => line !== null) ? (lines as PairDoseLine[]) : [];
}

/** 본문 결과 카드의 한 행: 대표 줄 + 같은 약이라 이 행으로 합친 줄(받은 순서) */
export interface ResultRow {
  main: MergedFinding;
  siblings: MergedFinding[];
}

/**
 * 본문 결과 카드의 행(FE-17 U-28 합치기 뒤 U-30 (b)·(c)). ① 같은 약의 허가사항 항목 줄은 그 약 판정 줄 안으로(U-28)
 * ② 줄 머리 약 이름이 같은 제품 줄은 처음 나온 줄의 행 하나로(b) ③ 쌍 줄 행을 맨 위로(c, 쌍 줄끼리·나머지끼리는 받은 순서). 값은 바꾸지 않는다
 */
export function resultRows(findings: readonly Finding[]): ResultRow[] {
  const rows: ResultRow[] = [];
  const byDrug = new Map<string, ResultRow>();
  for (const entry of mergeLabelFindings(findings)) {
    const { finding } = entry;
    const key = finding.target === TARGET_PRODUCT && finding.drug.trim() !== "" ? finding.drug : null;
    const row = key === null ? undefined : byDrug.get(key);
    if (row) {
      row.siblings.push(entry);
      continue;
    }
    const created = { main: entry, siblings: [] };
    rows.push(created);
    if (key !== null) byDrug.set(key, created);
  }
  return [...rows.filter((row) => row.main.finding.target === TARGET_PAIR), ...rows.filter((row) => row.main.finding.target !== TARGET_PAIR)];
}
