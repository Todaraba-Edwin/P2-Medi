// 대화 스토어(Zustand, 메모리 전용. persist를 쓰지 않는다: FE-01-08 A).
// 질문·응답은 이 메모리에만 있고 새로고침하면 사라진다. 브라우저 저장소·쿠키·콘솔에 남기지 않는다.
// 이번 탭의 대화 여러 개(FE-17 U-29)도 같은 메모리 상태(`conversations`)에만 있다: 새로고침하거나 탭을 닫으면 모두 사라진다.
import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import { canRetry, initialStreamState, runChatStream } from "@/lib/api";
import type { Emergency, StreamState } from "@/lib/api";
import { buildChatRequest, commitConfirmedDrugs, createMemoryContextStorage } from "./conversation-context";
import type { ContextStorage, ConversationContext } from "./conversation-context";

export interface ChatTurn {
  id: string;
  question: string;
  /**
   * 말풍선에 보일 표시용 글자(FE-09-04 A: 되묻기에서 고른 약으로 다시 물을 때). 있으면 말풍선은 이 글자를 보이고,
   * 서버로는 항상 `question`(원 질문)을 보낸다. 다른 값과 같이 메모리에만 있다
   */
  display?: string;
  /**
   * 이 차례를 보낼 때의 임신 여부 선택 값(`context.pregnant` 스냅샷, FE-11-03 A): 일반인(false)으로 받은 결과 아래에
   * "임부금기는 '임산부'를 고르면 확인해요" 한 줄을 두기 위해서다. 응답은 요청 context를 돌려주지 않으므로 보낼 때 적어 둔다. 메모리에만 있다.
   * 스토어가 보내는 차례에는 늘 있고, 부품 시험이 만드는 차례에는 없을 수 있다(없으면 한 줄을 두지 않는다)
   */
  pregnant?: boolean | null;
  stream: StreamState;
}

/**
 * 이번 탭의 대화 하나(FE-17 U-29, 2026-11-24 사용자 "새로고침 전에는 지금 대화들의 세션들이 남아있어야"). 메모리에만 있고 새로고침하면 사라진다.
 * 묶음(`context`)·119 안내·진행 중인 차례도 대화마다 따로다
 */
export interface ChatConversation {
  id: string;
  turns: ChatTurn[];
  activeTurnId: string | null;
  emergency: Emergency | null;
  context: ConversationContext;
  /** 이 대화로 돌아올 때 되살릴 화면 문맥(화면이 적는다, 메모리) */
  screen: ChatScreenContext;
}

/** 대화별 화면 문맥(FE-17 U-29): 떠날 때 열려 있던 근거 상세, 질문할 때의 대상 프로필. 질문·답이 아니라 화면 상태다 */
export interface ChatScreenContext {
  /** 그 대화를 떠날 때 열려 있던 근거 상세의 차례 id(또는 뒤에서 도착한 답). 없으면 null */
  evidenceTurnId: string | null;
  /** 그 대화에서 질문할 때 고른 대상 프로필(null = 게스트로 이용). 아직 보낸 적이 없으면 undefined */
  targetProfileId?: string | null;
}

/** 이번 탭에 남겨 두는 대화 수 상한(질문이 있는 대화만 센다). 넘으면 가장 오래된 대화부터 지운다(FE-17 U-29 ⓕ) */
export const CONVERSATIONS_MAX = 20;

export interface ChatState {
  /** 지금 대화의 차례 목록(메모리). `conversations` 중 `currentId` 대화의 값과 같다 */
  turns: ChatTurn[];
  /** 지금 대화의 진행 중인 차례. 한 대화에 한 번에 하나다 */
  activeTurnId: string | null;
  /** 지금 대화에서 받은 119 안내. 한 번 받으면 그 대화를 비우기 전까지 내리지 않는다(S2) */
  emergency: Emergency | null;
  /** 지금 대화의 묶음 */
  context: ConversationContext;
  /**
   * 이번 탭의 대화 전부(만든 순서, 지금 대화 포함, FE-17 U-29). 질문이 없는 대화는 지금 대화일 때만 있다(빈 대화는 쌓지 않는다).
   * 다른 대화의 응답이 진행 중이면 그 대화에 계속 쌓인다(백그라운드 스트림)
   */
  conversations: ChatConversation[];
  /** 지금 대화의 id */
  currentId: string;
  /** 새 질문을 보낸다. 지금 대화의 진행 중인 요청이 있으면 먼저 끊는다. `display`를 주면 말풍선에는 그 글자를 보인다(보내는 것은 `question`) */
  send: (question: string, display?: string) => Promise<void>;
  /** 같은 질문을 다시 보낸다. 사용자가 "다시 시도"를 눌렀을 때만 부른다(자동 재시도 없음) */
  retry: (turnId: string) => Promise<void>;
  /** 진행 중인 요청을 모두 끊는다(화면 이탈 등) */
  abort: () => void;
  /** 지금 대화를 비운다: 그 대화의 목록·119·묶음(이전 선택 포함)을 비우고 진행 중인 요청을 끊는다. 다른 대화는 그대로다 */
  reset: () => void;
  /**
   * 새 대화(사이드바 `새 질문`, FE-17 U-29): 지금 대화는 목록에 남기고(진행 중인 응답은 그 대화에 계속 쌓인다) 빈 새 대화를 연다.
   * 지금 대화에 질문이 없으면 새로 쌓지 않고 그 대화의 묶음만 비운다
   */
  startNew: () => void;
  /** 다른 대화로 옮긴다(목록 항목). 떠나는 대화가 비어 있으면 목록에서 뺀다. 진행 중인 응답은 끊지 않는다 */
  switchTo: (id: string) => void;
  /** 이번 탭의 대화를 모두 지운다. 진행 중인 요청은 모두 끊는다 */
  clearAll: () => void;
  /**
   * 지금 대화만 남기고 이번 탭의 다른 대화를 모두 지운다(로그아웃·탈퇴·계정 전환, FE-17 U-29: 다른 계정의 프로필 문맥과 섞이지 않게).
   * 지금 대화는 예전처럼 그대로 이어진다(로그아웃·탈퇴 뒤에도 보던 대화는 남는다는 기존 동작). 지운 대화의 진행 중인 요청은 끊는다
   */
  keepOnlyCurrent: () => void;
  setContext: (patch: Partial<ConversationContext>) => void;
  /** 대화 하나의 화면 문맥을 적는다(FE-17 U-29). 없는 대화면 아무것도 하지 않는다 */
  setScreen: (id: string, patch: Partial<ChatScreenContext>) => void;
}

export interface ChatStoreOptions {
  run?: typeof runChatStream;
  /** 지금 대화의 묶음을 두는 곳(기본 메모리). 다른 대화의 묶음은 스토어 상태(메모리)에 있다 */
  contextStorage?: ContextStorage;
}

export type ChatStore = StoreApi<ChatState>;

export function createChatStore({ run = runChatStream, contextStorage = createMemoryContextStorage() }: ChatStoreOptions = {}): ChatStore {
  // 대화별 진행 중 요청 하나. 직렬화할 수 없는 값이라 상태 밖에 둔다
  const controllers = new Map<string, AbortController>();
  let sequence = 0;
  let conversationSequence = 0;
  const newConversation = (context: ConversationContext): ChatConversation => {
    conversationSequence += 1;
    return { id: `chat-${conversationSequence}`, turns: [], activeTurnId: null, emergency: null, context, screen: { evidenceTurnId: null } };
  };
  /** 지금 대화의 값을 맨 위 칸으로 비춘다(기존 구독자는 `turns`·`emergency`·`context`만 본다) */
  const mirror = (conversation: ChatConversation) => ({
    turns: conversation.turns,
    activeTurnId: conversation.activeTurnId,
    emergency: conversation.emergency,
    context: conversation.context,
  });
  /** 상한을 넘으면 가장 오래된 대화(지금 대화가 아닌 것)부터 지우고 그 대화의 요청을 끊는다 */
  const prune = (conversations: ChatConversation[], currentId: string) => {
    let filled = conversations.filter((conversation) => conversation.turns.length > 0).length;
    if (filled <= CONVERSATIONS_MAX) return conversations;
    return conversations.filter((conversation) => {
      if (filled <= CONVERSATIONS_MAX || conversation.id === currentId || conversation.turns.length === 0) return true;
      filled -= 1;
      controllers.get(conversation.id)?.abort();
      controllers.delete(conversation.id);
      return false;
    });
  };
  const first = newConversation(contextStorage.read());

  return createStore<ChatState>()((set, get) => {
    const current = () => get().conversations.find((conversation) => conversation.id === get().currentId)!;
    /** 대화 하나를 바꾼다. 지금 대화면 맨 위 칸도 함께 바꾼다(다른 대화의 백그라운드 응답은 맨 위 칸을 건드리지 않는다) */
    const updateConversation = (id: string, update: (conversation: ChatConversation) => ChatConversation) =>
      set((state) => {
        let changed: ChatConversation | null = null;
        const conversations = state.conversations.map((conversation) => {
          if (conversation.id !== id) return conversation;
          changed = update(conversation);
          return changed;
        });
        if (changed === null) return {}; // 그사이 지워진 대화(상한·전부 지움)
        return id === state.currentId ? { conversations, ...mirror(changed) } : { conversations };
      });
    const syncContext = () => updateConversation(get().currentId, (conversation) => ({ ...conversation, context: contextStorage.read() }));

    const execute = async (conversationId: string, id: string, question: string, retry: boolean) => {
      controllers.get(conversationId)?.abort();
      const own = new AbortController();
      controllers.set(conversationId, own);
      // 보내는 순간의 임신 여부 선택을 그 차례에 적어 둔다(다시 시도도 지금 값으로 보낸다)
      updateConversation(conversationId, (conversation) => ({
        ...conversation,
        activeTurnId: id,
        turns: conversation.turns.map((turn) => (turn.id === id ? { ...turn, pregnant: conversation.context.pregnant } : turn)),
      }));
      const sent = get().conversations.find((conversation) => conversation.id === conversationId)!;
      const previous = sent.turns.find((turn) => turn.id === id)?.stream ?? initialStreamState;
      // 답(`answer`)을 받는 즉시 이번 질문의 되묻기 답을 이전 선택으로 옮긴다(AG-21-03 A). 스트림이 끝나기를 기다리지 않는다:
      // 사용자가 답을 보고 바로 다음 질문을 보내면 남은 스트림(done)이 끊기므로, 끝난 뒤에 옮기면 이전 선택을 잃는다.
      // 답 없이 끝났으면(오류·끊김) 옮기지 않아 "다시 시도"가 같은 답을 다시 싣는다.
      // 그사이 다른 대화로 옮겼으면(FE-17 U-29) 그 대화의 묶음(상태에 둔 값)에서 옮긴다: 지금 대화의 묶음과 섞지 않는다
      let committed = false;
      await run(buildChatRequest(question, sent.context), {
        signal: own.signal,
        previous,
        retry,
        onState: (stream) => {
          if (!committed && stream.response) {
            committed = true;
            if (conversationId === get().currentId) {
              contextStorage.write(commitConfirmedDrugs(contextStorage.read()));
              syncContext(); // 답을 반영하기 전에 옮겨 둔다: 답을 본 구독자는 옮겨진 묶음도 함께 본다
            } else {
              updateConversation(conversationId, (conversation) => ({ ...conversation, context: commitConfirmedDrugs(conversation.context) }));
            }
          }
          updateConversation(conversationId, (conversation) => ({
            ...conversation,
            turns: conversation.turns.map((turn) => (turn.id === id ? { ...turn, stream } : turn)),
            emergency: conversation.emergency ?? stream.emergency, // 받는 즉시 기록
          }));
        },
      });
      if (controllers.get(conversationId) === own) {
        controllers.delete(conversationId);
        updateConversation(conversationId, (conversation) => ({ ...conversation, activeTurnId: null }));
      }
    };

    return {
      ...mirror(first),
      conversations: [first],
      currentId: first.id,

      send: async (question, display) => {
        const text = question.trim();
        if (!text) return;
        sequence += 1;
        const id = `turn-${sequence}`;
        const conversationId = get().currentId;
        updateConversation(conversationId, (conversation) => ({
          ...conversation,
          turns: [...conversation.turns, { id, question: text, ...(display ? { display } : {}), pregnant: conversation.context.pregnant, stream: initialStreamState }],
        }));
        // 새 대화가 처음 질문을 받아 목록에 들면 상한을 맞춘다
        const pruned = prune(get().conversations, conversationId);
        if (pruned !== get().conversations) set({ conversations: pruned });
        await execute(conversationId, id, text, false);
      },

      retry: async (turnId) => {
        const turns = current().turns;
        const turn = turns[turns.length - 1];
        if (!turn || turn.id !== turnId || !canRetry(turn.stream)) return; // 마지막 차례만, 다시 시도할 수 있을 때만
        await execute(get().currentId, turn.id, turn.question, true);
      },

      abort: () => {
        for (const controller of controllers.values()) controller.abort();
      },

      reset: () => {
        const id = get().currentId;
        controllers.get(id)?.abort();
        controllers.delete(id);
        contextStorage.clear();
        updateConversation(id, (conversation) => ({ ...conversation, turns: [], activeTurnId: null, emergency: null, context: contextStorage.read() }));
      },

      startNew: () => {
        if (current().turns.length === 0) {
          get().reset();
          return;
        }
        contextStorage.clear();
        const next = newConversation(contextStorage.read());
        set((state) => ({ conversations: [...state.conversations, next], currentId: next.id, ...mirror(next) }));
      },

      switchTo: (id) => {
        const { currentId, conversations } = get();
        const target = conversations.find((conversation) => conversation.id === id);
        if (id === currentId || !target) return;
        const leaving = current();
        contextStorage.write(target.context);
        set({
          // 질문 없이 떠나는 빈 대화는 남기지 않는다
          conversations: leaving.turns.length === 0 ? conversations.filter((conversation) => conversation.id !== leaving.id) : conversations,
          currentId: id,
          ...mirror(target),
        });
      },

      clearAll: () => {
        for (const controller of controllers.values()) controller.abort();
        controllers.clear();
        contextStorage.clear();
        const next = newConversation(contextStorage.read());
        set({ conversations: [next], currentId: next.id, ...mirror(next) });
      },

      keepOnlyCurrent: () => {
        const { conversations, currentId } = get();
        if (conversations.length === 1) return;
        for (const conversation of conversations) {
          if (conversation.id === currentId) continue;
          controllers.get(conversation.id)?.abort();
          controllers.delete(conversation.id);
        }
        set({ conversations: conversations.filter((conversation) => conversation.id === currentId) });
      },

      setContext: (patch) => {
        contextStorage.write({ ...contextStorage.read(), ...patch });
        syncContext();
      },

      setScreen: (id, patch) => updateConversation(id, (conversation) => ({ ...conversation, screen: { ...conversation.screen, ...patch } })),
    };
  });
}

/** 앱 전체가 쓰는 스토어 하나 */
export const chatStore = createChatStore();

export function useChatStore<T>(selector: (state: ChatState) => T, store: ChatStore = chatStore): T {
  return useStore(store, selector);
}
