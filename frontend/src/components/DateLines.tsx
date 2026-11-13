import type { DateLine } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 날짜 줄 목록. `dates[]`의 한 항목이 한 줄이다(PRD-12 §5).
 * 라벨과 값은 받은 그대로 따로 그리고 문자열을 조립하지 않는다. 줄 순서도 받은 그대로다.
 * 한 줄은 중간에서 끊기지 않는다(좁으면 줄 단위로 아래로 내려간다). `날짜 없음`은 값이 없어 라벨만 보인다.
 * 라벨 칸 폭을 고정하고 숫자를 같은 폭으로 써서, 여러 목록이 위아래로 놓여도 라벨·날짜가 같은 열에 선다.
 */
export function DateLines({ dates, className }: { dates: readonly DateLine[]; className?: string }) {
  if (dates.length === 0) return null;
  return (
    <ul data-testid="date-lines" className={cn("m-0 flex list-none flex-col p-0 text-xs leading-[17px] text-mute", className)}>
      {dates.map((line, index) => (
        <li key={index} data-label={line.label} className="flex gap-1 whitespace-nowrap tabular-nums">
          <span className="inline-block min-w-[3.25em]">{line.label}</span>
          {line.value !== null && <span>{line.value}</span>}
        </li>
      ))}
    </ul>
  );
}
