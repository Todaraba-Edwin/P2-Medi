import type { Finding } from "@/lib/api";
import { LOOKUP_LABELS, countLabel } from "./copy";

/**
 * 약을 찾지 못한 줄의 찾아본 내용(PRD-14-01): 입력한 이름 · 찾아본 곳(건수) · 못 찾은 이유 · 다음에 해 보세요.
 * 값은 모두 응답 값이다. 값이 없는 칸은 그리지 않는다. 라벨 열은 한 줄이고 값 열은 단어 단위로 줄바꿈한다.
 */
export function LookupPairs({ finding }: { finding: Finding }) {
  const rows: [string, React.ReactNode][] = [];
  if (finding.input_name) rows.push([LOOKUP_LABELS.input, finding.input_name]);
  if (finding.searched.length > 0) {
    rows.push([
      LOOKUP_LABELS.searched,
      <span key="searched" className="flex flex-col">
        {finding.searched.map((entry, index) => (
          <span key={index} data-slot="searched" className="flex flex-wrap gap-x-2">
            <span>{entry.dataset}</span>
            {entry.count !== null && <span className="whitespace-nowrap text-mute">{countLabel(entry.count)}</span>}
          </span>
        ))}
      </span>,
    ]);
  }
  if (finding.why) rows.push([LOOKUP_LABELS.why, finding.why]);
  if (finding.next) rows.push([LOOKUP_LABELS.next, finding.next]);
  if (rows.length === 0) return null;
  return (
    <div data-testid="lookup-pairs" className="flex flex-col gap-1.5">
      <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 rounded-xl border border-line bg-bg px-3.5 py-3 text-sm tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="whitespace-nowrap text-mute">{label}</dt>
            <dd className="m-0 font-semibold [overflow-wrap:anywhere] [word-break:keep-all]">{value}</dd>
          </div>
        ))}
      </dl>
      {finding.retried_line && (
        <p data-slot="retried" className="m-0 text-xs leading-[17px] break-words text-mute">
          {finding.retried_line}
        </p>
      )}
    </div>
  );
}
