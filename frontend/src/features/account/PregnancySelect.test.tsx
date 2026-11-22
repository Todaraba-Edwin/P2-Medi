import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { createAccountStore } from "@/stores/account";
import { AccountModal } from "./AccountModal";
import { PREGNANCY_LABELS } from "./copy";
import { PREGNANCY_SELECT_ORDER, PregnancySelect } from "./PregnancySelect";
import { PREGNANCY_WHEN_NOT_FEMALE, pregnancyToSave, showsPregnancyField } from "./ProfileForm";

// 프로필 폼의 임신 여부(작업 B, 사용자 지시 2026-11-22): 성별이 여성일 때만 보이는 선택 버튼 "예 | 아니오 | 모름".
// 글자는 기존 `PREGNANCY_LABELS`만 쓴다. 입력창의 "일반인 | 임산부" 토글(FE-11)은 건드리지 않는다(`features/chat/PregnancyToggle.test.tsx`).
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  server.use(...createAccountHandlers());
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());

describe("PregnancySelect", () => {
  it("순서는 예 | 아니오 | 모름이고 고른 칸만 aria-checked + 굵게 + 노랑 토큰 + 체크 아이콘이다. 글자는 기존 라벨 그대로", () => {
    const { rerender } = render(
      <>
        <span id="label">임신 여부</span>
        <PregnancySelect value="unknown" onChange={() => {}} labelledBy="label" />
      </>,
    );
    const group = screen.getByRole("radiogroup", { name: "임신 여부" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((radio) => radio.textContent)).toEqual(["예", "아니오", "모름"]);
    expect(PREGNANCY_SELECT_ORDER.map((status) => PREGNANCY_LABELS[status])).toEqual(["예", "아니오", "모름"]);
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual(["false", "false", "true"]);
    expect(radios.map((radio) => radio.getAttribute("type"))).toEqual(["button", "button", "button"]); // 폼 제출을 일으키지 않는다
    const [yes, , unknown] = radios;
    expect(unknown.className).toMatch(/\bbg-yellow\b/);
    expect(unknown.className).toMatch(/\bfont-extrabold\b/);
    expect(unknown.className).toMatch(/\btext-on-yellow\b/);
    expect(unknown.querySelector("svg")).not.toBeNull(); // 체크 아이콘(색만으로 구분하지 않는다)
    expect(yes.className).toMatch(/\bbg-bg-soft\b/);
    expect(yes.className).toMatch(/\btext-mute\b/);
    expect(yes.querySelector("svg")).toBeNull();
    for (const radio of radios) {
      expect(radio.className).toMatch(/\bh-10\b/); // 틀 44px(h-11) 안 40px: 누르는 영역은 틀째 44px
      expect(radio.className).not.toMatch(/#[0-9a-f]{3,6}/i);
    }
    expect(group.className).toMatch(/\bh-11\b/);
    rerender(
      <>
        <span id="label">임신 여부</span>
        <PregnancySelect value="pregnant" onChange={() => {}} labelledBy="label" />
      </>,
    );
    expect(within(group).getAllByRole("radio").map((radio) => radio.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(group.getAttribute("data-value")).toBe("pregnant");
  });

  it("누르면 그 값이고 ←/→(↑/↓)로 옮기며 끝에서 돌고 초점이 따라간다. 로빙 탭", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <span id="label">임신 여부</span>
        <PregnancySelect value="pregnant" onChange={onChange} labelledBy="label" />
      </>,
    );
    const [yes, no, unknown] = screen.getAllByRole("radio");
    expect([yes.tabIndex, no.tabIndex, unknown.tabIndex]).toEqual([0, -1, -1]);
    await user.click(no);
    expect(onChange).toHaveBeenLastCalledWith("not_pregnant");
    yes.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("not_pregnant");
    expect(no).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("pregnant");
    expect(yes).toHaveFocus();
    await user.keyboard("{ArrowLeft}"); // 처음에서 왼쪽은 마지막으로
    expect(onChange).toHaveBeenLastCalledWith("unknown");
    expect(unknown).toHaveFocus();
    await user.keyboard("{ArrowDown}"); // 마지막에서 오른쪽은 처음으로(초점이 있는 칸 기준으로 옮긴다)
    expect(onChange).toHaveBeenLastCalledWith("pregnant");
    expect(yes).toHaveFocus();
    expect(onChange).toHaveBeenCalledTimes(5);
  });

  it("비활성이면 누르거나 옮길 수 없다", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <>
        <span id="label">임신 여부</span>
        <PregnancySelect value="unknown" onChange={onChange} labelledBy="label" disabled />
      </>,
    );
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "예" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("프로필 폼의 임신 여부 칸(여성일 때만)", () => {
  const modal = () => screen.getByTestId("account-modal");
  const step = () => modal().getAttribute("data-step");
  const field = () => screen.queryByTestId("pregnancy-field");

  async function openForm({ health }: { health: boolean }) {
    const store = createAccountStore();
    const user = userEvent.setup();
    render(<AccountModal store={store} />);
    store.getState().open();
    await user.click(await screen.findByRole("button", { name: "Google로 계속하기" })); // 카카오면 이름 칸에 닉네임이 미리 들어간다(FE-04-28 B)
    await waitFor(() => expect(step()).toBe("consent"));
    await waitFor(() => expect(modal().querySelectorAll('[data-testid="legal-doc"]')).toHaveLength(4));
    for (const docType of ["terms", "privacy_consent", "age_14", ...(health ? ["sensitive_consent"] : [])]) {
      await user.click(within(modal().querySelector<HTMLElement>(`[data-doc-type="${docType}"]`)!).getByRole("checkbox"));
    }
    await user.click(screen.getByTestId("consent-submit"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByTestId("add-self"));
    await waitFor(() => expect(step()).toBe("profile-form"));
    return { store, user };
  }

  it("순수 규칙(사용자 결정 2026-11-22 작업 C): 여성만 보이고 여성은 고른 값, 여성이 아니면(남성·미입력) 저장 값은 아니오(`not_pregnant`)다", () => {
    expect(showsPregnancyField("female")).toBe(true);
    expect(showsPregnancyField("male")).toBe(false);
    expect(showsPregnancyField("")).toBe(false);
    expect(PREGNANCY_WHEN_NOT_FEMALE).toBe("not_pregnant");
    expect(pregnancyToSave("female", "pregnant")).toBe("pregnant");
    expect(pregnancyToSave("female", "unknown")).toBe("unknown");
    expect(pregnancyToSave("male", "pregnant")).toBe("not_pregnant");
    expect(pregnancyToSave("male", "unknown")).toBe("not_pregnant");
    expect(pregnancyToSave("", "pregnant")).toBe("not_pregnant"); // 미입력도 아니오(2026-11-22 정정)
    expect(pregnancyToSave("", "unknown")).toBe("not_pregnant");
  });

  it("처음(성별 선택 안 함)에는 없고, 여성을 고르면 나타나며, 남성·선택 안 함으로 바꾸면 사라진다", async () => {
    const { user } = await openForm({ health: true });
    expect(field()).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "임신 여부" })).toBeNull();
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    expect(field()).not.toBeNull();
    expect(within(screen.getByRole("radiogroup", { name: "임신 여부" })).getAllByRole("radio").map((radio) => radio.textContent)).toEqual(["예", "아니오", "모름"]);
    expect(screen.getByRole("radio", { name: "모름" })).toHaveAttribute("aria-checked", "true"); // 기본 모름
    await user.selectOptions(screen.getByLabelText("성별"), "male");
    expect(field()).toBeNull();
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    expect(field()).not.toBeNull();
    await user.selectOptions(screen.getByLabelText("성별"), "");
    expect(field()).toBeNull();
  });

  it("여성에서 '예'를 고른 뒤 남성으로 바꾸면 칸이 숨겨지고(다시 여성으로 돌리면 모름에서 고른다), 남성으로 저장하면 요청의 pregnancy_status는 아니오다", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/profiles")) bodies.push(await request.clone().json());
    });
    const { user, store } = await openForm({ health: true });
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    await user.click(screen.getByRole("radio", { name: "예" }));
    expect(screen.getByRole("radio", { name: "예" })).toHaveAttribute("aria-checked", "true");
    await user.selectOptions(screen.getByLabelText("성별"), "male");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    expect(screen.getByRole("radio", { name: "모름" })).toHaveAttribute("aria-checked", "true"); // 숨겨질 때 초기화됐다
    await user.selectOptions(screen.getByLabelText("성별"), "male");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    server.events.removeAllListeners();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ sex: "male", pregnancy_status: "not_pregnant" });
    expect(store.getState().profiles[0]).toMatchObject({ sex: "male", pregnancy_status: "not_pregnant" });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("임신 여부 아니오"); // 저장 값이 모름이 아니라 요약에 보인다
  });

  it("성별 미입력(선택 안 함)으로 저장해도 요청의 pregnancy_status는 아니오다(2026-11-22 정정 '미입력도 아니오로 저장')", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/profiles")) bodies.push(await request.clone().json());
    });
    const { user, store } = await openForm({ health: true });
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    expect(screen.getByLabelText("성별")).toHaveValue("");
    expect(field()).toBeNull();
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    server.events.removeAllListeners();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ sex: null, pregnancy_status: "not_pregnant" });
    expect(store.getState().profiles[0]).toMatchObject({ sex: null, pregnancy_status: "not_pregnant" });
  });

  it("여성이면 고른 값(예)이 그대로 저장되고 수정 화면에 다시 채워진다", async () => {
    const { user, store } = await openForm({ health: true });
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ sex: "female", pregnancy_status: "pregnant" });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("여성 · 임신 여부 예");
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    await waitFor(() => expect(step()).toBe("profile-form"));
    expect(field()).not.toBeNull();
    expect(screen.getByRole("radio", { name: "예" })).toHaveAttribute("aria-checked", "true");
  });

  it("저장된 프로필이 여성이 아닌데 임신 상태가 남아 있으면(입력창 토글로 저장된 값) 수정 화면에서 숨기고, 저장하면 아니오로 정리한다", async () => {
    const { user, store } = await openForm({ health: true });
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByTestId("profile-save")); // 성별 미입력
    await waitFor(() => expect(step()).toBe("profiles"));
    const profileId = store.getState().profiles[0].profile_id;
    expect(await store.getState().savePregnancy(profileId, "pregnant")).toBeNull(); // 입력창 토글 경로(FE-11-13)는 성별과 상관없이 저장한다
    expect(store.getState().profiles[0]).toMatchObject({ sex: null, pregnancy_status: "pregnant" });
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    await waitFor(() => expect(step()).toBe("profile-form"));
    expect(field()).toBeNull();
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ sex: null, pregnancy_status: "not_pregnant" });
  });

  it("건강 정보 동의가 없으면 여성이어도 칸은 비활성(모름 고정)이고 저장 요청에 건강 칸이 없다. 가족 프로필도 같은 부품·독립 값이다", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/profiles")) bodies.push(await request.clone().json());
    });
    const { user } = await openForm({ health: false });
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    for (const radio of within(screen.getByRole("radiogroup", { name: "임신 여부" })).getAllByRole("radio")) expect(radio).toBeDisabled();
    expect(screen.getByRole("radio", { name: "모름" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByTestId("add-family"));
    await waitFor(() => expect(step()).toBe("profile-form"));
    expect(field()).toBeNull(); // 가족 프로필은 처음부터 다시(독립)
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    expect(screen.getByTestId("pregnancy-field")).toBeInTheDocument();
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    server.events.removeAllListeners();
    expect(bodies).toHaveLength(2);
    for (const body of bodies) expect(Object.keys(body)).toEqual(["relation", "label", "age_band", "sex"]);
  });
});
