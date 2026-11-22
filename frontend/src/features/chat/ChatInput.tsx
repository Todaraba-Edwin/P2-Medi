"use client";

import { useId, useState } from "react";
import { ArrowUpIcon } from "lucide-react";
import { HOVER_INNER_PRIMARY } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { INPUT_LABEL, INPUT_NOTICE, INPUT_PLACEHOLDER, SEND_LABEL } from "./copy";
import { PregnancyToggle } from "./PregnancyToggle";

/** 입력창 안 왼쪽의 임신 여부 선택(FE-11 §7.1). 주지 않으면(미리보기·시험) 선택을 그리지 않는다 */
export interface PregnancyControl {
  /** 임산부면 true, 일반인이면 false */
  value: boolean;
  onChange: (pregnant: boolean) => void;
  /** 선택 근처 안내 한 줄(동의 없음·게스트: 이 대화에만 적용, FE-11-14 A). 없으면 그리지 않는다 */
  hint?: string | null;
  /** 프로필 저장 실패 짧은 안내(대화 값은 유지, FE-11-13). 없으면 그리지 않는다 */
  error?: string | null;
}

export interface ChatInputProps {
  onSend: (question: string) => void;
  /** 입력을 막을 때만 쓴다. 답을 기다리는 중에도 새 질문을 보낼 수 있어야 하므로 기본은 false다 */
  disabled?: boolean;
  pregnancy?: PregnancyControl;
}

/**
 * 질문 입력창. 입력한 글자는 이 부품의 메모리에만 있고 어디에도 저장하지 않는다.
 * 입력창 바로 아래에 저장하지 않음·외부 AI 전송 고지 한 줄을 둔다(PRD-17-07 A, 게스트 포함). 고지는 `aria-describedby`로 입력창에 연결한다.
 * 입력창 안 왼쪽에 임신 여부 선택 "일반인 | 임산부"를 둔다(FE-11 §7.1 `Rdd-Toggle`, 393·1280 같은 모양). 값과 저장 여부는 조립하는 쪽(`AppShell`)이 정한다
 */
export function ChatInput({ onSend, disabled = false, pregnancy }: ChatInputProps) {
  const id = useId();
  const noticeId = `${id}-notice`;
  const pregnancyNoteId = `${id}-pregnancy-note`;
  const [value, setValue] = useState("");
  const canSend = !disabled && value.trim().length > 0;
  const pregnancyNote = pregnancy?.error ?? pregnancy?.hint ?? null;

  const submit = () => {
    if (!canSend) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <div className="flex flex-col gap-1">
      <form
        className="flex items-end gap-1.5 rounded-3xl border border-line-2 bg-bg py-1 pr-1 pl-2.5 focus-within:border-link"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {pregnancy && <PregnancyToggle value={pregnancy.value} onChange={pregnancy.onChange} describedBy={pregnancyNote ? pregnancyNoteId : undefined} />}
        <label htmlFor={id} className="sr-only">
          {INPUT_LABEL}
        </label>
        <textarea
          id={id}
          rows={1}
          value={value}
          disabled={disabled}
          placeholder={INPUT_PLACEHOLDER}
          autoComplete="off"
          aria-describedby={noticeId}
          className="max-h-32 min-h-11 min-w-0 flex-1 resize-none bg-transparent py-2.5 pl-1.5 text-base leading-6 outline-none placeholder:text-mute"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            // 한글 조합 중의 Enter는 보내지 않는다. Shift+Enter는 줄바꿈
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        {/* 터치 영역 44px(버튼 크기), 보이는 원은 36px */}
        <button type="submit" disabled={!canSend} aria-label={SEND_LABEL} className="group grid size-11 flex-none place-items-center">
          <span className={`grid size-9 place-items-center rounded-full bg-yellow text-on-yellow group-disabled:bg-line group-disabled:text-faint ${HOVER_INNER_PRIMARY}`}>
            <ArrowUpIcon className="size-5" aria-hidden="true" />
          </span>
        </button>
      </form>
      {/* 임신 여부 선택 근처 한 줄(FE-11-14 A 안내 또는 저장 실패 안내). 보조기기가 바로 읽는다. 마스코트 금지 영역 */}
      {pregnancyNote && (
        <NoMascotZone>
          <p
            id={pregnancyNoteId}
            role={pregnancy?.error ? "alert" : "status"}
            data-testid={pregnancy?.error ? "pregnancy-save-error" : "pregnancy-hint"}
            className={`m-0 px-4 text-xs leading-[17px] break-words ${pregnancy?.error ? "font-semibold text-red-ink" : "text-ink-2"}`}
          >
            {pregnancyNote}
          </p>
        </NoMascotZone>
      )}
      {/* 입력창 아래 고지(PRD-17-07 A): 작은 글씨, 체크·버튼 없음, 마스코트 금지 영역. 고정 안내·법적 고지는 입력창 위에 따로 있다 */}
      <NoMascotZone>
        <p id={noticeId} role="note" data-testid="input-notice" className="m-0 px-4 text-xs leading-[17px] break-words text-mute">
          {INPUT_NOTICE}
        </p>
      </NoMascotZone>
    </div>
  );
}
