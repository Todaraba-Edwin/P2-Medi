"""AG-03 원격 코퍼스 어댑터 오프라인 시험: 가짜 연결·가짜 임베딩(네트워크·원격 DB 없음)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ag02_synth import ctx as base_ctx  # noqa: E402
from ag03_synth import IBU, PAIR_IBU_WAR, SEQ_RX, WAR, synth_chunks, synth_index  # noqa: E402

from app.agent.tools import corpus_remote as cr  # noqa: E402
from app.agent.tools.corpus import ChunkFilter, CorpusIndex  # noqa: E402
from app.agent.tools.search_reason import SearchReasonArgs, search_reason  # noqa: E402


class FakeCur:
    def __init__(self, db: FakeDb) -> None:
        self.db, self._rows = db, []

    def execute(self, sql, params=None):
        self.db.log.append((sql, params))
        if "information_schema.columns" in sql:
            self._rows = [(c,) for c in self.db.columns]
        elif sql.startswith("SELECT chunk_id, 1 -"):
            self._rows = list(self.db.vector_rows)
        elif sql.startswith("SELECT chunk_id,") and "FROM corpus_chunks ORDER BY" in sql:
            cols = [c.strip() for c in sql[len("SELECT "): sql.index(" FROM")].split(",")]
            self._rows = [tuple(self.db.rows[i].get(c) for c in cols) for i in range(len(self.db.rows))]
            self.db.selected_cols = cols
        else:
            self._rows = []

    def fetchall(self):
        r, self._rows = self._rows, []
        return r

    def fetchmany(self, n):
        r, self._rows = self._rows[:n], self._rows[n:]
        return r


class FakeConn:
    def __init__(self, db: FakeDb) -> None:
        self.db, self.read_only, self.closed = db, False, False
        db.conns.append(self)

    def cursor(self):
        return FakeCur(self.db)

    def close(self):
        self.closed = True


class FakeDb:
    def __init__(self, chunks, columns=None, vector_rows=()):
        self.rows = []
        for c in chunks:  # DB 표현: 날짜는 date, NULL 가능한 배열
            r = dict(c)
            r["base_date"] = date.fromisoformat(c["base_date"])
            r["code_status"] = ""
            r["year"], r["source_file"], r["effective_date"] = 2026, "f.csv", date(2026, 7, 1)
            self.rows.append(r)
        self.columns = set(columns) if columns is not None else set(cr.BASE_COLUMNS) | set(cr.OPTIONAL_COLUMNS) | {"embedding"}
        self.vector_rows, self.log, self.conns, self.selected_cols = list(vector_rows), [], [], []

    def __call__(self):
        return FakeConn(self)


def fake_embed(text):
    return [0.5] * cr.DIM


# --------------------------------------------------------------------------- 로더

def test_loader_builds_index_equal_to_local():
    chunks = synth_chunks()
    idx = CorpusIndex.from_db(FakeDb(chunks))
    ref = synth_index()
    assert len(idx) == len(ref)
    assert idx.get("l2p-war")["base_date"] == "2026-07-21"  # date → 문자열
    q = "임부금기 출혈"
    assert [h.chunk["chunk_id"] for h in idx.search(q, top_k=5)] == [h.chunk["chunk_id"] for h in ref.search(q, top_k=5)]
    assert not idx.dangling_refs()


def test_loader_is_read_only_and_closes():
    db = FakeDb(synth_chunks())
    cr.load_corpus_from_db(db)
    assert all(c.read_only and c.closed for c in db.conns)
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER")) for s, _ in db.log)
    assert "embedding" not in db.selected_cols  # 벡터 열은 읽지 않는다


def test_optional_columns_read_only_when_present():
    full = FakeDb(synth_chunks())
    cr.load_corpus_from_db(full)
    assert {"year", "source_file", "effective_date"} <= set(full.selected_cols)
    partial = FakeDb(synth_chunks(), columns=set(cr.BASE_COLUMNS) | {"year"})
    idx = cr.load_corpus_from_db(partial)
    assert "year" in partial.selected_cols and "source_file" not in partial.selected_cols and "effective_date" not in partial.selected_cols
    assert "source_file" not in idx.chunks[0]
    none = FakeDb(synth_chunks(), columns=set(cr.BASE_COLUMNS))
    cr.load_corpus_from_db(none)
    assert not set(none.selected_cols) & set(cr.OPTIONAL_COLUMNS)


def test_effective_date_becomes_iso_string():
    idx = cr.load_corpus_from_db(FakeDb(synth_chunks()))
    assert idx.chunks[0]["effective_date"] == "2026-07-01"


def test_missing_required_column_and_empty_table_fail():
    with pytest.raises(RuntimeError, match="필수 열"):
        cr.load_corpus_from_db(FakeDb(synth_chunks(), columns={"chunk_id", "text"}))
    with pytest.raises(RuntimeError, match="미적재"):
        cr.load_corpus_from_db(FakeDb([]))


def test_null_arrays_become_empty_lists():
    chunks = synth_chunks()
    db = FakeDb(chunks)
    db.rows[0]["ingr_codes"] = None
    db.rows[0]["refs"] = None
    c = cr.load_corpus_from_db(db).chunks
    assert all(isinstance(x["ingr_codes"], list) and isinstance(x["refs"], list) for x in c)


# --------------------------------------------------------------------------- WHERE 생성

def test_weak_only_filter_has_no_sql_predicate():
    for flt in (ChunkFilter(), ChunkFilter(layers=frozenset({"L3"})), ChunkFilter(layers=frozenset({"L2"}), chunk_kinds=frozenset({"l2_preg"})),
                ChunkFilter(ingr_names=frozenset({"warfarin"}))):
        assert cr.build_where(flt) == ([], [])


def test_strong_filter_builds_params_not_string_interpolation():
    flt = ChunkFilter(layers=frozenset({"L2"}), ingr_codes=frozenset({WAR, IBU}), item_seq="x'; DROP TABLE t;--", section_prefix="UD")
    conds, params = cr.build_where(flt)
    sql = " AND ".join(conds)
    assert "ingr_codes && %s::text[]" in sql and "layer = ANY" in sql and "section LIKE" in sql
    assert "DROP" not in sql and "x'" not in sql  # 값은 전부 파라미터
    assert sorted([IBU, WAR]) in params and "x'; DROP TABLE t;--" in params and "UD %" in params


def test_like_prefix_escapes_wildcards():
    _, params = cr.build_where(ChunkFilter(item_seq="1", section_prefix="U_D%"))
    assert "U\\_D\\% %" in params


# --------------------------------------------------------------------------- 어댑터

def test_search_returns_rows_sorted_and_read_only():
    db = FakeDb([], vector_rows=[("l2p-war", 0.9), ("l2p-ibu-m", 0.8)])
    fn = cr.PgVectorSearch(db, fake_embed)
    out = fn("임부 출혈", k=10, filters=ChunkFilter(ingr_codes=frozenset({WAR})))
    assert out == [("l2p-war", 0.9), ("l2p-ibu-m", 0.8)]
    sql, params = db.log[-1]
    assert "embedding <=> %s::vector" in sql and "ingr_codes && %s::text[]" in sql and sql.rstrip().endswith("LIMIT %s")
    assert params[-1] == 10 and params[0].startswith("[") and params[0] == params[-2]
    assert fn.last_stats.mode == "strong" and fn.last_stats.rows == 2
    assert any("hnsw.ef_search" in s for s, _ in db.log)
    assert all(c.read_only and c.closed for c in db.conns)


def test_weak_filter_uses_global_search_without_layer_predicate():
    db = FakeDb([], vector_rows=[("a", 0.5)])
    fn = cr.PgVectorSearch(db, fake_embed)
    fn("술 상호작용", k=100, filters=ChunkFilter(layers=frozenset({"L3"})))
    sql, _ = db.log[-1]
    assert "layer" not in sql and fn.last_stats.mode == "global"


def test_empty_query_or_zero_k_skips_without_db_or_embedding():
    calls = []
    db = FakeDb([])
    fn = cr.PgVectorSearch(db, lambda t: calls.append(t) or [0.0] * cr.DIM)
    assert fn("  ", k=5, filters=ChunkFilter()) == [] and fn("q", k=0, filters=ChunkFilter()) == []
    assert not calls and not db.conns and fn.last_stats.mode == "skipped"


def test_zero_results_is_empty_list():
    fn = cr.PgVectorSearch(FakeDb([], vector_rows=[]), fake_embed)
    assert fn("없는 질의", k=5, filters=ChunkFilter(item_seq="000")) == []
    assert fn.last_stats.rows == 0 and fn.last_stats.error is None


def test_embedding_failure_degrades_with_class_name_only():
    def boom(t):
        raise RuntimeError("sk-SECRET-KEY leaked?")

    fn = cr.PgVectorSearch(FakeDb([]), boom)
    assert fn("q", k=5, filters=ChunkFilter()) == []
    assert fn.last_stats.error == "RuntimeError" and "SECRET" not in repr(fn.last_stats)


def test_db_failure_degrades_and_closes():
    class BadDb(FakeDb):
        def __call__(self):
            c = super().__call__()
            c.cursor = lambda: (_ for _ in ()).throw(ConnectionError("postgresql://u:PW@h/db"))
            return c

    db = BadDb([])
    fn = cr.PgVectorSearch(db, fake_embed)
    assert fn("q", k=5, filters=ChunkFilter()) == []
    assert fn.last_stats.error == "ConnectionError" and "PW" not in repr(fn.last_stats) and db.conns[0].closed


def test_wrong_dimension_is_rejected():
    fn = cr.PgVectorSearch(FakeDb([]), lambda t: [0.1, 0.2])
    assert fn("q", k=5, filters=ChunkFilter()) == []
    assert fn.last_stats.error == "ValueError"


def test_query_embedding_cached():
    calls = []
    fn = cr.PgVectorSearch(FakeDb([], vector_rows=[]), lambda t: calls.append(t) or [0.1] * cr.DIM)
    for _ in range(3):
        fn("같은 질의", k=5, filters=ChunkFilter())
    assert calls == ["같은 질의"]


# --------------------------------------------------------------------------- 도구 연결(계약 불변, 필터 위반 0)

def test_tool_uses_remote_vector_and_drops_out_of_filter_ids():
    chunks = synth_chunks()
    idx = CorpusIndex.from_db(FakeDb(chunks))
    # 가짜 DB가 필터를 어기고 L3·다른 성분 청크를 섞어 돌려줘도 도구 결과에는 남지 않는다.
    db = FakeDb([], vector_rows=[("l3e-int", 0.9), ("l2p-ibu-m", 0.8), ("l2p-war", 0.7)])
    fn = cr.PgVectorSearch(db, fake_embed)
    ctx = base_ctx()
    ctx.corpus, ctx.vector_search_fn = idx, fn
    out = search_reason(SearchReasonArgs(query="임신 중 출혈 위험", ingr_codes=[WAR]), ctx)
    chunks_out = [i for i in out["items"] if i["kind"] == "chunk" and i["relation"] == "hit"]
    assert chunks_out and all(WAR in i["ingr_codes"] for i in chunks_out)
    assert "l3e-int" not in {i["evidence_id"] for i in chunks_out}


def test_tool_falls_back_to_bm25_when_vector_returns_nothing():
    idx = CorpusIndex.from_db(FakeDb(synth_chunks()))
    ctx = base_ctx()
    ctx.corpus, ctx.vector_search_fn = idx, cr.PgVectorSearch(FakeDb([], vector_rows=[]), fake_embed)
    out = search_reason(SearchReasonArgs(query="출혈 위험", ingr_codes=[IBU, WAR]), ctx)
    assert any(i["status"] == "FOUND" for i in out["items"])


def test_tool_no_match_returns_explicit_no_evidence():
    idx = CorpusIndex.from_db(FakeDb(synth_chunks()))
    ctx = base_ctx()
    ctx.corpus, ctx.vector_search_fn = idx, cr.PgVectorSearch(FakeDb([], vector_rows=[]), fake_embed)
    out = search_reason(SearchReasonArgs(query="완전히없는질의어휘xyzq", ingr_codes=["999999ATB"]), ctx)
    assert [i["status"] for i in out["items"]] == ["NO_EVIDENCE"]


def test_pair_constants_present():
    assert PAIR_IBU_WAR and SEQ_RX
