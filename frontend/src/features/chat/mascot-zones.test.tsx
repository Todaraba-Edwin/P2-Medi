import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialStreamState, streamReducer } from "@/lib/api";
import type { StreamAction, StreamState } from "@/lib/api";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { adviceFirstResponse, emergencyResponse, foundResponse, notListedResponse } from "@/mocks/fixtures/responses";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatThread } from "./ChatThread";
import { EmergencySlot } from "./EmergencySlot";
import { ErrorState } from "./ErrorState";
import { HomeHero } from "./HomeHero";
import { ProgressSteps } from "./ProgressSteps";
import { ResultSlot } from "./ResultSlot";
import { Splash } from "./Splash";

// 마스코트(병아리) 이미지가 어디에 나오고 어디에 나오면 안 되는지(PRD-06-02, 계획서 5장 S3)
const reduce = (...actions: StreamAction[]): StreamState => actions.reduce(streamReducer, initialStreamState);
const isChick = (img: Element) => /mascot|face/.test(decodeURIComponent(img.getAttribute("src") ?? ""));
const chicks = (root: ParentNode) => [...root.querySelectorAll("img")].filter(isChick);
const variant = () => screen.getByTestId("mascot").getAttribute("data-variant");

describe("마스코트 허용 자리", () => {
  it("시작 화면: 질문 병아리 + 로고(심볼 이미지와 이름 글자)", () => {
    render(<HomeHero />);
    expect(variant()).toBe("question");
    expect(screen.getByTestId("brand-logo")).toHaveTextContent("Can I PPiyak");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Can I PPiyak 삐약");
  });

  it("여는 화면: 질문 병아리 + 워드마크(alt는 서비스 이름)", () => {
    render(<Splash onDone={() => {}} />);
    expect(variant()).toBe("question");
    expect(screen.getByRole("img", { name: "Can I PPiyak" })).toBeInTheDocument();
  });

  it("진행 표시·오류: 돋보기 병아리", () => {
    const { unmount } = render(<ProgressSteps stage="drug_lookup" />);
    expect(variant()).toBe("search");
    unmount();
    render(<ErrorState stream={reduce({ type: "start" }, { type: "failure", failure: { kind: "network" } })} onRetry={() => {}} />);
    expect(variant()).toBe("search");
  });
});

describe("마스코트 금지 영역: 이미지 0개", () => {
  it("응급 자리", () => {
    const { container } = render(<EmergencySlot emergency={{ text: "받은 응급 문구", tel: "tel:119" }} />);
    expect(chicks(container)).toEqual([]);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it.each([
    ["금기 발견", foundResponse],
    ["목록에 없음", notListedResponse],
    ["응급 + 결과", emergencyResponse],
    ["약사 확인 권고 + 고정 안내", adviceFirstResponse],
  ])("결과 자리(%s)", (_name, response) => {
    const { container } = render(<ResultSlot response={response} />);
    expect(chicks(container)).toEqual([]);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });

  it("오류 화면의 고정 안내·고지 영역", () => {
    const { container } = render(
      <ErrorState stream={reduce({ type: "start" }, { type: "failure", failure: { kind: "network" } })} onRetry={() => {}} />,
    );
    const all = chicks(container);
    expect(all).toHaveLength(1); // 안내 카드의 한 개뿐
    const card = all[0].parentElement as HTMLElement; // 마스코트가 든 안내 카드
    for (const text of [FIXED_NOTICE, DISCLAIMER]) {
      const box = screen.getByText(text);
      expect(box.querySelector("img")).toBeNull();
      expect(card.contains(box)).toBe(false); // 고정 안내·고지는 마스코트와 같은 카드에 있지 않다
    }
  });

  it("119 안내가 뜨면 진행 표시와 오류의 마스코트가 사라진다", () => {
    const streaming = reduce({ type: "start" }, { type: "event", event: scenarios.emergencyCut.events[0] }, { type: "event", event: scenarios.emergencyCut.events[1] });
    const cut = streamReducer(streaming, { type: "failure", failure: { kind: "network" } });
    for (const stream of [streaming, cut]) {
      const { container, unmount } = render(
        <ChatThread turns={[{ id: "t1", question: "질문", stream }]} hasEmergency onRetry={() => {}} />,
      );
      expect(chicks(container)).toEqual([]);
      unmount();
    }
  });

  it("나중 차례에서 119를 받아도 지난 오류 카드의 마스코트가 사라진다", () => {
    const failedBefore = reduce({ type: "start" }, { type: "failure", failure: { kind: "http", status: 500 } });
    const turns = [{ id: "t1", question: "지난 질문", stream: failedBefore }];
    const { container, rerender } = render(<ChatThread turns={turns} hasEmergency={false} onRetry={() => {}} />);
    expect(chicks(container)).toHaveLength(1);
    rerender(<ChatThread turns={turns} hasEmergency onRetry={() => {}} />);
    expect(chicks(container)).toEqual([]);
  });

  it("결과가 나온 차례에는 마스코트가 없다", () => {
    const done = reduce({ type: "start" }, ...scenarios.found.events.map((event) => ({ type: "event", event }) as const));
    const { container } = render(<ChatThread turns={[{ id: "t1", question: "질문", stream: done }]} hasEmergency={false} onRetry={() => {}} />);
    expect(chicks(container)).toEqual([]);
  });
});
