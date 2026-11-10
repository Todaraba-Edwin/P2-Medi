"""BE-09 파서·정규화·적재 시험. 작은 합성 샘플(공공데이터 형식)을 tmp_path에 만들어 쓴다.

실제 `data/` 파일 시험은 파일이 있을 때만 돈다(`data/`는 로컬 전용).
"""

import json
import sqlite3
import tracemalloc
from pathlib import Path

import pytest

from app.db import loaders

REAL_DATA = Path(__file__).resolve().parents[2] / "data"

PREG_HEADER = "성분명,성분코드,제품코드,제품명,업체명,급여구분,고시일자,고시번호,금기등급,상세정보\n"
PREG_ROWS = (
    "acamprosate,100501ATE,651904740,명인아캄프로세이트정333mg(아캄프로세이트칼슘)_(0.333g/1정),명인제약(주),급여,2016-12-30,20160155,2,임부에 대한 안전성 미확립.\n"
    "acamprosate,100501ATE,651904741,다른제품정_(1정),다른제약(주),급여,2016-12-30,20160155,2,임부에 대한 안전성 미확립.\n"  # 제품만 다른 중복
    'testdrugM,999901ATB,100000001,테스트엠정_(1정),테스트(주),급여,2021-01-01,20210001,M,"유산 치료 시 1등급, 그 외 2등급 (합성 시험 문구)"\n'
    "badgrade,999902ATB,100000002,등급이상정_(1정),테스트(주),급여,2021-01-01,20210001,9,무시되어야 함\n"
)
AGE_HEADER = "성분명,성분코드,제품코드,제품명,업체명,특정연령,특정연령단위,연령처리조건,급여구분,고시번호,고시일자,상세정보\n"
AGE_ROWS = (
    '"benserazide hydrochloride (as benserazide), levodopa",256000ACR,645000170,마도파캅셀_(1캡슐),(주)한국로슈,25,세 (3),미만 (1),급여,20070030,2007-04-11,안전성 및 유효성 미확립\n'
    "testdrugA,999903ATB,100000003,연령개월정_(1정),테스트(주),6,개월 (2),이하 (2),급여,20070031,2007-04-11,개월 시험\n"
    "testdrugB,999904ATB,100000004,연령이상정_(1정),테스트(주),65,세 (3),이상 (4),급여,20070032,2007-04-11,이상 시험\n"
    "testdrugC,999905ATB,100000005,연령이상정_(1정),테스트(주),abc,세 (3),이상 (4),급여,20070032,2007-04-11,숫자 아님\n"
)


def _write_cp949(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("cp949"))
    return path


def _contra_obj(i: int, a="161430BIJ", b="452400ACH", notice="20200130", reason="사유 문장"):
    return {
        "id": f"contra_{i}",
        "text": "[병용금기] ...",
        "metadata": {
            "성분명A": "5-fluorouracil", "성분코드A": a, "제품코드A": str(1000 + i),
            "성분명B": "gimeracil+oteracil potassium+tegafur", "성분코드B": b, "제품코드B": str(2000 + i),
            "고시번호": notice, "고시적용일": "2020-12-28", "금기사유": reason, "비고": "",
        },
    }


def test_csv_cp949_roundtrip(tmp_path):
    p = _write_cp949(tmp_path / "preg.csv", PREG_HEADER + PREG_ROWS)
    rows = list(loaders.iter_csv(p))
    assert len(rows) == 4
    assert rows[0]["제품명"].startswith("명인아캄프로세이트정")  # 한글이 깨지지 않는다


def test_pregnancy_dedup_and_grade_m_untouched(tmp_path):
    p = _write_cp949(tmp_path / "preg.csv", PREG_HEADER + PREG_ROWS)
    c = loaders.read_source(p, loaders.normalize_pregnancy, "pregnancy_contra", loaders.AS_OF_KIDS)
    assert c.stats.raw_rows == 4
    assert c.stats.skipped == 1               # 등급 '9'는 버린다
    assert c.stats.unique_rows == 2           # 제품만 다른 두 행은 성분코드 단위로 합쳐진다
    by_code = {r["ingr_code"]: r for r in c.records.values()}
    m = by_code["999901ATB"]
    assert m["grade"] == "M"                  # M을 1·2로 바꾸지 않는다
    assert m["detail"] == "유산 치료 시 1등급, 그 외 2등급 (합성 시험 문구)"  # 원문 그대로


def test_age_normalization(tmp_path):
    p = _write_cp949(tmp_path / "age.csv", AGE_HEADER + AGE_ROWS)
    c = loaders.read_source(p, loaders.normalize_age, "age_contra", loaders.AS_OF_KIDS)
    assert c.stats.skipped == 1               # 연령이 숫자가 아닌 행
    recs = {r["ingr_code"]: r for r in c.records.values()}
    r = recs["256000ACR"]
    assert (r["age_value"], r["age_unit"], r["age_cond"]) == (25, "세", "미만")
    assert recs["999903ATB"]["age_days"] == loaders.age_to_days(6, "개월")
    assert recs["999904ATB"]["age_cond"] == "이상"


def test_age_to_days_rejects_unknown_unit():
    with pytest.raises(ValueError):
        loaders.age_to_days(3, "년")


def test_contra_json_collapses_product_pairs(tmp_path):
    p = tmp_path / "contra.json"
    objs = [_contra_obj(i) for i in range(50)]                                  # 제품만 다른 같은 성분 쌍 50건
    objs.append(_contra_obj(99, a="452400ACH", b="161430BIJ"))                  # 방향만 반대 = 별도 행(원본 방향 보존)
    objs.append(_contra_obj(100, a="", b="161430BIJ"))                          # 성분코드 없음
    p.write_text(json.dumps(objs, ensure_ascii=False), encoding="utf-8")
    c = loaders.read_source(p, loaders.normalize_contra_json, "contra_pair", loaders.AS_OF_KIDS)
    assert c.stats.raw_rows == 52
    assert c.stats.skipped == 1
    assert c.stats.unique_rows == 2
    assert all(r["code_lo"] <= r["code_hi"] for r in c.records.values())


@pytest.mark.parametrize("chunk", [7, 64, 1 << 20])
def test_json_stream_chunk_boundaries(tmp_path, chunk):
    p = tmp_path / "arr.json"
    objs = [_contra_obj(i, reason=f"사유 {i} " + "가" * (i % 13)) for i in range(40)]
    p.write_text(json.dumps(objs, ensure_ascii=False, indent=2), encoding="utf-8")
    out = list(loaders.iter_json_array(p, chunk_size=chunk))
    assert out == objs


def test_json_stream_limit_and_empty(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text(json.dumps([_contra_obj(i) for i in range(10)]), encoding="utf-8")
    assert len(list(loaders.iter_json_array(p, limit=3))) == 3
    e = tmp_path / "empty.json"
    e.write_text("[ ]", encoding="utf-8")
    assert list(loaders.iter_json_array(e)) == []
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        list(loaders.iter_json_array(bad))
    trunc = tmp_path / "trunc.json"
    trunc.write_text('[{"a": 1}, {"b":', encoding="utf-8")
    with pytest.raises(Exception):
        list(loaders.iter_json_array(trunc))


def test_load_is_idempotent(tmp_path):
    preg = _write_cp949(tmp_path / "한국의약품안전관리원_임부금기약물_20260721.csv", PREG_HEADER + PREG_ROWS)
    age = _write_cp949(tmp_path / "한국의약품안전관리원_연령금기_20260721.csv", AGE_HEADER + AGE_ROWS)
    (tmp_path / "병용금기_데이터.json").write_text(
        json.dumps([_contra_obj(i) for i in range(5)], ensure_ascii=False), encoding="utf-8")
    assert preg.exists() and age.exists()
    collected = loaders.collect_all(tmp_path, include_extension=False)
    conn = sqlite3.connect(":memory:")
    first = loaders.load_into(conn, collected)
    second = loaders.load_into(conn, collected)   # 재실행해도 중복이 생기지 않는다
    assert first == second
    assert first["contra_pair"] == 1 and first["pregnancy_contra"] == 2 and first["age_contra"] == 3
    log = conn.execute("SELECT source_file, raw_rows, loaded_rows FROM load_log ORDER BY source_file").fetchall()
    assert len(log) == 3


def test_schema_rejects_bad_grade():
    conn = sqlite3.connect(":memory:")
    loaders.apply_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pregnancy_contra (row_key, ingr_code, grade, source, as_of) VALUES ('k','100501ATE','3','s','2026-07-21')")


def test_estimate_size_scales_with_rows(tmp_path):
    p = _write_cp949(tmp_path / "preg.csv", PREG_HEADER + PREG_ROWS)
    c = loaders.read_source(p, loaders.normalize_pregnancy, "pregnancy_contra", loaders.AS_OF_KIDS)
    est = loaders.estimate_size({"preg.csv": c})
    t = est["tables"]["pregnancy_contra"]
    assert t["rows"] == 2 and t["est_bytes"] > t["text_bytes"]
    assert est["total_est_bytes"] < est["free_plan_limit_bytes"]


# ------------------------------------------------------------ 실제 파일(있을 때만)

@pytest.mark.skipif(not (REAL_DATA / "병용금기_데이터.json").exists(), reason="data/ 원본 없음(로컬 전용)")
def test_real_contra_json_streams_first_n_within_memory():
    path = REAL_DATA / "병용금기_데이터.json"        # 약 540MB
    tracemalloc.start()
    n = 0
    for obj in loaders.iter_json_array(path, limit=2000):
        n += 1
        assert loaders.normalize_contra_json(obj) is not None
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n == 2000
    assert peak < 20 * 1024 * 1024       # 전체 파일(540MB)이 아니라 청크 수준만 쓴다


@pytest.mark.skipif(not (REAL_DATA / "한국의약품안전관리원_임부금기약물_20260721.csv").exists(),
                    reason="data/ 원본 없음(로컬 전용)")
def test_real_pregnancy_csv_has_m_grade_kept_as_is():
    c = loaders.read_source(REAL_DATA / "한국의약품안전관리원_임부금기약물_20260721.csv",
                            loaders.normalize_pregnancy, "pregnancy_contra", loaders.AS_OF_KIDS)
    grades = {r["grade"] for r in c.records.values()}
    assert grades == {"1", "2", "M"}
    assert c.stats.skipped == 0
