import type { Badge } from "@/lib/api";
import { cn } from "@/lib/utils";

// 금기 종류 키 → 색 토큰(PRD-09-07·08: 병용금기 빨강, 임부금기 보라 계열·등급 1·2·M 같은 색, 연령금기 빨강).
// 그 밖의 종류(용량 주의 등 금기가 아닌 주의)는 주의 색이다. 색은 종류를 고르는 데만 쓰고 글자는 응답 값이다.
const KIND_CLASS: Record<string, string> = {
  contra_pair: "bg-red text-on-solid",
  pregnancy: "bg-preg text-on-solid",
  age: "bg-red text-on-solid",
};
const CAUTION_CLASS = "bg-warn-bg text-warn-ink";

/**
 * 판정 줄의 배지 하나. 글자는 `badges[].text` 그대로다("삐!"와 등급·출처 꼬리도 응답 값 안에 있다).
 * 아이콘·소리는 쓰지 않는다. 글자가 길면 배지 안에서 띄어쓰기 단위로 줄바꿈하고 잘리지 않는다.
 */
export function StatusBadge({ badge }: { badge: Badge & { merged?: readonly Badge[] } }) {
  // 출처 꼬리만 다른 같은 배지를 합친 배지(FE-17 U-30 (a), `mergeSourceBadges`)는 합친 수와 근거 ID를 남긴다(화면 글자가 아니다)
  const merged = badge.merged && badge.merged.length > 1 ? badge.merged : null;
  return (
    <span
      data-testid="status-badge"
      data-kind={badge.kind}
      data-merged={merged ? merged.length : undefined}
      data-evidence-ids={merged ? merged.map((item) => item.evidence_id).filter((id): id is string => !!id).join(" ") || undefined : undefined}
      className={cn(
        "inline-flex max-w-full items-center rounded-xl px-2.5 py-[3px] text-xs leading-[17px] font-bold [overflow-wrap:break-word] [word-break:keep-all]",
        KIND_CLASS[badge.kind] ?? CAUTION_CLASS,
      )}
    >
      {badge.text}
    </span>
  );
}
