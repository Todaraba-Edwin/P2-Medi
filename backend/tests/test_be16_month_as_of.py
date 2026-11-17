"""BE-16-11 A: 심평원 DUR 품목리스트(원문 "2026.6", 일자 없음) 기준일은 표시 단계에서만 월 단위 `YYYY-MM`.

- DB `as_of`(DATE)와 적재값 `loaders.AS_OF_HIRA`(2026-06-01)는 그대로다.
- FOUND(DB 행 값)·NOT_LISTED(상수) 두 경로가 같은 표시값 `2026-06`을 낸다.
- 다른 자료의 날짜는 바뀌지 않는다. `DateLine`(출처 표 날짜 줄)은 `기준일 2026-06`을 받는다.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.api import schemas
from app.db import loaders
from app.tools import lookup, provenance
from app.tools.lookup import FOUND, NOT_LISTED, Item
from app.tools.provenance import DATASET_DATE_PRECISION, display_as_of

ELD = "999905ATB"    # 합성: 심평원 노인주의에 있는 성분
CLEAN = "111111ATB"  # 어느 표에도 없음


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    eld = loaders.collect(
        [{"성분코드": ELD, "성분명": "합성 성분", "약품상세정보": "합성 시험 문구", "공고번호": "20230001", "공고일자": "2023-01-02"}],
        loaders.normalize_elderly, "caution", "e.csv", loaders.AS_OF_HIRA)
    loaders.load_into(c, {"e.csv": eld})
    return c


def test_loader_value_unchanged_and_db_keeps_day():
    """적재(DB에 넣는 값)는 바뀌지 않는다: 상수·정규화 행·DB 저장값 모두 2026-06-01."""
    assert loaders.AS_OF_HIRA == "2026-06-01"
    row = loaders.normalize_elderly({"성분코드": ELD, "성분명": "x", "약품상세정보": "", "공고번호": "1", "공고일자": "2023-01-02"})
    assert row is not None and row["as_of"] == "2026-06-01"
    for name in ("의약품안전사용서비스(DUR)_노인주의 품목리스트 2026.6.csv", "의약품안전사용서비스(DUR)_노인주의(해열진통소염제) 품목리스트 2026.6.csv"):
        assert loaders.EXTENSION_SOURCES[name][2] == "2026-06-01"  # load_log.as_of(DATE)


def test_db_stores_day_value(conn):
    assert conn.execute("SELECT as_of FROM caution WHERE kind = 'elderly'").fetchall() == [("2026-06-01",)]


def test_found_and_not_listed_both_display_month(conn):
    found = lookup.lookup_caution(conn, ELD, "elderly")
    missing = lookup.lookup_caution(conn, CLEAN, "elderly")
    assert (found.status, missing.status) == (FOUND, NOT_LISTED)
    assert found.as_of == missing.as_of == "2026-06"
    assert found.to_dict()["as_of"] == "2026-06"
    assert found.matches[0]["notice_date"] == "2023-01-02"  # 행 고시일(공고일자)은 일 단위 그대로


def test_postgres_date_object_also_trimmed():
    """원격 DB는 DATE를 `date`로 돌려준다(`str()` → 'YYYY-MM-DD'). 같은 규칙으로 자른다."""
    it = Item("elderly", FOUND, (ELD,), f"elderly:{ELD}", loaders.SRC_HIRA, str(date(2026, 6, 1)))
    assert it.as_of == "2026-06"


@pytest.mark.parametrize(
    ("kind", "as_of"),
    [
        ("contra_pair", "2026-07-31"), ("pregnancy", "2026-07-21"), ("age", "2026-07-21"),
        ("dose", "2026-07-21"), ("lactation", "2025-11-27"),
    ],
)
def test_other_datasets_unchanged(conn, kind, as_of):
    it = Item(kind, NOT_LISTED, (CLEAN,), f"{kind}:{CLEAN}", "x", as_of)
    assert it.as_of == as_of
    assert display_as_of(kind, as_of) == as_of
    assert provenance.DATASET_AS_OF[kind] == as_of
    assert lookup.lookup_caution(conn, CLEAN, "dose").as_of == loaders.AS_OF_KIDS
    assert lookup.lookup_caution(conn, CLEAN, "lactation").as_of == loaders.AS_OF_LACTATION


def test_precision_table_and_rule():
    assert DATASET_DATE_PRECISION == {"elderly": "month"}  # 심평원 품목리스트만
    assert provenance.DATASET_AS_OF["elderly"] == "2026-06"
    assert display_as_of("elderly", "2026-06-01") == "2026-06"
    assert display_as_of("elderly", "2026-06") == "2026-06"          # 이미 월 단위면 그대로(멱등)
    assert display_as_of("elderly", None) is None
    assert display_as_of("elderly", "unknown") == "unknown"          # 해석할 수 없으면 손대지 않는다(지어내지 않음)
    assert display_as_of(None, "2026-06-01") == "2026-06-01"
    assert display_as_of("dur_ingr", "2026-06-01") == "2026-06-01"


def test_dateline_accepts_month_for_as_of_and_rejects_for_queried():
    assert schemas.DateLine(label=schemas.DATE_LABEL_AS_OF, value="2026-06").value == "2026-06"
    with pytest.raises(ValueError):
        schemas.DateLine(label=schemas.DATE_LABEL_QUERIED, value="2026-06")
    with pytest.raises(ValueError):
        schemas.DateLine(label=schemas.DATE_LABEL_AS_OF, value="2026-13")


@pytest.mark.parametrize("raw", ["2026-06-01", "2026-06"])
def test_citation_date_lines_month_for_elderly(raw):
    """출처 표 조립(`date_lines`): 도구를 거치지 않은 detail(일 단위 값)도 월 단위로 나가고, 다른 자료는 그대로다."""
    eld = schemas.date_lines({"dataset_key": "elderly", "as_of": raw, "rows": [{"notice_date": "2023-01-02"}]})
    assert [(x.label, x.value) for x in eld] == [(schemas.DATE_LABEL_NOTICE, "2023-01-02"), (schemas.DATE_LABEL_AS_OF, "2026-06")]
    other = schemas.date_lines({"dataset_key": "pregnancy", "as_of": "2026-07-21", "rows": []})
    assert [(x.label, x.value) for x in other] == [(schemas.DATE_LABEL_AS_OF, "2026-07-21")]
