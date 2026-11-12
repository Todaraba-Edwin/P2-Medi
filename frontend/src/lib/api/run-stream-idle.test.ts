import { afterEach, describe, expect, it, vi } from "vitest";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { runChatStream } from "./run-stream";
import type { ChatEvent } from "./types";

// 무응답 상한 시험은 통신 계층을 대신 세운다: 이벤트를 낸 뒤 닫지 않고, signal이 끊기면 읽기 오류를 내는 응답.
// (MSW Node 가로채기는 멈춘 응답을 타이머로 끊을 때 undici 내부 단언에 걸려 여기서는 쓰지 않는다.)
const postChatStream = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ postChatStream }));

function hangingResponse(events: ChatEvent[], signal?: AbortSignal): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
      signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    },
  });
  return new Response(body, { headers: { "Content-Type": "application/x-ndjson" } });
}

afterEach(() => postChatStream.mockReset());

describe("runChatStream 무응답 상한", () => {
  it("이벤트가 상한 동안 오지 않으면 abort하고 interrupted(idle_timeout)", async () => {
    let seenSignal: AbortSignal | undefined;
    postChatStream.mockImplementation(async (_request: unknown, signal?: AbortSignal) => {
      seenSignal = signal;
      return hangingResponse(scenarios.hang.events, signal);
    });
    const final = await runChatStream({ question: "합성 질문" }, { idleTimeoutMs: 40 });
    expect(seenSignal?.aborted).toBe(true);
    expect(final).toMatchObject({ status: "interrupted", stage: null, response: null });
    expect(final.error).toEqual({ kind: "idle_timeout", status: null, code: null, message: null });
    expect(postChatStream).toHaveBeenCalledTimes(1); // 다시 보내지 않는다
  });

  it("응급을 받은 뒤 무응답이면 119는 유지한다", async () => {
    postChatStream.mockImplementation(async (_request: unknown, signal?: AbortSignal) =>
      hangingResponse(scenarios.emergencyCut.events, signal),
    );
    const final = await runChatStream({ question: "합성 질문" }, { idleTimeoutMs: 40 });
    expect(final.status).toBe("interrupted");
    expect(final.emergency).not.toBeNull();
    expect(final.response).toBeNull();
  });

  it("answer 뒤 무응답이면 결과를 유지한다", async () => {
    postChatStream.mockImplementation(async (_request: unknown, signal?: AbortSignal) =>
      hangingResponse(scenarios.answerWithoutDone.events, signal),
    );
    const final = await runChatStream({ question: "합성 질문" }, { idleTimeoutMs: 40 });
    expect(final).toMatchObject({ status: "done", endedWithoutDone: true, error: null });
    expect(final.response).not.toBeNull();
  });

  it("응답 자체가 오지 않아도(첫 이벤트 전) 상한으로 끊는다", async () => {
    postChatStream.mockImplementation(
      (_request: unknown, signal?: AbortSignal) =>
        new Promise<Response>((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const final = await runChatStream({ question: "합성 질문" }, { idleTimeoutMs: 40 });
    expect(final).toMatchObject({ status: "interrupted" });
    expect(final.error?.kind).toBe("idle_timeout");
  });
});
