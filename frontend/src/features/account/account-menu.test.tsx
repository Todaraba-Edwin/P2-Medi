import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readUiSetting, removeUiSetting, writeUiSetting } from "@/lib/ui-settings";
import { SYSTEM_MODE_HINT, THEME_LABELS } from "@/features/settings/copy";
import type { Profile } from "@/lib/api/account";
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

describe("계정 메뉴의 대상 프로필(2026-11-23)", () => {
  const profiles: Profile[] = [
    { profile_id: "a", relation: "self", label: "나", age_band: null, sex: null, pregnancy_status: null, avatar_color: "yellow", sort_order: 0, medications: [] },
    { profile_id: "b", relation: "child", label: "첫째", age_band: null, sex: null, pregnancy_status: null, avatar_color: "pink", sort_order: 1, medications: [] },
  ];

  it("고른 프로필이 있으면 버튼이 그 색의 병아리 + 이름이고, `프로필 관리` 바로 아래(하위)에 '누가 먹나요' 목록(게스트로 이용·본인·가족)이 있어 고르면 닫힌다(FE-17 U-06)", async () => {
    const onChange = vi.fn();
    const { user, button } = renderMenu({ target: { profiles, value: "b", onChange } });
    expect(button).toHaveTextContent("첫째");
    expect(within(button).getByTestId("profile-avatar")).toHaveAttribute("data-color", "pink");
    await user.click(button);
    const menu = screen.getByTestId("account-menu");
    expect(within(menu).getByRole("group", { name: "누가 먹나요" })).toBeInTheDocument();
    const radios = within(menu).getAllByRole("menuitemradio");
    expect(radios.slice(0, 3).map((item) => item.textContent)).toEqual(["게스트로 이용", "나", "첫째"]);
    expect(within(menu).getByRole("menuitemradio", { name: "첫째" })).toHaveAttribute("aria-checked", "true");
    // 순서: 프로필 관리 → (하위) 누가 먹나요 목록 → 화면 모드. 목록은 들여쓴 하위 묶음 안에 있다
    const manage = within(menu).getByRole("menuitem", { name: "프로필 관리" });
    const group = within(menu).getByRole("group", { name: "누가 먹나요" });
    expect(manage.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(group.compareDocumentPosition(within(menu).getByTestId("theme-choice")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(menu).getByTestId("target-choice-nested")).toContainElement(group);
    const items = within(menu).getAllByRole("menuitem").concat(radios);
    expect(items.every((item) => !/선택 안 함/.test(item.textContent ?? ""))).toBe(true);
    await waitFor(() => expect(manage).toHaveFocus()); // 첫 항목(프로필 관리)에 초점
    await user.click(within(menu).getByRole("menuitemradio", { name: "나" }));
    expect(onChange).toHaveBeenLastCalledWith("a");
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
  });

  it("고르지 않았으면 기존 상태 글자 '로그인됨', 게스트·프로필 없음은 목록이 없다", async () => {
    const { user, button } = renderMenu({ target: { profiles, value: null, onChange: () => {} } });
    expect(button).toHaveTextContent("로그인됨");
    expect(within(button).queryByTestId("profile-avatar")).toBeNull();
    await user.click(button);
    expect(screen.getByRole("group", { name: "누가 먹나요" })).toBeInTheDocument();
  });

  it("프로필이 없으면 목록을 그리지 않는다(기존 메뉴 그대로)", async () => {
    const { user, button } = renderMenu({ target: { profiles: [], value: null, onChange: () => {} } });
    await user.click(button);
    expect(screen.queryByRole("group", { name: "누가 먹나요" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "프로필 관리" })).toHaveFocus());
  });
});

