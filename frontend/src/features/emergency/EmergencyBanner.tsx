import { PhoneIcon } from "lucide-react";
import type { Emergency } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { EMERGENCY_CALL_LABEL, EMERGENCY_TEL_HREF } from "./copy";

/**
 * 119 배너. 받은 `emergency.text`(넓은 폭에서는 보조 문장 `wide_text`도)를 그대로 보이고 전화 걸기 링크를 둔다(`role="alert"`, `href="tel:119"`).
 * 화면 맨 위에 두고 한 번 뜨면 내리지 않는다(배치는 조립하는 쪽). 119는 이 배너 하나로만 보인다(토스트 없음).
 * 마스코트 금지 영역이다. FE-IMPL-02의 `EmergencySlot`과 같은 props(`{ emergency }`)라 그대로 바꿔 끼울 수 있다.
 */
export function EmergencyBanner({ emergency }: { emergency: Emergency }) {
  return (
    <NoMascotZone>
      <div
        role="alert"
        data-testid="emergency-banner"
        className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-2xl bg-red px-3.5 py-3 text-on-solid"
      >
        <div className="min-w-0 flex-1 basis-44">
          <p className="m-0 text-[17px] leading-6 font-bold break-words">{emergency.text}</p>
          {/* 넓은 폭에서만 보이는 보조 문장(FE-07-15 A, 응답 값 그대로). 폭 기준은 셸이 사이드바·패널을 쓰는 폭(1024)과 같다 */}
          <p data-testid="emergency-wide" className="m-0 hidden text-sm leading-5 break-words lg:block">
            {emergency.wide_text}
          </p>
        </div>
        <a
          href={EMERGENCY_TEL_HREF}
          className="flex min-h-11 flex-none items-center gap-1.5 rounded-full bg-bg px-4 font-extrabold whitespace-nowrap text-red-ink no-underline"
        >
          <PhoneIcon className="size-4" strokeWidth={2.5} aria-hidden="true" />
          {EMERGENCY_CALL_LABEL}
        </a>
      </div>
    </NoMascotZone>
  );
}
