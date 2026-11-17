"""RFP-04 연도(year) 빈 칸 보충: base_date 앞 4자리 → year (로컬 jsonl·sqlite, 원격 corpus_chunks).

배경: `l1_notice.jsonl`·`l3_eyak.jsonl`(2026-11-11 생성)은 `year` 칸이 없다(RFP-04 §5 2026-11-17 후속, 로컬 30,744행).
chunk_id는 `kind|key|text` 해시라 year를 더해도 ID·벡터는 그대로다(`build_corpus_l3.py:86`).

  local           (기본 dry-run) 대상 수·파일별 수·유도 불가 수만 출력한다. 파일·DB 변경 0.
  local --apply   파일마다 원본을 `<이름>.before_rfp04year.jsonl`로 복사 → 임시 파일에 쓰기 → 검사(chunk_id 순서·year 외 칸 불변)
                  → os.replace(원자 교체). 검사 실패면 임시 파일을 지우고 중단한다. 백업 파일이 이미 있으면 거부한다.
                  `all.sqlite`에 year 열이 있으면 같은 규칙으로 UPDATE, 없으면 보고만 한다.
  remote          (기본 dry-run) 읽기 전용 트랜잭션에서 `year IS NULL` 대상 수·유도 불가 수·kind별 분포 SELECT. 쓰기 0.
  remote --apply --yes --expect N
                  승인 파일 `data/mock/review/rfp04_year_approved.flag`(사용자 승인 뒤 메인이 만든다)가 있어야 한다(원격 연결 전 확인).
                  한 트랜잭션: 사전 대상 수 = N 확인 → UPDATE → 영향 행 수 = 사전 수 = N 확인 → 남은 NULL = 유도 불가 수 확인 → COMMIT.
                  하나라도 다르면 ROLLBACK. 실행 기록 `logs/remote/rfp04_year_<UTC 시각>.json`.

유도 규칙: base_date(DATE 또는 'YYYY-…' 문자열)의 앞 4자리 정수. 비었거나 숫자 4자리로 시작하지 않으면 유도 불가(그대로 둔다).
접속 문자열은 환경변수 SUPABASE_DB_URL(없으면 앱 Settings)에서 프로세스 안에서만 읽고 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from load_corpus import RemoteLoadRefused, resolve_dsn  # noqa: E402

from app.security.redact import install_excepthook, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"
LOCAL_FILES = ("l1_notice.jsonl", "l3_eyak.jsonl")
SQLITE_NAME = "all.sqlite"
BACKUP_SUFFIX = ".before_rfp04year.jsonl"
FLAG_REL = Path("data") / "mock" / "review" / "rfp04_year_approved.flag"
EXPECT_LOCAL = 30_744  # l1_notice 2,904 + l3_eyak 27,840 (rfp04-worker 보고)
APPLY_TIMEOUT = "10min"  # 3만 행 UPDATE는 HNSW 색인 갱신을 동반할 수 있다
_YEAR_RE = re.compile(r"^(\d{4})")


class Refused(RuntimeError):
    """실행 조건 미충족 → 아무것도 바꾸지 않고 거부."""


class Abort(RuntimeError):
    """검사 실패 → 그 단계 롤백(원격) 또는 임시 파일 폐기(로컬) 후 중단."""


def derive_year(base_date: Any) -> int | None:
    if base_date is None:
        return None
    if hasattr(base_date, "year") and not isinstance(base_date, str):
        return int(base_date.year)
    m = _YEAR_RE.match(str(base_date))
    return int(m.group(1)) if m else None


def year_missing(rec: dict[str, Any]) -> bool:
    return rec.get("year") in (None, "")


# --------------------------------------------------------------------------- 로컬 jsonl

@dataclass
class FilePlan:
    path: Path
    total: int = 0
    targets: int = 0
    underivable: int = 0
    derived: Counter[int] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.path.name, "total": self.total, "targets": self.targets, "underivable": self.underivable,
                "derived_years": dict(sorted(self.derived.items()))}


def with_year(rec: dict[str, Any], year: int) -> dict[str, Any]:
    """year를 source_ref 바로 뒤에 둔다(l3_prmsn.jsonl·schema_corpus.sql과 같은 칸 순서). 나머지 칸·순서는 그대로."""
    out: dict[str, Any] = {}
    placed = False
    for k, v in rec.items():
        if k == "year":
            continue
        out[k] = v
        if k == "source_ref":
            out["year"] = year
            placed = True
    if not placed:
        out["year"] = year
    return out


def dumps(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def transform_lines(lines: Sequence[str], plan: FilePlan) -> list[str]:
    """줄 단위 변환. year가 이미 있거나 유도 불가한 줄은 바이트 그대로 둔다."""
    out: list[str] = []
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            continue
        rec = json.loads(ln)
        plan.total += 1
        if not year_missing(rec):
            out.append(ln)
            continue
        y = derive_year(rec.get("base_date"))
        if y is None:
            plan.underivable += 1
            out.append(ln)
            continue
        plan.targets += 1
        plan.derived[y] += 1
        out.append(dumps(with_year(rec, y)))
    return out


def plan_file(path: Path) -> tuple[FilePlan, list[str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    plan = FilePlan(path)
    return plan, lines, transform_lines(lines, plan)


def verify_transform(old_lines: Sequence[str], new_lines: Sequence[str]) -> dict[str, int]:
    """chunk_id 순서 동일, year 외 칸 불변, 바뀐 줄은 year만 새로 생김. 어긋나면 Abort."""
    if len(old_lines) != len(new_lines):
        raise Abort(f"줄 수가 다름: {len(old_lines)} → {len(new_lines)}")
    changed = 0
    for i, (a, b) in enumerate(zip(old_lines, new_lines, strict=True)):
        if a == b:
            continue
        ra, rb = json.loads(a), json.loads(b)
        if ra.get("chunk_id") != rb.get("chunk_id"):
            raise Abort(f"{i + 1}행 chunk_id가 바뀜")
        rest_a = {k: v for k, v in ra.items() if k != "year"}
        rest_b = {k: v for k, v in rb.items() if k != "year"}
        if rest_a != rest_b:
            raise Abort(f"{i + 1}행 year 외 칸이 바뀜")
        if not year_missing(ra) or year_missing(rb):
            raise Abort(f"{i + 1}행 year 변경 방향 이상")
        changed += 1
    return {"changed": changed}


def apply_file(path: Path, plan: FilePlan, old_lines: list[str], new_lines: list[str]) -> dict[str, Any]:
    backup = path.with_name(path.name.removesuffix(".jsonl") + BACKUP_SUFFIX)
    if backup.exists():
        raise Refused(f"백업 파일이 이미 있다(덮어쓰지 않음): {backup.name}")
    check = verify_transform(old_lines, new_lines)
    if check["changed"] != plan.targets:
        raise Abort(f"{path.name}: 바뀐 줄 {check['changed']} ≠ 대상 {plan.targets}")
    shutil.copy2(path, backup)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        written = tmp.read_text(encoding="utf-8").splitlines()
        verify_transform(old_lines, written)
        if sum(1 for ln in written if ln.strip() and year_missing(json.loads(ln))) != plan.underivable:
            raise Abort(f"{path.name}: 교체 전 검사에서 남은 빈 year 수가 유도 불가 수와 다름")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)  # 이번 호출에서 만든 백업(원본과 같은 내용). 원본은 그대로라 재시도가 막히지 않게 지운다
        raise
    return {"file": path.name, "backup": backup.name, "changed": check["changed"]}


def sqlite_plan(db: Path) -> dict[str, Any]:
    """읽기 전용(mode=ro)으로 열어 year 열 유무와 대상 수를 센다."""
    if not db.exists():
        return {"sqlite": db.name, "exists": False}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(corpus_chunks)")}
        if "year" not in cols:
            return {"sqlite": db.name, "exists": True, "year_column": False, "note": "year 열 없음 → 보고만(변경 없음)"}
        tgt = con.execute("SELECT COUNT(*) FROM corpus_chunks WHERE (year IS NULL OR year = '') "
                          "AND substr(base_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'").fetchone()[0]
        bad = con.execute("SELECT COUNT(*) FROM corpus_chunks WHERE (year IS NULL OR year = '') "
                          "AND NOT (COALESCE(substr(base_date, 1, 4), '') GLOB '[0-9][0-9][0-9][0-9]')").fetchone()[0]
        return {"sqlite": db.name, "exists": True, "year_column": True, "targets": int(tgt), "underivable": int(bad)}
    finally:
        con.close()


def sqlite_apply(db: Path, expect: int) -> dict[str, Any]:
    con = sqlite3.connect(db)
    try:
        with con:  # 한 트랜잭션, 예외면 롤백
            cur = con.execute("UPDATE corpus_chunks SET year = CAST(substr(base_date, 1, 4) AS INTEGER) "
                              "WHERE (year IS NULL OR year = '') AND substr(base_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'")
            if cur.rowcount != expect:
                raise Abort(f"sqlite 영향 행 {cur.rowcount} ≠ 대상 {expect}")
        return {"sqlite": db.name, "updated": expect}
    finally:
        con.close()


def run_local(corpus_dir: Path, apply: bool, expect: int | None, log: Callable[[str], None] = print) -> dict[str, Any]:
    plans = []
    for name in LOCAL_FILES:
        p = corpus_dir / name
        if not p.exists():
            raise Refused(f"파일 없음: {name}")
        plans.append(plan_file(p))
    total = sum(pl.targets for pl, _, _ in plans)
    rep: dict[str, Any] = {"mode": "local", "apply": apply, "files": [pl.as_dict() for pl, _, _ in plans],
                           "targets": total, "underivable": sum(pl.underivable for pl, _, _ in plans),
                           "sqlite": sqlite_plan(corpus_dir / SQLITE_NAME)}
    log(json.dumps(rep, ensure_ascii=False, indent=1))
    if not apply:
        return rep
    if expect is not None and total != expect:
        raise Refused(f"대상 {total} ≠ --expect {expect}")
    rep["applied"] = [apply_file(pl.path, pl, old, new) for pl, old, new in plans if pl.targets]
    sq = rep["sqlite"]
    if sq.get("year_column") and sq.get("targets"):
        rep["applied"].append(sqlite_apply(corpus_dir / SQLITE_NAME, sq["targets"]))
    after = [plan_file(pl.path)[0] for pl, _, _ in plans]
    rep["after_targets"] = sum(a.targets for a in after)
    if rep["after_targets"] != 0:
        raise Abort(f"적용 뒤에도 대상 {rep['after_targets']}건 남음")
    log(json.dumps({"applied": rep["applied"], "after_targets": rep["after_targets"]}, ensure_ascii=False))
    return rep


# --------------------------------------------------------------------------- 원격

def connect(connect_fn: Callable[..., Any] | None = None) -> Any:
    dsn = resolve_dsn(DSN_ENV)
    if not dsn:
        raise RemoteLoadRefused(f"{DSN_ENV} 값을 찾지 못했다")
    if connect_fn is None:
        import psycopg  # noqa: PLC0415

        connect_fn = psycopg.connect
    return connect_fn(dsn, autocommit=True)  # 트랜잭션은 BEGIN/COMMIT/ROLLBACK을 직접 보낸다


def _one(cur: Any, sql: str, params: Sequence[Any] | None = None) -> Any:
    cur.execute(sql, params)
    return cur.fetchone()[0]


def column_types(cur: Any) -> dict[str, str]:
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'corpus_chunks' AND column_name IN ('year', 'base_date')")
    return {r[0]: r[1] for r in cur.fetchall()}


def sql_for(types: dict[str, str]) -> dict[str, str]:
    """열 타입에 맞는 대상·유도 불가·UPDATE 문장. year가 정수형이 아니면 Abort."""
    yt, bt = types.get("year"), types.get("base_date")
    if yt not in ("smallint", "integer"):
        raise Abort(f"year 열 타입이 정수형이 아님: {yt}")
    if bt == "date":
        ok, expr = "base_date IS NOT NULL", "EXTRACT(YEAR FROM base_date)"
    elif bt in ("text", "character varying"):
        ok, expr = r"base_date ~ '^\d{4}'", "left(base_date, 4)"
    else:
        raise Abort(f"base_date 열 타입 미지원: {bt}")
    cast = "smallint" if yt == "smallint" else "integer"
    return {
        "targets": f"SELECT COUNT(*) FROM corpus_chunks WHERE year IS NULL AND {ok}",  # noqa: S608 - 상수 조합
        "underivable": f"SELECT COUNT(*) FROM corpus_chunks WHERE year IS NULL AND NOT ({ok})",  # noqa: S608
        "by_kind": ("SELECT layer, chunk_kind, COUNT(*) FROM corpus_chunks WHERE year IS NULL "  # noqa: S608
                    f"AND {ok} GROUP BY 1, 2 ORDER BY 1, 2"),
        "update": f"UPDATE corpus_chunks SET year = {expr}::{cast} WHERE year IS NULL AND {ok}",  # noqa: S608
        "null_left": "SELECT COUNT(*) FROM corpus_chunks WHERE year IS NULL",
    }


def remote_dry_run(conn: Any) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute("BEGIN READ ONLY")
    try:
        cur.execute("SET LOCAL statement_timeout = '30s'")
        if str(_one(cur, "SHOW transaction_read_only")).lower() != "on":
            raise Abort("transaction_read_only가 on이 아님")
        types = column_types(cur)
        if "year" not in types:
            return {"mode": "remote-dry-run", "year_column": None, "note": "year 열 없음(BE-16 단계 1 미적용?)"}
        q = sql_for(types)
        cur.execute(q["by_kind"])
        by_kind = [{"layer": r[0], "chunk_kind": r[1], "n": int(r[2])} for r in cur.fetchall()]
        return {"mode": "remote-dry-run", "types": types, "targets": int(_one(cur, q["targets"])),
                "underivable": int(_one(cur, q["underivable"])), "by_kind": by_kind, "update_sql": q["update"]}
    finally:
        cur.execute("ROLLBACK")


def gate(args: argparse.Namespace, flag: Path) -> None:
    """원격 연결 전에 확인한다: --yes, --expect, 승인 파일."""
    if not args.yes:
        raise Refused("remote --apply는 --yes가 필요하다")
    if args.expect is None:
        raise Refused("remote --apply는 --expect N(원격 dry-run 대상 수)이 필요하다")
    if not flag.exists():
        raise Refused(f"승인 파일이 없다: {FLAG_REL}")


def remote_apply(conn: Any, expect: int, timeout: str = APPLY_TIMEOUT) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        q = sql_for(column_types(cur))
        pre = int(_one(cur, q["targets"]))
        bad = int(_one(cur, q["underivable"]))
        if pre != expect:
            raise Abort(f"사전 대상 {pre} ≠ --expect {expect}")
        cur.execute(q["update"])
        n = cur.rowcount
        if n != pre:
            raise Abort(f"영향 행 {n} ≠ 사전 대상 {pre}")
        left = int(_one(cur, q["null_left"]))
        if left != bad:
            raise Abort(f"남은 year NULL {left} ≠ 유도 불가 {bad}")
        cur.execute("COMMIT")
    except BaseException:
        with contextlib.suppress(Exception):  # 연결이 끊겼으면 서버가 이미 롤백한다. 원래 예외를 가리지 않는다
            cur.execute("ROLLBACK")
        raise
    return {"mode": "remote-apply", "expect": expect, "pre_targets": pre, "updated": n, "null_left": left, "underivable": bad,
            "committed": True}


def save_log(rep: dict[str, Any], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"rfp04_year_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(redact(json.dumps(rep, ensure_ascii=False, indent=1, default=str)), encoding="utf-8")
    return path


def run_remote(args: argparse.Namespace, connect_fn: Callable[..., Any] | None = None,
               log: Callable[[str], None] = print) -> dict[str, Any]:
    root: Path = args.repo_root
    if args.apply:
        gate(args, root / FLAG_REL)
    conn = connect(connect_fn)
    rep: dict[str, Any] = {"started_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        try:
            rep.update(remote_apply(conn, args.expect) if args.apply else remote_dry_run(conn))
        except Abort as e:
            rep.update({"mode": "remote-apply" if args.apply else "remote-dry-run", "aborted": redact(str(e)), "committed": False})
            raise
        finally:
            rep["finished_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
            log(f"기록: {save_log(rep, root / 'logs' / 'remote')}")
    finally:
        conn.close()
    log(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("mode", choices=("local", "remote"))
    ap.add_argument("--apply", action="store_true", help="쓰기(없으면 dry-run)")
    ap.add_argument("--yes", action="store_true", help="remote --apply 동의(승인 파일도 필요)")
    ap.add_argument("--expect", type=int, help=f"대상 수 기대값(remote --apply 필수, local은 선택: 보통 {EXPECT_LOCAL})")
    ap.add_argument("--repo-root", type=Path, default=REPO, help="data/·logs/를 찾을 저장소 루트(기본: 이 스크립트의 저장소)")
    ap.add_argument("--corpus-dir", type=Path, help="로컬 코퍼스 폴더(기본: <repo-root>/data/mock/corpus)")
    return ap


def main(argv: Sequence[str] | None = None, connect_fn: Callable[..., Any] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "local":
            run_local(args.corpus_dir or args.repo_root / "data" / "mock" / "corpus", args.apply, args.expect)
        else:
            run_remote(args, connect_fn)
    except Refused as e:
        print(f"거부: {redact(str(e))}", file=sys.stderr)
        return 2
    except (Abort, RemoteLoadRefused) as e:
        print(f"중단: {redact(str(e))}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    install_excepthook()
    raise SystemExit(main())
