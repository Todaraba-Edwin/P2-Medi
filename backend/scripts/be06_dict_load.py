"""BE-06-24 B 제품·성분 사전 DB 적재(2026-11-17). `data/mock/dict/drug_dict.json` → `drug_dict_meta`·`drug_dict_entry`.

  plan             (기본, dry-run) 원격 연결 0. 로컬 사전 파일만 읽어 판(version)·행 수·sha256·바이트를 출력한다. 쓰기 0.
  plan --remote    읽기 전용 연결 1회. 원격에 테이블·같은 판이 있는지, 넣을 행 수(이미 있으면 0)를 출력한다. 쓰기 0.
  apply --yes      쓰기. `--yes`와 승인 파일 `data/mock/review/be06_dict_approved.flag`(사용자 승인 뒤 메인이 만든다)가 **둘 다** 있어야 한다.
                   한 트랜잭션: 스키마(IF NOT EXISTS) → entry 삽입(ON CONFLICT DO NOTHING) → 행 수 확인 → meta 삽입 → 커밋.
                   같은 판이 이미 완전히 있으면 0행(멱등). 같은 판에 다른 원본이 있으면 롤백하고 거부한다.
  verify           읽기 전용. 원격 최신 판을 읽어 `DrugDict`를 만들고 판·행 수·원본 sha256이 로컬 파일과 같은지 확인한다.
  --print-sql      `app/db/schema_dict.sql`을 출력한다(원격 연결 0).

금지(이 스크립트는 하지 않는다): DROP·DELETE·TRUNCATE·UPDATE, 다른 테이블 변경.
접속 문자열은 환경변수 SUPABASE_DB_URL(없으면 앱 Settings)에서 프로세스 안에서만 읽고 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from load_corpus import RemoteLoadRefused, resolve_dsn  # noqa: E402

from app.db import drug_dict_store as store  # noqa: E402
from app.security.redact import install_excepthook, redact  # noqa: E402
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"
APPROVAL_FLAG = REPO / "data" / "mock" / "review" / "be06_dict_approved.flag"
PARAMSTYLE = "format"  # psycopg


class Refused(RuntimeError):
    """안전장치에 걸려 실행하지 않음(원격 연결 전)."""


# --------------------------------------------------------------------------- 로컬

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_local(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise Refused(f"사전 파일이 없다: {path.name}(`scripts/build_drug_dict.py`가 만든다)")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    store.payload_summary(payload)  # 모양 확인(틀리면 ValueError)
    return payload, file_sha256(path)


def local_plan(payload: dict[str, Any], sha: str) -> dict[str, Any]:
    version, n_p, n_i = store.payload_summary(payload)
    data_bytes = sum(len(r[3].encode("utf-8")) for r in store.entry_rows(payload))
    return {"version": version, "products": n_p, "ingredients": n_i, "entry_rows": n_p + n_i, "meta_rows": 1,
            "entry_data_bytes": data_bytes, "source_sha256": sha}


# --------------------------------------------------------------------------- 원격

def connect(read_only: bool, connect_fn: Callable[[str], Any] | None = None) -> Any:
    dsn = resolve_dsn(DSN_ENV)
    if not dsn:
        raise RemoteLoadRefused(f"{DSN_ENV} 값을 찾지 못했다")
    if connect_fn is None:
        import psycopg  # noqa: PLC0415

        connect_fn = psycopg.connect
    conn = connect_fn(dsn)
    if read_only:
        conn.read_only = True
    return conn


def tables_present(cur: Any) -> dict[str, bool]:
    out = {}
    for t in (store.META_TABLE, store.ENTRY_TABLE):
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))
        out[t] = bool(cur.fetchone()[0])
    return out


def remote_plan(conn: Any, payload: dict[str, Any], sha: str, *, paramstyle: str = PARAMSTYLE,
                present_fn: Callable[[Any], dict[str, bool]] = tables_present) -> dict[str, Any]:
    """읽기만. 원격에 같은 판이 있는지와 넣을 행 수."""
    version, n_p, n_i = store.payload_summary(payload)
    ph = store.placeholder(paramstyle)
    cur = conn.cursor()
    present = present_fn(cur)
    out: dict[str, Any] = {"tables": present, "version": version, "to_insert_entries": n_p + n_i, "to_insert_meta": 1}
    if not all(present.values()):
        out["note"] = "테이블 없음: apply가 스키마를 먼저 만든다"
        return out
    meta = store.meta_row(cur, version, ph)
    counts = store.entry_counts(cur, version, ph)
    out["remote_meta"] = None if meta is None else {"source_sha256_prefix": meta[0][:12], "products": meta[1], "ingredients": meta[2],
                                                     "same_source": meta[0] == sha}
    out["remote_entries"] = counts
    if meta is not None and meta[0] == sha:
        out["to_insert_entries"], out["to_insert_meta"] = 0, 0
    else:
        out["to_insert_entries"] = n_p + n_i - sum(counts.values())
    cur.execute(f"SELECT COUNT(*) FROM {store.META_TABLE}")  # noqa: S608
    out["remote_versions"] = int(cur.fetchone()[0])
    return out


def apply(conn: Any, payload: dict[str, Any], sha: str, *, paramstyle: str = PARAMSTYLE, log: Callable[[str], None] = print) -> dict[str, Any]:
    """한 트랜잭션으로 스키마 + 적재. 예외면 롤백하고 다시 올린다."""
    try:
        store.apply_dict_schema(conn)
        res = store.load_payload(conn, payload, sha, paramstyle=paramstyle)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log(f"[apply] 롤백: {type(exc).__name__}: {redact(str(exc))[:200]}")
        raise
    log(f"[apply] 커밋: {json.dumps(res, ensure_ascii=False)}")
    return res


def verify(conn: Any, payload: dict[str, Any], sha: str, *, paramstyle: str = PARAMSTYLE) -> dict[str, Any]:
    """읽기만. 원격 최신 판으로 `DrugDict`를 만들고 로컬과 대조한다."""
    version, n_p, n_i = store.payload_summary(payload)
    remote = store.read_payload(conn, paramstyle=paramstyle)
    dd = DrugDict(remote)
    meta = store.meta_row(conn.cursor(), dd.version, store.placeholder(paramstyle))
    ok = (dd.version == version and len(dd.products) == n_p and len(dd.ingredients) == n_i and meta is not None and meta[0] == sha
          and remote["products"] == payload["products"] and remote["ingredients"] == payload["ingredients"])
    return {"ok": ok, "remote_version": dd.version, "local_version": version, "products": len(dd.products), "ingredients": len(dd.ingredients),
            "same_source": meta is not None and meta[0] == sha}


# --------------------------------------------------------------------------- CLI

def gate(args: argparse.Namespace, flag: Path = APPROVAL_FLAG) -> None:
    """이중 안전장치: --yes와 승인 파일이 둘 다 있어야 한다. 원격 연결 전에 확인한다."""
    if not args.yes:
        raise Refused("apply는 --yes가 필요하다")
    if not flag.is_file():
        raise Refused(f"승인 파일이 없다: {flag.name}(사용자 승인 뒤 메인 세션이 data/mock/review/에 만든다)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="plan", choices=("plan", "apply", "verify"))
    ap.add_argument("--dict-path", type=Path, default=DEFAULT_DICT_PATH, help="사전 JSON 경로(기본 data/mock/dict/drug_dict.json)")
    ap.add_argument("--remote", action="store_true", help="plan에서 원격 읽기 전용 확인")
    ap.add_argument("--yes", action="store_true", help="apply 확인")
    ap.add_argument("--print-sql", action="store_true", help="스키마 SQL만 출력")
    return ap


def main(argv: list[str] | None = None, *, connect_fn: Callable[[str], Any] | None = None, paramstyle: str = PARAMSTYLE,
         flag: Path = APPROVAL_FLAG, log: Callable[[str], None] = print,
         present_fn: Callable[[Any], dict[str, bool]] = tables_present) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if args.print_sql:
        log(store.SCHEMA_PATH.read_text(encoding="utf-8"))
        return {"print_sql": True, "remote_connections": 0}
    if args.cmd == "apply":
        gate(args, flag)  # 파일을 읽거나 연결하기 전에 거부
    payload, sha = read_local(args.dict_path)
    out: dict[str, Any] = {"cmd": args.cmd, "local": local_plan(payload, sha), "remote_connections": 0}
    if (args.cmd == "plan" and args.remote) or args.cmd == "verify":
        conn = connect(read_only=True, connect_fn=connect_fn)
        out["remote_connections"] = 1
        try:
            out["remote"] = (remote_plan(conn, payload, sha, paramstyle=paramstyle, present_fn=present_fn) if args.cmd == "plan"
                             else verify(conn, payload, sha, paramstyle=paramstyle))
        finally:
            conn.close()
    elif args.cmd == "apply":
        conn = connect(read_only=False, connect_fn=connect_fn)
        out["remote_connections"] = 1
        try:
            out["apply"] = apply(conn, payload, sha, paramstyle=paramstyle, log=log)
        finally:
            conn.close()
    log(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    install_excepthook()
    try:
        main()
    except (Refused, RemoteLoadRefused) as e:
        print(f"거부: {redact(str(e))}", file=sys.stderr)
        sys.exit(2)
