// 스트림 시나리오(합성). 이벤트 형식은 4장 (4) 초안(`chat_event@v0`).
import { ChatEventSchema } from "@/lib/api/schemas";
import type { ChatEvent, ChatEventInput, ChatResponse } from "@/lib/api/types";
import { PHRASES } from "./phrases";
import {
  clarifyResponse,
  emergencyResponse,
  foundResponse,
  notListedResponse,
  refuseResponse,
} from "./responses";

export type ScenarioEnding =
  | "close" // 서버가 정상으로 닫음
  | "cut" // 본문 읽기 중 연결이 끊김(읽기 오류)
  | "hang"; // 닫지 않고 멈춤(무응답 상한 시험용)

export type MockScenario =
  | { kind: "stream"; events: ChatEvent[]; ending: ScenarioEnding }
  | { kind: "http"; status: number };

type EventBody = ChatEventInput extends infer E ? (E extends unknown ? Omit<E, "seq" | "schema_version"> : never) : never;

/** seq와 schema_version을 붙이고 zod를 통과시킨다. */
function events(...bodies: EventBody[]): ChatEvent[] {
  return bodies.map((body, seq) => ChatEventSchema.parse({ ...body, seq, schema_version: "chat_event@v0" }));
}

const progress = (stage: "drug_lookup" | "contraindication_check" | "evidence_search"): EventBody => ({ type: "progress", stage });
const answer = (response: ChatResponse): EventBody => ({ type: "answer", response });
const done = (response: ChatResponse): EventBody => ({ type: "done", end_reason: response.end_reason });
const threeSteps = [progress("drug_lookup"), progress("contraindication_check"), progress("evidence_search")];

export const scenarios = {
  /** 정상(금기 발견) */
  found: { kind: "stream", ending: "close", events: events(...threeSteps, answer(foundResponse), done(foundResponse)) },
  /** 목록에 없음 */
  notListed: {
    kind: "stream",
    ending: "close",
    events: events(...threeSteps, answer(notListedResponse), done(notListedResponse)),
  },
  /** 응급: 첫 이벤트가 emergency, 뒤에 결과가 이어진다 */
  emergency: {
    kind: "stream",
    ending: "close",
    events: events(
      { type: "emergency", emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL } },
      ...threeSteps,
      answer(emergencyResponse),
      done(emergencyResponse),
    ),
  },
  /** 응급 첫 이벤트 뒤 answer 전에 끊김 */
  emergencyCut: {
    kind: "stream",
    ending: "cut",
    events: events(
      { type: "emergency", emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL } },
      progress("drug_lookup"),
    ),
  },
  /** 되묻기 */
  clarify: { kind: "stream", ending: "close", events: events(progress("drug_lookup"), answer(clarifyResponse), done(clarifyResponse)) },
  /** 거절(진행 없이 바로 답) */
  refuse: { kind: "stream", ending: "close", events: events(answer(refuseResponse), done(refuseResponse)) },
  /** 서버 오류 이벤트. 오류 문구 상수가 백엔드에 아직 없어 자리 글자만 둔다(BE-06과 확인) */
  serverError: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), { type: "error", code: "MOCK_SERVER_ERROR", message: "[mock] 오류 문구 자리" }, { type: "done" }),
  },
  /** answer 전 끊김(읽기 오류) */
  cutBeforeAnswer: { kind: "stream", ending: "cut", events: events(progress("drug_lookup"), progress("contraindication_check")) },
  /** answer 전에 done 없이 닫힘 */
  closeBeforeAnswer: { kind: "stream", ending: "close", events: events(progress("drug_lookup")) },
  /** answer 뒤 done 없이 닫힘 */
  answerWithoutDone: { kind: "stream", ending: "close", events: events(...threeSteps, answer(foundResponse)) },
  /** 이벤트 하나 뒤 멈춤(무응답) */
  hang: { kind: "stream", ending: "hang", events: events(progress("drug_lookup")) },
  /** HTTP 오류 */
  http400: { kind: "http", status: 400 },
  http500: { kind: "http", status: 500 },
} satisfies Record<string, MockScenario>;

export type ScenarioName = keyof typeof scenarios;
