import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { DRUG_DATA_SCOPE_NOTICE as ACCOUNT_DRUG_DATA_SCOPE_NOTICE } from "@/features/account/copy";
import { INPUT_NOTICE } from "@/features/chat/copy";
import { PHRASES } from "@/mocks/fixtures/phrases";
import { PHOTO_SCENARIO_PNG_WIDTH, createPhotoHandlers, pickPhotoScenario, pngWidth } from "@/mocks/photo-handlers";
import type { PhotoScenarioName } from "@/mocks/photo-handlers";
import { buildChatInput, buildProfileMedications, canConfirm, canRegister, emptyRow, rowsFromResponse } from "./build-chat-input";
import type { PhotoRow } from "./build-chat-input";
import * as copy from "./copy";
import { initialPhotoFlow, photoFlowReducer } from "./flow";
import { PHOTO_ROW_SEARCH_DEBOUNCE_MS } from "./api";
import { PHOTO_ACCEPT, PhotoImageError, prepareImage } from "./image";
import { PhotoModal } from "./PhotoModal";
import type { PhotoModalProps } from "./PhotoModal";
import type { IngestDrug } from "./types";

// 사진 입력 화면(FE-05 사진 부분)을 MSW 목(`photo-handlers.ts`)에 붙여 본다. 실제 서버 호출 0, 실제 사진 0(합성 바이트).
// H19·〔D7〕A: 이 화면은 `/chat`을 부르지 않는다 — 요청 기록으로 0회를 고정한다.

const server = setupServer();
let chatCalls = 0;
let ingestCalls = 0;
/** 확인 카드 행 검색 요청 기록(검색어는 시험 안에서만 본다): 본문 `q`와 `Authorization` 머리 유무 */
let searchCalls: { q: string; authorization: string | null }[] = [];
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", async ({ request }) => {
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith("/api/chat")) chatCalls += 1;
    if (pathname.endsWith("/api/ingest/image")) ingestCalls += 1;
    if (pathname.endsWith("/api/ingest/drugs/search") && request.method === "POST") {
      const body = (await request.clone().json().catch(() => ({ q: "" }))) as { q: string };
      searchCalls.push({ q: body.q, authorization: request.headers.get("authorization") });
    }
  });
});
beforeEach(() => {
  chatCalls = 0;
  ingestCalls = 0;
  searchCalls = [];
  server.use(
    http.post("*/api/chat", () => HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 })),
    ...createPhotoHandlers(),
  );
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const PNG_URL = "data:image/png;base64,iVBORw0KGgo=";
/** P2 승인 원문(제공자 OpenAI, 2026-11-23 only OpenAI 확정으로 복원). 상수가 아니라 글자로 적어 둘 다 검사한다 */
const OPENAI_NOTICE = "올린 사진은 약 이름을 읽기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 사진을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요.";
const fakePrepare: typeof prepareImage = async () => ({ dataUrl: PNG_URL, width: 10, height: 10, resized: false, bytes: 8 });
const pngFile = () => new File([new Uint8Array([1, 2, 3, 4])], "pouch.png", { type: "image/png" });

const CANDIDATE = { name: "가나다정 100밀리그램", item_seq: "200000001", entp_name: "합성제약(주)", prescription: "일반의약품", matched_by: "product_name" as const, match_type: "prefix" };
const DRUGS: IngestDrug[] = [
  { read_name: null, read_ingredient: "가나다성분", strength_or_form: null, candidates: [] },
  { read_name: "가나다정", read_ingredient: "가나다성분", strength_or_form: "100mg", candidates: [CANDIDATE] },
];

function setup(props: Partial<PhotoModalProps> = {}) {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  const onTypeInstead = vi.fn();
  const onOpenChange = vi.fn();
  const view = render(
    <PhotoModal
      open
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
      onTypeInstead={onTypeInstead}
      prepare={fakePrepare}
      emergencyEntry={
        <a href="tel:119" data-testid="layer-emergency-entry">
          119 전화
        </a>
      }
      {...props}
    />,
  );
  return { user, onConfirm, onTypeInstead, onOpenChange, unmount: view.unmount };
}

const modal = () => screen.getByTestId("photo-modal");
const upload = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.upload(within(modal()).getByTestId("photo-file"), pngFile());
};
const toCard = async (user: ReturnType<typeof userEvent.setup>) => {
  await upload(user);
  return within(modal()).findByTestId("photo-confirm-card");
};
const rows = () => within(modal()).queryAllByTestId("photo-row");
const nameInputs = () => within(modal()).getAllByTestId("photo-read-name") as HTMLInputElement[];
const confirmButton = () => within(modal()).getByTestId("photo-confirm") as HTMLButtonElement;
const question = () => within(modal()).getByTestId("photo-question");
const before = (a: Element, b: Element) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

describe("사진 고르기(P1·P2·P7·P9, PRD-13 코너)", () => {
  it("가림 안내·전송 고지가 고르기 버튼 위에 접히지 않고 보이고, 형식 안내가 아래에 있다. 제목에 초점, `<` 없음, `닫기` 우상단", () => {
    setup();
    const box = modal();
    expect(box.getAttribute("data-step")).toBe("pick");
    const privacy = within(box).getByTestId("photo-privacy-notice");
    const external = within(box).getByTestId("photo-external-ai-notice");
    const pick = within(box).getByTestId("photo-pick");
    const note = within(box).getByTestId("photo-format-note");
    expect(privacy.textContent).toBe(copy.PHOTO_PRIVACY_NOTICE);
    expect(external.textContent).toBe(copy.PHOTO_EXTERNAL_AI_NOTICE);
    expect(before(privacy, external)).toBe(true);
    expect(before(external, pick)).toBe(true);
    expect(before(pick, note)).toBe(true);
    for (const el of [privacy, external]) expect(el.closest("details, [data-state=closed]")).toBeNull();
    expect(pick.textContent).toBe(copy.PHOTO_ENTRY_LABEL);
    expect(note.textContent).toBe(copy.PHOTO_FORMAT_NOTE);
    expect(note.getAttribute("role")).toBe("note");
    expect(within(box).getByTestId("photo-close").textContent).toBe(copy.PHOTO_CLOSE_LABEL);
    expect(within(box).queryByTestId("photo-back")).toBeNull();
    expect(within(box).queryByRole("button", { name: "뒤로" })).toBeNull();
    expect(document.activeElement).toBe(within(box).getByRole("heading", { name: copy.PHOTO_ENTRY_LABEL }));
    // 모달이 머리줄을 덮는 동안의 119 진입점
    expect(within(box).getByTestId("layer-emergency-entry")).toHaveAttribute("href", "tel:119");
    // 파일 선택은 JPEG·PNG와 HEIC/HEIF(BE-14-08 A: HEIC는 브라우저 안에서 JPEG로 바꿔 보낸다)
    expect(within(box).getByTestId("photo-file")).toHaveAttribute("accept", PHOTO_ACCEPT);
    expect(PHOTO_ACCEPT.split(",")).toEqual(expect.arrayContaining(["image/jpeg", "image/png", "image/heic", "image/heif", ".heic", ".heif"]));
  });

  it("형식·크기 거절(8MB 초과)은 보내지 않고 P7을 강조한다", async () => {
    const { user } = setup({
      prepare: async () => {
        throw new PhotoImageError("too_large");
      },
    });
    await upload(user);
    const note = await within(modal()).findByTestId("photo-format-note");
    await waitFor(() => expect(note.getAttribute("data-rejected")).toBe("true"));
    expect(note.getAttribute("role")).toBe("alert");
    expect(note.textContent).toBe(copy.PHOTO_FORMAT_NOTE);
    expect(ingestCalls).toBe(0);
    expect(modal().getAttribute("data-step")).toBe("pick");
  });

  it("닫기는 승인 없이 버린다: onConfirm 없음, `/chat` 0회", async () => {
    const { user, onConfirm, onOpenChange } = setup();
    await toCard(user);
    await user.click(within(modal()).getByTestId("photo-close"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(chatCalls).toBe(0);
  });
});

describe("인식 중·실패(P3·P4·P8)", () => {
  it("읽는 동안 P3 진행 표시가 있고(돋보기 병아리), 119가 있으면 병아리를 그리지 않는다", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { user } = setup({
      prepare: async () => {
        await gate;
        return fakePrepare(new Blob());
      },
    });
    await upload(user);
    const reading = await within(modal()).findByTestId("photo-reading");
    expect(reading.textContent).toContain(copy.PHOTO_READING);
    expect(reading.getAttribute("role")).toBe("status");
    expect(within(reading).getByTestId("mascot")).toHaveAttribute("data-variant", "search");
    release();
    await within(modal()).findByTestId("photo-confirm-card");
  });

  it("119가 떠 있으면 인식 중·고르기 화면에 마스코트가 없다", () => {
    setup({ hasEmergency: true, emergencyEntry: null });
    expect(within(modal()).queryByTestId("mascot")).toBeNull();
  });

  it("UNREADABLE → P4와 `다시 찍기`·`글자로 입력`. `글자로 입력`은 입력창으로 간다", async () => {
    server.use(...createPhotoHandlers({ scenario: "unreadable" }));
    const { user, onTypeInstead, onConfirm } = setup();
    await upload(user);
    const failed = await within(modal()).findByTestId("photo-failed");
    expect(failed.textContent).toBe(copy.PHOTO_FAILED);
    expect(failed.getAttribute("role")).toBe("alert");
    expect(failed.getAttribute("data-kind")).toBe("unreadable");
    expect(within(modal()).getByTestId("photo-retake").textContent).toBe(copy.PHOTO_RETAKE_LABEL);
    const typeInstead = within(modal()).getByTestId("photo-type-instead");
    expect(typeInstead.textContent).toBe(copy.PHOTO_TYPE_INSTEAD_LABEL);
    await user.click(typeInstead);
    expect(onTypeInstead).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(chatCalls).toBe(0);
  });

  it("UNAVAILABLE(상한) → P8", async () => {
    server.use(...createPhotoHandlers({ scenario: "unavailable" }));
    const { user } = setup();
    await upload(user);
    const failed = await within(modal()).findByTestId("photo-failed");
    expect(failed.textContent).toBe(copy.PHOTO_UNAVAILABLE);
    expect(failed.getAttribute("data-kind")).toBe("unavailable");
  });

  it("서버 오류(5xx)·연결 실패도 P4로 간다(보낸 사진은 버린다)", async () => {
    server.use(http.post("*/api/ingest/image", () => HttpResponse.json({ code: "INTERNAL_ERROR", fields: [] }, { status: 500 })));
    const { user } = setup();
    await upload(user);
    expect((await within(modal()).findByTestId("photo-failed")).textContent).toBe(copy.PHOTO_FAILED);
  });

  it("`다시 찍기`는 파일 선택을 다시 연다(요청은 새 파일을 고른 뒤에만)", async () => {
    server.use(...createPhotoHandlers({ scenario: "unreadable" }));
    const { user } = setup();
    await upload(user);
    await within(modal()).findByTestId("photo-failed");
    const input = within(modal()).getByTestId("photo-file") as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    await user.click(within(modal()).getByTestId("photo-retake"));
    expect(click).toHaveBeenCalledTimes(1);
    expect(ingestCalls).toBe(1);
  });
});

describe("확인·수정 카드(P5·P6, 〔D6〕A, H19)", () => {
  it("읽은 글자가 입력칸에, 성분·용량이 작은 글자로, 후보는 라디오이고 기본 선택이 없다. 확신도는 없다", async () => {
    const { user } = setup();
    const card = await toCard(user);
    expect(within(card).getByTestId("photo-confirm-guide").textContent).toBe(copy.PHOTO_CONFIRM_GUIDE);
    expect(rows()).toHaveLength(2);
    expect(nameInputs().map((input) => input.value)).toEqual(["가나다정", "라마바캡슐"]);
    const first = rows()[0];
    expect(within(first).getByTestId("photo-read-sub").textContent).toContain("가나다성분");
    expect(within(first).getByTestId("photo-read-sub").textContent).toContain("100mg");
    expect(within(first).getByTestId("photo-candidates-guide").textContent).toBe(copy.PHOTO_CANDIDATES_GUIDE);
    const radios = within(first).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    for (const radio of radios) expect(radio).toHaveAttribute("aria-checked", "false");
    expect(within(rows()[1]).queryByTestId("photo-candidates-guide")).toBeNull();
    expect(within(rows()[1]).queryAllByRole("radio")).toHaveLength(0);
    expect(within(first).getByTestId("med-icon")).toBeInTheDocument();
    expect(card.textContent).not.toMatch(/확신|신뢰도|\d+\s?%/);
    // 라벨 글자
    expect(within(card).getByRole("button", { name: copy.PHOTO_ADD_DRUG_LABEL })).toBeInTheDocument();
    expect(confirmButton().textContent).toBe(copy.PHOTO_CONFIRM_LABEL);
    expect(within(card).getByLabelText(copy.PHOTO_QUESTION_LABEL)).toBe(question());
  });

  it("FE-04-25 A: 카드 안내 바로 아래에 자료 밖 약 고지가 승인 원문 그대로 한 줄 보인다(프로필 약 입력과 같은 상수, 마스코트 없음)", async () => {
    const { user } = setup();
    const card = await toCard(user);
    const notice = within(card).getByTestId("drug-data-scope-notice");
    expect(copy.DRUG_DATA_SCOPE_NOTICE).toBe(ACCOUNT_DRUG_DATA_SCOPE_NOTICE); // 원본은 계정 copy 하나
    expect(notice.textContent).toBe("국내 허가 의약품 자료만 확인할 수 있어요. 조제약·해외 약 등 자료에 없는 약은 금기를 확인하지 못하니, 이름을 그대로 적고 약사에게 확인하세요.");
    expect(before(within(card).getByTestId("photo-confirm-guide"), notice)).toBe(true);
    expect(before(notice, rows()[0])).toBe(true);
    expect(within(card).getAllByTestId("drug-data-scope-notice")).toHaveLength(1);
    expect(within(card).queryByTestId("mascot")).toBeNull();
  });

  it("질문이 비면 `이대로 확인`이 비활성이고, 약이 모두 비어도 비활성이다", async () => {
    const { user } = setup();
    await toCard(user);
    expect(confirmButton().disabled).toBe(true);
    await user.type(question(), "같이 먹어도 돼요?");
    expect(confirmButton().disabled).toBe(false);
    await user.clear(question());
    expect(confirmButton().disabled).toBe(true);
    await user.type(question(), "같이 먹어도 돼요?");
    // 모든 줄을 지우고 빈 줄만 남기면 약이 0개다
    for (const remove of within(modal()).getAllByTestId("photo-row-remove")) await user.click(remove);
    expect(rows()).toHaveLength(0);
    await user.click(within(modal()).getByTestId("photo-add-row"));
    expect(rows()).toHaveLength(1);
    expect(nameInputs()[0].value).toBe("");
    expect(confirmButton().disabled).toBe(true);
    await user.type(nameInputs()[0], "사아자정");
    expect(confirmButton().disabled).toBe(false);
  });

  it("수정·삭제·추가·후보 고르기(다시 누르면 풀림) 뒤 `이대로 확인`은 buildChatInput 모양으로 한 번 넘기고 `/chat`은 부르지 않는다", async () => {
    const { user, onConfirm, onOpenChange } = setup();
    await toCard(user);
    const radios = within(rows()[0]).getAllByRole("radio");
    await user.click(radios[0]);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
    expect(radios[1]).toHaveAttribute("aria-checked", "false");
    await user.click(radios[0]);
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
    await user.click(radios[0]);
    // 두 번째 줄 글자를 고친다
    await user.clear(nameInputs()[1]);
    await user.type(nameInputs()[1], "라마바캡슐 20mg");
    // 줄을 더하고 바로 지운다
    await user.click(within(modal()).getByTestId("photo-add-row"));
    expect(rows()).toHaveLength(3);
    await user.click(within(rows()[2]).getByTestId("photo-row-remove"));
    expect(rows()).toHaveLength(2);
    await user.type(question(), "같이 먹어도 돼요?");
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith({
      question: "가나다정 100밀리그램, 라마바캡슐 20mg 같이 먹어도 돼요?",
      confirmedDrugs: [{ name: "가나다정 100밀리그램", itemSeq: "200000001", inputName: "가나다정 100밀리그램" }],
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(chatCalls).toBe(0); // `/chat`은 조립하는 쪽(AppShell)이 승인 뒤에 한 번 부른다
    expect(ingestCalls).toBe(1);
  });

  it("읽은 글자를 고치면 골랐던 후보가 풀린다(후보는 읽은 글자로 찾은 것)", async () => {
    const { user } = setup();
    await toCard(user);
    const radios = within(rows()[0]).getAllByRole("radio");
    await user.click(radios[0]);
    await user.type(nameInputs()[0], "A");
    expect(within(rows()[0]).getAllByRole("radio")[0]).toHaveAttribute("aria-checked", "false");
  });

  it("응답에 `emergency`가 있으면 카드 맨 위에 119(서버 값 그대로)", async () => {
    server.use(...createPhotoHandlers({ scenario: "emergency" }));
    const { user } = setup();
    const card = await toCard(user);
    const banner = within(card).getByTestId("emergency-banner");
    expect(card.firstElementChild).toContain(banner);
    expect(banner.textContent).toContain(PHRASES.EMERGENCY_119);
    expect(within(banner).getByRole("link")).toHaveAttribute("href", "tel:119");
    expect(within(card).queryByTestId("mascot")).toBeNull();
  });
});

describe("확인 카드 행의 사전 후보 검색(2026-11-23 사용자 결정 '아스피린 A': 게스트 허용 /ingest/drugs/search, 디바운스, 최신 입력만)", () => {
  const DEBOUNCE = PHOTO_ROW_SEARCH_DEBOUNCE_MS;
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  /** 빈 줄만 남기고 `약 추가`로 새 행 하나를 만든다 → 그 행의 입력칸 */
  const addRow = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(within(modal()).getByTestId("photo-add-row"));
    const inputs = nameInputs();
    return inputs[inputs.length - 1];
  };
  const radiosOf = (row: HTMLElement) => within(row).queryAllByRole("radio");

  it("`약 추가` 행에 2글자 이상 적으면 입력이 멈춘 뒤 400ms에 한 번 찾고, 판독 행과 같은 라디오 목록(radiogroup, 기본 선택 없음)·같은 안내 글자(P6)가 붙는다. 토큰 없음·/chat 0회", async () => {
    const { user } = setup();
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다시럽");
    expect(searchCalls).toHaveLength(0); // 글자마다 부르지 않는다(디바운스 전)
    const row = rows()[2];
    await waitFor(() => expect(radiosOf(row).length).toBeGreaterThan(0), { timeout: DEBOUNCE + 1500 });
    expect(searchCalls).toEqual([{ q: "가나다시럽", authorization: null }]); // 마지막 글자로 한 번, 게스트(토큰 없음)
    expect(within(row).getByRole("radiogroup")).toBeInTheDocument();
    expect(within(row).getByTestId("photo-candidates-guide").textContent).toBe(copy.PHOTO_CANDIDATES_GUIDE);
    for (const radio of radiosOf(row)) expect(radio).toHaveAttribute("aria-checked", "false");
    expect(radiosOf(row).map((radio) => radio.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("가나다시럽")]));
    // 판독 행의 후보(목 `ok` 시나리오의 2개)는 그대로다(판독 행은 글자를 바꾸지 않았으므로 다시 찾지 않는다)
    expect(radiosOf(rows()[0])).toHaveLength(2);
    expect(chatCalls).toBe(0);
  });

  it("2글자 미만이면 부르지 않는다(공백만도 아니다)", async () => {
    const { user } = setup();
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가");
    await sleep(DEBOUNCE + 200);
    expect(searchCalls).toHaveLength(0);
    await user.type(input, "  ");
    await sleep(DEBOUNCE + 200);
    expect(searchCalls).toHaveLength(0);
    expect(radiosOf(rows()[2])).toHaveLength(0);
  });

  it("최신 입력만 반영한다: 앞 검색이 늦게 와도 끊겨서 버려지고, 마지막 글자의 후보만 붙는다", async () => {
    const aborted: string[] = [];
    const search: PhotoModalProps["search"] = (q, signal) =>
      new Promise((resolve, reject) => {
        // "가나다정"은 느리게, 나머지는 바로 답한다. 끊기면 그 검색어를 기록한다
        const wait = q === "가나다정" ? 600 : 0;
        const timer = setTimeout(() => resolve({ candidates: [{ ...CANDIDATE, name: `${q} 후보` }], needs_confirmation: false, dict_version: "t" }), wait);
        signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          aborted.push(q);
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    const { user } = setup({ search });
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다정");
    await sleep(DEBOUNCE + 50); // 첫 검색("가나다정", 느림)이 나간 뒤
    await user.type(input, " 100");
    const row = rows()[2];
    await waitFor(() => expect(radiosOf(row)).toHaveLength(1), { timeout: 2000 });
    expect(radiosOf(row)[0].textContent).toContain("가나다정 100 후보");
    expect(aborted).toEqual(["가나다정"]);
    await sleep(700); // 느린 응답이 왔을 시각이 지나도 덮어쓰지 않는다
    expect(radiosOf(row)[0].textContent).toContain("가나다정 100 후보");
  });

  it("후보를 고르면 확인된 약(item_seq)으로 넘어가고, 고르지 않으면 적힌 글자 그대로(확인 안 된 약). 판정 호출은 확인 전 0회", async () => {
    const { user, onConfirm } = setup();
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다시럽");
    const row = rows()[2];
    await waitFor(() => expect(radiosOf(row).length).toBeGreaterThan(0), { timeout: DEBOUNCE + 1500 });
    const second = await addRow(user);
    await user.type(second, "가나다시럽 키즈");
    await waitFor(() => expect(radiosOf(rows()[3]).length).toBeGreaterThan(0), { timeout: DEBOUNCE + 1500 });
    const exact = radiosOf(row).find((radio) => radio.textContent?.includes("가나다시럽") && !radio.textContent.includes("키즈") && !radio.textContent.includes("플러스"))!;
    await user.click(exact);
    expect(exact).toHaveAttribute("aria-checked", "true");
    await user.type(question(), "같이 먹어도 돼요?");
    expect(chatCalls).toBe(0);
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith({
      question: "가나다정, 라마바캡슐, 가나다시럽, 가나다시럽 키즈 같이 먹어도 돼요?",
      confirmedDrugs: [{ name: "가나다시럽", itemSeq: "200000003", inputName: "가나다시럽" }],
    });
    expect(chatCalls).toBe(0);
  });

  it("판독된 행의 글자를 고치면 골랐던 후보가 풀리고 새 글자로 다시 찾는다. 2글자 미만으로 줄이면 후보가 비고 부르지 않는다", async () => {
    const { user } = setup();
    await toCard(user);
    const first = rows()[0];
    await user.click(radiosOf(first)[0]);
    await user.clear(nameInputs()[0]);
    await user.type(nameInputs()[0], "라마바캡슐");
    await waitFor(() => expect(radiosOf(first).length).toBe(2), { timeout: DEBOUNCE + 1500 });
    expect(searchCalls.map((call) => call.q)).toEqual(["라마바캡슐"]);
    for (const radio of radiosOf(first)) expect(radio).toHaveAttribute("aria-checked", "false");
    await user.clear(nameInputs()[0]);
    await user.type(nameInputs()[0], "라");
    expect(radiosOf(first)).toHaveLength(0);
    await sleep(DEBOUNCE + 200);
    expect(searchCalls).toHaveLength(1);
  });

  it("검색 실패(503)·모양 오류는 후보 없음으로 조용히 넘기고 입력·확인을 막지 않는다. 검색어는 상태 밖에 남지 않는다", async () => {
    const { user, onConfirm } = setup();
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다 mock-503");
    await waitFor(() => expect(searchCalls).toHaveLength(1), { timeout: DEBOUNCE + 1500 });
    await sleep(100);
    expect(radiosOf(rows()[2])).toHaveLength(0);
    expect(within(modal()).queryByRole("alert")).toBeNull();
    server.use(http.post("*/api/ingest/drugs/search", () => HttpResponse.json({ nope: true })));
    await user.type(input, "x");
    await waitFor(() => expect(searchCalls).toHaveLength(2), { timeout: DEBOUNCE + 1500 });
    await sleep(100);
    expect(radiosOf(rows()[2])).toHaveLength(0);
    await user.type(question(), "같이 먹어도 돼요?");
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ question: "가나다정, 라마바캡슐, 가나다 mock-503x 같이 먹어도 돼요?", confirmedDrugs: [] }));
  });

  it("행을 지우거나 모달이 내려가면 예약된 검색이 나가지 않는다", async () => {
    const { user, unmount } = setup();
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다시럽");
    await user.click(within(rows()[2]).getByTestId("photo-row-remove"));
    await sleep(DEBOUNCE + 200);
    expect(searchCalls).toHaveLength(0);
    const again = await addRow(user);
    await user.type(again, "가나다시럽");
    unmount(); // 닫기(`open=false`)와 같은 정리 경로: 예약·진행 중 요청을 모두 지운다
    await sleep(DEBOUNCE + 200);
    expect(searchCalls).toHaveLength(0);
  });

  it("프로필 등록 목적지에서도 같은 검색이 돌고, 고른 후보는 확인된 약으로 onRegister에 간다", async () => {
    const onRegister = vi.fn();
    const { user, onConfirm } = setup({ destination: "profile", onRegister });
    await toCard(user);
    const input = await addRow(user);
    await user.type(input, "가나다시럽 키즈");
    const row = rows()[2];
    await waitFor(() => expect(radiosOf(row).length).toBeGreaterThan(0), { timeout: DEBOUNCE + 1500 });
    await user.click(radiosOf(row)[0]);
    await user.click(confirmButton());
    expect(onRegister).toHaveBeenCalledWith([
      { input_text: "가나다정", item_seq: null },
      { input_text: "라마바캡슐", item_seq: null },
      { input_text: "가나다시럽 키즈", item_seq: "200000004" },
    ]);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(chatCalls).toBe(0);
  });

  it("MSW 목: /api/ingest/drugs/search는 토큰 없이 답하고(게스트 허용) 모양은 /drugs/search와 같다. GET은 405", async () => {
    const response = await fetch("http://localhost/api/ingest/drugs/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q: "아스피린장용정" }) });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ needs_confirmation: true, dict_version: expect.any(String) });
    expect(body.candidates.map((candidate: { name: string }) => candidate.name)).toEqual(["아스피린장용정 100밀리그램", "아스피린장용정 500밀리그램"]);
    expect((await fetch("http://localhost/api/ingest/drugs/search", { method: "GET" })).status).toBe(405);
    expect((await fetch("http://localhost/api/ingest/drugs/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q: "" }) })).status).toBe(422);
  });
});

describe("buildChatInput·canConfirm(지시서 §3 7번)", () => {
  const row = (patch: Partial<PhotoRow>): PhotoRow => ({ ...emptyRow(), ...patch });

  it("후보를 고른 약은 후보 이름, 아니면 고친 읽은 글자. 고른 약만 confirmedDrugs에 {name, item_seq, input_name: name}", () => {
    const rows = [row({ readName: "가나다정", candidates: [CANDIDATE], picked: CANDIDATE }), row({ readName: " 라마바캡슐 " }), row({ readName: "   " })];
    expect(buildChatInput(rows, " 같이 먹어도 돼요? ")).toEqual({
      question: "가나다정 100밀리그램, 라마바캡슐 같이 먹어도 돼요?",
      confirmedDrugs: [{ name: "가나다정 100밀리그램", itemSeq: "200000001", inputName: "가나다정 100밀리그램" }],
    });
  });

  it("후보를 고르지 않은 약은 confirmedDrugs에 싣지 않는다(글자로만 찾는다)", () => {
    expect(buildChatInput([row({ readName: "가나다정", candidates: [CANDIDATE] })], "질문").confirmedDrugs).toEqual([]);
  });

  it("canConfirm: 약 1개 이상 + 질문", () => {
    expect(canConfirm([row({ readName: "가" })], "q")).toBe(true);
    expect(canConfirm([row({ readName: "가" })], "  ")).toBe(false);
    expect(canConfirm([row({ readName: " " })], "q")).toBe(false);
    expect(canConfirm([], "q")).toBe(false);
    expect(canConfirm([row({ readName: "", candidates: [CANDIDATE], picked: CANDIDATE })], "q")).toBe(true);
  });

  it("rowsFromResponse: 상품명이 없으면 성분 글자로 시작하고 성분 병기는 없다", () => {
    const [a, b] = rowsFromResponse(DRUGS);
    expect(a).toMatchObject({ readName: "가나다성분", readIngredient: null, picked: null });
    expect(b).toMatchObject({ readName: "가나다정", readIngredient: "가나다성분", strengthOrForm: "100mg", picked: null });
    expect(a.id).not.toBe(b.id);
  });

  it("flow: OK인데 항목이 비면 빈 줄 하나로 시작한다(봉투에 약 이름이 없을 수 있다)", () => {
    const state = photoFlowReducer(initialPhotoFlow, { type: "readOk", drugs: [], emergency: null });
    expect(state.step).toBe("confirm");
    if (state.step === "confirm") expect(state.rows).toHaveLength(1);
  });
});

// ---------------------------------------------------------------- 프로필 복용 약 등록 목적지(FE-04-27 A, 2026-11-22)
describe("프로필 등록 목적지(FE-04-27 A): 질문칸 없음, 이름만 넘김, 채팅 전송 없음", () => {
  const row = (patch: Partial<PhotoRow>): PhotoRow => ({ ...emptyRow(), ...patch });
  const CANDIDATE_2 = { ...CANDIDATE, name: "가나다정 500밀리그램", item_seq: "200000002" };

  it("buildProfileMedications: 후보를 고른 줄은 확인된 약 {input_text: 후보 이름, item_seq}, 글자만 있는 줄은 확인 안 된 약(item_seq null), 빈 줄은 빠진다", () => {
    const rows = [
      row({ readName: "가나다정", candidates: [CANDIDATE], picked: CANDIDATE }),
      row({ readName: " 라마바캡슐 ", readIngredient: "라마바성분", strengthOrForm: "연질캡슐 20mg" }),
      row({ readName: "   " }),
      row({ readName: "", candidates: [CANDIDATE_2], picked: CANDIDATE_2 }),
    ];
    const items = buildProfileMedications(rows);
    expect(items).toEqual([
      { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
      { input_text: "라마바캡슐", item_seq: null },
      { input_text: "가나다정 500밀리그램", item_seq: "200000002" },
    ]);
    // 사진·읽은 성분·용량 글자는 어디에도 싣지 않는다
    expect(JSON.stringify(items)).not.toMatch(/라마바성분|연질캡슐|data:|readIngredient|strength/);
  });

  it("buildProfileMedications: 같은 약(번호가 같거나, 번호 없이 글자가 같음)은 한 번만 들어간다", () => {
    const rows = [
      row({ readName: "가나다정", candidates: [CANDIDATE], picked: CANDIDATE }),
      row({ readName: "가나다 정", candidates: [CANDIDATE], picked: CANDIDATE }),
      row({ readName: "라마바" }),
      row({ readName: "라마바 " }),
    ];
    expect(buildProfileMedications(rows)).toEqual([
      { input_text: "가나다정 100밀리그램", item_seq: "200000001" },
      { input_text: "라마바", item_seq: null },
    ]);
  });

  it("canRegister: 이름이 있는 줄이 1개 이상이면 된다(질문은 보지 않는다)", () => {
    expect(canRegister([row({ readName: "가" })])).toBe(true);
    expect(canRegister([row({ readName: " " })])).toBe(false);
    expect(canRegister([])).toBe(false);
    expect(canRegister([row({ readName: "", candidates: [CANDIDATE], picked: CANDIDATE })])).toBe(true);
  });

  it("destination=profile: 카드에 질문칸이 없고 약이 1개 이상이면 `이대로 확인`이 켜진다. 안내·고지·후보(기본 선택 없음)는 채팅 목적지와 같다", async () => {
    const onRegister = vi.fn();
    const { user } = setup({ destination: "profile", onRegister });
    const card = await toCard(user);
    expect(modal()).toHaveAttribute("data-destination", "profile");
    expect(card).toHaveAttribute("data-destination", "profile");
    expect(within(card).queryByTestId("photo-question")).toBeNull();
    expect(within(card).queryByLabelText(copy.PHOTO_QUESTION_LABEL)).toBeNull();
    expect(within(card).getByTestId("photo-confirm-guide").textContent).toBe(copy.PHOTO_CONFIRM_GUIDE);
    expect(within(card).getByTestId("drug-data-scope-notice").textContent).toBe(copy.DRUG_DATA_SCOPE_NOTICE);
    for (const radio of within(card).getAllByRole("radio")) expect(radio).toHaveAttribute("aria-checked", "false");
    expect(confirmButton().disabled).toBe(false); // 읽은 줄 2개
    for (const remove of within(modal()).getAllByTestId("photo-row-remove")) await user.click(remove);
    expect(confirmButton().disabled).toBe(true);
    await user.click(within(modal()).getByTestId("photo-add-row"));
    expect(confirmButton().disabled).toBe(true);
    await user.type(nameInputs()[0], "사아자정");
    expect(confirmButton().disabled).toBe(false);
  });

  it("destination=profile: `이대로 확인`은 onRegister로 이름만 한 번 넘기고 onConfirm(채팅)은 부르지 않는다. 모달은 닫히고 /chat은 0회", async () => {
    const onRegister = vi.fn();
    const { user, onConfirm, onOpenChange } = setup({ destination: "profile", onRegister });
    await toCard(user);
    await user.click(within(rows()[0]).getAllByRole("radio")[1]); // 500밀리그램 후보
    await user.click(confirmButton());
    expect(onRegister).toHaveBeenCalledTimes(1);
    expect(onRegister).toHaveBeenCalledWith([
      { input_text: "가나다정 500밀리그램", item_seq: "200000002" },
      { input_text: "라마바캡슐", item_seq: null },
    ]);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(chatCalls).toBe(0);
    expect(ingestCalls).toBe(1);
  });

  it("destination=profile: 사진 고르기 화면의 가림 안내(P1)·외부 AI 전송 고지(P2, 제공자 OpenAI)·형식 안내(P7)는 채팅 목적지와 같은 글자 그대로 보인다", () => {
    setup({ destination: "profile", onRegister: vi.fn() });
    expect(within(modal()).getByTestId("photo-privacy-notice").textContent).toBe(copy.PHOTO_PRIVACY_NOTICE);
    expect(within(modal()).getByTestId("photo-external-ai-notice").textContent).toBe(copy.PHOTO_EXTERNAL_AI_NOTICE);
    expect(within(modal()).getByTestId("photo-external-ai-notice").textContent).toBe(OPENAI_NOTICE);
    expect(within(modal()).getByTestId("photo-format-note").textContent).toBe(copy.PHOTO_FORMAT_NOTE);
    expect(within(modal()).getByTestId("layer-emergency-entry")).toHaveAttribute("href", "tel:119");
  });

  it("destination 기본값은 chat: 카드에 질문칸이 있고 data-destination=chat이다(기존 동작 그대로). 전송 고지의 제공자도 OpenAI다", async () => {
    const { user } = setup();
    expect(within(modal()).getByTestId("photo-external-ai-notice").textContent).toBe(OPENAI_NOTICE);
    const card = await toCard(user);
    expect(modal()).toHaveAttribute("data-destination", "chat");
    expect(within(card).getByTestId("photo-question")).toBeInTheDocument();
  });

  it("사진 전송 고지(P2)는 제공자가 OpenAI다(2026-11-23 only OpenAI 확정, Upstage 표기 없음) 질문 경로 입력창 고지(INPUT_NOTICE)도 OpenAI 그대로다", () => {
    expect(copy.PHOTO_EXTERNAL_AI_NOTICE).toBe(OPENAI_NOTICE);
    expect(copy.PHOTO_EXTERNAL_AI_NOTICE).toContain("외부 AI(OpenAI)");
    expect(copy.PHOTO_EXTERNAL_AI_NOTICE).not.toContain("Upstage");
    expect(INPUT_NOTICE).toContain("외부 AI(OpenAI)");
    expect(INPUT_NOTICE).not.toContain("Upstage");
  });

  it("stacked: 스크림·상자가 한 층 위(z-50)에 그려진다. 기본은 z-40", () => {
    setup({ stacked: true });
    expect(modal().className).toMatch(/\bz-50\b/);
    expect(screen.getByTestId("photo-scrim").className).toMatch(/\bz-50\b/);
  });
});

describe("MSW 사진 핸들러(합성 규칙)", () => {
  /** PNG 머리 24바이트(서명 + IHDR 길이·종류 + 가로 4바이트)만 담은 data URL */
  const pngHead = (width: number) => {
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52, 0, 0, 0, 0, 0, 0, 0, 1]);
    new DataView(bytes.buffer).setUint32(16, width);
    return `data:image/png;base64,${btoa(String.fromCharCode(...bytes))}`;
  };

  it("PNG 가로 픽셀 수로 시나리오를 고르고, JPEG는 ok다", () => {
    for (const name of Object.keys(PHOTO_SCENARIO_PNG_WIDTH) as PhotoScenarioName[]) {
      expect(pngWidth(pngHead(PHOTO_SCENARIO_PNG_WIDTH[name]))).toBe(PHOTO_SCENARIO_PNG_WIDTH[name]);
      expect(pickPhotoScenario(pngHead(PHOTO_SCENARIO_PNG_WIDTH[name]))).toBe(name);
    }
    expect(pngWidth("data:image/jpeg;base64,/9j/4AAQ")).toBeNull();
    expect(pickPhotoScenario("data:image/jpeg;base64,/9j/4AAQ")).toBe("ok");
    expect(pickPhotoScenario(pngHead(1000))).toBe("ok");
  });

  it("본문 모양이 틀리면 422 {code, fields}(값은 되돌려 주지 않는다)", async () => {
    const response = await fetch("http://localhost/api/ingest/image", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image: "data:image/gif;base64,R0lG" }) });
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ code: "INVALID_REQUEST", fields: ["image"] });
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
});

describe("코드 점검(RFP-35-03, 〔D5〕A)", () => {
  const SRC = path.resolve(__dirname, "../..");
  const listSources = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) return listSources(full);
      return /\.(ts|tsx)$/.test(name) && !/\.(test|spec)\./.test(name) ? [full] : [];
    });

  it("프런트 디렉터리에 응급 키워드 목록·감지 함수 이름이 없다(백엔드 가드레일 상수·함수 이름 0건)", () => {
    // 금지 이름을 리터럴로 적으면 이 시험 파일이 백엔드 가드레일 검사(test_ag08_guardrail.py)에 걸리므로 조각을 조립한다.
    const forbidden = [["EMERGENCY", "KEYWORDS"].join("_"), ["detect", "emergency"].join("_")];
    const pattern = new RegExp(forbidden.join("|"));
    const hits = listSources(SRC).filter((file) => pattern.test(readFileSync(file, "utf8")));
    expect(hits).toEqual([]);
  });

  it("미식별 결과 카드 아래 두 번째 입구(`약 사진 올리기`)는 이번에 만들지 않는다(〔D5〕A): 결과·사진 화면 코드에 그 글자가 없다", () => {
    const files = [...listSources(path.join(SRC, "features/result")), ...listSources(path.join(SRC, "features/photo")), ...listSources(path.join(SRC, "app/(shell)"))];
    const hits = files.filter((file) => readFileSync(file, "utf8").includes('"약 사진 올리기"'));
    expect(hits).toEqual([]);
  });
});
