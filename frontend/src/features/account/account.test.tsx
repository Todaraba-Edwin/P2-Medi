import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { START_EXTERNAL_AI_NOTICE } from "@/lib/fixed/phrases.generated";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_LEGAL_DOCS } from "@/mocks/fixtures/account";
import { createAccountStore } from "@/stores/account";
import type { AccountStore } from "@/stores/account";
import { AccountModal, openAccountModal } from "./AccountModal";
import { HEALTH_CONSENT_REQUIRED_FALLBACK } from "./copy";
import { AccountMenu, EntryChoice } from "./EntryChoice";
import { Markdown, parseMarkdown } from "./Markdown";
import { TargetPicker } from "./TargetPicker";

// 계정 화면(모달·진입 선택·대상 선택)을 MSW 목에 붙여 그린다(실제 서버 호출 0).
const server = setupServer();
const setItem = vi.spyOn(Storage.prototype, "setItem");
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  server.use(...createAccountHandlers());
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
  setItem.mockClear();
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());

const modal = () => screen.getByTestId("account-modal");
const step = () => modal().getAttribute("data-step");
const docItem = (docType: string) => modal().querySelector<HTMLElement>(`[data-doc-type="${docType}"]`)!;
const check = (docType: string) => within(docItem(docType)).getByRole("checkbox");

function setup() {
  const user = userEvent.setup();
  const store: AccountStore = createAccountStore();
  render(
    <>
      <button type="button" onClick={() => openAccountModal(store)}>
        프로필 저장
      </button>
      <AccountModal store={store} emergencyEntry={<a href="tel:119">119 전화</a>} />
    </>,
  );
  return { user, store };
}

async function login(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "프로필 저장" }));
  await user.type(screen.getByLabelText("이메일"), "user@example.com");
  await user.type(screen.getByLabelText("비밀번호"), "pw-1234");
  await user.click(screen.getByRole("button", { name: "로그인" }));
  await waitFor(() => expect(step()).toBe("consent"));
  await waitFor(() => expect(modal().querySelectorAll('[data-testid="legal-doc"]')).toHaveLength(4));
}

async function consent(user: ReturnType<typeof userEvent.setup>, { health }: { health: boolean }) {
  await user.click(check("terms"));
  await user.click(check("privacy"));
  if (health) await user.click(check("sensitive_health"));
  await user.click(screen.getByTestId("consent-submit"));
  await waitFor(() => expect(step()).toBe("profiles"));
}

describe("모달 배치(PRD-13)", () => {
  it("로그인 첫 화면: header 띠·구분선이 없고 `<`는 DOM에 없으며 닫기는 글자다. 초점은 제목에 간다", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    expect(modal()).toHaveAttribute("role", "dialog");
    expect(modal().querySelector("header, hr")).toBeNull(); // ① 버튼만 담는 header·구분선 없음
    expect(screen.queryByRole("button", { name: "뒤로" })).toBeNull(); // ②⑨ 첫 화면에는 `<`가 없다(숨김이 아니라 없음)
    const close = screen.getByRole("button", { name: "닫기" });
    expect(close).toHaveTextContent("닫기"); // ⑥ 보이는 글자와 이름이 같다
    expect(close.className).toContain("absolute");
    expect(close.className).toContain("min-h-11");
    expect(close.className).toContain("min-w-11");
    expect(screen.getByRole("heading", { name: "프로필을 저장하려면 로그인하세요" })).toHaveFocus(); // ⑤
    expect(modal()).toHaveAccessibleName("프로필을 저장하려면 로그인하세요");
    // 모달이 머리줄을 덮는 동안의 119 진입점
    expect(within(modal()).getByRole("link", { name: "119 전화" })).toHaveAttribute("href", "tel:119");
  });

  it("가입 화면에서는 `<`가 생기고 누르면 로그인으로 돌아간다. 코너 버튼은 같은 높이의 absolute다", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "이메일로 가입하기" }));
    expect(step()).toBe("signup");
    const back = screen.getByRole("button", { name: "뒤로" });
    const close = screen.getByRole("button", { name: "닫기" });
    for (const button of [back, close]) for (const name of ["absolute", "top-2", "min-h-11", "min-w-11"]) expect(button.className).toContain(name);
    expect(back.className).toContain("left-2");
    expect(close.className).toContain("right-2");
    // 탭 순서는 화면 순서(`<` → 닫기)와 같다
    expect(back.compareDocumentPosition(close) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(back);
    expect(step()).toBe("login");
    expect(screen.queryByRole("button", { name: "뒤로" })).toBeNull();
  });

  it("Esc와 닫기로 닫히고 초점이 연 버튼으로 돌아온다", async () => {
    const { user } = setup();
    const opener = screen.getByRole("button", { name: "프로필 저장" });
    await user.click(opener);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "닫기" }));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("119 안내가 떠 있으면 마스코트를 그리지 않는다", async () => {
    const store = createAccountStore();
    render(<AccountModal store={store} hasEmergency />);
    store.getState().open();
    await screen.findByTestId("account-modal");
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("로그인 화면", () => {
  it("이메일 + Google·Kakao, Naver는 '준비 중' 비활성, Apple은 없다", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    expect(screen.getByRole("button", { name: "Google로 계속하기" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "카카오로 계속하기" })).toBeEnabled();
    const naver = screen.getByTestId("social-naver");
    expect(naver).toBeDisabled();
    expect(naver).toHaveTextContent("준비 중");
    expect(naver).not.toHaveAttribute("title"); // 이유 툴팁 없이 글자만
    expect(modal().textContent).not.toMatch(/apple|애플/i);
  });

  it("이메일 형식·빈 비밀번호는 보내지 않고 알린다", async () => {
    const { user, store } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "로그인" }));
    expect(screen.getByRole("alert")).toHaveTextContent("이메일 주소를 확인해 주세요.");
    await user.type(screen.getByLabelText("이메일"), "user@example.com");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    expect(screen.getByRole("alert")).toHaveTextContent("비밀번호를 입력해 주세요.");
    expect(store.getState().status).toBe("guest");
  });

  it("소셜 로그인 목 → 로그인 상태가 되고 동의 화면으로 간다", async () => {
    const { user, store } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "카카오로 계속하기" }));
    await waitFor(() => expect(step()).toBe("consent"));
    expect(store.getState().me?.providers).toEqual(["kakao"]);
  });

  it("'로그인 없이 계속하기'는 모달을 닫고 게스트로 둔다", async () => {
    const { user, store } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "로그인 없이 계속하기" }));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
    expect(store.getState()).toMatchObject({ status: "guest", entryDismissed: true });
  });
});

describe("약관 동의 화면", () => {
  it("문서 제목·본문은 API 값 그대로이고 필수·선택 표지가 붙는다", async () => {
    const { user } = setup();
    await login(user);
    for (const doc of Object.values(MOCK_LEGAL_DOCS)) {
      const item = docItem(doc.doc_type);
      expect(item).toHaveAttribute("data-required", String(doc.required));
      expect(within(item).getByRole("heading", { level: 3 })).toHaveTextContent(`[${doc.required ? "필수" : "선택"}] ${doc.title}`);
      expect(item).toHaveTextContent(doc.version);
    }
    expect(docItem("terms")).toHaveTextContent("이 문서는 화면 개발용 합성 목 문서이며 실제 약관이 아닙니다.");
    // 외부 AI 전송 고지: 화면이 기존 시작 화면 고지 문구를 한 번 더 넣지 않는다(문서 본문은 서버 값뿐이다)
    expect(modal().textContent).not.toContain(START_EXTERNAL_AI_NOTICE);
    expect(MOCK_LEGAL_DOCS.external_ai.body_md).not.toContain(START_EXTERNAL_AI_NOTICE);
  });

  it("필수 두 문서에 모두 동의하기 전에는 다음 버튼이 비활성이고 이유가 보인다", async () => {
    const { user } = setup();
    await login(user);
    const submit = screen.getByTestId("consent-submit");
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("consent-hint")).toBeVisible();
    await user.click(check("terms"));
    await user.click(check("sensitive_health"));
    await user.click(check("external_ai"));
    expect(submit).toBeDisabled(); // 선택만으로는 안 된다
    await user.click(check("privacy"));
    expect(submit).toBeEnabled();
    expect(screen.queryByTestId("consent-hint")).toBeNull();
    await user.click(check("terms"));
    expect(submit).toBeDisabled();
  });

  it("동의 화면의 `<`는 로그인으로 돌아간다", async () => {
    const { user } = setup();
    await login(user);
    await user.click(screen.getByRole("button", { name: "뒤로" }));
    expect(step()).toBe("login");
  });
});

describe("프로필 화면", () => {
  it("건강 정보 동의가 없으면 임신 여부·복용 약 칸이 비활성이고 서버 문구가 그대로 보인다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-family"));
    expect(step()).toBe("profile-form");
    expect(screen.getByTestId("health-fields")).toBeDisabled();
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
    expect(screen.getByLabelText("복용 중인 약(선택)")).toBeDisabled();
    expect(screen.getByTestId("medication-add")).toBeDisabled();
    expect(screen.getByTestId("health-consent-notice")).toHaveTextContent(MOCK_LEGAL_DOCS.sensitive_health.declined_notice!);
    expect(screen.getByTestId("health-consent-notice")).not.toHaveTextContent(HEALTH_CONSENT_REQUIRED_FALLBACK);
    // 저장해도 건강 정보는 가지 않는다
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    await user.selectOptions(screen.getByLabelText("연령대"), "child");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles).toEqual([expect.objectContaining({ label: "첫째", relation: "child", age_band: "child", pregnancy_status: "unknown", medications: [] })]);
  });

  it("건강 정보 동의가 있으면 임신 여부·복용 약(입력 원문)을 넣어 저장하고, 수정·삭제할 수 있다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: true });
    expect(screen.queryByTestId("health-consent-notice")).toBeNull();
    await user.click(screen.getByTestId("add-self"));
    expect(screen.getByLabelText("관계")).toBeDisabled(); // 본인은 관계 고정
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("연령대"), "adult");
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.type(screen.getByLabelText("복용 중인 약(선택)"), "가나다정 100밀리그램{Enter}");
    expect(step()).toBe("profile-form"); // Enter는 저장이 아니라 약 추가
    expect(screen.getAllByTestId("medication")).toHaveLength(1);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ relation: "self", label: "나", pregnancy_status: "yes", medications: [{ drug_name: "가나다정 100밀리그램", item_seq: null }] });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("본인 · 만 19~64세 · 임신 여부 예 · 약 1개");
    expect(screen.queryByTestId("add-self")).toBeNull(); // 본인은 1개
    // 수정
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(screen.getByRole("button", { name: "뒤로" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("이름(별명)"));
    await user.type(screen.getByLabelText("이름(별명)"), "본인");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(screen.getByTestId("profile-item")).toHaveTextContent("본인"));
    // 삭제(확인 모달)
    await user.click(screen.getByRole("button", { name: "본인 삭제" }));
    await user.click(within(screen.getByTestId("confirm-dialog")).getByTestId("confirm-action"));
    await waitFor(() => expect(store.getState().profiles).toEqual([]));
  });

  it("가족이 3명이면 4번째 추가 버튼이 비활성이다", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: false });
    for (const name of ["첫째", "둘째", "엄마"]) {
      expect(screen.getByTestId("add-family")).toBeEnabled();
      await user.click(screen.getByTestId("add-family"));
      await user.type(screen.getByLabelText("이름(별명)"), name);
      await user.click(screen.getByTestId("profile-save"));
      await waitFor(() => expect(step()).toBe("profiles"));
    }
    expect(screen.getAllByTestId("profile-item")).toHaveLength(3);
    expect(screen.getByTestId("add-family")).toBeDisabled();
    expect(screen.getByTestId("add-family")).toHaveTextContent("가족 추가 (3/3)");
    expect(screen.getByTestId("family-full")).toBeVisible();
    expect(screen.getByTestId("add-self")).toBeEnabled(); // 본인 자리는 따로다
  });

  it("이름이 비어 있으면 저장하지 않는다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-family"));
    await user.click(screen.getByTestId("profile-save"));
    expect(screen.getByRole("alert")).toHaveTextContent("이름(별명)을 입력해 주세요.");
    expect(store.getState().profiles).toEqual([]);
  });

  it("탈퇴는 확인 모달을 거치고, 끝나면 게스트로 돌아가 모달이 닫힌다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("withdraw"));
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog).toHaveAttribute("role", "alertdialog");
    expect(dialog).toHaveTextContent("탈퇴할까요?");
    expect(store.getState().status).toBe("member"); // 확인 전에는 그대로
    await user.click(within(dialog).getByRole("button", { name: "취소" }));
    expect(store.getState().status).toBe("member");
    await user.click(screen.getByTestId("withdraw"));
    await user.click(within(screen.getByTestId("confirm-dialog")).getByRole("button", { name: "탈퇴하기" }));
    await waitFor(() => expect(store.getState().status).toBe("guest"));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
  });
});

describe("브라우저 저장소 미사용(FE-01-08 A)", () => {
  it("로그인 → 동의 → 건강 정보가 든 프로필 저장까지 localStorage·sessionStorage에 아무것도 쓰지 않는다", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: true });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.type(screen.getByLabelText("복용 중인 약(선택)"), "가나다정{Enter}");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(setItem).not.toHaveBeenCalled();
    // 저장소를 들여다보는 시험이라 이 두 줄만 규칙을 끈다
    // eslint-disable-next-line no-restricted-properties
    expect(window.localStorage).toHaveLength(0);
    // eslint-disable-next-line no-restricted-properties
    expect(window.sessionStorage).toHaveLength(0);
    expect(document.cookie).toBe("");
  });

  it("계정 코드(화면·스토어·API 모듈)는 브라우저 저장소·쿠키·persist·Supabase 클라이언트를 쓰지 않는다", () => {
    const src = path.resolve(__dirname, "../..");
    const files = [
      ...readdirSync(__dirname).filter((name) => /\.tsx?$/.test(name) && !name.includes(".test.")).map((name) => path.join(__dirname, name)),
      path.join(src, "stores/account.ts"),
      path.join(src, "stores/profile-context.ts"),
      path.join(src, "lib/api/account.ts"),
    ];
    expect(files.length).toBeGreaterThanOrEqual(12);
    for (const file of files) {
      const code = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ""); // 주석 제외
      expect(code, file).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie|zustand\/middleware|supabase|readUiSetting|writeUiSetting/i);
    }
  });
});

describe("시작 화면 진입 선택·사이드바 계정 자리", () => {
  it("'게스트로 시작'(주)이 먼저, '로그인/가입'(보조)이 다음이다", async () => {
    const onGuest = vi.fn();
    const onLogin = vi.fn();
    render(<EntryChoice onGuest={onGuest} onLogin={onLogin} />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["게스트로 시작", "로그인/가입"]);
    await userEvent.click(screen.getByRole("button", { name: "게스트로 시작" }));
    await userEvent.click(screen.getByRole("button", { name: "로그인/가입" }));
    expect(onGuest).toHaveBeenCalledTimes(1);
    expect(onLogin).toHaveBeenCalledTimes(1);
  });

  it("게스트는 '로그인/가입', 로그인하면 이름·프로필 관리·로그아웃", () => {
    const { rerender } = render(<AccountMenu displayName={null} onOpen={() => {}} onLogout={() => {}} />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["로그인/가입"]);
    rerender(<AccountMenu displayName="삐약 사용자" onOpen={() => {}} onLogout={() => {}} />);
    expect(screen.getByTestId("account-name")).toHaveTextContent("삐약 사용자");
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["프로필 관리", "로그아웃"]);
  });
});

describe("대상 선택 '누가 먹나요'", () => {
  it("프로필마다 고를 수 있고 '선택 안 함'으로 되돌린다", async () => {
    const onChange = vi.fn();
    const profiles = [
      { id: "a", relation: "self", label: "나", age_band: "adult", pregnancy_status: "unknown", medications: [] },
      { id: "b", relation: "child", label: "첫째", age_band: "child", pregnancy_status: "unknown", medications: [] },
    ] as const;
    const { rerender } = render(<TargetPicker profiles={profiles.map((profile) => ({ ...profile, medications: [] }))} value={null} onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "누가 먹나요" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio").map((radio) => radio.closest("label")?.textContent)).toEqual(["선택 안 함", "나", "첫째"]);
    expect(screen.getByRole("radio", { name: "선택 안 함" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "첫째" }));
    expect(onChange).toHaveBeenLastCalledWith("b");
    rerender(<TargetPicker profiles={profiles.map((profile) => ({ ...profile, medications: [] }))} value="b" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "첫째" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "선택 안 함" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

describe("법적 문서 본문 렌더", () => {
  it("제목·목록·문단·굵게를 그리고 HTML은 글자 그대로 둔다", () => {
    expect(parseMarkdown("# 가\n\n나\n다\n\n- 라\n- 마\n\n1. 바\n2. 사")).toEqual([
      { kind: "heading", level: 1, text: "가" },
      { kind: "paragraph", text: "나 다" },
      { kind: "list", ordered: false, items: ["라", "마"] },
      { kind: "list", ordered: true, items: ["바", "사"] },
    ]);
    const { container } = render(<Markdown source={"## 제목\n**굵게** 글자 <script>alert(1)</script>\n\n- 항목"} />);
    expect(container.querySelector("h4")).toHaveTextContent("제목");
    expect(container.querySelector("strong")).toHaveTextContent("굵게");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("p")).toHaveTextContent("굵게 글자 <script>alert(1)</script>");
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });
});
