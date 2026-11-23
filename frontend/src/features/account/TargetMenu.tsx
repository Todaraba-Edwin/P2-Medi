"use client";

import { DropdownMenu } from "radix-ui";
import { CheckIcon, ChevronUpIcon, UserIcon } from "lucide-react";
import { HOVER_ROW } from "@/components/button";
import type { Profile } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { NOT_SELECTED, TARGET_LABEL, profileName } from "./copy";
import { useHoverMenu } from "./hover-menu";
import { ProfileAvatar } from "./ProfileAvatar";

/** `선택 안 함`의 라디오 값(프로필 id와 겹치지 않는 값) */
const NONE = "";

/** 메뉴 항목 모양(계정 메뉴와 같다): 44px 높이, 키보드 초점은 호버와 같은 바탕 */
export const MENU_ITEM_CLASS = "flex min-h-11 cursor-pointer items-center gap-2.5 rounded-[10px] px-2.5 text-sm font-semibold text-ink outline-none select-none data-[highlighted]:bg-tint";
export const MENU_CONTENT_CLASS = "z-50 flex w-[min(272px,calc(100vw-24px))] flex-col gap-0.5 rounded-2xl border border-line bg-bg p-1.5 shadow-lg outline-none";

export interface TargetChoiceProps {
  profiles: readonly Profile[];
  /** 고른 프로필. 고르지 않았으면 null */
  value: string | null;
  onChange: (profileId: string | null) => void;
}

/**
 * 대상 프로필("누가 먹나요") 고르기 항목: 메뉴 안의 라디오 묶음(`menuitemradio`). 입력창 프로필 칩과 계정 버튼 메뉴가 같은 부품을 쓴다.
 * 순서는 예전 본문 선택 줄과 같다: `선택 안 함`(프로필 없이 일반으로 묻는 길) → 본인 → 가족. 고른 항목은 체크 + 굵게(색만으로 구분하지 않는다)
 */
export function TargetChoiceItems({ profiles, value, onChange }: TargetChoiceProps) {
  return (
    <>
      <DropdownMenu.Label className="px-2.5 pt-2 pb-1 text-xs font-bold text-mute">{TARGET_LABEL}</DropdownMenu.Label>
      <DropdownMenu.RadioGroup value={value ?? NONE} onValueChange={(next) => onChange(next === NONE ? null : next)} data-testid="target-picker" aria-label={TARGET_LABEL}>
        {[null, ...profiles].map((profile) => {
          const key = profile?.profile_id ?? NONE;
          const checked = key === (value ?? NONE);
          return (
            <DropdownMenu.RadioItem key={key || "none"} value={key} data-testid="target-option" data-checked={checked} className={cn(MENU_ITEM_CLASS, !checked && "font-medium text-ink-2")}>
              {profile ? <ProfileAvatar color={profile.avatar_color} size={28} /> : <UserIcon className="mx-[5px] size-[18px] flex-none" aria-hidden="true" />}
              <span className="min-w-0 flex-1 truncate">{profile ? profileName(profile) : NOT_SELECTED}</span>
              <DropdownMenu.ItemIndicator>
                <CheckIcon className="size-4" aria-hidden="true" />
              </DropdownMenu.ItemIndicator>
            </DropdownMenu.RadioItem>
          );
        })}
      </DropdownMenu.RadioGroup>
    </>
  );
}

/**
 * 입력창 안의 대상 프로필 칩(2026-11-23 사용자 요구 "본문 INPUT에 (일반인|임산부) 누가 먹는지(이름)"): `[병아리 아바타] 이름 ⌃`.
 * 본문의 "누가 먹나요" 선택 줄을 대신한다. 호버·포커스(Enter·Space·↓)·탭으로 **위로** 프로필 목록이 열리고, 고르면 계정 버튼 표시도 같이 바뀐다
 * (값은 계정 스토어의 `targetProfileId` 하나다). 로그인하고 프로필이 있을 때만 조립하는 쪽이 그린다(게스트는 입력창이 예전 모양).
 * 접근 가능한 이름은 "누가 먹나요 + 이름"(`aria-label`, 보이는 글자는 이름뿐)이고 `aria-haspopup`·`aria-expanded`는 Radix가 단다
 */
export function TargetChip({ profiles, value, onChange, container = null }: TargetChoiceProps & { container?: HTMLElement | null }) {
  const { open, onOpenChange, attachContent, triggerProps, contentProps } = useHoverMenu();
  const target = profiles.find((profile) => profile.profile_id === value) ?? null;
  const shownName = target ? profileName(target) : NOT_SELECTED;
  return (
    <DropdownMenu.Root modal={false} open={open} onOpenChange={onOpenChange}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          data-testid="target-chip"
          data-target={target ? "profile" : "none"}
          // 접근 가능한 이름 = 묶음 이름 + 보이는 이름(보이는 글자가 이름 안에 그대로 있다, WCAG 2.5.3)
          aria-label={`${TARGET_LABEL} ${shownName}`}
          {...triggerProps}
          // 누르는 영역 44px(버튼), 보이는 칩은 32px(안쪽)
          className="group flex h-11 max-w-[11rem] min-w-0 flex-none items-center rounded-full focus-visible:outline-none"
        >
          <span
            className={cn(
              "flex h-8 min-w-0 items-center gap-1.5 rounded-full border border-line-2 bg-bg-soft py-0 pr-2 pl-1 text-xs font-bold text-ink",
              "group-focus-visible:outline-3 group-focus-visible:outline-offset-2 group-focus-visible:outline-ink-2",
              HOVER_ROW,
            )}
          >
            {target ? <ProfileAvatar color={target.avatar_color} size={24} /> : <UserIcon className="mx-1 size-4 flex-none text-ink-2" aria-hidden="true" />}
            <span className="min-w-0 truncate">{shownName}</span>
            <ChevronUpIcon className="size-3.5 flex-none text-mute" aria-hidden="true" />
          </span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal container={container}>
        <DropdownMenu.Content
          ref={attachContent}
          data-testid="target-menu"
          side="top"
          align="start"
          sideOffset={8}
          collisionPadding={8}
          loop
          {...contentProps}
          className={MENU_CONTENT_CLASS}
        >
          <TargetChoiceItems profiles={profiles} value={value} onChange={onChange} />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
