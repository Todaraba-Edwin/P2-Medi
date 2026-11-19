import type { Candidate } from "@/lib/api";

/** 되묻는 입력(`input_name`) 하나와 그 후보들 */
export interface CandidateGroup {
  inputName: string;
  items: Candidate[];
}

/** 묶음별로 고른 후보(`input_name` → 받은 후보 객체 그대로). 고르지 않은 묶음은 키가 없다 */
export type CandidatePicks = Readonly<Record<string, Candidate>>;

/** 후보를 되묻는 입력(`input_name`)별로 나눈다. 묶음과 후보의 순서는 받은 순서다 */
export function groupCandidates(candidates: readonly Candidate[]): CandidateGroup[] {
  const groups: CandidateGroup[] = [];
  for (const candidate of candidates) {
    const group = groups.find((item) => item.inputName === candidate.input_name);
    if (group) group.items.push(candidate);
    else groups.push({ inputName: candidate.input_name, items: [candidate] });
  }
  return groups;
}

/** 묶음 표지 글자(FE-10): 받은 순서대로 A·B·C… 색과 함께 쓰여 색만으로 구분하지 않게 한다 */
export const groupLetter = (index: number) => String.fromCharCode(65 + index);

/**
 * 다른 묶음에서 이미 고른 제품인가(FE-09-03 A). 품목기준코드(`item_seq`)가 같을 때만 같은 제품으로 본다(코드가 없는 후보는 막지 않는다).
 * 서버는 고른 코드가 어느 이름에서 왔는지 모르므로, 같은 코드를 두 묶음에서 고르지 못하게 화면이 막는다.
 */
export function isTakenElsewhere(candidate: Candidate, picks: CandidatePicks): boolean {
  if (candidate.item_seq === null) return false;
  return Object.entries(picks).some(([inputName, pick]) => inputName !== candidate.input_name && pick.item_seq === candidate.item_seq);
}
