import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { INPUT_NOTICE } from "@/features/chat/copy";
import type { Profile } from "@/lib/api/account";
import { createAccountHandlers } from "@/mocks/account-handlers";
import { MOCK_DRUG_DICT, MOCK_KAKAO_NICKNAME, MOCK_LEGAL_DOCS, searchMockDrugs } from "@/mocks/fixtures/account";
import { createPhotoHandlers } from "@/mocks/photo-handlers";
import { PHOTO_EXTERNAL_AI_NOTICE, PHOTO_PRIVACY_NOTICE } from "@/features/photo/copy";
import { mergeMedications } from "./ProfileForm";

// 사진 등록(FE-04-27 A) 시험: jsdom에는 canvas가 없어 사진 준비(`prepareImage`)만 합성 data URL로 바꿔 끼운다(실제 사진 0). 그 밖은 실제 모듈 그대로
vi.mock("@/features/photo/image", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/photo/image")>()),
  prepareImage: async () => ({ dataUrl: "data:image/png;base64,iVBORw0KGgo=", width: 10, height: 10, resized: false, bytes: 8 }),
}));
import { AVATAR_COLORS, AccountApiError, DRUG_CANDIDATES_MAX, MEDICATIONS_MAX, accountApi, searchDrugs } from "@/lib/api/account";
import { createAccountStore } from "@/stores/account";
import type { AccountStore } from "@/stores/account";
import { AccountModal, openAccountModal } from "./AccountModal";
import * as copy from "./copy";
import { HEALTH_CONSENT_REQUIRED_FALLBACK } from "./copy";
import { failureMessage } from "./parts";
import { AccountMenu } from "./AccountMenu";
import { EntryChoice } from "./EntryChoice";
import { Markdown, parseMarkdown } from "./Markdown";
import { MEDICATION_SEARCH_DEBOUNCE_MS } from "./MedicationPicker";
import { TargetChip } from "./TargetMenu";
import { suggestAvatarColor } from "./ProfileForm";

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
      <AccountModal store={store} />
    </>,
  );
  return { user, store };
}

async function login(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "프로필 저장" }));
  // S1 로그인은 소셜만이다(PRD-01-10 A). 목은 페이지를 옮기지 않고 목 세션만 만든다.
  // 공용 로그인은 Google이다: 카카오로 들어오면 본인 프로필 이름 칸에 닉네임이 미리 들어가(FE-04-28 B) 이름을 적는 시험이 달라진다. 카카오 초기값은 아래 전용 describe가 본다
  await user.click(screen.getByRole("button", { name: "Google로 계속하기" }));
  await waitFor(() => expect(step()).toBe("consent"));
  await waitFor(() => expect(modal().querySelectorAll('[data-testid="legal-doc"]')).toHaveLength(4));
}

/** 필수 동의 셋(약관·개인정보·만 14세 확인)을 체크하고 넘어간다. `health`면 건강 정보 동의도 */
async function consent(user: ReturnType<typeof userEvent.setup>, { health }: { health: boolean }) {
  await user.click(check("terms"));
  await user.click(check("privacy_consent"));
  await user.click(check("age_14"));
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
    // 119 진입점은 머리줄·응급 배너 두 곳뿐이다(FE-17 U-04): 모달 안에는 없다
    expect(modal().querySelector('a[href="tel:119"]')).toBeNull();
  });

  // 사양 변경(PRD-01-10 A): 가입 화면이 화면에서 빠져, `<`가 생기는 첫 단계인 동의 화면에서 같은 배치를 본다
  it("동의 화면에서는 `<`가 생기고 누르면 로그인으로 돌아간다. 코너 버튼은 같은 높이의 absolute다", async () => {
    const { user } = setup();
    await login(user);
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
  // 사양 변경(사용자 지시 2026-11-19 FE-04e): 로고만 있던 버튼 → 가로로 꽉 찬 "공식 로고 + 글자" 버튼. Naver는 화면에 없다(S2에서 다시)
  it("Google·Kakao는 공식 로고 + 글자 버튼이고 이름은 보이는 글자가 준다. Naver·Apple은 없다", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    // 제목은 "간편 로그인"(FE-04-17 A, 2026-11-19). 이전 글자 "다른 방법으로 로그인"은 남지 않는다
    const group = screen.getByRole("group", { name: "간편 로그인" });
    expect(modal().textContent).not.toContain("다른 방법으로 로그인");
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("data-testid"))).toEqual(["social-google", "social-kakao"]);
    expect(screen.getByRole("button", { name: "Google로 계속하기" })).toBe(screen.getByTestId("social-google"));
    expect(screen.getByRole("button", { name: "카카오 로그인" })).toBe(screen.getByTestId("social-kakao"));
    for (const [button, file, text] of [
      [buttons[0], "/social/google-g-logo.svg", "Google로 계속하기"],
      [buttons[1], "/social/kakao-symbol.svg", "카카오 로그인"],
    ] as const) {
      expect(button).toBeEnabled();
      expect(button).toHaveTextContent(text); // 글자가 보인다
      expect(button).not.toHaveAttribute("aria-label"); // 이름은 보이는 글자 하나뿐이다
      expect(button.className).toContain("min-h-12"); // 높이 44px 이상(48px)
      expect(button.className).toContain("w-full"); // 가로로 꽉 찬다
      const image = button.querySelector("img")!;
      expect(image).toHaveAttribute("alt", ""); // 장식: 이름이 두 번 읽히지 않는다
      expect(image.getAttribute("src")).toContain(file);
      expect(image).toHaveAttribute("width", "18"); // 로고 18~20px, 1:1
      expect(image).toHaveAttribute("height", "18");
      expect(button.firstElementChild).toBe(image); // 로고가 글자 앞이다
    }
    // 회사 가이드 색: Google 흰 바탕·테두리, Kakao 노랑 컨테이너
    expect(buttons[0].className).toContain("social-face-google");
    expect(buttons[1].className).toContain("social-face-kakao");
    expect(buttons[1].className).toContain("rounded-xl"); // 카카오 컨테이너 모서리 12px
    expect(group.className).toContain("flex-col"); // 세로 목록
    expect(screen.queryByTestId("social-naver")).toBeNull();
    expect(modal().textContent).not.toMatch(/네이버|naver|준비 중|apple|애플/i);
    expect(within(group).queryByTestId("mascot")).toBeNull(); // 마스코트는 이 영역에 쓰지 않는다
  });

  // 사양 변경(PRD-01-10 A, 2026-11-19): 이메일 로그인·가입은 메일 인증을 갖출 때까지 화면에서 닿지 않는다
  it("이메일 로그인·가입은 보이지 않는다. `signup` 단계로 들어와도 로그인 화면이다", async () => {
    const { user, store } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    const hidden = () => {
      expect(screen.queryByTestId("login-form")).toBeNull();
      expect(screen.queryByTestId("signup-form")).toBeNull();
      expect(screen.queryByLabelText("이메일")).toBeNull();
      expect(screen.queryByLabelText("비밀번호")).toBeNull();
      expect(modal().querySelector("input")).toBeNull();
      expect(screen.queryByRole("button", { name: "로그인" })).toBeNull();
      expect(screen.queryByRole("button", { name: "이메일로 가입하기" })).toBeNull();
      expect(screen.queryByRole("button", { name: "가입하기" })).toBeNull();
      expect(modal().textContent).not.toMatch(/이메일로 로그인|이메일로 가입/);
    };
    hidden();
    // 남는 것: 제목·설명·소셜 2개·로그인 없이 계속하기
    expect(within(modal()).getAllByRole("button").map((button) => button.getAttribute("aria-label") ?? button.textContent)).toEqual(["닫기", "Google로 계속하기", "카카오 로그인", "로그인 없이 계속하기"]);
    store.getState().go("signup");
    await waitFor(() => expect(step()).toBe("signup"));
    hidden();
    expect(screen.getByRole("heading", { name: "프로필을 저장하려면 로그인하세요" })).toBeInTheDocument();
    expect(screen.getByTestId("social-google")).toBeEnabled();
  });

  it("처리 중이면 소셜 버튼 두 개가 모두 비활성이다", async () => {
    let finish = () => {};
    const gate = new Promise<void>((resolve) => (finish = resolve));
    const { user } = setup(createAccountStore({ api: { ...accountApi, startSocialLogin: async (provider) => (await gate, accountApi.startSocialLogin(provider)) } }));
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByTestId("social-google"));
    await waitFor(() => expect(screen.getByTestId("social-google")).toBeDisabled());
    expect(screen.getByTestId("social-kakao")).toBeDisabled();
    finish();
    await waitFor(() => expect(step()).toBe("consent"));
  });

  it("소셜 로그인 목 → 로그인 상태가 되고 동의 화면으로 간다", async () => {
    const { user, store } = setup();
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name: "카카오 로그인" }));
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
    // 다른 길이 그대로 열려 있다: Google·로그인 없이 계속하기
    expect(screen.getByRole("button", { name: "Google로 계속하기" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "로그인 없이 계속하기" })).toBeEnabled();
    store.getState().failLogin("OAUTH_FAILED");
    await waitFor(() => expect(screen.getByTestId("account-error")).toHaveTextContent(copy.ERROR_OAUTH_FAILED));
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
    const tags: Readonly<Record<string, string>> = { terms: "필수", privacy_policy: "안내", privacy_consent: "필수", sensitive_consent: "선택" }; // 동의 화면 카드 4종(게스트판 `terms_guest`는 동의 화면에 없다)
    for (const doc of Object.values(MOCK_LEGAL_DOCS)) {
      if (doc.doc_type === "age_14") continue; // 카드가 아니라 별도 체크(아래)
      const item = docItem(doc.doc_type);
      expect(item).toHaveAttribute("data-required", String(doc.required));
      expect(within(item).getByRole("heading", { level: 3 })).toHaveTextContent(`[${tags[doc.doc_type]}] ${doc.title}`);
      expect(item).toHaveTextContent("버전 1 · 시행일 2026-11-18"); // 버전은 정수, 시행일은 일시의 날짜 부분
      expect(within(item).getByTestId("legal-not-reviewed")).toHaveTextContent("초안·법률 검토 전"); // legal_review: not_reviewed
    }
    expect(docItem("terms")).toHaveTextContent("이 문서는 화면 개발용 합성 목 문서이며 실제 약관이 아닙니다.");
    // 만 14세 이상 확인(PRD-17-09 A·12 A): 문서 카드가 아니라 목록 맨 아래의 별도 필수 체크 한 줄이다. 라벨은 화면 상수, 본문·버전 줄은 없다
    const age = screen.getByTestId("age-14-check");
    expect(age).toHaveAttribute("data-doc-type", "age_14");
    expect(age).toHaveAttribute("data-required", "true");
    expect(modal().querySelectorAll('[data-testid="legal-doc"]')).toHaveLength(4);
    expect(within(age).queryByRole("heading")).toBeNull();
    expect(age).not.toHaveTextContent("버전");
    expect(within(age).getByRole("checkbox")).toHaveAccessibleName(`[필수] ${copy.AGE_14_CHECK_LABEL}`);
    expect(copy.AGE_14_CHECK_LABEL).toBe("만 14세 이상입니다.");
    expect(within(age).getByRole("checkbox").closest("label")!.className).toContain("min-h-11"); // 44px 터치 대상
    expect(age.compareDocumentPosition(docItem("sensitive_consent")) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy(); // 문서 카드 뒤
    expect(age.compareDocumentPosition(screen.getByTestId("consent-submit")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // 버튼 앞
    // 외부 AI 전송 고지: 화면이 입력창 고지 문구(시작 화면 고지는 PRD-17-10 A로 삭제)를 동의 창에 한 번 더 넣지 않는다(문서 본문은 서버 값뿐이다)
    expect(modal().textContent).not.toContain(INPUT_NOTICE);
    expect(MOCK_LEGAL_DOCS.privacy_policy.body_md).not.toContain(INPUT_NOTICE);
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
    expect(within(modal()).getAllByRole("checkbox")).toHaveLength(4); // 동의 대상은 약관·개인정보·건강 정보 + 만 14세 확인
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
          { doc_type: "age_14", version: 1, action: "agree" },
        ],
      },
    ]);
  });

  it("필수 두 문서와 만 14세 확인에 모두 동의하기 전에는 다음 버튼이 비활성이고 이유가 보인다", async () => {
    const { user } = setup();
    await login(user);
    const submit = screen.getByTestId("consent-submit");
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("consent-hint")).toBeVisible();
    await user.click(check("terms"));
    await user.click(check("sensitive_consent"));
    expect(submit).toBeDisabled(); // 선택만으로는 안 된다
    await user.click(check("privacy_consent"));
    expect(submit).toBeDisabled(); // 만 14세 확인(age_14)이 빠지면 진행 불가(PRD-17-12 A)
    expect(screen.getByTestId("consent-hint")).toBeVisible();
    await user.click(check("age_14"));
    expect(submit).toBeEnabled();
    expect(screen.queryByTestId("consent-hint")).toBeNull();
    await user.click(check("age_14"));
    expect(submit).toBeDisabled(); // 다시 끄면 막힌다
    await user.click(check("age_14"));
    await user.click(check("terms"));
    expect(submit).toBeDisabled();
  });

  it("만 14세 확인을 체크하지 않으면 동의를 보내지 않고, 체크하면 age_14 동의가 함께 간다. 프로필에서 다시 보면 체크돼 있다", async () => {
    const posts: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/api/consents")) posts.push(await request.clone().json());
    });
    const { user, store } = setup();
    await login(user);
    await user.click(check("terms"));
    await user.click(check("privacy_consent"));
    await user.click(screen.getByTestId("consent-submit")); // 비활성이라 아무 일도 없다
    expect(posts).toEqual([]);
    expect(step()).toBe("consent");
    await user.click(check("age_14"));
    await user.click(screen.getByTestId("consent-submit"));
    await waitFor(() => expect(step()).toBe("profiles"));
    server.events.removeAllListeners();
    expect(posts).toEqual([{ channel: "onboarding", items: [{ doc_type: "terms", version: 1, action: "agree" }, { doc_type: "privacy_consent", version: 1, action: "agree" }, { doc_type: "age_14", version: 1, action: "agree" }] }]);
    expect(store.getState().me?.consents.find((consent) => consent.doc_type === "age_14")).toMatchObject({ required: true, needs_consent: false });
    await user.click(screen.getByRole("button", { name: "동의 내용 보기" }));
    await waitFor(() => expect(step()).toBe("consent"));
    expect(check("age_14")).toBeChecked();
  });

  it("동의해 둔 건강 정보 동의를 끄면 삭제 경고가 보이고, 확인 모달을 거쳐야 철회되어 건강 정보가 지워진다(FE-04-06 A)", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: true });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.selectOptions(screen.getByLabelText("성별"), "female"); // 임신 여부 칸은 여성일 때만 보인다(작업 B)
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByRole("button", { name: "동의 내용 보기" }));
    await waitFor(() => expect(step()).toBe("consent"));
    for (const docType of ["terms", "privacy_consent", "sensitive_consent", "age_14"]) expect(check(docType)).toBeChecked(); // 지금 동의 상태가 채워져 있다
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
    expect(screen.queryByTestId("pregnancy-field")).toBeNull(); // 성별 미입력이라 임신 여부 칸은 없다(작업 B)
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    for (const radio of within(screen.getByTestId("pregnancy-field")).getAllByRole("radio")) expect(radio).toBeDisabled(); // 여성이어도 동의가 없으면 비활성(프로필 색 칸은 건강 정보가 아니라 묶음 밖)
    await user.selectOptions(screen.getByLabelText("성별"), "");
    expect(screen.getByLabelText("복용 중인 약(선택)")).toBeDisabled();
    expect(screen.getByTestId("medication-add")).toBeDisabled();
    expect(screen.getByTestId("health-consent-notice")).toHaveTextContent(HEALTH_CONSENT_REQUIRED_FALLBACK);
    // 저장해도 건강 정보는 가지 않는다(서버가 422로 막지 않는다 = 건강 칸이 요청에 없다)
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    expect(within(screen.getByLabelText("연령대")).getAllByRole("option").map((option) => option.textContent)).toEqual(["선택 안 함", ...Object.values(copy.AGE_BAND_LABELS)]);
    await user.selectOptions(screen.getByLabelText("연령대"), "y6_11");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles).toEqual([expect.objectContaining({ label: "첫째", relation: "child", age_band: "y6_11", sex: null, pregnancy_status: null, medications: [] })]);
  });

  it("프로필 색(2026-11-23): 이름 아래 8색 라디오(이름은 색 이름, 건강 정보 묶음 밖), 새 가족은 아직 안 쓴 색을 제안하고 고른 색이 저장돼 목록 아바타가 그 색이다", async () => {
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-self"));
    const group = screen.getByRole("radiogroup", { name: "프로필 색" });
    expect(screen.getByTestId("health-fields")).not.toContainElement(group);
    expect(within(group).getAllByRole("radio").map((radio) => radio.getAttribute("aria-label"))).toEqual(["노랑", "코랄", "분홍", "보라", "파랑", "청록", "초록", "회색"]);
    expect(within(group).getByRole("radio", { name: "노랑" })).toBeChecked(); // 첫 프로필은 기본색
    for (const option of within(group).getAllByTestId("avatar-color-option")) expect(option.className).toContain("size-11"); // 누르는 영역 44px
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByTestId("add-family"));
    const family = screen.getByRole("radiogroup", { name: "프로필 색" });
    expect(within(family).getByRole("radio", { name: "코랄" })).toBeChecked(); // 노랑은 본인이 쓰고 있다
    await user.click(within(family).getByRole("radio", { name: "보라" }));
    expect(within(family).getByRole("radio", { name: "보라" })).toBeChecked();
    expect(within(family).getByRole("radio", { name: "코랄" })).not.toBeChecked();
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(screen.getAllByTestId("profile-item")).toHaveLength(2));
    expect(store.getState().profiles.map((profile) => profile.avatar_color)).toEqual(["yellow", "purple"]);
    expect(screen.getAllByTestId("profile-item").map((item) => within(item).getByTestId("profile-avatar").getAttribute("data-color"))).toEqual(["yellow", "purple"]);
    // 수정하면 저장된 색이 골라져 있다
    await user.click(screen.getByRole("button", { name: "첫째 수정" }));
    expect(within(screen.getByRole("radiogroup", { name: "프로필 색" })).getByRole("radio", { name: "보라" })).toBeChecked();
  });

  it("성별(선택, FE-11-09 C)은 연령대 아래 기본 칸이다: 처음엔 '선택 안 함'(로그인 정보로 채우지 않음), 건강 정보 동의 없이도 저장·수정·지우기가 되고 목록에 보인다", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.events.on("request:start", async ({ request }) => {
      if ((request.method === "POST" || request.method === "PATCH") && new URL(request.url).pathname.includes("/api/profiles")) bodies.push(await request.clone().json());
    });
    const { user, store } = setup();
    await login(user);
    await consent(user, { health: false }); // 건강 정보 동의 없음
    await user.click(screen.getByTestId("add-self"));
    const sex = screen.getByLabelText("성별");
    expect(sex).toBeEnabled(); // 건강 정보 묶음 밖이다
    expect(screen.getByTestId("health-fields")).not.toContainElement(sex);
    expect(sex).toHaveValue(""); // 간편 로그인 공급자 정보로 미리 채우지 않는다
    expect(within(sex).getAllByRole("option").map((option) => option.textContent)).toEqual(["선택 안 함", "여성", "남성"]);
    expect(within(sex).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual(["", "female", "male"]);
    // 연령대 아래, 건강 정보 묶음 위
    expect(screen.getByLabelText("연령대").compareDocumentPosition(sex) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sex.compareDocumentPosition(screen.getByTestId("health-fields")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 미입력으로 저장
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ sex: null });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("본인");
    expect(screen.getByTestId("profile-item")).not.toHaveTextContent(/여성|남성/);
    // 수정: 여성으로
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(screen.getByLabelText("성별")).toHaveValue("");
    await user.selectOptions(screen.getByLabelText("성별"), "female");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ sex: "female", pregnancy_status: null });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("본인 · 여성");
    // 다시 열면 저장된 값이 채워져 있고, '선택 안 함'으로 지운다
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(screen.getByLabelText("성별")).toHaveValue("female");
    await user.selectOptions(screen.getByLabelText("성별"), "");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ sex: null });
    // 가족 프로필에도 같은 칸
    await user.click(screen.getByTestId("add-family"));
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    await user.selectOptions(screen.getByLabelText("성별"), "male");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(screen.getAllByTestId("profile-item")).toHaveLength(2));
    server.events.removeAllListeners();
    expect(screen.getAllByTestId("profile-item")[1]).toHaveTextContent("자녀 · 남성");
    // 요청 본문: 성별만 바뀌고 건강 정보 칸은 없다(동의가 없으니 싣지 않는다)
    expect(bodies.map((body) => body.sex)).toEqual([null, "female", null, "male"]);
    // 건강 정보 칸은 없다. 병아리 배경색(`avatar_color`, 건강 정보 아님, FE-17 U-01)은 늘 실린다
    for (const body of bodies) {
      expect(Object.keys(body)).toEqual(["relation", "label", "age_band", "sex", "avatar_color"]);
      expect(AVATAR_COLORS).toContain(body.avatar_color);
    }
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
    await user.selectOptions(screen.getByLabelText("성별"), "female"); // 임신 여부 칸은 여성일 때만(작업 B)
    await user.click(screen.getByRole("radio", { name: "예" }));
    await user.type(screen.getByLabelText("복용 중인 약(선택)"), "가나다정 100밀리그램");
    // 검색이 끝난 뒤 후보를 고르지 않고 `그대로 추가`(FE-04-24 A: 검색 중에는 막히고, 후보가 있으면 Enter는 저장이 아니다)
    await waitFor(() => expect(screen.getByTestId("medication-add")).toBeEnabled());
    await user.click(screen.getByTestId("medication-add"));
    expect(step()).toBe("profile-form"); // 폼 저장이 아니라 약 추가
    expect(screen.getAllByTestId("medication")).toHaveLength(1);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0]).toMatchObject({ relation: "self", label: "나", pregnancy_status: "pregnant", medications: [{ input_text: "가나다정 100밀리그램", item_seq: null }] });
    expect(screen.getByTestId("profile-item")).toHaveTextContent("본인 · 만 19~64세 · 여성 · 임신 여부 예 · 약 1개");
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
    await user.selectOptions(screen.getByLabelText("성별"), "female"); // 임신 여부 칸은 여성일 때만(작업 B)
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
    // 로그인 연결 모듈까지: 세션 쿠키는 `@supabase/ssr`의 동작에 맡기고 프런트 코드가 저장소·쿠키·콘솔에 직접 쓰지 않는다.
    // 예외 한 곳: `lib/supabase/cookies.ts`만 `document.cookie`를 만진다(쿠키 수명을 7일로 제한하려고 패키지의 브라우저 쿠키 저장소를
    // 같은 동작으로 대신하는 모듈, 2026-11-22 사용자 결정). 그 파일도 저장소·콘솔 검사는 그대로 받는다
    const supabaseDir = path.join(src, "lib/supabase");
    const cookieModule = path.join(supabaseDir, "cookies.ts");
    const all = [
      ...screens,
      path.join(src, "lib/api/account.ts"),
      path.join(src, "lib/api/auth.ts"),
      path.join(src, "app/auth/callback/route.ts"),
      ...readdirSync(supabaseDir).filter((name) => !name.includes(".test.")).map((name) => path.join(supabaseDir, name)),
    ];
    expect(all).toContain(cookieModule);
    expect(all.length).toBeGreaterThanOrEqual(19);
    for (const file of all) {
      expect(strip(file), file).not.toMatch(/localStorage|sessionStorage|indexedDB|zustand\/middleware|console\.|readUiSetting|writeUiSetting/i);
      if (file !== cookieModule) expect(strip(file), file).not.toMatch(/document\.cookie/i);
    }
    expect(strip(cookieModule)).toMatch(/document\.cookie/);
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

  // 계정 자리는 버튼 하나 + 팝오버 메뉴다(2026-11-23). 항목 순서·초점·키보드는 `account-menu.test.tsx`가 본다
  const menuItems = () => screen.getAllByRole("menuitem").map((item) => item.textContent);

  it("게스트 버튼은 '계정'이고 메뉴는 '로그인/가입'·화면 모드·'약관·정책', 로그인하면 버튼이 상태 글자이고 메뉴는 프로필 관리·화면 모드·약관·정책·로그아웃(서버는 이름·이메일을 주지 않는다)", async () => {
    const user = userEvent.setup();
    const { rerender, unmount } = render(<AccountMenu member={false} accountEnabled onOpen={() => {}} onLogout={() => {}} onLegal={() => {}} />);
    expect(screen.getByTestId("account-menu-button")).toHaveTextContent("계정");
    await user.click(screen.getByTestId("account-menu-button"));
    expect(menuItems()).toEqual(["로그인/가입", "약관·정책"]);
    expect(screen.getAllByRole("menuitemradio").map((item) => item.textContent)).toEqual(["밝은 모드", "다크 모드", "시스템기기 설정을 따라요"]);
    await user.keyboard("{Escape}");
    rerender(<AccountMenu member accountEnabled onOpen={() => {}} onLogout={() => {}} onLegal={() => {}} />);
    expect(screen.getByTestId("account-menu-button")).toHaveTextContent("로그인됨");
    await user.click(screen.getByTestId("account-menu-button"));
    expect(menuItems()).toEqual(["프로필 관리", "약관·정책", "로그아웃"]);
    expect(screen.getByRole("separator")).toBeInTheDocument(); // 로그아웃 앞 구분선
    unmount();
  });

  it("계정 기능이 꺼져 있으면 게스트 메뉴에 '로그인/가입'을 그리지 않고 화면 모드·'약관·정책'만 남는다", async () => {
    const user = userEvent.setup();
    render(<AccountMenu member={false} accountEnabled={false} onOpen={() => {}} onLogout={() => {}} onLegal={() => {}} />);
    await user.click(screen.getByTestId("account-menu-button"));
    expect(menuItems()).toEqual(["약관·정책"]);
    expect(screen.getAllByRole("menuitemradio")).toHaveLength(3);
  });
});

describe("대상 선택 '누가 먹나요'(입력창 프로필 칩, 2026-11-23)", () => {
  const profiles: Profile[] = [
    { profile_id: "a", relation: "self", label: "나", age_band: "y19_64", sex: "female", pregnancy_status: null, avatar_color: "yellow", sort_order: 0, medications: [] },
    { profile_id: "b", relation: "child", label: "첫째", age_band: "y6_11", sex: null, pregnancy_status: null, avatar_color: "teal", sort_order: 1, medications: [] },
  ];
  const chip = () => screen.getByTestId("target-chip");
  const options = () => within(screen.getByTestId("target-menu")).getAllByRole("menuitemradio");

  it("칩은 고른 프로필의 병아리 아바타(그 색) + 이름이고, 누르면 위로 목록이 열려 프로필마다 고를 수 있으며 '선택 안 함'으로 되돌린다", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<TargetChip profiles={profiles} value={null} onChange={onChange} />);
    expect(chip()).toHaveAccessibleName("누가 먹나요 선택 안 함");
    expect(chip()).toHaveAttribute("aria-haspopup", "menu");
    expect(chip()).toHaveAttribute("aria-expanded", "false");
    expect(within(chip()).queryByTestId("profile-avatar")).toBeNull();
    await user.click(chip());
    expect(chip()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: "누가 먹나요" })).toBeInTheDocument();
    expect(options().map((option) => option.textContent)).toEqual(["선택 안 함", "나", "첫째"]);
    expect(screen.getByRole("menuitemradio", { name: "선택 안 함" })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(options()[0]).toHaveFocus()); // 누르면 첫 항목에 초점
    // 목록 안 아바타는 프로필마다 그 색이다
    expect(within(screen.getByRole("menuitemradio", { name: "첫째" })).getByTestId("profile-avatar")).toHaveAttribute("data-color", "teal");
    await user.click(screen.getByRole("menuitemradio", { name: "첫째" }));
    expect(onChange).toHaveBeenLastCalledWith("b");
    await waitFor(() => expect(screen.queryByTestId("target-menu")).toBeNull());
    rerender(<TargetChip profiles={profiles} value="b" onChange={onChange} />);
    expect(chip()).toHaveAccessibleName("누가 먹나요 첫째");
    expect(within(chip()).getByTestId("profile-avatar")).toHaveAttribute("data-color", "teal");
    await user.click(chip());
    expect(screen.getByRole("menuitemradio", { name: "첫째" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("menuitemradio", { name: "선택 안 함" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("키보드: 칩에서 Enter로 열고 ↓·Enter로 고르며, Esc로 닫으면 초점이 칩으로 돌아온다", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TargetChip profiles={profiles} value={null} onChange={onChange} />);
    chip().focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(options()[0]).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    expect(options()[1]).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("a");
    await waitFor(() => expect(screen.queryByTestId("target-menu")).toBeNull());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(options()[0]).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("target-menu")).toBeNull());
    expect(chip()).toHaveFocus();
  });

  it("마우스를 올리면 초점을 옮기지 않고 열리고(입력 중인 글자 칸 유지), 내리면 닫히며, 열린 채 누르면 닫지 않고 고정한다", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      render(
        <>
          <textarea aria-label="질문" />
          <TargetChip profiles={profiles} value={null} onChange={() => {}} />
        </>,
      );
      const box = screen.getByRole("textbox", { name: "질문" });
      box.focus();
      await user.hover(chip());
      await act(() => vi.advanceTimersByTimeAsync(200));
      expect(screen.getByTestId("target-menu")).toBeInTheDocument();
      expect(box).toHaveFocus();
      await user.unhover(chip());
      await act(() => vi.advanceTimersByTimeAsync(400));
      expect(screen.queryByTestId("target-menu")).toBeNull();
      expect(box).toHaveFocus();
      // 다시 올려 열고, 누르면 고정(첫 항목 초점), 포인터가 나가도 열려 있다
      await user.hover(chip());
      await act(() => vi.advanceTimersByTimeAsync(200));
      await user.click(chip());
      await act(() => vi.advanceTimersByTimeAsync(50));
      expect(screen.getByTestId("target-menu")).toBeInTheDocument();
      expect(options()[0]).toHaveFocus();
      await user.unhover(chip());
      await act(() => vi.advanceTimersByTimeAsync(400));
      expect(screen.getByTestId("target-menu")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("별명이 없는 프로필(서버는 label null을 허용한다)은 관계 글자로 보인다", async () => {
    const user = userEvent.setup();
    render(<TargetChip profiles={[{ profile_id: "c", relation: "parent", label: null, age_band: null, sex: null, pregnancy_status: null, avatar_color: "yellow", sort_order: 0, medications: [] }]} value="c" onChange={() => {}} />);
    expect(chip()).toHaveAccessibleName("누가 먹나요 부모");
    await user.click(chip());
    expect(screen.getByRole("menuitemradio", { name: "부모" })).toBeInTheDocument();
  });

  it("새 프로필의 기본 색은 아직 안 쓴 첫 색이고(8색 순서), 모두 쓰였으면 노랑이다", () => {
    expect(suggestAvatarColor([])).toBe("yellow");
    expect(suggestAvatarColor([{ avatar_color: "yellow" }])).toBe("coral");
    expect(suggestAvatarColor([{ avatar_color: "yellow" }, { avatar_color: "pink" }, { avatar_color: "coral" }])).toBe("purple");
    expect(suggestAvatarColor(AVATAR_COLORS.map((avatar_color) => ({ avatar_color })))).toBe("yellow");
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

  it("GFM 파이프 표는 머리·구분·본문 줄로 표가 되고, 구분 줄이 없는 `|` 줄은 문단(글자 그대로)이다", () => {
    const table = "| 항목 | 목적 |\n|:---|---:|\n| **로그인** 정보 | 식별 |\n| 프로필 | 확인 | 넘침 |\n| 모자람 |\n\n| 표 아님 | 구분 줄 없음 |";
    expect(parseMarkdown(table)).toEqual([
      { kind: "table", header: ["항목", "목적"], rows: [["**로그인** 정보", "식별"], ["프로필", "확인 | 넘침"], ["모자람", ""]] },
      { kind: "paragraph", text: "| 표 아님 | 구분 줄 없음 |" },
    ]);
    const { container } = render(<Markdown source={table} />);
    const ths = container.querySelectorAll("thead th");
    expect(ths).toHaveLength(2);
    for (const th of ths) expect(th).toHaveAttribute("scope", "col");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(container.querySelector("tbody td strong")).toHaveTextContent("로그인"); // 칸 안 굵게 유지
    expect(container.querySelector("table")!.parentElement).toHaveClass("overflow-x-auto"); // 상자 안에서만 가로 스크롤
    expect(container.querySelector("p")).toHaveTextContent("| 표 아님 | 구분 줄 없음 |");
    expect(container.querySelectorAll("table")).toHaveLength(1);
  });

  it("인용(`> …`)은 blockquote로 그리고 이어지는 `>` 줄은 한 인용으로 잇는다", () => {
    expect(parseMarkdown("> 초안입니다.\n> **검토** 전.\n\n본문")).toEqual([
      { kind: "quote", text: "초안입니다. **검토** 전." },
      { kind: "paragraph", text: "본문" },
    ]);
    const { container } = render(<Markdown source={"> 초안입니다.\n> 검토 전."} />);
    expect(container.querySelectorAll("blockquote")).toHaveLength(1);
    expect(container.querySelector("blockquote")).toHaveTextContent("초안입니다. 검토 전.");
    expect(container.querySelector("blockquote")!.textContent).not.toContain(">");
  });

  describe("백엔드 시드 본문(읽기만)", () => {
    const DB = path.resolve(__dirname, "../../../../backend/app/db");
    /** 시드 SQL의 `('doc_type', version, 'title', $md$본문$md$` 행을 뽑는다 */
    const seedBodies = (file: string) =>
      [...readFileSync(path.join(DB, file), "utf8").matchAll(/\('(\w+)',\s*(\d+),\s*'[^']*',\s*\$md\$([\s\S]*?)\$md\$/g)].map((m) => ({ docType: m[1], version: Number(m[2]), body: m[3] }));
    const v2 = seedBodies("seed_legal_v2.sql");
    const v1 = seedBodies("seed_legal_v1.sql");
    const age14 = seedBodies("seed_legal_age14.sql");

    it("시드 v2 네 문서·v1 네 문서·age_14를 읽었다(파싱 깨짐 감지)", () => {
      expect(v2.map((d) => d.docType)).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent"]);
      expect(v1.map((d) => d.docType)).toEqual(["terms", "privacy_policy", "privacy_consent", "sensitive_consent"]);
      expect(age14).toEqual([{ docType: "age_14", version: 1, body: "만 14세 이상입니다." }]);
    });

    it.each([...v2, ...v1, ...age14].map((d) => [`${d.docType} v${d.version}`, d.body] as const))("%s: `|`로 시작하는 줄이 문단으로 남지 않고 인용 표식 `>`이 글자로 남지 않는다", (_name, body) => {
      const blocks = parseMarkdown(body);
      for (const block of blocks) {
        if (block.kind === "paragraph" || block.kind === "quote") {
          expect(block.text.startsWith("|"), block.text).toBe(false);
          expect(block.text, block.text).not.toContain("|---");
          expect(block.text.startsWith(">"), block.text).toBe(false);
        }
      }
      const { container, unmount } = render(<Markdown source={body} />);
      for (const p of container.querySelectorAll("p, li, blockquote, h4")) {
        expect(p.textContent!.trim().startsWith("|"), p.textContent!).toBe(false);
        expect(p.textContent!, p.textContent!).not.toContain("|---");
      }
      unmount();
    });

    it("시드 v2 처리방침: 표 두 개(1절 3칸 5행, 3절 6칸 2행)가 table·th[scope=col]로 그려진다", () => {
      const policy = v2.find((d) => d.docType === "privacy_policy")!;
      const tables = parseMarkdown(policy.body).filter((b) => b.kind === "table");
      expect(tables).toHaveLength(2);
      expect(tables[0]).toMatchObject({ header: ["항목", "목적", "언제"] });
      expect(tables[0].kind === "table" && tables[0].rows).toHaveLength(5);
      expect(tables[0].kind === "table" && tables[0].rows[0][0].startsWith("로그인 정보: 소셜 로그인 공급자")).toBe(true);
      expect(tables[1]).toMatchObject({ header: ["받는 자", "위탁하는 업무", "이전되는 항목", "국가·시기·방법", "보유·이용 기간", "거부 방법과 효과"] });
      expect(tables[1].kind === "table" && tables[1].rows).toHaveLength(2);
      const { container } = render(<Markdown source={policy.body} />);
      expect(container.querySelectorAll("table")).toHaveLength(2);
      expect(container.querySelectorAll('th[scope="col"]')).toHaveLength(3 + 6);
      expect(container.querySelectorAll("tbody tr")).toHaveLength(5 + 2);
      for (const cell of container.querySelectorAll("td")) expect(cell.textContent).not.toContain("|");
    });

    it("시드 v2 네 문서의 머리 '초안·법률 검토 전' 안내는 blockquote로 그려진다", () => {
      for (const doc of v2) {
        const first = parseMarkdown(doc.body)[0];
        expect(first.kind, doc.docType).toBe("quote");
        const { container, unmount } = render(<Markdown source={doc.body} />);
        const quotes = container.querySelectorAll("blockquote");
        expect(quotes, doc.docType).toHaveLength(1);
        expect(quotes[0]).toHaveTextContent("초안·법률 검토 전입니다.");
        expect(quotes[0]).toHaveTextContent("원문 승인 2026-11-19(사용자)");
        unmount();
      }
    });

    it("age_14 본문은 문단 하나다", () => {
      expect(parseMarkdown(age14[0].body)).toEqual([{ kind: "paragraph", text: "만 14세 이상입니다." }]);
    });

    // 사용자 보고 2026-11-22(실서버 §6·§7 연락처 줄): 시드는 `운영자(개발자) · {{PRIVACY_CONTACT}}` 한 줄이고 원격 적용이
    // `개인정보 보호책임자: <이름>, 문의: <이메일>`로 같은 줄에 채운다(account_repo_pg.render_privacy_contact). 줄 구분이 본문에 없으니
    // 화면은 한 문단으로 그리고(GFM), 어디서 접히는지는 폭에 따라 다르다. 프런트가 보장하는 것: 이메일은 중간에서 끊기지 않는다.
    // 값은 가짜(저장소·시험에 실제 이름·이메일을 넣지 않는다)
    const CONTACT = "개인정보 보호책임자: 홍길동, 문의: privacy@example.com";
    const fillContact = (body: string) => body.replaceAll("{{PRIVACY_CONTACT}}", CONTACT);

    it.each(["terms", "privacy_policy"])("시드 v2 %s의 연락처 줄은 한 문단이고 이메일은 끊기지 않는 덩어리(nowrap)로 그려진다", (docType) => {
      const body = fillContact(v2.find((d) => d.docType === docType)!.body);
      expect(body).not.toContain("{{PRIVACY_CONTACT}}");
      const contact = parseMarkdown(body).find((b) => b.kind === "paragraph" && b.text.includes("운영자(개발자)"));
      expect(contact).toEqual({ kind: "paragraph", text: `Can I PPiyak 운영자(개발자) · ${CONTACT}` }); // 줄 구분 없음(서버 본문 그대로)
      const { container } = render(<Markdown source={body} />);
      // 표 안의 위탁처 이메일에도 같은 표식이 붙으므로 연락처 문단 안의 것을 고른다
      const email = [...container.querySelectorAll('p [data-testid="legal-email"]')].find((el) => el.textContent === "privacy@example.com")!;
      expect(email).toBeDefined();
      expect(email.className).toContain("whitespace-nowrap");
      expect(email.closest("p")).toHaveTextContent(`Can I PPiyak 운영자(개발자) · ${CONTACT}`);
      for (const span of container.querySelectorAll('[data-testid="legal-email"]')) expect(span.textContent).toMatch(/^[^\s@]+@[^\s@]+\.[A-Za-z]+$/); // 이메일만 덩어리
      expect(container.querySelectorAll("br")).toHaveLength(0); // 시드에 강제 줄바꿈이 없으니 br도 없다
    });

    it("GFM 강제 줄바꿈(줄 끝 두 칸 공백·백슬래시)은 문단·인용 안에서 br이 되고, 그냥 이어지는 줄은 공백으로 잇는다", () => {
      expect(parseMarkdown("운영자(개발자)  \n보호책임자: 홍길동\\\n문의: a@b.co\n이어짐  ")).toEqual([{ kind: "paragraph", text: "운영자(개발자)\n보호책임자: 홍길동\n문의: a@b.co 이어짐" }]);
      expect(parseMarkdown("> 첫 줄  \n> 둘째 줄\n> 셋째 줄")).toEqual([{ kind: "quote", text: "첫 줄\n둘째 줄 셋째 줄" }]);
      const { container } = render(<Markdown source={"운영자  \n**문의**: a@b.co\n\n> 가  \n> 나"} />);
      expect(container.querySelectorAll("p br")).toHaveLength(1);
      expect(container.querySelectorAll("blockquote br")).toHaveLength(1);
      expect(container.querySelector("p strong")).toHaveTextContent("문의");
      expect(container.querySelector("p")!.textContent).toBe("운영자문의: a@b.co");
      expect(container.querySelector("p")!.textContent).not.toContain("\\");
    });
  });
});

describe("프로필 약 검색 후보 고르기(FE-04-13 A·FE-04-20 A·FE-04-21 A)", () => {
  const medicationInput = () => screen.getByRole("combobox", { name: "복용 중인 약(선택)" });
  const listbox = () => screen.getByTestId("medication-candidates");
  const options = () => within(listbox()).getAllByRole("option");
  const chips = () => screen.getAllByTestId("medication").map((chip) => ({ name: within(chip).getByTestId("medication-name").textContent, confirmed: chip.getAttribute("data-confirmed") }));

  /** `POST /api/drugs/search` 요청을 모은다(주소·본문). 검색어가 URL에 실리지 않는지도 본다 */
  function watchSearch() {
    const requests: { url: string; method: string; body: unknown }[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (!new URL(request.url).pathname.endsWith("/api/drugs/search")) return;
      requests.push({ url: request.url, method: request.method, body: await request.clone().json().catch(() => null) });
    });
    return requests;
  }

  async function openForm(user: ReturnType<typeof userEvent.setup>) {
    await login(user);
    await consent(user, { health: true });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
  }

  afterEach(() => server.events.removeAllListeners());

  it("입력이 멈춘 뒤 한 번만 POST 본문 `{q}`로 검색하고(URL에 검색어 없음), 후보는 제품명·성분명 표지와 함께 목록으로 보인다", async () => {
    const requests = watchSearch();
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAttribute("aria-controls", listbox().id);
    expect(listbox()).not.toBeVisible();
    await user.type(input, "가나다");
    expect(requests).toEqual([]); // 300ms 안에는 부르지 않는다
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe("POST");
    expect(requests[0].body).toEqual({ q: "가나다" });
    expect(new URL(requests[0].url).search).toBe("");
    expect(listbox()).toHaveAccessibleName("후보 6개");
    expect(options().map((option) => option.getAttribute("data-matched-by"))).toEqual(["product_name", "product_name", "product_name", "product_name", "product_name", "ingredient_name"]); // 제품 → 성분
    expect(options()[0]).toHaveAccessibleName("가나다정 100밀리그램, 제품명, 합성제약(주), 일반");
    expect(options()[5]).toHaveAccessibleName("가나다마이신, 성분명");
    expect(options()[5]).toHaveTextContent("성분명");
    expect(screen.getByTestId("medication-status")).toHaveTextContent("후보 6개");
    expect(screen.queryByTestId("medication-no-candidates")).toBeNull();
  });

  it("↑↓로 후보를 옮기고(aria-activedescendant) Enter로 고르면 `item_seq`와 함께 저장된다. 고른 뒤 입력은 비고 목록은 닫힌다", async () => {
    const { user, store } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "가나다");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(input).not.toHaveAttribute("aria-activedescendant");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options()[1].id);
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    expect(options()[0]).toHaveAttribute("aria-selected", "false");
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", options()[0].id);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(step()).toBe("profile-form"); // Enter는 폼 저장이 아니다
    expect(chips()).toEqual([{ name: "가나다정 500밀리그램", confirmed: "true" }]);
    expect(screen.queryByTestId("medication-unconfirmed")).toBeNull();
    expect(screen.queryByTestId("medication-unconfirmed-note")).toBeNull();
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveFocus();
    // 저장: 고른 후보는 `{input_text, item_seq}`로 간다. 목(서버 규칙)은 사전에 있는 번호를 확인 시각과 함께 남긴다
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0].medications).toEqual([{ medication_id: expect.any(String), input_text: "가나다정 500밀리그램", item_seq: "200000002", confirmed_at: expect.any(String) }]);
    // 수정 폼을 다시 열면 확인된 약으로 보인다
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(chips()).toEqual([{ name: "가나다정 500밀리그램", confirmed: "true" }]);
  });

  it("후보가 없으면 안내가 보이고, `그대로 추가`나 Enter는 글자 그대로 확인 안 된 약(`item_seq` 없음)으로 넣는다. 성분명 후보도 번호가 없어 확인 안 된 약이다", async () => {
    const requests = watchSearch();
    const { user, store } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "없는약");
    await waitFor(() => expect(screen.getByTestId("medication-no-candidates")).toHaveTextContent(copy.MEDICATION_NO_CANDIDATES));
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveValue("없는약"); // 입력은 그대로
    await user.click(screen.getByTestId("medication-add"));
    expect(chips()).toEqual([{ name: "없는약", confirmed: "false" }]);
    expect(screen.getByTestId("medication-unconfirmed")).toHaveTextContent(copy.MEDICATION_UNCONFIRMED_TAG);
    expect(screen.getByTestId("medication-unconfirmed-note")).toHaveTextContent(copy.MEDICATION_UNCONFIRMED_NOTE);
    expect(screen.queryByTestId("medication-no-candidates")).toBeNull(); // 넣고 나면 안내도 지운다
    // 후보가 없을 때(FE-04-24 A의 "후보가 있으면"에 해당하지 않음)의 Enter도 글자 그대로
    await user.type(input, "가나다정 100밀리그램 없는약");
    await waitFor(() => expect(screen.getByTestId("medication-no-candidates")).toBeVisible());
    await user.keyboard("{Enter}");
    expect(chips()).toEqual([
      { name: "없는약", confirmed: "false" },
      { name: "가나다정 100밀리그램 없는약", confirmed: "false" },
    ]);
    // 성분명 후보를 마우스로 고르면 이름은 후보 글자이고 번호는 없다
    await user.type(input, "라마바펜");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(options()).toHaveLength(1);
    await user.click(options()[0]);
    expect(chips()).toEqual([
      { name: "없는약", confirmed: "false" },
      { name: "가나다정 100밀리그램 없는약", confirmed: "false" },
      { name: "라마바펜", confirmed: "false" },
    ]);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0].medications.map((item) => [item.input_text, item.item_seq, item.confirmed_at])).toEqual([
      ["없는약", null, null],
      ["가나다정 100밀리그램 없는약", null, null],
      ["라마바펜", null, null],
    ]);
    expect(requests.every((request) => request.method === "POST" && new URL(request.url).search === "")).toBe(true);
  });

  it("후보는 최대 10개이고 비슷한 이름(`bm25`)에는 표지가 붙는다. 같은 약은 두 번 넣지 않는다", async () => {
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "다목");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(options()).toHaveLength(DRUG_CANDIDATES_MAX);
    expect(MOCK_DRUG_DICT.filter((entry) => entry.name.startsWith("다목")).length).toBeGreaterThan(DRUG_CANDIDATES_MAX);
    await user.clear(input);
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.type(input, "가나다졍");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(options()).toHaveLength(1);
    expect(options()[0]).toHaveTextContent(copy.MEDICATION_SIMILAR_TAG);
    expect(options()[0]).toHaveAccessibleName("가나다정 100밀리그램, 제품명, 합성제약(주), 일반, 비슷한 이름");
    await user.click(options()[0]);
    await user.type(input, "가나다정 100밀리그램");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    await user.keyboard("{ArrowDown}{Enter}"); // 같은 번호
    expect(chips()).toEqual([{ name: "가나다정 100밀리그램", confirmed: "true" }]);
  });

  it("Esc는 열린 목록만 닫고 모달은 남는다. 목록이 닫힌 뒤의 Esc는 모달을 닫는다", async () => {
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "가나다");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(listbox()).not.toBeVisible();
    expect(step()).toBe("profile-form");
    expect(input).toHaveValue("가나다"); // 적은 글자는 남는다
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
  });

  it("검색이 401·422·네트워크 오류로 실패해도 입력은 그대로 남고 글자 저장은 된다. 검색어는 콘솔에 찍히지 않는다", async () => {
    const consoleSpy = ["log", "info", "warn", "error", "debug"].map((name) => vi.spyOn(console, name as "log").mockImplementation(() => {}));
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    for (const [text, respond, message] of [
      ["mock-401", () => HttpResponse.json({ code: "AUTH_REQUIRED", fields: [] }, { status: 401 }), copy.MEDICATION_SEARCH_AUTH_EXPIRED],
      ["mock-422", () => HttpResponse.json({ code: "INVALID_REQUEST", fields: ["q"] }, { status: 422 }), copy.MEDICATION_SEARCH_FAILED],
      ["mock-net", () => HttpResponse.error(), copy.MEDICATION_SEARCH_FAILED],
    ] as const) {
      server.use(http.post("*/api/drugs/search", respond));
      await user.type(input, text);
      await waitFor(() => expect(screen.getByTestId("medication-search-error")).toHaveTextContent(message));
      expect(input).toHaveValue(text);
      expect(input).toHaveAttribute("aria-expanded", "false");
      await user.click(screen.getByTestId("medication-add"));
      expect(screen.queryByTestId("medication-search-error")).toBeNull();
    }
    expect(chips()).toEqual([
      { name: "mock-401", confirmed: "false" },
      { name: "mock-422", confirmed: "false" },
      { name: "mock-net", confirmed: "false" },
    ]);
    // 다시 적으면 오류 줄이 사라진다
    await user.type(input, "가");
    expect(screen.queryByTestId("medication-search-error")).toBeNull();
    const logged = consoleSpy.flatMap((spy) => spy.mock.calls.flat()).map((value) => (typeof value === "string" ? value : JSON.stringify(value) ?? ""));
    for (const text of ["mock-401", "mock-422", "mock-net", "가나다"]) expect(logged.join("\n")).not.toContain(text);
    consoleSpy.forEach((spy) => spy.mockRestore());
  });

  it("검색어가 바뀌면 앞 요청의 결과를 버린다(늦게 온 옛 후보가 새 입력을 덮지 않는다)", async () => {
    let release: () => void = () => {};
    const first = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("*/api/drugs/search", async ({ request }) => {
        const { q } = (await request.json()) as { q: string };
        if (q === "가나다") await first; // 첫 검색은 붙잡아 둔다
        return HttpResponse.json(searchMockDrugs(q));
      }),
    );
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "가나다");
    await waitFor(() => expect(screen.getByTestId("medication-searching")).toBeVisible());
    await user.type(input, "시럽"); // "가나다시럽": 새 검색
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(options().map((option) => option.textContent)).toHaveLength(3);
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(options()).toHaveLength(3); // 옛 결과(6개)로 바뀌지 않는다
  });

  it("약이 10개면 입력·추가가 막히고 상한 글자가 보인다", async () => {
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    for (let index = 0; index < MEDICATIONS_MAX; index += 1) {
      await user.type(input, `약${index}`);
      await waitFor(() => expect(screen.getByTestId("medication-add")).toBeEnabled()); // 검색이 끝나야 `그대로 추가`가 켜진다(FE-04-24 A)
      await user.click(screen.getByTestId("medication-add"));
    }
    expect(screen.getAllByTestId("medication")).toHaveLength(MEDICATIONS_MAX);
    expect(input).toBeDisabled();
    expect(screen.getByTestId("medication-add")).toBeDisabled();
    expect(screen.getByTestId("medication-limit")).toHaveTextContent(copy.ERROR_MEDICATION_LIMIT);
    await user.click(screen.getByRole("button", { name: "약0 삭제" }));
    expect(input).toBeEnabled();
    expect(screen.queryByTestId("medication-limit")).toBeNull();
  });

  it("건강 정보 동의가 없으면 검색 칸도 비활성이다", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-family"));
    expect(medicationInput()).toBeDisabled();
    expect(screen.getByTestId("medication-add")).toBeDisabled();
  });

  // ---- FE-04-24 A(2026-11-22): 검색 중 저장 막음, 후보가 있으면 Enter는 첫 후보로 이동만, 버튼 글자 "그대로 추가"
  it("FE-04-24 A: 검색 중(디바운스 대기·요청 중)에는 `그대로 추가`가 비활성이고 Enter도 저장하지 않는다. 결과가 오면 다시 켜진다", async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("*/api/drugs/search", async ({ request }) => {
        const { q } = (await request.json()) as { q: string };
        await held; // 요청을 붙잡아 "요청 중" 상태를 만든다
        return HttpResponse.json(searchMockDrugs(q));
      }),
    );
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    const add = () => screen.getByTestId("medication-add");
    expect(add()).toBeDisabled(); // 빈 입력
    // 디바운스 대기 중(300ms 안): 버튼 비활성, "찾는 중" 한 줄, Enter 무시
    await user.type(input, "가나다");
    expect(add()).toBeDisabled();
    expect(screen.getByTestId("medication-searching")).toHaveTextContent(copy.MEDICATION_SEARCHING);
    await user.keyboard("{Enter}");
    expect(screen.queryAllByTestId("medication")).toHaveLength(0);
    expect(input).toHaveValue("가나다");
    // 요청 중(300ms 뒤, 응답 전): 그대로 막혀 있다
    await new Promise((resolve) => setTimeout(resolve, MEDICATION_SEARCH_DEBOUNCE_MS + 50));
    expect(add()).toBeDisabled();
    expect(screen.getByTestId("medication-searching")).toBeVisible();
    await user.click(add());
    await user.keyboard("{Enter}");
    expect(screen.queryAllByTestId("medication")).toHaveLength(0);
    expect(step()).toBe("profile-form");
    // 응답이 오면 켜진다
    release();
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(add()).toBeEnabled();
    expect(screen.queryByTestId("medication-searching")).toBeNull();
  });

  it("FE-04-24 A: 후보가 있을 때 고르지 않은 Enter는 첫 후보로 활성만 옮기고 저장하지 않는다. 한 번 더 Enter면 그 후보가 `item_seq`와 함께 들어간다", async () => {
    const { user, store } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "가나다");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(input).not.toHaveAttribute("aria-activedescendant");
    await user.keyboard("{Enter}");
    expect(screen.queryAllByTestId("medication")).toHaveLength(0); // 저장 없음
    expect(input).toHaveValue("가나다"); // 입력도 그대로
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options()[0].id);
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveFocus(); // 초점은 입력에 남는다(combobox 패턴)
    // Esc로 목록을 닫은 뒤의 Enter도 저장이 아니라 목록을 다시 열고 첫 후보로 간다
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Enter}");
    expect(screen.queryAllByTestId("medication")).toHaveLength(0);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options()[0].id);
    // 한 번 더 Enter: 첫 후보(제품명, item_seq 있음)가 확인된 약으로 들어간다
    await user.keyboard("{Enter}");
    expect(chips()).toEqual([{ name: "가나다정 100밀리그램", confirmed: "true" }]);
    expect(input).toHaveValue("");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0].medications.map((item) => [item.input_text, item.item_seq])).toEqual([["가나다정 100밀리그램", "200000001"]]);
  });

  it("FE-04-24 A: 버튼 글자는 \"그대로 추가\"이고, 후보가 떠 있어도 누르면 확인 안 된 약(`item_seq` 없음)으로 들어간다. 마우스로 후보를 고르면 `item_seq`가 붙는다", async () => {
    const { user, store } = setup();
    await openForm(user);
    const input = medicationInput();
    const add = screen.getByTestId("medication-add");
    expect(copy.MEDICATION_ADD_LABEL).toBe("그대로 추가");
    expect(add).toHaveTextContent("그대로 추가");
    expect(screen.getByRole("button", { name: "그대로 추가" })).toBe(add);
    await user.type(input, "가나다");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    expect(options().length).toBeGreaterThan(0);
    await user.click(add);
    expect(chips()).toEqual([{ name: "가나다", confirmed: "false" }]);
    expect(screen.getByTestId("medication-unconfirmed")).toHaveTextContent(copy.MEDICATION_UNCONFIRMED_TAG);
    expect(screen.getByTestId("medication-unconfirmed-note")).toHaveTextContent(copy.MEDICATION_UNCONFIRMED_NOTE);
    // 후보를 고르면 확인된 약
    await user.type(input, "라마바");
    await waitFor(() => expect(input).toHaveAttribute("aria-expanded", "true"));
    await user.click(options()[0]);
    expect(chips()).toEqual([
      { name: "가나다", confirmed: "false" },
      { name: "라마바캡슐 10밀리그램", confirmed: "true" },
    ]);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(store.getState().profiles[0].medications.map((item) => [item.input_text, item.item_seq])).toEqual([
      ["가나다", null],
      ["라마바캡슐 10밀리그램", "200000006"],
    ]);
  });

  it("FE-04-24 A: 한글 조합을 끝내는 Enter(`isComposing` 또는 `keyCode 229`)는 저장도 후보 이동도 아니다", async () => {
    const { user } = setup();
    await openForm(user);
    const input = medicationInput();
    await user.type(input, "없는약");
    await waitFor(() => expect(screen.getByTestId("medication-no-candidates")).toBeVisible());
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(screen.queryAllByTestId("medication")).toHaveLength(0);
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(screen.queryAllByTestId("medication")).toHaveLength(0);
    fireEvent.keyDown(input, { key: "Enter" }); // 조합이 끝난 보통 Enter는 후보가 없으니 글자 그대로
    expect(chips()).toEqual([{ name: "없는약", confirmed: "false" }]);
  });

  // ---- FE-04-25 A(2026-11-22): 자료 밖 약 고지 한 줄(프로필 복용 약 입력 화면). 사진 확인 카드 쪽은 `photo.test.tsx`
  it("FE-04-25 A: 프로필 약 입력 아래에 자료 밖 약 고지가 승인 원문 그대로 한 줄 보인다(건강 정보 동의와 무관)", async () => {
    const { user } = setup();
    await openForm(user);
    const notice = screen.getByTestId("drug-data-scope-notice");
    expect(copy.DRUG_DATA_SCOPE_NOTICE).toBe("국내 허가 의약품 자료만 확인할 수 있어요. 조제약·해외 약 등 자료에 없는 약은 금기를 확인하지 못하니, 이름을 그대로 적고 약사에게 확인하세요.");
    expect(notice.textContent).toBe(copy.DRUG_DATA_SCOPE_NOTICE);
    // 입력 칸 바로 아래(라벨 → 입력 → 고지 순서)
    expect(medicationInput().compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.getAllByTestId("drug-data-scope-notice")).toHaveLength(1);
  });

  it("searchDrugs: 끊은 요청은 연결 오류로 바꾸지 않고 그대로 던진다(호출자가 버린다)", async () => {
    server.use(http.post("*/api/drugs/search", async () => HttpResponse.json(searchMockDrugs("가나다"))));
    const controller = new AbortController();
    controller.abort();
    await expect(searchDrugs("가나다", controller.signal)).rejects.not.toBeInstanceOf(AccountApiError);
    await expect(searchDrugs("가나다")).resolves.toMatchObject({ candidates: expect.any(Array), needs_confirmation: true });
  });
});

// ---------------------------------------------------------------- 복용 약 사진으로 등록(FE-04-27 A, 2026-11-22)
describe("복용 약 사진으로 등록(FE-04-27 A): 확인한 이름만 지금 편집 중인 프로필 목록에, 사진은 저장하지 않음", () => {
  const chips = () => screen.queryAllByTestId("medication").map((chip) => ({ name: within(chip).getByTestId("medication-name").textContent, confirmed: chip.getAttribute("data-confirmed") }));
  const photoButton = () => screen.getByTestId("medication-photo") as HTMLButtonElement;
  const photoModal = () => screen.getByTestId("photo-modal");
  const photoCard = () => within(photoModal()).findByTestId("photo-confirm-card");
  const pngFile = () => new File([new Uint8Array([1, 2, 3, 4])], "pouch.png", { type: "image/png" });
  /** 요청 기록: `/api/chat` 횟수와 프로필 저장 본문 */
  function watch() {
    const log = { chat: 0, ingest: 0, saves: [] as Record<string, unknown>[], bodies: [] as string[] };
    server.events.on("request:start", async ({ request }) => {
      const pathname = new URL(request.url).pathname;
      if (pathname.endsWith("/api/chat")) log.chat += 1;
      if (pathname.endsWith("/api/ingest/image")) log.ingest += 1;
      if (/\/api\/profiles(\/|$)/.test(pathname) && request.method !== "GET") {
        const text = await request.clone().text();
        log.bodies.push(text);
        if (request.method === "POST") log.saves.push(JSON.parse(text));
      }
    });
    return log;
  }
  async function openForm(user: ReturnType<typeof userEvent.setup>, { health = true } = {}) {
    await login(user);
    await consent(user, { health });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
  }
  /** `사진으로 등록` → 합성 PNG → 확인 카드(목 `ok`: 가나다정[후보 2]·라마바캡슐[후보 없음]) */
  async function toCard(user: ReturnType<typeof userEvent.setup>) {
    await user.click(photoButton());
    await waitFor(() => expect(photoModal()).toHaveAttribute("data-step", "pick"));
    await user.upload(within(photoModal()).getByTestId("photo-file"), pngFile());
    return photoCard();
  }

  beforeEach(() => {
    server.use(...createPhotoHandlers(), http.post("*/api/chat", () => HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 })));
  });
  afterEach(() => server.events.removeAllListeners());

  it("mergeMedications: 같은 약은 넣지 않고 10개를 넘기지 않는다(글자 입력·사진 등록이 같은 규칙)", () => {
    const a = { input_text: "가나다정 100밀리그램", item_seq: "200000001" };
    const b = { input_text: "라마바", item_seq: null };
    expect(mergeMedications([a], [a, b, { ...b }, { input_text: "다른 글자", item_seq: "200000001" }])).toEqual([a, b]);
    const ten = Array.from({ length: MEDICATIONS_MAX }, (_, i) => ({ input_text: `약${i}`, item_seq: null }));
    expect(mergeMedications(ten.slice(0, 9), [ten[9], { input_text: "열한번째", item_seq: null }])).toEqual(ten);
    expect(mergeMedications(ten, [{ input_text: "열한번째", item_seq: null }])).toEqual(ten);
  });

  it("버튼 `사진으로 등록`(새 글자, 승인 전)이 약 입력 아래·고지 위에 있고 건강 정보 묶음 안이라 동의가 없으면 비활성이다. 누르면 사진 모달이 계정 모달 위에 프로필 목적지로 열린다", async () => {
    const { user } = setup();
    await openForm(user, { health: false });
    expect(copy.MEDICATION_PHOTO_LABEL).toBe("사진으로 등록");
    expect(photoButton().textContent).toBe(copy.MEDICATION_PHOTO_LABEL);
    expect(photoButton()).toBeDisabled(); // fieldset disabled
    expect(screen.getByTestId("health-fields")).toContainElement(photoButton());
    const input = screen.getByRole("combobox", { name: "복용 중인 약(선택)" });
    const notice = screen.getByTestId("drug-data-scope-notice");
    expect(input.compareDocumentPosition(photoButton()) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(photoButton().compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.queryByTestId("photo-modal")).toBeNull();
  });

  it("열린 사진 모달: 가림 안내·외부 전송 고지(기존 글자 그대로)·119 진입점이 보이고, 계정 모달(z-40) 위 한 층(z-50)이며 초점은 사진 모달 제목에 있다. 닫으면 폼 입력은 그대로이고 초점은 버튼으로 돌아온다", async () => {
    const { user } = setup();
    await openForm(user);
    await user.type(screen.getByRole("combobox", { name: "복용 중인 약(선택)" }), "없는약");
    await waitFor(() => expect(screen.getByTestId("medication-add")).toBeEnabled()); // 검색이 끝나야 `그대로 추가`가 켜진다(FE-04-24 A)
    await user.click(screen.getByTestId("medication-add"));
    expect(chips()).toEqual([{ name: "없는약", confirmed: "false" }]);
    await user.click(photoButton());
    const box = photoModal();
    expect(box).toHaveAttribute("data-destination", "profile");
    expect(box.className).toMatch(/\bz-50\b/);
    expect(modal().className).toMatch(/\bz-40\b/);
    expect(within(box).getByTestId("photo-privacy-notice").textContent).toBe(PHOTO_PRIVACY_NOTICE);
    expect(within(box).getByTestId("photo-external-ai-notice").textContent).toBe(PHOTO_EXTERNAL_AI_NOTICE);
    expect(within(box).getByTestId("photo-external-ai-notice").textContent).toContain("외부 AI(OpenAI)"); // 사진 판독 제공자 only OpenAI(2026-11-23), 프로필 진입점에서도 같은 글자
    expect(box.querySelector('a[href="tel:119"]')).toBeNull(); // 층 안 119 진입점 없음(FE-17 U-04)
    expect(document.activeElement).toBe(within(box).getByRole("heading", { name: "사진으로 약 이름 읽기" }));
    expect(modal()).toBeInTheDocument(); // 계정 모달은 그대로 아래에 있다
    await user.click(within(box).getByTestId("photo-close"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(step()).toBe("profile-form");
    expect(screen.getByLabelText("이름(별명)")).toHaveValue("나");
    expect(chips()).toEqual([{ name: "없는약", confirmed: "false" }]); // 취소 뒤 변화 없음
    expect(document.activeElement).toBe(photoButton());
    // Esc도 같다
    await user.click(photoButton());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(step()).toBe("profile-form"); // 계정 모달은 닫히지 않는다(Esc 한 번에 한 층)
    expect(chips()).toEqual([{ name: "없는약", confirmed: "false" }]);
  });

  it("확인 카드 `이대로 확인`: 후보를 고른 약은 확인된 약(item_seq), 글자만 있는 약은 확인 안 된 약으로 목록에 들어간다. /chat 0회, 저장 요청 0회, 사진·이미지는 저장 요청에 없다", async () => {
    const log = watch();
    const { user, store } = setup();
    await openForm(user);
    const card = await toCard(user);
    expect(within(card).queryByTestId("photo-question")).toBeNull();
    const radios = within(within(card).getAllByTestId("photo-row")[0]).getAllByRole("radio");
    await user.click(radios[0]);
    await user.click(within(card).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(step()).toBe("profile-form");
    expect(chips()).toEqual([
      { name: "가나다정 100밀리그램", confirmed: "true" },
      { name: "라마바캡슐", confirmed: "false" },
    ]);
    expect(screen.getByTestId("medication-unconfirmed-note")).toHaveTextContent(copy.MEDICATION_UNCONFIRMED_NOTE);
    expect(document.activeElement).toBe(photoButton());
    expect(log).toMatchObject({ chat: 0, ingest: 1, saves: [] }); // 저장은 `저장`을 눌러야
    expect(setItem).not.toHaveBeenCalled();
    // 같은 사진을 다시 등록해도 중복은 들어가지 않는다
    const again = await toCard(user);
    await user.click(within(within(again).getAllByTestId("photo-row")[0]).getAllByRole("radio")[0]);
    await user.click(within(again).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(chips()).toHaveLength(2);
    // 저장: 이름만 간다. 사진 data URL·읽은 성분·용량 글자는 요청 어디에도 없다
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(log.saves).toHaveLength(1);
    expect(log.saves[0].medications).toEqual([
      { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
      { input_text: "라마바캡슐", item_seq: null },
    ]);
    for (const body of log.bodies) expect(body).not.toMatch(/data:image|base64|가나다성분|100mg|image/);
    expect(JSON.stringify(store.getState())).not.toMatch(/data:image|base64/);
    expect(log.chat).toBe(0);
  });

  it("후보를 고르지 않고 확인하면 읽은 글자 모두 확인 안 된 약으로 들어간다(FE-04-24 A 규칙). `글자로 입력`(실패 화면)은 닫고 약 입력 칸에 초점", async () => {
    const { user } = setup();
    await openForm(user);
    const card = await toCard(user);
    await user.click(within(card).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(chips()).toEqual([
      { name: "가나다정", confirmed: "false" },
      { name: "라마바캡슐", confirmed: "false" },
    ]);
    // 인식 실패 → 글자로 입력
    server.use(...createPhotoHandlers({ scenario: "unreadable" }));
    await user.click(photoButton());
    await user.upload(within(photoModal()).getByTestId("photo-file"), pngFile());
    await user.click(await within(photoModal()).findByTestId("photo-type-instead"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "복용 중인 약(선택)" }));
    expect(chips()).toHaveLength(2);
  });

  it("프로필별 도착지: 본인 프로필에 등록한 약은 가족 프로필 폼에 보이지 않고, 가족 폼에서 등록한 약은 그 가족 프로필에만 저장된다", async () => {
    const log = watch();
    const { user, store } = setup();
    await openForm(user);
    const card = await toCard(user);
    await user.click(within(within(card).getAllByTestId("photo-row")[0]).getAllByRole("radio")[0]);
    await user.click(within(card).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByTestId("add-family"));
    await waitFor(() => expect(step()).toBe("profile-form"));
    expect(chips()).toEqual([]); // 가족 폼은 비어서 시작
    await user.type(screen.getByLabelText("이름(별명)"), "첫째");
    const familyCard = await toCard(user);
    await user.click(within(within(familyCard).getAllByTestId("photo-row")[0]).getAllByRole("radio")[1]); // 500밀리그램
    await user.click(within(familyCard).getAllByTestId("photo-row-remove")[1]); // 라마바캡슐 줄은 지운다
    await user.click(within(familyCard).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(chips()).toEqual([{ name: "가나다정 500밀리그램", confirmed: "true" }]);
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(log.saves.map((save) => save.medications)).toEqual([
      [
        { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
        { input_text: "라마바캡슐", item_seq: null },
      ],
      [{ input_text: "가나다정 500밀리그램", item_seq: "200000002" }],
    ]);
    const [self, child] = store.getState().profiles;
    expect(self.medications.map((item) => item.input_text)).toEqual(["가나다정 100밀리그램", "라마바캡슐"]);
    expect(child.medications.map((item) => item.input_text)).toEqual(["가나다정 500밀리그램"]);
    expect(log.chat).toBe(0);
  });

  it("약이 10개면 버튼이 비활성이고, 9개일 때 사진으로 2개를 더하면 10개까지만 들어간다", async () => {
    const { user } = setup();
    await openForm(user);
    const input = screen.getByRole("combobox", { name: "복용 중인 약(선택)" });
    for (let i = 0; i < 9; i += 1) {
      await user.type(input, `없는약${i}`);
      await waitFor(() => expect(screen.getByTestId("medication-add")).toBeEnabled());
      await user.click(screen.getByTestId("medication-add"));
    }
    expect(chips()).toHaveLength(9);
    expect(photoButton()).toBeEnabled();
    const card = await toCard(user);
    await user.click(within(within(card).getAllByTestId("photo-row")[0]).getAllByRole("radio")[0]);
    await user.click(within(card).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(chips()).toHaveLength(MEDICATIONS_MAX);
    expect(chips()[9]).toEqual({ name: "가나다정 100밀리그램", confirmed: "true" });
    expect(photoButton()).toBeDisabled();
    expect(screen.getByTestId("medication-limit")).toHaveTextContent(copy.ERROR_MEDICATION_LIMIT);
  });
});

// ---------------------------------------------------------------- 프로필 저장 완료 안내(FE-04-15 A·FE-04-26, 2026-11-22)
describe("프로필 저장 완료 안내(FE-04-15 A): 저장 뒤 목록 위에 한 줄(role=status) + `질문하러 가기`", () => {
  function setupWithInput(store: AccountStore = createAccountStore()) {
    const user = userEvent.setup();
    render(
      <>
        <button type="button" onClick={() => openAccountModal(store)}>
          프로필 저장
        </button>
        <main data-testid="main">
          <textarea aria-label="질문 입력" />
        </main>
        <AccountModal store={store} />
      </>,
    );
    return { user, store };
  }
  const notice = () => screen.queryByTestId("profile-saved-notice");

  it("저장이 끝나면 목록 맨 위(설명 아래)에 안내(초안·승인 전)와 버튼이 보이고 보조기기용 role=status다. 초점은 제목, 마스코트 없음. 처음 열 때는 없다", async () => {
    const { user } = setup();
    await login(user);
    await consent(user, { health: true });
    expect(notice()).toBeNull();
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    expect(modal().querySelector("form")!).toHaveAttribute("aria-busy", "false");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    const box = notice()!;
    expect(box).toHaveAttribute("role", "status");
    expect(box).toHaveTextContent(copy.PROFILE_SAVED_NOTICE);
    expect(within(box).getByRole("button", { name: copy.GO_ASK_LABEL })).toBeInTheDocument();
    expect(copy.GO_ASK_LABEL).toBe("질문하러 가기");
    expect(within(box).queryByTestId("mascot")).toBeNull();
    expect(box.textContent).not.toMatch(/119|응급|금기/);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "프로필" }));
    // 설명 바로 아래, 목록 위
    expect(screen.getByText(copy.PROFILES_DESCRIPTION).compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(box.compareDocumentPosition(screen.getByTestId("profile-item")) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    // 다른 화면으로 가면 사라지고, 돌아와도 다시 보이지 않는다
    await user.click(screen.getByRole("button", { name: "나 수정" }));
    expect(notice()).toBeNull();
    await user.click(screen.getByRole("button", { name: "취소" }));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(notice()).toBeNull();
  });

  it("`질문하러 가기`는 모달을 닫고 초점을 질문 입력창에 둔다", async () => {
    const { user } = setupWithInput();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    await user.click(screen.getByTestId("go-ask"));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "질문 입력" }));
    // 다시 열면 안내는 없다
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(notice()).toBeNull();
  });

  it("저장이 실패하면(422) 폼에 남아 오류(role=alert)만 보이고 완료 안내는 없다. 저장 중에는 폼이 aria-busy다", async () => {
    let release: () => void = () => {};
    server.use(
      http.post("*/api/profiles", async () => {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json({ code: "INVALID_REQUEST", fields: ["label"] }, { status: 422 });
      }),
    );
    const { user } = setup();
    await login(user);
    await consent(user, { health: false });
    await user.click(screen.getByTestId("add-self"));
    await user.type(screen.getByLabelText("이름(별명)"), "나");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(modal().querySelector("form")!).toHaveAttribute("aria-busy", "true"));
    expect(screen.getByTestId("profile-save")).toBeDisabled();
    release();
    await waitFor(() => expect(screen.getByTestId("account-error")).toHaveTextContent(copy.ERROR_INVALID_REQUEST));
    expect(step()).toBe("profile-form");
    expect(screen.getByTestId("account-error")).toHaveAttribute("role", "alert");
    expect(notice()).toBeNull();
    expect(modal().querySelector("form")!).toHaveAttribute("aria-busy", "false");
  });
});

describe("본인 프로필 이름 초기값 = 카카오 닉네임(FE-04-28 B, 2026-11-22)", () => {
  const nameField = () => screen.getByLabelText("이름(별명)");
  /** 목이 받은 프로필 쓰기 요청의 본문(저장 전에는 비어 있어야 한다) */
  let written: { method: string; label: unknown }[] = [];
  beforeEach(() => {
    written = [];
    server.use(
      http.post("*/api/profiles", async ({ request }) => {
        const body = (await request.clone().json()) as { label?: unknown };
        written.push({ method: "POST", label: body.label });
        return HttpResponse.json(
          { profile_id: "00000000-0000-4000-8000-000000000077", relation: "self", label: String(body.label), age_band: null, sex: null, pregnancy_status: null, avatar_color: "yellow", sort_order: 0, medications: [] } satisfies Profile,
          { status: 201 },
        );
      }),
    );
  });

  async function loginWith(user: ReturnType<typeof userEvent.setup>, name: "카카오 로그인" | "Google로 계속하기") {
    await user.click(screen.getByRole("button", { name: "프로필 저장" }));
    await user.click(screen.getByRole("button", { name }));
    await waitFor(() => expect(step()).toBe("consent"));
    await waitFor(() => expect(modal().querySelectorAll('[data-testid="legal-doc"]')).toHaveLength(4));
    await consent(user, { health: false });
  }

  it("카카오 로그인 → 본인 프로필 만들기: 이름 칸에 닉네임이 미리 들어 있고, 그때까지 프로필 쓰기 요청은 없다. 그대로 저장하면 그 값이 간다", async () => {
    const { user } = setup();
    await loginWith(user, "카카오 로그인");
    await user.click(screen.getByTestId("add-self"));
    await waitFor(() => expect(nameField()).toHaveValue(MOCK_KAKAO_NICKNAME));
    expect(screen.getByLabelText("성별")).toHaveValue(""); // 다른 칸은 공급자 정보로 채우지 않는다
    expect(screen.getByLabelText("연령대")).toHaveValue("");
    expect(written).toEqual([]); // 저장 전에는 서버로 가지 않는다
    expect(setItem).not.toHaveBeenCalled(); // 닉네임을 브라우저 저장소에 남기지 않는다
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(written).toEqual([{ method: "POST", label: MOCK_KAKAO_NICKNAME }]);
  });

  it("사용자가 고친 값이 우선이다: 고치면 고친 값이, 지우면 빈 값이 남고(초기값으로 되돌아가지 않는다) 저장 요청에는 폼에 남은 값만 간다", async () => {
    const { user } = setup();
    await loginWith(user, "카카오 로그인");
    await user.click(screen.getByTestId("add-self"));
    await waitFor(() => expect(nameField()).toHaveValue(MOCK_KAKAO_NICKNAME));
    await user.clear(nameField());
    expect(nameField()).toHaveValue("");
    await user.click(screen.getByTestId("profile-save"));
    expect(screen.getByRole("alert")).toHaveTextContent(copy.ERROR_NAME_EMPTY); // 지운 채 저장하면 기존 검증 그대로
    expect(written).toEqual([]);
    await user.type(nameField(), "나");
    expect(nameField()).toHaveValue("나");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(written).toEqual([{ method: "POST", label: "나" }]);
  });

  it("초기값이 늦게 와도 그 전에 적은 값을 덮지 않는다", async () => {
    let finish: (value: string | null) => void = () => {};
    const { user } = setup(createAccountStore({ api: { ...accountApi, fetchSelfNameDefault: () => new Promise((resolve) => (finish = resolve)) } }));
    await loginWith(user, "카카오 로그인");
    await user.click(screen.getByTestId("add-self"));
    expect(nameField()).toHaveValue("");
    await user.type(nameField(), "나");
    finish(MOCK_KAKAO_NICKNAME);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(nameField()).toHaveValue("나");
  });

  it("Google 로그인은 비어 있다(구글 실명은 가져오지 않는다)", async () => {
    const { user } = setup();
    await loginWith(user, "Google로 계속하기");
    await user.click(screen.getByTestId("add-self"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(nameField()).toHaveValue("");
  });

  it("가족 프로필 추가와 본인 프로필 수정은 비어 있거나 저장된 값이다(닉네임을 읽지 않는다)", async () => {
    const read = vi.fn(accountApi.fetchSelfNameDefault);
    const { user } = setup(createAccountStore({ api: { ...accountApi, fetchSelfNameDefault: read } }));
    await loginWith(user, "카카오 로그인");
    await user.click(screen.getByTestId("add-family"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(nameField()).toHaveValue("");
    expect(read).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: copy.CANCEL_LABEL }));
    await user.click(await screen.findByTestId("add-self"));
    await waitFor(() => expect(nameField()).toHaveValue(MOCK_KAKAO_NICKNAME));
    await user.clear(nameField());
    await user.type(nameField(), "본인");
    await user.click(screen.getByTestId("profile-save"));
    await waitFor(() => expect(step()).toBe("profiles"));
    expect(read).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "본인 수정" }));
    expect(nameField()).toHaveValue("본인"); // 저장된 값. 닉네임으로 바꾸지 않는다
    expect(read).toHaveBeenCalledTimes(1);
  });
});
