"""BE-09 성분코드 조회 도구 시험: 일치 / 불일치 / M 등급 / 연령 조건 / 빈 입력."""

import sqlite3

import pytest

from app.db import loaders
from app.tools import lookup
from app.tools.lookup import FOUND, NOT_LISTED, UNIDENTIFIED, Age

FLU = "161430BIJ"      # 5-fluorouracil 주사
TSONE = "452400ACH"    # gimeracil+oteracil+tegafur
ACAM = "100501ATE"
M_CODE = "999901ATB"   # 합성 M 등급
LEVO = "256000ACR"
CLEAN = "111111ATB"    # 어느 표에도 없음


def _contra(i, a, b, reason="독성 증가, 병용 금기 (합성 시험 문구)"):
    return {"id": f"c{i}", "text": "", "metadata": {
        "성분명A": "a", "성분코드A": a, "성분명B": "b", "성분코드B": b,
        "고시번호": "20200130", "고시적용일": "2020-12-28", "금기사유": reason, "비고": ""}}


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)

    contra = loaders.collect(
        [_contra(1, FLU, TSONE)], loaders.normalize_contra_json, "contra_pair", "x.json", loaders.AS_OF_KIDS)
    preg = loaders.collect(
        [
            {"성분명": "acamprosate", "성분코드": ACAM, "고시일자": "2016-12-30", "고시번호": "20160155",
             "금기등급": "2", "상세정보": "임부에 대한 안전성 미확립."},
            {"성분명": "testM", "성분코드": M_CODE, "고시일자": "2021-01-01", "고시번호": "20210001",
             "금기등급": "M", "상세정보": "유산 치료 시 1등급, 그 외 2등급 (합성 시험 문구)"},
        ],
        loaders.normalize_pregnancy, "pregnancy_contra", "p.csv", loaders.AS_OF_KIDS)
    age = loaders.collect(
        [
            {"성분명": "levodopa", "성분코드": LEVO, "특정연령": "25", "특정연령단위": "세 (3)",
             "연령처리조건": "미만 (1)", "고시번호": "20070030", "고시일자": "2007-04-11", "상세정보": "안전성 미확립"},
            {"성분명": "levodopa", "성분코드": LEVO, "특정연령": "6", "특정연령단위": "개월 (2)",
             "연령처리조건": "이하 (2)", "고시번호": "20070031", "고시일자": "2007-04-11", "상세정보": "개월 시험"},
            {"성분명": "old", "성분코드": "999904ATB", "특정연령": "65", "특정연령단위": "세 (3)",
             "연령처리조건": "이상 (4)", "고시번호": "20070032", "고시일자": "2007-04-11", "상세정보": "이상 시험"},
        ],
        loaders.normalize_age, "age_contra", "a.csv", loaders.AS_OF_KIDS)
    lact = loaders.collect(
        [{"주성분코드": ACAM, "성분명": "acamprosate", "공고일자": "2024-01-19", "공고번호": "20240041", "비고": ""}],
        loaders.normalize_lactation, "caution", "l.csv", loaders.AS_OF_LACTATION)
    loaders.load_into(c, {"x.json": contra, "p.csv": preg, "a.csv": age, "l.csv": lact})
    return c


def _one(res, kind):
    xs = [i for i in res.items if i.kind == kind]
    assert len(xs) == 1
    return xs[0]


def test_pair_found_both_directions(conn):
    for a, b in ((FLU, TSONE), (TSONE, FLU)):
        item = _one(lookup.check_contraindications(conn, [a, b]), "contra_pair")
        assert item.status == FOUND
        m = item.matches[0]
        assert m["reason"].startswith("독성 증가")
        assert m["notice_no"] == "20200130"
        assert item.as_of == "2026-07-21" and item.source == "한국의약품안전관리원"
        assert item.evidence_id == f"contra_pair:{FLU}:{TSONE}"


def test_pair_not_listed_carries_source_and_date(conn):
    item = _one(lookup.check_contraindications(conn, [FLU, CLEAN]), "contra_pair")
    assert item.status == NOT_LISTED and item.matches == []
    assert item.as_of == "2026-07-21" and item.source


def test_pregnancy_grade_and_detail_verbatim(conn):
    item = _one(lookup.check_contraindications(conn, [ACAM], pregnancy=True), "pregnancy")
    assert item.status == FOUND
    assert item.matches[0]["grade"] == "2"
    assert item.matches[0]["detail"] == "임부에 대한 안전성 미확립."


def test_pregnancy_m_grade_not_converted(conn):
    item = lookup.lookup_pregnancy(conn, M_CODE)
    assert item.status == FOUND
    assert item.matches[0]["grade"] == "M"             # 1·2로 환산하지 않는다
    assert item.matches[0]["detail"] == "유산 치료 시 1등급, 그 외 2등급 (합성 시험 문구)"


def test_pregnancy_not_listed(conn):
    assert lookup.lookup_pregnancy(conn, CLEAN).status == NOT_LISTED


@pytest.mark.parametrize(
    "age, expected",
    [
        (Age(24, "세"), FOUND),      # 25세 미만
        (Age(25, "세"), NOT_LISTED),  # 경계: 미만이라 25세는 해당 아님
        (Age(3, "개월"), FOUND),      # 6개월 이하 + 25세 미만
        (Age(40, "세"), NOT_LISTED),
    ],
)
def test_age_conditions(conn, age, expected):
    assert lookup.lookup_age(conn, LEVO, age).status == expected


def test_age_boundaries_inclusive_and_over(conn):
    assert lookup.lookup_age(conn, "999904ATB", Age(65, "세")).status == FOUND     # 이상은 경계 포함
    assert lookup.lookup_age(conn, "999904ATB", Age(64, "세")).status == NOT_LISTED
    # 이하는 경계 포함: 개월 규칙 6개월 이하만 쓰는 시험을 위해 25세 이상으로 비교
    assert lookup.lookup_age(conn, LEVO, Age(6, "개월")).status == FOUND


def test_age_found_returns_detail_and_unit(conn):
    item = lookup.lookup_age(conn, LEVO, Age(10, "세"))
    assert item.status == FOUND
    m = item.matches[0]
    assert (m["age_value"], m["age_unit"], m["age_cond"]) == (25, "세", "미만")
    assert m["detail"] == "안전성 미확립"


def test_age_rejects_bad_input():
    with pytest.raises(ValueError):
        Age(-1, "세")
    with pytest.raises(ValueError):
        Age(3, "년")


def test_empty_and_single_input(conn):
    assert lookup.check_contraindications(conn, []).items == []
    assert lookup.check_contraindications(conn, [FLU]).items == []           # 쌍도 임부도 없음
    assert lookup.check_contraindications(conn, [FLU, FLU]).items == []      # 같은 코드는 한 번만 본다


def test_three_codes_make_all_pairs(conn):
    res = lookup.check_contraindications(conn, [FLU, TSONE, CLEAN])
    pairs = [i for i in res.items if i.kind == "contra_pair"]
    assert len(pairs) == 3
    assert sorted(i.status for i in pairs) == [FOUND, NOT_LISTED, NOT_LISTED]


def test_invalid_code_is_unidentified_not_listed(conn):
    res = lookup.check_contraindications(conn, [FLU, None, "D000123"])
    statuses = {(i.kind, i.status) for i in res.items}
    assert ("identify", UNIDENTIFIED) in statuses
    pair_items = [i for i in res.items if i.kind == "contra_pair"]
    assert pair_items and all(i.status == UNIDENTIFIED for i in pair_items)  # '목록에 없음'으로 새지 않는다
    assert all("PAIR_NOT_CHECKED" in i.flags for i in pair_items)


def test_cautions_optional(conn):
    res = lookup.check_contraindications(conn, [ACAM], include_cautions=True)
    by_kind = {i.kind: i.status for i in res.items}
    assert by_kind == {"dose": NOT_LISTED, "lactation": FOUND, "elderly": NOT_LISTED}
    lact = [i for i in res.items if i.kind == "lactation"][0]
    assert lact.as_of == "2025-11-27"


def test_to_dict_is_json_serializable(conn):
    import json

    res = lookup.check_contraindications(conn, [FLU, TSONE], pregnancy=True, age=Age(10, "세"))
    json.dumps(res.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------------------------
# be-fix: 행 키·행 단위 근거 ID·자료 키
# ---------------------------------------------------------------------------------------------
def test_matches_carry_row_key_and_row_evidence_id(conn):
    cases = [
        (_one(lookup.check_contraindications(conn, [FLU, TSONE]), "contra_pair"), f"contra_pair:{FLU}:{TSONE}"),
        (_one(lookup.check_contraindications(conn, [ACAM], pregnancy=True), "pregnancy"), f"pregnancy:{ACAM}"),
        (_one(lookup.check_contraindications(conn, [LEVO], age=Age(10, "세")), "age"), f"age:{LEVO}"),
        (lookup.lookup_caution(conn, ACAM, "lactation"), f"lactation:{ACAM}"),
    ]
    for item, evidence_id in cases:
        assert item.status == FOUND and item.evidence_id == evidence_id
        for m in item.matches:
            assert len(m["row_key"]) == 40
            assert m["row_evidence_id"] == f"{evidence_id}#{m['row_key'][:12]}"


def test_row_evidence_ids_are_distinct_per_row(conn):
    item = lookup.lookup_age(conn, LEVO, Age(3, "개월"))      # 25세 미만 + 6개월 이하 두 행
    ids = [m["row_evidence_id"] for m in item.matches]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_dataset_key_is_key_only_and_identify_has_none(conn):
    res = lookup.check_contraindications(conn, [FLU, TSONE, ACAM, "bad"], pregnancy=True, age=Age(10, "세"), include_cautions=True)
    for i in res.items:
        if i.kind == "identify":
            assert i.dataset_key is None
        else:
            assert i.dataset_key == i.kind and i.dataset_key in lookup.DATASET_KEYS
    assert lookup.DATASET_KEYS == {"contra_pair", "pregnancy", "age", "dose", "lactation", "elderly"}
    assert "dataset_key" in res.to_dict()["items"][0]


def test_invalid_code_and_pair_not_checked_behaviour_unchanged(conn):
    res = lookup.check_contraindications(conn, [FLU, "bad"])
    flags = {i.kind: (i.status, i.flags) for i in res.items}
    assert flags["identify"] == (UNIDENTIFIED, ["INVALID_CODE"])
    assert flags["contra_pair"] == (UNIDENTIFIED, ["PAIR_NOT_CHECKED"])


def test_pair_not_checked_source_and_as_of_are_none(conn):
    """조회하지 않은 쌍은 INVALID_CODE처럼 출처·기준일이 없다(BE-09-04 A)."""
    res = lookup.check_contraindications(conn, [FLU, "bad"])
    pairs = [i for i in res.items if i.kind == "contra_pair"]
    assert pairs
    for item in pairs:
        assert item.status == UNIDENTIFIED
        assert item.source is None and item.as_of is None
        assert item.flags == ["PAIR_NOT_CHECKED"]


# =============================================================================================
# BE-09 identify 항목 source=None 검증 (2026-11-10)
# =============================================================================================
def test_identify_source_and_as_of_are_none(conn):
    """identify 항목의 source와 as_of가 None인지 확인."""
    res = lookup.check_contraindications(conn, [None, "bad"])
    identify_items = [i for i in res.items if i.kind == "identify"]
    assert len(identify_items) == 2
    for item in identify_items:
        assert item.status == UNIDENTIFIED
        assert item.source is None
        assert item.as_of is None
        assert "INVALID_CODE" in item.flags


def test_identify_renders_without_error_with_source_none(conn):
    """identify 항목의 source=None일 때 렌더러가 깨지지 않는지 확인."""
    from app.agent.renderer import render

    res = lookup.check_contraindications(conn, [None])
    items_dict = [i.to_dict() for i in res.items]

    # 렌더러는 .get("source")를 쓰므로 None 안전함
    result = render(items_dict, [])
    assert result.detail  # 에러 없이 처리됨
    for detail in result.detail:
        if detail["kind"] == "identify":
            assert detail["publisher"] is None  # source=None이면 publisher도 None
            assert detail["as_of"] is None
