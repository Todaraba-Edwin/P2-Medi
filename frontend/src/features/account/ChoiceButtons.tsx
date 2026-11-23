"use client";

import { useRef } from "react";
import { CheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChoiceOption<T extends string> {
  value: T;
  label: string;
  /** 고를 수 없는 칸(본인 프로필의 관계 고정 등) */
  disabled?: boolean;
}

export interface ChoiceButtonsProps<T extends string> {
  options: readonly ChoiceOption<T>[];
  /** 고른 값. 아직 고르지 않았으면 "" */
  value: T | "";
  onChange: (value: T) => void;
  /** 묶음 이름을 주는 요소(폼의 칸 이름) */
  labelledBy: string;
  /** `segment`: 한 줄 세그먼트(관계 5칸·성별 2칸). `grid`: 3열 칩 그리드, 줄바꿈(연령대 11칸) */
  layout: "segment" | "grid";
  /** 필수 칸이면 true(`aria-required`) */
  required?: boolean;
  /** 이유 한 줄 등 묶음의 설명 */
  describedBy?: string;
  "data-testid"?: string;
}

/**
 * 프로필 폼의 선택 버튼 묶음(FE-17 U-07, 2026-11-23 사용자 요구 "select 박스 대신 버튼 선택방식으로 풀어서"): `<select>`를 대신한다.
 * 임신 여부 선택(`PregnancySelect`)과 같은 계열이다: `role="radiogroup"` 안의 `role="radio"` 버튼, 로빙 탭(고른 칸만 Tab 순서, 아직 안 골랐으면 첫 칸),
 * ←/→(↑/↓)로 옮기며 고르고 초점이 따라간다(끝에서는 반대쪽으로 돌고 비활성 칸은 건너뛴다).
 * 고른 칸은 노랑 바탕 + 굵게 + 체크 아이콘(색만으로 구분하지 않는다), 칸 높이 44px(터치 대상). 색은 토큰만 쓴다. 글자는 부르는 쪽의 기존 상수다
 */
export function ChoiceButtons<T extends string>({ options, value, onChange, labelledBy, layout, required = false, describedBy, "data-testid": testId }: ChoiceButtonsProps<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = options.map((option, index) => (option.disabled ? -1 : index)).filter((index) => index >= 0);
  const checkedIndex = options.findIndex((option) => option.value === value);
  // Tab으로 들어올 칸: 고른 칸, 없으면 고를 수 있는 첫 칸
  const tabStop = checkedIndex >= 0 ? checkedIndex : (enabled[0] ?? -1);

  const move = (from: number, delta: number) => {
    if (enabled.length === 0) return;
    const at = enabled.indexOf(from);
    const nextIndex = enabled[(at < 0 ? 0 : at + delta + enabled.length) % enabled.length];
    onChange(options[nextIndex].value);
    buttons.current[nextIndex]?.focus();
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
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      aria-required={required || undefined}
      aria-describedby={describedBy}
      data-testid={testId}
      data-value={value}
      className={cn(layout === "segment" ? "flex min-h-11 w-full items-stretch gap-0.5 rounded-full border border-line-2 bg-bg-soft p-0.5" : "grid grid-cols-3 gap-2")}
    >
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              buttons.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === tabStop ? 0 : -1}
            disabled={option.disabled}
            data-value={option.value}
            onClick={() => onChange(option.value)}
            onKeyDown={onKeyDown(index)}
            className={cn(
              "flex min-h-11 min-w-0 items-center justify-center gap-1 px-1.5 text-sm leading-tight transition-colors [word-break:keep-all]",
              "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink-2",
              "disabled:cursor-not-allowed disabled:opacity-50",
              layout === "segment" ? "flex-1 rounded-full" : "min-h-11 rounded-xl border text-center",
              checked
                ? cn("font-extrabold text-on-yellow", layout === "segment" ? "bg-yellow shadow-sm" : "border-link bg-yellow")
                : cn("font-normal text-ink-2", layout === "segment" ? "bg-bg-soft" : "border-line-2 bg-bg"),
            )}
          >
            {checked && <CheckIcon className="size-4 flex-none" aria-hidden="true" />}
            <span className="min-w-0">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
