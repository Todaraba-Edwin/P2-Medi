// FE-17 U-28(2026-11-24, ISSUE-034): 같은 약의 허가사항 항목 줄(`{약} · 주의사항`)을 그 약의 판정 줄 하나 안으로 합치고,
// 사용자에게 보이는 문장 맨 앞의 품목 기준 코드(`209900001 · `)는 화면에서만 숨긴다(근거 ID·서버 문구는 그대로).
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceDetail } from "@/features/evidence";
import type { ChatResponse, Finding } from "@/lib/api";
import { API_NO_CODE_NOTE, CAUTION_DOSE, PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import { hideItemCode, isLabelOf, mergeLabelFindings, splitItemCode } from "./label-merge";
import { ResultCard } from "./ResultCard";

const response = fixtures.labelMergeResponse;
const [judgment, label] = response.findings;
const CODE = "209900001";
const HIDDEN_TEXT = PHRASES.MISSING_OUT_OF_SCOPE.replace("{drug}", "주의사항"); // 코드 앞부분만 숨긴 글자(서버 문장의 나머지 그대로)
const notesOf = (line: Element) => [...line.querySelectorAll('[data-slot="notes"]')].map((el) => el.textContent);
const texts = (elements: Element[]) => elements.map((el) => el.textContent);

describe("mergeLabelFindings (U-28 (a)·(b) 규칙)", () => {
  it("합성 labelMerge(사용자 사례 모양): 판정 줄 하나에 같은 약의 주의사항 줄이 붙고 따로 남지 않는다", () => {
    expect(label.drug).toBe(`${judgment.drug} · 주의사항`);
    const merged = mergeLabelFindings(response.findings);
    expect(merged).toHaveLength(1);
    expect(merged[0].finding).toBe(judgment);
    expect(merged[0].labels).toEqual([label]);
  });

  it("같은 약의 판정 줄이 없고 허가사항 항목 줄만 있으면 지금처럼 그 줄 하나다", () => {
    const merged = mergeLabelFindings([label]);
    expect(merged).toEqual([{ finding: label, labels: [] }]);
    // 다른 약의 판정 줄만 있어도 붙지 않는다
    const other = { ...judgment, drug: "라마바캡슐", drugs: ["라마바캡슐"] };
    expect(mergeLabelFindings([other, label]).map((entry) => entry.labels.length)).toEqual([0, 0]);
  });

  it("판정 줄이 항목 줄보다 뒤에 와도 그 판정 줄 자리에 붙고, 같은 약의 항목 줄(주의사항·경고)은 받은 순서대로 모두 붙는다", () => {
    const warning: Finding = { ...label, evidence_id: "ev-label-warn", drug: `${judgment.drug} · 경고` };
    const merged = mergeLabelFindings([label, warning, judgment]);
    expect(merged).toHaveLength(1);
    expect(merged[0].labels.map((item) => item.evidence_id)).toEqual(["ev-label-u28", "ev-label-warn"]);
  });

  it("쌍 줄·허가사항 항목 줄은 주인이 되지 않고, 이름이 접두로만 겹치거나 항목 이름에 이음이 더 있으면 붙지 않는다", () => {
    expect(isLabelOf({ drug: "가나다정 · 주의사항" }, "가나다정")).toBe(true);
    expect(isLabelOf({ drug: "가나다정정 · 주의사항" }, "가나다정")).toBe(false);
    expect(isLabelOf({ drug: "가나다정 · 라마바캡슐 · 주의사항" }, "가나다정")).toBe(false);
    expect(isLabelOf({ drug: "가나다정 · " }, "가나다정")).toBe(false);
    const pair = fixtures.foundResponse.findings[0];
    const pairLabel = { ...label, drug: `${pair.drug} · 주의사항` };
    expect(mergeLabelFindings([pair, pairLabel]).map((entry) => entry.labels.length)).toEqual([0, 0]);
  });

  it("기존 합성 응답 전부: 이 규칙에 걸리는 줄이 없어 줄 수·순서가 그대로다(현행 유지)", () => {
    for (const [name, value] of Object.entries(fixtures)) {
      if (name === "labelMergeResponse" || typeof value !== "object" || value === null || !("findings" in value)) continue;
      const findings = (value as ChatResponse).findings;
      expect(mergeLabelFindings(findings).map((entry) => entry.finding), name).toEqual(findings);
    }
  });
});

describe("품목 기준 코드 숨김 (U-28 (c))", () => {
  it("문장 맨 앞의 숫자 6자리 이상 + ` · `만 숨기고 숨긴 코드를 돌려준다. 그 밖은 그대로다", () => {
    expect(splitItemCode(label.text)).toEqual({ text: HIDDEN_TEXT, code: CODE });
    expect(hideItemCode("12345 · 주의사항")).toBe("12345 · 주의사항"); // 5자리
    expect(hideItemCode("가나 209900001 · 주의사항")).toBe("가나 209900001 · 주의사항"); // 맨 앞이 아님
    expect(hideItemCode("209900001 · ")).toBe("209900001 · "); // 숨기면 빈 글자가 되는 경우는 그대로
    expect(hideItemCode(PHRASES.NOT_LISTED)).toBe(PHRASES.NOT_LISTED);
  });
});

describe("결과 카드(본문): 같은 약 행 하나", () => {
  it("행 하나, 덧붙임 줄은 `하루 최대량 주의 성분 포함` 다음에 주의사항 문장(코드 숨김), 실시간 확인 노트는 본문에 없다", () => {
    render(<ResultCard response={response} />);
    const lines = screen.getAllByTestId("product-line");
    expect(lines).toHaveLength(1);
    const line = lines[0];
    expect(within(line).getByTestId("line-title").textContent).toBe(judgment.drug);
    expect(line.getAttribute("data-kind")).toBe("pregnancy");
    expect(line.getAttribute("data-merged-labels")).toBe("1");
    expect(notesOf(line)).toEqual([CAUTION_DOSE, HIDDEN_TEXT]);
    const merged = line.querySelector('[data-merged="label"]')!;
    expect(merged.getAttribute("data-slot")).toBe("notes");
    expect(merged.className).toBe(line.querySelector('[data-slot="notes"]')!.className); // 같은 모양(text-xs leading-[17px] text-mute)
    // 근거 ID와 숨긴 코드는 화면 글자가 아닌 속성에 남는다
    expect(merged.getAttribute("data-evidence-ids")).toBe("ev-label-u28");
    expect(merged.getAttribute("data-item-code")).toBe(CODE);
    expect(line.textContent).not.toContain(CODE);
    expect(line.textContent).not.toContain(API_NO_CODE_NOTE);
    expect(line.textContent).not.toContain("· 주의사항"); // 따로 된 행 제목이 없다
    expect(screen.queryByText(`${judgment.drug} · 주의사항`)).toBeNull();
  });

  it("허가사항 항목 줄만 있으면 지금처럼 그 행 하나(머리 `{약} · 주의사항`, 점선 칩)이고 칩 글자의 품목 기준 코드만 숨긴다", () => {
    render(<ResultCard response={{ ...response, findings: [label] }} />);
    const lines = screen.getAllByTestId("product-line");
    expect(lines).toHaveLength(1);
    expect(lines[0].getAttribute("data-kind")).toBe("label");
    expect(within(lines[0]).getByTestId("line-title").textContent).toBe(label.drug);
    const chip = within(lines[0]).getByTestId("line-text");
    expect(chip.textContent).toBe(HIDDEN_TEXT);
    expect(chip.getAttribute("data-item-code")).toBe(CODE);
    expect(chip.className).toContain("border-dashed");
  });

  it("허가사항 항목이 아닌 줄의 글자는 숫자로 시작해도 숨기지 않는다(표시 가공은 허가사항 항목 문장에만)", () => {
    const numeric = { ...judgment, badges: [], bucket: "not_listed" as const, text: `${CODE} · ${PHRASES.NOT_LISTED}` };
    render(<ResultCard response={{ ...response, findings: [numeric] }} />);
    expect(screen.getByTestId("line-text").textContent).toBe(numeric.text);
  });
});

describe("근거 상세: 같은 약 카드 안 한 그룹", () => {
  it("판정 구역에 `· 주의사항` 따로 된 카드가 없고, 같은 약 박스 안 덧붙임 줄로 있다(근거 ID는 박스에 이어 붙음)", () => {
    render(<EvidenceDetail response={response} />);
    const judgmentSection = screen.getAllByTestId("evidence-section").find((el) => el.getAttribute("data-section") === "judgment")!;
    const groups = within(judgmentSection).getAllByTestId("judgment-drug-group");
    expect(groups).toHaveLength(1);
    const boxes = within(groups[0]).getAllByTestId("judgment-box");
    expect(boxes).toHaveLength(1);
    expect(boxes[0].getAttribute("data-evidence-ids")).toBe("ev-preg-1 ev-label-u28");
    expect(texts(within(judgmentSection).getAllByTestId("line-title"))).toEqual([judgment.drug]);
    // 근거 상세의 줄은 실시간 확인 노트를 그대로 보이고, 그 다음 `하루 최대량…`, 그 다음 주의사항 문장
    expect(notesOf(boxes[0])).toEqual([API_NO_CODE_NOTE, CAUTION_DOSE, HIDDEN_TEXT]);
    expect(judgmentSection.textContent).not.toContain(CODE);
  });

  it("허가사항 구역의 미확보 카드 문구도 맨 앞 코드를 숨기고(속성에 보존), 사유 원문은 `제형유형 2건`으로 묶인 채다", () => {
    render(<EvidenceDetail response={response} />);
    const missing = screen.getAllByTestId("missing-text");
    expect(texts(missing)).toEqual([HIDDEN_TEXT]);
    expect(missing[0].getAttribute("data-item-code")).toBe(CODE);
    expect(texts(screen.getAllByTestId("reason-form-count"))).toEqual(["제형유형 2건"]);
  });

  it("서버 몫(하지 않음): 권고 줄의 문장 중간 `{코드} · 주의사항을…`은 받은 글자 그대로 둔다(U-28 (d), 서버 조립 후속)", () => {
    render(<EvidenceDetail response={response} />);
    expect(screen.getByTestId("missing-group").textContent).toContain(response.pharmacist_advice[0]);
    expect(response.pharmacist_advice[0]).toContain(`${CODE} · 주의사항을`);
  });

  it("다른 묶음과 함께: 같은 내용 N건(U-26-6)·같은 약 묶음(U-26-5)은 그대로이고 주의사항 줄은 같은 약의 첫 판정 줄에만 붙는다", () => {
    const dup = fixtures.judgmentDupResponse;
    const owner = dup.findings[0];
    const extra: Finding = { ...label, drug: `${owner.drug} · 주의사항` };
    render(<EvidenceDetail response={{ ...dup, findings: [...dup.findings, extra], detail: [...dup.detail, response.detail[3]] }} />);
    const groups = screen.getAllByTestId("judgment-drug-group");
    expect(groups.map((group) => group.getAttribute("data-count"))).toEqual(["2", "1", "1", "1"]);
    expect(screen.getAllByTestId("judgment-same-count")).toHaveLength(1);
    const ownerBoxes = within(groups[0]).getAllByTestId("judgment-box");
    expect(ownerBoxes[0].querySelectorAll('[data-merged="label"]')).toHaveLength(1);
    expect(ownerBoxes[1].querySelectorAll('[data-merged="label"]')).toHaveLength(0);
    expect(screen.queryAllByText(`${owner.drug} · 주의사항`)).toHaveLength(0);
  });
});
