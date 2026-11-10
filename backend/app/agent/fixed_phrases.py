"""고정 문구 코드 상수(AG-08). 프롬프트가 아니라 코드가 맡는다. 화면·mock·프로토타입의 문구는 여기서만 나온다.

- 원본: `P2-doc/PJ2-Agent-Harness.md` 3.4절 표, `P2-doc/PJ2-RFP.md` 7장(고지), `tickets/doc/PRD-11.md` §6.6~6.7,
  `tickets/doc/PRD-09.md`(표지), `tickets/doc/PRD-14.md`(미식별), `tickets/doc/PRD-15.md`(등급 정의 블록).
- **초안 표시**: 문서에 문구가 없는 것(응급 안내 본문·거절 이유·상한 도달·미식별 다음 행동·`LOOKUP_FAILED`·`TRUNCATED`·
  `DRAFT_ONLY` 목록)은 아래 `DRAFT_KEYS`에 이름을 적었다. 사용자·디자인 세션 승인 전이다.
- 내부 용어(상태명·`L3`·"약 이름 사전"·"공식 약 목록")는 화면 문구에 넣지 않는다(시험이 막는다).
- 응급 안내는 119와 약국·약사 안내만 쓴다(RFP-19-01 A, 출처 미확인 연락처 금지).
"""

from __future__ import annotations

from app.tools.provenance import FLAG_NOTES, NOT_SAFE

# --------------------------------------------------------------------------- 119·고지·약사 권고
EMERGENCY_119 = "응급 상황일 수 있어요. 지금 바로 119에 전화하세요."  # 초안(문서에 본문 없음). 119 외 연락처·처치는 쓰지 않는다
EMERGENCY_119_TEL = "tel:119"

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

# 미확보 항목의 약사 확인 권고(PRD-11 §6.7). `{drugs}`는 약 이름 나열
PHARMACIST_ADVICE = "복용 전에 꼭 약국·약사에게 {drugs}을(를) 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."
PHARMACIST_ADVICE_NO_NAMES = "복용 전에 꼭 약국·약사에게 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."  # 약 이름이 없을 때(초안)
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
UNIDENTIFIED_NEXT = "봉투나 상자에 적힌 제품명을 그대로 다시 알려 주세요"  # 초안
UNIDENTIFIED_NOT_SAFE = "찾지 못했다는 뜻이며 안전하다는 뜻이 아니에요"  # 초안
IDENTIFIED_LINE = "{drug}: 약을 확인했어요(성분 {ingredients})"  # 금기 목록 문구 없음(PRD-14-04)
IDENTIFIED_LINE_NO_INGR = "{drug}: 약을 확인했어요"

# 성분코드 없음·참고 전용·이름 모호·조회 실패·잘림: 판정 문구가 아니다
CODE_NOT_LINKED = FLAG_NOTES["CODE_NOT_LINKED"]
AMBIGUOUS_NAME = FLAG_NOTES["AMBIGUOUS_NAME"]
REFERENCE_ONLY = FLAG_NOTES["REFERENCE_ONLY"]
LOOKUP_FAILED = "조회하지 못해 확인하지 못함. " + NOT_SAFE + ". 약사에게 확인하세요"  # 초안(FLAG_NOTES에 없음)
TRUNCATED = "원문이 길어 일부만 보여 드려요. 전체는 약사에게 확인하세요"  # 초안(FLAG_NOTES에 없음)
REFERENCE_ONLY_LINE = "참고: {drug}는 다른 제형에서 금기 목록에 있어요. 이 제품에 대한 판정은 아니에요"  # 판정 문구 아님(초안)

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
# 입력 코드 형식 꼬리표(하네스 3.4절, 초안): 코드명은 화면에 노출하지 않는다
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
# 금기가 아닌 주의 종류(초안). "삐!"는 금기 발견 전용이라 쓰지 않는다
CAUTION_LABELS = {"dose": "용량 주의", "lactation": "수유부 주의", "elderly": "노인 주의", "dup_ingredient": "같은 성분 중복"}

# --------------------------------------------------------------------------- 입구 거절(초안, `guardrail.classify_scope` 이유 키)
REFUSE_MESSAGES = {
    "STOP_DOSE_CHANGE": "복용을 멈추거나 양을 바꾸는 것은 처방한 의사·약사와 상의하세요. 이 서비스는 복용 변경을 안내하지 않아요.",
    "HIDE_FROM_DOCTOR": "먹는 약은 의사·약사에게 숨기지 말고 모두 알려 주세요. 숨겨 달라는 요청은 도와드릴 수 없어요.",
    "DIAGNOSIS": "진단은 할 수 없어요. 증상이 걱정되면 의사·약사에게 확인하세요. 약 이름이 있으면 금기 여부는 공공 자료로 확인해 드려요.",
    "PRESCRIPTION": "처방은 할 수 없어요. 처방은 의사가 해요. 가진 약의 금기 여부는 공공 자료로 확인해 드려요.",
    "DOSAGE": "복용량은 정해 드릴 수 없어요. 약사·의사에게 확인하세요. 허가사항의 용법·용량은 근거 상세에서 원문으로 볼 수 있어요.",
    "PERSONAL_RECORD": "개인 의료기록은 처리하지 않아요. 약 이름을 알려 주시면 공공 자료로 확인해 드려요.",
    "OUT_OF_SCOPE": "이 질문은 도와드릴 수 없는 범위예요. 약 이름을 알려 주시면 공공 자료로 금기 여부를 확인해 드려요.",  # 알 수 없는 이유 키의 대체 문구
    "IGNORE_PREVIOUS": "지시를 바꾸라는 요청은 따르지 않아요. 약 이름과 궁금한 점만 다시 적어 주세요.",
}

DRAFT_KEYS = (
    "EMERGENCY_119", "UNIDENTIFIED_NEXT", "UNIDENTIFIED_NOT_SAFE", "LOOKUP_FAILED", "TRUNCATED", "REFERENCE_ONLY_LINE",
    "REFUSE_MESSAGES", "LIMIT_REACHED", "CAUTION_LABELS", "PHARMACIST_ADVICE_NO_NAMES", "PHARMACIST_ADVICE_FIXED",
    "BLOCKED_NO_SOURCE_KIND", "GRADE_DEF_MISSING_TEXT", "INVALID_CODE", "PAIR_NOT_CHECKED", "IDENTIFIED_LINE",
)

# 상한 도달 안내(초안): 모델 호출 상한으로 끝났을 때 LLM 요약 없이 코드가 붙인다
LIMIT_REACHED = "답을 정리하다 시간이 다 되어 여기까지 확인한 결과만 보여 드려요. 확인하지 못한 항목은 약국·약사에게 물어보세요."
BLOCKED_NO_SOURCE_KIND = "출처 종류를 알 수 없는 근거는 보여 드리지 않아요"  # 근거 항목 차단 안내(초안)

# 화면에 나가면 안 되는 내부 용어·폐기 문구(시험용 목록)
FORBIDDEN_SCREEN_TERMS = (
    "UNIDENTIFIED", "NOT_LISTED", "FOUND", "NO_EVIDENCE", "EASY_TEXT_MISSING", "NO_PRODUCT_INFO", "missing_reason",
    "L3", "L1", "약 이름 사전", "공식 약 목록", "원문을 가져오지 못했어요", "허가 라벨", "(서비스의 한계예요)",
    "이 서비스가 쓰는", "단계",
)
