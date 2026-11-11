"""BE-05 L2 코퍼스 빌더·적재 시험. 합성 소표본만 쓰고 원격·API 호출은 없다."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_corpus_l2 as B  # noqa: E402
import load_corpus as L  # noqa: E402


def _combo(i: int, ca: str, na: str, cb: str, nb: str, reason: str, gosi: str = "20200130") -> dict:
    return {"id": f"contra_{i}", "text": "x", "metadata": {"성분코드A": ca, "성분명A": na, "성분코드B": cb, "성분명B": nb, "금기사유": reason, "고시번호": gosi, "비고": ""}}


@pytest.fixture
def json_path(tmp_path: Path) -> Path:
    rows = [
        _combo(1, "AAA000AAA", "alpha", "BBB000BBB", "beta", "독성 증가"),
        _combo(2, "BBB000BBB", "beta", "AAA000AAA", "alpha", "독성 증가"),  # 방향이 반대인 같은 조합 → 합쳐진다
        _combo(3, "AAA000AAA", "alpha", "BBB000BBB", "beta", "다른 사유"),  # 같은 쌍, 사유가 다르면 별도 청크
        _combo(4, "CCC000CCC", "gamma", "AAA000AAA", "alpha", "QT 연장", "bad"),
    ]
    p = tmp_path / "combo.json"
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return p


PREG = [
    {"성분명": "drugM", "성분코드": "M00000AAA", "금기등급": "M", "상세정보": "상병에 따라 1등급 또는 2등급 적용 (원문)", "고시번호": "20200130"},
    {"성분명": "drug1", "성분코드": "P10000AAA", "금기등급": "1", "상세정보": "임부 투여금기", "고시번호": "20200130"},
    {"성분명": "drug1", "성분코드": "P10000AAA", "금기등급": "1", "상세정보": "임부 투여금기", "고시번호": "20260052"},  # 같은 성분의 중복 행
]
AGE = [{"성분명": "drugA", "성분코드": "A00000AAA", "특정연령": "12 (1)", "특정연령단위": "세 (3)", "연령처리조건": "미만 (1)", "상세정보": "안전성 미확립", "고시번호": "20070030"}]

MD = """---
rows: 3
---

| 연번 | 유효성분 | 연령기준 | 해당 제형 |
|---|---|---|---|
| 9 | atropine | 12세 미만<br>4세 미만 | 점안제(1%)<br>점안제(0.125%) |
| 17 | <삭제> |  |  |
| 68 | mesalazine | 2세 미만 | 좌제 |
"""


@pytest.fixture
def md_path(tmp_path: Path) -> Path:
    p = tmp_path / "b2.md"
    p.write_text(MD, encoding="utf-8")
    return p


@pytest.fixture
def chunks(json_path: Path, md_path: Path) -> list[dict]:
    return B.build_combo_chunks(json_path) + B.build_detail_chunks(PREG, AGE, "preg.csv", "age.csv") + B.build_bupyo2_chunks(md_path)


def test_chunk_id_deterministic(json_path: Path):
    a = B.build_combo_chunks(json_path)
    b = B.build_combo_chunks(json_path)
    assert [c["chunk_id"] for c in a] == [c["chunk_id"] for c in b]
    assert len({c["chunk_id"] for c in a}) == len(a)
    assert B.manifest_of(a)["sha256"] == B.manifest_of(b)["sha256"]


def test_combo_dedup_and_pair_id_order_independent(json_path: Path):
    cs = B.build_combo_chunks(json_path)
    assert len(cs) == 3  # (A,B,독성) 합침 + (A,B,다른 사유) + (A,C,QT)
    assert B.make_pair_id("AAA000AAA", "BBB000BBB") == B.make_pair_id("BBB000BBB", "AAA000AAA") == "AAA000AAA+BBB000BBB"
    assert all(c["ingr_codes"] == sorted(c["ingr_codes"]) and c["layer"] == "L2" and c["base_date"] == "2026-07-31" for c in cs)
    # 형식이 맞지 않는 고시번호는 빈 값(연도 4자리+번호 4자리만 인정)
    assert [c["notice_no"] for c in cs if "QT" in c["text"]] == [""]


def test_pair_id_lookup_returns_all_chunks_of_pair(chunks: list[dict]):
    idx = B.pair_index(chunks)
    got = idx["AAA000AAA+BBB000BBB"]
    assert len(got) == 2 and {c["chunk_id"] for c in got} == {c["chunk_id"] for c in chunks if c["pair_id"] == "AAA000AAA+BBB000BBB"}
    assert idx[B.make_pair_id("BBB000BBB", "AAA000AAA")] == got  # 한 번 조회, 순서 무관


def test_pregnancy_m_grade_kept_verbatim(chunks: list[dict]):
    m = next(c for c in chunks if c["ingr_codes"] == ["M00000AAA"])
    assert "임부금기 M등급: 상병에 따라 1등급 또는 2등급 적용 (원문)" in m["text"]
    assert "임부금기 1등급" not in m["text"] and "임부금기 2등급" not in m["text"]  # 1·2로 환산하지 않는다(RFP-17)
    p1 = next(c for c in chunks if c["ingr_codes"] == ["P10000AAA"])
    assert p1["notice_no"] == "20260052" and p1["locator"] == "preg.csv 행 2,3"  # 최댓값 고시번호, 중복 행도 한 청크


def test_age_detail_condition_text(chunks: list[dict]):
    a = next(c for c in chunks if c["chunk_kind"] == "l2_age")
    assert "연령금기 12세 미만: 안전성 미확립" in a["text"] and a["ingr_names"] == ["drugA"]


def test_bupyo2_row_has_column_names_and_parent(chunks: list[dict]):
    rows = [c for c in chunks if c["chunk_kind"] == "l1_bupyo2_row"]
    table = next(c for c in chunks if c["chunk_kind"] == "l1_bupyo2_table")
    assert len(rows) == 2  # 삭제 행 제외
    by_id = {c["chunk_id"]: c for c in chunks}
    for r in rows:
        assert all(col in r["text"] for col in ("연번", "유효성분", "연령기준", "해당 제형")) and "별표 2" in r["text"]
        assert by_id[r["parent_id"]] is table and "열: 연번 | 유효성분 | 연령기준 | 해당 제형" in table["text"]
    atropine = next(r for r in rows if "atropine" in r["text"])
    assert "연령기준 4세 미만 ↔ 해당 제형 점안제(0.125%)" in atropine["text"]  # 줄 수가 같은 행은 짝을 적는다
    assert atropine["notice_no"] == "20260052" and atropine["locator"] == "별표 2 연번 9"


def test_no_dangling_links(chunks: list[dict]):
    rep = B.link_report(chunks)
    assert rep["dangling_parent"] == 0 and rep["dangling_refs"] == 0 and rep["with_parent"] == 2
    broken = [*chunks, {**chunks[0], "chunk_id": "x", "refs": ["nope"], "parent_id": "nope2"}]
    rep2 = B.link_report(broken)
    assert rep2["dangling_parent"] == 1 and rep2["dangling_refs"] == 1  # 점검기가 실제로 끊어진 참조를 잡는다


def test_sqlite_load_idempotent(chunks: list[dict], tmp_path: Path):
    db = tmp_path / "c.db"
    first = L.load_sqlite(chunks, db)
    second = L.load_sqlite(chunks, db)
    assert first["inserted"] == len(chunks) and second["inserted"] == 0 and second["after"] == len(chunks)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(DISTINCT chunk_id) FROM corpus_chunks").fetchone()[0] == len(chunks)
        row = conn.execute("SELECT refs, ingr_codes FROM corpus_chunks WHERE pair_id=?", ("AAA000AAA+BBB000BBB",)).fetchone()
        assert json.loads(row[0]) == [] and json.loads(row[1]) == ["AAA000AAA", "BBB000BBB"]
        assert conn.execute("SELECT COUNT(*) FROM corpus_chunks WHERE pair_id=?", ("AAA000AAA+BBB000BBB",)).fetchone()[0] == 2
    finally:
        conn.close()


def test_sql_template_has_all_columns_and_dim():
    sql = L.render_sql(512)
    code = "\n".join(ln for ln in sql.splitlines() if not ln.lstrip().startswith("--"))  # 주석은 제외하고 DDL만 본다
    assert "vector(512)" in code and "{{DIM}}" not in sql and "hnsw" not in code.lower() and "ON CONFLICT" not in code
    assert all(f in sql for f in B.FIELDS) and "IF NOT EXISTS" in sql
    h = L.render_sql(1536, hnsw=True)
    assert "hnsw" in h.lower() and "CREATE TABLE" not in h
    with pytest.raises(ValueError):
        L.render_sql(777)


def test_remote_load_refused_without_yes_or_env(chunks: list[dict], monkeypatch: pytest.MonkeyPatch):
    def boom(_dsn: str):
        raise AssertionError("접속하면 안 된다")

    monkeypatch.delenv("X_CORPUS_DSN", raising=False)
    with pytest.raises(L.RemoteLoadRefused):
        L.remote_load(chunks, "X_CORPUS_DSN", yes=False, connect=boom)
    with pytest.raises(L.RemoteLoadRefused):
        L.remote_load(chunks, "X_CORPUS_DSN", yes=True, connect=boom)  # 환경변수 없음


def test_remote_load_uses_on_conflict_do_nothing_with_fake_conn(chunks: list[dict], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("X_CORPUS_DSN", "postgresql://fake")
    seen: dict = {}

    class Cur:
        def execute(self, sql: str, *a):
            seen.setdefault("sql", []).append(sql)

        def fetchone(self):
            return (seen.get("n", 0),)  # COUNT(*)

        def fetchall(self):
            return []  # 기존 chunk_id 없음

        def executemany(self, sql: str, rows):
            seen["insert"], seen["n"] = sql, len(list(rows))

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            seen["commit"] = True

        def close(self):
            seen["closed"] = True

    out = L.remote_load(chunks, "X_CORPUS_DSN", yes=True, connect=lambda _d: Conn())
    assert out["sent"] == len(chunks) and out["input"] == len(chunks) and seen["n"] == len(chunks) and "ON CONFLICT (chunk_id) DO NOTHING" in seen["insert"]
    assert seen["commit"] and seen["closed"] and "vector(1536)" in seen["sql"][0]


def test_embed_plan_is_plan_only(chunks: list[dict]):
    plan = L.embed_plan(chunks, 512)
    assert plan["executed"] is False and plan["dimensions"] == 512 and plan["unique_texts"] <= len(chunks)


def test_estimate_dim_smaller_vectors(chunks: list[dict]):
    assert L.estimate(chunks, 512)["vector_mb"] < L.estimate(chunks, 1536)["vector_mb"]
