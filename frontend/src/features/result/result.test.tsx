import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RESULT_SAMPLES } from "@/app/dev/preview/result/samples";
import { initialStreamState, streamReducer } from "@/lib/api";
import type { ChatResponse, Finding } from "@/lib/api";
import { PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatThread } from "../chat/ChatThread";
import { CandidateCard } from "./CandidateCard";
import * as copy from "./copy";
import { IngredientChip, IngredientChips } from "./IngredientChips";
import { ProductLine } from "./ProductLine";
import { ResultCard } from "./ResultCard";
import { ResultView } from "./ResultView";
import { StatusBadge } from "./StatusBadge";

const texts = (elements: Element[]) => elements.map((el) => el.textContent);
const sample = (id: string) => RESULT_SAMPLES.find((s) => s.id === id)!.response;
const line = (finding: Finding) => render(<ul><ProductLine finding={finding} /></ul>);

describe("StatusBadge", () => {
  it.each([
    ["contra_pair", "bg-red"],
    ["pregnancy", "bg-preg"],
    ["age", "bg-red"],
    ["dose", "bg-warn-bg"],
  ])("%s 종류는 %s 색 토큰을 고르고 글자는 받은 그대로다", (kind, className) => {
    render(<StatusBadge badge={{ kind, grade: null, source: null, text: "받은 배지 글자", evidence_id: null, note: null }} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge).toHaveTextContent("받은 배지 글자");
    expect(badge.textContent).toBe("받은 배지 글자");
    expect(badge).toHaveClass(className);
  });

  it("임부금기 1·2·M등급은 같은 색이고 등급 글자는 응답 값이다", () => {
    const badges = [
      ...fixtures.gradeMismatchResponse.findings[0].badges,
      ...fixtures.pregnancyMResponse.findings[0].badges,
    ];
    render(<>{badges.map((badge, i) => <StatusBadge key={i} badge={badge} />)}</>);
    const rendered = screen.getAllByTestId("status-badge");
    expect(new Set(rendered.map((el) => el.className)).size).toBe(1);
    expect(texts(rendered)).toEqual(badges.map((b) => b.text));
  });

  it("아이콘·이미지·소리 요소가 없다", () => {
    const { container } = render(<StatusBadge badge={fixtures.foundResponse.findings[0].badges[0]} />);
    expect(container.querySelector("svg, img, audio")).toBeNull();
  });
});

describe("ProductLine", () => {
  it("배지는 응답 배열 순서 그대로, 글자 그대로 그린다(재정렬·합치기 없음)", () => {
    const finding = sample("three-badges").findings[0];
    line(finding);
    expect(texts(screen.getAllByTestId("status-badge"))).toEqual(finding.badges.map((b) => b.text));
    expect(finding.badges).toHaveLength(3);
    // 화면이 순서를 정하지 않는다: 뒤집어 줘도 뒤집힌 그대로 그린다
    const reversed = { ...finding, badges: [...finding.badges].reverse() };
    render(<ul><ProductLine finding={reversed} /></ul>);
    const second = screen.getAllByTestId("product-line")[1];
    expect(texts(within(second).getAllByTestId("status-badge"))).toEqual(reversed.badges.map((b) => b.text));
  });

  it("제목은 응답의 drug 그대로이고 배지보다 먼저 온다", () => {
    const finding = fixtures.foundResponse.findings[0];
    line(finding);
    const title = screen.getByTestId("line-title");
    expect(title.textContent).toBe(finding.drug);
    expect(title.compareDocumentPosition(screen.getByTestId("line-status")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(title).toHaveClass("flex-none", "max-w-full"); // 제목이 먼저 전체 폭을 갖는다
    expect(screen.getByTestId("line-status")).toHaveClass("flex-wrap"); // 배지 줄은 flex-wrap 한 규칙
  });

  it("'목록에 없음' 줄: 응답의 text(안전 아님 문구 포함)를 그대로, 접힘 요소 밖에 항상 보인다", () => {
    const finding = fixtures.notListedResponse.findings[0];
    const { container } = line(finding);
    const text = screen.getByTestId("line-text");
    expect(text.textContent).toBe(PHRASES.NOT_LISTED);
    expect(text.textContent).toContain("안전하다는 뜻이 아님");
    expect(text).toBeVisible();
    expect(text.closest("details, [hidden], [aria-hidden='true'], [data-state='closed']")).toBeNull();
    expect(container.querySelector("details")).toBeNull();
    expect(screen.queryByTestId("status-badge")).toBeNull(); // "삐!" 배지 없음
    expect(container.textContent).not.toContain("삐!");
  });

  it("미식별 줄: 판정 글자와 이유·다음 행동을 받은 그대로 보인다", () => {
    const finding = fixtures.unidentifiedResponse.findings[0];
    const { container } = line(finding);
    expect(screen.getByTestId("line-text").textContent).toBe(PHRASES.UNIDENTIFIED);
    for (const value of [finding.why, finding.retried_line, finding.next]) expect(screen.getByText(value!)).toBeInTheDocument();
    expect(container.textContent).not.toContain("삐!");
    expect(screen.getByTestId("product-line")).toHaveAttribute("data-bucket", "unconfirmed");
  });

  it("연령금기: 배지 글자는 그대로이고 나이 기준 값은 보조줄에 원문 그대로 있다", () => {
    const finding = fixtures.ageFoundResponse.findings[0];
    const { container } = line(finding);
    expect(texts(screen.getAllByTestId("status-badge"))).toEqual([PHRASES.BADGE_AGE]);
    const sub = container.querySelectorAll('[data-slot="age-criteria"]');
    expect(texts([...sub])).toEqual(finding.age_criteria);
    expect(screen.getByTestId("status-badge").textContent).not.toContain(finding.age_criteria[0]);
  });

  it("나이 기준 값이 비면 보조줄을 그리지 않고, 안내 문구(age_info_line)는 값이 올 때만 그린다", () => {
    const finding = { ...fixtures.ageFoundResponse.findings[0], age_criteria: [] };
    const { container, rerender } = line(finding);
    expect(container.querySelector('[data-slot="age-criteria"], [data-slot="age-info"]')).toBeNull();
    rerender(<ul><ProductLine finding={{ ...finding, age_info_line: "받은 안내 문구" }} /></ul>);
    expect(container.querySelector('[data-slot="age-info"]')?.textContent).toBe("받은 안내 문구");
  });

  it("M등급 덧붙임 글은 한 번만 보인다", () => {
    line(fixtures.pregnancyMResponse.findings[0]);
    expect(screen.getAllByText(PHRASES.BADGE_PREGNANCY_M_NOTE)).toHaveLength(1);
    expect(texts(screen.getAllByTestId("status-badge"))).toEqual([PHRASES.BADGE_PREGNANCY_M]);
  });

  it("날짜·시각 줄이 없다(FE-07-06 A)", () => {
    const { container } = render(<ResultCard response={fixtures.pairAndPregnancyResponse} />);
    expect(screen.queryByTestId("date-lines")).toBeNull();
    expect(container.textContent).not.toMatch(/\d{4}-\d{2}(-\d{2})?|고시일|기준일|조회/);
  });
});

/** 칩의 성분 이름(상태 글자를 뺀 첫 글자 덩어리) */
const chipNames = () => screen.getAllByTestId("ingredient-chip").map((el) => el.firstChild?.textContent);

describe("IngredientChips", () => {
  const finding = fixtures.pregnancyResponse.findings[0];

  it("4개까지는 받은 순서 그대로 모두 보이고 표시명은 받은 그대로다", () => {
    render(<IngredientChips ingredients={finding.ingredients} />);
    expect(chipNames()).toEqual(finding.ingredients.map((i) => i.name));
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("상태는 칩마다 data-state로 구분하고, 상태 글자는 응답의 state_labels 그대로다(BE-06-13)", () => {
    render(<IngredientChips ingredients={finding.ingredients} />);
    const chips = screen.getAllByTestId("ingredient-chip");
    expect(chips.map((el) => el.getAttribute("data-state"))).toEqual(["cause", "dup"]);
    // fixture 값: 임부금기 원인 성분 = "금기 원인", 중복 성분 = "중복"
    expect(chips.map((el) => [...el.querySelectorAll("[data-slot='state-label']")].map((label) => label.textContent?.replace(/[\s·\u00a0]/g, "")))).toEqual([
      ["금기원인"],
      ["중복"],
    ]);
  });

  it("상태 글자는 프런트가 짓지 않는다: 글자 칸이 비면 그리지 않고, 다른 글자가 오면 그 글자를 받은 순서대로 그린다", () => {
    const base = finding.ingredients[0]; // contra_kinds가 있는 성분
    const { rerender } = render(<IngredientChip ingredient={{ ...base, state_labels: [] }} />);
    expect(screen.getByTestId("ingredient-chip").textContent).toBe(base.name);
    rerender(<IngredientChip ingredient={{ ...base, contra_kinds: [], dup: false, state_labels: ["받은 글자 하나", "받은 글자 둘"] }} />);
    expect(screen.getByTestId("ingredient-chip")).toHaveTextContent(`${base.name} · 받은 글자 하나 · 받은 글자 둘`);
  });

  it("성분코드 미확보 안내는 받은 글자를 한 번만 칩 줄 아래에 그린다", () => {
    const list = finding.ingredients.map((ingredient) => ({ ...ingredient, code: null, code_missing_text: "받은 코드 미확보 안내" }));
    const { container, rerender } = render(<IngredientChips ingredients={list} />);
    expect(texts([...container.querySelectorAll("[data-slot='code-missing']")])).toEqual(["받은 코드 미확보 안내"]);
    rerender(<IngredientChips ingredients={finding.ingredients} />);
    expect(container.querySelector("[data-slot='code-missing']")).toBeNull();
  });

  it("5개 이상이면 원인·중복 성분만 먼저 보이고 '외 N개'를 누르면 받은 순서 그대로 모두 보인다", async () => {
    const all = sample("many-ingredients").findings[0].ingredients;
    render(<IngredientChips ingredients={all} />);
    expect(chipNames()).toEqual(["두울성분", "네엣성분"]);
    const more = screen.getByRole("button", { name: copy.moreIngredientsLabel(4) });
    await userEvent.click(more);
    expect(chipNames()).toEqual(all.map((i) => i.name));
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("5개 이상인데 원인·중복이 없으면 앞의 3개만 먼저 보인다", () => {
    const plain = sample("many-ingredients").findings[0].ingredients.map((i) => ({ ...i, contra_kinds: [], dup: false }));
    render(<IngredientChips ingredients={plain} />);
    expect(chipNames()).toEqual(plain.slice(0, 3).map((i) => i.name));
    expect(screen.getByRole("button", { name: copy.moreIngredientsLabel(3) })).toBeInTheDocument();
  });

  it("성분이 없으면 줄을 그리지 않는다", () => {
    const { container } = render(<IngredientChips ingredients={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ResultCard·ResultView", () => {
  it("판정 줄은 응답 배열 순서 그대로다", () => {
    const response = fixtures.pairAndPregnancyResponse;
    render(<ResultCard response={response} />);
    expect(texts(screen.getAllByTestId("line-title"))).toEqual(response.findings.map((f) => f.drug));
    expect(screen.getAllByTestId("product-line").map((el) => el.getAttribute("data-target"))).toEqual(["pair", "product"]);
    const reversed: ChatResponse = { ...response, findings: [...response.findings].reverse() };
    render(<ResultCard response={reversed} />);
    const second = screen.getAllByTestId("result-card")[1];
    expect(texts(within(second).getAllByTestId("line-title"))).toEqual(reversed.findings.map((f) => f.drug));
  });

  it.each(RESULT_SAMPLES.map((s) => [s.id, s.response] as const))("%s: 렌더 글자가 응답 값과 같다", (_id, response) => {
    const { container } = render(<ResultView response={response} onPickCandidate={() => {}} />);
    if (response.summary !== null) expect(screen.getByTestId("result-summary").textContent).toBe(response.summary);
    else expect(screen.queryByTestId("result-summary")).toBeNull();
    if (response.notice !== null) expect(screen.getByTestId("result-notice").textContent).toBe(response.notice);
    if (response.name_corrections.length > 0) {
      expect(texts([...screen.getByTestId("name-corrections").querySelectorAll("li")])).toEqual(response.name_corrections.map((c) => c.text));
    } else expect(screen.queryByTestId("name-corrections")).toBeNull();
    const lines = screen.queryAllByTestId("product-line");
    expect(lines).toHaveLength(response.findings.length);
    response.findings.forEach((finding, index) => {
      const el = within(lines[index]);
      expect(el.getByTestId("line-title").textContent).toBe(finding.drug);
      if (finding.badges.length) expect(texts(el.getAllByTestId("status-badge"))).toEqual(finding.badges.map((b) => b.text));
      else expect(el.getByTestId("line-text").textContent).toBe(finding.text);
    });
    // 마스코트·이미지·펼침 요소 0개
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(container.querySelector("img, details, audio")).toBeNull();
  });

  it("요약은 가공하지 않는다(줄바꿈·숫자·기호 그대로)", () => {
    const summary = "첫 줄 요약이에요.\n둘째 줄: 1) 가나다정 2) 라마바캡슐 — 그대로";
    render(<ResultView response={{ ...fixtures.foundResponse, summary }} />);
    expect(screen.getByTestId("result-summary").textContent).toBe(summary);
    expect(screen.getByTestId("result-summary")).toHaveClass("whitespace-pre-wrap");
  });

  it("판정 줄이 없으면 카드를 그리지 않는다(거절·되묻기)", () => {
    render(<ResultView response={fixtures.refuseResponse} />);
    expect(screen.queryByTestId("result-card")).toBeNull();
    expect(screen.getByTestId("result-summary").textContent).toBe(fixtures.refuseResponse.summary);
  });

  it("대상이 아닌 종류는 응답에 줄이 없으면 그리지 않는다('해당 없음' 상태를 만들지 않는다)", () => {
    const { container } = render(<ResultCard response={fixtures.foundResponse} />);
    expect(screen.getAllByTestId("product-line")).toHaveLength(1);
    expect(container.textContent).not.toMatch(/해당 없음|임부금기/);
  });

  it("머리글은 기준 글자를 받으면 붙이고, 아래 자리(footer)를 받는다", () => {
    render(<ResultCard response={fixtures.foundResponse} basis="받은 기준 글자" footer={<button type="button">받은 버튼</button>} />);
    expect(screen.getByText(copy.RESULT_HEADING)).toBeInTheDocument();
    expect(screen.getByTestId("result-basis").textContent).toBe("받은 기준 글자");
    expect(screen.getByRole("button", { name: "받은 버튼" })).toBeInTheDocument();
  });

  it("카드 안에는 마스코트가 그려지지 않는다(NoMascotZone)", async () => {
    const { Mascot } = await import("@/components/Mascot");
    render(<ResultCard response={fixtures.foundResponse} footer={<Mascot variant="search" />} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });

  it("copy.ts에는 판정·배지·상태 글자가 없다", () => {
    const all = JSON.stringify({ ...copy, more: copy.moreIngredientsLabel(2) });
    expect(all).not.toMatch(/삐!|금기 원인|중복|목록에 없음|안전|단계/);
  });
});

describe("CandidateCard", () => {
  const candidates = fixtures.clarifyResponse.candidates;

  it("selected를 주면 고른 후보만 눌린 상태(aria-pressed)이고, 눌러도 onPick만 부른다", async () => {
    const onPick = vi.fn();
    const { rerender } = render(<CandidateCard candidates={candidates} onPick={onPick} selected={null} />);
    expect(screen.getAllByTestId("candidate").map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "false", "false"]);
    await userEvent.click(screen.getAllByTestId("candidate")[1]);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(candidates[1]);
    rerender(<CandidateCard candidates={candidates} onPick={onPick} selected={candidates[1]} />);
    expect(screen.getAllByTestId("candidate").map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
  });

  it("selected를 주지 않으면 눌린 상태 속성이 없다", () => {
    render(<CandidateCard candidates={candidates} onPick={() => {}} />);
    for (const button of screen.getAllByTestId("candidate")) expect(button.hasAttribute("aria-pressed")).toBe(false);
  });

  it("후보의 이름·업체·구분을 받은 그대로, 받은 순서대로 보이고 판정 표시가 없다", () => {
    const { container } = render(<CandidateCard candidates={candidates} onPick={() => {}} />);
    const buttons = screen.getAllByTestId("candidate");
    expect(buttons).toHaveLength(candidates.length);
    buttons.forEach((button, index) => {
      expect(button.querySelector("b")?.textContent).toBe(candidates[index].name);
      expect(button.querySelector('[data-slot="prescription"]')?.textContent).toBe(candidates[index].prescription);
      expect(button.querySelector('[data-slot="entp-name"]')?.textContent).toBe(candidates[index].entp_name);
    });
    expect(screen.getByTestId("candidate-group").querySelector("header")?.textContent).toBe(candidates[0].input_name);
    expect(container.textContent).not.toMatch(/삐!|금기|안전|먹어도/);
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("누르면 그 후보를 콜백으로 넘기고 스스로는 아무것도 보내지 않는다", async () => {
    const onPick = vi.fn();
    const onOther = vi.fn();
    render(<CandidateCard candidates={candidates} onPick={onPick} onOther={onOther} />);
    await userEvent.click(screen.getAllByTestId("candidate")[1]);
    expect(onPick).toHaveBeenCalledExactlyOnceWith(candidates[1]);
    await userEvent.click(screen.getByRole("button", { name: copy.CANDIDATE_OTHER_LABEL }));
    expect(onOther).toHaveBeenCalledTimes(1);
  });

  it("onOther가 없으면 직접 입력 버튼이 없고, 값이 없는 칸은 그리지 않는다", () => {
    render(<CandidateCard candidates={[{ ...candidates[0], entp_name: null, prescription: null }]} onPick={() => {}} />);
    expect(screen.queryByRole("button", { name: copy.CANDIDATE_OTHER_LABEL })).toBeNull();
    expect(screen.getByTestId("candidate").querySelectorAll("[data-slot]")).toHaveLength(0);
  });

  it("되묻는 입력이 여럿이면 입력별로 나누고 순서를 지킨다", () => {
    const two = [candidates[0], { ...candidates[1], input_name: "라마바" }, candidates[2]];
    render(<CandidateCard candidates={two} onPick={() => {}} />);
    const groups = screen.getAllByTestId("candidate-group");
    expect(groups.map((g) => g.querySelector("header")?.textContent)).toEqual([candidates[0].input_name, "라마바"]);
    expect(within(groups[0]).getAllByTestId("candidate")).toHaveLength(2);
  });

  it("ResultView: 되묻기 응답이고 콜백이 있을 때만 후보 카드를 그린다", () => {
    const { rerender } = render(<ResultView response={fixtures.clarifyResponse} onPickCandidate={() => {}} />);
    expect(screen.getByTestId("candidate-card")).toBeInTheDocument();
    expect(screen.getByTestId("result-summary").textContent).toBe(fixtures.clarifyResponse.summary);
    rerender(<ResultView response={fixtures.clarifyResponse} />);
    expect(screen.queryByTestId("candidate-card")).toBeNull();
    rerender(<ResultView response={fixtures.foundResponse} onPickCandidate={() => {}} />);
    expect(screen.queryByTestId("candidate-card")).toBeNull();
  });
});

describe("T1: 진행 표시는 서버가 준 문구(label)를 쓴다", () => {
  const streaming = streamReducer(initialStreamState, { type: "start" });
  const turn = (stream: typeof streaming) => [{ id: "t1", question: "질문", stream }];

  it("label이 있으면 그 글자를 지금 줄에 쓴다", () => {
    const event = { ...scenarios.found.events[1], label: "서버가 보낸 진행 문구" };
    render(<ChatThread turns={turn(streamReducer(streaming, { type: "event", event }))} hasEmergency={false} onRetry={() => {}} />);
    expect(texts(screen.getAllByRole("listitem"))).toEqual(["약 찾는 중", "서버가 보낸 진행 문구", "근거 찾는 중"]);
  });

  it("label이 없으면(이벤트 전) 기존 상수 문구다", () => {
    render(<ChatThread turns={turn(streaming)} hasEmergency={false} onRetry={() => {}} />);
    expect(texts(screen.getAllByRole("listitem"))).toEqual(["약 찾는 중", "금기 확인 중", "근거 찾는 중"]);
  });
});

describe("AG-08 새 칸(받은 값 그대로)", () => {
  it("식별된 약 줄: 표지 `찾음`과 보조줄(성분 이름)을 그리고 같은 이름의 칩은 한 번 더 그리지 않는다", () => {
    const line = fixtures.pairNoEvidenceResponse.findings[0];
    render(<ul><ProductLine finding={line} /></ul>);
    expect(screen.getByTestId("line-text").textContent).toBe(PHRASES.IDENTIFIED_LINE);
    expect(screen.getByTestId("product-line").querySelector("[data-slot='sub-line']")?.textContent).toBe(line.sub_line);
    expect(screen.queryByTestId("ingredient-chips")).toBeNull();
    expect(screen.getByTestId("product-line").textContent).not.toContain("금기 목록에 없음");
  });

  it("쌍 확인 불가 줄: 문장은 줄 글자로 한 번만 보인다(notes·why·next가 오지 않는다)", () => {
    const line = fixtures.pairNoEvidenceResponse.findings[1];
    render(<ul><ProductLine finding={line} /></ul>);
    expect(screen.getAllByText(PHRASES.PAIR_NOT_CHECKED)).toHaveLength(1);
    expect(screen.getByTestId("product-line").querySelector("[data-slot='notes'], [data-slot='why'], [data-slot='next']")).toBeNull();
  });

  it("약을 찾지 못한 줄: 보조줄은 서버가 조사까지 고른 글자 그대로다", () => {
    const line = fixtures.unidentifiedResponse.findings[0];
    render(<ul><ProductLine finding={line} /></ul>);
    const sub = screen.getByTestId("product-line").querySelector("[data-slot='sub-line']");
    expect(sub?.textContent).toBe(line.sub_line);
    expect(sub?.textContent).toMatch(/^차카타파정을 /);
    expect(sub?.textContent).not.toContain("을(를)");
  });

  it("나이 안내 줄은 나이 기준 값 위에 받은 글자로, 값은 한 값에 한 줄씩 받은 순서로 보인다(판정 배지 없음)", () => {
    const line = fixtures.ageInfoResponse.findings[0];
    render(<ul><ProductLine finding={line} /></ul>);
    const slots = [...screen.getByTestId("product-line").querySelectorAll("[data-slot='age-info'], [data-slot='age-criteria']")];
    expect(slots.map((el) => [el.getAttribute("data-slot"), el.textContent])).toEqual([
      ["age-info", PHRASES.AGE_INFO_LINE],
      ["age-criteria", "12세 미만"],
      ["age-criteria", "6개월 미만"],
    ]);
    expect(screen.queryByTestId("status-badge")).toBeNull();
    expect(screen.getByTestId("product-line").closest("details")).toBeNull();
  });

  it("나이 안내 줄이 오지 않으면 그리지 않는다(프런트가 안내 문구를 갖지 않는다)", () => {
    render(<ul><ProductLine finding={fixtures.ageFoundResponse.findings[0]} /></ul>);
    expect(screen.getByTestId("product-line").querySelector("[data-slot='age-info']")).toBeNull();
    expect(JSON.stringify(copy)).not.toContain("나이");
  });

  it("확인하지 못한 종류의 줄: 받은 순서·글자 그대로, 접히지 않는 자리에 보인다", () => {
    const response = { ...fixtures.notCheckedResponse, not_checked_lines: ["받은 줄 하나", "받은 줄 둘"] };
    render(<ResultView response={response} />);
    const list = screen.getByTestId("not-checked-lines");
    expect(texts([...list.querySelectorAll("li")])).toEqual(["받은 줄 하나", "받은 줄 둘"]);
    expect(list.closest("details, [data-state='closed']")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();
  });

  it("확인하지 못한 줄이 없으면 그 자리를 그리지 않는다", () => {
    render(<ResultView response={fixtures.foundResponse} />);
    expect(screen.queryByTestId("not-checked-lines")).toBeNull();
    expect(screen.queryByTestId("candidates-line")).toBeNull();
  });

  it("되묻기 안내는 받은 글자 그대로 후보 카드 아래에 보인다", () => {
    const response = { ...fixtures.clarifyResponse, candidates_line: "받은 되묻기 안내" };
    render(<ResultView response={response} onPickCandidate={() => {}} />);
    const line = screen.getByTestId("candidates-line");
    expect(line.textContent).toBe("받은 되묻기 안내");
    expect(screen.getByTestId("candidate-card").compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fixtures.clarifyResponse.candidates_line).toBe(PHRASES.CLARIFY_PICK_LINE);
  });

  it("공공 API 실패 배너(notice의 새 값)도 받은 글자 그대로 보인다", () => {
    render(<ResultView response={fixtures.apiFailResponse} />);
    expect(screen.getByTestId("result-notice").textContent).toBe(PHRASES.NOTICE_API_FAIL);
  });
});

describe("FE-02 보정 고지(name_corrections)", () => {
  const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("고지 줄은 요약보다 먼저, 배너보다 뒤에, 받은 글자·순서 그대로 접히지 않는 자리에 보인다(읽기 순서 = DOM 순서)", () => {
    const response: ChatResponse = {
      ...fixtures.typoCorrectedResponse,
      notice: PHRASES.NOTICE_API_FAIL,
      name_corrections: [
        { input: "가", name: "가나", text: "받은 고지 하나" },
        { input: "나", name: "나다", text: "받은 고지 둘" },
      ],
    };
    const { container } = render(<ResultView response={response} />);
    const list = screen.getByTestId("name-corrections");
    expect(texts([...list.querySelectorAll("li")])).toEqual(["받은 고지 하나", "받은 고지 둘"]);
    expect(before(screen.getByTestId("result-notice"), list)).toBe(true);
    expect(before(list, screen.getByTestId("result-summary"))).toBe(true);
    expect(before(list, screen.getByTestId("result-card"))).toBe(true);
    expect(list.closest("details, [hidden], [aria-hidden='true'], [data-state='closed']")).toBeNull();
    expect(container.textContent).not.toContain("'가' → '가나'"); // 화면이 문장을 조립하지 않는다(input·name을 따로 그리지 않음)
    expect(within(list).queryByTestId("status-badge")).toBeNull();
    expect(list.textContent).not.toContain("삐!");
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(list.querySelector("svg, img, audio")).toBeNull();
  });

  it("fixture 고지는 서버가 완성한 문장(상수 + 두 이름) 그대로이고, 보정이 없으면 그 자리를 그리지 않는다", () => {
    const { rerender } = render(<ResultView response={fixtures.typoCorrectedResponse} />);
    const [correction] = fixtures.typoCorrectedResponse.name_corrections;
    expect(screen.getByTestId("name-corrections").textContent).toBe(correction.text);
    expect(correction.text).toBe(PHRASES.TYPO_CORRECTED_LINE.replace("{input}", correction.input).replace("{name}", correction.name));
    rerender(<ResultView response={fixtures.foundResponse} />);
    expect(screen.queryByTestId("name-corrections")).toBeNull();
  });

  it("copy.ts에 보정 고지 문구가 없다(문장은 서버 몫)", () => {
    expect(JSON.stringify(copy)).not.toMatch(/보정|비슷한|다시 알려/);
  });
});
