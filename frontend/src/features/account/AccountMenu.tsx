"use client";

import { useEffect, useRef, useState } from "react";
import { DropdownMenu } from "radix-ui";
import { CheckIcon, ChevronUpIcon, LogOutIcon, MonitorIcon, MoonIcon, ScrollTextIcon, SunIcon, UserIcon, type LucideIcon } from "lucide-react";
import { HOVER_ROW } from "@/components/button";
import { THEME_MODES, readThemeMode, saveThemeMode, type ThemeMode } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { SCREEN_MODE_LABEL, SYSTEM_MODE_HINT, THEME_LABELS } from "@/features/settings/copy";
import { ACCOUNT_LABEL, ACCOUNT_SIGNED_IN, LEGAL_MENU_LABEL, LOGIN_ENTRY_LABEL, LOGOUT_LABEL, MANAGE_PROFILES_LABEL } from "./copy";

const THEME_ICONS: Readonly<Record<ThemeMode, LucideIcon>> = { light: SunIcon, dark: MoonIcon, system: MonitorIcon };

export interface AccountMenuProps {
  /** 로그인했는가. 서버(`GET /me`)는 이름·이메일을 주지 않으므로 식별 표시는 기존 상태 글자 `로그인됨`뿐이다(새 식별값을 노출하지 않는다) */
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
}

const ROW_CLASS = `flex min-h-11 w-full items-center gap-2.5 rounded-[10px] px-2.5 text-left text-sm font-semibold ${HOVER_ROW}`;
/** 메뉴 항목: 44px 높이, 키보드 초점(`data-highlighted`)은 호버와 같은 바탕으로 보인다 */
const ITEM_CLASS = "flex min-h-11 cursor-pointer items-center gap-2.5 rounded-[10px] px-2.5 text-sm font-semibold text-ink outline-none select-none data-[highlighted]:bg-tint";

/**
 * 사이드바·드로어 아래쪽의 계정 메뉴(2026-11-23 사용자 요구: claude.ai 앱처럼 계정 버튼 하나를 누르면 메뉴가 위로 열린다).
 * - 버튼 하나: 로그인 상태는 기존 상태 글자 `로그인됨`, 게스트는 `계정`. `aria-haspopup`·`aria-expanded`는 Radix가 단다
 * - 메뉴 안: 회원 = 프로필 관리 · 화면 모드(밝은·다크·시스템을 바로 고른다) · 약관·정책 · ─ · 로그아웃. 게스트 = 로그인/가입(계정 기능이 켜졌을 때) · 화면 모드 · 약관·정책
 * - 화면 모드는 고르는 즉시 적용하고 기기 브라우저 저장소에만 둔다(FE-12-04 A, 서버 호출 없음). 골라도 메뉴는 닫히지 않는다(다른 모드를 바로 비교할 수 있게)
 * - 키보드: 열면 첫 항목에 초점, ↑/↓로 옮기고 끝에서 돈다(`loop`), Enter·Space로 고르고, Esc·바깥 누름으로 닫힌다. 닫히면 초점은 버튼으로 돌아온다(Radix)
 * - 로그아웃은 기존 동작 그대로(확인창 없음. 탈퇴는 프로필 관리 안에서만, 확인창 유지)
 */
export function AccountMenu({ member, accountEnabled, onOpen, onLogout, onLegal, container = null, variant = "row" }: AccountMenuProps) {
  // 저장값은 처음 그릴 때 읽고, 열릴 때마다 다시 읽는다(다른 자리(레일·드로어)의 메뉴에서 바꿨을 수 있다)
  const [mode, setMode] = useState<ThemeMode>(readThemeMode);
  const [open, setOpen] = useState(false);
  const content = useRef<HTMLDivElement>(null);
  // 마우스로 열어도 첫 항목에 초점을 둔다(Radix 기본은 키보드로 열 때만 첫 항목, 마우스면 메뉴 상자). 메뉴 이름은 버튼 글자다(Radix `aria-labelledby`)
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => content.current?.querySelector<HTMLElement>('[role="menuitem"], [role="menuitemradio"]')?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open]);
  const choose = (next: string) => {
    const picked = THEME_MODES.find((item) => item === next);
    if (!picked) return;
    setMode(picked);
    saveThemeMode(picked);
  };
  const label = member ? ACCOUNT_SIGNED_IN : ACCOUNT_LABEL;
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
        setOpen(next);
        if (next) setMode(readThemeMode());
      }}
    >
      <DropdownMenu.Trigger asChild>
        {variant === "icon" ? (
          <button type="button" aria-label={label} data-testid="account-menu-button" className={cn("grid size-11 flex-none place-items-center rounded-xl text-ink-2", HOVER_ROW)}>
            <UserIcon className="size-5" aria-hidden="true" />
          </button>
        ) : (
          <button type="button" data-testid="account-menu-button" className={cn(ROW_CLASS, "mt-auto")}>
            <UserIcon className="size-[18px]" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <ChevronUpIcon className="size-4 text-mute" aria-hidden="true" />
          </button>
        )}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal container={container}>
        <DropdownMenu.Content
          ref={content}
          data-testid="account-menu"
          data-audience={member ? "member" : "guest"}
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={8}
          loop
          className="z-50 flex w-[min(272px,calc(100vw-24px))] flex-col gap-0.5 rounded-2xl border border-line bg-bg p-1.5 shadow-lg outline-none"
        >
          {(member || accountEnabled) && entry}
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
              <DropdownMenu.Separator className="mx-2.5 my-1 border-t border-line" />
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
