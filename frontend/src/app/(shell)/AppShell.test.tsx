import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { PREGNANCY_SAVE_CONSENT_HINT } from "@/features/chat";
import { INPUT_COMBINED_NOTICE } from "@/features/chat/copy";
import { PREGNANCY_PICK_HINT } from "@/features/result";
import { CONSENT_DOC_TYPES, HEALTH_CONSENT_DOC } from "@/lib/api/account";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { createAccountHandlers, mockSession } from "@/mocks/account-handlers";
import type { AccountMockState } from "@/mocks/account-handlers";
import { API_NO_CODE_NOTE, PHRASES } from "@/mocks/fixtures/phrases";
import { handlers } from "@/mocks/handlers";
import { createPhotoHandlers } from "@/mocks/photo-handlers";
import { createAccountStore } from "@/stores/account";
import { createChatStore } from "@/stores/chat";
import { AppShell } from "./AppShell";
import { SYNTHETIC_DEMO_NOTICE } from "./copy";

// 화면 조립(AppShell)을 MSW 목(대화 + 계정)에 붙여 본다(실제 서버 호출 0). GROUP-01 5a(FE-11, 2026-11-20):
// - F3(FE-11-10 A): 본문 고지 개수 고정 — "실시간 확인" 0회(근거 상세에만), 안전 고지 1회, 법적 고지 1회, 입력창 고지 1회
// - F2(FE-11-12 A·13·14 A): 입력창 안 임신 여부 토글 → 요청 `context.pregnant`(일반인 false·임산부 true), 프로필 연동(PATCH)·동의 없음·게스트 안내
// - FE-11-03 A: 일반인으로 받은 결과 아래 "임부금기는 '임산부'를 고르면 확인해요" 한 줄

const server = setupServer();
const NOW = "2026-11-18T00:00:00Z";
const SELF_ID = "00000000-0000-4000-8000-000100009001";
const CHILD_ID = "00000000-0000-4000-8000-000100009002";

/** 요청 본문 기록: `/api/chat`과 프로필 PATCH */
let chatBodies: { question: string; context: { pregnant: boolean | null; age: unknown } }[] = [];
let patches: { path: string; body: unknown }[] = [];

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", async ({ request }) => {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname.endsWith("/api/chat")) chatBodies.push(await request.clone().json());
    if (request.method === "PATCH") patches.push({ path: url.pathname, body: await request.clone().json() });
  });
});
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "enabled");
  chatBodies = [];
  patches = [];
});
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());

/** 로그인·동의·프로필이 끝난 목 세션: 동의 대상 문서 전부(건강 정보 동의만 선택)에 동의한 상태 */
function onboardedSession(healthConsent: boolean, selfPregnancy: "pregnant" | "not_pregnant" | null = "not_pregnant"): NonNullable<AccountMockState["session"]> {
  const agree = { action: "agree" as const, version: 1, acted_at: NOW };
  return {
    provider: "email",
    step: "family",
    completedAt: null,
    consents: Object.fromEntries(CONSENT_DOC_TYPES.filter((docType) => healthConsent || docType !== HEALTH_CONSENT_DOC).map((docType) => [docType, agree])),
    profiles: [
      { profile_id: SELF_ID, relation: "self", label: "나", age_band: "y19_64", sex: null, pregnancy_status: selfPregnancy, avatar_color: "yellow", sort_order: 0, medications: [] },
      { profile_id: CHILD_ID, relation: "child", label: "첫째", age_band: "y6_11", sex: null, pregnancy_status: null, avatar_color: "yellow", sort_order: 1, medications: [] },
    ],
  };
}

function setWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
}

function setup({ session = null, width = 1280 }: { session?: AccountMockState["session"]; width?: number } = {}) {
  const state: AccountMockState = { session };
  server.use(...handlers, ...createAccountHandlers(state));
  setWidth(width);
  const store = createChatStore();
  const account = createAccountStore();
  const user = userEvent.setup();
  render(<AppShell store={store} account={account} />);
  return { store, account, user, state };
}

const main = () => screen.getByTestId("main");
const toggle = () => screen.getByRole("radiogroup", { name: "임신 여부" });
const radio = (name: "일반인" | "임산부") => within(toggle()).getByRole("radio", { name });
const checkedLabel = () => within(toggle()).getAllByRole("radio").find((el) => el.getAttribute("aria-checked") === "true")?.textContent;
const count = (text: string, scope: HTMLElement = main()) => (scope.textContent?.match(new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) ?? []).length;

/** 입력창 프로필 칩을 눌러 위로 열린 목록에서 대상을 고른다(2026-11-23: 본문 "누가 먹나요" 선택 줄 대신). 고르면 목록이 닫힌다 */
async function pickTarget(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByTestId("target-chip"));
  const menu = await screen.findByTestId("target-menu");
  await user.click(within(menu).getByRole("menuitemradio", { name }));
  await waitFor(() => expect(screen.queryByTestId("target-menu")).toBeNull());
}

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  const before = screen.queryAllByTestId("result-card").length;
  await user.type(screen.getByRole("textbox"), question);
  await user.click(screen.getByRole("button", { name: "보내기" }));
  await waitFor(() => expect(screen.getAllByTestId("result-card")).toHaveLength(before + 1));
}

describe("F3 고지 개수(FE-11-10 A)", () => {
  it.each([1280, 393])("%ipx 시작 화면(게스트): 외부 AI 전송 고지는 입력창 고지 1회뿐이다(PRD-17-10 A: 시작 화면 고지 삭제)", async (width) => {
    setup({ width });
    const body = await screen.findByTestId("main");
    expect(screen.queryByTestId("start-emergency")).toBeNull(); // 시작 화면 119 줄은 없다(FE-17 U-04)
    expect(document.querySelectorAll('a[href="tel:119"]')).toHaveLength(1); // 평상시 119는 머리줄 하나
    expect(screen.getByTestId("emergency-entry")).toHaveAttribute("href", "tel:119");
    expect(screen.queryByTestId("external-ai-notice")).toBeNull();
    expect(within(body).getAllByTestId("input-combined-notice")).toHaveLength(1); // 입력창 아래 통합 고지 하나(FE-17 U-02)
    expect(within(body).queryByTestId("input-notice")).toBeNull();
    expect(within(body).queryByTestId("legal-footer")).toBeNull();
    expect(count("외부 AI", body)).toBe(1);
    expect(count("OpenAI", body)).toBe(1);
    expect(count("외부 AI", document.body)).toBe(1);
  });

  it("U-26-1(2026-11-24): 고정 안내는 입력창 위(고정 영역)에 없고 답 아래에 있으며, 질문을 두 번 해도 같은 문장은 가장 최근 답 아래 한 번만 남는다(하네스 고정 문구 유지)", async () => {
    const { user } = setup({ width: 393 });
    await ask(user, "가나다정 먹어도 돼요");
    expect(within(screen.getByTestId("dock")).queryByTestId("fixed-notice")).toBeNull();
    expect(count(FIXED_NOTICE, main())).toBe(1);
    await ask(user, "라마바캡슐 먹어도 돼요");
    const [first, second] = [...main().querySelectorAll<HTMLElement>("[data-turn]")];
    expect(within(first).queryByTestId("fixed-notice")).toBeNull();
    expect(within(second).getByTestId("fixed-notice").textContent).toContain(FIXED_NOTICE);
    expect(count(FIXED_NOTICE, main())).toBe(1); // 결과 화면에 적어도(정확히) 한 번
    expect(within(screen.getByTestId("dock")).queryByTestId("fixed-notice")).toBeNull();
  });

  it("1280: 실시간 확인 실패 응답에서 본문은 '실시간 확인' 0회·안전 고지 1회·법적 고지 1회·입력창 고지 1회이고, 자동으로 열린 근거 상세에만 배너·줄 노트가 있다", async () => {
    const { user } = setup({ width: 1280 });
    await ask(user, "mock:실시간실패 가나다정");
    const body = main();
    expect(count("실시간 확인", body)).toBe(0);
    expect(count(PHRASES.NOTICE_API_FAIL, body)).toBe(0);
    expect(count(API_NO_CODE_NOTE, body)).toBe(0);
    expect(count(FIXED_NOTICE, body)).toBe(1);
    // 법적 고지는 입력창 아래 통합 고지 한 단락에 합쳤다(FE-17 U-02): 통합 고지 1회, 따로 떨어진 법적 고지 줄은 없다
    expect(count(INPUT_COMBINED_NOTICE, body)).toBe(1);
    expect(count(DISCLAIMER, body)).toBe(0);
    expect(within(body).getAllByTestId("input-combined-notice")).toHaveLength(1);
    expect(within(body).queryByTestId("result-notice")).toBeNull();
    // 기대값 갱신(2026-11-24, FE-17 U-26-3 "'기준일 자료' 제거"): 결과 카드 머리 표지는 없다. 기준일 안내 문장은 아래 근거 상세 맨 위에 그대로다
    expect(within(body).queryByTestId("basis-file-tag")).toBeNull();
    expect(count("기준일 자료", body)).toBe(0);
    // 넓은 폭은 판정 줄이 있는 답이 오면 근거 상세 패널이 열린다: 배너 1 + 줄 노트 1
    const panel = await screen.findByTestId("panel-column");
    expect(within(panel).getByTestId("evidence-api-fail-notice").textContent).toBe(PHRASES.NOTICE_API_FAIL);
    expect(count(API_NO_CODE_NOTE, panel)).toBe(1);
    expect(count("실시간 확인", panel)).toBe(2);
    expect(count(FIXED_NOTICE, panel)).toBe(0);
  });

  it("393: 본문은 같은 개수이고 근거 상세 시트를 열어야 배너가 보인다. 상한 도달 배너는 본문에 그대로", async () => {
    const { user } = setup({ width: 393 });
    await ask(user, "mock:실시간실패 가나다정");
    expect(count("실시간 확인", document.body)).toBe(0); // 시트는 닫혀 있어 그리지 않는다
    expect(count(FIXED_NOTICE)).toBe(1);
    expect(count(INPUT_COMBINED_NOTICE)).toBe(1);
    expect(count(DISCLAIMER)).toBe(0);
    expect(screen.getAllByTestId("input-combined-notice")).toHaveLength(1);
    await user.click(screen.getByTestId("evidence-entry"));
    const sheet = await screen.findByRole("dialog", { name: "근거 상세" });
    expect(within(sheet).getByTestId("evidence-api-fail-notice").textContent).toBe(PHRASES.NOTICE_API_FAIL);
    expect(count("실시간 확인", sheet)).toBe(2);
    await user.keyboard("{Escape}");
    await ask(user, "mock:상한 가나다정");
    const second = screen.getAllByTestId("result-view")[1];
    expect(within(second).getByTestId("result-notice").textContent).toBe(PHRASES.LIMIT_REACHED);
    expect(within(second).queryByTestId("basis-file-tag")).toBeNull();
  });
});

describe("F2 임신 여부 토글(게스트, FE-11-12 A·14 A·FE-11-03 A)", () => {
  it("게스트는 일반인으로 시작해 context.pregnant=false를 보내고, 결과 아래 '임산부를 고르면 확인' 한 줄이 있다. 임산부로 바꾸면 true를 보내고 한 줄은 없다", async () => {
    const { user } = setup({ width: 393 });
    expect(checkedLabel()).toBe("일반인");
    expect(screen.queryByTestId("target-chip")).toBeNull(); // 게스트는 프로필 칩이 없다(배치는 로그인과 같다, FE-17 U-09)
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context).toMatchObject({ pregnant: false, age: null });
    const hint = screen.getByTestId("pregnancy-pick-hint");
    expect(hint.textContent).toBe(PREGNANCY_PICK_HINT);
    expect(hint.textContent).toBe("임부금기는 '임산부'를 고르면 확인해요");
    expect(screen.queryByTestId("not-checked-lines")).toBeNull(); // 점선 상자는 임산부 + 확인 못 함일 때만(서버 줄)
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    // 게스트: 저장하지 않고 이 대화에만 적용, 토글 근처 안내 한 줄(초안 글자)
    expect(screen.getByTestId("pregnancy-hint").textContent).toBe(PREGNANCY_SAVE_CONSENT_HINT);
    expect(patches).toEqual([]);
    await ask(user, "mock:임부 가나다정");
    expect(chatBodies[1].context.pregnant).toBe(true);
    const turns = screen.getAllByTestId("turn-answer");
    expect(within(turns[0]).getByTestId("pregnancy-pick-hint")).toBeInTheDocument(); // 지난 차례의 줄은 그대로
    expect(within(turns[1]).queryByTestId("pregnancy-pick-hint")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();
  });

  it("새 질문(새 대화)을 시작하면 토글은 다시 일반인이고 안내는 사라진다", async () => {
    const { user, store } = setup({ width: 1280 });
    await user.click(radio("임산부"));
    expect(store.getState().context.pregnant).toBe(true);
    expect(screen.getByTestId("pregnancy-hint")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "새 질문" }));
    expect(checkedLabel()).toBe("일반인");
    expect(store.getState().context.pregnant).toBe(false);
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
  });
});

describe("F2 임신 여부 토글(로그인, FE-11-13·14 A)", () => {
  it("건강 정보 동의 + 대상 프로필: 토글을 바꾸면 그 프로필의 pregnancy_status만 PATCH(양방향)하고 프로필 화면에 바뀐 값이 보인다. 대상을 바꾸면 그 프로필 값으로 시작한다", async () => {
    const { user, account, state } = setup({ session: onboardedSession(true, "not_pregnant"), width: 1280 });
    await screen.findByTestId("target-chip");
    expect(checkedLabel()).toBe("일반인"); // 대상을 고르기 전
    await pickTarget(user, "나");
    expect(checkedLabel()).toBe("일반인"); // 프로필 not_pregnant
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ path: `/api/profiles/${SELF_ID}`, body: { pregnancy_status: "pregnant" } });
    await waitFor(() => expect(account.getState().profiles.find((profile) => profile.profile_id === SELF_ID)?.pregnancy_status).toBe("pregnant"));
    expect(state.session?.profiles.find((profile) => profile.profile_id === SELF_ID)?.pregnancy_status).toBe("pregnant");
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    expect(screen.queryByTestId("pregnancy-save-error")).toBeNull();
    // 프로필 화면(계정 모달)에서 바뀐 값이 보인다: 계정 메뉴(버튼 → 팝오버)의 `프로필 관리`
    await user.click(screen.getByTestId("account-menu-button"));
    await user.click(screen.getByTestId("account-entry"));
    const modal = await screen.findByTestId("account-modal");
    expect(within(modal).getAllByTestId("profile-item")[0].textContent).toContain("임신 여부 예");
    await user.click(within(modal).getByRole("button", { name: "닫기" }));
    // 양방향: 일반인으로 돌리면 not_pregnant
    await user.click(radio("일반인"));
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1].body).toEqual({ pregnancy_status: "not_pregnant" });
    await waitFor(() => expect(account.getState().profiles[0].pregnancy_status).toBe("not_pregnant"));
    // 질문에는 토글 값과 대상의 나이가 실린다
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context).toMatchObject({ pregnant: false, age: { lower: 19, upper: 64, unit: "세" } });
    // 임신 중으로 저장된 프로필을 고르면 임산부로 시작한다(§7.1 규칙 ①·②)
    await user.click(radio("임산부"));
    await waitFor(() => expect(account.getState().profiles[0].pregnancy_status).toBe("pregnant"));
    await pickTarget(user, "첫째");
    expect(checkedLabel()).toBe("일반인");
    await pickTarget(user, "나");
    expect(checkedLabel()).toBe("임산부");
    expect(patches).toHaveLength(3); // 대상 변경은 저장하지 않는다
  });

  it("건강 정보 동의가 없으면 PATCH 없이 이 대화에만 적용하고 안내 한 줄을 둔다(422를 받아도 같은 동작)", async () => {
    const { user, state } = setup({ session: onboardedSession(false), width: 1280 });
    await screen.findByTestId("target-chip");
    await pickTarget(user, "나");
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    expect(screen.getByTestId("pregnancy-hint").textContent).toBe(PREGNANCY_SAVE_CONSENT_HINT);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
    expect(patches).toEqual([]);
    expect(state.session?.profiles[0].pregnancy_status).toBe("not_pregnant");
    // 대상을 바꾸면 안내는 사라지고 토글은 그 프로필 값(없음 → 일반인)으로 돌아간다
    await pickTarget(user, "첫째");
    expect(checkedLabel()).toBe("일반인");
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    // 서버가 422 HEALTH_CONSENT_REQUIRED를 주는 경우는 아래 "저장 실패" 시험이 본다
  });

  it("저장이 다른 이유로 실패하면 대화 값은 유지하고 짧은 오류 안내를 보인다", async () => {
    const { user, account, state } = setup({ session: onboardedSession(true), width: 1280 });
    await screen.findByTestId("target-chip");
    await pickTarget(user, "나");
    server.use(http.patch("*/api/profiles/:profileId", () => HttpResponse.json({ code: "ACCOUNT_UNAVAILABLE", fields: [] }, { status: 503 })));
    await user.click(radio("임산부"));
    const error = await screen.findByTestId("pregnancy-save-error");
    expect(error.textContent).toBe("지금은 계정 정보를 불러오거나 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.");
    expect(error.getAttribute("role")).toBe("alert");
    expect(checkedLabel()).toBe("임산부"); // 대화 값 유지
    expect(account.getState().profiles[0].pregnancy_status).toBe("not_pregnant");
    expect(state.session?.profiles[0].pregnancy_status).toBe("not_pregnant");
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
    // 서버가 422 HEALTH_CONSENT_REQUIRED를 주면 오류가 아니라 동의 안내다(FE-11-14 A)
    server.use(http.patch("*/api/profiles/:profileId", () => HttpResponse.json({ code: "HEALTH_CONSENT_REQUIRED", fields: ["pregnancy_status"] }, { status: 422 })));
    await user.click(radio("일반인"));
    expect(await screen.findByTestId("pregnancy-hint")).toHaveTextContent(PREGNANCY_SAVE_CONSENT_HINT);
    expect(screen.queryByTestId("pregnancy-save-error")).toBeNull();
    expect(checkedLabel()).toBe("일반인");
  });
});

describe("대상 프로필 한 값(2026-11-23): 계정 버튼·입력창 칩·요청 context가 같이 바뀐다, 본문 선택 줄 없음", () => {
  it("로그인 직후 본인이 기본 대상이고(FE-17 U-06), 계정 버튼 메뉴의 `프로필 관리` 아래 목록에서 고르면 버튼이 병아리 + 이름이 되고 입력창 칩도 같은 프로필이며, 요청에는 예전과 같은 값(연령대)만 실린다", async () => {
    const { user, account } = setup({ session: onboardedSession(true), width: 1280 });
    const chip = await screen.findByTestId("target-chip");
    const button = screen.getAllByTestId("account-menu-button")[0];
    expect(screen.queryByRole("radiogroup", { name: "누가 먹나요" })).toBeNull(); // 본문 선택 줄은 없다
    // 고르기 전에도 본인(나)이 대상이라 계정 버튼에 선택된 프로필이 보인다('로그인됨'이 아니다)
    expect(account.getState().targetProfileId).toBe(SELF_ID);
    expect(button).toHaveTextContent("나");
    expect(button).not.toHaveTextContent("로그인됨");
    expect(within(button).getByTestId("profile-avatar")).toBeInTheDocument();
    expect(chip).toHaveAccessibleName("누가 먹나요 나");
    await user.click(button);
    const menu = await screen.findByTestId("account-menu");
    const items = within(menu).getAllByRole("menuitemradio").map((item) => item.textContent);
    expect(items.slice(0, 3)).toEqual(["게스트로 이용", "나", "첫째"]);
    const manage = within(menu).getByRole("menuitem", { name: "프로필 관리" }); // 기존 계정 메뉴 항목과 같은 층
    expect(manage.compareDocumentPosition(within(menu).getByRole("group", { name: "누가 먹나요" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // 목록은 프로필 관리 아래
    await user.click(within(menu).getByRole("menuitemradio", { name: "첫째" }));
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
    expect(account.getState().targetProfileId).toBe(CHILD_ID);
    expect(button).toHaveTextContent("첫째");
    expect(within(button).getByTestId("profile-avatar")).toBeInTheDocument();
    expect(chip).toHaveAccessibleName("누가 먹나요 첫째");
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context).toMatchObject({ age: { lower: 6, upper: 11, unit: "세" } });
    expect(JSON.stringify(chatBodies[0])).not.toMatch(/avatar|첫째/); // 색·이름은 요청에 싣지 않는다
    // 입력창 칩에서 바꾸면 계정 버튼도 바뀐다. '게스트로 이용'(프로필 값 없이)을 고르면 칩도 계정 버튼도 게스트 모드 표시(FE-17 U-21이 U-06의 `로그인됨`을 대체):
    // 색 없는 점선 원 병아리 + `게스트로 이용`. 비로그인의 `계정`과 다르고, 로그인 상태는 메뉴 안의 `프로필 관리`·`로그아웃`으로 구분된다
    await pickTarget(user, "나");
    expect(button).toHaveTextContent("나");
    await pickTarget(user, "게스트로 이용");
    expect(chip).toHaveAccessibleName("누가 먹나요 게스트로 이용");
    expect(button).toHaveTextContent("게스트로 이용");
    expect(button).toHaveAttribute("data-target", "guest");
    expect(within(button).getByTestId("profile-avatar")).toHaveAttribute("data-color", "none");
    expect(button).not.toHaveTextContent("로그인됨");
    expect(button).not.toHaveTextContent("계정");
    await user.click(button);
    const guestMenu = await screen.findByTestId("account-menu");
    expect(within(guestMenu).getByRole("menuitem", { name: "프로필 관리" })).toBeInTheDocument();
    expect(within(guestMenu).getByRole("menuitem", { name: "로그아웃" })).toBeInTheDocument();
    expect(within(guestMenu).queryByRole("menuitem", { name: "로그인/가입" })).toBeNull();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("account-menu")).toBeNull());
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[1].context).toMatchObject({ age: null });
  });
});

describe("시작 화면 기본 대상 안내·기본 대상 저장(FE-17 U-08)", () => {
  it("로그인 + 프로필이면 병아리 이미지 아래에 지금 대상과 `게스트로 이용`이 보이고, 누르면 대상·서버 기본 대상이 바뀌며 초점은 질문 칸이다. 대화가 시작되면 안내는 없다", async () => {
    const { user, account, state } = setup({ session: onboardedSession(true), width: 393 });
    const notice = await screen.findByTestId("start-target");
    const home = screen.getByTestId("home");
    expect(home.contains(notice)).toBe(true);
    // 시작 화면 병아리(HomeHero) 뒤에 있다
    const hero = within(home).getByRole("heading", { level: 1 });
    expect(hero.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(notice).getByTestId("start-target-heading")).toHaveTextContent("나 프로필로 확인해요");
    expect(within(notice).getByTestId("start-target-lead")).toHaveTextContent("연령대·임신 여부가 답변에 쓰여요");
    expect(notice.textContent).not.toMatch(/안전/);
    // FE-17 U-11: 카드·아바타·버튼 모양 없이 `<p>` 한 단락 문장(통합 고지와 같은 글자 모양), `게스트로 이용`은 밑줄 링크 모양의 버튼
    // FE-17 U-23: 링크는 세 번째 문장 **중간**에 있다(사용자 지정 문구와 글자·문장 부호까지 같다)
    expect(notice.tagName).toBe("P");
    expect(notice.textContent).toBe("나 프로필로 확인해요. 이 프로필의 연령대·임신 여부가 답변에 쓰여요. 프로필 없이 질문을 이어가시려면 게스트로 이용으로 프로필을 변경해주세요.");
    expect(within(notice).queryByTestId("profile-avatar")).toBeNull();
    const combined = screen.getByTestId("input-combined-notice");
    for (const token of ["text-xs", "leading-[17px]", "text-mute"]) expect(notice.className.split(" "), token).toContain(token);
    for (const token of ["text-xs", "leading-[17px]", "text-mute"]) expect(combined.className.split(" "), token).toContain(token);
    const link = within(notice).getByRole("button", { name: "게스트로 이용" });
    expect(link.className).toContain("underline");
    expect(link.className).not.toMatch(/(^| )(border|bg-|min-h-11)/);
    expect(link.parentElement?.textContent).toBe("프로필 없이 질문을 이어가시려면 게스트로 이용으로 프로필을 변경해주세요."); // 문장 중간(U-23)
    expect(link.nextSibling?.textContent).toBe("으로 프로필을 변경해주세요.");
    await user.click(within(notice).getByRole("button", { name: "게스트로 이용" }));
    expect(account.getState()).toMatchObject({ targetProfileId: null, targetChosen: true });
    expect(within(notice).getByTestId("start-target-heading")).toHaveTextContent("게스트로 이용 중이에요");
    // FE-17 U-22: 게스트 상태 문장은 "…질문해요." 뒤에 `변경` 링크 하나(U-08의 "버튼 없음"을 대체)
    expect(notice.textContent).toBe("게스트로 이용 중이에요. 저장한 프로필 값 없이 질문해요. 변경");
    expect(within(notice).getAllByRole("button").map((el) => el.textContent)).toEqual(["변경"]);
    expect(screen.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 게스트로 이용");
    expect(document.activeElement).toBe(screen.getByRole("textbox"));
    await waitFor(() => expect(state.session?.defaultTarget).toBe("guest"));
    // 칩에서 다시 고르면 안내도 같은 값
    await pickTarget(user, "첫째");
    expect(within(screen.getByTestId("start-target")).getByTestId("start-target-heading")).toHaveTextContent("첫째 프로필로 확인해요");
    await waitFor(() => expect(state.session?.defaultTarget).toBe(CHILD_ID));
    // 안내를 무시하고 질문하면 고른 대상 그대로(요청 계약 불변). 대화가 시작되면 안내는 그리지 않는다
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context).toMatchObject({ age: { lower: 6, upper: 11, unit: "세" } });
    expect(JSON.stringify(chatBodies[0])).not.toMatch(/default_target|guest/);
    expect(screen.queryByTestId("start-target")).toBeNull();
  });

  it("게스트 상태 안내의 `변경`은 입력창 칩과 같은 프로필 목록을 열고(첫 항목 초점), 고르면 대상·서버 기본 대상이 바뀌고 초점은 질문 칸, Esc는 `변경`으로 돌아온다(FE-17 U-22)", async () => {
    const session = { ...onboardedSession(true), defaultTarget: "guest" };
    const { user, account, state } = setup({ session, width: 393 });
    const notice = await screen.findByTestId("start-target");
    expect(notice).toHaveAttribute("data-target", "guest");
    const change = within(notice).getByRole("button", { name: "변경" });
    expect(change.className).toContain("underline");
    expect(change.className).not.toMatch(/(^| )(border|bg-|min-h-11)/);
    expect(change).toHaveAttribute("aria-haspopup", "menu");
    expect(change).toHaveAttribute("aria-expanded", "false");
    // 키보드로 연다 → 칩과 같은 목록(게스트로 이용 · 본인 · 가족), 첫 항목에 초점. Esc로 닫으면 초점은 `변경`
    change.focus();
    await user.keyboard("{Enter}");
    const menu = await screen.findByTestId("start-target-menu");
    expect(within(menu).getAllByRole("menuitemradio").map((item) => item.textContent)).toEqual(["게스트로 이용", "나", "첫째"]);
    expect(within(menu).getByRole("group", { name: "누가 먹나요" })).toBeInTheDocument();
    await waitFor(() => expect(within(menu).getAllByRole("menuitemradio")[0]).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("start-target-menu")).toBeNull());
    await waitFor(() => expect(change).toHaveFocus());
    expect(account.getState().targetProfileId).toBeNull();
    // 눌러서 열고 가족을 고른다 → 대상·칩·안내가 같이 바뀌고 서버 기본 대상 저장, 초점은 질문 칸
    await user.click(change);
    await user.click(within(await screen.findByTestId("start-target-menu")).getByRole("menuitemradio", { name: "첫째" }));
    expect(account.getState()).toMatchObject({ targetProfileId: CHILD_ID, targetChosen: true });
    expect(within(screen.getByTestId("start-target")).getByTestId("start-target-heading")).toHaveTextContent("첫째 프로필로 확인해요");
    expect(screen.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 첫째");
    await waitFor(() => expect(state.session?.defaultTarget).toBe(CHILD_ID));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox")));
    expect(screen.queryByTestId("start-target-menu")).toBeNull();
  });

  it("새 세션은 서버 저장값으로 시작한다(`guest` → 게스트로 이용 안내). 게스트(비로그인)에는 안내가 없다", async () => {
    const session = { ...onboardedSession(true), defaultTarget: "guest" };
    setup({ session, width: 1280 });
    const notice = await screen.findByTestId("start-target");
    expect(notice).toHaveAttribute("data-target", "guest");
    expect(screen.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 게스트로 이용");
    cleanup();
    setup({ session: null, width: 1280 });
    await screen.findByTestId("entry-choice");
    expect(screen.queryByTestId("start-target")).toBeNull();
  });
});

describe("GROUP-03 3단계 성별 숨김(FE-11-09 C·FE-11-12 A)", () => {
  /** 본인은 남성, 첫째는 여성(둘 다 건강 정보 동의 범위 안의 임신 값 포함) */
  function sexedSession(healthConsent: boolean, { selfSex, childSex, selfPregnancy = null as "pregnant" | "not_pregnant" | null }: { selfSex: "male" | "female" | null; childSex: "male" | "female" | null; selfPregnancy?: "pregnant" | "not_pregnant" | null }) {
    const session = onboardedSession(healthConsent, selfPregnancy);
    session.profiles = session.profiles.map((profile) => (profile.profile_id === SELF_ID ? { ...profile, sex: selfSex } : { ...profile, sex: childSex, pregnancy_status: "pregnant" }));
    return session;
  }
  const toggleOrNull = () => screen.queryByRole("radiogroup", { name: "임신 여부" });
  const form = () => screen.getByRole("textbox").closest("form")!;

  it("남성 프로필이 대상이면 토글이 없고 context.pregnant=false를 보낸다. 저장 값이 임신이어도 같다. '게스트로 이용'과 게스트는 보인다", async () => {
    const { user, store } = setup({ session: sexedSession(true, { selfSex: "male", childSex: "female", selfPregnancy: "pregnant" }), width: 1280 });
    await screen.findByTestId("target-chip");
    expect(toggleOrNull()).toBeNull(); // 로그인 직후 본인(남성)이 기본 대상(FE-17 U-06)
    await pickTarget(user, "게스트로 이용");
    expect(toggleOrNull()).not.toBeNull(); // 대상 없음(게스트로 이용)은 보인다
    const formBefore = form();
    await pickTarget(user, "나");
    expect(toggleOrNull()).toBeNull();
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    expect(screen.queryByTestId("pregnancy-save-error")).toBeNull();
    expect(form()).toBe(formBefore); // 입력창 틀은 그대로다(토글만 빠진다)
    expect(store.getState().context.pregnant).toBe(false);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context).toMatchObject({ pregnant: false, age: { lower: 19, upper: 64, unit: "세" } });
    expect(JSON.stringify(chatBodies[0])).not.toMatch(/sex|gender|male/);
    expect(patches).toEqual([]); // 토글이 없으니 저장도 없다
  });

  it("가족 프로필을 고르면 그 프로필의 성별을 따른다: 남성(숨김) → 여성(보임, 임신 값으로 시작) → 남성(다시 숨김, false)", async () => {
    const { user, store } = setup({ session: sexedSession(true, { selfSex: "male", childSex: "female" }), width: 1280 });
    await screen.findByTestId("target-chip");
    await pickTarget(user, "나");
    expect(toggleOrNull()).toBeNull();
    await pickTarget(user, "첫째");
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("임산부"); // 첫째는 임신으로 저장돼 있다(§7.1 규칙 ①)
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
    await pickTarget(user, "나");
    expect(toggleOrNull()).toBeNull();
    expect(store.getState().context.pregnant).toBe(false);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[1].context.pregnant).toBe(false);
    // 게스트로 이용으로 돌아가면 다시 보이고 일반인이다
    await pickTarget(user, "게스트로 이용");
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("일반인");
  });

  it("여성·성별 미입력 프로필과 게스트는 토글이 보이고 동작한다(동의 없음은 안내 한 줄)", async () => {
    const { user } = setup({ session: sexedSession(false, { selfSex: "female", childSex: null }), width: 393 });
    await screen.findByTestId("target-chip");
    await pickTarget(user, "나"); // 여성
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("일반인");
    await pickTarget(user, "첫째"); // 미입력
    expect(toggleOrNull()).not.toBeNull();
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    expect(screen.getByTestId("pregnancy-hint").textContent).toBe(PREGNANCY_SAVE_CONSENT_HINT);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
  });

  it("게스트는 토글이 보인다", async () => {
    setup({ session: null, width: 393 });
    await screen.findByTestId("app-shell");
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("일반인");
  });
});

describe("사진 입력(FE-05 사진 부분, 〔D5〕·〔D6〕·〔D7〕A)", () => {
  // jsdom에는 createImageBitmap·URL.createObjectURL이 없다: 디코드만 가짜로 두고 파일 읽기(FileReader)·요청·화면은 실제 경로다
  const realCreateObjectURL = URL.createObjectURL;
  const realRevokeObjectURL = URL.revokeObjectURL;
  beforeEach(() => {
    vi.stubGlobal("createImageBitmap", async () => ({ width: 120, height: 90, close: () => {} }));
    URL.createObjectURL = () => "blob:mock-preview";
    URL.revokeObjectURL = () => {};
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    URL.createObjectURL = realCreateObjectURL;
    URL.revokeObjectURL = realRevokeObjectURL;
  });
  const pouch = () => new File([new Uint8Array([1, 2, 3, 4])], "pouch.png", { type: "image/png" });
  type ChatBody = { question: string; context: { confirmed_drugs: unknown[]; prior_drugs: unknown[] } };

  it("입력창 옆 사진 버튼 하나(두 번째 입구 없음) → 모달 → 승인 전 /chat 0회 → `이대로 확인` → /chat 1회(고른 후보만 confirmed_drugs)", async () => {
    const { user } = setup({ width: 393 });
    server.use(...createPhotoHandlers());
    expect(screen.getAllByTestId("photo-entry")).toHaveLength(1);
    expect(main().textContent).not.toContain("약 사진 올리기");
    await user.click(screen.getByTestId("photo-entry"));
    const modal = await screen.findByTestId("photo-modal");
    expect(modal.querySelector('a[href="tel:119"]')).toBeNull(); // 층 안 119 진입점 없음(FE-17 U-04)
    await user.upload(within(modal).getByTestId("photo-file"), pouch());
    const card = await within(modal).findByTestId("photo-confirm-card");
    expect(chatBodies).toHaveLength(0);
    await user.click(within(card).getAllByTestId("photo-candidate")[0]);
    await user.type(within(card).getByTestId("photo-question"), "같이 먹어도 돼요?");
    expect(chatBodies).toHaveLength(0);
    await user.click(within(card).getByTestId("photo-confirm"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    await waitFor(() => expect(chatBodies).toHaveLength(1));
    const body = chatBodies[0] as unknown as ChatBody;
    expect(body.question).toBe("가나다정 100밀리그램, 라마바캡슐 같이 먹어도 돼요?");
    expect(body.context.confirmed_drugs).toEqual([{ name: "가나다정 100밀리그램", item_seq: "200000001", input_name: "가나다정 100밀리그램" }]);
    expect(body.context.prior_drugs).toEqual([]);
    await waitFor(() => expect(screen.getAllByTestId("result-card")).toHaveLength(1));
    // 말풍선에는 승인한 질문이 보인다
    expect(main().textContent).toContain("가나다정 100밀리그램, 라마바캡슐 같이 먹어도 돼요?");
  });

  it("`닫기`는 /chat을 부르지 않고 초점이 사진 버튼으로 돌아온다. `글자로 입력`은 입력창으로 간다", async () => {
    const { user } = setup({ width: 393 });
    server.use(...createPhotoHandlers({ scenario: "unreadable" }));
    await user.click(screen.getByTestId("photo-entry"));
    let modal = await screen.findByTestId("photo-modal");
    await user.click(within(modal).getByRole("button", { name: "닫기" }));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(document.activeElement).toBe(screen.getByTestId("photo-entry"));
    expect(chatBodies).toHaveLength(0);
    await user.click(screen.getByTestId("photo-entry"));
    modal = await screen.findByTestId("photo-modal");
    await user.upload(within(modal).getByTestId("photo-file"), pouch());
    await within(modal).findByTestId("photo-failed");
    await user.click(within(modal).getByTestId("photo-type-instead"));
    await waitFor(() => expect(screen.queryByTestId("photo-modal")).toBeNull());
    expect(document.activeElement).toBe(screen.getByRole("textbox"));
    expect(chatBodies).toHaveLength(0);
  });
});

describe("로그인 콜백 복귀(?auth_resume=1, 2026-11-22 사용자 보고): 온보딩이 남았으면 모달이 그 단계로 다시 열린다", () => {
  const setUrl = (search: string) => window.history.replaceState(null, "", `/${search}`);
  afterEach(() => setUrl(""));

  it("막 로그인한 사용자(동의 전)는 모달이 동의 화면으로 자동으로 열리고, 주소의 표시는 지워진다. 닫으면 다시 열리지 않고 `프로필 관리`에서 같은 단계로 이어 간다", async () => {
    setUrl("?auth_resume=1&keep=1");
    const { user, account } = setup({ session: mockSession("new"), width: 1280 });
    const modal = await screen.findByTestId("account-modal");
    expect(modal).toHaveAttribute("data-step", "consent");
    expect(account.getState().flow).toEqual(["consent"]);
    expect(window.location.search).toBe("?keep=1"); // 복귀 표시만 지운다(다른 값은 그대로)
    expect(screen.queryByTestId("entry-choice")).toBeNull(); // 로그인 상태
    // 닫으면 닫힌 채다(새로고침 없이 아무것도 다시 열지 않는다)
    await user.click(within(modal).getByRole("button", { name: "닫기" }));
    await waitFor(() => expect(screen.queryByTestId("account-modal")).toBeNull());
    await account.getState().bootstrap(); // 상태를 다시 읽어도 열리지 않는다
    expect(screen.queryByTestId("account-modal")).toBeNull();
    // 사이드바 계정 메뉴의 `프로필 관리`에서 이어 간다: 동의가 남았으니 동의 화면
    await user.click(screen.getByTestId("account-menu-button"));
    await user.click(screen.getByRole("menuitem", { name: "프로필 관리" }));
    expect(await screen.findByTestId("account-modal")).toHaveAttribute("data-step", "consent");
  });

  it("동의는 마쳤지만 본인 프로필이 없으면 프로필 화면으로 열린다", async () => {
    const session = mockSession("onboarded");
    session.profiles = [];
    session.step = "consent";
    setUrl("?auth_resume=1");
    setup({ session, width: 393 });
    expect(await screen.findByTestId("account-modal")).toHaveAttribute("data-step", "profiles");
    expect(screen.getByTestId("add-self")).toBeInTheDocument();
  });

  it("온보딩을 마친 사용자는 모달 없이 바로 채팅이다(대상 선택이 보인다)", async () => {
    setUrl("?auth_resume=1");
    setup({ session: mockSession("onboarded"), width: 1280 });
    await screen.findByTestId("target-chip");
    expect(window.location.search).toBe("");
    expect(screen.queryByTestId("account-modal")).toBeNull();
  });

  it("표시가 있어도 세션이 없으면(게스트) 아무것도 열지 않고, 세션이 있어도 표시가 없으면(새로고침·일반 방문) 열지 않는다", async () => {
    setUrl("?auth_resume=1");
    const first = setup({ session: null, width: 393 });
    await screen.findByTestId("entry-choice");
    await waitFor(() => expect(first.account.getState().status).toBe("guest"));
    expect(screen.queryByTestId("account-modal")).toBeNull();
    cleanup();
    setUrl("");
    const second = setup({ session: mockSession("new"), width: 393 });
    await waitFor(() => expect(second.account.getState().status).toBe("member"));
    expect(screen.queryByTestId("account-modal")).toBeNull();
    expect(second.account.getState().flow).toEqual([]);
  });
});

describe("합성 데이터 데모 표시(BE-13-07 A)", () => {
  it("목 모드(NEXT_PUBLIC_API_MOCKING=enabled)에서만 머리줄 아래 승인 원문 한 줄이 보이고, 일반(실서버) 모드에서는 DOM에 없다", () => {
    setup({ width: 393 });
    const notice = screen.getByTestId("demo-notice");
    expect(notice.textContent).toBe(SYNTHETIC_DEMO_NOTICE);
    expect(SYNTHETIC_DEMO_NOTICE).toBe("합성 데이터 데모예요. 화면의 약 이름·판정은 실제 의약품 정보가 아니에요.");
    expect(notice.getAttribute("role")).toBe("note");
    // 머리줄 바로 아래(머리줄의 다음 형제 안)
    const topBar = screen.getByTestId("top-bar");
    expect(topBar.nextElementSibling?.contains(notice)).toBe(true);
    expect(notice.querySelector("img, svg")).toBeNull(); // 마스코트 없음
    expect(screen.getAllByTestId("demo-notice")).toHaveLength(1);
    cleanup();

    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "");
    setup({ width: 393 });
    expect(screen.queryByTestId("demo-notice")).toBeNull();
    expect(document.body.textContent).not.toContain("합성 데이터 데모");
  });
});

describe("창 크기 자동 열고 닫기(FE-17 U-18)", () => {
  const resize = (width: number) =>
    act(() => {
      setWidth(width);
      window.dispatchEvent(new Event("resize"));
    });

  it("1280 → 393이면 사이드바가 닫히고(☰), 393 → 1280이면 펼쳐진다. 같은 구간 안의 수동 접기는 폭만 바뀌면 그대로이며 입력 중 글자는 남는다", async () => {
    const { user } = setup({ width: 1280 });
    await screen.findByTestId("sidebar");
    await user.type(screen.getByRole("textbox"), "입력 중");
    // 같은 구간(넓은 폭)에서 사용자가 접는다 → 폭만 바꾸면(1280 → 1100) 그대로 접힘
    await user.click(screen.getByTestId("sidebar-toggle"));
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
    resize(1100);
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar")).toBeNull();
    // 기준선 아래로: 사이드바 칸이 없고 ☰
    resize(393);
    expect(screen.queryByTestId("sidebar-rail")).toBeNull();
    expect(screen.getByTestId("menu-button")).toBeInTheDocument();
    // 드로어를 열어 둔 채 다시 넓히면 드로어는 닫히고 사이드바가 펼쳐진다(접어 두었던 것과 상관없이)
    await user.click(screen.getByTestId("menu-button"));
    expect(await screen.findByTestId("menu-drawer")).toBeInTheDocument();
    resize(1280);
    await waitFor(() => expect(screen.queryByTestId("menu-drawer")).toBeNull());
    expect(screen.getByTestId("sidebar")).toHaveAttribute("data-presentation", "push");
    expect(screen.getByRole("textbox")).toHaveValue("입력 중"); // 다시 마운트하지 않는다
    // 같은 구간 안의 크기 변화(1280 → 1500)에는 반응하지 않는다: 다시 접은 뒤 넓혀도 접힘
    await user.click(screen.getByTestId("sidebar-toggle"));
    resize(1500);
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
  });

  it("근거 상세(U-18 추가): 1280에서 열린 채 900으로 줄이면 닫히고(시트로 덮지 않음), 다시 1280으로 넓혀도 닫힌 채다. 좁은 폭에서 직접 연 시트는 넓어져도 유지한다", async () => {
    const { user } = setup({ width: 1280 });
    await ask(user, "가나다정 먹어도 돼요");
    const panel = await screen.findByTestId("panel-column");
    // 패널 안에 초점이 있으면 닫힌 뒤 그 결과의 진입 버튼으로 돌아간다
    within(panel).getAllByRole("button")[0].focus();
    resize(900);
    await waitFor(() => expect(screen.queryByTestId("panel-column")).toBeNull());
    expect(screen.queryByRole("dialog", { name: "근거 상세" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("evidence-entry")));
    resize(1280);
    expect(screen.queryByTestId("panel-column")).toBeNull();
    expect(screen.queryByRole("dialog", { name: "근거 상세" })).toBeNull();
    // 좁은 폭에서 사용자가 직접 연 시트는 폭이 더 줄어도, 넓어져도 닫지 않는다(넓어지면 우측 패널)
    resize(900);
    await user.click(screen.getByTestId("evidence-entry"));
    expect(await screen.findByRole("dialog", { name: "근거 상세" })).toBeInTheDocument();
    resize(700);
    expect(screen.getByRole("dialog", { name: "근거 상세" })).toBeInTheDocument();
    resize(1280);
    expect(await screen.findByTestId("panel-column")).toBeInTheDocument();
  });
});

describe("로그인 상태 새로고침 깜박임(FE-17 U-22 추가, 2026-11-24)", () => {
  it("재현·수정: 로그인 세션이 있으면 `/me`가 답하기 전 프레임에도 `게스트로 시작`·`로그인/가입`이 그려지지 않고, 같은 자리에 빈 자리(글자 없음)만 둔다. 확정 뒤 한 번에 그린다", async () => {
    const { account } = setup({ session: mockSession("onboarded"), width: 1280 });
    // 첫 그리기 직후(아직 `bootstrap()` 진행 중): 계정 상태는 게스트 초기값이지만 진입 선택은 없다
    expect(account.getState().status).toBe("guest");
    expect(screen.queryByTestId("entry-choice")).toBeNull(); // 수정 전에는 여기서 진입 선택이 그려졌다(재현, 보고 ux-batch7 §3)
    expect(account.getState().sessionChecked).toBe(false);
    expect(screen.queryByRole("button", { name: "게스트로 시작" })).toBeNull();
    expect(screen.queryByRole("button", { name: "로그인/가입" })).toBeNull();
    expect(screen.queryByTestId("start-target")).toBeNull();
    const pending = screen.getByTestId("start-account-pending");
    expect(pending).toHaveAttribute("aria-hidden", "true");
    expect(pending.textContent).toBe(""); // 새 글자 0건
    // 확정 뒤: 로그인 상태의 시작 안내가 나오고 빈 자리·진입 선택은 없다
    await waitFor(() => expect(account.getState().status).toBe("member"));
    expect(await screen.findByTestId("start-target")).toBeInTheDocument();
    expect(screen.queryByTestId("start-account-pending")).toBeNull();
    expect(screen.queryByTestId("entry-choice")).toBeNull();
  });

  it("비로그인(세션 없음)은 확정 뒤 진입 선택이 보이고, 확정 전 빈 자리는 진입 선택과 같은 높이 칸이다", async () => {
    const { account } = setup({ session: null, width: 393 });
    // 목 모드는 세션이 워커 메모리에만 있어 `/me` 답 전에는 모른다(실서버 Supabase는 쿠키가 없으면 곧바로 게스트, 스토어·쿠키 시험)
    expect(screen.getByTestId("start-account-pending")).toHaveClass("h-11");
    expect(await screen.findByTestId("entry-choice")).toBeInTheDocument();
    expect(account.getState()).toMatchObject({ status: "guest", sessionChecked: true });
    expect(screen.queryByTestId("start-account-pending")).toBeNull();
  });

  it("계정 기능이 꺼져 있으면(목·Supabase 설정 없음) 기다리는 빈 자리 없이 곧바로 시작 화면이다", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_MOCKING", "");
    setup({ session: null, width: 393 });
    expect(screen.queryByTestId("start-account-pending")).toBeNull();
    expect(screen.queryByTestId("entry-choice")).toBeNull(); // 계정 진입점 자체가 없다(기존 동작)
  });
});

describe("대상을 바꾸면 새 대화(FE-17 U-21 추가, 2026-11-24)", () => {
  it("질문이 오간 대화에서 다른 대상을 고르면 이전 대화를 잇지 않고 새 대화(시작 화면)가 되고, 토글은 새 대상 값이다. 같은 대상을 다시 고르면 대화가 그대로다", async () => {
    const { user, store, account } = setup({ session: onboardedSession(true, "pregnant"), width: 1280 });
    await screen.findByTestId("target-chip");
    await pickTarget(user, "첫째");
    await ask(user, "가나다정 먹어도 돼요");
    expect(store.getState().turns).toHaveLength(1);
    // 같은 대상(첫째)을 다시 고른다 → 대화 그대로
    await pickTarget(user, "첫째");
    expect(store.getState().turns).toHaveLength(1);
    expect(screen.queryByTestId("home")).toBeNull();
    // 다른 대상(나, 임신 중) → 새 대화. 토글은 바뀐 대상의 값(임산부)
    await pickTarget(user, "나");
    expect(account.getState().targetProfileId).toBe(SELF_ID);
    expect(store.getState().turns).toHaveLength(0);
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(screen.queryByTestId("panel-column")).toBeNull(); // 근거 상세도 닫힌다(새 대화 버튼과 같다)
    expect(store.getState().context.pregnant).toBe(true);
    expect(checkedLabel()).toBe("임산부");
    expect(store.getState().context.priorDrugs).toEqual([]);
  });

  it("시작 화면(대화 없음)에서는 대상만 바꾸고 새 대화를 열지 않는다", async () => {
    const { user, store } = setup({ session: onboardedSession(true), width: 393 });
    await screen.findByTestId("target-chip");
    // 새 대화(`reset`)는 대화 묶음을 비운다: 대상 변경이 건드리지 않는 칸(`tookToday`)에 표시를 두고 남는지 본다
    store.getState().setContext({ tookToday: true });
    await pickTarget(user, "첫째");
    await pickTarget(user, "나");
    expect(store.getState().context.tookToday).toBe(true);
    expect(screen.getByTestId("home")).toBeInTheDocument();
  });

  it("답을 받는 중(스트리밍)에 다른 대상을 고르면 진행 응답을 끊고 새 대화를 연다", async () => {
    const { user, store } = setup({ session: onboardedSession(true), width: 1280 });
    let aborted = false;
    server.use(
      http.post("*/api/chat", ({ request }) => {
        request.signal.addEventListener("abort", () => {
          aborted = true;
        });
        return new Promise<Response>(() => undefined); // 끝나지 않는 응답(스트리밍 중)
      }),
    );
    await screen.findByTestId("target-chip");
    await pickTarget(user, "나");
    await user.type(screen.getByRole("textbox"), "가나다정 먹어도 돼요");
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await waitFor(() => expect(store.getState().turns).toHaveLength(1));
    await pickTarget(user, "첫째");
    expect(store.getState().turns).toHaveLength(0);
    await waitFor(() => expect(aborted).toBe(true));
    expect(await screen.findByTestId("home")).toBeInTheDocument();
  });
});

describe("근거 상세가 열린 채 창이 줄면 사이드바를 레일로(FE-17 U-18 추가 지시 2)", () => {
  const resize = (width: number) =>
    act(() => {
      setWidth(width);
      window.dispatchEvent(new Event("resize"));
    });

  it("1280에서 근거 상세 + 펼친 사이드바 → 1231로 줄이면 레일로 접히고 dim(사이드바 오버레이)이 없으며 본문을 조작할 수 있다. 1280으로 넓혀도 레일이다", async () => {
    const { user } = setup({ width: 1280 });
    await ask(user, "가나다정 먹어도 돼요");
    await screen.findByTestId("panel-column");
    expect(screen.getByTestId("sidebar")).toHaveAttribute("data-presentation", "push");
    resize(1232);
    expect(screen.getByTestId("sidebar")).toHaveAttribute("data-presentation", "push"); // 1232는 밀 수 있다
    resize(1231);
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar-scrim")).toBeNull();
    expect(screen.getByTestId("main")).not.toHaveAttribute("inert");
    expect(screen.getByTestId("panel-column")).toBeInTheDocument();
    resize(1280);
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar")).toBeNull();
  });

  it("사용자가 1100에서 직접 펼친 사이드바는 오버레이(dim)로 열리고, 폭이 바뀌어도 닫지 않는다(현행 유지)", async () => {
    const { user } = setup({ width: 1100 });
    await ask(user, "가나다정 먹어도 돼요");
    await screen.findByTestId("panel-column");
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument(); // 열리는 순간 접힘(§11 ⑦)
    await user.click(screen.getByTestId("sidebar-toggle"));
    await waitFor(() => expect(screen.getByTestId("main")).toHaveAttribute("inert"));
    resize(1080);
    expect(screen.getByTestId("main")).toHaveAttribute("inert"); // 오버레이 그대로
  });
});
