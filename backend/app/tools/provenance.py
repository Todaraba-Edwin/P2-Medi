"""표시 계약 공통 상수(AG-02 §2 마지막 항목, PRD-12-03). 자료 약칭·기관명·표지 종류의 정의는 이 모듈 한 곳뿐이다.

세 도구 래퍼·AG-08 `finalize`·BE-06은 이 상수만 import한다. 자료 키(`dataset_key`)는 `lookup.DATASET_KEYS`의 키이고,
화면 문자열(약칭)은 여기서 키로 찾는다. 문구는 후보이며 디자인 세션에서 확정한다(PRD-12 §7).
"""

from __future__ import annotations

from app.db.loaders import AS_OF_COMBO, AS_OF_HIRA, AS_OF_KIDS, AS_OF_LACTATION, SRC_HIRA, SRC_KIDS

# 기관(대그룹). 값은 적재 모듈의 출처 문자열과 같다.
PUBLISHER = {
    "kids": SRC_KIDS,
    "hira": SRC_HIRA,
    "mfds": "식약처",
}

# 허가정보 출처 이름(API 서비스 이름, 도구 항목의 `source`)
SOURCE_PRMSN = "식약처 의약품 제품 허가정보"

# 자료 키 → 화면 약칭(출처 표 `dataset` 열과 같은 문자열)
DATASET_LABELS = {
    "contra_pair": "병용금기 파일",
    "pregnancy": "임부금기 파일",
    "age": "연령금기 파일",
    "dose": "용량주의 파일",
    "lactation": "수유부주의 파일",
    "elderly": "노인주의 파일",
    "dur_ingr": "DUR 성분정보 API",
    "dup_ingredient": "성분코드 비교",
    "identify": "의약품 허가정보",
    "eyak": "e약은요 쉬운 설명",
    "prmsn": "의약품 허가정보",
}

# 자료 키 → 기관 키
DATASET_PUBLISHER = {
    "contra_pair": "kids", "pregnancy": "kids", "age": "kids", "dose": "kids", "lactation": "kids", "elderly": "hira",
    "dur_ingr": "mfds", "dup_ingredient": "kids", "identify": "mfds", "eyak": "mfds", "prmsn": "mfds",
}

# 날짜 줄 라벨
DATE_LABELS = {
    "as_of": "자료 기준일",
    "queried_at": "조회 시각",
    "snapshot_collected_at": "스냅샷 수집 시각",
}

# 출처 표 날짜 줄 라벨(PRD-12 §5.1: 고시일·기준일·조회일, 화면은 "조회"로 줄여 씀. 날짜 없음은 §5.6 가정). BE-06 `citations[].dates[].label` 값.
# 위 `DATE_LABELS`(내부 설명용 이름)와 별개이며, 응답·화면에 나가는 라벨은 이 표만 쓴다. 새 라벨은 여기에 먼저 더한다.
CITATION_DATE_LABELS = {
    "notice": "고시일",
    "as_of": "기준일",
    "queried": "조회",
    "none": "날짜 없음",
    # BE-06-08 A(2026-11-12): 발간물의 발간일. 값은 `YYYY-MM`(월 단위)도 허용한다. 예: 심평원 「기능과 역할」 2026년판 발간일 2025-11
    "published": "발간일",
}

# 자료 키 → 원문 날짜 정밀도(BE-16-11 A, BE-06-08 A "원본 기준"). 표에 없는 자료는 일 단위 그대로다.
# 심평원 DUR 품목리스트는 원문이 "2026.6"(일자 없음)이라 화면·응답에는 월 단위 `YYYY-MM`만 내보낸다.
# DB `as_of`(DATE)와 `loaders.AS_OF_HIRA`(적재값 2026-06-01)는 바꾸지 않는다. 자르는 일은 표시 단계(`display_as_of`)만 한다.
DATE_PRECISION_MONTH = "month"
DATASET_DATE_PRECISION: dict[str, str] = {"elderly": DATE_PRECISION_MONTH}


def display_as_of(dataset_key: str | None, value: str | None) -> str | None:
    """표시용 기준일. 월 단위 자료면 `YYYY-MM-DD`(또는 그 앞부분이 날짜인 문자열) → `YYYY-MM`. 그 밖의 자료·값은 그대로 돌려준다."""
    if value is None or DATASET_DATE_PRECISION.get(dataset_key or "") != DATE_PRECISION_MONTH:
        return value
    s = str(value).strip()
    if len(s) >= 7 and s[:4].isdigit() and s[4] == "-" and s[5:7].isdigit():
        return s[:7]
    return value


# 자료 키 → 기준일(파일 자료만, 표시값. 월 단위 자료는 `display_as_of`로 자른 값)
DATASET_AS_OF = {
    k: display_as_of(k, v)
    for k, v in {
        "contra_pair": AS_OF_COMBO, "pregnancy": AS_OF_KIDS, "age": AS_OF_KIDS, "dose": AS_OF_KIDS,
        "lactation": AS_OF_LACTATION, "elderly": AS_OF_HIRA,
    }.items()
}

# `source_kind` 값과 표지 종류 문구(쉬운 말, 내부 용어 없음)
SK_API_DIRECT, SK_FILE, SK_CORPUS_QUOTE = "API_DIRECT", "FILE", "CORPUS_QUOTE"
SOURCE_KIND = {
    SK_API_DIRECT: "공식 자료에서 직접 가져왔어요",
    SK_FILE: "공식 파일 기준이에요",
    SK_CORPUS_QUOTE: "공식 문서에서 찾은 문장이에요",
}
SOURCE_KIND_PREFIX = {SK_API_DIRECT: "공식 자료", SK_FILE: "공식 파일", SK_CORPUS_QUOTE: "공식 문서"}


def badge(source_kind: str, dataset_key: str) -> str:
    """표지 `{종류} · {자료 약칭}` (PRD-12-03)."""
    return f"{SOURCE_KIND_PREFIX[source_kind]} · {DATASET_LABELS[dataset_key]}"


# 파일·API 4경우 꼬리표 → 항목에 붙는 안내(코드 상수. PJ2-RFP.md 5.1절 (7), PJ2-Agent-Harness.md 어휘 표)
NOT_SAFE = "안전하다는 뜻이 아니에요"
FLAG_NOTES = {
    "API_SAME": "파일과 실시간 조회 결과가 같아요",
    "FILE_ONLY": "파일에는 있고 실시간 조회에는 없어요. 기준일 이후 해제되었을 수 있어요. 약사·의사에게 확인하세요",
    "API_ONLY": "실시간 조회에만 있고 파일에는 없어요. 기준일 이후 새로 지정되었을 수 있어요. " + NOT_SAFE,
    "API_FAIL": "실시간 확인을 하지 못함(파일 기준 결과는 그대로예요)",
    "API_PAIR_INCOMPLETE": "실시간 확인을 하지 못함(쌍의 한쪽 조회가 빠졌어요)",
    # 사용자 수정 문구(2026-11-12 승인, 하네스 3.4절 표·Recap 0-1)
    "CODE_NOT_LINKED": "금기 목록에서 확인하지 못했지만, " + NOT_SAFE + ". 약사에게 확인하세요",
    "AMBIGUOUS_NAME": "같은 이름의 약이 여러 개라 어느 약인지 먼저 확인해야 해요",
    "REFERENCE_ONLY": "다른 제형에서 목록에 있음, 이 제품 판정 아님",
    # "허가 라벨"→"허가사항"(2026-11-16 사용자 결정 Recap 19②, 하네스 3.4절 표·`fixed_phrases.NO_PRODUCT_INFO`와 같은 글자)
    "NO_PRODUCT_INFO": "제품 단위 정보(제품 연령 문장·허가사항·제형) 없음. 봉투의 제품명을 알려 주시면 더 확인할 수 있어요",
    "EASY_TEXT_MISSING": "전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요",
}

# 실시간 확인을 하지 못한 **사유**(AG-01-10 A, 2026-11-17). 꼬리표(`API_FAIL`·`API_PAIR_INCOMPLETE`)와 도구 출력 계약은 그대로 두고,
# 항목의 `api.reason`에 사유만 더 적는다. 사유가 없는 항목(실시간 조회를 끈 실행, 전부 실패)은 지금까지와 같다.
API_REASON_NO_CODE = "NO_API_CODE"  # 성분에 실시간 조회용(DUR 성분) 코드가 없어 **호출하지 않았다**(실패가 아니다)
API_REASON_PARTIAL = "PARTIAL"      # 조회한 것 중 일부가 실패했다(쌍의 한쪽 등)
API_REASON_TRUNCATED = "TRUNCATED"  # 성분 코드가 한도보다 많아 일부 성분만 물었다(대조가 끝나지 않았다)
API_REASONS = (API_REASON_NO_CODE, API_REASON_PARTIAL, API_REASON_TRUNCATED)
# 사유별 노트 문구 **초안**(사용자 승인 전, `fixed_phrases.DRAFT_KEYS`의 `API_REASON_NOTES`). 승인되면 아래 `API_REASON_NOTES_APPROVED`를 True로 바꾼다.
API_REASON_NOTES = {
    API_REASON_NO_CODE: "실시간 확인을 하지 못함(이 성분은 실시간 조회에 쓸 코드가 없어요. 파일 기준 결과는 그대로예요)",
    API_REASON_PARTIAL: "실시간 확인을 하지 못함(쌍의 한쪽 조회에 실패했어요. 파일 기준 결과는 그대로예요)",
    API_REASON_TRUNCATED: "실시간 확인을 일부만 함(성분이 많아 일부 성분만 조회했어요. 파일 기준 결과는 그대로예요)",
}
API_REASON_NOTES_APPROVED = False


def api_flag_note(flag: str, reason: str | None = None) -> str:
    """실시간 확인 꼬리표의 노트 문구. 사유(`api.reason`)가 있으면 사유에 맞는 문구를 고른다.

    사유별 문구가 승인되기 전(`API_REASON_NOTES_APPROVED = False`)에는 **이미 승인된 문구**만 쓴다:
      - `NO_API_CODE`: `API_FAIL` 문구 "실시간 확인을 하지 못함(파일 기준 결과는 그대로예요)". 코드가 없어 묻지 않은 것을 쌍 꼬리표 문구
        "쌍의 한쪽 조회가 빠졌어요"로 말하면 사용자가 조회 실패로 읽고 요약 모델도 그대로 옮긴다(lane-D 보고 §2). `API_FAIL` 문구는
        실패라고 단정하지 않고 어느 사유에도 사실이다(중립).
      - `PARTIAL`·`TRUNCATED`: 지금까지의 꼬리표 문구 그대로(쌍은 "쌍의 한쪽 조회가 빠졌어요": 실제로 일부 조회가 빠졌다. AG-01-04 A).
    사유가 없거나 모르는 값이면 지금까지의 꼬리표 문구 그대로다."""
    if flag not in ("API_FAIL", "API_PAIR_INCOMPLETE") or reason not in API_REASONS:
        return FLAG_NOTES[flag]
    if API_REASON_NOTES_APPROVED:
        return API_REASON_NOTES[reason]
    return FLAG_NOTES["API_FAIL"] if reason == API_REASON_NO_CODE else FLAG_NOTES[flag]
