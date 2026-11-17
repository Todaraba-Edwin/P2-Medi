"""rfp04_year_backfill: 임시 파일·가짜 연결(네트워크 없음).

로컬: dry-run은 파일을 바꾸지 않는다, apply는 백업 + 원자 교체 + chunk_id·다른 칸 불변, 검사 실패 시 원본 유지.
원격: dry-run은 BEGIN READ ONLY … ROLLBACK, apply는 --yes·--expect·승인 파일이 없으면 연결 전 거부, 영향 수 불일치 시 ROLLBACK.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rfp04_year_backfill as y  # noqa: E402


def rec(cid, base_date="2026-07-21", **kw):
    r = {"chunk_id": cid, "chunk_kind": "l1_article", "layer": "L1", "base_date": base_date, "text": f"본문 {cid}",
         "source_ref": "고시|x.md", "item_seq": ""}
    r.update(kw)
    return r


def write_jsonl(path: Path, rows):
    path.write_text("".join(y.dumps(r) + "\n" for r in rows), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    write_jsonl(d / "l1_notice.jsonl", [rec("l1-a"), rec("l1-b"), rec("l1-c", year=2025), rec("l1-d", base_date="")])
    write_jsonl(d / "l3_eyak.jsonl", [rec("l3e-a", base_date="2026-11-10"), rec("l3e-b", base_date="2026-11-10", year="")])
    return d


# --------------------------------------------------------------------------- 유도 규칙

@pytest.mark.parametrize(("value", "want"), [
    ("2026-07-21", 2026), ("20260721", 2026), ("", None), (None, None), ("미상", None),
])
def test_derive_year(value, want):
    assert y.derive_year(value) == want


def test_derive_year_from_date_object():
    from datetime import date

    assert y.derive_year(date(2025, 1, 2)) == 2025


def test_with_year_places_after_source_ref_and_keeps_order():
    out = y.with_year(rec("x"), 2026)
    keys = list(out)
    assert keys[keys.index("source_ref") + 1] == "year"
    assert [k for k in keys if k != "year"] == list(rec("x"))


# --------------------------------------------------------------------------- 로컬

def test_local_dry_run_counts_and_changes_nothing(corpus):
    before = {p.name: sha(p) for p in corpus.iterdir()}
    rep = y.run_local(corpus, apply=False, expect=None, log=lambda s: None)
    assert rep["targets"] == 4 and rep["underivable"] == 1
    assert {f["file"]: f["targets"] for f in rep["files"]} == {"l1_notice.jsonl": 2, "l3_eyak.jsonl": 2}
    assert rep["sqlite"] == {"sqlite": "all.sqlite", "exists": False}
    assert {p.name: sha(p) for p in corpus.iterdir()} == before


def test_local_apply_backup_atomic_and_ids_unchanged(corpus):
    src = corpus / "l1_notice.jsonl"
    old_lines = src.read_text(encoding="utf-8").splitlines()
    rep = y.run_local(corpus, apply=True, expect=4, log=lambda s: None)
    assert rep["after_targets"] == 0
    backup = corpus / "l1_notice.before_rfp04year.jsonl"
    assert backup.read_text(encoding="utf-8").splitlines() == old_lines
    new = [json.loads(ln) for ln in src.read_text(encoding="utf-8").splitlines()]
    old = [json.loads(ln) for ln in old_lines]
    assert [r["chunk_id"] for r in new] == [r["chunk_id"] for r in old]
    for a, b in zip(old, new, strict=True):
        assert {k: v for k, v in a.items() if k != "year"} == {k: v for k, v in b.items() if k != "year"}
    assert [r.get("year") for r in new] == [2026, 2026, 2025, None]  # 기존 값 유지, 유도 불가는 그대로
    assert src.read_text(encoding="utf-8").splitlines()[2] == old_lines[2]  # 손대지 않은 줄은 바이트 그대로
    assert not list(corpus.glob(".*.tmp"))
    eyak = [json.loads(ln) for ln in (corpus / "l3_eyak.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["year"] for r in eyak] == [2026, 2026]


def test_local_apply_refuses_expect_mismatch_without_touching(corpus):
    before = {p.name: sha(p) for p in corpus.iterdir()}
    with pytest.raises(y.Refused):
        y.run_local(corpus, apply=True, expect=30_744, log=lambda s: None)
    assert {p.name: sha(p) for p in corpus.iterdir()} == before


def test_local_apply_refuses_existing_backup(corpus):
    (corpus / "l1_notice.before_rfp04year.jsonl").write_text("old\n", encoding="utf-8")
    src_sha = sha(corpus / "l1_notice.jsonl")
    with pytest.raises(y.Refused):
        y.run_local(corpus, apply=True, expect=None, log=lambda s: None)
    assert sha(corpus / "l1_notice.jsonl") == src_sha
    assert (corpus / "l1_notice.before_rfp04year.jsonl").read_text(encoding="utf-8") == "old\n"


def test_verify_transform_aborts_on_chunk_id_change():
    a = [y.dumps(rec("x"))]
    b = [y.dumps(y.with_year(rec("y"), 2026))]
    with pytest.raises(y.Abort, match="chunk_id"):
        y.verify_transform(a, b)


def test_verify_transform_aborts_on_other_field_change():
    a = [y.dumps(rec("x"))]
    b = [y.dumps(y.with_year(rec("x", text="바뀐 본문"), 2026))]
    with pytest.raises(y.Abort, match="year 외"):
        y.verify_transform(a, b)


def test_apply_file_keeps_original_when_post_write_check_fails(corpus, monkeypatch):
    src = corpus / "l1_notice.jsonl"
    before = sha(src)
    plan, old, new = y.plan_file(src)
    calls = {"n": 0}
    real = y.verify_transform

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 2:  # 임시 파일을 다시 읽은 뒤 검사에서 실패시킨다
            raise y.Abort("가짜 실패")
        return real(a, b)

    monkeypatch.setattr(y, "verify_transform", flaky)
    with pytest.raises(y.Abort):
        y.apply_file(src, plan, old, new)
    assert sha(src) == before
    assert not list(corpus.glob(".*.tmp"))
    assert not (corpus / "l1_notice.before_rfp04year.jsonl").exists()


def make_sqlite(path: Path, with_year: bool):
    con = sqlite3.connect(path)
    cols = "chunk_id TEXT PRIMARY KEY, base_date TEXT" + (", year INTEGER" if with_year else "")
    con.execute(f"CREATE TABLE corpus_chunks ({cols})")
    rows = [("a", "2026-07-21"), ("b", ""), ("c", "2026-11-10")]
    if with_year:
        con.executemany("INSERT INTO corpus_chunks VALUES (?, ?, ?)", [(*r, None) for r in rows] + [("d", "2026-01-01", 2025)])
    else:
        con.executemany("INSERT INTO corpus_chunks VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_sqlite_without_year_is_report_only(corpus):
    make_sqlite(corpus / "all.sqlite", with_year=False)
    before = sha(corpus / "all.sqlite")
    rep = y.run_local(corpus, apply=True, expect=None, log=lambda s: None)
    assert rep["sqlite"]["year_column"] is False
    assert sha(corpus / "all.sqlite") == before


def test_sqlite_with_year_is_filled_by_same_rule(corpus):
    db = corpus / "all.sqlite"
    make_sqlite(db, with_year=True)
    plan = y.sqlite_plan(db)
    assert (plan["targets"], plan["underivable"]) == (2, 1)
    y.run_local(corpus, apply=True, expect=None, log=lambda s: None)
    con = sqlite3.connect(db)
    got = dict(con.execute("SELECT chunk_id, year FROM corpus_chunks"))
    con.close()
    assert got == {"a": 2026, "b": None, "c": 2026, "d": 2025}


# --------------------------------------------------------------------------- 원격(가짜 연결)

class Cur:
    def __init__(self, conn):
        self.conn, self._res, self.rowcount = conn, [], -1

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        if sql.startswith("UPDATE"):
            self.rowcount = self.conn.update_rows
        self._res = self.conn.answer(sql)

    def fetchone(self):
        return self._res[0]

    def fetchall(self):
        return self._res


class Conn:
    def __init__(self, targets=30_744, bad=0, update_rows=30_744, null_left=0, types=None):
        self.executed: list[str] = []
        self.update_rows = update_rows
        self.closed = False
        t = types or [("year", "smallint"), ("base_date", "date")]
        self.answers = [
            ("transaction_read_only", [("on",)]),
            ("information_schema.columns", t),
            ("GROUP BY 1, 2", [("L1", "l1_article", 2904), ("L3", "l3_eyak_section", 27840)]),
            ("AND NOT (", [(bad,)]),
            ("WHERE year IS NULL AND", [(targets,)]),
            ("WHERE year IS NULL", [(null_left,)]),
        ]

    def cursor(self):
        return Cur(self)

    def close(self):
        self.closed = True

    def answer(self, sql):
        for key, val in self.answers:
            if key in sql:
                return val
        return []


def args_for(tmp_path, *extra):
    return y.build_parser().parse_args(["remote", "--repo-root", str(tmp_path), *extra])


def flag(tmp_path):
    f = tmp_path / y.FLAG_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("ok", encoding="utf-8")
    return f


@pytest.fixture
def fake_dsn(monkeypatch):
    monkeypatch.setattr(y, "resolve_dsn", lambda env: "postgresql://fake")


def test_remote_dry_run_read_only_and_rollback(tmp_path, fake_dsn):
    conn = Conn()
    rep = y.run_remote(args_for(tmp_path), connect_fn=lambda dsn, autocommit: conn, log=lambda s: None)
    assert conn.executed[0] == "BEGIN READ ONLY" and conn.executed[-1] == "ROLLBACK"
    assert not any(s.startswith(("UPDATE", "COMMIT")) for s in conn.executed)
    assert (rep["targets"], rep["underivable"]) == (30_744, 0)
    assert "EXTRACT(YEAR FROM base_date)::smallint" in rep["update_sql"]
    assert len(list((tmp_path / "logs" / "remote").glob("rfp04_year_*.json"))) == 1


@pytest.mark.parametrize(("extra", "with_flag"), [
    (["--apply", "--expect", "30744"], True),           # --yes 없음
    (["--apply", "--yes"], True),                        # --expect 없음
    (["--apply", "--yes", "--expect", "30744"], False),  # 승인 파일 없음
])
def test_remote_apply_refused_before_connect(tmp_path, fake_dsn, extra, with_flag):
    if with_flag:
        flag(tmp_path)

    def no_connect(*a, **k):
        pytest.fail("거부는 연결 전이어야 한다")

    assert y.main(["remote", "--repo-root", str(tmp_path), *extra], connect_fn=no_connect) == 2


def test_remote_apply_commits_when_counts_match(tmp_path, fake_dsn):
    flag(tmp_path)
    conn = Conn()
    rep = y.run_remote(args_for(tmp_path, "--apply", "--yes", "--expect", "30744"), connect_fn=lambda d, autocommit: conn,
                       log=lambda s: None)
    assert rep["committed"] and rep["updated"] == 30_744
    assert conn.executed[0] == "BEGIN" and conn.executed[-1] == "COMMIT" and "ROLLBACK" not in conn.executed
    upd = [s for s in conn.executed if s.startswith("UPDATE")]
    assert upd == ["UPDATE corpus_chunks SET year = EXTRACT(YEAR FROM base_date)::smallint WHERE year IS NULL AND base_date IS NOT NULL"]
    assert conn.closed


@pytest.mark.parametrize("kw", [
    {"update_rows": 30_743},          # 영향 행 수 ≠ 사전 대상
    {"targets": 30_000, "update_rows": 30_000},  # 사전 대상 ≠ --expect
    {"null_left": 5},                 # 남은 NULL ≠ 유도 불가
])
def test_remote_apply_rolls_back_on_mismatch(tmp_path, fake_dsn, kw):
    flag(tmp_path)
    conn = Conn(**kw)
    rc = y.main(["remote", "--repo-root", str(tmp_path), "--apply", "--yes", "--expect", "30744"], connect_fn=lambda d, autocommit: conn)
    assert rc == 3
    assert conn.executed[-1] == "ROLLBACK" and "COMMIT" not in conn.executed
    logs = list((tmp_path / "logs" / "remote").glob("rfp04_year_*.json"))
    assert len(logs) == 1 and json.loads(logs[0].read_text(encoding="utf-8"))["committed"] is False


def test_remote_text_base_date_uses_regex_rule():
    q = y.sql_for({"year": "smallint", "base_date": "text"})
    assert q["update"] == r"UPDATE corpus_chunks SET year = left(base_date, 4)::smallint WHERE year IS NULL AND base_date ~ '^\d{4}'"


def test_remote_rejects_non_integer_year_column():
    with pytest.raises(y.Abort):
        y.sql_for({"year": "text", "base_date": "date"})
