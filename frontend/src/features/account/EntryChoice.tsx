import { ScrollTextIcon, SettingsIcon, UserIcon } from "lucide-react";
import { HOVER_ROW, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/button";
import { cn } from "@/lib/utils";
import { ACCOUNT_SIGNED_IN, ENTRY_GROUP_LABEL, GUEST_START_LABEL, LEGAL_MENU_LABEL, LOGIN_ENTRY_LABEL, LOGOUT_LABEL, MANAGE_PROFILES_LABEL } from "./copy";
import { ACCOUNT_MENU_LABEL, SETTINGS_LABEL } from "@/features/settings/copy";

/**
 * 시작 화면의 진입 선택(할 일 1): "게스트로 시작"(주 버튼)이 먼저, "로그인/가입"(보조)이 다음이다.
 * 질문 입력창과 119 진입점을 막지 않는다: 이 선택을 누르지 않아도 바로 질문할 수 있다(응급, 게스트는 지금처럼 채팅으로 바로).
 */
export function EntryChoice({ onGuest, onLogin }: { onGuest: () => void; onLogin: () => void }) {
  return (
    <div role="group" aria-label={ENTRY_GROUP_LABEL} data-testid="entry-choice" className="mx-auto flex w-full max-w-[360px] gap-2">
      <button type="button" data-testid="guest-start" onClick={onGuest} className={cn(PRIMARY_BUTTON, "min-w-0 flex-1 px-3")}>
        {GUEST_START_LABEL}
      </button>
      <button type="button" data-testid="login-entry" onClick={onLogin} className={cn(SECONDARY_BUTTON, "min-w-0 flex-1 px-3")}>
        {LOGIN_ENTRY_LABEL}
      </button>
    </div>
  );
}

export interface AccountMenuProps {
  /** 로그인했는가. 서버(`GET /me`)는 이름·이메일을 주지 않으므로 이름 대신 로그인 상태 글자만 보인다 */
  member: boolean;
  /** 계정 기능(로그인 진입점)을 켰는가. 끄면 게스트도 "설정" 줄만 보인다 */
  accountEnabled: boolean;
  /** 계정 모달 열기(게스트: 로그인, 로그인: 프로필 관리) */
  onOpen: () => void;
  onLogout: () => void;
  /** 설정 화면 열기(화면 모드) */
  onSettings: () => void;
  /** 약관·정책 열람 열기(설정 화면의 약관·정책 묶음으로, 2026-11-23). 게스트·회원 모두 있다 */
  onLegal: () => void;
}

const ROW_CLASS = `flex min-h-11 items-center gap-2.5 rounded-[10px] px-2.5 text-left text-sm font-semibold ${HOVER_ROW}`;

/**
 * 사이드바·드로어 아래쪽의 계정 자리(FE-12-03 B). 게스트: "로그인/가입"(계정 기능이 켜졌을 때) + "설정" + "약관·정책".
 * 로그인하면: 상태 글자 + "프로필 관리 / 설정 / 약관·정책 / ─ / 로그아웃".
 */
export function AccountMenu({ member, accountEnabled, onOpen, onLogout, onSettings, onLegal }: AccountMenuProps) {
  const settingsRow = (
    <button type="button" data-testid="settings-entry" onClick={onSettings} className={ROW_CLASS}>
      <SettingsIcon className="size-[18px]" aria-hidden="true" />
      {SETTINGS_LABEL}
    </button>
  );
  const legalRow = (
    <button type="button" data-testid="legal-entry" onClick={onLegal} className={ROW_CLASS}>
      <ScrollTextIcon className="size-[18px]" aria-hidden="true" />
      {LEGAL_MENU_LABEL}
    </button>
  );
  if (!member) {
    return (
      <div role="group" aria-label={ACCOUNT_MENU_LABEL} className="mt-auto flex flex-col pt-2">
        {accountEnabled && (
          <button type="button" data-testid="account-entry" onClick={onOpen} className={ROW_CLASS}>
            <UserIcon className="size-[18px]" aria-hidden="true" />
            {LOGIN_ENTRY_LABEL}
          </button>
        )}
        {settingsRow}
        {legalRow}
      </div>
    );
  }
  return (
    <div role="group" aria-label={ACCOUNT_MENU_LABEL} data-testid="account-menu" className="mt-auto flex flex-col pt-2">
      <p data-testid="account-name" className="m-0 truncate px-2.5 text-xs font-semibold text-mute">
        {ACCOUNT_SIGNED_IN}
      </p>
      <button type="button" data-testid="account-entry" onClick={onOpen} className={ROW_CLASS}>
        <UserIcon className="size-[18px]" aria-hidden="true" />
        {MANAGE_PROFILES_LABEL}
      </button>
      {settingsRow}
      {legalRow}
      <hr className="mx-2.5 my-1 border-0 border-t border-line" />
      <button type="button" data-testid="account-logout" onClick={onLogout} className={ROW_CLASS}>
        {LOGOUT_LABEL}
      </button>
    </div>
  );
}
