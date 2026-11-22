import type { Emergency } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { EMERGENCY_TEL_HREF, EMERGENCY_TEL_TEXT } from "./copy";

/**
 * 119 안내 임시 부품(배너 부품은 FE-IMPL-05가 만든다). 받은 `emergency.text`를 그대로 보이고 전화 링크만 둔다.
 * 화면 맨 위 자리에 두고, 한 번 뜨면 내리지 않는다(S2). 마스코트 금지 영역이다(S3).
 */
export function EmergencySlot({ emergency }: { emergency: Emergency }) {
  return (
    <NoMascotZone>
      <div
        role="alert"
        data-testid="emergency-slot"
        className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-2xl bg-red px-3.5 py-3 text-on-solid"
      >
        <p className="m-0 min-w-0 flex-1 basis-44 text-base leading-6 font-bold break-words">{emergency.text}</p>
        <a
          href={EMERGENCY_TEL_HREF}
          className="flex min-h-11 items-center rounded-full bg-bg px-4 font-extrabold text-red-ink no-underline"
        >
          {EMERGENCY_TEL_TEXT}
        </a>
      </div>
    </NoMascotZone>
  );
}
