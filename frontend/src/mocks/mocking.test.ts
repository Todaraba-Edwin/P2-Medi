import { afterEach, describe, expect, it, vi } from "vitest";

const start = vi.fn(async () => undefined);
vi.mock("./browser", () => ({ worker: { start } }));

import { enableApiMocking, isApiMockingEnabled } from "./index";
import { pickScenario } from "./handlers";

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
