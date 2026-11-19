// 계정·약관 목의 합성 자료(FE-04). **실제 약관·방침이 아니다.** 실제 문서는 DB에서 버전 관리하고 API가 내려 준다.
// 화면 코드는 이 파일을 가져다 쓰지 않는다(mock·시험 전용). 문구는 목이 "서버 값"으로 내려 주는 자리 표시다.
import type { LegalDoc, LegalDocType } from "@/lib/api/account";

type LegalDocInput = Omit<LegalDoc, "declined_notice"> & { declined_notice?: string | null };

export const MOCK_LEGAL_DOCS: Readonly<Record<LegalDocType, LegalDocInput>> = {
  terms: {
    doc_type: "terms",
    version: "mock-2026-11-18",
    title: "이용약관 (합성 목 문서)",
    effective_at: "2026-11-18",
    required: true,
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
  privacy: {
    doc_type: "privacy",
    version: "mock-2026-11-18",
    title: "개인정보 수집·이용 동의 (합성 목 문서)",
    effective_at: "2026-11-18",
    required: true,
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
  sensitive_health: {
    doc_type: "sensitive_health",
    version: "mock-2026-11-18",
    title: "민감정보(건강 정보) 수집·이용 동의 (합성 목 문서)",
    effective_at: "2026-11-18",
    required: false,
    declined_notice: "건강 정보 동의를 하지 않아 임신 여부와 복용 중인 약은 입력할 수 없어요. (합성 목 문구)",
    body_md: [
      "## 수집 항목",
      "- 임신 여부",
      "- 복용 중인 약(입력한 글자 그대로)",
      "",
      "동의하지 않아도 서비스를 쓸 수 있습니다. 이 문서는 화면 개발용 **합성 목 문서**입니다.",
    ].join("\n"),
  },
  external_ai: {
    doc_type: "external_ai",
    version: "mock-2026-11-18",
    title: "외부 AI 전송 안내 (합성 목 문서)",
    effective_at: "2026-11-18",
    required: false,
    body_md: ["## 보내는 항목", "- 고른 프로필의 연령대와 임신 여부", "", "이 문서는 화면 개발용 **합성 목 문서**입니다."].join("\n"),
  },
};

/** 이 글자가 이메일에 있으면 로그인·가입이 실패한다(개발 미리보기용 합성 규칙) */
export const MOCK_LOGIN_FAIL_MARK = "mock-fail";
export const MOCK_SIGNUP_TAKEN_MARK = "mock-taken";
/** 이 글자가 이메일에 있으면 이미 동의·프로필을 마친 사용자로 로그인한다 */
export const MOCK_ONBOARDED_MARK = "mock-onboarded";
