import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";

/** 고지: 응답의 `disclaimer`를 받은 그대로 그린다. 화면 상시 영역에 둔다(배치는 조립하는 쪽). 마스코트 금지 영역이다 */
export function LegalFooter({ disclaimer, className }: { disclaimer: string; className?: string }) {
  return (
    <NoMascotZone>
      <p data-testid="legal-footer" className={cn("m-0 px-1 text-xs leading-[17px] break-words text-mute", className)}>
        {disclaimer}
      </p>
    </NoMascotZone>
  );
}
