// 계정·약관 목의 합성 자료(FE-04). **실제 약관·방침이 아니다.** 실제 문서는 DB에서 버전 관리하고 API가 내려 준다.
// 화면 코드는 이 파일을 가져다 쓰지 않는다(mock·시험 전용). 모양은 백엔드 `LegalDocumentOut`과 같다(`src/lib/api/account.ts`).
import { DRUG_CANDIDATES_MAX, DRUG_MATCH_SIMILAR } from "@/lib/api/account";
import type { DrugCandidate, DrugSearchResult, LegalDoc, LegalDocType } from "@/lib/api/account";

/** 합성 본문 지문 자리(64자리 16진수 모양만 맞춘 값. 실제 해시가 아니다) */
const fakeSha = (digit: string) => digit.repeat(64);
const EFFECTIVE_AT = "2026-11-18T00:00:00Z";

export const MOCK_LEGAL_DOCS: Readonly<Record<LegalDocType, LegalDoc>> = {
  terms: {
    doc_type: "terms",
    version: 1,
    title: "이용약관 (합성 목 문서)",
    effective_at: EFFECTIVE_AT,
    required: true,
    requires_reconsent: false,
    legal_review: "not_reviewed",
    body_sha256: fakeSha("1"),
    body_md: [
      "## 제1조 (목적)",
      "이 문서는 화면 개발용 **합성 목 문서**이며 실제 약관이 아닙니다.",
      "",
      "## 제2조 (서비스의 성격)",
      "- 공공데이터 기반 정보 제공이며 진단·처방이 아닙니다.",
      "- 복용 여부와 용량은 정해 주지 않습니다.",
      "",
      "## 제3조 (계정)",
      "1. 계정 없이(게스트) 질문할 수 있습니다.",
      "2. 계정은 프로필 저장에만 씁니다.",
    ].join("\n"),
  },
  // 고지 문서: 동의 대상이 아니다(체크 없음). 외부 AI 전송 안내는 이 문서의 한 절이다
  privacy_policy: {
    doc_type: "privacy_policy",
    version: 1,
    title: "개인정보 처리방침 (합성 목 문서)",
    effective_at: EFFECTIVE_AT,
    required: false,
    requires_reconsent: false,
    legal_review: "not_reviewed",
    body_sha256: fakeSha("2"),
    // 시드 v2(`backend/app/db/seed_legal_v2.sql`)와 같은 모양: 머리 인용(`> …`) + 파이프 표. 화면 표 렌더(Markdown.tsx) e2e용이며 내용은 합성이다
    body_md: [
      "> 초안·법률 검토 전입니다(합성 목 문서).",
      "",
      "## 처리하는 항목",
      "| 항목 | 목적 | 언제 |",
      "|---|---|---|",
      "| 로그인 식별자: 소셜 로그인 공급자가 넘기는 계정 식별자(합성) | 회원 식별, 중복 가입 방지 | 계정을 만들 때 |",
      "| 프로필 이름(별명), 관계, 연령대 | 질문할 때 연령대를 자동으로 채워 **연령금기** 확인 | 프로필을 저장할 때 |",
      "",
      "## 외부 AI 전송",
      "- 질문과 고른 프로필의 연령대·임신 여부",
      "",
      "이 문서는 화면 개발용 **합성 목 문서**입니다.",
    ].join("\n"),
  },
  privacy_consent: {
    doc_type: "privacy_consent",
    version: 1,
    title: "개인정보 수집·이용 동의 (합성 목 문서)",
    effective_at: EFFECTIVE_AT,
    required: true,
    requires_reconsent: false,
    legal_review: "not_reviewed",
    body_sha256: fakeSha("3"),
    body_md: [
      "## 수집 항목",
      "- 로그인 식별자, 프로필 이름(별명), 관계, 연령대",
      "",
      "## 저장하지 않는 것",
      "질문과 대화 내용은 저장하지 않습니다.",
      "",
      "이 문서는 화면 개발용 **합성 목 문서**입니다.",
    ].join("\n"),
  },
  sensitive_consent: {
    doc_type: "sensitive_consent",
    version: 1,
    title: "민감정보(건강 정보) 수집·이용 동의 (합성 목 문서)",
    effective_at: EFFECTIVE_AT,
    required: false,
    requires_reconsent: false,
    legal_review: "not_reviewed",
    body_sha256: fakeSha("4"),
    body_md: [
      "## 수집 항목",
      "- 임신 여부",
      "- 복용 중인 약(입력한 글자 그대로)",
      "",
      "동의하지 않아도 서비스를 쓸 수 있습니다. 이 문서는 화면 개발용 **합성 목 문서**입니다.",
    ].join("\n"),
  },
  // 만 14세 이상 확인(PRD-17-12 A): 화면은 별도 필수 체크로 그린다(본문 카드 없음). 제목·본문은 백엔드 시드(`seed_legal_age14.sql`)와 같은 문구(2026-11-20 사용자 확인 "그대로")
  age_14: {
    doc_type: "age_14",
    version: 1,
    title: "만 14세 이상입니다.",
    effective_at: EFFECTIVE_AT,
    required: true,
    requires_reconsent: false,
    legal_review: "not_reviewed",
    body_sha256: fakeSha("5"),
    body_md: "만 14세 이상입니다.",
  },
};

/** 이 글자가 이메일에 있으면 로그인·가입이 실패한다(개발 미리보기용 합성 규칙. 로그인 경로는 백엔드에 없는 목이다) */
export const MOCK_LOGIN_FAIL_MARK = "mock-fail";
export const MOCK_SIGNUP_TAKEN_MARK = "mock-taken";
/** 이 글자가 이메일에 있으면 이미 동의·프로필을 마친 사용자로 로그인한다 */
export const MOCK_ONBOARDED_MARK = "mock-onboarded";
/**
 * 목 소셜 로그인 사용자의 표시 이름(합성, FE-04-28 B). 카카오 닉네임만 본인 프로필 이름 칸의 **초기값**으로 쓰고
 * 구글 이름은 받아도 쓰지 않는다(화면 규칙은 `lib/api/account.ts`의 `fetchSelfNameDefault`). 어디에도 저장하지 않는다
 */
export const MOCK_KAKAO_NICKNAME = "삐약이";
export const MOCK_GOOGLE_NAME = "mock-google-name";

// ---------------------------------------------------------------- 약 이름 사전(합성, `POST /api/drugs/search` 목. FE-04-13 A)
// 실제 사전(DB의 제품 47,773·성분 1,581)이 아니라 화면 개발용 합성 이름이다. 제품명은 채팅 목(`responses.ts`의 되묻기 후보)과 같은 이름·번호를 쓴다.
interface MockDictEntry {
  name: string;
  item_seq: string | null;
  entp_name: string | null;
  prescription: string | null;
  matched_by: DrugCandidate["matched_by"];
  /** 이 글자로 찾으면 "비슷한 이름"(`bm25`) 후보로 낸다(오타 흉내) */
  similar?: string[];
}

const product = (name: string, item_seq: string, entp_name: string, prescription: "일반" | "전문", similar?: string[]): MockDictEntry => ({ name, item_seq, entp_name, prescription, matched_by: "product_name", similar });
const ingredient = (name: string): MockDictEntry => ({ name, item_seq: null, entp_name: null, prescription: null, matched_by: "ingredient_name" });

/** 제품 → 성분 순서(백엔드 `lookup_name` 계약). `다목정`은 후보 상한(10)을 보는 12개짜리 묶음이다 */
export const MOCK_DRUG_DICT: readonly MockDictEntry[] = [
  product("가나다정 100밀리그램", "200000001", "합성제약(주)", "일반", ["가나다졍"]),
  product("가나다정 500밀리그램", "200000002", "합성제약(주)", "전문"),
  product("가나다시럽", "200000003", "가상약품(주)", "일반"),
  product("가나다시럽 키즈", "200000004", "가상약품(주)", "일반"),
  product("가나다시럽 플러스", "200000005", "합성제약(주)", "전문"),
  product("라마바캡슐 10밀리그램", "200000006", "합성제약(주)", "일반"),
  product("라마바캡슐 20밀리그램", "200000007", "가상약품(주)", "전문"),
  ...Array.from({ length: 12 }, (_, index) => product(`다목정 ${index + 1}밀리그램`, `2000001${String(index + 1).padStart(2, "0")}`, "합성제약(주)", "일반")),
  ingredient("가나다마이신"),
  ingredient("라마바펜"),
  ingredient("사아자페린"),
];
export const MOCK_DRUG_DICT_VERSION = "mock-dict-2026-11-20";
/** 서버가 사전에서 확인한 품목 번호만 저장한다(`dict_item_seq_checker`): 목도 같은 규칙으로 사전에 없는 번호를 버린다 */
export const MOCK_DRUG_ITEM_SEQS: ReadonlySet<string> = new Set(MOCK_DRUG_DICT.flatMap((entry) => (entry.item_seq ? [entry.item_seq] : [])));
/** 검색어에 이 글자가 있으면 그 오류로 답한다(화면의 실패 처리 확인용 합성 규칙. 실제 서버에는 없다) */
export const MOCK_DRUG_SEARCH_ERRORS: ReadonlyArray<readonly [mark: string, status: number, code: string]> = [
  ["mock-401", 401, "AUTH_REQUIRED"],
  ["mock-422", 422, "INVALID_REQUEST"],
  ["mock-503", 503, "DICT_UNAVAILABLE"],
];
/** 검색어에 이 글자가 있으면 응답을 `MOCK_DRUG_SEARCH_SLOW_MS`만큼 늦춘다(FE-04-24 A "검색 중에는 저장 막힘" 확인용 합성 규칙. 실제 서버에는 없다) */
export const MOCK_DRUG_SEARCH_SLOW_MARK = "mock-slow";
export const MOCK_DRUG_SEARCH_SLOW_MS = 1500;

const normalize = (text: string) => text.normalize("NFC").toLowerCase().replace(/\s+/g, "");

/**
 * 합성 검색: 정규화한 이름의 일치 → 앞부분 → 포함 → 비슷한 이름 순서로 제품을 먼저, 성분을 나중에 낸다. 최대 10개.
 * `needs_confirmation`은 후보가 여럿이거나 비슷한 이름이 섞였을 때 true, 후보가 없으면 false(백엔드 계약과 같다)
 */
export function searchMockDrugs(q: string): DrugSearchResult {
  const key = normalize(q);
  const matchType = (entry: MockDictEntry): string | null => {
    const name = normalize(entry.name);
    if (name === key) return "exact";
    if (name.startsWith(key)) return "prefix";
    if (name.includes(key)) return "contains";
    if (entry.similar?.some((alias) => normalize(alias) === key)) return DRUG_MATCH_SIMILAR;
    return null;
  };
  const candidates: DrugCandidate[] = [];
  for (const matched_by of ["product_name", "ingredient_name"] as const) {
    for (const entry of MOCK_DRUG_DICT) {
      if (entry.matched_by !== matched_by) continue;
      const match_type = matchType(entry);
      if (!match_type || candidates.length >= DRUG_CANDIDATES_MAX) continue;
      candidates.push({ name: entry.name, item_seq: entry.item_seq, entp_name: entry.entp_name, prescription: entry.prescription, matched_by, match_type });
    }
  }
  return {
    candidates,
    needs_confirmation: candidates.length > 1 || candidates.some((candidate) => candidate.match_type === DRUG_MATCH_SIMILAR),
    dict_version: MOCK_DRUG_DICT_VERSION,
  };
}
