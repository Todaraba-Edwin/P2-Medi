"""BE-06-24 B 제품·성분 사전 DB 저장소(2026-11-17): 사전 JSON ↔ `drug_dict_meta`·`drug_dict_entry`(schema_dict.sql).

- 서비스 경로는 사전을 이 테이블에서 읽는다(`DrugDict.from_db`). 파일(`data/mock/dict/drug_dict.json`)은 개발·평가용으로 남는다.
- 이 모듈은 접속하지 않는다. 호출자가 넘긴 DB-API 연결(psycopg `format`, sqlite3 `qmark`)에만 SQL을 보낸다.
- 적재(`load_payload`)는 커밋하지 않는다. 호출자가 한 트랜잭션으로 묶고 성공하면 커밋, 예외면 롤백한다.
  같은 판(version)을 다시 넣으면 아무것도 바꾸지 않는다(멱등). 같은 판에 다른 파일(sha256)이 오면 거부한다.
- 읽기(`read_payload`)는 판이 완전한지(행 수·순서 번호가 0..n-1로 이어지는지) 확인하고, 아니면 예외로 올린다(빈 사전으로 서비스하지 않는다).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.loaders import _placeholder as placeholder

SCHEMA_PATH = Path(__file__).with_name("schema_dict.sql")
META_TABLE = "drug_dict_meta"
ENTRY_TABLE = "drug_dict_entry"
KIND_PRODUCT = "product"
KIND_INGREDIENT = "ingredient"
_KIND_KEY = {KIND_PRODUCT: "products", KIND_INGREDIENT: "ingredients"}
INSERT_BATCH = 500


class DictStoreError(RuntimeError):
    """사전 테이블 상태가 기대와 다르다(미적재·불완전·충돌)."""


class DictNotLoaded(DictStoreError):
    """사전 판이 하나도 없다(원격 미적재 신호)."""


class DictIncomplete(DictStoreError):
    """판의 행 수·순서가 meta와 맞지 않는다."""


class DictConflict(DictStoreError):
    """같은 판(version)에 다른 원본(sha256)이 이미 있다."""


# --------------------------------------------------------------------------- 공통

def payload_summary(payload: dict[str, Any]) -> tuple[str, int, int]:
    """(version, 제품 수, 성분 수). 모양이 틀리면 ValueError."""
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("사전 meta가 dict가 아니다")
    version = meta.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("사전 meta.version이 비어 있다")
    products, ingredients = payload.get("products"), payload.get("ingredients")
    if not isinstance(products, list) or not isinstance(ingredients, list):
        raise ValueError("사전 products·ingredients가 목록이 아니다")
    if not products:
        raise ValueError("사전 products가 비어 있다")
    return version, len(products), len(ingredients)


def entry_rows(payload: dict[str, Any]) -> Iterator[tuple[str, str, int, str]]:
    """(version, kind, ord, data JSON) 행. 제품 먼저, 성분 뒤, 파일 안 순서 그대로."""
    version, _, _ = payload_summary(payload)
    for kind in (KIND_PRODUCT, KIND_INGREDIENT):
        for i, item in enumerate(payload[_KIND_KEY[kind]]):
            yield version, kind, i, json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def apply_dict_schema(conn: Any) -> None:
    """schema_dict.sql 실행(IF NOT EXISTS라 다시 돌려도 안전). 커밋은 호출자가 한다."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    if hasattr(conn, "executescript"):  # sqlite3
        conn.executescript(sql)
    else:
        conn.cursor().execute(sql)


def meta_row(cur: Any, version: str, ph: str) -> tuple[str, int, int] | None:
    """(source_sha256, 제품 수, 성분 수) 또는 None."""
    cur.execute(f"SELECT source_sha256, n_products, n_ingredients FROM {META_TABLE} WHERE version = {ph}", (version,))  # noqa: S608
    row = cur.fetchone()
    return None if row is None else (str(row[0]), int(row[1]), int(row[2]))


def entry_counts(cur: Any, version: str, ph: str) -> dict[str, int]:
    cur.execute(f"SELECT kind, COUNT(*) FROM {ENTRY_TABLE} WHERE version = {ph} GROUP BY kind", (version,))  # noqa: S608
    out = {KIND_PRODUCT: 0, KIND_INGREDIENT: 0}
    for kind, n in cur.fetchall():
        out[str(kind)] = int(n)
    return out


# --------------------------------------------------------------------------- 적재(쓰기, 커밋은 호출자)

def load_payload(conn: Any, payload: dict[str, Any], source_sha256: str, *, paramstyle: str = "qmark",
                 batch: int = INSERT_BATCH, now: str | None = None) -> dict[str, Any]:
    """사전 한 판을 넣는다. 이미 완전히 들어 있으면 0행(`already_loaded`). 커밋하지 않는다.

    순서: meta 행 확인(같은 판·같은 sha면 건너뜀, 다른 sha면 `DictConflict`) → entry 일괄 삽입(ON CONFLICT DO NOTHING)
    → 판의 entry 행 수가 기대와 같은지 확인(다르면 `DictIncomplete`, 호출자가 롤백) → meta 행 삽입.
    """
    version, n_p, n_i = payload_summary(payload)
    ph = placeholder(paramstyle)
    cur = conn.cursor()
    existing = meta_row(cur, version, ph)
    if existing is not None:
        sha, ep, ei = existing
        if sha != source_sha256:
            raise DictConflict(f"판 {version}에 다른 원본이 이미 있다(sha256 {sha[:12]}… ≠ {source_sha256[:12]}…)")
        counts = entry_counts(cur, version, ph)
        if (ep, ei) != (n_p, n_i) or counts != {KIND_PRODUCT: n_p, KIND_INGREDIENT: n_i}:
            raise DictIncomplete(f"판 {version}의 meta·행 수가 원본과 다르다: meta={ep}/{ei}, 행={counts}, 원본={n_p}/{n_i}")
        return {"status": "already_loaded", "version": version, "inserted_entries": 0, "products": n_p, "ingredients": n_i}

    before = entry_counts(cur, version, ph)
    sql = (f"INSERT INTO {ENTRY_TABLE} (version, kind, ord, data) VALUES ({ph}, {ph}, {ph}, {ph}) "  # noqa: S608
           f"ON CONFLICT (version, kind, ord) DO NOTHING")
    buf: list[tuple[str, str, int, str]] = []
    for row in entry_rows(payload):
        buf.append(row)
        if len(buf) >= batch:
            cur.executemany(sql, buf)
            buf.clear()
    if buf:
        cur.executemany(sql, buf)
    after = entry_counts(cur, version, ph)
    if after != {KIND_PRODUCT: n_p, KIND_INGREDIENT: n_i}:
        raise DictIncomplete(f"판 {version} 적재 뒤 행 수가 기대와 다르다: {after}, 기대 {n_p}/{n_i}")
    cur.execute(
        f"INSERT INTO {META_TABLE} (version, meta, n_products, n_ingredients, source_sha256, loaded_at) "  # noqa: S608
        f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}) ON CONFLICT (version) DO NOTHING",
        (version, json.dumps(payload["meta"], ensure_ascii=False, separators=(",", ":")), n_p, n_i, source_sha256,
         now or datetime.now(UTC).isoformat(timespec="seconds")))
    inserted = sum(after.values()) - sum(before.values())
    return {"status": "loaded", "version": version, "inserted_entries": inserted, "products": n_p, "ingredients": n_i}


# --------------------------------------------------------------------------- 읽기

def latest_version(cur: Any, ph: str, version: str | None = None) -> tuple[str, dict[str, Any], int, int]:
    """(version, meta, 제품 수, 성분 수). `version`을 주면 그 판, 없으면 가장 늦게 적재한 판."""
    if version is None:
        cur.execute(f"SELECT version, meta, n_products, n_ingredients FROM {META_TABLE} "  # noqa: S608
                    "ORDER BY loaded_at DESC, version DESC LIMIT 1")
    else:
        cur.execute(f"SELECT version, meta, n_products, n_ingredients FROM {META_TABLE} WHERE version = {ph}", (version,))  # noqa: S608
    row = cur.fetchone()
    if row is None:
        raise DictNotLoaded(f"{META_TABLE}에 사전 판이 없다(원격 사전 미적재)" + (f": {version}" if version else ""))
    meta = row[1] if isinstance(row[1], dict) else json.loads(row[1])
    return str(row[0]), meta, int(row[2]), int(row[3])


def read_payload(conn: Any, *, paramstyle: str = "qmark", version: str | None = None, batch: int = 5000) -> dict[str, Any]:
    """사전 한 판 → `DrugDict` 생성자에 넣을 dict(`meta`·`products`·`ingredients`). 판이 불완전하면 `DictIncomplete`."""
    ph = placeholder(paramstyle)
    cur = conn.cursor()
    ver, meta, n_p, n_i = latest_version(cur, ph, version)
    cur.execute(f"SELECT kind, ord, data FROM {ENTRY_TABLE} WHERE version = {ph} ORDER BY kind, ord", (ver,))  # noqa: S608
    out: dict[str, list[Any]] = {"products": [], "ingredients": []}
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        for kind, ord_, data in rows:
            key = _KIND_KEY.get(str(kind))
            if key is None:
                raise DictIncomplete(f"판 {ver}에 알 수 없는 종류가 있다: {kind!r}")
            if int(ord_) != len(out[key]):
                raise DictIncomplete(f"판 {ver}의 {kind} 순서 번호가 끊겼다: {ord_} (기대 {len(out[key])})")
            out[key].append(data if isinstance(data, dict) else json.loads(data))
    if (len(out["products"]), len(out["ingredients"])) != (n_p, n_i):
        raise DictIncomplete(f"판 {ver}의 행 수가 meta와 다르다: {len(out['products'])}/{len(out['ingredients'])}, meta {n_p}/{n_i}")
    return {"meta": meta, "products": out["products"], "ingredients": out["ingredients"]}


__all__ = ["ENTRY_TABLE", "META_TABLE", "SCHEMA_PATH", "DictConflict", "DictIncomplete", "DictNotLoaded", "DictStoreError",
           "apply_dict_schema", "entry_counts", "entry_rows", "latest_version", "load_payload", "meta_row", "payload_summary", "placeholder",
           "read_payload"]
