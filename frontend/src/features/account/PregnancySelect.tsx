"use client";

import { useRef } from "react";
import { CheckIcon } from "lucide-react";
import type { PregnancyStatus } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { PREGNANCY_LABELS } from "./copy";

/** 보이는 순서(사용자 지시 2026-11-22): 예 | 아니오 | 모름. 값 체계는 백엔드 `PregnancyStatus` 그대로(기본은 `unknown`) */
export const PREGNANCY_SELECT_ORDER: readonly PregnancyStatus[] = ["pregnant", "not_pregnant", "unknown"];

export interface PregnancySelectProps {
  value: PregnancyStatus;
  onChange: (status: PregnancyStatus) => void;
  /** 묶음 이름을 주는 요소(폼의 `임신 여부` 라벨) */
  labelledBy: string;
  /** 비활성(건강 정보 동의 없음). 감싸는 fieldset이 비활성이면 버튼도 함께 비활성이 되지만 표시용으로 받는다 */
  disabled?: boolean;
}

/**
 * 프로필 폼의 임신 여부 선택 버튼(사용자 지시 2026-11-22, 작업 B): 라디오 대신 입력창의 "일반인 | 임산부" 토글(`features/chat/PregnancyToggle`)과
 * 같은 계열의 세그먼트 버튼이다. 고른 칸은 노랑 바탕(`--color-yellow`) + `--color-on-yellow` 굵게 + 체크 아이콘, 안 고른 칸은 크림(`--color-bg-soft`) + `--color-mute`.
 * 색만으로 구분하지 않는다(굵기·체크·`aria-checked`). 색은 토큰만 쓴다. 칸 높이는 44px(터치 대상)이다.
 * 접근성: `role="radiogroup"` 안의 `role="radio"` 셋, 로빙 탭(고른 칸만 Tab 순서), ←/→(↑/↓)로 옮기며 선택·초점이 따라간다.
 * 글자는 기존 `PREGNANCY_LABELS`(예·아니오·모름)만 쓴다(새 글자 없음). 값은 메모리에만 있다.
 */
export function PregnancySelect({ value, onChange, labelledBy, disabled = false }: PregnancySelectProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  /** 초점이 있는 칸에서 `delta`만큼 옮겨 고르고 초점을 준다(끝에서는 반대쪽으로 돈다) */
  const move = (from: number, delta: number) => {
    const next = (from + delta + PREGNANCY_SELECT_ORDER.length) % PREGNANCY_SELECT_ORDER.length;
    onChange(PREGNANCY_SELECT_ORDER[next]);
    buttons.current[next]?.focus();
  };
  const onKeyDown = (index: number) => (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(index, -1);
    }
  };

  return (
    <div role="radiogroup" aria-labelledby={labelledBy} data-testid="pregnancy-select" data-value={value} className="flex h-11 items-center">
      <div className="flex h-11 w-full max-w-md items-center gap-0.5 rounded-full border border-line-2 bg-bg-soft p-0.5">
        {PREGNANCY_SELECT_ORDER.map((status, index) => {
          const checked = status === value;
          return (
            <button
              key={status}
              ref={(el) => {
                buttons.current[index] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              disabled={disabled}
              data-testid={`pregnancy-${status}`}
              onClick={() => onChange(status)}
              onKeyDown={onKeyDown(index)}
              className={cn(
                "flex h-10 flex-1 items-center justify-center gap-1 rounded-full px-3 text-sm leading-none whitespace-nowrap transition-colors",
                "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink-2",
                "disabled:cursor-not-allowed disabled:opacity-60",
                checked ? "bg-yellow font-extrabold text-on-yellow shadow-sm" : "bg-bg-soft font-normal text-mute",
              )}
            >
              {checked && <CheckIcon className="size-4 flex-none" aria-hidden="true" />}
              {PREGNANCY_LABELS[status]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
