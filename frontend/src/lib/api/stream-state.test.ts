import { describe, expect, it } from "vitest";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { canRetry, initialStreamState, streamReducer } from "./stream-state";
import type { StreamAction, StreamState } from "./stream-state";
import type { ChatEvent } from "./types";

const run = (actions: StreamAction[], from: StreamState = initialStreamState) => actions.reduce(streamReducer, from);
const ev = (events: ChatEvent[]): StreamAction[] => events.map((event) => ({ type: "event", event }));
const start: StreamAction = { type: "start" };

describe("streamReducer", () => {
  it("정상: progress로 stage가 바뀌고 answer·done 뒤 done", () => {
    const events = scenarios.found.events;
    const mid = run([start, ...ev(events.slice(0, 2))]);
    expect(mid).toMatchObject({ status: "streaming", stage: "contraindication_check", label: "금기 확인 중", response: null });
    const end = run([start, ...ev(events), { type: "end" }]);
    expect(end).toMatchObject({ status: "done", stage: null, label: null, error: null, endedWithoutDone: false });
    expect(end.response).toEqual(scenarios.found.events.find((e) => e.type === "answer")?.response);
  });

  it("이벤트 없이는 stage가 바뀌지 않는다(가짜 진행 없음)", () => {
    expect(run([start]).stage).toBeNull();
  });

  it("응급 첫 이벤트 → 끊김: 119는 유지, 결과는 없음", () => {
    const state = run([start, ...ev(scenarios.emergencyCut.events), { type: "failure", failure: { kind: "network" } }]);
    expect(state.status).toBe("interrupted");
    expect(state.emergency).toEqual(scenarios.emergencyCut.events[0].type === "emergency" ? scenarios.emergencyCut.events[0].emergency : null);
    expect(state.emergency).not.toBeNull();
    expect(state.response).toBeNull();
  });

  it.each<[string, StreamAction]>([
    ["서버 error 이벤트", { type: "event", event: scenarios.serverError.events[1] }],
    ["HTTP 500", { type: "failure", failure: { kind: "http", status: 500 } }],
    ["형식 오류", { type: "failure", failure: { kind: "invalid_event" } }],
    ["무응답 상한", { type: "failure", failure: { kind: "idle_timeout" } }],
    ["사용자 abort", { type: "abort" }],
    ["닫힘", { type: "end" }],
  ])("받은 emergency는 %s 뒤에도 남는다", (_name, action) => {
    const state = run([start, ...ev(scenarios.emergencyCut.events), action]);
    expect(state.emergency).not.toBeNull();
    expect(state.response).toBeNull();
  });

  it("answer 전 끊김(읽기 오류·done 없이 닫힘)은 부분 결과 없이 interrupted", () => {
    const cut = run([start, ...ev(scenarios.cutBeforeAnswer.events), { type: "failure", failure: { kind: "network" } }]);
    const closed = run([start, ...ev(scenarios.closeBeforeAnswer.events), { type: "end" }]);
    for (const state of [cut, closed]) {
      expect(state).toMatchObject({ status: "interrupted", response: null, stage: null });
    }
  });

  it("answer 없이 done만 오면 결과를 만들지 않는다", () => {
    const state = run([start, { type: "event", event: { type: "done", seq: 0, schema_version: "chat_event@v1", end_reason: null } }]);
    expect(state).toMatchObject({ status: "interrupted", response: null });
  });

  it("answer 뒤 done 없이 닫히거나 끊겨도 결과는 유지한다", () => {
    const events = ev(scenarios.answerWithoutDone.events);
    const closed = run([start, ...events, { type: "end" }]);
    const cut = run([start, ...events, { type: "failure", failure: { kind: "network" } }]);
    for (const state of [closed, cut]) {
      expect(state).toMatchObject({ status: "done", endedWithoutDone: true, error: null });
      expect(state.response).not.toBeNull();
    }
  });

  it("서버 error 이벤트는 코드·문구를 받은 그대로 담는다", () => {
    const state = run([start, ...ev(scenarios.serverError.events), { type: "end" }]);
    expect(state.status).toBe("error");
    expect(state.error).toEqual({ kind: "server", status: null, code: "INTERNAL_ERROR", message: "[mock] 오류 문구 자리" });
    expect(state.response).toBeNull();
  });

  it("서버 오류 문구가 null이면 null로 둔다(문구는 화면 상수 몫)", () => {
    const state = run([start, ...ev(scenarios.serverErrorNoMessage.events), { type: "end" }]);
    expect(state.status).toBe("error");
    expect(state.error).toEqual({ kind: "server", status: null, code: "UPSTREAM_UNAVAILABLE", message: null });
  });

  it("진행 문구(label)는 받은 값 그대로 담고, 서버가 다른 문구를 보내면 그 값이 담긴다", () => {
    const event = { ...scenarios.found.events[0], label: "서버가 보낸 문구" };
    expect(run([start, { type: "event", event }])).toMatchObject({ stage: "drug_lookup", label: "서버가 보낸 문구" });
    expect(run([start]).label).toBeNull();
  });

  it("HTTP 오류 본문의 code를 담는다", () => {
    const state = run([start, { type: "failure", failure: { kind: "http", status: 422, code: "INVALID_REQUEST" } }]);
    expect(state.error).toEqual({ kind: "http", status: 422, code: "INVALID_REQUEST", message: null });
    expect(canRetry(state)).toBe(false);
  });

  it("응답 안의 emergency는 배너 한 자리에 합쳐진다", () => {
    const state = run([start, ...ev(scenarios.emergency.events)]);
    expect(state.emergency).toEqual(state.response?.emergency);
    const answerOnly = run([start, ...ev(scenarios.emergency.events.filter((e) => e.type !== "emergency"))]);
    expect(answerOnly.emergency).toEqual(answerOnly.response?.emergency);
  });

  it("끝난 뒤의 이벤트는 반영하지 않는다", () => {
    const done = run([start, ...ev(scenarios.found.events)]);
    expect(run([{ type: "event", event: scenarios.serverError.events[1] }, { type: "abort" }], done)).toBe(done);
  });

  it("새 질문은 이전 119를 지우고, 다시 시도(retry)는 유지한다", () => {
    const cut = run([start, ...ev(scenarios.emergencyCut.events), { type: "failure", failure: { kind: "network" } }]);
    expect(streamReducer(cut, { type: "start" }).emergency).toBeNull();
    const retried = streamReducer(cut, { type: "start", retry: true });
    expect(retried).toMatchObject({ status: "streaming", response: null, error: null });
    expect(retried.emergency).toEqual(cut.emergency);
  });
});

describe("canRetry", () => {
  const failed = (failure: { kind: "http" | "network" | "idle_timeout" | "invalid_json"; status?: number }) =>
    run([start, { type: "failure", failure }]);

  it("4xx는 다시 시도를 보이지 않는다", () => {
    expect(canRetry(failed({ kind: "http", status: 400 }))).toBe(false);
    expect(canRetry(failed({ kind: "http", status: 422 }))).toBe(false);
  });

  it("5xx·네트워크·무응답·형식 오류·끊김은 다시 시도를 보인다", () => {
    expect(canRetry(failed({ kind: "http", status: 500 }))).toBe(true);
    expect(canRetry(failed({ kind: "network" }))).toBe(true);
    expect(canRetry(failed({ kind: "idle_timeout" }))).toBe(true);
    expect(canRetry(failed({ kind: "invalid_json" }))).toBe(true);
    expect(canRetry(run([start, { type: "end" }]))).toBe(true);
  });

  it("진행 중·완료·abort에서는 보이지 않는다", () => {
    expect(canRetry(run([start]))).toBe(false);
    expect(canRetry(run([start, ...ev(scenarios.found.events)]))).toBe(false);
    expect(canRetry(run([start, { type: "abort" }]))).toBe(false);
  });
});
