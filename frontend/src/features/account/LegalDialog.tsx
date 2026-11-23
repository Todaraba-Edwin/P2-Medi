"use client";

import { Dialog } from "radix-ui";
import { HOVER_TEXT } from "@/components/button";
import { cn } from "@/lib/utils";
import { CLOSE_LABEL, LEGAL_MENU_LABEL } from "./copy";
import { LegalDocsSection } from "./LegalDocsSection";

// 크기: 1280(넓은 화면)은 가운데 모달 560px, 393(좁은 화면)은 전체 화면 시트(옛 설정 화면과 같은 틀, FE-12 §5)
const DIALOG_CLASS =
  "absolute inset-0 z-40 flex flex-col overflow-hidden bg-bg outline-none sm:inset-auto sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[min(640px,calc(100%-24px))] sm:w-[min(560px,calc(100%-24px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-3xl sm:shadow-lg";
const TITLE_ID = "legal-dialog-title";

export interface LegalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** 로그인했는가. 열람 목록이 게스트/회원으로 갈린다(`legal-menu.ts`) */
  member: boolean;
  /** 닫힌 뒤 초점을 둘 곳(연 메뉴 버튼). Radix는 `Dialog.Trigger`가 없으면 돌려주지 않는다 */
  onCloseAutoFocus?: (event: Event) => void;
}

/**
 * 약관·정책 열람 화면(2026-11-23): 계정 메뉴의 `약관·정책` 항목에서 연다. 게스트·회원 모두 현재 적용 문서를 읽기 전용으로 다시 본다(`LegalDocsSection`).
 * 제목이 곧 묶음 이름이라 안쪽에 같은 제목을 두 번 두지 않는다(`labelledBy`). 열리면 초점은 제목에 있고 본문만 스크롤하며 Esc·닫기로 닫힌다.
 */
export function LegalDialog({ open, onOpenChange, container = null, member, onCloseAutoFocus }: LegalDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="legal-scrim" className="absolute inset-0 z-40 bg-scrim/50" />
        <Dialog.Content
          aria-describedby={undefined}
          data-testid="legal-dialog"
          className={DIALOG_CLASS}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            (event.currentTarget as HTMLElement).querySelector<HTMLElement>(`#${TITLE_ID}`)?.focus();
          }}
          onCloseAutoFocus={onCloseAutoFocus}
        >
          <div className="flex h-14 flex-none items-center justify-between px-5">
            <Dialog.Title id={TITLE_ID} tabIndex={-1} className="m-0 text-base font-bold outline-none">
              {LEGAL_MENU_LABEL}
            </Dialog.Title>
            <div className="flex items-center gap-2">
              <Dialog.Close data-testid="legal-close" className={cn("min-h-11 rounded-full border border-line bg-bg px-3 text-sm font-bold text-link", HOVER_TEXT)}>
                {CLOSE_LABEL}
              </Dialog.Close>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pt-1 pb-6">
            {/* 읽기 전용, 동의 기록 없음. 게스트/회원 목록은 legal-menu.ts 한 곳. 서버에 없는 문서는 빠진다 */}
            <LegalDocsSection member={member} labelledBy={TITLE_ID} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
