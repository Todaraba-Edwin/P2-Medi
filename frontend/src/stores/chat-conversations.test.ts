// 이번 탭의 대화 여러 개(FE-17 U-29, 2026-11-24 사용자 "새 질문을 클릭하면 … 새로고침 전에는 지금 대화들의 세션들이 남아있어야").
// 대화 스토어의 새 대화·전환·상한·전부 지움·대화별 묶음·백그라운드 응답을 본다. 모두 메모리(상태)에만 있고 브라우저 저장소는 쓰지 않는다
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { initialStreamState } from "@/lib/api";
import type { ChatRequest, StreamState } from "@/lib/api";
import { createChatHandler } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { CONVERSATIONS_MAX, createChatStore } from "./chat";
import type { ChatStore } from "./chat";
import { createMemoryContextStorage, emptyConversationContext } from "./conversation-context";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const filled = (store: ChatStore) => store.getState().conversations.filter((conversation) => conversation.turns.length > 0);
const questions = (store: ChatStore) => filled(store).map((conversation) => conversation.turns[0].question);
const PICK = { name: "가나다정 100밀리그램", itemSeq: "200000001", inputName: "가나다" };

describe("대화 여러 개(U-29)", () => {
  it("새 대화는 지금 대화를 목록에 남기고 빈 대화를 연다. 질문 없는 대화에서 누르면 쌓지 않고 묶음만 비운다", async () => {
    server.use(createChatHandler({ scenario: "found" }));
    const store = createChatStore();
    const first = store.getState().currentId;
    store.getState().setContext({ tookToday: true });
    store.getState().startNew(); // 빈 대화 → 쌓지 않음
    expect(store.getState().conversations).toHaveLength(1);
    expect(store.getState().currentId).toBe(first);
    expect(store.getState().context).toEqual(emptyConversationContext);
    await store.getState().send("첫 질문");
    store.getState().startNew();
    expect(store.getState().conversations).toHaveLength(2);
    expect(store.getState().currentId).not.toBe(first);
    expect(store.getState().turns).toEqual([]);
    expect(store.getState().emergency).toBeNull();
    expect(questions(store)).toEqual(["첫 질문"]);
  });

  it("전환하면 그 대화의 차례·119·묶음이 맨 위 칸으로 돌아오고, 떠난 빈 대화는 목록에서 빠진다", async () => {
    server.use(createChatHandler({ scenario: "emergency" }));
    const storage = createMemoryContextStorage();
    const store = createChatStore({ contextStorage: storage });
    store.getState().setContext({ pregnant: true, priorDrugs: [PICK] });
    await store.getState().send("응급 질문");
    const first = store.getState().currentId;
    const emergency = store.getState().emergency;
    expect(emergency).not.toBeNull();
    store.getState().startNew();
    expect(store.getState().emergency).toBeNull(); // 새 대화는 119 안내 없이 시작
    store.getState().setContext({ pregnant: false });
    const empty = store.getState().currentId;
    store.getState().switchTo(first);
    const state = store.getState();
    expect(state.currentId).toBe(first);
    expect(state.turns.map((turn) => turn.question)).toEqual(["응급 질문"]);
    expect(state.emergency).toEqual(emergency);
    expect(state.context.pregnant).toBe(true);
    expect(state.context.priorDrugs).toEqual([PICK]);
    expect(storage.read()).toEqual(state.context); // 지금 대화의 묶음은 저장 위치(메모리)와 같다
    expect(state.conversations.some((conversation) => conversation.id === empty)).toBe(false);
    // 같은 대화·없는 대화로 옮기기는 아무것도 하지 않는다
    store.getState().switchTo(first);
    store.getState().switchTo("chat-없음");
    expect(store.getState()).toBe(state);
  });

  it(`질문이 있는 대화는 ${CONVERSATIONS_MAX}개까지만 남고, 넘으면 가장 오래된 것부터 지운다(지금 대화는 지우지 않는다)`, async () => {
    server.use(createChatHandler({ scenario: "found" }));
    const store = createChatStore();
    for (let index = 1; index <= CONVERSATIONS_MAX + 2; index += 1) {
      await store.getState().send(`질문 ${index}`);
      store.getState().startNew();
    }
    expect(filled(store)).toHaveLength(CONVERSATIONS_MAX);
    expect(questions(store)[0]).toBe("질문 3");
    expect(questions(store).at(-1)).toBe(`질문 ${CONVERSATIONS_MAX + 2}`);
  });

  it("상한으로 지워지는 대화의 진행 중 요청은 끊는다", async () => {
    let aborted = 0;
    const store = createChatStore({
      run: (_request, options) =>
        new Promise<StreamState>((resolve) => {
          options?.signal?.addEventListener("abort", () => {
            aborted += 1;
            resolve(initialStreamState);
          });
        }),
    });
    for (let index = 1; index <= CONVERSATIONS_MAX + 1; index += 1) {
      void store.getState().send(`질문 ${index}`);
      store.getState().startNew();
    }
    await vi.waitFor(() => expect(aborted).toBe(1));
    expect(filled(store)).toHaveLength(CONVERSATIONS_MAX);
    store.getState().abort();
  });

  it("다른 대화로 옮겨도 진행 중인 응답은 끊기지 않고 그 대화에 쌓이며, 고른 약은 그 대화의 묶음에서 이전 선택으로 옮겨진다", async () => {
    server.use(createChatHandler({ scenario: "found", delayMs: 30 }));
    const seen: ChatRequest[] = [];
    const real = (await import("@/lib/api")).runChatStream;
    const store = createChatStore({
      run: (request, options) => {
        seen.push(request);
        return real(request, options);
      },
    });
    store.getState().setContext({ confirmedDrugs: [PICK] });
    const sending = store.getState().send("첫 질문");
    const first = store.getState().currentId;
    store.getState().startNew();
    store.getState().setContext({ pregnant: true });
    await sending;
    const background = store.getState().conversations.find((conversation) => conversation.id === first)!;
    expect(background.turns[0].stream.status).toBe("done");
    expect(background.activeTurnId).toBeNull();
    expect(background.context.confirmedDrugs).toEqual([]);
    expect(background.context.priorDrugs).toEqual([PICK]);
    // 지금(새) 대화는 건드리지 않았다
    expect(store.getState().turns).toEqual([]);
    expect(store.getState().context).toEqual({ ...emptyConversationContext, pregnant: true });
    expect(seen).toHaveLength(1);
  });

  it("reset은 지금 대화만 비우고 다른 대화는 그대로다", async () => {
    server.use(createChatHandler({ scenario: "found" }));
    const store = createChatStore();
    await store.getState().send("첫 질문");
    store.getState().startNew();
    await store.getState().send("둘째 질문");
    store.getState().reset();
    expect(store.getState().turns).toEqual([]);
    expect(questions(store)).toEqual(["첫 질문"]);
  });

  it("clearAll(로그아웃·계정 전환)은 대화를 모두 지우고 진행 중 요청을 끊는다", async () => {
    server.use(createChatHandler({ scenario: "found", delayMs: 40 }));
    const store = createChatStore();
    await store.getState().send("첫 질문");
    store.getState().startNew();
    store.getState().setContext({ priorDrugs: [PICK] });
    const sending = store.getState().send("둘째 질문");
    store.getState().clearAll();
    await sending;
    const state = store.getState();
    expect(state.conversations).toHaveLength(1);
    expect(state.turns).toEqual([]);
    expect(state.context).toEqual(emptyConversationContext);
    expect(state.conversations[0].id).toBe(state.currentId);
  });

  it("keepOnlyCurrent(로그아웃·탈퇴·계정 전환)는 지금 대화만 남기고 다른 대화의 진행 중 요청을 끊는다", async () => {
    server.use(createChatHandler({ scenario: "found", delayMs: 40 }));
    const store = createChatStore();
    const sending = store.getState().send("첫 질문");
    const first = store.getState().currentId;
    store.getState().startNew();
    await store.getState().send("둘째 질문");
    store.getState().keepOnlyCurrent();
    await sending;
    expect(questions(store)).toEqual(["둘째 질문"]);
    expect(store.getState().conversations.some((conversation) => conversation.id === first)).toBe(false);
    expect(store.getState().turns.map((turn) => turn.stream.status)).toEqual(["done"]);
  });

  it("화면 문맥(근거 상세·대상)은 대화마다 따로 적힌다", async () => {
    server.use(createChatHandler({ scenario: "found" }));
    const store = createChatStore();
    await store.getState().send("첫 질문");
    const first = store.getState().currentId;
    store.getState().setScreen(first, { evidenceTurnId: store.getState().turns[0].id, targetProfileId: "p-1" });
    store.getState().startNew();
    expect(store.getState().conversations.find((conversation) => conversation.id === store.getState().currentId)!.screen).toEqual({ evidenceTurnId: null });
    store.getState().switchTo(first);
    expect(store.getState().conversations.find((conversation) => conversation.id === first)!.screen).toEqual({ evidenceTurnId: "turn-1", targetProfileId: "p-1" });
  });

  it("대화를 여러 개 만들어도 브라우저 저장소·쿠키에 질문·답이 없다", async () => {
    server.use(createChatHandler({ scenario: "found" }));
    const store = createChatStore();
    await store.getState().send("저장 금지 첫 질문");
    store.getState().startNew();
    await store.getState().send("저장 금지 둘째 질문");
    const summary = store.getState().turns[0].stream.response?.summary ?? "";
    // 저장소를 직접 들여다보는 시험이라 이 줄만 저장소 접근 금지 규칙을 끈다
    // eslint-disable-next-line no-restricted-properties
    const dump = JSON.stringify([{ ...window.localStorage }, { ...window.sessionStorage }, document.cookie]);
    for (const text of ["저장 금지", summary]) expect(dump).not.toContain(text);
  });
});
