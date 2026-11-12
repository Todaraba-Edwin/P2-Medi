"""AG-03 하이브리드 정답 사례 스크립트(`scripts/ag03_hybrid_case.py`) 오프라인 시험. 네트워크·원격 DB·로컬 data/ 파일 없이 돈다."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ag03_hybrid_case import (  # noqa: E402
    INF,
    LocalVectors,
    build_queries,
    evaluate,
    rank_of,
    short_name,
    summarize,
    text_hash,
)

from app.agent.tools.corpus import ChunkFilter, CorpusIndex  # noqa: E402


def _chunk(cid: str, text: str, **kw: object) -> dict:
    base = {"chunk_id": cid, "chunk_kind": "l3_eyak_section", "layer": "L3", "doc_type": "", "text": text, "ingr_codes": [], "ingr_names": [],
            "item_seq": "", "item_name": "", "section": "", "parent_id": None, "refs": [], "pair_id": None, "notice_no": "", "base_date": ""}
    base.update(kw)
    return base


def test_short_name_and_hash() -> None:
    assert short_name("케이메트서방정(메트포르민염산염)") == "케이메트서방정"
    assert text_hash("a") == text_hash("a") != text_hash("b")


def test_rank_of() -> None:
    assert rank_of(["a", "b", "c"], {"c", "z"}) == 3
    assert rank_of(["a"], {"x"}) is None


def _mini_index() -> CorpusIndex:
    chunks = []
    for i in range(12):
        chunks.append(_chunk(f"e{i}", f"[약{i}정 · 효능] 두통 치통 생리통 증상 완화{i}", item_seq=f"S{i}", item_name=f"약{i}정(성분)", section="효능"))
    return CorpusIndex(chunks)


def test_build_queries_deterministic_and_gold_valid() -> None:
    idx = _mini_index()
    per = {"eyak_daily": 5, "eyak_kw": 3, "preg_daily": 0, "combo_daily": 0, "prmsn_kw": 0}
    a, b = build_queries(idx, seed=1, per_family=per), build_queries(idx, seed=1, per_family=per)
    assert a == b
    assert {q["family"] for q in a} <= {"eyak_daily", "eyak_kw"}
    ids = {c["chunk_id"] for c in idx.chunks}
    for q in a:
        assert q["gold"] and set(q["gold"]) <= ids
    assert any("어디에 쓰는 약" in q["query"] for q in a)


def test_evaluate_flags_hybrid_win_and_summary() -> None:
    chunks = [
        _chunk("A", "알파 베타 알파 베타 알파 베타"),
        _chunk("G", "알파 베타 감마 델타 입실론 제타 에타"),
        _chunk("B", "오메가 시그마 파이 카이 프시"),
    ]
    idx = CorpusIndex(chunks)

    def vec(query: str, *, k: int, filters: ChunkFilter) -> list[tuple[str, float]]:  # noqa: ARG001
        return [("B", 0.9), ("G", 0.8)][:k]

    q = [{"id": "t-01", "family": "t", "query": "알파 베타", "gold": ["G"]}]
    rows = evaluate(idx, q, vec)
    r = rows[0]
    assert r["rank_vector"] == 2
    assert r["rank_bm25"] == 2  # A가 어휘 1위
    assert r["rank_hybrid"] == 1 and r["hybrid_beats_both"] is True
    s = summarize(rows)
    assert s["hybrid_beats_both"] == 1 and s["top1"]["hybrid"] == 1 and s["top1"]["vector"] == 0
    # 단독 방식이 이미 1위면 우위가 아니다
    r2 = evaluate(idx, [{"id": "t-02", "family": "t", "query": "알파 베타", "gold": ["A"]}], vec)[0]
    assert r2["rank_bm25"] == 1 and r2["hybrid_beats_both"] is False
    assert INF > 10**6


def test_local_vectors_ranks_by_dot_and_counts_missing() -> None:
    chunks = [_chunk("x", "t1"), _chunk("y", "t2"), _chunk("z", "t3-없음")]
    idx = CorpusIndex(chunks)
    rows = {text_hash("t1"): 0, text_hash("t2"): 1}
    mat = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    lv = LocalVectors(mat, rows, idx, {"q": [0.1, 1.0]})
    assert lv.n_missing == 1
    out = lv("q", k=5, filters=ChunkFilter())
    assert [c for c, _ in out] == ["y", "x"]
