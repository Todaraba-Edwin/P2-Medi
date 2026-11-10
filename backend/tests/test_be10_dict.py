"""BE-10 제품·성분 사전 시험. 합성 소규모 재료로 빌더와 조회를 함께 확인한다(큰 파일·네트워크 의존 없음)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary, classify_unmatched  # noqa: E402

from app.tools.drug_dict import (  # noqa: E402
    BM25,
    DrugDict,
    char_ngrams,
    ingredient_key,
    normalize_name,
    split_en_salt,
    split_ko_salt,
)

KIDS = [
    {"product_code": "111111111", "name": "타이레놀정500밀리그람(아세트아미노펜)_(500mg/1정)", "ingr_code": "101301ATB", "ingr_name": "acetaminophen", "entp": "A사"},
    {"product_code": "222222222", "name": "복합콜드정", "ingr_code": "999901ATB",
     "ingr_name": "acetaminophen+pseudoephedrine hydrochloride+chlorpheniramine maleate", "entp": "B사"},
    {"product_code": "333333333", "name": "슈도정(슈도에페드린염산염)_(60mg/1정)", "ingr_code": "100101ATB", "ingr_name": "pseudoephedrine hydrochloride", "entp": "C사"},
]
SNAPS = {
    "prmsn": [
        {"item_seq": "1", "item_name": "타이레놀정500밀리그람", "entp_name": "A사", "spclty_pblc": "일반의약품", "item_ingr_name": "Acetaminophen",
         "edi_code": "111111111", "cancel_name": "정상"},
        {"item_seq": "2", "item_name": "타이레놀8시간이알서방정", "entp_name": "A사", "spclty_pblc": "일반의약품", "item_ingr_name": "Acetaminophen",
         "edi_code": "", "cancel_name": "정상"},
        {"item_seq": "3", "item_name": "동명약", "entp_name": "D사", "spclty_pblc": "전문의약품", "item_ingr_name": "Zzz", "edi_code": "", "cancel_name": "정상"},
        {"item_seq": "4", "item_name": "동명약", "entp_name": "E사", "spclty_pblc": "전문의약품", "item_ingr_name": "Yyy", "edi_code": "", "cancel_name": "정상"},
        {"item_seq": "5", "item_name": "콜드에스정(수출명:ColdS Tab.)", "entp_name": "F사", "spclty_pblc": "일반의약품",
         "item_ingr_name": "Acetaminophen/Pseudoephedrine HCl/Chlorpheniramine Maleate", "edi_code": "", "cancel_name": "정상"},
        {"item_seq": "7", "item_name": "이름만있는약정", "entp_name": "G사", "spclty_pblc": "전문의약품", "item_ingr_name": "", "edi_code": "", "cancel_name": "취하"},
    ],
    "eyak": [{"item_seq": "6", "item_name": "어린이타이레놀현탁액(아세트아미노펜)", "entp_name": "A사"}],
    "detail": [],
    "dur_ingr": [{"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "단일"}],
    "ingr_codes": {},
}


@pytest.fixture(scope="module")
def built():
    return build_dictionary(KIDS, [], SNAPS, {"x": "y"})


@pytest.fixture(scope="module")
def dd(built):
    return DrugDict(built[0])


class TestNormalize:
    def test_export_paren_space_case(self):
        assert normalize_name("콜드에스정(수출명:ColdS Tab.)") == "콜드에스정"
        assert normalize_name("Tylenol  ER") == normalize_name("tylenol-er")
        assert normalize_name("타이레놀정 500밀리그람") == normalize_name("타이레놀정500mg")

    def test_kids_suffix_and_paren(self):
        assert normalize_name("중외5-에프유주(플루오로우라실)_(0.25g/5mL)") == "중외5에프유주플루오로우라실"
        assert normalize_name("뉴론틴정600밀리그램(가바펜틴)", keep_paren=False) == "뉴론틴정600mg"

    def test_salt_shortening_ko(self):
        assert split_ko_salt("슈도에페드린염산염") == ("슈도에페드린", "염산염")
        assert split_ko_salt("에스오메프라졸스트론튬사수화물")[0] == "에스오메프라졸"
        assert split_ko_salt("아세트아미노펜") == ("아세트아미노펜", "")
        assert split_ko_salt("탄산칼슘") == ("탄산칼슘", "")  # 물질 자체 이름은 줄이지 않는다

    def test_salt_shortening_en(self):
        assert split_en_salt("Pseudoephedrine hydrochloride") == ("pseudoephedrine", "hydrochloride")
        assert split_en_salt("esomeprazole magnesium (as esomeprazole)")[0] == "esomeprazole"
        assert ingredient_key("ibuprofen   10g(20mg/mL)") == "ibuprofen"
        assert ingredient_key("슈도에페드린염산염") == ingredient_key("슈도에페드린")


class TestBM25:
    def test_ngram_and_rank(self):
        docs = [char_ngrams(normalize_name(t)) for t in ("타이레놀정", "게보린정", "타이레놀콜드")]
        bm = BM25(docs)
        sc = bm.scores(char_ngrams("타이레놀"))
        assert set(sc) == {0, 2} and sc[0] > 0
        assert bm.scores(char_ngrams("zzz")) == {}

    def test_short_text_is_one_token(self):
        assert char_ngrams("정") == ["정"]


class TestBuild:
    def test_meta_and_materials(self, built):
        meta = built[0]["meta"]
        assert meta["version"].startswith("be10-dict-s1-") and meta["built_at"]
        assert meta["material_sha256"] == {"x": "y"}
        assert meta["materials"]["DUR 품목리스트 CSV(심평원)"].startswith("쓰지 않음")

    def test_link_methods(self, dd):
        by_seq = {p.get("item_seq"): p for p in dd.products}
        assert by_seq["1"]["code_link"] == "edi_code" and by_seq["1"]["code_scope"] == "product"
        assert by_seq["1"]["kids_codes"] == ["101301ATB"]
        assert by_seq["2"]["code_link"] == "ingredient_name" and by_seq["2"]["code_scope"] == "all_forms"
        assert by_seq["5"]["kids_codes"] == ["999901ATB"]  # 복합제는 조합 코드로 이어진다
        assert by_seq["6"]["code_link"] == "ingredient_name"  # e약은요 괄호 성분명
        assert by_seq["3"]["code_link"] == "none" and by_seq["3"]["kids_codes"] == []
        assert by_seq["7"]["cancelled"] is True
        kids_only = [p for p in dd.products if p["item_seq"] is None]
        assert {p["code_link"] for p in kids_only} == {"kids_source"}

    def test_api_code_attached(self, dd):
        r = dd.lookup_name("아세트아미노펜")
        assert r.candidates[0].api_codes == ("D000147",)
        assert r.candidates[0].kids_codes == ("101301ATB",)


class TestLookup:
    def test_exact_product(self, dd):
        r = dd.lookup_name("타이레놀정500밀리그람")
        assert r.matched_by == "product_name" and r.match_type == "exact" and r.resolved and not r.needs_clarification
        c = r.candidates[0]
        assert c.item_seq == "1" and c.kids_codes == ("101301ATB",) and c.prescription == "일반" and c.code_link == "edi_code"

    def test_normalized_product_export_name(self, dd):
        r = dd.lookup_name("콜드에스정")
        assert r.match_type == "normalized" and r.resolved and r.candidates[0].item_seq == "5"
        r2 = dd.lookup_name("  콜드에스 정 ")
        assert r2.candidates[0].item_seq == "5"

    def test_combination_returns_all_components(self, dd):
        c = dd.lookup_name("콜드에스정").candidates[0]
        assert {i.name_en for i in c.ingredients} == {"acetaminophen", "pseudoephedrine", "chlorpheniramine"}
        assert {i.salt for i in c.ingredients} >= {"hydrochloride", "maleate"} or {i.salt for i in c.ingredients} >= {"hcl", "maleate"}

    def test_ingredient_input_matched_by(self, dd):
        for q in ("acetaminophen", "아세트아미노펜", "파라세타몰", "ACETAMINOPHEN"):
            r = dd.lookup_name(q)
            assert r.matched_by == "ingredient_name", q
            assert r.candidates[0].code_scope == "all_forms" and r.candidates[0].item_seq is None
            assert "성분 단위" in r.notes[0]

    def test_salt_display_and_preserved_raw(self, dd):
        r = dd.lookup_name("슈도에페드린")
        ref = r.candidates[0].ingredients[0]
        assert ref.display == "슈도에페드린" and ref.salt in ("hydrochloride", "염산염")
        assert "pseudoephedrine hydrochloride" in dd.ingredients[[i["id"] for i in dd.ingredients if "pseudoephedrine hydrochloride" in i["names"]][0]]["names"]
        r2 = dd.lookup_name("슈도에페드린염산염")  # 원문 염 이름으로 입력해도 같은 성분
        assert r2.matched_by == "ingredient_name" and r2.candidates[0].kids_codes == ("100101ATB",)

    def test_same_name_multiple_products_returns_candidates(self, dd):
        r = dd.lookup_name("동명약")
        assert not r.resolved and r.needs_clarification and r.total_candidates == 2
        assert {c.item_seq for c in r.candidates} == {"3", "4"}
        assert "임의 선택 금지" in r.notes[0]

    def test_unknown_returns_empty(self, dd):
        r = dd.lookup_name("힣쀍뷁")
        assert r.empty and r.candidates == () and r.matched_by is None and not r.resolved and not r.needs_clarification
        assert dd.lookup_name("   ").empty

    def test_brand_prefix_needs_clarification(self, dd):
        r = dd.lookup_name("타이레놀")
        assert r.match_type == "prefix" and not r.resolved and r.total_candidates >= 2
        assert all(c.matched_by == "product_name" for c in r.candidates)

    def test_contains_and_typo_bm25(self, dd):
        assert dd.lookup_name("에스정").match_type == "contains"
        r = dd.lookup_name("타이레놀정500밀리그램")  # 표기 차이(그램/그람)는 정규화가 아니라 BM25로 오는지 확인
        assert r.candidates[0].item_seq == "1"
        typo = dd.lookup_name("타이래놀정")
        assert typo.match_type == "bm25" and not typo.resolved and typo.needs_clarification
        assert typo.candidates[0].name.startswith("타이레놀")

    def test_top_k(self, dd):
        assert len(dd.lookup_name("타이레놀", top_k=1).candidates) == 1

    def test_result_to_dict(self, dd):
        d = dd.lookup_name("동명약").to_dict()
        assert d["dict_version"] == dd.version and isinstance(d["candidates"], list)


class TestEmbeddingHook:
    def test_embed_fn_is_injection_point_only(self, built):
        called = []
        dd = DrugDict(built[0], embed_fn=lambda t: called.append(t) or [[0.0]] * len(t))
        dd.lookup_name("타이레놀")
        assert called == []  # 조회가 임베딩을 호출하지 않는다
        with pytest.raises(ValueError):
            dd.attach_vectors([[0.0]])
        assert len(dd.doc_texts()) == len(dd.products) + len(dd.ingredients)


def test_classify_unmatched(dd):
    out = classify_unmatched(dd, ["동명약", "타이레놀", "아세트아미노펜", "힣쀍뷁", "타이래놀정500밀리그람"])
    c = out["counts"]
    assert c["사전에 있음(제품명 일치)"] == 1 and c["브랜드명(접두 후보)"] == 1 and c["성분명"] == 1
    assert c["사전에 없음(가상 약 후보)"] == 1 and c["오탈자 후보"] == 1
