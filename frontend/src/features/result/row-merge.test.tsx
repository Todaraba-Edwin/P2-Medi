// FE-17 U-30(2026-11-24, ISSUE-035 "타이레놀정500 먹고 이부프로펜도 먹어도 돼요?" 결과·근거 상세 지적)을 합성 응답 `u30Response`(같은 모양)로 본다.
// (a) 출처만 다른 배지 하나로 (b) 같은 약 줄 한 행 (c) 병용(쌍) 줄 맨 위 (d) 쌍 줄 안 두 약의 하루 최대량 주의 (e) `금기 목록에 없음` 괄호 안내 뗌
// (f) `파일과 실시간 조회 결과가 같아요` 뺌 (g) 근거 상세도 같은 배지·글자 정리 (h) 판정·사유 원문 한 구역 (i) 같은 내용 문장 하나로 (j) 반복 노트 묶음당 한 번
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceDetail } from "@/features/evidence";
import { reasonTextKey } from "@/features/evidence/sections";
import { FixedNoticeBox } from "@/features/emergency";
import type { Badge, ChatResponse, Finding } from "@/lib/api";
import { API_SAME_NOTE as GENERATED_API_SAME, CAUTION_DOSE_LABEL, NOT_LISTED } from "@/lib/fixed/phrases.generated";
import { API_SAME_NOTE, BADGE_SOURCE_TAIL, CAUTION_DOSE, FIXED_NOTICE, PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import { ResultView } from "./ResultView";
import { ResultCard } from "./ResultCard";
import { mergeSourceBadges, pairDoseLines, resultRows, shortStatusText, withoutApiSame } from "./row-merge";

const response = fixtures.u30Response;
const [ib, tyDose, pair, tyPreg] = response.findings;
const TY = tyDose.drug;
const IB = ib.drug;
const texts = (elements: Element[]) => elements.map((el) => el.textContent);
const preg = (grade: string) => PHRASES.BADGE_PREGNANCY.replace("{grade}", grade);

describe("u30 합성 응답은 사용자 사례(ISSUE-035)의 모양이다", () => {
  it("라마성분 줄에 배지 3개(2등급 파일·2등급 성분 API·1등급 성분 API), 같은 약(가나다정) 줄 2개, 쌍 줄이 세 번째, 행마다 `파일과 실시간…` 노트", () => {
    expect(ib.badges.map((badge) => badge.text)).toEqual([`${preg("2")} ${BADGE_SOURCE_TAIL.FILE}`, `${preg("2")} ${BADGE_SOURCE_TAIL.API_DIRECT}`, `${preg("1")} ${BADGE_SOURCE_TAIL.API_DIRECT}`]);
    expect(response.findings.filter((finding) => finding.drug === TY)).toHaveLength(2);
    expect(response.findings.map((finding) => finding.target).indexOf("pair")).toBe(2);
    expect(response.findings.filter((finding) => finding.notes.includes(API_SAME_NOTE))).toHaveLength(3);
    expect(GENERATED_API_SAME).toBe(API_SAME_NOTE);
    expect(CAUTION_DOSE_LABEL).toBe(CAUTION_DOSE);
    // 근거 상세: 임부금기 파일 근거마다 같은 노트 2개(행마다 반복)
    expect(response.detail.filter((item) => item.notes.includes(PHRASES.GRADE_MISMATCH_NOTE)).length).toBeGreaterThan(10);
  });
});

describe("(a) 출처 꼬리만 다른 같은 배지 하나로", () => {
  it("2등급(파일)+2등급(성분 API) → `삐! 임부금기 2등급 (파일, 성분 API)` 하나, 등급이 다른 1등급(성분 API)은 따로", () => {
    const merged = mergeSourceBadges(ib.badges);
    expect(merged.map((badge) => badge.text)).toEqual([`${preg("2")} (파일, 성분 API)`, `${preg("1")} (성분 API)`]);
    expect(merged[0].merged.map((badge) => badge.evidence_id)).toEqual(["preg-ib-a-1", "preg-ib-api-2"]);
    expect(merged[1].merged).toHaveLength(1);
  });

  it("출처(source)가 없는 배지·종류가 다른 배지·꼬리 앞 글자가 다른 배지는 합치지 않는다", () => {
    const pairBadge: Badge = { kind: "contra_pair", grade: null, source: null, text: PHRASES.BADGE_PAIR, evidence_id: "p1", note: null };
    expect(mergeSourceBadges([pairBadge, { ...pairBadge, evidence_id: "p2" }]).map((badge) => badge.text)).toEqual([PHRASES.BADGE_PAIR, PHRASES.BADGE_PAIR]);
    const a: Badge = { kind: "pregnancy", grade: "2", source: "FILE", text: `${preg("2")} (파일)`, evidence_id: "a", note: null };
    const b: Badge = { ...a, kind: "age", source: "API_DIRECT", text: `${preg("2")} (성분 API)` };
    expect(mergeSourceBadges([a, b])).toHaveLength(2);
    expect(mergeSourceBadges([a, { ...a, source: "API_DIRECT", text: `${preg("1")} (성분 API)`, grade: "1" }])).toHaveLength(2);
  });

  it("결과 카드·근거 상세의 배지 글자: 합친 배지에는 합친 수와 근거 ID가 속성으로 남는다", () => {
    render(<ResultCard response={response} />);
    const line = screen.getAllByTestId("product-line").find((el) => within(el).getByTestId("line-title").textContent === IB)!;
    const badges = within(line).getAllByTestId("status-badge");
    expect(texts(badges)).toEqual([`${preg("2")} (파일, 성분 API)`, `${preg("1")} (성분 API)`]);
    expect(badges[0]).toHaveAttribute("data-merged", "2");
    expect(badges[0]).toHaveAttribute("data-evidence-ids", "preg-ib-a-1 preg-ib-api-2");
    expect(badges[1]).not.toHaveAttribute("data-merged");
  });
});

describe("(b)(c) 본문 결과 카드: 쌍 줄 맨 위, 같은 약 줄 한 행", () => {
  it("행 묶기: 쌍 → 라마성분 → 가나다정(용량주의 줄 + 임부금기 금기 목록에 없음 줄이 한 행)", () => {
    const rows = resultRows(response.findings);
    expect(rows.map((row) => row.main.finding.drug)).toEqual([pair.drug, IB, TY]);
    expect(rows[2].siblings.map((sibling) => sibling.finding)).toEqual([tyPreg]);
    render(<ResultCard response={response} />);
    const lines = screen.getAllByTestId("product-line");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveAttribute("data-target", "pair");
    expect(texts(lines.map((el) => within(el).getByTestId("line-title")))).toEqual([pair.drug, IB, TY]);
    const ty = lines[2];
    expect(ty).toHaveAttribute("data-merged-rows", "2");
    expect(ty).toHaveAttribute("data-kinds", "dose pregnancy");
    // 한 행 안에 두 줄의 표지와 출처가 모두 있다(받은 순서)
    expect(texts(within(ty).getAllByTestId("line-text"))).toEqual([CAUTION_DOSE, "금기 목록에 없음"]);
    expect(texts([...ty.querySelectorAll('[data-slot="source"]')])).toEqual(["공식 파일 · 용량주의 파일", "공식 파일 · 임부금기 파일"]);
    expect(screen.getAllByText(TY, { selector: '[data-testid="line-title"]' })).toHaveLength(1);
  });

  it("같은 약 줄이 같은 글자를 가지면 행 안에서 한 번만 보인다", () => {
    const twice: ChatResponse = { ...response, findings: [tyDose, { ...tyDose, evidence_id: "dose:300002ATB" }] };
    render(<ResultCard response={twice} />);
    const line = screen.getByTestId("product-line");
    expect(within(line).getAllByTestId("line-text")).toHaveLength(1);
    expect(line.querySelectorAll('[data-slot="source"]')).toHaveLength(1);
  });

  it("제품 줄끼리만 합친다: 쌍 줄·이름이 다른 줄은 합치지 않는다", () => {
    const rows = resultRows([pair, { ...pair, evidence_id: "ev-pair-2" }, ib, tyDose]);
    expect(rows.map((row) => row.siblings.length)).toEqual([0, 0, 0, 0]);
  });
});

describe("(d) 쌍 줄 안 두 약의 하루 최대량 주의", () => {
  it("두 약이 모두 하루 최대량 주의 성분을 가지면(줄 글자 또는 덧붙임 줄) 쌍 줄 안에 약 이름별로 같은 글자가 보인다", () => {
    expect(pairDoseLines(pair, response.findings)).toEqual([
      { drug: TY, text: CAUTION_DOSE },
      { drug: IB, text: CAUTION_DOSE },
    ]);
    render(<ResultCard response={response} />);
    const line = screen.getAllByTestId("product-line")[0];
    const doses = [...line.querySelectorAll('[data-slot="pair-dose"]')];
    expect(doses.map((el) => el.getAttribute("data-drug"))).toEqual([TY, IB]);
    expect(doses.map((el) => el.textContent)).toEqual([`${TY} - ${CAUTION_DOSE}`, `${IB} - ${CAUTION_DOSE}`]);
    expect(texts(within(line).getAllByTestId("pair-dose-text"))).toEqual([CAUTION_DOSE, CAUTION_DOSE]); // 새 글자 없음(서버 상수 그대로)
  });

  it("한 약만 해당하면 쌍 줄에 붙이지 않는다", () => {
    const one = response.findings.filter((finding) => finding !== tyDose);
    expect(pairDoseLines(pair, one)).toEqual([]);
    expect(pairDoseLines(pair, [pair, tyDose, { ...ib, notes: [] }])).toEqual([]);
    expect(pairDoseLines(ib, response.findings)).toEqual([]); // 쌍 줄이 아니면 없음
  });
});

describe("(e)(f) 반복 안내 정리와 '안전하다는 뜻이 아니에요' 안내 유지", () => {
  it("줄 글자 `금기 목록에 없음(안전하다는 뜻이 아님)`은 `금기 목록에 없음`으로(받은 글자의 앞부분, 전체는 속성), 다른 글자는 그대로", () => {
    expect(NOT_LISTED).toBe(PHRASES.NOT_LISTED);
    expect(shortStatusText(PHRASES.NOT_LISTED)).toBe("금기 목록에 없음");
    expect(shortStatusText(PHRASES.IDENTIFIED_LINE)).toBe(PHRASES.IDENTIFIED_LINE);
    expect(shortStatusText(`${PHRASES.NOT_LISTED} `)).toBe(`${PHRASES.NOT_LISTED} `); // 완전히 같을 때만
    render(<ResultCard response={response} />);
    const card = screen.getByTestId("result-card");
    expect(card.textContent).not.toContain("(안전하다는 뜻이 아님)");
    for (const text of within(card).getAllByTestId("line-text").filter((el) => el.textContent === "금기 목록에 없음")) expect(text).toHaveAttribute("data-full-text", PHRASES.NOT_LISTED);
  });

  it("`파일과 실시간 조회 결과가 같아요`는 본문·근거 상세 어디에도 없다(받은 응답에는 줄 3개·근거 15개에 있다)", () => {
    expect(withoutApiSame([API_SAME_NOTE, CAUTION_DOSE])).toEqual([CAUTION_DOSE]);
    render(
      <>
        <ResultView response={response} />
        <EvidenceDetail response={response} />
      </>,
    );
    expect(document.body.textContent).not.toContain(API_SAME_NOTE);
  });

  it("불변 조건(하네스 원칙): 결과 화면에 '안전하다는 뜻이 아니에요' 안내가 최소 1회 남는다(고정 안내 + 받은 묶음 요약·안내)", () => {
    render(
      <>
        <ResultView response={response} />
        <FixedNoticeBox lines={response.fixed_notice} />
      </>,
    );
    expect(response.fixed_notice).toContain(FIXED_NOTICE);
    const shown = document.body.textContent ?? "";
    expect(shown.match(/안전하다는 뜻이 아니/g)?.length ?? 0).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("fixed-notice").textContent).toContain(FIXED_NOTICE);
  });
});

describe("(g)(h)(i)(j) 근거 상세", () => {
  const draw = () => render(<EvidenceDetail response={response} />);
  const cards = () => screen.getAllByTestId("verdict-group");

  it("(h) 판정·사유 원문이 한 구역이고 판정 종류 카드마다 판정 줄과 그 사유 원문이 함께 있다. 병용 카드가 맨 위다", () => {
    draw();
    expect(screen.getAllByTestId("evidence-section").map((el) => el.getAttribute("data-section"))).toEqual(["judgment", "sources"]);
    expect(cards().map((card) => card.getAttribute("data-kind"))).toEqual(["contra_pair", "pregnancy", "dose"]);
    // 임부금기 카드: 판정 줄(라마성분, 가나다정 금기 목록에 없음) → 사유 원문(파일 칸 · 성분 API 칸, 자료가 다르면 칸이 나뉜다)
    const pregCard = cards()[1];
    expect(texts(within(pregCard).getAllByTestId("line-title"))).toEqual([IB, TY]);
    const reasonBoxes = within(pregCard).getAllByTestId("reason-box");
    expect(reasonBoxes.map((box) => within(box).getByTestId("source-tag").textContent)).toEqual(["공식 파일 · 임부금기 파일", "공식 자료 · DUR 성분정보 API"]);
    // 판정 칸이 사유 원문 칸보다 앞이다(같은 카드 안)
    const firstJudgment = within(pregCard).getAllByTestId("judgment-box")[0];
    expect(firstJudgment.compareDocumentPosition(reasonBoxes[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 용량주의 카드: 가나다정 용량주의 판정 줄 → 사유 원문별 묶음(U-25 구조 그대로)
    const doseCard = cards()[2];
    expect(texts(within(doseCard).getAllByTestId("line-title"))).toEqual([TY]);
    const groups = within(doseCard).getAllByTestId("reason-group");
    expect(groups.map((group) => within(group).getByTestId("reason-text").textContent)).toEqual(["가나성분으로 4,000mg", "라마성분 3,200mg", "가나성분으로써 4,000mg"]);
    expect(groups.map((group) => texts(within(group).getAllByTestId("reason-drug")))).toEqual([[`${TY} - 제형유형 6건`], [`${IB} - 제형유형 23건`], [`${IB} - 제형유형 1건`]]);
  });

  it("(g) 근거 상세 판정 줄도 배지 하나로·`금기 목록에 없음`·쌍 줄 안 하루 최대량 주의이고, 쌍 줄의 사유 원문 칸(약 이름 쌍 + 고정 문구)은 따로 없다", () => {
    draw();
    const ibLine = screen.getAllByTestId("product-line").find((el) => within(el).getByTestId("line-title").textContent === IB)!;
    expect(texts(within(ibLine).getAllByTestId("status-badge"))).toEqual([`${preg("2")} (파일, 성분 API)`, `${preg("1")} (성분 API)`]);
    const pairCard = cards()[0];
    expect(within(pairCard).getByTestId("line-text").textContent).toBe("금기 목록에 없음");
    expect(pairCard.querySelectorAll('[data-slot="pair-dose"]')).toHaveLength(2);
    expect(screen.queryByTestId("reason-not-listed")).toBeNull();
    expect(screen.getByTestId("evidence-detail").textContent).not.toContain("(안전하다는 뜻이 아님)");
  });

  it("(i) 영문 성분명 접두·공백·문장 부호만 다른 같은 문장은 한 묶음(같은 내용 11건, 근거 ID 모두 보존), 완전히 다른 내용(외용)은 따로", () => {
    draw();
    const fileBox = within(cards()[1]).getAllByTestId("reason-box")[0];
    const groups = within(fileBox).getAllByTestId("reason-group");
    expect(groups).toHaveLength(2);
    expect(texts(groups.map((group) => within(group).getByTestId("reason-drug")))).toEqual([`${IB} - 같은 내용 11건`, `${IB} - 같은 내용 2건`]);
    // 보이는 글자는 첫 항목 원문 그대로
    expect(within(groups[0]).getByTestId("reason-text").textContent).toBe(response.detail[0].rows[0].detail);
    expect(within(groups[1]).getByTestId("reason-text").textContent).toContain("(외용)");
    const ids = groups[0].getAttribute("data-evidence-ids")!.split(" ");
    expect(ids).toHaveLength(11);
    expect(ids).toEqual(expect.arrayContaining(["preg-ib-a-1", "preg-ib-b-1", "preg-ib-d-3"]));
    expect(groups[1].getAttribute("data-evidence-ids")).toBe("preg-ib-c-1 preg-ib-c-2");
  });

  it("(i) 비교 글자: 접두·공백·마침표·쉼표 차이는 같고, 숫자 안의 점·쉼표와 낱말 차이는 다르다", () => {
    expect(reasonTextKey("ibuprofen: 미확립.임신 말기")).toBe(reasonTextKey("미확립. 임신 말기"));
    expect(reasonTextKey("미확립, 임신")).toBe(reasonTextKey("미확립 임신"));
    expect(reasonTextKey("1.5mg 이상")).not.toBe(reasonTextKey("15mg 이상"));
    expect(reasonTextKey("4,000mg")).not.toBe(reasonTextKey("4000mg"));
    expect(reasonTextKey("(외용) 임신 후반기")).not.toBe(reasonTextKey("임신 후반기"));
    expect(reasonTextKey("가나성분으로 4,000mg")).not.toBe(reasonTextKey("가나성분으로써 4,000mg"));
    expect(reasonTextKey("NSAIDs 계열: 문장")).toBe("NSAIDs계열:문장"); // 한글이 섞인 머리는 접두로 보지 않는다
  });

  it("(j) 행마다 반복되던 노트는 판정 종류 카드마다 한 번만 보이고, `파일과 실시간…`은 없다(새 등급 불일치 문구는 받은 글자 그대로)", () => {
    draw();
    const pregCard = cards()[1];
    const notes = texts([...pregCard.querySelectorAll('[data-testid="reason-box"] [data-slot="notes"]')]);
    expect(notes).toEqual([PHRASES.GRADE_MISMATCH_NOTE]);
    expect(pregCard.textContent).not.toContain(API_SAME_NOTE);
  });

  it("(k) 사유 원문 칸에 보이는 글자는 받은 원문 칸 그대로다: 화면이 `test` 같은 글자를 더하지 않는다(비고 칸은 받은 글자 그대로 한 줄)", () => {
    draw();
    const apiBox = within(cards()[1]).getAllByTestId("reason-box")[1];
    expect(texts(within(apiBox).getAllByTestId("reason-text"))).toEqual(["(경구, 주사)- 임부에 대한 합성 안전성 미확립.(외용)- 임신 후반기 합성 외용 문장", "겔제, 첩부제 포함", "(경구, 주사)- 합성 1등급 문장"]);
    expect(screen.getByTestId("evidence-detail").textContent).not.toMatch(/\btest\b/);
  });
});

describe("다른 응답에는 영향이 없다", () => {
  it.each(Object.entries(fixtures).filter(([name]) => name.endsWith("Response")) as [string, ChatResponse][])("%s: 받은 줄은 모두 행 하나에 들어 있다(빠지는 줄 없음)", (_name, fixture) => {
    const rows = resultRows(fixture.findings);
    const placed: Finding[] = rows.flatMap((row) => [row.main, ...row.siblings].flatMap((entry) => [entry.finding, ...entry.labels]));
    expect(placed).toHaveLength(fixture.findings.length);
    expect(new Set(placed)).toEqual(new Set(fixture.findings));
  });
});
