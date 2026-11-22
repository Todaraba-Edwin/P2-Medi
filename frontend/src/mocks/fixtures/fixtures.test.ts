import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ChatEventSchema, ChatResponseSchema } from "@/lib/api/schemas";
import { API_FLAG_NOTES, NOTICE_API_FAIL } from "@/lib/fixed/phrases.generated";
import * as phrases from "./phrases";
import * as responses from "./responses";
import { scenarios } from "./scenarios";

// 문구 원문 대조: 백엔드 파일은 읽기만 한다.
const BACKEND = path.resolve(__dirname, "../../../../backend/app");
const fixedPhrases = readFileSync(path.join(BACKEND, "agent/fixed_phrases.py"), "utf8");
const router = readFileSync(path.join(BACKEND, "agent/router.py"), "utf8");
const provenance = readFileSync(path.join(BACKEND, "tools/provenance.py"), "utf8");
const loaders = readFileSync(path.join(BACKEND, "db/loaders.py"), "utf8");

/** `NAME = "값"` 한 줄 대입의 값 */
function pyConst(source: string, name: string): string | undefined {
  return new RegExp(`^${name}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, "m").exec(source)?.[1];
}

describe("fixture 문구는 백엔드 상수 원문과 같다", () => {
  it.each(Object.entries(phrases.PHRASES))("%s", (name, value) => {
    expect(pyConst(fixedPhrases, name)).toBe(value);
  });

  it("DISCLAIMER_PARTS·조립 규칙", () => {
    const block = /DISCLAIMER_PARTS\s*=\s*\(([\s\S]*?)\n\)/.exec(fixedPhrases)?.[1] ?? "";
    expect([...block.matchAll(/"([^"]+)"/g)].map((m) => m[1])).toEqual([...phrases.DISCLAIMER_PARTS]);
    expect(fixedPhrases).toContain('DISCLAIMER = " · ".join(DISCLAIMER_PARTS)');
    expect(fixedPhrases).toContain('FIXED_NOTICE = f"{NOT_SAFE_NOTICE} {PHARMACIST_CHECK_NOTICE}"');
  });

  it("사전 값(거절·출처 종류)과 되묻기 템플릿·출처 표 값", () => {
    expect(fixedPhrases).toContain(`"DOSAGE": "${phrases.REFUSE_DOSAGE}"`);
    expect(fixedPhrases).toContain(`"FILE": "${phrases.SOURCE_KIND_FILE}"`);
    expect(provenance).toContain(`SK_FILE: "${phrases.SOURCE_PREFIX_FILE}"`);
    expect(provenance).toContain('return f"{SOURCE_KIND_PREFIX[source_kind]} · {DATASET_LABELS[dataset_key]}"');
    expect(pyConst(fixedPhrases, "FALLBACK_SOME_DATASET_SEP")).toBe(phrases.FALLBACK_SOME_DATASET_SEP);
    // 되묻기 질문(AG-05-10): 문구는 fixed_phrases 상수이고 router는 그 상수에 약 이름만 채운다
    expect(router).toContain("return CLARIFY_MANY_CANDIDATES.format(drug=t.raw)");
    expect(router).toContain("return CLARIFY_ONE_CANDIDATE.format(drug=t.raw)");
    expect(pyConst(fixedPhrases, "CLARIFY_MANY_CANDIDATES")).toBe(`'{drug}'${phrases.CLARIFY_TAIL}`);
    expect(responses.clarifyResponse.summary).toBe(pyConst(fixedPhrases, "CLARIFY_MANY_CANDIDATES")?.replace("{drug}", "가나다"));
    expect(responses.clarifyResponse.summary?.match(/\?/g)).toHaveLength(1);
    expect(provenance).toContain(`"contra_pair": "${phrases.DATASET_CONTRA_PAIR}"`);
    expect(provenance).toContain(`"pregnancy": "${phrases.DATASET_PREGNANCY}"`);
    expect(provenance).toContain(`"age": "${phrases.DATASET_AGE}"`);
    expect(provenance).toContain(`"dur_ingr": "${phrases.DATASET_DUR_INGR}"`);
    expect(provenance).toContain(`"prmsn": "${phrases.DATASET_PRMSN}"`);
    expect(provenance).toContain(`"mfds": "${phrases.PUBLISHER_MFDS}"`);
    expect(fixedPhrases).toContain(`BADGE_SOURCE_TAIL = {"FILE": "${phrases.BADGE_SOURCE_TAIL.FILE}", "API_DIRECT": "${phrases.BADGE_SOURCE_TAIL.API_DIRECT}"}`);
    expect(pyConst(loaders, "SRC_KIDS")).toBe(phrases.PUBLISHER_KIDS);
    // 등급 정의 미확보 문구 두 사유(PRD-15-03)
    expect(fixedPhrases).toContain(`"FETCH_FAIL": "${phrases.GRADE_DEF_MISSING_FETCH_FAIL}"`);
    expect(fixedPhrases).toContain(`"OUT_OF_SCOPE": "${phrases.GRADE_DEF_MISSING_OUT_OF_SCOPE}"`);
    expect(provenance).toContain('"kids": SRC_KIDS');
    // 실시간 확인 꼬리표 노트(FE-11-10 A): FLAG_NOTES·API_REASON_NOTES 원문과 같고, 생성 상수(판별용)에도 같은 글자가 있다
    expect(provenance).toContain(`"API_FAIL": "${phrases.API_FAIL_NOTE}"`);
    expect(provenance).toContain(`API_REASON_NO_CODE: "${phrases.API_NO_CODE_NOTE}"`);
    expect(API_FLAG_NOTES).toContain(phrases.API_FAIL_NOTE);
    expect(API_FLAG_NOTES).toContain(phrases.API_NO_CODE_NOTE);
    expect(NOTICE_API_FAIL).toBe(phrases.PHRASES.NOTICE_API_FAIL);
  });
});

describe("fixture 모양", () => {
  it("진행 문구 대응은 PROGRESS_LABELS와 같다", () => {
    const block = /^PROGRESS_LABELS\s*=\s*\{([\s\S]*?)\n\}/m.exec(fixedPhrases)?.[1] ?? "";
    const pairs = [...block.matchAll(/"(\w+)":\s*(\w+)/g)].map((m) => [m[1], pyConst(fixedPhrases, m[2])]);
    expect(Object.fromEntries(pairs)).toEqual(phrases.PROGRESS_LABELS);
  });

  it.each(Object.entries(responses))("%s는 chat_response@v1 zod를 통과한다", (_name, response) => {
    expect(ChatResponseSchema.parse(structuredClone(response))).toEqual(response);
    expect(response.fixed_notice).toContain(phrases.FIXED_NOTICE);
    expect(response.disclaimer).toBe(phrases.DISCLAIMER);
  });

  it("모든 시나리오 이벤트가 zod를 통과하고 seq가 0부터 1씩 는다", () => {
    for (const scenario of Object.values(scenarios)) {
      if (scenario.kind !== "stream") continue;
      scenario.events.forEach((event, index) => {
        expect(ChatEventSchema.parse(structuredClone(event))).toEqual(event);
        expect(event.seq).toBe(index);
      });
    }
  });

  it("모든 시나리오가 서버 순서 규칙(events.py)을 지킨다", () => {
    for (const [name, scenario] of Object.entries(scenarios)) {
      if (scenario.kind !== "stream") continue;
      const types = scenario.events.map((e) => e.type);
      const answerAt = types.indexOf("answer");
      const errorAt = types.indexOf("error");
      const doneAt = types.indexOf("done");
      const answered = scenario.events.find((e) => e.type === "answer");
      expect(types.filter((t) => t === "emergency").length, name).toBeLessThanOrEqual(1);
      if (types.includes("emergency")) expect(types[0], name).toBe("emergency"); // 응급은 seq 0
      expect(answerAt >= 0 && errorAt >= 0, name).toBe(false); // answer·error는 둘 중 하나
      const settled = Math.max(answerAt, errorAt);
      if (settled >= 0) expect(types.slice(settled + 1).every((t) => t === "done"), name).toBe(true); // 그 뒤에는 done만
      if (doneAt >= 0) {
        expect(doneAt, name).toBe(types.length - 1);
        expect(settled, name).toBeGreaterThanOrEqual(0); // done은 answer 또는 error 뒤
        const done = scenario.events[doneAt];
        expect(done.type === "done" && done.end_reason, name).toBe(answered?.type === "answer" ? answered.response.end_reason : null);
      }
      if (answered?.type === "answer") expect(answered.response.emergency !== null, name).toBe(types[0] === "emergency");
      for (const e of scenario.events) if (e.type === "progress") expect(e.label, name).toBe(phrases.PROGRESS_LABELS[e.stage]);
    }
  });

  it("되묻기 후보는 CLARIFY 응답에만 있고 이름을 갖는다", () => {
    expect(responses.clarifyResponse.candidates.length).toBeGreaterThan(1);
    for (const [name, response] of Object.entries(responses)) {
      if (response.end_reason !== "CLARIFY") expect(response.candidates, name).toEqual([]);
    }
    for (const c of responses.clarifyResponse.candidates) expect(c.item_seq).toMatch(/^\d{9}$/);
  });

  it("쌍 줄은 두 약, 배지는 금기 발견 줄에만 있다", () => {
    for (const response of Object.values(responses)) {
      for (const f of response.findings) {
        if (f.target === "pair") expect(f.drugs).toHaveLength(2);
        if (f.badges.length) expect(f.bucket).toBe("found");
        for (const b of f.badges) expect(b.text.startsWith("삐!")).toBe(true);
      }
    }
  });

  it("응급 시나리오는 첫 이벤트가 emergency다", () => {
    expect(scenarios.emergency.events[0].type).toBe("emergency");
    expect(scenarios.emergencyCut.events[0].type).toBe("emergency");
  });

  it("되묻기·거절의 끝난 이유와 경로", () => {
    expect(responses.clarifyResponse).toMatchObject({ route: "AGENT", end_reason: "CLARIFY" });
    expect(responses.refuseResponse).toMatchObject({ route: "REFUSE", end_reason: "REFUSE" });
  });

  it("약사 확인 권고가 있으면 줄 순서는 권고 → 고정이다", () => {
    expect(responses.adviceFirstResponse.fixed_notice).toEqual([phrases.PHRASES.PHARMACIST_ADVICE_FIXED, phrases.FIXED_NOTICE]);
  });
});

describe("AG-08·BE-06-13~17 새 칸의 fixture(서버 규칙과 같은 모양)", () => {
  it("사전 값: 출처 종류 글자·등급 정의 미확보 문구·성분 중복 라벨·용법용량 항목 이름", () => {
    expect(provenance).toContain(
      `SOURCE_KIND_PREFIX = {SK_API_DIRECT: "${phrases.SOURCE_KIND_PREFIX.API_DIRECT}", SK_FILE: "${phrases.SOURCE_KIND_PREFIX.FILE}", SK_CORPUS_QUOTE: "${phrases.SOURCE_KIND_PREFIX.CORPUS_QUOTE}"}`,
    );
    expect(fixedPhrases).toContain(`"FETCH_FAIL": "${phrases.GRADE_DEF_MISSING_FETCH_FAIL}"`);
    expect(fixedPhrases).toContain(`"dup_ingredient": "${phrases.CAUTION_DUP_INGREDIENT}"`);
    expect(fixedPhrases).not.toContain("같은 성분 중복");
    // provenance.FLAG_NOTES["CODE_NOT_LINKED"] = "금기 목록에서 확인하지 못했지만, " + NOT_SAFE + ". 약사에게 확인하세요"
    expect(provenance).toContain('"CODE_NOT_LINKED": "금기 목록에서 확인하지 못했지만, " + NOT_SAFE + ". 약사에게 확인하세요"');
    expect(phrases.CODE_NOT_LINKED).toBe(`금기 목록에서 확인하지 못했지만, ${pyConst(provenance, "NOT_SAFE")}. 약사에게 확인하세요`);
    expect(responses.codeNotLinkedResponse.findings[0].notes).toEqual([phrases.CODE_NOT_LINKED]);
    expect(responses.ageInfoResponse.findings[1].text).toBe(phrases.CAUTION_DUP_INGREDIENT);
    const schemasPy = readFileSync(path.join(BACKEND, "api/schemas.py"), "utf8");
    expect(pyConst(schemasPy, "DOSE_SECTION")).toBe(phrases.DOSE_SECTION);
  });

  it("조사 '을(를)'은 받침으로 고른 글자만 남는다(josa.fill과 같은 규칙)", () => {
    expect(phrases.fillJosa("{drug}을(를) 찾지", "drug", "가나다정")).toBe("가나다정을 찾지");
    expect(phrases.fillJosa("{drug}을(를) 찾지", "drug", "판콜에이")).toBe("판콜에이를 찾지");
    // 예외: 이전 선택 확인 질문(`clarifyPriorResponse`)은 서버 `router._single_question`이 `josa.fill` 없이 `.format`만 해서 "을(를)"이 그대로 나간다(백엔드 정정 후보). fixture는 서버 글자 그대로다
    for (const [name, response] of Object.entries(responses)) {
      if (name === "clarifyPriorResponse") continue;
      expect(JSON.stringify(response), name).not.toContain("을(를)");
    }
  });

  it("성분 상태 글자는 contra_kinds·dup에서 서버 규칙으로 정한 값이고 순서는 병용금기 원인 → 금기 원인 → 중복이다", () => {
    expect(phrases.ingredientStateLabels(["age", "contra_pair"], true)).toEqual(["병용금기 원인", "금기 원인", "중복"]);
    expect(phrases.ingredientStateLabels([], false)).toEqual([]);
    for (const response of Object.values(responses)) {
      for (const ingredient of response.findings.flatMap((f) => f.ingredients)) {
        expect(ingredient.state_labels).toEqual(phrases.ingredientStateLabels(ingredient.contra_kinds ?? [], ingredient.dup ?? false));
        if (ingredient.code_missing_text !== null) expect(ingredient.code).toBeNull();
      }
    }
  });

  it("근거 항목: 출처 종류가 있으면 종류 글자가 있고, 한 줄 설명은 허가정보 원문 근거에만, 인용 고지는 용법용량 인용에만 있다", () => {
    for (const [name, response] of Object.entries(responses)) {
      for (const item of response.detail) {
        expect(item.source_kind_label, name).toBe(item.source_kind ? phrases.SOURCE_KIND_PREFIX[item.source_kind] : null);
        expect(item.label_help, name).toBe(item.source_kind && item.dataset_key === "prmsn" ? phrases.PHRASES.LABEL_ONE_LINE : null);
        expect(item.quote_notice, name).toBe(item.section === phrases.DOSE_SECTION && item.rows.length > 0 ? phrases.PHRASES.DOSE_QUOTE_NOTICE : null);
        if (item.easy_text_missing_line !== null) expect(item.flags, name).toContain("EASY_TEXT_MISSING");
      }
    }
    expect(responses.rxPermitResponse.detail.filter((d) => d.quote_notice !== null)).toHaveLength(1);
  });

  it("미확보 항목이 있으면 약사 확인 권고가 비지 않는다(BE-06-17)", () => {
    for (const [name, response] of Object.entries(responses)) {
      const missing =
        response.findings.some((f) => f.unresolved) ||
        response.detail.some((d) => d.missing_reason !== null) ||
        response.grade_def_missing.length > 0 ||
        response.grade_defs.some((g) => g.missing_reason !== null);
      if (missing) expect(response.pharmacist_advice.length, name).toBeGreaterThan(0);
    }
  });

  it("쌍 확인 불가 줄은 줄 글자 한 번뿐이고, 식별된 약 줄은 `찾음` + 보조줄 + 이름만 든 성분이다", () => {
    const [identified, pair] = responses.pairNoEvidenceResponse.findings;
    expect(pair).toMatchObject({ target: "pair", text: phrases.PHRASES.PAIR_NOT_CHECKED, notes: [], why: null, next: null, retried: null });
    expect(identified).toMatchObject({ bucket: "identified", text: phrases.PHRASES.IDENTIFIED_LINE });
    expect(identified.sub_line).toBe(identified.ingredients.map((i) => i.name).join(phrases.PHRASES.IDENTIFIED_SUB_SEP));
    for (const ingredient of identified.ingredients) expect(ingredient).toMatchObject({ code: null, contra_kinds: [], dup: false, state_labels: [] });
  });

  it("등급 불일치 안내는 그 근거의 notes에 한 번, 나이 안내 줄은 나이 기준 값이 있을 때만, 되묻기 안내는 후보가 있을 때만 있다", () => {
    const notes = responses.gradeMismatchResponse.detail.flatMap((d) => d.notes);
    expect(notes.filter((n) => n === phrases.PHRASES.GRADE_MISMATCH_NOTE)).toHaveLength(1);
    for (const [name, response] of Object.entries(responses)) {
      for (const f of response.findings) if (f.age_info_line !== null) expect(f.age_criteria.length, name).toBeGreaterThan(0);
      expect(response.candidates_line, name).toBe(response.candidates.length > 0 ? phrases.PHRASES.CLARIFY_PICK_LINE : null);
      expect(response.emergency === null || response.emergency.wide_text === phrases.PHRASES.EMERGENCY_119_WIDE, name).toBe(true);
    }
    expect(responses.ageInfoResponse.findings[0].age_info_line).toBe(phrases.PHRASES.AGE_INFO_LINE);
  });

  it("나이 안내 줄 fixture는 백엔드 계약(schemas.py Finding 검증기)의 규칙을 지킨다: 상수 그대로, 나이 기준 값이 있을 때만", () => {
    const schemasPy = readFileSync(path.join(BACKEND, "api/schemas.py"), "utf8");
    // 서버가 이 칸에 허용하는 값의 규칙(바뀌면 이 시험이 먼저 알린다)
    expect(schemasPy).toContain("if self.age_info_line is not None and (self.age_info_line != fp.AGE_INFO_LINE or not self.age_criteria):");
    expect(pyConst(fixedPhrases, "AGE_INFO_LINE")).toBe(phrases.PHRASES.AGE_INFO_LINE);
    const withLine = Object.values(responses).flatMap((r) => r.findings).filter((f) => f.age_info_line !== null);
    expect(withLine).toHaveLength(1);
    expect(withLine[0]).toMatchObject({ kind: "age", age_info_line: phrases.PHRASES.AGE_INFO_LINE, age_criteria: ["12세 미만", "6개월 미만"], badges: [] });
    // 나이가 있어 판정한 연령금기 줄(서버 `finalize` 출력 모양): 나이 기준 값은 있고 안내 줄은 없다
    expect(responses.ageFoundResponse.findings[0]).toMatchObject({ bucket: "found", age_criteria: ["12세 미만"], age_info_line: null });
  });

  it("등급 정의 블록: 제목은 상수, 원문과 미확보 사유는 하나만, 줄 목록 칸은 미확보 문구와 같다", () => {
    const { grade_defs: defs, grade_def_missing: lines } = responses.gradeDefsResponse;
    for (const def of defs) expect(def.title).toBe(phrases.PHRASES.GRADE_DEF_TITLE.replace("{grade}", def.grade));
    expect(lines).toEqual(defs.filter((d) => d.missing_reason !== null).map((d) => d.missing_text));
  });

  it("보정 고지(FE-02): text는 상수 TYPO_CORRECTED_LINE에 input·name을 넣은 문장 그대로이고, 되묻기 응답에는 없다", () => {
    // 서버 규칙(schemas.py NameCorrection 검증기·ChatResponse `_check`): 바뀌면 이 시험이 먼저 알린다
    const schemasPy = readFileSync(path.join(BACKEND, "api/schemas.py"), "utf8");
    expect(schemasPy).toContain("if self.text != fp.TYPO_CORRECTED_LINE.format(input=self.input, name=self.name):");
    expect(schemasPy).toContain('if self.name_corrections and self.end_reason == "CLARIFY":');
    expect(responses.typoCorrectedResponse.name_corrections).toHaveLength(1);
    expect(responses.typoCorrectedResponse.end_reason).toBe("NORMAL");
    for (const [name, response] of Object.entries(responses)) {
      if (response.end_reason === "CLARIFY") expect(response.name_corrections, name).toEqual([]);
      for (const c of response.name_corrections) {
        expect(c.text, name).toBe(phrases.PHRASES.TYPO_CORRECTED_LINE.replace("{input}", c.input).replace("{name}", c.name));
        expect(c.input, name).not.toBe(c.name);
      }
    }
    // 가짜 서버 `typo`와 같은 흐름: 진행 둘 → 답(보정 1건 + 병용금기 1건) → done
    expect(scenarios.typoCorrected.events.map((e) => e.type)).toEqual(["progress", "progress", "answer", "done"]);
  });

  it("이전 선택 확인 되묻기(AG-21-04 A): router가 상수 CLARIFY_PRIOR_PICK에 첫 후보(이전 선택)의 사전 제품명을 채우고, fixture도 같은 문장·첫 후보다", () => {
    expect(router).toContain("return CLARIFY_PRIOR_PICK.format(drug=t.options[0].name)");
    const first = responses.clarifyPriorResponse.candidates[0];
    expect(responses.clarifyPriorResponse.summary).toBe(phrases.fillPriorPick(first.name));
    expect(responses.clarifyPriorResponse.summary?.match(/\?/g)).toHaveLength(1);
    // 서버가 `.format`만 하고 `josa.fill`을 거치지 않으므로(router.py `_single_question`) "을(를)"이 그대로 온다: fixture는 서버 글자와 같다(바뀌면 이 시험이 알린다)
    expect(router).not.toMatch(/CLARIFY_PRIOR_PICK[^\n]*josa|fill\([^\n]*CLARIFY_PRIOR_PICK/);
    expect(responses.clarifyPriorResponse.summary).toContain(`'${first.name}'을(를)`);
    expect(responses.clarifyPriorResponse.end_reason).toBe("CLARIFY");
    expect(scenarios.clarifyPrior.events.map((e) => e.type)).toEqual(["progress", "answer", "done"]);
  });

  it("GROUP-01 3단계 새 칸: 고지는 상수 그대로, 요약 글자는 서버 틀 그대로, 접힘 건수는 rest 줄 수, 짝 참조는 제품 줄에만, 되묻기 응답에는 결과 칸이 없다", () => {
    const schemasPy = readFileSync(path.join(BACKEND, "api/schemas.py"), "utf8");
    // 서버 검증 규칙(바뀌면 이 시험이 먼저 알린다)
    expect(schemasPy).toContain("if self.dose_notice not in (None, fp.DOSE_NOTICE):");
    expect(schemasPy).toContain("if self.redose_notice not in (None, fp.REDOSE_NOTICE):");
    expect(schemasPy).toContain("if self.text != fp.PAIR_REF_LINE.format(n=self.count):");
    expect(schemasPy).toContain("if self.text != fp.REST_FOLD_LINE.format(n=self.count):");
    expect(responses.redoseResponse.redose_notice).toBe(phrases.PHRASES.REDOSE_NOTICE);
    const summary = responses.resultSummaryResponse.result_summary!;
    expect(summary.text).toBe(phrases.resultSummaryFound(3, [["가나다정", "라마바캡슐"]]));
    expect(summary.text).toBe("약 3개를 함께 먹을 때: 병용금기 1건(가나다정 + 라마바캡슐)");
    expect(summary.pair_only_notice).toBe(phrases.PHRASES.PAIR_ONLY_NOTICE);
    const rest = responses.resultSummaryResponse.findings.filter((f) => f.section === "rest");
    expect(responses.resultSummaryResponse.rest_fold).toEqual({ count: rest.length, text: phrases.PHRASES.REST_FOLD_LINE.replace("{n}", String(rest.length)), open_label: "펼치기", close_label: "접기" });
    for (const [name, response] of Object.entries(responses)) {
      for (const f of response.findings) {
        if (f.pair_ref !== null) {
          expect(f.target, name).toBe("product");
          expect(f.pair_ref.text, name).toBe(phrases.PHRASES.PAIR_REF_LINE.replace("{n}", String(f.pair_ref.count)));
          expect(f.badges.some((b) => b.kind === "contra_pair"), name).toBe(false); // 병용 배지 대신 짝 참조
        }
        if (f.caution_desc !== null) expect(f.caution_desc, name).toBe(phrases.PHRASES.DOSE_CAUTION_DESC);
      }
      expect(response.dose_notice === null || response.dose_notice === phrases.PHRASES.DOSE_NOTICE, name).toBe(true);
      if (response.end_reason === "CLARIFY") {
        expect(response.result_summary, name).toBeNull();
        expect(response.rest_fold, name).toBeNull();
        expect(response.dose_check, name).toBeNull();
        expect(response.dose_notice, name).toBeNull();
        expect(response.redose_notice, name).toBeNull();
      }
      if (response.result_summary !== null) expect(response.result_summary.pair_only_notice !== null, name).toBe(response.result_summary.n_drugs >= 3);
    }
  });

  it("오류 이벤트의 문구는 코드별 상수이고 항상 있다", () => {
    const expected: Record<string, string> = {
      INTERNAL_ERROR: phrases.PHRASES.ERROR_INTERNAL,
      TIMEOUT: phrases.PHRASES.ERROR_TIMEOUT,
      UPSTREAM_UNAVAILABLE: phrases.PHRASES.ERROR_UPSTREAM_UNAVAILABLE,
    };
    let seen = 0;
    for (const scenario of Object.values(scenarios)) {
      if (scenario.kind !== "stream") continue;
      for (const event of scenario.events) {
        if (event.type !== "error") continue;
        seen += 1;
        expect(event.message).toBe(expected[event.code]);
      }
    }
    expect(seen).toBeGreaterThan(0);
  });
});
