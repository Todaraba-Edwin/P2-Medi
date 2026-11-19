import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { START_EXTERNAL_AI_NOTICE } from "@/lib/fixed/phrases.generated";
import type { Profile } from "@/lib/api/account";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_LEGAL_DOCS } from "@/mocks/fixtures/account";
import { accountApi } from "@/lib/api/account";
import { createAccountStore } from "@/stores/account";
import type { AccountStore } from "@/stores/account";
import { AccountModal, openAccountModal } from "./AccountModal";
import * as copy from "./copy";
import { HEALTH_CONSENT_REQUIRED_FALLBACK } from "./copy";
import { failureMessage } from "./parts";
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

function setup(store: AccountStore = createAccountStore()) {
  const user = userEvent.setup();
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
  await user.click(check("privacy_consent"));
  if (health) await user.click(check("sensitive_consent"));
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
    expect(store.getState()).toMatchObject({ status: "member", me: { onboarding_step: "consent" } });
  });

  it("소셜 로그인 콜백이 실패해 돌아오면 로그인 화면에 고정 문구로 안내한다(이메일 없는 카카오계정, BE-11-16 B)", async () => {
    const { store } = setup();
    store.getState().failLogin("OAUTH_EMAIL_REQUIRED");
    await screen.findByTestId("account-modal");
    expect(step()).toBe("login");
    expect(screen.getByTestId("account-error")).toHaveTextContent("카카오계정에 이메일이 없거나 동의하지 않으면 로그인할 수 없어요. 다른 방법으로 로그인하거나 로그인 없이 쓰세요.");
    expect(screen.getByTestId("account-error")).toHaveTextContent(copy.ERROR_OAUTH_EMAIL_REQUIRED);
    // 다른 길이 그대로 열려 있다: 이메일·Google·로그인 없이 계속하기
    expect(screen.getByRole("button", { name: "Google로 계속하기" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "로그인 없이 계속하기" })).toBeEnabled();
    store.getState().failLogin("OAUTH_FAILED");
    await waitFor(() => expect(screen.getByTestId("account-error")).toHaveTextContent(copy.ERROR_OAUTH_FAILED));
  });

  it("가입 뒤 이메일 확인이 필요하면 가입 화면에 안내 한 줄이 보이고 로그인 상태가 되지 않는다", async () => {
    const { user, store } = setup(createAccountStore({ api: { ...accountApi, signupWithEmail: async () => "confirm_email" } }));
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "이메일로 가입하기" }));
    await user.type(screen.getByLabelText("이메일"), "user@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "pw-1234");
    await user.click(screen.getByRole("button", { name: "가입하기" }));
    expect(await screen.findByTestId("signup-confirm-notice")).toHaveTextContent(copy.SIGNUP_CONFIRM_NOTICE);
    expect(screen.getByTestId("signup-confirm-notice")).toHaveAttribute("role", "status");
    expect(step()).toBe("signup");
    expect(store.getState().status).toBe("guest");
    await user.click(screen.getByRole("button", { name: "뒤로" }));
    expect(screen.queryByTestId("signup-confirm-notice")).toBeNull();
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
  it("문서 제목·본문은 API 값 그대로이고 필수·선택·안내 표지와 버전·시행일, '초안·법률 검토 전' 표지가 붙는다", async () => {
    const { user } = setup();
    await login(user);
    const tags = { terms: "필수", privacy_policy: "안내", privacy_consent: "필수", sensitive_consent: "선택" } as const;
    for (const doc of Object.values(MOCK_LEGAL_DOCS)) {
      const item = docItem(doc.doc_type);
      expect(item).toHaveAttribute("data-required", String(doc.required));
      expect(within(item).getByRole("heading", { level: 3 })).toHaveTextContent(`[${tags[doc.doc_type]}] ${doc.title}`);
      expect(item).toHaveTextContent("버전 1 · 시행일 2026-11-18"); // 버전은 정수, 시행일은 일시의 날짜 부분
      expect(within(item).getByTestId("legal-not-reviewed")).toHaveTextContent("초안·법률 검토 전"); // legal_review: not_reviewed
    }
    expect(docItem("terms")).toHaveTextContent("이 문서는 화면 개발용 합성 목 문서이며 실제 약관이 아닙니다.");
    // 외부 AI 전송 고지: 화면이 기존 시작 화면 고지 문구를 한 번 더 넣지 않는다(문서 본문은 서버 값뿐이다)
    expect(modal().textContent).not.toContain(START_EXTERNAL_AI_NOTICE);
    expect(MOCK_LEGAL_DOCS.privacy_policy.body_md).not.toContain(START_EXTERNAL_AI_NOTICE);
  });

  it("법률 검토를 마친 문서(legal_review: reviewed)에는 '초안·법률 검토 전' 표지가 없다", async () => {
    server.use(http.get("*/api/legal/terms", () => HttpResponse.json({ ...MOCK_LEGAL_DOCS.terms, legal_review: "reviewed" })));
    const { user } = setup();
    await login(user);
    expect(within(docItem("terms")).queryByTestId("legal-not-reviewed")).toBeNull();
    expect(within(docItem("privacy_consent")).getByTestId("legal-not-reviewed")).toBeInTheDocument();
  });

  it("고지 문서(외부 AI 전송 안내가 든 처리방침)는 체크 없는 고지로만 보이고 동의 항목에 들어가지 않는다(FE-04-03 A)", async () => {
    const bodies: unknown[] = [];
    const { user } = setup();
    await login(user);
    const notice = docItem("privacy_policy");
    expect(notice).toHaveAttribute("data-consent", "false");
    expect(within(notice).queryByRole("checkbox")).toBeNull();
    expect(notice).toHaveTextContent("외부 AI 전송"); // 본문(서버 값)은 그대로 읽을 수 있다
    expect(within(modal()).getAllByRole("checkbox")).toHaveLength(3); // 동의 대상은 약관·개인정보·건강 정보 셋뿐
    expect(modal().querySelector('[data-doc-type="external_ai"]')).toBeNull();
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/consents")) bodies.push(await request.clone().json());
    });
    await consent(user, { health: true });
    server.events.removeAllListeners();
    expect(bodies).toEqual([
      {
        channel: "onboarding",
        items: [
          { doc_type: "terms", version: 1, action: "agree" },
          { doc_type: "privacy_consent", version: 1, action: "agree" },
          { doc_type: "sensitive_consent", version: 1, action: "agree" },
        ],
      },
    ]);
  });

  it("필수 두 문서에 모두 동의하기 전에는 다음 버튼이 비활성이고 이유가 보인다", async () => {
    const { user } = setup();
    await login(user);
    const submit = screen.getByTestId("consent-submit");
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("consent-hint")).toBeVisible();
    await user.click(check("terms"));
    await user.click(check("sensitive_consent"));
    expect(submit).toBeDisabled(); // 선택만으로는 안 된다
    await user.click(check("privacy_consent"));
    expect(submit).toBeEnabled();
    expect(screen.queryByTestId("consent-hint")).toBeNull();
    await user.click(check("terms"));
    expect(submit).toBeDisabled();
  });

  it("동의해 둔 건강 정보 동의를 끄면 삭제 경고가 보이고, 확인 모달을 거쳐야 철회되어 건강 정보가 지워진다(FE-04-06 A)", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: true });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByRole("button", { name: "동의 내용 보기" }));
    await waitFor(() => expect(step()).toBe("consent"));
    for (const docType of ["terms", "privacy_consent", "sensitive_consent"]) expect(check(docType)).toBeChecked(); // 지금 동의 상태가 채워져 있다
    expect(screen.queryByTestId("health-withdraw-warning")).toBeNull();
    await user.click(check("sensitive_consent"));
    expect(screen.getByTestId("health-withdraw-warning")).toHaveTextContent(copy.HEALTH_WITHDRAW_WARNING);
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/consents")) requests.push(request.url);
    });
    // 누르면 바로 보내지 않고 확인 모달이 뜬다(삭제·탈퇴와 같은 패턴: alertdialog, 취소가 먼저, 되돌릴 수 없음 명시)
    await user.click(screen.getByTestId("consent-submit"));
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog).toHaveAttribute("role", "alertdialog");
    expect(dialog).toHaveAccessibleName("건강 정보 동의를 철회할까요?");
    expect(dialog).toHaveTextContent("저장해 둔 임신 여부와 복용 중인 약이 바로 삭제되고 되돌릴 수 없어요.");
    expect(within(dialog).getAllByRole("button").map((button) => button.textContent)).toEqual(["취소", "철회하기"]);
    // 취소하면 아무것도 보내지 않고 동의 화면에 그대로 있다(건강 정보도 그대로)
    await user.click(within(dialog).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(screen.queryByTestId("confirm-dialog")).toBeNull());
    expect(step()).toBe("consent");
    expect(requests).toEqual([]);
    expect(store.getState().me?.health_consent_active).toBe(true);
    expect(store.getState().profiles[0]).toMatchObject({ pregnancy_status: "pregnant" });
    // 확인하면 철회된다
    await user.click(screen.getByTestId("consent-submit"));
    await user.click(within(screen.getByTestId("confirm-dialog")).getByRole("button", { name: "철회하기" }));
    await waitFor(() => expect(step()).toBe("profiles"));
    server.events.removeAllListeners();
    expect(requests).toHaveLength(1);
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
    expect(store.getState().me?.health_consent_active).toBe(false);
    expect(store.getState().profiles[0]).toMatchObject({ label: "나", pregnancy_status: null, medications: [] });
    expect(screen.getByTestId("health-consent-notice")).toBeVisible();
  });

  it("철회가 섞이지 않은 동의(새로 동의·그대로)는 확인 모달 없이 보낸다", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByRole("button", { name: "동의 내용 보기" }));
    await waitFor(() => expect(step()).toBe("consent"));
    await user.click(check("sensitive_consent")); // 새로 동의
    await user.click(screen.getByTestId("consent-submit"));
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
    await waitFor(() => expect(step()).toBe("profiles"));
  });

  it("동의 화면의 `<`는 로그인으로 돌아간다", async () => {
    const { user } = setup();
    await login(user);
    await user.click(screen.getByRole("button", { name: "뒤로" }));
    expect(step()).toBe("login");
  });
});

describe("프로필 화면", () => {
  it("건강 정보 동의가 없으면 임신 여부·복용 약 칸이 비활성이고 이유 한 줄이 보인다. 저장 요청에 건강 칸을 싣지 않는다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-family"));
    expect(step()).toBe("profile-form");
    expect(screen.getByTestId("health-fields")).toBeDisabled();
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
    expect(screen.getByLabelText("복용 중인 약(선택)")).toBeDisabled();
    expect(screen.getByTestId("medication-add")).toBeDisabled();
    expect(screen.getByTestId("health-consent-notice")).toHaveTextContent(HEALTH_CONSENT_REQUIRED_FALLBACK);
    // 저장해도 건강 정보는 가지 않는다(서버가 422로 막지 않는다 = 건강 칸이 요청에 없다)
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    expect(within(screen.getByLabelText("연령대")).getAllByRole("option").map((option) => option.textContent)).toEqual(["선택 안 함", ...Object.values(copy.AGE_BAND_LABELS)]);
    await user.selectOptions(screen.getByLabelText("연령대"), "y6_11");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles).toEqual([expect.objectContaining({ label: "첫째", relation: "child", age_band: "y6_11", pregnancy_status: null, medications: [] })]);
  });

  it("건강 정보 동의가 있으면 임신 여부·복용 약(입력 원문)을 넣어 저장하고, 수정·삭제할 수 있다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: true });
    expect(screen.queryByTestId("health-consent-notice")).toBeNull();
    await user.click(screen.getByTestId("add-self"));
    expect(screen.getByLabelText("관계")).toBeDisabled(); // 본인은 관계 고정
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("연령대"), "y19_64");
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.type(screen.getByLabelText("복용 중인 약(선택)"), "가나다정 100밀리그램{Enter}");
    expect(step()).toBe("profile-form"); // Enter는 저장이 아니라 약 추가
    expect(screen.getAllByTestId("medication")).toHaveLength(1);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ relation: "self", label: "나", pregnancy_status: "pregnant", medications: [{ input_text: "가나다정 100밀리그램", item_seq: null }] });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("본인 · 만 19~64세 · 임신 여부 예 · 약 1개");
    expect(screen.queryByTestId("add-self")).toBeNull(); // 본인은 1개
    // 수정
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(screen.getByRole("button", { name: "뒤로" })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("이름(별명)"));
    await user.type(screen.getByLabelText("이름(별명)"), "본인");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(screen.getByTestId("profile-item")).toHaveTextContent("본인"));
    expect(store.getState().profiles[0]).toMatchObject({ label: "본인", pregnancy_status: "pregnant", medications: [{ input_text: "가나다정 100밀리그램" }] }); // 수정해도 건강 정보는 그대로
    // 본인 프로필에는 삭제 버튼이 없다(서버 409 SELF_REQUIRED. 계정을 지우려면 탈퇴)
    expect(screen.queryByRole("button", { name: "본인 삭제" })).toBeNull();
    // 가족 프로필은 삭제할 수 있다(확인 모달)
    await user.click(screen.getByTestId("add-family"));
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(screen.getAllByTestId("profile-item")).toHaveLength(2));
    await user.click(screen.getByRole("button", { name: "첫째 삭제" }));
    await user.click(within(screen.getByTestId("confirm-dialog")).getByTestId("confirm-action"));
    await waitFor(() => expect(store.getState().profiles.map((profile) => profile.label)).toEqual(["본인"]));
  });

  it("저장이 서버 오류로 막히면 폼에 남고 코드에 맞는 문구가 보인다(501·503·422)", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: true });
    await user.click(screen.getByTestId("add-family"));
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    for (const [status, code, text] of [
      [501, "NOT_IMPLEMENTED", copy.ERROR_NOT_IMPLEMENTED],
      [503, "ACCOUNT_UNAVAILABLE", copy.ERROR_ACCOUNT_UNAVAILABLE],
      [422, "HEALTH_CONSENT_REQUIRED", copy.HEALTH_CONSENT_REQUIRED_FALLBACK],
    ] as const) {
      server.use(http.post("*/api/profiles", () => HttpResponse.json({ code, fields: [] }, { status })));
      await user.click(screen.getByTestId("profile-save"));
      await waitFor(() => expect(screen.getByTestId("account-error")).toHaveTextContent(text));
      expect(step()).toBe("profile-form");
    }
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

  it("로그인은 했지만 계정 서버가 준비 전(501)이면 준비 중 안내와 로그아웃만 보인다(추가·동의·탈퇴 버튼 없음)", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 })));
    const store = createAccountStore({ api: { ...accountApi, hasSession: async () => true } });
    const { user } = setup(store);
    await store.getState().bootstrap();
    expect(store.getState()).toMatchObject({ status: "member", me: null });
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    expect(step()).toBe("profiles");
    expect(screen.getByTestId("account-unavailable")).toHaveTextContent(copy.ERROR_NOT_IMPLEMENTED);
    for (const testId of ["add-self", "add-family", "withdraw", "health-consent-notice", "account-error"]) expect(screen.queryByTestId(testId), testId).toBeNull();
    expect(screen.queryByRole("button", { name: "동의 내용 보기" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "로그아웃" }));
    await waitFor(() => expect(store.getState().status).toBe("guest"));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
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

describe("오류 코드 → 화면 문구(서버는 문구를 주지 않는다: {code, fields})", () => {
  const failure = (status: number, code: string | null) => ({ kind: "http", status, code, fields: [] }) as const;

  it.each([
    [422, "HEALTH_CONSENT_REQUIRED", copy.HEALTH_CONSENT_REQUIRED_FALLBACK],
    [422, "PROFILE_LIMIT", copy.ERROR_PROFILE_LIMIT],
    [422, "MEDICATION_LIMIT", copy.ERROR_MEDICATION_LIMIT],
    [422, "INVALID_REQUEST", copy.ERROR_INVALID_REQUEST],
    [409, "SELF_REQUIRED", copy.ERROR_SELF_REQUIRED],
    [409, "SELF_EXISTS", copy.ERROR_SELF_EXISTS],
    [409, "SELF_FIXED", copy.ERROR_SELF_FIXED],
    [409, "VERSION_MISMATCH", copy.ERROR_VERSION_MISMATCH],
    [409, "USE_ACCOUNT_DELETE", copy.ERROR_USE_ACCOUNT_DELETE],
    [403, "CONSENT_REQUIRED", copy.ERROR_REQUIRED_CONSENT],
    [403, "RECONSENT_REQUIRED", copy.ERROR_RECONSENT_REQUIRED],
    [404, "NOT_FOUND", copy.ERROR_NOT_FOUND],
    [401, "AUTH_REQUIRED", copy.ERROR_AUTH_REQUIRED],
    [401, "AUTH_INVALID", copy.ERROR_AUTH_REQUIRED],
    [501, "NOT_IMPLEMENTED", copy.ERROR_NOT_IMPLEMENTED],
    [503, "AUTH_UNAVAILABLE", copy.ERROR_AUTH_UNAVAILABLE],
    [503, "ACCOUNT_UNAVAILABLE", copy.ERROR_ACCOUNT_UNAVAILABLE],
    // 로그인·가입·소셜 콜백(백엔드 코드가 아니다)
    [400, "INVALID_CREDENTIALS", copy.ERROR_INVALID_CREDENTIALS],
    [400, "EMAIL_NOT_CONFIRMED", copy.ERROR_EMAIL_NOT_CONFIRMED],
    [422, "EMAIL_TAKEN", copy.ERROR_EMAIL_TAKEN],
    [422, "WEAK_PASSWORD", copy.ERROR_WEAK_PASSWORD],
    [429, "EMAIL_SEND_FAILED", copy.ERROR_EMAIL_SEND_FAILED],
    [429, "AUTH_RATE_LIMITED", copy.ERROR_AUTH_RATE_LIMITED],
    [500, "AUTH_FAILED", copy.ERROR_AUTH_FAILED],
    [400, "OAUTH_EMAIL_REQUIRED", copy.ERROR_OAUTH_EMAIL_REQUIRED],
    [400, "OAUTH_FAILED", copy.ERROR_OAUTH_FAILED],
  ])("%i %s", (status, code, text) => {
    expect(failureMessage(failure(status, code))).toBe(text);
    expect(text.length).toBeGreaterThan(0);
  });

  it("코드가 없거나 모르는 코드면 상태 코드로 고르고, 그것도 없으면 일반 문구다. 네트워크 실패는 따로다", () => {
    expect(failureMessage(failure(501, null))).toBe(copy.ERROR_NOT_IMPLEMENTED);
    expect(failureMessage(failure(503, "SOMETHING_NEW"))).toBe(copy.ERROR_ACCOUNT_UNAVAILABLE);
    expect(failureMessage(failure(401, null))).toBe(copy.ERROR_AUTH_REQUIRED);
    expect(failureMessage(failure(500, "INTERNAL"))).toBe(copy.ERROR_GENERIC);
    expect(failureMessage({ kind: "network", status: 0, code: null, fields: [] })).toBe(copy.ERROR_NETWORK);
  });

  it("오류 문구는 금기·안전을 말하지 않고 119 외 연락처를 넣지 않는다", () => {
    const texts = Object.entries(copy).filter(([name, value]) => name.startsWith("ERROR_") && typeof value === "string").map(([, value]) => value as string);
    expect(texts.length).toBeGreaterThanOrEqual(15);
    for (const text of texts) expect(text).not.toMatch(/안전|괜찮|먹어도|\d{2,4}-\d{3,4}/);
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

  it("계정 코드(화면·스토어·API·로그인 모듈)는 브라우저 저장소·쿠키·persist를 직접 쓰지 않고, 화면·스토어는 Supabase 클라이언트를 직접 쓰지 않는다", () => {
    const src = path.resolve(__dirname, "../..");
    const strip = (file: string) => readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ""); // 주석 제외
    // 화면·스토어: 로그인은 `lib/api/account.ts`의 함수로만 한다
    const screens = [
      ...readdirSync(__dirname).filter((name) => /\.tsx?$/.test(name) && !name.includes(".test.")).map((name) => path.join(__dirname, name)),
      path.join(src, "stores/account.ts"),
      path.join(src, "stores/profile-context.ts"),
    ];
    expect(screens.length).toBeGreaterThanOrEqual(11);
    for (const file of screens) expect(strip(file), file).not.toMatch(/supabase/i);
    // 로그인 연결 모듈까지: 세션 쿠키는 `@supabase/ssr`의 기본 동작에만 맡기고 프런트 코드가 저장소·쿠키·콘솔에 직접 쓰지 않는다
    const supabaseDir = path.join(src, "lib/supabase");
    const all = [
      ...screens,
      path.join(src, "lib/api/account.ts"),
      path.join(src, "lib/api/auth.ts"),
      path.join(src, "app/auth/callback/route.ts"),
      ...readdirSync(supabaseDir).filter((name) => !name.includes(".test.")).map((name) => path.join(supabaseDir, name)),
    ];
    expect(all.length).toBeGreaterThanOrEqual(18);
    for (const file of all) expect(strip(file), file).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie|zustand\/middleware|console\.|readUiSetting|writeUiSetting/i);
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

  it("게스트는 '로그인/가입', 로그인하면 상태 글자·프로필 관리·로그아웃(서버는 이름·이메일을 주지 않는다)", () => {
    const { rerender } = render(<AccountMenu member={false} onOpen={() => {}} onLogout={() => {}} />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["로그인/가입"]);
    rerender(<AccountMenu member onOpen={() => {}} onLogout={() => {}} />);
    expect(screen.getByTestId("account-name")).toHaveTextContent("로그인됨");
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["프로필 관리", "로그아웃"]);
  });
});

describe("대상 선택 '누가 먹나요'", () => {
  it("프로필마다 고를 수 있고 '선택 안 함'으로 되돌린다", async () => {
    const onChange = vi.fn();
    const profiles: Profile[] = [
      { profile_id: "a", relation: "self", label: "나", age_band: "y19_64", pregnancy_status: null, sort_order: 0, medications: [] },
      { profile_id: "b", relation: "child", label: "첫째", age_band: "y6_11", pregnancy_status: null, sort_order: 1, medications: [] },
    ];
    const { rerender } = render(<TargetPicker profiles={profiles} value={null} onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "누가 먹나요" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio").map((radio) => radio.closest("label")?.textContent)).toEqual(["선택 안 함", "나", "첫째"]);
    expect(screen.getByRole("radio", { name: "선택 안 함" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "첫째" }));
    expect(onChange).toHaveBeenLastCalledWith("b");
    rerender(<TargetPicker profiles={profiles} value="b" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "첫째" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "선택 안 함" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("별명이 없는 프로필(서버는 label null을 허용한다)은 관계 글자로 보인다", () => {
    render(<TargetPicker profiles={[{ profile_id: "c", relation: "parent", label: null, age_band: null, pregnancy_status: null, sort_order: 0, medications: [] }]} value={null} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "부모" })).toBeInTheDocument();
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
