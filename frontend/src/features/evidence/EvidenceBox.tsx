import type { DetailItem } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 근거 박스의 표지 `{출처 종류 글자} · {자료 이름}`(PRD-12-03). 두 글자 모두 응답 값 그대로다:
 * 종류 글자는 `source_kind_label`(`공식 파일` 등, BE-06-14 A), 자료 이름은 `dataset`이고 출처 표의 자료 열과 같은 글자다.
 * 종류 글자가 오지 않으면(출처 종류가 없는 근거) 자료 이름만 보인다. 색만으로 구분하지 않는다.
 */
export function SourceTag({ item }: { item: Pick<DetailItem, "dataset" | "source_kind" | "source_kind_label"> }) {
  if (!item.dataset) return null;
  return (
    <span
      data-testid="source-tag"
      data-source-kind={item.source_kind ?? undefined}
      className="max-w-full flex-none rounded-md bg-tint px-[7px] py-0.5 text-[11px] leading-[15px] font-semibold text-link [word-break:keep-all]"
    >
      {item.source_kind_label ? (
        <>
          <span data-slot="source-kind-label">{item.source_kind_label}</span>
          {" · "}
        </>
      ) : null}
      <span data-slot="source-dataset">{item.dataset}</span>
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
  ...data
}: {
  title?: React.ReactNode;
  tag?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  testId?: string;
  /** 박스에 붙일 `data-*` 값(예: 묶인 근거 ID). 화면 글자가 아니다 */
  [key: `data-${string}`]: string | number | undefined;
}) {
  return (
    <div data-testid={testId} {...data} className={cn("flex flex-col gap-2 rounded-xl border border-line bg-bg px-3.5 py-3", className)}>
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
