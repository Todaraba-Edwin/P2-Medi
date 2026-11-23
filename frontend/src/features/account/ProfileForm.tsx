"use client";

import { useId, useRef, useState } from "react";
import { CameraIcon, CheckIcon, XIcon } from "lucide-react";
import { PhotoModal } from "@/features/photo/PhotoModal";
import { AGE_BANDS, AVATAR_COLORS, DEFAULT_AVATAR_COLOR, MEDICATIONS_MAX, PROFILE_LABEL_MAX_CHARS, RELATIONS, SEXES, sameMedication } from "@/lib/api/account";
import type { AgeBand, AvatarColor, MedicationInput, PregnancyStatus, ProfileDraft, Relation, Sex } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { hasHealthConsent, useAccountStore } from "@/stores/account";
import {
  AGE_BAND_LABEL,
  AGE_BAND_LABELS,
  AVATAR_COLOR_LABEL,
  AVATAR_COLOR_LABELS,
  CANCEL_LABEL,
  DRUG_DATA_SCOPE_NOTICE,
  ERROR_NAME_EMPTY,
  MEDICATIONS_LABEL,
  MEDICATION_PHOTO_LABEL,
  MEDICATION_UNCONFIRMED_NOTE,
  MEDICATION_UNCONFIRMED_TAG,
  OPTIONAL_TAG,
  PREGNANCY_LABEL,
  PROFILE_FORM_EDIT_TITLE,
  PROFILE_FORM_NEW_LEAD,
  PROFILE_FORM_NEW_TITLE,
  PROFILE_NAME_HINT,
  PROFILE_NAME_LABEL,
  PROFILE_REQUIRED_HINT,
  REQUIRED_TAG,
  RELATION_LABEL,
  RELATION_LABELS,
  SAVE_LABEL,
  SEX_LABEL,
  SEX_LABELS,
  removeMedicationLabel,
} from "./copy";
import { ChoiceButtons } from "./ChoiceButtons";
import { MedicationPicker } from "./MedicationPicker";
import { FIELD_CLASS, FailureLine, ICON_BUTTON, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, useAccountModal } from "./parts";
import { PregnancySelect } from "./PregnancySelect";
import { ProfileAvatar } from "./ProfileAvatar";
import { useHealthConsentNotice } from "./ProfileList";

const LABEL_CLASS = "text-xs font-bold text-ink-2";

/**
 * 목록에 약을 더한다(FE-04-27 A: 글자 입력과 사진 등록이 같은 규칙). 같은 약(`sameMedication`)은 넣지 않고 10개(`MEDICATIONS_MAX`)를 넘기지 않는다.
 * 넘치는 항목은 조용히 빠진다(폼이 상한 안내 `ERROR_MEDICATION_LIMIT`를 보인다). 순수 함수라 시험에서 바로 본다
 */
export function mergeMedications(current: readonly MedicationInput[], added: readonly MedicationInput[]): MedicationInput[] {
  const next = [...current];
  for (const item of added) {
    if (next.length >= MEDICATIONS_MAX) break;
    if (!next.some((other) => sameMedication(other, item))) next.push(item);
  }
  return next;
}

/**
 * 새 프로필의 기본 색(FE-17 U-07, 2026-11-23 사용자 확정 "프로필 색 기본값은 한 가지로 yellow"): 서버 기본값(`DEFAULT_AVATAR_COLOR`)과 같은 노랑을 미리 골라 둔다.
 * 직전 구현의 "안 쓴 색 제안"을 대체한다. 사용자는 바꿀 수 있다
 */
export const NEW_PROFILE_AVATAR_COLOR: AvatarColor = DEFAULT_AVATAR_COLOR;

/** 필수 4칸(FE-17 U-07 2026-11-23 사용자 확정: 관계·이름·연령대·성별). 모두 채워야 `저장`이 눌린다. 순수 함수라 시험에서 바로 본다 */
export function requiredFilled(fields: { relation: Relation | ""; label: string; ageBand: AgeBand | ""; sex: Sex | "" }): boolean {
  return fields.relation !== "" && fields.label.trim() !== "" && fields.ageBand !== "" && fields.sex !== "";
}

interface ProgressStep {
  key: string;
  label: string;
  required: boolean;
  done: boolean;
}

/**
 * 폼 상단 진행바(FE-17 U-07, 2026-11-23 사용자 확정 "입력 단계별 6단계"): 관계·이름·연령대·성별(필수 4) → 복용 중인 약·프로필 색(선택 2).
 * - 필수 칸을 채우면 그 막대가 초록(`ok-ink`) + 체크 아이콘, 아직이면 회색 선 색. 선택 2칸은 뒤쪽에 파랑(`blue-ink`) 막대와 `선택` 머리 글자로 구분한다(색만으로 구분하지 않는다).
 * - 보조기기: 머리의 `필수 n/4`가 `role="progressbar"`(값 0~4)이고, 칸마다 이름 뒤에 `필수`/`선택`을 읽는다. 막대는 장식이다.
 * - 글자는 기존 상수(칸 이름·`필수`·`선택`)와 숫자뿐이다. 약 칸 이름의 "(선택)"은 머리 `선택`과 겹쳐 뺐다
 */
function ProfileProgress({ steps }: { steps: readonly ProgressStep[] }) {
  const required = steps.filter((step) => step.required);
  const doneCount = required.filter((step) => step.done).length;
  const optionalCount = steps.length - required.length;
  return (
    <div data-testid="profile-progress" className="flex flex-col gap-1">
      <div className="grid gap-1 text-xs font-bold" style={{ gridTemplateColumns: `${required.length}fr ${optionalCount}fr` }}>
        <span
          role="progressbar"
          aria-label={REQUIRED_TAG}
          aria-valuemin={0}
          aria-valuemax={required.length}
          aria-valuenow={doneCount}
          aria-valuetext={`${doneCount}/${required.length}`}
          data-testid="profile-progress-required"
          className={doneCount === required.length ? "text-ok-ink" : "text-ink-2"}
        >
          {REQUIRED_TAG} {doneCount}/{required.length}
        </span>
        <span data-testid="profile-progress-optional" className="text-blue-ink">
          {OPTIONAL_TAG}
        </span>
      </div>
      <ol className="m-0 grid list-none gap-1 p-0" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((step) => {
          const state = step.required ? (step.done ? "done" : "todo") : "optional";
          return (
            <li key={step.key} data-testid="profile-step" data-step={step.key} data-state={state} className="flex min-w-0 flex-col gap-1">
              <span aria-hidden="true" className={cn("h-1.5 rounded-full", state === "done" ? "bg-ok-ink" : state === "todo" ? "bg-line-2" : "bg-blue-ink")} />
              <span className={cn("flex min-w-0 items-start gap-0.5 text-[11px] leading-[14px] [word-break:keep-all]", state === "done" ? "font-bold text-ok-ink" : state === "todo" ? "text-mute" : "text-blue-ink")}>
                {state === "done" && <CheckIcon className="mt-px size-3 flex-none" strokeWidth={3} aria-hidden="true" />}
                <span className="min-w-0">
                  {step.label}
                  <span className="sr-only"> {step.required ? REQUIRED_TAG : OPTIONAL_TAG}</span>
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * 필수 칸의 이름 줄: 칸 이름(라벨) + 옆 표지(기존 글자 `필수`). 표지는 라벨 밖이라 칸의 접근 가능한 이름은 칸 이름 그대로이고,
 * 보조기기는 칸의 `aria-required`·`required`로 필수임을 읽으므로 표지는 장식이다
 */
function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className={cn(LABEL_CLASS, "flex items-baseline gap-1")}>
      {children}
      <span aria-hidden="true" className="font-normal text-mute">
        {REQUIRED_TAG}
      </span>
    </div>
  );
}

/**
 * 프로필 색 고르기 8칸(라디오 묶음). 칸은 색 원만 보이고(고른 칸은 원 한가운데 체크 표시 + 굵은 테두리: 색만으로 구분하지 않는다) 접근 가능한 이름은 색 이름이다.
 * 누르는 영역 44px, ←/→로 옮기며 고른다(브라우저 기본 라디오). 고른 색의 병아리 미리보기는 폼 머리(제목 옆)에 있다.
 * 폼의 첫 번째 입력이다(FE-17 U-15: 제목 바로 아래, 관계·이름·연령대·성별보다 앞). 고르면 머리의 병아리 배경색이 바로 같이 바뀐다.
 * 체크 위치(FE-17 U-07, ISSUE-026): 원과 체크를 같은 격자 칸(`[grid-area:1/1]`)에 겹쳐 원 안 가운데에 둔다(예전에는 기준 상자가 없어 원 밖 아래로 떨어졌다)
 */
function AvatarColorPicker({ id, value, onChange }: { id: string; value: AvatarColor; onChange: (color: AvatarColor) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <span id={`${id}-avatar`} className={LABEL_CLASS}>
        {AVATAR_COLOR_LABEL}
      </span>
      <div role="radiogroup" aria-labelledby={`${id}-avatar`} data-testid="avatar-color-picker" className="flex min-w-0 flex-wrap items-center">
        {AVATAR_COLORS.map((color) => {
          const checked = color === value;
          return (
            // `relative`: 화면에서 숨긴 라디오(`sr-only` = position absolute)의 기준 상자를 이 칸으로 둔다(FE-17 U-14, ISSUE-031).
            // 기준 상자가 없으면 라디오가 모달 상자(스크롤 영역 밖) 기준으로 놓여, 칸을 눌러 라디오가 초점을 받을 때 브라우저가 모달 상자 자체를 스크롤해 내용이 위로 밀렸다
            <label key={color} data-testid="avatar-color-option" data-color={color} data-checked={checked} className="relative grid size-11 cursor-pointer place-items-center rounded-full has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-[-4px] has-[:focus-visible]:outline-ink-2">
              <input type="radio" name={`${id}-avatar-color`} value={color} checked={checked} onChange={() => onChange(color)} aria-label={AVATAR_COLOR_LABELS[color]} className="sr-only" />
              <span data-testid="avatar-color-swatch" className={cn("grid size-8 place-items-center rounded-full border", checked ? "border-2 border-ink" : "border-line-2")}>
                <ProfileAvatar color={color} size={checked ? 28 : 30} face={false} className="[grid-area:1/1]" />
                {checked && <CheckIcon data-testid="avatar-color-check" className="relative size-4 text-ink [grid-area:1/1]" strokeWidth={3} aria-hidden="true" />}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

/** 임신 여부 칸을 그리는가(사용자 지시 2026-11-22): 성별이 **여성일 때만**. 남성·미입력(기본 "선택 안 함")은 숨긴다 */
export const showsPregnancyField = (sex: Sex | "") => sex === "female";

/**
 * 여성이 아닐 때 저장하는 임신 여부(사용자 결정 2026-11-22 "여성이 아니면 '아니오' 저장", 같은 날 정정 "미입력도 아니오로 저장"):
 * 남성·그 밖 값·미입력(선택 안 함) 모두 `not_pregnant`다. 기준이 바뀌면 이 상수 한 줄만 바꾼다
 */
export const PREGNANCY_WHEN_NOT_FEMALE: PregnancyStatus = "not_pregnant";

/**
 * 저장할 임신 여부(분기 한 곳): 여성이면 사용자가 고른 값, 아니면(칸이 숨겨짐: 남성·그 밖·미입력) `PREGNANCY_WHEN_NOT_FEMALE`(아니오)로 정리한다.
 * 저장된 프로필이 여성이 아닌데 `pregnant`가 남아 있는 비정상 값(입력창 토글은 성별 미입력 프로필에도 저장한다, FE-11-13)은 편집 화면에서 보이지 않고 저장 때 아니오로 돌아간다.
 * 질문 입력창의 임신 토글(FE-11: 남성만 숨김, 여성·미입력·게스트는 보임)은 이 값과 별개로 질문마다 `context.pregnant`를 정한다
 */
export const pregnancyToSave = (sex: Sex | "", pregnancy: PregnancyStatus): PregnancyStatus => (showsPregnancyField(sex) ? pregnancy : PREGNANCY_WHEN_NOT_FEMALE);

/**
 * 프로필 추가·수정 폼(한 화면 + 상단 진행바, FE-17 U-07 2026-11-23). 필수 4칸 관계·이름·연령대·성별을 버튼 선택(세그먼트·칩)으로 고르고,
 * 임신 여부(여성일 때)·복용 중인 약(선택)·프로필 색(선택, 기본 노랑)을 둔다. 필수 4칸을 다 채우기 전에는 `저장`이 비활성이다.
 * 2단계 분리(와이어프레임 Profile-Basic → Health)는 사용자 확인 전이라 하지 않았다. 와이어프레임의 "응급이면 바로 119" 링크는 넣지 않는다(FE-17 U-04 119 위치 정책).
 * (아래는 FE-17 이전 설명. 성별·연령대의 "선택 안 함"은 2026-11-23부터 없다)
 * 성별(FE-11-09 C·PRD-17-13 A)은 연령대 아래 기본 단계의 선택 칸이다: "여성 | 남성" + 선택 안 함(null). 건강 정보가 아니라 건강 정보 동의 없이도 저장되고,
 * 온보딩에서 사용자가 직접 고른다(간편 로그인 공급자 정보로 미리 채우지 않는다. 처음 열면 늘 "선택 안 함"이다). `/chat` 요청에는 싣지 않는다(S10).
 * 임신 여부(사용자 지시 2026-11-22, 작업 B)는 **성별이 여성일 때만** 나타나는 선택 버튼 "예 | 아니오 | 모름"(`PregnancySelect`)이다. 처음(성별 미입력)에는 숨기고,
 * 여성에서 다른 값으로 바꾸면 칸을 숨기며, 여성이 아닌 프로필(남성·그 밖·미입력)의 저장 값은 `not_pregnant`(아니오)다(`pregnancyToSave`, 사용자 결정 2026-11-22 작업 C).
 * 가족 프로필마다 독립이고 추가·수정이 같은 부품이다.
 * 입력창의 "일반인 | 임산부" 토글(FE-11, 남성만 숨김)과 `context.pregnant` 규칙은 여기와 별개다.
 * 건강 정보(임신 여부·복용 약)는 건강 정보 동의가 있을 때만 입력·저장할 수 있다: 동의가 없으면 두 칸이 비활성이고 이유 한 줄이 보이며,
 * 저장할 때도 건강 정보 칸을 요청에 싣지 않는다(실으면 서버가 422 `HEALTH_CONSENT_REQUIRED`로 막는다).
 * 약은 사전 검색 후보를 골라 `{input_text, item_seq}`로 보내고(FE-04-13 A), 사전에 없거나 고르지 않고 확정하면 `{input_text}`만 보낸다
 * (`item_seq` null = 확인 안 된 약, FE-04-20 A. 목록에서 표지로 구분한다). 적은 값은 이 부품의 메모리에만 있다(브라우저 저장소에 두지 않는다).
 * 사진으로 등록(FE-04-27 A, 2026-11-22): 약 입력 아래 `사진으로 등록` 버튼이 기존 사진 모달을 **프로필 목적지**로 연다(계정 모달 위에 한 층 더, `stacked`).
 * 확인 카드에서 `이대로 확인`한 약만 **지금 편집 중인 이 프로필**의 목록에 더한다(후보를 고른 약은 확인된 약, 글자만 있는 약은 확인 안 된 약, 같은 약은 한 번만).
 * 사진·이미지는 어디에도 저장하지 않고 이름만 목록에 들어가며, 저장은 기존처럼 `저장`을 눌러야 한다(건강 정보 동의가 없으면 묶음이 비활성이라 버튼도 눌리지 않는다).
 * 이름(별명) 초기값(FE-04-28 B, 2026-11-22): 본인 프로필을 **처음 만들 때만** 로그인 공급자가 카카오면 닉네임이 미리 들어 있다(`target.labelDefault`, 스토어가 어댑터에서 읽는다).
 * 구글·이메일·가족 추가·수정은 비어 있다. 사용자가 고치거나 지울 수 있고 저장을 누르기 전에는 서버로 가지 않으며 저장 요청에는 칸에 남은 값만 간다. 성별 등 다른 칸은 공급자 정보로 채우지 않는다.
 * 채팅 입력창의 사진 흐름(`AppShell`, 채팅 목적지)과는 별개의 모달 인스턴스다. 모달을 닫으면(`닫기`·Esc·`글자로 입력`) 폼의 입력 상태는 그대로다
 */
export function ProfileForm() {
  const { store, container, hideMascot } = useAccountModal();
  const target = useAccountStore((state) => state.form, store);
  const existing = useAccountStore((state) => state.profiles.find((profile) => profile.profile_id === state.form?.profileId) ?? null, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const healthConsent = hasHealthConsent(me);
  const healthNotice = useHealthConsentNotice();
  const id = useId();
  const self = target?.self ?? false;

  // 이름(별명): 사용자가 적은 값(`typed`)이 있으면 그것, 없으면 저장된 값, 새 본인 프로필이면 스토어가 읽어 온 초기값(카카오 닉네임, FE-04-28 B)이다.
  // 초기값은 나중에 도착해도 사용자가 아직 적지 않았을 때만 보이고, 지운 값("")도 사용자 값이라 초기값으로 되돌아가지 않는다. 저장은 지금 보이는 값만 보낸다
  const [typed, setTyped] = useState<string | null>(null);
  const label = typed ?? existing?.label ?? target?.labelDefault ?? "";
  // 관계(필수): 본인 프로필은 `본인` 고정, 새 가족은 아직 안 고른 상태에서 시작한다(FE-17 U-07: 필수 칸을 진행바로 보인다)
  const [relation, setRelation] = useState<Relation | "">(existing?.relation ?? (self ? "self" : ""));
  const [ageBand, setAgeBand] = useState<AgeBand | "">(existing?.age_band ?? "");
  // 병아리 배경색: 고치면 저장된 색, 새 프로필은 노랑이 미리 골라져 있다(FE-17 U-07 사용자 확정)
  const [avatarColor, setAvatarColor] = useState<AvatarColor>(existing?.avatar_color ?? NEW_PROFILE_AVATAR_COLOR);
  // 성별: 저장된 값만 채운다(새 프로필은 늘 미선택. 로그인 공급자 정보는 읽지 않는다)
  const [sex, setSex] = useState<Sex | "">(existing?.sex ?? "");
  // 임신 여부(칸의 값): 여성 프로필의 저장 값만 채운다. 여성이 아니면 칸이 숨겨지고 다시 여성을 고르면 모름(`unknown`)에서 시작한다(고르기 전에는 아니오로 두지 않는다, 2026-11-22 확정).
  // 저장 값은 늘 `pregnancyToSave`가 정한다(여성이 아니면 아니오)
  const [pregnancy, setPregnancy] = useState<PregnancyStatus>(showsPregnancyField(existing?.sex ?? "") ? (existing?.pregnancy_status ?? "unknown") : "unknown");
  /** 성별을 바꾸면 임신 여부 칸이 나타나거나 사라진다. 사라질 때(여성 → 다른 값) 칸의 값을 모름으로 되돌린다(저장 값은 `pregnancyToSave`가 아니오로 정리한다) */
  const changeSex = (next: Sex | "") => {
    setSex(next);
    if (!showsPregnancyField(next)) setPregnancy("unknown");
  };
  const [medications, setMedications] = useState<MedicationInput[]>(() => (existing?.medications ?? []).map((item) => ({ input_text: item.input_text, item_seq: item.item_seq })));
  const [nameMissing, setNameMissing] = useState(false);
  /** 사진 등록 모달(프로필 목적지). 사진·읽은 목록은 모달 안 메모리에만 있다 */
  const [photoOpen, setPhotoOpen] = useState(false);
  /** 사진 모달이 닫힌 뒤 초점을 둘 곳: 기본은 `사진으로 등록` 버튼, `글자로 입력`이면 약 입력 칸 */
  const photoCloseFocus = useRef<"entry" | "input">("entry");
  const photoEntry = useRef<HTMLButtonElement>(null);

  const addMedication = (item: MedicationInput) => setMedications((current) => mergeMedications(current, [item]));
  /** 사진 확인 카드의 `이대로 확인`(FE-04-27 A): 이 폼(지금 편집 중인 프로필)의 목록에만 더한다 */
  const addFromPhoto = (items: MedicationInput[]) => setMedications((current) => mergeMedications(current, items));
  const openPhoto = () => {
    photoCloseFocus.current = "entry";
    setPhotoOpen(true);
  };
  const photoTypeInstead = () => {
    photoCloseFocus.current = "input";
    setPhotoOpen(false);
  };
  const photoClosed = () => {
    if (photoCloseFocus.current === "input") document.getElementById(`${id}-medication`)?.focus();
    else photoEntry.current?.focus();
  };
  const hasUnconfirmed = medications.some((item) => !item.item_seq);

  const complete = requiredFilled({ relation: self ? "self" : relation, label, ageBand, sex });
  const steps: ProgressStep[] = [
    { key: "relation", label: RELATION_LABEL, required: true, done: self || relation !== "" },
    { key: "name", label: PROFILE_NAME_LABEL, required: true, done: label.trim() !== "" },
    { key: "age", label: AGE_BAND_LABEL, required: true, done: ageBand !== "" },
    { key: "sex", label: SEX_LABEL, required: true, done: sex !== "" },
    { key: "medications", label: MEDICATIONS_LABEL.replace(/\(.*\)$/, ""), required: false, done: medications.length > 0 },
    { key: "color", label: AVATAR_COLOR_LABEL, required: false, done: true },
  ];

  const save = () => {
    const name = label.trim();
    if (!name) return setNameMissing(true);
    setNameMissing(false);
    // 필수 4칸이 비면 저장하지 않는다(버튼도 비활성이다. Enter 제출도 같은 규칙)
    if (!complete || relation === "" || ageBand === "" || sex === "") return;
    const draft: ProfileDraft = {
      relation: self ? "self" : relation,
      label: name,
      age_band: ageBand,
      sex,
      avatar_color: avatarColor,
      // 건강 정보 동의가 없으면 건강 정보 칸을 보내지 않는다. 여성이 아니면 임신 여부는 모름으로 정리해 보낸다(숨겨진 값은 저장하지 않는다)
      health: healthConsent ? { pregnancy_status: pregnancyToSave(sex, pregnancy), medications } : null,
    };
    void store.getState().saveProfile(draft);
  };

  return (
    <StepBody data-testid="profile-form">
      {/* 머리(FE-17 U-07, 와이어프레임 Profile-Basic): 고른 색의 병아리 + 제목·보조 문구. 수정 화면은 기존 제목이다. 119 안내 중에는 병아리 없이 색 원만.
          병아리 배경은 폼 첫 칸 `프로필 색`의 값(`avatarColor`)을 그대로 쓰므로 색을 고르면 즉시 같이 바뀐다(FE-17 U-15) */}
      <div data-testid="profile-form-head" className="flex items-center gap-3.5">
        <ProfileAvatar color={avatarColor} size={56} face={!hideMascot} />
        <div className="flex min-w-0 flex-col gap-0.5">
          <StepTitle>{existing ? PROFILE_FORM_EDIT_TITLE : PROFILE_FORM_NEW_TITLE}</StepTitle>
          {!existing && <p className="m-0 text-sm leading-5 text-ink-2 [word-break:keep-all]">{PROFILE_FORM_NEW_LEAD}</p>}
        </div>
      </div>
      <ProfileProgress steps={steps} />
      <form
        noValidate
        aria-busy={pending}
        className="flex flex-col gap-2.5"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        {/* 프로필 색(선택, 건강 정보 아님): 폼의 첫 번째 입력(FE-17 U-15, 2026-11-23 사용자 지시 "프로필 색상을 첫번째로"). 계정 버튼·입력창 칩·목록에서 사람을 구분하는 병아리 배경색.
            진행바는 사용자 확정 사양(필수 4칸 → 선택 2칸, 색은 맨 뒤)을 그대로 두어 폼 순서와 진행바 순서가 다르다(보고에 적음) */}
        <AvatarColorPicker id={id} value={avatarColor} onChange={setAvatarColor} />

        {/* 관계(필수): 5칸 세그먼트(본인|자녀|부모|배우자|기타). 본인 프로필은 `본인` 고정(다른 칸 비활성), 가족은 `본인`을 고를 수 없다 */}
        <FieldLabel>
          <span id={`${id}-relation`}>{RELATION_LABEL}</span>
        </FieldLabel>
        <ChoiceButtons
          data-testid="profile-relation"
          layout="segment"
          required
          labelledBy={`${id}-relation`}
          value={self ? "self" : relation}
          onChange={setRelation}
          options={RELATIONS.map((value) => ({ value, label: RELATION_LABELS[value], disabled: self ? value !== "self" : value === "self" }))}
        />

        <FieldLabel>
          <label htmlFor={`${id}-name`}>{PROFILE_NAME_LABEL}</label>
        </FieldLabel>
        <input
          id={`${id}-name`}
          type="text"
          autoComplete="off"
          maxLength={PROFILE_LABEL_MAX_CHARS}
          value={label}
          required
          aria-invalid={nameMissing}
          aria-describedby={`${id}-name-hint`}
          onChange={(event) => setTyped(event.target.value)}
          className={FIELD_CLASS}
        />
        <p id={`${id}-name-hint`} role={nameMissing ? "alert" : undefined} className={nameMissing ? "m-0 text-sm font-semibold text-red-ink" : "m-0 text-xs text-mute"}>
          {nameMissing ? ERROR_NAME_EMPTY : PROFILE_NAME_HINT}
        </p>

        {/* 연령대(필수): 11칸 칩 그리드(3열, 줄바꿈). 예전 `선택 안 함`은 없다(필수 칸) */}
        <FieldLabel>
          <span id={`${id}-age`}>{AGE_BAND_LABEL}</span>
        </FieldLabel>
        <ChoiceButtons
          data-testid="profile-age"
          layout="grid"
          required
          labelledBy={`${id}-age`}
          value={ageBand}
          onChange={setAgeBand}
          options={AGE_BANDS.map((value) => ({ value, label: AGE_BAND_LABELS[value] }))}
        />

        {/* 성별(필수): 2칸 세그먼트(여성|남성). 건강 정보 묶음 밖이라 동의와 상관없이 고를 수 있다 */}
        <FieldLabel>
          <span id={`${id}-sex`}>{SEX_LABEL}</span>
        </FieldLabel>
        <ChoiceButtons
          data-testid="profile-sex"
          layout="segment"
          required
          labelledBy={`${id}-sex`}
          value={sex}
          onChange={changeSex}
          options={SEXES.map((value) => ({ value, label: SEX_LABELS[value] }))}
        />

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
          {/* 사진으로 등록(FE-04-27 A): 약 입력 바로 아래. 건강 정보 묶음 안이라 동의가 없으면 함께 비활성이고, 10개면 더 넣을 수 없어 비활성 */}
          <button
            ref={photoEntry}
            type="button"
            data-testid="medication-photo"
            disabled={medications.length >= MEDICATIONS_MAX}
            onClick={openPhoto}
            className={`${SECONDARY_BUTTON} flex items-center justify-center gap-1.5 self-start`}
          >
            <CameraIcon className="size-4" aria-hidden="true" />
            {MEDICATION_PHOTO_LABEL}
          </button>
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
        {/* 필수 4칸을 다 채우기 전에는 `저장`이 비활성이고 이유 한 줄을 버튼 설명으로 잇는다 */}
        {!complete && (
          <p id={`${id}-required`} data-testid="profile-required-hint" className="m-0 text-xs leading-[17px] text-ink-2 [word-break:keep-all]">
            {PROFILE_REQUIRED_HINT}
          </p>
        )}
        <div className="mt-1 flex gap-2">
          <button type="button" onClick={() => store.getState().back()} className={`${SECONDARY_BUTTON} flex-1`}>
            {CANCEL_LABEL}
          </button>
          <button type="submit" data-testid="profile-save" disabled={pending || !complete} aria-describedby={complete ? undefined : `${id}-required`} className={`${PRIMARY_BUTTON} flex-1`}>
            {SAVE_LABEL}
          </button>
        </div>
      </form>
      {/* 사진 등록 모달(프로필 목적지): 계정 모달과 같은 자리(119 배너 아래)에 한 층 위로 겹친다. 확인한 이름만 이 폼의 목록에 들어가고 채팅 전송은 부르지 않는다 */}
      <PhotoModal
        open={photoOpen}
        onOpenChange={setPhotoOpen}
        destination="profile"
        onConfirm={() => {}}
        onRegister={addFromPhoto}
        onTypeInstead={photoTypeInstead}
        onCloseAutoFocus={photoClosed}
        container={container}
        hasEmergency={hideMascot}
        stacked
      />
    </StepBody>
  );
}
