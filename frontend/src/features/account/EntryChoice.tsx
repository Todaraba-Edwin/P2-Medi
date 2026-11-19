import { UserIcon } from "lucide-react";
import { ACCOUNT_LABEL, ENTRY_GROUP_LABEL, GUEST_START_LABEL, LOGIN_ENTRY_LABEL, LOGOUT_LABEL, MANAGE_PROFILES_LABEL } from "./copy";

/**
 * 시작 화면의 진입 선택(할 일 1): "게스트로 시작"(주 버튼)이 먼저, "로그인/가입"(보조)이 다음이다.
 * 질문 입력창과 119 진입점을 막지 않는다: 이 선택을 누르지 않아도 바로 질문할 수 있다(응급, 게스트는 지금처럼 채팅으로 바로).
 */
export function EntryChoice({ onGuest, onLogin }: { onGuest: () => void; onLogin: () => void }) {
  return (
    <div role="group" aria-label={ENTRY_GROUP_LABEL} data-testid="entry-choice" className="mx-auto flex w-full max-w-[360px] gap-2">
      <button type="button" data-testid="guest-start" onClick={onGuest} className="min-h-11 min-w-0 flex-1 rounded-full bg-yellow px-3 text-sm font-bold text-ink">
        {GUEST_START_LABEL}
      </button>
      <button type="button" data-testid="login-entry" onClick={onLogin} className="min-h-11 min-w-0 flex-1 rounded-full border border-line-2 bg-bg px-3 text-sm font-bold text-ink-2">
        {LOGIN_ENTRY_LABEL}
      </button>
    </div>
  );
}

export interface AccountMenuProps {
  /** 로그인한 사용자의 표시 이름. 게스트면 null */
  displayName: string | null;
  /** 계정 모달 열기(게스트: 로그인, 로그인: 프로필 관리) */
  onOpen: () => void;
  onLogout: () => void;
}

const ROW_CLASS = "flex min-h-11 items-center gap-2.5 rounded-[10px] px-2.5 text-left text-sm font-semibold hover:bg-tint";

/** 사이드바·드로어 아래쪽의 계정 자리. 게스트는 "로그인/가입", 로그인하면 이름·프로필 관리·로그아웃 */
export function AccountMenu({ displayName, onOpen, onLogout }: AccountMenuProps) {
  if (displayName === null) {
    return (
      <div className="mt-auto flex flex-col pt-2">
        <button type="button" data-testid="account-entry" onClick={onOpen} className={ROW_CLASS}>
          <UserIcon className="size-[18px]" aria-hidden="true" />
          {LOGIN_ENTRY_LABEL}
        </button>
      </div>
    );
  }
  return (
    <div role="group" aria-label={ACCOUNT_LABEL} data-testid="account-menu" className="mt-auto flex flex-col pt-2">
      <p data-testid="account-name" className="m-0 truncate px-2.5 text-xs font-semibold text-mute">
        {displayName}
      </p>
      <button type="button" data-testid="account-entry" onClick={onOpen} className={ROW_CLASS}>
        <UserIcon className="size-[18px]" aria-hidden="true" />
        {MANAGE_PROFILES_LABEL}
      </button>
      <button type="button" data-testid="account-logout" onClick={onLogout} className={ROW_CLASS}>
        {LOGOUT_LABEL}
      </button>
    </div>
  );
}
