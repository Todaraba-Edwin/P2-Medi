import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RESULT_SAMPLES } from "@/app/dev/preview/result/samples";
import { initialStreamState, streamReducer } from "@/lib/api";
import type { ChatResponse, Finding } from "@/lib/api";
import { EvidenceDetail } from "@/features/evidence/EvidenceDetail";
import { API_FAIL_NOTE, API_NO_CODE_NOTE, PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import { scenarios } from "@/mocks/fixtures/scenarios";
import { ChatThread } from "../chat/ChatThread";
import { CandidateCard } from "./CandidateCard";
import { PickCapsule } from "./PickCapsule";
import { groupCandidates, isTakenElsewhere } from "./candidate-groups";
import * as copy from "./copy";
import { IngredientChip, IngredientChips } from "./IngredientChips";
import { ProductLine } from "./ProductLine";
import { ResultCard } from "./ResultCard";
import { ResultView } from "./ResultView";
import { RetryActions } from "./RetryActions";
import { CHIP_CLASS } from "@/components/chip";
import { ExampleChips } from "../chat/ExampleChips";
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

  it("병용금기 쌍 줄: 받은 사유 원문이 `사유:` 보조줄에 한 줄씩 글자 그대로 있고 2줄 말줄임이다(FE-02-06 A)", () => {
    const long = "합성 긴 사유 문장 ".repeat(30).trim();
    const finding = { ...fixtures.foundResponse.findings[0], reasons: [long, "둘째 사유"] };
    const { container } = line(finding);
    const reasons = [...container.querySelectorAll('[data-slot="reason"]')];
    expect(texts(reasons)).toEqual([`사유: ${long}`, "사유: 둘째 사유"]); // 글자를 자르지 않는다(DOM 전체 글자)
    for (const reason of reasons) expect(reason.className).toContain("line-clamp-2");
    expect(screen.getByTestId("status-badge").textContent).not.toContain("사유");
    expect(container.textContent).not.toMatch(/\d+\s?(mg|밀리그램|정|캡슐)\b/); // 카드에 용량 숫자가 없다(RFP-21-03)
  });

  it("사유 칸이 비어 있으면(서버가 주기 전·용량 숫자로 뺀 경우) 사유 줄을 그리지 않는다", () => {
    const { container } = line({ ...fixtures.foundResponse.findings[0], reasons: [] });
    expect(container.querySelector('[data-slot="reason"]')).toBeNull();
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

describe("성분 칩의 모름(contra_kinds·dup이 null, BE-06-40 A)", () => {
  const known = fixtures.notListedResponse.findings[0].ingredients[0]; // 지금 서버 모양: `[]`·`false`
  const unknown = { ...known, contra_kinds: null, dup: null };
  const NOT_CAUSE_WORDS = /원인|중복|아님|해당 없음|안전|괜찮/;

  it("지금 서버 모양(`[]`·`false`)은 원인 아님(none), null은 모름(unknown)으로 구분된다", () => {
    expect(known).toMatchObject({ contra_kinds: [], dup: false });
    const { rerender } = render(<IngredientChip ingredient={known} />);
    expect(screen.getByTestId("ingredient-chip")).toHaveAttribute("data-state", "none");
    rerender(<IngredientChip ingredient={unknown} />);
    expect(screen.getByTestId("ingredient-chip")).toHaveAttribute("data-state", "unknown");
    expect(screen.getByTestId("ingredient-chip")).not.toHaveAttribute("data-kinds");
  });

  it("모름인 칩에는 화면이 상태 글자를 짓지 않는다: 이름만 그리고 원인·중복 색을 쓰지 않는다", () => {
    render(<IngredientChip ingredient={unknown} />);
    const chip = screen.getByTestId("ingredient-chip");
    expect(chip.textContent).toBe(unknown.name);
    expect(chip.querySelector("[data-slot='state-label']")).toBeNull();
    expect(chip.textContent).not.toMatch(NOT_CAUSE_WORDS);
    expect(chip.className).not.toMatch(/bg-(preg|combo|warn)-bg/);
  });

  it("모름인 칩도 서버가 상태 글자를 주면 그 글자를 그대로 그린다(state_labels만 따른다)", () => {
    render(<IngredientChip ingredient={{ ...unknown, state_labels: ["받은 상태 글자"] }} />);
    expect(screen.getByTestId("ingredient-chip")).toHaveTextContent(`${unknown.name} · 받은 상태 글자`);
  });

  it.each([
    ["원인 칸만 모름, 중복은 참", { contra_kinds: null, dup: true }, "dup"],
    ["원인 칸만 모름, 중복은 거짓", { contra_kinds: null, dup: false }, "unknown"],
    ["원인은 빈 목록, 중복만 모름", { contra_kinds: [], dup: null }, "unknown"],
    ["원인이 있고 중복은 모름", { contra_kinds: ["pregnancy"], dup: null }, "cause"],
  ])("한 칸만 모름: %s", (_name, patch, state) => {
    render(<IngredientChip ingredient={{ ...known, ...patch }} />);
    expect(screen.getByTestId("ingredient-chip")).toHaveAttribute("data-state", state);
  });

  it("복합제 제품 줄(칸 없음)의 칩은 모두 모름이고, 성분 하나인 줄의 칩은 원인으로 그린다", () => {
    const [combo, single] = fixtures.productRowsResponse.findings;
    const { unmount } = line(combo);
    expect(screen.getAllByTestId("ingredient-chip").map((el) => el.getAttribute("data-state"))).toEqual(combo.ingredients.map(() => "unknown"));
    expect(chipNames()).toEqual(combo.ingredients.map((i) => i.name));
    unmount();
    line(single);
    expect(screen.getAllByTestId("ingredient-chip").map((el) => el.getAttribute("data-state"))).toEqual(["cause"]);
  });

  it("5개 이상에서 모름은 먼저 보일 성분(원인·중복)으로 치지 않는다: 원인이 있으면 원인만, 없으면 앞의 3개", async () => {
    const names = ["하나성분", "두울성분", "세엣성분", "네엣성분", "다섯성분", "여섯성분"];
    const allUnknown = names.map((name) => ({ ...unknown, name }));
    const { unmount } = render(<IngredientChips ingredients={allUnknown} />);
    expect(chipNames()).toEqual(names.slice(0, 3));
    await userEvent.click(screen.getByRole("button", { name: copy.moreIngredientsLabel(3) }));
    expect(chipNames()).toEqual(names);
    unmount();
    const withCause = allUnknown.map((ingredient, index) => (index === 4 ? { ...ingredient, contra_kinds: ["pregnancy"], dup: false } : ingredient));
    render(<IngredientChips ingredients={withCause} />);
    expect(chipNames()).toEqual(["다섯성분"]);
  });
});

describe("evidence_id가 없는 제품 줄(BE-06-41 A)", () => {
  const response = fixtures.productRowsResponse;

  it("결과 카드: null 줄이 여럿이어도 줄이 받은 순서로 모두 나오고 React key 경고가 없다", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ResultCard response={response} />);
    const lines = screen.getAllByTestId("product-line");
    expect(response.findings.filter((f) => f.evidence_id === null).length).toBeGreaterThan(1);
    expect(texts(lines.map((el) => within(el).getByTestId("line-title")))).toEqual(response.findings.map((f) => f.drug));
    expect(lines.map((el) => el.getAttribute("data-target"))).toEqual(response.findings.map((f) => f.target));
    expect(error.mock.calls.filter((call) => /key/i.test(String(call[0])))).toEqual([]);
    error.mockRestore();
  });

  it("제품 줄의 배지는 받은 순서 그대로이고(병용 → 임부) kind가 없어도 data-kind를 짓지 않는다", () => {
    render(<ResultCard response={response} />);
    const lines = screen.getAllByTestId("product-line");
    response.findings.forEach((finding, index) => {
      expect(texts(within(lines[index]).getAllByTestId("status-badge"))).toEqual(finding.badges.map((b) => b.text));
      if (finding.kind === null) expect(lines[index]).not.toHaveAttribute("data-kind");
    });
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

  it("selected를 주면 고른 후보만 고른 상태(aria-checked)이고, 눌러도 onPick만 부른다", async () => {
    const onPick = vi.fn();
    const { rerender } = render(<CandidateCard candidates={candidates} onPick={onPick} selected={{}} />);
    expect(screen.getAllByTestId("candidate").map((button) => button.getAttribute("aria-checked"))).toEqual(["false", "false", "false"]);
    await userEvent.click(screen.getAllByTestId("candidate")[1]);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(candidates[1]);
    rerender(<CandidateCard candidates={candidates} onPick={onPick} selected={{ [candidates[1].input_name]: candidates[1] }} />);
    expect(screen.getAllByTestId("candidate").map((button) => button.getAttribute("aria-checked"))).toEqual(["false", "true", "false"]);
  });

  it("selected를 주지 않으면 모두 고르지 않은 상태다(라디오는 상태를 늘 알린다)", () => {
    render(<CandidateCard candidates={candidates} onPick={() => {}} />);
    for (const button of screen.getAllByTestId("candidate")) expect(button).toHaveAttribute("aria-checked", "false");
    expect(screen.getAllByRole("radio")).toHaveLength(candidates.length);
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
    expect(screen.getByTestId("candidate-group").querySelector('header [data-slot="group-name"]')?.textContent).toBe(candidates[0].input_name);
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
    expect(groups.map((g) => g.querySelector('header [data-slot="group-name"]')?.textContent)).toEqual([candidates[0].input_name, "라마바"]);
    expect(within(groups[0]).getAllByTestId("candidate")).toHaveLength(2);
  });

  describe("되묻는 이름이 둘 이상(FE-09)", () => {
    const multi = fixtures.clarifyMultiResponse.candidates;
    const [nameA, nameB] = [multi[0].input_name, multi[3].input_name];
    /** 고른 값을 들고 있는 조립 쪽 대역 */
    function Harness({ onOther }: { onOther?: () => void }) {
      const [picks, setPicks] = useState<Record<string, (typeof multi)[number]>>({});
      return <CandidateCard candidates={multi} selected={picks} onOther={onOther} onPick={(candidate) => setPicks((prev) => ({ ...prev, [candidate.input_name]: candidate }))} />;
    }
    const group = (index: number) => screen.getAllByTestId("candidate-group")[index];

    it("fixture: 묶음 둘, 묶음마다 후보 3~5개, 겹치는 제품 1개, 질문은 승인 원문(물음표 1개)", () => {
      expect([...new Set(multi.map((c) => c.input_name))]).toEqual([nameA, nameB]);
      for (const name of [nameA, nameB]) {
        const size = multi.filter((c) => c.input_name === name).length;
        expect(size).toBeGreaterThanOrEqual(3);
        expect(size).toBeLessThanOrEqual(5);
      }
      const seqA = multi.filter((c) => c.input_name === nameA).map((c) => c.item_seq);
      expect(multi.filter((c) => c.input_name === nameB && seqA.includes(c.item_seq))).toHaveLength(1);
      expect(fixtures.clarifyMultiResponse.summary).toBe(`'${nameA}', '${nameB}'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?`);
      expect(fixtures.clarifyMultiResponse.summary?.match(/\?/g)).toHaveLength(1);
    });

    it("고른 묶음은 한 줄 요약으로 접히고 초점이 '바꾸기'로 가며, '바꾸기'로 다시 펼치면 고른 값이 눌린 채 남는다", async () => {
      render(<Harness />);
      expect(screen.getAllByTestId("candidate")).toHaveLength(6);
      await userEvent.click(within(group(0)).getAllByTestId("candidate")[0]);
      // 첫 묶음만 접힌다: 입력한 이름 → 고른 제품 · 바꾸기
      expect(group(0)).toHaveAttribute("data-collapsed", "true");
      expect(within(group(0)).queryAllByTestId("candidate")).toHaveLength(0);
      expect(within(group(0)).getByTestId("candidate-picked").textContent).toBe(`A${nameA} ${copy.CANDIDATE_PICKED_ARROW} ${multi[0].name}${copy.CANDIDATE_CHANGE_LABEL}`); // 앞의 A는 묶음 표지(FE-10)
      const change = within(group(0)).getByRole("button", { name: `${nameA} ${copy.CANDIDATE_CHANGE_LABEL}` });
      expect(change).toHaveFocus();
      expect(group(1)).not.toHaveAttribute("data-collapsed");
      expect(within(group(1)).getAllByTestId("candidate")).toHaveLength(3);
      // 다시 펼친다: 고른 값은 그대로(눌린 상태)이고 초점이 그 후보로 간다
      await userEvent.click(change);
      const reopened = within(group(0)).getAllByTestId("candidate");
      expect(reopened.map((button) => button.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
      expect(reopened[0]).toHaveFocus();
      // 다른 후보를 고르면 다시 접히고 요약이 바뀐다
      await userEvent.click(reopened[1]);
      expect(within(group(0)).getByTestId("candidate-picked").textContent).toContain(multi[1].name);
      // 묶음은 이름으로 불린다(보조기기)
      // 묶음은 이름으로 불린다(보조기기): 접힌 묶음은 group, 펼쳐진 묶음은 radiogroup(FE-10). 표지 글자·후보 수는 이름에 섞이지 않는다
      expect(screen.getByRole("group", { name: nameA })).toBe(group(0));
      expect(screen.getByRole("radiogroup", { name: nameB })).toBe(group(1));
    });

    it("다른 묶음에서 이미 고른 제품은 비활성이고 이유를 보인다. 그 묶음을 바꾸면 다시 고를 수 있다(FE-09-03 A)", async () => {
      render(<Harness />);
      // 첫 묶음에서 겹치는 제품(가나다시럽)을 고른다
      await userEvent.click(within(group(0)).getAllByTestId("candidate")[2]);
      const second = within(group(1)).getAllByTestId("candidate");
      expect(second[0]).toBeDisabled();
      expect(second[0]).toHaveAttribute("data-taken", "true");
      expect(second[0].querySelector('[data-slot="taken-note"]')?.textContent).toBe(copy.CANDIDATE_TAKEN_NOTE);
      expect(second[1]).toBeEnabled();
      expect(second[1].querySelector('[data-slot="taken-note"]')).toBeNull();
      await userEvent.click(second[0]); // 눌러도 고르지 않는다
      expect(group(1)).not.toHaveAttribute("data-collapsed");
      // 첫 묶음을 다른 제품으로 바꾸면 풀린다
      await userEvent.click(within(group(0)).getByTestId("candidate-change"));
      await userEvent.click(within(group(0)).getAllByTestId("candidate")[0]);
      expect(within(group(1)).getAllByTestId("candidate")[0]).toBeEnabled();
      expect(screen.getByTestId("candidate-card").textContent).not.toMatch(/삐!|금기|안전|먹어도|드셔도/);
    });

    it("'직접 입력'은 펼쳐진 묶음마다 있고, 누르면 onOther만 부른다(그 묶음을 고른 것으로 치지 않는다)", async () => {
      const onOther = vi.fn();
      render(<Harness onOther={onOther} />);
      expect(screen.getAllByRole("button", { name: copy.CANDIDATE_OTHER_LABEL })).toHaveLength(2);
      await userEvent.click(within(group(1)).getByRole("button", { name: copy.CANDIDATE_OTHER_LABEL }));
      expect(onOther).toHaveBeenCalledTimes(1);
      expect(group(1)).not.toHaveAttribute("data-collapsed");
      // 접힌 묶음에는 없다
      await userEvent.click(within(group(0)).getAllByTestId("candidate")[0]);
      expect(screen.getAllByRole("button", { name: copy.CANDIDATE_OTHER_LABEL })).toHaveLength(1);
    });

    it("isTakenElsewhere: 코드가 같을 때만, 다른 묶음의 선택만 본다", () => {
      const picks = { [nameA]: multi[2] };
      expect(isTakenElsewhere(multi[3], picks)).toBe(true); // 다른 묶음, 같은 코드
      expect(isTakenElsewhere(multi[2], picks)).toBe(false); // 같은 묶음
      expect(isTakenElsewhere(multi[4], picks)).toBe(false); // 다른 코드
      expect(isTakenElsewhere({ ...multi[3], item_seq: null }, { [nameA]: { ...multi[2], item_seq: null } })).toBe(false); // 코드 없음
      expect(groupCandidates(multi).map((g) => [g.inputName, g.items.length])).toEqual([[nameA, 3], [nameB, 3]]);
    });
  });

  describe("모양 2차(FE-10, 디자인 'FE-09 r2')", () => {
    const multi = fixtures.clarifyMultiResponse.candidates;
    /** 묶음 `count`개(묶음마다 후보 2개)인 합성 후보 */
    const many = (count: number) =>
      Array.from({ length: count }, (_, g) => [0, 1].map((i) => ({ ...candidates[i], input_name: `합성${g + 1}`, name: `합성${g + 1}정 ${i + 1}`, item_seq: `3000000${g}${i}` }))).flat();
    const classes = (element: Element | null) => (element?.className ?? "").split(/\s+/);

    it("글자 위계(FE-10-01 B): 묶음 머리 16px 굵게 > 후보 이름 15px 반굵게 > 보조줄 12px, 머리 바탕은 노랑(yellow-2)", () => {
      render(<CandidateCard candidates={multi} onPick={() => {}} selected={{}} />);
      const head = screen.getAllByTestId("candidate-group")[0].querySelector("header");
      expect(classes(head)).toEqual(expect.arrayContaining(["text-base", "font-bold", "bg-yellow-2", "text-ink-2"]));
      const first = screen.getAllByTestId("candidate")[0];
      expect(classes(first.querySelector('[data-part="candidate-name"]'))).toEqual(expect.arrayContaining(["text-[15px]", "font-semibold"]));
      expect(classes(first.querySelector('[data-part="candidate-sub"]'))).toEqual(expect.arrayContaining(["text-xs", "text-mute"]));
      expect(classes(head?.querySelector('[data-slot="group-count"]') ?? null)).toEqual(expect.arrayContaining(["text-xs", "ml-auto"]));
    });

    it("묶음 머리 오른쪽에 후보 수('제품 N개')가 있고, 후보 줄마다 라디오 원이 있다", () => {
      render(<CandidateCard candidates={multi} onPick={() => {}} selected={{ [multi[0].input_name]: multi[1] }} />);
      // 고른 묶음은 접히므로 두 번째 묶음에서 본다
      const second = screen.getAllByTestId("candidate-group")[1];
      expect(second.querySelector('[data-slot="group-count"]')?.textContent).toBe(copy.candidateCountLabel(3));
      expect(copy.candidateCountLabel(3)).toBe("제품 3개");
      for (const button of within(second).getAllByTestId("candidate")) {
        const mark = button.querySelector('[data-part="radio-mark"]');
        expect(mark).toHaveAttribute("aria-hidden", "true");
        expect(classes(mark)).toEqual(expect.arrayContaining(["rounded-full", "group-aria-checked:border-[6px]", "group-aria-checked:border-yellow"]));
        expect(classes(button)).toContain("aria-checked:bg-bg-soft");
      }
    });

    it.each([2, 3, 6])("캡슐 표지 %i칸: 흰/파 번갈아, 글자 A·B·C…, 맨 앞은 왼쪽·맨 뒤는 오른쪽만 둥글고 가운데는 직각", (count) => {
      render(<CandidateCard candidates={many(count)} onPick={() => {}} selected={{}} />);
      const tags = screen.getAllByTestId("group-tag");
      expect(tags.map((tag) => tag.textContent)).toEqual(["A", "B", "C", "D", "E", "F"].slice(0, count));
      expect(tags.map((tag) => tag.getAttribute("data-tone"))).toEqual(Array.from({ length: count }, (_, i) => (i % 2 === 0 ? "white" : "blue")));
      expect(tags.map((tag) => tag.getAttribute("data-shape"))).toEqual(["left", ...Array.from({ length: count - 2 }, () => "middle"), "right"]);
      tags.forEach((tag, index) => {
        expect(classes(tag)).toEqual(expect.arrayContaining(["border-2", "border-capsule-line", "h-6"]));
        expect(classes(tag)).toEqual(expect.arrayContaining(index % 2 === 0 ? ["bg-bg", "text-ink-2"] : ["bg-capsule-blue", "text-capsule-blue-ink"]));
        expect(classes(tag).includes("rounded-l-xl")).toBe(index === 0);
        expect(classes(tag).includes("rounded-r-xl")).toBe(index === count - 1);
      });
      // 표지 글자·후보 수는 묶음 이름에 섞이지 않는다
      expect(screen.getAllByRole("radiogroup").map((g) => g.getAttribute("aria-labelledby")).map((id) => document.getElementById(id!)?.textContent)).toEqual(
        Array.from({ length: count }, (_, g) => `합성${g + 1}`),
      );
    });

    it("묶음이 하나면 표지가 없고 2열 클래스도 없다(FE-09-07 A). 둘 이상이면 카드 칸 640px부터 2열(컨테이너 기준, FE-10-02 A·04 A)", () => {
      const { unmount } = render(<CandidateCard candidates={candidates} onPick={() => {}} selected={{}} />);
      expect(screen.queryByTestId("group-tag")).toBeNull();
      expect(screen.getByTestId("candidate-card").className).not.toContain("grid-cols-2");
      unmount();
      render(<CandidateCard candidates={many(3)} onPick={() => {}} selected={{}} />);
      const card = screen.getByTestId("candidate-card");
      expect(classes(card)).toEqual(expect.arrayContaining(["@[640px]:grid", "@[640px]:grid-cols-2", "@[640px]:items-start"]));
      expect(classes(card.parentElement)).toContain("@container");
      expect(card.className).not.toMatch(/(^|\s)(sm|md|lg|xl):/); // 화면 폭 기준을 쓰지 않는다
    });

    it("접힌 줄 앞에도 그 묶음의 표지가 붙는다", async () => {
      function Harness() {
        const [picks, setPicks] = useState<Record<string, (typeof multi)[number]>>({});
        return <CandidateCard candidates={multi} selected={picks} onPick={(candidate) => setPicks((prev) => ({ ...prev, [candidate.input_name]: candidate }))} />;
      }
      render(<Harness />);
      await userEvent.click(within(screen.getAllByTestId("candidate-group")[1]).getAllByTestId("candidate")[1]);
      const picked = screen.getByTestId("candidate-picked");
      expect(within(picked).getByTestId("group-tag").textContent).toBe("B");
      expect(within(picked).getByTestId("group-tag")).toHaveAttribute("data-tone", "blue");
    });

    it("화살표 키는 같은 묶음 안에서 초점만 옮기고(비활성 건너뜀, 끝에서 돈다) 고르지 않는다", async () => {
      const onPick = vi.fn();
      render(<CandidateCard candidates={multi} onPick={onPick} selected={{ [multi[0].input_name]: multi[2] }} />);
      // 첫 묶음은 접혔고, 둘째 묶음의 첫 후보는 겹치는 제품이라 비활성이다
      const second = within(screen.getAllByTestId("candidate-group")[1]).getAllByTestId("candidate");
      expect(second[0]).toBeDisabled();
      second[1].focus();
      await userEvent.keyboard("{ArrowDown}");
      expect(second[2]).toHaveFocus();
      await userEvent.keyboard("{ArrowDown}");
      expect(second[1]).toHaveFocus();
      await userEvent.keyboard("{ArrowUp}");
      expect(second[2]).toHaveFocus();
      expect(onPick).not.toHaveBeenCalled();
      await userEvent.keyboard("{Enter}");
      expect(onPick).toHaveBeenCalledExactlyOnceWith(multi[5]);
    });

    it("PickCapsule: 고른 칸은 글자 + 이름(흰/파), 안 고른 칸은 점선 빈 칸 'A 고르기 전'. 말줄임이 없고 좁으면 세로로 쌓는다", () => {
      const long = "아주긴합성제품이름정500밀리그램서방형필름코팅정";
      render(<PickCapsule names={[long, null, "합성시럽"]} />);
      const cells = screen.getAllByTestId("capsule-cell");
      expect(cells.map((cell) => cell.textContent)).toEqual([`A${long}`, copy.pickPendingLabel("B"), "C합성시럽"]);
      expect(copy.pickPendingLabel("B")).toBe("B 고르기 전");
      expect(cells.map((cell) => [cell.getAttribute("data-state"), cell.getAttribute("data-tone")])).toEqual([["picked", "white"], ["empty", null], ["picked", "white"]]);
      expect(classes(cells[0])).toEqual(expect.arrayContaining(["text-[15px]", "font-semibold", "bg-bg", "text-ink-2"]));
      expect(classes(cells[1])).toEqual(expect.arrayContaining(["outline-dashed", "outline-faint", "text-mute"]));
      const capsule = screen.getByTestId("picked-capsule");
      expect(classes(capsule)).toEqual(expect.arrayContaining(["flex-col", "rounded-[22px]", "overflow-hidden", "border-2", "border-capsule-line", "@[640px]:flex-row", "@[640px]:rounded-full"]));
      expect(capsule.innerHTML).not.toMatch(/truncate|text-ellipsis|line-clamp|whitespace-nowrap/);
      expect(capsule.textContent).not.toMatch(/삐!|금기|안전|먹어도|드셔도/);
    });

    it.each([2, 3, 6])("PickCapsule %i칸: 흰/파 번갈아, 칸 사이에만 경계선", (count) => {
      render(<PickCapsule names={Array.from({ length: count }, (_, i) => `합성${i + 1}정`)} />);
      const cells = screen.getAllByTestId("capsule-cell");
      expect(cells.map((cell) => cell.getAttribute("data-tone"))).toEqual(Array.from({ length: count }, (_, i) => (i % 2 === 0 ? "white" : "blue")));
      expect(cells.map((cell) => cell.textContent?.[0])).toEqual(["A", "B", "C", "D", "E", "F"].slice(0, count));
      cells.forEach((cell, index) => expect(classes(cell).includes("border-t-2")).toBe(index > 0));
    });

    it("ResultView: hideCandidatesLine이면 되묻기 안내를 그리지 않는다(조립하는 쪽이 확인 줄에 그린다)", () => {
      const { rerender } = render(<ResultView response={fixtures.clarifyMultiResponse} onPickCandidate={() => {}} />);
      expect(screen.getByTestId("candidates-line")).toBeInTheDocument();
      rerender(<ResultView response={fixtures.clarifyMultiResponse} onPickCandidate={() => {}} hideCandidatesLine />);
      expect(screen.queryByTestId("candidates-line")).toBeNull();
    });
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

  // 2026-11-20 FE-11-10 A: 아래 두 시험은 옛 "본문 배너" 기대를 근거 상세 기대로 옮긴 것이다(본문 0회, 결과 카드 머리 "기준일 자료" 표지만)
  it("공공 API 실패 배너(notice)와 줄의 실시간 확인 노트는 본문에 없고(결과 카드 머리 '기준일 자료' 표지만) 근거 상세에 받은 글자 그대로 보인다", () => {
    const response = fixtures.apiFailResponse;
    expect(response.notice).toBe(PHRASES.NOTICE_API_FAIL);
    expect(response.findings[0].notes).toEqual([API_NO_CODE_NOTE]);
    const body = render(<ResultView response={response} />);
    expect(screen.queryByTestId("result-notice")).toBeNull();
    expect(body.container.textContent).not.toContain("실시간 확인");
    expect(screen.getByTestId("product-line").querySelector("[data-slot='notes']")).toBeNull();
    const tag = screen.getByTestId("basis-file-tag");
    expect(tag.textContent).toBe(copy.BASIS_FILE_TAG);
    expect(tag.textContent).toBe("기준일 자료");
    expect(screen.getByTestId("result-card").querySelector("header")?.contains(tag)).toBe(true);
    body.unmount();
    // 근거 상세: 배너 글자는 맨 위에 한 번, 줄 노트는 판정 줄 부품에 그대로
    const detail = render(<EvidenceDetail response={response} />);
    const notice = screen.getByTestId("evidence-api-fail-notice");
    expect(notice.textContent).toBe(PHRASES.NOTICE_API_FAIL);
    expect(screen.getByTestId("evidence-detail").firstElementChild).toBe(notice);
    expect(texts([...screen.getByTestId("judgment-box").querySelectorAll("[data-slot='notes']")])).toEqual([API_NO_CODE_NOTE]);
    expect((detail.container.textContent?.match(/실시간 확인/g) ?? []).length).toBe(2); // 배너 1 + 줄 노트 1
  });

  it("실시간 확인 노트만 있고 배너는 없는 줄: 본문 줄에서는 빠지고 표지는 켜지며, 다른 노트는 그대로 남는다", () => {
    const finding: Finding = { ...fixtures.apiFailResponse.findings[0], notes: ["받은 다른 노트", API_FAIL_NOTE] };
    const response: ChatResponse = { ...fixtures.apiFailResponse, notice: null, findings: [finding] };
    render(<ResultView response={response} />);
    expect(screen.queryByTestId("result-notice")).toBeNull();
    expect(screen.getByTestId("basis-file-tag")).toBeInTheDocument();
    expect(texts([...screen.getByTestId("product-line").querySelectorAll("[data-slot='notes']")])).toEqual(["받은 다른 노트"]);
    // 줄 부품을 바로 쓰면(근거 상세) 두 노트가 받은 순서 그대로다
    const { container } = line(finding);
    expect(texts([...container.querySelectorAll("[data-slot='notes']")])).toEqual(["받은 다른 노트", API_FAIL_NOTE]);
  });

  it("다른 배너(상한 도달)는 본문에 그대로이고 표지는 붙지 않는다", () => {
    render(<ResultView response={fixtures.limitResponse} />);
    expect(screen.getByTestId("result-notice").textContent).toBe(PHRASES.LIMIT_REACHED);
    expect(screen.queryByTestId("basis-file-tag")).toBeNull();
    const { container } = render(<EvidenceDetail response={fixtures.limitResponse} />);
    expect(within(container).queryByTestId("evidence-api-fail-notice")).toBeNull();
  });
});

describe("FE-02 보정 고지(name_corrections)", () => {
  const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("고지 줄은 요약보다 먼저, 배너보다 뒤에, 받은 글자·순서 그대로 접히지 않는 자리에 보인다(읽기 순서 = DOM 순서)", () => {
    // 배너는 본문에 남는 종류(상한 도달)로 본다: 공공 API 실패 배너는 본문 0회라(FE-11-10 A) 순서 비교 대상이 아니다
    const response: ChatResponse = {
      ...fixtures.typoCorrectedResponse,
      notice: PHRASES.LIMIT_REACHED,
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

describe("PRD-14-03 미식별 결과 카드 아래 동작 칩", () => {
  it("약을 찾지 못한 줄이 있고 콜백이 있을 때만 `이름 다시 입력`이 결과 카드 바로 아래에 보인다", async () => {
    const onRetryName = vi.fn();
    const { rerender } = render(<ResultView response={fixtures.unidentifiedResponse} onRetryName={onRetryName} />);
    const view = screen.getByTestId("result-view");
    const actions = screen.getByTestId("retry-actions");
    // 카드 다음 형제다(카드 안이 아니다)
    expect(screen.getByTestId("result-card").nextElementSibling).toBe(actions);
    expect(screen.getByTestId("result-card").contains(actions)).toBe(false);
    expect(view.contains(actions)).toBe(true);
    const button = within(actions).getByRole("button", { name: copy.RETRY_NAME_LABEL });
    expect(button.textContent).toBe("이름 다시 입력");
    await userEvent.click(button);
    expect(onRetryName).toHaveBeenCalledTimes(1);
    rerender(<ResultView response={fixtures.unidentifiedResponse} />);
    expect(screen.queryByTestId("retry-actions")).toBeNull();
  });

  it("약을 찾은 결과(금기 발견·목록에 없음·쌍 확인 불가·되묻기·거절)에는 그리지 않는다", () => {
    for (const response of [fixtures.foundResponse, fixtures.notListedResponse, fixtures.pairNoEvidenceResponse, fixtures.codeNotLinkedResponse, fixtures.clarifyResponse, fixtures.refuseResponse]) {
      const { unmount } = render(<ResultView response={response} onRetryName={() => {}} onPickCandidate={() => {}} />);
      expect(screen.queryByTestId("retry-actions")).toBeNull();
      unmount();
    }
  });

  it("`약 사진 올리기`는 사진 입력이 없는 구성이라 DOM에 없다(PRD-14 §6 ⑥)", () => {
    const { container } = render(<ResultView response={fixtures.unidentifiedResponse} onRetryName={() => {}} />);
    expect(container.textContent).not.toContain("약 사진 올리기");
    expect(within(screen.getByTestId("retry-actions")).getAllByRole("button")).toHaveLength(1);
    expect(container.querySelector("input[type=file]")).toBeNull();
  });

  it("칩은 시작 화면 예시 질문 칩과 같은 모양 값을 쓰고(같은 class), 판정·안전 글자·마스코트가 없다", () => {
    render(
      <>
        <ExampleChips onPick={() => {}} questions={["합성 예시 질문"]} />
        <RetryActions onRetryName={() => {}} />
      </>,
    );
    const example = screen.getByTestId("example-chip");
    const retry = screen.getByTestId("retry-name");
    expect(retry.className).toBe(CHIP_CLASS);
    expect(example.className).toBe(CHIP_CLASS);
    expect(CHIP_CLASS).toContain("min-h-11"); // 누르는 영역 44px
    expect(screen.getByTestId("retry-actions").className).toContain("flex-wrap"); // 좁으면 줄바꿈
    expect(screen.getByTestId("retry-actions").textContent).not.toMatch(/삐!|금기|안전|먹어도/);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("PRD-01-01·FR-10 되묻기: 후보와 질문 1개, 가부 미표시", () => {
  const response = fixtures.clarifyResponse;

  it("되묻기 화면에는 질문 한 문장(summary)과 후보 카드·안내 줄만 있고 결과 카드·배지·판정 줄이 없다", () => {
    render(<ResultView response={response} onPickCandidate={() => {}} onOtherCandidate={() => {}} selectedCandidates={{}} />);
    expect(screen.getAllByTestId("result-summary")).toHaveLength(1);
    expect(screen.getByTestId("result-summary").textContent).toBe(response.summary);
    expect(screen.getByTestId("candidate-card")).toBeInTheDocument();
    expect(screen.queryByTestId("result-card")).toBeNull();
    expect(screen.queryByTestId("product-line")).toBeNull();
    expect(screen.queryByTestId("status-badge")).toBeNull();
    expect(screen.queryByTestId("retry-actions")).toBeNull();
  });

  it("후보를 고른 뒤에도(선택 상태) 가부·판정 글자가 생기지 않는다", () => {
    const { container } = render(
      <ResultView response={response} onPickCandidate={() => {}} onOtherCandidate={() => {}} selectedCandidates={{ [response.candidates[1].input_name]: response.candidates[1] }} />,
    );
    expect(screen.getAllByTestId("candidate")[1]).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("status-badge")).toBeNull();
    // 후보 카드 안에는 가부로 읽힐 글자가 없다(질문 문장·안내 줄은 서버 값이라 카드 밖에서 따로 본다)
    expect(screen.getByTestId("candidate-card").textContent).not.toMatch(/삐!|금기|안전|먹어도|드셔도|됩니다|안 돼/);
    expect(container.querySelector("[data-bucket]")).toBeNull();
  });

  it("되묻기 fixture의 질문·안내 줄에도 가부 문장이 없다(먹어도 된다/안 된다를 말하지 않는다)", () => {
    for (const text of [response.summary, response.candidates_line]) {
      expect(text ?? "").not.toMatch(/먹어도 (돼|됩|괜찮)|드셔도|안전해|안전합|금기예요|금기입/);
    }
    expect(response.findings).toEqual([]);
  });
});

describe("PRD-09-01~04 판정 줄의 등급 표기(등급은 표지에만, '단계' 글자 없음)", () => {
  const all = Object.entries(fixtures).filter(([name]) => name.endsWith("Response")) as [string, ChatResponse][];
  const GRADE = /(1|2|M)등급/;

  it("fixture 응답이 충분히 있고 임부금기 1·2·M등급 줄이 모두 들어 있다(시험 대상 확인)", () => {
    expect(all.length).toBeGreaterThanOrEqual(20);
    const grades = new Set(all.flatMap(([, r]) => r.findings.flatMap((f) => f.badges.map((b) => b.grade))));
    expect(grades.has("1") && grades.has("2") && grades.has("M")).toBe(true);
  });

  it.each(all)("%s: 등급 글자는 배지(표지) 안에만 있고 보조줄에 반복되지 않는다", (_name, response) => {
    const { container, unmount } = render(<ResultView response={response} onPickCandidate={() => {}} />);
    for (const row of container.querySelectorAll('[data-testid="product-line"]')) {
      const copyRow = row.cloneNode(true) as Element;
      for (const badge of copyRow.querySelectorAll('[data-testid="status-badge"]')) badge.remove();
      expect(copyRow.textContent ?? "").not.toMatch(GRADE); // 배지를 뺀 나머지(제목·성분·보조줄)에 등급이 없다
    }
    // 임부금기 배지 글자는 "삐! 임부금기 N등급"(M이면 M등급)으로 시작한다
    for (const badge of container.querySelectorAll('[data-testid="status-badge"][data-kind="pregnancy"]')) {
      expect(badge.textContent ?? "").toMatch(/^삐! 임부금기 (1|2|M)등급/);
    }
    unmount();
  });

  it.each(all)("%s: 화면에 '단계' 글자가 없다", (_name, response) => {
    const { container, unmount } = render(<ResultView response={response} onPickCandidate={() => {}} onRetryName={() => {}} />);
    expect(container.textContent ?? "").not.toContain("단계");
    unmount();
  });

  it("M등급: 표지는 'M등급'이고 '적응증에 따라 등급이 달라요'는 보조줄에 한 번만 있다", () => {
    render(<ResultView response={fixtures.pregnancyMResponse} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.textContent).toBe(PHRASES.BADGE_PREGNANCY_M);
    expect(screen.getAllByText(PHRASES.BADGE_PREGNANCY_M_NOTE)).toHaveLength(1);
    expect(badge.textContent).not.toContain(PHRASES.BADGE_PREGNANCY_M_NOTE);
  });

  it("프런트 고유 글자(copy.ts)에 '단계'·등급 글자가 없다", () => {
    expect(JSON.stringify(copy)).not.toMatch(/단계|등급/);
    expect(copy.moreIngredientsLabel(2)).not.toMatch(/단계|등급/);
  });
});

// GROUP-01 3단계 새 칸의 최소 표시(디자인 전 임시): 고지 2종은 결과 위 안내 띠, 묶음 요약은 결과 카드 위 한 줄. 구역·짝 참조·용량 되묻기 카드는 그리지 않는다
describe("새 응답 칸(AG-22·FE-11) 최소 표시", () => {
  const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("redose_notice는 받은 글자 그대로 요약 다음·결과 카드 앞의 안내 띠로 보이고, 없으면 띠가 없다", () => {
    const { rerender } = render(<ResultView response={fixtures.redoseResponse} />);
    const band = screen.getByTestId("redose-notice");
    expect(band.textContent).toBe(PHRASES.REDOSE_NOTICE);
    expect(band.className).toBe(screen.getByTestId("result-summary").nextElementSibling?.className); // 같은 띠 모양(배너 부품 재사용)
    expect(before(screen.getByTestId("result-summary"), band)).toBe(true);
    expect(before(band, screen.getByTestId("result-card"))).toBe(true);
    expect(band.closest("details, [hidden], [data-state='closed']")).toBeNull();
    rerender(<ResultView response={fixtures.foundResponse} />);
    expect(screen.queryByTestId("redose-notice")).toBeNull();
    expect(screen.queryByTestId("dose-notice")).toBeNull();
    expect(screen.queryByTestId("result-summary-line")).toBeNull();
  });

  it("dose_notice는 결과 묶음의 맨 위(배너보다 앞)에 안내 띠로 보인다", () => {
    // 본문에 남는 배너(상한 도달)와 견준다: 공공 API 실패 배너는 본문에 없다(FE-11-10 A)
    const response: ChatResponse = { ...fixtures.limitResponse, dose_notice: PHRASES.DOSE_NOTICE };
    render(<ResultView response={response} />);
    const band = screen.getByTestId("dose-notice");
    expect(band.textContent).toBe(PHRASES.DOSE_NOTICE);
    expect(band.className).toBe(screen.getByTestId("result-notice").className);
    expect(before(band, screen.getByTestId("result-notice"))).toBe(true);
    expect(screen.getByTestId("result-view").firstElementChild).toBe(band);
  });

  it("result_summary.text와 pair_only_notice는 결과 카드 바로 위 한 줄에 받은 글자 그대로이고, 구역·짝 참조·접힘·용량 되묻기는 아직 그리지 않는다", () => {
    const { container } = render(<ResultView response={fixtures.resultSummaryResponse} />);
    const line = screen.getByTestId("result-summary-line");
    const summary = fixtures.resultSummaryResponse.result_summary!;
    expect(line.firstElementChild?.textContent).toBe(summary.text);
    expect(screen.getByTestId("pair-only-notice").textContent).toBe(summary.pair_only_notice);
    expect(before(screen.getByTestId("result-summary"), line)).toBe(true);
    expect(line.nextElementSibling).toBe(screen.getByTestId("result-card")); // 카드 바로 위
    // 판정 줄은 받은 순서 그대로(핵심 → 나머지), 제품 줄에 병용 배지 없음
    expect(texts(screen.getAllByTestId("line-title"))).toEqual(fixtures.resultSummaryResponse.findings.map((f) => f.drug));
    expect(screen.getAllByTestId("status-badge")).toHaveLength(1);
    expect(container.textContent).not.toContain(PHRASES.PAIR_REF_LINE.replace("{n}", "1"));
    expect(container.textContent).not.toContain(PHRASES.REST_FOLD_LINE.replace("{n}", "2"));
    expect(container.textContent).not.toContain("펼치기");
    expect(container.textContent).not.toContain("오늘 이 약(같은 성분)을 이미 드셨나요?");
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});
