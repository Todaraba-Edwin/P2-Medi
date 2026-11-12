// 대화 스토어(Zustand, 메모리 전용. persist를 쓰지 않는다: FE-01-08 A).
// 질문·응답은 이 메모리에만 있고 새로고침하면 사라진다. 브라우저 저장소·쿠키·콘솔에 남기지 않는다.
import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import { canRetry, initialStreamState, runChatStream } from "@/lib/api";
import type { Emergency, StreamState } from "@/lib/api";
import { buildChatRequest, createMemoryContextStorage } from "./conversation-context";
import type { ContextStorage, ConversationContext } from "./conversation-context";

export interface ChatTurn {
  id: string;
  question: string;
  stream: StreamState;
}

export interface ChatState {
  /** 대화 목록(메모리) */
  turns: ChatTurn[];
  /** 진행 중인 차례. 한 번에 하나다 */
  activeTurnId: string | null;
  /** 이 대화에서 받은 119 안내. 한 번 받으면 새 대화(reset) 전까지 내리지 않는다(S2) */
  emergency: Emergency | null;
  context: ConversationContext;
  /** 새 질문을 보낸다. 진행 중인 요청이 있으면 먼저 끊는다 */
  send: (question: string) => Promise<void>;
  /** 같은 질문을 다시 보낸다. 사용자가 "다시 시도"를 눌렀을 때만 부른다(자동 재시도 없음) */
  retry: (turnId: string) => Promise<void>;
  /** 진행 중인 요청을 끊는다(화면 이탈 등) */
  abort: () => void;
  /** 새 대화: 목록·119·묶음을 비운다 */
  reset: () => void;
  setContext: (patch: Partial<ConversationContext>) => void;
}

export interface ChatStoreOptions {
  run?: typeof runChatStream;
  contextStorage?: ContextStorage;
}

export type ChatStore = StoreApi<ChatState>;

export function createChatStore({ run = runChatStream, contextStorage = createMemoryContextStorage() }: ChatStoreOptions = {}): ChatStore {
  // 진행 중 요청 하나. 직렬화할 수 없는 값이라 상태 밖에 둔다
  let controller: AbortController | null = null;
  let sequence = 0;

  return createStore<ChatState>()((set, get) => {
    const patchTurn = (id: string, stream: StreamState) =>
      set((state) => ({
        turns: state.turns.map((turn) => (turn.id === id ? { ...turn, stream } : turn)),
        emergency: state.emergency ?? stream.emergency, // 받는 즉시 기록
      }));

    const execute = async (id: string, question: string, retry: boolean) => {
      controller?.abort();
      const own = new AbortController();
      controller = own;
      set({ activeTurnId: id });
      const previous = get().turns.find((turn) => turn.id === id)?.stream ?? initialStreamState;
      await run(buildChatRequest(question, get().context), {
        signal: own.signal,
        previous,
        retry,
        onState: (stream) => patchTurn(id, stream),
      });
      if (controller === own) {
        controller = null;
        set({ activeTurnId: null });
      }
    };

    return {
      turns: [],
      activeTurnId: null,
      emergency: null,
      context: contextStorage.read(),

      send: async (question) => {
        const text = question.trim();
        if (!text) return;
        sequence += 1;
        const id = `turn-${sequence}`;
        set((state) => ({ turns: [...state.turns, { id, question: text, stream: initialStreamState }] }));
        await execute(id, text, false);
      },

      retry: async (turnId) => {
        const turns = get().turns;
        const turn = turns[turns.length - 1];
        if (!turn || turn.id !== turnId || !canRetry(turn.stream)) return; // 마지막 차례만, 다시 시도할 수 있을 때만
        await execute(turn.id, turn.question, true);
      },

      abort: () => controller?.abort(),

      reset: () => {
        controller?.abort();
        controller = null;
        contextStorage.clear();
        set({ turns: [], activeTurnId: null, emergency: null, context: contextStorage.read() });
      },

      setContext: (patch) => {
        contextStorage.write({ ...contextStorage.read(), ...patch });
        set({ context: contextStorage.read() });
      },
    };
  });
}

/** 앱 전체가 쓰는 스토어 하나 */
export const chatStore = createChatStore();

export function useChatStore<T>(selector: (state: ChatState) => T, store: ChatStore = chatStore): T {
  return useStore(store, selector);
}
