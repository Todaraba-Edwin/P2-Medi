import type { DetailItem } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 근거 박스의 표지: 자료 이름(`dataset`)을 받은 그대로 보인다. 출처 표의 자료 열과 같은 글자다(PRD-12-03).
 * 출처 종류(`source_kind`)는 속성으로만 남긴다: 종류 문구("공식 파일" 등)는 근거 항목에 실려 오지 않아 그리지 않는다.
 */
export function SourceTag({ item }: { item: Pick<DetailItem, "dataset" | "source_kind"> }) {
  if (!item.dataset) return null;
  return (
    <span
      data-testid="source-tag"
      data-source-kind={item.source_kind ?? undefined}
      className="max-w-full flex-none rounded-md bg-tint px-[7px] py-0.5 text-[11px] leading-[15px] font-semibold text-link [word-break:keep-all]"
    >
      {item.dataset}
    </span>
  );
}

/** 흰 박스 하나 = 근거 하나(PRD-11-01). 머리 한 줄(제목 + 표지 1개) + 본문 */
export function EvidenceBox({
  title,
  tag,
  children,
  className,
  testId = "evidence-box",
}: {
  title?: React.ReactNode;
  tag?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className={cn("flex flex-col gap-2 rounded-xl border border-line bg-bg px-3.5 py-3", className)}>
      {(title || tag) && (
        <div className="flex flex-wrap items-baseline justify-start gap-x-2.5 gap-y-1">
          {title ? <b className="max-w-full flex-none text-sm leading-5 font-semibold [overflow-wrap:break-word] [word-break:keep-all]">{title}</b> : null}
          {tag}
        </div>
      )}
      {children}
    </div>
  );
}
