import type { Citation } from "@/lib/api";
import { DateLines } from "@/components/DateLines";
import { SOURCE_EXTRA_LABELS, SOURCE_HEADERS } from "./copy";
import { groupByPublisher } from "./sections";

function Extra({ label, values }: { label: string; values: readonly string[] }) {
  if (values.length === 0) return null;
  return (
    <span data-slot="source-extra" className="flex flex-wrap gap-x-1 text-xs leading-[17px] text-mute">
      <span className="whitespace-nowrap">{label}</span>
      {values.map((value, index) => (
        <span key={index} className="whitespace-nowrap">
          {value}
        </span>
      ))}
    </span>
  );
}

/**
 * 출처 표. 기관(대그룹)은 한 번만 쓰고 그 아래에 자료(중그룹) 행을 둔다(PRD-12-01·02).
 * 행 순서는 `citations[]` 그대로다. 날짜는 한 날짜 = 한 줄(`DateLines`)이고 화면이 글자를 조립하지 않는다.
 * 기관·자료 이름은 단어 중간에서 끊기지 않는다. 좁으면 날짜가 자료 이름 아래로 내려간다(카드형, 폭 분기 코드 없음).
 * 고시 번호·판·쪽은 값이 있을 때만 보인다(BE-06-05 A).
 */
export function SourceTable({ citations }: { citations: readonly Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div data-testid="source-table" className="overflow-hidden rounded-xl border border-line bg-bg text-[13px] leading-[19px] tabular-nums [word-break:keep-all]">
      <div className="flex flex-wrap justify-between gap-x-3 bg-bg-softer px-3 py-[7px] text-xs font-semibold text-mute">
        <span>{SOURCE_HEADERS.name}</span>
        <span>{SOURCE_HEADERS.dates}</span>
      </div>
      {groupByPublisher(citations).map((group) => (
        <div key={group.publisher} data-testid="source-group" className="border-t border-line-2 first:border-t-0">
          <div className="border-t border-line px-3 pt-2 pb-0.5">
            <b data-testid="source-publisher" className="font-bold text-ink">
              {group.publisher}
            </b>
          </div>
          {group.rows.map((citation, index) => (
            <div key={index} data-testid="source-row" className="flex flex-wrap items-start justify-between gap-x-3 gap-y-0.5 py-1 pr-3 pl-6 last:pb-[9px]">
              <span className="flex min-w-0 flex-col">
                <span data-testid="source-dataset" className="text-ink-2">
                  {citation.dataset}
                </span>
                <Extra label={SOURCE_EXTRA_LABELS.noticeNos} values={citation.notice_nos} />
                <Extra label={SOURCE_EXTRA_LABELS.edition} values={citation.edition ? [citation.edition] : []} />
                <Extra label={SOURCE_EXTRA_LABELS.pages} values={citation.pages} />
              </span>
              <DateLines dates={citation.dates} className="w-[10.5em] flex-none text-[13px] leading-[19px] text-ink-2" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
