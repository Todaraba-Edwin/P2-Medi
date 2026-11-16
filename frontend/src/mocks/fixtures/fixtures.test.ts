import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ChatEventSchema, ChatResponseSchema } from "@/lib/api/schemas";
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
    expect(router).toContain(`'{t.raw}'${phrases.CLARIFY_TAIL}`);
    expect(provenance).toContain(`"contra_pair": "${phrases.DATASET_CONTRA_PAIR}"`);
    expect(provenance).toContain(`"pregnancy": "${phrases.DATASET_PREGNANCY}"`);
    expect(provenance).toContain(`"age": "${phrases.DATASET_AGE}"`);
    expect(provenance).toContain(`"dur_ingr": "${phrases.DATASET_DUR_INGR}"`);
    expect(provenance).toContain(`"prmsn": "${phrases.DATASET_PRMSN}"`);
    expect(provenance).toContain(`"mfds": "${phrases.PUBLISHER_MFDS}"`);
    expect(fixedPhrases).toContain(`BADGE_SOURCE_TAIL = {"FILE": "${phrases.BADGE_SOURCE_TAIL.FILE}", "API_DIRECT": "${phrases.BADGE_SOURCE_TAIL.API_DIRECT}"}`);
    expect(pyConst(loaders, "SRC_KIDS")).toBe(phrases.PUBLISHER_KIDS);
    expect(provenance).toContain('"kids": SRC_KIDS');
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
