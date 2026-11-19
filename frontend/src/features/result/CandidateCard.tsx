"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Candidate } from "@/lib/api";
import { HOVER_TEXT, TEXT_BUTTON } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { groupCandidates, isTakenElsewhere } from "./candidate-groups";
import type { CandidatePicks } from "./candidate-groups";
import { CANDIDATES_LABEL, CANDIDATE_CHANGE_LABEL, CANDIDATE_OTHER_LABEL, CANDIDATE_PICKED_ARROW, CANDIDATE_TAKEN_NOTE } from "./copy";

export interface CandidateCardProps {
  /** 되묻기 후보(`end_reason == CLARIFY`일 때만 온다). 받은 순서대로 그린다 */
  candidates: readonly Candidate[];
  /** 후보를 눌렀을 때. 어느 묶음인지는 후보의 `input_name`이다. 선택값을 붙여 다시 묻는 일은 조립하는 쪽(FE-IMPL-06)이 한다 */
  onPick: (candidate: Candidate) => void;
  /** 주면 묶음마다 "목록에 없어요 · 직접 입력" 버튼이 보인다 */
  onOther?: () => void;
  /**
   * 묶음별로 지금 고른 후보(`input_name` → 받은 후보 객체 그대로). 주면 후보 버튼이 선택 상태(`aria-pressed`)를 알린다(고른 것이 없으면 빈 객체).
   * 누르면 `onPick`만 부른다: 보내거나 다른 결과로 가는 일은 이 카드가 하지 않는다
   */
  selected?: CandidatePicks;
}

/**
 * 되묻기 후보 카드. 후보의 이름·업체·구분 글자를 받은 그대로 보이고, 먹어도 되는지는 말하지 않는다(판정 표시 없음).
 * 묻는 문장은 응답의 `summary`이며 이 카드 밖(조립하는 쪽)에서 그린다. 마스코트는 쓰지 않는다.
 *
 * 되묻는 이름이 둘 이상이면(FE-09-01 A) 묶음마다 하나씩 고른다: 고른 묶음은 한 줄("입력 → 고른 제품 · 바꾸기")로 접히고 "바꾸기"로 다시 펼친다.
 * 다른 묶음에서 이미 고른 제품은 고를 수 없다(FE-09-03 A). 묶음이 하나면 접지 않는다(고른 후보가 눌린 상태로 남는다).
 */
export function CandidateCard({ candidates, onPick, onOther, selected }: CandidateCardProps) {
  const baseId = useId();
  const card = useRef<HTMLElement>(null);
  /** "바꾸기"로 다시 펼친 묶음(고른 값은 그대로 두고 목록만 다시 보인다) */
  const [reopened, setReopened] = useState<readonly string[]>([]);
  /** 접히거나 펼쳐져 초점이 있던 버튼이 사라질 때 초점을 옮길 자리(묶음 순번과 대상) */
  const focusNext = useRef<{ group: number; target: "change" | "pressed" } | null>(null);

  useEffect(() => {
    const next = focusNext.current;
    if (!next) return;
    const selector = next.target === "change" ? '[data-testid="candidate-change"]' : '[data-testid="candidate"][aria-pressed="true"]';
    const element = card.current?.querySelector<HTMLElement>(`[data-group-index="${next.group}"] ${selector}`);
    if (!element) return; // 아직 접히거나 펼쳐지지 않았다(고른 값은 조립하는 쪽이 준다)
    focusNext.current = null;
    element.focus();
  });

  if (candidates.length === 0) return null;
  const groups = groupCandidates(candidates);
  const multiple = groups.length > 1;

  return (
    <NoMascotZone>
      <section ref={card} data-testid="candidate-card" aria-label={CANDIDATES_LABEL} className="overflow-hidden rounded-2xl border border-line bg-bg">
        {groups.map((group, groupIndex) => {
          const pick = selected?.[group.inputName];
          const collapsed = multiple && pick !== undefined && !reopened.includes(group.inputName);
          const headingId = `${baseId}-group-${groupIndex}`;
          return (
            <div
              key={group.inputName}
              role="group"
              aria-labelledby={headingId}
              data-testid="candidate-group"
              data-group-index={groupIndex}
              data-collapsed={collapsed ? "true" : undefined}
              className="border-t border-line first:border-t-0"
            >
              {collapsed && pick !== undefined ? (
                // 고른 묶음의 한 줄 요약. 이름은 받은 글자 그대로다
                <div data-testid="candidate-picked" className="flex min-h-[54px] items-center gap-2 bg-bg-softer py-1 pr-1.5 pl-3.5">
                  <p className="m-0 min-w-0 flex-1 text-sm leading-5 [overflow-wrap:break-word] [word-break:keep-all]">
                    <span id={headingId} className="font-bold text-ink">
                      {group.inputName}
                    </span>{" "}
                    <span aria-hidden="true" className="text-mute">
                      {CANDIDATE_PICKED_ARROW}
                    </span>{" "}
                    <b data-slot="picked-name" className="font-semibold">
                      {pick.name}
                    </b>
                  </p>
                  <button
                    type="button"
                    data-testid="candidate-change"
                    aria-label={`${group.inputName} ${CANDIDATE_CHANGE_LABEL}`}
                    onClick={() => {
                      focusNext.current = { group: groupIndex, target: "pressed" };
                      setReopened((prev) => [...prev, group.inputName]);
                    }}
                    className={`${TEXT_BUTTON} flex-none`}
                  >
                    {CANDIDATE_CHANGE_LABEL}
                  </button>
                </div>
              ) : (
                <>
                  <header id={headingId} className="bg-bg-softer px-3.5 py-[9px] text-[13px] font-bold break-words text-ink">
                    {group.inputName}
                  </header>
                  <ul className="m-0 list-none p-0">
                    {group.items.map((candidate, index) => {
                      const taken = multiple && selected !== undefined && isTakenElsewhere(candidate, selected);
                      return (
                        <li key={`${candidate.item_seq ?? ""}:${candidate.name}:${index}`} className="border-t border-line">
                          <button
                            type="button"
                            data-testid="candidate"
                            data-taken={taken ? "true" : undefined}
                            disabled={taken}
                            aria-pressed={selected === undefined ? undefined : pick === candidate}
                            onClick={() => {
                              // 여러 묶음이면 고른 묶음이 접힌다: 초점은 그 줄의 "바꾸기"로 옮긴다
                              focusNext.current = multiple && selected !== undefined ? { group: groupIndex, target: "change" } : null;
                              setReopened((prev) => prev.filter((name) => name !== group.inputName));
                              onPick(candidate);
                            }}
                            className={`flex min-h-[54px] w-full flex-col items-start justify-center gap-0.5 px-3.5 py-2 text-left aria-pressed:bg-bg-soft aria-pressed:shadow-[inset_3px_0_0_var(--color-yellow)] disabled:bg-bg-softer disabled:text-mute ${HOVER_TEXT}`}
                          >
                            <b className="max-w-full text-[15px] leading-[21px] font-semibold [overflow-wrap:break-word] [word-break:keep-all]">{candidate.name}</b>
                            {(candidate.prescription || candidate.entp_name) && (
                              <span className="flex max-w-full flex-wrap gap-x-2 text-xs leading-[17px] text-mute">
                                {candidate.prescription && <span data-slot="prescription">{candidate.prescription}</span>}
                                {candidate.entp_name && <span data-slot="entp-name">{candidate.entp_name}</span>}
                              </span>
                            )}
                            {/* 고를 수 없는 이유(다른 묶음에서 이미 고른 제품). 가부를 말하지 않는다 */}
                            {taken && (
                              <span data-slot="taken-note" className="max-w-full text-xs leading-[17px] font-semibold text-ink-2">
                                {CANDIDATE_TAKEN_NOTE}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  {onOther && (
                    <button
                      type="button"
                      data-testid="candidate-other"
                      onClick={onOther}
                      className={`flex min-h-11 w-full items-center border-t border-line px-3.5 py-2.5 text-left text-sm font-semibold text-link ${HOVER_TEXT}`}
                    >
                      {CANDIDATE_OTHER_LABEL}
                    </button>
                  )}
                </>
              )}
            </div>
          );
        })}
      </section>
    </NoMascotZone>
  );
}
