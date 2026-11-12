"""be05_04c_reload: 가짜 연결(원격 0, 임베딩 0). plan 무연결·무쓰기, 승인 파일 없으면 apply 거부, 블록 기대 불일치 시 롤백·중단,
새 id 삽입 → 옛 id 삭제 순서(한 트랜잭션), 백업 행 수 대조, 로그에 비밀·본문 없음, --reindex 없으면 REINDEX 미실행."""

from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import be05_04c_reload as m  # noqa: E402

BODY_MARK = "본문표식ZQX"
SECRET = "SeCrEtPaSsWoRd9876"
DSN = f"postgresql://postgres.abcd:{SECRET}@pooler.example.invalid:5432/postgres"
WRITE_PREFIX = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE", "REINDEX", "ANALYZE")

# 작은 합성 범위: 삽입 4(새 본문 2 + 본문 같음 2), 삭제 5(교체 3 + 제거 2), 유지 2, 허가 밖 2
E = m.Expect(total_before=9, l3p_before=7, insert=4, delete=5, vec_copy=2, vec_new=2, keep=2, para_after=3, table_after=3)


# --------------------------------------------------------------------------- 합성 입력

def chunk(cid: str, text: str, kind: str = m.KIND_PARA, parent: str | None = None, year: int | None = None) -> dict[str, Any]:
    c = {f: "" for f in m.FIELDS}
    c.update({"chunk_id": cid, "chunk_kind": kind, "parent_id": parent, "refs": [], "pair_id": None, "layer": "L3",
              "ingr_codes": [], "ingr_names": [], "text": f"{text} {BODY_MARK}", "year": year, "effective_date": None,
              "base_date": "2026-11-10"})
    return c


OLD = [chunk("l3p-o1", "T1", m.KIND_TABLE), chunk("l3p-o2", "T2"), chunk("l3p-o3", "T3", m.KIND_TABLE), chunk("l3p-o4", "T4"),
       chunk("l3p-o5", "T5"), chunk("l3p-o6", "T6"), chunk("l3p-o7", "T7", m.KIND_TABLE)]
NEW = [chunk("l3p-n1", "N1", m.KIND_TABLE, year=2026), chunk("l3p-n2", "T2", year=2026),
       chunk("l3p-n3", "N3", m.KIND_TABLE, parent="l3p-n1", year=2026), chunk("l3p-n5", "T5", year=2026),
       chunk("l3p-o6", "T6"), chunk("l3p-o7", "T7", m.KIND_TABLE)]
OUTSIDE = [chunk("l2c-a", "A"), chunk("l2c-b", "B")]
CHANGES = {"changes": {
    "replaced": [{"old_chunk_id": "l3p-o1", "new_chunk_id": "l3p-n1", "text_changed": True},
                 {"old_chunk_id": "l3p-o2", "new_chunk_id": "l3p-n2", "text_changed": False},
                 {"old_chunk_id": "l3p-o3", "new_chunk_id": "l3p-n3", "text_changed": True}],
    "removed": [{"old_chunk_id": "l3p-o4"}, {"old_chunk_id": "l3p-o5"}],
    "added": [{"new_chunk_id": "l3p-n5", "text_changed": False}], "unchanged": 2, "id_only": 2}}


def unit_vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(m.DIM).astype("<f4")
    return v / np.linalg.norm(v)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def write_index(emb: Path, texts: list[str]) -> dict[str, np.ndarray]:
    emb.mkdir(parents=True, exist_ok=True)
    hashes = sorted({m.text_hash(t) for t in texts})
    vecs = {h: unit_vec(i) for i, h in enumerate(hashes)}
    np.save(emb / "vectors.npy", np.stack([vecs[h] for h in hashes]))
    (emb / "index.json").write_text(json.dumps({"model": "x", "dim": m.DIM, "rows": {h: i for i, h in enumerate(hashes)}}))
    return vecs


@pytest.fixture
def env(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_jsonl(corpus / "l3_prmsn.jsonl", OLD)
    write_jsonl(corpus / "l3_prmsn.v2.jsonl", NEW)
    (corpus / "l3_prmsn.v2.changes.json").write_text(json.dumps(CHANGES), encoding="utf-8")
    write_jsonl(corpus / "l2_chunks.jsonl", OUTSIDE)
    write_jsonl(corpus / "l3_eyak.jsonl", [])
    write_jsonl(corpus / "l1_notice.jsonl", [])
    base_texts = [c["text"] for c in [*OLD, *OUTSIDE]]
    vecs = write_index(corpus / "embeddings", base_texts)
    review = tmp_path / "review"
    paths = {
        "OUT_DIR": corpus, "CUR_PATH": corpus / "l3_prmsn.jsonl", "V2_PATH": corpus / "l3_prmsn.v2.jsonl",
        "OLD_KEEP_PATH": corpus / "l3_prmsn.before_be0504.jsonl", "CHANGES_PATH": corpus / "l3_prmsn.v2.changes.json",
        "EMB_DIR": corpus / "embeddings", "EMB_KEEP_DIR": corpus / "embeddings.before_be0504", "WORK_DIR": review / "be0504",
        "MANIFEST_PATH": review / "be0504" / "manifest.json", "EMBED_TODO_PATH": review / "be0504" / "embed_todo.jsonl",
        "APPROVAL_FLAG": review / "be05_04c_approved.flag", "YEAR_APPROVAL_FLAG": review / "be05_04c_year_approved.flag", "BACKUP_DIR": tmp_path / "backup", "LOG_DIR": tmp_path / "logs",
    }
    for k, v in paths.items():
        monkeypatch.setattr(m, k, v)
    monkeypatch.setenv(m.DSN_ENV, DSN)
    monkeypatch.setattr(m, "render_default_prmsn", lambda: paths["V2_PATH"].read_bytes())  # 기본 build 결과(= v2) 흉내, 스냅샷 없이
    return {"tmp": tmp_path, "corpus": corpus, "vecs": vecs, **paths}


def embed_new_texts(env: dict[str, Any]) -> dict[str, np.ndarray]:
    """`embed_corpus run` 뒤 상태를 흉내 낸다(색인에 새 본문 N1·N3 추가). 실제 호출은 없다."""
    texts = [c["text"] for c in [*OLD, *OUTSIDE, *NEW]]
    return write_index(env["EMB_DIR"], texts)


# --------------------------------------------------------------------------- 가짜 Postgres(상태 시뮬레이션, 트랜잭션 롤백 지원)

class FakeDB:
    def __init__(self, vecs: dict[str, np.ndarray], extra_rows: int = 0) -> None:
        rows = {}
        for c in [*OLD, *OUTSIDE]:
            rows[c["chunk_id"]] = {"chunk_kind": c["chunk_kind"], "parent_id": c["parent_id"], "year": c["year"], "text": c["text"],
                                   "embedding": vecs[m.text_hash(c["text"])].tolist()}
        for i in range(extra_rows):
            rows[f"l2c-x{i}"] = {"chunk_kind": "l2_combo", "parent_id": None, "year": None, "text": "x", "embedding": [0.0]}
        self.committed: dict[str, Any] = {"rows": rows, "tables": {}, "stage": None}
        self.work = copy.deepcopy(self.committed)
        self.executed: list[str] = []
        self.fail_delete: set[str] = set()
        self.drop_backup_row = False
        self.after_commit: list[Any] = []
        self.closed = False

    # 연결 API
    def cursor(self) -> FakeCur:
        return FakeCur(self)

    def commit(self) -> None:
        self.committed = copy.deepcopy(self.work)
        self.executed.append("COMMIT")
        for hook in list(self.after_commit):
            hook(self)

    def rollback(self) -> None:
        self.work = copy.deepcopy(self.committed)
        self.executed.append("ROLLBACK")

    def close(self) -> None:
        self.closed = True

    @property
    def rows(self) -> dict[str, dict[str, Any]]:
        return self.work["rows"]


class FakeCur:
    def __init__(self, db: FakeDB) -> None:
        self.db, self._res, self.rowcount = db, [], -1

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res

    def executemany(self, sql, seq):
        assert sql == m.S2_INSERT, sql
        self.db.executed.append(sql)
        cols = [*m.PG_COLS, "src_chunk_id"]
        for t in seq:
            r = dict(zip(cols, t, strict=True))
            emb = r["embedding"]
            r["embedding"] = json.loads(emb) if emb else None
            self.db.work["stage"].append(r)

    def execute(self, sql, params=None):  # noqa: C901, PLR0912 - SQL 상수별 분기
        db, rows = self.db, self.db.rows
        db.executed.append(sql)
        p = params or ()
        l3p = [k for k in rows if k.startswith("l3p-")]
        if sql.startswith(("SET ", "RESET ")) or sql == m.S4_ANALYZE or sql == m.S5_REINDEX or sql == m.S2_ADDCOL:
            self._res = []
        elif sql == m.Q_TOTAL:
            self._res = [(len(rows),)]
        elif sql == m.Q_L3P:
            self._res = [(len(l3p),)]
        elif sql == m.Q_NOT_L3P:
            self._res = [(len(rows) - len(l3p),)]
        elif sql == m.Q_L3P_NULLVEC:
            self._res = [(sum(rows[k]["embedding"] is None for k in l3p),)]
        elif sql == m.Q_L3P_YEAR_NULL:
            self._res = [(sum(rows[k]["year"] is None for k in l3p),)]
        elif sql == m.Q_IDS_PRESENT:
            self._res = [(sum(i in rows for i in p[0]),)]
        elif sql == m.Q_IDS_WITH_VEC:
            self._res = [(sum(i in rows and rows[i]["embedding"] is not None for i in p[0]),)]
        elif sql == m.Q_IDS_NULLVEC:
            self._res = [(sum(i in rows and rows[i]["embedding"] is None for i in p[0]),)]
        elif sql in (m.Q_FK, m.Q_LONG_XACT):
            self._res = [(0,)]
        elif sql == m.Q_TABLE_EXISTS:
            self._res = [(p[0] in db.work["tables"],)]
        elif sql == m.Q_HNSW_BYTES:
            self._res = [(400 * 1048576,)]
        elif sql == m.Q_TUPLES:
            self._res = [(len(rows), 0)]
        elif sql == m.Q_SIZES:
            self._res = [(1048576, 2 * 1048576)]
        elif sql == m.Q_KINDS:
            kinds: dict[str, int] = {}
            for k in l3p:
                kinds[rows[k]["chunk_kind"]] = kinds.get(rows[k]["chunk_kind"], 0) + 1
            self._res = list(kinds.items())
        elif sql == m.Q_BROKEN_PARENT:
            self._res = [(sum(1 for k in l3p if rows[k]["parent_id"] and rows[k]["parent_id"] not in rows),)]
        elif sql == m.Q_BACKUP_ROWS:
            ids = sorted(i for i in p[0] if i in rows)
            if db.drop_backup_row:
                ids = ids[1:]
            self._res = [(i, json.dumps({"chunk_id": i, **rows[i]}, ensure_ascii=False)) for i in ids]
        elif sql == m.S1B_CREATE:
            db.work["tables"][m.BACKUP_TABLE] = {i: copy.deepcopy(rows[i]) for i in p[0] if i in rows}
        elif sql == m.Q_BACKUP_TABLE:
            t = db.work["tables"][m.BACKUP_TABLE]
            self._res = [(len(t), len(set(t)))]
        elif sql == m.S2_CREATE:
            db.work["stage"] = []
        elif sql == m.Q_STAGE:
            st = db.work["stage"]
            self._res = [(len(st), sum(r["embedding"] is not None for r in st), sum(r["src_chunk_id"] is not None for r in st),
                          sum(r["embedding"] is None and r["src_chunk_id"] is None for r in st),
                          sum(r["embedding"] is not None and r["src_chunk_id"] is not None for r in st))]
        elif sql == m.S3_INSERT:
            n = 0
            for r in db.work["stage"]:
                if r["chunk_id"] in rows:
                    continue
                src = rows.get(r["src_chunk_id"]) if r["src_chunk_id"] else None
                rows[r["chunk_id"]] = {"chunk_kind": r["chunk_kind"], "parent_id": r["parent_id"], "year": r["year"], "text": r["text"],
                                       "embedding": r["embedding"] if r["embedding"] is not None else (src or {}).get("embedding")}
                n += 1
            self.rowcount = n
        elif sql == m.S3_DELETE:
            n = 0
            for i in p[0]:
                if i in rows and i not in db.fail_delete:
                    del rows[i]
                    n += 1
            self.rowcount = n
        elif sql == m.S3B_UPDATE:
            n = 0
            for k in l3p:
                if rows[k]["year"] is None:
                    rows[k]["year"] = p[0]
                    n += 1
            self.rowcount = n
        else:
            raise AssertionError(f"모르는 SQL: {sql[:80]}")


def boom(_dsn: str) -> Any:
    raise AssertionError("원격에 연결하면 안 된다")


def run(env, argv, db=None, capsys=None):
    calls = []

    def connect(dsn):
        calls.append(dsn)
        return db

    code = m.main(argv, connect_fn=connect if db is not None else boom, exp=E)
    return code, calls


def prepared(env, approve=True):
    assert m.main(["prepare"], connect_fn=boom, exp=E) == 0
    vecs = embed_new_texts(env)
    if approve:
        env["APPROVAL_FLAG"].parent.mkdir(parents=True, exist_ok=True)
        env["APPROVAL_FLAG"].write_text("ok")
        env["YEAR_APPROVAL_FLAG"].write_text("ok")  # 승인 A8(S3b)
    return vecs


def writes(db: FakeDB) -> list[str]:
    return [s for s in db.executed if s.lstrip().upper().startswith(WRITE_PREFIX)]


# --------------------------------------------------------------------------- 범위 계산

def test_scope_counts_match_changes(env):
    scope, _, _ = m.compute_scope()
    assert m.check_scope(scope, E)["insert"] == 4
    assert (scope.vec_copy, scope.vec_rows, len(scope.vec_new_hashes), scope.keep) == (2, 2, 2, 2)
    assert {r["chunk_id"]: r["src_chunk_id"] for r in scope.insert} == {
        "l3p-n1": None, "l3p-n2": "l3p-o2", "l3p-n3": None, "l3p-n5": "l3p-o5"}
    assert set(scope.src_ids) <= set(scope.delete)  # 복사 원본은 같은 트랜잭션에서 지워질 옛 행


def test_scope_mismatch_with_expect_aborts(env):
    scope, _, _ = m.compute_scope()
    with pytest.raises(m.ReloadAbort, match="기대값과 다름"):
        m.check_scope(scope, m.Expect(total_before=9, l3p_before=7, insert=5, delete=5, vec_copy=2, vec_new=2, keep=2,
                                      para_after=3, table_after=3))


def test_scope_rejects_inconsistent_changes(env):
    bad = copy.deepcopy(CHANGES)
    bad["changes"]["removed"].append({"old_chunk_id": "l3p-o6"})  # v2에 남아 있는 행을 지우려 함
    with pytest.raises(m.ReloadAbort, match="v2에 남아 있는 삭제 id"):
        m.build_scope(OLD, NEW, bad, {})


def test_default_expect_matches_plan_numbers():
    d = m.DEFAULT_EXPECT
    assert (d.total_after, d.l3p_after, d.outside) == (68_687, 9_553, 59_134)
    assert d.vec_copy + d.vec_new == d.insert and d.keep + d.delete == d.l3p_before


# --------------------------------------------------------------------------- plan / prepare(원격 0)

def test_plan_does_not_connect_or_write(env, capsys):
    code, calls = run(env, ["plan"])
    assert code == 0 and calls == []
    out = capsys.readouterr().out
    assert m.S3_INSERT in out and m.S3_DELETE in out and m.S5_REINDEX in out
    assert not env["WORK_DIR"].exists() and not env["LOG_DIR"].exists() and not env["BACKUP_DIR"].exists()
    assert BODY_MARK not in out


def test_plan_blocks_show_expected_rows(env):
    scope, _, _ = m.compute_scope()
    blocks = {b["block"]: b for b in m.plan_blocks(scope, E)}
    assert blocks["S3"]["rows"]["post_total"] == 8 and blocks["S3"]["rows"]["delete_batches"] == [5]
    assert "실행 안 함" in blocks["S5"]["remote"]
    assert "S3b" in blocks  # BE-05-11 B 기본
    assert blocks["S3b"]["rows"]["updated"] == E.keep == blocks["S3b"]["rows"]["pre_year_null(유지 행)"]
    assert "S3b" not in {b["block"] for b in m.plan_blocks(scope, E, align_year=False)}
    names = [b["block"] for b in m.plan_blocks(scope, E, reindex=True)]
    assert names.index("S3b") < names.index("S5")  # year UPDATE는 반드시 REINDEX 앞


def test_prepare_writes_manifest_without_text(env):
    assert m.main(["prepare"], connect_fn=boom, exp=E) == 0
    man = json.loads(env["MANIFEST_PATH"].read_text(encoding="utf-8"))
    assert len(man["insert"]) == 4 and len(man["delete"]) == 5 and len(man["embed_todo"]) == 2
    todo = env["EMBED_TODO_PATH"].read_text(encoding="utf-8")
    assert len(todo.splitlines()) == 2 and BODY_MARK not in todo and BODY_MARK not in json.dumps(man, ensure_ascii=False)


def test_prepare_refuses_over_budget(env):
    assert m.main(["prepare", "--max-usd", "0"], connect_fn=boom, exp=E) == 3
    assert not env["MANIFEST_PATH"].exists()


def test_prepare_switch_input_keeps_old_and_is_idempotent(env):
    old_bytes = env["CUR_PATH"].read_bytes()
    assert m.main(["prepare", "--switch-input"], connect_fn=boom, exp=E) == 0
    assert env["OLD_KEEP_PATH"].read_bytes() == old_bytes
    assert env["CUR_PATH"].read_bytes() == env["V2_PATH"].read_bytes()
    assert (env["EMB_KEEP_DIR"] / "vectors.npy").exists() and (env["EMB_KEEP_DIR"] / "index.json").exists()
    assert m.main(["prepare", "--switch-input"], connect_fn=boom, exp=E) == 0  # 두 번째는 건너뜀
    scope, old_p, _ = m.compute_scope()
    assert old_p == env["OLD_KEEP_PATH"] and len(scope.delete) == 5


# --------------------------------------------------------------------------- 실행 조건(승인 파일·--yes·manifest·벡터)

def test_apply_refused_without_flag(env, capsys):
    prepared(env, approve=False)
    code, calls = run(env, ["apply", "--yes"])
    assert code == 2 and calls == []
    assert m.APPROVAL_FLAG.name in capsys.readouterr().err


def test_apply_refused_without_yes(env, capsys):
    prepared(env)
    code, calls = run(env, ["apply"])
    assert code == 2 and calls == [] and "--yes" in capsys.readouterr().err


def test_apply_refused_when_new_vectors_missing(env, capsys):
    assert m.main(["prepare"], connect_fn=boom, exp=E) == 0
    env["APPROVAL_FLAG"].parent.mkdir(parents=True, exist_ok=True)
    env["APPROVAL_FLAG"].write_text("ok")
    env["YEAR_APPROVAL_FLAG"].write_text("ok")
    code, calls = run(env, ["apply", "--yes"])
    assert code == 2 and calls == [] and "embed_corpus" in capsys.readouterr().err


def test_apply_refused_when_manifest_tampered(env, capsys):
    prepared(env)
    man = json.loads(env["MANIFEST_PATH"].read_text(encoding="utf-8"))
    man["delete"].append("l3p-o6")
    env["MANIFEST_PATH"].write_text(json.dumps(man), encoding="utf-8")
    code, calls = run(env, ["apply", "--yes"])
    assert code == 2 and calls == [] and "sha256" in capsys.readouterr().err


def test_from_s5_requires_reindex(env):
    prepared(env)
    code, calls = run(env, ["apply", "--yes", "--from", "S5"])
    assert code == 2 and calls == []


# --------------------------------------------------------------------------- apply(가짜 원격)

def test_apply_success_replaces_rows_and_skips_reindex(env, capsys):
    vecs = prepared(env)
    db = FakeDB(vecs)
    code, calls = run(env, ["apply", "--yes"], db)
    assert code == 0 and calls == [DSN] and db.closed
    rows = db.committed["rows"]
    assert len(rows) == E.total_after and sum(k.startswith("l3p-") for k in rows) == E.l3p_after
    assert not any(k in rows for k in ("l3p-o1", "l3p-o2", "l3p-o3", "l3p-o4", "l3p-o5"))
    # 본문 같은 행은 서버 안에서 옛 벡터를 복사, 새 본문은 로컬 벡터
    assert rows["l3p-n2"]["embedding"] == pytest.approx(vecs[m.text_hash(OLD[1]["text"])].tolist())
    assert rows["l3p-n1"]["embedding"] == pytest.approx(vecs[m.text_hash(NEW[0]["text"])].tolist(), abs=1e-6)
    assert rows["l2c-a"] == FakeDB(vecs).committed["rows"]["l2c-a"]  # 허가 밖 행 그대로
    assert m.S5_REINDEX not in db.executed  # --reindex 없으면 REINDEX 없음
    assert not any(s.startswith("SET maintenance_work_mem") for s in db.executed)
    assert len(db.committed["tables"][m.BACKUP_TABLE]) == E.delete
    out = capsys.readouterr().out
    assert m.DSN_ENV in out and "일일 백업" in out and SECRET not in out


def test_insert_before_delete_in_one_transaction(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes"], db)[0] == 0
    ex = db.executed
    i_ins = ex.index(m.S3_INSERT)
    i_dels = [i for i, s in enumerate(ex) if s == m.S3_DELETE]
    assert i_dels and i_ins < min(i_dels)
    first_commit_after = next(i for i in range(i_ins, len(ex)) if ex[i] in ("COMMIT", "ROLLBACK"))
    assert ex[first_commit_after] == "COMMIT" and first_commit_after > max(i_dels)  # 삽입~삭제 사이 커밋 없음
    assert not any(s in ("COMMIT", "ROLLBACK") for s in ex[i_ins:max(i_dels)])


def test_s0_aborts_when_remote_count_differs(env, capsys):
    db = FakeDB(prepared(env), extra_rows=1)  # 다른 pane이 원격에 한 행을 더 썼다고 가정
    code, _ = run(env, ["apply", "--yes"], db)
    assert code == 3 and "S0" in capsys.readouterr().err
    assert writes(db) == [] and not env["BACKUP_DIR"].exists()


def test_s3_rolls_back_and_stops_on_delete_mismatch(env, capsys):
    vecs = prepared(env)
    db = FakeDB(vecs)
    db.fail_delete = {"l3p-o4"}
    code, _ = run(env, ["apply", "--yes"], db)
    assert code == 3 and "삭제 묶음" in capsys.readouterr().err
    rows = db.committed["rows"]
    assert all(i in rows for i in ("l3p-o1", "l3p-o2", "l3p-o3", "l3p-o4", "l3p-o5"))  # 삭제 롤백
    assert not any(i in rows for i in ("l3p-n1", "l3p-n2", "l3p-n3", "l3p-n5"))  # 삽입도 롤백
    assert len(rows) == E.total_before
    assert m.S4_ANALYZE not in db.executed and m.S5_REINDEX not in db.executed  # 다음 블록으로 가지 않음


def test_s3_precount_mismatch_rolls_back_before_insert(env):
    db = FakeDB(prepared(env))

    def tamper(d: FakeDB) -> None:  # S2 커밋 직후 다른 세션이 행을 더함
        if d.committed["stage"] is not None and "l2c-late" not in d.committed["rows"]:
            d.committed["rows"]["l2c-late"] = {"chunk_kind": "l2_combo", "parent_id": None, "year": None, "text": "x", "embedding": [0.0]}
            d.work = copy.deepcopy(d.committed)

    db.after_commit.append(tamper)
    code, _ = run(env, ["apply", "--yes"], db)
    assert code == 3
    i_s3 = max(i for i, s in enumerate(db.executed) if s == m.SET_STMT_S3)
    assert m.S3_INSERT not in db.executed[i_s3:] and "ROLLBACK" in db.executed[i_s3:]
    assert "l3p-n1" not in db.committed["rows"]


def test_backup_line_count_mismatch_aborts_before_any_write(env, capsys):
    db = FakeDB(prepared(env))
    db.drop_backup_row = True
    code, _ = run(env, ["apply", "--yes"], db)
    assert code == 3 and "로컬 백업 줄 수" in capsys.readouterr().err
    assert writes(db) == [] and not list(env["BACKUP_DIR"].glob("*.gz"))


def test_backup_file_and_table_match_delete_list(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes", "--until", "S1"], db)[0] == 0
    files = list(env["BACKUP_DIR"].glob("be0504_before_reload_*.jsonl.gz"))
    assert len(files) == 1
    with gzip.open(files[0], "rt", encoding="utf-8") as f:
        ids = [json.loads(ln)["chunk_id"] for ln in f]
    assert sorted(ids) == sorted(json.loads(env["MANIFEST_PATH"].read_text())["delete"])
    assert set(db.committed["tables"][m.BACKUP_TABLE]) == set(ids)
    assert m.S2_CREATE not in db.executed  # --until S1에서 멈춤


def test_backup_table_count_must_equal_local_lines(env):
    db = FakeDB(prepared(env))
    man = m.load_manifest(E)
    with pytest.raises(m.ReloadAbort, match="로컬 백업 줄 수"):
        m.s1b_backup_table(db.cursor(), man, local_lines=E.delete - 1)


def test_backup_local_only_option_skips_remote_table(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes", "--backup", "local"], db)[0] == 0
    assert m.S1B_CREATE not in db.executed and m.BACKUP_TABLE not in db.committed["tables"]
    assert len(db.committed["rows"]) == E.total_after


def test_log_has_no_secret_or_body(env, capsys):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes"], db)[0] == 0
    logs = list(env["LOG_DIR"].glob("be0504_reload_*.jsonl"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    recs = [json.loads(ln) for ln in text.splitlines()]
    assert {r["event"] for r in recs} >= {"start", "read", "commit", "skip", "done"}
    assert SECRET not in text and DSN not in text and BODY_MARK not in text
    assert all("text" not in json.dumps(r.get("result", {})) for r in recs)
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err and BODY_MARK not in out.out + out.err


def test_log_drops_body_keys_and_redacts(tmp_path, monkeypatch):
    monkeypatch.setenv(m.DSN_ENV, DSN)
    lines: list[str] = []
    log = m.JsonlLog(tmp_path / "l.jsonl", echo=lines.append)
    log.event("x", text=BODY_MARK, result={"embedding": [1.0], "ok": 1}, detail=f"오류 {DSN}")
    raw = (tmp_path / "l.jsonl").read_text(encoding="utf-8")
    assert BODY_MARK not in raw and "embedding" not in raw and SECRET not in raw and '"ok": 1' in raw


def test_reindex_runs_only_with_flag_and_session_settings(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes", "--reindex"], db)[0] == 0
    ex = db.executed
    i = ex.index(m.S5_REINDEX)
    assert ex.index("SET maintenance_work_mem = '128MB'") < i and ex.index("SET max_parallel_maintenance_workers = 0") < i
    assert ex.index("RESET maintenance_work_mem") > i
    assert ex.index(m.S4_ANALYZE) < i  # S4 뒤에만
    assert not any(s.startswith("SET maintenance_work_mem") for s in ex[: ex.index(m.S3_INSERT) + 1])  # 삽입·삭제는 기본 설정


def test_from_s5_reindex_only_checks_post_state(env):
    vecs = prepared(env)
    db = FakeDB(vecs)
    assert run(env, ["apply", "--yes"], db)[0] == 0
    db.executed.clear()
    assert run(env, ["apply", "--yes", "--from", "S5", "--reindex"], db)[0] == 0
    assert m.S5_REINDEX in db.executed and m.S3_INSERT not in db.executed and m.S1B_CREATE not in db.executed
    fresh = FakeDB(vecs)  # 재적재 전 상태면 S4 재확인에서 멈춘다
    assert run(env, ["apply", "--yes", "--from", "S5", "--reindex"], fresh)[0] == 3
    assert m.S5_REINDEX not in fresh.executed


def test_year_is_aligned_by_default_before_measure(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes"], db)[0] == 0
    rows = db.committed["rows"]
    assert all(rows[k]["year"] == m.V2_YEAR for k in rows if k.startswith("l3p-"))
    assert db.executed.index(m.S3B_UPDATE) < db.executed.index(m.S4_ANALYZE)


def test_keep_year_mixed_option_leaves_year_mixed(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes", "--keep-year-mixed"], db)[0] == 0
    rows = db.committed["rows"]
    assert rows["l3p-o6"]["year"] is None and rows["l3p-n1"]["year"] == 2026 and m.S3B_UPDATE not in db.executed


def test_until_s0_is_read_only(env):
    db = FakeDB(prepared(env))
    assert run(env, ["apply", "--yes", "--until", "S0"], db)[0] == 0
    assert writes(db) == [] and m.SET_READ_ONLY in db.executed and "COMMIT" not in db.executed


def test_keyboard_interrupt_in_s3_rolls_back(env):
    db = FakeDB(prepared(env))
    orig = FakeCur.execute

    def stop_on_delete(self, sql, params=None):
        if sql == m.S3_DELETE:
            raise KeyboardInterrupt
        return orig(self, sql, params)

    FakeCur.execute = stop_on_delete  # type: ignore[method-assign]
    try:
        with pytest.raises(KeyboardInterrupt):
            run(env, ["apply", "--yes"], db)
    finally:
        FakeCur.execute = orig  # type: ignore[method-assign]
    assert "l3p-n1" not in db.committed["rows"] and len(db.committed["rows"]) == E.total_before and db.closed
    log = next(env["LOG_DIR"].glob("*.jsonl")).read_text(encoding="utf-8")
    assert '"KeyboardInterrupt"' in log


# --------------------------------------------------------------------------- BE-05-09 B·BE-05-11 B

def test_plan_output_has_year_block_and_b_options(env, capsys):
    code, calls = run(env, ["plan"])
    out = capsys.readouterr().out
    assert code == 0 and calls == []
    assert m.S3B_UPDATE in out and "BE-05-11" in out and "B(유지 행 year UPDATE" in out and "+40~50" in out and "A8" in out
    assert "BE-05-09" in out
    code, _ = run(env, ["plan", "--keep-year-mixed"])
    assert code == 0 and m.S3B_UPDATE not in capsys.readouterr().out


def test_default_expect_year_rows_equal_keep():
    assert m.DEFAULT_EXPECT.keep == 7_466


def test_apply_refused_without_year_flag_unless_keep_year_mixed(env, capsys):
    db = FakeDB(prepared(env))
    env["YEAR_APPROVAL_FLAG"].unlink()
    code, calls = run(env, ["apply", "--yes"], db)
    assert code == 2 and calls == [] and "A8" in capsys.readouterr().err
    assert run(env, ["apply", "--yes", "--keep-year-mixed"], db)[0] == 0


def test_year_update_count_mismatch_rolls_back_and_stops(env):
    db = FakeDB(prepared(env))
    db.committed["rows"]["l3p-o6"]["year"] = 2025  # 유지 행 하나가 이미 year가 있어 기대 2행 ≠ 실제 1행
    db.work = copy.deepcopy(db.committed)
    code, _ = run(env, ["apply", "--yes"], db)
    assert code == 3
    assert m.S4_ANALYZE not in db.executed and m.S5_REINDEX not in db.executed
    assert db.committed["rows"]["l3p-o7"]["year"] is None  # S3b 롤백(S3 교체는 이미 커밋)
    assert "l3p-n1" in db.committed["rows"] and "l3p-o1" not in db.committed["rows"]


def test_from_s5_stops_when_year_not_aligned(env):
    vecs = prepared(env)
    db = FakeDB(vecs)
    assert run(env, ["apply", "--yes", "--keep-year-mixed"], db)[0] == 0  # year 혼재 상태로 재적재
    assert run(env, ["apply", "--yes", "--from", "S5", "--reindex"], db)[0] == 3  # year 미정렬이면 REINDEX 거부
    assert m.S5_REINDEX not in db.executed
    assert run(env, ["apply", "--yes", "--from", "S5", "--reindex", "--keep-year-mixed"], db)[0] == 0


def test_switch_input_refuses_when_default_build_differs_from_v2(env, monkeypatch):
    monkeypatch.setattr(m, "render_default_prmsn", lambda: b"x\n")
    before = env["CUR_PATH"].read_bytes()
    assert m.main(["prepare", "--switch-input"], connect_fn=boom, exp=E) == 3
    assert env["CUR_PATH"].read_bytes() == before and not env["OLD_KEEP_PATH"].exists() and not env["EMB_KEEP_DIR"].exists()


def test_plan_and_prepare_without_switch_do_not_touch_local_input(env):
    before = env["CUR_PATH"].read_bytes()
    assert m.main(["plan"], connect_fn=boom, exp=E) == 0 and m.main(["prepare"], connect_fn=boom, exp=E) == 0
    assert env["CUR_PATH"].read_bytes() == before and not env["OLD_KEEP_PATH"].exists()
