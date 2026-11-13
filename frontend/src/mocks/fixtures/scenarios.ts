// 스트림 시나리오(합성, `chat_event@v1`). 진행 문구(`label`)는 백엔드 상수 원문이다(phrases.ts).
import { ChatEventSchema } from "@/lib/api/schemas";
import type { ChatEvent, ChatEventInput, ChatResponse, ProgressStage } from "@/lib/api/types";
import { PHRASES, PROGRESS_LABELS } from "./phrases";
import {
  ageFoundResponse,
  clarifyResponse,
  emergencyResponse,
  fallbackNoneResponse,
  fallbackSomeResponse,
  foundResponse,
  gradeMismatchResponse,
  limitResponse,
  missingCausesResponse,
  missingEvidenceResponse,
  notListedResponse,
  pairNoEvidenceResponse,
  pairAndPregnancyResponse,
  pregnancyMResponse,
  pregnancyResponse,
  refuseResponse,
  rxPermitResponse,
  unidentifiedResponse,
} from "./responses";

export type ScenarioEnding =
  | "close" // 서버가 정상으로 닫음
  | "cut" // 본문 읽기 중 연결이 끊김(읽기 오류)
  | "hang"; // 닫지 않고 멈춤(무응답 상한 시험용)

export type MockScenario =
  | {
      kind: "stream";
      events: ChatEvent[];
      ending: ScenarioEnding;
      /** 이벤트마다 그 앞에 보내는 빈 줄(하트비트) 수 */
      heartbeats?: number;
    }
  | { kind: "http"; status: number; code?: string; fields?: string[] };

type EventBody = ChatEventInput extends infer E ? (E extends unknown ? Omit<E, "seq" | "schema_version"> : never) : never;

/** seq(0부터 1씩)와 schema_version을 붙이고 zod를 통과시킨다. */
function events(...bodies: EventBody[]): ChatEvent[] {
  return bodies.map((body, seq) => ChatEventSchema.parse({ ...body, seq, schema_version: "chat_event@v1" }));
}

const progress = (stage: ProgressStage): EventBody => ({ type: "progress", stage, label: PROGRESS_LABELS[stage] });
const answer = (response: ChatResponse): EventBody => ({ type: "answer", response });
const done = (response: ChatResponse): EventBody => ({ type: "done", end_reason: response.end_reason });
const emergency: EventBody = { type: "emergency", emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL } };
const threeSteps = [progress("drug_lookup"), progress("contraindication_check"), progress("evidence_search")];
/** 진행 세 줄 → 답 → done */
const normal = (response: ChatResponse): MockScenario => ({
  kind: "stream",
  ending: "close",
  events: events(...threeSteps, answer(response), done(response)),
});

export const scenarios = {
  /** 정상(병용금기 발견, 쌍 줄) */
  found: { kind: "stream", ending: "close", events: events(...threeSteps, answer(foundResponse), done(foundResponse)) },
  /** 목록에 없음 */
  notListed: {
    kind: "stream",
    ending: "close",
    events: events(...threeSteps, answer(notListedResponse), done(notListedResponse)),
  },
  /** 응급: 첫 이벤트(seq 0)가 emergency, 뒤에 결과가 이어진다 */
  emergency: {
    kind: "stream",
    ending: "close",
    events: events(emergency, ...threeSteps, answer(emergencyResponse), done(emergencyResponse)),
  },
  /** 응급 첫 이벤트 뒤 answer 전에 끊김 */
  emergencyCut: { kind: "stream", ending: "cut", events: events(emergency, progress("drug_lookup")) },
  /** 되묻기(후보 목록) */
  clarify: { kind: "stream", ending: "close", events: events(progress("drug_lookup"), answer(clarifyResponse), done(clarifyResponse)) },
  /** 거절(진행 없이 바로 답) */
  refuse: { kind: "stream", ending: "close", events: events(answer(refuseResponse), done(refuseResponse)) },
  /**
   * 서버 오류 이벤트(문구가 실려 온 경우). 오류 문구 상수는 사용자 승인 전이라 **지금 서버는 null을 보낸다**(serverErrorNoMessage).
   * 이 시나리오의 글자는 "받은 문구를 그대로 보인다"를 시험하려는 자리 글자이며 실제 문구가 아니다.
   */
  serverError: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), { type: "error", code: "INTERNAL_ERROR", message: "[mock] 오류 문구 자리" }, { type: "done" }),
  },
  /** 서버 오류 이벤트(지금 서버 모양: 문구 null → 화면 상수를 쓴다) */
  serverErrorNoMessage: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), { type: "error", code: "UPSTREAM_UNAVAILABLE", message: null }, { type: "done" }),
  },
  /** answer 전 끊김(읽기 오류) */
  cutBeforeAnswer: { kind: "stream", ending: "cut", events: events(progress("drug_lookup"), progress("contraindication_check")) },
  /** answer 전에 done 없이 닫힘 */
  closeBeforeAnswer: { kind: "stream", ending: "close", events: events(progress("drug_lookup")) },
  /** answer 뒤 done 없이 닫힘 */
  answerWithoutDone: { kind: "stream", ending: "close", events: events(...threeSteps, answer(foundResponse)) },
  /** 이벤트 하나 뒤 멈춤(무응답) */
  hang: { kind: "stream", ending: "hang", events: events(progress("drug_lookup")) },
  /** 이벤트 사이에 빈 줄(하트비트)이 온다 */
  heartbeat: { kind: "stream", ending: "close", heartbeats: 3, events: events(progress("drug_lookup"), answer(foundResponse), done(foundResponse)) },
  /** HTTP 오류(본문 `{code, fields}`) */
  http400: { kind: "http", status: 400 },
  http422: { kind: "http", status: 422, code: "INVALID_REQUEST", fields: ["question"] },
  http500: { kind: "http", status: 500 },
  /** 엔드포인트가 아직 그래프에 연결되지 않았을 때의 서버 응답 */
  http501: { kind: "http", status: 501, code: "NOT_IMPLEMENTED" },

  // ---- 화면 부품(FE-IMPL-04·05)용 결과 모양
  /** 임부금기 발견(등급 배지 1개, 성분 칩) */
  pregnancy: normal(pregnancyResponse),
  /** 병용 + 임부(쌍 줄과 제품 줄) */
  pairAndPregnancy: normal(pairAndPregnancyResponse),
  /** 등급 불일치(파일·성분 API 배지 둘) */
  gradeMismatch: normal(gradeMismatchResponse),
  /** 임부금기 M등급 */
  pregnancyM: normal(pregnancyMResponse),
  /** 연령금기 발견(나이 기준 값) */
  ageFound: normal(ageFoundResponse),
  /** 미식별(약을 찾지 못함) */
  unidentified: normal(unidentifiedResponse),
  /** 근거 원문 미확보 + 약사 확인 권고 줄 */
  missingEvidence: normal(missingEvidenceResponse),
  /** 상한 도달(상단 배너) */
  limit: normal(limitResponse),
  // ---- FE-IMPL-06 추가(흐름 시험용. 질문 표시 글자(`mock:`)는 handlers.ts 소유라 붙이지 않았다)
  /** 미확보 나머지 세 원인 + 박스 안 약사 확인 권고 */
  missingCauses: normal(missingCausesResponse),
  /** 검증 폴백(확인된 항목 없음) */
  fallbackNone: normal(fallbackNoneResponse),
  /** 검증 폴백(확인된 항목만) */
  fallbackSome: normal(fallbackSomeResponse),
  /** 쌍 확인 불가(배지 없는 쌍 줄) */
  pairNoEvidence: normal(pairNoEvidenceResponse),
  /** 허가사항 원문 인용 */
  rxPermit: normal(rxPermitResponse),
} satisfies Record<string, MockScenario>;

export type ScenarioName = keyof typeof scenarios;
