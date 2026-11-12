// NDJSON 스트림 소비(FE-01-07 B). 화면·스토어는 `streamChat`만 쓴다(이벤트 소스 추상화).
// 공개 인터페이스: `streamChat(request, { signal }): AsyncIterable<ChatEvent>`. 이름과 반환 모양을 바꾸지 않는다.
import { postChatStream } from "./client";
import { ChatEventSchema, ChatRequestSchema, ErrorBodySchema } from "./schemas";
import type { ChatEvent, ChatRequest } from "./types";

export type ChatStreamErrorKind =
  | "invalid_request" // 요청 본문이 형식에 맞지 않아 보내지 않음(서버였다면 422)
  | "http" // 응답 상태가 2xx가 아님(`status` 있음)
  | "network" // 연결 실패·본문 읽기 중 끊김
  | "invalid_json" // 줄이 JSON이 아님
  | "invalid_event" // zod 검증 실패(모양·schema_version 다름) 또는 seq 빠짐·역순
  | "aborted"; // signal로 끊음

/** 스트림이 정상 이벤트를 더 낼 수 없을 때 던진다. 질문·응답 내용은 싣지 않는다. */
export class ChatStreamError extends Error {
  readonly kind: ChatStreamErrorKind;
  readonly status: number | null;
  /** HTTP 오류 본문의 `code`(예: `INVALID_REQUEST`). 본문에는 입력 값·문구가 없다 */
  readonly code: string | null;

  constructor(kind: ChatStreamErrorKind, status: number | null = null, code: string | null = null) {
    super(status === null ? `chat stream ${kind}` : `chat stream ${kind} ${status}`);
    this.name = "ChatStreamError";
    this.kind = kind;
    this.status = status;
    this.code = code;
  }
}

export interface StreamChatOptions {
  signal?: AbortSignal;
  /**
   * 서버에서 줄이 하나 올 때마다 불린다. 이벤트 줄뿐 아니라 **빈 줄(하트비트)**도 센다.
   * 무응답 시계를 다시 돌리는 데 쓴다(BE-06-10 A: 빈 줄은 서버 생존 신호).
   */
  onActivity?: () => void;
}

function readFailure(signal: AbortSignal | undefined): ChatStreamError {
  return new ChatStreamError(signal?.aborted ? "aborted" : "network");
}

function parseLine(raw: string): ChatEvent | null {
  const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
  if (line.trim() === "") return null; // 빈 줄은 건너뛴다(하트비트 포함)
  let data: unknown;
  try {
    data = JSON.parse(line);
  } catch {
    throw new ChatStreamError("invalid_json");
  }
  const parsed = ChatEventSchema.safeParse(data);
  if (!parsed.success) throw new ChatStreamError("invalid_event");
  return parsed.data;
}

/**
 * 바이트 스트림을 줄 단위로 읽어 검증된 이벤트를 낸다. 실패한 줄은 건너뛰지 않고 `ChatStreamError`를 던진다.
 * `seq`는 0에서 시작해 1씩 늘어야 한다. 빠지거나 거꾸로면 `invalid_event`다(빈 줄은 이벤트가 아니라 세지 않는다).
 */
export async function* parseNdjsonStream(
  body: ReadableStream<Uint8Array>,
  { signal, onActivity }: StreamChatOptions = {},
): AsyncGenerator<ChatEvent, void, void> {
  const reader = body.pipeThrough(new TextDecoderStream("utf-8") as ReadableWritablePair<string, Uint8Array>).getReader();
  let buffer = "";
  let expectedSeq = 0;
  const take = (line: string): ChatEvent | null => {
    onActivity?.();
    const event = parseLine(line);
    if (event) {
      if (event.seq !== expectedSeq) throw new ChatStreamError("invalid_event");
      expectedSeq += 1;
    }
    return event;
  };
  try {
    for (;;) {
      if (signal?.aborted) throw new ChatStreamError("aborted");
      let chunk: ReadableStreamReadResult<string>;
      try {
        chunk = await reader.read();
      } catch {
        throw readFailure(signal);
      }
      if (chunk.done) break;
      buffer += chunk.value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? ""; // 마지막 조각은 줄이 끝나지 않았을 수 있다
      for (const line of lines) {
        const event = take(line);
        if (event) yield event;
      }
    }
    if (buffer !== "") {
      const last = take(buffer); // 끝 버퍼(개행 없는 마지막 줄)
      if (last) yield last;
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

/** 질문을 보내고 이벤트를 받은 순서대로 낸다. 자동 재시도는 없다. 실패는 `ChatStreamError`로 던진다. */
export async function* streamChat(
  request: ChatRequest,
  { signal, onActivity }: StreamChatOptions = {},
): AsyncGenerator<ChatEvent, void, void> {
  const checked = ChatRequestSchema.safeParse(request);
  if (!checked.success) throw new ChatStreamError("invalid_request"); // 보내지 않는다
  const body = checked.data;
  let response: Response;
  try {
    response = await postChatStream(body, signal);
  } catch {
    throw readFailure(signal);
  }
  if (!response.ok) {
    // 4xx·5xx 본문은 `{code, fields}`다. 못 읽어도 상태 코드만으로 처리한다
    const parsed = ErrorBodySchema.safeParse(await response.json().catch(() => null));
    throw new ChatStreamError("http", response.status, parsed.success ? parsed.data.code : null);
  }
  if (!response.body) throw new ChatStreamError("network");
  yield* parseNdjsonStream(response.body, { signal, onActivity });
}
