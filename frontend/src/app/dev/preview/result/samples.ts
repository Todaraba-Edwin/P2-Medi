// 개발 미리보기·화면 시험용 표본. 모두 합성 fixture(src/mocks/fixtures)에서 가져오거나 그 조각을 다시 짠 것이다.
// 새 문구를 짓지 않는다: 글자는 fixture(백엔드 상수 원문)의 값이고, 제품명·성분명만 가상 이름이다.
import { ChatResponseSchema } from "@/lib/api";
import type { ChatResponse } from "@/lib/api";
import { PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";

export interface ResultSample {
  id: string;
  /** 미리보기 목록에 보이는 이름(개발 전용) */
  title: string;
  /** 대응하는 디자인 보드(2026-11-12 after5 스냅샷). 없으면 null */
  board: string | null;
  basis?: string;
  response: ChatResponse;
}

const check = (response: ChatResponse): ChatResponse => ChatResponseSchema.parse(structuredClone(response));
const pairLine = fixtures.foundResponse.findings[0];
const mismatchLine = fixtures.gradeMismatchResponse.findings[0];
const pregnancyLine = fixtures.pregnancyResponse.findings[0];
const notListedLine = fixtures.notListedResponse.findings[0];

/** 병용 + 등급 불일치: 한 줄에 배지 3개(PRD-15 §7 화면 시험용). 배지 순서는 병용 → 임부(파일 → 성분 API) */
const threeBadges = check({
  ...fixtures.gradeMismatchResponse,
  findings: [{ ...mismatchLine, badges: [...pairLine.badges, ...mismatchLine.badges] }],
});

/** 긴 제목: 띄어쓰기에서만 줄바꿈하는지 보는 표본 */
const LONG_A = "가나다라마바사아자차정 500밀리그램";
const LONG_B = "카타파하가나다라마바캡슐 250밀리그램";
const longTitle = check({
  ...fixtures.pairAndPregnancyResponse,
  findings: [
    { ...pairLine, drug: `${LONG_A} × ${LONG_B}`, drugs: [LONG_A, LONG_B] },
    { ...mismatchLine, drug: LONG_B, drugs: [LONG_B], badges: [...pairLine.badges, ...mismatchLine.badges] },
  ],
});

/** 성분 6개: 5개 이상이면 원인·중복 먼저 + 외 N개 */
const manyIngredients = check({
  ...fixtures.pregnancyResponse,
  findings: [
    {
      ...pregnancyLine,
      ingredients: [
        { code: null, name: "하나성분", contra_kinds: [], dup: false, state_labels: [], code_missing_text: null },
        { code: null, name: "두울성분", contra_kinds: ["pregnancy"], dup: false, state_labels: [PHRASES.INGR_STATE_CAUSE], code_missing_text: null },
        { code: null, name: "세엣성분", contra_kinds: [], dup: false, state_labels: [], code_missing_text: null },
        { code: null, name: "네엣성분", contra_kinds: [], dup: true, state_labels: [PHRASES.INGR_STATE_DUP], code_missing_text: null },
        { code: null, name: "다섯성분", contra_kinds: [], dup: false, state_labels: [], code_missing_text: null },
        { code: null, name: "여섯성분", contra_kinds: [], dup: false, state_labels: [], code_missing_text: null },
      ],
    },
  ],
});

/** 금기 발견 줄과 "목록에 없음" 줄이 함께 */
const mixed = check({
  ...fixtures.pregnancyResponse,
  findings: [pregnancyLine, { ...notListedLine, evidence_id: "ev-preg-2" }],
});

export const RESULT_SAMPLES: ResultSample[] = [
  { id: "found", title: "병용금기 발견(쌍 줄)", board: "Result-Found", response: fixtures.foundResponse },
  { id: "pregnancy", title: "임부금기 발견(등급 배지 1개)", board: null, basis: "임신 기준", response: fixtures.pregnancyResponse },
  { id: "mixed", title: "발견 + 목록에 없음", board: "Result-Mixed", basis: "임신 기준", response: mixed },
  { id: "both", title: "병용 + 임부(쌍 줄과 제품 줄)", board: "Result-Both", basis: "임신 기준", response: fixtures.pairAndPregnancyResponse },
  { id: "grade-mismatch", title: "등급 불일치(파일·성분 API 배지 둘)", board: null, basis: "임신 기준", response: fixtures.gradeMismatchResponse },
  { id: "three-badges", title: "병용 + 등급 불일치(배지 셋)", board: null, basis: "임신 기준", response: threeBadges },
  { id: "m-grade", title: "임부금기 M등급", board: "Result-MGrade", basis: "임신 기준", response: fixtures.pregnancyMResponse },
  { id: "age", title: "연령금기(나이 기준 값 보조줄)", board: "Result-AgeContra", response: fixtures.ageFoundResponse },
  { id: "not-listed", title: "목록에 없음", board: null, basis: "임신 기준", response: fixtures.notListedResponse },
  { id: "unidentified", title: "약을 찾지 못함", board: "Result-NoEvidence", response: fixtures.unidentifiedResponse },
  { id: "missing", title: "근거 원문 미확보(카드는 발견 줄)", board: null, response: fixtures.missingEvidenceResponse },
  { id: "limit", title: "상한 도달(상단 배너)", board: "Result-Limit", response: fixtures.limitResponse },
  { id: "emergency", title: "응급 뒤 결과(119 자리는 FE-IMPL-05)", board: "Result-EmergencyResult", response: fixtures.emergencyResponse },
  { id: "clarify", title: "되묻기(후보 카드)", board: "Result-Ask", response: fixtures.clarifyResponse },
  { id: "refuse", title: "거절(요약만)", board: "Result-Refuse", response: fixtures.refuseResponse },
  { id: "long-title", title: "긴 제목 + 배지 셋", board: null, response: longTitle },
  { id: "many-ingredients", title: "성분 6개(외 N개)", board: null, basis: "임신 기준", response: manyIngredients },
];

/** fixture가 없어 그리지 못한 보드와 이유(개발 메모) */
export const BOARDS_WITHOUT_SAMPLE: { board: string; reason: string }[] = [
  { board: "Result-FallbackNone", reason: "요약 문구 상수(FALLBACK_NONE_*)가 fixture에 없음" },
  { board: "Result-FallbackSome", reason: "요약 문구 상수(FALLBACK_SOME_CONFIRMED)가 승인 전" },
  { board: "Result-Infant", reason: "보드의 상태 글자가 응답 계약 v1에 없음" },
  { board: "Result-NoEvidence6c", reason: "쌍을 확인하지 못한 줄의 문구(PAIR_NOT_CHECKED)가 승인 전" },
  { board: "Result-Emergency-360", reason: "응급 뒤 결과 표본과 같음(119 자리는 FE-IMPL-05)" },
  { board: "Photo-Source-FromResult", reason: "사진 입력(FE-05) 범위" },
];
