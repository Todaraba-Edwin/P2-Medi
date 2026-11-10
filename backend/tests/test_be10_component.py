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
        # BE-10-10 C: 용량주의 CSV는 제품·복합제 연결에는 쓰지 않고, 단일 성분 코드 목록으로만 쓴다
        assert any("용량주의" in k and "코드 목록만" in k for k in meta["materials"])
        assert "연결에는 쓰지 않는다" in meta["boundaries"]["dose_caution_csv"]


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


# --------------------------------------------------------------------------- BE-10-10 C: 용량주의 CSV의 단일 성분 코드 목록

def DR(code: str, name: str, ingr: str = "Acetaminophen") -> dict[str, str]:
    return {"ingr_code": code, "ingr_name": ingr, "name": name}


class TestDoseSingleCodes:
    """용량주의 CSV는 복합제가 1성분만 적혀 있다. 이미 사전에 있는 단일 성분에 대해 제품명이 그 성분 하나만 가리키는 코드만 더한다."""

    KO = {"acetaminophen": {"아세트아미노펜"}}

    def test_adds_single_code_with_ingredient_in_parenthesis_or_name(self):
        rows = [DR("101311ACS", "솔루아펜연질캡슐(아세트아미노펜)_(0.325g/1캡슐)"), DR("101305ATB", "삼익아세트아미노펜정500밀리그람_(0.5g/1정)")]
        out = B.dose_single_codes(rows, self.KO, set())
        assert set(out) == {"101311ACS", "101305ATB"} and all(v[0] == "acetaminophen" for v in out.values())

    def test_nested_parenthesis_and_trailing_tag(self):
        rows = [DR("101330ASS", "어린이타이레놀현탁액(아세트아미노펜(미분화))_(16g/500mL)(무색소)")]
        assert set(B.dose_single_codes(rows, self.KO, set())) == {"101330ASS"}

    def test_rejects_combination_brand_without_ingredient_name(self):
        assert B.dose_single_codes([DR("251700ATB", "리렉사정_(1정)")], self.KO, set()) == {}

    def test_rejects_combination_with_separator_in_parenthesis(self):
        assert B.dose_single_codes([DR("252500ATB", "게보린정(아세트아미노펜, 카페인)_(1정)")], self.KO, set()) == {}

    def test_all_rows_of_a_code_must_pass(self):
        rows = [DR("101303ATB", "삼남아세트아미노펜정_(0.3g/1정)"), DR("101303ATB", "리렉사정_(1정)")]
        assert B.dose_single_codes(rows, self.KO, set()) == {}

    def test_known_code_and_unknown_ingredient_are_skipped(self):
        assert B.dose_single_codes([DR("101305APD", "톡아세트산(아세트아미노펜)_(0.5g/1포)")], self.KO, {"101305APD"}) == {}
        assert B.dose_single_codes([DR("999999ATB", "미지정(미지성분)_(1정)", "Zzzdrug")], self.KO, set()) == {}

    def test_build_adds_codes_only_to_existing_single_ingredient_and_creates_nothing_new(self):
        rows = [DR("101301ATB", "타이레놀정(아세트아미노펜)_(0.5g/1정)"), DR("101311ACS", "솔루아펜연질캡슐(아세트아미노펜)_(0.325g/1캡슐)"),
                DR("777777ATB", "새성분정(새성분)_(1정)", "Newdrug")]
        kids = KIDS + [K("100000009", "타이레놀정(아세트아미노펜)", "acetaminophen", "101301ATB")]
        data, stats = B.build_dictionary(kids, [], SNAPS, {"x": "y"}, rows)
        ap = next(i for i in data["ingredients"] if i["set_key"] == "acetaminophen")
        assert "101311ACS" in ap["kids_codes"] and B.SRC_KIDS_DOSE in ap["sources"]
        assert not any("777777ATB" in i["kids_codes"] for i in data["ingredients"])
        assert not any(p["name"].startswith("솔루아펜") for p in data["products"])  # 코드 목록만, 제품은 만들지 않는다
        assert stats["dose_single_codes_added"] == {"codes": 1, "ingredients": 1}
        base = B.build_dictionary(kids, [], SNAPS, {"x": "y"})[0]
        assert [p["item_seq"] for p in data["products"]] == [p["item_seq"] for p in base["products"]]


# --------------------------------------------------------------------------- BE-10-12 A: 성분 이름 연결(all_forms) 제품의 제형 비교

class TestAllFormsFormMatch:
    """`ingredient_name`·`all_forms` 연결 제품은 제품 제형과 맞는 코드(match)만 판정에 쓴다. 제품 코드 연결은 대상이 아니다."""

    FORM_MAP = {
        "ATB": {"route": "경구", "group": "정제", "confidence": "high"},
        "ATR": {"route": "경구", "group": "서방정", "confidence": "high"},
        "ASY": {"route": "경구", "group": "시럽", "confidence": "high"},
        "BIJ": {"route": "주사", "group": "주사제", "confidence": "high"},
    }
    ING = {"id": 0, "set_key": "acetaminophen", "display": "아세트아미노펜", "names": ["acetaminophen", "아세트아미노펜"],
           "components": [{"en": "acetaminophen", "ko": "아세트아미노펜", "display": "아세트아미노펜", "raw": "acetaminophen", "salt": ""}],
           "kids_codes": ["101303ATB", "101430ATR", "101332ASY", "101333BIJ"], "api_codes": [], "sources": []}

    @staticmethod
    def product(seq, name, form, link, codes, scope):
        return {"item_seq": seq, "name": name, "entp": "A사", "prescription": "일반", "kids_codes": codes, "api_codes": [], "ingredient_ids": [0],
                "code_link": link, "code_scope": scope, "cancelled": False, "sources": [], "form": form, "ingr_keys": ["acetaminophen"]}

    @pytest.fixture()
    def d(self):
        tab = {"route": "경구", "group": "정제", "form": "정제", "src": "name"}
        syr = {"route": "경구", "group": "시럽", "form": "시럽", "src": "name"}
        eye = {"route": "안과", "group": "점안액", "form": "점안액", "src": "name"}
        unk = {"route": None, "group": None, "form": None, "src": "none"}
        allc = ["101303ATB", "101430ATR", "101332ASY", "101333BIJ"]
        prods = [
            self.product("1", "아세정", tab, "ingredient_name", allc, "all_forms"),
            self.product("2", "아세시럽", syr, "ingredient_name", allc, "all_forms"),
            self.product("3", "아세점안액", eye, "ingredient_name", allc, "all_forms"),
            self.product("4", "아세모름", unk, "ingredient_name", allc, "all_forms"),
            self.product("5", "서방코드연결정", tab, "edi_code", ["101430ATR"], "product"),
            self.product("6", "이름연결정", tab, "product_name", ["101430ATR"], "product"),
        ]
        return DrugDict({"meta": {"form_map": self.FORM_MAP, "version": "t"}, "products": prods, "ingredients": [self.ING]})

    def cand(self, d, seq):
        return d._product_candidate(d._by_seq[seq], 1.0, "exact")

    def test_tablet_uses_only_tablet_code(self, d):
        c = self.cand(d, "1")
        assert (c.form_match, c.usable_for_judgment, c.usable_kids_codes, c.code_status) == ("match", True, ("101303ATB",), CODE_LINKED)
        assert c.note is None and "101430ATR" in c.kids_codes  # 모든 제형 코드는 참고용으로 남는다

    def test_syrup_uses_only_syrup_code(self, d):
        c = self.cand(d, "2")
        assert c.usable_kids_codes == ("101332ASY",) and c.usable_for_judgment

    def test_different_route_is_reference_only(self, d):
        c = self.cand(d, "3")
        assert (c.form_match, c.usable_for_judgment, c.usable_kids_codes) == ("mismatch", False, ())
        assert "이 제품 판정 아님" in c.note

    def test_unknown_product_form_is_reference_only(self, d):
        c = self.cand(d, "4")
        assert (c.form_match, c.usable_for_judgment, c.usable_kids_codes) == ("unknown", False, ())
        assert c.note

    @pytest.mark.parametrize("seq", ["5", "6"])
    def test_product_code_links_are_unchanged(self, d, seq):
        c = self.cand(d, seq)
        assert (c.form_match, c.usable_for_judgment, c.usable_kids_codes, c.note) == (None, True, (), None)
        assert c.kids_codes == ("101430ATR",)

    def test_tool_uses_usable_codes_only_and_reference_only_flag(self, d):
        from app.agent.tools.check_contraindications import _from_candidate

        ok = _from_candidate("아세정", self.cand(d, "1"), 1)
        assert ok.ok and ok.kids_codes == ["101303ATB"] and not ok.partial
        ref = _from_candidate("아세점안액", self.cand(d, "3"), 1)
        assert not ref.ok and ref.kids_codes == [] and {"CODE_NOT_LINKED", "REFERENCE_ONLY"} <= set(ref.flags) and ref.notes  # UNIDENTIFIED 경로
        link = _from_candidate("서방코드연결정", self.cand(d, "5"), 1)
        assert link.ok and link.kids_codes == ["101430ATR"] and "REFERENCE_ONLY" not in link.flags

    def test_ingredient_name_input_unchanged(self, d):
        c = d.lookup_name("아세트아미노펜").candidates[0]
        assert c.matched_by == D.MATCHED_BY_INGREDIENT and c.form_match is None and c.usable_for_judgment
