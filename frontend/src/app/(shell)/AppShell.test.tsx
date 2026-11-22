import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { PREGNANCY_SAVE_CONSENT_HINT } from "@/features/chat";
import { PREGNANCY_PICK_HINT } from "@/features/result";
import { CONSENT_DOC_TYPES, HEALTH_CONSENT_DOC } from "@/lib/api/account";
import { DISCLAIMER, FIXED_NOTICE } from "@/lib/fixed/phrases.generated";
import { createAccountHandlers } from "@/mocks/account-handlers";
import type { AccountMockState } from "@/mocks/account-handlers";
import { API_NO_CODE_NOTE, PHRASES } from "@/mocks/fixtures/phrases";
import { handlers } from "@/mocks/handlers";
import { createPhotoHandlers } from "@/mocks/photo-handlers";
import { createAccountStore } from "@/stores/account";
import { createChatStore } from "@/stores/chat";
import { AppShell } from "./AppShell";

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
    step: "family",
    completedAt: null,
    consents: Object.fromEntries(CONSENT_DOC_TYPES.filter((docType) => healthConsent || docType !== HEALTH_CONSENT_DOC).map((docType) => [docType, agree])),
    profiles: [
      { profile_id: SELF_ID, relation: "self", label: "나", age_band: "y19_64", sex: null, pregnancy_status: selfPregnancy, sort_order: 0, medications: [] },
      { profile_id: CHILD_ID, relation: "child", label: "첫째", age_band: "y6_11", sex: null, pregnancy_status: null, sort_order: 1, medications: [] },
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
    expect(screen.getByTestId("start-emergency")).toBeInTheDocument(); // 시작 화면 119 줄은 그대로
    expect(screen.queryByTestId("external-ai-notice")).toBeNull();
    expect(within(body).getAllByTestId("input-notice")).toHaveLength(1);
    expect(count("외부 AI", body)).toBe(1);
    expect(count("OpenAI", body)).toBe(1);
    expect(count("외부 AI", document.body)).toBe(1);
  });

  it("1280: 실시간 확인 실패 응답에서 본문은 '실시간 확인' 0회·안전 고지 1회·법적 고지 1회·입력창 고지 1회이고, 자동으로 열린 근거 상세에만 배너·줄 노트가 있다", async () => {
    const { user } = setup({ width: 1280 });
    await ask(user, "mock:실시간실패 가나다정");
    const body = main();
    expect(count("실시간 확인", body)).toBe(0);
    expect(count(PHRASES.NOTICE_API_FAIL, body)).toBe(0);
    expect(count(API_NO_CODE_NOTE, body)).toBe(0);
    expect(count(FIXED_NOTICE, body)).toBe(1);
    expect(count(DISCLAIMER, body)).toBe(1);
    expect(within(body).getAllByTestId("input-notice")).toHaveLength(1);
    expect(within(body).queryByTestId("result-notice")).toBeNull();
    expect(within(body).getByTestId("basis-file-tag").textContent).toBe("기준일 자료");
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
    expect(count(DISCLAIMER)).toBe(1);
    expect(screen.getAllByTestId("input-notice")).toHaveLength(1);
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
    expect(screen.queryByTestId("target-picker")).toBeNull();
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
    const picker = await screen.findByTestId("target-picker");
    expect(checkedLabel()).toBe("일반인"); // 대상을 고르기 전
    await user.click(within(picker).getByRole("radio", { name: "나" }));
    expect(checkedLabel()).toBe("일반인"); // 프로필 not_pregnant
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ path: `/api/profiles/${SELF_ID}`, body: { pregnancy_status: "pregnant" } });
    await waitFor(() => expect(account.getState().profiles.find((profile) => profile.profile_id === SELF_ID)?.pregnancy_status).toBe("pregnant"));
    expect(state.session?.profiles.find((profile) => profile.profile_id === SELF_ID)?.pregnancy_status).toBe("pregnant");
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    expect(screen.queryByTestId("pregnancy-save-error")).toBeNull();
    // 프로필 화면(계정 모달)에서 바뀐 값이 보인다
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
    await user.click(within(picker).getByRole("radio", { name: "첫째" }));
    expect(checkedLabel()).toBe("일반인");
    await user.click(within(picker).getByRole("radio", { name: "나" }));
    expect(checkedLabel()).toBe("임산부");
    expect(patches).toHaveLength(3); // 대상 변경은 저장하지 않는다
  });

  it("건강 정보 동의가 없으면 PATCH 없이 이 대화에만 적용하고 안내 한 줄을 둔다(422를 받아도 같은 동작)", async () => {
    const { user, state } = setup({ session: onboardedSession(false), width: 1280 });
    const picker = await screen.findByTestId("target-picker");
    await user.click(within(picker).getByRole("radio", { name: "나" }));
    await user.click(radio("임산부"));
    expect(checkedLabel()).toBe("임산부");
    expect(screen.getByTestId("pregnancy-hint").textContent).toBe(PREGNANCY_SAVE_CONSENT_HINT);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
    expect(patches).toEqual([]);
    expect(state.session?.profiles[0].pregnancy_status).toBe("not_pregnant");
    // 대상을 바꾸면 안내는 사라지고 토글은 그 프로필 값(없음 → 일반인)으로 돌아간다
    await user.click(within(picker).getByRole("radio", { name: "첫째" }));
    expect(checkedLabel()).toBe("일반인");
    expect(screen.queryByTestId("pregnancy-hint")).toBeNull();
    // 서버가 422 HEALTH_CONSENT_REQUIRED를 주는 경우는 아래 "저장 실패" 시험이 본다
  });

  it("저장이 다른 이유로 실패하면 대화 값은 유지하고 짧은 오류 안내를 보인다", async () => {
    const { user, account, state } = setup({ session: onboardedSession(true), width: 1280 });
    const picker = await screen.findByTestId("target-picker");
    await user.click(within(picker).getByRole("radio", { name: "나" }));
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

describe("GROUP-03 3단계 성별 숨김(FE-11-09 C·FE-11-12 A)", () => {
  /** 본인은 남성, 첫째는 여성(둘 다 건강 정보 동의 범위 안의 임신 값 포함) */
  function sexedSession(healthConsent: boolean, { selfSex, childSex, selfPregnancy = null as "pregnant" | "not_pregnant" | null }: { selfSex: "male" | "female" | null; childSex: "male" | "female" | null; selfPregnancy?: "pregnant" | "not_pregnant" | null }) {
    const session = onboardedSession(healthConsent, selfPregnancy);
    session.profiles = session.profiles.map((profile) => (profile.profile_id === SELF_ID ? { ...profile, sex: selfSex } : { ...profile, sex: childSex, pregnancy_status: "pregnant" }));
    return session;
  }
  const toggleOrNull = () => screen.queryByRole("radiogroup", { name: "임신 여부" });
  const form = () => screen.getByRole("textbox").closest("form")!;

  it("남성 프로필이 대상이면 토글이 없고 context.pregnant=false를 보낸다. 저장 값이 임신이어도 같다. 대상 바꾸기 전(선택 안 함)과 게스트는 보인다", async () => {
    const { user, store } = setup({ session: sexedSession(true, { selfSex: "male", childSex: "female", selfPregnancy: "pregnant" }), width: 1280 });
    const picker = await screen.findByTestId("target-picker");
    expect(toggleOrNull()).not.toBeNull(); // 대상을 고르기 전(선택 안 함)은 보인다
    const formBefore = form();
    await user.click(within(picker).getByRole("radio", { name: "나" }));
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
    const picker = await screen.findByTestId("target-picker");
    await user.click(within(picker).getByRole("radio", { name: "나" }));
    expect(toggleOrNull()).toBeNull();
    await user.click(within(picker).getByRole("radio", { name: "첫째" }));
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("임산부"); // 첫째는 임신으로 저장돼 있다(§7.1 규칙 ①)
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[0].context.pregnant).toBe(true);
    await user.click(within(picker).getByRole("radio", { name: "나" }));
    expect(toggleOrNull()).toBeNull();
    expect(store.getState().context.pregnant).toBe(false);
    await ask(user, "가나다정 먹어도 돼요");
    expect(chatBodies[1].context.pregnant).toBe(false);
    // 선택 안 함으로 돌아가면 다시 보이고 일반인이다
    await user.click(within(picker).getByRole("radio", { name: "선택 안 함" }));
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("일반인");
  });

  it("여성·성별 미입력 프로필과 게스트는 토글이 보이고 동작한다(동의 없음은 안내 한 줄)", async () => {
    const { user } = setup({ session: sexedSession(false, { selfSex: "female", childSex: null }), width: 393 });
    const picker = await screen.findByTestId("target-picker");
    await user.click(within(picker).getByRole("radio", { name: "나" })); // 여성
    expect(toggleOrNull()).not.toBeNull();
    expect(checkedLabel()).toBe("일반인");
    await user.click(within(picker).getByRole("radio", { name: "첫째" })); // 미입력
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
    expect(within(modal).getByTestId("layer-emergency-entry")).toHaveAttribute("href", "tel:119");
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
