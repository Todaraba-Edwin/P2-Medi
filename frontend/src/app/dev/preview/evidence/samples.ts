// 개발 미리보기·화면 시험용 표본. 합성 fixture(src/mocks/fixtures)와 그 조각을 다시 짠 것이다.
// 새 문구를 짓지 않는다: 문구는 fixture(백엔드 상수 원문)의 값이고, 제품명·성분명·허가사항 원문 문장은 가상 값이다.
import { ChatResponseSchema } from "@/lib/api";
import type { ChatResponse } from "@/lib/api";
import * as fixtures from "@/mocks/fixtures/responses";

export interface EvidenceSample {
  id: string;
  /** 미리보기 목록에 보이는 이름(개발 전용) */
  title: string;
  /** 대응하는 디자인 보드(2026-11-12 after5 스냅샷). 없으면 null */
  board: string | null;
  response: ChatResponse;
}

const check = (response: ChatResponse): ChatResponse => ChatResponseSchema.parse(structuredClone(response));

// 허가정보 자료의 이름·기관은 fixture의 값을 그대로 가져온다
const permitSource = fixtures.missingEvidenceResponse.detail[1];
const permitCitation = {
  publisher: permitSource.publisher!,
  dataset: permitSource.dataset!,
  dates: [{ label: "조회" as const, value: "2026-11-12" }],
  source_kind: "API_DIRECT" as const,
  evidence_ids: ["ev-permit-1", "ev-permit-2"],
  notice_nos: [],
  edition: null,
  pages: [],
};
const permitItem = (id: string, drug: string, section: string, text: string) => ({
  ...permitSource,
  evidence_id: id,
  status: "FOUND",
  source_kind: "API_DIRECT" as const,
  dates: [{ label: "조회" as const, value: "2026-11-12" }],
  drug_name: drug,
  section,
  rows: [{ row_key: `${id}#0`, text }],
  drugs: [drug],
  missing_reason: null,
  missing_text: null,
});

/** 허가사항 원문 인용(정상 경로): 주의사항과 용법·용량. 용법·용량도 표가 아니라 원문 인용 그대로다 */
const permit = check({
  ...fixtures.foundResponse,
  detail: [
    ...fixtures.foundResponse.detail,
    permitItem("ev-permit-1", "가나다정", "사용상 주의사항", "(합성 원문) 다른 약을 복용하고 있는 사람은 이 약을 복용하기 전에 의사 또는 약사와 상의하십시오."),
    permitItem(
      "ev-permit-2",
      "라마바캡슐",
      "용법·용량",
      "(합성 원문) 성인: 1회 가나 단위, 1일 다 회 복용한다.\n소아: 연령과 체중에 따라 의사의 지시에 따른다. 복용 간격은 라 시간 이상으로 한다.",
    ),
  ],
  citations: [permitCitation, ...fixtures.foundResponse.citations],
});

/** 출처 표: 판·쪽·발간일·여러 고시일이 있는 행(서버가 지금은 비워 보내는 칸을 채운 예) */
const richSources = check({
  ...fixtures.gradeMismatchResponse,
  citations: [
    {
      ...fixtures.gradeMismatchResponse.citations[0],
      dates: [
        { label: "고시일", value: "2017-11-06" },
        { label: "조회", value: "2026-11-12" },
      ],
    },
    { ...permitCitation, evidence_ids: [] },
    {
      ...fixtures.gradeMismatchResponse.citations[1],
      dates: [
        { label: "고시일", value: "2024-01-02" },
        { label: "고시일", value: "2025-03-02" },
        { label: "발간일", value: "2026-06" },
        { label: "기준일", value: "2026-07-21" },
      ],
      notice_nos: ["20250002", "20240001"],
      edition: "2026년판",
      pages: ["12쪽", "13쪽"],
    },
  ],
});

export const EVIDENCE_SAMPLES: EvidenceSample[] = [
  { id: "found", title: "병용금기 발견", board: "Detail-Combo", response: fixtures.foundResponse },
  { id: "emergency", title: "응급 + 결과", board: "Result-EmergencyResult", response: fixtures.emergencyResponse },
  { id: "both", title: "병용 + 임부", board: "Detail-Both", response: fixtures.pairAndPregnancyResponse },
  { id: "grade-mismatch", title: "등급 불일치", board: "Detail-GradeDiff", response: fixtures.gradeMismatchResponse },
  { id: "grade-defs", title: "등급 정의 블록(원문 + 미확보 FETCH_FAIL)", board: null, response: fixtures.gradeDefsResponse },
  { id: "grade-defs-out-of-scope", title: "등급 정의 미확보(OUT_OF_SCOPE, 두 블록)", board: null, response: fixtures.gradeDefsOutOfScopeResponse },
  { id: "m-grade-def", title: "임부금기 M등급 + 정의 블록(심평원 설명, 합성)", board: "Detail-MGrade", response: fixtures.pregnancyMDefResponse },
  { id: "m-grade", title: "임부금기 M등급", board: "Detail-MGrade", response: fixtures.pregnancyMResponse },
  { id: "age", title: "연령금기(나이 기준 값)", board: "Detail-Infant", response: fixtures.ageFoundResponse },
  { id: "not-listed", title: "목록에 없음", board: null, response: fixtures.notListedResponse },
  { id: "missing", title: "근거 원문 미확보(관련 문장을 찾지 못함) + 약사 확인 권고", board: "Detail-Missing3", response: fixtures.missingEvidenceResponse },
  { id: "unidentified", title: "근거 없음(약을 찾지 못함)", board: "Detail-NoEvidence", response: fixtures.unidentifiedResponse },
  { id: "limit", title: "상한 도달(확인한 데까지)", board: "Detail-Limit", response: fixtures.limitResponse },
  { id: "permit", title: "허가사항 원문 인용(정상 경로)", board: "Detail-RxPermit", response: permit },
  { id: "rich-sources", title: "출처 표: 고시 번호·판·쪽·발간일", board: null, response: richSources },
];

/** fixture가 없어 그리지 못한 것과 이유(개발 메모) */
export const EVIDENCE_WITHOUT_SAMPLE: { name: string; reason: string }[] = [
  { name: "미확보 원인 3종 중 나머지 둘(항목 없음, 불러오지 못함)과 범위 밖", reason: "그 문구가 fixture에 없음(관련 문장을 찾지 못함 하나만 있음)" },
  { name: "폴백(Result-FallbackNone·FallbackSome)", reason: "요약 문구 상수가 fixture에 없음. 상한 도달 표본으로 대신 봄" },
  { name: "등급 정의 블록(원문 인용·미확보 문구)", reason: "응답 계약 v1에 정의 원문·제목 칸이 없고 미확보 문구도 fixture에 없음. 부품 시험으로만 확인" },
  { name: "허가사항 한 줄 설명, 전문의약품 안내 줄(Detail-RxPermit)", reason: "응답에 실려 오지 않음(문구 대기 AG-08-16 포함)" },
  { name: "Photo-Source-FromResult", reason: "사진 입력(FE-05) 범위" },
];
