// NDJSON 스트림 소비(FE-01-07 B). 화면·스토어는 `streamChat`만 쓴다(이벤트 소스 추상화).
// 공개 인터페이스: `streamChat(request, { signal }): AsyncIterable<ChatEvent>`. 이름과 반환 모양을 바꾸지 않는다.
import { postChatStream } from "./client";
import { ChatEventSchema, ChatRequestSchema } from "./schemas";
import type { ChatEvent, ChatRequest } from "./types";

export type ChatStreamErrorKind =
  | "http" // 응답 상태가 2xx가 아님(`status` 있음)
  | "network" // 연결 실패·본문 읽기 중 끊김
  | "invalid_json" // 줄이 JSON이 아님
  | "invalid_event" // zod 검증 실패(모양·schema_version 다름)
  | "aborted"; // signal로 끊음

/** 스트림이 정상 이벤트를 더 낼 수 없을 때 던진다. 질문·응답 내용은 싣지 않는다. */
export class ChatStreamError extends Error {
  readonly kind: ChatStreamErrorKind;
  readonly status: number | null;

  constructor(kind: ChatStreamErrorKind, status: number | null = null) {
    super(status === null ? `chat stream ${kind}` : `chat stream ${kind} ${status}`);
    this.name = "ChatStreamError";
    this.kind = kind;
    this.status = status;
  }
}

export interface StreamChatOptions {
  signal?: AbortSignal;
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

/** 바이트 스트림을 줄 단위로 읽어 검증된 이벤트를 낸다. 실패한 줄은 건너뛰지 않고 `ChatStreamError`를 던진다. */
export async function* parseNdjsonStream(
  body: ReadableStream<Uint8Array>,
  { signal }: StreamChatOptions = {},
): AsyncGenerator<ChatEvent, void, void> {
  const reader = body.pipeThrough(new TextDecoderStream("utf-8") as ReadableWritablePair<string, Uint8Array>).getReader();
  let buffer = "";
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
        const event = parseLine(line);
        if (event) yield event;
      }
    }
    const last = parseLine(buffer); // 끝 버퍼(개행 없는 마지막 줄)
    if (last) yield last;
  } finally {
    reader.cancel().catch(() => {});
  }
}

/** 질문을 보내고 이벤트를 받은 순서대로 낸다. 자동 재시도는 없다. 실패는 `ChatStreamError`로 던진다. */
export async function* streamChat(
  request: ChatRequest,
  { signal }: StreamChatOptions = {},
): AsyncGenerator<ChatEvent, void, void> {
  const body = ChatRequestSchema.parse(request);
  let response: Response;
  try {
    response = await postChatStream(body, signal);
  } catch {
    throw readFailure(signal);
  }
  if (!response.ok) {
    response.body?.cancel().catch(() => {});
    throw new ChatStreamError("http", response.status);
  }
  if (!response.body) throw new ChatStreamError("network");
  yield* parseNdjsonStream(response.body, { signal });
}
