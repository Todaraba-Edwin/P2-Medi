import { PhoneIcon } from "lucide-react";
import { NoMascotZone } from "@/components/NoMascotZone";
import { EMERGENCY_TEL_HREF } from "./copy";

/**
 * 시작 화면의 119 안내 줄(FE-01-19 A·FE-01-24 A). 글자는 백엔드 상수에서 생성한 값을 조립하는 쪽이 넘긴다(이 부품은 문장을 갖지 않는다, S1).
 * 줄 전체가 전화 걸기 링크(`tel:119`)이고 누르는 영역은 44px 이상이다. 119 영역이라 마스코트를 쓰지 않는다.
 */
export function StartEmergencyLink({ text }: { text: string }) {
  return (
    <NoMascotZone>
      <a
        href={EMERGENCY_TEL_HREF}
        data-testid="start-emergency"
        className="flex min-h-11 items-center gap-1.5 rounded-xl px-1 text-[13px] leading-[19px] font-bold break-words text-red-ink no-underline"
      >
        <PhoneIcon className="size-4 flex-none" strokeWidth={2.5} aria-hidden="true" />
        <span className="min-w-0">{text}</span>
      </a>
    </NoMascotZone>
  );
}
