import { canRetry } from "@/lib/api";
import type { StreamState } from "@/lib/api";
import { PRIMARY_BUTTON } from "@/components/button";
import { Mascot } from "@/components/Mascot";
import { NoMascotZone } from "@/components/NoMascotZone";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { ERROR_BODY_NOT_READY, ERROR_BODY_NO_RETRY, ERROR_BODY_RETRY, ERROR_TITLE, RETRY_LABEL } from "./copy";

export interface ErrorStateProps {
  /** 응답을 받지 못하고 끝난 스트림 상태(error·interrupted) */
  stream: StreamState;
  /** 사용자가 "다시 시도"를 눌렀을 때만 불린다. 이 부품은 스스로 다시 보내지 않는다 */
  onRetry: () => void;
  /** 지난 차례의 오류면 false로 준다(다시 보낼 수 있는 것은 마지막 차례뿐이다) */
  allowRetry?: boolean;
  /** 대화에 119 안내가 떠 있으면 true로 준다(이 차례가 아닌 다른 차례에서 받았더라도 마스코트를 숨긴다) */
  hideMascot?: boolean;
}

/**
 * 응답(`fixed_notice`)을 받지 못한 오류 화면. 서버가 오류 문구를 보냈으면 그대로 보인다.
 * 응답이 없으므로 고정 안내·고지는 백엔드 상수에서 생성한 값을 쓴다(f5 A. 쓰는 곳은 여기 하나다).
 */
export function ErrorState({ stream, onRetry, allowRetry = true, hideMascot = false }: ErrorStateProps) {
  const retryable = allowRetry && canRetry(stream);
  const received = stream.error?.kind === "server" ? stream.error.message : null;
  // 서버가 아직 연결되지 않았을 때(501)는 그 문구를 쓴다. "다시 시도"는 그대로 둔다
  const notReady = stream.error?.kind === "http" && stream.error.status === 501;
  const fallback = notReady ? ERROR_BODY_NOT_READY : retryable ? ERROR_BODY_RETRY : ERROR_BODY_NO_RETRY;
  return (
    <section data-testid="error-state" aria-label={ERROR_TITLE} className="flex flex-col gap-2.5">
      <div className="flex items-center gap-3.5 rounded-2xl bg-bg-soft p-4">
        {/* 오류는 마스코트 허용 자리다. 119 안내가 떠 있으면 숨긴다 */}
        {!hideMascot && !stream.emergency && <Mascot variant="search" size={72} />}
        <div className="min-w-0">
          <b className="text-base">{ERROR_TITLE}</b>
          <p className="mt-0.5 mb-2 text-sm break-words text-ink-2">{received ?? fallback}</p>
          {retryable && (
            <button
              type="button"
              onClick={onRetry}
              className={PRIMARY_BUTTON}
            >
              {RETRY_LABEL}
            </button>
          )}
        </div>
      </div>
      <NoMascotZone>
        <div className="rounded-xl bg-fixed px-3 py-2 text-xs leading-[17px] text-ink-2">
          <p className="m-0">{FIXED_NOTICE}</p>
        </div>
        <p className="m-0 px-1 text-xs leading-[17px] text-mute">{DISCLAIMER}</p>
      </NoMascotZone>
    </section>
  );
}
