import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { BASIS_FILE_TAG, RESULT_HEADING } from "./copy";
import { ProductLine } from "./ProductLine";
import { hasApiFailInfo } from "./realtime-notice";

export interface ResultCardProps {
  response: ChatResponse;
  /** 머리글 뒤에 붙는 기준 글자(예: 대상). 조립하는 쪽이 준다. 없으면 머리글만 보인다 */
  basis?: string | null;
  /** 카드 맨 아래 자리(근거 상세 진입 버튼 등). FE-IMPL-05·06이 채운다 */
  footer?: React.ReactNode;
}

/**
 * 결과 카드: 판정 줄을 받은 순서대로 그린다. 줄이 없으면(되묻기·거절 등) 카드를 그리지 않는다.
 * 날짜·시각 줄은 두지 않는다(FE-07-06 A: 날짜는 근거 상세의 출처 표에만 있다).
 * 대상 조건이 아닌 종류는 응답에 줄이 없으므로 그리지 않는다("해당 없음" 상태를 만들지 않는다, AG-08-18 A).
 * 실시간 확인을 하지 못한 결과에는 머리에 작은 "기준일 자료" 표지만 붙고 문장은 근거 상세에만 있다(FE-11-10 A, §7.2).
 * 금기 결과 영역이라 마스코트를 쓰지 않는다(S3).
 */
export function ResultCard({ response, basis, footer }: ResultCardProps) {
  if (response.findings.length === 0) return null;
  return (
    <NoMascotZone>
      <section data-testid="result-card" aria-label={RESULT_HEADING} className="overflow-hidden rounded-2xl border border-line bg-bg">
        <header className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 bg-bg-softer px-3.5 py-[9px] text-xs text-mute">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <b className="text-[13px] text-ink">{RESULT_HEADING}</b>
            {hasApiFailInfo(response) && (
              <span data-testid="basis-file-tag" className="rounded-md bg-warn-bg px-[7px] py-0.5 text-[11px] leading-[15px] font-semibold text-warn-ink [word-break:keep-all]">
                {BASIS_FILE_TAG}
              </span>
            )}
          </span>
          {basis ? <span data-testid="result-basis">{basis}</span> : null}
        </header>
        <ul className="m-0 list-none border-t border-line p-0">
          {response.findings.map((finding, index) => (
            // 본문의 줄에서는 실시간 확인 노트를 뺀다(근거 상세의 같은 줄 부품에는 그대로 보인다)
            <ProductLine key={index} finding={finding} omitApiFlagNotes />
          ))}
        </ul>
        {footer ? <div className="border-t border-line">{footer}</div> : null}
      </section>
    </NoMascotZone>
  );
}
