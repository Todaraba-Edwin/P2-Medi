import { HttpResponse, http } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { scenarios } from "@/mocks/fixtures/scenarios";
import type { ScenarioName } from "@/mocks/fixtures/scenarios";
import { createChatHandler } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { runChatStream } from "./run-stream";
import { ChatStreamError, streamChat } from "./stream";
import type { StreamState } from "./stream-state";
import type { ChatEvent } from "./types";

let requests = 0;
const countRequest = () => {
  requests += 1;
};

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", countRequest);
});
afterEach(() => {
  server.resetHandlers();
  requests = 0;
});
afterAll(() => server.close());

const use = (scenario: ScenarioName, delayMs = 0) => server.use(createChatHandler({ scenario, delayMs }));
const request = { question: "합성 질문" };

async function collect(signal?: AbortSignal) {
  const seen: ChatEvent[] = [];
  try {
    for await (const event of streamChat(request, { signal })) seen.push(event);
    return { seen, error: null };
  } catch (error) {
    return { seen, error: error as ChatStreamError };
  }
}

describe("streamChat (MSW)", () => {
  it("이벤트를 받은 순서대로 낸다", async () => {
    use("emergency");
    const { seen, error } = await collect();
    expect(error).toBeNull();
    expect(seen).toEqual(scenarios.emergency.events);
    expect(seen[0].type).toBe("emergency");
    expect(requests).toBe(1);
  });

  it("질문 글자로 시나리오를 고르는 기본 핸들러도 같은 인터페이스다", async () => {
    const seen: ChatEvent[] = [];
    for await (const event of streamChat({ question: "mock:거절 합성 질문" })) seen.push(event);
    expect(seen).toEqual(scenarios.refuse.events);
  });

  it.each<[ScenarioName, number]>([
    ["http400", 400],
    ["http500", 500],
  ])("%s: 오류를 내고 POST를 다시 보내지 않는다", async (scenario, status) => {
    use(scenario);
    const { seen, error } = await collect();
    expect(seen).toEqual([]);
    expect(error).toMatchObject({ kind: "http", status });
    expect(requests).toBe(1);
  });

  it("네트워크 오류: 오류를 내고 POST를 다시 보내지 않는다", async () => {
    server.use(http.post("*/api/chat", () => HttpResponse.error()));
    const { error } = await collect();
    expect(error).toMatchObject({ kind: "network" });
    expect(requests).toBe(1);
  });

  it("본문 읽기 중 끊기면 answer 없이 끝나고 POST를 다시 보내지 않는다", async () => {
    use("cutBeforeAnswer");
    const { seen, error } = await collect();
    // 끊김은 환경에 따라 읽기 오류(network)나 done 없는 닫힘으로 보인다. 어느 쪽이든 리듀서가 interrupted로 만든다
    expect(seen).toEqual(scenarios.cutBeforeAnswer.events.slice(0, seen.length));
    expect(seen.some((e) => e.type === "answer" || e.type === "done")).toBe(false);
    if (error) expect(error).toMatchObject({ kind: "network" });
    expect(requests).toBe(1);
  });

  it("abort()하면 aborted로 끝난다", async () => {
    use("hang");
    const controller = new AbortController();
    const seen: ChatEvent[] = [];
    const run = (async () => {
      for await (const event of streamChat(request, { signal: controller.signal })) {
        seen.push(event);
        controller.abort();
      }
    })();
    await expect(run).rejects.toMatchObject({ kind: "aborted" });
    expect(seen).toHaveLength(1);
  });

  it("요청 본문은 질문만 담고 Accept는 NDJSON이다", async () => {
    let body: unknown;
    let accept: string | null = null;
    server.use(
      http.post("*/api/chat", async ({ request: req }) => {
        body = await req.json();
        accept = req.headers.get("accept");
        return new HttpResponse("", { headers: { "Content-Type": "application/x-ndjson" } });
      }),
    );
    await collect();
    expect(body).toEqual(request);
    expect(accept).toBe("application/x-ndjson");
  });
});

describe("runChatStream (MSW)", () => {
  it("정상: 상태가 streaming → done으로 가고 결과를 담는다", async () => {
    use("found");
    const states: StreamState[] = [];
    const final = await runChatStream(request, { onState: (s) => states.push(s) });
    expect(states[0].status).toBe("streaming");
    expect(states.map((s) => s.stage).filter(Boolean)).toEqual(["drug_lookup", "contraindication_check", "evidence_search"]);
    expect(final).toMatchObject({ status: "done", endedWithoutDone: false, error: null });
    expect(final.response?.fixed_notice.length).toBeGreaterThan(0);
    expect(requests).toBe(1);
  });

  it("응급 첫 이벤트 → 끊김: 119 유지, 부분 결과 없음, 재시도 0회", async () => {
    use("emergencyCut");
    const states: StreamState[] = [];
    const final = await runChatStream(request, { onState: (s) => states.push(s) });
    expect(states[1].emergency).not.toBeNull(); // 첫 이벤트에서 바로 반영
    expect(final.status).toBe("interrupted");
    expect(final.emergency?.text).toBe(scenarios.emergency.events[0].type === "emergency" ? scenarios.emergency.events[0].emergency.text : "");
    expect(final.response).toBeNull();
    expect(requests).toBe(1);
  });

  it.each<[ScenarioName, StreamState["status"]]>([
    ["cutBeforeAnswer", "interrupted"],
    ["closeBeforeAnswer", "interrupted"],
    ["serverError", "error"],
    ["http500", "error"],
    ["http400", "error"],
  ])("%s: 결과 없이 %s, 재시도 0회", async (scenario, status) => {
    use(scenario);
    const final = await runChatStream(request);
    expect(final.status).toBe(status);
    expect(final.response).toBeNull();
    expect(requests).toBe(1);
  });

  it("answer 뒤 done 없이 닫혀도 결과를 유지한다", async () => {
    use("answerWithoutDone");
    const final = await runChatStream(request);
    expect(final).toMatchObject({ status: "done", endedWithoutDone: true });
    expect(final.response).not.toBeNull();
  });

  it("이벤트가 오면 무응답 시계가 다시 돈다", async () => {
    use("found", 30); // 이벤트 간격 30ms < 상한 80ms, 전체는 상한보다 길다
    const final = await runChatStream(request, { idleTimeoutMs: 80 });
    expect(final.status).toBe("done");
  });

  it("호출자가 abort하면 aborted, 받은 119는 유지", async () => {
    server.use(createChatHandler({ scenario: "emergency", delayMs: 20 }));
    const controller = new AbortController();
    const final = await runChatStream(request, {
      signal: controller.signal,
      onState: (s) => {
        if (s.emergency) controller.abort();
      },
    });
    expect(final.status).toBe("aborted");
    expect(final.emergency).not.toBeNull();
    expect(final.response).toBeNull();
  });

  it("다시 시도(retry)는 이전 119를 유지한 채 새로 보낸다", async () => {
    use("emergencyCut");
    const first = await runChatStream(request);
    use("cutBeforeAnswer");
    const second = await runChatStream(request, { previous: first, retry: true });
    expect(second.status).toBe("interrupted");
    expect(second.emergency).toEqual(first.emergency);
    expect(requests).toBe(2); // 사용자가 누른 한 번만 더 간다
  });
});
