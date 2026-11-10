"""BE-10 사전 개선 시험: 2-gram 단독, 영문 정규화(·, mesilate, 원료 꼬리), 성분 단위 보조 조회, 코드 상태. 합성 재료만 쓴다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_drug_dict as B  # noqa: E402

from app.tools import drug_dict as D  # noqa: E402
from app.tools.drug_dict import (  # noqa: E402
    CODE_COMPONENT_ONLY,
    CODE_LINKED,
    CODE_NONE,
    MATCHED_BY_COMPONENT,
    DrugDict,
    char_ngrams,
    ingredient_key,
    split_api_components,
    split_en_salt,
)


def K(code: str, name: str, ingr: str, ingr_code: str) -> dict[str, str]:
    return {"product_code": code, "name": name, "ingr_code": ingr_code, "ingr_name": ingr, "entp": "K사"}


KIDS = [
    K("100000001", "타이레놀정", "acetaminophen", "101301ATB"),
    K("100000002", "슈도정", "pseudoephedrine hydrochloride", "100101ATB"),
    K("100000003", "세라타제킷", "streptokinase+streptodornase", "438901ATB"),
    K("100000004", "나파주", "nafamostat mesylate", "461501BIJ"),
    K("100000005", "은행엽정", "ginkgo biloba leaf ext.", "165301ATB"),
    K("100000006", "이소정", "isosorbide mononitrate", "178501ATB"),
    K("100000007", "클로닉신정", "clonixin lysinate", "136601ATB"),
    K("100000008", "베르베린", "berberine", "A19500ATB"),
]


def P(seq: str, name: str, ingr: str) -> dict[str, str]:
    return {"item_seq": seq, "item_name": name, "entp_name": "A사", "spclty_pblc": "일반의약품", "item_ingr_name": ingr, "edi_code": "", "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        P("10", "감기복합정", "Acetaminophen/Anhydrous Caffeine/Pseudoephedrine HCl"),
        P("11", "세라타제정", "Streptokinase·Streptodornase"),
        P("12", "미지약정", "Zzzdrug/Yyydrug"),
        P("13", "나파모스타트주", "Nafamostat Mesilate"),
        P("14", "알파은행엽엑스정", "Ginkgo Leaf Extract"),
        P("15", "모노맥스서방정", "Isosorbide-5-Mononitrate Montan Glycol Wax Mixture 40%"),
        P("16", "클로닉신리시네이트정", "Clonixin Lysinate Mixture 50%"),
        P("17", "성분없는정", ""),
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}


@pytest.fixture(scope="module")
def built():
    return B.build_dictionary(KIDS, [], SNAPS, {"x": "y"})


@pytest.fixture(scope="module")
def dd(built):
    return DrugDict(built[0])


def prod(dd: DrugDict, seq: str) -> dict:
    return dd.products[dd._by_seq[seq]]


# --------------------------------------------------------------------------- BE-10-07 A: 2-gram 단독

class TestTwoGram:
    def test_default_is_bigram_only(self):
        assert char_ngrams("타이레놀") == ["타이", "이레", "레놀"]
        assert D.BM25_NGRAM_SIZES == (2,)
        assert D.BM25_TOKENIZER == "char-ngram-2"

    def test_short_text_is_single_token(self):
        assert char_ngrams("정") == ["정"]

    def test_version_changes_with_tokenizer(self, built, monkeypatch):
        v1 = built[0]["meta"]["version"]
        monkeypatch.setattr(B, "BM25_TOKENIZER", "char-ngram-2+3")
        v2 = B.build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0]["meta"]["version"]
        assert v1 != v2
        assert built[0]["meta"]["bm25_tokenizer"] == "char-ngram-2"

    def test_version_changes_with_rules(self, built, monkeypatch):
        monkeypatch.setattr(B, "normalize_rules_signature", lambda: "other-rules")
        v2 = B.build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0]["meta"]["version"]
        assert built[0]["meta"]["version"] != v2


# --------------------------------------------------------------------------- BE-10 정규화 개선 C

class TestNormalizeRules:
    def test_middle_dot_separator(self):
        assert split_api_components("Streptokinase·Streptodornase") == ["Streptokinase", "Streptodornase"]
        assert B._set_key("Streptokinase·Streptodornase", "api") == "streptodornase+streptokinase"
        assert split_api_components("A/B;C·D") == ["A", "B", "C", "D"]

    @pytest.mark.parametrize("a,b", [("Nafamostat Mesilate", "Nafamostat Mesylate"), ("Bepotastine Besilate", "Bepotastine Besylate")])
    def test_mesilate_besilate_are_salts(self, a, b):
        assert ingredient_key(a) == ingredient_key(b)
        assert split_en_salt(a)[1] in ("mesilate", "besilate")

    def test_extract_and_biloba(self):
        assert ingredient_key("Ginkgo Biloba Leaf Ext.") == ingredient_key("Ginkgo Leaf Extract") == "ginkgoleafextract"
        assert ingredient_key("Ginkgo biloba leaf ext") == "ginkgoleafextract"

    def test_raw_material_tail_with_carrier(self):
        assert ingredient_key("Isosorbide-5-Mononitrate Montan Glycol Wax Mixture 40%") == ingredient_key("isosorbide mononitrate")

    def test_mixture_tail_without_carrier_keeps_ingredient_name(self):
        # 담체 단어가 없으면 `Mixture nn%`만 떼고 성분 이름(Lysinate)은 남긴다
        assert ingredient_key("Clonixin Lysinate Mixture 50%") == "clonixinlysinate"
        assert ingredient_key("Clonixin Lysinate Mixture 50%") != ingredient_key("clonixin")

    def test_bare_substances_unchanged(self):
        assert ingredient_key("Calcium Carbonate") == "calciumcarbonate"
        assert ingredient_key("Magnesium Sulfate") == "magnesiumsulfate"

    def test_build_links_rule_cases_by_set(self, dd):
        for seq in ("11", "13", "14", "15", "16"):
            p = prod(dd, seq)
            assert p["kids_codes"], seq
            assert p["code_link"] == "ingredient_name", seq

    def test_meta_boundary_for_dose_caution_csv(self, built):
        meta = built[0]["meta"]
        assert "용량주의" in meta["boundaries"]["dose_caution_csv"]
        assert "UNIDENTIFIED" in meta["boundaries"]["dose_caution_csv"]
        assert any("용량주의" in k and v.startswith("쓰지 않음") for k, v in meta["materials"].items())


# --------------------------------------------------------------------------- BE-10-06 B: 성분 단위 보조 조회

class TestComponentLookup:
    def test_component_only_product(self, dd):
        p = prod(dd, "10")
        assert p["kids_codes"] == []  # 성분 단위 코드는 제품 코드로 넣지 않는다
        assert p["code_link"] == CODE_COMPONENT_ONLY
        r = dd.lookup_name("감기복합정")
        c = r.candidates[0]
        assert c.code_status == CODE_COMPONENT_ONLY
        assert c.code_link == CODE_COMPONENT_ONLY
        assert c.kids_codes == ()
        assert {m.component for m in c.component_matches} == {"acetaminophen", "pseudoephedrine"}
        assert c.note and "제품 단위 판정 아님" in c.note

    def test_component_candidates(self, dd):
        cands = dd.component_candidates("10")
        assert len(cands) == 2
        by = {c.component_matches[0].component: c for c in cands}
        assert all(c.matched_by == MATCHED_BY_COMPONENT and c.code_status == CODE_COMPONENT_ONLY for c in cands)
        assert by["acetaminophen"].kids_codes == ("101301ATB",)
        assert by["pseudoephedrine"].kids_codes == ("100101ATB",)
        assert all(c.code_scope == "all_forms" and c.item_seq == "10" for c in cands)
        assert "이 제품에 든" in by["acetaminophen"].note and "제품 단위 판정 아님" in by["acetaminophen"].note
        assert "caffeine" not in " ".join(c.note or "" for c in cands)

    def test_unmatched_components_not_guessed(self, dd):
        # caffeine은 KIDS 단일 성분 항목이 없어 후보에 없다(비슷한 이름으로 넓히지 않는다)
        assert all(m.component != "anhydrouscaffeine" for c in dd.component_candidates("10") for m in c.component_matches)

    def test_none_status_has_no_candidates_and_is_not_not_listed(self, dd):
        assert prod(dd, "12")["code_link"] == "none"
        c = dd.lookup_name("미지약정").candidates[0]
        assert c.code_status == CODE_NONE
        assert c.component_matches == () and c.note is None
        assert dd.component_candidates("12") == ()  # 빈 결과는 "금기 없음"이 아니다(UNIDENTIFIED, AG-02가 변환)

    def test_product_without_ingredient_info_is_none(self, dd):
        assert dd.lookup_name("성분없는정").candidates[0].code_status == CODE_NONE

    def test_linked_status_and_unknown_seq(self, dd):
        assert dd.lookup_name("세라타제정").candidates[0].code_status == CODE_LINKED
        assert dd.lookup_name("세라타제정").candidates[0].component_matches == ()
        assert dd.component_candidates("no-such-seq") == ()

    def test_stats_count_component_only(self, built):
        by_src = built[1]["link_by_source"]["허가정보(식약처)"]
        assert by_src["component_only"] == 1
        assert by_src["rate_with_code_or_component"] > by_src["rate_with_code"]

    def test_to_dict_serializable(self, dd):
        d = dd.lookup_name("감기복합정").to_dict()
        c = d["candidates"][0]
        assert c["code_status"] == CODE_COMPONENT_ONLY and c["component_matches"][0]["kids_codes"]
