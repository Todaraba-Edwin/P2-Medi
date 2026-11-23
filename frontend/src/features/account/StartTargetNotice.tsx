"use client";

import { useRef } from "react";
import { DropdownMenu } from "radix-ui";
import type { Profile } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import {
  GUEST_USE_LABEL,
  START_TARGET_CHANGE_LABEL,
  START_TARGET_GUEST_HEADING,
  START_TARGET_GUEST_LEAD,
  START_TARGET_PROFILE_LEAD,
  START_TARGET_PROFILE_SWITCH,
  profileName,
  startTargetProfileHeading,
} from "./copy";
import { useHoverMenu } from "./hover-menu";
import { MENU_CONTENT_CLASS, TargetChoiceItems } from "./TargetMenu";

export interface StartTargetNoticeProps {
  profiles: readonly Profile[];
  /** 지금 대상(계정 스토어 `targetProfileId`). null = `게스트로 이용` */
  value: string | null;
  /** 대상을 바꿨다(안내의 `게스트로 이용` 링크 = null, `변경` 목록에서 고른 값). 대상과 서버 기본 대상을 바꾸는 기존 경로로 보낸다 */
  onChange: (profileId: string | null) => void;
  /** 바꾼 뒤 초점을 옮길 곳(질문 칸). 목록이 닫히며 Radix가 버튼으로 초점을 돌리기 전에 가로챈다 */
  onSettled?: () => void;
  /** `변경` 목록을 그릴 자리(119 배너 아래 영역) */
  container?: HTMLElement | null;
}

/** 문장 안 밑줄 링크 모양의 버튼(U-11). 보이는 높이는 줄 높이, 누르는 영역은 투명 `before:`로 위아래를 넓혀 44px 이상 */
const LINK_CLASS = cn(
  "relative inline cursor-pointer rounded-sm p-0 align-baseline text-xs leading-[17px] whitespace-nowrap text-link underline underline-offset-2",
  "before:absolute before:-inset-y-3.5 before:content-['']",
  "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-ink-2",
);

/**
 * 시작 화면 기본 대상 안내(FE-17 U-08, 2026-11-23 "body 중앙 이미지 하단에 해당 내용을 명시하고, 게스트로 이용하는 부분에 대한 안내"):
 * 시작 화면 병아리 이미지(`HomeHero`) 아래에 지금 질문이 어느 프로필 기준인지 밝힌다.
 * - 모양(FE-17 U-11): 카드·아바타·큰 제목·둥근 버튼 없이 `<p>` 한 단락의 단순한 문장이다. 글자 디자인은 입력창 아래 통합 고지(`input-combined-notice`)와 같다
 *   (12px·줄 간격 17px·`text-mute`). 링크는 같은 글자 크기의 밑줄 링크 모양이고, 동작이 이동이 아니라 대상 변경이므로 요소는 `<button>`이다
 * - 프로필 상태(FE-17 U-23): "{이름} 프로필로 확인해요. 이 프로필의 연령대·임신 여부가 답변에 쓰여요. 프로필 없이 질문을 이어가시려면 [게스트로 이용]으로 프로필을 변경해주세요."
 *   문장 **중간**의 `게스트로 이용`을 누르면 대상이 게스트로 바뀌고 서버 기본 대상도 저장된다(기존 동작)
 * - 게스트 상태(FE-17 U-22): "게스트로 이용 중이에요. 저장한 프로필 값 없이 질문해요. [변경]". `변경`은 입력창 프로필 칩과 **같은 프로필 선택 목록**을 연다
 *   (Enter·Space·누름으로 열고 첫 항목에 초점, ↑↓ 이동, Esc·바깥 누름으로 닫히면 초점은 `변경`으로). 고르면 대상과 서버 기본 대상이 바뀐다(U-08의 "게스트 안내에는 버튼 없음"을 대체)
 * - 문구는 사용자 지정 상수 그대로다. 머리 문장 상수에는 마침표가 없어 문장을 잇는 마침표 하나만 붙인다(새 낱말 없음)
 * - 조립하는 쪽(`AppShell`)이 로그인 + 프로필이 있고 대화가 시작되기 전에만 그린다(비로그인·프로필 없음·대화 중에는 없다)
 * - 안전을 보증하는 말은 두지 않는다. 바뀐 문장은 보조기기가 읽는다(`aria-live="polite"`). 프로필 이름은 화면에만 쓴다
 */
export function StartTargetNotice({ profiles, value, onChange, onSettled, container = null }: StartTargetNoticeProps) {
  const target = profiles.find((profile) => profile.profile_id === value) ?? null;
  const [switchBefore, switchAfter] = START_TARGET_PROFILE_SWITCH.split("{link}");
  return (
    <p data-testid="start-target" data-target={target ? "profile" : "guest"} className="m-0 mx-auto w-full max-w-[400px] px-4 text-center text-xs leading-[17px] break-words text-mute [word-break:keep-all]">
      <span aria-live="polite">
        <span data-testid="start-target-heading">{target ? startTargetProfileHeading(profileName(target)) : START_TARGET_GUEST_HEADING}</span>.{" "}
        <span data-testid="start-target-lead">{target ? START_TARGET_PROFILE_LEAD : START_TARGET_GUEST_LEAD}</span>
      </span>
      {target ? (
        <>
          {" "}
          <span data-testid="start-target-switch">
            {switchBefore}
            <button
              type="button"
              data-testid="start-target-guest"
              onClick={() => {
                onChange(null);
                onSettled?.();
              }}
              className={cn(LINK_CLASS, "before:-inset-x-1")}
            >
              {GUEST_USE_LABEL}
            </button>
            {switchAfter}
          </span>
        </>
      ) : (
        <>
          {" "}
          <ChangeMenu profiles={profiles} value={value} onChange={onChange} onSettled={onSettled} container={container} />
        </>
      )}
    </p>
  );
}

/** 게스트 상태 안내 끝의 `변경`: 입력창 칩과 같은 프로필 선택 목록(`TargetChoiceItems`)을 아래로 연다. 누름·키보드로만 연다(호버 열림 없음) */
function ChangeMenu({ profiles, value, onChange, onSettled, container }: Required<Pick<StartTargetNoticeProps, "profiles" | "value" | "onChange">> & Pick<StartTargetNoticeProps, "onSettled" | "container">) {
  const { open, onOpenChange, attachContent, contentProps } = useHoverMenu();
  // 목록에서 대상을 골라 닫히는 중인가: 그때는 초점을 `변경`(고른 뒤에는 사라진다) 대신 질문 칸으로 보낸다
  const picked = useRef(false);
  return (
    <DropdownMenu.Root modal={false} open={open} onOpenChange={onOpenChange}>
      <DropdownMenu.Trigger asChild>
        {/* 글자가 2자라 가로 누르는 영역도 `before:`로 넓혀 44px 이상(세로는 링크 공통) */}
        <button type="button" data-testid="start-target-change" className={cn(LINK_CLASS, "before:-inset-x-3.5")}>
          {START_TARGET_CHANGE_LABEL}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal container={container}>
        <DropdownMenu.Content
          ref={attachContent}
          data-testid="start-target-menu"
          side="bottom"
          align="center"
          sideOffset={8}
          collisionPadding={8}
          loop
          {...contentProps}
          onCloseAutoFocus={(event) => {
            if (!picked.current) return contentProps.onCloseAutoFocus(event);
            picked.current = false;
            if (!onSettled) return;
            event.preventDefault();
            onSettled();
          }}
          className={MENU_CONTENT_CLASS}
        >
          <TargetChoiceItems
            profiles={profiles}
            value={value}
            onChange={(next) => {
              picked.current = true;
              onChange(next);
            }}
          />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
