import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EVIDENCE_SAMPLES } from "@/app/dev/preview/evidence/samples";
import { FixedNoticeBox } from "@/features/emergency";
import type { ChatResponse } from "@/lib/api";
import { PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import * as copy from "./copy";
import { EvidenceDetail } from "./EvidenceDetail";
import { EvidenceEntryButton, EvidencePanel } from "./EvidencePanel";
import { GradeDefBlock } from "./GradeDefBlock";
import { MissingBox, MissingGroup } from "./MissingBox";
import { PermitText } from "./PermitText";
import { adviceOf, groupByPublisher, groupReasons, rowTexts } from "./sections";
import { SourceTable } from "./SourceTable";

const texts = (elements: Element[]) => elements.map((el) => el.textContent);
const sample = (id: string) => EVIDENCE_SAMPLES.find((s) => s.id === id)!.response;
const sections = () => screen.getAllByTestId("evidence-section").map((el) => el.getAttribute("data-section"));
/** 표지 안의 자료 이름 글자(출처 종류 글자를 뺀 부분). 출처 표의 자료 열과 같은 글자여야 한다 */
const tagDataset = (tag: Element) => tag.querySelector("[data-slot='source-dataset']")?.textContent;
const tagKind = (tag: Element) => tag.querySelector("[data-slot='source-kind-label']")?.textContent ?? null;
const CLOSED = "details:not([open]), [hidden], [aria-hidden='true'], [data-state='closed']";

describe("EvidenceDetail", () => {
  it("구역 순서는 판정 → 사유 원문 → 허가사항 → 출처이고 구역마다 소제목이 하나다", () => {
    render(<EvidenceDetail response={sample("permit")} />);
    expect(sections()).toEqual(["judgment", "reason", "label", "sources"]);
    for (const section of screen.getAllByTestId("evidence-section")) expect(within(section).getAllByRole("heading")).toHaveLength(1);
    expect(texts(screen.getAllByRole("heading", { level: 3 }))).toEqual(Object.values(copy.SECTION_TITLES));
  });

  it("소제목은 13자 이내의 짧은 명사형이다(PRD-10-03)", () => {
    for (const title of [...Object.values(copy.SECTION_TITLES), copy.EVIDENCE_TITLE]) {
      expect(title.length).toBeLessThanOrEqual(13);
      expect(title).not.toMatch(/[.?!]|요$|다$/);
    }
    expect(JSON.stringify(copy)).not.toMatch(/허가 라벨|허가정보|단계|펼치기/);
  });

  it("값이 없는 구역은 그리지 않는다", () => {
    render(<EvidenceDetail response={fixtures.unidentifiedResponse} />);
    expect(sections()).toEqual(["judgment"]);
    const { container } = render(<EvidenceDetail response={fixtures.refuseResponse} />);
    expect(within(container).queryByTestId("evidence-section")).toBeNull();
  });

  it("판정 줄·배지는 응답 순서·글자 그대로이고 표지의 자료 이름이 출처 표의 자료 열과 글자가 같다", () => {
    const response = fixtures.pairAndPregnancyResponse;
    render(<EvidenceDetail response={response} />);
    const boxes = screen.getAllByTestId("judgment-box");
    expect(boxes).toHaveLength(response.findings.length);
    boxes.forEach((box, index) => {
      const finding = response.findings[index];
      expect(within(box).getByTestId("line-title").textContent).toBe(finding.drug);
      expect(texts(within(box).getAllByTestId("status-badge"))).toEqual(finding.badges.map((b) => b.text));
    });
    const tags = screen.getAllByTestId("source-tag");
    const datasets = new Set(texts(screen.getAllByTestId("source-dataset")));
    for (const tag of tags) expect(datasets.has(tagDataset(tag) ?? "")).toBe(true);
    // 표지는 `{출처 종류 글자} · {자료 이름}`이고 종류 글자는 응답의 source_kind_label 그대로다(BE-06-14)
    const byDataset = new Map(response.detail.map((item) => [item.dataset, item.source_kind_label]));
    for (const tag of tags) {
      expect(tagKind(tag)).toBe(byDataset.get(tagDataset(tag) ?? null) ?? null);
      if (tagKind(tag)) expect(tag.textContent).toBe(`${tagKind(tag)} · ${tagDataset(tag)}`);
    }
  });

  it("등급 불일치: 판정 박스의 배지 둘이 출처 꼬리와 함께 받은 순서대로 보인다", () => {
    render(<EvidenceDetail response={fixtures.gradeMismatchResponse} />);
    expect(texts(within(screen.getAllByTestId("judgment-box")[0]).getAllByTestId("status-badge"))).toEqual(
      fixtures.gradeMismatchResponse.findings[0].badges.map((b) => b.text),
    );
  });

  it("사유 원문은 맨 글이 아니라 박스이고 원문 글자를 그대로 보인다(같은 문장은 한 번)", () => {
    const item = { ...fixtures.foundResponse.detail[0], rows: [{ reason: "합성 사유 문장" }, { reason: "합성 사유 문장" }, { content: "둘째 합성 문장" }] };
    render(<EvidenceDetail response={{ ...fixtures.foundResponse, detail: [item] }} />);
    const box = screen.getByTestId("reason-box");
    expect(texts([...box.querySelectorAll("p")])).toEqual(["합성 사유 문장", "둘째 합성 문장"]);
    expect(rowTexts(item)).toEqual(["합성 사유 문장", "둘째 합성 문장"]);
    expect(tagDataset(within(box).getByTestId("source-tag"))).toBe(item.dataset);
  });

  it("같은 내용(종류·제목·표지·원문)의 사유 박스는 하나로 묶고 '같은 내용 N건'을 더한다. 글자가 다른 원문은 묶지 않고, 근거 ID는 받은 순서대로 남는다(FE-17 U-19 후속)", () => {
    const response = fixtures.doseDupResponse;
    const reasonItems = response.detail.filter((item) => item.kind === "dose");
    expect(reasonItems).toHaveLength(30); // 묶기 전: 항목마다 박스 하나였다(6 + 1 + 23)
    const groups = groupReasons(reasonItems);
    expect(groups.map((group) => group.items.length)).toEqual([6, 1, 23]);
    // 묶음 순서는 처음 나온 순서, 묶음 안은 받은 순서(받은 순서: 같은 문장 3건 → 다른 글자 1건 → 같은 문장 3건 → 약 B 23건). ID는 하나도 빠지거나 바뀌지 않는다
    const ids = reasonItems.map((item) => item.evidence_id);
    expect(groups.map((group) => group.evidenceIds)).toEqual([[...ids.slice(0, 3), ...ids.slice(4, 7)], [ids[3]], ids.slice(7)]);
    expect(new Set(groups.flatMap((group) => group.evidenceIds))).toEqual(new Set(reasonItems.map((item) => item.evidence_id)));

    render(<EvidenceDetail response={response} />);
    const boxes = screen.getAllByTestId("reason-box");
    expect(boxes).toHaveLength(3);
    expect(boxes.map((box) => box.getAttribute("data-count"))).toEqual(["6", "1", "23"]);
    expect(boxes.map((box) => within(box).queryByTestId("reason-same-count")?.textContent ?? null)).toEqual(["같은 내용 6건", null, "같은 내용 23건"]);
    expect(copy.sameContentCount(6)).toBe("같은 내용 6건");
    // 보이는 글자는 받은 값 그대로(용량 숫자 원문 포함, 근거 상세에서는 허용: RFP-21-03), 박스마다 원문 문장 한 번
    boxes.forEach((box, index) => {
      expect(texts([...box.querySelectorAll("p")])).toEqual(rowTexts(groups[index].item));
      expect(within(box).getAllByTestId("source-tag")).toHaveLength(1);
      expect(box.getAttribute("data-evidence-ids")!.split(" ")).toEqual(groups[index].evidenceIds);
    });
    expect(texts([...boxes[0].querySelectorAll("p")])).toEqual(["가나성분으로 4,000mg"]);
    expect(texts([...boxes[1].querySelectorAll("p")])).toEqual(["가나성분으로써 4000mg"]); // 글자가 다르면 따로
    expect(texts([...boxes[2].querySelectorAll("p")])).toEqual(["라마성분 3,200mg"]);
    // 구역 순서·출처 표는 그대로(출처 표는 묶지 않는다)
    expect(sections()).toEqual(["judgment", "reason", "sources"]);
  });

  it("묶기 열쇠: 약 이름·자료·출처 종류 글자·덧붙임 줄이 하나라도 다르면 따로 박스다", () => {
    const base = fixtures.doseDupResponse.detail[0];
    const variants = [
      base,
      { ...base, evidence_id: "x-1" }, // 근거 ID만 다름 → 묶임
      { ...base, evidence_id: "x-2", drugs: ["다른정"], drug_name: "다른정" },
      { ...base, evidence_id: "x-3", dataset: "다른 파일" },
      { ...base, evidence_id: "x-4", source_kind_label: "다른 종류" },
      { ...base, evidence_id: "x-5", notes: ["덧붙임 한 줄"] },
      { ...base, evidence_id: "x-6", kind: "lactation" },
    ];
    expect(groupReasons(variants).map((group) => group.items.length)).toEqual([2, 1, 1, 1, 1, 1]);
  });

  it("표지의 출처 종류 글자는 받은 글자 그대로이고, 오지 않으면 자료 이름만 보인다(프런트가 종류 글자를 짓지 않는다)", () => {
    const item = { ...fixtures.foundResponse.detail[0], source_kind_label: "받은 종류 글자" };
    const { rerender } = render(<EvidenceDetail response={{ ...fixtures.foundResponse, detail: [item] }} />);
    for (const tag of screen.getAllByTestId("source-tag")) expect(tag.textContent).toBe(`받은 종류 글자 · ${item.dataset}`);
    rerender(<EvidenceDetail response={{ ...fixtures.foundResponse, detail: [{ ...item, source_kind_label: null }] }} />);
    for (const tag of screen.getAllByTestId("source-tag")) expect(tag.textContent).toBe(item.dataset);
  });

  it("등급 불일치 안내는 그 근거 박스에 받은 글자로 한 번만 보인다", () => {
    render(<EvidenceDetail response={fixtures.gradeMismatchResponse} />);
    expect(screen.getAllByText(PHRASES.GRADE_MISMATCH_NOTE)).toHaveLength(1);
  });

  it("등급 정의 블록(grade_defs): 원문 블록은 접힘, 미확보 블록은 문구와 권고만 접힘 밖에 보인다", async () => {
    const response = fixtures.gradeDefsResponse;
    render(<EvidenceDetail response={response} />);
    const block = screen.getByTestId("grade-def");
    const [quoted, missing] = response.grade_defs;
    const trigger = within(block).getByRole("button", { name: quoted.title });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(within(block).queryByRole("button", { name: missing.title })).toBeNull();
    const missingBox = within(block).getByTestId("grade-def-missing");
    expect(texts([...missingBox.querySelectorAll(":scope > p")])).toEqual([missing.missing_text]);
    expect(within(missingBox).getByTestId("pharmacist-advice").textContent).toBe(response.pharmacist_advice[0]);
    expect(missingBox.closest(CLOSED)).toBeNull();
    await userEvent.click(trigger);
    expect(block.querySelector("blockquote")?.textContent).toBe(quoted.text);
    expect(block.querySelector("[data-slot='grade-def-source']")?.textContent).toBe(quoted.source);
    expect(block.querySelectorAll("[data-slot='grade-def-source']")).toHaveLength(1); // 미확보 블록에는 출처 줄이 없다
  });

  it("허가사항 구역: 한 줄 설명은 맨 위에 한 번, 전문의약품 안내 줄은 원문 앞, 인용 고지는 용법용량 인용 바로 아래(모두 받은 글자)", () => {
    const response = fixtures.rxPermitResponse;
    render(<EvidenceDetail response={response} />);
    const section = screen.getAllByTestId("evidence-section").find((el) => el.getAttribute("data-section") === "label")!;
    expect(texts(within(section).getAllByTestId("label-help"))).toEqual([PHRASES.LABEL_ONE_LINE]);
    expect(section.children[1]).toBe(within(section).getByTestId("label-help")); // 소제목 바로 아래
    const [caution, dose] = within(section).getAllByTestId("permit-text");
    const easy = within(caution).getByTestId("easy-text-missing");
    expect(easy.textContent).toBe(response.detail[1].easy_text_missing_line);
    expect(easy.compareDocumentPosition(caution.querySelector("q")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(caution).queryByTestId("quote-notice")).toBeNull();
    const notice = within(dose).getByTestId("quote-notice");
    expect(notice.textContent).toBe(PHRASES.DOSE_QUOTE_NOTICE);
    expect(dose.querySelector("q")!.closest("p")!.nextElementSibling).toBe(notice);
    expect(within(dose).queryByTestId("easy-text-missing")).toBeNull();
    expect(dose.querySelector("table, dl, ul, ol")).toBeNull();
    expect(notice.closest(CLOSED)).toBeNull();
  });

  it("연령금기 판정 줄 뒤에 나이 기준 값이 원문 그대로 있고, 안내 문구 자리는 값이 올 때만 그려진다", () => {
    const { container } = render(<EvidenceDetail response={fixtures.ageFoundResponse} />);
    const box = screen.getByTestId("judgment-box");
    expect(texts([...box.querySelectorAll('[data-slot="age-criteria"]')])).toEqual(fixtures.ageFoundResponse.findings[0].age_criteria);
    expect(container.querySelector('[data-slot="age-info"]')).toBeNull(); // 문구 승인 전: 프런트가 문장을 짓지 않는다
  });

  it("약을 찾지 못한 줄: 입력한 이름·찾아본 곳(건수)·이유·다음 행동이 응답 값 그대로다", () => {
    const finding = fixtures.unidentifiedResponse.findings[0];
    render(<EvidenceDetail response={fixtures.unidentifiedResponse} />);
    const pairs = screen.getByTestId("lookup-pairs");
    expect(texts([...pairs.querySelectorAll("dt")])).toEqual(Object.values(copy.LOOKUP_LABELS));
    const values = [...pairs.querySelectorAll("dd")];
    expect(values[0].textContent).toBe(finding.input_name);
    expect(texts([...values[1].querySelectorAll('[data-slot="searched"]')])).toEqual(finding.searched.map((s) => `${s.dataset}${s.count}건`));
    expect(values[2].textContent).toBe(finding.why);
    expect(values[3].textContent).toBe(finding.next);
    expect(pairs.querySelector('[data-slot="retried"]')?.textContent).toBe(finding.retried_line);
    for (const dt of pairs.querySelectorAll("dt")) expect(dt).toHaveClass("whitespace-nowrap"); // 라벨은 한 줄
    expect(pairs.textContent).not.toMatch(/약 이름 사전|공식 약 목록/);
  });

  it.each(EVIDENCE_SAMPLES.map((s) => [s.id, s.response] as const))("%s: 마스코트·이미지·소리 0개, 내부 키 글자 없음", (_id, response) => {
    const { container } = render(<EvidenceDetail response={response} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
    expect(container.querySelector("img, audio")).toBeNull();
    expect(container.textContent).not.toMatch(/SEARCH_MISS|contra_pair|API_DIRECT|CORPUS_QUOTE|ev-[a-z]+-\d/);
    expect(screen.queryAllByTestId("source-row")).toHaveLength(response.citations.length);
  });

  it("근거 상세 안에는 마스코트가 그려지지 않는다(NoMascotZone)", () => {
    render(<EvidenceDetail response={fixtures.foundResponse} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});

describe("PermitText", () => {
  const response = sample("permit");
  const [caution, dosage] = response.detail.filter((d) => d.kind === "label");

  it("머리는 `{약 이름} 허가사항 원문({항목})`이고 원문은 인용부호 안에 받은 그대로다", () => {
    render(<PermitText item={caution} />);
    const box = screen.getByTestId("permit-text");
    expect(box.querySelector("b")?.textContent).toBe(`${caution.drug_name} 허가사항 원문(${caution.section})`);
    expect(box.querySelector("q")?.textContent).toBe(rowTexts(caution)[0]);
    expect(tagDataset(within(box).getByTestId("source-tag"))).toBe(caution.dataset);
  });

  it("용법·용량도 표로 쪼개지 않고 원문 인용 그대로다(줄바꿈·숫자 가공 없음)", () => {
    const { container } = render(<PermitText item={dosage} />);
    expect(container.querySelector("table, dl, ul, ol")).toBeNull();
    expect(container.querySelectorAll("q")).toHaveLength(1);
    expect(container.querySelector("q")?.textContent).toBe(rowTexts(dosage)[0]);
    expect(rowTexts(dosage)[0]).toContain("\n");
  });

  it("허가정보가 아닌 인용(쉬운 설명 등)에는 '허가사항 원문' 머리를 붙이지 않는다", () => {
    render(<PermitText item={{ ...caution, dataset_key: "eyak", dataset: "받은 자료 이름" }} />);
    const head = screen.getByTestId("permit-text").querySelector("b")?.textContent;
    expect(head).toBe(`${caution.drug_name} · ${caution.section}`);
    expect(head).not.toContain("허가사항 원문");
    expect(tagDataset(screen.getByTestId("source-tag"))).toBe("받은 자료 이름");
  });

  it("약 이름·항목이 비면 그 부분을 그리지 않는다", () => {
    expect(copy.permitHeading(null, "상호작용")).toBe("허가사항 원문(상호작용)");
    expect(copy.permitHeading("가나다정", null)).toBe("가나다정 허가사항 원문");
    expect(copy.permitHeading(null, null)).toBe("허가사항 원문");
  });
});

describe("MissingBox·MissingGroup", () => {
  const response = fixtures.missingEvidenceResponse;
  const item = response.detail[1];

  it("미확보 문구는 응답 값 그대로이고 화면 상수가 아니다", () => {
    render(<MissingBox item={item} />);
    expect(screen.getByTestId("missing-text").textContent).toBe(PHRASES.MISSING_SEARCH_MISS);
    render(<MissingBox item={{ ...item, missing_text: "서버가 준 다른 미확보 문구" }} />);
    expect(screen.getByText("서버가 준 다른 미확보 문구")).toBeInTheDocument();
    expect(JSON.stringify(copy)).not.toMatch(/찾지 못|불러오지 못|확인할 수 없|적혀 있지/);
  });

  it("항목 박스에는 약사 확인 권고가 없다(권고는 구역 묶음이 한 번만 그린다)", () => {
    render(<MissingBox item={item} />);
    expect(screen.getByTestId("missing-box").querySelector('[data-testid="pharmacist-advice"]')).toBeNull();
  });

  it("묶음: 권고 박스 1개가 받은 글자 그대로 맨 위에 있고 접히지 않으며, 그 아래에 미확보 항목이 모두 있다", () => {
    const advice = ["복용 전에 꼭 약국·약사에게 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."];
    const items = [item, { ...item, drug_name: "라마바캡슐", missing_text: "받은 둘째 미확보 문구" }, { ...item, drug_name: "마바사정", missing_text: "받은 셋째 미확보 문구" }];
    render(<MissingGroup items={items} advice={advice} />);
    const group = screen.getByTestId("missing-group");
    const adviceBoxes = within(group).getAllByTestId("pharmacist-advice");
    expect(adviceBoxes).toHaveLength(1);
    expect(adviceBoxes[0].textContent).toBe(advice[0]);
    expect(adviceBoxes[0].closest(CLOSED)).toBeNull();
    expect(group.firstElementChild).toBe(adviceBoxes[0].closest("[data-testid='pharmacist-advice']"));
    const boxes = within(group).getAllByTestId("missing-box");
    expect(boxes).toHaveLength(items.length);
    expect(texts(boxes.map((box) => box.querySelector('[data-testid="missing-text"]')!))).toEqual(items.map((i) => i.missing_text));
    expect(boxes.map((box) => box.querySelector("b")?.textContent)).toEqual(items.map((i) => `${i.drug_name} · ${i.section}`));
    // 권고가 항목보다 위에 있다
    expect(adviceBoxes[0].compareDocumentPosition(boxes[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(group.querySelector("details, button")).toBeNull();
    expect(group.textContent).not.toContain("삐!");
  });

  it("묶음: 미확보 항목이 없으면 아무것도 그리지 않는다", () => {
    const { container } = render(<MissingGroup items={[]} advice={["받은 권고"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("EvidenceDetail: 허가사항 구역의 미확보 항목이 미확보 박스로 나오고 권고는 구역에 하나, 응답의 줄이다", () => {
    const withAdvice: ChatResponse = { ...response, pharmacist_advice: ["받은 권고 첫 문장. 받은 권고 둘째 문장."] };
    render(<EvidenceDetail response={withAdvice} />);
    const label = screen.getAllByTestId("evidence-section").find((el) => el.getAttribute("data-section") === "label")!;
    const box = within(label).getByTestId("missing-box");
    expect(box.querySelector("b")?.textContent).toBe(`${item.drug_name} · ${item.section}`);
    expect(within(label).getByTestId("pharmacist-advice").textContent).toBe(withAdvice.pharmacist_advice[0]);
    expect(within(label).queryByTestId("permit-text")).toBeNull();
  });
});

describe("약사 확인 권고의 구역 필터(pharmacist_advice_kinds, AG-08-28 A)", () => {
  // 등급 정의 미확보 + 허가사항 미확보가 함께 온 응답: 권고 두 줄(약 조합 권고 → 등급 뜻 권고)
  const response = fixtures.gradeDefAndMissingResponse;
  const [missingLine, gradeDefLine] = response.pharmacist_advice;
  const section = (id: string) => screen.getAllByTestId("evidence-section").find((el) => el.getAttribute("data-section") === id)!;
  const adviceLines = (root: HTMLElement) => texts(within(root).getAllByTestId("pharmacist-advice").flatMap((box) => [...box.querySelectorAll("p")]));

  it("fixture: 두 종류의 권고 줄과 같은 길이·순서의 종류 칸이 있다", () => {
    expect(response.pharmacist_advice).toHaveLength(2);
    expect(response.pharmacist_advice_kinds).toEqual(["missing", "grade_def"]);
    expect(gradeDefLine).toBe(PHRASES.GRADE_DEF_PHARMACIST_ADVICE);
    expect(missingLine).not.toBe(gradeDefLine);
  });

  it("이전 곁가지 재현: 종류 칸이 없으면(옛 응답) 두 줄이 두 구역 모두에 그대로 나온다(지금 동작 유지)", () => {
    render(<EvidenceDetail response={{ ...response, pharmacist_advice_kinds: [] }} />);
    expect(adviceLines(within(section("judgment")).getByTestId("grade-def-missing"))).toEqual([missingLine, gradeDefLine]);
    expect(adviceLines(within(section("label")).getByTestId("missing-group"))).toEqual([missingLine, gradeDefLine]);
  });

  it("종류 칸이 오면 등급 정의 블록에는 grade_def 줄만, 허가사항 미확보 묶음에는 missing 줄만 나온다", () => {
    render(<EvidenceDetail response={response} />);
    expect(adviceLines(within(section("judgment")).getByTestId("grade-def-missing"))).toEqual([gradeDefLine]);
    const group = within(section("label")).getByTestId("missing-group");
    expect(adviceLines(group)).toEqual([missingLine]);
    // 묶음 규칙은 그대로다: 권고 박스 1개가 맨 위, 접히지 않는다(FE-02-05 A)
    expect(within(group).getAllByTestId("pharmacist-advice")).toHaveLength(1);
    expect(group.firstElementChild).toBe(within(group).getByTestId("pharmacist-advice"));
    expect(within(group).getByTestId("pharmacist-advice").closest(CLOSED)).toBeNull();
  });

  it("사유 원문 구역의 미확보 묶음에도 missing 줄만 나온다", () => {
    const reasonMissing = { ...fixtures.foundResponse.detail[0], evidence_id: "ev-pair-missing", rows: [], missing_reason: "FETCH_FAIL", missing_text: PHRASES.MISSING_FETCH_FAIL };
    render(<EvidenceDetail response={{ ...response, detail: [...response.detail, reasonMissing] }} />);
    expect(adviceLines(within(section("reason")).getByTestId("missing-group"))).toEqual([missingLine]);
    expect(adviceLines(within(section("label")).getByTestId("missing-group"))).toEqual([missingLine]);
    expect(adviceLines(within(section("judgment")).getByTestId("grade-def-missing"))).toEqual([gradeDefLine]);
  });

  it("같은 종류의 줄이 여럿이면 받은 순서 그대로 모두 나오고 글자를 바꾸지 않는다", () => {
    const lines = ["받은 미확보 권고 하나.", "받은 등급 권고.", "받은 미확보 권고 둘."];
    expect(adviceOf({ pharmacist_advice: lines, pharmacist_advice_kinds: ["missing", "grade_def", "missing"] })).toEqual({
      missing: [lines[0], lines[2]],
      gradeDef: [lines[1]],
    });
  });

  it("종류 칸의 길이가 권고 줄과 어긋나면 고르지 않고 전부 보인다(권고를 숨기지 않는다)", () => {
    const lines = ["받은 권고 하나.", "받은 권고 둘."];
    expect(adviceOf({ pharmacist_advice: lines, pharmacist_advice_kinds: ["missing"] })).toEqual({ missing: lines, gradeDef: lines });
    expect(adviceOf({ pharmacist_advice: lines, pharmacist_advice_kinds: [] })).toEqual({ missing: lines, gradeDef: lines });
  });

  it("구역을 가르는 데 권고 문구를 비교하지 않는다: 글자가 바뀌어도 종류 칸대로 나뉜다", () => {
    render(<EvidenceDetail response={{ ...response, pharmacist_advice: ["서버가 바꾼 미확보 권고.", "서버가 바꾼 등급 권고."] }} />);
    expect(adviceLines(within(section("judgment")).getByTestId("grade-def-missing"))).toEqual(["서버가 바꾼 등급 권고."]);
    expect(adviceLines(within(section("label")).getByTestId("missing-group"))).toEqual(["서버가 바꾼 미확보 권고."]);
  });
});

describe("evidence_id가 없는 제품 줄(BE-06-41 A)", () => {
  const response = fixtures.productRowsResponse;

  it("판정 박스가 줄마다 하나씩 받은 순서로 나오고, React key 경고(같은 key·key 없음)가 없다", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<EvidenceDetail response={response} />);
    const boxes = screen.getAllByTestId("judgment-box");
    expect(boxes).toHaveLength(response.findings.length);
    expect(texts(boxes.map((box) => within(box).getByTestId("line-title")))).toEqual(response.findings.map((f) => f.drug));
    expect(error.mock.calls.filter((call) => /key/i.test(String(call[0])))).toEqual([]);
    error.mockRestore();
  });

  it("evidence_id가 없는 줄은 다른 줄의 근거 표지를 빌리지 않고, 배지는 받은 순서 그대로다", () => {
    render(<EvidenceDetail response={response} />);
    const boxes = screen.getAllByTestId("judgment-box");
    response.findings.forEach((finding, index) => {
      expect(texts(within(boxes[index]).getAllByTestId("status-badge"))).toEqual(finding.badges.map((b) => b.text));
      // 박스 표지는 줄의 `evidence_id`가 가리키는 근거 하나의 것이다. 배지가 여러 근거를 가리키는 제품 줄에는 표지를 짓지 않는다
      expect(within(boxes[index]).queryAllByTestId("source-tag")).toHaveLength(finding.evidence_id === null ? 0 : 1);
    });
  });

  it("배지가 가리키는 근거는 사유 원문·출처 구역에 그대로 있다(근거 상세는 응답 단위로 열린다)", () => {
    render(<EvidenceDetail response={response} />);
    expect(sections()).toEqual(["judgment", "reason", "sources"]);
    const ids = new Set(response.findings.flatMap((f) => f.badges.map((b) => b.evidence_id)));
    for (const id of ids) expect(response.detail.some((item) => item.evidence_id === id)).toBe(true);
    expect(screen.getAllByTestId("reason-box")).toHaveLength(response.detail.length);
  });
});

describe("GradeDefBlock", () => {
  const advice = ["받은 등급 권고 문장."];

  it("미확보 문구와 약사 권고는 접힘 밖에 받은 그대로 보이고 출처 줄이 없다", () => {
    render(<GradeDefBlock missing={["받은 등급 정의 미확보 문구"]} advice={advice} />);
    const missing = screen.getByTestId("grade-def-missing");
    expect(missing).toHaveTextContent("받은 등급 정의 미확보 문구");
    expect(within(missing).getByTestId("pharmacist-advice").textContent).toBe(advice[0]);
    expect(missing.closest(CLOSED)).toBeNull();
    expect(screen.getByTestId("grade-def").querySelector("blockquote, [data-slot='source']")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("정의 원문 블록은 기본으로 접혀 있고 누르면 원문이 받은 그대로 보인다. 미확보·권고는 그와 상관없이 보인다", async () => {
    render(
      <GradeDefBlock
        definitions={[
          { grade: "2", title: "받은 블록 제목", text: "받은 고시 원문 인용", source: "받은 출처 표기", missing_reason: null, missing_text: null },
          { grade: "1", title: "받은 미확보 블록 제목", text: null, source: null, missing_reason: "FETCH_FAIL", missing_text: "받은 등급 정의 미확보 문구" },
        ]}
        missing={["받은 등급 정의 미확보 문구"]}
        advice={advice}
      />,
    );
    const trigger = screen.getByRole("button", { name: "받은 블록 제목" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("받은 고시 원문 인용")).toBeNull();
    // 구조 칸이 오면 미확보 문구는 그 칸의 값으로 한 번만 보인다(줄 목록 칸과 겹쳐 두 번 그리지 않는다)
    expect(screen.getAllByText("받은 등급 정의 미확보 문구")).toHaveLength(1);
    expect(screen.getByText("받은 등급 정의 미확보 문구")).toBeVisible();
    expect(screen.getByTestId("pharmacist-advice")).toBeVisible();
    // 원문이 없는 블록은 접힘 블록(버튼)도 조항 출처 줄도 없다
    expect(screen.queryByRole("button", { name: "받은 미확보 블록 제목" })).toBeNull();
    await userEvent.click(trigger);
    expect(screen.getByText("받은 고시 원문 인용")).toBeInTheDocument();
    expect(screen.getByText("받은 출처 표기")).toBeInTheDocument();
  });

  it("EvidenceDetail: 응답의 grade_def_missing 줄이 판정 구역에 그대로 나온다", () => {
    const response: ChatResponse = { ...fixtures.gradeMismatchResponse, grade_def_missing: ["받은 미확보 줄 하나", "받은 미확보 줄 둘"], pharmacist_advice: advice };
    render(<EvidenceDetail response={response} />);
    expect(texts([...screen.getByTestId("grade-def-missing").querySelectorAll(":scope > p")])).toEqual(response.grade_def_missing);
    expect(screen.getByTestId("grade-def").closest('[data-section="judgment"]')).not.toBeNull();
  });

  it("줄이 없으면 그리지 않는다", () => {
    const { container } = render(<GradeDefBlock missing={[]} advice={advice} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SourceTable", () => {
  const citations = sample("rich-sources").citations;

  it("행 순서는 citations[] 그대로이고 기관은 한 번씩만 나온다", () => {
    render(<SourceTable citations={citations} />);
    expect(texts(screen.getAllByTestId("source-dataset"))).toEqual(citations.map((c) => c.dataset));
    const publishers = texts(screen.getAllByTestId("source-publisher"));
    expect(publishers).toEqual([...new Set(citations.map((c) => c.publisher))]);
    expect(new Set(publishers).size).toBe(publishers.length);
    expect(within(screen.getAllByTestId("source-group")[0]).getAllByTestId("source-row")).toHaveLength(2);
  });

  it("순서를 정하지 않는다: 뒤집어 줘도 뒤집힌 순서 그대로다", () => {
    const reversed = [...citations].reverse();
    render(<SourceTable citations={reversed} />);
    expect(texts(screen.getAllByTestId("source-dataset"))).toEqual(reversed.map((c) => c.dataset));
  });

  it("같은 기관이 떨어져 와도 한 묶음으로 모으고 자료 행은 받은 순서를 지킨다", () => {
    const apart = [citations[0], citations[2], citations[1]];
    expect(groupByPublisher(apart).map((g) => [g.publisher, g.rows.map((r) => r.dataset)])).toEqual([
      [citations[0].publisher, [citations[0].dataset, citations[1].dataset]],
      [citations[2].publisher, [citations[2].dataset]],
    ]);
  });

  it("날짜는 한 날짜 = 한 줄이고 받은 순서·글자 그대로다(같은 라벨이 여럿이어도 줄마다 하나)", () => {
    render(<SourceTable citations={citations} />);
    const rows = screen.getAllByTestId("source-row");
    rows.forEach((row, index) => {
      const lines = within(row).getAllByRole("listitem");
      expect(lines.map((li) => [...li.children].map((c) => c.textContent))).toEqual(citations[index].dates.map((d) => [d.label, d.value]));
      for (const li of lines) expect(li).toHaveClass("whitespace-nowrap");
    });
    expect(within(rows[2]).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByTestId("source-table")).toHaveClass("[word-break:keep-all]");
  });

  it("고시 번호·판·쪽은 값이 있을 때만 받은 그대로 보인다", () => {
    render(<SourceTable citations={citations} />);
    const rows = screen.getAllByTestId("source-row");
    expect(rows[0].querySelector('[data-slot="source-extra"]')).toBeNull();
    const extras = texts([...rows[2].querySelectorAll('[data-slot="source-extra"]')]);
    expect(extras).toEqual(["고시 번호2025000220240001", "판2026년판", "쪽12쪽13쪽"]);
  });

  it("출처가 없으면 그리지 않는다", () => {
    const { container } = render(<SourceTable citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("EvidencePanel·진입 버튼", () => {
  it("진입 글자는 둘뿐이다: 시트 '근거 상세 보기', 패널 '근거 상세 열기'", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<EvidenceEntryButton mode="sheet" onClick={onClick} />);
    expect(screen.getByRole("button")).toHaveTextContent("근거 상세 보기");
    rerender(<EvidenceEntryButton mode="panel" onClick={onClick} />);
    expect(screen.getByRole("button")).toHaveTextContent("근거 상세 열기");
    expect(screen.getByRole("button")).toHaveClass("min-h-11");
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(Object.values(copy.ENTRY_LABELS)).toEqual(["근거 상세 보기", "근거 상세 열기"]);
  });

  it("패널 배치: 열리면 제목과 닫기 버튼이 있고, 닫으면 내용을 그리지 않는다", async () => {
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <EvidencePanel mode="panel" open onOpenChange={onOpenChange}>
        <EvidenceDetail response={fixtures.foundResponse} />
      </EvidencePanel>,
    );
    const panel = screen.getByRole("complementary", { name: copy.EVIDENCE_TITLE });
    expect(panel).toHaveAttribute("data-mode", "panel");
    expect(within(panel).getByTestId("evidence-detail")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: copy.CLOSE_LABEL }));
    expect(onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
    rerender(
      <EvidencePanel mode="panel" open={false} onOpenChange={onOpenChange}>
        <EvidenceDetail response={fixtures.foundResponse} />
      </EvidencePanel>,
    );
    expect(screen.queryByTestId("evidence-detail")).toBeNull();
  });

  it("시트 배치: 열리면 대화상자로 제목과 함께 보이고 닫기 버튼으로 닫는다", async () => {
    const onOpenChange = vi.fn();
    render(
      <EvidencePanel mode="sheet" open onOpenChange={onOpenChange}>
        <EvidenceDetail response={fixtures.foundResponse} />
      </EvidencePanel>,
    );
    const dialog = screen.getByRole("dialog", { name: copy.EVIDENCE_TITLE });
    expect(dialog).toHaveAttribute("data-mode", "sheet");
    expect(within(dialog).getByTestId("evidence-detail")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: copy.CLOSE_LABEL }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("근거 상세가 닫혀 있어도 고정 안내는 그대로 보인다(틀 밖에 둔다)", () => {
    render(
      <>
        <EvidencePanel mode="sheet" open={false} onOpenChange={() => {}}>
          <EvidenceDetail response={fixtures.missingEvidenceResponse} />
        </EvidencePanel>
        <FixedNoticeBox lines={fixtures.missingEvidenceResponse.fixed_notice} />
      </>,
    );
    expect(screen.queryByTestId("evidence-detail")).toBeNull();
    const fixed = screen.getByTestId("fixed-notice");
    expect(fixed).toBeVisible();
    expect(fixed.closest(`${CLOSED}, [role='dialog']`)).toBeNull();
    expect([...fixed.querySelectorAll("p")].map((p) => p.textContent)).toEqual(fixtures.missingEvidenceResponse.fixed_notice);
  });
});

describe("FE-02 FR-04: 답변의 출처·조회 시각/기준일·조항 글자", () => {
  const sourceRows = () =>
    screen.getAllByTestId("source-row").map((row) => ({
      dataset: row.querySelector("[data-testid='source-dataset']")?.textContent,
      dates: [...row.querySelectorAll("[data-testid='date-lines'] li")].map((li) => texts([...li.querySelectorAll("span")])),
      extras: [...row.querySelectorAll("[data-slot='source-extra']")].map((extra) => texts([...extra.querySelectorAll("span")])),
    }));

  it("파일 근거: 출처(기관·자료)와 기준일·고시일, 고시 번호가 받은 글자 그대로 보인다", () => {
    const response = fixtures.foundResponse;
    render(<EvidenceDetail response={response} />);
    const [citation] = response.citations;
    expect(texts(screen.getAllByTestId("source-publisher"))).toEqual([citation.publisher]);
    expect(sourceRows()).toEqual([
      {
        dataset: citation.dataset,
        dates: citation.dates.map((line) => [line.label, line.value]),
        extras: [[copy.SOURCE_EXTRA_LABELS.noticeNos, ...citation.notice_nos]],
      },
    ]);
    // 표본 값 자체도 확인한다(빈 값끼리 같은 것이 아니다)
    expect(citation.dates.map((line) => line.label)).toEqual(["고시일", "기준일"]);
    expect(citation.notice_nos).toEqual(["20260001"]);
  });

  it("실시간 조회 근거: 조회 시각 줄(`조회`)이 파일의 기준일 줄과 따로, 받은 순서대로 보인다", () => {
    const response = fixtures.gradeMismatchResponse;
    render(<EvidenceDetail response={response} />);
    const rows = sourceRows();
    expect(rows.map((row) => row.dataset)).toEqual(response.citations.map((citation) => citation.dataset));
    expect(rows.map((row) => row.dates)).toEqual(response.citations.map((citation) => citation.dates.map((line) => [line.label, line.value])));
    expect(rows[0].dates).toEqual([["조회", "2026-11-12"]]);
    expect(rows.flatMap((row) => row.dates.map(([label]) => label))).toContain("기준일");
  });

  it("조항 글자: 등급 정의 블록의 조항 출처 줄이 받은 글자 그대로 보인다(제○조 제○호까지)", async () => {
    const response = fixtures.gradeDefsResponse;
    const [quoted] = response.grade_defs;
    // 표본의 조항 글자 자체를 확인한다: 고시 이름과 조·호·목
    expect(quoted.source).toMatch(/「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 나목/);
    render(<EvidenceDetail response={response} />);
    await userEvent.click(screen.getByRole("button", { name: quoted.title }));
    const sourceLine = screen.getByTestId("grade-def").querySelector("[data-slot='grade-def-source']");
    expect(sourceLine?.textContent).toBe(quoted.source);
    expect(sourceLine?.textContent).toContain("제3조 제3호 나목");
    // 조항 줄은 그 원문 인용과 같은 블록 안에 있다(원문 바로 뒤)
    expect(sourceLine?.previousElementSibling?.tagName).toBe("BLOCKQUOTE");
    expect(sourceLine?.previousElementSibling?.textContent).toBe(quoted.text);
  });

  it("조항 글자는 화면이 짓지 않는다: 다른 조항이 오면 그 글자를, 오지 않으면 조항 줄을 그리지 않는다", async () => {
    const base = { grade: "1" as const, title: "받은 제목", text: "받은 원문", missing_reason: null, missing_text: null };
    const { unmount } = render(<GradeDefBlock definitions={[{ ...base, source: "받은 고시 제9조 제2항" }]} missing={[]} advice={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "받은 제목" }));
    expect(screen.getByTestId("grade-def").querySelector("[data-slot='grade-def-source']")?.textContent).toBe("받은 고시 제9조 제2항");
    unmount();
    render(<GradeDefBlock definitions={[{ ...base, source: null }]} missing={[]} advice={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "받은 제목" }));
    expect(screen.getByTestId("grade-def").querySelector("[data-slot='grade-def-source']")).toBeNull();
    expect(screen.getByTestId("grade-def").textContent).not.toMatch(/제\d+조/);
  });

  it("프런트 고유 글자(copy.ts)에 조항·날짜 값이 없다(칸 이름뿐)", () => {
    expect(JSON.stringify(copy)).not.toMatch(/제\d+조|\d{4}-\d{2}/);
  });

  it("판정 근거가 있는 모든 fixture: 출처 표의 행 수·자료·날짜 줄이 citations[]와 같다", () => {
    const all = Object.entries(fixtures).filter(([name, value]) => name.endsWith("Response") && (value as ChatResponse).citations.length > 0) as [string, ChatResponse][];
    expect(all.length).toBeGreaterThanOrEqual(8);
    for (const [name, response] of all) {
      const { unmount } = render(<EvidenceDetail response={response} />);
      const rows = sourceRows();
      // 기관별로 묶으므로 같은 기관이 떨어져 오면 순서가 달라질 수 있다: 묶은 순서로 견준다
      const expected = groupByPublisher(response.citations).flatMap((group) => group.rows);
      expect(rows.map((row) => row.dataset), name).toEqual(expected.map((citation) => citation.dataset));
      expect(rows.map((row) => row.dates), name).toEqual(expected.map((citation) => citation.dates.map((line) => (line.value === null ? [line.label] : [line.label, line.value]))));
      for (const row of rows) expect(row.dates.length, name).toBeGreaterThan(0); // 출처마다 날짜 줄이 하나 이상
      unmount();
    }
  });
});

describe("PRD-09-01~04 근거 상세 판정 박스의 등급 표기", () => {
  const all = Object.entries(fixtures).filter(([name]) => name.endsWith("Response")) as [string, ChatResponse][];

  it.each(all)("%s: 판정 박스에서 등급은 배지에만 있고 '단계' 글자가 화면에 없다", (_name, response) => {
    const { container, unmount } = render(<EvidenceDetail response={response} />);
    for (const box of container.querySelectorAll('[data-testid="judgment-box"]')) {
      const copyBox = box.cloneNode(true) as Element;
      for (const badge of copyBox.querySelectorAll('[data-testid="status-badge"]')) badge.remove();
      expect(copyBox.textContent ?? "").not.toMatch(/(1|2|M)등급/);
    }
    expect(container.textContent ?? "").not.toContain("단계");
    unmount();
  });

  it("등급 불일치: 배지 둘이 출처 꼬리를 달고 둘 다 보인다(합친 배지 없음)", () => {
    render(<EvidenceDetail response={fixtures.gradeMismatchResponse} />);
    const box = screen.getAllByTestId("judgment-box")[0];
    expect(texts(within(box).getAllByTestId("status-badge"))).toEqual(["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]);
  });

  it("등급 정의 블록 제목은 '임부금기 N등급이란?'이고 기본으로 접혀 있다", () => {
    render(<EvidenceDetail response={fixtures.gradeDefsResponse} />);
    const trigger = screen.getByRole("button", { name: "임부금기 2등급이란?" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("grade-def").querySelector("blockquote")).toBeNull(); // 접힌 동안 원문을 그리지 않는다
  });

  it("프런트 고유 글자(copy.ts)에 '단계'가 없다", () => {
    expect(JSON.stringify(copy)).not.toContain("단계");
  });
});
