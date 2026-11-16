// MSW 핸들러: `POST /api/chat` → NDJSON 스트림(합성 fixture). 개발·시험 전용이다.
import { HttpResponse, delay, http } from "msw";
import { ChatRequestSchema } from "@/lib/api/schemas";
import { scenarios } from "./fixtures/scenarios";
import type { MockScenario, ScenarioName } from "./fixtures/scenarios";

/** 질문에 이 글자가 있으면 해당 시나리오를 돌려준다(개발 미리보기용 합성 규칙. 실제 서버의 응급 감지와 무관하다). */
export const SCENARIO_KEYWORDS: ReadonlyArray<readonly [string, ScenarioName]> = [
  ["mock:응급끊김", "emergencyCut"],
  ["mock:응급", "emergency"],
  ["mock:없음", "notListed"],
  ["mock:되묻기", "clarify"],
  ["mock:거절", "refuse"],
  ["mock:오류이벤트", "serverError"],
  ["mock:끊김", "cutBeforeAnswer"],
  ["mock:닫힘", "closeBeforeAnswer"],
  ["mock:done없음", "answerWithoutDone"],
  ["mock:무응답", "hang"],
  ["mock:오류코드", "serverErrorNoMessage"],
  ["mock:하트비트", "heartbeat"],
  ["mock:400", "http400"],
  ["mock:422", "http422"],
  ["mock:500", "http500"],
  ["mock:501", "http501"],
  ["mock:임부M", "pregnancyM"],
  ["mock:임부", "pregnancy"],
  ["mock:병용임부", "pairAndPregnancy"],
  ["mock:등급불일치", "gradeMismatch"],
  ["mock:연령", "ageFound"],
  ["mock:미식별", "unidentified"],
  ["mock:미확보", "missingEvidence"],
  ["mock:상한", "limit"],
];

/** 되묻기 뒤 재전송(고른 약이 `context.confirmed_drugs`에 실려 옴)에 돌려줄 결과 시나리오 */
export const CONFIRMED_SCENARIO: ScenarioName = "found";

/**
 * 질문의 표시 글자로 시나리오를 고른다. 되묻기(`mock:되묻기`)라도 고른 약이 실려 오면(`confirmedDrugs` > 0) 다시 묻지 않고
 * 결과로 답한다(FE-IMPL-06b: 재전송 흐름을 워커로 끝까지 볼 수 있게. 실제 서버의 되묻기 판정과는 무관한 합성 규칙).
 */
export function pickScenario(question: string, confirmedDrugs = 0): ScenarioName {
  const picked = SCENARIO_KEYWORDS.find(([keyword]) => question.includes(keyword))?.[1] ?? "found";
  return picked === "clarify" && confirmedDrugs > 0 ? CONFIRMED_SCENARIO : picked;
}

/** 시나리오를 NDJSON 응답으로 바꾼다. 이벤트 사이에 `delayMs`만큼 쉰다. */
export function scenarioResponse(scenario: MockScenario, delayMs = 0): Response {
  if (scenario.kind === "http") {
    // 서버의 4xx·5xx 본문 모양: `{code, fields}`(입력 값·문구 없음). code가 없으면 본문 없이 보낸다
    if (!scenario.code) return new HttpResponse(null, { status: scenario.status });
    return HttpResponse.json({ code: scenario.code, fields: scenario.fields ?? [] }, { status: scenario.status });
  }
  const encoder = new TextEncoder();
  const heartbeats = scenario.heartbeats ?? 0;
  let index = 0;
  let beats = 0;
  // pull 방식: 앞 이벤트가 읽힌 뒤에 다음 것을 낸다(끊김이 앞 이벤트를 지우지 않게)
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const event = scenario.events[index];
      if (event && beats < heartbeats) {
        if (delayMs > 0) await delay(delayMs);
        beats += 1;
        controller.enqueue(encoder.encode("\n")); // 하트비트: 빈 줄
        return;
      }
      if (event) {
        if (delayMs > 0) await delay(delayMs);
        beats = 0;
        index += 1;
        controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        return;
      }
      if (scenario.ending === "close") controller.close();
      else if (scenario.ending === "cut") controller.error(new Error("mock connection cut"));
      // hang: 아무것도 내지 않고 닫지도 않는다
    },
  });
  return new HttpResponse(body, { headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } });
}

export interface ChatHandlerOptions {
  delayMs?: number;
  /** 시험에서 시나리오를 고정할 때 쓴다 */
  scenario?: ScenarioName;
}

export function createChatHandler({ delayMs = 0, scenario }: ChatHandlerOptions = {}) {
  return http.post("*/api/chat", async ({ request }) => {
    // 요청 본문은 서버와 같은 규칙으로 본다: 형식이 틀리면 422 `{code, fields}`(입력 값은 되돌려 주지 않는다)
    const parsed = ChatRequestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      const fields = [...new Set(parsed.error.issues.map((issue) => issue.path.join(".")))];
      return HttpResponse.json({ code: "INVALID_REQUEST", fields }, { status: 422 });
    }
    const name = scenario ?? pickScenario(parsed.data.question, parsed.data.context.confirmed_drugs.length);
    return scenarioResponse(scenarios[name], delayMs);
  });
}

export const handlers = [createChatHandler()];
