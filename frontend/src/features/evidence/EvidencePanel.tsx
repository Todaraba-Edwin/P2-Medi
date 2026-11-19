"use client";

import { XIcon } from "lucide-react";
import { HOVER_TEXT, ICON_BUTTON } from "@/components/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { CLOSE_LABEL, ENTRY_HINT_LOOKUP, ENTRY_LABELS, EVIDENCE_TITLE } from "./copy";

export type EvidenceMode = "sheet" | "panel";

export interface EvidencePanelProps {
  /** `sheet`: 좁은 폭의 아래 시트(Radix, 모달). `panel`: 넓은 폭의 옆 패널(모달 아님). 어느 쪽인지는 조립하는 쪽이 폭으로 정한다 */
  mode: EvidenceMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  /**
   * 시트만: 그릴 자리. 주면 시트와 스크림이 그 요소 안에만 그려진다(조립이 119 배너 아래 영역을 넘겨 배너를 덮지 않게 한다,
   * 사용자 결정 2026-11-16 후보 5 B). 없으면 화면 전체(응급이 아닐 때의 기존 동작)
   */
  container?: HTMLElement | null;
  /** 시트만: 제목 줄 오른쪽(닫기 버튼 왼쪽)에 둘 요소. 조립이 119 진입점을 넣는다(시트가 머리줄 진입점을 덮을 때) */
  headerAction?: React.ReactNode;
}

/**
 * 근거 상세를 담는 틀. 두 배치를 모두 그릴 수 있다. 폭 분기·사이드바 연동은 FE-IMPL-06이 한다.
 * 닫혀 있으면 내용을 그리지 않으므로 **고정 안내·고지·119는 이 틀 안에 넣지 않는다**(접히지 않는 영역에 따로 둔다, S5).
 * 단 시트가 머리줄의 119 진입점을 덮는 동안 누를 수 있게, 조립이 `headerAction`으로 같은 진입점을 하나 더 넣을 수 있다(바깥 진입점을 대신하지 않는다).
 */
export function EvidencePanel({ mode, open, onOpenChange, children, container, headerAction }: EvidencePanelProps) {
  if (mode === "sheet") {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="bottom"
          container={container}
          aria-describedby={undefined}
          data-testid="evidence-panel"
          data-mode="sheet"
          // 닫기 버튼(ui/sheet가 그린다)의 누르는 영역을 44px로 키운다. 자리를 받으면 그 높이를 넘지 않는다(배너를 덮지 않게)
          className={cn(
            "flex flex-col gap-3 overflow-y-auto rounded-t-[20px] px-[18px] pt-3.5 pb-[max(20px,env(safe-area-inset-bottom,0px))] [&>button]:top-1.5 [&>button]:right-1.5 [&>button]:grid [&>button]:size-11 [&>button]:place-items-center",
            container ? "max-h-[min(88dvh,calc(100%-16px))]" : "max-h-[88dvh]",
          )}
        >
          <div className="mr-11 flex min-h-8 items-center justify-between gap-2">
            <SheetTitle className="text-[21px] leading-7">{EVIDENCE_TITLE}</SheetTitle>
            {headerAction}
          </div>
          {children}
        </SheetContent>
      </Sheet>
    );
  }
  if (!open) return null;
  return (
    <aside aria-label={EVIDENCE_TITLE} data-testid="evidence-panel" data-mode="panel" className="flex h-full min-h-0 flex-col overflow-y-auto border-l border-line bg-bg-softer">
      <header className="sticky top-0 z-10 flex min-h-14 items-center justify-between border-b border-line bg-bg-softer pr-1.5 pl-5">
        <h2 className="m-0 text-base font-bold">{EVIDENCE_TITLE}</h2>
        <button type="button" aria-label={CLOSE_LABEL} onClick={() => onOpenChange(false)} className={ICON_BUTTON}>
          <XIcon className="size-4" aria-hidden="true" />
        </button>
      </header>
      <div className="px-5 py-[18px]">{children}</div>
    </aside>
  );
}

/**
 * 근거 상세 진입 버튼. 글자는 배치에 따라 둘 중 하나다(시트 "근거 상세 보기", 패널 "근거 상세 열기").
 * 결과 카드의 아래 자리(`ResultCard`·`ResultView`의 `footer`)에 넣는다. 누르는 영역 44px.
 * 약을 찾지 못한 결과에서는 `lookup`으로 `· 찾아본 곳`이 붙는다(그 밖에는 덧붙임 없음).
 */
export function EvidenceEntryButton({
  mode,
  onClick,
  expanded,
  lookup = false,
}: {
  mode: EvidenceMode;
  onClick: () => void;
  expanded?: boolean;
  /** 약을 찾지 못한 결과면 true: 글자 뒤에 `· 찾아본 곳`을 붙인다(PRD-14, 근거 상세에 성분코드가 아니라 찾아본 곳이 있다) */
  lookup?: boolean;
}) {
  return (
    <button
      type="button"
      data-testid="evidence-entry"
      aria-expanded={expanded}
      onClick={onClick}
      className={`flex min-h-11 w-full items-center justify-between px-3.5 py-2.5 text-left text-sm font-semibold text-link ${HOVER_TEXT}`}
    >
      <span>
        {ENTRY_LABELS[mode]}
        {lookup ? <span data-slot="entry-hint">{` · ${ENTRY_HINT_LOOKUP}`}</span> : null}
      </span>
    </button>
  );
}
