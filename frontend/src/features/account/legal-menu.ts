import { fetchLegalDocIfPublished } from "@/lib/api/account";
import type { LegalMenuDoc } from "@/lib/api/account";

/**
 * 약관·정책 열람 목록(2026-11-23 사용자 요구: 로그인·게스트 모두 설정에서 현재 적용 문서를 다시 읽을 수 있어야 한다. 게스트용과 회원용 문서는 다르다).
 * 상태별로 **어떤 문서 종류를 보일지만** 여기 둔다. 제목·본문·버전은 서버 `GET /legal/{doc_type}` 값을 그대로 그린다(프런트에 문구를 두지 않는다).
 * - `audience`: `guest`(게스트에게만) · `member`(로그인 사용자에게만) · `all`(둘 다)
 * - 서버가 그 종류를 모르거나(422) 게시본이 없으면(404) 그 항목은 **아예 그리지 않는다**(`fetchLegalDocIfPublished`가 null).
 *   게스트용 종류(`terms_guest`)는 백엔드 `DocType`에 2026-11-23 추가됐다(열람 전용, 동의 대상 아님). 게시본이 없으면(404) 숨긴다.
 *   처리방침은 게스트용을 따로 두지 않고 공통 `privacy_policy`를 게스트·회원이 함께 본다(PRD-17-23 A, 2026-11-23)
 * - 순서는 이 배열 순서다. 회원 목록은 동의 화면과 같은 순서(`LEGAL_DOC_TYPES`)
 */
export type LegalAudience = "guest" | "member" | "all";

export interface LegalMenuEntry {
  readonly docType: string;
  readonly audience: LegalAudience;
}

export const LEGAL_MENU: readonly LegalMenuEntry[] = [
  // 게스트용(서버에 아직 없음 → 지금은 숨김. 서버가 게시하면 보인다)
  { docType: "terms_guest", audience: "guest" },
  // 공통: 이용약관·처리방침(외부 AI 전송 안내가 처리방침에 있다. 게스트의 질문도 외부 AI로 가므로 게스트에게도 보인다)
  { docType: "terms", audience: "all" },
  { docType: "privacy_policy", audience: "all" },
  // 회원용: 프로필 저장과 건강 정보에 대한 동의서, 만 14세 확인(게스트는 저장이 없어 해당 없음)
  { docType: "privacy_consent", audience: "member" },
  { docType: "sensitive_consent", audience: "member" },
  { docType: "age_14", audience: "member" },
];

/** 지금 상태(게스트/회원)에 보일 문서 종류(순서 유지) */
export function legalMenuDocTypes(member: boolean): string[] {
  const audience: LegalAudience = member ? "member" : "guest";
  return LEGAL_MENU.filter((entry) => entry.audience === "all" || entry.audience === audience).map((entry) => entry.docType);
}

/**
 * 상태별 목록의 문서를 모두 받는다. 없는 문서(404·422)는 빠지고, 하나라도 다른 이유로 실패하면 던진다(화면은 "불러오지 못했어요" + 다시 불러오기).
 * 요청은 병렬이고 응답 순서는 목록 순서를 지킨다
 */
export async function fetchLegalMenu(member: boolean, fetchOne: (docType: string) => Promise<LegalMenuDoc | null> = fetchLegalDocIfPublished): Promise<LegalMenuDoc[]> {
  const docs = await Promise.all(legalMenuDocTypes(member).map(fetchOne));
  return docs.filter((doc): doc is LegalMenuDoc => doc !== null);
}
