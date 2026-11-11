"""BE-16 원격 Supabase 단계 1~3 이행(사용자 승인 2026-11-11: BE-16-02 A, BE-16-03 A).

  plan            (기본) 읽기 전용. 사전 COUNT·적용할 SQL·예상 변경 행 수를 출력한다. 쓰기 0.
  apply --yes     쓰기. 단계마다 트랜잭션 + 사전·사후 COUNT 비교, 기대와 다르면 롤백하고 중단한다(다음 단계로 넘어가지 않음).
  verify          읽기 전용 사후 확인(행 수·색인·샘플·하이브리드 검색 스모크, 질의 임베딩 호출 포함 ≤3회).

단계 1  비파괴 스키마: corpus_chunks 열 3개 + caution CHECK 재정의
단계 2  추가만: l2_elderly 청크·elderly_kids 행·load_log UPSERT (ON CONFLICT DO NOTHING, 기존 행 변경 0)
단계 3  UPDATE: contra_pair.as_of·l2_combo base_date 07-21→07-31, 기존 청크 메타(year·source_file·effective_date) 채움. 앞서 로컬 백업.

금지(이 스크립트는 하지 않는다): DROP INDEX·DROP TABLE·DELETE·TRUNCATE·REINDEX·벡터 열 변경·임부/연령/용량/수유부/노인주의(심평원) as_of 변경.
접속 문자열은 환경변수 SUPABASE_DB_URL(없으면 앱 Settings)에서 프로세스 안에서만 읽고 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from build_corpus_l2 import OUT_DIR, read_chunks  # noqa: E402
from load_corpus import ALL_FILES, RemoteLoadRefused, _insert_sql, load_vectors, resolve_dsn  # noqa: E402

from app.db import loaders  # noqa: E402
from app.security.redact import install_excepthook, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"
OLD_DATE = "2026-07-21"
NEW_DATE = loaders.AS_OF_COMBO  # 2026-07-31(병용 JSON 파일 이름 끝 날짜)
CAUTION_KINDS = ("dose", "lactation", "elderly", "elderly_kids")
CHECK_NAME = "caution_kind_check"
NEW_COLS = {"year": "SMALLINT", "source_file": "TEXT NOT NULL DEFAULT ''", "effective_date": "DATE"}
HNSW_INDEX = "idx_corpus_embedding_hnsw"
UPDATE_BATCH = 500

# 기대값(지시서). 실제 원격·로컬 값이 다르면 그 단계를 롤백하고 중단한다.
EXPECT = {
    "corpus_before": 68_572, "corpus_after": 68_818, "new_chunks": 246, "new_chunk_kind": "l2_elderly",
    "caution_before": 1_740, "caution_after": 3_337, "new_caution": 1_597,
    "contra_pair": 23_619, "combo_chunks": 23_619,
}


class StageAbort(RuntimeError):
    """기대와 다름 → 그 단계 롤백, 이후 단계 실행하지 않음."""


# --------------------------------------------------------------------------- 공통

def connect(read_only: bool, connect_fn: Callable[[str], Any] | None = None) -> Any:
    dsn = resolve_dsn(DSN_ENV)
    if not dsn:
        raise RemoteLoadRefused(f"{DSN_ENV} 값을 찾지 못했다")
    if connect_fn is None:
        import psycopg  # noqa: PLC0415

        connect_fn = psycopg.connect
    conn = connect_fn(dsn)
    if read_only:
        conn.read_only = True  # 쓰기 연결에서만 해제한다
    return conn


def one(cur: Any, sql: str, params: tuple[Any, ...] | None = None) -> Any:
    cur.execute(sql, params)
    return cur.fetchone()[0]


def count(cur: Any, table: str) -> int:
    return int(one(cur, f"SELECT COUNT(*) FROM {table}"))  # noqa: S608 - 테이블 이름은 코드 상수


def iso(v: Any) -> str | None:
    return None if v is None else (v.isoformat() if hasattr(v, "isoformat") else str(v))


def transaction(conn: Any, name: str, fn: Callable[[Any], dict[str, Any]], log: Callable[[str], None] = print) -> dict[str, Any]:
    """한 트랜잭션으로 fn을 실행한다. 예외·StageAbort면 롤백하고 StageAbort로 올린다. 커밋은 fn이 끝난 뒤 한 번만."""
    cur = conn.cursor()
    try:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        res = fn(cur)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log(f"[{name}] 롤백: {type(exc).__name__}: {redact(str(exc))[:200]}")  # S-07: psycopg DETAIL의 행·접속 조각 가리기
        raise StageAbort(f"{name}: {type(exc).__name__}") from exc
    log(f"[{name}] 커밋: {json.dumps(res, ensure_ascii=False, default=str)}")
    return res


def expect_eq(what: str, got: Any, want: Any) -> None:
    if got != want:
        raise StageAbort(f"{what}: 기대 {want}, 실제 {got}")


# --------------------------------------------------------------------------- 현재 상태 조회(읽기)

def caution_check_def(cur: Any) -> list[tuple[str, str]]:
    cur.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'public.caution'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) ILIKE '%kind%'")
    return [(r[0], r[1]) for r in cur.fetchall()]


def corpus_columns(cur: Any) -> set[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'corpus_chunks'")
    return {r[0] for r in cur.fetchall()}


def state(cur: Any) -> dict[str, Any]:
    cols = corpus_columns(cur)
    checks = caution_check_def(cur)
    cur.execute("SELECT as_of::text, COUNT(*) FROM contra_pair GROUP BY 1 ORDER BY 1")
    as_of = {r[0]: int(r[1]) for r in cur.fetchall()}
    cur.execute("SELECT base_date::text, COUNT(*) FROM corpus_chunks WHERE chunk_kind = 'l2_combo' GROUP BY 1 ORDER BY 1")
    base = {r[0]: int(r[1]) for r in cur.fetchall()}
    return {
        "corpus": count(cur, "corpus_chunks"), "caution": count(cur, "caution"), "contra_pair": count(cur, "contra_pair"),
        "load_log": count(cur, "load_log"), "new_cols_present": sorted(set(NEW_COLS) & cols),
        "caution_checks": checks, "contra_as_of": as_of, "combo_base_date": base,
        "hnsw_bytes": int(one(cur, "SELECT COALESCE(pg_relation_size(to_regclass(%s)), 0)", (HNSW_INDEX,))),
    }


def stage1_done(st: dict[str, Any]) -> bool:
    return len(st["new_cols_present"]) == len(NEW_COLS) and any("elderly_kids" in d for _, d in st["caution_checks"])


def stage2_done(st: dict[str, Any]) -> bool:
    return st["corpus"] == EXPECT["corpus_after"] and st["caution"] == EXPECT["caution_after"]


# --------------------------------------------------------------------------- 로컬 입력

def local_chunks() -> list[dict[str, Any]]:
    """`--all`과 같은 입력(corpus/ 기준 네 파일). before_be16 백업 파일은 읽지 않는다."""
    return [c for n in ALL_FILES for c in read_chunks(OUT_DIR / n)]


def collect_sources() -> dict[str, Any]:
    """load_log 갱신·elderly_kids 적재용(병용 JSON은 스트리밍, 1분 안팎)."""
    data = REPO / "data"
    out = {}
    for name in (loaders.COMBO_JSON_NAME, loaders.ELDERLY_KIDS_CSV_NAME):
        table, norm, as_of = loaders.CORE_SOURCES.get(name) or loaders.EXTENSION_SOURCES[name]
        out[name] = loaders.read_source(data / name, norm, table, as_of)
    return out


def meta_tuple(c: dict[str, Any]) -> tuple[int | None, str, str | None]:
    y = c.get("year")
    return (int(y) if y not in (None, "") else None, c.get("source_file") or "", c.get("effective_date") or None)


def meta_map(chunks: Iterable[dict[str, Any]]) -> dict[str, tuple[int | None, str, str | None]]:
    """로컬 jsonl에 year·source_file·effective_date 중 하나라도 값이 있는 청크만."""
    out = {}
    for c in chunks:
        t = meta_tuple(c)
        if t != (None, "", None):
            out[c["chunk_id"]] = t
    return out


# --------------------------------------------------------------------------- 단계 1

STAGE1_SQL = [
    *[f"ALTER TABLE corpus_chunks ADD COLUMN IF NOT EXISTS {c} {t}" for c, t in NEW_COLS.items()],
    "ALTER TABLE caution DROP CONSTRAINT <카탈로그에서 찾은 이름>",
    f"ALTER TABLE caution ADD CONSTRAINT {CHECK_NAME} CHECK (kind IN ({', '.join(repr(k) for k in CAUTION_KINDS)}))",
]


def stage1(cur: Any) -> dict[str, Any]:
    pre_caution, pre_corpus = count(cur, "caution"), count(cur, "corpus_chunks")
    expect_eq("caution 사전 COUNT", pre_caution, EXPECT["caution_before"])
    expect_eq("corpus 사전 COUNT", pre_corpus, EXPECT["corpus_before"])
    for c, t in NEW_COLS.items():
        cur.execute(f"ALTER TABLE corpus_chunks ADD COLUMN IF NOT EXISTS {c} {t}")  # noqa: S608 - 상수
    checks = caution_check_def(cur)
    if len(checks) != 1:
        raise StageAbort(f"caution kind CHECK 제약이 {len(checks)}개(1개여야 함)")
    name, _ = checks[0]
    if not name.replace("_", "").isalnum():
        raise StageAbort("제약 이름 형식 이상")
    cur.execute(f'ALTER TABLE caution DROP CONSTRAINT "{name}"')  # noqa: S608 - 카탈로그에서 읽은 식별자(검증함)
    kinds = ", ".join(f"'{k}'" for k in CAUTION_KINDS)
    cur.execute(f"ALTER TABLE caution ADD CONSTRAINT {CHECK_NAME} CHECK (kind IN ({kinds}))")  # noqa: S608 - 상수
    post_caution, post_corpus = count(cur, "caution"), count(cur, "corpus_chunks")
    expect_eq("caution 사후 COUNT", post_caution, pre_caution)
    expect_eq("corpus 사후 COUNT", post_corpus, pre_corpus)
    expect_eq("새 열", sorted(set(NEW_COLS) & corpus_columns(cur)), sorted(NEW_COLS))
    post_checks = caution_check_def(cur)
    if not (len(post_checks) == 1 and "elderly_kids" in post_checks[0][1]):
        raise StageAbort("재정의한 CHECK에 elderly_kids가 없음")
    return {"caution": [pre_caution, post_caution], "corpus": [pre_corpus, post_corpus], "dropped_constraint": name,
            "added_constraint": CHECK_NAME, "added_columns": sorted(NEW_COLS)}


# --------------------------------------------------------------------------- 단계 2

def stage2(cur: Any, chunks: list[dict[str, Any]], vectors: Any, sources: dict[str, Any], batch_rows: int = 200) -> dict[str, Any]:
    from load_corpus import pg_row, vec_literal  # noqa: PLC0415

    pre_corpus, pre_caution, pre_log = count(cur, "corpus_chunks"), count(cur, "caution"), count(cur, "load_log")
    expect_eq("corpus 사전 COUNT", pre_corpus, EXPECT["corpus_before"])
    expect_eq("caution 사전 COUNT", pre_caution, EXPECT["caution_before"])
    cur.execute("SELECT chunk_id FROM corpus_chunks")
    have = {r[0] for r in cur.fetchall()}
    todo = [c for c in chunks if c["chunk_id"] not in have]
    expect_eq("추가할 청크 수", len(todo), EXPECT["new_chunks"])
    expect_eq("추가 청크 종류", {c["chunk_kind"] for c in todo}, {EXPECT["new_chunk_kind"]})
    if vectors is None:
        raise StageAbort("로컬 vectors.npy 없음(API 호출이 필요하므로 중단)")
    mat, idx = vectors
    from embed_corpus import text_hash  # noqa: PLC0415

    missing = [c["chunk_id"] for c in todo if text_hash(c["text"]) not in idx]
    if missing:
        raise StageAbort(f"로컬 벡터가 없는 청크 {len(missing)}건(임베딩 호출 필요 → 중단)")
    sql = _insert_sql()
    for i in range(0, len(todo), batch_rows):
        cur.executemany(sql, [pg_row(c, vec_literal(mat[idx[text_hash(c["text"])]])) for c in todo[i : i + batch_rows]])
    post_corpus = count(cur, "corpus_chunks")
    expect_eq("corpus 사후 COUNT", post_corpus, EXPECT["corpus_after"])

    ek = sources[loaders.ELDERLY_KIDS_CSV_NAME]
    expect_eq("elderly_kids 정규화 행 수", len(ek.records), EXPECT["new_caution"])
    cols = loaders.TABLE_COLUMNS["caution"]
    csql = f"INSERT INTO caution ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT (row_key) DO NOTHING"  # noqa: S608
    cur.executemany(csql, [tuple(r[c] for c in cols) for r in ek.records.values()])
    post_caution = count(cur, "caution")
    expect_eq("caution 사후 COUNT", post_caution, EXPECT["caution_after"])
    expect_eq("elderly_kids kind 행 수", int(one(cur, "SELECT COUNT(*) FROM caution WHERE kind = 'elderly_kids'")), EXPECT["new_caution"])

    combo = sources[loaders.COMBO_JSON_NAME]
    expect_eq("병용 고유 행 수", len(combo.records), EXPECT["contra_pair"])
    for name, c in sources.items():
        st = c.stats
        cur.execute(
            "INSERT INTO load_log (source_file, table_name, raw_rows, loaded_rows, as_of) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (source_file) DO UPDATE SET table_name = excluded.table_name, raw_rows = excluded.raw_rows, "
            "loaded_rows = excluded.loaded_rows, as_of = excluded.as_of",
            (name, st.table, st.raw_rows, st.unique_rows, st.as_of))
    return {"corpus": [pre_corpus, post_corpus], "caution": [pre_caution, post_caution], "load_log": [pre_log, count(cur, "load_log")],
            "load_log_upserts": sorted(sources)}


# --------------------------------------------------------------------------- 백업(단계 3 전)

def backup(conn: Any, path: Path, expect_pair: int, expect_corpus: int) -> dict[str, Any]:
    """바뀔 값의 옛 값을 로컬에 저장한다. 행 수가 COUNT와 다르면 StageAbort. 되돌림은 이 파일의 값으로 UPDATE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    n = {"contra_pair": 0, "corpus_chunks": 0}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        cur.execute("SELECT row_key, as_of FROM contra_pair ORDER BY row_key")
        for r in cur.fetchall():
            f.write(json.dumps({"t": "contra_pair", "row_key": r[0], "as_of": iso(r[1])}) + "\n")
            n["contra_pair"] += 1
        cur.execute("SELECT chunk_id, base_date, year, source_file, effective_date FROM corpus_chunks ORDER BY chunk_id")
        for r in cur.fetchall():
            f.write(json.dumps({"t": "corpus_chunks", "chunk_id": r[0], "base_date": iso(r[1]), "year": r[2], "source_file": r[3],
                                "effective_date": iso(r[4])}, ensure_ascii=False) + "\n")
            n["corpus_chunks"] += 1
    conn.rollback()  # 읽기 트랜잭션 종료
    expect_eq("백업 contra_pair 행 수", n["contra_pair"], expect_pair)
    expect_eq("백업 corpus_chunks 행 수", n["corpus_chunks"], expect_corpus)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        expect_eq("백업 파일 줄 수", sum(1 for _ in f), expect_pair + expect_corpus)
    return {"path": str(path), "rows": n, "bytes": path.stat().st_size}


# --------------------------------------------------------------------------- 단계 3

def stage3_contra(cur: Any) -> dict[str, Any]:
    pre_old = int(one(cur, "SELECT COUNT(*) FROM contra_pair WHERE as_of = %s AND source = %s", (OLD_DATE, loaders.SRC_KIDS)))
    expect_eq("contra_pair 변경 대상(사전)", pre_old, EXPECT["contra_pair"])
    total = count(cur, "contra_pair")
    cur.execute("UPDATE contra_pair SET as_of = %s WHERE as_of = %s AND source = %s", (NEW_DATE, OLD_DATE, loaders.SRC_KIDS))
    updated = cur.rowcount
    expect_eq("contra_pair UPDATE 행 수", updated, EXPECT["contra_pair"])
    cur.execute("SELECT as_of::text, COUNT(*) FROM contra_pair GROUP BY 1")
    dist = {r[0]: int(r[1]) for r in cur.fetchall()}
    expect_eq("contra_pair as_of 분포(사후)", dist, {NEW_DATE: EXPECT["contra_pair"]})
    expect_eq("contra_pair 총 행 수", count(cur, "contra_pair"), total)
    return {"updated": updated, "as_of_distribution": dist}


def read_meta(cur: Any) -> dict[str, tuple[int | None, str, str | None]]:
    cur.execute("SELECT chunk_id, year, source_file, effective_date FROM corpus_chunks")
    return {r[0]: (r[1], r[2] or "", iso(r[3])) for r in cur.fetchall()}


def stage3_corpus(cur: Any, local_meta: dict[str, tuple[int | None, str, str | None]], batch: int = UPDATE_BATCH) -> dict[str, Any]:
    total = count(cur, "corpus_chunks")
    pre_combo = int(one(cur, "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_kind = 'l2_combo' AND base_date = %s", (OLD_DATE,)))
    expect_eq("l2_combo 변경 대상(사전)", pre_combo, EXPECT["combo_chunks"])
    cur.execute("SELECT chunk_id, base_date FROM corpus_chunks")
    base_before = {r[0]: iso(r[1]) for r in cur.fetchall()}
    meta_before = read_meta(cur)
    # ② base_date
    cur.execute("UPDATE corpus_chunks SET base_date = %s WHERE chunk_kind = 'l2_combo' AND base_date = %s", (NEW_DATE, OLD_DATE))
    expect_eq("l2_combo UPDATE 행 수", cur.rowcount, EXPECT["combo_chunks"])
    # ③ 메타: 로컬에 값이 있고 원격 값과 다른 청크만(chunk_id 일치)
    todo = [(cid, t) for cid, t in local_meta.items() if cid in meta_before and meta_before[cid] != t]
    sql = ("UPDATE corpus_chunks SET year = %s, source_file = %s, effective_date = %s WHERE chunk_id = %s")
    for i in range(0, len(todo), batch):
        cur.executemany(sql, [(t[0], t[1], t[2], cid) for cid, t in todo[i : i + batch]])
    meta_after = read_meta(cur)
    expect_eq("청크 총 행 수", count(cur, "corpus_chunks"), total)
    bad = [cid for cid, t in local_meta.items() if cid in meta_after and meta_after[cid] != t]
    expect_eq("메타 불일치(사후)", len(bad), 0)
    touched = {cid for cid, _ in todo}
    stray = [cid for cid, t in meta_after.items() if cid not in touched and t != meta_before.get(cid)]
    expect_eq("대상 밖 메타 변경", len(stray), 0)
    cur.execute("SELECT chunk_id, base_date FROM corpus_chunks")
    base_after = {r[0]: iso(r[1]) for r in cur.fetchall()}
    changed_base = {cid for cid in base_after if base_after[cid] != base_before[cid]}
    expect_eq("base_date 변경 행 수", len(changed_base), EXPECT["combo_chunks"])
    dist = Counter(base_after.values())
    return {"base_date_updated": len(changed_base), "meta_updated": len(todo),
            "meta_by_source_file": dict(Counter(t[1] or "(빈 문자열)" for _, t in todo)),
            "meta_unmatched_local": sum(1 for cid in local_meta if cid not in meta_before),
            "base_date_distribution": dict(sorted(dist.items()))}


# --------------------------------------------------------------------------- plan / apply / verify

def do_plan(conn: Any, chunks: list[dict[str, Any]], sources: dict[str, Any], log: Callable[[str], None] = print) -> dict[str, Any]:
    cur = conn.cursor()
    st = state(cur)
    conn.rollback()
    have_n = st["corpus"]
    meta = meta_map(chunks)
    log("== 사전 상태(원격, 읽기 전용) ==")
    log(json.dumps(st, ensure_ascii=False, default=str, indent=1))
    log("== 적용할 SQL ==")
    for s in STAGE1_SQL:
        log("  [1] " + s)
    log("  [2] INSERT corpus_chunks … ON CONFLICT (chunk_id) DO NOTHING (l2_elderly), INSERT caution … ON CONFLICT (row_key) DO NOTHING, load_log UPSERT 2건")
    log(
        f"  [3] UPDATE contra_pair SET as_of='{NEW_DATE}' WHERE as_of='{OLD_DATE}' AND source=KIDS; "  # noqa: S608 - 출력용
        f"UPDATE corpus_chunks SET base_date='{NEW_DATE}' WHERE chunk_kind='l2_combo' AND base_date='{OLD_DATE}'; "
        "UPDATE corpus_chunks SET year,source_file,effective_date WHERE chunk_id=…(로컬 값이 있고 다른 것만)")
    log("== 예상 변경 ==")
    ek = sources[loaders.ELDERLY_KIDS_CSV_NAME]
    combo = sources[loaders.COMBO_JSON_NAME]
    summary = {
        "stage1_done": stage1_done(st), "stage2_done": stage2_done(st),
        "local_chunks": len(chunks), "local_meta_chunks": len(meta), "elderly_kids_rows": len(ek.records),
        "combo_unique": len(combo.records), "corpus_now": have_n,
        "expected": EXPECT,
    }
    log(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def do_apply(conn: Any, chunks: list[dict[str, Any]], vectors: Any, sources: dict[str, Any], backup_path: Path,
             log: Callable[[str], None] = print) -> dict[str, Any]:
    report: dict[str, Any] = {}
    st = state(conn.cursor())
    conn.rollback()
    log(f"사전: {json.dumps({k: v for k, v in st.items() if k != 'caution_checks'}, ensure_ascii=False)}")
    if stage1_done(st):
        log("[단계 1] 이미 적용됨, 건너뜀")
    else:
        report["stage1"] = transaction(conn, "단계 1", stage1, log)
    st = state(conn.cursor())
    conn.rollback()
    if stage2_done(st):
        log("[단계 2] 이미 적용됨, 건너뜀")
    else:
        report["stage2"] = transaction(conn, "단계 2", lambda c: stage2(c, chunks, vectors, sources), log)
    report["backup"] = backup(conn, backup_path, EXPECT["contra_pair"], EXPECT["corpus_after"])
    log(f"[백업] {report['backup']}")
    st = state(conn.cursor())
    conn.rollback()
    if st["contra_as_of"] == {OLD_DATE: EXPECT["contra_pair"]}:
        report["stage3_contra"] = transaction(conn, "단계 3① contra_pair", stage3_contra, log)
    else:
        log(f"[단계 3①] 건너뜀(as_of 분포 {st['contra_as_of']})")
    meta = meta_map(chunks)
    report["stage3_corpus"] = transaction(conn, "단계 3②③ corpus_chunks", lambda c: stage3_corpus(c, meta), log)
    final = state(conn.cursor())
    conn.rollback()
    report["final"] = final
    return report


def hybrid_search(cur: Any, qvec: list[float], keyword: str, k: int = 8) -> list[tuple[str, str, float]]:
    """스모크용 하이브리드: 벡터 상위 k + 키워드(text ILIKE) 상위 k를 RRF(상수 60)로 합친다."""
    lit = "[" + ",".join(f"{x:.8g}" for x in qvec) + "]"
    cur.execute("SELECT chunk_id, chunk_kind FROM corpus_chunks ORDER BY embedding <=> %s::vector LIMIT %s", (lit, k))
    vec = [(r[0], r[1]) for r in cur.fetchall()]
    cur.execute("SELECT chunk_id, chunk_kind FROM corpus_chunks WHERE text ILIKE %s LIMIT %s", (f"%{keyword}%", k))
    kw = [(r[0], r[1]) for r in cur.fetchall()]
    score: dict[tuple[str, str], float] = {}
    for lst in (vec, kw):
        for rank, key in enumerate(lst):
            score[key] = score.get(key, 0.0) + 1.0 / (60 + rank + 1)
    return [(a, b, s) for (a, b), s in sorted(score.items(), key=lambda x: -x[1])]


def do_verify(conn: Any, embed: Callable[[str], list[float]] | None, log: Callable[[str], None] = print) -> dict[str, Any]:
    cur = conn.cursor()
    st = state(cur)
    out: dict[str, Any] = {"state": st}
    cur.execute("SELECT chunk_kind, COUNT(*) FROM corpus_chunks GROUP BY 1 ORDER BY 1")
    out["chunks_by_kind"] = {r[0]: int(r[1]) for r in cur.fetchall()}
    cur.execute("SELECT chunk_id, locator, base_date::text, year, source_file, left(text, 80) FROM corpus_chunks WHERE chunk_kind = 'l2_elderly' LIMIT 1")
    out["l2_elderly_sample"] = cur.fetchone()
    out["l2_elderly_embedding_null"] = int(one(cur, "SELECT COUNT(*) FROM corpus_chunks WHERE chunk_kind = 'l2_elderly' AND embedding IS NULL"))
    cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", (HNSW_INDEX,))
    row = cur.fetchone()
    out["hnsw"] = {"exists": bool(row), "def": row[0] if row else None, "mb": round(st["hnsw_bytes"] / 1048576, 1)}
    out["table_mb"] = round(int(one(cur, "SELECT pg_total_relation_size('corpus_chunks')")) / 1048576, 1)
    out["db_mb"] = round(int(one(cur, "SELECT pg_database_size(current_database())")) / 1048576, 1)
    out["search"] = []
    if embed:
        for q, kw in (("노인에게 주의가 필요한 약 성분", "노인"), ("고령자 복용 시 주의 약물 목록", "노인주의")):
            res = hybrid_search(cur, embed(q), kw)
            out["search"].append({"query": q, "top": res[:5], "has_l2_elderly": any(k == "l2_elderly" for _, k, _ in res)})
    conn.rollback()
    log(json.dumps(out, ensure_ascii=False, default=str, indent=1))
    return out


def make_embedder() -> Callable[[str], list[float]]:
    import numpy as np  # noqa: PLC0415
    from embed_compare import decode_b64_vectors, resolve_key  # noqa: PLC0415
    from embed_corpus import MODEL_ID, http_embed  # noqa: PLC0415

    key = resolve_key()
    if not key:
        raise RemoteLoadRefused("OPENAI_API_KEY를 찾지 못했다")
    calls = {"n": 0}

    def embed(text: str) -> list[float]:
        calls["n"] += 1
        if calls["n"] > 3:
            raise RemoteLoadRefused("질의 임베딩 호출 상한(3회) 초과")
        resp = http_embed(MODEL_ID, [text], key)
        return np.frombuffer(decode_b64_vectors(resp["data"]), dtype="<f4").astype(float).tolist()

    return embed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="plan", choices=("plan", "apply", "verify"))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "verify":
            conn = connect(read_only=True)
            try:
                do_verify(conn, make_embedder())
            finally:
                conn.close()
            return 0
        chunks = local_chunks()
        sources = collect_sources()
        if args.cmd == "plan":
            conn = connect(read_only=True)
            try:
                do_plan(conn, chunks, sources)
            finally:
                conn.close()
            return 0
        if not args.yes:
            print("거부: apply는 --yes가 필요하다", file=sys.stderr)
            return 2
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        conn = connect(read_only=False)
        try:
            t0 = time.time()
            rep = do_apply(conn, chunks, load_vectors(), sources, REPO / "data" / "mock" / "backup" / f"be16_before_update_{stamp}.jsonl.gz")
            print(json.dumps({"done": True, "seconds": round(time.time() - t0, 1), "final": rep["final"]}, ensure_ascii=False, default=str))
        finally:
            conn.close()
        return 0
    except (RemoteLoadRefused, StageAbort) as e:
        print(f"중단: {redact(str(e))}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    install_excepthook()  # S-05: 처리되지 않은 예외·logging 출력에서 DSN·키 가리기(가져오기만 할 때는 설치하지 않음)
    raise SystemExit(main())
