"use client";

import { useEffect, useRef } from "react";
import { Dialog } from "radix-ui";
import { ChevronLeftIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { accountStore, useAccountStore } from "@/stores/account";
import type { AccountStore } from "@/stores/account";
import { ConsentStep } from "./ConsentStep";
import { BACK_LABEL, CLOSE_LABEL } from "./copy";
import { LoginStep } from "./LoginStep";
import { AccountModalContext } from "./parts";
import { ProfileForm } from "./ProfileForm";
import { ProfileList } from "./ProfileList";

/** 모달을 연 요소. 닫히면 초점을 돌려준다(Radix는 `Dialog.Trigger`가 없으면 돌려주지 않는다) */
let opener: HTMLElement | null = null;

/** 계정 모달을 연다. 누른 버튼을 기억해 두었다가 닫힐 때 초점을 돌려준다(PRD-13 §4.5) */
export function openAccountModal(store: AccountStore = accountStore) {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  store.getState().open();
}

function restoreFocus(event: Event) {
  event.preventDefault();
  // 연 버튼이 사라졌으면(드로어 안 버튼 등) 메뉴·사이드바 버튼으로 돌아간다
  const target = opener?.isConnected ? opener : document.querySelector<HTMLElement>('[data-testid="menu-button"], [data-testid="sidebar-toggle"]');
  opener = null;
  target?.focus();
}

/** 코너 버튼(PRD-13-01 A): 모달 상자 기준 `position: absolute`, 누르는 영역 44px 이상, 본문 글자가 밑으로 지나가도 읽히게 불투명 바탕 */
const CORNER_CLASS = "absolute top-2 z-10 grid min-h-11 min-w-11 place-items-center rounded-full border border-line bg-bg text-sm font-bold text-link";

export interface AccountModalProps {
  store?: AccountStore;
  /** 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** 119 안내가 떠 있으면 마스코트를 그리지 않는다(PRD-06-02) */
  hasEmergency?: boolean;
  /** 모달이 머리줄의 119 진입점을 덮는 동안 누를 수 있게 모달 안에 둘 진입점(배너가 있으면 넘기지 않는다) */
  emergencyEntry?: React.ReactNode;
}

/**
 * 계정 중앙 모달: 로그인·가입 → 약관 동의 → 프로필(PJ2-PRD.md 15.3 S10). 배치는 PRD-13을 따른다.
 * - 버튼만 담는 header 띠·구분선이 없고 `<`(뒤로)·`닫기`는 모달 상자의 좌상단·우상단 코너에 같은 높이로 있다
 * - `<`는 돌아갈 이전 단계가 있을 때만 DOM에 있다(PRD-13-02 A). `닫기`는 글자이고 Esc도 닫기다(PRD-13-04 A)
 * - 본문만 모달 안에서 스크롤하고 코너 버튼은 상자에 고정된다(§4.7). Tab은 모달 안에서만 돈다(Radix)
 * - 탭 순서는 화면 순서와 같게 `<` → `닫기`로 둔다(§4.5·§11의 WCAG 2.4.3 점검에서 고른 값)
 */
export function AccountModal({ store = accountStore, container = null, hasEmergency = false, emergencyEntry = null }: AccountModalProps) {
  const flow = useAccountStore((state) => state.flow, store);
  const step = flow[flow.length - 1];
  const content = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const focusTitle = () => content.current?.querySelector<HTMLElement>("[data-account-title]")?.focus();

  // 단계가 바뀌면 본문을 맨 위로 올리고 제목을 읽게 한다
  useEffect(() => {
    if (!step) return;
    body.current?.scrollTo?.({ top: 0 });
    focusTitle();
  }, [step]);

  const wide = step === "login" || step === "signup";

  return (
    <Dialog.Root open={step !== undefined} onOpenChange={(open) => !open && store.getState().close()}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="account-scrim" className="absolute inset-0 z-40 bg-ink/50" />
        <Dialog.Content
          ref={content}
          aria-describedby={undefined}
          data-testid="account-modal"
          data-step={step}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            focusTitle();
          }}
          onCloseAutoFocus={restoreFocus}
          // 바깥을 눌러도 닫지 않는다: 적던 값이 실수로 사라지지 않게 닫기·Esc로만 닫는다
          onPointerDownOutside={(event) => event.preventDefault()}
          className={cn(
            "@container absolute top-1/2 left-1/2 z-40 flex max-h-[calc(100%-24px)] w-[calc(100%-24px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl bg-bg shadow-lg outline-none",
            wide ? "max-w-[760px]" : "max-w-[520px]",
          )}
        >
          {flow.length > 1 && (
            <button type="button" data-testid="account-back" aria-label={BACK_LABEL} onClick={() => store.getState().back()} className={cn(CORNER_CLASS, "left-2")}>
              <ChevronLeftIcon className="size-5" aria-hidden="true" />
            </button>
          )}
          <Dialog.Close data-testid="account-close" className={cn(CORNER_CLASS, "right-2 px-3")}>
            {CLOSE_LABEL}
          </Dialog.Close>
          <div ref={body} data-testid="account-body" className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
            <AccountModalContext.Provider value={{ store, container, hideMascot: hasEmergency, emergencyEntry }}>
              {(step === "login" || step === "signup") && <LoginStep key={step} mode={step} />}
              {step === "consent" && <ConsentStep />}
              {step === "profiles" && <ProfileList />}
              {step === "profile-form" && <ProfileForm />}
            </AccountModalContext.Provider>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
