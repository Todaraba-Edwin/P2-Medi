import { PhoneIcon } from "lucide-react";
import { EMERGENCY_CALL_LABEL, EMERGENCY_TEL_HREF } from "@/features/emergency";
import { cn } from "@/lib/utils";

/**
 * 119 배너가 없을 때의 119 진입점(지시서 G-3). 글자는 승인된 `EMERGENCY_CALL_LABEL`, 누르는 영역 44px.
 * 머리줄·드로어·사이드바 오버레이·근거 상세 시트가 같은 것을 쓴다: 사용자가 연 층이 머리줄을 덮어도 그 층 안의 진입점을 누를 수 있다.
 * 배너가 뜨면 119는 배너 하나뿐이므로 이 진입점은 그리지 않는다(층은 배너 아래 영역에만 그려진다).
 */
export function EmergencyEntry({ testId, className }: { testId: string; className?: string }) {
  return (
    <a
      href={EMERGENCY_TEL_HREF}
      data-testid={testId}
      className={cn(
        "flex min-h-11 flex-none items-center gap-1 rounded-full px-2 text-[13px] font-bold whitespace-nowrap text-red-ink no-underline",
        className,
      )}
    >
      <PhoneIcon className="size-4" strokeWidth={2.5} aria-hidden="true" />
      {EMERGENCY_CALL_LABEL}
    </a>
  );
}
