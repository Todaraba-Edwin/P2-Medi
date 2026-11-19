// 고른 프로필("누가 먹나요")을 대화 묶음(`ConversationContext`)의 나이·임신 칸으로 바꾸는 한 곳(FE-04 할 일 5).
// 서버는 아직 프로필을 모르므로 값 전달만 한다. 복용 중인 약(입력 원문)은 확인된 약이 아니라 `confirmed_drugs`에 싣지 않는다.
import type { AgeBand, Profile } from "@/lib/api/account";
import type { AgeRange, ConversationContext } from "./conversation-context";

/**
 * 연령대 → 요청 `context.age` 구간(가정). 경계는 `account.ts` 머리 주석의 `age_band` 정의와 같다.
 * `senior`의 위 끝(120)은 "위가 열린 구간"을 나타내려고 둔 값이며 서버 계약이 정해지면 맞춘다.
 */
export const AGE_BAND_RANGE: Readonly<Record<AgeBand, AgeRange>> = {
  infant: { lower: 0, upper: 23, unit: "개월" },
  child: { lower: 2, upper: 11, unit: "세" },
  teen: { lower: 12, upper: 18, unit: "세" },
  adult: { lower: 19, upper: 64, unit: "세" },
  senior: { lower: 65, upper: 120, unit: "세" },
};

export type ProfileContext = Pick<ConversationContext, "age" | "pregnant">;

export const emptyProfileContext: ProfileContext = { age: null, pregnant: null };

/**
 * 프로필을 고르지 않았으면 두 칸 모두 null이다.
 * 임신 여부는 건강 정보라 건강 정보 동의가 있을 때만 싣는다(동의가 없으면 저장돼 있던 값이 있어도 보내지 않는다). `unknown`은 null이다.
 */
export function profileToContext(profile: Profile | null, healthConsent: boolean): ProfileContext {
  if (!profile) return emptyProfileContext;
  return {
    age: profile.age_band ? AGE_BAND_RANGE[profile.age_band] : null,
    pregnant: !healthConsent || profile.pregnancy_status === "unknown" ? null : profile.pregnancy_status === "yes",
  };
}
