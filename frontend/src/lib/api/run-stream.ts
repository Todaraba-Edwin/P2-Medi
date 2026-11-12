// `streamChat`을 돌려 리듀서 상태를 만든다. 무응답 상한을 넘으면 abort한다. 자동 재시도는 없다.
import { ChatStreamError, streamChat } from "./stream";
import { STREAM_IDLE_TIMEOUT_MS, initialStreamState, streamReducer } from "./stream-state";
import type { StreamAction, StreamFailure, StreamState } from "./stream-state";
import type { ChatRequest } from "./types";

export interface RunChatStreamOptions {
  /** 새 질문·화면 이탈 때 호출자가 끊는 신호 */
  signal?: AbortSignal;
  /** 상태가 바뀔 때마다 불린다 */
  onState?: (state: StreamState) => void;
  /** 이어 갈 이전 상태. retry와 함께 주면 이미 받은 119 안내를 유지한다 */
  previous?: StreamState;
  retry?: boolean;
  idleTimeoutMs?: number;
}

function toFailure(error: unknown): StreamFailure {
  if (error instanceof ChatStreamError && error.kind !== "aborted") return { kind: error.kind, status: error.status };
  return { kind: "network" };
}

export async function runChatStream(request: ChatRequest, options: RunChatStreamOptions = {}): Promise<StreamState> {
  const { signal, onState, previous = initialStreamState, retry = false, idleTimeoutMs = STREAM_IDLE_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });

  let state = previous;
  const dispatch = (action: StreamAction) => {
    const next = streamReducer(state, action);
    if (next !== state) {
      state = next;
      onState?.(state);
    }
  };

  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const armIdleTimer = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, idleTimeoutMs);
  };

  dispatch({ type: "start", retry });
  armIdleTimer();
  try {
    for await (const event of streamChat(request, { signal: controller.signal })) {
      armIdleTimer();
      dispatch({ type: "event", event });
      if (state.status !== "streaming") break; // done·error 뒤에는 더 읽지 않는다
    }
    dispatch({ type: "end" });
  } catch (error) {
    if (timedOut) dispatch({ type: "failure", failure: { kind: "idle_timeout" } });
    else if (controller.signal.aborted) dispatch({ type: "abort" });
    else dispatch({ type: "failure", failure: toFailure(error) });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abortFromCaller);
    controller.abort(); // 남은 연결을 닫는다
  }
  return state;
}
