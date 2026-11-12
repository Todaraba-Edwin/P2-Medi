import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { PHRASES } from "@/mocks/fixtures/phrases";
import { foundResponse } from "@/mocks/fixtures/responses";
import type { ScenarioName } from "@/mocks/fixtures/scenarios";
import { createChatHandler } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createChatStore } from "@/stores/chat";
import { ChatScreen } from "./ChatScreen";
import * as copy from "./copy";

let requests = 0;
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", () => {
    requests += 1;
  });
});
afterEach(() => {
  server.resetHandlers();
  requests = 0;
});
afterAll(() => server.close());

const use = (scenario: ScenarioName, delayMs = 0) => server.use(createChatHandler({ scenario, delayMs }));
const QUESTION = "합성 질문 가나다정";

async function ask(question = QUESTION) {
  await userEvent.type(screen.getByRole("textbox"), question);
  await userEvent.click(screen.getByRole("button", { name: copy.SEND_LABEL }));
}

function setup() {
  const store = createChatStore();
  render(<ChatScreen store={store} />);
  return store;
}

describe("ChatScreen 흐름", () => {
  it("시작 화면: 표시 이름·예시 질문·입력창이 있다", () => {
    setup();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.APP_NAME);
    expect(screen.getByText(copy.EXAMPLES_HEADING)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.INPUT_LABEL)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("질문 → 진행 표시 → 결과 자리(summary와 응답의 고정 안내)", async () => {
    use("found", 15);
    setup();
    await ask();
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
    expect(await screen.findByRole("status")).toBeInTheDocument();
    const slot = await screen.findByTestId("result-slot");
    expect(within(slot).getByText(foundResponse.summary ?? "")).toBeInTheDocument();
    expect(within(slot).getByText(foundResponse.fixed_notice[0])).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByTestId("error-state")).toBeNull();
    expect(requests).toBe(1);
  });

  it("예시 질문을 누르면 그 질문을 보낸다", async () => {
    use("found");
    const store = setup();
    await userEvent.click(screen.getByRole("button", { name: copy.EXAMPLE_QUESTIONS[0] }));
    await screen.findByTestId("result-slot");
    expect(store.getState().turns[0].question).toBe(copy.EXAMPLE_QUESTIONS[0]);
  });

  it("응급: 119 자리가 화면의 첫 요소로 먼저 뜨고 진행 표시의 마스코트가 숨는다", async () => {
    use("emergency", 25);
    setup();
    await ask();
    const alert = await screen.findByRole("alert");
    expect(screen.queryByTestId("result-slot")).toBeNull(); // 답보다 먼저 떴다
    expect(screen.getByTestId("chat-screen").firstElementChild).toBe(alert);
    expect(within(alert).getByText(PHRASES.EMERGENCY_119)).toBeInTheDocument();
    expect(within(alert).getByRole("link")).toHaveAttribute("href", "tel:119");
    expect(within(screen.getByRole("status")).queryByTestId("mascot")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();

    await screen.findByTestId("result-slot"); // 금기 조회 결과는 그 아래 이어진다
    expect(screen.getByTestId("chat-screen").firstElementChild).toBe(screen.getByRole("alert"));
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("응급 뒤 끊겨도 119 자리는 첫 요소로 남고, 다시 시도와 다음 질문 뒤에도 남는다", async () => {
    use("emergencyCut");
    setup();
    await ask();
    await screen.findByTestId("error-state");
    const first = () => screen.getByTestId("chat-screen").firstElementChild;
    expect(first()).toBe(screen.getByRole("alert"));
    expect(screen.queryByTestId("result-slot")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();

    use("cutBeforeAnswer");
    await userEvent.click(screen.getByRole("button", { name: copy.RETRY_LABEL }));
    await waitFor(() => expect(requests).toBe(2));
    await screen.findByTestId("error-state");
    expect(first()).toBe(screen.getByRole("alert"));

    use("found");
    await ask("다음 합성 질문");
    await screen.findByTestId("result-slot");
    expect(first()).toBe(screen.getByRole("alert"));
  });

  it("오류: 다시 시도는 눌렀을 때만 요청한다", async () => {
    use("http500");
    setup();
    await ask();
    await screen.findByTestId("error-state");
    expect(screen.getByText(FIXED_NOTICE)).toBeInTheDocument(); // 응답이 없어 생성 문구
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(requests).toBe(1);

    use("found");
    await userEvent.click(screen.getByRole("button", { name: copy.RETRY_LABEL }));
    await screen.findByTestId("result-slot");
    expect(requests).toBe(2);
    expect(screen.queryByTestId("error-state")).toBeNull();
    expect(screen.getAllByText(QUESTION)).toHaveLength(1); // 같은 차례에서 다시 보냈다
  });

  it("새 질문을 보내면 진행 중이던 요청은 끊기고 새 질문만 답을 받는다", async () => {
    use("found", 40);
    const store = setup();
    await ask("첫 합성 질문");
    await screen.findByRole("status");
    await ask("둘째 합성 질문");
    await waitFor(() => expect(store.getState().activeTurnId).toBeNull());
    const [a, b] = store.getState().turns;
    expect(a.stream.status).toBe("aborted");
    expect(b.stream.status).toBe("done");
    expect(screen.getAllByTestId("result-slot")).toHaveLength(1);
    expect(requests).toBe(2);
  });

  it("되묻기·거절은 summary만 보이는 자리로 나온다", async () => {
    use("clarify");
    setup();
    await ask();
    expect(await screen.findByTestId("result-slot")).toHaveAttribute("data-end-reason", "CLARIFY");
    use("refuse");
    await ask("둘째 합성 질문");
    await waitFor(() => expect(screen.getAllByTestId("result-slot")).toHaveLength(2));
    expect(screen.getAllByTestId("result-slot")[1]).toHaveAttribute("data-end-reason", "REFUSE");
  });

  it("대화 뒤 브라우저 저장소에 질문 문장이 없다", async () => {
    use("found");
    setup();
    await ask();
    await screen.findByTestId("result-slot");
    // 저장소를 직접 들여다보는 시험이라 이 줄만 저장소 접근 금지 규칙을 끈다
    // eslint-disable-next-line no-restricted-properties
    const dump = JSON.stringify([{ ...window.localStorage }, { ...window.sessionStorage }]);
    expect(dump).toBe("[{},{}]");
    expect(document.cookie).not.toContain("합성");
  });
});
