// 스트림 시나리오(합성, `chat_event@v1`). 진행 문구(`label`)는 백엔드 상수 원문이다(phrases.ts).
import { ChatEventSchema } from "@/lib/api/schemas";
import type { ChatEvent, ChatEventInput, ChatResponse, ProgressStage } from "@/lib/api/types";
import { PHRASES, PROGRESS_LABELS } from "./phrases";
import {
  ageFoundResponse,
  ageInfoResponse,
  apiFailResponse,
  clarifyResponse,
  codeNotLinkedResponse,
  emergencyResponse,
  fallbackNoneResponse,
  fallbackSomeResponse,
  foundResponse,
  gradeDefsResponse,
  gradeMismatchResponse,
  limitResponse,
  missingCausesResponse,
  missingEvidenceResponse,
  notCheckedResponse,
  notListedResponse,
  pairNoEvidenceResponse,
  pairAndPregnancyResponse,
  pregnancyMResponse,
  pregnancyResponse,
  refuseResponse,
  rxPermitResponse,
  typoCorrectedResponse,
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
const emergency: EventBody = {
  type: "emergency",
  emergency: { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL, wide_text: PHRASES.EMERGENCY_119_WIDE },
};
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
  /** 서버 오류 이벤트. `message`는 오류 문구 상수(`ERROR_MESSAGES[code]`)이고 항상 온다(2026-11-12 승인 뒤). 화면은 받은 글자를 그대로 보인다 */
  serverError: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), { type: "error", code: "INTERNAL_ERROR", message: PHRASES.ERROR_INTERNAL }, { type: "done" }),
  },
  /** 서버 오류 이벤트(다른 코드: 외부 연결 실패). 이름은 예전 것을 유지했다(지금은 이 코드도 문구가 온다) */
  serverErrorNoMessage: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), { type: "error", code: "UPSTREAM_UNAVAILABLE", message: PHRASES.ERROR_UPSTREAM_UNAVAILABLE }, { type: "done" }),
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
  // ---- FE-IMPL-06 추가(흐름 시험용)
  /** 미확보 나머지 세 원인 + 박스 안 약사 확인 권고 */
  missingCauses: normal(missingCausesResponse),
  /** 검증 폴백(확인된 항목 없음) */
  fallbackNone: normal(fallbackNoneResponse),
  /** 검증 폴백(확인된 항목만) */
  fallbackSome: normal(fallbackSomeResponse),
  /** 쌍 확인 불가(배지 없는 쌍 줄) */
  pairNoEvidence: normal(pairNoEvidenceResponse),
  /** 허가사항 원문 인용(한 줄 설명·전문의약품 안내 줄·용법용량 인용 고지) */
  rxPermit: normal(rxPermitResponse),
  // ---- FE-IMPL-08 추가(AG-08·BE-06-13~17의 새 칸)
  /** 나이를 특정할 수 없을 때: 나이별 연령금기 원문 값 + 안내 줄, 성분 중복 줄 */
  ageInfo: normal(ageInfoResponse),
  /** 등급 정의 블록(원문 블록 + 미확보 블록) */
  gradeDefs: normal(gradeDefsResponse),
  /** 정보가 없어 확인하지 못한 종류의 줄 */
  notChecked: normal(notCheckedResponse),
  /** 코드가 이어지지 않아 확인하지 못한 줄(바뀐 안내 문구) */
  codeNotLinked: normal(codeNotLinkedResponse),
  /** 공공 API 실패 배너 */
  apiFail: normal(apiFailResponse),
  // ---- FE-02 추가(AG-10-02 A `name_corrections`)
  /** 오탈자 보정 고지 + 병용금기(가짜 서버 `typo`와 같은 흐름: progress×2 → answer → done) */
  typoCorrected: {
    kind: "stream",
    ending: "close",
    events: events(progress("drug_lookup"), progress("contraindication_check"), answer(typoCorrectedResponse), done(typoCorrectedResponse)),
  },
} satisfies Record<string, MockScenario>;

export type ScenarioName = keyof typeof scenarios;
