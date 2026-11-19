"use client";

import { useId } from "react";
import type { Profile } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { NOT_SELECTED, TARGET_LABEL, profileName } from "./copy";

export interface TargetPickerProps {
  profiles: readonly Profile[];
  /** 고른 프로필. 고르지 않았으면 null */
  value: string | null;
  onChange: (profileId: string | null) => void;
}

/**
 * 질문 입력 위의 대상 선택 "누가 먹나요"(S10 4단계, 모달이 아니라 화면 안 선택). 로그인하고 프로필이 있을 때만 조립이 그린다(게스트는 숨김).
 * 고른 프로필의 연령대·임신 여부만 요청 `context`로 간다. 고른 값은 메모리에만 있다.
 */
export function TargetPicker({ profiles, value, onChange }: TargetPickerProps) {
  const id = useId();
  const options: { key: string; profileId: string | null; label: string }[] = [
    { key: "none", profileId: null, label: NOT_SELECTED },
    ...profiles.map((profile) => ({ key: profile.profile_id, profileId: profile.profile_id, label: profileName(profile) })),
  ];
  return (
    <div role="radiogroup" aria-labelledby={`${id}-label`} data-testid="target-picker" className="flex min-w-0 flex-wrap items-center gap-1.5 px-1">
      <span id={`${id}-label`} className="mr-0.5 text-xs font-bold text-ink-2">
        {TARGET_LABEL}
      </span>
      {options.map((option) => {
        const checked = option.profileId === value;
        return (
          <label
            key={option.key}
            data-testid="target-option"
            data-checked={checked}
            className={cn(
              "flex min-h-11 max-w-full cursor-pointer items-center rounded-full border px-3 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-link",
              checked ? "border-ink bg-tint font-bold" : "border-line bg-bg",
            )}
          >
            <input type="radio" name={id} checked={checked} onChange={() => onChange(option.profileId)} className="sr-only" />
            <span className="max-w-40 truncate">{option.label}</span>
          </label>
        );
      })}
    </div>
  );
}
