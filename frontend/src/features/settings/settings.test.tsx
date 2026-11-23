import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readUiSetting, removeUiSetting, writeUiSetting } from "@/lib/ui-settings";
import { SettingsDialog } from "./SettingsDialog";
import { SYSTEM_MODE_HINT, THEME_LABELS } from "./copy";

// 설정 화면의 "화면 모드" 3칸(FE-12-03 B): radiogroup, 기본은 시스템, 고른 값은 기기 저장소에만 저장한다(FE-12-04 A)
beforeEach(() => {
  removeUiSetting("theme");
  delete document.documentElement.dataset.theme;
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderDialog(showLogin = false, onLogin = () => {}) {
  return render(<SettingsDialog open onOpenChange={() => {}} showLogin={showLogin} onLogin={onLogin} />);
}

describe("설정 화면 화면 모드", () => {
  it("기본은 시스템이고, 승인된 글자 세 칸과 설명을 보인다", () => {
    renderDialog();
    const group = screen.getByRole("radiogroup", { name: "화면 모드" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: THEME_LABELS.system })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: THEME_LABELS.light })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(SYSTEM_MODE_HINT)).toBeInTheDocument();
  });

  it("다크 모드를 고르면 바로 적용되고 기기 저장소에 저장된다(서버 호출 없음)", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderDialog();
    await userEvent.click(screen.getByRole("radio", { name: THEME_LABELS.dark }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(readUiSetting("theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: THEME_LABELS.dark })).toHaveAttribute("aria-checked", "true");
    // 약관·정책 묶음은 열릴 때 문서(`GET /api/legal/*`)를 읽는다(2026-11-23, 읽기 전용). 화면 모드 선택은 그 밖의 어떤 호출도 만들지 않는다
    const urlOf = (input: unknown) => (input instanceof Request ? input.url : String(input));
    expect(fetchSpy.mock.calls.map(([input]) => urlOf(input)).filter((url) => !url.includes("/api/legal/"))).toEqual([]);
  });

  it("화살표 키로 칸을 옮기며 고르고, 끝에서 처음으로 돈다", () => {
    renderDialog();
    const system = screen.getByRole("radio", { name: THEME_LABELS.system });
    system.focus();
    fireEvent.keyDown(system, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: THEME_LABELS.light })).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("radio", { name: THEME_LABELS.light })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("radio", { name: THEME_LABELS.light }), { key: "ArrowLeft" });
    expect(screen.getByRole("radio", { name: THEME_LABELS.system })).toHaveAttribute("aria-checked", "true");
  });

  it("저장된 값이 있으면 열 때 그 값을 고른 상태로 보인다", () => {
    writeUiSetting("theme", "dark");
    renderDialog();
    expect(screen.getByRole("radio", { name: THEME_LABELS.dark })).toHaveAttribute("aria-checked", "true");
  });

  it("게스트에게는 로그인 안내와 로그인/가입 버튼을 보인다", async () => {
    const onLogin = vi.fn();
    renderDialog(true, onLogin);
    expect(screen.getByText("프로필을 저장하려면 로그인하세요.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "로그인/가입" }));
    expect(onLogin).toHaveBeenCalledTimes(1);
  });
});
