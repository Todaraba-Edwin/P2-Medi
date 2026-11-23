"use client";

import { useId } from "react";
import { SECONDARY_BUTTON } from "@/components/button";
import type { Profile } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { GUEST_USE_LABEL, START_TARGET_GUEST_HEADING, START_TARGET_GUEST_LEAD, START_TARGET_PROFILE_LEAD, profileName, startTargetProfileHeading } from "./copy";
import { ProfileAvatar } from "./ProfileAvatar";

export interface StartTargetNoticeProps {
  profiles: readonly Profile[];
  /** 지금 대상(계정 스토어 `targetProfileId`). null = `게스트로 이용` */
  value: string | null;
  /** 안내의 `게스트로 이용`을 눌렀다: 대상(과 서버 기본 대상)을 `게스트로 이용`으로 바꾼다 */
  onGuest: () => void;
}

/**
 * 시작 화면 기본 대상 안내(FE-17 U-08, 2026-11-23 "body 중앙 이미지 하단에 해당 내용을 명시하고, 게스트로 이용하는 부분에 대한 안내"):
 * 시작 화면 병아리 이미지(`HomeHero`) 아래에 지금 질문이 어느 프로필 기준인지(병아리 아바타 + 이름) 밝히고, 프로필이면 `게스트로 이용` 버튼을 둔다.
 * - 안내를 무시하고 질문하면 지금 대상 그대로 간다(요청 계약은 바뀌지 않는다). 버튼을 누르면 대상이 `게스트로 이용`으로 바뀌고 서버 기본 대상도 바뀐다
 * - 조립하는 쪽(`AppShell`)이 로그인 + 프로필이 있고 대화가 시작되기 전에만 그린다(게스트·프로필 없음·대화 중에는 없다)
 * - 아바타는 보조 자리(시작 화면)의 장식이다. 응급·금기 결과·고정 문구 영역이 아니다. 안전을 보증하는 말은 두지 않는다
 * - 바뀐 머리 줄은 보조기기가 읽는다(`aria-live="polite"`)
 */
export function StartTargetNotice({ profiles, value, onGuest }: StartTargetNoticeProps) {
  const headingId = useId();
  const target = profiles.find((profile) => profile.profile_id === value) ?? null;
  return (
    <section
      aria-labelledby={headingId}
      data-testid="start-target"
      data-target={target ? "profile" : "guest"}
      className="mx-auto flex w-full max-w-[400px] flex-col items-center gap-2 rounded-2xl border border-line bg-bg-soft px-4 py-3 text-center"
    >
      <div aria-live="polite" className="flex w-full flex-col items-center gap-1">
        <p id={headingId} data-testid="start-target-heading" className="m-0 flex max-w-full items-center gap-2 text-sm font-bold text-ink">
          <ProfileAvatar color={target?.avatar_color ?? null} size={28} />
          <span className="min-w-0 break-words [word-break:keep-all]">{target ? startTargetProfileHeading(profileName(target)) : START_TARGET_GUEST_HEADING}</span>
        </p>
        <p data-testid="start-target-lead" className="m-0 text-xs leading-[17px] break-words text-ink-2 [word-break:keep-all]">
          {target ? START_TARGET_PROFILE_LEAD : START_TARGET_GUEST_LEAD}
        </p>
      </div>
      {target && (
        <button type="button" data-testid="start-target-guest" onClick={onGuest} className={cn(SECONDARY_BUTTON, "px-4")}>
          {GUEST_USE_LABEL}
        </button>
      )}
    </section>
  );
}
