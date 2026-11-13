// 대화 상태 한 입력 묶음(FE-01 완료 조건, PRD-07-01 A): 같은 대화 안에서 이미 말한 값.
// 브라우저 메모리에만 두고 새로고침하면 사라진다. 저장 위치는 ContextStorage 구현만 바꿔 끼우면 된다
// (예: 로그인 프로필은 서버, BE-11 확장). 질문 문장·응답은 여기에 넣지 않는다.
import { CONFIRMED_DRUGS_MAX } from "@/lib/api";
import type { ChatRequest } from "@/lib/api";

/** 먹는 사람의 나이 구간(요청 `context.age`와 같은 모양). 한 나이면 두 값이 같다 */
export interface AgeRange {
  lower: number;
  upper: number;
  unit: "세" | "개월" | "주";
}

/** 사용자가 확인한 약(되묻기 후보에서 고른 값). 이름·품목 번호는 응답이 준 값 그대로다 */
export interface ConfirmedDrug {
  name: string;
  itemSeq: string | null;
}

export interface ConversationContext {
  /** 먹는 사람의 나이. **확정 값만 구간으로** 둔다(사용자가 쓴 자유 글 나이는 넣지 않는다). 모르면 null */
  age: AgeRange | null;
  /** 임신 여부. 말하지 않았으면 null */
  pregnant: boolean | null;
  /** 되묻기 등으로 사용자가 확인한 약 */
  confirmedDrugs: ConfirmedDrug[];
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

const ITEM_SEQ = /^\d{9}$/;

/**
 * 요청 본문을 만드는 한 곳(`ChatRequest` v1). 요청마다 묶음 값만 `context`로 싣는다.
 * 품목 번호는 9자리 숫자일 때만 싣고, 확인한 약은 서버 상한까지만 싣는다(뒤에 고른 것이 남는다).
 */
export function buildChatRequest(question: string, context: ConversationContext): ChatRequest {
  return {
    question,
    context: {
      age: context.age,
      pregnant: context.pregnant,
      confirmed_drugs: context.confirmedDrugs
        .slice(-CONFIRMED_DRUGS_MAX)
        .map((drug) => ({ name: drug.name, item_seq: drug.itemSeq !== null && ITEM_SEQ.test(drug.itemSeq) ? drug.itemSeq : null })),
    },
  };
}
