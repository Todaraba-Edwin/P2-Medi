import type { Candidate } from "@/lib/api";
import { HOVER_TEXT } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { CANDIDATES_LABEL, CANDIDATE_OTHER_LABEL } from "./copy";

export interface CandidateCardProps {
  /** 되묻기 후보(`end_reason == CLARIFY`일 때만 온다). 받은 순서대로 그린다 */
  candidates: readonly Candidate[];
  /** 후보를 눌렀을 때. 선택값을 붙여 다시 묻는 일은 조립하는 쪽(FE-IMPL-06)이 한다 */
  onPick: (candidate: Candidate) => void;
  /** 주면 "목록에 없어요 · 직접 입력" 버튼이 보인다 */
  onOther?: () => void;
  /**
   * 지금 고른 후보(받은 후보 객체 그대로). 주면 후보 버튼이 선택 상태(`aria-pressed`)를 알린다(고른 것이 없으면 null).
   * 누르면 `onPick`만 부른다: 보내거나 다른 결과로 가는 일은 이 카드가 하지 않는다
   */
  selected?: Candidate | null;
}

/**
 * 되묻기 후보 카드. 후보의 이름·업체·구분 글자를 받은 그대로 보이고, 먹어도 되는지는 말하지 않는다(판정 표시 없음).
 * 묻는 문장은 응답의 `summary`이며 이 카드 밖(조립하는 쪽)에서 그린다. 마스코트는 쓰지 않는다.
 */
export function CandidateCard({ candidates, onPick, onOther, selected }: CandidateCardProps) {
  if (candidates.length === 0) return null;
  // 되묻는 입력(`input_name`)별로 나눈다. 묶음과 후보의 순서는 받은 순서다
  const groups: { inputName: string; items: Candidate[] }[] = [];
  for (const candidate of candidates) {
    const group = groups.find((g) => g.inputName === candidate.input_name);
    if (group) group.items.push(candidate);
    else groups.push({ inputName: candidate.input_name, items: [candidate] });
  }
  return (
    <NoMascotZone>
      <section data-testid="candidate-card" aria-label={CANDIDATES_LABEL} className="overflow-hidden rounded-2xl border border-line bg-bg">
        {groups.map((group) => (
          <div key={group.inputName} data-testid="candidate-group" className="border-t border-line first:border-t-0">
            <header className="bg-bg-softer px-3.5 py-[9px] text-[13px] font-bold break-words text-ink">{group.inputName}</header>
            <ul className="m-0 list-none p-0">
              {group.items.map((candidate, index) => (
                <li key={`${candidate.item_seq ?? ""}:${candidate.name}:${index}`} className="border-t border-line">
                  <button
                    type="button"
                    data-testid="candidate"
                    aria-pressed={selected === undefined ? undefined : selected === candidate}
                    onClick={() => onPick(candidate)}
                    className={`flex min-h-[54px] w-full flex-col items-start justify-center gap-0.5 px-3.5 py-2 text-left aria-pressed:bg-bg-soft aria-pressed:shadow-[inset_3px_0_0_var(--color-yellow)] ${HOVER_TEXT}`}
                  >
                    <b className="max-w-full text-[15px] leading-[21px] font-semibold [overflow-wrap:break-word] [word-break:keep-all]">{candidate.name}</b>
                    {(candidate.prescription || candidate.entp_name) && (
                      <span className="flex max-w-full flex-wrap gap-x-2 text-xs leading-[17px] text-mute">
                        {candidate.prescription && <span data-slot="prescription">{candidate.prescription}</span>}
                        {candidate.entp_name && <span data-slot="entp-name">{candidate.entp_name}</span>}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {onOther && (
          <button
            type="button"
            onClick={onOther}
            className={`flex min-h-11 w-full items-center border-t border-line px-3.5 py-2.5 text-left text-sm font-semibold text-link ${HOVER_TEXT}`}
          >
            {CANDIDATE_OTHER_LABEL}
          </button>
        )}
      </section>
    </NoMascotZone>
  );
}
