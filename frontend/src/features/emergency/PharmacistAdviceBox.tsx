import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";

/** 첫 문장과 나머지로 가른다. 글자는 바꾸지 않는다(둘을 이으면 원문과 같다) */
function splitFirstSentence(line: string): [string, string] {
  const match = /^.*?[.!?](?=\s|$)/.exec(line);
  return match ? [match[0], line.slice(match[0].length)] : [line, ""];
}

/**
 * 약사 확인 권고 박스(PRD-11 §6.7): `pharmacist_advice[]`의 줄을 받은 순서·글자 그대로 그린다.
 * 강조 색 박스이고 줄의 첫 문장을 굵게 쓴다. 접히지 않는 영역에 둔다(S5). 마스코트·"삐!" 표지를 쓰지 않는다.
 */
export function PharmacistAdviceBox({ lines, className }: { lines: readonly string[]; className?: string }) {
  if (lines.length === 0) return null;
  return (
    <NoMascotZone>
      <div
        role="note"
        data-testid="pharmacist-advice"
        className={cn("flex flex-col gap-1 rounded-[10px] bg-ink-2 px-3 py-2.5 text-sm leading-[21px] break-words text-bg", className)}
      >
        {lines.map((line, index) => {
          const [first, rest] = splitFirstSentence(line);
          return (
            <p key={index} className="m-0">
              <b className="text-yellow-2">{first}</b>
              {rest}
            </p>
          );
        })}
      </div>
    </NoMascotZone>
  );
}
