import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { RESULT_HEADING } from "./copy";
import { ProductLine } from "./ProductLine";

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
 * 금기 결과 영역이라 마스코트를 쓰지 않는다(S3).
 */
export function ResultCard({ response, basis, footer }: ResultCardProps) {
  if (response.findings.length === 0) return null;
  return (
    <NoMascotZone>
      <section data-testid="result-card" aria-label={RESULT_HEADING} className="overflow-hidden rounded-2xl border border-line bg-bg">
        <header className="flex flex-wrap items-baseline justify-between gap-x-2 bg-bg-softer px-3.5 py-[9px] text-xs text-mute">
          <b className="text-[13px] text-ink">{RESULT_HEADING}</b>
          {basis ? <span data-testid="result-basis">{basis}</span> : null}
        </header>
        <ul className="m-0 list-none border-t border-line p-0">
          {response.findings.map((finding, index) => (
            <ProductLine key={index} finding={finding} />
          ))}
        </ul>
        {footer ? <div className="border-t border-line">{footer}</div> : null}
      </section>
    </NoMascotZone>
  );
}
