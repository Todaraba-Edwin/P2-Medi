"""AG-03 코퍼스 계층: 사전 필터·하이브리드 RRF·연결 청크. 합성 소코퍼스(항상 실행)."""

from __future__ import annotations

import pytest
from ag03_synth import IBU, PAIR_IBU_WAR, SEQ_EASY, SEQ_RX, WAR, FakeVector, mk, synth_index

from app.agent.tools.corpus import ChunkFilter, CorpusIndex, expand_chunks, rrf_fuse, tokenize


@pytest.fixture(scope="module")
def idx():
    return synth_index()


def ids(hits):
    return [h.chunk["chunk_id"] for h in hits]


# ------------------------------------------------------------------ 1. 사전 필터
def test_prefilter_ingr_codes_restricts_scope(idx):
    hits = idx.search("출혈", ChunkFilter(ingr_codes=frozenset({WAR}), layers=frozenset({"L2"})), top_k=10)
    assert hits and all(WAR in h.chunk["ingr_codes"] and h.chunk["layer"] == "L2" for h in hits)


def test_prefilter_ingr_names_substring_for_l1_rows(idx):
    hits = idx.search("임부금기 등급", ChunkFilter(layers=frozenset({"L1"}), ingr_names=frozenset({"enalap"})), top_k=10)
    assert ids(hits) == ["l1r-a3-1"]


def test_layer_filter_excludes_other_layers(idx):
    for layer in ("L1", "L2", "L3"):
        hits = idx.search("임부금기 출혈 주의", ChunkFilter(layers=frozenset({layer})), top_k=20)
        assert hits and {h.chunk["layer"] for h in hits} == {layer}


def test_item_seq_and_section_filters(idx):
    hits = idx.search("", ChunkFilter(item_seq=SEQ_RX, section_prefix="UD"), top_k=10)
    assert ids(hits) == ["l3p-ud-1"] and hits[0].via == "filter"
    hits = idx.search("술과 함께", ChunkFilter(item_seq=SEQ_EASY, sections=frozenset({"상호작용"})), top_k=10)
    assert ids(hits) == ["l3e-int"]


def test_notice_no_and_base_date_filters(idx):
    hits = idx.search("병용금기 사유", ChunkFilter(layers=frozenset({"L2"}), notice_no="20210001"), top_k=10)
    assert ids(hits) == ["l2c-2"]
    assert idx.search("병용금기", ChunkFilter(base_date="1999-01-01"), top_k=10) == []


@pytest.mark.parametrize("flt", [
    ChunkFilter(layers=frozenset({"L1"})), ChunkFilter(ingr_codes=frozenset({IBU})), ChunkFilter(item_seq=SEQ_RX),
    ChunkFilter(pair_ids=frozenset({PAIR_IBU_WAR})), ChunkFilter(layers=frozenset({"L3"}), section_prefix="NB"),
    ChunkFilter(chunk_kinds=frozenset({"l2_preg"})), ChunkFilter(doc_types=frozenset({"e약은요"})),
])
def test_filter_violations_are_zero(idx, flt):
    hits = idx.search("출혈 임부금기 주의 술 병용금기", flt, top_k=20)
    assert all(idx.matches(h.chunk, flt) for h in hits)


def test_top_k_count_and_empty_unscoped_query(idx):
    assert len(idx.search("임부금기", ChunkFilter(), top_k=3)) == 3
    assert idx.search("", ChunkFilter(layers=frozenset({"L2"})), top_k=5) == []  # 식별 조건 없는 빈 질의는 근거로 세우지 않는다
    assert idx.search("임부금기", ChunkFilter(ingr_codes=frozenset({"999999ZZZ"})), top_k=5) == []


def test_tokenize_word_bigrams():
    assert tokenize("A b 임부금기") == ["a", "b", "임부", "부금", "금기"]


# ------------------------------------------------------------------ 2. 하이브리드 RRF
def test_rrf_fuse_values_depth_and_tie_order():
    f = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert [x[0] for x in f][:2] == ["a", "b"]  # 동점은 먼저 나온 순서
    assert f[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert [x[0] for x in rrf_fuse([["a", "b", "c"]], k=60, depth=2)] == ["a", "b"]


def test_both_rankings_rank_first_and_via_both(idx):
    vec = FakeVector({"출혈": ["l2c-2", "l2c-1"]})
    flt = ChunkFilter(layers=frozenset({"L2"}), pair_ids=frozenset({PAIR_IBU_WAR}))
    hits = idx.search("위장관 출혈", flt, top_k=2, vector_fn=vec)
    assert hits[0].chunk["chunk_id"] == "l2c-2" and hits[0].via == "both"
    assert vec.calls and vec.calls[0][2] == flt  # 필터를 그대로 주입 함수에 넘긴다


def test_hybrid_beats_bm25_alone_when_wording_differs(idx):
    q = "함께 복용하면 피가 멎지 않는 이유"  # 청크 문구와 어휘가 겹치지 않는다
    flt = ChunkFilter(ingr_codes=frozenset({WAR, IBU}), layers=frozenset({"L2"}), chunk_kinds=frozenset({"l2_combo"}))
    assert ids(idx.search(q, flt, top_k=3)) == []  # BM25 단독은 근거를 못 찾는다
    hits = idx.search(q, flt, top_k=3, vector_fn=FakeVector({"피가": ["l2c-1", "l2c-2"]}))
    assert ids(hits)[:1] == ["l2c-1"] and {h.via for h in hits} == {"vector"}  # 식별 조건이 있어 의미 검색만으로도 통과


def test_vector_only_hit_without_lexical_or_id_scope_is_dropped(idx):
    vec = FakeVector({"전혀관련없는": ["l3e-eff"]}, always=["l1r-a2-1"])
    assert idx.search("전혀관련없는 질의", ChunkFilter(), top_k=5, vector_fn=vec) == []  # 벡터는 항상 k개를 주므로 코드 검사로 막는다


def test_vector_ids_outside_prefilter_are_dropped(idx):
    vec = FakeVector({"출혈": ["l3p-nb-1", "l2p-war", "l1r-a3-2"]})  # 후보 밖(L3·L1)이 섞여 온다
    hits = idx.search("출혈", ChunkFilter(layers=frozenset({"L2"}), ingr_codes=frozenset({WAR})), top_k=10, vector_fn=vec)
    assert hits and all(h.chunk["layer"] == "L2" for h in hits)


def test_no_vector_fn_is_bm25_only(idx):
    hits = idx.search("출혈 위험", ChunkFilter(layers=frozenset({"L2"})), top_k=3)
    assert hits and all(h.via == "bm25" and h.vector_rank is None for h in hits)


# ------------------------------------------------------------------ 3. 연결 청크
def test_expand_parent_chain_and_refs(idx):
    row = idx.get("l1r-a3-1")
    out = expand_chunks(idx, [row])
    rel = {e.chunk["chunk_id"]: e.relation for e in out}
    assert rel["l1t-annex3"] == "parent" and rel["l1n-art6"] == "parent"  # 행 → 표 → 조문


def test_expand_ref_article_to_annex(idx):
    out = expand_chunks(idx, [idx.get("l1n-art3")])
    assert [(e.chunk["chunk_id"], e.relation) for e in out][:1] == [("l1t-annex3", "ref")]


def test_expand_same_pair_chunks(idx):
    out = expand_chunks(idx, [idx.get("l2c-1")])
    assert [(e.chunk["chunk_id"], e.relation) for e in out] == [("l2c-2", "pair")]


def test_expand_whole_section_in_paragraph_order(idx):
    out = expand_chunks(idx, [idx.get("l3p-nb-3")])
    assert [e.chunk["chunk_id"] for e in out] == ["l3p-nb-1", "l3p-nb-2", "l3p-nb-4"] and {e.relation for e in out} == {"section"}


def test_expand_dedup_cap_and_no_self(idx):
    hits = [idx.get("l3p-nb-1"), idx.get("l3p-nb-2")]
    out = expand_chunks(idx, hits)
    got = [e.chunk["chunk_id"] for e in out]
    assert len(got) == len(set(got)) and not ({"l3p-nb-1", "l3p-nb-2"} & set(got))
    assert len(expand_chunks(idx, [idx.get("l3p-nb-1")], max_total=1)) == 1


def test_dangling_refs_zero_and_detected():
    assert synth_index().dangling_refs() == []
    bad = CorpusIndex([mk("x1", "l1_notice_article", "L1", "t", parent_id="없는부모", refs=["없는참조"])])
    assert bad.dangling_refs() == [("x1", "없는부모"), ("x1", "없는참조")]
    assert expand_chunks(bad, [bad.get("x1")]) == []  # 끊어진 참조는 건너뛴다(예외 없음)
