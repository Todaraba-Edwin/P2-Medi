"use client";

import { useEffect, useState } from "react";

/** 마우스를 올린 뒤 열기까지·내린 뒤 닫기까지(ms). 지나가는 포인터로 열리거나 메뉴로 옮기는 사이 닫히지 않게 */
export const HOVER_OPEN_DELAY = 120;
export const HOVER_CLOSE_DELAY = 250;

/**
 * Radix `DropdownMenu`를 **마우스 호버로도** 여는 손잡이(2026-11-23, 입력창 프로필 칩. 계정 버튼은 FE-17 U-13부터 호버 손잡이 `triggerProps`를 달지 않아 클릭·키보드로만 열린다).
 * 호버만으로는 터치(아이패드)·키보드에서 쓸 수 없으므로 Radix 기본 열기(누름·탭, Enter·Space·↓)는 그대로 두고 호버를 더한다.
 * - 호버(마우스 포인터만): 올리면 열고, 버튼·메뉴 밖으로 나가면 닫는다. 호버로 열 때는 **초점을 옮기지 않는다**(입력창에 적던 글자가 끊기지 않게),
 *   닫힐 때도 버튼으로 초점을 돌리지 않는다
 * - 호버로 열린 상태에서 버튼을 누르면 닫지 않고 "고정"한다(누름으로 연 것과 같아져 첫 항목에 초점, 포인터가 나가도 열려 있다)
 * - 누름·탭·키보드로 열면 기존 동작(첫 항목 초점, Esc·바깥 누름으로 닫힘, 닫히면 초점은 버튼으로)
 */
export function useHoverMenu() {
  const [view, setView] = useState({ open: false, hover: false });
  // 타이머·초점 복원 자리 같은 바뀌는 값은 한 번 만든 제어 객체 안에 둔다(그리기 중에는 읽지 않고 이벤트에서만 읽는다)
  const [control] = useState(() => new HoverMenuControl((open, hover) => setView({ open, hover })));
  useEffect(() => () => control.clear(), [control]);
  // 누름·탭·키보드로 열었거나 호버 메뉴를 눌러 고정하면 첫 항목에 초점(Radix 기본은 마우스로 열 때 메뉴 상자에 초점). 호버로만 열면 옮기지 않는다
  useEffect(() => {
    if (!view.open || view.hover) return;
    const id = window.setTimeout(() => control.focusFirst(), 0);
    return () => window.clearTimeout(id);
  }, [view.open, view.hover, control]);
  return {
    open: view.open,
    hover: view.hover,
    /** 메뉴 상자에 붙이는 ref(콜백) */
    attachContent: control.setContent,
    /** Radix `onOpenChange`: 누름·키보드·Esc·바깥 누름·항목 고름 */
    onOpenChange: control.onOpenChange,
    triggerProps: control.triggerProps,
    contentProps: control.contentProps,
  };
}

const isMouse = (event: React.PointerEvent) => event.pointerType === "mouse";

class HoverMenuControl {
  private open = false;
  /** 지금 열림이 호버로 생긴 것인가 */
  private hover = false;
  private timer: number | null = null;
  private content: HTMLElement | null = null;
  /** 호버를 받은 버튼(메뉴 밖 누름 판정에서 버튼 누름을 빼는 데 쓴다) */
  private trigger: HTMLElement | null = null;
  /** 호버로 열 때 초점이 있던 곳(입력창 등). 호버 상태로 닫히면 그리로 돌려준다(메뉴 항목은 포인터가 지나가면 초점을 받는다: Radix) */
  private restore: HTMLElement | null = null;
  /** 호버로 열린 채 닫히는 중(누름·키보드로 연 메뉴가 닫히는 것과 구분) */
  private closingByHover = false;

  constructor(private readonly render: (open: boolean, hover: boolean) => void) {}

  clear = () => {
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
  };

  setContent = (element: HTMLDivElement | null) => {
    this.content = element;
  };

  focusFirst = () => this.content?.querySelector<HTMLElement>('[role="menuitem"], [role="menuitemradio"]')?.focus();

  private apply(next: boolean, byHover: boolean) {
    if (next && byHover && !this.open) this.restore = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
    if (next && !byHover) this.restore = null; // 누름·키보드로 열거나 고정하면 Radix 기본(닫히면 버튼으로)
    this.open = next;
    this.hover = next && byHover;
    this.render(this.open, this.hover);
  }

  /** 닫기. 호버로 열린 채 닫히면(포인터가 나감·항목 고름·Esc) 초점은 열기 전 자리로 돌아간다(`onCloseAutoFocus`) */
  private close = () => {
    this.closingByHover = this.hover;
    if (!this.hover) this.restore = null;
    this.apply(false, false);
  };

  private scheduleClose() {
    this.clear();
    if (!this.open || !this.hover) return;
    this.timer = window.setTimeout(this.close, HOVER_CLOSE_DELAY);
  }

  onOpenChange = (next: boolean) => {
    this.clear();
    if (next) this.apply(true, false);
    else this.close();
  };

  readonly triggerProps = {
    onPointerEnter: (event: React.PointerEvent<HTMLElement>) => {
      if (!isMouse(event)) return;
      this.trigger = event.currentTarget;
      this.clear();
      if (this.open) return;
      this.timer = window.setTimeout(() => this.apply(true, true), HOVER_OPEN_DELAY);
    },
    onPointerLeave: (event: React.PointerEvent) => {
      if (!isMouse(event)) return;
      if (!this.open) this.clear();
      else this.scheduleClose();
    },
    onPointerDown: (event: React.PointerEvent) => {
      this.clear();
      // 호버로 열린 메뉴를 누르면 닫지 않고 고정한다(Radix의 열고 닫기 토글을 건너뛴다)
      if (this.open && this.hover) {
        event.preventDefault();
        this.apply(true, false);
      }
    },
  };

  readonly contentProps = {
    onPointerEnter: (event: React.PointerEvent) => {
      if (isMouse(event)) this.clear();
    },
    onPointerLeave: (event: React.PointerEvent) => {
      if (isMouse(event)) this.scheduleClose();
    },
    /** 버튼을 누른 것은 "메뉴 밖 누름"으로 닫지 않는다: 호버 메뉴는 버튼이 고정하고, 누름으로 연 메뉴는 버튼(Radix 토글)이 닫는다 */
    onPointerDownOutside: (event: Event) => {
      if (event.target instanceof Node && this.trigger?.contains(event.target)) event.preventDefault();
    },
    /** 호버로 열면 초점을 옮기지 않는다 */
    onOpenAutoFocus: (event: Event) => {
      if (this.hover) event.preventDefault();
    },
    /** 호버로 열렸다 닫히면 초점을 버튼으로 돌리지 않고 열기 전 자리(입력창 등)로 돌려준다. 그런 자리가 없었으면 아무 데도 옮기지 않는다 */
    onCloseAutoFocus: (event: Event) => {
      if (!this.closingByHover) return;
      event.preventDefault();
      const target = this.restore;
      this.restore = null;
      this.closingByHover = false;
      if (target?.isConnected) target.focus();
    },
  };
}
