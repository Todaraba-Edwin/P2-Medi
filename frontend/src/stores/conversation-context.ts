// 대화 상태 한 입력 묶음(FE-01 완료 조건, PRD-07-01 A): 같은 대화 안에서 이미 말한 값.
// 브라우저 메모리에만 두고 새로고침하면 사라진다. 저장 위치는 ContextStorage 구현만 바꿔 끼우면 된다
// (예: 로그인 프로필은 서버, BE-11 확장). 질문 문장·응답은 여기에 넣지 않는다.
import { CONFIRMED_DRUGS_MAX, DRUG_NAME_MAX_CHARS } from "@/lib/api";
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
  /** 그 약을 고른 되묻기 묶음의 이름(후보의 `input_name` 그대로, FE-09-05 A). 되묻기를 거치지 않은 값이면 없다 */
  inputName?: string | null;
}

export interface ConversationContext {
  /** 먹는 사람의 나이. **확정 값만 구간으로** 둔다(사용자가 쓴 자유 글 나이는 넣지 않는다). 모르면 null */
  age: AgeRange | null;
  /** 임신 여부. 말하지 않았으면 null */
  pregnant: boolean | null;
  /** **이번 질문**의 되묻기 답(같은 질문을 다시 보낼 때만 찬다, AG-21-02 A). 응답이 오면 `priorDrugs`로 옮기고 비운다 */
  confirmedDrugs: ConfirmedDrug[];
  /**
   * 이전 차례에서 고른 약(AG-21-02·03 A). 서버는 확정에 쓰지 않고 같은 이름이 다시 나오면 확인 되묻기의 첫 후보로만 쓴다.
   * 새 대화·"누가 먹나요" 대상 변경 때 비운다. 메모리에만 있다
   */
  priorDrugs: ConfirmedDrug[];
  /** 용량주의 되묻기 답(AG-22-05 A): 예 `true`, 아니요 `false`, 아직 답하지 않았으면 null. 되묻기 카드는 4단계 디자인 뒤에 만든다 */
  tookToday: boolean | null;
}

export const emptyConversationContext: ConversationContext = { age: null, pregnant: null, confirmedDrugs: [], priorDrugs: [], tookToday: null };

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
/** 서버 규칙(비어 있지 않고 약 이름 상한 이하)에 맞는 입력 이름만 싣는다. 아니면 null(서버는 이전 규칙으로 매칭한다) */
const inputNameOf = (drug: ConfirmedDrug) => (drug.inputName && drug.inputName.trim().length > 0 && drug.inputName.length <= DRUG_NAME_MAX_CHARS ? drug.inputName : null);

/** 약 목록을 요청 모양으로: 품목 번호는 9자리 숫자일 때만, 서버 상한까지만(뒤에 고른 것이 남는다). `confirmed_drugs`·`prior_drugs`가 같은 규칙이다 */
const toRequestDrugs = (drugs: ConfirmedDrug[]) =>
  drugs.slice(-CONFIRMED_DRUGS_MAX).map((drug) => ({ name: drug.name, item_seq: drug.itemSeq !== null && ITEM_SEQ.test(drug.itemSeq) ? drug.itemSeq : null, input_name: inputNameOf(drug) }));

/**
 * 요청 본문을 만드는 한 곳(`ChatRequest` v1). 요청마다 묶음 값만 `context`로 싣는다.
 * 되묻기에서 고른 약에는 그 묶음의 이름을 `input_name`으로 함께 싣는다(FE-09-05 A, 서버가 이름별로 매칭한다).
 * 이번 질문의 답(`confirmed_drugs`)과 이전 차례의 선택(`prior_drugs`)은 다른 칸으로 나눠 싣는다(AG-21-02 A). 용량주의 답은 `took_today`다
 */
export function buildChatRequest(question: string, context: ConversationContext): ChatRequest {
  return {
    question,
    context: {
      age: context.age,
      pregnant: context.pregnant,
      confirmed_drugs: toRequestDrugs(context.confirmedDrugs),
      prior_drugs: toRequestDrugs(context.priorDrugs),
      took_today: context.tookToday,
    },
  };
}

/** 같은 제품이거나 같은 묶음 이름(`inputName`)으로 고른 이전 선택은 새 선택으로 바꾼다 */
const supersededBy = (chosen: ConfirmedDrug[]) => {
  const names = new Set(chosen.map((drug) => drug.name));
  const inputNames = new Set(chosen.flatMap((drug) => (drug.inputName ? [drug.inputName] : [])));
  return (drug: ConfirmedDrug) => names.has(drug.name) || (drug.inputName !== undefined && drug.inputName !== null && inputNames.has(drug.inputName));
};

/**
 * 응답이 온 뒤 이번 질문의 답을 이전 선택으로 옮긴 묶음(AG-21-03 A): `priorDrugs`에 더하고(겹치는 것은 새 선택으로 바꿈, 상한까지만) `confirmedDrugs`를 비운다.
 * 답이 없었으면 그대로다
 */
export function commitConfirmedDrugs(context: ConversationContext): ConversationContext {
  if (context.confirmedDrugs.length === 0) return context;
  const superseded = supersededBy(context.confirmedDrugs);
  const priorDrugs = [...context.priorDrugs.filter((drug) => !superseded(drug)), ...context.confirmedDrugs].slice(-CONFIRMED_DRUGS_MAX);
  return { ...context, priorDrugs, confirmedDrugs: [] };
}
