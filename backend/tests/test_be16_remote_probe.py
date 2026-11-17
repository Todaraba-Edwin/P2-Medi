"""be16_remote_probe: 가짜 연결(네트워크 없음). 블록마다 BEGIN READ ONLY … ROLLBACK, 쓰기 문장 거부, EXPLAIN 요약, 반복·저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import be16_remote_probe as p  # noqa: E402

WRITE_WORDS = ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "TRUNCATE", "CREATE", "REINDEX", "VACUUM", "COMMIT")

EXPLAIN_JSON = [{
    "Plan": {"Node Type": "Limit", "Actual Rows": 10, "Shared Hit Blocks": 120, "Shared Read Blocks": 7,
             "Plans": [{"Node Type": "Index Scan", "Index Name": p.HNSW_INDEX, "Actual Rows": 10}]},
    "Planning Time": 0.3, "Execution Time": 12.5,
}]


class Cur:
    def __init__(self, conn):
        self.conn, self._res = conn, []

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        self._res = self.conn.answer(sql)

    def fetchall(self):
        return self._res


class Conn:
    def __init__(self, answers=None, fail_on=None):
        self.executed: list[str] = []
        self.answers = {"transaction_read_only": [("on",)], "EXPLAIN": [(EXPLAIN_JSON,)], **(answers or {})}
        self.fail_on = fail_on
        self.closed = False

    def cursor(self):
        return Cur(self)

    def close(self):
        self.closed = True

    def answer(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("canceling statement due to statement timeout")
        for key, val in self.answers.items():
            if key in sql:
                return val
        return [(None,)]


def full_answers():
    return {
        "chunk_id LIKE 'l3p-%'": [("l3p-0000aaaa",)],
        "unnest(ingr_codes)": [("D000123", 23)],
        "information_schema.columns": [("year", "smallint"), ("base_date", "date")],
        "GROUP BY 1, 2 ORDER BY 1, 2": [("L1", "l1_article", 100, 100), ("L3", "l3_eyak_section", 27840, 27840)],
        "WHERE year IS NULL GROUP BY 1": [("2026", 27940)],
        "left(base_date::text, 4)": [("2026", 68818)],
        "pg_stat_user_tables": [(68818, 5, None, "2026-11-12", None, None)],
    }


def balanced(executed):
    begins = [i for i, s in enumerate(executed) if s.startswith("BEGIN READ ONLY")]
    rollbacks = [i for i, s in enumerate(executed) if s == "ROLLBACK"]
    return begins, rollbacks


@pytest.mark.parametrize("sql", [
    "UPDATE corpus_chunks SET year = 1", "SET hnsw.ef_search = 40", "ANALYZE corpus_chunks", "COMMIT",
    "SELECT 1; DELETE FROM corpus_chunks", "BEGIN", "VACUUM corpus_chunks",
])
def test_guard_rejects_writes_and_session_set(sql):
    with pytest.raises(p.ProbeRefused):
        p.guard_sql(sql)


@pytest.mark.parametrize("sql", [
    "BEGIN READ ONLY", "SET LOCAL hnsw.ef_search = 40", "SHOW transaction_read_only", "ROLLBACK",
    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT chunk_id FROM corpus_chunks LIMIT 10",
    "SELECT n_dead_tup, last_analyze, last_autovacuum FROM pg_stat_user_tables",
])
def test_guard_allows_read_statements(sql):
    assert p.guard_sql(sql) == sql


def test_read_only_block_always_rolls_back_even_on_error():
    conn = Conn()
    s = p.Session(conn)
    with pytest.raises(ValueError), s.read_only():
        raise ValueError("x")
    assert conn.executed[0] == "BEGIN READ ONLY"
    assert conn.executed[1] == "SET LOCAL statement_timeout = '30s'"
    assert conn.executed[-1] == "ROLLBACK"


def test_read_only_block_refuses_when_not_read_only():
    conn = Conn({"transaction_read_only": [("off",)]})
    with pytest.raises(p.ProbeRefused), p.Session(conn).read_only():
        pass
    assert conn.executed[-1] == "ROLLBACK"


def test_summarize_explain_picks_index_rows_time_buffers():
    s = p.summarize_explain(json.dumps(EXPLAIN_JSON))
    assert s["plan_first"] == "Limit"
    assert s["indexes"] == [p.HNSW_INDEX] and s["uses_hnsw"]
    assert (s["rows"], s["execution_ms"], s["shared_hit"], s["shared_read"]) == (10, 12.5, 120, 7)


def test_run_probe_full_is_read_only_and_repeats():
    conn = Conn(full_answers())
    sleeps: list[float] = []
    rep = p.run_probe(conn, repeat=3, interval=300, log=lambda s: None, sleep=sleeps.append)
    assert not any(w in s.upper().split()[0] for s in conn.executed for w in WRITE_WORDS)
    assert not any(s.upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER")) for s in conn.executed)
    begins, rollbacks = balanced(conn.executed)
    assert len(begins) == len(rollbacks) > 0
    assert all(b < r for b, r in zip(begins, rollbacks, strict=True))
    assert sleeps == [300, 300]  # 3회 → 대기 2번, 대기 중 트랜잭션 없음
    assert len(rep["4_repeat"]) == 3 and rep["4_repeat"][0]["table"]["n_dead_tup"] == 5
    assert rep["sample"] == {"chunk_id": "l3p-0000aaaa", "ingr_code": "D000123", "ingr_code_l2_chunks": 23}
    assert set(rep["3_strong"]) == {"off", "relaxed_order"} and rep["3_strong"]["off"]["fills_limit"]
    assert "SET LOCAL hnsw.ef_search = 40" in conn.executed and "SET LOCAL hnsw.iterative_scan = relaxed_order" in conn.executed
    assert rep["rfp04_year"]["year_column"] == "smallint" and rep["rfp04_year"]["year_null_total"] == 27940
    assert not any(s.startswith("SET ") and not s.startswith("SET LOCAL") for s in conn.executed)


def test_block_error_is_recorded_and_next_blocks_run():
    conn = Conn(full_answers(), fail_on="iterative_scan = relaxed_order")
    rep = p.run_probe(conn, repeat=1, interval=0, log=lambda s: None, sleep=lambda s: None)
    assert "statement timeout" in rep["3_strong"]["relaxed_order"]["error"]
    assert "rows" in rep["3_strong"]["off"] and "rfp04_year" in rep
    begins, rollbacks = balanced(conn.executed)
    assert len(begins) == len(rollbacks)


def test_main_saves_summary_without_text(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "resolve_dsn", lambda env: "postgresql://fake")
    conn = Conn(full_answers())
    rc = p.main(["--repeat", "1", "--interval", "0", "--repo-root", str(tmp_path)], connect_fn=lambda dsn, autocommit: conn,
                sleep=lambda s: None)
    assert rc == 0 and conn.closed
    files = list((tmp_path / "logs" / "remote").glob("be16_probe_*.json"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "postgresql://" not in body and json.loads(body)["sample"]["chunk_id"] == "l3p-0000aaaa"


def test_main_refuses_bad_repeat():
    assert p.main(["--repeat", "0"], connect_fn=lambda *a, **k: pytest.fail("연결하면 안 됨")) == 2
