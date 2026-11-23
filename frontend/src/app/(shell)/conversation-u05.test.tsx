import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialStreamState } from "@/lib/api";
import { groupCandidates } from "@/features/result";
import type { CandidatePicks } from "@/features/result";
import { clarifyMultiResponse } from "@/mocks/fixtures/responses";
import type { ChatTurn } from "@/stores/chat";
import { Conversation } from "./Conversation";

// FE-17 U-05: `이 약들로 확인하기`를 누른 뒤에도 지난 답의 고른 줄 요약(A 입력 → 고른 제품 · 바꾸기)은 남고, 되묻기 안내 줄·확인 줄은 숨으며,
// 새 차례에는 기존 진행 표시(약 찾는 중 → 금기 확인 중 → 근거 찾는 중)가 이어진다.
// FE-17 U-17: 지난 고른 줄 요약의 `바꾸기`는 숨기고(U-05의 비활성 표시를 대체), `고른 약: …로 다시 확인` 말풍선은 목록에 그리지 않아 진행 표시가 요약 카드 다음 항목이다
const groups = groupCandidates(clarifyMultiResponse.candidates);
const picks: CandidatePicks = Object.fromEntries(groups.map((group) => [group.inputName, group.items[0]]));
const QUESTION = "합성 질문";
const DISPLAY = "고른 약: 합성으로 다시 확인";

function renderTurns(second: ChatTurn["stream"] | null) {
  const turns: ChatTurn[] = [{ id: "turn-1", question: QUESTION, stream: { ...initialStreamState, status: "done", response: clarifyMultiResponse } }];
  if (second) turns.push({ id: "turn-2", question: QUESTION, display: DISPLAY, stream: second });
  const noop = () => {};
  render(
    <Conversation
      turns={turns}
      hasEmergency={false}
      dockTurnId={second?.response ? "turn-2" : "turn-1"}
      evidenceTurnId={null}
      entryLabelMode="panel"
      picked={{ "turn-1": picks }}
      onOpenEvidence={noop}
      onRetry={noop}
      onPick={noop}
      onOther={noop}
      onResend={noop}
    />,
  );
  return { turn1: () => document.querySelector<HTMLElement>('[data-turn="turn-1"]')!, turn2: () => document.querySelector<HTMLElement>('[data-turn="turn-2"]')! };
}

describe("FE-17 U-05 고른 뒤 지난 되묻기 카드", () => {
  it("고르는 중(마지막 차례)에는 후보·안내 줄·확인 줄이 있다", () => {
    const { turn1 } = renderTurns(null);
    expect(groups.length).toBeGreaterThan(1);
    expect(within(turn1()).getAllByTestId("candidate-picked")).toHaveLength(groups.length);
    expect(within(turn1()).getByTestId("resend-pick")).toBeInTheDocument();
    expect(within(turn1()).getByTestId("candidates-line")).toBeInTheDocument();
  });

  it("다시 물은 뒤: 고른 줄 요약은 남고(바꾸기는 숨김, U-17), 후보 목록·안내 줄·확인 줄은 없으며, 새 차례는 말풍선 없이 진행 표시가 첫 항목이다", () => {
    const { turn1, turn2 } = renderTurns({ ...initialStreamState, status: "streaming", stage: "drug_lookup" });
    const card = within(turn1()).getByTestId("candidate-card");
    expect(card).toHaveAttribute("data-readonly", "true");
    const rows = within(turn1()).getAllByTestId("candidate-picked");
    expect(rows).toHaveLength(groups.length);
    groups.forEach((group, index) => {
      expect(rows[index].textContent).toContain(group.inputName);
      expect(rows[index].textContent).toContain(group.items[0].name);
      expect(within(rows[index]).queryByTestId("candidate-change")).toBeNull();
      expect(rows[index].textContent).not.toContain("바꾸기");
    });
    expect(within(turn1()).queryAllByTestId("candidate")).toHaveLength(0);
    expect(within(turn1()).queryByTestId("candidates-line")).toBeNull();
    expect(within(turn1()).queryByTestId("resend-pick")).toBeNull();
    expect(within(turn1()).queryByTestId("resend-button")).toBeNull();
    // 고정 안내는 숨기지 않는다(코드 강제): 새 답을 기다리는 동안 지난 답의 고정 안내는 아래 고정 영역(dock)이 보이고, 새 답이 오면 지난 답 아래로 온다(e2e clarify-multi)
    // 새 차례: 말풍선 없이 진행 표시(기존 ProgressSteps 재사용)가 첫 항목이다. 표시용 글자(display)는 화면 목록에 없다
    expect(screen.queryByText(DISPLAY)).toBeNull();
    expect(turn2().querySelector('[data-side="me"]')).toBeNull();
    const progress = within(turn2()).getByRole("status", { name: "진행 상태" });
    expect(turn2().firstElementChild?.contains(progress)).toBe(true);
    // 처음 차례의 원 질문 말풍선은 그대로다
    expect(within(turn1()).getByText(QUESTION)).toBeInTheDocument();
    expect(within(progress).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
    expect(screen.getAllByTestId("candidate-card")).toHaveLength(1);
  });
});
