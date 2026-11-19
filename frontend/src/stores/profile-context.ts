// 고른 프로필("누가 먹나요")을 대화 묶음(`ConversationContext`)의 나이·임신 칸으로 바꾸는 한 곳(FE-04 할 일 5).
// `/chat`은 프로필을 읽지 않으므로(설계 11장) 화면이 값만 옮겨 싣는다. 복용 중인 약(입력 원문)은 확인된 약이 아니라 `confirmed_drugs`에 싣지 않는다.
import type { AgeBand, Profile } from "@/lib/api/account";
import type { AgeRange, ConversationContext } from "./conversation-context";

/**
 * 연령대 → 요청 `context.age` 구간. 설계 문서 `P2-doc/PJ2-계정-프로필-데이터.md` 4.8절 표 그대로다(11구간, BE-11-07 A).
 * `upper`는 만 나이 정수의 포함 상한이고, `y65_plus`의 150은 `/chat` 나이 상한(`request.py` `AGE_MAX_YEARS`)이다.
 * 경계 값은 설계 문서에서 아직 "가정"이다(연령금기 기준 분포 확인 전).
 */
export const AGE_BAND_RANGE: Readonly<Record<AgeBand, AgeRange>> = {
  m0_2: { lower: 0, upper: 2, unit: "개월" },
  m3_5: { lower: 3, upper: 5, unit: "개월" },
  m6_11: { lower: 6, upper: 11, unit: "개월" },
  y1: { lower: 1, upper: 1, unit: "세" },
  y2: { lower: 2, upper: 2, unit: "세" },
  y3_5: { lower: 3, upper: 5, unit: "세" },
  y6_11: { lower: 6, upper: 11, unit: "세" },
  y12_14: { lower: 12, upper: 14, unit: "세" },
  y15_18: { lower: 15, upper: 18, unit: "세" },
  y19_64: { lower: 19, upper: 64, unit: "세" },
  y65_plus: { lower: 65, upper: 150, unit: "세" },
};

export type ProfileContext = Pick<ConversationContext, "age" | "pregnant">;

export const emptyProfileContext: ProfileContext = { age: null, pregnant: null };

/**
 * 프로필을 고르지 않았으면 두 칸 모두 null이다.
 * 임신 여부는 건강 정보라 건강 정보 동의가 있을 때만 싣는다(동의가 없으면 저장돼 있던 값이 있어도 보내지 않는다).
 * `pregnant` → true, `not_pregnant` → false, `unknown`·null → null(설계 문서 11장 표).
 */
export function profileToContext(profile: Profile | null, healthConsent: boolean): ProfileContext {
  if (!profile) return emptyProfileContext;
  return {
    age: profile.age_band ? AGE_BAND_RANGE[profile.age_band] : null,
    pregnant: !healthConsent || profile.pregnancy_status === null || profile.pregnancy_status === "unknown" ? null : profile.pregnancy_status === "pregnant",
  };
}
