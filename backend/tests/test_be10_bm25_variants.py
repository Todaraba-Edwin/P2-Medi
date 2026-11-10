"""BE-10 BM25 변형 비교 시험: 토크나이저 단위 시험과 합성 소사전에서 단어 단위 vs n-gram 차이 재현. 파일·네트워크 없음."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import bm25_variants as V  # noqa: E402

from app.tools.drug_dict import BM25  # noqa: E402

PRODUCTS = ["타이레놀정500밀리그램", "타이레놀 8시간 이알서방정", "게보린정", "판콜에이내복액", "어린이부루펜시럽"]


def _index(name: str) -> tuple[BM25, V.Tokenizer]:
    qtok, ptok, ing = V._variants()[name]
    docs = V.build_docs(_Dict(), ptok, ing)
    return BM25(docs), qtok


class _Dict:
    products = [{"name": n} for n in PRODUCTS]
    ingredients = [{"names": ["Acetaminophen", "아세트아미노펜"]}]


def test_word_tokens_split_on_space_and_punct_after_same_preprocessing() -> None:
    assert V.word_tokens("타이레놀 8시간-이알서방정(수출명 X)") == ["타이레놀", "8시간", "이알서방정"]
    assert V.word_tokens("정제 500밀리그램") == ["정제", "500mg"]  # 단위 통일은 현재 구현과 같다
    assert V.word_tokens("") == []


def test_ngram_tokens_match_current_implementation() -> None:
    assert V.ngram_tokens((2,))("A b") == ["ab"]  # 길이가 n보다 짧으면 키 전체
    assert V.ngram_tokens((2, 3))("타이레놀") == ["타이", "이레", "레놀", "타이레", "이레놀"]


def test_spacing_variant_word_fails_ngram_succeeds() -> None:
    q = "게 보린정"  # 띄어쓰기 변형: 단어 토큰 [게, 보린정]은 사전 토큰 [게보린정]과 하나도 겹치지 않는다
    bm_w, qw = _index("word")
    bm_n, qn = _index("char2")
    assert V.rank(bm_w, qw(q)) == []
    top = V.rank(bm_n, qn(q))
    assert top and top[0] == PRODUCTS.index("게보린정")


def test_typo_variant_word_fails_ngram_succeeds() -> None:
    q = "판콜에이내복엑"  # 받침 치환 오탈자
    bm_w, qw = _index("word")
    bm_n, qn = _index("char2")
    assert V.rank(bm_w, qw(q)) == []
    assert V.rank(bm_n, qn(q))[0] == PRODUCTS.index("판콜에이내복액")


def test_exact_multiword_name_word_variant_succeeds() -> None:
    bm_w, qw = _index("word")
    assert V.rank(bm_w, qw("타이레놀 8시간 이알서방정"))[0] == 1


def test_ingredient_docs_follow_products_in_both_variants() -> None:
    bm_w, qw = _index("word")
    assert V.rank(bm_w, qw("아세트아미노펜"))[0] == len(PRODUCTS)
    assert bm_w.n == len(PRODUCTS) + 1


def test_pick_cases_cycles_types_and_respects_limit() -> None:
    queries = [{"id": f"t{i}", "type": t, "query": f"q{i}"} for i, t in enumerate(["typo_drop", "typo_drop", "spacing"])]
    golds = [{0}, {0}, {0}]
    rankings = {"a": [[0], [0], [0]], "b": [[1], [1], [1]]}
    dd = _Dict()
    dd.products = [{"name": "p0"}, {"name": "p1"}]  # type: ignore[assignment]
    got = V.pick_cases(dd, queries, golds, rankings, "a", "b", 2)  # type: ignore[arg-type]
    assert [c["type"] for c in got] == ["typo_drop", "spacing"]
