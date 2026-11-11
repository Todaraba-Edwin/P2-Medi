"""BE-05-04 C 허가 상세(`l3p-`) 원격 재적재 실행 도구(계획서 `data/mock/review/be05_04c_reload_plan.md`, SQL 초안 `be05_04c_reload.sql`).

  plan                 (기본) 원격 연결 0. 로컬 입력(v2 청크·변경 목록·임베딩 색인)만으로 블록별 예상 행 수·SQL·비용·소요를 출력한다.
  prepare              원격 연결 0, 임베딩 호출 0. L1~L4 로컬 준비: v2 입력 점검, 새 본문만 임베딩 대상으로 추림(`embed_corpus.py run`
                       증분 경로가 그대로 집어 갈 목록과 비용 어림, `--max-usd` 초과면 거부), 삽입·삭제·벡터 복사 목록을 manifest로 고정(sha256).
                       `--switch-input`을 주면 BE-05-09 A(v2를 `l3_prmsn.jsonl` 이름으로, 옛 파일·임베딩은 `*.before_be0504`로 보관)를 실행한다.
  apply --yes          원격 쓰기. `--yes` + 승인 파일 `data/mock/review/be05_04c_approved.flag`(사용자 승인 뒤 메인이 만든다)가 둘 다 있어야 한다.
                       S0 읽기 점검(전체 68,818이 아니면 중단) → S1 백업(로컬 jsonl.gz + 원격 백업 표, BE-05-10) → S2 세션 TEMP 적재 →
                       S3 한 트랜잭션(새 id 삽입 → 옛 id 삭제 → 사후 검사 → 커밋) → [S3b year 맞춤, `--align-year`] → S4 측정·ANALYZE →
                       [S5 REINDEX, `--reindex`를 따로 줄 때만]. 블록마다 사전·사후 COUNT를 기대값과 비교하고 다르면 그 블록을 롤백하고 멈춘다.

기본값은 결정 BE-05-09~11의 권장 A(입력 전환 A, 백업 둘 다 A, year 혼재 그대로 A)다. 다른 답이면 `--old/--new`, `--backup local`, `--align-year`로 바꾼다.
접속 문자열은 환경변수 SUPABASE_DB_URL(없으면 앱 Settings)에서 프로세스 안에서만 읽고 출력하지 않는다. 줄 단위 로그(`logs/be0504_reload_{UTC}.jsonl`)에는
행 수·chunk_id·소요만 남기고 본문·벡터·접속 문자열은 남기지 않는다(문자열은 redact를 거친다).
금지(이 도구는 하지 않는다): DROP INDEX·DROP TABLE(본 표·백업 표)·TRUNCATE·`l3p-` 밖 행 변경·임베딩/LLM/공공 API 호출.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from build_corpus_l2 import OUT_DIR, read_chunks  # noqa: E402
from load_corpus import ALL_FILES, FIELDS, PG_COLS, pg_row, resolve_dsn, vec_literal  # noqa: E402

from app.security.redact import install_excepthook, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"

# --------------------------------------------------------------------------- 경로(시험에서 바꿔 끼운다)
CUR_PATH = OUT_DIR / "l3_prmsn.jsonl"  # 앱·embed_corpus·load_corpus가 읽는 이름
V2_PATH = OUT_DIR / "l3_prmsn.v2.jsonl"
OLD_KEEP_PATH = OUT_DIR / "l3_prmsn.before_be0504.jsonl"  # BE-05-09 A 보관 이름
CHANGES_PATH = OUT_DIR / "l3_prmsn.v2.changes.json"
EMB_DIR = OUT_DIR / "embeddings"
EMB_KEEP_DIR = OUT_DIR / "embeddings.before_be0504"
WORK_DIR = REPO / "data" / "mock" / "review" / "be0504"
MANIFEST_PATH = WORK_DIR / "manifest.json"
EMBED_TODO_PATH = WORK_DIR / "embed_todo.jsonl"
APPROVAL_FLAG = REPO / "data" / "mock" / "review" / "be05_04c_approved.flag"
BACKUP_DIR = REPO / "data" / "mock" / "backup"
LOG_DIR = REPO / "logs"

L3P = "l3p-%"
KIND_PARA, KIND_TABLE = "l3_prmsn_para", "l3_prmsn_table"
BACKUP_TABLE = "corpus_chunks_bak_be0504"
STAGE_TABLE = "stage_be0504"
HNSW_INDEX = "idx_corpus_embedding_hnsw"
DELETE_BATCH = 500
STAGE_BATCH = 200
DIM = 1536
EMBED_PRICE_PER_M = 0.02
DEFAULT_MAX_USD = 0.05
LONG_XACT_MIN = 5
V2_YEAR = 2026
BLOCKS = ("S0", "S1", "S2", "S3", "S4")


class ReloadAbort(RuntimeError):
    """기대와 다름·입력 이상 → 그 블록 롤백, 이후 블록 실행하지 않음."""


class Refused(RuntimeError):
    """실행 조건(승인 파일·--yes·manifest·벡터) 미충족 → 원격 연결 전에 거부."""


@dataclass(frozen=True)
class Expect:
    """기대값. 원격 사전값(68,818·9,684)은 BE-16 백업 기준이고, 나머지는 로컬 변경 목록에서 다시 센 값과 같아야 한다."""

    total_before: int = 68_818
    l3p_before: int = 9_684
    insert: int = 2_087
    delete: int = 2_218
    vec_copy: int = 887
    vec_new: int = 1_200
    keep: int = 7_466
    para_after: int = 8_108
    table_after: int = 1_445

    @property
    def total_after(self) -> int:
        return self.total_before - self.delete + self.insert

    @property
    def l3p_after(self) -> int:
        return self.l3p_before - self.delete + self.insert

    @property
    def outside(self) -> int:
        return self.total_before - self.l3p_before

    def as_dict(self) -> dict[str, int]:
        return {**asdict(self), "total_after": self.total_after, "l3p_after": self.l3p_after, "outside": self.outside}


DEFAULT_EXPECT = Expect()


def expect_eq(what: str, got: Any, want: Any) -> None:
    if got != want:
        raise ReloadAbort(f"{what}: 기대 {want}, 실제 {got}")


# --------------------------------------------------------------------------- SQL(계획 출력과 실행이 같은 문자열을 쓴다)
Q_TOTAL = "SELECT COUNT(*) FROM corpus_chunks"
Q_L3P = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id LIKE %s"
Q_NOT_L3P = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id NOT LIKE %s"
Q_L3P_NULLVEC = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id LIKE %s AND embedding IS NULL"
Q_L3P_YEAR_NULL = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id LIKE %s AND year IS NULL"
Q_IDS_PRESENT = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id = ANY(%s)"
Q_IDS_WITH_VEC = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id = ANY(%s) AND embedding IS NOT NULL"
Q_IDS_NULLVEC = "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_id = ANY(%s) AND embedding IS NULL"
Q_FK = "SELECT COUNT(*) FROM pg_constraint WHERE contype = 'f' AND confrelid = to_regclass('public.corpus_chunks')"
Q_LONG_XACT = (
    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() "
    "AND xact_start IS NOT NULL AND now() - xact_start > make_interval(mins => %s)")
Q_TABLE_EXISTS = "SELECT to_regclass(%s) IS NOT NULL"
Q_HNSW_BYTES = "SELECT COALESCE(pg_relation_size(to_regclass(%s)), 0)"
Q_TUPLES = "SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 'corpus_chunks'"
Q_SIZES = "SELECT pg_total_relation_size('corpus_chunks'), pg_database_size(current_database())"
Q_KINDS = "SELECT chunk_kind, COUNT(*) FROM corpus_chunks WHERE chunk_id LIKE %s GROUP BY 1"
Q_BROKEN_PARENT = (
    "SELECT COUNT(*) FROM corpus_chunks c WHERE c.chunk_id LIKE %s AND c.parent_id IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM corpus_chunks p WHERE p.chunk_id = c.parent_id)")
Q_BACKUP_ROWS = "SELECT chunk_id, row_to_json(c)::text FROM corpus_chunks c WHERE chunk_id = ANY(%s) ORDER BY chunk_id"
SET_READ_ONLY = "SET TRANSACTION READ ONLY"
SET_LOCK = "SET LOCAL lock_timeout = '10s'"
SET_STMT_S1 = "SET LOCAL statement_timeout = '120s'"
SET_STMT_S3 = "SET LOCAL statement_timeout = '300s'"
S1B_CREATE = f"CREATE TABLE {BACKUP_TABLE} AS SELECT * FROM corpus_chunks WHERE chunk_id = ANY(%s)"  # noqa: S608 - 상수
Q_BACKUP_TABLE = f"SELECT COUNT(*), COUNT(DISTINCT chunk_id) FROM {BACKUP_TABLE}"  # noqa: S608 - 상수
S2_CREATE = f"CREATE TEMP TABLE {STAGE_TABLE} (LIKE corpus_chunks INCLUDING DEFAULTS) ON COMMIT PRESERVE ROWS"
S2_ADDCOL = f"ALTER TABLE {STAGE_TABLE} ADD COLUMN src_chunk_id TEXT"
_STAGE_PH = ", ".join("%s::jsonb" if f == "refs" else ("%s::vector" if f == "embedding" else "%s") for f in PG_COLS)
S2_INSERT = f"INSERT INTO {STAGE_TABLE} ({', '.join(PG_COLS)}, src_chunk_id) VALUES ({_STAGE_PH}, %s)"  # noqa: S608 - 상수
Q_STAGE = (
    "SELECT COUNT(*), COUNT(*) FILTER (WHERE embedding IS NOT NULL), COUNT(*) FILTER (WHERE src_chunk_id IS NOT NULL), "
    "COUNT(*) FILTER (WHERE embedding IS NULL AND src_chunk_id IS NULL), "
    "COUNT(*) FILTER (WHERE embedding IS NOT NULL AND src_chunk_id IS NOT NULL) FROM stage_be0504")
S3_INSERT = (
    f"INSERT INTO corpus_chunks ({', '.join(PG_COLS)}) "  # noqa: S608 - 상수
    f"SELECT {', '.join('s.' + f for f in FIELDS)}, COALESCE(s.embedding, o.embedding) "
    f"FROM {STAGE_TABLE} s LEFT JOIN corpus_chunks o ON o.chunk_id = s.src_chunk_id "
    "ON CONFLICT (chunk_id) DO NOTHING")
S3_DELETE = "DELETE FROM corpus_chunks WHERE chunk_id = ANY(%s)"
S3B_UPDATE = "UPDATE corpus_chunks SET year = %s WHERE chunk_id LIKE %s AND year IS NULL"
S4_ANALYZE = "ANALYZE corpus_chunks"
S5_SETS = ("SET maintenance_work_mem = '128MB'", "SET max_parallel_maintenance_workers = 0",
           "SET statement_timeout = '1200s'", "SET lock_timeout = '10s'")
S5_REINDEX = f"REINDEX INDEX {HNSW_INDEX}"
S5_RESETS = ("RESET maintenance_work_mem", "RESET max_parallel_maintenance_workers", "RESET statement_timeout", "RESET lock_timeout")

# 계획서 §7 예상 소요(추정, 이전 측정 비례)
EST_TIME = {"S0": "2~3분", "S1": "1~3분", "S2": "1~2분", "S3": "10~60초", "S3b": "수 분(7,466행 비HOT 갱신, 추정)",
            "S4": "1분 미만", "S5": "약 6~7분(첫 빌드 367초 기준, 벡터 검색 중단)"}
DAILY_BACKUP_NOTICE = ("[확인] Supabase 대시보드 Database → Backups에서 최근 일일 백업 시각을 확인했는가(계획서 §2 P2). "
                       "대시보드 메모리 70% 미만·데모/평가 측정이 없는 시간인지도 확인한다(P4). 85% 이상이면 Ctrl+C(커밋 전이면 원격 변화 0).")


# --------------------------------------------------------------------------- 공통 유틸

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 - embed_corpus와 같은 중복 제거 키(보안 용도 아님)


def body_sha(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


_FORBIDDEN_LOG_KEYS = frozenset({"text", "embedding", "vector", "dsn", "row"})


def _clean(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if k not in _FORBIDDEN_LOG_KEYS}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


class JsonlLog:
    """줄 단위 jsonl 로그. 본문·벡터 키는 버리고 문자열은 redact한다. 한 줄 쓸 때마다 flush(중간 중단에도 남는다)."""

    def __init__(self, path: Path | None, echo: Callable[[str], None] = print) -> None:
        self.path, self.echo = path, echo
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, name: str, **fields: Any) -> None:
        rec = _clean({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "event": name, **fields})
        line = json.dumps(rec, ensure_ascii=False, default=str)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        self.echo(line)


# --------------------------------------------------------------------------- 로컬 범위(plan·prepare 공통, 원격 0)

@dataclass
class Scope:
    insert: list[dict[str, Any]]  # {chunk_id, text_hash, src_chunk_id|None}
    delete: list[str]
    keep: int
    new_rows: int
    kinds_after: dict[str, int]
    broken_parent: int
    vec_new_hashes: list[str]  # 로컬 색인에 없는 새 본문(임베딩 대상)
    vec_new_chars: int
    vec_new_tokens_est: float
    year_new: dict[str, int] = field(default_factory=dict)

    @property
    def vec_copy(self) -> int:
        return sum(1 for r in self.insert if r["src_chunk_id"])

    @property
    def vec_rows(self) -> int:
        return sum(1 for r in self.insert if not r["src_chunk_id"])

    @property
    def src_ids(self) -> list[str]:
        return sorted({r["src_chunk_id"] for r in self.insert if r["src_chunk_id"]})

    @property
    def insert_ids(self) -> list[str]:
        return [r["chunk_id"] for r in self.insert]


def resolve_inputs(old: Path | None = None, new: Path | None = None) -> tuple[Path, Path]:
    """(옛 파일, v2 파일). 입력 전환(BE-05-09 A) 뒤에는 옛 파일이 `*.before_be0504`다. 옛·새 파일 내용이 같으면 거부."""
    new_p = new or V2_PATH
    if old is None:
        old = OLD_KEEP_PATH if OLD_KEEP_PATH.exists() else CUR_PATH
    for p in (old, new_p, CHANGES_PATH):
        if not p.exists():
            raise ReloadAbort(f"입력 없음: {p.name}")
    if sha256_file(old) == sha256_file(new_p):
        raise ReloadAbort(f"옛 입력({old.name})과 v2 입력({new_p.name})이 같다. 입력 전환 뒤라면 {OLD_KEEP_PATH.name}이 있어야 한다")
    return old, new_p


def load_index_rows(emb_dir: Path | None = None) -> dict[str, int]:
    p = (emb_dir or EMB_DIR) / "index.json"
    if not p.exists():
        raise ReloadAbort("로컬 임베딩 색인(index.json)이 없다(embed_corpus 마무리 상태가 아님)")
    return json.loads(p.read_text(encoding="utf-8"))["rows"]


def build_scope(old_chunks: Sequence[dict[str, Any]], new_chunks: Sequence[dict[str, Any]], changes: dict[str, Any],
                index_rows: dict[str, int]) -> Scope:
    from embed_compare import estimate_tokens  # noqa: PLC0415 - 토큰 근사(호출 없음)

    old = {c["chunk_id"]: c for c in old_chunks}
    new = {c["chunk_id"]: c for c in new_chunks}
    ch = changes["changes"]
    ins_ids = [r["new_chunk_id"] for r in ch["replaced"]] + [r["new_chunk_id"] for r in ch["added"]]
    del_ids = [r["old_chunk_id"] for r in ch["replaced"]] + [r["old_chunk_id"] for r in ch["removed"]]
    problems = []
    if len(set(ins_ids)) != len(ins_ids) or len(set(del_ids)) != len(del_ids):
        problems.append("변경 목록에 중복 id")
    if any(i not in new for i in ins_ids):
        problems.append(f"v2에 없는 삽입 id {sum(i not in new for i in ins_ids)}")
    if any(i in old for i in ins_ids):
        problems.append(f"옛 파일에 이미 있는 삽입 id {sum(i in old for i in ins_ids)}")
    if any(i not in old for i in del_ids):
        problems.append(f"옛 파일에 없는 삭제 id {sum(i not in old for i in del_ids)}")
    if any(i in new for i in del_ids):
        problems.append(f"v2에 남아 있는 삭제 id {sum(i in new for i in del_ids)}")
    keep = set(old) - set(del_ids)
    if keep != set(new) - set(ins_ids):
        problems.append("유지 집합 불일치(옛 − 삭제 ≠ v2 − 삽입)")
    if any(not str(i).startswith("l3p-") for i in [*ins_ids, *del_ids]):
        problems.append("l3p- 밖 id가 변경 목록에 있음")
    if problems:
        raise ReloadAbort("변경 목록 점검 실패: " + "; ".join(problems))
    # 벡터 복사 원본: 삭제될 옛 행 중 본문이 같은 것(삽입 → 삭제 순서라 같은 트랜잭션 안에서 복사할 수 있다)
    src_by_hash: dict[str, str] = {}
    for cid in sorted(del_ids):
        src_by_hash.setdefault(text_hash(old[cid]["text"]), cid)
    insert, todo, chars, tokens = [], {}, 0, 0.0
    for cid in ins_ids:
        h = text_hash(new[cid]["text"])
        src = src_by_hash.get(h)
        insert.append({"chunk_id": cid, "text_hash": h, "src_chunk_id": src})
        if src is None and h not in index_rows and h not in todo:
            todo[h] = cid
            chars += len(new[cid]["text"])
            tokens += estimate_tokens(new[cid]["text"])
    broken = sum(1 for c in new.values() if c.get("parent_id") and c["parent_id"] not in new)
    return Scope(insert=insert, delete=del_ids, keep=len(keep), new_rows=len(new),
                 kinds_after=dict(Counter(c["chunk_kind"] for c in new.values())), broken_parent=broken,
                 vec_new_hashes=sorted(todo), vec_new_chars=chars, vec_new_tokens_est=tokens,
                 year_new={str(k): v for k, v in Counter(new[i].get("year") for i in ins_ids).items()})


def check_scope(scope: Scope, exp: Expect) -> dict[str, Any]:
    """로컬에서 다시 센 값이 계획서 기대값과 같은지. 다르면 ReloadAbort(모두 모아 한 번에)."""
    got = {"insert": len(scope.insert), "delete": len(scope.delete), "keep": scope.keep, "vec_copy": scope.vec_copy,
           "vec_rows": scope.vec_rows, "l3p_after": scope.new_rows, "para_after": scope.kinds_after.get(KIND_PARA, 0),
           "table_after": scope.kinds_after.get(KIND_TABLE, 0), "broken_parent": scope.broken_parent}
    want = {"insert": exp.insert, "delete": exp.delete, "keep": exp.keep, "vec_copy": exp.vec_copy, "vec_rows": exp.vec_new,
            "l3p_after": exp.l3p_after, "para_after": exp.para_after, "table_after": exp.table_after, "broken_parent": 0}
    bad = {k: {"기대": want[k], "실제": got[k]} for k in want if got[k] != want[k]}
    if bad:
        raise ReloadAbort(f"로컬 범위가 기대값과 다름: {json.dumps(bad, ensure_ascii=False)}")
    if exp.keep + exp.delete != exp.l3p_before:
        raise ReloadAbort("기대값 자체 모순: keep + delete ≠ l3p_before")
    return got


def embed_cost(scope: Scope) -> dict[str, Any]:
    tok_char = scope.vec_new_chars * 1.7
    return {"texts": len(scope.vec_new_hashes), "chars": scope.vec_new_chars,
            "tokens_est": int(scope.vec_new_tokens_est), "tokens_chars_x1_7": int(tok_char),
            "usd_est": round(scope.vec_new_tokens_est / 1e6 * EMBED_PRICE_PER_M, 4),
            "usd_chars_x1_7": round(tok_char / 1e6 * EMBED_PRICE_PER_M, 4), "model": "text-embedding-3-small", "executed": False}


def compute_scope(old: Path | None = None, new: Path | None = None) -> tuple[Scope, Path, Path]:
    old_p, new_p = resolve_inputs(old, new)
    changes = json.loads(CHANGES_PATH.read_text(encoding="utf-8"))
    scope = build_scope(read_chunks(old_p), read_chunks(new_p), changes, load_index_rows())
    return scope, old_p, new_p


# --------------------------------------------------------------------------- plan

def plan_blocks(scope: Scope, exp: Expect, backup: str = "both", align_year: bool = False, reindex: bool = False) -> list[dict[str, Any]]:
    nb = math.ceil(len(scope.delete) / DELETE_BATCH)
    sizes = [min(DELETE_BATCH, len(scope.delete) - i * DELETE_BATCH) for i in range(nb)]
    blocks = [
        {"block": "S0", "remote": "읽기 전용", "rows": {"total": exp.total_before, "l3p": exp.l3p_before, "delete_present": exp.delete,
                                                    "insert_collide": 0, "src_with_vec": len(scope.src_ids), "fk_refs": 0, "long_xact": 0,
                                                    "backup_table_exists": False},
         "sql": [SET_READ_ONLY, Q_TOTAL, Q_L3P, Q_L3P_NULLVEC, Q_IDS_PRESENT + " -- 삭제 목록", Q_IDS_PRESENT + " -- 삽입 목록",
                 Q_IDS_WITH_VEC + " -- 복사 원본", Q_FK, Q_LONG_XACT, Q_TABLE_EXISTS, Q_HNSW_BYTES, Q_TUPLES]},
        {"block": "S1", "remote": "읽기" + (" + DDL 1건" if backup == "both" else ""),
         "rows": {"local_backup_lines": exp.delete, **({"backup_table_rows": exp.delete} if backup == "both" else {})},
         "sql": [Q_BACKUP_ROWS, *([SET_LOCK, SET_STMT_S1, S1B_CREATE, Q_BACKUP_TABLE] if backup == "both" else [])]},
        {"block": "S2", "remote": "TEMP만(본 표 무변화)",
         "rows": {"stage": exp.insert, "with_vec": exp.vec_new, "copy_vec": exp.vec_copy, "neither": 0, "both": 0},
         "sql": [S2_CREATE, S2_ADDCOL, S2_INSERT + f" -- {STAGE_BATCH}행 묶음", Q_STAGE]},
        {"block": "S3", "remote": "쓰기(한 트랜잭션)",
         "rows": {"pre_total": exp.total_before, "pre_l3p": exp.l3p_before, "inserted": exp.insert, "deleted": exp.delete,
                  "delete_batches": sizes, "post_total": exp.total_after, "post_l3p": exp.l3p_after, "l3p_nullvec": 0,
                  "para": exp.para_after, "table": exp.table_after, "broken_parent": 0, "outside": exp.outside},
         "sql": [SET_LOCK, SET_STMT_S3, Q_TOTAL, Q_L3P, S3_INSERT, Q_IDS_NULLVEC, S3_DELETE + " -- 묶음마다",
                 Q_TOTAL, Q_L3P, Q_L3P_NULLVEC, Q_KINDS, Q_BROKEN_PARENT, Q_NOT_L3P, Q_IDS_PRESENT, "COMMIT"]},
    ]
    if align_year:
        blocks.append({"block": "S3b", "remote": "쓰기(BE-05-11 B, REINDEX 앞)", "rows": {"updated": exp.keep},
                       "sql": [SET_LOCK, Q_L3P_YEAR_NULL, S3B_UPDATE + f" -- year={V2_YEAR}", Q_L3P_YEAR_NULL]})
    blocks.append({"block": "S4", "remote": "읽기 + ANALYZE", "rows": {"n_live_tup(기대 근처)": exp.total_after},
                   "sql": [Q_HNSW_BYTES, Q_TUPLES, Q_SIZES, Q_L3P_NULLVEC, Q_BROKEN_PARENT, S4_ANALYZE]})
    blocks.append({"block": "S5", "remote": "쓰기(REINDEX)" if reindex else "실행 안 함(--reindex 없음)", "rows": {},
                   "sql": [*S5_SETS, S5_REINDEX, *S5_RESETS, Q_HNSW_BYTES]})
    for b in blocks:
        b["est_time"] = EST_TIME.get(b["block"], "")
    return blocks


def do_plan(args: argparse.Namespace, exp: Expect = DEFAULT_EXPECT, log: Callable[[str], None] = print) -> dict[str, Any]:
    """원격 연결 없음. 로컬 파일만 읽는다."""
    scope, old_p, new_p = compute_scope(args.old, args.new)
    counted = check_scope(scope, exp)
    cost = embed_cost(scope)
    blocks = plan_blocks(scope, exp, args.backup, args.align_year, args.reindex)
    out = {"remote_connections": 0, "inputs": {"old": old_p.name, "new": new_p.name}, "local_counts": counted,
           "expect": exp.as_dict(), "embedding": cost, "max_usd": args.max_usd,
           "options": {"input_switch(BE-05-09)": "A" if args.old is None and args.new is None else "사용자 지정",
                       "backup(BE-05-10)": "A(로컬+원격 표)" if args.backup == "both" else "B(로컬만)",
                       "year(BE-05-11)": "B(맞춤)" if args.align_year else "A(그대로)", "reindex": bool(args.reindex)},
           "remote_cost_usd": 0.0, "blocks": blocks,
           "approval": {"flag": str(APPROVAL_FLAG.relative_to(REPO)) if APPROVAL_FLAG.is_relative_to(REPO) else APPROVAL_FLAG.name,
                        "flag_exists": APPROVAL_FLAG.exists()}}
    log(f"== BE-05-04 C 재적재 계획(원격 연결 0) 입력: 옛 {old_p.name} → 새 {new_p.name} ==")
    log(f"로컬 범위: {json.dumps(counted, ensure_ascii=False)}")
    log(f"임베딩(호출 안 함, 어림): {json.dumps(cost, ensure_ascii=False)} / 상한 ${args.max_usd}")
    for b in blocks:
        log(f"-- [{b['block']}] {b['remote']} · 예상 소요 {b['est_time']} · 기대 {json.dumps(b['rows'], ensure_ascii=False)}")
        for s in b["sql"]:
            log(f"     {s}")
    log("롤백 R1(커밋 뒤, 이 도구 밖·별도 승인): 백업 표 재삽입 ON CONFLICT DO NOTHING → 새 id 삭제 → COUNT 68,818·9,684 확인")
    return out


# --------------------------------------------------------------------------- prepare(L1~L4, 원격 0·임베딩 0)

def switch_input(log: Callable[[str], None] = print) -> dict[str, Any]:
    """BE-05-09 A: 옛 `l3_prmsn.jsonl`·임베딩을 `*.before_be0504`로 복사 보관하고 v2 내용을 `l3_prmsn.jsonl`로 복사한다(v2 파일은 그대로 둔다)."""
    if OLD_KEEP_PATH.exists():
        if sha256_file(CUR_PATH) == sha256_file(V2_PATH):
            log("입력 전환은 이미 되어 있다(건너뜀)")
            return {"switched": False, "already": True}
        raise ReloadAbort(f"{OLD_KEEP_PATH.name}가 이미 있는데 {CUR_PATH.name}이 v2와 다르다. 손으로 확인한다")
    shutil.copy2(CUR_PATH, OLD_KEEP_PATH)
    expect_eq("보관본 sha256", sha256_file(OLD_KEEP_PATH), sha256_file(CUR_PATH))
    EMB_KEEP_DIR.mkdir(parents=True, exist_ok=False)
    for name in ("vectors.npy", "index.json"):
        shutil.copy2(EMB_DIR / name, EMB_KEEP_DIR / name)
    tmp = CUR_PATH.with_suffix(".jsonl.tmp")
    shutil.copy2(V2_PATH, tmp)
    tmp.replace(CUR_PATH)
    expect_eq("전환 뒤 sha256", sha256_file(CUR_PATH), sha256_file(V2_PATH))
    log(f"입력 전환: {CUR_PATH.name} ← {V2_PATH.name}, 보관 {OLD_KEEP_PATH.name}, {EMB_KEEP_DIR.name}/")
    return {"switched": True}


def simulate_embed_corpus(new_chunks: Sequence[dict[str, Any]], index_rows: dict[str, int]) -> list[str]:
    """`embed_corpus.py run`이 전환 뒤 입력(ALL_FILES의 l3_prmsn 자리에 v2)으로 새로 호출할 고유 텍스트 해시."""
    other = [c for n in ALL_FILES if n != CUR_PATH.name for c in read_chunks(OUT_DIR / n)]
    return sorted({text_hash(c["text"]) for c in [*other, *new_chunks]} - set(index_rows))


def write_manifest(scope: Scope, old_p: Path, new_p: Path, exp: Expect) -> dict[str, Any]:
    body = {
        "version": 1, "created_utc": utc_stamp(),
        "inputs": {"old": {"name": old_p.name, "sha256": sha256_file(old_p)}, "new": {"name": new_p.name, "sha256": sha256_file(new_p)},
                   "changes": {"name": CHANGES_PATH.name, "sha256": sha256_file(CHANGES_PATH)}},
        "expect": exp.as_dict(), "insert": scope.insert, "delete": scope.delete, "embed_todo": scope.vec_new_hashes,
    }
    manifest = {**body, "body_sha256": body_sha(body)}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)
    return manifest


def do_prepare(args: argparse.Namespace, exp: Expect = DEFAULT_EXPECT, log: Callable[[str], None] = print) -> dict[str, Any]:
    out: dict[str, Any] = {"remote_connections": 0, "embedding_calls": 0}
    if args.switch_input:  # L1
        out["switch"] = switch_input(log)
    scope, old_p, new_p = compute_scope(args.old, args.new)  # L2 입력 점검
    out["local_counts"] = check_scope(scope, exp)
    cost = embed_cost(scope)
    out["embedding"] = cost
    raw_usd = max(scope.vec_new_tokens_est, scope.vec_new_chars * 1.7) / 1e6 * EMBED_PRICE_PER_M  # 반올림 전 값으로 비교
    if raw_usd > args.max_usd:
        raise ReloadAbort(f"임베딩 어림 비용이 상한 ${args.max_usd}를 넘는다: {cost}")
    index_rows = load_index_rows()
    new_chunks = read_chunks(new_p)
    would = simulate_embed_corpus(new_chunks, index_rows)
    out["embed_corpus_would_call"] = len(would)
    if set(would) != set(scope.vec_new_hashes):
        extra = len(set(would) - set(scope.vec_new_hashes))
        raise ReloadAbort(f"embed_corpus가 부를 텍스트({len(would)})가 재적재 새 본문({len(scope.vec_new_hashes)})과 다르다(밖 {extra})")
    by_hash = {r["text_hash"]: r["chunk_id"] for r in scope.insert}
    chars = {text_hash(c["text"]): len(c["text"]) for c in new_chunks}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with open(EMBED_TODO_PATH, "w", encoding="utf-8") as f:  # 본문은 쓰지 않는다(v2 파일에 있음)
        for h in scope.vec_new_hashes:
            f.write(json.dumps({"text_hash": h, "chunk_id": by_hash[h], "chars": chars[h]}) + "\n")
    manifest = write_manifest(scope, old_p, new_p, exp)  # L4
    out["manifest"] = {"path": MANIFEST_PATH.name, "body_sha256": manifest["body_sha256"], "insert": len(scope.insert),
                       "delete": len(scope.delete), "vec_copy": scope.vec_copy, "embed_todo": len(scope.vec_new_hashes)}
    cur_is_v2 = CUR_PATH.exists() and sha256_file(CUR_PATH) == sha256_file(new_p)
    out["input_switched"] = cur_is_v2
    out["next"] = ([] if cur_is_v2 else ["python scripts/be05_04c_reload.py prepare --switch-input   # BE-05-09 A, 승인 A1 뒤"]) + [
        "python scripts/embed_corpus.py plan   # 남은 고유 텍스트가 embed_todo와 같은지(호출 0)",
        f"python scripts/embed_corpus.py run --max-usd {args.max_usd}   # 승인 A2 뒤, 새 본문 {len(scope.vec_new_hashes)}개만 호출",
        "python scripts/be05_04c_reload.py apply --yes   # 승인 파일 생성 뒤(A3~A6)"]
    log(json.dumps(out, ensure_ascii=False, indent=1))
    return out


# --------------------------------------------------------------------------- apply 준비(원격 연결 전)

def load_manifest(exp: Expect) -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise Refused("manifest 없음: 먼저 prepare를 실행한다")
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    body = {k: v for k, v in m.items() if k != "body_sha256"}
    if body_sha(body) != m.get("body_sha256"):
        raise Refused("manifest 본문 sha256 불일치(손으로 고쳤거나 손상)")
    if m["expect"] != exp.as_dict():
        raise Refused("manifest 기대값이 도구 기대값과 다르다. prepare를 다시 실행한다")
    for key, p in (("new", V2_PATH), ("changes", CHANGES_PATH)):
        if not p.exists() or sha256_file(p) != m["inputs"][key]["sha256"]:
            raise Refused(f"입력 {p.name}이 manifest를 만든 뒤 바뀌었다. prepare를 다시 실행한다")
    expect_counts = {"insert": exp.insert, "delete": exp.delete}
    if {"insert": len(m["insert"]), "delete": len(m["delete"])} != expect_counts:
        raise Refused("manifest 목록 길이가 기대값과 다르다")
    return m


def build_stage_rows(manifest: dict[str, Any], vectors: tuple[Any, dict[str, int]] | None) -> list[tuple[Any, ...]]:
    """S2에 보낼 행. 새 본문은 로컬 벡터 리터럴, 본문 같은 행은 src_chunk_id(서버 안에서 옛 벡터 복사). 벡터가 없으면 Refused."""
    import numpy as np  # noqa: PLC0415

    new = {c["chunk_id"]: c for c in read_chunks(V2_PATH)}
    mat, idx = vectors if vectors else (None, {})
    missing, bad, rows = [], [], []
    for r in manifest["insert"]:
        c = new[r["chunk_id"]]
        if text_hash(c["text"]) != r["text_hash"]:
            raise Refused("v2 본문 해시가 manifest와 다르다")
        if r["src_chunk_id"]:
            rows.append((*pg_row(c, None), r["src_chunk_id"]))
            continue
        i = idx.get(r["text_hash"]) if mat is not None else None
        if i is None:
            missing.append(r["chunk_id"])
            continue
        v = np.asarray(mat[i], dtype="float64")
        if v.shape != (DIM,) or not np.all(np.isfinite(v)) or abs(float(np.linalg.norm(v)) - 1.0) > 0.01:
            bad.append(r["chunk_id"])
            continue
        rows.append((*pg_row(c, vec_literal(v)), None))
    if missing:
        raise Refused(f"로컬 벡터가 없는 새 본문 {len(missing)}개: embed_corpus.py run(승인 A2)을 먼저 끝낸다")
    if bad:
        raise Refused(f"차원·노름이 이상한 로컬 벡터 {len(bad)}개")
    return rows


def gate(args: argparse.Namespace) -> None:
    """이중 안전장치: --yes와 승인 파일이 둘 다 있어야 한다. 원격 연결 전에 확인한다."""
    if not args.yes:
        raise Refused("apply는 --yes가 필요하다")
    if not APPROVAL_FLAG.is_file():
        raise Refused(f"승인 파일이 없다: {APPROVAL_FLAG.name}(사용자 승인 뒤 메인 세션이 data/mock/review/에 만든다)")
    if args.from_block == "S5" and not args.reindex:
        raise Refused("--from S5는 --reindex와 함께 쓴다")


# --------------------------------------------------------------------------- 원격 블록

def one(cur: Any, sql: str, params: tuple[Any, ...] | None = None) -> Any:
    cur.execute(sql, params)
    return cur.fetchone()[0]


def transaction(conn: Any, name: str, fn: Callable[[Any], dict[str, Any]], log: JsonlLog) -> dict[str, Any]:
    """한 트랜잭션. 예외·기대 불일치면 롤백하고 ReloadAbort. 커밋은 fn이 끝난 뒤 한 번."""
    cur = conn.cursor()
    t0 = time.time()
    try:
        cur.execute(SET_LOCK)
        res = fn(cur)
        conn.commit()
    except BaseException as exc:  # Ctrl+C(계획서 §5.2 메모리 85% 중단)도 명시적으로 롤백하고 기록한다
        conn.rollback()
        log.event("rollback", block=name, error=type(exc).__name__, detail=str(exc)[:300], seconds=round(time.time() - t0, 2))
        if isinstance(exc, ReloadAbort) or not isinstance(exc, Exception):
            raise
        raise ReloadAbort(f"{name}: {type(exc).__name__}") from exc
    log.event("commit", block=name, result=res, seconds=round(time.time() - t0, 2))
    return res


def read_only(conn: Any, name: str, fn: Callable[[Any], dict[str, Any]], log: JsonlLog) -> dict[str, Any]:
    cur = conn.cursor()
    t0 = time.time()
    try:
        cur.execute(SET_READ_ONLY)
        res = fn(cur)
    except Exception as exc:
        log.event("abort", block=name, error=type(exc).__name__, detail=str(exc)[:300])
        if isinstance(exc, ReloadAbort):
            raise
        raise ReloadAbort(f"{name}: {type(exc).__name__}") from exc
    finally:
        conn.rollback()
    log.event("read", block=name, result=res, seconds=round(time.time() - t0, 2))
    return res


def s0_check(cur: Any, m: dict[str, Any], exp: Expect, backup: str) -> dict[str, Any]:
    ins = [r["chunk_id"] for r in m["insert"]]
    src = sorted({r["src_chunk_id"] for r in m["insert"] if r["src_chunk_id"]})
    got = {
        "total": int(one(cur, Q_TOTAL)), "l3p": int(one(cur, Q_L3P, (L3P,))), "l3p_nullvec": int(one(cur, Q_L3P_NULLVEC, (L3P,))),
        "delete_present": int(one(cur, Q_IDS_PRESENT, (m["delete"],))), "insert_collide": int(one(cur, Q_IDS_PRESENT, (ins,))),
        "src_with_vec": int(one(cur, Q_IDS_WITH_VEC, (src,))), "fk_refs": int(one(cur, Q_FK)), "long_xact": int(one(cur, Q_LONG_XACT, (LONG_XACT_MIN,))),
        "backup_table_exists": bool(one(cur, Q_TABLE_EXISTS, (BACKUP_TABLE,))),
    }
    want = {"total": exp.total_before, "l3p": exp.l3p_before, "l3p_nullvec": 0, "delete_present": exp.delete, "insert_collide": 0,
            "src_with_vec": len(src), "fk_refs": 0, "long_xact": 0, "backup_table_exists": False}
    if backup != "both":
        want["backup_table_exists"] = got["backup_table_exists"]  # 원격 표를 만들지 않으면 상관없음
    bad = {k: {"기대": want[k], "실제": got[k]} for k in want if got[k] != want[k]}
    if bad:
        raise ReloadAbort(f"S0 사전 점검 불일치(원격 상태가 계획과 다름, 다른 작업이 썼을 수 있음): {json.dumps(bad, ensure_ascii=False)}")
    got["hnsw_mb"] = round(int(one(cur, Q_HNSW_BYTES, (HNSW_INDEX,))) / 1048576, 1)
    cur.execute(Q_TUPLES)
    t = cur.fetchone()
    got["n_live_tup"], got["n_dead_tup"] = (int(t[0]), int(t[1])) if t else (None, None)
    return got


def s1a_backup_local(conn: Any, m: dict[str, Any], path: Path, log: JsonlLog) -> dict[str, Any]:
    """삭제 대상 행 전체 열(벡터 포함)을 row_to_json 그대로 jsonl.gz에 쓴다. 줄 수·id 집합이 삭제 목록과 같아야 한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    want = set(m["delete"])

    def fn(cur: Any) -> dict[str, Any]:
        cur.execute(Q_BACKUP_ROWS, (m["delete"],))
        rows = cur.fetchall()
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for _cid, js in rows:
                f.write(js + "\n")
        ids, nullvec = [], 0
        with gzip.open(tmp, "rt", encoding="utf-8") as f:
            for ln in f:
                rec = json.loads(ln)
                ids.append(rec["chunk_id"])
                nullvec += rec.get("embedding") is None
        expect_eq("로컬 백업 줄 수", len(ids), len(want))
        expect_eq("로컬 백업 id 집합", set(ids) == want, True)
        tmp.replace(path)
        return {"file": path.name, "lines": len(ids), "nullvec": nullvec, "bytes": path.stat().st_size, "sha256": sha256_file(path)}

    return read_only(conn, "S1a 로컬 백업", fn, log)


def s1b_backup_table(cur: Any, m: dict[str, Any], local_lines: int) -> dict[str, Any]:
    cur.execute(SET_STMT_S1)
    if one(cur, Q_TABLE_EXISTS, (BACKUP_TABLE,)):
        raise ReloadAbort(f"백업 표 {BACKUP_TABLE}가 이미 있다(이전 실행 흔적). 손으로 확인한다")
    cur.execute(S1B_CREATE, (m["delete"],))
    cur.execute(Q_BACKUP_TABLE)
    n, distinct = (int(x) for x in cur.fetchone())
    expect_eq("백업 표 행 수", n, len(m["delete"]))
    expect_eq("백업 표 고유 id", distinct, len(m["delete"]))
    expect_eq("백업 표 = 로컬 백업 줄 수", n, local_lines)
    return {"table": BACKUP_TABLE, "rows": n}


def s2_stage(cur: Any, rows: list[tuple[Any, ...]], exp: Expect) -> dict[str, Any]:
    cur.execute(S2_CREATE)
    cur.execute(S2_ADDCOL)
    for i in range(0, len(rows), STAGE_BATCH):
        cur.executemany(S2_INSERT, rows[i : i + STAGE_BATCH])
    cur.execute(Q_STAGE)
    n, with_vec, copy_vec, neither, both = (int(x) for x in cur.fetchone())
    got = {"stage": n, "with_vec": with_vec, "copy_vec": copy_vec, "neither": neither, "both": both}
    want = {"stage": exp.insert, "with_vec": exp.vec_new, "copy_vec": exp.vec_copy, "neither": 0, "both": 0}
    for k in want:
        expect_eq(f"S2 {k}", got[k], want[k])
    return got


def s3_replace(cur: Any, m: dict[str, Any], exp: Expect) -> dict[str, Any]:
    """새 id 삽입 → (벡터 확인) → 옛 id 삭제(500개씩) → 사후 검사. 호출자가 한 트랜잭션으로 감싸고 실패 시 롤백한다."""
    ins = [r["chunk_id"] for r in m["insert"]]
    cur.execute(SET_STMT_S3)
    expect_eq("S3 사전 전체", int(one(cur, Q_TOTAL)), exp.total_before)
    expect_eq("S3 사전 l3p", int(one(cur, Q_L3P, (L3P,))), exp.l3p_before)
    cur.execute(S3_INSERT)
    expect_eq("S3 삽입 rowcount", cur.rowcount, exp.insert)
    expect_eq("S3 삽입 행 벡터 NULL", int(one(cur, Q_IDS_NULLVEC, (ins,))), 0)
    deleted, batches = 0, []
    for i in range(0, len(m["delete"]), DELETE_BATCH):
        part = m["delete"][i : i + DELETE_BATCH]
        cur.execute(S3_DELETE, (part,))
        expect_eq(f"S3 삭제 묶음 {i // DELETE_BATCH + 1} rowcount", cur.rowcount, len(part))
        deleted += cur.rowcount
        batches.append(cur.rowcount)
    expect_eq("S3 삭제 합계", deleted, exp.delete)
    cur.execute(Q_KINDS, (L3P,))
    kinds = {r[0]: int(r[1]) for r in cur.fetchall()}
    got = {
        "post_total": int(one(cur, Q_TOTAL)), "post_l3p": int(one(cur, Q_L3P, (L3P,))), "l3p_nullvec": int(one(cur, Q_L3P_NULLVEC, (L3P,))),
        "para": kinds.get(KIND_PARA, 0), "table": kinds.get(KIND_TABLE, 0), "other_kinds": sum(v for k, v in kinds.items() if k not in (KIND_PARA, KIND_TABLE)),
        "broken_parent": int(one(cur, Q_BROKEN_PARENT, (L3P,))), "outside": int(one(cur, Q_NOT_L3P, (L3P,))),
        "insert_present": int(one(cur, Q_IDS_PRESENT, (ins,))), "delete_left": int(one(cur, Q_IDS_PRESENT, (m["delete"],))),
    }
    want = {"post_total": exp.total_after, "post_l3p": exp.l3p_after, "l3p_nullvec": 0, "para": exp.para_after, "table": exp.table_after,
            "other_kinds": 0, "broken_parent": 0, "outside": exp.outside, "insert_present": exp.insert, "delete_left": 0}
    for k in want:
        expect_eq(f"S3 사후 {k}", got[k], want[k])
    return {"inserted": exp.insert, "deleted": deleted, "delete_batches": batches, **got}


def s3b_align_year(cur: Any, exp: Expect) -> dict[str, Any]:
    pre = int(one(cur, Q_L3P_YEAR_NULL, (L3P,)))
    expect_eq("S3b 사전 year NULL(유지 행)", pre, exp.keep)
    cur.execute(S3B_UPDATE, (V2_YEAR, L3P))
    expect_eq("S3b UPDATE rowcount", cur.rowcount, exp.keep)
    expect_eq("S3b 사후 year NULL", int(one(cur, Q_L3P_YEAR_NULL, (L3P,))), 0)
    expect_eq("S3b 사후 전체", int(one(cur, Q_TOTAL)), exp.total_after)
    return {"updated": exp.keep}


def s4_measure(cur: Any, exp: Expect) -> dict[str, Any]:
    got: dict[str, Any] = {"hnsw_mb": round(int(one(cur, Q_HNSW_BYTES, (HNSW_INDEX,))) / 1048576, 1)}
    cur.execute(Q_TUPLES)
    t = cur.fetchone()
    got["n_live_tup"], got["n_dead_tup"] = (int(t[0]), int(t[1])) if t else (None, None)
    cur.execute(Q_SIZES)
    s = cur.fetchone()
    got["table_mb"], got["db_mb"] = round(int(s[0]) / 1048576, 1), round(int(s[1]) / 1048576, 1)
    got["total"] = int(one(cur, Q_TOTAL))
    got["l3p"] = int(one(cur, Q_L3P, (L3P,)))
    got["l3p_nullvec"] = int(one(cur, Q_L3P_NULLVEC, (L3P,)))
    got["broken_parent"] = int(one(cur, Q_BROKEN_PARENT, (L3P,)))
    for k, w in (("total", exp.total_after), ("l3p", exp.l3p_after), ("l3p_nullvec", 0), ("broken_parent", 0)):
        expect_eq(f"S4 {k}(S5 진행 조건)", got[k], w)
    return got


def s4_analyze(cur: Any) -> dict[str, Any]:
    cur.execute(S4_ANALYZE)
    return {"analyze": True}


def s5_reindex(conn: Any, log: JsonlLog) -> dict[str, Any]:
    """REINDEX(128MB·병렬 0, 세션 SET은 이 단계에서만). 실패하면 롤백·RESET하고 ReloadAbort."""
    cur = conn.cursor()
    t0 = time.time()
    try:
        before = int(one(cur, Q_HNSW_BYTES, (HNSW_INDEX,)))
        for s in S5_SETS:
            cur.execute(s)
        cur.execute(S5_REINDEX)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.event("rollback", block="S5", error=type(exc).__name__, detail=str(exc)[:300], seconds=round(time.time() - t0, 1))
        raise ReloadAbort(f"S5: {type(exc).__name__}") from exc
    finally:
        rc = conn.cursor()
        for s in S5_RESETS:
            rc.execute(s)
        conn.commit()
    after = int(one(conn.cursor(), Q_HNSW_BYTES, (HNSW_INDEX,)))
    conn.rollback()
    res = {"hnsw_mb_before": round(before / 1048576, 1), "hnsw_mb_after": round(after / 1048576, 1), "seconds": round(time.time() - t0, 1)}
    log.event("commit", block="S5", result=res)
    return res


@dataclass
class ApplyOptions:
    backup: str = "both"
    align_year: bool = False
    reindex: bool = False
    until: str = "S4"
    from_block: str = "S0"


def do_apply(conn: Any, m: dict[str, Any], stage_rows: list[tuple[Any, ...]], opts: ApplyOptions, log: JsonlLog,
             exp: Expect = DEFAULT_EXPECT, stamp: str | None = None) -> dict[str, Any]:
    stamp = stamp or utc_stamp()
    rep: dict[str, Any] = {}
    log.event("start", options=asdict(opts), expect=exp.as_dict(), dsn_env=DSN_ENV, manifest_body_sha256=m["body_sha256"])
    if opts.from_block == "S5":
        rep["S4"] = read_only(conn, "S4 재확인", lambda c: s4_measure(c, exp), log)
        rep["S5"] = s5_reindex(conn, log)
        return rep

    rep["S0"] = read_only(conn, "S0", lambda c: s0_check(c, m, exp, opts.backup), log)
    if opts.until == "S0":
        return rep
    rep["S1a"] = s1a_backup_local(conn, m, BACKUP_DIR / f"be0504_before_reload_{stamp}.jsonl.gz", log)
    if opts.backup == "both":
        rep["S1b"] = transaction(conn, "S1b 원격 백업 표", lambda c: s1b_backup_table(c, m, rep["S1a"]["lines"]), log)
    if opts.until == "S1":
        return rep
    rep["S2"] = transaction(conn, "S2 TEMP 적재", lambda c: s2_stage(c, stage_rows, exp), log)
    if opts.until == "S2":
        log.event("note", block="S2", detail="TEMP 표는 연결을 닫으면 사라진다. 다음 실행은 S0부터 다시 한다")
        return rep
    rep["S3"] = transaction(conn, "S3 본 교체", lambda c: s3_replace(c, m, exp), log)
    if opts.align_year:
        rep["S3b"] = transaction(conn, "S3b year 맞춤", lambda c: s3b_align_year(c, exp), log)
    if opts.until == "S3":
        return rep
    rep["S4"] = read_only(conn, "S4 측정", lambda c: s4_measure(c, exp), log)
    rep["S4_analyze"] = transaction(conn, "S4 ANALYZE", s4_analyze, log)
    if opts.reindex:
        rep["S5"] = s5_reindex(conn, log)
    else:
        log.event("skip", block="S5", detail="--reindex 없음. S4 결과를 본 뒤 별도 승인(A7)으로 `apply --yes --from S5 --reindex`")
    return rep


def connect(connect_fn: Callable[[str], Any] | None = None) -> Any:
    dsn = resolve_dsn(DSN_ENV)
    if not dsn:
        raise Refused(f"{DSN_ENV} 값을 찾지 못했다")
    if connect_fn is None:
        import psycopg  # noqa: PLC0415 - apply 때만 필요

        connect_fn = psycopg.connect
    return connect_fn(dsn)


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="plan", choices=("plan", "prepare", "apply"))
    ap.add_argument("--yes", action="store_true", help="apply 쓰기 동의(승인 파일도 필요)")
    ap.add_argument("--old", type=Path, help="옛 허가 상세 청크 파일(기본: before_be0504가 있으면 그것, 없으면 l3_prmsn.jsonl)")
    ap.add_argument("--new", type=Path, help="새(v2) 허가 상세 청크 파일(기본 l3_prmsn.v2.jsonl). BE-05-09 B일 때 지정")
    ap.add_argument("--switch-input", action="store_true", help="prepare에서 BE-05-09 A 입력 전환 실행")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="임베딩 어림 비용 상한(이 도구는 호출하지 않는다)")
    ap.add_argument("--backup", choices=("both", "local"), default="both", help="BE-05-10: both=A(로컬+원격 표), local=B")
    ap.add_argument("--align-year", action="store_true", help="BE-05-11 B: 유지 행 year 맞춤(S3b, REINDEX 앞)")
    ap.add_argument("--reindex", action="store_true", help="S5 REINDEX 실행(기본 안 함, 승인 A7)")
    ap.add_argument("--until", choices=BLOCKS, default="S4", help="이 블록까지만 실행하고 멈춘다")
    ap.add_argument("--from", dest="from_block", choices=("S0", "S5"), default="S0", help="S5: 재적재 뒤 REINDEX만(--reindex 필요)")
    return ap


def main(argv: Sequence[str] | None = None, connect_fn: Callable[[str], Any] | None = None, exp: Expect | None = None) -> int:
    args = build_parser().parse_args(argv)
    exp = exp or DEFAULT_EXPECT
    try:
        if args.cmd == "plan":
            do_plan(args, exp)
            return 0
        if args.cmd == "prepare":
            do_prepare(args, exp)
            return 0
        gate(args)
        manifest = load_manifest(exp)
        from load_corpus import load_vectors  # noqa: PLC0415

        rows = build_stage_rows(manifest, load_vectors(EMB_DIR)) if args.from_block == "S0" else []
        print(f"접속: 환경변수 {DSN_ENV}(값은 출력하지 않는다)")
        print(DAILY_BACKUP_NOTICE)
        stamp = utc_stamp()
        log = JsonlLog(LOG_DIR / f"be0504_reload_{stamp}.jsonl")
        opts = ApplyOptions(args.backup, args.align_year, args.reindex, args.until, args.from_block)
        conn = connect(connect_fn)
        try:
            t0 = time.time()
            rep = do_apply(conn, manifest, rows, opts, log, exp, stamp)
            log.event("done", blocks=sorted(rep), seconds=round(time.time() - t0, 1))
        finally:
            conn.close()
        return 0
    except Refused as e:
        print(f"거부: {redact(str(e))}", file=sys.stderr)
        return 2
    except ReloadAbort as e:
        print(f"중단: {redact(str(e))}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    install_excepthook()  # 처리되지 않은 예외에서 DSN·키 가리기(가져오기만 할 때는 설치하지 않음)
    raise SystemExit(main())

