import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EVIDENCE_SAMPLES } from "@/app/dev/preview/evidence/samples";
import { RESULT_SAMPLES } from "@/app/dev/preview/result/samples";
import { FixedNoticeBox } from "@/features/emergency";
import { EvidenceDetail, EvidenceEntryButton } from "@/features/evidence";
import * as evidenceCopy from "@/features/evidence/copy";
import { groupJudgments } from "@/features/evidence/sections";
import { ResultView, mergeSourceBadges, resultRows } from "@/features/result";
import type { ChatResponse } from "@/lib/api";
import { GRADE_DEF_MISSING_OUT_OF_SCOPE, PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";

// PRD 화면 시험 항목의 전수 확인(2026-11-18 goal 2차): 모든 fixture 응답과 미리보기 표본을 결과 카드 + 근거 상세로 그려
// 문서의 "화면에 없다"·"모든 박스에 있다" 꼴 규칙을 한꺼번에 본다. 항목 번호는 각 문서의 화면 시험 절이다
// (tickets/doc/PRD-09.md §7.5, PRD-10.md §7, PRD-11.md §8, PRD-12.md §9, PRD-14.md §6, PRD-15.md §7).
// 폭·줄바꿈·색처럼 실제 배치가 필요한 항목은 e2e(result.spec·evidence.spec·flows.spec·contrast.spec)가 본다.

const cases: [string, ChatResponse][] = [
  ...(Object.entries(fixtures).filter(([name]) => name.endsWith("Response")) as [string, ChatResponse][]),
  ...RESULT_SAMPLES.map((sample): [string, ChatResponse] => [`result-sample:${sample.id}`, sample.response]),
  ...EVIDENCE_SAMPLES.map((sample): [string, ChatResponse] => [`evidence-sample:${sample.id}`, sample.response]),
];

function draw(response: ChatResponse) {
  const view = render(
    <>
      <div data-testid="t-result">
        <ResultView response={response} onPickCandidate={() => {}} onOtherCandidate={() => {}} onRetryName={() => {}} />
      </div>
      <div data-testid="t-detail">
        <EvidenceDetail response={response} />
      </div>
      <div data-testid="t-fixed">
        <FixedNoticeBox lines={response.fixed_notice} />
      </div>
    </>,
  );
  const q = (selector: string) => [...view.container.querySelectorAll(selector)];
  return { ...view, q, text: view.container.textContent ?? "" };
}
const texts = (elements: Element[]) => elements.map((el) => el.textContent ?? "");

describe("표본 범위", () => {
  it("fixture 응답과 미리보기 표본을 모두 본다", () => {
    expect(cases.length).toBeGreaterThanOrEqual(60);
  });
});

describe.each(cases)("%s", (_name, response) => {
  it("화면에 없어야 하는 옛 문구·내부 용어가 없다(PRD-10 §7 ②⑤⑥, PRD-11 §8 ⑥⑫, PRD-14 §6 ③, PRD-15 §7 ⑨, PRD-09 §7.5 ③)", () => {
    const { text } = draw(response);
    for (const banned of [
      "자료 날짜", // PRD-10 ② 옛 구역
      "둘 다 보여 드려요", // PRD-10 ②
      "허가 라벨", // PRD-10 ⑤
      "허가정보 원문 인용", // PRD-10 ⑤
      "원문을 가져오지 못했어요", // PRD-11 ⑫
      "근거 문장을 찾지 못했어요", // PRD-15 ⑨
      "(서비스의 한계예요)", // ISSUE-007
      "이 서비스가 쓰는", // ISSUE-007
      "약 이름 사전", // PRD-14 ③
      "공식 약 목록",
      "다시 찾기(표기 바꿔서)",
      "사전·e약은요·허가정보에서",
      "근거 없음의 뜻", // PRD-14 §4.2 프로토타입 구역
      "단계", // PRD-09 ③
      "RAG", // PRD-11 ⑥
      "검색 실패",
      "청크",
      "API 오류",
    ]) {
      expect(text, banned).not.toContain(banned);
    }
    // PRD-10 ⑥: 값이 비어 보이는 대괄호 자리표시가 없다
    expect(text).not.toMatch(/\[[^\]]*\]/);
  });

  it("근거 박스: 표지 하나, 박스 안 출처·조회일 줄 없음, 표지의 자료 이름이 출처 표의 자료 열과 글자 일치(PRD-12 §9 ⑨~⑬, PRD-11 §8 ④⑨)", () => {
    const { q } = draw(response);
    const tableDatasets = new Set(texts(q('[data-testid="t-detail"] [data-testid="source-dataset"]')));
    const boxes = q('[data-testid="judgment-box"], [data-testid="reason-box"], [data-testid="permit-text"], [data-testid="missing-box"]');
    const missingDatasets = new Set(response.detail.filter((item) => item.missing_text !== null).map((item) => item.dataset));
    for (const box of boxes) {
      const tags = [...box.querySelectorAll('[data-testid="source-tag"]')];
      expect(tags.length).toBeLessThanOrEqual(1); // ⑬ 머리 한 줄에 표지 1개
      for (const tag of tags) {
        const dataset = tag.querySelector('[data-slot="source-dataset"]')?.textContent ?? "";
        expect(dataset).not.toBe(""); // ⑩ 표지에 자료 이름이 있다
        // ⑨⑫ 원문을 확보한 근거의 표지는 출처 표의 자료 열에 같은 글자로 있다.
        // 미확보 근거(그 박스와 그 근거의 "확인하지 못함" 판정 줄)는 뺀다: 원문을 가져오지 못한 근거에 출처 행(`citations[]`)을 줄지는 서버가 정한다(fixture에는 행이 없다, 보고의 "서버 몫")
        if (tableDatasets.size > 0 && !missingDatasets.has(dataset)) expect(tableDatasets.has(dataset), `표지 "${dataset}"가 출처 표에 없다`).toBe(true);
        // ⑪ 같은 출처 문자열은 박스 안에서 한 번만 "보인다"(판정 줄의 출처 표지는 박스 표지가 있으면 숨긴다)
        const visibleCopy = box.cloneNode(true) as Element;
        for (const hidden of visibleCopy.querySelectorAll('[data-slot="source"]')) hidden.remove();
        expect((visibleCopy.textContent ?? "").split(tag.textContent ?? "\u0000").length - 1).toBe(1);
      }
      // ⑪ 박스 안에 `출처: …`·조회일 줄이 없다(기관·조회일은 출처 표에만)
      expect(box.textContent ?? "").not.toMatch(/출처\s*:/);
      expect(box.textContent ?? "").not.toMatch(/조회(일)?\s*\d{4}-\d{2}/);
      expect(box.querySelector('[data-testid="date-lines"]')).toBeNull();
      // 박스 안 e약은요 라벨(`쉬운 설명(e약은요)`)을 본문에 따로 두지 않는다(PRD-12-04)
      expect([...box.querySelectorAll("p")].some((p) => (p.textContent ?? "").startsWith("쉬운 설명(e약은요)"))).toBe(false);
    }
    // 근거가 이어진(dataset이 있는) 사유·허가사항·미확보 박스에는 표지가 반드시 있다(⑩)
    for (const box of q('[data-testid="reason-box"], [data-testid="permit-text"]')) expect(box.querySelector('[data-testid="source-tag"]')).not.toBeNull();
  });

  it("허가사항 박스마다 약 이름·항목이 머리에 있고, 쉬운 설명 인용에는 '허가사항 원문'이 붙지 않는다(PRD-11 §8 ④⑦, PRD-10 §7 ⑦⑧)", () => {
    const { q } = draw(response);
    const labels = response.detail.filter((item) => item.kind === "label" && item.missing_text === null);
    const boxes = q('[data-testid="permit-text"]');
    expect(boxes).toHaveLength(labels.length);
    boxes.forEach((box, index) => {
      const item = labels[index];
      const head = box.querySelector("b")?.textContent ?? "";
      if (item.drug_name) expect(head).toContain(item.drug_name);
      if (item.section) expect(head).toContain(item.section);
      expect(head.includes("허가사항 원문")).toBe(item.dataset_key === "prmsn"); // 허가정보 인용에만
      for (const quote of box.querySelectorAll("q")) expect(item.rows.some((row) => Object.values(row).includes(quote.textContent))).toBe(true); // ⑧ 원문 글자 일치
    });
    // PRD-10 ⑧: 허가사항 설명 한 줄은 같은 문장이 한 번만
    const help = texts(q('[data-testid="label-help"]'));
    expect(new Set(help).size).toBe(help.length);
  });

  it("미확보 묶음: 구역마다 권고 박스 1개가 위에 있고 목록에 미확보 항목이 모두 있으며 '없음·안전' 암시가 없다(PRD-11 §8 ⑤⑪, FE-02-05 A)", () => {
    const { q } = draw(response);
    for (const box of q('[data-testid="missing-box"]')) {
      expect(box.querySelector('[data-testid="missing-text"]')?.textContent ?? "").not.toBe("");
      expect(box.querySelector('[data-testid="pharmacist-advice"]')).toBeNull(); // 항목마다 권고를 되풀이하지 않는다
      expect(box.closest("details, [data-state='closed'], [hidden]")).toBeNull();
      expect(box.textContent ?? "").not.toMatch(/상호작용(이)? 없|금기가 없|안전해요|안전합니다/);
      expect(box.textContent ?? "").not.toContain("삐!");
    }
    const groups = q('[data-testid="missing-group"]');
    // 묶음 안의 미확보 항목을 모두 합치면 응답의 미확보 항목(사유 원문·허가사항 구역)과 같다
    const inGroups = groups.flatMap((group) => [...group.querySelectorAll('[data-testid="missing-box"]')]);
    expect(inGroups).toHaveLength(response.detail.filter((item) => item.missing_text !== null && item.kind !== "identify").length);
    for (const group of groups) {
      const advice = group.querySelectorAll('[data-testid="pharmacist-advice"]');
      if (response.pharmacist_advice.length > 0) {
        expect(advice).toHaveLength(1); // 구역마다 권고 박스 1개
        expect(group.firstElementChild).toBe(advice[0]); // 목록 위
        expect(group.closest("details, [data-state='closed'], [hidden]")).toBeNull();
      }
    }
    // 구역마다 묶음은 하나만 있다
    for (const section of q('[data-testid="evidence-section"]')) expect(section.querySelectorAll('[data-testid="missing-group"]').length).toBeLessThanOrEqual(1);
    // 미확보 항목이 있으면 접히지 않는 고정 안내에도 권고 한 줄이 있다(서버가 fixed_notice에 싣는다)
    if (response.detail.some((item) => item.missing_text !== null)) {
      expect(response.pharmacist_advice.length).toBeGreaterThan(0);
      expect(response.fixed_notice.length).toBeGreaterThanOrEqual(2);
    }
  });

  it("출처 표: 기관은 한 번씩, 대그룹에 `삐약`이 없고, 행마다 날짜 줄이 있다(PRD-12 §9 ①②⑤, PRD-14 §6 ④, PRD-11 §8 ③)", () => {
    const { q } = draw(response);
    const publishers = texts(q('[data-testid="t-detail"] [data-testid="source-publisher"]'));
    expect(new Set(publishers).size).toBe(publishers.length);
    for (const publisher of publishers) expect(publisher).not.toMatch(/삐약|PPiyak/);
    const rows = q('[data-testid="t-detail"] [data-testid="source-row"]');
    expect(rows).toHaveLength(response.citations.length); // 1출처 = 1행
    for (const row of rows) {
      expect(row.closest('[data-testid="source-group"]')).not.toBeNull(); // 자료는 기관 묶음 아래
      expect(row.querySelectorAll('[data-testid="date-lines"] li').length).toBeGreaterThan(0);
    }
  });

  it("배지 줄: 등급 없는 종류의 배지에 '등급'이 없고, 모든 배지에 종류 글자가 있으며, 출처 표지가 배지 줄에 섞이지 않는다(PRD-09 §7.5 ②⑦, PRD-15 §7 ⑥⑧)", () => {
    const { q } = draw(response);
    for (const badge of q('[data-testid="status-badge"]')) {
      const kind = badge.getAttribute("data-kind");
      const label = badge.textContent ?? "";
      if (kind !== "pregnancy") expect(label).not.toContain("등급");
      expect(label.replace(/삐!/g, "").trim().length).toBeGreaterThan(0); // 색만으로 구분하지 않는다(G15)
      expect(badge.querySelector("svg, img")).toBeNull();
    }
    for (const status of q('[data-testid="line-status"]')) expect(status.querySelector('[data-testid="source-tag"]')).toBeNull();
    // 기대값 갱신(2026-11-24, FE-17 U-30 사용자 지시 (a)(b)(c)): 배지 글자는 받은 글자 그대로이되 출처 꼬리만 다른 같은 배지는 하나(`… (파일, 성분 API)`)이고,
    // 행 순서는 쌍 줄이 맨 위·같은 약 줄은 한 행이다. 그 밖의 재조합·재정렬은 없다(행 안 배지 순서는 받은 순서)
    const expected = resultRows(response.findings).flatMap(({ main, siblings }) => [
      ...new Set([main, ...siblings].flatMap(({ finding }) => mergeSourceBadges(finding.badges).map((badge) => badge.text))),
    ]);
    const shown = texts(q('[data-testid="t-result"] [data-testid="status-badge"]'));
    expect(shown).toEqual(expected);
    // 보이는 배지 글자는 받은 배지 글자이거나, 받은 배지들의 꼬리 앞 글자 + 받은 꼬리들을 이은 것이다(새 낱말 없음)
    const received = new Set(response.findings.flatMap((finding) => finding.badges.map((badge) => badge.text)));
    for (const label of shown) {
      if (received.has(label)) continue;
      const match = /^(.*\S) \(([^()]+)\)$/.exec(label);
      expect(match, label).not.toBeNull();
      for (const tail of match![2].split(", ")) expect(received.has(`${match![1]} (${tail})`), label).toBe(true);
    }
    // 받은 배지는 하나도 빠지지 않는다(합친 배지 안에 들었거나 그대로 보인다)
    const covered = q('[data-testid="t-result"] [data-testid="status-badge"]').flatMap((badge) => {
      const label = badge.textContent ?? "";
      const match = /^(.*\S) \(([^()]+)\)$/.exec(label);
      return [label, ...(match ? match[2].split(", ").map((tail) => `${match[1]} (${tail})`) : [])];
    });
    for (const label of received) expect(covered, label).toContain(label);
  });

  it("약을 찾지 못한 줄: 약 이름 박스에 입력한 이름이 있고 '금기 없음·안전' 암시가 없다(PRD-14 §6 ①②⑧)", () => {
    const { q } = draw(response);
    const lookups = response.findings.filter((finding) => finding.input_name !== null);
    const pairs = q('[data-testid="t-detail"] [data-testid="lookup-pairs"]');
    // 기대값 갱신(2026-11-24, FE-17 U-26-6): 보이는 것이 같은 줄(같은 약 이름·상태·문장)은 근거 상세에서 한 박스로 묶인다. 박스 수는 묶은 뒤의 수다(줄마다 박스가 있는지는 아래에서 그대로 본다)
    const distinct = groupJudgments(lookups.map((finding) => ({ finding, item: null }))).reduce((sum, group) => sum + group.boxes.length, 0);
    expect(pairs.length).toBeGreaterThanOrEqual(distinct);
    lookups.forEach((finding) => {
      const box = pairs.find((el) => (el.querySelector("dd")?.textContent ?? "") === finding.input_name);
      expect(box, finding.input_name ?? "").toBeDefined();
      // 찾아본 곳에는 자료만(건수와 함께), 재검색은 곳 목록 밖의 한 줄
      expect(box!.querySelectorAll('[data-slot="searched"]')).toHaveLength(finding.searched.length);
      const retried = box!.querySelector('[data-slot="retried"]');
      if (finding.retried_line) expect(retried?.closest("dl")).toBeNull();
      const boxText = box!.closest('[data-testid="judgment-box"]')?.textContent ?? "";
      // 이유·재검색·다음 행동은 박스 안에서 한 번씩만 보인다(줄과 표에 두 번 나오지 않는다, PRD-12-04)
      for (const once of [finding.why, finding.next, finding.retried_line]) if (once) expect(boxText.split(once).length - 1, once).toBe(1);
      expect(boxText).not.toMatch(/금기가 없|금기 없음|안전해요|안전합니다/);
      // '안전'이라는 글자는 "안전하다는 뜻이 아니"라는 부정 문장 안에서만 나온다
      expect(boxText.replace(/안전하다는 뜻(은|이)? 아니/g, "").replace(/한국의약품안전관리원/g, "")).not.toContain("안전"); // 기관 이름의 글자는 뺀다
    });
  });
});

describe("PRD-14 미식별 결과의 진입 글자와 혼합 질문", () => {
  it("진입 버튼: 약을 찾지 못한 결과에서만 `· 찾아본 곳`이 붙고, 본 글자는 둘뿐이다(FE-02 §2 PRD-14 조건)", () => {
    for (const mode of ["sheet", "panel"] as const) {
      const lookup = render(<EvidenceEntryButton mode={mode} onClick={() => {}} lookup />);
      expect(lookup.getByTestId("evidence-entry").textContent).toBe(`${evidenceCopy.ENTRY_LABELS[mode]} · 찾아본 곳`);
      lookup.unmount();
      const plain = render(<EvidenceEntryButton mode={mode} onClick={() => {}} />);
      expect(plain.getByTestId("evidence-entry").textContent).toBe(evidenceCopy.ENTRY_LABELS[mode]);
      expect(plain.getByTestId("evidence-entry").textContent).not.toContain("성분코드"); // 미식별이 아니어도 덧붙임 없음
      plain.unmount();
    }
    expect(Object.values(evidenceCopy.ENTRY_LABELS)).toEqual(["근거 상세 보기", "근거 상세 열기"]);
  });

  it("하나는 찾고 하나는 못 찾은 질문: 찾은 약은 `찾음` + 성분 이름 한 줄이고 '금기 목록에 없음' 문구가 없다(PRD-14 §6 ⑦)", () => {
    const response = fixtures.unidentifiedMixedResponse;
    const { q } = draw(response);
    const lines = q('[data-testid="t-result"] [data-testid="product-line"]');
    expect(lines.map((line) => line.getAttribute("data-bucket"))).toEqual(["unconfirmed", "identified"]);
    const identified = lines[1];
    expect(identified.querySelector('[data-testid="line-text"]')?.textContent).toBe(PHRASES.IDENTIFIED_LINE);
    expect(identified.querySelector('[data-slot="sub-line"]')?.textContent).toBe(response.findings[1].sub_line);
    expect(identified.textContent ?? "").not.toContain("목록에 없음");
    expect(identified.querySelector('[data-testid="status-badge"]')).toBeNull();
    // 못 찾은 약 줄에는 입력한 이름이 그대로 제목이다
    expect(lines[0].querySelector('[data-testid="line-title"]')?.textContent).toBe(response.findings[0].input_name);
    // 결과 카드 아래에 `이름 다시 입력`이 있다
    expect(q('[data-testid="retry-name"]')).toHaveLength(1);
  });
});

describe("PRD-15-03 등급 정의 미확보(사유 OUT_OF_SCOPE)와 PRD-09 §7.3 M등급 정의 블록", () => {
  it("OUT_OF_SCOPE: 블록마다 그 사유의 상수 문구와 약사 권고만 있고, 접힘 블록·조항 출처 줄이 없다", () => {
    const response = fixtures.gradeDefsOutOfScopeResponse;
    const { q } = draw(response);
    const missing = q('[data-testid="grade-def-missing"]');
    expect(missing).toHaveLength(1);
    expect(texts([...missing[0].querySelectorAll(":scope > p")])).toEqual(["2", "1"].map((grade) => GRADE_DEF_MISSING_OUT_OF_SCOPE.replace("{grade}", grade)));
    expect(missing[0].querySelector('[data-testid="pharmacist-advice"]')?.textContent).toBe(PHRASES.GRADE_DEF_PHARMACIST_ADVICE);
    expect(q('[data-testid="grade-def-item"]')).toHaveLength(0);
    expect(q('[data-slot="grade-def-source"]')).toHaveLength(0);
    expect(q('[data-testid="grade-def"] blockquote')).toHaveLength(0);
    // 등급 불일치 응답의 두 등급 블록이 모두 있다(한쪽만 빈 ISSUE-011 상태가 아니다)
    expect(response.grade_defs.map((def) => def.grade).sort()).toEqual(["1", "2"]);
    expect(response.grade_defs.every((def) => def.missing_reason === "OUT_OF_SCOPE" && def.text === null && def.source === null)).toBe(true);
  });

  it("두 사유의 문구가 서로 다르다(사유에 맞는 문구가 온다)", () => {
    expect(fixtures.gradeDefsResponse.grade_def_missing[0]).not.toBe(fixtures.gradeDefsOutOfScopeResponse.grade_def_missing[1]);
  });

  it("M등급: 블록 제목은 '임부금기 M등급이란?'이고 원문·출처 줄(판·표·쪽)은 받은 글자 그대로다. 등급을 1·2로 고르지 않는다", () => {
    const response = fixtures.pregnancyMDefResponse;
    const { q, getByRole } = draw(response);
    const [def] = response.grade_defs;
    const trigger = getByRole("button", { name: "임부금기 M등급이란?" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    trigger.click();
    return Promise.resolve().then(() => {
      expect(q('[data-testid="grade-def-item"]').map((el) => el.getAttribute("data-grade"))).toEqual(["M"]);
      expect(texts(q('[data-testid="t-result"] [data-testid="status-badge"]'))).toEqual([PHRASES.BADGE_PREGNANCY_M]);
      expect(def.source).toContain("건강보험심사평가원 「기능과 역할」");
      expect(def.source).toMatch(/판 .*쪽/);
    });
  });
});
