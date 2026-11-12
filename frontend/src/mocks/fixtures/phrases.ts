// 문구 원문: backend/app/agent/fixed_phrases.py의 상수 값을 그대로 옮겼다(지어내지 않음).
// fixtures.test.ts가 파이썬 원본과 글자 일치를 확인한다. 화면 코드는 이 파일을 가져다 쓰지 않는다(mock 전용).
export const PHRASES = {
  EMERGENCY_119: "응급 상황일 수 있어요. 지금 바로 119에 전화하세요.",
  EMERGENCY_119_TEL: "tel:119",
  NOT_SAFE_NOTICE: "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요.",
  PHARMACIST_CHECK_NOTICE: "근처 약국·약사에게 확인하세요.",
  PHARMACIST_ADVICE_FIXED: "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요.",
  NOT_LISTED: "금기 목록에 없음(안전하다는 뜻이 아님)",
  BADGE_PAIR: "삐! 병용금기",
  BADGE_PREGNANCY: "삐! 임부금기 {grade}등급",
  BADGE_PREGNANCY_M: "삐! 임부금기 M등급",
  BADGE_PREGNANCY_M_NOTE: "적응증에 따라 등급이 달라요",
  BADGE_AGE: "삐! 연령금기",
  UNIDENTIFIED: "약을 찾지 못해 확인하지 못함",
  UNIDENTIFIED_WHY: "식약처·한국의약품안전관리원 자료에서 찾지 못했어요",
  UNIDENTIFIED_RETRIED: "표기를 바꿔 한 번 더 찾아봤어요",
  UNIDENTIFIED_NEXT: "봉투나 상자에 적힌 제품명을 그대로 다시 알려 주세요",
  MISSING_SEARCH_MISS: "허가사항에서 관련 문장을 찾지 못했어요",
  LIMIT_REACHED: "답을 정리하다 시간이 다 되어 여기까지 확인한 결과만 보여 드려요. 확인하지 못한 항목은 약국·약사에게 물어보세요.",
  // 진행 문구(`progress.label`): PROGRESS_LABELS[stage]
  PROGRESS_DRUG_LOOKUP: "약 찾는 중",
  PROGRESS_CONTRA_CHECK: "금기 확인 중",
  PROGRESS_EVIDENCE_SEARCH: "근거 찾는 중",
} as const;

/** `fixed_phrases.PROGRESS_LABELS`와 같은 대응(키는 `stage`) */
export const PROGRESS_LABELS = {
  drug_lookup: PHRASES.PROGRESS_DRUG_LOOKUP,
  contraindication_check: PHRASES.PROGRESS_CONTRA_CHECK,
  evidence_search: PHRASES.PROGRESS_EVIDENCE_SEARCH,
} as const;

// BADGE_SOURCE_TAIL: 등급 불일치 배지의 출처 꼬리(파일 → 성분 API). 배지 문구 = `{배지} {꼬리}`(finalize._badges)
export const BADGE_SOURCE_TAIL = { FILE: "(파일)", API_DIRECT: "(성분 API)" } as const;

export const DISCLAIMER_PARTS = [
  "공공데이터 기반 정보 제공이며 진단·처방이 아님",
  "금기 목록에 없다는 것이 안전하다는 뜻이 아님",
  "요양기관의 DUR 점검을 대체하지 않음",
] as const;

// fixed_phrases.py와 같은 조립: DISCLAIMER = " · ".join(parts), FIXED_NOTICE = f"{NOT_SAFE_NOTICE} {PHARMACIST_CHECK_NOTICE}"
export const DISCLAIMER = DISCLAIMER_PARTS.join(" · ");
export const FIXED_NOTICE = `${PHRASES.NOT_SAFE_NOTICE} ${PHRASES.PHARMACIST_CHECK_NOTICE}`;

// REFUSE_MESSAGES["DOSAGE"], SOURCE_KIND_TEXT["FILE"]
export const REFUSE_DOSAGE =
  "복용량은 정해 드릴 수 없어요. 약사·의사에게 확인하세요. 허가사항의 용법·용량은 근거 상세에서 원문으로 볼 수 있어요.";
export const SOURCE_KIND_FILE = "공식 파일 기준이에요";

// backend/app/agent/router.py `_clarify` 템플릿의 꼬리(앞의 '{raw}'는 합성 이름으로 채운다)
export const CLARIFY_TAIL = "에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요.";

// 출처 표 값: backend/app/tools/provenance.py PUBLISHER["kids"](= backend/app/db/loaders.py SRC_KIDS), DATASET_LABELS
export const PUBLISHER_KIDS = "한국의약품안전관리원";
export const DATASET_CONTRA_PAIR = "병용금기 파일";
export const DATASET_PREGNANCY = "임부금기 파일";
export const DATASET_AGE = "연령금기 파일";
export const DATASET_DUR_INGR = "DUR 성분정보 API";
export const DATASET_PRMSN = "의약품 허가정보";
export const PUBLISHER_MFDS = "식약처"; // PUBLISHER["mfds"]
