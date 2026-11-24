"use client";

import { useId } from "react";
import { Dialog } from "radix-ui";
import { MenuIcon, PanelLeftIcon, SquarePenIcon, XIcon } from "lucide-react";
import { BrandLogo } from "@/components/BrandLogo";
import { HOVER_ROW } from "@/components/button";
import { cn } from "@/lib/utils";
import {
  CURRENT_CHAT_EMPTY,
  CURRENT_CHAT_HEADING,
  MENU_CLOSE_LABEL,
  MENU_LABEL,
  MENU_OPEN_LABEL,
  NEW_CHAT_LABEL,
  RAIL_LABEL,
  SIDEBAR_COLLAPSE_LABEL,
  SIDEBAR_EXPAND_LABEL,
  SIDEBAR_LABEL,
} from "./copy";

/** 아이콘 버튼. 누르는 영역 44×44(지시서 G-2) */
export function IconButton({ label, className, children, ...props }: { label: string } & React.ComponentProps<"button">) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn("grid size-11 flex-none place-items-center rounded-xl text-ink-2", HOVER_ROW, className)}
      {...props}
    >
      {children}
    </button>
  );
}

export function MenuButton({ onClick }: { onClick: () => void }) {
  return (
    <IconButton label={MENU_OPEN_LABEL} data-testid="menu-button" onClick={onClick}>
      <MenuIcon className="size-5" aria-hidden="true" />
    </IconButton>
  );
}

/** 사이드바 `지금 대화` 목록의 항목 하나(FE-17 U-29): 이번 탭의 대화(메모리 값). 제목은 그 대화의 첫 질문이다 */
export interface ChatListItem {
  id: string;
  title: string;
  /** 지금 보고 있는 대화인가(강조) */
  current: boolean;
}

interface SidebarBodyProps {
  /** 이번 탭의 대화 목록(질문이 있는 대화만, 보일 순서대로). 비어 있으면 빈 상태 글자 */
  chats: readonly ChatListItem[];
  onNewChat: () => void;
  /** 목록 항목을 누르면 그 대화로 옮긴다 */
  onSelectChat: (id: string) => void;
  /** 머리 오른쪽 버튼(접기 또는 닫기) */
  action: React.ReactNode;
  /** 맨 아래 계정 자리(FE-04: 게스트는 로그인/가입, 로그인하면 프로필 관리·로그아웃) */
  account?: React.ReactNode;
}

/**
 * 사이드바 안쪽. 칸·오버레이·드로어가 같은 내용을 쓴다. 대화는 저장하지 않으므로 지난 대화(다른 탭·새로고침 전) 목록은 없고,
 * 이번 탭에서 `새 질문`으로 남겨 둔 대화들만 `지금 대화` 아래 항목으로 보인다(FE-17 U-29: 새로고침하면 사라진다).
 * 항목 제목은 첫 질문 한 줄(넘치면 말줄임, 지금 제목 규칙 그대로)이고 지금 대화는 강조·`aria-current`다
 */
function SidebarBody({ chats, onNewChat, onSelectChat, action, account }: SidebarBodyProps) {
  // 칸·오버레이·드로어가 한 화면에 함께 있을 수 있어 머리글 id는 목록마다 다르다
  const headingId = useId();
  return (
    <>
      <div className="flex min-h-11 items-center justify-between pb-2 pl-1.5">
        <b className="text-base">
          <BrandLogo size={26} />
        </b>
        {action}
      </div>
      <button
        type="button"
        data-testid="new-chat"
        onClick={onNewChat}
        className={`flex min-h-11 flex-none items-center gap-2.5 rounded-[10px] px-2.5 text-left text-sm font-semibold ${HOVER_ROW}`}
      >
        <SquarePenIcon className="size-[18px]" aria-hidden="true" />
        {NEW_CHAT_LABEL}
      </button>
      <p id={headingId} className="mx-2.5 mt-3 mb-0.5 flex-none text-xs font-semibold text-mute">
        {CURRENT_CHAT_HEADING}
      </p>
      {chats.length > 0 ? (
        // 목록이 길면 이 칸만 스크롤한다(계정 자리는 맨 아래 그대로)
        <ul data-testid="chat-list" aria-labelledby={headingId} className="m-0 flex min-h-0 list-none flex-col gap-0.5 overflow-y-auto p-0">
          {chats.map((chat) => (
            <li key={chat.id} className="flex-none">
              <button
                type="button"
                data-testid={chat.current ? "current-chat" : "chat-session"}
                data-chat-id={chat.id}
                aria-current={chat.current ? "true" : undefined}
                onClick={() => onSelectChat(chat.id)}
                className={cn(
                  "block min-h-11 w-full truncate rounded-[10px] px-2.5 py-2.5 text-left text-sm",
                  chat.current ? "bg-tint font-semibold" : cn("font-normal text-ink-2", HOVER_ROW),
                )}
              >
                {chat.title}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <span className="px-2.5 text-xs text-mute">{CURRENT_CHAT_EMPTY}</span>
      )}
      {/* 저장 안내는 여기 두지 않는다(PRD-17-08 A): 입력창 아래 고지 한 곳에서만 말한다 */}
      {account}
    </>
  );
}

const SIDE_CLASS = "flex h-full w-[272px] flex-none flex-col gap-1 border-r border-line bg-bg-soft p-3";

export interface SidebarProps {
  chats: readonly ChatListItem[];
  onNewChat: () => void;
  onSelectChat: (id: string) => void;
  onToggle: () => void;
  /** 계정 자리(펼친 칸·오버레이·드로어) */
  account?: React.ReactNode;
  /** 접힌 레일의 계정 버튼 */
  railAccount?: React.ReactNode;
}

/** 넓은 폭의 사이드바 칸: 펼친 모양(272) 또는 접힌 레일(60) */
export function SidebarColumn({ mode, chats, onNewChat, onSelectChat, onToggle, account, railAccount }: SidebarProps & { mode: "rail" | "expanded" }) {
  if (mode === "rail") {
    return (
      <aside aria-label={RAIL_LABEL} data-testid="sidebar-rail" className="flex h-full w-[60px] flex-none flex-col items-center gap-1.5 border-r border-line bg-bg-soft py-3">
        <IconButton label={SIDEBAR_EXPAND_LABEL} data-testid="sidebar-toggle" onClick={onToggle}>
          <PanelLeftIcon className="size-5" aria-hidden="true" />
        </IconButton>
        <IconButton label={NEW_CHAT_LABEL} onClick={onNewChat}>
          <SquarePenIcon className="size-5" aria-hidden="true" />
        </IconButton>
        {railAccount}
      </aside>
    );
  }
  return (
    <aside aria-label={SIDEBAR_LABEL} data-testid="sidebar" data-presentation="push" className={SIDE_CLASS}>
      <SidebarBody
        chats={chats}
        onSelectChat={onSelectChat}
        onNewChat={onNewChat}
        account={account}
        action={
          <IconButton label={SIDEBAR_COLLAPSE_LABEL} data-testid="sidebar-toggle" onClick={onToggle}>
            <PanelLeftIcon className="size-5" aria-hidden="true" />
          </IconButton>
        }
      />
    </aside>
  );
}

interface LayerProps {
  open: boolean;
  /** 스크림 클릭·Esc·닫기 버튼 */
  onClose: () => void;
  /** 층을 그릴 자리(119 배너 아래 영역). 스크림은 이 영역 전체를 덮고 119 배너는 덮지 않는다 */
  container: HTMLElement | null;
}

/** 닫히면 초점을 연 버튼으로 돌려준다(Radix는 `Dialog.Trigger`가 없으면 돌려주지 않는다) */
function returnFocus(container: HTMLElement | null, selector: string) {
  return (event: Event) => {
    event.preventDefault();
    // 창 크기가 기준선을 넘어 층이 닫히면(FE-17 U-18) 원래 버튼이 없을 수 있다: 그때는 지금 배치의 사이드바·메뉴 버튼으로 돌려준다
    (container?.querySelector<HTMLElement>(selector) ?? container?.querySelector<HTMLElement>('[data-testid="sidebar-toggle"], [data-testid="menu-button"]'))?.focus();
  };
}

const SCRIM_CLASS = "absolute inset-0 z-40 bg-scrim/30";

/**
 * 본문 위 오버레이로 펼친 사이드바(지시서 §9): 스크림이 근거 상세 패널까지 덮고, 스크림 클릭·Esc로 사이드바만 닫힌다.
 * Radix Dialog(모달)라 Tab이 뒤 요소에 닿지 않고 닫히면 초점이 누른 버튼으로 돌아간다.
 */
export function SidebarOverlay({ open, onClose, container, chats, onNewChat, onSelectChat, account }: LayerProps & Omit<SidebarProps, "onToggle">) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal container={container}>
        {/* 열린 직후의 클릭도 놓치지 않게 스크림이 직접 닫는다(Radix의 바깥 누름 감지는 열린 다음 틱부터 돈다) */}
        <Dialog.Overlay data-testid="sidebar-scrim" className={SCRIM_CLASS} onClick={onClose} />
        <Dialog.Content
          aria-describedby={undefined}
          data-testid="sidebar"
          data-presentation="overlay"
          onCloseAutoFocus={returnFocus(container, '[data-testid="sidebar-toggle"]')}
          className={cn(SIDE_CLASS, "absolute inset-y-0 left-0 z-40 shadow-lg outline-none")}
        >
          <Dialog.Title className="sr-only">{SIDEBAR_LABEL}</Dialog.Title>
          <SidebarBody
            chats={chats}
            onSelectChat={onSelectChat}
            onNewChat={onNewChat}
            account={account}
            action={
              <IconButton label={SIDEBAR_COLLAPSE_LABEL} data-testid="sidebar-toggle" onClick={onClose}>
                <PanelLeftIcon className="size-5" aria-hidden="true" />
              </IconButton>
            }
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 좁은 폭의 ☰ 드로어. 폭은 디자인 반영본 `.drawer{width:min(320px,86%)}` */
export function MenuDrawer({ open, onClose, container, chats, onNewChat, onSelectChat, account }: LayerProps & Omit<SidebarProps, "onToggle">) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="drawer-scrim" className={SCRIM_CLASS} onClick={onClose} />
        <Dialog.Content
          aria-describedby={undefined}
          data-testid="menu-drawer"
          onCloseAutoFocus={returnFocus(container, '[data-testid="menu-button"]')}
          className="absolute inset-y-0 left-0 z-40 flex w-[min(320px,86%)] flex-col gap-1 bg-bg-soft px-3 pt-3 pb-[max(16px,env(safe-area-inset-bottom,0px))] shadow-lg outline-none"
        >
          <Dialog.Title className="sr-only">{MENU_LABEL}</Dialog.Title>
          <SidebarBody
            chats={chats}
            onSelectChat={onSelectChat}
            onNewChat={onNewChat}
            account={account}
            action={
              <IconButton label={MENU_CLOSE_LABEL} onClick={onClose}>
                <XIcon className="size-5" aria-hidden="true" />
              </IconButton>
            }
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
