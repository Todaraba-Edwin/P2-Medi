"use client";

import { useState } from "react";
import { Mascot } from "@/components/Mascot";
import { FAMILY_PROFILE_MAX } from "@/lib/api/account";
import type { Profile } from "@/lib/api/account";
import { canAddFamily, canAddSelf, familyProfiles, hasHealthConsent, useAccountStore } from "@/stores/account";
import {
  ADD_SELF_LABEL,
  AGE_BAND_LABELS,
  DELETE_LABEL,
  DELETE_PROFILE_BODY,
  EDIT_LABEL,
  FAMILY_FULL_NOTE,
  HEALTH_CONSENT_REQUIRED_FALLBACK,
  LOGOUT_LABEL,
  PREGNANCY_LABEL,
  PREGNANCY_LABELS,
  PROFILES_DESCRIPTION,
  PROFILES_EMPTY,
  PROFILES_TITLE,
  RELATION_LABELS,
  REVIEW_CONSENT_LABEL,
  WITHDRAW_CONFIRM_BODY,
  WITHDRAW_CONFIRM_LABEL,
  WITHDRAW_CONFIRM_TITLE,
  WITHDRAW_LABEL,
  addFamilyLabel,
  deleteProfileConfirm,
  deleteProfileLabel,
  editProfileLabel,
  medicationCount,
  profileName,
} from "./copy";
import { ConfirmDialog, EmergencyEntrySlot, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, TEXT_BUTTON, useAccountModal } from "./parts";

/** 프로필 한 줄 요약. 건강 정보(임신 여부·복용 약)는 건강 정보 동의가 있을 때만 보인다 */
export function profileSummary(profile: Profile, healthConsent: boolean): string {
  const parts = [RELATION_LABELS[profile.relation]];
  if (profile.age_band) parts.push(AGE_BAND_LABELS[profile.age_band]);
  if (healthConsent && profile.pregnancy_status !== null && profile.pregnancy_status !== "unknown") parts.push(`${PREGNANCY_LABEL} ${PREGNANCY_LABELS[profile.pregnancy_status]}`);
  if (healthConsent && profile.medications.length > 0) parts.push(medicationCount(profile.medications.length));
  return parts.join(" · ");
}

/** 건강 정보 동의가 없을 때의 이유 한 줄. 서버는 이 문구를 주지 않으므로(계약에 없다) 화면 글자(초안)를 쓴다 */
export function useHealthConsentNotice(): string {
  return HEALTH_CONSENT_REQUIRED_FALLBACK;
}

/**
 * 프로필 목록(S10 3·5단계): 본인 + 가족 최대 3명의 추가·수정·삭제, 동의 다시 보기, 로그아웃, 탈퇴.
 * 가족이 3명이면 추가 버튼이 비활성이다(4번째 추가 불가). 본인 프로필에는 삭제 버튼이 없다(서버가 409 `SELF_REQUIRED`로 막는다. 계정을 지우려면 탈퇴).
 */
export function ProfileList() {
  const { store, hideMascot } = useAccountModal();
  const profiles = useAccountStore((state) => state.profiles, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const healthConsent = hasHealthConsent(me);
  const healthNotice = useHealthConsentNotice();
  const [deleting, setDeleting] = useState<Profile | null>(null);
  const [withdrawing, setWithdrawing] = useState(false);
  const familyCount = familyProfiles(profiles).length;
  const { editProfile, go, logout, removeProfile, withdraw } = store.getState();

  return (
    <StepBody data-testid="profile-list">
      <StepTitle>{PROFILES_TITLE}</StepTitle>
      <p className="m-0 text-sm leading-5 text-ink-2">{PROFILES_DESCRIPTION}</p>
      {!healthConsent && (
        <p data-testid="health-consent-notice" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-xs leading-[17px] text-ink-2">
          {healthNotice}
        </p>
      )}
      {profiles.length === 0 ? (
        <p className="m-0 text-sm text-mute">{PROFILES_EMPTY}</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {profiles.map((profile) => (
            <li key={profile.profile_id} data-testid="profile-item" data-relation={profile.relation} className="flex flex-wrap items-center gap-2 rounded-2xl border border-line px-3 py-2">
              {/* 프로필 기본 이미지: 병아리 얼굴(FE-06-01, 위험 정보와 무관한 자리) */}
              {!hideMascot && <Mascot variant="face" size={36} />}
              <div className="min-w-0 flex-1 basis-32">
                <b className="block truncate text-sm">{profileName(profile)}</b>
                <span className="block text-xs leading-[17px] text-mute">{profileSummary(profile, healthConsent)}</span>
              </div>
              <div className="flex flex-none gap-1">
                <button type="button" aria-label={editProfileLabel(profileName(profile))} onClick={() => editProfile({ profileId: profile.profile_id, self: profile.relation === "self" })} className={TEXT_BUTTON}>
                  {EDIT_LABEL}
                </button>
                {profile.relation !== "self" && (
                  <button type="button" aria-label={deleteProfileLabel(profileName(profile))} onClick={() => setDeleting(profile)} className={TEXT_BUTTON}>
                    {DELETE_LABEL}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <FailureLine failure={failure} />
      <div className="flex flex-wrap gap-2">
        {canAddSelf(profiles) && (
          <button type="button" data-testid="add-self" onClick={() => editProfile({ profileId: null, self: true })} className={PRIMARY_BUTTON}>
            {ADD_SELF_LABEL}
          </button>
        )}
        <button type="button" data-testid="add-family" disabled={!canAddFamily(profiles)} onClick={() => editProfile({ profileId: null, self: false })} className={SECONDARY_BUTTON}>
          {addFamilyLabel(familyCount, FAMILY_PROFILE_MAX)}
        </button>
      </div>
      {!canAddFamily(profiles) && (
        <p data-testid="family-full" className="m-0 text-xs leading-[17px] text-mute">
          {FAMILY_FULL_NOTE}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-1">
        <button type="button" onClick={() => go("consent")} className={TEXT_BUTTON}>
          {REVIEW_CONSENT_LABEL}
        </button>
        <button type="button" disabled={pending} onClick={() => void logout()} className={TEXT_BUTTON}>
          {LOGOUT_LABEL}
        </button>
        <button type="button" data-testid="withdraw" onClick={() => setWithdrawing(true)} className="min-h-11 rounded-full px-3 text-sm font-bold text-red-ink">
          {WITHDRAW_LABEL}
        </button>
      </div>
      <EmergencyEntrySlot />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={deleting ? deleteProfileConfirm(profileName(deleting)) : ""}
        body={DELETE_PROFILE_BODY}
        confirmLabel={DELETE_LABEL}
        pending={pending}
        onConfirm={() => {
          if (!deleting) return;
          void removeProfile(deleting.profile_id).then(() => setDeleting(null));
        }}
      />
      <ConfirmDialog
        open={withdrawing}
        onOpenChange={setWithdrawing}
        title={WITHDRAW_CONFIRM_TITLE}
        body={WITHDRAW_CONFIRM_BODY}
        confirmLabel={WITHDRAW_CONFIRM_LABEL}
        pending={pending}
        onConfirm={() => void withdraw().then((ok) => !ok && setWithdrawing(false))}
      />
    </StepBody>
  );
}
