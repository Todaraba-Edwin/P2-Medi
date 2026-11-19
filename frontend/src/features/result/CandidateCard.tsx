"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Candidate } from "@/lib/api";
import { HOVER_TEXT, TEXT_BUTTON } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";
import { groupCandidates, isTakenElsewhere } from "./candidate-groups";
import type { CandidatePicks } from "./candidate-groups";
import { CANDIDATES_LABEL, CANDIDATE_CHANGE_LABEL, CANDIDATE_OTHER_LABEL, CANDIDATE_PICKED_ARROW, CANDIDATE_TAKEN_NOTE, candidateCountLabel } from "./copy";
import { GroupTag } from "./PickCapsule";

export interface CandidateCardProps {
  /** 되묻기 후보(`end_reason == CLARIFY`일 때만 온다). 받은 순서대로 그린다 */
  candidates: readonly Candidate[];
  /** 후보를 눌렀을 때. 어느 묶음인지는 후보의 `input_name`이다. 선택값을 붙여 다시 묻는 일은 조립하는 쪽(FE-IMPL-06)이 한다 */
  onPick: (candidate: Candidate) => void;
  /** 주면 묶음마다 "목록에 없어요 · 직접 입력" 버튼이 보인다 */
  onOther?: () => void;
  /**
   * 묶음별로 지금 고른 후보(`input_name` → 받은 후보 객체 그대로). 후보는 라디오(`role="radio"`)이고 고른 것만 `aria-checked="true"`다(주지 않으면 모두 고르지 않은 상태).
   * 누르면 `onPick`만 부른다: 보내거나 다른 결과로 가는 일은 이 카드가 하지 않는다
   */
  selected?: CandidatePicks;
}

/**
 * 되묻기 후보 카드. 후보의 이름·업체·구분 글자를 받은 그대로 보이고, 먹어도 되는지는 말하지 않는다(판정 표시 없음).
 * 묻는 문장은 응답의 `summary`이며 이 카드 밖(조립하는 쪽)에서 그린다. 마스코트는 쓰지 않는다.
 *
 * 되묻는 이름이 둘 이상이면(FE-09-01 A) 묶음마다 하나씩 고른다: 고른 묶음은 한 줄("입력 → 고른 제품 · 바꾸기")로 접히고 "바꾸기"로 다시 펼친다.
 * 다른 묶음에서 이미 고른 제품은 고를 수 없다(FE-09-03 A). 묶음이 하나면 접지 않는다(고른 후보가 고른 상태로 남는다).
 *
 * 모양(FE-10, 디자인 "FE-09 r2"): 묶음 머리 16px 굵게(노랑 바탕) > 후보 이름 15px 반굵게 > 보조줄 12px(FE-10-01 B). 후보 줄 오른쪽에 라디오 원을 둔다.
 * 묶음이 둘 이상이면 머리·접힌 줄 앞에 캡슐 칸 표지(A·B·C…)를 두고, 카드가 놓인 칸이 640px 이상이면 2열로 놓는다(FE-10-02 A·FE-10-04 A, 3개부터 줄바꿈).
 * 묶음은 `role="radiogroup"`이다. 화살표 키는 같은 묶음 안에서 초점만 옮기고 고르지는 않는다(고르면 묶음이 접히므로 Enter·Space로 고른다).
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
    const selector = next.target === "change" ? '[data-testid="candidate-change"]' : '[data-testid="candidate"][aria-checked="true"]';
    const element = card.current?.querySelector<HTMLElement>(`[data-group-index="${next.group}"] ${selector}`);
    if (!element) return; // 아직 접히거나 펼쳐지지 않았다(고른 값은 조립하는 쪽이 준다)
    focusNext.current = null;
    element.focus();
  });

  if (candidates.length === 0) return null;
  const groups = groupCandidates(candidates);
  const multiple = groups.length > 1;

  /** 화살표 키: 같은 묶음의 고를 수 있는 후보 사이에서 초점만 옮긴다(끝에서 처음으로 돈다) */
  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) return;
    const radios = [...(event.currentTarget.closest('[role="radiogroup"]')?.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)') ?? [])];
    const at = radios.indexOf(event.currentTarget);
    if (at < 0 || radios.length < 2) return;
    event.preventDefault();
    radios[(at + step + radios.length) % radios.length].focus();
  };

  return (
    <NoMascotZone>
      {/* 2열 기준은 화면 폭이 아니라 카드가 놓인 칸의 폭이다(FE-10-02 A) */}
      <div className="@container">
        <section
          ref={card}
          data-testid="candidate-card"
          data-multiple={multiple ? "true" : undefined}
          aria-label={CANDIDATES_LABEL}
          className={cn(
            "overflow-hidden rounded-2xl border border-line bg-bg",
            // 2열: 위쪽 정렬, 가운데 1px 선(묶음 바탕 아래에 깔린다)
            multiple &&
              "@[640px]:grid @[640px]:grid-cols-2 @[640px]:items-start @[640px]:bg-[linear-gradient(var(--color-line),var(--color-line))] @[640px]:bg-[length:1px_100%] @[640px]:bg-center @[640px]:bg-no-repeat",
          )}
        >
          {groups.map((group, groupIndex) => {
            const pick = selected?.[group.inputName];
            const collapsed = multiple && pick !== undefined && !reopened.includes(group.inputName);
            const headingId = `${baseId}-group-${groupIndex}`;
            const tag = multiple ? <GroupTag index={groupIndex} count={groups.length} /> : null;
            return (
              <div
                key={group.inputName}
                role={collapsed ? "group" : "radiogroup"}
                aria-labelledby={headingId}
                data-testid="candidate-group"
                data-group-index={groupIndex}
                data-collapsed={collapsed ? "true" : undefined}
                className={cn("min-w-0 border-t border-line first:border-t-0", multiple && "@[640px]:nth-2:border-t-0")}
              >
                {collapsed && pick !== undefined ? (
                  // 고른 묶음의 한 줄 요약. 이름은 받은 글자 그대로다
                  <div data-testid="candidate-picked" className="flex min-h-[52px] items-center gap-2 py-1 pr-1.5 pl-3.5">
                    {tag}
                    <p className="m-0 min-w-0 flex-1 text-[15px] leading-5 text-ink-2 [overflow-wrap:break-word] [word-break:keep-all]">
                      <span id={headingId}>{group.inputName}</span>{" "}
                      <span aria-hidden="true" className="text-mute">
                        {CANDIDATE_PICKED_ARROW}
                      </span>{" "}
                      <b data-slot="picked-name" className="font-bold text-ink">
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
                    <header data-slot="group-head" className="flex items-center gap-2 bg-yellow-2 px-3.5 py-[9px] text-base font-bold text-ink-2">
                      {tag}
                      <span id={headingId} data-slot="group-name" className="min-w-0 break-words">
                        {group.inputName}
                      </span>
                      <small data-slot="group-count" className="ml-auto flex-none text-xs font-semibold text-mute">
                        {candidateCountLabel(group.items.length)}
                      </small>
                    </header>
                    <ul className="m-0 list-none p-0">
                      {group.items.map((candidate, index) => {
                        const taken = multiple && selected !== undefined && isTakenElsewhere(candidate, selected);
                        return (
                          <li key={`${candidate.item_seq ?? ""}:${candidate.name}:${index}`} className="border-t border-line">
                            <button
                              type="button"
                              role="radio"
                              aria-checked={pick === candidate}
                              data-testid="candidate"
                              data-taken={taken ? "true" : undefined}
                              disabled={taken}
                              onKeyDown={moveFocus}
                              onClick={() => {
                                // 여러 묶음이면 고른 묶음이 접힌다: 초점은 그 줄의 "바꾸기"로 옮긴다
                                focusNext.current = multiple && selected !== undefined ? { group: groupIndex, target: "change" } : null;
                                setReopened((prev) => prev.filter((name) => name !== group.inputName));
                                onPick(candidate);
                              }}
                              className={`group flex min-h-14 w-full items-center justify-between gap-2.5 px-3.5 py-2 text-left aria-checked:bg-bg-soft disabled:bg-bg-softer disabled:text-mute ${HOVER_TEXT}`}
                            >
                              <span className="flex min-w-0 flex-col items-start gap-0.5">
                                <b data-part="candidate-name" className="max-w-full text-[15px] leading-5 font-semibold [overflow-wrap:break-word] [word-break:keep-all]">
                                  {candidate.name}
                                </b>
                                {(candidate.prescription || candidate.entp_name) && (
                                  <span data-part="candidate-sub" className="flex max-w-full flex-wrap gap-x-2 text-xs leading-4 text-mute">
                                    {candidate.prescription && <span data-slot="prescription">{candidate.prescription}</span>}
                                    {candidate.entp_name && <span data-slot="entp-name">{candidate.entp_name}</span>}
                                  </span>
                                )}
                                {/* 고를 수 없는 이유(다른 묶음에서 이미 고른 제품). 가부를 말하지 않는다 */}
                                {taken && (
                                  <span data-slot="taken-note" className="max-w-full text-xs leading-4 font-semibold text-ink-2">
                                    {CANDIDATE_TAKEN_NOTE}
                                  </span>
                                )}
                              </span>
                              {/* 라디오 원: 고르면 노랑 6px 테두리. 상태는 `aria-checked`가 알린다 */}
                              <span
                                aria-hidden="true"
                                data-part="radio-mark"
                                className="size-5 flex-none rounded-full border-[1.5px] border-faint group-disabled:border-line-2 group-aria-checked:border-[6px] group-aria-checked:border-yellow"
                              />
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
      </div>
    </NoMascotZone>
  );
}
