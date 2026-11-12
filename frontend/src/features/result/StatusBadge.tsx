import type { Badge } from "@/lib/api";
import { cn } from "@/lib/utils";

// 금기 종류 키 → 색 토큰(PRD-09-07·08: 병용금기 빨강, 임부금기 보라 계열·등급 1·2·M 같은 색, 연령금기 빨강).
// 그 밖의 종류(용량 주의 등 금기가 아닌 주의)는 주의 색이다. 색은 종류를 고르는 데만 쓰고 글자는 응답 값이다.
const KIND_CLASS: Record<string, string> = {
  contra_pair: "bg-red text-bg",
  pregnancy: "bg-preg text-bg",
  age: "bg-red text-bg",
};
const CAUTION_CLASS = "bg-warn-bg text-warn-ink";

/**
 * 판정 줄의 배지 하나. 글자는 `badges[].text` 그대로다("삐!"와 등급·출처 꼬리도 응답 값 안에 있다).
 * 아이콘·소리는 쓰지 않는다. 글자가 길면 배지 안에서 띄어쓰기 단위로 줄바꿈하고 잘리지 않는다.
 */
export function StatusBadge({ badge }: { badge: Badge }) {
  return (
    <span
      data-testid="status-badge"
      data-kind={badge.kind}
      className={cn(
        "inline-flex max-w-full items-center rounded-xl px-2.5 py-[3px] text-xs leading-[17px] font-bold [overflow-wrap:break-word] [word-break:keep-all]",
        KIND_CLASS[badge.kind] ?? CAUTION_CLASS,
      )}
    >
      {badge.text}
    </span>
  );
}
