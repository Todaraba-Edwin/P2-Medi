import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ChatRequestSchema, initialStreamState } from "@/lib/api";
import type { ChatRequest, RunChatStreamOptions, StreamState } from "@/lib/api";
import { scenarios } from "@/mocks/fixtures/scenarios";
import type { ScenarioName } from "@/mocks/fixtures/scenarios";
import { createChatHandler } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createChatStore } from "./chat";
import { buildChatRequest, createMemoryContextStorage, emptyConversationContext } from "./conversation-context";

let requests = 0;
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", () => {
    requests += 1;
  });
});
afterEach(() => {
  server.resetHandlers();
  requests = 0;
});
afterAll(() => server.close());

const use = (scenario: ScenarioName, delayMs = 0) => server.use(createChatHandler({ scenario, delayMs }));
const QUESTION = "합성 질문 가나다정 먹어도 되나요";

describe("대화 스토어", () => {
  it("질문을 보내면 차례가 생기고 결과가 메모리에 담긴다", async () => {
    use("found");
    const store = createChatStore();
    const sending = store.getState().send(`  ${QUESTION}  `);
    expect(store.getState().turns).toHaveLength(1);
    expect(store.getState().turns[0].question).toBe(QUESTION);
    expect(store.getState().activeTurnId).toBe(store.getState().turns[0].id);
    await sending;
    const state = store.getState();
    expect(state.activeTurnId).toBeNull();
    expect(state.turns[0].stream.status).toBe("done");
    expect(state.turns[0].stream.response?.summary).toBe(
      scenarios.found.events.find((e) => e.type === "answer")?.response.summary,
    );
    expect(requests).toBe(1);
  });

  it("표시용 글자를 주면 차례에 따로 두고, 서버로는 원 질문을 보낸다(FE-09-04 A)", async () => {
    const seen: unknown[] = [];
    const store = createChatStore({
      run: async (request, options) => {
        seen.push(request);
        return options?.previous ?? initialStreamState;
      },
    });
    await store.getState().send(QUESTION);
    await store.getState().send(QUESTION, "고른 약: 가나다정, 가나다시럽으로 다시 확인");
    const [first, second] = store.getState().turns;
    expect("display" in first).toBe(false);
    expect(second).toMatchObject({ question: QUESTION, display: "고른 약: 가나다정, 가나다시럽으로 다시 확인" });
    expect(seen.map((request) => (request as { question: string }).question)).toEqual([QUESTION, QUESTION]);
    expect(JSON.stringify(seen)).not.toContain("고른 약");
  });

  it("빈 질문은 보내지 않는다", async () => {
    const store = createChatStore();
    await store.getState().send("   ");
    expect(store.getState().turns).toEqual([]);
    expect(requests).toBe(0);
  });

  it("새 질문을 보내면 진행 중인 요청을 abort한다", async () => {
    use("found", 40);
    const signals: AbortSignal[] = [];
    const store = createChatStore();
    const real = (await import("@/lib/api")).runChatStream;
    const spied = createChatStore({
      run: (request, options) => {
        if (options?.signal) signals.push(options.signal);
        return real(request, options);
      },
    });
    void store; // 기본 스토어도 만들 수 있는지만 본다
    const first = spied.getState().send("첫 질문");
    await vi.waitFor(() => expect(spied.getState().turns[0].stream.stage).not.toBeNull());
    const second = spied.getState().send("둘째 질문");
    expect(signals[0].aborted).toBe(true); // 보내는 즉시 끊는다
    await Promise.all([first, second]);
    const [a, b] = spied.getState().turns;
    expect(a.stream.status).toBe("aborted");
    expect(a.stream.response).toBeNull();
    expect(b.stream.status).toBe("done");
    expect(spied.getState().activeTurnId).toBeNull();
    expect(requests).toBe(2);
  });

  it("응급 이벤트는 받는 즉시 기록하고, 끊긴 뒤와 다음 질문 뒤에도 남는다", async () => {
    use("emergencyCut", 20);
    const store = createChatStore();
    let statusWhenRecorded: string | null = null;
    store.subscribe((state) => {
      if (state.emergency && statusWhenRecorded === null) statusWhenRecorded = state.turns[0].stream.status;
    });
    const sending = store.getState().send(QUESTION);
    await vi.waitFor(() => expect(store.getState().emergency).not.toBeNull());
    expect(statusWhenRecorded).toBe("streaming"); // 스트림이 끝나기 전에 이미 기록됐다
    await sending;
    expect(store.getState().turns[0].stream.status).toBe("interrupted");
    expect(store.getState().turns[0].stream.response).toBeNull();
    const emergency = store.getState().emergency;
    expect(emergency?.text).toBe(scenarios.emergencyCut.events[0].type === "emergency" ? scenarios.emergencyCut.events[0].emergency.text : "");

    use("found");
    await store.getState().send("다음 질문");
    expect(store.getState().emergency).toEqual(emergency);
    store.getState().reset();
    expect(store.getState().emergency).toBeNull();
    expect(store.getState().turns).toEqual([]);
  });

  it("다시 시도는 부를 때만 보내고, 같은 차례에서 같은 질문으로 간다", async () => {
    use("http500");
    const store = createChatStore();
    await store.getState().send(QUESTION);
    const id = store.getState().turns[0].id;
    expect(store.getState().turns[0].stream.status).toBe("error");
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(requests).toBe(1); // 스스로 다시 보내지 않는다

    use("found");
    await store.getState().retry(id);
    expect(requests).toBe(2);
    expect(store.getState().turns).toHaveLength(1);
    expect(store.getState().turns[0].stream.status).toBe("done");
  });

  it("다시 시도할 수 없는 차례(4xx·완료·마지막이 아닌 차례)는 보내지 않는다", async () => {
    use("http400");
    const store = createChatStore();
    await store.getState().send(QUESTION);
    await store.getState().retry(store.getState().turns[0].id);
    expect(requests).toBe(1);

    use("http500");
    await store.getState().send("둘째");
    use("found");
    await store.getState().send("셋째");
    await store.getState().retry(store.getState().turns[1].id); // 마지막이 아니다
    await store.getState().retry(store.getState().turns[2].id); // 완료됐다
    expect(requests).toBe(3);
  });

  it("abort()는 진행 중인 요청을 끊는다", async () => {
    use("found", 40);
    const store = createChatStore();
    const sending = store.getState().send(QUESTION);
    await vi.waitFor(() => expect(store.getState().turns[0].stream.stage).not.toBeNull());
    store.getState().abort();
    await sending;
    expect(store.getState().turns[0].stream.status).toBe("aborted");
    expect(store.getState().activeTurnId).toBeNull();
  });

  it("대화 뒤 브라우저 저장소·쿠키에 질문과 응답이 없다", async () => {
    use("found");
    const store = createChatStore();
    await store.getState().send(QUESTION);
    const summary = store.getState().turns[0].stream.response?.summary ?? "";
    expect(summary).not.toBe("");
    // 저장소를 직접 들여다보는 시험이라 이 줄만 저장소 접근 금지 규칙을 끈다
    // eslint-disable-next-line no-restricted-properties
    const stores = [window.localStorage, window.sessionStorage];
    for (const storage of stores) {
      expect(storage.length).toBe(0);
      expect(JSON.stringify({ ...storage })).not.toContain(QUESTION);
    }
    expect(document.cookie).toBe("");
  });
});

const AGE_5 = { lower: 5, upper: 5, unit: "세" } as const;
const AGE_70 = { lower: 70, upper: 70, unit: "세" } as const;

describe("대화 상태 묶음", () => {
  it("메모리에만 두고 reset하면 비운다", () => {
    const storage = createMemoryContextStorage();
    const store = createChatStore({ contextStorage: storage });
    expect(store.getState().context).toEqual(emptyConversationContext);
    store.getState().setContext({ age: AGE_5, pregnant: false });
    store.getState().setContext({ confirmedDrugs: [{ name: "가나다정", itemSeq: null }] });
    expect(store.getState().context).toEqual({ age: AGE_5, pregnant: false, confirmedDrugs: [{ name: "가나다정", itemSeq: null }], priorDrugs: [], tookToday: null });
    expect(storage.read()).toEqual(store.getState().context);
    store.getState().setContext({ priorDrugs: [{ name: "라마바캡슐", itemSeq: "200000006" }], tookToday: true });
    store.getState().reset(); // 새 대화: 이전 선택·용량 답도 비운다
    expect(store.getState().context).toEqual(emptyConversationContext);
    expect(store.getState().context.priorDrugs).toEqual([]);
  });

  it("저장 위치를 바꿔 끼울 수 있다", () => {
    const written: unknown[] = [];
    const store = createChatStore({
      contextStorage: {
        read: () => ({ age: AGE_70, pregnant: null, confirmedDrugs: [], priorDrugs: [], tookToday: null }),
        write: (next) => written.push(next),
        clear: () => written.push("clear"),
      },
    });
    expect(store.getState().context.age).toEqual(AGE_70);
    store.getState().setContext({ pregnant: true });
    expect(written).toEqual([{ age: AGE_70, pregnant: true, confirmedDrugs: [], priorDrugs: [], tookToday: null }]);
  });

  it("요청 본문은 한 곳(buildChatRequest)에서 만들고 묶음 값을 v1 context로 싣는다", async () => {
    const seen: unknown[] = [];
    const run = async (request: unknown, options?: RunChatStreamOptions): Promise<StreamState> => {
      seen.push(request);
      options?.onState?.({ ...initialStreamState, status: "streaming" });
      return initialStreamState;
    };
    const store = createChatStore({ run });
    await store.getState().send(QUESTION);
    expect(seen[0]).toEqual({ question: QUESTION, context: { age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [], took_today: null } });
    store.getState().setContext({ age: AGE_5, pregnant: true, confirmedDrugs: [{ name: "가나다정", itemSeq: "200000001" }] });
    await store.getState().send(QUESTION);
    const expected = {
      question: QUESTION,
      context: { age: AGE_5, pregnant: true, confirmed_drugs: [{ name: "가나다정", item_seq: "200000001", input_name: null }], prior_drugs: [], took_today: null },
    };
    expect(seen[1]).toEqual(expected);
    expect(ChatRequestSchema.safeParse(seen[1]).success).toBe(true);
    // 가짜 `run`은 응답을 주지 않으므로 고른 약은 그대로 남는다(옮기는 규칙은 아래 "이전 선택" 묶음)
    expect(buildChatRequest(QUESTION, store.getState().context)).toEqual(expected);
  });

  it("품목 번호는 9자리 숫자일 때만 싣고, 확인한 약은 서버 상한(10개)까지만 싣는다", () => {
    const drugs = Array.from({ length: 12 }, (_, i) => ({ name: `합성약${i}`, itemSeq: i === 11 ? "12345" : null }));
    const request = buildChatRequest(QUESTION, { ...emptyConversationContext, confirmedDrugs: drugs });
    expect(request.context?.confirmed_drugs).toHaveLength(10);
    expect(request.context?.confirmed_drugs?.at(-1)).toEqual({ name: "합성약11", item_seq: null, input_name: null });
    expect(ChatRequestSchema.safeParse(request).success).toBe(true);
    // 이전 선택도 같은 규칙(같은 상한·같은 모양)이다
    const prior = buildChatRequest(QUESTION, { ...emptyConversationContext, priorDrugs: drugs });
    expect(prior.context?.prior_drugs).toHaveLength(10);
    expect(prior.context?.confirmed_drugs).toEqual([]);
    expect(ChatRequestSchema.safeParse(prior).success).toBe(true);
  });

  it("되묻기에서 고른 약에는 그 묶음의 이름을 input_name으로 싣는다(FE-09-05 A). 서버 규칙에 안 맞는 이름은 null로 보낸다", () => {
    const request = buildChatRequest(QUESTION, {
      ...emptyConversationContext,
      confirmedDrugs: [
        { name: "가나다정 100밀리그램", itemSeq: "200000001", inputName: "가나다" },
        { name: "가나다시럽 키즈", itemSeq: "200000004", inputName: "가나다시럽" },
        { name: "합성약1", itemSeq: null }, // 되묻기를 거치지 않은 값
        { name: "합성약2", itemSeq: null, inputName: "  " },
        { name: "합성약3", itemSeq: null, inputName: "가".repeat(101) },
      ],
    });
    expect(request.context?.confirmed_drugs).toEqual([
      { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" },
      { name: "가나다시럽 키즈", item_seq: "200000004", input_name: "가나다시럽" },
      { name: "합성약1", item_seq: null, input_name: null },
      { name: "합성약2", item_seq: null, input_name: null },
      { name: "합성약3", item_seq: null, input_name: null },
    ]);
    expect(ChatRequestSchema.safeParse(request).success).toBe(true);
  });
});

// AG-21-02·03 A: 이번 질문의 답(`confirmed_drugs`)과 이전 차례의 선택(`prior_drugs`)을 나눠 싣고, 답이 오면 고른 것을 이전 선택으로 옮긴다
describe("이전 선택(prior_drugs)과 이번 답(confirmed_drugs)", () => {
  const PICK_A = { name: "가나다정 100밀리그램", itemSeq: "200000001", inputName: "가나다" };
  const PICK_A2 = { name: "가나다정 500밀리그램", itemSeq: "200000002", inputName: "가나다" };
  const PICK_B = { name: "라마바캡슐 10밀리그램", itemSeq: "200000006", inputName: "라마바" };
  const wire = (drug: typeof PICK_A) => ({ name: drug.name, item_seq: drug.itemSeq, input_name: drug.inputName });

  it("재전송: 고른 약은 confirmed_drugs로, 이전 확정은 prior_drugs로 따로 실리고, 답(answer)을 받는 즉시 고른 약이 이전 선택이 되며 confirmed는 빈다", async () => {
    use("found", 20);
    const seen: ChatRequest[] = [];
    const real = (await import("@/lib/api")).runChatStream;
    const store = createChatStore({
      run: (request, options) => {
        seen.push(request);
        return real(request, options);
      },
    });
    store.getState().setContext({ priorDrugs: [PICK_B], confirmedDrugs: [PICK_A] });
    let contextWhenAnswered: unknown = null;
    store.subscribe((state) => {
      if (contextWhenAnswered === null && state.turns[0]?.stream.response) contextWhenAnswered = state.context;
    });
    const sending = store.getState().send(QUESTION, "고른 약: 가나다정 100밀리그램으로 다시 확인");
    expect(seen[0].context).toEqual({ age: null, pregnant: null, confirmed_drugs: [wire(PICK_A)], prior_drugs: [wire(PICK_B)], took_today: null });
    await vi.waitFor(() => expect(store.getState().turns[0].stream.response).not.toBeNull());
    // 스트림이 끝나기(done) 전, 답을 받는 순간 이미 옮겨졌다(사용자가 답을 보고 바로 다음 질문을 보내도 이전 선택을 잃지 않는다)
    expect(store.getState().turns[0].stream.status).toBe("streaming");
    expect(store.getState().context.confirmedDrugs).toEqual([]);
    expect(store.getState().context.priorDrugs).toEqual([PICK_B, PICK_A]);
    await sending;
    expect(contextWhenAnswered).toEqual(store.getState().context);
    expect(store.getState().turns[0].stream.status).toBe("done");
  });

  it("답을 본 뒤 스트림이 끝나기 전에 다음 질문을 보내도(앞 요청이 끊김) 이전 선택이 실린다", async () => {
    use("found", 20);
    const seen: ChatRequest[] = [];
    const real = (await import("@/lib/api")).runChatStream;
    const store = createChatStore({
      run: (request, options) => {
        seen.push(request);
        return real(request, options);
      },
    });
    store.getState().setContext({ confirmedDrugs: [PICK_A] });
    const first = store.getState().send(QUESTION, "고른 약: 가나다정 100밀리그램으로 다시 확인");
    await vi.waitFor(() => expect(store.getState().turns[0].stream.response).not.toBeNull());
    store.getState().setContext({ confirmedDrugs: [] }); // 새 질문(AppShell `send`)과 같은 순서
    const second = store.getState().send("다음 질문");
    await Promise.all([first, second]);
    expect(store.getState().turns[0].stream.status).toBe("aborted");
    expect(seen[1].context).toEqual({ age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [wire(PICK_A)], took_today: null });
  });

  it("새 질문: confirmed_drugs는 비어 있고 이전 선택만 prior_drugs로 실린다. 같은 묶음 이름으로 다시 고르면 이전 선택이 새 선택으로 바뀐다", async () => {
    use("found");
    const seen: ChatRequest[] = [];
    const real = (await import("@/lib/api")).runChatStream;
    const store = createChatStore({
      run: (request, options) => {
        seen.push(request);
        return real(request, options);
      },
    });
    store.getState().setContext({ confirmedDrugs: [PICK_A] });
    await store.getState().send(QUESTION);
    await store.getState().send("다음 질문");
    expect(seen[1].context).toEqual({ age: null, pregnant: null, confirmed_drugs: [], prior_drugs: [wire(PICK_A)], took_today: null });
    // 같은 이름 '가나다'로 다른 제품을 고르면(확인 되묻기 뒤) 이전 선택이 바뀐다(묶음 이름당 하나)
    store.getState().setContext({ confirmedDrugs: [PICK_A2] });
    await store.getState().send(QUESTION);
    expect(seen[2].context).toMatchObject({ confirmed_drugs: [wire(PICK_A2)], prior_drugs: [wire(PICK_A)] });
    expect(store.getState().context.priorDrugs).toEqual([PICK_A2]);
    expect(store.getState().context.confirmedDrugs).toEqual([]);
  });

  it("답 없이 끝나면(오류) 고른 약을 옮기지 않아 '다시 시도'가 같은 답을 다시 싣고, 새 대화(reset)는 이전 선택을 비운다", async () => {
    use("http500");
    const seen: ChatRequest[] = [];
    const real = (await import("@/lib/api")).runChatStream;
    const store = createChatStore({
      run: (request, options) => {
        seen.push(request);
        return real(request, options);
      },
    });
    store.getState().setContext({ confirmedDrugs: [PICK_A] });
    await store.getState().send(QUESTION);
    expect(store.getState().context.confirmedDrugs).toEqual([PICK_A]);
    expect(store.getState().context.priorDrugs).toEqual([]);
    use("found");
    await store.getState().retry(store.getState().turns[0].id);
    expect(seen[1].context).toMatchObject({ confirmed_drugs: [wire(PICK_A)], prior_drugs: [] });
    expect(store.getState().context.priorDrugs).toEqual([PICK_A]);
    store.getState().reset();
    expect(store.getState().context).toEqual(emptyConversationContext);
    // 이전 선택은 브라우저 저장소에 없다(대화 미저장 원칙)
    // eslint-disable-next-line no-restricted-properties
    expect(JSON.stringify([{ ...window.localStorage }, { ...window.sessionStorage }, document.cookie])).not.toContain("가나다정");
  });
});
