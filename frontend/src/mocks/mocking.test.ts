import { afterEach, describe, expect, it, vi } from "vitest";

const start = vi.fn(async () => undefined);
vi.mock("./browser", () => ({ worker: { start } }));

import { enableApiMocking, isApiMockingEnabled } from "./index";
import { setupServer } from "msw/node";
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

  it("핸들러가 요청 context.confirmed_drugs를 보고 되묻기 대신 결과를 스트림으로 보낸다", async () => {
    const server = setupServer(createChatHandler());
    server.listen({ onUnhandledFrame: "error" });
    try {
      const post = async (context: unknown) => {
        const res = await fetch("http://localhost/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: "mock:되묻기 합성 질문", context }),
        });
        const events = (await res.text()).split("\n").filter(Boolean).map((line) => JSON.parse(line) as { type: string; response?: { end_reason: string } });
        return events.find((event) => event.type === "answer")?.response?.end_reason;
      };
      expect(await post({})).toBe("CLARIFY");
      expect(await post({ confirmed_drugs: [{ name: "가나다정 100밀리그램", item_seq: "200000001" }] })).toBe("NORMAL");
    } finally {
      server.close();
    }
  });
});
