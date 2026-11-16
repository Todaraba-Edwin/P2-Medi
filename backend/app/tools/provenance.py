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

# 자료 키 → 기준일(파일 자료만)
DATASET_AS_OF = {
    "contra_pair": AS_OF_COMBO, "pregnancy": AS_OF_KIDS, "age": AS_OF_KIDS, "dose": AS_OF_KIDS,
    "lactation": AS_OF_LACTATION, "elderly": AS_OF_HIRA,
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
    "NO_PRODUCT_INFO": "제품 단위 정보(제품 연령 문장·허가 라벨·제형) 없음. 봉투의 제품명을 알려 주시면 더 확인할 수 있어요",
    "EASY_TEXT_MISSING": "전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요",
}
