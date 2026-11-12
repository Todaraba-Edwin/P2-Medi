// 대화 상태 한 입력 묶음(FE-01 완료 조건, PRD-07-01 A): 같은 대화 안에서 이미 말한 값.
// 브라우저 메모리에만 두고 새로고침하면 사라진다. 저장 위치는 ContextStorage 구현만 바꿔 끼우면 된다
// (예: 로그인 프로필은 서버, BE-11 확장). 질문 문장·응답은 여기에 넣지 않는다.
import type { ChatRequest } from "@/lib/api";

export interface ConversationContext {
  /** 먹는 사람의 나이(사용자가 말한 그대로). 모르면 null */
  age: string | null;
  /** 임신 여부. 말하지 않았으면 null */
  pregnant: boolean | null;
  /** 되묻기 등으로 사용자가 확인한 약 이름 */
  confirmedDrugs: string[];
}

export const emptyConversationContext: ConversationContext = { age: null, pregnant: null, confirmedDrugs: [] };

export interface ContextStorage {
  read(): ConversationContext;
  write(next: ConversationContext): void;
  clear(): void;
}

/** 기본 구현: 메모리 */
export function createMemoryContextStorage(): ContextStorage {
  let value = emptyConversationContext;
  return {
    read: () => value,
    write: (next) => {
      value = next;
    },
    clear: () => {
      value = emptyConversationContext;
    },
  };
}

/**
 * 요청 본문을 만드는 한 곳. 요청마다 필요한 값만 보낸다.
 * 가정: 지금 요청 모델(`chat_response@v0` 골격)은 질문 한 칸뿐이라 묶음 값은 아직 싣지 않는다.
 * BE-06 v1이 요청 모델을 정하면(FE-IMPL-03) 여기만 고친다.
 */
export function buildChatRequest(question: string, context: ConversationContext): ChatRequest {
  void context;
  return { question };
}
