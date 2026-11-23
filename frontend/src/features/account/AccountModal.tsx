"use client";

import { useEffect, useRef } from "react";
import { Dialog } from "radix-ui";
import { ChevronLeftIcon } from "lucide-react";
import { HOVER_TEXT } from "@/components/button";
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

/**
 * 완료 안내의 `질문하러 가기`(FE-04-15 A): 모달을 닫고 초점을 연 버튼 대신 **질문 입력창**에 둔다(다음 행동이 바로 이어지게).
 * 입력창이 없으면(화면 준비 전) 기존 복귀 규칙대로 연 버튼으로 간다
 */
export function closeAccountModalToQuestion(store: AccountStore = accountStore) {
  opener = document.querySelector<HTMLElement>('[data-testid="main"] textarea') ?? opener;
  store.getState().close();
}

function restoreFocus(event: Event) {
  event.preventDefault();
  // 연 버튼이 사라졌으면(드로어 안 버튼 등) 메뉴·사이드바 버튼으로 돌아간다
  const target = opener?.isConnected ? opener : document.querySelector<HTMLElement>('[data-testid="menu-button"], [data-testid="sidebar-toggle"]');
  opener = null;
  target?.focus();
}

/** 코너 버튼(PRD-13-01 A): 모달 상자 기준 `position: absolute`, 누르는 영역 44px 이상, 본문 글자가 밑으로 지나가도 읽히게 불투명 바탕 */
const CORNER_CLASS = `absolute top-2 z-10 grid min-h-11 min-w-11 place-items-center rounded-full border border-line bg-bg text-sm font-bold text-link ${HOVER_TEXT}`;

/**
 * 모달 상자: 단계와 내용에 상관없이 같은 크기다(사용자 지시 2026-11-19: 단계가 바뀔 때 상자가 튀지 않게).
 * - 640px 이상 화면: 760×642px(고정 전 로그인 단계의 노트북 표시 크기). 화면이 더 작으면 `min(고정값, 100% - 24px)`
 * - 그보다 좁은 화면: 가로·세로 모두 `100% - 24px`(고정 전 로그인 단계의 모바일 표시 크기)
 * 넘치는 내용은 본문(`account-body`) 안에서만 스크롤한다.
 * 상자는 `overflow-clip`이다(FE-17 U-14, ISSUE-031): `overflow-hidden`은 스크롤 상자라 안쪽 요소가 초점을 받을 때 브라우저가 상자 자체를 스크롤할 수 있었다
 * (색 칸의 숨긴 라디오가 상자 기준으로 놓여 상자가 위로 밀리고 아래가 빈 채 남았다). `clip`은 잘라 보이기만 하고 스크롤되지 않는다.
 */
const MODAL_BOX_CLASS =
  "@container absolute top-1/2 left-1/2 z-40 flex h-[calc(100%-24px)] w-[calc(100%-24px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-clip rounded-3xl bg-bg shadow-lg outline-none sm:h-[min(642px,calc(100%-24px))] sm:w-[min(760px,calc(100%-24px))]";

export interface AccountModalProps {
  store?: AccountStore;
  /** 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** 119 안내가 떠 있으면 마스코트를 그리지 않는다(PRD-06-02) */
  hasEmergency?: boolean;
}

/**
 * 계정 중앙 모달: 로그인·가입 → 약관 동의 → 프로필(PJ2-PRD.md 15.3 S10). 배치는 PRD-13을 따른다.
 * - 버튼만 담는 header 띠·구분선이 없고 `<`(뒤로)·`닫기`는 모달 상자의 좌상단·우상단 코너에 같은 높이로 있다
 * - `<`는 돌아갈 이전 단계가 있을 때만 DOM에 있다(PRD-13-02 A). `닫기`는 글자이고 Esc도 닫기다(PRD-13-04 A)
 * - 상자 크기는 모든 단계에서 같다(`MODAL_BOX_CLASS`)
 * - 본문만 모달 안에서 스크롤하고 코너 버튼은 상자에 고정된다(§4.7). Tab은 모달 안에서만 돈다(Radix)
 * - 탭 순서는 화면 순서와 같게 `<` → `닫기`로 둔다(§4.5·§11의 WCAG 2.4.3 점검에서 고른 값)
 */
export function AccountModal({ store = accountStore, container = null, hasEmergency = false }: AccountModalProps) {
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

  return (
    <Dialog.Root open={step !== undefined} onOpenChange={(open) => !open && store.getState().close()}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="account-scrim" className="absolute inset-0 z-40 bg-scrim/50" />
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
          // 열린 콤보박스(약 검색 후보 목록) 위의 Esc는 목록만 닫는다(Radix는 document capture 단계에서 먼저 받으므로 여기서 막는다). 목록이 닫힌 뒤의 Esc는 모달을 닫는다
          onEscapeKeyDown={(event) => {
            if (event.target instanceof Element && event.target.closest('[role="combobox"][aria-expanded="true"]')) event.preventDefault();
          }}
          className={MODAL_BOX_CLASS}
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
            <AccountModalContext.Provider value={{ store, container, hideMascot: hasEmergency }}>
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
