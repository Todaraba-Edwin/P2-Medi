// MSW 핸들러: `POST /api/chat` → NDJSON 스트림(합성 fixture). 개발·시험 전용이다.
import { HttpResponse, delay, http } from "msw";
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
  ["mock:400", "http400"],
  ["mock:500", "http500"],
];

export function pickScenario(question: string): ScenarioName {
  return SCENARIO_KEYWORDS.find(([keyword]) => question.includes(keyword))?.[1] ?? "found";
}

/** 시나리오를 NDJSON 응답으로 바꾼다. 이벤트 사이에 `delayMs`만큼 쉰다. */
export function scenarioResponse(scenario: MockScenario, delayMs = 0): Response {
  if (scenario.kind === "http") return new HttpResponse(null, { status: scenario.status });
  const encoder = new TextEncoder();
  let index = 0;
  // pull 방식: 앞 이벤트가 읽힌 뒤에 다음 것을 낸다(끊김이 앞 이벤트를 지우지 않게)
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const event = scenario.events[index];
      if (event) {
        if (delayMs > 0) await delay(delayMs);
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
    const body = (await request.json().catch(() => null)) as { question?: unknown } | null;
    const question = typeof body?.question === "string" ? body.question : "";
    return scenarioResponse(scenarios[scenario ?? pickScenario(question)], delayMs);
  });
}

export const handlers = [createChatHandler()];
