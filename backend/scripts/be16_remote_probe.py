"""BE-16 원격 읽기 점검(읽기 전용, 사용자 승인 2026-11-17 Recap 22 아래 메인이 실행).

be16-worker 보고 "메인이 사용자 승인 뒤 돌릴 원격 읽기 명령" 1~4와 RFP-04 연도 칸 확인을 한 번에 한다.

  1 설정       hnsw.ef_search·iterative_scan·max_scan_tuples, pgvector 버전
  2 무필터     ef_search 40, EXPLAIN (ANALYZE, BUFFERS) 벡터 top-10
  3 강한 필터  ef_search 100, ingr_codes && + layer L2, iterative_scan off / relaxed_order 비교
  4 반복       3의 강한 필터 질의를 --repeat N회, --interval S초 간격(기본 3회·300초) + pg_stat_user_tables
  RFP-04       corpus_chunks.year 열 존재·타입, layer·kind별 year NULL 수, base_date 앞 4자리 분포

안전:
- 블록마다 `BEGIN READ ONLY` → `SET LOCAL statement_timeout = '30s'` → `transaction_read_only = on` 확인 → … → `ROLLBACK`.
  세션 전역 `SET`·쓰기·ANALYZE는 하지 않는다. 실행하는 모든 문장은 허용 접두(BEGIN READ ONLY/SET LOCAL/SHOW/SELECT/EXPLAIN/ROLLBACK)
  검사를 거친다(`guard_sql`).
- 반복 대기 중에는 트랜잭션을 열어 두지 않는다(블록마다 열고 닫는다).
- 표본 chunk_id·성분코드는 원격 SELECT로 고르고 값만 출력한다. 본문·벡터·접속 문자열은 출력·저장하지 않는다(문자열은 redact).

사용(backend 디렉터리, 원격 접속이 일어나므로 승인 뒤에만):
  .venv/bin/python scripts/be16_remote_probe.py [--repeat 3 --interval 300] [--chunk-id l3p-…] [--ingr-code …]
결과: `<repo-root>/logs/remote/be16_probe_<UTC 시각>.json`(요약만), 화면에는 짧은 줄.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from load_corpus import RemoteLoadRefused, resolve_dsn  # noqa: E402

from app.security.redact import install_excepthook, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"
HNSW_INDEX = "idx_corpus_embedding_hnsw"
STATEMENT_TIMEOUT = "30s"
EF_GLOBAL = 40
EF_STRONG = 100
LIMIT = 10
STRONG_LAYER = "L2"
# 성분코드 표본: 강한 필터 결과가 LIMIT 근처라 iterative_scan 보충 효과가 드러나는 범위(없으면 최다 빈도 코드)
INGR_RANGE = (10, 50)

_ALLOWED = re.compile(r"^\s*(BEGIN READ ONLY|SET LOCAL |SHOW |SELECT |EXPLAIN |ROLLBACK)", re.IGNORECASE)
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE|CREATE|REINDEX|VACUUM|ANALYZE\s+\w|GRANT|COPY)\b", re.IGNORECASE)
# SELECT로 부를 수 있는 부작용 함수(세션 종료·설정 변경·외부 연결·잠금). 읽기 전용 트랜잭션에서도 일부는 동작한다.
_FORBIDDEN_FUNCS = re.compile(r"\b(pg_terminate\w*|pg_cancel_backend|set_config|dblink\w*|pg_advisory\w*)\s*\(", re.IGNORECASE)


class ProbeRefused(RuntimeError):
    """읽기 전용 조건이 깨짐(쓰기 문장 시도, read-only 아님) → 즉시 중단."""


def guard_sql(sql: str) -> str:
    """허용 접두만 통과. `EXPLAIN (ANALYZE, …)`의 ANALYZE 옵션은 허용하고 `ANALYZE 표` 명령은 막는다.

    이 허용·금지 목록은 실수를 일찍 잡는 **보조 장치**일 뿐이다(정규식은 SQL을 완전히 해석하지 못한다).
    읽기 전용의 실제 보장은 ① 블록마다 `BEGIN READ ONLY`로 열고 ② `SHOW transaction_read_only`가 on인지
    확인한 뒤 ③ 끝에서 예외와 상관없이 `ROLLBACK`하는 것이다(`Session.read_only`). 부작용 함수
    (`pg_terminate_backend`·`set_config`·`dblink`·`pg_advisory_lock` 등)는 SELECT로도 부를 수 있어 따로 막는다.
    """
    if not _ALLOWED.match(sql):
        raise ProbeRefused(f"허용되지 않은 문장: {sql.split()[0] if sql.split() else ''}")
    body = re.sub(r"^\s*EXPLAIN\s*\([^)]*\)", "", sql, flags=re.IGNORECASE)
    if _FORBIDDEN.search(body):
        raise ProbeRefused("쓰기·관리 키워드가 든 문장")
    if _FORBIDDEN_FUNCS.search(body):
        raise ProbeRefused("부작용 함수가 든 문장")
    return sql


def connect(connect_fn: Callable[..., Any] | None = None) -> Any:
    """autocommit 연결(트랜잭션은 블록마다 `BEGIN READ ONLY`로 직접 연다). 접속 문자열은 출력하지 않는다."""
    dsn = resolve_dsn(DSN_ENV)
    if not dsn:
        raise RemoteLoadRefused(f"{DSN_ENV} 값을 찾지 못했다")
    if connect_fn is None:
        import psycopg  # noqa: PLC0415

        connect_fn = psycopg.connect
    return connect_fn(dsn, autocommit=True)


class Session:
    """검사된 문장만 실행하는 얇은 감싸개. 실행한 문장 목록(`executed`)은 시험·로그용."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.cur = conn.cursor()
        self.executed: list[str] = []

    def run(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        guard_sql(sql)
        self.executed.append(sql)
        self.cur.execute(sql, params)
        if sql.lstrip().upper().startswith(("BEGIN", "SET LOCAL", "ROLLBACK")):
            return []
        return list(self.cur.fetchall())

    def one(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        rows = self.run(sql, params)
        return rows[0][0] if rows else None

    @contextmanager
    def read_only(self, timeout: str = STATEMENT_TIMEOUT) -> Iterator[Session]:
        """BEGIN READ ONLY … ROLLBACK. 예외가 나도 ROLLBACK은 반드시 보낸다."""
        self.run("BEGIN READ ONLY")
        try:
            self.run(f"SET LOCAL statement_timeout = '{timeout}'")
            if str(self.one("SHOW transaction_read_only")).lower() != "on":
                raise ProbeRefused("transaction_read_only가 on이 아님")
            yield self
        finally:
            self.run("ROLLBACK")


# --------------------------------------------------------------------------- EXPLAIN 요약

def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for ch in node.get("Plans", []) or []:
        yield from _walk(ch)


def summarize_explain(raw: Any) -> dict[str, Any]:
    """EXPLAIN (FORMAT JSON) 결과 → 계획 첫 줄·인덱스 이름·반환 행·Execution Time·Buffers(상위 노드 누적)."""
    doc = json.loads(raw) if isinstance(raw, str) else raw
    top = doc[0] if isinstance(doc, list) else doc
    plan = top["Plan"]
    nodes = list(_walk(plan))
    first = plan.get("Node Type", "")
    if plan.get("Index Name"):
        first += f" using {plan['Index Name']}"
    return {
        "plan_first": first,
        "node_types": [n.get("Node Type") for n in nodes],
        "indexes": sorted({n["Index Name"] for n in nodes if n.get("Index Name")}),
        "rows": plan.get("Actual Rows"),
        "execution_ms": top.get("Execution Time"),
        "planning_ms": top.get("Planning Time"),
        "shared_hit": plan.get("Shared Hit Blocks"),
        "shared_read": plan.get("Shared Read Blocks"),
        "uses_hnsw": any(n.get("Index Name") == HNSW_INDEX for n in nodes),
    }


def explain(s: Session, sql: str, params: Sequence[Any]) -> dict[str, Any]:
    return summarize_explain(s.one(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params))


VEC_SQL = ("SELECT chunk_id FROM corpus_chunks WHERE embedding IS NOT NULL{extra} "
           "ORDER BY embedding <=> (SELECT embedding FROM corpus_chunks WHERE chunk_id = %s) LIMIT {limit}")
STRONG_EXTRA = " AND ingr_codes && ARRAY[%s]::text[] AND layer = ANY(ARRAY[%s]::text[])"


def strong_sql() -> str:
    return VEC_SQL.format(extra=STRONG_EXTRA, limit=LIMIT)


def strong_params(chunk_id: str, code: str) -> tuple[Any, ...]:
    return (code, STRONG_LAYER, chunk_id)


# --------------------------------------------------------------------------- 블록

def settings(s: Session) -> dict[str, Any]:
    out = {k: s.one("SELECT current_setting(%s, true)", (f"hnsw.{k}",)) for k in ("ef_search", "iterative_scan", "max_scan_tuples")}
    out["vector_version"] = s.one("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    out["expected"] = {"ef_search": "40", "iterative_scan": "off", "max_scan_tuples": "20000", "vector_version": "0.8.2"}
    return out


def pick_chunk(s: Session) -> str | None:
    return s.one("SELECT chunk_id FROM corpus_chunks WHERE chunk_id LIKE 'l3p-%' AND embedding IS NOT NULL ORDER BY chunk_id LIMIT 1")


def pick_code(s: Session) -> tuple[str | None, int | None]:
    lo, hi = INGR_RANGE
    base = ("SELECT u.c, COUNT(*) AS n FROM corpus_chunks, unnest(ingr_codes) AS u(c) "
            "WHERE layer = %s AND embedding IS NOT NULL GROUP BY u.c ")
    rows = s.run(base + "HAVING COUNT(*) BETWEEN %s AND %s ORDER BY n DESC, u.c LIMIT 1", (STRONG_LAYER, lo, hi))
    if not rows:
        rows = s.run(base + "ORDER BY n DESC, u.c LIMIT 1", (STRONG_LAYER,))
    return (rows[0][0], int(rows[0][1])) if rows else (None, None)


def unfiltered(s: Session, chunk_id: str) -> dict[str, Any]:
    s.run(f"SET LOCAL hnsw.ef_search = {EF_GLOBAL}")
    return {"ef_search": EF_GLOBAL, **explain(s, VEC_SQL.format(extra="", limit=LIMIT), (chunk_id,))}


def strong(s: Session, chunk_id: str, code: str, iterative: str | None) -> dict[str, Any]:
    s.run(f"SET LOCAL hnsw.ef_search = {EF_STRONG}")
    if iterative is not None:
        if iterative not in ("off", "relaxed_order", "strict_order"):
            raise ProbeRefused("iterative_scan 값 이상")
        s.run(f"SET LOCAL hnsw.iterative_scan = {iterative}")
    res = explain(s, strong_sql(), strong_params(chunk_id, code))
    res.update({"ef_search": EF_STRONG, "iterative_scan": iterative or "(기본)", "fills_limit": res["rows"] == LIMIT})
    return res


def table_stats(s: Session) -> dict[str, Any]:
    rows = s.run("SELECT n_live_tup, n_dead_tup, last_analyze::text, last_autoanalyze::text, last_vacuum::text, last_autovacuum::text "
                 "FROM pg_stat_user_tables WHERE relname = 'corpus_chunks'")
    if not rows:
        return {}
    keys = ("n_live_tup", "n_dead_tup", "last_analyze", "last_autoanalyze", "last_vacuum", "last_autovacuum")
    return dict(zip(keys, rows[0], strict=True))


def rfp04_year(s: Session) -> dict[str, Any]:
    cols = dict(s.run("SELECT column_name, data_type FROM information_schema.columns "
                      "WHERE table_schema = 'public' AND table_name = 'corpus_chunks' AND column_name IN ('year', 'base_date')"))
    out: dict[str, Any] = {"year_column": cols.get("year"), "base_date_type": cols.get("base_date")}
    if "year" not in cols:
        return out
    rows = s.run("SELECT layer, chunk_kind, COUNT(*), COUNT(*) FILTER (WHERE year IS NULL) FROM corpus_chunks GROUP BY 1, 2 ORDER BY 1, 2")
    out["by_kind"] = [{"layer": r[0], "chunk_kind": r[1], "n": int(r[2]), "year_null": int(r[3])} for r in rows]
    out["year_null_total"] = sum(r["year_null"] for r in out["by_kind"])
    out["base_date_year"] = {r[0]: int(r[1]) for r in s.run("SELECT left(base_date::text, 4), COUNT(*) FROM corpus_chunks GROUP BY 1 ORDER BY 1")}
    out["year_null_base_date_year"] = {
        r[0]: int(r[1]) for r in s.run("SELECT left(base_date::text, 4), COUNT(*) FROM corpus_chunks WHERE year IS NULL GROUP BY 1 ORDER BY 1")}
    return out


def guarded(name: str, fn: Callable[[], dict[str, Any]], log: Callable[[str], None]) -> dict[str, Any]:
    """블록 하나의 실패(시간 초과 등)는 기록하고 다음 블록으로 간다. ProbeRefused는 그대로 올린다."""
    try:
        return fn()
    except ProbeRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - 원격 오류 종류·요약만 남긴다
        msg = f"{type(exc).__name__}: {redact(str(exc))[:200]}"
        log(f"[{name}] 오류 {msg}")
        return {"error": msg}


def run_probe(conn: Any, repeat: int, interval: float, chunk_id: str | None = None, code: str | None = None,
              log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    s = Session(conn)
    rep: dict[str, Any] = {"started_utc": datetime.now(UTC).isoformat(timespec="seconds")}

    def blk(fn: Callable[[Session], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
        def inner() -> dict[str, Any]:
            with s.read_only() as ss:
                return fn(ss)
        return inner

    rep["1_settings"] = guarded("1", blk(settings), log)
    log(f"[1] {json.dumps(rep['1_settings'], ensure_ascii=False)}")

    def pick(ss: Session) -> dict[str, Any]:
        cid = chunk_id or pick_chunk(ss)
        c, n = (code, None) if code else pick_code(ss)
        return {"chunk_id": cid, "ingr_code": c, "ingr_code_l2_chunks": n}

    rep["sample"] = guarded("표본", blk(pick), log)
    log(f"[표본] {json.dumps(rep['sample'], ensure_ascii=False)}")
    cid, c = rep["sample"].get("chunk_id"), rep["sample"].get("ingr_code")
    if cid:
        rep["2_unfiltered"] = guarded("2", blk(lambda ss: unfiltered(ss, cid)), log)
        log(f"[2] {_short(rep['2_unfiltered'])}")
    if cid and c:
        rep["3_strong"] = {it: guarded(f"3 {it}", blk(lambda ss, it=it: strong(ss, cid, c, it)), log) for it in ("off", "relaxed_order")}
        for it, r in rep["3_strong"].items():
            log(f"[3 {it}] {_short(r)}")
        rep["4_repeat"] = []
        for i in range(repeat):
            if i:
                sleep(interval)
            r = guarded(f"4 #{i + 1}", blk(lambda ss: {"at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                                                         **strong(ss, cid, c, None), "table": table_stats(ss)}), log)
            rep["4_repeat"].append(r)
            log(f"[4 #{i + 1}] {_short(r)}")
    rep["rfp04_year"] = guarded("RFP-04", blk(rfp04_year), log)
    y = rep["rfp04_year"]
    log(f"[RFP-04] year 열 {y.get('year_column')}, NULL 합계 {y.get('year_null_total')}, base_date 연도 {y.get('base_date_year')}")
    rep["statements"] = len(s.executed)
    rep["finished_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    return rep


def _short(r: dict[str, Any]) -> str:
    if "error" in r:
        return r["error"]
    return (f"{r.get('plan_first')} rows={r.get('rows')} exec={r.get('execution_ms')}ms "
            f"hit={r.get('shared_hit')} read={r.get('shared_read')} hnsw={r.get('uses_hnsw')}")


def save(rep: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"be16_probe_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(redact(json.dumps(rep, ensure_ascii=False, indent=1, default=str)), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repeat", type=int, default=3, help="명령 4 반복 횟수(기본 3)")
    ap.add_argument("--interval", type=float, default=300.0, help="명령 4 반복 간격 초(기본 300)")
    ap.add_argument("--chunk-id", help="표본 chunk_id 직접 지정(없으면 원격에서 고른다)")
    ap.add_argument("--ingr-code", help="강한 필터 성분코드 직접 지정")
    ap.add_argument("--repo-root", type=Path, default=REPO, help="logs/remote를 둘 저장소 루트(기본: 이 스크립트의 저장소)")
    return ap


def main(argv: Sequence[str] | None = None, connect_fn: Callable[..., Any] | None = None,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = build_parser().parse_args(argv)
    if args.repeat < 1 or args.interval < 0:
        print("거부: --repeat ≥ 1, --interval ≥ 0", file=sys.stderr)
        return 2
    try:
        conn = connect(connect_fn)
        try:
            rep = run_probe(conn, args.repeat, args.interval, args.chunk_id, args.ingr_code, sleep=sleep)
        finally:
            conn.close()
    except (RemoteLoadRefused, ProbeRefused) as e:
        print(f"중단: {redact(str(e))}", file=sys.stderr)
        return 3
    print(f"저장: {save(rep, args.repo_root / 'logs' / 'remote')}")
    return 0


if __name__ == "__main__":
    install_excepthook()
    raise SystemExit(main())
