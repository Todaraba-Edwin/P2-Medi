import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/button";
import { cn } from "@/lib/utils";
import { ENTRY_GROUP_LABEL, GUEST_START_LABEL, LOGIN_ENTRY_LABEL } from "./copy";

/**
 * 시작 화면의 진입 선택(할 일 1): "게스트로 시작"(주 버튼)이 먼저, "로그인/가입"(보조)이 다음이다.
 * 질문 입력창과 119 진입점을 막지 않는다: 이 선택을 누르지 않아도 바로 질문할 수 있다(응급, 게스트는 지금처럼 채팅으로 바로).
 * 사이드바 아래쪽의 계정 자리는 `AccountMenu.tsx`(계정 버튼 하나 + 팝오버 메뉴, 2026-11-23)다.
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
