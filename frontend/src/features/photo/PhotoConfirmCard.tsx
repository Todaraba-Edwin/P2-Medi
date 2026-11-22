"use client";

import { useId } from "react";
import { PlusIcon, Trash2Icon } from "lucide-react";
import type { DrugCandidate } from "@/lib/api/account";
import type { Emergency } from "@/lib/api";
import { HOVER_TEXT, ICON_BUTTON, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/button";
import { MedIcon } from "@/components/MedIcon";
import { NoMascotZone } from "@/components/NoMascotZone";
import { EmergencyBanner } from "@/features/emergency";
import { cn } from "@/lib/utils";
import { canConfirm } from "./build-chat-input";
import type { PhotoRow } from "./build-chat-input";
import {
  DRUG_DATA_SCOPE_NOTICE,
  PHOTO_ADD_DRUG_LABEL,
  PHOTO_CANDIDATES_GUIDE,
  PHOTO_CANDIDATES_LABEL,
  PHOTO_CONFIRM_GUIDE,
  PHOTO_CONFIRM_LABEL,
  PHOTO_DRUG_LIST_LABEL,
  PHOTO_QUESTION_LABEL,
  PHOTO_READ_NAME_LABEL,
  photoDeleteRowLabel,
} from "./copy";
import { INGEST_QUESTION_MAX_CHARS } from "./types";

export interface PhotoConfirmCardProps {
  rows: readonly PhotoRow[];
  question: string;
  /** 응답의 `emergency`(서버 상수). 있으면 카드 맨 위에 119를 둔다 */
  emergency: Emergency | null;
  onEditName: (id: string, value: string) => void;
  /** 후보를 고르거나(같은 것을 다시 누르면) 푼다. 기본 선택은 없다 */
  onPick: (id: string, candidate: DrugCandidate | null) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
  onQuestion: (value: string) => void;
  /** `이대로 확인`: 약 1개 이상 + 질문이 있을 때만 켜진다(〔D6〕A). 누르면 조립하는 쪽이 `/chat`을 한 번 부른다 */
  onConfirm: () => void;
}

/**
 * 확인·수정 카드(PJ2-PRD.md 15.4 "확인·수정 카드" 행, 되묻기 카드와 같은 틀): 읽은 약을 세로 목록으로 보이고 항목별 수정·삭제, `약 추가`, 질문 입력칸, `이대로 확인`.
 * - 읽은 글자는 입력칸에 그대로 두고(수정 가능), 성분·용량/제형 글자는 작은 글자로 병기한다. 항목 앞은 캡슐 말풍선 아이콘(FE-06-01, 병아리 아님)
 * - 사전 후보는 라디오(`role="radio"`)이고 **기본 선택이 없다**(PRD-08-06 A). 고르지 않으면 적힌 글자로 찾는다(P6). 확신도는 응답에 없고 화면에도 없다
 * - 확인을 누르기 전에는 판정을 찾지 않는다(H19): 이 카드는 서버를 부르지 않는다
 * - `약 추가`는 빈 입력칸 하나다(사전 검색 없음: `/drugs/search`는 로그인 전용이라 게스트가 못 쓴다)
 */
export function PhotoConfirmCard({ rows, question, emergency, onEditName, onPick, onRemove, onAdd, onQuestion, onConfirm }: PhotoConfirmCardProps) {
  const baseId = useId();
  const questionId = `${baseId}-question`;
  const ready = canConfirm(rows, question);

  return (
    <div data-testid="photo-confirm-card" className="flex flex-col gap-3.5">
      {/* 서버가 준 119는 카드 맨 위(프런트 키워드 목록 없음, RFP-35-03) */}
      {emergency && <EmergencyBanner emergency={emergency} />}
      <NoMascotZone>
        <p data-testid="photo-confirm-guide" className="m-0 text-sm leading-5 text-ink-2 [word-break:keep-all]">
          {PHOTO_CONFIRM_GUIDE}
        </p>
        {/* 자료 밖 약 고지(FE-04-25 A): 프로필 복용 약 입력과 같은 상수·같은 모양. 색은 토큰만(라이트·다크 AA) */}
        <p data-testid="drug-data-scope-notice" className="m-0 mt-2 rounded-xl bg-bg-soft px-3 py-2 text-xs leading-[17px] text-ink-2 [word-break:keep-all]">
          {DRUG_DATA_SCOPE_NOTICE}
        </p>
      </NoMascotZone>
      <ul aria-label={PHOTO_DRUG_LIST_LABEL} data-testid="photo-rows" className="m-0 flex list-none flex-col gap-2 p-0">
        {rows.map((row, index) => {
          const inputId = `${baseId}-row-${index}`;
          return (
            <li key={row.id} data-testid="photo-row" className="overflow-hidden rounded-2xl border border-line bg-bg">
              <div className="flex items-center gap-2 py-1.5 pr-1 pl-3">
                <MedIcon size={24} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <label htmlFor={inputId} className="sr-only">
                    {PHOTO_READ_NAME_LABEL}
                  </label>
                  <input
                    id={inputId}
                    type="text"
                    value={row.readName}
                    autoComplete="off"
                    data-testid="photo-read-name"
                    onChange={(event) => onEditName(row.id, event.target.value)}
                    className="min-h-11 w-full min-w-0 rounded-lg border border-line-2 bg-bg px-2.5 text-[15px] leading-5 font-semibold outline-none focus:border-link"
                  />
                  {(row.readIngredient || row.strengthOrForm) && (
                    <span data-testid="photo-read-sub" className="flex flex-wrap gap-x-2 px-1 pt-1 text-xs leading-4 text-mute">
                      {row.readIngredient && <span data-slot="read-ingredient">{row.readIngredient}</span>}
                      {row.strengthOrForm && <span data-slot="strength-or-form">{row.strengthOrForm}</span>}
                    </span>
                  )}
                </div>
                <button type="button" data-testid="photo-row-remove" aria-label={photoDeleteRowLabel(row.readName)} onClick={() => onRemove(row.id)} className={ICON_BUTTON}>
                  <Trash2Icon className="size-5 text-ink-2" aria-hidden="true" />
                </button>
              </div>
              {row.candidates.length > 0 && (
                <NoMascotZone>
                  <div className="border-t border-line">
                    <p data-testid="photo-candidates-guide" className="m-0 px-3 py-2 text-xs leading-4 text-ink-2 [word-break:keep-all]">
                      {PHOTO_CANDIDATES_GUIDE}
                    </p>
                    <div role="radiogroup" aria-label={`${rowNameForLabel(row)} ${PHOTO_CANDIDATES_LABEL}`}>
                      {row.candidates.map((candidate, candidateIndex) => {
                        const checked = row.picked === candidate;
                        return (
                          <button
                            key={`${candidate.item_seq ?? ""}:${candidate.name}:${candidateIndex}`}
                            type="button"
                            role="radio"
                            aria-checked={checked}
                            data-testid="photo-candidate"
                            onClick={() => onPick(row.id, checked ? null : candidate)}
                            className={`group flex min-h-12 w-full items-center justify-between gap-2.5 border-t border-line px-3 py-2 text-left aria-checked:bg-bg-soft ${HOVER_TEXT}`}
                          >
                            <span className="flex min-w-0 flex-col items-start gap-0.5">
                              <b data-part="candidate-name" className="max-w-full text-[15px] leading-5 font-semibold [overflow-wrap:break-word] [word-break:keep-all]">
                                {candidate.name}
                              </b>
                              {(candidate.prescription || candidate.entp_name) && (
                                <span className="flex max-w-full flex-wrap gap-x-2 text-xs leading-4 text-mute">
                                  {candidate.prescription && <span data-slot="prescription">{candidate.prescription}</span>}
                                  {candidate.entp_name && <span data-slot="entp-name">{candidate.entp_name}</span>}
                                </span>
                              )}
                            </span>
                            {/* 라디오 원(되묻기 카드와 같은 모양). 상태는 `aria-checked`가 알린다 */}
                            <span
                              aria-hidden="true"
                              data-part="radio-mark"
                              className="size-5 flex-none rounded-full border-[1.5px] border-faint group-aria-checked:border-[6px] group-aria-checked:border-yellow"
                            />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </NoMascotZone>
              )}
            </li>
          );
        })}
      </ul>
      <button type="button" data-testid="photo-add-row" onClick={onAdd} className={cn(SECONDARY_BUTTON, "flex items-center justify-center gap-1.5 self-start")}>
        <PlusIcon className="size-4" aria-hidden="true" />
        {PHOTO_ADD_DRUG_LABEL}
      </button>
      <div className="flex flex-col gap-1">
        <label htmlFor={questionId} className="text-xs font-semibold text-ink-2">
          {PHOTO_QUESTION_LABEL}
        </label>
        <textarea
          id={questionId}
          rows={2}
          value={question}
          maxLength={INGEST_QUESTION_MAX_CHARS}
          autoComplete="off"
          data-testid="photo-question"
          onChange={(event) => onQuestion(event.target.value)}
          className="min-h-11 w-full resize-none rounded-2xl border border-line-2 bg-bg px-3 py-2.5 text-base leading-6 outline-none focus:border-link"
        />
      </div>
      <button type="button" data-testid="photo-confirm" disabled={!ready} onClick={onConfirm} className={cn(PRIMARY_BUTTON, "w-full")}>
        {PHOTO_CONFIRM_LABEL}
      </button>
    </div>
  );
}

/** 후보 묶음 이름 앞에 붙일 그 줄의 글자(비어 있으면 "약") */
const rowNameForLabel = (row: PhotoRow) => row.readName.trim() || "약";
