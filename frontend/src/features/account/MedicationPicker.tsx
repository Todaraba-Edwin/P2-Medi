"use client";

import { useEffect, useId, useRef, useState } from "react";
import { AccountApiError, DRUG_CANDIDATES_MAX, DRUG_MATCH_SIMILAR, DRUG_QUERY_MAX_CHARS, MEDICATIONS_MAX, searchDrugs } from "@/lib/api/account";
import type { DrugCandidate, MedicationInput } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import {
  ERROR_MEDICATION_LIMIT,
  MEDICATION_ADD_LABEL,
  MEDICATION_HINT,
  MEDICATION_KIND_LABELS,
  MEDICATION_NO_CANDIDATES,
  MEDICATION_SEARCHING,
  MEDICATION_SEARCH_AUTH_EXPIRED,
  MEDICATION_SEARCH_FAILED,
  MEDICATION_SEARCH_HINT,
  MEDICATION_SIMILAR_TAG,
  medicationCandidatesLabel,
} from "./copy";
import { FIELD_CLASS, SECONDARY_BUTTON } from "./parts";

/** 입력이 멈춘 뒤 검색까지의 간격(지시서 2026-11-20 fedrug: 300ms. 서버에 요청 수 제한이 없어 입력 중 호출을 줄인다) */
export const MEDICATION_SEARCH_DEBOUNCE_MS = 300;

type SearchStatus = "idle" | "searching" | "ready" | "error";

interface SearchResult {
  /** 이 후보를 낸 검색어(앞뒤 공백 제거). 입력이 바뀌어도 새 결과가 올 때까지 앞 후보를 보여 준다 */
  q: string;
  candidates: DrugCandidate[];
}

export interface MedicationPickerProps {
  /** 입력 칸 id(폼의 `<label htmlFor>`가 가리킨다) */
  id: string;
  /** 지금 목록에 있는 약 개수. `MEDICATIONS_MAX`에 닿으면 입력을 막는다 */
  count: number;
  /** 후보를 고르거나 글자를 그대로 확정했을 때. `item_seq`가 null이면 확인 안 된 약(FE-04-20 A) */
  onAdd: (item: MedicationInput) => void;
  /** 시험에서 바꿔 끼운다. 기본은 `POST /api/drugs/search` */
  search?: typeof searchDrugs;
}

/**
 * 프로필 약 입력(FE-04-13 A): 글자를 적으면 사전 후보(제품명 → 성분명, 최대 10)를 보여 주고 고르게 하는 콤보박스(WAI-ARIA combobox + listbox).
 * - 입력이 멈춘 뒤 300ms에 한 번 검색한다(1글자 이상, 100자 이하). 검색어가 바뀌면 앞 요청은 끊고 결과를 버린다
 * - ↑↓로 후보를 옮기고 Enter로 고른다. 후보가 하나뿐이어도 자동으로 고르지 않는다(FE-04-22 A, 비슷한 이름 후보를 조용히 확정하지 않게).
 *   Esc는 목록만 닫는다(목록이 닫혀 있으면 모달의 Esc다)
 * - 고르지 않은 채 저장하는 길(FE-04-24 A, 2026-11-22):
 *   · 검색 중(입력이 멈추기 전 디바운스 대기·요청 중)에는 `그대로 추가`가 비활성이고 Enter도 저장하지 않는다(후보를 보기 전에 확인 안 된 약으로 들어가지 않게)
 *   · 지금 글자의 후보가 1개 이상 있으면 Enter는 **첫 후보로 활성만 옮기고** 저장하지 않는다. 한 번 더 Enter를 누르면 그 후보가 들어간다
 *   · 후보가 없거나 검색이 실패했을 때의 Enter와, 언제든 누르는 `그대로 추가` 버튼은 적은 글자를 **그대로**(`item_seq` 없음 = 확인 안 된 약) 넣는다
 * - 검색이 실패해도(401·422·네트워크) 적은 글자는 그대로 남고 `그대로 추가`로 저장할 수 있다. 검색어는 콘솔·로그·오류 객체에 남기지 않는다
 * - 한글 조합 중의 Enter·화살표는 넘긴다(`isComposing`, 조합을 끝내는 Enter를 `keyCode 229`로 보내는 브라우저도 같이 본다)
 */
export function MedicationPicker({ id, count, onAdd, search = searchDrugs }: MedicationPickerProps) {
  const listId = useId();
  const optionId = (index: number) => `${listId}-option-${index}`;
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [authExpired, setAuthExpired] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const full = count >= MEDICATIONS_MAX;
  const q = query.trim();
  const candidates = result?.candidates ?? [];
  const listed = open && candidates.length > 0;
  /** 검색할 글자인데 아직 이 글자의 결과가 없다(디바운스 대기·요청 중). 실패(`error`)는 끝난 것으로 쳐서 글자 저장을 막지 않는다 */
  const awaiting = !!q && !full && q.length <= DRUG_QUERY_MAX_CHARS && status !== "error" && result?.q !== q;
  /** 지금 글자로 찾은 후보가 1개 이상 있다(목록이 닫혀 있어도) */
  const hasCandidates = !awaiting && result?.q === q && candidates.length > 0;

  // 입력이 멈춘 뒤 300ms에 검색한다. 그 사이 입력이 바뀌면 예약을 지우고 진행 중 요청은 끊는다(끊은 요청의 결과·오류는 버린다)
  useEffect(() => {
    if (!q || q.length > DRUG_QUERY_MAX_CHARS || full) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus("searching");
      try {
        const found = await search(q, controller.signal);
        if (controller.signal.aborted) return;
        setResult({ q, candidates: found.candidates.slice(0, DRUG_CANDIDATES_MAX) });
        setStatus("ready");
        setActive(-1);
        setOpen(true);
      } catch (error) {
        if (controller.signal.aborted) return;
        // 코드·상태만 본다(검색어는 쓰지 않는다). 401은 로그인 만료 안내, 나머지는 공통 안내
        setAuthExpired(error instanceof AccountApiError && error.status === 401);
        setStatus("error");
        setResult(null);
        setOpen(false);
      }
    }, MEDICATION_SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q, full, search]);

  const reset = () => {
    setQuery("");
    setResult(null);
    setStatus("idle");
    setAuthExpired(false);
    setOpen(false);
    setActive(-1);
  };

  const pick = (candidate: DrugCandidate) => {
    onAdd({ input_text: candidate.name, item_seq: candidate.item_seq });
    reset();
    input.current?.focus();
  };

  /** 후보 없이 적은 글자 그대로(확인 안 된 약). 검색 중에는 넣지 않는다(FE-04-24 A) */
  const confirmText = () => {
    if (!q || full || awaiting) return;
    onAdd({ input_text: q, item_seq: null });
    reset();
    input.current?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    // 한글 조합 중이면 넘긴다. 일부 브라우저(Safari)는 조합을 끝내는 Enter를 `isComposing=false`·`keyCode 229`로 보내므로 함께 본다
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    switch (event.key) {
      case "ArrowDown":
        if (candidates.length === 0) return;
        event.preventDefault();
        setOpen(true);
        setActive((current) => (open ? Math.min(current + 1, candidates.length - 1) : Math.max(current, 0)));
        return;
      case "ArrowUp":
        if (!listed) return;
        event.preventDefault();
        setActive((current) => Math.max(current - 1, -1));
        return;
      case "Enter":
        // 폼을 저장하지 않는다(폼 submit은 저장 버튼만).
        // 고른 후보가 있으면 그 후보 → 후보가 있는데 안 골랐으면 첫 후보로 활성만(저장 없음, FE-04-24 A) → 검색 중이면 아무것도 안 함 → 그 밖(후보 없음·실패)은 글자 그대로
        event.preventDefault();
        if (listed && active >= 0 && candidates[active]) pick(candidates[active]);
        else if (hasCandidates) {
          setOpen(true);
          setActive(0);
        } else confirmText();
        return;
      case "Escape":
        // 목록이 열려 있을 때만 여기서 먹는다(모달의 Esc 닫기는 `AccountModal`이 열린 콤보박스를 보고 막는다)
        if (!listed) return;
        event.preventDefault();
        setOpen(false);
        setActive(-1);
        return;
      case "Tab":
        setOpen(false);
        setActive(-1);
        return;
      default:
        return;
    }
  };

  /** 상태 한 줄: 상한 → 찾는 중 → 실패 → 후보 없음 순서. 없으면 null(후보가 보일 때는 개수만 보조기기에 읽힌다) */
  const line = ((): { text: string; testId: string } | null => {
    if (full) return { text: ERROR_MEDICATION_LIMIT, testId: "medication-limit" };
    // 디바운스 대기 중에도 "찾는 중"으로 둔다: 이 동안 `그대로 추가`가 비활성인 이유가 보여야 한다(FE-04-24 A)
    if (awaiting) return { text: MEDICATION_SEARCHING, testId: "medication-searching" };
    if (status === "error") return { text: authExpired ? MEDICATION_SEARCH_AUTH_EXPIRED : MEDICATION_SEARCH_FAILED, testId: "medication-search-error" };
    if (status === "ready" && result !== null && candidates.length === 0) return { text: MEDICATION_NO_CANDIDATES, testId: "medication-no-candidates" };
    return null;
  })();

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex gap-2">
        <input
          ref={input}
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          aria-expanded={listed}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={listed && active >= 0 ? optionId(active) : undefined}
          aria-describedby={`${id}-hint`}
          maxLength={DRUG_QUERY_MAX_CHARS}
          disabled={full}
          value={query}
          onChange={(event) => {
            const next = event.target.value;
            setQuery(next);
            setActive(-1);
            setAuthExpired(false);
            if (!next.trim()) {
              setResult(null);
              setOpen(false);
              setStatus("idle");
            } else if (status === "error") setStatus("idle");
          }}
          onKeyDown={onKeyDown}
          onFocus={() => candidates.length > 0 && setOpen(true)}
          onBlur={(event) => {
            // 후보를 마우스로 누르는 동안은 초점이 입력에 남는다(`onMouseDown` preventDefault). 그 밖으로 나가면 목록을 닫는다
            if (event.relatedTarget instanceof Node && list.current?.contains(event.relatedTarget)) return;
            setOpen(false);
            setActive(-1);
          }}
          className={FIELD_CLASS}
        />
        {/* 검색 중에는 비활성(FE-04-24 A): 후보를 보기 전에 확인 안 된 약으로 저장되지 않게 한다 */}
        <button type="button" data-testid="medication-add" disabled={full || !q || awaiting} onClick={confirmText} className={`${SECONDARY_BUTTON} flex-none`}>
          {MEDICATION_ADD_LABEL}
        </button>
      </div>
      <p id={`${id}-hint`} className="m-0 text-xs text-mute">
        {MEDICATION_HINT} {MEDICATION_SEARCH_HINT}
      </p>
      {/* 후보 목록: 본문 흐름 안에 그려 모달 본문 스크롤과 함께 움직인다(겹치는 층을 만들지 않는다) */}
      <ul
        ref={list}
        id={listId}
        role="listbox"
        aria-label={medicationCandidatesLabel(candidates.length)}
        data-testid="medication-candidates"
        hidden={!listed}
        className="m-0 max-h-64 list-none overflow-y-auto rounded-xl border border-line-2 bg-bg p-1"
      >
        {candidates.map((candidate, index) => {
          const selected = index === active;
          const similar = candidate.match_type === DRUG_MATCH_SIMILAR;
          const detail = [MEDICATION_KIND_LABELS[candidate.matched_by], candidate.entp_name, candidate.prescription, similar ? MEDICATION_SIMILAR_TAG : null].filter((part): part is string => !!part);
          return (
            // 키보드는 입력 칸의 핸들러(↑↓·Enter)가 맡는다(combobox 패턴: 초점은 입력에 있고 활성 후보는 aria-activedescendant). 이 줄만 규칙을 끈다
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events
            <li
              key={`${candidate.matched_by}:${candidate.item_seq ?? ""}:${candidate.name}`}
              id={optionId(index)}
              role="option"
              aria-selected={selected}
              aria-label={[candidate.name, ...detail].join(", ")}
              tabIndex={-1}
              data-testid="medication-candidate"
              data-matched-by={candidate.matched_by}
              data-active={selected || undefined}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(candidate)}
              onMouseMove={() => !selected && setActive(index)}
              className={cn("flex min-h-11 cursor-pointer flex-col justify-center rounded-lg px-3 py-1.5 transition-colors hover:bg-bg-soft", selected && "bg-tint")}
            >
              <span className="text-sm font-bold [overflow-wrap:anywhere]">{candidate.name}</span>
              <span className="text-xs text-mute">{detail.join(" · ")}</span>
            </li>
          );
        })}
      </ul>
      {/* 상태 한 줄(보조기기가 바로 읽는다): 찾는 중·후보 없음·실패·상한 */}
      <p role="status" aria-live="polite" data-testid={line?.testId ?? "medication-status"} className={cn("m-0 text-xs leading-[17px]", status === "error" ? "font-semibold text-red-ink" : "text-ink-2", !line && "sr-only")}>
        {line?.text ?? (listed ? medicationCandidatesLabel(candidates.length) : "")}
      </p>
    </div>
  );
}
