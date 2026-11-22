import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";

/**
 * 고정 안내 박스: `fixed_notice[]`의 줄을 **받은 순서 그대로, 받은 글자 그대로** 그린다(재정렬·합치기·줄이기 없음).
 * 접히지 않는 영역에 둔다: 이 부품을 펼침 요소(Accordion·Sheet·details) 안에 넣지 않는다(S5).
 * "근처 약국·약사"는 글자만이고 링크가 아니다(FE-07-07 A). 마스코트 금지 영역이다.
 */
export function FixedNoticeBox({ lines, className }: { lines: readonly string[]; className?: string }) {
  if (lines.length === 0) return null;
  return (
    <NoMascotZone>
      <div
        role="note"
        data-testid="fixed-notice"
        // 다크에서는 테두리와 앞의 "!"로 띠를 구분한다(FE-12 §3 ③: 색만으로 구분하지 않는다). 글자 내용은 그대로다(CSS 장식)
        className={cn(
          "rounded-xl bg-fixed px-3 py-2 text-xs leading-[17px] break-words text-ink-2 dark:border dark:border-fixed-edge dark:[&>p:first-child]:before:mr-1 dark:[&>p:first-child]:before:font-bold dark:[&>p:first-child]:before:content-['!']",
          className,
        )}
      >
        {lines.map((line, index) => (
          <p key={index} className="m-0">
            {line}
          </p>
        ))}
      </div>
    </NoMascotZone>
  );
}
