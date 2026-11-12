"use client";

import { useId, useState } from "react";
import { ArrowUpIcon } from "lucide-react";
import { INPUT_LABEL, INPUT_PLACEHOLDER, SEND_LABEL } from "./copy";

export interface ChatInputProps {
  onSend: (question: string) => void;
  /** 입력을 막을 때만 쓴다. 답을 기다리는 중에도 새 질문을 보낼 수 있어야 하므로 기본은 false다 */
  disabled?: boolean;
}

/** 질문 입력창. 입력한 글자는 이 부품의 메모리에만 있고 어디에도 저장하지 않는다. */
export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const id = useId();
  const [value, setValue] = useState("");
  const canSend = !disabled && value.trim().length > 0;

  const submit = () => {
    if (!canSend) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <form
      className="flex items-end gap-1.5 rounded-3xl border border-line-2 bg-bg py-1 pr-1 pl-4 focus-within:border-link"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
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
        className="max-h-32 min-h-11 min-w-0 flex-1 resize-none bg-transparent py-2.5 text-base leading-6 outline-none placeholder:text-mute"
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
        <span className="grid size-9 place-items-center rounded-full bg-yellow text-ink group-disabled:bg-line group-disabled:text-faint">
          <ArrowUpIcon className="size-5" aria-hidden="true" />
        </span>
      </button>
    </form>
  );
}
