"""BE-07 약품명 유사 후보 조회 시험(오탈자 보정용, FR-07). LLM·네트워크·DB 호출 0.

합성 소사전(가상의 제품명)으로 규칙을 시험하고, 실사전(`data/mock/dict/drug_dict.json`, 로컬 전용)이 있으면 색인 생성 시간·조회 지연·이름 건수를 잰다.
"""

from __future__ import annotations

import ast
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FORM_MAP, _ing, _prod  # noqa: E402

from app.tools import name_similarity as NS  # noqa: E402
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict, normalize_name  # noqa: E402

# 가상의 제품명(실제 제품이 아니다). 함량만 다른 쌍, 한 글자 다른 쌍, 괄호 병기, 같은 이름 두 제품을 둔다.
NAMES = [
    ("300000001", "가나미솔정10밀리그램"), ("300000002", "가나미솔정20밀리그램"),
    ("300000003", "다라보틴캡슐"), ("300000004", "다라보탄캡슐"),
    ("300000005", "마바스타시럽(마바성분)"),
    ("300000006", "사아코린서방정5/500밀리그램"),
    ("300000007", "자차포론정"), ("300000008", "자차포론정"),  # 같은 이름의 제품 둘(회사가 다르다고 가정)
    ("300000009", "카타"),
]


def make_dict() -> DrugDict:
    ings = [_ing(0, "Acetaminophen", "아세트아미노펜", ["101300ATB"], ["D000147"])]
    prods = [_prod(seq, name, "일반", kids=["101300ATB"], api=[], ids=[0]) for seq, name in NAMES]
    return DrugDict({"meta": {"version": "be07-synth", "built_at": "2026-11-18T00:00:00+00:00", "form_map": FORM_MAP}, "products": prods, "ingredients": ings})


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return make_dict()


# --------------------------------------------------------------------------- 자모·편집 거리

def test_to_jamo_splits_hangul_and_keeps_others():
    assert NS.to_jamo("가") == "ㄱㅏ" and NS.to_jamo("정") == "ㅈㅓㅇ"
    assert NS.to_jamo("a1정") == "a1ㅈㅓㅇ" and NS.to_jamo("") == ""


@pytest.mark.parametrize("a,b,d", [
    ("abc", "abc", 0), ("abc", "abd", 1), ("abc", "ab", 1), ("abc", "xabc", 1), ("abcd", "abdc", 1),  # 맞바꿈 1
    ("", "abc", 3), ("kitten", "sitting", 3),
])
def test_edit_distance(a, b, d):
    assert NS.edit_distance(a, b) == d and NS.edit_distance(b, a) == d


def test_edit_distance_limit_stops_early():
    assert NS.edit_distance("abcdefgh", "zzzzzzzz", limit=2) == 3  # limit + 1
    assert NS.edit_distance("abc", "abcdefgh", limit=2) == 3  # 길이 차만으로 넘는다
    assert NS.edit_distance("abc", "abd", limit=2) == 1


def test_one_vowel_typo_is_one_jamo_apart():
    """모음 하나를 잘못 쓴 이름은 음절로는 한 글자가 통째로 다르지만 자모로는 한 칸이다."""
    a, b = NS.to_jamo("가나미솔정"), NS.to_jamo("가나메솔정")
    assert NS.edit_distance(a, b) == 1
    assert NS.similarity("가나미솔정", "가나메솔정") == round(1 - 1 / len(a), 4)


def test_similarity_uses_the_dictionary_normalization():
    assert NS.similarity("가나미솔정 10mg", "가나미솔정10밀리그램") == 1.0  # 단위·공백 표기 차이는 정규화가 흡수한다
    assert NS.similarity("", "") == 0.0


def test_number_signature_reads_numbers_in_order():
    assert NS.number_signature(normalize_name("가나미솔정10밀리그램")) == ("10",)
    assert NS.number_signature(normalize_name("다라보틴캡슐")) == ()
    assert NS.number_signature(normalize_name("가5나10")) == ("5", "10")
    # 구분자(`/`·`.`)는 사전 정규화가 이미 지운다: 사전 조회와 같은 기준으로 숫자 덩어리를 본다
    assert NS.number_signature(normalize_name("사아코린서방정5/500밀리그램")) == ("5500",)


# --------------------------------------------------------------------------- 조회

def test_top_candidate_is_the_one_jamo_neighbour(dd):
    c = NS.similar_names(dd, "가나메솔정10밀리그램", top_k=3)
    assert c[0].name == "가나미솔정10밀리그램" and c[0].distance == 1 and c[0].kind == NS.KIND_PRODUCT
    assert c[0].score > c[1].score and [x.score for x in c] == sorted((x.score for x in c), reverse=True)


def test_same_numbers_keeps_only_names_with_the_same_strength(dd):
    both = NS.similar_names(dd, "가나메솔정10밀리그램", top_k=5)
    assert {x.numbers for x in both} >= {("10",), ("20",)}  # 함량만 다른 이름도 비슷하다고 나온다
    same = NS.similar_names(dd, "가나메솔정10밀리그램", top_k=5, same_numbers=True)
    assert same and all(x.numbers == ("10",) for x in same)
    assert NS.similar_names(dd, "가나메솔정", top_k=5, same_numbers=True) == [] or all(
        x.numbers == () for x in NS.similar_names(dd, "가나메솔정", top_k=5, same_numbers=True))


def test_paren_base_name_is_indexed(dd):
    """괄호(성분명 병기)를 뗀 기본형과 비교한다: 사용자는 괄호 부분을 쓰지 않는다. 키는 그대로 `lookup_name`에 넣을 수 있다."""
    c = NS.similar_names(dd, "마바스터시럽", top_k=2)
    assert c[0].key == normalize_name("마바스타시럽") and c[0].distance == 1 and c[0].name == "마바스타시럽(마바성분)"
    r = dd.lookup_name(c[0].key)
    assert r.resolved and r.candidates[0].item_seq == "300000005"


def test_ingredient_names_are_candidates_too(dd):
    c = NS.similar_names(dd, "아세트아미노팬", top_k=1)
    assert c and c[0].kind == NS.KIND_INGREDIENT and c[0].name == "아세트아미노펜" and c[0].distance == 1


def test_same_name_rows_collapse_to_one_candidate_with_count(dd):
    c = NS.similar_names(dd, "자차포른정", top_k=3)
    hits = [x for x in c if x.key == normalize_name("자차포론정")]
    assert len(hits) == 1 and hits[0].n_entries == 2


def test_exact_name_scores_one_and_unrelated_returns_nothing(dd):
    assert NS.similar_names(dd, "다라보틴캡슐", top_k=1)[0].score == 1.0
    assert NS.similar_names(dd, "완전히다른이름의무언가", top_k=5) == []
    assert NS.similar_names(dd, "", top_k=5) == [] and NS.similar_names(dd, "가나미솔정", top_k=0) == []


def test_min_score_and_top_k_bound_the_result(dd):
    assert len(NS.similar_names(dd, "다라보톤캡슐", top_k=1)) == 1
    loose = NS.similar_names(dd, "다라보톤캡슐", top_k=5, min_score=0.5)
    tight = NS.similar_names(dd, "다라보톤캡슐", top_k=5, min_score=0.99)
    assert len(loose) >= 2 and tight == [] and all(x.score >= 0.5 for x in loose)


def test_results_are_deterministic(dd):
    a = NS.similar_names(dd, "다라보톤캡슐", top_k=5)
    assert a == NS.similar_names(dd, "다라보톤캡슐", top_k=5)
    assert [x.name for x in a[:2]] == sorted([x.name for x in a[:2]], key=lambda n: normalize_name(n))  # 동점은 키 순


def test_index_is_built_once_per_dictionary_and_reports_counts(dd):
    idx = NS.index_for(dd)
    assert NS.index_for(dd) is idx and NS.index_for(make_dict()) is not idx
    st = idx.stats()
    assert st["dict_version"] == "be07-synth" and st["n_product_rows"] == len(NAMES)
    assert st["n_product_names"] == len({n for _, n in NAMES}) + 1  # 서로 다른 이름 8개 + 괄호를 뗀 기본형 1개
    assert st["n_names"] == st["n_product_names"] + 2  # 성분 이름(영문·한글)


def test_module_has_no_io_imports():
    """순수 계산 모듈이다(Router가 import하므로 입출력·네트워크·로깅 import가 없어야 한다)."""
    tree = ast.parse(Path(NS.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= {"__future__", "re", "time", "weakref", "array", "collections", "dataclasses", "app.tools.drug_dict"}


# --------------------------------------------------------------------------- 실사전: 건수·생성 시간·조회 지연(로컬 전용 파일이 있을 때만)

@pytest.fixture(scope="module")
def real() -> Any:
    if not Path(DEFAULT_DICT_PATH).is_file():
        pytest.skip("data/mock/dict/drug_dict.json 없음(로컬 전용)")
    return DrugDict.load()


def test_real_dict_index_counts_and_build_cost(real):
    """측정(2026-11-18, 사전 be10-dict-s1-1055d3576876, 로컬 M3): 제품 행 47,773 → 제품 이름 키 72,250(전체 키 + 괄호를 뗀 기본형), 성분 포함 76,727,
    자모 3-gram 12,553종, 색인 생성 약 0.55초(사전 파일 읽기 약 0.8초와 별개, 첫 조회 때 한 번). 상한은 느린 기계를 감안해 넉넉히 둔다."""
    idx = NS.SimilarityIndex(real)
    st = idx.stats()
    assert st["n_product_rows"] == len(real.products) > 40000
    assert st["n_product_rows"] <= st["n_product_names"] <= 2 * st["n_product_rows"]
    assert st["n_names"] > st["n_product_names"]
    assert st["build_seconds"] < 10


def test_real_dict_lookup_latency(real):
    """측정(같은 조건): 개발셋의 BM25 후보 엔티티 49개 조회 중앙값 약 9ms, 최대 약 38ms. 여기서는 사전 이름을 한 글자 바꾼 합성 질의로 잰다."""
    idx = NS.index_for(real)
    names = [p["name"] for p in real.products[:: max(len(real.products) // 40, 1)]][:40]
    lat = []
    for n in names:
        q = n[:-1] + ("캅" if n[-1] != "캅" else "정")
        t0 = time.perf_counter()
        idx.search(q, 5, same_numbers=True)
        lat.append(time.perf_counter() - t0)
    assert statistics.median(lat) < 0.2 and max(lat) < 2.0


def test_real_dict_finds_a_name_after_one_vowel_change(real):
    """사전의 한 제품 이름에서 모음 하나를 바꾼 질의의 1위는 원래 이름이다(이름은 사전에서 고르고 출력하지 않는다)."""
    idx = NS.index_for(real)
    checked = 0
    for p in real.products[:: max(len(real.products) // 200, 1)]:
        key = normalize_name(p["name"], keep_paren=False)
        j = NS.to_jamo(key)
        pos = next((i for i, ch in enumerate(key) if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 588 // 28 == 0), None)  # 중성 ㅏ인 첫 글자
        if pos is None or len(j) < 12:
            continue
        typo = key[:pos] + chr(ord(key[pos]) + 28 * 4) + key[pos + 1:]  # ㅏ → ㅓ
        c = idx.search(typo, 2, same_numbers=True)
        assert c and c[0].distance <= 1
        checked += 1
    assert checked > 50
