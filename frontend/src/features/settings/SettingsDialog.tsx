"use client";

import { useState } from "react";
import { Dialog } from "radix-ui";
import { cn } from "@/lib/utils";
import { HOVER_TEXT, SECONDARY_BUTTON } from "@/components/button";
import { readThemeMode, saveThemeMode, type ThemeMode } from "@/lib/theme";
import { ACCOUNT_LABEL, CLOSE_LABEL, LOGIN_ENTRY_LABEL } from "@/features/account/copy";
import { GUEST_SAVE_NOTICE, SCREEN_MODE_LABEL, SETTINGS_LABEL } from "./copy";
import { ThemeChoice } from "./ThemeChoice";

// 크기: 1280(넓은 화면)은 가운데 모달 560px, 393(좁은 화면)은 전체 화면 시트(FE-12 §5, 디자인 보고 fe12-design §5)
const DIALOG_CLASS =
  "absolute inset-0 z-40 flex flex-col overflow-hidden bg-bg outline-none sm:inset-auto sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[min(640px,calc(100%-24px))] sm:w-[min(560px,calc(100%-24px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-3xl sm:shadow-lg";

export interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** 게스트면 로그인 안내 한 줄과 로그인/가입 버튼을 보인다(계정 기능이 켜져 있을 때만) */
  showLogin: boolean;
  onLogin: () => void;
  /** 머리줄 119 진입점을 덮는 층 안에서도 누를 수 있게 둘 진입점(배너가 떠 있으면 넘기지 않는다) */
  emergencyEntry?: React.ReactNode;
}

/**
 * 설정 화면(FE-12-03 B): 맨 위에 "화면 모드" 3칸. 고른 값은 기기 브라우저 저장소에만 둔다(FE-12-04 A, 서버 저장 없음).
 * 열릴 때 저장값을 읽고, 고르는 즉시 적용한다(저장·확인 버튼 없음).
 */
export function SettingsDialog({ open, onOpenChange, container = null, showLogin, onLogin, emergencyEntry = null }: SettingsDialogProps) {
  // 저장값은 처음 마운트할 때 읽는다(서버 렌더 때는 저장소를 읽지 못해 "시스템"이고, 닫힌 동안에는 그리지 않는다)
  const [mode, setMode] = useState<ThemeMode>(readThemeMode);

  const choose = (next: ThemeMode) => {
    setMode(next);
    saveThemeMode(next);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="settings-scrim" className="absolute inset-0 z-40 bg-scrim/50" />
        <Dialog.Content aria-describedby={undefined} data-testid="settings-dialog" className={DIALOG_CLASS}>
          <div className="flex h-14 flex-none items-center justify-between px-5">
            <Dialog.Title className="m-0 text-base font-bold">{SETTINGS_LABEL}</Dialog.Title>
            <div className="flex items-center gap-2">
              {emergencyEntry}
              <Dialog.Close data-testid="settings-close" className={cn("min-h-11 rounded-full border border-line bg-bg px-3 text-sm font-bold text-link", HOVER_TEXT)}>
                {CLOSE_LABEL}
              </Dialog.Close>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-5 pt-1 pb-6">
            <section aria-labelledby="settings-screen-mode" className="flex flex-col gap-2.5">
              <h3 id="settings-screen-mode" className="m-0 text-xs font-bold text-mute">
                {SCREEN_MODE_LABEL}
              </h3>
              <ThemeChoice value={mode} onChange={choose} />
            </section>
            {showLogin && (
              <section aria-labelledby="settings-account" className="flex flex-col gap-2.5">
                <h3 id="settings-account" className="m-0 text-xs font-bold text-mute">
                  {ACCOUNT_LABEL}
                </h3>
                <p className="m-0 text-sm leading-5 text-ink-2">{GUEST_SAVE_NOTICE}</p>
                <button type="button" data-testid="settings-login" onClick={onLogin} className={cn(SECONDARY_BUTTON, "self-start")}>
                  {LOGIN_ENTRY_LABEL}
                </button>
              </section>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
