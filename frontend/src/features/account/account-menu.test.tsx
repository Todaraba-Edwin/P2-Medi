import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readUiSetting, removeUiSetting, writeUiSetting } from "@/lib/ui-settings";
import { SYSTEM_MODE_HINT, THEME_LABELS } from "@/features/settings/copy";
import { AccountMenu } from "./AccountMenu";

// 계정 메뉴 팝오버(2026-11-23): 버튼 하나 → 위로 열리는 메뉴. 화면 모드 3칸(FE-12-03 B)은 메뉴 안에서 바로 고르고 기기 저장소에만 저장한다(FE-12-04 A).
// 옛 설정 화면 시험(settings.test.tsx)의 단언을 같은 행동·새 자리로 옮겼다: 기본 시스템, 고르면 즉시 적용·저장·서버 호출 0, 키보드 이동·끝에서 돌기, 저장값 복원.
beforeEach(() => {
  removeUiSetting("theme");
  delete document.documentElement.dataset.theme;
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function renderMenu(props: Partial<React.ComponentProps<typeof AccountMenu>> = {}) {
  const user = userEvent.setup();
  const handlers = { onOpen: vi.fn(), onLogout: vi.fn(), onLegal: vi.fn() };
  render(<AccountMenu member accountEnabled {...handlers} {...props} />);
  return { user, ...handlers, button: screen.getByTestId("account-menu-button") };
}
const radio = (mode: keyof typeof THEME_LABELS) => screen.getByRole("menuitemradio", { name: new RegExp(`^${THEME_LABELS[mode]}`) });

describe("계정 메뉴 팝오버", () => {
  it("버튼은 aria-haspopup·aria-expanded를 갖고, 열면 첫 항목에 초점이 가며 Esc로 닫히고 초점이 버튼으로 돌아온다", async () => {
    const { user, button } = renderMenu();
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("account-menu")).toBeNull();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByTestId("account-menu");
    expect(menu).toHaveAttribute("role", "menu");
    expect(menu).toHaveAccessibleName("로그인됨"); // 메뉴 이름은 버튼 글자(Radix `aria-labelledby`)
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "프로필 관리" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("바깥을 누르면 닫힌다", async () => {
    const { user, button } = renderMenu();
    await user.click(button);
    expect(screen.getByTestId("account-menu")).toBeInTheDocument();
    await user.click(document.body);
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
  });

  it("항목을 고르면 맡은 동작이 불리고 메뉴가 닫힌다(프로필 관리·약관·정책·로그아웃)", async () => {
    const { user, button, onOpen, onLegal, onLogout } = renderMenu();
    await user.click(button);
    await user.click(screen.getByRole("menuitem", { name: "프로필 관리" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
    await user.click(button);
    await user.click(screen.getByRole("menuitem", { name: "약관·정책" }));
    expect(onLegal).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
    await user.click(button);
    await user.click(screen.getByRole("menuitem", { name: "로그아웃" }));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("게스트 메뉴의 첫 항목은 '로그인/가입'이고 로그아웃이 없다", async () => {
    const { user, button, onOpen } = renderMenu({ member: false });
    expect(button).toHaveTextContent("계정");
    await user.click(button);
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "로그인/가입" })).toHaveFocus());
    expect(screen.queryByRole("menuitem", { name: "로그아웃" })).toBeNull();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("계정 메뉴의 화면 모드", () => {
  it("기본은 시스템이고, 승인된 글자 세 칸과 설명을 보인다", async () => {
    const { user, button } = renderMenu();
    await user.click(button);
    expect(screen.getByText("화면 모드")).toBeInTheDocument();
    expect(radio("system")).toHaveAttribute("aria-checked", "true");
    expect(radio("light")).toHaveAttribute("aria-checked", "false");
    expect(radio("dark")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(SYSTEM_MODE_HINT)).toBeInTheDocument();
  });

  it("다크 모드를 고르면 바로 적용되고 기기 저장소에 저장되며(서버 호출 없음) 메뉴는 열린 채다", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { user, button } = renderMenu();
    await user.click(button);
    await user.click(radio("dark"));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(readUiSetting("theme")).toBe("dark");
    expect(radio("dark")).toHaveAttribute("aria-checked", "true");
    expect(radio("system")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("account-menu")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("키보드로 칸을 옮겨 고르고(↓/↑·Enter), 끝에서 처음으로 돈다", async () => {
    const { user, button } = renderMenu({ member: false, accountEnabled: false });
    button.focus();
    await user.keyboard("{Enter}");
    // 첫 항목(밝은 모드)에 초점
    await waitFor(() => expect(radio("light")).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    expect(radio("dark")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(radio("dark")).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.theme).toBe("dark");
    // 위로 올라가 끝(약관·정책)에서 처음(밝은 모드)으로 돈다
    await user.keyboard("{ArrowUp}");
    expect(radio("light")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "약관·정책" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(radio("light")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(radio("light")).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("저장된 값이 있으면 열 때 그 값을 고른 상태로 보인다", async () => {
    writeUiSetting("theme", "dark");
    const { user, button } = renderMenu();
    await user.click(button);
    expect(radio("dark")).toHaveAttribute("aria-checked", "true");
  });
});
