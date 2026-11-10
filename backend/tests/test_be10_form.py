"""BE-10-08 A: 제형 분류·코드 접미 추정·form_match·용도 괄호 제외. 합성 재료만 쓴다(외부 호출·평가 세트 없음)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_drug_dict as B  # noqa: E402

from app.tools import drug_form as F  # noqa: E402
from app.tools.drug_dict import CODE_COMPONENT_ONLY, CODE_LINKED, DrugDict  # noqa: E402


@pytest.mark.parametrize("name,route,group", [
    ("타이레놀정500밀리그람", "경구", "정제"),
    ("유나스크정10mg(암로디핀베실산염)", "경구", "정제"),
    ("아라빌정5밀리그램(아리피프라졸(미분화))", "경구", "정제"),  # 중첩 괄호
    ("명인갈란타민서방캡슐16밀리그램(갈란타민브롬화수소산염)", "경구", "서방캡슐"),
    ("크리쿨산", "경구", "산제·분말"),
    ("제일하이비6주(피리독신염산염)", "주사", "주사제"),
    ("에피즈텍정맥주사(우스테키누맙)", "주사", "주사제"),  # 이름 속 `정`보다 끝의 `주사`
    ("더아이즈톡점안액(트레할로스수화물)(1회용)", "안과", "점안액"),
    ("큐어덤로션(모메타손푸로에이트)", "외용", "로션"),
    ("게보린정 에스", "경구", "정제"),  # 짧은 브랜드 꼬리
    ("바이헬스멜라토닌구강붕해필름3.3밀리그램(수출용)", "경구", "필름"),
    ("Chong Cap", "경구", "캡슐"),
])
def test_classify_by_name(name, route, group):
    c = F.classify_product_form(name)
    assert (c["route"], c["group"]) == (route, group)


def test_ambiguous_liquid_needs_type_hint():
    assert F.classify_product_form("파워라센액")["route"] is None  # `액`만으로는 경로를 정하지 않는다
    c = F.classify_product_form("비에스에스플러스(BSSPLUS)액", "[03490]기타의 인공관류용제")
    assert (c["route"], c["group"], c["src"]) == ("외용", "관류액", "product_type")
    assert F.classify_product_form("아무개안과액", "[01310]안과용제")["route"] == "안과"


def test_unknown_stays_unknown():
    c = F.classify_product_form("비에스에스액플라스틱백타입")  # `스틱`이 끝에서 떨어져 있어도 형태로 읽지 않는다
    assert c["route"] is None and c["src"] == "none"
    assert F.classify_product_form("")["route"] is None


def test_compare_and_best():
    oral_tab = {"route": "경구", "group": "정제"}
    assert F.compare_forms(oral_tab, {"route": "경구", "group": "정제"}) == "match"
    assert F.compare_forms(oral_tab, {"route": "경구", "group": "서방정"}) == "route_only"
    assert F.compare_forms(oral_tab, {"route": "경구", "group": None}) == "route_only"
    assert F.compare_forms(oral_tab, {"route": "주사", "group": "주사제"}) == "mismatch"
    assert F.compare_forms(oral_tab, {"route": None, "group": None}) == "unknown"
    assert F.compare_forms({"route": None}, {"route": "경구", "group": "정제"}) == "unknown"
    assert F.compare_forms(None, None) == "unknown"
    assert F.best_match(["mismatch", "match", "unknown"]) == "match"
    assert F.best_match([]) == "unknown"
    assert F.USABLE == {"match"}


def test_infer_code_forms_from_name_distribution():
    pairs = [("111111BIJ", f"약{i}주사액") for i in range(6)] + [("222222ATB", f"약{i}정") for i in range(5)] + [("222222ATB", "약주사액")]
    pairs += [("333333XXX", "약정"), ("333333XXX", "약주"), ("333333XXX", "약크림"), ("333333XXX", "약캡슐"), ("333333XXX", "약연고"), ("bad", "무시")]
    m = F.infer_code_forms(pairs)
    assert m["BIJ"]["route"] == "주사" and m["BIJ"]["group"] == "주사제" and m["BIJ"]["confidence"] == "high"
    assert m["ATB"]["route"] == "경구" and m["ATB"]["confidence"] == "medium"  # 5/6 = 0.83 ≥ 0.8이라 경로는 경구, 제형군은 0.83(<0.85)이라 medium
    assert m["XXX"]["route"] is None and m["XXX"]["confidence"] == "low"  # 섞여 있으면 추정하지 않는다
    assert m["BIJ"]["method"].startswith("measured")
    assert F.code_form("999999BIJ", m)["route"] == "주사"
    assert F.code_form("999999QQQ", m)["route"] is None  # 모르는 접미


def test_usage_paren_rule():
    for t in ("소아용", "수출용", "성인용", "병원용", "어린이용"):
        assert B.is_usage_paren(t)
    assert not B.is_usage_paren("망간")
    assert B._ko_candidates("싸이젠네오트레이스4주(소아용)") == []
    assert B._ko_candidates("망간주(망간)(수출용)") == ["망간"]


# --------------------------------------------------------------------------- 사전 통합(합성)

def K(code: str, name: str, ingr: str, ingr_code: str) -> dict[str, str]:
    return {"product_code": code, "name": name, "ingr_code": ingr_code, "ingr_name": ingr, "entp": "K사"}


def P(seq: str, name: str, ingr: str, ptype: str = "[00000]시험") -> dict[str, str]:
    return {"item_seq": seq, "item_name": name, "entp_name": "A사", "spclty_pblc": "일반의약품", "item_ingr_name": ingr, "edi_code": "",
            "cancel_name": "정상", "prduct_type": ptype}


KIDS = (
    [K(f"40000000{i}", f"트레이스{i}주(소아용)", "manganese", "320800BIJ") for i in range(6)]  # manganese는 주사제 코드만
    + [K(f"50000000{i}", f"파라{i}정", "paracetamolx", "101301ATB") for i in range(6)]  # 경구 정제 코드
    + [K(f"60000000{i}", f"염화{i}주", "potassium chloride", "215803BIJ") for i in range(6)]
    + [K("700000001", "아이엠정", "ilmax", "999901ATB")]
)
SNAPS = {
    "prmsn": [
        P("1", "미네정", "Ascorbic Acid/Manganese"),  # 경구 정제 vs 주사제 코드 → mismatch
        P("2", "복합정", "Paracetamolx/Zzz"),  # 경구 정제 vs 정제 코드 → match
        P("3", "관류플러스액", "Potassium Chloride/Glucose", "[03490]기타의 인공관류용제"),  # 외용 vs 주사제 → mismatch
        P("4", "미상액", "Potassium Chloride"),  # 액(경로 모름) → unknown
        P("5", "주사칼륨주", "Potassium Chloride/Glucose"),  # 주사 vs 주사제 → match
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}


@pytest.fixture(scope="module")
def built():
    return B.build_dictionary(KIDS, [], SNAPS, {"x": "y"})


@pytest.fixture(scope="module")
def dd(built):
    return DrugDict(built[0])


def cand(dd, seq, comp):
    return next(c for c in dd.component_candidates(seq) if c.component_matches[0].component == comp)


def test_meta_has_form_map_and_note(built):
    meta = built[0]["meta"]
    assert meta["form_map"]["BIJ"]["route"] == "주사"
    assert meta["form_map"]["ATB"]["route"] == "경구"
    assert "공식 코드표가 아니라" in meta["form_map_note"]


def test_mismatch_is_reference_only(dd):
    c = cand(dd, "1", "manganese")
    m = c.component_matches[0]
    assert (c.form_match, m.form_match) == ("mismatch", "mismatch")
    assert c.usable_for_judgment is False and c.usable_kids_codes == () and m.usable_codes == ()
    assert c.kids_codes == ("320800BIJ",)  # 참고용으로는 코드를 남긴다
    assert "다른 제형(주사/주사제)에서 목록에 있음, 이 제품 판정 아님" in c.note
    assert "제품 단위 판정 아님" in c.note
    assert m.product_form == "경구/정제" and m.code_form == "주사/주사제"
    assert c.code_status == CODE_COMPONENT_ONLY  # 상태는 그대로, 판정만 막는다


def test_match_is_usable_with_only_matching_codes(dd):
    c = cand(dd, "2", "paracetamolx")
    assert (c.form_match, c.usable_for_judgment) == ("match", True)
    assert c.usable_kids_codes == ("101301ATB",) and "이 제품 판정 아님" not in (c.note or "")


def test_type_hint_gives_topical_mismatch(dd):
    c = cand(dd, "3", "potassiumchloride")
    assert c.component_matches[0].product_form == "외용/관류액"
    assert (c.form_match, c.usable_for_judgment) == ("mismatch", False)


def test_unknown_product_form_not_used(dd):
    c = cand(dd, "4", "potassiumchloride")
    assert c.form_match == "unknown" and c.usable_for_judgment is False and c.usable_kids_codes == ()
    assert "판정에 쓰지 않음" in c.note


def test_injection_product_matches_injection_code(dd):
    assert cand(dd, "5", "potassiumchloride").form_match == "match"


def test_lookup_candidate_carries_form(dd):
    r = dd.lookup_name("미네정")
    c = r.candidates[0]
    assert c.code_status == CODE_COMPONENT_ONLY and c.form_match == "mismatch" and c.usable_for_judgment is False
    d = r.to_dict()["candidates"][0]
    assert d["component_matches"][0]["form_match"] == "mismatch" and d["usable_for_judgment"] is False


def test_linked_products_form_rules():
    # 제품 코드 연결(edi_code·product_name)은 제형 검사를 받지 않는다. 성분 이름 연결(ingredient_name·all_forms)은 BE-10-12 A부터 받는다.
    snaps = {"prmsn": [P("9", "아이엠주", "Ilmax")], "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {}}
    d = DrugDict(B.build_dictionary(KIDS, [], snaps, {"x": "y"})[0])
    c = d.lookup_name("아이엠주").candidates[0]  # 경구 정제 코드뿐인 성분에 주사제 이름이 연결됨(성분 이름·all_forms)
    assert c.code_status == CODE_LINKED and c.kids_codes and c.code_link == "ingredient_name"
    assert (c.form_match, c.usable_for_judgment, c.usable_kids_codes) == ("mismatch", False, ())  # BE-10-12 A: 다른 제형 코드는 판정에 쓰지 않는다
    assert c.component_matches == ()


def test_ingredient_display_not_usage_word(dd):
    ing = next(i for i in dd.ingredients if i["set_key"] == "manganese")
    assert ing["display"] != "소아용" and "소아용" not in ing["names"]


def test_version_changes_with_form_rules(built, monkeypatch):
    monkeypatch.setattr(B, "forms_rules_signature", lambda: "other")
    assert B.build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0]["meta"]["version"] != built[0]["meta"]["version"]
