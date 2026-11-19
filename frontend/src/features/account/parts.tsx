"use client";

import { createContext, useContext } from "react";
import { AlertDialog, Dialog } from "radix-ui";
import { DANGER_BUTTON, SECONDARY_BUTTON } from "@/components/button";
import { cn } from "@/lib/utils";
import { accountStore } from "@/stores/account";
import type { AccountFailure, AccountStore } from "@/stores/account";
import {
  CANCEL_LABEL,
  ERROR_ACCOUNT_UNAVAILABLE,
  ERROR_AUTH_FAILED,
  ERROR_AUTH_RATE_LIMITED,
  ERROR_AUTH_REQUIRED,
  ERROR_AUTH_UNAVAILABLE,
  ERROR_EMAIL_NOT_CONFIRMED,
  ERROR_EMAIL_SEND_FAILED,
  ERROR_EMAIL_TAKEN,
  ERROR_GENERIC,
  ERROR_INVALID_CREDENTIALS,
  ERROR_INVALID_REQUEST,
  ERROR_MEDICATION_LIMIT,
  ERROR_NETWORK,
  ERROR_NOT_FOUND,
  ERROR_NOT_IMPLEMENTED,
  ERROR_OAUTH_EMAIL_REQUIRED,
  ERROR_OAUTH_FAILED,
  ERROR_PROFILE_LIMIT,
  ERROR_RECONSENT_REQUIRED,
  ERROR_REQUIRED_CONSENT,
  ERROR_SELF_EXISTS,
  ERROR_SELF_FIXED,
  ERROR_SELF_REQUIRED,
  ERROR_USE_ACCOUNT_DELETE,
  ERROR_VERSION_MISMATCH,
  ERROR_WEAK_PASSWORD,
  HEALTH_CONSENT_REQUIRED_FALLBACK,
} from "./copy";

/** 모달 안 부품이 함께 쓰는 값: 스토어, 층을 그릴 자리, 마스코트를 숨길지, 119 진입점 */
export interface AccountModalContextValue {
  store: AccountStore;
  container: HTMLElement | null;
  hideMascot: boolean;
  emergencyEntry: React.ReactNode;
}

export const AccountModalContext = createContext<AccountModalContextValue>({ store: accountStore, container: null, hideMascot: false, emergencyEntry: null });
export const useAccountModal = () => useContext(AccountModalContext);

/** 단계 제목. 모달이 열리거나 단계가 바뀌면 초점이 여기로 온다(PRD-13 §4.5: 입력창이 아니라 제목) */
export function StepTitle({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Dialog.Title data-account-title tabIndex={-1} className={cn("m-0 text-xl leading-7 font-extrabold outline-none [word-break:keep-all]", className)}>
      {children}
    </Dialog.Title>
  );
}

/** 단계 본문 틀(1열, 상자가 넓어도 520px 폭 가운데). 위 여백(`padding-top`)만으로 코너 버튼 자리를 비운다: header 띠·구분선이 없다 */
export function StepBody({ children, className, ...props }: React.ComponentProps<"div">) {
  return (
    <div className={cn("mx-auto flex w-full max-w-[520px] flex-col gap-3.5 px-5 pt-14 pb-5", className)} {...props}>
      {children}
    </div>
  );
}

/** 모달이 머리줄의 119 진입점을 덮는 동안의 진입점 자리(조립이 넘긴 것을 그대로 둔다. 배너가 떠 있으면 비어 있다) */
export function EmergencyEntrySlot({ className }: { className?: string }) {
  const { emergencyEntry } = useAccountModal();
  return emergencyEntry ? <div className={cn("flex", className)}>{emergencyEntry}</div> : null;
}

/**
 * 오류 코드 → 화면 글자. 문구는 화면 상수다(서버는 문구를 주지 않는다).
 * 백엔드 코드 목록은 `backend/app/api/account.py`·`backend/app/security/auth.py`, 로그인 코드는 `lib/api/auth.ts`·`lib/supabase/callback.ts`
 */
const CODE_MESSAGES: Readonly<Record<string, string>> = {
  // 로그인·가입(Supabase Auth·목 로그인. 백엔드 코드가 아니다)
  INVALID_CREDENTIALS: ERROR_INVALID_CREDENTIALS,
  EMAIL_TAKEN: ERROR_EMAIL_TAKEN,
  EMAIL_NOT_CONFIRMED: ERROR_EMAIL_NOT_CONFIRMED,
  WEAK_PASSWORD: ERROR_WEAK_PASSWORD,
  EMAIL_SEND_FAILED: ERROR_EMAIL_SEND_FAILED,
  AUTH_RATE_LIMITED: ERROR_AUTH_RATE_LIMITED,
  AUTH_FAILED: ERROR_AUTH_FAILED,
  // 소셜 로그인 콜백(`/auth/callback`)
  OAUTH_EMAIL_REQUIRED: ERROR_OAUTH_EMAIL_REQUIRED,
  OAUTH_FAILED: ERROR_OAUTH_FAILED,
  // 401
  AUTH_REQUIRED: ERROR_AUTH_REQUIRED,
  AUTH_INVALID: ERROR_AUTH_REQUIRED,
  // 403
  CONSENT_REQUIRED: ERROR_REQUIRED_CONSENT,
  RECONSENT_REQUIRED: ERROR_RECONSENT_REQUIRED,
  // 404
  NOT_FOUND: ERROR_NOT_FOUND,
  // 409
  VERSION_MISMATCH: ERROR_VERSION_MISMATCH,
  USE_ACCOUNT_DELETE: ERROR_USE_ACCOUNT_DELETE,
  SELF_REQUIRED: ERROR_SELF_REQUIRED,
  SELF_EXISTS: ERROR_SELF_EXISTS,
  SELF_FIXED: ERROR_SELF_FIXED,
  // 422
  HEALTH_CONSENT_REQUIRED: HEALTH_CONSENT_REQUIRED_FALLBACK,
  PROFILE_LIMIT: ERROR_PROFILE_LIMIT,
  MEDICATION_LIMIT: ERROR_MEDICATION_LIMIT,
  INVALID_REQUEST: ERROR_INVALID_REQUEST,
  // 501·503
  NOT_IMPLEMENTED: ERROR_NOT_IMPLEMENTED,
  AUTH_UNAVAILABLE: ERROR_AUTH_UNAVAILABLE,
  ACCOUNT_UNAVAILABLE: ERROR_ACCOUNT_UNAVAILABLE,
};

/** 코드가 없거나 모르는 코드일 때 상태 코드로 고르는 글자 */
const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  401: ERROR_AUTH_REQUIRED,
  501: ERROR_NOT_IMPLEMENTED,
  503: ERROR_ACCOUNT_UNAVAILABLE,
};

/** 실패를 화면 글자로 바꾼다. 서버가 준 코드(없으면 상태 코드)만 보고 입력 값은 쓰지 않는다 */
export function failureMessage(failure: AccountFailure): string {
  if (failure.kind === "network") return ERROR_NETWORK;
  return (failure.code !== null ? CODE_MESSAGES[failure.code] : undefined) ?? STATUS_MESSAGES[failure.status] ?? ERROR_GENERIC;
}

/** 실패 한 줄(보조기기가 바로 읽는다) */
export function FailureLine({ failure }: { failure: AccountFailure | null }) {
  if (!failure) return null;
  return (
    <p role="alert" data-testid="account-error" className="m-0 text-sm leading-5 font-semibold text-red-ink">
      {failureMessage(failure)}
    </p>
  );
}

/** 버튼 모양·호버 반응의 원본은 `components/button.ts`다(계정 화면은 여기서 가져다 쓴다) */
export { DANGER_TEXT_BUTTON, ICON_BUTTON, PRIMARY_BUTTON, SECONDARY_BUTTON, SOCIAL_BUTTON, TEXT_BUTTON } from "@/components/button";
export const FIELD_CLASS = "min-h-11 w-full min-w-0 rounded-xl border border-line-2 bg-bg px-3 text-base outline-none focus:border-link disabled:bg-bg-softer disabled:text-faint";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
}

/** 확인 모달(삭제·탈퇴·건강 정보 동의 철회). 버튼만 담는 header가 없고 취소가 먼저다. 계정 모달과 같은 자리(119 배너 아래)에 그린다 */
export function ConfirmDialog({ open, onOpenChange, title, body, confirmLabel, onConfirm, pending = false }: ConfirmDialogProps) {
  const { container } = useAccountModal();
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal container={container}>
        <AlertDialog.Overlay className="absolute inset-0 z-50 bg-ink/50" />
        <AlertDialog.Content
          data-testid="confirm-dialog"
          className="absolute top-1/2 left-1/2 z-50 flex w-[calc(100%-48px)] max-w-[360px] -translate-x-1/2 -translate-y-1/2 flex-col gap-2 rounded-3xl bg-bg p-5 shadow-lg outline-none"
        >
          <AlertDialog.Title className="m-0 text-lg leading-6 font-extrabold [word-break:keep-all]">{title}</AlertDialog.Title>
          <AlertDialog.Description className="m-0 text-sm leading-5 text-ink-2">{body}</AlertDialog.Description>
          <div className="mt-2 flex gap-2">
            <AlertDialog.Cancel className={cn(SECONDARY_BUTTON, "flex-1 px-3")}>{CANCEL_LABEL}</AlertDialog.Cancel>
            <button
              type="button"
              data-testid="confirm-action"
              disabled={pending}
              onClick={onConfirm}
              className={cn(DANGER_BUTTON, "flex-1")}
            >
              {confirmLabel}
            </button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
