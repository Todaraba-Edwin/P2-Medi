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
} as const;

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
