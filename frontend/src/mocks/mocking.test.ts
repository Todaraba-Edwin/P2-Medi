import { afterEach, describe, expect, it, vi } from "vitest";

const start = vi.fn(async () => undefined);
vi.mock("./browser", () => ({ worker: { start } }));

import { enableApiMocking, isApiMockingEnabled } from "./index";
import { setupServer } from "msw/node";
import { fillPriorPick } from "./fixtures/phrases";
import { createChatHandler, pickScenario } from "./handlers";

afterEach(() => {
  vi.unstubAllEnvs();
  start.mockClear();
});

describe("MSW 스위치", () => {
  it.each([undefined, "", "disabled", "true", "ENABLED"])("NEXT_PUBLIC_API_MOCKING=%s면 워커를 켜지 않는다", async (value) => {
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", value);
    expect(isApiMockingEnabled()).toBe(false);
    expect(await enableApiMocking()).toBe(false);
    expect(start).not.toHaveBeenCalled();
  });

  it("enabled일 때만 워커를 켜고, 여러 번 불려도 한 번만 켠다", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
    const results = await Promise.all([enableApiMocking(), enableApiMocking()]);
    expect(results).toEqual([true, true]);
    expect(await enableApiMocking()).toBe(true);
    expect(start).toHaveBeenCalledTimes(1);
  });
});

describe("pickScenario", () => {
  it("표시 글자가 없으면 정상 시나리오다", () => {
    expect(pickScenario("합성 질문")).toBe("found");
  });

  it("더 긴 표시 글자가 먼저 걸린다", () => {
    expect(pickScenario("mock:응급끊김")).toBe("emergencyCut");
    expect(pickScenario("mock:응급")).toBe("emergency");
  });
});

describe("되묻기 뒤 재전송(FE-IMPL-06b)", () => {
  it("고른 약이 없으면 되묻기, 있으면 결과 시나리오다", () => {
    expect(pickScenario("mock:되묻기 합성 질문")).toBe("clarify");
    expect(pickScenario("mock:되묻기 합성 질문", 0)).toBe("clarify");
    expect(pickScenario("mock:되묻기 합성 질문", 1)).toBe("found");
    // 이름 둘을 되묻는 시나리오(FE-09): 더 긴 표시 글자가 먼저 걸리고, 고른 약이 둘 이상이어야 결과로 답한다
    expect(pickScenario("mock:되묻기여러 합성 질문")).toBe("clarifyMulti");
    expect(pickScenario("mock:되묻기여러 합성 질문", 1)).toBe("clarifyMulti");
    expect(pickScenario("mock:되묻기여러 합성 질문", 2)).toBe("found");
    // 되묻기가 아닌 시나리오는 고른 약이 있어도 그대로다
    expect(pickScenario("mock:응급", 1)).toBe("emergency");
  });

  it("고른 약은 없고 이전 선택만 실려 오면 확인 되묻기(이전 선택이 첫 후보)이고, 그 뒤 고르면 결과다(AG-21 q1 → q2 → q3)", () => {
    expect(pickScenario("mock:되묻기 합성 질문", 0, 0)).toBe("clarify"); // q1
    expect(pickScenario("mock:되묻기 합성 질문", 1, 0)).toBe("found"); // q2 재전송
    expect(pickScenario("mock:되묻기 합성 질문", 0, 1)).toBe("clarifyPrior"); // q3 새 질문(이전 선택만)
    expect(pickScenario("mock:되묻기 합성 질문", 1, 1)).toBe("found"); // q3 확인 뒤 재전송(이번 답이 이전 선택을 이긴다)
    expect(pickScenario("mock:이전선택 합성 질문")).toBe("clarifyPrior");
    expect(pickScenario("mock:이전선택 합성 질문", 1)).toBe("found");
    // 이전 선택만으로는 결과로 답하지 않는다(확정은 confirmed_drugs로만)
    expect(pickScenario("mock:되묻기여러 합성 질문", 0, 2)).toBe("clarifyMulti");
    expect(pickScenario("mock:응급", 0, 1)).toBe("emergency");
  });

  it("핸들러가 요청 context.confirmed_drugs를 보고 되묻기 대신 결과를 스트림으로 보낸다", async () => {
    const server = setupServer(createChatHandler());
    server.listen({ onUnhandledFrame: "error" });
    try {
      const post = async (context: unknown, question = "mock:되묻기 합성 질문") => {
        const res = await fetch("http://localhost/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, context }),
        });
        const events = (await res.text()).split("\n").filter(Boolean).map((line) => JSON.parse(line) as { type: string; response?: { end_reason: string; summary: string | null } });
        return events.find((event) => event.type === "answer")?.response?.end_reason;
      };
      expect(await post({})).toBe("CLARIFY");
      // 이전 선택만 실려 오면 확인 되묻기(CLARIFY_PRIOR_PICK, 첫 후보 = 이전 선택)이고, 이번 답이 실리면 결과다
      const prior = [{ name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" }];
      const priorRes = await fetch("http://localhost/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: "mock:되묻기 합성 질문", context: { prior_drugs: prior } }) });
      const priorAnswer = (await priorRes.text()).split("\n").filter(Boolean).map((line) => JSON.parse(line) as { type: string; response?: { end_reason: string; summary: string | null; candidates: { name: string }[] } }).find((e) => e.type === "answer")?.response;
      expect(priorAnswer?.end_reason).toBe("CLARIFY");
      expect(priorAnswer?.summary).toBe(fillPriorPick("가나다정 100밀리그램"));
      expect(priorAnswer?.candidates[0].name).toBe("가나다정 100밀리그램");
      expect(await post({ prior_drugs: prior, confirmed_drugs: prior })).toBe("NORMAL");
      // 상한을 넘는 이전 선택·불리언이 아닌 용량 답은 서버처럼 422
      const bad = await fetch("http://localhost/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: "합성 질문", context: { prior_drugs: Array.from({ length: 11 }, (_, i) => ({ name: `약${i}` })), took_today: "예" } }) });
      expect(bad.status).toBe(422);
      expect(await bad.json()).toEqual({ code: "INVALID_REQUEST", fields: ["context.prior_drugs", "context.took_today"] });
      expect(await post({ confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] })).toBe("NORMAL");
      // 고른 묶음의 이름(input_name, FE-09-05 A)이 실려 와도 같은 규칙으로 답한다
      expect(await post({ confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" }] })).toBe("NORMAL");
      const multi = [
        { name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다" },
        { name: "가나다시럽 키즈", item_seq: "200000004", input_name: "가나다시럽" },
      ];
      expect(await post({ confirmed_drugs: multi.slice(0, 1) }, "mock:되묻기여러 합성 질문")).toBe("CLARIFY");
      expect(await post({ confirmed_drugs: multi }, "mock:되묻기여러 합성 질문")).toBe("NORMAL");
    } finally {
      server.close();
    }
  });
});
