import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatInput } from "./ChatInput";
import * as copy from "./copy";
import { PregnancyToggle } from "./PregnancyToggle";

// 임신 여부 좌우 토글(FE-11 §7.1 최종 디자인 `Rdd-Toggle`, 2026-11-20): 글자·역할·키보드·표시 규칙. 폭·색 대비·누르는 영역은 e2e(g1-5a.spec)가 본다

describe("PregnancyToggle", () => {
  it("라디오 묶음 '임신 여부'에 '일반인 | 임산부' 두 칸이 늘 함께 보이고 고른 칸만 aria-checked다(승인 글자 FE-11-11 A)", () => {
    const { rerender } = render(<PregnancyToggle value={false} onChange={() => {}} />);
    const group = screen.getByRole("radiogroup", { name: "임신 여부" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((radio) => radio.textContent)).toEqual(["일반인", "임산부"]);
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(copy.PREGNANCY_TOGGLE_LABEL).toBe("임신 여부");
    expect([copy.PREGNANCY_OPTION_GENERAL, copy.PREGNANCY_OPTION_PREGNANT]).toEqual(["일반인", "임산부"]);
    // 옛 글자("일반 | 임신 중")·"모름" 칸은 없다
    expect(group.textContent).not.toMatch(/임신 중|모름/);
    rerender(<PregnancyToggle value onChange={() => {}} />);
    expect(within(group).getAllByRole("radio").map((radio) => radio.getAttribute("aria-checked"))).toEqual(["false", "true"]);
    expect(group.getAttribute("data-pregnant")).toBe("true");
  });

  it("고른 칸은 노랑 토큰 + 굵게, 안 고른 칸은 크림 토큰 + 보통 글자(색만으로 구분하지 않는다). 칸 높이 28px 틀 안 24px, 누르는 영역은 before로 44px", () => {
    render(<PregnancyToggle value={false} onChange={() => {}} />);
    const [general, pregnant] = screen.getAllByRole("radio");
    expect(general.className).toMatch(/\bbg-yellow\b/);
    expect(general.className).toMatch(/\bfont-extrabold\b/);
    expect(general.className).toMatch(/\btext-on-yellow\b/); // 노랑 바탕 전용 글자 토큰(다크에서 text-ink는 크림이라 안 보인다, FE-12)
    expect(general.className).not.toMatch(/\btext-ink\b/);
    expect(pregnant.className).toMatch(/\bbg-bg-soft\b/);
    expect(pregnant.className).toMatch(/\btext-mute\b/);
    expect(pregnant.className).not.toMatch(/\bfont-extrabold\b/);
    for (const radio of [general, pregnant]) {
      expect(radio.className).toMatch(/\bh-6\b/);
      expect(radio.className).toMatch(/before:-inset-y-2\.5/); // 24 + 10 + 10 = 44
      expect(radio.className).toMatch(/focus-visible:outline-3/);
      expect(radio.className).toMatch(/focus-visible:outline-ink-2/);
      expect(radio.className).not.toMatch(/#[0-9a-f]{3,6}/i); // 하드코딩 색 없음(토큰만)
    }
    expect(general.parentElement?.className).toMatch(/\bh-7\b/);
    expect(screen.getByRole("radiogroup").className).toMatch(/\bh-11\b/);
  });

  it("누르면 그 칸 값으로 바뀌고 ←/→(↑/↓)로 옮기며 초점이 따라간다", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<PregnancyToggle value={false} onChange={onChange} />);
    const [general, pregnant] = screen.getAllByRole("radio");
    await user.click(pregnant);
    expect(onChange).toHaveBeenLastCalledWith(true);
    // 로빙 탭: 고른 칸만 탭 순서에 있다
    expect(general.tabIndex).toBe(0);
    expect(pregnant.tabIndex).toBe(-1);
    general.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith(true);
    expect(pregnant).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith(false);
    expect(general).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(onChange).toHaveBeenLastCalledWith(true);
    await user.keyboard("{ArrowUp}");
    expect(onChange).toHaveBeenLastCalledWith(false);
    expect(onChange).toHaveBeenCalledTimes(5);
  });
});

describe("ChatInput의 임신 여부 선택", () => {
  it("pregnancy를 주면 입력창 안 왼쪽(텍스트 영역 앞)에 토글이 있고, 주지 않으면 없다. 폼 제출을 일으키지 않는다", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<ChatInput onSend={onSend} />);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    rerender(<ChatInput onSend={onSend} pregnancy={{ value: false, onChange: () => {} }} />);
    const form = screen.getByRole("textbox").closest("form")!;
    const group = screen.getByRole("radiogroup", { name: "임신 여부" });
    expect(form.contains(group)).toBe(true);
    expect(group.compareDocumentPosition(screen.getByRole("textbox")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const radio of within(group).getAllByRole("radio")) expect(radio.getAttribute("type")).toBe("button");
    await user.click(within(group).getByRole("radio", { name: "임산부" }));
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    expect(screen.queryByTestId("pregnancy-save-error")).toBeNull();
  });

  it("안내(hint)는 status, 저장 실패(error)는 alert로 토글 아래 한 줄이고 묶음이 aria-describedby로 가리킨다. 입력창 고지는 그대로 1회", () => {
    const { rerender } = render(<ChatInput onSend={() => {}} pregnancy={{ value: false, onChange: () => {}, hint: copy.PREGNANCY_SAVE_CONSENT_HINT }} />);
    const hint = screen.getByTestId("pregnancy-hint");
    expect(hint.textContent).toBe("프로필에 저장하려면 건강 정보 동의가 필요해요");
    expect(hint.getAttribute("role")).toBe("status");
    expect(screen.getByRole("radiogroup").getAttribute("aria-describedby")).toBe(hint.id);
    expect(screen.getAllByTestId("input-combined-notice")).toHaveLength(1);
    rerender(<ChatInput onSend={() => {}} pregnancy={{ value: false, onChange: () => {}, hint: copy.PREGNANCY_SAVE_CONSENT_HINT, error: "저장 실패 안내" }} />);
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    const error = screen.getByTestId("pregnancy-save-error");
    expect(error.textContent).toBe("저장 실패 안내");
    expect(error.getAttribute("role")).toBe("alert");
    expect(screen.getByRole("radiogroup").getAttribute("aria-describedby")).toBe(error.id);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});
