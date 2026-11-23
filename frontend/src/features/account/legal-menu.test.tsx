import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchLegalDocIfPublished } from "@/lib/api/account";
import { LegalDialog } from "./LegalDialog";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_GUEST_LEGAL_DOCS, MOCK_LEGAL_DOCS } from "@/mocks/fixtures/account";
import { LegalDocsSection } from "./LegalDocsSection";
import { LEGAL_MENU, fetchLegalMenu, legalMenuDocTypes } from "./legal-menu";

// 약관·정책 열람(2026-11-23): 게스트/회원 목록 매핑 한 곳, 서버에 없는 문서는 숨김, 읽기 전용(동의 호출 0), 펼침·접힘·초점.
const server = setupServer();
const consentCalls = vi.fn();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
beforeEach(() => {
  server.use(
    ...createAccountHandlers(),
    http.post("*/api/consents", () => {
      consentCalls();
      return HttpResponse.json({ code: "AUTH_REQUIRED", fields: [] }, { status: 401 });
    }),
  );
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }));
  consentCalls.mockClear();
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
afterAll(() => server.close());

const items = () => screen.getAllByTestId("legal-menu-item").map((item) => item.dataset.docType);
/** 항목 버튼(접근 가능한 이름은 서버 제목으로 시작하고 버전 줄이 이어진다) */
const itemButton = (title: string) => screen.getByRole("button", { name: (name) => name.startsWith(title) });

describe("legal-menu 매핑", () => {
  it("게스트 목록과 회원 목록이 다르고, 회원용 동의서는 게스트에게 없다", () => {
    expect(legalMenuDocTypes(false)).toEqual(["terms_guest", "terms", "privacy_policy"]);
    // 처리방침은 게스트용을 따로 두지 않는다(PRD-17-23 A)
    expect(LEGAL_MENU.find((entry) => entry.docType === "privacy_policy")?.audience).toBe("all");
    expect(legalMenuDocTypes(true)).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"]);
    // 문서 제목·본문은 매핑에 없다(서버 값만 그린다)
    for (const entry of LEGAL_MENU) expect(Object.keys(entry)).toEqual(["docType", "audience"]);
  });

  it("서버가 모르는 종류(422)·게시본 없음(404)은 null이고, 그 밖의 실패는 던진다", async () => {
    expect(await fetchLegalDocIfPublished("no_such_doc")).toBeNull();
    server.use(http.get("*/api/legal/terms", () => HttpResponse.json({ code: "NOT_FOUND", fields: [] }, { status: 404 })));
    expect(await fetchLegalDocIfPublished("terms")).toBeNull();
    server.use(http.get("*/api/legal/privacy_policy", () => HttpResponse.json({ code: "ACCOUNT_UNAVAILABLE", fields: [] }, { status: 503 })));
    await expect(fetchLegalDocIfPublished("privacy_policy")).rejects.toMatchObject({ status: 503 });
    await expect(fetchLegalMenu(false)).rejects.toMatchObject({ status: 503 });
  });

  it("게스트 목록은 목에 있는 게스트 문서 + 공통 문서이고 없는 종류는 빠진다(순서 유지)", async () => {
    expect((await fetchLegalMenu(false)).map((doc) => doc.doc_type)).toEqual(["terms_guest", "terms", "privacy_policy"]);
    // 실서버처럼 `terms_guest`가 아직 없으면(404) 공통 2종만 남는다
    server.use(http.get("*/api/legal/terms_guest", () => HttpResponse.json({ code: "NOT_FOUND", fields: [] }, { status: 404 })));
    expect((await fetchLegalMenu(false)).map((doc) => doc.doc_type)).toEqual(["terms", "privacy_policy"]);
    expect((await fetchLegalMenu(true)).map((doc) => doc.doc_type)).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"]);
  });
});

describe("LegalDocsSection", () => {
  it("게스트: 서버 제목 그대로 목록, 누르면 펼쳐지고 본문 상자가 초점을 받으며 동의 호출이 없다", async () => {
    const user = userEvent.setup();
    render(<LegalDocsSection member={false} />);
    expect(screen.getByRole("heading", { name: "약관·정책" })).toBeInTheDocument();
    await waitFor(() => expect(items()).toEqual(["terms_guest", "terms", "privacy_policy"]));
    // 항목 이름은 서버 제목 그대로, 체크박스는 없다(읽기 전용)
    const guestButton = itemButton(MOCK_GUEST_LEGAL_DOCS.terms_guest.title);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(guestButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("legal-menu-body")).toBeNull();
    await user.click(guestButton);
    expect(guestButton).toHaveAttribute("aria-expanded", "true");
    const body = screen.getByRole("group", { name: MOCK_GUEST_LEGAL_DOCS.terms_guest.title });
    expect(body).toHaveAttribute("id", guestButton.getAttribute("aria-controls"));
    expect(body).toHaveAttribute("tabindex", "0");
    expect(within(body).getByText("제1조 (게스트 이용)")).toBeInTheDocument();
    // 다른 항목을 열면 앞 항목은 접힌다(한 번에 하나)
    await user.click(itemButton(MOCK_LEGAL_DOCS.terms.title));
    expect(guestButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByTestId("legal-menu-body")).toHaveLength(1);
    expect(consentCalls).not.toHaveBeenCalled();
  });

  it("회원: 동의서·만 14세 문서까지 보이고 버전 줄과 법률 검토 전 표지가 있다", async () => {
    render(<LegalDocsSection member />);
    await waitFor(() => expect(items()).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"]));
    for (const item of screen.getAllByTestId("legal-menu-item")) expect(item).toHaveTextContent("버전 1 · 시행일 2026-11-18 · 초안·법률 검토 전");
    expect(screen.getAllByTestId("legal-not-reviewed")).toHaveLength(5);
  });

  it("서버가 없다고 하는 종류(404)는 항목이 아예 없고 안내 글자도 없다", async () => {
    server.use(http.get("*/api/legal/sensitive_consent", () => HttpResponse.json({ code: "NOT_FOUND", fields: [] }, { status: 404 })));
    render(<LegalDocsSection member />);
    await waitFor(() => expect(items()).toEqual(["terms", "privacy_policy", "privacy_consent", "age_14"]));
    expect(screen.queryByText(/준비 중/)).toBeNull();
  });

  it("목 상태 `missingLegal`로 게스트용 문서가 없으면 게스트 목록은 공통 2종만이다", async () => {
    server.use(...createAccountHandlers({ session: null, missingLegal: ["terms_guest"] }));
    render(<LegalDocsSection member={false} />);
    await waitFor(() => expect(items()).toEqual(["terms", "privacy_policy"]));
    expect(screen.queryByText(/준비 중/)).toBeNull();
  });

  it("모든 문서가 없으면 묶음 자체를 그리지 않는다", async () => {
    render(<LegalDocsSection member={false} load={async () => []} />);
    await waitFor(() => expect(screen.queryByTestId("legal-menu")).toBeNull());
  });

  it("불러오기 실패면 한 줄과 다시 불러오기를 보이고, 다시 누르면 받는다", async () => {
    const user = userEvent.setup();
    let fail = true;
    server.use(http.get("*/api/legal/terms", () => (fail ? HttpResponse.json({ code: "ACCOUNT_UNAVAILABLE", fields: [] }, { status: 503 }) : HttpResponse.json(MOCK_LEGAL_DOCS.terms))));
    render(<LegalDocsSection member={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("문서를 불러오지 못했어요.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "다시 불러오기" }));
    await waitFor(() => expect(items()).toContain("terms"));
  });
});

describe("약관·정책 열람 화면(계정 메뉴 항목에서 연다)", () => {
  it("게스트: 제목 '약관·정책' 하나(안쪽 제목 중복 없음)에 초점이 가고, 게스트 목록을 보인다. 체크박스·제출 없음", async () => {
    render(<LegalDialog open onOpenChange={() => {}} member={false} />);
    const dialog = screen.getByTestId("legal-dialog");
    const title = within(dialog).getByRole("heading", { name: "약관·정책" });
    await waitFor(() => expect(title).toHaveFocus());
    expect(within(dialog).getAllByRole("heading")).toHaveLength(1);
    expect(within(dialog).getByTestId("legal-menu")).toHaveAttribute("aria-labelledby", title.id);
    await waitFor(() => expect(items()).toEqual(["terms_guest", "terms", "privacy_policy"]));
    expect(within(dialog).queryAllByRole("checkbox")).toHaveLength(0);
    expect(consentCalls).not.toHaveBeenCalled();
  });

  it("회원: 회원 목록 5종이고, 닫기 버튼으로 닫힌다", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<LegalDialog open onOpenChange={onOpenChange} member />);
    await waitFor(() => expect(items()).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"]));
    expect(screen.getByTestId("legal-menu")).toHaveAttribute("data-audience", "member");
    await user.click(screen.getByRole("button", { name: "닫기" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
