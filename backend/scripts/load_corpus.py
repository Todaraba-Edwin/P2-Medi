"""BE-05 근거 코퍼스 적재 스크립트(이번 단계: 드라이런·로컬 SQLite까지. 원격 적재와 임베딩 호출은 하지 않는다).

기본은 `--dry-run`(건수·용량 어림만 출력, 아무것도 쓰지 않음)이다.
  --sqlite OUT.db        로컬 SQLite에 텍스트·메타를 적재한다(임베딩 열 없음, 재실행해도 중복 0: ON CONFLICT (chunk_id) DO NOTHING)
  --print-sql [--hnsw]   `app/db/schema_corpus.sql`을 `--dim` 차원으로 채워 출력한다(`--hnsw`는 인덱스 단계만)
  --embed-plan           임베딩 호출 계획(텍스트 수·토큰 근사·어림 비용)만 출력한다. 실호출은 BE-05-03 답 뒤 별도
  --dsn-env 변수이름 --yes   원격 Postgres 적재(BE-05-03 D 이행 뒤). `--yes` 없이는 거부한다. 접속 문자열은 환경변수 또는 앱 Settings(.env)에서
                         프로세스 안에서만 읽고 출력하지 않는다. embeddings/vectors.npy가 있으면 함께 적재한다. 재실행해도 중복 0.
  --dsn-env 변수이름 --drop --yes  롤백(corpus_chunks만 삭제). 사용자가 지시했을 때만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from build_corpus_l2 import CHUNKS_PATH, EXTRA_FIELDS, OUT_DIR, read_chunks  # noqa: E402
from build_corpus_l2 import FIELDS as BASE_FIELDS  # noqa: E402

FIELDS = BASE_FIELDS + EXTRA_FIELDS  # L3 선택 열(L2 청크에는 없으므로 빈 문자열)
ALL_FILES = ("l2_chunks.jsonl", "l3_eyak.jsonl", "l3_prmsn.jsonl", "l1_notice.jsonl")

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "app" / "db" / "schema_corpus.sql"
HNSW_MARK = "-- @@HNSW@@"
JSON_COLS = ("refs", "ingr_codes", "ingr_names")  # SQLite에서는 JSON 문자열로 저장
EMBED_PRICE_PER_M = 0.02  # text-embedding-3-small, USD/1M 토큰(BE-05-01 시험 실측 단가: 4,165,749토큰 $0.0833)
TOKENS_PER_CHAR = 1.7  # 한글 보수적 근사(chunk_trial과 같음)
ROW_OVERHEAD = 300
HNSW_FACTOR = 1.3  # 추정(실측 아님)


# --------------------------------------------------------------------------- SQL 렌더링

def render_sql(dim: int = 1536, hnsw: bool = False) -> str:
    if dim not in (512, 1536):
        raise ValueError("차원은 512 또는 1536")
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    base, _, idx = raw.partition(HNSW_MARK)
    part = (HNSW_MARK + idx) if hnsw else base
    return part.replace("{{DIM}}", str(dim))


def sqlite_ddl() -> list[str]:
    cols = ", ".join(f"{f} TEXT" + (" PRIMARY KEY" if f == "chunk_id" else "") for f in FIELDS)
    return [
        f"CREATE TABLE IF NOT EXISTS corpus_chunks ({cols})",
        "CREATE INDEX IF NOT EXISTS idx_corpus_pair_id ON corpus_chunks (pair_id)",
        "CREATE INDEX IF NOT EXISTS idx_corpus_parent_id ON corpus_chunks (parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_corpus_layer_kind ON corpus_chunks (layer, chunk_kind)",
    ]


def sqlite_row(c: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(json.dumps(c[f], ensure_ascii=False) if f in JSON_COLS else c.get(f, "") for f in FIELDS)


# --------------------------------------------------------------------------- 로컬 SQLite 적재(멱등)

def load_sqlite(chunks: Iterable[dict[str, Any]], path: str | Path) -> dict[str, int]:
    conn = sqlite3.connect(str(path))
    try:
        for ddl in sqlite_ddl():
            conn.execute(ddl)
        before = conn.execute("SELECT COUNT(*) FROM corpus_chunks").fetchone()[0]
        ph = ", ".join("?" for _ in FIELDS)
        # 열 이름은 코드 상수(FIELDS)이고 값은 바인딩한다.
        conn.executemany(f"INSERT INTO corpus_chunks ({', '.join(FIELDS)}) VALUES ({ph}) ON CONFLICT (chunk_id) DO NOTHING",  # noqa: S608
                         (sqlite_row(c) for c in chunks))
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM corpus_chunks").fetchone()[0]
    finally:
        conn.close()
    return {"before": before, "after": after, "inserted": after - before}


# --------------------------------------------------------------------------- 어림(드라이런)

def estimate(chunks: Sequence[dict[str, Any]], dim: int) -> dict[str, Any]:
    text_bytes = sum(len(c["text"].encode("utf-8")) for c in chunks)
    meta_bytes = sum(len(c["locator"].encode("utf-8")) + len(c["source_ref"].encode("utf-8")) + 120 for c in chunks)
    vec = 4 * dim + 8
    n = len(chunks)
    mb = 1024 * 1024
    return {
        "chunks": n, "dim": dim, "text_mb": round(text_bytes / mb, 2), "meta_mb": round(meta_bytes / mb, 2),
        "vector_mb": round(vec * n / mb, 1), "hnsw_mb(추정)": round(vec * n * HNSW_FACTOR / mb, 1),
        "row_overhead_mb(추정)": round(ROW_OVERHEAD * n / mb, 1),
        "total_mb(추정)": round((text_bytes + meta_bytes + (vec * (1 + HNSW_FACTOR) + ROW_OVERHEAD) * n) / mb, 1),
    }


def embed_plan(chunks: Sequence[dict[str, Any]], dim: int) -> dict[str, Any]:
    """임베딩 호출 계획만. 네트워크·API 키를 쓰지 않는다."""
    texts = {c["text"] for c in chunks}
    chars = sum(len(t) for t in texts)
    tokens = int(chars * TOKENS_PER_CHAR)
    batches, cur_n, cur_t = 0, 0, 0
    for t in sorted(texts):  # chunk_trial과 같은 배치 규칙(256개·6만 토큰 근사 이하)
        tk = int(min(len(t), 3000) * TOKENS_PER_CHAR)
        if cur_n and (cur_n >= 256 or cur_t + tk > 60_000):
            batches, cur_n, cur_t = batches + 1, 0, 0
        cur_n, cur_t = cur_n + 1, cur_t + tk
    batches += bool(cur_n)
    return {"chunks": len(chunks), "unique_texts": len(texts), "batches": batches, "approx_tokens": tokens, "approx_usd": round(tokens / 1e6 * EMBED_PRICE_PER_M, 4),
            "model": "text-embedding-3-small", "dimensions": dim, "executed": False,
            "note": "계획만 출력. 실호출은 BE-05-03 답 뒤 별도 지시서(비용 상한·원장 경유)"}


# --------------------------------------------------------------------------- 원격 적재(BE-05-03 D 이행, 2026-11-11)

class RemoteLoadRefused(RuntimeError):
    pass


BATCH_ROWS = 200  # 보수적 배치(행당 벡터 약 12KB). 배치마다 커밋해 중단 뒤 재개할 수 있다
PG_COLS = FIELDS + ("embedding",)
ARRAY_COLS = ("ingr_codes", "ingr_names")


def resolve_dsn(dsn_env: str) -> str:
    """환경변수 우선, 없으면 앱 Settings(.env)에서 프로세스 안에서만 읽는다. 값은 출력하지 않는다."""
    dsn = os.environ.get(dsn_env, "")
    if dsn:
        return dsn
    try:
        from pydantic_settings import SettingsConfigDict  # noqa: PLC0415

        from app.config import Settings  # noqa: PLC0415

        class _S(Settings):
            model_config = SettingsConfigDict(extra="ignore")

        root = Path(__file__).resolve().parents[2]
        val = getattr(_S(_env_file=(".env", str(root / ".env"))), dsn_env.lower(), None)
        return str(val) if val else ""
    except Exception as exc:  # noqa: BLE001 - 검증 오류 문구에 .env 값이 섞일 수 있어 종류만 알린다
        raise RemoteLoadRefused(f"설정(.env)을 읽지 못했다: {type(exc).__name__}") from None


def vec_literal(row: Any) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in row) + "]"


def pg_row(c: dict[str, Any], vec: str | None) -> tuple[Any, ...]:
    vals: list[Any] = []
    for f in FIELDS:
        v = c.get(f, "")
        if f == "refs":
            v = json.dumps(c.get(f) or [], ensure_ascii=False)
        elif f in ARRAY_COLS:
            v = list(c.get(f) or [])
        elif f in ("parent_id", "pair_id"):
            v = v or None
        vals.append(v)
    vals.append(vec)
    return tuple(vals)


def load_vectors(emb_dir: Path | None = None) -> tuple[Any, dict[str, int]] | None:
    import numpy as np  # noqa: PLC0415

    d = emb_dir or (OUT_DIR / "embeddings")
    if not (d / "vectors.npy").exists() or not (d / "index.json").exists():
        return None
    return np.load(d / "vectors.npy", mmap_mode="r"), json.loads((d / "index.json").read_text(encoding="utf-8"))["rows"]


def _insert_sql() -> str:
    ph = ", ".join("%s::jsonb" if f == "refs" else ("%s::vector" if f == "embedding" else "%s") for f in PG_COLS)
    return f"INSERT INTO corpus_chunks ({', '.join(PG_COLS)}) VALUES ({ph}) ON CONFLICT (chunk_id) DO NOTHING"  # noqa: S608


def remote_load(chunks: Sequence[dict[str, Any]], dsn_env: str, yes: bool, dim: int = 1536,
                connect: Callable[[str], Any] | None = None, vectors: tuple[Any, dict[str, int]] | None = None,
                batch_rows: int = BATCH_ROWS, log: Callable[[str], None] = print) -> dict[str, int]:
    """`--yes`와 접속 문자열이 있을 때만 접속한다. 접속 문자열은 출력·예외 문구에 쓰지 않는다.
    corpus_chunks 새 테이블만 만들고 쓴다(기존 판정 테이블은 건드리지 않는다). 이미 있는 chunk_id는 건너뛰므로(재개·재실행 중복 0) 안전하다."""
    from embed_corpus import text_hash  # noqa: PLC0415

    if not yes:
        raise RemoteLoadRefused("원격 적재는 --yes가 필요하다")
    dsn = resolve_dsn(dsn_env)
    if not dsn:
        raise RemoteLoadRefused(f"{dsn_env} 값을 찾지 못했다")
    if connect is None:
        import psycopg  # noqa: PLC0415 - 원격 적재 때만 필요(지연 import)

        connect = psycopg.connect
    conn = connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(render_sql(dim))
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM corpus_chunks")
        before = int(cur.fetchone()[0])
        cur.execute("SELECT chunk_id FROM corpus_chunks")
        have = {r[0] for r in cur.fetchall()}
        todo = [c for c in chunks if c["chunk_id"] not in have]
        sql = _insert_sql()
        mat, idx = vectors if vectors else (None, {})
        sent = 0
        for i in range(0, len(todo), batch_rows):
            part = todo[i : i + batch_rows]
            rows = []
            for c in part:
                r = idx.get(text_hash(c["text"])) if mat is not None else None
                rows.append(pg_row(c, vec_literal(mat[r]) if r is not None else None))
            cur.executemany(sql, rows)
            conn.commit()
            sent += len(part)
            if (i // batch_rows) % 50 == 0:
                log(f"  적재 {sent}/{len(todo)}")
        cur.execute("SELECT COUNT(*) FROM corpus_chunks")
        after = int(cur.fetchone()[0])
    finally:
        conn.close()
    return {"input": len(chunks), "skipped_existing": len(chunks) - len(todo), "sent": sent, "before": before, "after": after, "added": after - before}


def remote_drop(dsn_env: str, yes: bool, connect: Callable[[str], Any] | None = None) -> str:
    """롤백: corpus_chunks만 삭제한다. 사용자가 지시했을 때만 쓴다(--drop --yes). 판정 테이블은 건드리지 않는다."""
    if not yes:
        raise RemoteLoadRefused("--drop은 --yes가 필요하다")
    dsn = resolve_dsn(dsn_env)
    if not dsn:
        raise RemoteLoadRefused(f"{dsn_env} 값을 찾지 못했다")
    if connect is None:
        import psycopg  # noqa: PLC0415

        connect = psycopg.connect
    conn = connect(dsn)
    try:
        conn.cursor().execute("DROP TABLE IF EXISTS corpus_chunks")
        conn.commit()
    finally:
        conn.close()
    return "corpus_chunks 삭제"


# --------------------------------------------------------------------------- CLI

def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", type=Path, nargs="+", default=[CHUNKS_PATH])
    ap.add_argument("--all", action="store_true", help="L2+L3+L1 네 파일 전체(corpus/ 기준)를 입력으로")
    ap.add_argument("--selected", action="store_true", help="--all의 입력을 corpus/selected/ 라벨 선별본(L2는 corpus/ 그대로)으로")
    ap.add_argument("--dim", type=int, default=1536, choices=(512, 1536))
    ap.add_argument("--dry-run", action="store_true", help="기본 동작. 건수·용량 어림만 출력")
    ap.add_argument("--sqlite", type=Path, help="로컬 SQLite 출력 경로")
    ap.add_argument("--print-sql", action="store_true")
    ap.add_argument("--hnsw", action="store_true")
    ap.add_argument("--embed-plan", action="store_true")
    ap.add_argument("--dsn-env", help="원격 Postgres 접속 문자열이 든 환경변수 이름(값이 아님)")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--no-vectors", action="store_true", help="임베딩 없이 텍스트·메타만 적재")
    ap.add_argument("--again", action="store_true", help="재실행 중복 확인용(적재 전후 행 수를 함께 출력)")
    ap.add_argument("--drop", action="store_true", help="롤백: corpus_chunks만 삭제(사용자 지시 시에만, --yes 필요)")
    args = ap.parse_args(argv)

    if args.print_sql:
        print(render_sql(args.dim, args.hnsw))
        return 0
    paths = args.input
    if args.all:
        d = OUT_DIR / "selected" if args.selected else OUT_DIR
        paths = [OUT_DIR / ALL_FILES[0], *(d / n for n in ALL_FILES[1:])]
    if args.dsn_env and args.drop:
        try:
            print(remote_drop(args.dsn_env, args.yes))
        except RemoteLoadRefused as e:
            print(f"거부: {e}", file=sys.stderr)
            return 2
        return 0
    chunks = [c for p in paths for c in read_chunks(p)]
    if args.dsn_env:
        try:
            print(remote_load(chunks, args.dsn_env, args.yes, args.dim, vectors=None if args.no_vectors else load_vectors()))
        except RemoteLoadRefused as e:
            print(f"거부: {e}", file=sys.stderr)
            return 2
        return 0
    if args.sqlite:
        print(json.dumps(load_sqlite(chunks, args.sqlite), ensure_ascii=False))
        size = args.sqlite.stat().st_size
        print(f"SQLite 파일 {size / 1024 / 1024:.2f} MB")
        return 0
    if args.embed_plan:
        print(json.dumps(embed_plan(chunks, args.dim), ensure_ascii=False, indent=2))
        return 0
    print("[dry-run] 아무것도 쓰지 않음")
    for d in (1536, 512):
        print(json.dumps(estimate(chunks, d), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
