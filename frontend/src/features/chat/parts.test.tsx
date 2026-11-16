import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initialStreamState, streamReducer } from "@/lib/api";
import type { ChatResponse, StreamAction, StreamState } from "@/lib/api";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { clarifyResponse, foundResponse } from "@/mocks/fixtures/responses";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatInput } from "./ChatInput";
import { ChatThread } from "./ChatThread";
import * as copy from "./copy";
import { EmergencySlot } from "./EmergencySlot";
import { ErrorState } from "./ErrorState";
import { ExampleChips } from "./ExampleChips";
import { HomeHero } from "./HomeHero";
import { ProgressSteps } from "./ProgressSteps";
import { ResultSlot } from "./ResultSlot";
import { Splash } from "./Splash";

afterEach(() => vi.useRealTimers());

const reduce = (...actions: StreamAction[]): StreamState => actions.reduce(streamReducer, initialStreamState);
const streaming = reduce({ type: "start" });
const failed = (failure: Extract<StreamAction, { type: "failure" }>["failure"]) => reduce({ type: "start" }, { type: "failure", failure });
const stepStates = () => screen.getAllByRole("listitem").map((li) => li.getAttribute("data-state"));

describe("ProgressSteps", () => {
  it("문구는 세 가지뿐이고 이벤트 값대로만 진행한다", () => {
    const { rerender } = render(<ProgressSteps stage={null} />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
    expect(stepStates()).toEqual(["todo", "todo", "todo"]);
    rerender(<ProgressSteps stage="drug_lookup" />);
    expect(stepStates()).toEqual(["now", "todo", "todo"]);
    rerender(<ProgressSteps stage="evidence_search" />);
    expect(stepStates()).toEqual(["done", "done", "now"]);
  });

  it("progress 이벤트 없이는 시간이 지나도 진행 문구가 바뀌지 않는다(가짜 진행 없음)", () => {
    vi.useFakeTimers();
    render(<ChatThread turns={[{ id: "t1", question: "합성 질문", stream: streaming }]} hasEmergency={false} onRetry={() => {}} />);
    const before = screen.getByRole("status").innerHTML;
    expect(stepStates()).toEqual(["todo", "todo", "todo"]);
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(stepStates()).toEqual(["todo", "todo", "todo"]);
    expect(screen.getByRole("status").innerHTML).toBe(before);
  });

  it("이벤트에 label이 오면 지금 줄에 그 값을 쓴다", () => {
    render(<ProgressSteps stage="contraindication_check" label="받은 진행 문구" />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["약 찾는 중", "받은 진행 문구", "근거 찾는 중"]);
  });

  it("마스코트는 기본으로 보이고 hideMascot이면 숨는다", () => {
    const { rerender } = render(<ProgressSteps stage="drug_lookup" />);
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
    rerender(<ProgressSteps stage="drug_lookup" hideMascot />);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("ChatInput", () => {
  it("라벨이 입력창에 연결돼 있고 전송 버튼에 이름이 있다", () => {
    render(<ChatInput onSend={() => {}} />);
    expect(screen.getByLabelText(copy.INPUT_LABEL)).toBe(screen.getByRole("textbox"));
    expect(screen.getByRole("button", { name: copy.SEND_LABEL })).toBeDisabled();
  });

  it("보내면 다듬은 글자를 넘기고 입력창을 비운다", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await userEvent.type(screen.getByRole("textbox"), "  합성 질문  ");
    await userEvent.click(screen.getByRole("button", { name: copy.SEND_LABEL }));
    expect(onSend).toHaveBeenCalledExactlyOnceWith("합성 질문");
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("Enter로 보내고 Shift+Enter·한글 조합 중 Enter·빈 글자는 보내지 않는다", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const box = screen.getByRole("textbox");
    fireEvent.keyDown(box, { key: "Enter" });
    await userEvent.type(box, "질문{Shift>}{Enter}{/Shift}");
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});

describe("EmergencySlot", () => {
  it("받은 문구를 그대로 보이고 role=alert, tel:119 링크를 둔다", () => {
    render(<EmergencySlot emergency={{ text: "받은 응급 문구 그대로", tel: "tel:119", wide_text: "받은 보조 문장" }} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("받은 응급 문구 그대로")).toBeInTheDocument();
    expect(within(alert).getByRole("link")).toHaveAttribute("href", "tel:119");
  });
});

describe("ResultSlot", () => {
  const custom: ChatResponse = { ...foundResponse, summary: "받은 요약 1줄\n받은 요약 2줄", fixed_notice: ["받은 고정 줄 가", "받은 고정 줄 나"], disclaimer: "받은 고지" };

  it("summary·고정 안내 줄·고지를 받은 그대로, 받은 순서대로 보인다", () => {
    render(<ResultSlot response={custom} />);
    const slot = screen.getByTestId("result-slot");
    expect(within(slot).getByText(/받은 요약 1줄/).textContent).toBe(custom.summary);
    const text = slot.textContent ?? "";
    expect(text.indexOf("받은 고정 줄 가")).toBeGreaterThan(-1);
    expect(text.indexOf("받은 고정 줄 가")).toBeLessThan(text.indexOf("받은 고정 줄 나"));
    expect(within(slot).getByText("받은 고지")).toBeInTheDocument();
  });

  it("응답이 있으면 생성 문구가 아니라 응답의 값을 쓴다", () => {
    render(<ResultSlot response={custom} />);
    expect(screen.queryByText(FIXED_NOTICE)).toBeNull();
    expect(screen.queryByText(DISCLAIMER)).toBeNull();
  });

  it("되묻기는 summary만 보이는 자리다", () => {
    render(<ResultSlot response={clarifyResponse} />);
    expect(screen.getByTestId("result-slot")).toHaveAttribute("data-end-reason", "CLARIFY");
    expect(screen.getByText(clarifyResponse.summary ?? "")).toBeInTheDocument();
  });

  it("결과 자리에는 마스코트와 펼침 요소가 없다", () => {
    const { container } = render(<ResultSlot response={custom} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(container.querySelector("details, [data-state='closed']")).toBeNull();
  });
});

describe("ErrorState", () => {
  it("서버가 아직 연결되지 않았으면(501) 승인 문구를 보이고 다시 시도를 둔다", () => {
    render(<ErrorState stream={failed({ kind: "http", status: 501, code: "NOT_IMPLEMENTED" })} onRetry={() => {}} />);
    expect(screen.getByText("아직 준비 중이라 답을 드릴 수 없어요. 급하면 약국·약사에게 확인하세요.")).toBeInTheDocument();
    expect(screen.queryByText(copy.ERROR_BODY_RETRY)).toBeNull();
    expect(screen.getByRole("button", { name: copy.RETRY_LABEL })).toBeInTheDocument();
  });

  it("다른 5xx는 501 문구를 쓰지 않는다", () => {
    render(<ErrorState stream={failed({ kind: "http", status: 500 })} onRetry={() => {}} />);
    expect(screen.getByText(copy.ERROR_BODY_RETRY)).toBeInTheDocument();
    expect(screen.queryByText(copy.ERROR_BODY_NOT_READY)).toBeNull();
  });

  it("응답이 없으므로 생성한 고정 안내·고지를 보인다", () => {
    render(<ErrorState stream={failed({ kind: "network" })} onRetry={() => {}} />);
    expect(screen.getByText(FIXED_NOTICE)).toBeInTheDocument();
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
    expect(screen.getByText(copy.ERROR_BODY_RETRY)).toBeInTheDocument();
  });

  it("서버가 보낸 오류 문구는 그대로 보인다", () => {
    // 서버 오류 문구 상수(외부 연결 실패). 화면 상수와 다른 문장이라 "받은 그대로"가 드러난다
    const stream = reduce({ type: "start" }, { type: "event", event: scenarios.serverErrorNoMessage.events[1] });
    render(<ErrorState stream={stream} onRetry={() => {}} />);
    expect(screen.getByText("지금은 확인에 필요한 곳에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.")).toBeInTheDocument();
    expect(screen.queryByText(copy.ERROR_BODY_RETRY)).toBeNull();
  });

  it("다시 시도는 눌렀을 때만 불린다", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onRetry = vi.fn();
    render(<ErrorState stream={failed({ kind: "http", status: 500 })} onRetry={onRetry} />);
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(onRetry).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: copy.RETRY_LABEL }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("4xx는 다시 시도 버튼이 없다", () => {
    render(<ErrorState stream={failed({ kind: "http", status: 400 })} onRetry={() => {}} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(copy.ERROR_BODY_NO_RETRY)).toBeInTheDocument();
  });

  it("119 안내를 받은 상태면 마스코트를 숨기고, 고정 안내 영역에는 언제나 없다", () => {
    const { rerender } = render(<ErrorState stream={failed({ kind: "network" })} onRetry={() => {}} />);
    expect(screen.getAllByTestId("mascot")).toHaveLength(1);
    const cut = reduce({ type: "start" }, { type: "event", event: scenarios.emergencyCut.events[0] }, { type: "failure", failure: { kind: "network" } });
    rerender(<ErrorState stream={cut} onRetry={() => {}} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("ChatThread", () => {
  const answered = reduce({ type: "start" }, ...scenarios.answerWithoutDone.events.map((event) => ({ type: "event", event }) as const), { type: "end" });

  it("상태마다 한 가지 자리만 그린다", () => {
    const turns = [
      { id: "t1", question: "끊은 질문", stream: reduce({ type: "start" }, { type: "abort" }) },
      { id: "t2", question: "끊긴 질문", stream: failed({ kind: "network" }) },
      { id: "t3", question: "답 받은 질문", stream: answered },
      { id: "t4", question: "기다리는 질문", stream: streaming },
    ];
    render(<ChatThread turns={turns} hasEmergency={false} onRetry={() => {}} />);
    const turn = (id: string) => within(screen.getByTestId("chat-thread").querySelector(`[data-turn="${id}"]`) as HTMLElement);
    expect(turn("t1").queryByTestId("error-state")).toBeNull();
    expect(turn("t1").queryByRole("status")).toBeNull();
    expect(turn("t2").getByTestId("error-state")).toBeInTheDocument();
    expect(turn("t3").getByTestId("result-slot")).toBeInTheDocument(); // done 없이 끝나도 결과 유지
    expect(turn("t4").getByRole("status")).toBeInTheDocument();
    expect(turn("t4").queryByTestId("result-slot")).toBeNull();
  });

  it("다시 시도는 그 차례의 id로 불린다", async () => {
    const onRetry = vi.fn();
    render(<ChatThread turns={[{ id: "t9", question: "질문", stream: failed({ kind: "network" }) }]} hasEmergency={false} onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: copy.RETRY_LABEL }));
    expect(onRetry).toHaveBeenCalledExactlyOnceWith("t9");
  });

  it("다시 시도 버튼은 마지막 차례의 오류에만 보인다", () => {
    const turns = [
      { id: "t1", question: "지난 질문", stream: failed({ kind: "network" }) },
      { id: "t2", question: "마지막 질문", stream: failed({ kind: "network" }) },
    ];
    render(<ChatThread turns={turns} hasEmergency={false} onRetry={() => {}} />);
    expect(screen.getAllByTestId("error-state")).toHaveLength(2);
    const buttons = screen.getAllByRole("button", { name: copy.RETRY_LABEL });
    expect(buttons).toHaveLength(1);
    expect(screen.getByTestId("chat-thread").querySelector('[data-turn="t2"]')).toContainElement(buttons[0]);
  });

  it("119 안내가 떠 있으면 진행 표시의 마스코트를 숨긴다", () => {
    const turns = [{ id: "t1", question: "질문", stream: { ...streaming, stage: "drug_lookup" as const } }];
    const { rerender } = render(<ChatThread turns={turns} hasEmergency={false} onRetry={() => {}} />);
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
    rerender(<ChatThread turns={turns} hasEmergency onRetry={() => {}} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("시작 화면 부품", () => {
  it("HomeHero는 표시 이름과 한글 병기를 보인다", () => {
    render(<HomeHero />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Can I PPiyak 삐약");
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
  });

  it("ExampleChips는 예시 질문을 그대로 넘기고 내부 표기를 싣지 않는다", async () => {
    const onPick = vi.fn();
    render(<ExampleChips onPick={onPick} />);
    const chips = screen.getAllByRole("button");
    expect(chips.map((chip) => chip.textContent)).toEqual([...copy.EXAMPLE_QUESTIONS]);
    for (const chip of chips) expect(chip.textContent).not.toMatch(/S\d|ISSUE|시나리오|mock/i);
    await userEvent.click(chips[1]);
    expect(onPick).toHaveBeenCalledExactlyOnceWith(copy.EXAMPLE_QUESTIONS[1]);
  });

  it("Splash는 시간이 지나거나 누르면 닫힌다", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onDone = vi.fn();
    const { unmount } = render(<Splash onDone={onDone} durationMs={1000} />);
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onDone).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: copy.SPLASH_LABEL }));
    expect(onDone).toHaveBeenCalledTimes(2);
    unmount();
  });
});

describe("copy.ts", () => {
  it("진행 문구에 금지어 '단계'가 없고 고정 안내 문구를 담지 않는다", () => {
    const all = JSON.stringify(copy);
    expect(all).not.toContain("단계");
    expect(all).not.toContain(FIXED_NOTICE);
    expect(all).not.toContain(DISCLAIMER);
    expect(Object.values(copy.STAGE_LABELS)).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
  });
});
