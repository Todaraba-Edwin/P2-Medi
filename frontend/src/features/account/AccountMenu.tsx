"use client";

import { useState } from "react";
import { DropdownMenu } from "radix-ui";
import { CheckIcon, ChevronUpIcon, LogOutIcon, MonitorIcon, MoonIcon, ScrollTextIcon, SunIcon, UserIcon, type LucideIcon } from "lucide-react";
import { HOVER_ROW } from "@/components/button";
import type { Profile } from "@/lib/api/account";
import { THEME_MODES, readThemeMode, saveThemeMode, type ThemeMode } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { SCREEN_MODE_LABEL, SYSTEM_MODE_HINT, THEME_LABELS } from "@/features/settings/copy";
import { ACCOUNT_LABEL, ACCOUNT_SIGNED_IN, GUEST_USE_LABEL, LEGAL_MENU_LABEL, LOGIN_ENTRY_LABEL, LOGOUT_LABEL, MANAGE_PROFILES_LABEL, profileName } from "./copy";
import { useHoverMenu } from "./hover-menu";
import { ProfileAvatar } from "./ProfileAvatar";
import { MENU_CONTENT_CLASS, MENU_ITEM_CLASS, TargetChoiceItems } from "./TargetMenu";

const THEME_ICONS: Readonly<Record<ThemeMode, LucideIcon>> = { light: SunIcon, dark: MoonIcon, system: MonitorIcon };

/** 대상 프로필 고르기(회원 + 프로필이 있을 때만 준다). 값은 계정 스토어의 `targetProfileId` 하나이고 입력창 칩과 같이 바뀐다 */
export interface AccountTargetChoice {
  profiles: readonly Profile[];
  value: string | null;
  onChange: (profileId: string | null) => void;
}

export interface AccountMenuProps {
  /** 로그인했는가. 서버(`GET /me`)는 이름·이메일을 주지 않으므로 식별 표시는 고른 프로필(병아리 + 사용자가 적은 이름), `게스트로 이용`을 골랐으면 게스트 모드 표시(FE-17 U-21), 프로필이 없으면 기존 상태 글자 `로그인됨`이다 */
  member: boolean;
  /** 계정 기능(로그인 진입점)을 켰는가. 끄면 게스트 메뉴에 `로그인/가입` 항목이 빠지고 화면 모드·약관·정책만 남는다 */
  accountEnabled: boolean;
  /** 계정 모달 열기(게스트: 로그인, 로그인: 프로필 관리) */
  onOpen: () => void;
  onLogout: () => void;
  /** 약관·정책 열람 화면 열기(게스트·회원 모두) */
  onLegal: () => void;
  /** 메뉴 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** `row`: 사이드바·드로어 아래쪽의 한 줄 버튼(아이콘 + 글자 + ⌃). `icon`: 접힌 레일의 아이콘 버튼 */
  variant?: "row" | "icon";
  /** 회원 + 프로필이 있을 때: "누가 먹나요" 섹션(FE-17 U-12)과 버튼의 아바타·이름(2026-11-23, FE-17 U-06) */
  target?: AccountTargetChoice;
}

const ROW_CLASS = `flex min-h-11 w-full items-center gap-2.5 rounded-[10px] px-2.5 text-left text-sm font-semibold ${HOVER_ROW}`;
/** 메뉴 항목: 44px 높이, 키보드 초점(`data-highlighted`)은 호버와 같은 바탕으로 보인다 */
const ITEM_CLASS = MENU_ITEM_CLASS;
/** 메뉴 구획 구분선 */
const SEPARATOR_CLASS = "mx-2.5 my-1 border-t border-line";

/**
 * 사이드바·드로어 아래쪽의 계정 메뉴(2026-11-23 사용자 요구: claude.ai 앱처럼 계정 버튼 하나를 누르면 메뉴가 위로 열린다).
 * - 버튼 하나: 로그인 + 대상 프로필이 있으면 **그 프로필의 병아리 아바타 + 이름**(로그인 직후 본인 프로필이 기본 대상, FE-17 U-06),
 *   프로필이 있는데 `게스트로 이용`을 골랐으면 **게스트 모드 표시**(색 없는 점선 원 병아리 + `게스트로 이용`, FE-17 U-21이 U-06의 `로그인됨` 표기를 대체),
 *   프로필이 없거나 읽기 전이면 기존 상태 글자 `로그인됨`, 게스트(비로그인)는 `계정` + 사람 아이콘. 로그인 상태는 메뉴 안의 `프로필 관리`·`로그아웃`으로 구분된다.
 *   `aria-haspopup`·`aria-expanded`는 Radix가 단다
 * - 메뉴 안: 회원 = 프로필 관리 · ─ · 누가 먹나요 섹션(게스트로 이용 · 본인 · 가족, 프로필이 있을 때) · ─ · 화면 모드(밝은·다크·시스템을 바로 고른다) · 약관·정책 · ─ · 로그아웃.
 *   `누가 먹나요`는 `화면 모드`와 같은 모양의 독립 섹션이다(작은 섹션 제목 + 메뉴 폭 전체 항목, 같은 높이·체크 자리, 구분선 구획. FE-17 U-12가 U-06의 들여쓴 하위 묶음을 대체).
 *   게스트 = 로그인/가입(계정 기능이 켜졌을 때) · 화면 모드 · 약관·정책
 * - 열고 닫기는 **누름(클릭·탭)과 키보드로만** 한다. 마우스를 올려도 열리지 않는다(FE-17 U-13이 U-01·U-06의 계정 버튼 호버 열림을 대체).
 *   입력창 프로필 칩(`TargetChip`)의 호버 열림은 그대로다
 * - 화면 모드는 고르는 즉시 적용하고 기기 브라우저 저장소에만 둔다(FE-12-04 A, 서버 호출 없음). 골라도 메뉴는 닫히지 않는다(다른 모드를 바로 비교할 수 있게)
 * - 키보드: 열면 첫 항목에 초점, ↑/↓로 옮기고 끝에서 돈다(`loop`), Enter·Space로 고르고, Esc·바깥 누름으로 닫힌다. 닫히면 초점은 버튼으로 돌아온다(Radix)
 * - 로그아웃은 기존 동작 그대로(확인창 없음. 탈퇴는 프로필 관리 안에서만, 확인창 유지)
 */
export function AccountMenu({ member, accountEnabled, onOpen, onLogout, onLegal, container = null, variant = "row", target }: AccountMenuProps) {
  // 저장값은 처음 그릴 때 읽고, 열릴 때마다 다시 읽는다(다른 자리(레일·드로어)의 메뉴에서 바꿨을 수 있다)
  const [mode, setMode] = useState<ThemeMode>(readThemeMode);
  // 열림 상태·첫 항목 초점은 입력창 칩과 같은 손잡이를 쓰되, 호버 손잡이(`triggerProps`)는 버튼에 달지 않는다: 클릭·탭·키보드로만 열린다(FE-17 U-13)
  const { open, onOpenChange, attachContent, contentProps } = useHoverMenu();
  const choice = member && target && target.profiles.length > 0 ? target : null;
  const current = choice ? (choice.profiles.find((profile) => profile.profile_id === choice.value) ?? null) : null;
  const choose = (next: string) => {
    const picked = THEME_MODES.find((item) => item === next);
    if (!picked) return;
    setMode(picked);
    saveThemeMode(picked);
  };
  // 로그인 + 프로필이 있는데 대상으로 `게스트로 이용`을 골랐다(FE-17 U-21): 버튼은 게스트 모드 표시(입력창 칩과 같은 색 없는 점선 원 병아리 + `게스트로 이용`).
  // 로그인 상태임은 메뉴 안의 `프로필 관리`·`로그아웃`으로 구분한다(비로그인은 `계정` + 사람 아이콘, 메뉴에 `로그인/가입`)
  const guestMode = choice !== null && current === null;
  const label = current ? profileName(current) : guestMode ? GUEST_USE_LABEL : member ? ACCOUNT_SIGNED_IN : ACCOUNT_LABEL;
  const targetState = current ? "profile" : guestMode ? "guest" : "none";
  const icon = (size: "row" | "icon") =>
    current || guestMode ? (
      <ProfileAvatar color={current?.avatar_color ?? null} size={size === "row" ? 28 : 32} />
    ) : (
      <UserIcon className={size === "row" ? "size-[18px]" : "size-5"} aria-hidden="true" />
    );
  const entry = (
    <DropdownMenu.Item data-testid="account-entry" onSelect={onOpen} className={ITEM_CLASS}>
      <UserIcon className="size-[18px]" aria-hidden="true" />
      {member ? MANAGE_PROFILES_LABEL : LOGIN_ENTRY_LABEL}
    </DropdownMenu.Item>
  );

  return (
    <DropdownMenu.Root
      modal={false}
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (next) setMode(readThemeMode());
      }}
    >
      <DropdownMenu.Trigger asChild>
        {variant === "icon" ? (
          <button
            type="button"
            aria-label={label}
            data-testid="account-menu-button"
            data-target={targetState}
            className={cn("grid size-11 flex-none place-items-center rounded-xl text-ink-2", HOVER_ROW)}
          >
            {icon("icon")}
          </button>
        ) : (
          <button type="button" data-testid="account-menu-button" data-target={targetState} className={cn(ROW_CLASS, "mt-auto")}>
            {icon("row")}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <ChevronUpIcon className="size-4 text-mute" aria-hidden="true" />
          </button>
        )}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal container={container}>
        <DropdownMenu.Content
          ref={attachContent}
          data-testid="account-menu"
          data-audience={member ? "member" : "guest"}
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={8}
          loop
          {...contentProps}
          className={cn(MENU_CONTENT_CLASS, "max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto")}
        >
          {(member || accountEnabled) && entry}
          {/* 대상 프로필(누가 먹나요): `화면 모드`와 같은 독립 섹션(FE-17 U-12). 위아래 구분선으로 구획하고, 고르면 메뉴가 닫히며 입력창 칩도 같이 바뀐다 */}
          {choice && (
            <>
              <DropdownMenu.Separator className={SEPARATOR_CLASS} />
              <TargetChoiceItems profiles={choice.profiles} value={choice.value} onChange={choice.onChange} />
              <DropdownMenu.Separator className={SEPARATOR_CLASS} />
            </>
          )}
          {/* 화면 모드(FE-12-03 B): 메뉴 안에서 바로 고른다. 고른 항목은 체크 + 굵게(색만으로 구분하지 않는다) */}
          <DropdownMenu.Label className="px-2.5 pt-2 pb-1 text-xs font-bold text-mute">{SCREEN_MODE_LABEL}</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={mode} onValueChange={choose} data-testid="theme-choice">
            {THEME_MODES.map((item) => {
              const Icon = THEME_ICONS[item];
              return (
                <DropdownMenu.RadioItem key={item} value={item} data-testid={`theme-${item}`} onSelect={(event) => event.preventDefault()} className={cn(ITEM_CLASS, mode !== item && "font-medium text-ink-2")}>
                  <Icon className="size-[18px]" aria-hidden="true" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span>{THEME_LABELS[item]}</span>
                    {item === "system" && <span className="text-xs font-normal text-mute">{SYSTEM_MODE_HINT}</span>}
                  </span>
                  <DropdownMenu.ItemIndicator>
                    <CheckIcon className="size-4" aria-hidden="true" />
                  </DropdownMenu.ItemIndicator>
                </DropdownMenu.RadioItem>
              );
            })}
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Item data-testid="legal-entry" onSelect={onLegal} className={ITEM_CLASS}>
            <ScrollTextIcon className="size-[18px]" aria-hidden="true" />
            {LEGAL_MENU_LABEL}
          </DropdownMenu.Item>
          {member && (
            <>
              <DropdownMenu.Separator className={SEPARATOR_CLASS} />
              <DropdownMenu.Item data-testid="account-logout" onSelect={onLogout} className={ITEM_CLASS}>
                <LogOutIcon className="size-[18px]" aria-hidden="true" />
                {LOGOUT_LABEL}
              </DropdownMenu.Item>
            </>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
