"""RFP-04 FR-03 추적 확인 시험: 표 보존(행+열 이름)·메타 필터 검색·연결 메타데이터(`parent_id`·`refs`·`pair_id`).

- 로컬 실코퍼스(`data/mock/corpus/*.jsonl`)가 없으면 실데이터 시험은 skip한다. worktree처럼 코퍼스가 다른 곳에 있으면
  환경변수 `RFP04_CORPUS_DIR`로 폴더를 준다(읽기만 한다). 원격 DB·LLM·공공 API 호출 없음.
- 합성 시험(항상 실행)은 RFP-04-01 A로 더한 연도(`years`)·부처(`issuers`) 필터를 로컬 인덱스와 원격 `build_where` 양쪽에서 고정한다.
  `year`가 빈(None) 청크는 연도 필터에 걸리지 않는다(제외). `notice_no`·`base_date` 필터와 같은 규칙이다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.agent.tools import corpus_remote as cr
from app.agent.tools.corpus import CORPUS_FILES, DEFAULT_CORPUS_DIR, ChunkFilter, CorpusIndex, expand_chunks, load_jsonl

CORPUS_DIR = Path(os.environ.get("RFP04_CORPUS_DIR") or DEFAULT_CORPUS_DIR)
HAS_CORPUS = all((CORPUS_DIR / n).is_file() for n in CORPUS_FILES)
real = pytest.mark.skipif(not HAS_CORPUS, reason="로컬 코퍼스(data/mock/corpus) 없음")

ANNEX_RE = re.compile(r"별표\s*([123])")


@pytest.fixture(scope="module")
def idx() -> CorpusIndex:
    return CorpusIndex(load_jsonl([CORPUS_DIR / n for n in CORPUS_FILES]))


# ------------------------------------------------------------------ 1. 표 보존(행 + 열 이름 반복, 설계 문서 5장 (2) 결정 12)
@real
@pytest.mark.parametrize("n", [1, 2, 3])
def test_annex_rows_keep_title_column_names_and_parent_table(idx, n):
    rows = [c for c in idx.chunks if c["chunk_kind"] == f"l1_bupyo{n}_row"]
    table = next(c for c in idx.chunks if c["chunk_kind"] == f"l1_bupyo{n}_table")
    assert rows and table["text"].startswith(f"[별표 {n}") and "열: 연번 | " in table["text"]
    for r in rows:
        assert r["parent_id"] == table["chunk_id"]  # 표 → 행 연결
        assert r["text"].startswith(f"[별표 {n}") and "연번: " in r["text"]  # 행마다 표 제목·열 이름이 붙어 경계에서 끊기지 않는다
        assert r["locator"].startswith(f"별표 {n} 연번 ")


@real
def test_label_tables_carry_header_and_parent(idx):
    tables = [c for c in idx.chunks if c["chunk_kind"] == "l3_prmsn_table"]
    assert tables
    assert all("표 열" in c["text"] for c in tables)  # 허가 상세 표: 나뉜 조각마다 열 이름 줄을 반복한다
    heads = [c for c in tables if not c.get("parent_id")]  # 같은 조항의 첫 표 조각(build_corpus_l3.py: 이어지는 조각이 첫 조각을 가리킨다)
    assert heads
    for c in tables:
        if c.get("parent_id"):
            p = idx.get(c["parent_id"])
            assert p is not None and p["chunk_kind"] == "l3_prmsn_table" and not p.get("parent_id")
            assert (p["item_seq"], p["section"]) == (c["item_seq"], c["section"])


# ------------------------------------------------------------------ 2. 메타데이터 사전 필터 검색(실데이터, 위반 0)
META_CASES = [
    ("doc_type", ChunkFilter(doc_types=frozenset({"고시"})), "임부금기 등급 정의", "고시"),
    ("notice_no", ChunkFilter(notice_no="20260052"), "병용금기 성분", "20260052"),
    ("base_date", ChunkFilter(base_date="2026-07-31"), "병용금기 사유", "2026-07-31"),
]


@real
@pytest.mark.parametrize(("field", "flt", "query", "value"), META_CASES, ids=[c[0] for c in META_CASES])
def test_metadata_filter_search_on_real_corpus(idx, field, flt, query, value):
    cand = idx.candidates(flt)
    assert cand and all(idx.chunks[i].get(field) == value for i in cand)  # 후보 범위 자체가 조건과 같다
    assert len(cand) == sum(1 for c in idx.chunks if c.get(field) == value)  # 빠진 청크도 없다
    hits = idx.search(query, flt, top_k=10)
    assert len(hits) == 10 and all(h.chunk.get(field) == value for h in hits)


# ------------------------------------------------------------------ 3. 연결 메타데이터
@real
def test_no_dangling_parent_or_refs_on_real_corpus(idx):
    assert idx.dangling_refs() == []
    assert sum(1 for c in idx.chunks if c.get("parent_id")) > 0 and sum(1 for c in idx.chunks if c.get("refs")) > 0


@real
def test_article_annex_mentions_link_to_annex_table(idx):
    tables = {n: next(c["chunk_id"] for c in idx.chunks if c["chunk_kind"] == f"l1_bupyo{n}_table") for n in (1, 2, 3)}
    arts = [c for c in idx.chunks if c["chunk_kind"].startswith("l1_notice") and ANNEX_RE.search(c["text"])]
    assert len(arts) == 3  # 제4조·제5조·제6조("별표 N과 같다")
    for a in arts:
        for n in {int(m) for m in ANNEX_RE.findall(a["text"])}:
            assert tables[n] in a["refs"]  # 조문의 "별표 N" 표현 → 별표 N 표 청크
            got = {e.chunk["chunk_id"] for e in expand_chunks(idx, [a]) if e.relation == "ref"}
            assert tables[n] in got  # 코드가 붙인다(임베딩 추측 아님)


@real
def test_annex_row_expands_to_table_and_article(idx):
    row = next(c for c in idx.chunks if c["chunk_kind"] == "l1_bupyo3_row")
    kinds = [(e.relation, e.chunk["chunk_kind"]) for e in expand_chunks(idx, [row])]
    assert kinds[:2] == [("parent", "l1_bupyo3_table"), ("parent", "l1_notice_article")]  # 행 → 표 → 근거 조문(제6조)


@real
def test_pair_id_lookup_equals_full_scan_on_real_corpus(idx):
    pairs = sorted({c["pair_id"] for c in idx.chunks if c.get("pair_id")})
    assert pairs
    for p in pairs[:: max(1, len(pairs) // 200)]:
        scan = {c["chunk_id"] for c in idx.chunks if c.get("pair_id") == p}
        got = {h.chunk["chunk_id"] for h in idx.search("", ChunkFilter(pair_ids=frozenset({p})), top_k=50)}
        assert got == scan and all(idx.chunks[i]["chunk_kind"] == "l2_combo" for i in idx.candidates(ChunkFilter(pair_ids=frozenset({p}))))


# ------------------------------------------------------------------ 4. 연도·부처 필터(RFP-04-01 A, 합성, 항상 실행)
MFDS, KIDS = "식품의약품안전처", "한국의약품안전관리원"


@pytest.fixture(scope="module")
def ym_idx() -> CorpusIndex:
    return CorpusIndex([
        {"chunk_id": "a", "layer": "L1", "issuer": MFDS, "year": 2026, "notice_no": "20260052", "text": "고시 병용금기"},
        {"chunk_id": "b", "layer": "L2", "issuer": KIDS, "year": 2025, "notice_no": "20250001", "text": "고시 병용금기"},
        {"chunk_id": "c", "layer": "L1", "issuer": MFDS, "year": None, "notice_no": "20260052", "text": "고시 병용금기"},  # 연도 빈 칸
        {"chunk_id": "d", "layer": "L3", "issuer": MFDS, "year": "2026", "text": "고시 병용금기"},  # 문자열 연도도 같은 키
        {"chunk_id": "e", "layer": "L3", "issuer": "", "text": "고시 병용금기"},  # year 칸 없음·부처 빈 칸
    ])


def _ids(idx: CorpusIndex, flt: ChunkFilter) -> set[str]:
    return {idx.chunks[i]["chunk_id"] for i in idx.candidates(flt)}


def test_year_filter_excludes_empty_year(ym_idx):
    assert _ids(ym_idx, ChunkFilter(years=frozenset({2026}))) == {"a", "d"}  # c(None)·e(칸 없음)는 걸리지 않는다
    assert _ids(ym_idx, ChunkFilter(years=frozenset({2025, 2026}))) == {"a", "b", "d"}  # 한 칸 안은 OR
    assert _ids(ym_idx, ChunkFilter(years=frozenset({1999}))) == set()
    assert ym_idx.search("고시", ChunkFilter(years=frozenset({2026})), top_k=10)  # search 경로도 동작


def test_issuer_filter_exact_match(ym_idx):
    assert _ids(ym_idx, ChunkFilter(issuers=frozenset({MFDS}))) == {"a", "c", "d"}  # 빈 부처(e)는 걸리지 않는다
    assert _ids(ym_idx, ChunkFilter(issuers=frozenset({"식약처"}))) == set()  # 부분 일치 아님
    assert _ids(ym_idx, ChunkFilter(issuers=frozenset({MFDS, KIDS}))) == {"a", "b", "c", "d"}


def test_year_issuer_and_other_fields_are_and(ym_idx):
    assert _ids(ym_idx, ChunkFilter(years=frozenset({2026}), issuers=frozenset({MFDS}), layers=frozenset({"L1"}))) == {"a"}
    hits = ym_idx.search("병용금기", ChunkFilter(years=frozenset({2026}), issuers=frozenset({MFDS})), top_k=10)
    assert {h.chunk["chunk_id"] for h in hits} == {"a", "d"} and all(ym_idx.matches(h.chunk, ChunkFilter(years=frozenset({2026}))) for h in hits)


def test_year_issuer_are_weak_filters_remotely():
    """연도·부처만 있으면 SQL에 걸지 않는다(인덱스 없는 약한 필터, 후필터는 `CorpusIndex` 후보 집합이 맡는다)."""
    for flt in (ChunkFilter(years=frozenset({2026})), ChunkFilter(issuers=frozenset({MFDS})),
                ChunkFilter(years=frozenset({2026}), issuers=frozenset({MFDS}), layers=frozenset({"L1"}))):
        assert not cr.has_strong_filter(flt) and cr.build_where(flt) == ([], [])


def test_year_issuer_sql_with_strong_filter_uses_params():
    flt = ChunkFilter(notice_no="20260052", years=frozenset({2026, 2025}), issuers=frozenset({"x'; DROP TABLE t;--", MFDS}))
    conds, params = cr.build_where(flt)
    sql = " AND ".join(conds)
    assert "year = ANY (%s::smallint[])" in conds and "issuer = ANY (%s)" in conds
    assert "DROP" not in sql and "2026" not in sql  # 값은 전부 파라미터
    assert [2025, 2026] in params and sorted([MFDS, "x'; DROP TABLE t;--"]) in params
    assert sql.count("%s") == len(params)


@real
def test_year_and_issuer_filters_on_real_corpus(idx):
    n2026 = sum(1 for c in idx.chunks if c.get("year") is not None and int(c["year"]) == 2026)
    cand = idx.candidates(ChunkFilter(years=frozenset({2026})))
    assert len(cand) == n2026 and all(idx.chunks[i].get("year") is not None for i in cand)  # 빈 연도 청크는 제외
    for issuer in {c.get("issuer") for c in idx.chunks if c.get("issuer")}:
        got = idx.candidates(ChunkFilter(issuers=frozenset({issuer})))
        assert len(got) == sum(1 for c in idx.chunks if c.get("issuer") == issuer)
        hits = idx.search("병용금기", ChunkFilter(issuers=frozenset({issuer})), top_k=10)
        assert hits and all(h.chunk["issuer"] == issuer for h in hits)
