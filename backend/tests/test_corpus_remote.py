"""load_corpus 원격 적재 경로(가짜 연결, 네트워크 없음): --yes 거부, 중복 0, 기존 테이블 비접촉, 비밀 비출력."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import load_corpus as lc  # noqa: E402
from embed_corpus import text_hash  # noqa: E402


class FakeCur:
    def __init__(self, db):
        self.db, self._res = db, []

    def execute(self, sql, params=None):
        self.db.executed.append(sql)
        if sql.startswith("SELECT COUNT"):
            self._res = [(len(self.db.rows),)]
        elif sql.startswith("SELECT chunk_id"):
            self._res = [(k,) for k in self.db.rows]

    def executemany(self, sql, rows):
        assert "ON CONFLICT (chunk_id) DO NOTHING" in sql
        for r in rows:
            self.db.rows.setdefault(r[0], r)

    def fetchone(self):
        return self._res[0]

    def fetchall(self):
        return self._res


class FakeDb:
    def __init__(self):
        self.rows, self.executed = {}, []

    def connect(self, dsn):
        db = self

        class Conn:
            def cursor(self):
                return FakeCur(db)

            def commit(self):
                pass

            def close(self):
                pass

        return Conn()


def chunk(i, text="t"):
    return {"chunk_id": f"c{i}", "chunk_kind": "k", "parent_id": "", "refs": [], "pair_id": None, "layer": "L2", "issuer": "x", "doc_type": "d",
            "notice_no": "", "base_date": "2026-07-21", "locator": "l", "ingr_codes": ["A"], "ingr_names": [], "license": "x", "text": text, "source_ref": "s"}


def test_refuses_without_yes(monkeypatch):
    monkeypatch.setenv("X_DSN", "postgresql://u:SECRETPW@h/db")
    with pytest.raises(lc.RemoteLoadRefused):
        lc.remote_load([chunk(1)], "X_DSN", False, connect=FakeDb().connect)


def test_idempotent_and_vectors_and_no_dsn_leak(monkeypatch, capsys):
    monkeypatch.setenv("X_DSN", "postgresql://u:SECRETPW@h/db")
    db = FakeDb()
    import numpy as np

    mat = np.ones((1, 4), dtype="<f4")
    chunks = [chunk(i, "같은 텍스트") for i in range(5)]
    vecs = (mat, {text_hash("같은 텍스트"): 0})
    r1 = lc.remote_load(chunks, "X_DSN", True, connect=db.connect, vectors=vecs, batch_rows=2)
    r2 = lc.remote_load(chunks, "X_DSN", True, connect=db.connect, vectors=vecs, batch_rows=2)
    assert (r1["added"], r2["added"], r2["sent"], r2["after"]) == (5, 0, 0, 5)
    assert all(row[-1] == "[1,1,1,1]" for row in db.rows.values())  # 같은 텍스트 벡터를 공유
    assert all(row[2] is None for row in db.rows.values())  # parent_id "" -> NULL
    out = capsys.readouterr().out
    assert "SECRETPW" not in out and "SECRETPW" not in "".join(db.executed)
    ddl = "".join(db.executed)
    assert "DROP" not in ddl and "TRUNCATE" not in ddl and "contra_pair" not in ddl


def test_drop_needs_yes_and_only_corpus(monkeypatch):
    monkeypatch.setenv("X_DSN", "postgresql://u:p@h/db")
    with pytest.raises(lc.RemoteLoadRefused):
        lc.remote_drop("X_DSN", False, connect=FakeDb().connect)
    db = FakeDb()
    lc.remote_drop("X_DSN", True, connect=db.connect)
    assert db.executed == ["DROP TABLE IF EXISTS corpus_chunks"]


def test_schema_template_renders_1536():
    sql = lc.render_sql(1536)
    assert "vector(1536)" in sql and "{{DIM}}" not in sql and "hnsw" not in sql.lower().split("create table")[0] and "USING hnsw" not in sql
