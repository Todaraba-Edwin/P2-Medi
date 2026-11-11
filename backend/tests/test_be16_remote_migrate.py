"""be16_remote_migrate: 가짜 연결(네트워크 없음). plan은 쓰기 0, 기대 불일치 시 롤백·중단, 백업 행 수 대조, --yes 없는 apply 거부."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import be16_remote_migrate as m  # noqa: E402

WRITE_WORDS = ("INSERT", "UPDATE", "ALTER", "DELETE", "DROP", "TRUNCATE", "REINDEX", "CREATE")


class Cur:
    def __init__(self, conn):
        self.conn, self._res, self.rowcount = conn, [], 0

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        self._res = self.conn.answer(sql)

    def executemany(self, sql, rows):
        self.conn.executed.append(sql)

    def fetchone(self):
        return self._res[0]

    def fetchall(self):
        return self._res


class Conn:
    def __init__(self, answers=None):
        self.executed, self.commits, self.rollbacks = [], 0, 0
        self.answers = answers or {}

    def cursor(self):
        return Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def answer(self, sql):
        for key, val in self.answers.items():
            if key in sql:
                return val() if callable(val) else val
        return [(0,)]


def test_transaction_rolls_back_on_mismatch():
    conn = Conn()

    def bad(cur):
        m.expect_eq("행 수", 5, 6)
        return {}

    with pytest.raises(m.StageAbort):
        m.transaction(conn, "t", bad, log=lambda s: None)
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_transaction_commits_once_on_success():
    conn = Conn()
    assert m.transaction(conn, "t", lambda c: {"ok": 1}, log=lambda s: None) == {"ok": 1}
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_stage1_aborts_when_precount_differs():
    conn = Conn({"COUNT(*) FROM caution": [(1741,)]})
    with pytest.raises(m.StageAbort):
        m.transaction(conn, "단계 1", m.stage1, log=lambda s: None)
    assert conn.rollbacks == 1 and not any("ALTER" in s for s in conn.executed)


def test_stage1_aborts_when_constraint_not_unique():
    conn = Conn({
        "COUNT(*) FROM caution": [(m.EXPECT["caution_before"],)], "COUNT(*) FROM corpus_chunks": [(m.EXPECT["corpus_before"],)],
        "pg_constraint": [("a", "CHECK kind"), ("b", "CHECK kind")],
    })
    with pytest.raises(m.StageAbort):
        m.transaction(conn, "단계 1", m.stage1, log=lambda s: None)
    assert conn.rollbacks == 1 and not any("DROP CONSTRAINT" in s for s in conn.executed)


def test_stage3_contra_aborts_when_target_count_differs():
    conn = Conn({"COUNT(*) FROM contra_pair WHERE": [(23_000,)]})
    with pytest.raises(m.StageAbort):
        m.transaction(conn, "단계 3", m.stage3_contra, log=lambda s: None)
    assert conn.rollbacks == 1 and not any(s.startswith("UPDATE") for s in conn.executed)


def test_plan_does_not_write():
    st = {"stage": 1}
    conn = Conn({
        "information_schema": [], "pg_constraint": [], "GROUP BY": [], "pg_relation_size": [(1,)], "COUNT": [(1,)],
    })
    ns = SimpleNamespace(stats=SimpleNamespace(), records={"a": 1})
    sources = {m.loaders.COMBO_JSON_NAME: ns, m.loaders.ELDERLY_KIDS_CSV_NAME: ns}
    lines: list[str] = []
    m.do_plan(conn, [{"chunk_id": "c", "year": 2026}], sources, log=lines.append)
    assert st and conn.commits == 0
    upper = [s.upper().lstrip() for s in conn.executed]
    assert not any(u.startswith(w) for u in upper for w in WRITE_WORDS)


def test_apply_requires_yes(capsys):
    assert m.main(["apply"]) == 2
    assert "--yes" in capsys.readouterr().err


def test_meta_map_only_chunks_with_values():
    chunks = [{"chunk_id": "a", "year": 2026, "source_file": "f", "effective_date": "2026-01-02"},
              {"chunk_id": "b", "year": None, "source_file": "", "effective_date": ""}, {"chunk_id": "c", "source_file": "g"}]
    assert m.meta_map(chunks) == {"a": (2026, "f", "2026-01-02"), "c": (None, "g", None)}


def test_backup_checks_row_counts(tmp_path):
    conn = Conn({"FROM contra_pair": [("k1", "2026-07-21"), ("k2", "2026-07-21")],
                 "FROM corpus_chunks": [("c1", "2026-07-21", None, "", None)]})
    info = m.backup(conn, tmp_path / "b.jsonl.gz", 2, 1)
    assert info["rows"] == {"contra_pair": 2, "corpus_chunks": 1}
    with gzip.open(tmp_path / "b.jsonl.gz", "rt") as f:
        assert len(f.readlines()) == 3
    with pytest.raises(m.StageAbort):
        m.backup(conn, tmp_path / "c.jsonl.gz", 3, 1)


def test_stage3_corpus_metadata_only_touches_mapped_rows():
    remote_meta = {"a": (None, "", None), "b": (None, "", None), "c": (2020, "x", "2020-01-01")}
    base = {"a": "2026-07-21", "b": "2026-07-21", "c": "2026-07-21"}
    state = {"updated": False}

    class C(Cur):
        def execute(self, sql, params=None):
            self.conn.executed.append(sql)
            if sql.startswith("UPDATE corpus_chunks SET base_date"):
                state["updated"], self.rowcount = True, 2
                for k in ("a", "b"):
                    base[k] = "2026-07-31"
                self._res = []
            elif "SELECT chunk_id, base_date" in sql:
                self._res = [(k, __import__("datetime").date.fromisoformat(v)) for k, v in base.items()]
            elif "SELECT chunk_id, year" in sql:
                self._res = [(k, v[0], v[1], v[2]) for k, v in remote_meta.items()]
            elif "COUNT(*) FROM corpus_chunks WHERE" in sql:
                self._res = [(2,)]
            elif "COUNT(*) FROM corpus_chunks" in sql:
                self._res = [(3,)]
            else:
                self._res = [(0,)]

        def executemany(self, sql, rows):
            for y, sf, ed, cid in rows:
                remote_meta[cid] = (y, sf, ed)

    conn = Conn()
    conn.cursor = lambda: C(conn)  # type: ignore[method-assign]
    old = dict(m.EXPECT)
    m.EXPECT["combo_chunks"] = 2
    try:
        res = m.stage3_corpus(C(conn), {"a": (2026, "f.pdf", "2026-07-21"), "c": (2020, "x", "2020-01-01")})
    finally:
        m.EXPECT.update(old)
    assert res["meta_updated"] == 1 and remote_meta["a"] == (2026, "f.pdf", "2026-07-21") and remote_meta["b"] == (None, "", None)
