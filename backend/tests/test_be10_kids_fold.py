"""BE-10-13 A: `lookup_name`이 `_(함량)` 꼬리만 다른 KIDS 행을 같은 정규화 키의 허가 행(item_seq 있음) 하나로 접는다.

합성 사전만 쓴다(실제 제품명·개발셋 제품명 없음). 접는 기준은 꼬리 형식·item_seq 유무·정규화 키뿐이다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tools.drug_dict import DrugDict


def prod(name: str, seq: str | None = None, codes: tuple[str, ...] = (), link: str = "none", **kw: Any) -> dict[str, Any]:
    p: dict[str, Any] = {"name": name, "item_seq": seq, "entp": "X사", "prescription": "전문", "kids_codes": list(codes), "api_codes": [],
                         "code_link": link, "code_scope": "product" if codes else None, "cancelled": False, "sources": ["허가정보(식약처)" if seq else "KIDS"],
                         "ingredient_ids": [], "ingr_keys": [], "form": {"group": "정제"} if seq else {}}
    p.update(kw)
    return p


def make(products: list[dict[str, Any]]) -> DrugDict:
    return DrugDict({"meta": {"version": "syn"}, "products": products, "ingredients": []})


# --------------------------------------------------------------------------- 접는 경우(5건)

@pytest.mark.parametrize("query", [
    "가나정5밀리그램", "가나정5밀리그램(다라마염산염)", "가나정5밀리그램(다라마염산염)_(5mg/1정)", "가나정5mg", " 가나정 5밀리그램 ",
])
def test_kids_strength_row_folds_into_single_permit_row(query):
    dd = make([prod("가나정5밀리그램(다라마염산염)", "100", ("111AAA",), "product_name"),
               prod("가나정5밀리그램(다라마염산염)_(5mg/1정)", None, ("111AAA",), "kids_source")])
    r = dd.lookup_name(query)
    assert r.resolved and not r.needs_clarification and r.total_candidates == 1
    assert r.candidates[0].item_seq == "100" and r.candidates[0].name == "가나정5밀리그램(다라마염산염)"


def test_fold_adds_note_with_count():
    dd = make([prod("가나정5밀리그램(다라마)", "100", (), "none"), prod("가나정5밀리그램(다라마)_(5mg/1정)", None, ("K1",), "kids_source"),
               prod("가나정5밀리그램(다라마)_(0.005g/1정)", None, ("K1",), "kids_source")])
    r = dd.lookup_name("가나정5밀리그램")
    assert r.resolved and any("KIDS 함량 행 2개" in n for n in r.notes)


def test_two_kids_rows_with_different_tails_fold_together():
    dd = make([prod("라마시럽(덱스)", "7", ("A1",), "edi_code"), prod("라마시럽(덱스)_(6g/500mL)", None, ("A2",), "kids_source"),
               prod("라마시럽(덱스)_(1g/100mL)", None, ("A3",), "kids_source")])
    r = dd.lookup_name("라마시럽")
    assert r.resolved and set(r.candidates[0].kids_codes) == {"A1", "A2", "A3"}


def test_exact_raw_kids_name_input_resolves_to_permit_row():
    dd = make([prod("바사정(에이)", "9", ("Z1",), "product_name"), prod("바사정(에이)_(10mg/1정)", None, ("Z1",), "kids_source")])
    r = dd.lookup_name("바사정(에이)_(10mg/1정)")  # 원문 정확 일치가 KIDS 행뿐이어도 허가 행이 대표
    assert r.resolved and r.candidates[0].item_seq == "9"


def test_folded_candidate_keeps_permit_form_and_link():
    dd = make([prod("차카정(파)", "5", ("C1",), "edi_code", form={"group": "정제", "route": "경구"}), prod("차카정(파)_(1mg/1정)", None, ("C1",), "kids_source")])
    c = dd.lookup_name("차카정").candidates[0]
    assert c.code_link == "edi_code" and c.code_status == "linked" and c.item_seq == "5"


# --------------------------------------------------------------------------- 코드 합집합 보존

def test_kids_codes_union_preserved_before_and_after():
    rows = [prod("타파정(하)", "20", ("T1", "T2"), "edi_code"), prod("타파정(하)_(1mg/1정)", None, ("T3",), "kids_source"),
            prod("타파정(하)_(2mg/1정)", None, ("T2", "T4"), "kids_source")]
    dd = make(rows)
    before = set().union(*(set(p["kids_codes"]) for p in rows))
    c = dd.lookup_name("타파정").candidates[0]
    assert set(c.kids_codes) == before == {"T1", "T2", "T3", "T4"}
    assert len(c.kids_codes) == len(set(c.kids_codes))  # 중복 없음
    assert dd.products[0]["kids_codes"] == ["T1", "T2"]  # 원본 사전은 바뀌지 않는다


def test_permit_without_codes_inherits_kids_link():
    dd = make([prod("파차정(가)", "30", (), "none"), prod("파차정(가)_(3mg/1정)", None, ("P1",), "kids_source")])
    c = dd.lookup_name("파차정").candidates[0]
    assert c.kids_codes == ("P1",) and c.code_status == "linked" and c.code_link == "kids_source"


def test_sources_union():
    dd = make([prod("하바정(나)", "40", ("H1",), "edi_code"), prod("하바정(나)_(1mg/1정)", None, ("H1",), "kids_source")])
    assert set(dd.lookup_name("하바정").candidates[0].sources) == {"허가정보(식약처)", "KIDS"}


# --------------------------------------------------------------------------- 접지 않는 경우(각 5건 이상)

@pytest.mark.parametrize("n_permits", [2, 3])
def test_two_or_more_permit_numbers_stay_ambiguous(n_permits):
    rows = [prod("카타정(다)", str(100 + i), ("K1",), "product_name") for i in range(n_permits)]
    rows.append(prod("카타정(다)_(5mg/1정)", None, ("K1",), "kids_source"))
    r = make(rows).lookup_name("카타정")
    assert not r.resolved and r.needs_clarification and r.total_candidates == n_permits + 1  # KIDS 행도 접지 않는다


def test_cancelled_plus_active_permits_still_ask():
    rows = [prod("마아정(라)", "1", ("M1",), "product_name"), prod("마아정(라)", "2", ("M1",), "product_name", cancelled=True),
            prod("마아정(라)_(5mg/1정)", None, ("M1",), "kids_source")]
    assert not make(rows).lookup_name("마아정").resolved


@pytest.mark.parametrize("a, b", [("펜아패취12μg/h(펜)", "펜아패취12μg/h(펜)(수출용)"), ("펜아정(펜)", "펜아정(펜)(수출명:PenA Tab.)")])
def test_export_twin_never_auto_resolved(a, b):
    r = make([prod(a, "1", ("E1",), "edi_code"), prod(b, "2", ("E1",), "product_name")]).lookup_name(a.split("(")[0])
    assert not r.resolved and r.needs_clarification and r.total_candidates == 2


def test_export_twin_domestic_row_ranked_first():
    r = make([prod("펜아정(펜)(수출용)", "2"), prod("펜아정(펜)", "1")]).lookup_name("펜아정")
    assert [c.item_seq for c in r.candidates] == ["1", "2"]
    r2 = make([prod("라바정(수출명:RabaTab.)", "9"), prod("라바정", "8")]).lookup_name("라바")
    assert r2.candidates[0].item_seq == "8"


@pytest.mark.parametrize("q", ["사하정5밀리그램", "사하정10밀리그램", "사하정2.5밀리그램"])
def test_strength_inside_name_not_merged(q):
    dd = make([prod("사하정5밀리그램(마)", "1", ("S1",), "product_name"), prod("사하정5밀리그램(마)_(5mg/1정)", None, ("S1",), "kids_source"),
               prod("사하정10밀리그램(마)", "2", ("S2",), "product_name"), prod("사하정10밀리그램(마)_(10mg/1정)", None, ("S2",), "kids_source")])
    r = dd.lookup_name(q)
    if q.startswith("사하정5") or q.startswith("사하정10"):
        assert r.resolved
        want = "1" if "5" == q[3] else "2"
        assert r.candidates[0].item_seq == want and set(r.candidates[0].kids_codes) == {"S" + want}  # 다른 함량 코드가 섞이지 않는다
    else:
        assert not r.resolved  # 2.5는 접두·중간 일치 되묻기나 후보 없음, 자동 확정 금지


def test_kids_only_name_without_permit_not_folded():
    dd = make([prod("오다정(바)_(5mg/1정)", None, ("O1",), "kids_source"), prod("오다정(바)_(10mg/1정)", None, ("O2",), "kids_source")])
    r = dd.lookup_name("오다정")
    assert not r.resolved and r.total_candidates == 2


def test_kids_row_without_item_seq_but_no_suffix_is_not_folded():
    dd = make([prod("조카정(사)", "1", ("J1",), "product_name"), prod("조카정(사)", None, ("J2",), "kids_source")])
    r = dd.lookup_name("조카정")
    assert not r.resolved and r.total_candidates == 2


def test_permit_with_different_key_not_a_fold_target():
    dd = make([prod("라이정(가)", "1", ("L1",), "product_name"), prod("라이정에스(가)_(5mg/1정)", None, ("L2",), "kids_source")])
    r = dd.lookup_name("라이정에스")
    assert r.candidates[0].item_seq is None and set(r.candidates[0].kids_codes) == {"L2"}


def test_exact_permit_name_input_also_gets_code_union():
    """원문 정확 일치 경로(허가 행만 후보)에서도 같은 키 KIDS 행의 코드가 합쳐져 정규화·접두 경로와 코드가 같다."""
    dd = make([prod("헤타주(나트륨)", "11", ("H1",), "edi_code"), prod("헤타주(나트륨)_(5KI.U/1mL)", None, ("H2",), "kids_source")])
    exact = dd.lookup_name("헤타주(나트륨)")
    norm = dd.lookup_name("헤타주")
    assert exact.match_type == "exact" and exact.resolved and set(exact.candidates[0].kids_codes) == {"H1", "H2"}
    assert set(norm.candidates[0].kids_codes) == {"H1", "H2"}
