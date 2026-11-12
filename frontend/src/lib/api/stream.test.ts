import { describe, expect, it } from "vitest";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatStreamError, parseNdjsonStream } from "./stream";
import type { ChatEvent } from "./types";

const encoder = new TextEncoder();
const foundEvents = scenarios.found.events;
const ndjson = (events: ChatEvent[], eol = "\n") => events.map((e) => JSON.stringify(e) + eol).join("");

/** 바이트 조각들을 차례로 내는 스트림 */
function byteStream(chunks: Uint8Array[], ending: "close" | "error" = "close"): ReadableStream<Uint8Array> {
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) controller.enqueue(chunks[index++]);
      else if (ending === "close") controller.close();
      else controller.error(new Error("cut"));
    },
  });
}

function splitBytes(bytes: Uint8Array, size: number): Uint8Array[] {
  const out: Uint8Array[] = [];
  for (let i = 0; i < bytes.length; i += size) out.push(bytes.slice(i, i + size));
  return out;
}

async function collect(stream: ReadableStream<Uint8Array>, signal?: AbortSignal): Promise<ChatEvent[]> {
  const out: ChatEvent[] = [];
  for await (const event of parseNdjsonStream(stream, { signal })) out.push(event);
  return out;
}

async function failure(stream: ReadableStream<Uint8Array>, signal?: AbortSignal) {
  const seen: ChatEvent[] = [];
  try {
    for await (const event of parseNdjsonStream(stream, { signal })) seen.push(event);
  } catch (error) {
    return { error: error as ChatStreamError, seen };
  }
  throw new Error("오류가 나야 한다");
}

describe("parseNdjsonStream", () => {
  it("한 덩어리로 온 줄들을 순서대로 낸다", async () => {
    expect(await collect(byteStream([encoder.encode(ndjson(foundEvents))]))).toEqual(foundEvents);
  });

  it.each([1, 2, 3, 7, 64])("줄이 조각 경계(%i바이트씩)에서 잘려도 같다(한글 바이트 중간 포함)", async (size) => {
    const bytes = encoder.encode(ndjson(foundEvents));
    expect(await collect(byteStream(splitBytes(bytes, size)))).toEqual(foundEvents);
  });

  it("한글 한 글자의 바이트 사이에서 잘려도 글자가 깨지지 않는다", async () => {
    const text = ndjson(foundEvents);
    const bytes = encoder.encode(text);
    const cut = encoder.encode(text.slice(0, text.indexOf("가나다"))).length + 1; // '가'의 3바이트 중 1바이트 뒤
    const events = await collect(byteStream([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events).toEqual(foundEvents);
    expect(JSON.stringify(events)).not.toContain("�");
  });

  it("\\r\\n 줄 끝을 받는다", async () => {
    expect(await collect(byteStream([encoder.encode(ndjson(foundEvents, "\r\n"))]))).toEqual(foundEvents);
  });

  it("빈 줄·공백 줄은 건너뛴다", async () => {
    const text = `\n${JSON.stringify(foundEvents[0])}\n\n  \n\r\n${JSON.stringify(foundEvents[1])}\n`;
    expect(await collect(byteStream([encoder.encode(text)]))).toEqual(foundEvents.slice(0, 2));
  });

  it("마지막 줄에 개행이 없어도 낸다(끝 버퍼)", async () => {
    const text = ndjson(foundEvents).replace(/\n$/, "");
    expect(await collect(byteStream([encoder.encode(text)]))).toEqual(foundEvents);
  });

  it("빈 본문은 이벤트 없이 끝난다", async () => {
    expect(await collect(byteStream([]))).toEqual([]);
  });

  it("잘못된 JSON 줄은 건너뛰지 않고 오류로 낸다(앞 이벤트는 이미 전달됨)", async () => {
    const text = `${JSON.stringify(foundEvents[0])}\n{"type":"progress",\n${JSON.stringify(foundEvents[1])}\n`;
    const { error, seen } = await failure(byteStream([encoder.encode(text)]));
    expect(error).toBeInstanceOf(ChatStreamError);
    expect(error.kind).toBe("invalid_json");
    expect(seen).toEqual(foundEvents.slice(0, 1));
  });

  it("zod 검증에 실패한 줄은 오류로 낸다", async () => {
    const bad = { ...foundEvents[0], stage: "not_a_stage" };
    const { error } = await failure(byteStream([encoder.encode(`${JSON.stringify(bad)}\n`)]));
    expect(error.kind).toBe("invalid_event");
  });

  it("다른 이벤트 schema_version은 오류로 낸다", async () => {
    const bad = { ...foundEvents[0], schema_version: "chat_event@v1" };
    const { error } = await failure(byteStream([encoder.encode(`${JSON.stringify(bad)}\n`)]));
    expect(error.kind).toBe("invalid_event");
  });

  it("answer 안의 다른 응답 schema_version은 오류로 낸다", async () => {
    const answer = foundEvents.find((e) => e.type === "answer");
    const bad = { ...answer, response: { ...(answer as { response: object }).response, schema_version: "chat_response@v1" } };
    const { error } = await failure(byteStream([encoder.encode(`${JSON.stringify(bad)}\n`)]));
    expect(error.kind).toBe("invalid_event");
  });

  it("읽는 중 연결이 끊기면 network 오류로 낸다", async () => {
    const { error, seen } = await failure(byteStream([encoder.encode(`${JSON.stringify(foundEvents[0])}\n`)], "error"));
    expect(error.kind).toBe("network");
    expect(seen).toEqual(foundEvents.slice(0, 1));
  });

  it("abort()하면 aborted로 끝난다", async () => {
    const controller = new AbortController();
    let push!: (chunk: Uint8Array) => void;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        push = (chunk) => c.enqueue(chunk);
        controller.signal.addEventListener("abort", () => c.error(new DOMException("aborted", "AbortError")));
      },
    });
    push(encoder.encode(`${JSON.stringify(foundEvents[0])}\n`));
    const seen: ChatEvent[] = [];
    const run = (async () => {
      for await (const event of parseNdjsonStream(stream, { signal: controller.signal })) {
        seen.push(event);
        controller.abort();
      }
    })();
    await expect(run).rejects.toMatchObject({ name: "ChatStreamError", kind: "aborted" });
    expect(seen).toEqual(foundEvents.slice(0, 1));
  });
});
