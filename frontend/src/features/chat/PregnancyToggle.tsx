"use client";

import { useRef } from "react";
import { cn } from "@/lib/utils";
import { PREGNANCY_OPTION_GENERAL, PREGNANCY_OPTION_PREGNANT, PREGNANCY_TOGGLE_LABEL } from "./copy";

export interface PregnancyToggleProps {
  /** 임산부면 true, 일반인이면 false(기본값은 조립하는 쪽이 정한다: 게스트·프로필 없음은 일반인) */
  value: boolean;
  onChange: (pregnant: boolean) => void;
  /** 선택 근처 안내·오류 줄의 id(보조기기가 묶음과 함께 읽는다) */
  describedBy?: string;
}

const OPTIONS: readonly { pregnant: boolean; label: string; testId: string }[] = [
  { pregnant: false, label: PREGNANCY_OPTION_GENERAL, testId: "pregnancy-general" },
  { pregnant: true, label: PREGNANCY_OPTION_PREGNANT, testId: "pregnancy-pregnant" },
];

/**
 * 임신 여부 좌우 토글 "일반인 | 임산부"(FE-11 §7.1 최종 디자인 `Rdd-Toggle`, 2026-11-20). 질문 입력창 안 왼쪽에 둔다.
 * - 두 칸이 늘 함께 보여 "임산부" 선택이 있다는 것을 놓치지 않는다(select가 아니다)
 * - 고른 칸: 노랑 바탕(`--color-yellow` #FFCC00) + 검정 굵게(800) + 그림자. 안 고른 칸: 크림(`--color-bg-soft` #FFF8E1) + `--color-mute` #6B5F3F 보통.
 *   색만으로 구분하지 않는다(굵기·`aria-checked`). 색은 토큰만 쓴다
 * - 고른 칸 글자는 `--color-on-yellow`(노랑 바탕 전용, FE-12): 다크에서 `--color-ink`는 밝은 크림이라 노랑 위에 올리면 안 보인다(1.29:1, 2026-11-22 재현)
 * - 칸 높이 28px, 누르는 영역은 위아래로 넓혀 44px(`before:` 투명 히트 영역)
 * - 접근성: `role="radiogroup"`(이름 "임신 여부") 안의 `role="radio"` 둘, ←/→(↑/↓)로 이동·선택, 초점 링 3px(`--color-ink-2` #3D3524)
 * - 값은 메모리에만 있고 저장 여부(프로필 연동)는 조립하는 쪽이 정한다(FE-11-13·14)
 */
export function PregnancyToggle({ value, onChange, describedBy }: PregnancyToggleProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  const move = (toPregnant: boolean) => {
    onChange(toPregnant);
    buttons.current[toPregnant ? 1 : 0]?.focus();
  };
  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(true);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(false);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={PREGNANCY_TOGGLE_LABEL}
      aria-describedby={describedBy}
      data-testid="pregnancy-toggle"
      data-pregnant={value}
      className="flex h-11 flex-none items-center"
    >
      <div className="flex h-7 items-center gap-0.5 rounded-full border border-line-2 bg-bg-soft p-0.5">
        {OPTIONS.map((option, index) => {
          const checked = option.pregnant === value;
          return (
            <button
              key={option.testId}
              ref={(el) => {
                buttons.current[index] = el;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              data-testid={option.testId}
              onClick={() => onChange(option.pregnant)}
              onKeyDown={onKeyDown}
              className={cn(
                // 보이는 칸 24px(틀 28px - 안쪽 여백), 누르는 영역은 `before:`로 위아래 10px씩 넓혀 44px
                "relative flex h-6 items-center rounded-full px-2.5 text-xs leading-none whitespace-nowrap transition-colors",
                "before:absolute before:inset-x-0 before:-inset-y-2.5 before:content-['']",
                "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink-2",
                checked ? "bg-yellow font-extrabold text-on-yellow shadow-sm" : "bg-bg-soft font-normal text-mute",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
