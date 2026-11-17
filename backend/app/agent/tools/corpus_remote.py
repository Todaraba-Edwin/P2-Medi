"""AG-03 원격 코퍼스 연결: DB → `CorpusIndex` 로더와 pgvector `VectorSearchFn` 어댑터.

- **읽기 전용**이다. 연결을 `read_only`로 열고 `SELECT`·`SET`(검색 파라미터)만 보낸다. 쓰기 SQL은 이 모듈에 없다.
- 연결·임베딩은 모두 주입한다(`ConnFactory`, `QueryEmbedder`). 시험은 가짜 연결·가짜 임베딩을 넣고 네트워크를 쓰지 않는다.
- 로더(`load_corpus_from_db`): 서버 시작 시 1회 청크 본문·메타를 읽어 메모리 `CorpusIndex`(BM25 글자 2-gram, BE-10-07)를 만든다.
  원격에 아직 없을 수 있는 열(`year`·`source_file`·`effective_date`)은 카탈로그(`information_schema.columns`)로 확인해 있을 때만 읽는다.
- 어댑터(`PgVectorSearch`): 질의 임베딩 → `embedding <=> q`(cosine) top-k. **강한 필터**(`ingr_codes` GIN·`item_seq`·`pair_id`·`notice_no`)가 있을 때만
  SQL `WHERE`로 좁혀 검색한다(BE-05 §5 "약한 필터 후필터 문제"). `layer` 같은 약한 필터만 있으면 SQL에는 걸지 않고(전역 근사 검색),
  결과 걸러내기는 `CorpusIndex.search`의 후보 집합이 맡는다. 그래서 줄어든 벡터 결과는 BM25가 메운다(RRF는 BM25 단독으로도 동작).
- 벡터 경로의 어떤 실패(임베딩·DB)도 검색 전체를 막지 않는다. 빈 결과를 돌려주고 `last_stats`에 오류 종류만 남긴다(비밀값·연결 문자열 없음).
"""

from __future__ import annotations

import base64
import os
import struct
import sys
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from app.agent.tools.corpus import ChunkFilter, CorpusIndex

DIM = 1536
EMBED_MODEL = "text-embedding-3-small"
TABLE = "corpus_chunks"
FETCH_BATCH = 5000
EF_SEARCH = 100

# 항상 읽는 열(임베딩 제외). 순서는 아래 SELECT와 같다.
BASE_COLUMNS = (
    "chunk_id", "chunk_kind", "parent_id", "refs", "pair_id", "layer", "issuer", "doc_type", "notice_no", "base_date", "locator", "ingr_codes",
    "ingr_names", "license", "text", "source_ref", "item_seq", "item_name", "section", "code_status",
)
# 원격에 아직 없을 수 있는 열: 카탈로그에 있을 때만 읽는다.
OPTIONAL_COLUMNS = ("year", "source_file", "effective_date")
_DATE_COLUMNS = ("base_date", "effective_date")
_LIST_COLUMNS = ("ingr_codes", "ingr_names")

ConnFactory = Callable[[], Any]  # psycopg 방식 연결(`cursor()`·`close()`). 호출마다 새 연결, 이 모듈이 닫는다.


class QueryEmbedder(Protocol):
    """질의 1개 → 임베딩 벡터(`DIM` 차원)."""

    def __call__(self, text: str) -> Sequence[float]: ...


def _open_read_only(conn_factory: ConnFactory) -> Any:
    conn = conn_factory()
    conn.read_only = True  # psycopg: 이 연결의 트랜잭션은 읽기 전용(쓰기 시도는 서버가 거부)
    return conn


# --------------------------------------------------------------------------- 로더

def existing_columns(cur: Any, table: str = TABLE) -> set[str]:
    """카탈로그로 열 이름을 읽는다. 표가 없으면 빈 집합."""
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = ANY (current_schemas(false))", (table,))
    return {r[0] for r in cur.fetchall()}


def select_columns(present: set[str]) -> list[str]:
    """읽을 열 목록: 기본 열은 전부 있어야 하고(없으면 오류), 선택 열은 있는 것만."""
    missing = [c for c in BASE_COLUMNS if c not in present]
    if missing:
        raise RuntimeError(f"{TABLE}에 필수 열이 없다: {missing}")
    return list(BASE_COLUMNS) + [c for c in OPTIONAL_COLUMNS if c in present]


def row_to_chunk(cols: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    """DB 행 → 로컬 jsonl 청크와 같은 dict(날짜는 `YYYY-MM-DD` 문자열, 배열은 list, NULL 배열은 빈 list)."""
    c: dict[str, Any] = dict(zip(cols, row, strict=True))
    for k in _DATE_COLUMNS:
        v = c.get(k)
        if isinstance(v, (date, datetime)):
            c[k] = v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
    for k in _LIST_COLUMNS:
        c[k] = list(c.get(k) or [])
    c["refs"] = list(c.get("refs") or [])
    return c


def load_chunks_from_db(conn_factory: ConnFactory, *, batch: int = FETCH_BATCH) -> tuple[list[dict[str, Any]], list[str]]:
    """청크 전체를 `chunk_id` 순으로 읽는다. `(청크 목록, 읽은 열 이름)`. 같은 `chunk_id`는 PK라 중복 없음."""
    conn = _open_read_only(conn_factory)
    try:
        cur = conn.cursor()
        cols = select_columns(existing_columns(cur))
        cur.execute(f"SELECT {', '.join(cols)} FROM {TABLE} ORDER BY chunk_id")  # noqa: S608 - 열·표 이름은 이 모듈 상수
        chunks: list[dict[str, Any]] = []
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            chunks.extend(row_to_chunk(cols, r) for r in rows)
        return chunks, cols
    finally:
        conn.close()


def load_corpus_from_db(conn_factory: ConnFactory, *, batch: int = FETCH_BATCH) -> CorpusIndex:
    """서버 시작 시 1회: DB 청크 → 메모리 `CorpusIndex`(BM25 2-gram). 0행이면 빈 코퍼스 대신 오류(원격 미적재 신호)."""
    chunks, _ = load_chunks_from_db(conn_factory, batch=batch)
    if not chunks:
        raise RuntimeError(f"{TABLE}에 행이 없다(원격 코퍼스 미적재)")
    return CorpusIndex(chunks)


# --------------------------------------------------------------------------- 벡터 어댑터

def vec_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def has_strong_filter(flt: ChunkFilter) -> bool:
    """SQL에서 인덱스(GIN·btree)로 먼저 좁혀지는 조건이 있는가. 성분명(`ingr_names`)은 인덱스가 없어 약한 필터로 본다."""
    return bool(flt.ingr_codes or flt.item_seq or flt.pair_ids or flt.notice_no)


def build_where(flt: ChunkFilter) -> tuple[list[str], list[Any]]:
    """`ChunkFilter` → SQL 조건·파라미터(`%s`). **강한 필터가 있을 때만** 약한 조건(layer·kind…)을 함께 건다."""
    if not has_strong_filter(flt):
        return [], []
    conds: list[str] = []
    params: list[Any] = []
    if flt.ingr_codes:
        conds.append("ingr_codes && %s::text[]")
        params.append(sorted(flt.ingr_codes))
    if flt.item_seq:
        conds.append("item_seq = %s")
        params.append(flt.item_seq)
    if flt.pair_ids:
        conds.append("pair_id = ANY (%s)")
        params.append(sorted(flt.pair_ids))
    if flt.notice_no:
        conds.append("notice_no = %s")
        params.append(flt.notice_no)
    for col, vals in (("layer", flt.layers), ("chunk_kind", flt.chunk_kinds), ("doc_type", flt.doc_types)):
        if vals is not None:
            conds.append(f"{col} = ANY (%s)")
            params.append(sorted(vals))
    if flt.base_date is not None:
        conds.append("base_date = %s::date")
        params.append(flt.base_date)
    if flt.years is not None:  # year가 NULL인 행은 `= ANY`에 걸리지 않는다(`CorpusIndex.candidates`와 같은 의미)
        conds.append("year = ANY (%s::smallint[])")
        params.append(sorted(int(y) for y in flt.years))
    if flt.issuers is not None:
        conds.append("issuer = ANY (%s)")
        params.append(sorted(flt.issuers))
    if flt.sections is not None or flt.section_prefix is not None:  # 두 조건은 OR(`CorpusIndex.candidates`와 같은 의미)
        ors: list[str] = []
        if flt.sections:
            ors.append("section = ANY (%s)")
            params.append(sorted(flt.sections))
        if flt.section_prefix is not None:
            ors.append("(section = %s OR section LIKE %s ESCAPE '\\')")
            params.extend([flt.section_prefix, _like_escape(flt.section_prefix) + " %"])
        conds.append("(" + " OR ".join(ors) + ")" if ors else "FALSE")
    return conds, params


@dataclass
class SearchStats:
    mode: str = ""             # "strong"(SQL 필터) | "global"(필터 없음 또는 약한 필터만: 후필터는 앱) | "skipped"(질의 없음) | "error"
    rows: int = 0
    embed_ms: float = 0.0
    sql_ms: float = 0.0
    error: str | None = None   # 예외 클래스 이름만(메시지에는 비밀이 있을 수 있어 싣지 않는다)


@dataclass
class PgVectorSearch:
    """`corpus.VectorSearchFn` 구현. 호출마다 새 읽기 전용 연결을 열고 닫는다."""

    conn_factory: ConnFactory
    embed: QueryEmbedder
    dim: int = DIM
    ef_search: int = EF_SEARCH
    cache_size: int = 64
    last_stats: SearchStats = field(default_factory=SearchStats)
    _cache: OrderedDict[str, tuple[float, ...]] = field(default_factory=OrderedDict, repr=False)

    def _embed(self, query: str) -> Sequence[float]:
        hit = self._cache.get(query)
        if hit is not None:
            self._cache.move_to_end(query)
            return hit
        vec = tuple(float(x) for x in self.embed(query))
        if len(vec) != self.dim:
            raise ValueError(f"임베딩 차원 불일치: {len(vec)} != {self.dim}")
        self._cache[query] = vec
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return vec

    def __call__(self, query: str, *, k: int, filters: ChunkFilter) -> Sequence[tuple[str, float]]:
        st = SearchStats()
        self.last_stats = st
        if not query.strip() or k <= 0:
            st.mode = "skipped"
            return []
        try:
            t0 = time.perf_counter()
            vec = self._embed(query)
            st.embed_ms = (time.perf_counter() - t0) * 1000
            conds, params = build_where(filters)
            st.mode = "strong" if conds else "global"
            where = " AND ".join(["embedding IS NOT NULL", *conds])
            lit = vec_literal(vec)
            sql = f"SELECT chunk_id, 1 - (embedding <=> %s::vector) FROM {TABLE} WHERE {where} ORDER BY embedding <=> %s::vector LIMIT %s"  # noqa: S608
            t1 = time.perf_counter()
            conn = _open_read_only(self.conn_factory)
            try:
                cur = conn.cursor()
                cur.execute(f"SET hnsw.ef_search = {int(max(self.ef_search, k))}")
                cur.execute(sql, [lit, *params, lit, int(k)])
                rows = [(str(r[0]), float(r[1])) for r in cur.fetchall()]
            finally:
                conn.close()
            st.sql_ms = (time.perf_counter() - t1) * 1000
            st.rows = len(rows)
            return rows
        except Exception as exc:  # noqa: BLE001 - 벡터 경로 실패는 BM25 단독으로 저하(검색을 막지 않는다)
            st.mode, st.error = "error", type(exc).__name__
            return []


# --------------------------------------------------------------------------- 조립·기본 임베더

def build_remote_search(conn_factory: ConnFactory, embed: QueryEmbedder) -> tuple[CorpusIndex, PgVectorSearch]:
    """`ToolContext(corpus=index, vector_search_fn=search)`에 그대로 넣는 한 쌍."""
    return load_corpus_from_db(conn_factory), PgVectorSearch(conn_factory, embed)


def psycopg_conn_factory(dsn_env: str = "SUPABASE_DB_URL") -> ConnFactory:
    """환경변수(또는 앱 설정)의 접속 문자열로 psycopg 연결을 여는 팩토리. 문자열은 출력·예외에 쓰지 않는다."""
    import psycopg  # noqa: PLC0415 - 원격 연결 때만 필요

    dsn = os.environ.get(dsn_env, "")
    if not dsn:
        scripts = str(Path(__file__).resolve().parents[3] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from load_corpus import resolve_dsn  # noqa: PLC0415

        dsn = resolve_dsn(dsn_env)
    if not dsn:
        raise RuntimeError(f"{dsn_env} 값을 찾지 못했다")
    return lambda: psycopg.connect(dsn)


def openai_query_embedder(max_usd: float = 0.01) -> QueryEmbedder:
    """기존 임베딩 클라이언트(`embed_compare.Embedder`: 상한·개발 원장·캐시, `embed_corpus.http_embed`: 실호출)를 질의 1개 단위로 재사용한다."""
    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from embed_compare import Embedder, _ensure_cache_importable, resolve_key  # noqa: PLC0415

    _ensure_cache_importable()
    from embed_corpus import http_embed  # noqa: PLC0415

    key = resolve_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY 값을 찾지 못했다")
    emb = Embedder("small", max_usd, lambda model, texts: http_embed(model, texts, key))
    emb.cached_batches = 0
    n = [0]

    def embed(text: str) -> list[float]:
        n[0] += 1
        b64 = emb.embed_batch([text], f"query_embed:{n[0]}")[0]
        raw = base64.b64decode(b64)
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))

    embed.embedder = emb  # type: ignore[attr-defined]  # 스모크가 호출 수·비용을 읽는다
    return embed
