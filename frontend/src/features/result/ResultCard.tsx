import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { RESULT_HEADING } from "./copy";
import { ProductLine } from "./ProductLine";
import { pairDoseLines, resultRows } from "./row-merge";

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
 * 실시간 확인을 하지 못한 결과의 문장("실시간 확인을 하지 못해 … 기준일 자료로 확인한 것이에요")은 근거 상세에만 있다(FE-11-10 A, §7.2).
 * 머리의 "기준일 자료" 표지는 FE-17 U-26-3(2026-11-24 사용자 "'기준일 자료' 제거")으로 없앴다. 기준일은 근거 상세 맨 위 안내·출처 표의 기준일 열에 그대로 있다.
 * 같은 약의 허가사항 항목 줄(`{약 이름} · 주의사항` 꼴)은 그 약의 판정 줄 안 덧붙임 줄로 합쳐 행 하나로 보인다(FE-17 U-28, `mergeLabelFindings`).
 * 행 묶기·순서(FE-17 U-30, 2026-11-24 사용자 지시, `resultRows`): 같은 약(줄 머리 약 이름이 같은 제품 줄)의 줄은 한 행, 병용(쌍) 행이 맨 위다.
 * "화면은 줄을 조합·재정렬하지 않는다"(FE-11-04 A)의 예외로 둔다(글자·판정은 그대로이고 놓이는 자리만 바뀐다).
 * 쌍 행에는 두 약이 모두 하루 최대량 주의 성분을 가졌을 때 약 이름별로 같은 글자를 다시 보인다(`pairDoseLines`).
 * 금기 결과 영역이라 마스코트를 쓰지 않는다(S3).
 */
export function ResultCard({ response, basis, footer }: ResultCardProps) {
  if (response.findings.length === 0) return null;
  return (
    <NoMascotZone>
      <section data-testid="result-card" aria-label={RESULT_HEADING} className="overflow-hidden rounded-2xl border border-line bg-bg">
        <header className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 bg-bg-softer px-3.5 py-[9px] text-xs text-mute">
          <b className="text-[13px] text-ink">{RESULT_HEADING}</b>
          {basis ? <span data-testid="result-basis">{basis}</span> : null}
        </header>
        <ul className="m-0 list-none border-t border-line p-0">
          {resultRows(response.findings).map(({ main, siblings }, index) => (
            // 본문의 줄에서는 실시간 확인 노트를 뺀다(근거 상세의 같은 줄 부품에는 그대로 보인다)
            <ProductLine
              key={index}
              finding={main.finding}
              labels={main.labels}
              siblings={siblings}
              pairDose={pairDoseLines(main.finding, response.findings)}
              omitApiFlagNotes
            />
          ))}
        </ul>
        {footer ? <div className="border-t border-line">{footer}</div> : null}
      </section>
    </NoMascotZone>
  );
}
