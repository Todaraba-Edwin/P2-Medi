import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { DRUG_DATA_SCOPE_NOTICE as ACCOUNT_DRUG_DATA_SCOPE_NOTICE } from "@/features/account/copy";
import { PHRASES } from "@/mocks/fixtures/phrases";
import { PHOTO_SCENARIO_PNG_WIDTH, createPhotoHandlers, pickPhotoScenario, pngWidth } from "@/mocks/photo-handlers";
import type { PhotoScenarioName } from "@/mocks/photo-handlers";
import { buildChatInput, canConfirm, emptyRow, rowsFromResponse } from "./build-chat-input";
import type { PhotoRow } from "./build-chat-input";
import * as copy from "./copy";
import { initialPhotoFlow, photoFlowReducer } from "./flow";
import { PHOTO_ACCEPT, PhotoImageError, prepareImage } from "./image";
import { PhotoModal } from "./PhotoModal";
import type { PhotoModalProps } from "./PhotoModal";
import type { IngestDrug } from "./types";

// 사진 입력 화면(FE-05 사진 부분)을 MSW 목(`photo-handlers.ts`)에 붙여 본다. 실제 서버 호출 0, 실제 사진 0(합성 바이트).
// H19·〔D7〕A: 이 화면은 `/chat`을 부르지 않는다 — 요청 기록으로 0회를 고정한다.

const server = setupServer();
let chatCalls = 0;
let ingestCalls = 0;
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", ({ request }) => {
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith("/api/chat")) chatCalls += 1;
    if (pathname.endsWith("/api/ingest/image")) ingestCalls += 1;
  });
});
beforeEach(() => {
  chatCalls = 0;
  ingestCalls = 0;
  server.use(
    http.post("*/api/chat", () => HttpResponse.json({ code: "NOT_IMPLEMENTED", fields: [] }, { status: 501 })),
    ...createPhotoHandlers(),
  );
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const PNG_URL = "data:image/png;base64,iVBORw0KGgo=";
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
  render(
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
  return { user, onConfirm, onTypeInstead, onOpenChange };
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
