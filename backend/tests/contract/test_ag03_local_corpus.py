"""AG-03 로컬 실코퍼스 시험. `data/mock/corpus/*.jsonl`이 없으면 skip한다(합성 시험은 항상 실행). 외부 호출 없음."""

from __future__ import annotations

import pytest

from app.agent.tools.context import ToolContext
from app.agent.tools.corpus import CORPUS_FILES, DEFAULT_CORPUS_DIR, ChunkFilter, load_local_corpus
from app.agent.tools.registry import invoke

pytestmark = pytest.mark.skipif(not all((DEFAULT_CORPUS_DIR / n).is_file() for n in CORPUS_FILES), reason="로컬 코퍼스(data/mock/corpus) 없음")


@pytest.fixture(scope="module")
def idx():
    return load_local_corpus()


@pytest.fixture(scope="module")
def c(idx):
    return ToolContext(drug_dict=None, corpus=idx)


def test_no_dangling_parent_or_refs(idx):
    assert idx.dangling_refs() == []


def test_notice_definition_found_with_notice_no(c):
    out = invoke("search_notice", {"query": "임부금기 1등급 정의 원칙적으로 사용금지", "scope": "article"}, c)
    assert out["contract_violations"] == []
    top = out["items"][0]
    assert top["status"] == "FOUND" and top["layer"] == "L1" and top["notice_no"] and top["locator"].startswith("제3조")


def test_reason_pair_bulk_from_real_l2(idx, c):
    pair = next(ch["pair_id"] for ch in idx.chunks if ch.get("pair_id"))
    out = invoke("search_reason", {"pair_ids": [pair]}, c)
    assert out["contract_violations"] == [] and out["items"][0]["status"] == "FOUND" and all(i["pair_id"] == pair for i in out["items"] if i["status"] == "FOUND")


def test_reason_m_grade_verbatim_in_real_data(idx, c):
    m = next((ch for ch in idx.chunks if ch["chunk_kind"] == "l2_preg" and "M등급" in ch["text"]), None)
    if m is None:
        pytest.skip("M 등급 청크 없음")
    out = invoke("search_reason", {"ingr_codes": [m["ingr_codes"][0]], "kinds": ["pregnancy"]}, c)
    assert any(i["text"] == m["text"] for i in out["items"])  # 원문 그대로


def test_label_section_whole_for_real_item(idx, c):
    ch = next(x for x in idx.chunks if x["chunk_kind"] == "l3_prmsn_para" and len(idx.section_siblings(x)) > 2)
    out = invoke("search_label", {"item_seq": ch["item_seq"], "section": "주의사항", "top_k": 1}, c)
    assert out["contract_violations"] == []
    assert {i["layer"] for i in out["items"] if i["status"] == "FOUND"} == {"L3"}


def test_prefilter_never_leaks_other_layers_on_real_data(idx):
    flt = ChunkFilter(layers=frozenset({"L2"}), chunk_kinds=frozenset({"l2_combo"}))
    hits = idx.search("출혈 위험 증가", flt, top_k=10)
    assert len(hits) == 10 and all(idx.matches(h.chunk, flt) for h in hits)
