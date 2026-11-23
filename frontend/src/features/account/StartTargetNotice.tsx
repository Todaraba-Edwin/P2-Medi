"use client";

import type { Profile } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { GUEST_USE_LABEL, START_TARGET_GUEST_HEADING, START_TARGET_GUEST_LEAD, START_TARGET_PROFILE_LEAD, profileName, startTargetProfileHeading } from "./copy";

export interface StartTargetNoticeProps {
  profiles: readonly Profile[];
  /** 지금 대상(계정 스토어 `targetProfileId`). null = `게스트로 이용` */
  value: string | null;
  /** 안내의 `게스트로 이용`을 눌렀다: 대상(과 서버 기본 대상)을 `게스트로 이용`으로 바꾼다 */
  onGuest: () => void;
}

/**
 * 시작 화면 기본 대상 안내(FE-17 U-08, 2026-11-23 "body 중앙 이미지 하단에 해당 내용을 명시하고, 게스트로 이용하는 부분에 대한 안내"):
 * 시작 화면 병아리 이미지(`HomeHero`) 아래에 지금 질문이 어느 프로필 기준인지 밝히고, 프로필이면 `게스트로 이용`을 둔다.
 * - 모양(FE-17 U-11): 카드·아바타·큰 제목·둥근 버튼 없이 `<p>` 한 단락의 단순한 문장이다. 글자 디자인은 입력창 아래 통합 고지(`input-combined-notice`)와 같다
 *   (12px·줄 간격 17px·`text-mute`). `게스트로 이용`은 같은 글자 크기의 밑줄 링크 모양으로 문장 끝에 이어 붙는다.
 *   동작이 이동이 아니라 대상 변경이므로 요소는 `<button>`이다(링크 모양의 버튼). 문장 안의 글자라 보이는 높이는 줄 높이이고,
 *   누르는 영역은 투명 `before:`로 위아래를 넓혀 44px다(입력창 토글과 같은 방식)
 * - 문구는 승인된 상수 그대로다. 머리 문장 상수에는 마침표가 없어 문장을 잇는 마침표 하나만 붙인다(새 낱말 없음)
 * - 안내를 무시하고 질문하면 지금 대상 그대로 간다(요청 계약은 바뀌지 않는다). 누르면 대상이 `게스트로 이용`으로 바뀌고 서버 기본 대상도 바뀐다
 * - 조립하는 쪽(`AppShell`)이 로그인 + 프로필이 있고 대화가 시작되기 전에만 그린다(게스트·프로필 없음·대화 중에는 없다)
 * - 안전을 보증하는 말은 두지 않는다. 바뀐 문장은 보조기기가 읽는다(`aria-live="polite"`)
 */
export function StartTargetNotice({ profiles, value, onGuest }: StartTargetNoticeProps) {
  const target = profiles.find((profile) => profile.profile_id === value) ?? null;
  return (
    <p data-testid="start-target" data-target={target ? "profile" : "guest"} className="m-0 mx-auto w-full max-w-[400px] px-4 text-center text-xs leading-[17px] break-words text-mute [word-break:keep-all]">
      <span aria-live="polite">
        <span data-testid="start-target-heading">{target ? startTargetProfileHeading(profileName(target)) : START_TARGET_GUEST_HEADING}</span>.{" "}
        <span data-testid="start-target-lead">{target ? START_TARGET_PROFILE_LEAD : START_TARGET_GUEST_LEAD}</span>
      </span>
      {target && (
        <>
          {" "}
          <button
            type="button"
            data-testid="start-target-guest"
            onClick={onGuest}
            className={cn(
              "relative inline cursor-pointer rounded-sm p-0 align-baseline text-xs leading-[17px] whitespace-nowrap text-link underline underline-offset-2",
              "before:absolute before:-inset-x-1 before:-inset-y-3.5 before:content-['']",
              "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink-2",
            )}
          >
            {GUEST_USE_LABEL}
          </button>
        </>
      )}
    </p>
  );
}
