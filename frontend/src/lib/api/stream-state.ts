// 스트림 상태 규칙(PJ2-프론트-기술스택.md 4장 (3))을 순수 리듀서로 둔다. 타이머·통신은 run-stream.ts가 맡는다.
import type { ChatEvent, ChatResponse, Emergency, ProgressStage } from "./types";

/**
 * 무응답 상한. 가정 값이다(서버 `CLIENT_IDLE_TIMEOUT_S` 60초와 같은 값). BE-13(Vercel rewrites 시간 상한)에서 확정하면 이 한 곳만 고친다.
 * 서버는 이벤트 사이가 길면 빈 줄(하트비트, 15초 가정)을 보내고, 빈 줄도 이 시계를 다시 돌린다.
 */
export const STREAM_IDLE_TIMEOUT_MS = 60_000;

export type StreamStatus =
  | "idle"
  | "streaming"
  | "done" // 검증된 answer가 있다(done 없이 끊겨도 결과 유지)
  | "error" // 오류 이벤트·HTTP 오류·형식 오류
  | "interrupted" // answer 전에 끊김(부분 결과 없음)
  | "aborted"; // 사용자가 끊음(새 질문·화면 이탈)

export type StreamFailureKind = "invalid_request" | "http" | "network" | "invalid_json" | "invalid_event" | "idle_timeout";

export interface StreamFailure {
  kind: StreamFailureKind;
  status?: number | null;
  /** HTTP 오류 본문의 `code` */
  code?: string | null;
}

export interface StreamError {
  /** `server`는 서버가 보낸 error 이벤트, 나머지는 클라이언트가 본 실패 */
  kind: "server" | StreamFailureKind;
  status: number | null;
  /** 서버 error 이벤트의 코드, 또는 HTTP 오류 본문의 `code`. 없으면 null */
  code: string | null;
  /** 서버 error 이벤트의 문구(받은 그대로). 서버가 null을 보냈거나 클라이언트 실패면 null이며 그때 문구는 화면 쪽 상수 몫 */
  message: string | null;
}

export interface StreamState {
  status: StreamStatus;
  stage: ProgressStage | null;
  /** 지금 진행 줄의 문구(`progress.label`, 서버 상수 그대로). `stage`와 함께 바뀐다 */
  label: string | null;
  /** 한 번 받으면 어떤 경우에도 지우지 않는다(S2) */
  emergency: Emergency | null;
  response: ChatResponse | null;
  error: StreamError | null;
  /** answer 뒤 done 없이 끝났는지(로그용, 화면 결과에는 영향 없음) */
  endedWithoutDone: boolean;
}

export type StreamAction =
  | { type: "start"; retry?: boolean } // retry면 이미 받은 119 안내를 유지한다
  | { type: "event"; event: ChatEvent }
  | { type: "end" } // 스트림이 닫힘
  | { type: "failure"; failure: StreamFailure }
  | { type: "abort" };

export const initialStreamState: StreamState = {
  status: "idle",
  stage: null,
  label: null,
  emergency: null,
  response: null,
  error: null,
  endedWithoutDone: false,
};

function onEvent(state: StreamState, event: ChatEvent): StreamState {
  switch (event.type) {
    case "progress":
      return state.response ? state : { ...state, stage: event.stage, label: event.label };
    case "emergency":
      return { ...state, emergency: state.emergency ?? event.emergency };
    case "answer":
      // 응답 안의 emergency는 이미 띄운 배너와 같은 자리 하나다(중복 없음)
      return {
        ...state,
        response: event.response,
        emergency: state.emergency ?? event.response.emergency,
        stage: null,
        label: null,
      };
    case "error":
      return {
        ...state,
        status: state.response ? "done" : "error",
        stage: null,
        label: null,
        error: { kind: "server", status: null, code: event.code, message: event.message },
      };
    case "done":
      // answer 없이 done만 오면 결과를 만들지 않고 끊김으로 본다
      return { ...state, status: state.response ? "done" : "interrupted", stage: null, label: null };
  }
}

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  if (action.type === "start") {
    return { ...initialStreamState, status: "streaming", emergency: action.retry ? state.emergency : null };
  }
  if (state.status !== "streaming") return state; // 끝난 뒤의 이벤트는 반영하지 않는다
  switch (action.type) {
    case "event":
      return onEvent(state, action.event);
    case "end":
      return state.response
        ? { ...state, status: "done", stage: null, label: null, endedWithoutDone: true }
        : { ...state, status: "interrupted", stage: null, label: null };
    case "failure": {
      if (state.response) return { ...state, status: "done", stage: null, label: null, endedWithoutDone: true };
      const { kind, status = null, code = null } = action.failure;
      const cut = kind === "network" || kind === "idle_timeout";
      return {
        ...state,
        status: cut ? "interrupted" : "error",
        stage: null,
        label: null,
        error: { kind, status, code, message: null },
      };
    }
    case "abort":
      return { ...state, status: "aborted", stage: null, label: null };
  }
}

/** "다시 시도" 버튼을 보일 수 있는가. 4xx는 다시 보내도 같으므로 보이지 않는다. 재시도는 사용자가 눌렀을 때만 한다. */
export function canRetry(state: StreamState): boolean {
  if (state.status !== "error" && state.status !== "interrupted") return false;
  if (state.error?.kind === "invalid_request") return false; // 같은 본문을 다시 보내도 같다
  const status = state.error?.status ?? null;
  return !(state.error?.kind === "http" && status !== null && status >= 400 && status < 500);
}
