"use client";

import { useState } from "react";
import { FAMILY_PROFILE_MAX } from "@/lib/api/account";
import type { Profile } from "@/lib/api/account";
import { accountUnavailable, canAddFamily, canAddSelf, familyProfiles, hasHealthConsent, useAccountStore } from "@/stores/account";
import { closeAccountModalToQuestion } from "./AccountModal";
import {
  ADD_SELF_LABEL,
  AGE_BAND_LABELS,
  DELETE_LABEL,
  DELETE_PROFILE_BODY,
  EDIT_LABEL,
  ERROR_NOT_IMPLEMENTED,
  FAMILY_FULL_NOTE,
  GO_ASK_LABEL,
  HEALTH_CONSENT_REQUIRED_FALLBACK,
  LOGOUT_LABEL,
  PREGNANCY_LABEL,
  PREGNANCY_LABELS,
  PROFILES_DESCRIPTION,
  PROFILES_EMPTY,
  PROFILE_SAVED_NOTICE,
  PROFILES_TITLE,
  RELATION_LABELS,
  REVIEW_CONSENT_LABEL,
  SEX_LABELS,
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
import { ProfileAvatar } from "./ProfileAvatar";
import { ConfirmDialog, DANGER_TEXT_BUTTON, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, TEXT_BUTTON, useAccountModal } from "./parts";

/** 프로필 한 줄 요약. 성별(선택)은 건강 정보가 아니라 동의와 상관없이 보이고, 건강 정보(임신 여부·복용 약)는 건강 정보 동의가 있을 때만 보인다 */
export function profileSummary(profile: Profile, healthConsent: boolean): string {
  const parts = [RELATION_LABELS[profile.relation]];
  if (profile.age_band) parts.push(AGE_BAND_LABELS[profile.age_band]);
  if (profile.sex) parts.push(SEX_LABELS[profile.sex]);
  if (healthConsent && profile.pregnancy_status !== null && profile.pregnancy_status !== "unknown") parts.push(`${PREGNANCY_LABEL} ${PREGNANCY_LABELS[profile.pregnancy_status]}`);
  if (healthConsent && profile.medications.length > 0) parts.push(medicationCount(profile.medications.length));
  return parts.join(" · ");
}

/** 건강 정보 동의가 없을 때의 이유 한 줄. 서버는 이 문구를 주지 않으므로(계약에 없다) 화면 글자를 쓴다 */
export function useHealthConsentNotice(): string {
  return HEALTH_CONSENT_REQUIRED_FALLBACK;
}

/**
 * 프로필 목록(S10 3·5단계): 본인 + 가족 최대 3명의 추가·수정·삭제, 동의 다시 보기, 로그아웃, 탈퇴.
 * 가족이 3명이면 추가 버튼이 비활성이다(4번째 추가 불가). 본인 프로필에는 삭제 버튼이 없다(서버가 409 `SELF_REQUIRED`로 막는다. 계정을 지우려면 탈퇴).
 * 로그인은 했지만 계정 서버가 아직 답하지 못하면(501 미설정·503 장애, `me`가 null) 준비 중 안내와 로그아웃만 보인다:
 * 눌러도 실패할 추가·동의·탈퇴 버튼은 그리지 않는다(BE-11-23 A).
 */
export function ProfileList() {
  const { store, hideMascot } = useAccountModal();
  const profiles = useAccountStore((state) => state.profiles, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const notice = useAccountStore((state) => state.notice, store);
  const healthConsent = hasHealthConsent(me);
  const unavailable = useAccountStore(accountUnavailable, store);
  const healthNotice = useHealthConsentNotice();
  const [deleting, setDeleting] = useState<Profile | null>(null);
  const [withdrawing, setWithdrawing] = useState(false);
  const familyCount = familyProfiles(profiles).length;
  const { editProfile, go, logout, removeProfile, withdraw } = store.getState();

  return (
    <StepBody data-testid="profile-list">
      <StepTitle>{PROFILES_TITLE}</StepTitle>
      <p className="m-0 text-sm leading-5 text-ink-2">{PROFILES_DESCRIPTION}</p>
      {/* 저장 완료 안내(FE-04-15 A·FE-04-26 A, 문구 승인 2026-11-22): 저장 직후 한 번, 보조기기가 바로 읽는다(`role="status"`). 초점은 제목에 있고 다음 행동 `질문하러 가기`가 옆에 있다.
          마스코트·응급·금기 문구는 두지 않는다. 다른 단계로 옮기거나 닫으면 스토어가 지운다 */}
      {notice === "profile-saved" && (
        <div role="status" data-testid="profile-saved-notice" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl bg-bg-soft px-3 py-2">
          <p className="m-0 min-w-0 flex-1 basis-40 text-sm leading-5 font-semibold text-ink [word-break:keep-all]">{PROFILE_SAVED_NOTICE}</p>
          <button type="button" data-testid="go-ask" onClick={() => closeAccountModalToQuestion(store)} className={PRIMARY_BUTTON}>
            {GO_ASK_LABEL}
          </button>
        </div>
      )}
      {unavailable && !failure && (
        <p role="status" data-testid="account-unavailable" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-sm leading-5 text-ink-2 [word-break:keep-all]">
          {ERROR_NOT_IMPLEMENTED}
        </p>
      )}
      {!unavailable && !healthConsent && (
        <p data-testid="health-consent-notice" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-xs leading-[17px] text-ink-2">
          {healthNotice}
        </p>
      )}
      {unavailable ? null : profiles.length === 0 ? (
        <p className="m-0 text-sm text-mute">{PROFILES_EMPTY}</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {profiles.map((profile) => (
            <li key={profile.profile_id} data-testid="profile-item" data-relation={profile.relation} className="flex flex-wrap items-center gap-2 rounded-2xl border border-line px-3 py-2">
              {/* 프로필 이미지: 프로필 색 원 + 병아리 얼굴(FE-06-01, 위험 정보와 무관한 자리, 2026-11-23 8색 배경). 119 안내 중에는 색 원만 */}
              <ProfileAvatar color={profile.avatar_color} size={36} face={!hideMascot} />
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
      {!unavailable && (
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
      )}
      {!unavailable && !canAddFamily(profiles) && (
        <p data-testid="family-full" className="m-0 text-xs leading-[17px] text-mute">
          {FAMILY_FULL_NOTE}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-1">
        {!unavailable && (
          <button type="button" onClick={() => go("consent")} className={TEXT_BUTTON}>
            {REVIEW_CONSENT_LABEL}
          </button>
        )}
        <button type="button" disabled={pending} onClick={() => void logout()} className={TEXT_BUTTON}>
          {LOGOUT_LABEL}
        </button>
        {!unavailable && (
          <button type="button" data-testid="withdraw" onClick={() => setWithdrawing(true)} className={DANGER_TEXT_BUTTON}>
            {WITHDRAW_LABEL}
          </button>
        )}
      </div>
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
