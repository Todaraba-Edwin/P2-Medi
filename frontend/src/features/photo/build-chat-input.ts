// 확인 카드의 값 → 기존 `/chat` 흐름에 넘길 값(계약 변경 없음, 지시서 §3 7번).
// - 질문 = "{약 이름들 ', '로} {질문}". 약 이름은 후보를 골랐으면 후보 `name`, 아니면 (고친) 읽은 글자
// - 후보를 고른 약만 `confirmedDrugs`에 `{name, item_seq, input_name: name}`로 싣는다(FE-09-05 A 모양). 고르지 않은 약은 글자로만 들어가
//   기존 식별·되묻기·미식별 경로를 탄다. 확신도는 어디에도 없다
import type { DrugCandidate } from "@/lib/api/account";
import type { ConfirmedDrug } from "@/stores/conversation-context";
import type { IngestDrug } from "./types";

export const PHOTO_NAME_JOIN = ", ";

/** 확인 카드의 약 한 줄(메모리). `readName`은 사용자가 고칠 수 있는 입력칸 값이다 */
export interface PhotoRow {
  id: string;
  readName: string;
  /** 봉투에서 읽은 성분 글자(있으면 작은 글자로 병기). 입력칸이 성분 글자로 시작했으면 null */
  readIngredient: string | null;
  strengthOrForm: string | null;
  /** 사전 후보(≤5). 기본 선택 없음 */
  candidates: readonly DrugCandidate[];
  /** 사용자가 고른 후보. 고르지 않았으면 null */
  picked: DrugCandidate | null;
}

export interface ChatInputFromPhoto {
  question: string;
  confirmedDrugs: ConfirmedDrug[];
}

let sequence = 0;
/** 새 줄 id(메모리 안에서만 구분한다) */
export const nextRowId = () => `photo-row-${(sequence += 1)}`;

/** 응답 항목 → 줄. 상품명이 없고 성분명만 있으면 입력칸을 성분 글자로 시작한다(서버도 그 글자로 후보를 찾는다) */
export function rowsFromResponse(drugs: readonly IngestDrug[]): PhotoRow[] {
  return drugs.map((drug) => ({
    id: nextRowId(),
    readName: drug.read_name ?? drug.read_ingredient ?? "",
    readIngredient: drug.read_name === null ? null : drug.read_ingredient,
    strengthOrForm: drug.strength_or_form,
    candidates: drug.candidates,
    picked: null,
  }));
}

/** 빈 줄("약 추가") */
export const emptyRow = (): PhotoRow => ({ id: nextRowId(), readName: "", readIngredient: null, strengthOrForm: null, candidates: [], picked: null });

/** 이 줄이 질문에 들어갈 이름: 후보를 골랐으면 그 이름, 아니면 입력칸 글자(앞뒤 공백 제거). 비어 있으면 "" */
export const rowName = (row: PhotoRow): string => (row.picked ? row.picked.name : row.readName.trim());

/** 〔D6〕A: 약 1개 이상 + 질문이 비어 있지 않을 때만 `이대로 확인`이 켜진다 */
export function canConfirm(rows: readonly PhotoRow[], question: string): boolean {
  return rows.some((row) => rowName(row).length > 0) && question.trim().length > 0;
}

export function buildChatInput(rows: readonly PhotoRow[], question: string): ChatInputFromPhoto {
  const named = rows.filter((row) => rowName(row).length > 0);
  const names = named.map(rowName);
  const confirmedDrugs: ConfirmedDrug[] = named.flatMap((row) =>
    row.picked ? [{ name: row.picked.name, itemSeq: row.picked.item_seq, inputName: row.picked.name }] : [],
  );
  return { question: `${names.join(PHOTO_NAME_JOIN)} ${question.trim()}`.trim(), confirmedDrugs };
}
