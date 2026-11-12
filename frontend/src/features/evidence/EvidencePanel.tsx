"use client";

import { XIcon } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { CLOSE_LABEL, ENTRY_LABELS, EVIDENCE_TITLE } from "./copy";

export type EvidenceMode = "sheet" | "panel";

export interface EvidencePanelProps {
  /** `sheet`: 좁은 폭의 아래 시트(Radix, 모달). `panel`: 넓은 폭의 옆 패널(모달 아님). 어느 쪽인지는 조립하는 쪽이 폭으로 정한다 */
  mode: EvidenceMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

/**
 * 근거 상세를 담는 틀. 두 배치를 모두 그릴 수 있다. 폭 분기·사이드바 연동은 FE-IMPL-06이 한다.
 * 닫혀 있으면 내용을 그리지 않으므로 **고정 안내·고지·119는 이 틀 안에 넣지 않는다**(접히지 않는 영역에 따로 둔다, S5).
 */
export function EvidencePanel({ mode, open, onOpenChange, children }: EvidencePanelProps) {
  if (mode === "sheet") {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="bottom"
          aria-describedby={undefined}
          data-testid="evidence-panel"
          data-mode="sheet"
          // 닫기 버튼(ui/sheet가 그린다)의 누르는 영역을 44px로 키운다
          className="flex max-h-[88dvh] flex-col gap-3 overflow-y-auto rounded-t-[20px] px-[18px] pt-3.5 pb-[max(20px,env(safe-area-inset-bottom,0px))] [&>button]:top-1.5 [&>button]:right-1.5 [&>button]:grid [&>button]:size-11 [&>button]:place-items-center"
        >
          <SheetTitle className="mr-11 text-[21px] leading-7">{EVIDENCE_TITLE}</SheetTitle>
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
        <button type="button" aria-label={CLOSE_LABEL} onClick={() => onOpenChange(false)} className="grid size-11 place-items-center rounded-full">
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
 */
export function EvidenceEntryButton({ mode, onClick, expanded }: { mode: EvidenceMode; onClick: () => void; expanded?: boolean }) {
  return (
    <button
      type="button"
      data-testid="evidence-entry"
      aria-expanded={expanded}
      onClick={onClick}
      className="flex min-h-11 w-full items-center justify-between px-3.5 py-2.5 text-left text-sm font-semibold text-link"
    >
      {ENTRY_LABELS[mode]}
    </button>
  );
}
