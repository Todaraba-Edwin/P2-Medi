import { readFileSync } from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initialStreamState, streamReducer } from "@/lib/api";
import type { ChatResponse, StreamAction, StreamState } from "@/lib/api";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { TargetChip } from "@/features/account";
import { clarifyResponse, foundResponse } from "@/mocks/fixtures/responses";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatInput } from "./ChatInput";
import { ChatThread } from "./ChatThread";
import * as copy from "./copy";
import { EmergencySlot } from "./EmergencySlot";
import { ErrorState } from "./ErrorState";
import { ExampleChips } from "./ExampleChips";
import { HomeHero } from "./HomeHero";
import { PROGRESS_MASCOT_GAP, ProgressSteps } from "./ProgressSteps";
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

  it("대기 표시는 첫 progress 이벤트 전(stage=null)에만, 단계 줄 밖에 글자 없이 보인다(BE-17-04 A)", () => {
    const { rerender } = render(<ProgressSteps stage={null} />);
    const waiting = screen.getByTestId("progress-waiting");
    expect(waiting).toHaveAttribute("aria-hidden", "true");
    expect(waiting.textContent).toBe(""); // 새 글자 없음
    expect(waiting.closest("ol")).toBeNull(); // 단계 줄과 따로
    expect(within(waiting).queryByTestId("mascot")).toBeNull(); // 마스코트를 쓰지 않는다
    expect(stepStates()).toEqual(["todo", "todo", "todo"]); // 어느 단계도 주장하지 않는다
    expect(screen.getByRole("list").querySelector(".animate-spin")).toBeNull();
    // 전이: null → drug_lookup → contraindication_check
    rerender(<ProgressSteps stage="drug_lookup" />);
    expect(screen.queryByTestId("progress-waiting")).toBeNull();
    expect(stepStates()).toEqual(["now", "todo", "todo"]);
    rerender(<ProgressSteps stage="contraindication_check" />);
    expect(screen.queryByTestId("progress-waiting")).toBeNull();
    expect(stepStates()).toEqual(["done", "now", "todo"]);
  });

  it("움직임 줄이기에서는 스피너를 숨기고 멈춘 점 3개로 바꾼다", () => {
    render(<ProgressSteps stage={null} />);
    const spinner = screen.getByTestId("progress-waiting-spinner");
    expect(spinner).toHaveClass("motion-safe:animate-spin", "motion-reduce:hidden");
    expect(spinner).not.toHaveClass("animate-spin"); // 움직임은 motion-safe에서만
    const still = screen.getByTestId("progress-waiting-still");
    expect(still).toHaveClass("hidden", "motion-reduce:flex");
    expect(still.children).toHaveLength(3);
  });

  it("첫 이벤트가 drug_lookup이면 대기 표시 없이 그 줄에 기존 스피너가 돈다", () => {
    render(<ProgressSteps stage="drug_lookup" />);
    expect(screen.queryByTestId("progress-waiting")).toBeNull();
    const [first, ...rest] = screen.getAllByRole("listitem");
    expect(first).toHaveAttribute("aria-current", "step");
    expect(first.querySelector(".animate-spin")).not.toBeNull();
    for (const li of rest) expect(li.querySelector(".animate-spin")).toBeNull();
  });

  it("119 안내로 마스코트를 숨겨도 대기 표시는 보인다", () => {
    render(<ProgressSteps stage={null} hideMascot />);
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(screen.getByTestId("progress-waiting")).toBeInTheDocument();
  });

  it("U-24: 단계는 마스코트 오른쪽 세로 목록이고 바깥 노란 상자가 없다", () => {
    render(<ProgressSteps stage="contraindication_check" />);
    const root = screen.getByRole("status", { name: "진행 상태" });
    expect(root).toHaveClass("flex", "items-center"); // 가로 배치(마스코트 | 단계)
    expect(root).not.toHaveClass("flex-col");
    const mascot = within(root).getByTestId("mascot");
    const list = screen.getByTestId("progress-step-list");
    expect(mascot.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // 마스코트 다음(오른쪽)
    expect(list).toHaveClass("flex-col");
    for (const cls of ["bg-bg-soft", "rounded-[18px]", "px-4", "py-3"]) expect(list).not.toHaveClass(cls);
    expect(list.className).not.toMatch(/\b(bg-|border)/);
  });

  it("U-24: 완료는 체크 표시 그대로, 진행 중은 굵은 글자 + 쉬머, 예정은 낮은 불투명도다", () => {
    render(<ProgressSteps stage="contraindication_check" />);
    const [done, now, todo] = screen.getAllByRole("listitem");
    expect(done).toHaveAttribute("data-state", "done");
    expect(done.querySelector(".bg-yellow svg")).not.toBeNull(); // 기존 체크 아이콘·색
    expect(done).not.toHaveClass("opacity-55");
    expect(within(done).getByTestId("progress-step-text")).not.toHaveClass("progress-shimmer");
    expect(now).toHaveClass("font-bold");
    expect(within(now).getByTestId("progress-step-text")).toHaveClass("progress-shimmer");
    expect(now).not.toHaveClass("opacity-55");
    expect(todo).toHaveClass("opacity-55");
    expect(within(todo).getByTestId("progress-step-text")).not.toHaveClass("progress-shimmer");
    expect(screen.getAllByTestId("progress-step-text").map((el) => el.textContent)).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]); // 새 글자 없음
  });

  it("U-24: 움직임 줄이기에서는 지금 줄 스피너가 멈추고(motion-reduce:animate-none) 쉬머는 CSS가 끈다", () => {
    render(<ProgressSteps stage="drug_lookup" />);
    const spinner = screen.getAllByRole("listitem")[0].querySelector(".animate-spin");
    expect(spinner).toHaveClass("motion-reduce:animate-none");
    const css = readFileSync(path.resolve(__dirname, "../../styles/globals.css"), "utf8");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.progress-shimmer\s*\{[^}]*animation:\s*none/);
  });

  it("U-24 수정: 병아리와 단계 목록 사이 간격은 기존 12px + 12px = 24px(gap-6) 한 곳에서 정한다", () => {
    render(<ProgressSteps stage="drug_lookup" />);
    const root = screen.getByTestId("progress-steps");
    expect(PROGRESS_MASCOT_GAP).toBe("gap-6");
    expect(root).toHaveClass(PROGRESS_MASCOT_GAP);
    expect(root).not.toHaveClass("gap-3"); // 이전 간격(12px)은 남지 않는다
  });

  it("U-24 수정: 쉬머는 더 밝은 띠가 왼쪽→오른쪽으로 계속 지나가고(배경 위치 100% → 0%, 무한 반복), 다크는 바탕을 낮춰 띠를 밝히며, 움직임 줄이기에서는 멈춘다", () => {
    const css = readFileSync(path.resolve(__dirname, "../../styles/globals.css"), "utf8");
    const rule = css.match(/\.progress-shimmer\s*\{([^}]*)\}/)?.[1] ?? "";
    // 바탕 → 띠 → 바탕 그라데이션, 글자 모양으로 자른다
    expect(rule).toMatch(/--shimmer-base:\s*var\(--color-ink\)/);
    // 라이트: 검정 글자 위 더 밝은 갈색(mute) 띠. 2026-11-24 U-24 수정-3으로 faint(띠 한가운데 약 3.3:1) → mute(약 6.3:1, 4.5:1 유지).
    // 대비 수치는 tokens.test.ts "진행 표시 쉬머"가 계산해 단언한다
    expect(rule).toMatch(/--shimmer-hi:\s*var\(--color-mute\)/);
    expect(rule).toMatch(/linear-gradient\(90deg,[^;]*var\(--shimmer-hi\) 50%/);
    expect(rule).toMatch(/background-clip:\s*text/);
    expect(rule).toMatch(/animation:\s*progress-shimmer\s+1\.5s\s+linear\s+infinite/);
    // 배경이 글자보다 넓을 때 위치 100% → 0%는 띠를 왼쪽 밖에서 오른쪽 밖으로 옮긴다(왼쪽→오른쪽)
    expect(css).toMatch(/@keyframes progress-shimmer\s*\{\s*from\s*\{\s*background-position:\s*100% 0;\s*\}\s*to\s*\{\s*background-position:\s*0% 0;/);
    // 다크(수동·시스템 둘 다): 바탕 mute, 띠 ink
    expect(css).toMatch(/:root\[data-theme="dark"\] \.progress-shimmer\s*\{\s*--shimmer-base:\s*var\(--color-mute\);\s*--shimmer-hi:\s*var\(--color-ink\);/);
    expect(css).toMatch(/:root:not\(\[data-theme="light"\]\) \.progress-shimmer\s*\{\s*--shimmer-base:\s*var\(--color-mute\);\s*--shimmer-hi:\s*var\(--color-ink\);/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.progress-shimmer\s*\{[^}]*background-image:\s*none/);
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

  it("입력창 아래 통합 고지(FE-17 U-02): 한 단락(role=note)이고 입력창의 설명이며, 입력창 아래·체크·버튼·마스코트 없음. 예전 두 줄(legal-footer·input-notice)은 없다", () => {
    render(<ChatInput onSend={() => {}} />);
    const notice = screen.getByTestId("input-combined-notice");
    expect(notice.tagName).toBe("P");
    expect(notice.textContent).toBe(copy.INPUT_COMBINED_NOTICE);
    expect(notice).toHaveAttribute("role", "note");
    expect(screen.getByRole("textbox")).toHaveAccessibleDescription(copy.INPUT_COMBINED_NOTICE);
    expect(notice.compareDocumentPosition(screen.getByRole("textbox")) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(notice.closest("details, [role=dialog], [data-state=closed]")).toBeNull();
    expect(notice.querySelector("button, a, input, img")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(screen.queryByTestId("legal-footer")).toBeNull();
    expect(screen.queryByTestId("input-notice")).toBeNull();
  });

  it("통합 고지 문장은 빠지면 안 되는 의미 5가지를 모두 담는다(FE-17 §3.2). 예전 두 상수는 지우지 않고 그대로다", () => {
    const text = copy.INPUT_COMBINED_NOTICE;
    // ① 공공데이터 기반 정보 제공·진단·처방 아님 ② 금기 목록에 없다고 안전한 것 아님 ③ DUR 점검 대체 아님 ④ 질문 저장 안 함(탭 닫으면 사라짐) ⑤ 외부 AI(OpenAI) 전송·일정 기간 보관 가능
    for (const part of ["공공데이터 기반 정보 제공", "진단·처방이 아니", "금기 목록에 없어도 안전하다는 뜻은 아니", "DUR 점검을 대체하지 않", "질문은 저장하지 않", "탭을 닫으면 사라지", "질문과 선택한 프로필 값", "외부 AI(OpenAI)로 전송", "제공자 정책에 따라 일정 기간 보관될 수 있"]) {
      expect(text, part).toContain(part);
    }
    expect(text).toBe(
      "공공데이터 기반 정보 제공이며 진단·처방이 아니에요. 금기 목록에 없어도 안전하다는 뜻은 아니고, 요양기관의 DUR 점검을 대체하지 않아요. 질문은 저장하지 않고 탭을 닫으면 사라지지만, 답변을 만들기 위해 질문과 선택한 프로필 값이 외부 AI(OpenAI)로 전송되며 제공자 정책에 따라 일정 기간 보관될 수 있어요.",
    );
    // 예전 상수(승인 원문)는 그대로 남아 있다(다른 화면·시험이 쓴다)
    expect(copy.INPUT_NOTICE).toBe("질문은 이 탭에만 있고 저장하지 않아요. 새로고침하거나 탭을 닫으면 사라져요. 답변을 만들기 위해 질문과 선택한 프로필 값은 외부 AI(OpenAI)로 전송되며, 제공자 정책에 따라 일정 기간 보관될 수 있어요.");
    expect(DISCLAIMER).toBe("공공데이터 기반 정보 제공이며 진단·처방이 아님 · 금기 목록에 없다는 것이 안전하다는 뜻이 아님 · 요양기관의 DUR 점검을 대체하지 않음");
  });

  it("토글 칸과 프로필 칩은 같은 글자 크기·줄 높이(12px/16px)라 글자 윗부분이 잘리지 않는다(FE-17 U-20: 예전 줄 높이 12px에서 말줄임 칸이 글꼴 상자를 잘랐다)", () => {
    render(<ChatInput onSend={() => {}} pregnancy={{ value: false, onChange: () => {} }} onPhoto={() => {}} target={<TargetChip profiles={[]} value={null} onChange={() => {}} />} />);
    const face = screen.getByTestId("target-chip-face");
    for (const el of [screen.getByTestId("pregnancy-general"), screen.getByTestId("pregnancy-pregnant"), face]) {
      const tokens = el.className.split(" ");
      expect(tokens).toContain("text-xs");
      expect(tokens).toContain("leading-4");
      expect(tokens).not.toContain("leading-none");
    }
    // 실제 잘림(글꼴 상자 ⊂ 잘림 상자)은 브라우저에서만 잴 수 있어 e2e(ux-batch5)가 본다
  });

  it("질문 칸 아래 줄 왼쪽이 '사진 → 토글 · 칩' 한 묶음이고(FE-17 U-07 좌하단) 보내기는 그 뒤다. 칩을 주지 않아도(게스트·프로필 없음) 같은 배치에서 칩과 점만 빠진다(FE-17 U-09)", () => {
    const pregnancy = { value: false, onChange: () => {} };
    const { rerender } = render(<ChatInput onSend={() => {}} pregnancy={pregnancy} onPhoto={() => {}} />);
    // 게스트: 질문 칸(첫 줄 전체) → 아래 줄 [사진 → 토글] → 보내기. 예전 한 줄(토글 → 질문 칸 → 사진)은 없다
    const guestRow = screen.getByTestId("input-target-row");
    expect(guestRow.getAttribute("data-target")).toBe("none");
    const guestPhoto = within(guestRow).getByTestId("photo-entry");
    const guestToggle = within(guestRow).getByTestId("pregnancy-toggle");
    expect(guestPhoto.compareDocumentPosition(guestToggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("textbox").compareDocumentPosition(guestRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(guestRow.compareDocumentPosition(screen.getByRole("button", { name: "보내기" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("textbox").className).toContain("basis-full");
    expect(screen.getAllByTestId("photo-entry")).toHaveLength(1);
    expect(guestRow.textContent).not.toContain("·"); // 칩이 없으면 구분 점도 없다
    rerender(<ChatInput onSend={() => {}} pregnancy={pregnancy} onPhoto={() => {}} target={<button type="button">칩</button>} />);
    const row = screen.getByTestId("input-target-row");
    const photo = within(row).getByTestId("photo-entry");
    const toggle = within(row).getByTestId("pregnancy-toggle");
    const chip = within(row).getByRole("button", { name: "칩" });
    expect(screen.getAllByTestId("photo-entry")).toHaveLength(1); // 사진 입구는 하나
    // 묶음 안 순서: 사진 → 토글 → 칩
    expect(photo.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggle.compareDocumentPosition(chip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 묶음은 질문 칸 아래(뒤), 보내기는 묶음 뒤
    expect(screen.getByRole("textbox").compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(row.compareDocumentPosition(screen.getByRole("button", { name: "보내기" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("textbox").className).toContain("basis-full"); // 질문 칸이 첫 줄 전체
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

  it("보정 고지(name_corrections)는 요약보다 먼저, 받은 글자·순서 그대로 보이고 없으면 그리지 않는다(FE-02)", () => {
    const corrected: ChatResponse = {
      ...custom,
      name_corrections: [
        { input: "가", name: "가나", text: "받은 고지 하나" },
        { input: "나", name: "나다", text: "받은 고지 둘" },
      ],
    };
    const { rerender } = render(<ResultSlot response={corrected} />);
    const list = screen.getByTestId("name-corrections");
    expect([...list.querySelectorAll("li")].map((el) => el.textContent)).toEqual(["받은 고지 하나", "받은 고지 둘"]);
    const summary = screen.getByText(/받은 요약 1줄/);
    expect(list.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(list.textContent).not.toContain("삐!");
    rerender(<ResultSlot response={custom} />);
    expect(screen.queryByTestId("name-corrections")).toBeNull();
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
