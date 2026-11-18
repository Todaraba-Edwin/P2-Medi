import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { MessageBubble } from "./MessageBubble";

/**
 * 결과 자리표시(임시). 받은 응답의 보정 고지(`name_corrections`, 요약보다 먼저)와 `summary`를 가공 없이 보이고,
 * 응답의 고정 안내 줄과 고지를 받은 그대로·받은 순서대로 둔다.
 * 결과 카드·근거 상세·고정 안내 박스는 FE-IMPL-04·05가 만들고 조립은 FE-IMPL-06이 한다.
 * 되묻기(`end_reason: CLARIFY`)도 지금은 `summary`만 보인다(후보 카드는 BE-06 v1 뒤 보완).
 * 고정 안내는 펼침 요소 안에 두지 않는다(S5). 마스코트 금지 영역이다(S3).
 */
export function ResultSlot({ response }: { response: ChatResponse }) {
  return (
    <NoMascotZone>
      <div data-testid="result-slot" data-end-reason={response.end_reason ?? undefined} className="flex flex-col gap-2.5">
        {response.name_corrections.length > 0 && (
          <ul data-testid="name-corrections" className="m-0 flex list-none flex-col gap-1 p-0">
            {response.name_corrections.map((correction, index) => (
              <li key={index} className="rounded-xl border border-line bg-bg-softer px-3 py-2 text-[13px] leading-[19px] break-words text-ink-2">
                {correction.text}
              </li>
            ))}
          </ul>
        )}
        {response.summary !== null && <MessageBubble side="bot">{response.summary}</MessageBubble>}
        <div className="rounded-xl bg-fixed px-3 py-2 text-xs leading-[17px] text-ink-2">
          {response.fixed_notice.map((line, index) => (
            <p key={index} className="m-0">
              {line}
            </p>
          ))}
        </div>
        <p className="m-0 px-1 text-xs leading-[17px] text-mute">{response.disclaimer}</p>
      </div>
    </NoMascotZone>
  );
}
