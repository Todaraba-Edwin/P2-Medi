"use client";

import { useId, useState } from "react";
import { XIcon } from "lucide-react";
import { AGE_BANDS, MEDICATIONS_MAX, MEDICATION_NAME_MAX_CHARS, PREGNANCY_STATUSES, PROFILE_LABEL_MAX_CHARS, RELATIONS } from "@/lib/api/account";
import type { AgeBand, MedicationInput, PregnancyStatus, ProfileDraft, Relation } from "@/lib/api/account";
import { hasHealthConsent, useAccountStore } from "@/stores/account";
import {
  AGE_BAND_LABEL,
  AGE_BAND_LABELS,
  CANCEL_LABEL,
  ERROR_NAME_EMPTY,
  MEDICATIONS_LABEL,
  MEDICATION_ADD_LABEL,
  MEDICATION_HINT,
  NOT_SELECTED,
  PREGNANCY_LABEL,
  PREGNANCY_LABELS,
  PROFILE_FORM_EDIT_TITLE,
  PROFILE_FORM_NEW_TITLE,
  PROFILE_NAME_HINT,
  PROFILE_NAME_LABEL,
  RELATION_LABEL,
  RELATION_LABELS,
  SAVE_LABEL,
  removeMedicationLabel,
} from "./copy";
import { EmergencyEntrySlot, FIELD_CLASS, FailureLine, ICON_BUTTON, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, useAccountModal } from "./parts";
import { useHealthConsentNotice } from "./ProfileList";

const FAMILY_RELATIONS = RELATIONS.filter((relation) => relation !== "self");
const LABEL_CLASS = "text-xs font-bold text-ink-2";

/**
 * 프로필 추가·수정 폼. 관계·연령대·임신 여부·복용 중인 약(선택, 적은 글자 그대로).
 * 건강 정보(임신 여부·복용 약)는 건강 정보 동의가 있을 때만 입력·저장할 수 있다: 동의가 없으면 두 칸이 비활성이고 이유 한 줄이 보이며,
 * 저장할 때도 건강 정보 칸을 요청에 싣지 않는다(실으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다).
 * 약은 적은 글자 그대로(`input_text`) 보내고 품목 번호는 붙이지 않는다. 적은 값은 이 부품의 메모리에만 있다(브라우저 저장소에 두지 않는다).
 */
export function ProfileForm() {
  const { store } = useAccountModal();
  const target = useAccountStore((state) => state.form, store);
  const existing = useAccountStore((state) => state.profiles.find((profile) => profile.profile_id === state.form?.profileId) ?? null, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const healthConsent = hasHealthConsent(me);
  const healthNotice = useHealthConsentNotice();
  const id = useId();
  const self = target?.self ?? false;

  const [label, setLabel] = useState(existing?.label ?? "");
  const [relation, setRelation] = useState<Relation>(existing?.relation ?? (self ? "self" : "child"));
  const [ageBand, setAgeBand] = useState<AgeBand | "">(existing?.age_band ?? "");
  const [pregnancy, setPregnancy] = useState<PregnancyStatus>(existing?.pregnancy_status ?? "unknown");
  const [medications, setMedications] = useState<MedicationInput[]>(() => (existing?.medications ?? []).map((item) => ({ input_text: item.input_text, item_seq: item.item_seq })));
  const [medicationInput, setMedicationInput] = useState("");
  const [nameMissing, setNameMissing] = useState(false);

  const addMedication = () => {
    const name = medicationInput.trim();
    if (!name || medications.length >= MEDICATIONS_MAX) return;
    if (!medications.some((item) => item.input_text === name)) setMedications([...medications, { input_text: name, item_seq: null }]);
    setMedicationInput("");
  };

  const save = () => {
    const name = label.trim();
    if (!name) return setNameMissing(true);
    setNameMissing(false);
    const draft: ProfileDraft = {
      relation: self ? "self" : relation,
      label: name,
      age_band: ageBand === "" ? null : ageBand,
      // 건강 정보 동의가 없으면 건강 정보 칸을 보내지 않는다
      health: healthConsent ? { pregnancy_status: pregnancy, medications } : null,
    };
    void store.getState().saveProfile(draft);
  };

  return (
    <StepBody data-testid="profile-form">
      <StepTitle>{existing ? PROFILE_FORM_EDIT_TITLE : PROFILE_FORM_NEW_TITLE}</StepTitle>
      <form
        noValidate
        className="flex flex-col gap-2.5"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <label htmlFor={`${id}-name`} className={LABEL_CLASS}>
          {PROFILE_NAME_LABEL}
        </label>
        <input
          id={`${id}-name`}
          type="text"
          autoComplete="off"
          maxLength={PROFILE_LABEL_MAX_CHARS}
          value={label}
          aria-invalid={nameMissing}
          aria-describedby={`${id}-name-hint`}
          onChange={(event) => setLabel(event.target.value)}
          className={FIELD_CLASS}
        />
        <p id={`${id}-name-hint`} role={nameMissing ? "alert" : undefined} className={nameMissing ? "m-0 text-sm font-semibold text-red-ink" : "m-0 text-xs text-mute"}>
          {nameMissing ? ERROR_NAME_EMPTY : PROFILE_NAME_HINT}
        </p>

        <label htmlFor={`${id}-relation`} className={LABEL_CLASS}>
          {RELATION_LABEL}
        </label>
        {/* 본인 프로필은 관계가 고정이다 */}
        <select id={`${id}-relation`} value={self ? "self" : relation} disabled={self} onChange={(event) => setRelation(event.target.value as Relation)} className={FIELD_CLASS}>
          {(self ? (["self"] as const) : FAMILY_RELATIONS).map((value) => (
            <option key={value} value={value}>
              {RELATION_LABELS[value]}
            </option>
          ))}
        </select>

        <label htmlFor={`${id}-age`} className={LABEL_CLASS}>
          {AGE_BAND_LABEL}
        </label>
        <select id={`${id}-age`} value={ageBand} onChange={(event) => setAgeBand(event.target.value as AgeBand | "")} className={FIELD_CLASS}>
          <option value="">{NOT_SELECTED}</option>
          {AGE_BANDS.map((value) => (
            <option key={value} value={value}>
              {AGE_BAND_LABELS[value]}
            </option>
          ))}
        </select>

        {/* 건강 정보 묶음: 동의가 없으면 통째로 비활성 */}
        <fieldset data-testid="health-fields" disabled={!healthConsent} aria-describedby={healthConsent ? undefined : `${id}-health`} className="m-0 flex min-w-0 flex-col gap-2.5 border-0 p-0">
          {!healthConsent && (
            <p id={`${id}-health`} data-testid="health-consent-notice" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-xs leading-[17px] text-ink-2">
              {healthNotice}
            </p>
          )}
          <div role="radiogroup" aria-labelledby={`${id}-pregnancy`} className="flex flex-col gap-1">
            <span id={`${id}-pregnancy`} className={LABEL_CLASS}>
              {PREGNANCY_LABEL}
            </span>
            <div className="flex flex-wrap gap-x-4">
              {PREGNANCY_STATUSES.map((value) => (
                <label key={value} className={`flex min-h-11 items-center gap-2 text-sm ${healthConsent ? "cursor-pointer" : "text-faint"}`}>
                  <input type="radio" name={`${id}-pregnancy`} value={value} checked={(healthConsent ? pregnancy : "unknown") === value} onChange={() => setPregnancy(value)} className="size-5 accent-ink" />
                  {PREGNANCY_LABELS[value]}
                </label>
              ))}
            </div>
          </div>
          <label htmlFor={`${id}-medication`} className={LABEL_CLASS}>
            {MEDICATIONS_LABEL}
          </label>
          <div className="flex gap-2">
            <input
              id={`${id}-medication`}
              type="text"
              autoComplete="off"
              aria-describedby={`${id}-medication-hint`}
              maxLength={MEDICATION_NAME_MAX_CHARS}
              value={medicationInput}
              onChange={(event) => setMedicationInput(event.target.value)}
              onKeyDown={(event) => {
                // Enter는 폼을 저장하지 않고 약을 목록에 더한다. 한글 조합 중의 Enter는 넘긴다
                if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  addMedication();
                }
              }}
              className={FIELD_CLASS}
            />
            <button type="button" data-testid="medication-add" onClick={addMedication} className={`${SECONDARY_BUTTON} flex-none`}>
              {MEDICATION_ADD_LABEL}
            </button>
          </div>
          <p id={`${id}-medication-hint`} className="m-0 text-xs text-mute">
            {MEDICATION_HINT}
          </p>
          {healthConsent && medications.length > 0 && (
            <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
              {medications.map((item) => (
                <li key={item.input_text} data-testid="medication" className="flex max-w-full items-center rounded-full border border-line bg-bg-softer pl-3 text-sm">
                  <span className="min-w-0 [overflow-wrap:anywhere]">{item.input_text}</span>
                  <button
                    type="button"
                    aria-label={removeMedicationLabel(item.input_text)}
                    onClick={() => setMedications(medications.filter((other) => other.input_text !== item.input_text))}
                    className={ICON_BUTTON}
                  >
                    <XIcon className="size-4" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        <FailureLine failure={failure} />
        <div className="mt-1 flex gap-2">
          <button type="button" onClick={() => store.getState().back()} className={`${SECONDARY_BUTTON} flex-1`}>
            {CANCEL_LABEL}
          </button>
          <button type="submit" data-testid="profile-save" disabled={pending} className={`${PRIMARY_BUTTON} flex-1`}>
            {SAVE_LABEL}
          </button>
        </div>
      </form>
      <EmergencyEntrySlot />
    </StepBody>
  );
}
