"""고정 문구 코드 상수(AG-08). 프롬프트가 아니라 코드가 맡는다. 화면·mock·프로토타입의 문구는 여기서만 나온다.

- 원본: `P2-doc/PJ2-Agent-Harness.md` 3.4절 표, `P2-doc/PJ2-RFP.md` 7장(고지), `tickets/doc/PRD-11.md` §6.6~6.7,
  `tickets/doc/PRD-09.md`(표지), `tickets/doc/PRD-14.md`(미식별), `tickets/doc/PRD-15.md`(등급 정의 블록).
- **초안 표시**: 사용자 승인 전인 문구는 아래 `DRAFT_KEYS`에 이름을 적었다. 2026-11-12 승인분(AG-08-04~18, Recap 0-1·0-E:
  `tickets/agent/AG-08.md` §5 "승인 문구 원본" 표, 하네스 3.4절 표)과 2026-11-16 문구 승인 17줄은 목록에서 뺐다. 거절 문구는 `REFUSE_DRAFT_KEYS`가 초안인 이유 키다.
- 내부 용어(상태명·`L3`·"약 이름 사전"·"공식 약 목록")는 화면 문구에 넣지 않는다(시험이 막는다).
- 응급 안내는 119와 약국·약사 안내만 쓴다(RFP-19-01 A, 출처 미확인 연락처 금지).
"""

from __future__ import annotations

from app.tools.provenance import API_REASON_NOTES as _API_REASON_NOTES
from app.tools.provenance import API_REASON_NOTES_APPROVED, FLAG_NOTES, NOT_SAFE

# --------------------------------------------------------------------------- 119·고지·약사 권고
EMERGENCY_119 = "응급 상황일 수 있어요. 지금 바로 119에 전화하세요."  # 원문 승인(AG-08-04 A). 119 외 연락처·처치는 쓰지 않는다
# 넓은 폭 응급 보조 문장(FE-07-15 A, 0-E 5번 승인). 연락처가 아니라 방법 안내이며 프런트가 넓은 폭에서만 보인다
EMERGENCY_119_WIDE = "컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요."
EMERGENCY_119_TEL = "tel:119"

# 시작 화면 안내 2종(FE-01-24 A, 2026-11-16 문구 승인 1·2번). 프런트는 `frontend/scripts/gen-fixed-phrases.mjs`가 이 파일을
# 읽어 생성한 값만 쓴다(FE-01-19 A). 생성기가 `^NAME = "..."` 한 줄 글자만 읽으므로 이어 붙이기·f-string으로 바꾸지 않는다.
# 응급 안내: 승인된 `EMERGENCY_119` 말투에 맞춤, 119 외 연락처 금지(RFP-19-01 A)
START_EMERGENCY_119 = "응급 상황이면 지금 바로 119에 전화하세요."
# 외부 AI 전송 고지(RFP-24-01, PJ2-RFP.md 7장 고지 항목·FE-02 §2): 질문·프로필 전송, 이 서비스는 질문 비저장,
# 제공자 쪽 보관은 "될 수 있어요"로만 쓴다(학습 사용 여부·보관 기간은 단정하지 않는다)
START_EXTERNAL_AI_NOTICE = "질문과 입력한 프로필은 답을 만들기 위해 외부 AI(OpenAI)로 보내요. 이 서비스는 질문 내용을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요."

# PJ2-RFP.md 7장 고지 항목(따옴표 안 문구 그대로)
DISCLAIMER_PARTS = (
    "공공데이터 기반 정보 제공이며 진단·처방이 아님",
    "금기 목록에 없다는 것이 안전하다는 뜻이 아님",
    "요양기관의 DUR 점검을 대체하지 않음",
)
DISCLAIMER = " · ".join(DISCLAIMER_PARTS)

# 모든 응답에 붙는 고정 문구(`fixed_notice`): 금기 목록에 없음 ≠ 안전, 근처 약국·약사 확인
NOT_SAFE_NOTICE = "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요."
PHARMACIST_CHECK_NOTICE = "근처 약국·약사에게 확인하세요."
FIXED_NOTICE = f"{NOT_SAFE_NOTICE} {PHARMACIST_CHECK_NOTICE}"

# 미확보 항목의 약사 확인 권고(PRD-11 §6.7). `{drugs}`는 약 이름 나열. "을(를)"은 `josa.fill`이 받침으로 고른다(AG-08-15 B)
PHARMACIST_ADVICE = "복용 전에 꼭 약국·약사에게 {drugs}을(를) 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."
PHARMACIST_ADVICE_NO_NAMES = "복용 전에 꼭 약국·약사에게 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."  # 약 이름이 없을 때(2026-11-16 승인)
PHARMACIST_ADVICE_FIXED = "확인하지 못한 항목이 있어요. 복용 전에 꼭 약국·약사에게 확인하세요."  # 접히지 않는 고정 영역 한 줄(PRD-11 §6.7)

# --------------------------------------------------------------------------- 상태별 항목 문구
NOT_LISTED = "금기 목록에 없음(안전하다는 뜻이 아님)"
UNIDENTIFIED = "약을 찾지 못해 확인하지 못함"
NO_EVIDENCE = "근거 문장을 찾지 못함"
NO_PRODUCT_INFO = "제품 단위 정보(제품 연령 문장·허가사항·제형) 없음. 봉투의 제품명을 알려 주시면 더 확인할 수 있어요"  # PRD-10-04: "허가 라벨"→"허가사항"
EASY_TEXT_MISSING = "{drug}은 전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요"
LABEL_ONE_LINE = "허가사항: 식약처가 의약품을 허가할 때 정한 효능·효과, 용법·용량, 사용상 주의사항이에요."  # PRD-10-04 한 줄 설명

# 미식별 박스(PRD-14-01·02·04)
UNIDENTIFIED_WHY = "식약처·한국의약품안전관리원 자료에서 찾지 못했어요"
UNIDENTIFIED_RETRIED = "표기를 바꿔 한 번 더 찾아봤어요"
UNIDENTIFIED_NEXT = "봉투나 상자에 적힌 제품명을 그대로 다시 알려 주세요"  # 원문 승인(AG-08-05 A)
UNIDENTIFIED_NOT_SAFE = "찾지 못했다는 뜻이며 안전하다는 뜻이 아니에요"  # 원문 승인(AG-08-06 A)
# 근거 없음 카드 보조줄(UI-019, 0-E 7-1 승인). "을(를)"은 `josa.fill`이 고른다
UNIDENTIFIED_SUB_LINE = "{drug}을(를) 찾지 못해 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요."
# 식별된 약 줄(AG-08-12 B, PRD-14 §5.2): 표지 글자 "찾음" + 보조줄(성분 이름을 `IDENTIFIED_SUB_SEP`로 이음). "금기 목록에 없음"은 쓰지 않는다
IDENTIFIED_LINE = "찾음"
IDENTIFIED_SUB_SEP = " · "
# 정보가 없어 확인하지 못한 종류의 줄(FE-07-16 B, 0-E 6번 승인). 승인 문장은 임부금기 한 가지이고 틀은 기록용이다
NOT_CHECKED_TEMPLATE = "{info}를 알 수 없어 {kind}는 확인하지 못했어요"
PREGNANCY_NOT_CHECKED = "임신 여부를 알 수 없어 임부금기는 확인하지 못했어요."
NOT_CHECKED_LINES = {"pregnancy": PREGNANCY_NOT_CHECKED}  # 금기 종류 키 → 줄. 승인 문장이 없는 종류는 줄을 만들지 않는다
# 나이를 특정할 수 없을 때 나이별 연령금기 원문 값 위에 두는 안내(FE-07-18, 0-E 3번 승인). 판정이 아니다
AGE_INFO_LINE = "나이를 특정할 수 없어 판정하지 않고, 이 약의 나이별 연령금기 기준을 원문 그대로 보여 드려요."
# 되묻기·오탈자 카드 안내(UI-620, 0-E 7-5 승인)
CLARIFY_PICK_LINE = "어느 제품인지 고르면 금기를 확인해 드려요."

# 성분코드 없음·참고 전용·이름 모호·조회 실패·잘림: 판정 문구가 아니다
CODE_NOT_LINKED = FLAG_NOTES["CODE_NOT_LINKED"]
AMBIGUOUS_NAME = FLAG_NOTES["AMBIGUOUS_NAME"]
REFERENCE_ONLY = FLAG_NOTES["REFERENCE_ONLY"]
LOOKUP_FAILED = "조회하지 못해 확인하지 못함. " + NOT_SAFE + ". 약사에게 확인하세요"  # 하네스 3.4절 표(2026-11-12 승인)
TRUNCATED = "원문이 길어 일부만 보여 드려요. 전체는 약사에게 확인하세요"  # 하네스 3.4절 표(2026-11-12 승인)
# 판정 문구 아님. "은(는)"은 `josa.fill`이 받침으로 고른다(2026-11-16 문구 승인 3번 "조사 자동")
REFERENCE_ONLY_LINE = "참고: {drug}은(는) 다른 제형에서 금기 목록에 있어요. 이 제품에 대한 판정은 아니에요"

# 도구 꼬리표 → 한 줄(`FLAG_NOTES` 재사용). 키는 화면에 나가지 않는다
FLAG_LINES = {
    "API_SAME": FLAG_NOTES["API_SAME"],
    "FILE_ONLY": FLAG_NOTES["FILE_ONLY"],
    "API_ONLY": FLAG_NOTES["API_ONLY"],
    "API_FAIL": FLAG_NOTES["API_FAIL"],
    "API_PAIR_INCOMPLETE": FLAG_NOTES["API_PAIR_INCOMPLETE"],
    "CODE_NOT_LINKED": CODE_NOT_LINKED,
    "AMBIGUOUS_NAME": AMBIGUOUS_NAME,
    "REFERENCE_ONLY": REFERENCE_ONLY,
    "LOOKUP_FAILED": LOOKUP_FAILED,
    "TRUNCATED": TRUNCATED,
}
# 입력 코드 형식 꼬리표(하네스 3.4절, 2026-11-16 승인): 코드명은 화면에 노출하지 않는다
INVALID_CODE = "입력한 약을 식약처·한국의약품안전관리원 자료에서 찾지 못했어요. 약 이름을 다시 알려 주세요."
PAIR_NOT_CHECKED = "이 약과 함께 먹어도 되는지는 식약처·한국의약품안전관리원 자료에서 확인하지 못했어요. 안전하다는 뜻이 아니에요."

# --------------------------------------------------------------------------- 미확보 4종(`missing_reason`, PRD-11 §6.6)
MISSING_OUT_OF_SCOPE = "{drug}은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요"
MISSING_ABSENT = "{drug} 허가사항에는 이 항목이 따로 적혀 있지 않아요"
MISSING_FETCH_FAIL = "지금은 허가사항을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요"
MISSING_SEARCH_MISS = "허가사항에서 관련 문장을 찾지 못했어요"
MISSING_TEXT = {
    "OUT_OF_SCOPE": MISSING_OUT_OF_SCOPE,
    "ABSENT": MISSING_ABSENT,
    "FETCH_FAIL": MISSING_FETCH_FAIL,
    "SEARCH_MISS": MISSING_SEARCH_MISS,
}

# 등급 정의 블록 미확보(PRD-15-03, 후보). SEARCH_MISS 없음(청크 ID 조회)
GRADE_DEF_MISSING_TEXT = {
    "FETCH_FAIL": "지금은 임부금기 {grade}등급의 뜻(고시 원문)을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요.",
    "OUT_OF_SCOPE": "임부금기 {grade}등급의 뜻(고시 원문)을 아직 준비하지 못했어요.",
}
GRADE_DEF_PHARMACIST_ADVICE = "등급의 뜻이 궁금하면 약국·약사에게 물어보세요."
GRADE_DEF_TITLE = "임부금기 {grade}등급이란?"  # 등급 정의 블록 제목(PRD-09 §7.2·§7.3 글자 그대로, BE-06-16 A)

# 근거 상세 안내 줄(0-E 승인, AG-08-16 A)
GRADE_MISMATCH_NOTE = "파일 자료와 실시간 조회의 등급이 달라요. 어느 쪽이 맞는지 정하지 않고 둘 다 출처와 함께 보여 드려요."  # UI-020, 7-2
INGR_CODE_MISSING_TEXT = {  # UI-021, 7-3: 성분코드 미확보 원인별 2종
    "ABSENT": "성분코드는 자료에 적혀 있지 않아요",
    "FETCH_FAIL": "성분코드는 지금 불러오지 못했어요",
}
DOSE_QUOTE_NOTICE = "허가사항 원문 인용이며 복용 지시가 아닙니다. 복용량은 약사·의사에게 확인하세요."  # UI-611, 7-4(RFP-21-03 원문, 합니다체)

# --------------------------------------------------------------------------- `source_kind` 표지(내부 용어 없음)
SOURCE_KIND_TEXT = {
    "API_DIRECT": "공식 자료에서 직접 가져왔어요",
    "FILE": "공식 파일 기준이에요",
    "CORPUS_QUOTE": "공식 문서에서 찾은 문장이에요",
}

# --------------------------------------------------------------------------- `FOUND` 표지(PRD-09·15). 순서 병용 → 임부 → 연령
BADGE_PAIR = "삐! 병용금기"
BADGE_PREGNANCY = "삐! 임부금기 {grade}등급"
BADGE_PREGNANCY_M = "삐! 임부금기 M등급"
BADGE_PREGNANCY_M_NOTE = "적응증에 따라 등급이 달라요"
BADGE_AGE = "삐! 연령금기"
BADGE_ORDER = ("contra_pair", "pregnancy", "age")  # `kind` 키 순서(화면이 색을 고르는 기준도 이 키)
# 등급 불일치 출처 꼬리(파일 → 성분 API). 합친 배지는 만들지 않는다
BADGE_SOURCE_TAIL = {"FILE": "(파일)", "API_DIRECT": "(성분 API)"}
BADGE_TAIL_ORDER = ("FILE", "API_DIRECT")
# 금기가 아닌 주의 종류(2026-11-16 승인). "삐!"는 금기 발견 전용이라 쓰지 않는다
# `dup_ingredient`는 PRD-09 §7.4 글자(AG-08-10 B, 확정). 나머지 셋은 2026-11-16 승인(문구 승인 11~13번)
CAUTION_LABELS = {"dose": "용량 주의", "lactation": "수유부 주의", "elderly": "노인 주의", "dup_ingredient": "성분 중복"}

# 성분 칩 상태 글자(BE-06-13 A, PRD-09 G11·§7.1, 디자인 보드 글자 그대로). 화면은 받은 글자를 그대로 그린다
INGR_STATE_CAUSE = "금기 원인"
INGR_STATE_PAIR_CAUSE = "병용금기 원인"
INGR_STATE_DUP = "중복"


def ingredient_state_labels(contra_kinds: list[str] | tuple[str, ...], dup: bool) -> list[str]:
    """성분 하나의 상태 글자 목록(없으면 빈 목록). 순서: 병용금기 원인 → 금기 원인(임부·연령) → 중복.

    금기 종류 키(`BADGE_ORDER`)만 원인으로 본다. 주의 종류(용량·수유부 등)는 "금기 원인"이라고 하지 않는다.
    """
    kinds = [k for k in BADGE_ORDER if k in contra_kinds]
    out: list[str] = []
    if "contra_pair" in kinds:
        out.append(INGR_STATE_PAIR_CAUSE)
    if any(k != "contra_pair" for k in kinds):
        out.append(INGR_STATE_CAUSE)
    if dup:
        out.append(INGR_STATE_DUP)
    return out

# --------------------------------------------------------------------------- 입구 거절(`guardrail.classify_scope` 이유 키)
# `STOP_DOSE_CHANGE`·`ASSESS_STATE`는 2026-11-11 사용자 결정 문구다(하네스 4.4절, AG-08-07 A). 나머지 이유 키는 2026-11-16 승인(문구 승인 4~10번)
REFUSE_MESSAGES = {
    "STOP_DOSE_CHANGE": "약을 줄이거나 끊는 방법과 시기는 알려 드릴 수 없어요. 의사가 줄이라고 했더라도 어떻게 줄일지는 처방한 그 의사나 약사에게 다시 확인하세요. 이 서비스는 지금 상태로 약을 줄여도 되는지 판단(진단·평가)해 드릴 수 없어요.",
    "ASSESS_STATE": "지금 상태로 약을 줄이거나 끊어도 되는지는 진찰과 검사가 필요한 판단이라 이 서비스가 해 드릴 수 없어요. 처방한 의사나 약사와 상의하세요.",
    "HIDE_FROM_DOCTOR": "먹는 약은 의사·약사에게 숨기지 말고 모두 알려 주세요. 숨겨 달라는 요청은 도와드릴 수 없어요.",
    "DIAGNOSIS": "진단은 할 수 없어요. 증상이 걱정되면 의사·약사에게 확인하세요. 약 이름이 있으면 금기 여부는 공공 자료로 확인해 드려요.",
    "PRESCRIPTION": "처방은 할 수 없어요. 처방은 의사가 해요. 가진 약의 금기 여부는 공공 자료로 확인해 드려요.",
    "DOSAGE": "복용량은 정해 드릴 수 없어요. 약사·의사에게 확인하세요. 허가사항의 용법·용량은 근거 상세에서 원문으로 볼 수 있어요.",
    "PERSONAL_RECORD": "개인 의료기록은 처리하지 않아요. 약 이름을 알려 주시면 공공 자료로 확인해 드려요.",
    "OUT_OF_SCOPE": "이 질문은 도와드릴 수 없는 범위예요. 약 이름을 알려 주시면 공공 자료로 금기 여부를 확인해 드려요.",  # 알 수 없는 이유 키의 대체 문구
    "IGNORE_PREVIOUS": "지시를 바꾸라는 요청은 따르지 않아요. 약 이름과 궁금한 점만 다시 적어 주세요.",
}

# 거절 이유가 여럿일 때 문구를 잇는 구분자(AG-08-08 A: 모두 보인다, 위 표의 정의 순서). 문장이 아니라 구분자다
REFUSE_JOIN = " "

REFUSE_APPROVED_KEYS = tuple(REFUSE_MESSAGES)  # 2026-11-16 전부 승인(문구 승인 4~10번)
REFUSE_DRAFT_KEYS = tuple(k for k in REFUSE_MESSAGES if k not in REFUSE_APPROVED_KEYS)

# 사용자 승인 전인 상수 이름. 새 문구를 더하면 승인 전까지 여기에 적는다.
# 2026-11-12 승인으로 뺀 것: EMERGENCY_119(AG-08-04)·UNIDENTIFIED_NEXT(05)·UNIDENTIFIED_NOT_SAFE(06)·LIMIT_REACHED(09)·
# PHARMACIST_ADVICE_FIXED(11)·GRADE_DEF_MISSING_TEXT(14)·IDENTIFIED_LINE(12 B), LOOKUP_FAILED·TRUNCATED·FALLBACK_SOME_CONFIRMED·
# FALLBACK_NONE_SCOPE_DOC(Recap 0-1, 하네스 3.4절 표).
# 2026-11-16 문구 승인 표 17줄(3번만 조사 자동, 나머지 원문 승인)로 뺀 것: START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE·
# REFERENCE_ONLY_LINE·REFUSE_MESSAGES·CAUTION_LABELS·PHARMACIST_ADVICE_NO_NAMES·BLOCKED_NO_SOURCE_KIND·INVALID_CODE·PAIR_NOT_CHECKED.
# 2026-11-17 AG-10-02 A 승인으로 뺀 것: TYPO_CORRECTED_LINE(오탈자 보정 고지, 원문 승인).
# 2026-11-18 AG-01-11 A(2026-11-17 사용자 "권장대로", 문구 초안 4개 원문 승인) 코드 반영으로 뺀 것: API_REASON_NOTES(AG-01-10 A 실시간
# 확인 못 한 사유별 노트 3종, `provenance.API_REASON_NOTES_APPROVED = True`)·EMERGENCY_ASK_DRUG_NAME(AG-09 §2 TC-11 응급 약 이름 묻기).
# 지금은 초안이 없다. 새 문구를 더하면 승인 전까지 이 튜플에 이름을 적는다(`API_REASON_NOTES`는 provenance 쪽 스위치가 False면 자동으로 돌아온다).
DRAFT_KEYS: tuple[str, ...] = (*(() if API_REASON_NOTES_APPROVED else ("API_REASON_NOTES",)),)

# 응급 질문에 약 이름이 없을 때 119 안내 아래에 붙여 약 이름을 묻는 문장(AG-09 §2, `P2-doc/PJ2-가설검증.md` TC-11).
# **원문 승인(AG-01-11 A, 2026-11-17)**: `finalize(emergency=True, emergency_no_drug=True)`가 요약 끝에 붙인다(거절·상한·검증 폴백 경로 제외).
# 119 안내는 그대로 맨 위다. 119 외 연락처·처치·가부 표현 없음(RFP-19-01 A). 글자 하나도 바꾸지 않는다(`test_ag09_no_evidence.py`가 원문 고정).
EMERGENCY_ASK_DRUG_NAME = "어떤 약을 먹었는지 약 이름을 알려 주시면 금기 여부를 확인해 드려요."

# 실시간 확인을 하지 못한 사유별 노트(AG-01-10 A). **원문 승인(AG-01-11 A, 2026-11-17)**: `provenance.api_flag_note`가 항목 `api.reason`에
# 맞는 문구를 고른다(원본은 `provenance.API_REASON_NOTES`, 여기는 같은 값의 복사본). 사유가 없는 항목은 지금까지의 꼬리표 문구 그대로다.
# 키(사유 코드)는 화면에 나가지 않는다: NO_API_CODE = 조회용 코드가 없어 묻지 않음, PARTIAL = 쌍의 한쪽 실패, TRUNCATED = 성분이 많아 일부만 물음.
API_REASON_NOTES = dict(_API_REASON_NOTES)

# 오탈자 보정 고지(AG-10 §2 "OO로 보정하여 검색" 표시, RFP-26-09 A). **원문 승인(AG-10-02 A, 2026-11-17 사용자 "권장대로")**.
# 보정으로 확정한 약의 결과를 보이는 답에는 이 줄이 항상 함께 나간다(`finalize(name_corrections=...)` → `/chat` 응답 `name_corrections[].text`).
# 이름 뒤에 조사를 붙이지 않는 꼴이다(오탈자 조각은 받침 판단이 어긋날 수 있다). 가부·안전 표현 없음.
TYPO_CORRECTED_LINE = "'{input}' → '{name}': 이름이 비슷한 이 약으로 보고 확인했어요. 찾으시는 약이 아니면 약 이름을 다시 알려 주세요."

# 상한 도달 안내(원문 승인, AG-08-09 A): 모델 호출 상한으로 끝났을 때 LLM 요약 없이 코드가 붙인다
LIMIT_REACHED = "답을 정리하다 시간이 다 되어 여기까지 확인한 결과만 보여 드려요. 확인하지 못한 항목은 약국·약사에게 물어보세요."
# 검증 폴백(두 번째 검증 실패) 요약 문구 2종(AG-01·AG-08, 사용자 승인 2026-11-11). 모델은 쓰지 않는다.
# 확인된 항목(FOUND·NOT_LISTED) 0개 → NONE, 하나라도 있으면 SOME. 날짜·시각은 항목 값만 쓰고 없으면 해당 부분을 생략한다.
FALLBACK_NONE_CONFIRMED = "검색한 자료({scope})에서는 확인하지 못했어요. 정확한 확인은 약국·약사에게 하세요."  # {scope}: 아래 조각
FALLBACK_NONE_SCOPE_API = "API 조회 {api_time}"
FALLBACK_NONE_SCOPE_DOC = "{label} 기준일 {doc_date}"  # AG-08-03 B: 자료(`label`)마다 따로. 자료 이름을 모르면 아래 라벨
FALLBACK_NONE_DOC_LABEL = "문서"
FALLBACK_NONE_NO_SCOPE = "검색한 자료에서는 확인하지 못했어요. 정확한 확인은 약국·약사에게 하세요."  # 날짜·시각 모두 없을 때
# SOME: 확인된 자료마다 이름과 기준일을 나열한다(AG-08-03 B, 사용자 2026-11-11: 자료마다 기준일이 달라 한쪽에 편승할 수 없다). 2026-11-12 승인(Recap 0-1)
FALLBACK_SOME_CONFIRMED = "{datasets}에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요."
FALLBACK_SOME_DATASET_DATED = "{label}(기준일 {doc_date})"
FALLBACK_SOME_DATASET_SEP = "·"
FALLBACK_SOME_NO_DATE = "공공 자료에서 확인된 내용만 아래에 보여 드려요. 이 서비스가 확인하지 못한 부분은 약국·약사에게 확인하세요."  # 자료 이름을 모를 때
BLOCKED_NO_SOURCE_KIND = "출처 종류를 알 수 없는 근거는 보여 드리지 않아요"  # 근거 항목 차단 안내(2026-11-16 승인)

# --------------------------------------------------------------------------- 스트림 오류·상단 배너(0-E 1-1~1-3·2번 승인, BE-06 ⓐⓑ)
# 오류 카드 본문. 키는 `events.ERROR_CODES`와 같다. 1-1은 프런트 `ERROR_BODY_RETRY`와 같은 문장이다(소유 위치는 승인 밖, 보고 선택지)
ERROR_INTERNAL = "잠시 뒤 다시 시도해 주세요. 보낸 질문은 그대로 있어요."
ERROR_TIMEOUT = "시간 안에 답을 마치지 못했어요. 잠시 뒤 다시 시도해 주세요."
ERROR_UPSTREAM_UNAVAILABLE = "지금은 확인에 필요한 곳에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요."
ERROR_MESSAGES = {"INTERNAL_ERROR": ERROR_INTERNAL, "TIMEOUT": ERROR_TIMEOUT, "UPSTREAM_UNAVAILABLE": ERROR_UPSTREAM_UNAVAILABLE}
# 공공 API 실패 상단 배너(`notice`, BE-06-06 A). 파일 기준 결과는 그대로다
NOTICE_API_FAIL = "실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요."

# --------------------------------------------------------------------------- 스트림 진행 표시(BE-06-09 A, 2026-11-12)
# `progress` 이벤트의 `label`은 이 표에서만 나간다(서버가 준다, 프런트 상수 없음). 문구는 `P2-doc/PJ2-PRD.md` 15.4절
# 로딩 행 "진행 상태(약 찾는 중·금기 확인 중·근거 찾는 중)"의 글자 그대로다(새 문구 아님, 초안 아님). 키는 `stage` 식별자.
PROGRESS_DRUG_LOOKUP = "약 찾는 중"
PROGRESS_CONTRA_CHECK = "금기 확인 중"
PROGRESS_EVIDENCE_SEARCH = "근거 찾는 중"
PROGRESS_LABELS = {
    "drug_lookup": PROGRESS_DRUG_LOOKUP,
    "contraindication_check": PROGRESS_CONTRA_CHECK,
    "evidence_search": PROGRESS_EVIDENCE_SEARCH,
}

# 화면에 나가면 안 되는 내부 용어·폐기 문구(시험용 목록)
FORBIDDEN_SCREEN_TERMS = (
    "UNIDENTIFIED", "NOT_LISTED", "FOUND", "NO_EVIDENCE", "EASY_TEXT_MISSING", "NO_PRODUCT_INFO", "missing_reason",
    "L3", "L1", "약 이름 사전", "공식 약 목록", "원문을 가져오지 못했어요", "허가 라벨", "(서비스의 한계예요)",
    "이 서비스가 쓰는", "단계",
)
