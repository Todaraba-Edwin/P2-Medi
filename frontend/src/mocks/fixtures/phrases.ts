// 문구 원문: backend/app/agent/fixed_phrases.py의 상수 값을 그대로 옮겼다(지어내지 않음).
// fixtures.test.ts가 파이썬 원본과 글자 일치를 확인한다. 화면 코드는 이 파일을 가져다 쓰지 않는다(mock 전용).
export const PHRASES = {
  EMERGENCY_119: "응급 상황일 수 있어요. 지금 바로 119에 전화하세요.",
  EMERGENCY_119_TEL: "tel:119",
  EMERGENCY_119_WIDE: "컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요.", // 넓은 폭 보조 문장(`emergency.wide_text`)
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
  // 미식별 카드 보조줄(`sub_line`). "을(를)"은 서버 `josa.fill`이 받침으로 고른다(fixture는 `fillJosa`)
  UNIDENTIFIED_SUB_LINE: "{drug}을(를) 찾지 못해 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요.",
  // 식별된 약 줄: 표지 글자와 보조줄의 성분 이름 사이 글자
  IDENTIFIED_LINE: "찾음",
  IDENTIFIED_SUB_SEP: " · ",
  // 정보가 없어 확인하지 못한 종류의 줄(`not_checked_lines[]`), 나이 미특정 안내(`age_info_line`), 되묻기 안내(`candidates_line`)
  PREGNANCY_NOT_CHECKED: "임신 여부를 알 수 없어 임부금기는 확인하지 못했어요.",
  AGE_INFO_LINE: "나이를 특정할 수 없어 판정하지 않고, 이 약의 나이별 연령금기 기준을 원문 그대로 보여 드려요.",
  CLARIFY_PICK_LINE: "어느 제품인지 고르면 금기를 확인해 드려요.",
  // 되묻기 질문(`summary`, AG-05-05 A·AG-05-10 A): 후보 1개 / 여럿. `router._clarify`가 `.format(drug=t.raw)`로 채운다(물음표 1개)
  CLARIFY_ONE_CANDIDATE: "'{drug}'은(는) 아래 약을 말씀하신 건가요? 맞으면 골라 주시고, 아니면 약 이름을 다시 알려 주세요.",
  CLARIFY_MANY_CANDIDATES: "'{drug}'에 해당하는 약이 여러 개예요. 어떤 약을 말씀하시는 건가요?",
  // 이전 차례에서 고른 약과 같은 이름이 다시 나왔을 때의 확인 질문(AG-21-04 A). `router._single_question`이 첫 후보(이전 선택)의 사전 제품명으로 채운다(fixture는 `fillPriorPick`)
  CLARIFY_PRIOR_PICK: "앞에서 고른 '{drug}'을(를) 말씀하시는 건가요? 다른 약이면 아래에서 골라 주세요.",
  // 용량주의 "예" 답 고지(`dose_notice`)·재복용 질문 고지(`redose_notice`)(AG-22, 2026-11-19 원문 승인). 결과 위 안내 띠에 그대로
  DOSE_NOTICE: "오늘 이미 드셨다면 하루 최대량을 넘을 수 있어요. 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",
  REDOSE_NOTICE: "추가 복용 여부·간격은 정해 드릴 수 없어요. 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",
  // 약 2개 이상 결과의 묶음 요약(`result_summary.text`, FE-11-04 A)과 약 3개 이상일 때의 한 줄(`pair_only_notice`, FE-11-06 A). fixture는 `resultSummaryFound`
  RESULT_SUMMARY_FOUND: "약 {n}개를 함께 먹을 때: 병용금기 {k}건({pairs})",
  RESULT_SUMMARY_PAIR_JOIN: " + ",
  RESULT_SUMMARY_PAIRS_SEP: ", ",
  PAIR_ONLY_NOTICE: "병용금기는 두 약씩 짝으로 확인해요. 세 약 이상을 함께 먹을 때의 규칙은 자료에 따로 없어요.",
  REST_FOLD_LINE: "나머지 확인 {n}건: 금기·주의 목록에 없음(안전하다는 뜻이 아님)",
  REST_FOLD_OPEN: "펼치기",
  REST_FOLD_CLOSE: "접기",
  PAIR_REF_LINE: "병용금기 짝 {n}건에 포함",
  DOSE_CAUTION_DESC: "하루 최대량이 정해진 성분이에요. 오늘 이미 드신 약이 있으면 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",
  // 근거 상세 안내 줄·등급 정의 블록
  GRADE_DEF_TITLE: "임부금기 {grade}등급이란?",
  GRADE_DEF_PHARMACIST_ADVICE: "등급의 뜻이 궁금하면 약국·약사에게 물어보세요.",
  GRADE_MISMATCH_NOTE: "파일 자료와 실시간 조회의 등급이 달라요. 어느 쪽이 맞는지 정하지 않고 둘 다 출처와 함께 보여 드려요.",
  DOSE_QUOTE_NOTICE: "허가사항 원문 인용이며 복용 지시가 아닙니다. 복용량은 약사·의사에게 확인하세요.",
  LABEL_ONE_LINE: "허가사항: 식약처가 의약품을 허가할 때 정한 효능·효과, 용법·용량, 사용상 주의사항이에요.",
  EASY_TEXT_MISSING: "{drug}은 전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요",
  // 성분 칩 상태 글자(`ingredients[].state_labels[]`)
  INGR_STATE_CAUSE: "금기 원인",
  INGR_STATE_PAIR_CAUSE: "병용금기 원인",
  INGR_STATE_DUP: "중복",
  // 스트림 오류 문구(`error.message`)와 공공 API 실패 배너(`notice`)
  ERROR_INTERNAL: "잠시 뒤 다시 시도해 주세요. 보낸 질문은 그대로 있어요.",
  ERROR_TIMEOUT: "시간 안에 답을 마치지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  ERROR_UPSTREAM_UNAVAILABLE: "지금은 확인에 필요한 곳에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  NOTICE_API_FAIL: "실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.",
  MISSING_SEARCH_MISS: "허가사항에서 관련 문장을 찾지 못했어요",
  // 미확보 나머지 원인(FE-IMPL-06 추가, `{drug}`는 fixture가 합성 이름으로 채운다)
  MISSING_OUT_OF_SCOPE: "{drug}은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요",
  MISSING_ABSENT: "{drug} 허가사항에는 이 항목이 따로 적혀 있지 않아요",
  MISSING_FETCH_FAIL: "지금은 허가사항을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요",
  // 미확보 박스 안의 약사 확인 권고(`{drugs}`는 fixture가 채우고 "을(를)"은 받침으로 고른다)
  PHARMACIST_ADVICE: "복용 전에 꼭 약국·약사에게 {drugs}을(를) 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.",
  // 검증 폴백 요약 2종(날짜·자료 이름이 없을 때의 문장)
  FALLBACK_NONE_NO_SCOPE: "검색한 자료에서는 확인하지 못했어요. 정확한 확인은 약국·약사에게 하세요.",
  FALLBACK_SOME_NO_DATE: "공공 자료에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요.",
  // 검증 폴백(확인된 항목 있음): 자료마다 이름과 기준일(`fallback_summary`, FE-IMPL-06b: 서버가 실제로 고르는 문장)
  FALLBACK_SOME_CONFIRMED: "{datasets}에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요.",
  FALLBACK_SOME_DATASET_DATED: "{label}(기준일 {doc_date})",
  NO_EVIDENCE: "근거 문장을 찾지 못함",
  // 쌍 확인 불가(Result-NoEvidence6c): 줄 글자로 한 번만 온다(AG-08 뒤 `notes[]`에 같은 문장이 오지 않는다)
  PAIR_NOT_CHECKED: "이 약과 함께 먹어도 되는지는 식약처·한국의약품안전관리원 자료에서 확인하지 못했어요. 안전하다는 뜻이 아니에요.",
  LIMIT_REACHED: "답을 정리하다 시간이 다 되어 여기까지 확인한 결과만 보여 드려요. 확인하지 못한 항목은 약국·약사에게 물어보세요.",
  // 오탈자 보정 고지(`name_corrections[].text`, AG-10-02 A). 서버가 `{input}`·`{name}`을 채워 완성한 문장으로 온다(fixture는 `fillCorrection`)
  TYPO_CORRECTED_LINE: "'{input}' → '{name}': 이름이 비슷한 이 약으로 보고 확인했어요. 찾으시는 약이 아니면 약 이름을 다시 알려 주세요.",
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
  "복용량은 정해 드릴 수 없어요. 개인의 나이·몸 상태에 맞는 양을 고르는 것은 진단·처방에 해당해 이 서비스가 하지 않아요. 약사·의사에게 확인하세요. 허가사항의 용법·용량은 근거 상세에서 원문으로 볼 수 있어요.";
export const SOURCE_KIND_FILE = "공식 파일 기준이에요";
// provenance.SOURCE_KIND_PREFIX[FILE]. 판정 줄의 `source_label`은 `badge(source_kind, dataset_key)` = `{종류} · {자료 약칭}`이다
// (finalize._source_label: dataset_key가 있으면 이 표지, 없을 때만 SOURCE_KIND_TEXT)
export const SOURCE_PREFIX_FILE = "공식 파일";

// 후보가 여럿인 되묻기 질문의 꼬리(AG-05-10 A): `fixed_phrases.CLARIFY_MANY_CANDIDATES`에서 앞의 `'{drug}'`를 뗀 글자.
// `router._clarify`는 `CLARIFY_MANY_CANDIDATES.format(drug=t.raw)`로 만든다(fixture는 앞에 합성 이름을 붙인다)
export const CLARIFY_TAIL = PHRASES.CLARIFY_MANY_CANDIDATES.slice("'{drug}'".length);

// 되묻는 이름이 둘 이상일 때의 질문(FE-09-02 A 승인 원문, 2026-11-19): `'{A}', '{B}'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?`(물음표 1개).
// 백엔드 상수는 Agent 쪽 브랜치(`feature/FE-09-agent-clarify`)가 더한다. 그 브랜치가 병합되기 전이라 `PHRASES`(백엔드 상수와 글자 단위로 맞추는 표)에 넣지 않고
// 승인 원문을 여기 따로 둔다(병합 뒤 `PHRASES`로 옮겨 상수와 맞춘다)
export const CLARIFY_MULTI_TAIL = "에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?";
export const clarifyMultiQuestion = (names: readonly string[]) => `${names.map((name) => `'${name}'`).join(", ")}${CLARIFY_MULTI_TAIL}`;

// 출처 표 값: backend/app/tools/provenance.py PUBLISHER["kids"](= backend/app/db/loaders.py SRC_KIDS), DATASET_LABELS
export const PUBLISHER_KIDS = "한국의약품안전관리원";
export const DATASET_CONTRA_PAIR = "병용금기 파일";
export const DATASET_PREGNANCY = "임부금기 파일";
export const DATASET_AGE = "연령금기 파일";
export const DATASET_DUR_INGR = "DUR 성분정보 API";
export const DATASET_PRMSN = "의약품 허가정보";
export const PUBLISHER_MFDS = "식약처"; // PUBLISHER["mfds"]
/** fixed_phrases.FALLBACK_SOME_DATASET_SEP(자료가 여럿일 때 사이 글자) */
export const FALLBACK_SOME_DATASET_SEP = "·";
/** finalize의 약 이름 잇기(`" · ".join(names)`): 쌍 줄 머리·약사 확인 권고의 `{drugs}` */
export const NAME_JOIN = " · ";

// ---- AG-08·BE-06-13~17 반영(FE-IMPL-08)
/** provenance.SOURCE_KIND_PREFIX: 근거 항목의 출처 종류 글자(`detail[].source_kind_label`) */
export const SOURCE_KIND_PREFIX = { API_DIRECT: "공식 자료", FILE: "공식 파일", CORPUS_QUOTE: "공식 문서" } as const;
/** fixed_phrases.GRADE_DEF_MISSING_TEXT["FETCH_FAIL"](`{grade}`는 fixture가 채운다) */
export const GRADE_DEF_MISSING_FETCH_FAIL = "지금은 임부금기 {grade}등급의 뜻(고시 원문)을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요.";
/** fixed_phrases.GRADE_DEF_MISSING_TEXT["OUT_OF_SCOPE"](원문 자료가 아직 준비되지 않은 경우, PRD-15-03) */
export const GRADE_DEF_MISSING_OUT_OF_SCOPE = "임부금기 {grade}등급의 뜻(고시 원문)을 아직 준비하지 못했어요.";
/** fixed_phrases.CAUTION_LABELS["dose"](용량주의 성분이 든 줄의 덧붙임 글자, AG-22-02 B ③) */
export const CAUTION_DOSE = "하루 최대량 주의 성분 포함";
/** fixed_phrases.CAUTION_LABELS["dup_ingredient"](성분 중복 줄의 글자, AG-08-10 B) */
export const CAUTION_DUP_INGREDIENT = "성분 중복";
/** provenance.FLAG_NOTES["CODE_NOT_LINKED"](= fixed_phrases.CODE_NOT_LINKED): 코드가 이어지지 않아 확인하지 못한 줄의 안내(AG-08에서 문구 변경) */
export const CODE_NOT_LINKED = "금기 목록에서 확인하지 못했지만, 안전하다는 뜻이 아니에요. 약사에게 확인하세요";
/**
 * 실시간 확인 꼬리표 노트(`findings[].notes[]`, `finalize._notes` → `provenance.api_flag_note`): FLAG_NOTES["API_FAIL"]과 API_REASON_NOTES[API_REASON_NO_CODE].
 * 화면은 본문에 그리지 않고 근거 상세에만 둔다(FE-11-10 A). 생성 상수 `lib/fixed/phrases.generated.API_FLAG_NOTES`와 같은 글자다
 */
export const API_FAIL_NOTE = "실시간 확인을 하지 못함(파일 기준 결과는 그대로예요)";
export const API_NO_CODE_NOTE = "실시간 확인을 하지 못함(이 성분은 실시간 조회에 쓸 코드가 없어요. 파일 기준 결과는 그대로예요)";
/** schemas.DOSE_SECTION: 이 항목의 원문 인용 아래에만 인용 고지(`quote_notice`)가 온다 */
export const DOSE_SECTION = "용법용량";

/** `josa.fill`과 같은 규칙(한글 이름만: 마지막 글자의 받침 유무). fixture의 합성 이름은 모두 한글로 끝난다 */
export function fillJosa(template: string, key: string, value: string): string {
  const last = value.charCodeAt(value.length - 1);
  const batchim = last >= 0xac00 && last <= 0xd7a3 && (last - 0xac00) % 28 !== 0;
  return template.replace(`{${key}}을(를)`, `${value}${batchim ? "을" : "를"}`).replace(`{${key}}`, value);
}

/**
 * `router._single_question`과 같은 규칙: `CLARIFY_PRIOR_PICK.format(drug=<이전 선택의 사전 제품명>)`.
 * 서버는 이 문장에 `josa.fill`을 적용하지 않아 "'이름'을(를)"이 그대로 나간다(2026-11-19 밤 FE 확인, 백엔드 정정 후보). fixture는 서버가 보내는 글자 그대로 둔다
 */
export const fillPriorPick = (name: string) => PHRASES.CLARIFY_PRIOR_PICK.replace("{drug}", name);

/** `finalize._result_summary`·`schemas.result_summary_text`와 같은 규칙(걸린 짝이 있을 때): 틀에 약 수·짝 수·짝 이름을 넣는다 */
export function resultSummaryFound(nDrugs: number, pairs: ReadonlyArray<readonly [string, string]>): string {
  const joined = pairs.map((pair) => pair.join(PHRASES.RESULT_SUMMARY_PAIR_JOIN)).join(PHRASES.RESULT_SUMMARY_PAIRS_SEP);
  return PHRASES.RESULT_SUMMARY_FOUND.replace("{n}", String(nDrugs)).replace("{k}", String(pairs.length)).replace("{pairs}", joined);
}

/** `finalize`가 보정 고지를 만드는 규칙과 같다: `TYPO_CORRECTED_LINE.format(input=…, name=…)` → `{input, name, text}` */
export function fillCorrection(input: string, name: string): { input: string; name: string; text: string } {
  return { input, name, text: PHRASES.TYPO_CORRECTED_LINE.replace("{input}", input).replace("{name}", name) };
}

/** `fixed_phrases.ingredient_state_labels`와 같은 규칙: 병용금기 원인 → 금기 원인(임부·연령) → 중복 */
export function ingredientStateLabels(contraKinds: readonly string[], dup: boolean): string[] {
  const out: string[] = [];
  if (contraKinds.includes("contra_pair")) out.push(PHRASES.INGR_STATE_PAIR_CAUSE);
  if (contraKinds.some((kind) => kind === "pregnancy" || kind === "age")) out.push(PHRASES.INGR_STATE_CAUSE);
  if (dup) out.push(PHRASES.INGR_STATE_DUP);
  return out;
}
