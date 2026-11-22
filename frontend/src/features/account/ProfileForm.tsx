"use client";

import { useId, useState } from "react";
import { XIcon } from "lucide-react";
import { AGE_BANDS, MEDICATIONS_MAX, PROFILE_LABEL_MAX_CHARS, RELATIONS, SEXES } from "@/lib/api/account";
import type { AgeBand, MedicationInput, PregnancyStatus, ProfileDraft, Relation, Sex } from "@/lib/api/account";
import { hasHealthConsent, useAccountStore } from "@/stores/account";
import {
  AGE_BAND_LABEL,
  AGE_BAND_LABELS,
  CANCEL_LABEL,
  DRUG_DATA_SCOPE_NOTICE,
  ERROR_NAME_EMPTY,
  MEDICATIONS_LABEL,
  MEDICATION_UNCONFIRMED_NOTE,
  MEDICATION_UNCONFIRMED_TAG,
  NOT_SELECTED,
  PREGNANCY_LABEL,
  PROFILE_FORM_EDIT_TITLE,
  PROFILE_FORM_NEW_TITLE,
  PROFILE_NAME_HINT,
  PROFILE_NAME_LABEL,
  RELATION_LABEL,
  RELATION_LABELS,
  SAVE_LABEL,
  SEX_LABEL,
  SEX_LABELS,
  removeMedicationLabel,
} from "./copy";
import { MedicationPicker } from "./MedicationPicker";
import { EmergencyEntrySlot, FIELD_CLASS, FailureLine, ICON_BUTTON, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, useAccountModal } from "./parts";
import { PregnancySelect } from "./PregnancySelect";
import { useHealthConsentNotice } from "./ProfileList";

const FAMILY_RELATIONS = RELATIONS.filter((relation) => relation !== "self");
const LABEL_CLASS = "text-xs font-bold text-ink-2";

/** 같은 약인가: 품목 번호가 있으면 번호로, 없으면 적은 글자로 본다 */
const sameMedication = (a: MedicationInput, b: MedicationInput) => (a.item_seq && b.item_seq ? a.item_seq === b.item_seq : a.input_text === b.input_text);

/** 임신 여부 칸을 그리는가(사용자 지시 2026-11-22): 성별이 **여성일 때만**. 남성·미입력(기본 "선택 안 함")은 숨긴다 */
export const showsPregnancyField = (sex: Sex | "") => sex === "female";

/**
 * 저장할 임신 여부(사용자 지시 2026-11-22): 여성이면 고른 값, 아니면(칸이 숨겨짐) `unknown`(모름, 기존 기본값)으로 정리한다.
 * 저장된 프로필이 여성이 아닌데 `pregnant`가 남아 있는 비정상 값(입력창 토글은 성별 미입력 프로필에도 저장한다, FE-11-13)은 편집 화면에서 보이지 않고 저장 때 모름으로 돌아간다
 */
export const pregnancyToSave = (sex: Sex | "", pregnancy: PregnancyStatus): PregnancyStatus => (showsPregnancyField(sex) ? pregnancy : "unknown");

/**
 * 프로필 추가·수정 폼. 관계·연령대·성별(선택)·임신 여부·복용 중인 약(선택).
 * 성별(FE-11-09 C·PRD-17-13 A)은 연령대 아래 기본 단계의 선택 칸이다: "여성 | 남성" + 선택 안 함(null). 건강 정보가 아니라 건강 정보 동의 없이도 저장되고,
 * 온보딩에서 사용자가 직접 고른다(간편 로그인 공급자 정보로 미리 채우지 않는다. 처음 열면 늘 "선택 안 함"이다). `/chat` 요청에는 싣지 않는다(S10).
 * 임신 여부(사용자 지시 2026-11-22, 작업 B)는 **성별이 여성일 때만** 나타나는 선택 버튼 "예 | 아니오 | 모름"(`PregnancySelect`)이다. 처음(성별 미입력)에는 숨기고,
 * 여성에서 다른 값으로 바꾸면 칸을 숨기면서 값을 `unknown`(모름)으로 되돌려 숨겨진 값이 저장되지 않게 한다(`pregnancyToSave`). 가족 프로필마다 독립이고 추가·수정이 같은 부품이다.
 * 입력창의 "일반인 | 임산부" 토글(FE-11, 남성만 숨김)과 `context.pregnant` 규칙은 여기와 별개다.
 * 건강 정보(임신 여부·복용 약)는 건강 정보 동의가 있을 때만 입력·저장할 수 있다: 동의가 없으면 두 칸이 비활성이고 이유 한 줄이 보이며,
 * 저장할 때도 건강 정보 칸을 요청에 싣지 않는다(실으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다).
 * 약은 사전 검색 후보를 골라 `{input_text, item_seq}`로 보내고(FE-04-13 A), 사전에 없거나 고르지 않고 확정하면 `{input_text}`만 보낸다
 * (`item_seq` null = 확인 안 된 약, FE-04-20 A. 목록에서 표지로 구분한다). 적은 값은 이 부품의 메모리에만 있다(브라우저 저장소에 두지 않는다).
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
  // 성별: 저장된 값만 채운다(새 프로필은 늘 미선택. 로그인 공급자 정보는 읽지 않는다)
  const [sex, setSex] = useState<Sex | "">(existing?.sex ?? "");
  // 임신 여부: 여성 프로필의 저장 값만 채운다. 여성이 아니면 칸이 숨겨지므로 모름(`unknown`)에서 시작한다
  const [pregnancy, setPregnancy] = useState<PregnancyStatus>(pregnancyToSave(existing?.sex ?? "", existing?.pregnancy_status ?? "unknown"));
  /** 성별을 바꾸면 임신 여부 칸이 나타나거나 사라진다. 사라질 때(여성 → 다른 값) 값을 모름으로 되돌린다 */
  const changeSex = (next: Sex | "") => {
    setSex(next);
    if (!showsPregnancyField(next)) setPregnancy("unknown");
  };
  const [medications, setMedications] = useState<MedicationInput[]>(() => (existing?.medications ?? []).map((item) => ({ input_text: item.input_text, item_seq: item.item_seq })));
  const [nameMissing, setNameMissing] = useState(false);

  const addMedication = (item: MedicationInput) => {
    if (medications.length >= MEDICATIONS_MAX) return;
    if (!medications.some((other) => sameMedication(other, item))) setMedications([...medications, item]);
  };
  const hasUnconfirmed = medications.some((item) => !item.item_seq);

  const save = () => {
    const name = label.trim();
    if (!name) return setNameMissing(true);
    setNameMissing(false);
    const draft: ProfileDraft = {
      relation: self ? "self" : relation,
      label: name,
      age_band: ageBand === "" ? null : ageBand,
      sex: sex === "" ? null : sex,
      // 건강 정보 동의가 없으면 건강 정보 칸을 보내지 않는다. 여성이 아니면 임신 여부는 모름으로 정리해 보낸다(숨겨진 값은 저장하지 않는다)
      health: healthConsent ? { pregnancy_status: pregnancyToSave(sex, pregnancy), medications } : null,
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

        {/* 성별(선택): 건강 정보 묶음 밖이라 동의와 상관없이 고를 수 있다 */}
        <label htmlFor={`${id}-sex`} className={LABEL_CLASS}>
          {SEX_LABEL}
        </label>
        <select id={`${id}-sex`} data-testid="profile-sex" value={sex} onChange={(event) => changeSex(event.target.value as Sex | "")} className={FIELD_CLASS}>
          <option value="">{NOT_SELECTED}</option>
          {SEXES.map((value) => (
            <option key={value} value={value}>
              {SEX_LABELS[value]}
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
          {/* 임신 여부: 성별이 여성일 때만 그린다(처음에는 숨김). 선택 버튼 "예 | 아니오 | 모름" */}
          {showsPregnancyField(sex) && (
            <div data-testid="pregnancy-field" className="flex flex-col gap-1">
              <span id={`${id}-pregnancy`} className={LABEL_CLASS}>
                {PREGNANCY_LABEL}
              </span>
              <PregnancySelect value={healthConsent ? pregnancy : "unknown"} onChange={setPregnancy} labelledBy={`${id}-pregnancy`} disabled={!healthConsent} />
            </div>
          )}
          <label htmlFor={`${id}-medication`} className={LABEL_CLASS}>
            {MEDICATIONS_LABEL}
          </label>
          <MedicationPicker id={`${id}-medication`} count={medications.length} onAdd={addMedication} />
          {/* 자료 밖 약 고지(FE-04-25 A): 사진 확인 카드와 같은 상수·같은 모양. 색은 토큰만(라이트·다크 AA) */}
          <p data-testid="drug-data-scope-notice" className="m-0 rounded-xl bg-bg-soft px-3 py-2 text-xs leading-[17px] text-ink-2 [word-break:keep-all]">
            {DRUG_DATA_SCOPE_NOTICE}
          </p>
          {healthConsent && medications.length > 0 && (
            <>
              <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                {medications.map((item) => (
                  <li
                    key={`${item.item_seq ?? ""}:${item.input_text}`}
                    data-testid="medication"
                    data-confirmed={item.item_seq ? "true" : "false"}
                    className={`flex max-w-full items-center rounded-full border pl-3 text-sm ${item.item_seq ? "border-line bg-bg-softer" : "border-warn-ink/30 bg-warn-bg"}`}
                  >
                    <span data-testid="medication-name" className="min-w-0 [overflow-wrap:anywhere]">
                      {item.input_text}
                    </span>
                    {/* 사전 후보 없이 글자만 저장하는 약(FE-04-20 A): 표지로 구분한다 */}
                    {!item.item_seq && (
                      <span data-testid="medication-unconfirmed" className="ml-1.5 flex-none rounded-full bg-bg px-1.5 py-0.5 text-[11px] leading-4 font-bold text-warn-ink">
                        {MEDICATION_UNCONFIRMED_TAG}
                      </span>
                    )}
                    <button
                      type="button"
                      aria-label={removeMedicationLabel(item.input_text)}
                      onClick={() => setMedications(medications.filter((other) => !sameMedication(other, item)))}
                      className={ICON_BUTTON}
                    >
                      <XIcon className="size-4" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
              {hasUnconfirmed && (
                <p data-testid="medication-unconfirmed-note" className="m-0 rounded-xl bg-warn-bg px-3 py-2 text-xs leading-[17px] text-warn-ink">
                  {MEDICATION_UNCONFIRMED_NOTE}
                </p>
              )}
            </>
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
