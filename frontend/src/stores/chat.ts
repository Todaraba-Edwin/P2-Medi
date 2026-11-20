// 대화 스토어(Zustand, 메모리 전용. persist를 쓰지 않는다: FE-01-08 A).
// 질문·응답은 이 메모리에만 있고 새로고침하면 사라진다. 브라우저 저장소·쿠키·콘솔에 남기지 않는다.
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

export interface ChatState {
  /** 대화 목록(메모리) */
  turns: ChatTurn[];
  /** 진행 중인 차례. 한 번에 하나다 */
  activeTurnId: string | null;
  /** 이 대화에서 받은 119 안내. 한 번 받으면 새 대화(reset) 전까지 내리지 않는다(S2) */
  emergency: Emergency | null;
  context: ConversationContext;
  /** 새 질문을 보낸다. 진행 중인 요청이 있으면 먼저 끊는다. `display`를 주면 말풍선에는 그 글자를 보인다(보내는 것은 `question`) */
  send: (question: string, display?: string) => Promise<void>;
  /** 같은 질문을 다시 보낸다. 사용자가 "다시 시도"를 눌렀을 때만 부른다(자동 재시도 없음) */
  retry: (turnId: string) => Promise<void>;
  /** 진행 중인 요청을 끊는다(화면 이탈 등) */
  abort: () => void;
  /** 새 대화: 목록·119·묶음(이전 선택 포함)을 비운다 */
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
      // 보내는 순간의 임신 여부 선택을 그 차례에 적어 둔다(다시 시도도 지금 값으로 보낸다)
      set((state) => ({ activeTurnId: id, turns: state.turns.map((turn) => (turn.id === id ? { ...turn, pregnant: state.context.pregnant } : turn)) }));
      const previous = get().turns.find((turn) => turn.id === id)?.stream ?? initialStreamState;
      // 답(`answer`)을 받는 즉시 이번 질문의 되묻기 답을 이전 선택으로 옮긴다(AG-21-03 A). 스트림이 끝나기를 기다리지 않는다:
      // 사용자가 답을 보고 바로 다음 질문을 보내면 남은 스트림(done)이 끊기므로, 끝난 뒤에 옮기면 이전 선택을 잃는다.
      // 답 없이 끝났으면(오류·끊김) 옮기지 않아 "다시 시도"가 같은 답을 다시 싣는다
      let committed = false;
      await run(buildChatRequest(question, get().context), {
        signal: own.signal,
        previous,
        retry,
        onState: (stream) => {
          if (!committed && stream.response) {
            committed = true;
            contextStorage.write(commitConfirmedDrugs(contextStorage.read()));
            set({ context: contextStorage.read() }); // 답을 반영하기 전에 옮겨 둔다: 답을 본 구독자는 옮겨진 묶음도 함께 본다
          }
          patchTurn(id, stream);
        },
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

      send: async (question, display) => {
        const text = question.trim();
        if (!text) return;
        sequence += 1;
        const id = `turn-${sequence}`;
        set((state) => ({ turns: [...state.turns, { id, question: text, ...(display ? { display } : {}), pregnant: state.context.pregnant, stream: initialStreamState }] }));
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
