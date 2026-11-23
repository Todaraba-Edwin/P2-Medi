"use client";

import { useId, useState } from "react";
import { ArrowUpIcon, CameraIcon } from "lucide-react";
import { HOVER_INNER_PRIMARY, HOVER_INNER_TEXT } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { PHOTO_ENTRY_LABEL } from "@/features/photo/copy";
import { cn } from "@/lib/utils";
import { INPUT_COMBINED_NOTICE, INPUT_LABEL, INPUT_PLACEHOLDER, SEND_LABEL } from "./copy";
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
  /** 사진 입력 입구(FE-05, PJ2-PRD.md 15.4 "사진 올리기" 행 "버튼이 입력창 옆, 첫 화면"). 주지 않으면(미리보기·시험) 버튼을 그리지 않는다 */
  onPhoto?: () => void;
  /**
   * 대상 프로필 칩(2026-11-23, `features/account` `TargetChip`). 주면 입력창 안 첫 줄이 `(일반인|임산부) · [병아리] 이름`이 되고 질문 칸은 그 아래 줄이다.
   * 주지 않으면(게스트·프로필 없음·미리보기) 입력창은 예전 한 줄 모양이다
   */
  target?: React.ReactNode;
}

/**
 * 질문 입력창. 입력한 글자는 이 부품의 메모리에만 있고 어디에도 저장하지 않는다.
 * 입력창 바로 아래에 통합 고지 한 단락(FE-17 U-02: 진단·처방 아님·안전 아님·DUR 대체 아님·저장 안 함·외부 AI 전송, 게스트 포함)을 두고 `aria-describedby`로 입력창에 연결한다.
 * 입력창 안 왼쪽에 임신 여부 선택 "일반인 | 임산부"를 둔다(FE-11 §7.1 `Rdd-Toggle`, 393·1280 같은 모양). 값과 저장 여부는 조립하는 쪽(`AppShell`)이 정한다
 */
export function ChatInput({ onSend, disabled = false, pregnancy, onPhoto, target }: ChatInputProps) {
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
        className={cn("flex gap-1.5 rounded-3xl border border-line-2 bg-bg py-1 pr-1 pl-2.5 focus-within:border-link", target ? "flex-wrap items-end" : "items-end")}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {/* 대상 프로필이 있으면 첫 줄: 임신 여부 토글 · 프로필 칩(토글이 빠지는 남성 대상도 줄 높이 44px는 그대로) */}
        {target ? (
          <div data-testid="input-target-row" className="flex h-11 w-full min-w-0 items-center gap-1.5">
            {pregnancy && <PregnancyToggle value={pregnancy.value} onChange={pregnancy.onChange} describedBy={pregnancyNote ? pregnancyNoteId : undefined} />}
            {pregnancy && (
              <span aria-hidden="true" className="flex-none text-xs text-mute">
                ·
              </span>
            )}
            {target}
          </div>
        ) : (
          pregnancy && <PregnancyToggle value={pregnancy.value} onChange={pregnancy.onChange} describedBy={pregnancyNote ? pregnancyNoteId : undefined} />
        )}
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
        {/* 사진 입력 입구(FE-05 사진 부분, 〔D5〕A: 입구는 여기 하나). 터치 영역 44px, 보이는 원은 36px. 누르면 조립하는 쪽이 사진 모달을 연다 */}
        {onPhoto && (
          <button type="button" data-testid="photo-entry" disabled={disabled} aria-label={PHOTO_ENTRY_LABEL} onClick={onPhoto} className="group grid size-11 flex-none place-items-center">
            <span className={`grid size-9 place-items-center rounded-full text-ink-2 group-disabled:text-faint ${HOVER_INNER_TEXT}`}>
              <CameraIcon className="size-5" aria-hidden="true" />
            </span>
          </button>
        )}
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
      {/* 입력창 아래 통합 고지(FE-17 U-02): 법적 고지 + 저장 안 함·외부 AI 전송 고지를 한 단락으로(상수 `INPUT_COMBINED_NOTICE`, 게스트 포함).
          접히지 않는 영역, 작은 글씨, 체크·버튼 없음, 마스코트 금지 영역. 입력창의 설명(`aria-describedby`)이다 */}
      <NoMascotZone>
        <p id={noticeId} role="note" data-testid="input-combined-notice" className="m-0 px-4 text-xs leading-[17px] break-words text-mute">
          {INPUT_COMBINED_NOTICE}
        </p>
      </NoMascotZone>
    </div>
  );
}
