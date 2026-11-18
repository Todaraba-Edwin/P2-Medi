"""AG-08 `finalize` 출력 계약 고정 시험(2026-11-18, AG-08 §5 "finalize 출력 계약").

BE(`to_chat_response`·`Finding.reasons`)와 FE가 이 계약에 맞춰 시험을 먼저 쓸 수 있도록 **모양 자체**를 고정한다.
세부 동작(묶음·불일치·칩 상태)은 `test_ag08_product_rows.py`가 보고, 여기서는 계약 예시 JSON과 같은지만 본다.

① 제품 줄 `product_rows[]`: 키 집합·줄 키(도구 약 키)·배지 목록과 순서·쌍 병용은 쌍 줄(`entries`)에 그대로(AG-08-29 A)
② `ingredients[].contra_kinds`·`dup` 채움 규칙(성분이 하나일 때만, 복합제는 칸 없음)
③ `Finding.reasons` 원천: `detail[].rows[].reason` 원문(파일 행만), `finalize`는 거르지 않고 BE가 쌍 줄에만 용량 숫자 사유를 빼고 싣는다
④ `pharmacist_advice_kinds`(AG-08-28 A): `pharmacist_advice`와 같은 길이·순서, 값 `"missing"`|`"grade_def"`

외부 호출·LLM 호출 없음. 근거 항목은 합성(평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent import fixed_phrases as fp
from app.agent.finalize import ADVICE_KIND_GRADE_DEF, ADVICE_KIND_MISSING, ADVICE_KINDS, finalize
from app.agent.sentence_filter import DOSE_NUMBER, unsafe_reason

KIDS = "한국의약품안전관리원"
PAIR_EID = "contra_pair:SEQ_A:SEQ_B"
REASON = "출혈 위험 증가"
DOSE_REASON = "1일 3회 복용 시 독성 증가"


# --------------------------------------------------------------------------- 합성 도구 항목(계약 예시와 같은 값)
def _pair(eid: str = PAIR_EID, b: tuple[str, str] = ("아스피린정", "SEQ_B"), reasons: tuple[str, ...] = (REASON, DOSE_REASON)) -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE",
            "drugs": ["와파린정", b[0]], "drug_keys": ["SEQ_A", b[1]], "cause_codes": ["111111ATB", "222222ATB"],
            "matches": [{"row_key": f"rk{i}", "row_evidence_id": f"{eid}#{i}", "reason": r, "notice_no": "제2026-1호"}
                        for i, r in enumerate(reasons)]}


def _api_pair() -> dict:
    eid = "dur_ingr:usjnt:SEQ_A"
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["와파린정"], "evidence_id": eid, "source": "식약처 DUR 성분정보",
            "as_of": None, "queried_at_utc": "2026-11-18T01:00:00Z", "flags": [], "dataset_key": "dur_ingr", "source_kind": "API_DIRECT",
            "drugs": ["와파린정", "아스피린정"], "drug_keys": ["SEQ_A", "SEQ_B"],
            "matches": [{"row_key": "a0", "row_evidence_id": f"{eid}#0", "content": REASON, "notice_date": "2017-11-06"}]}


def _preg(grade: str = "2") -> dict:
    eid = "pregnancy:SEQ_A"
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["와파린정"], "drug_keys": ["SEQ_A"],
            "matches": [{"row_key": "r", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호", "grade": grade}]}


def _age() -> dict:
    eid = "age:SEQ_A"
    return {"kind": "age", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": "age", "source_kind": "FILE", "drugs": ["와파린정"], "drug_keys": ["SEQ_A"],
            "matches": [{"row_key": "g", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호",
                         "age_value": 12, "age_unit": "세", "age_cond": "미만"}]}


def _dose_caution() -> dict:
    eid = "dose:SEQ_A"
    return {"kind": "dose", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": "dose", "source_kind": "FILE", "drugs": ["와파린정"], "drug_keys": ["SEQ_A"],
            "matches": [{"row_key": "d", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호"}]}


def _dup() -> dict:
    return {"kind": "dup_ingredient", "status": "FOUND", "subject": ["와파린정", "쿠마딘정"], "evidence_id": "dup_ingredient:SEQ_A:SEQ_C",
            "source": KIDS, "as_of": "2026-07-21", "flags": [], "matches": [], "dataset_key": "dup_ingredient", "source_kind": "FILE",
            "drugs": ["와파린정", "쿠마딘정"], "drug_keys": ["SEQ_A", "SEQ_C"], "cause_codes": ["111111ATB"]}


def _ident(ingredients: tuple[str, ...] = ("와파린",), codes: tuple[str, ...] = ("111111ATB",), status: str = "linked") -> dict:
    return {"kind": "identify", "status": "FOUND", "subject": ["와파린정"], "evidence_id": "identify:SEQ_A", "source": "식약처",
            "as_of": "2026-11-01", "flags": [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": "와파린정",
            "matched_by": "product_name", "item_seq": "SEQ_A", "ingredients": [{"display": x, "name_ko": x} for x in ingredients],
            "kids_codes": list(codes), "code_status": status}


def _rows(resp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["key"]: r for r in resp["product_rows"]}


# --------------------------------------------------------------------------- ① 제품 줄 계약
PRODUCT_ROW_KEYS = {
    "key", "drug", "name", "bucket", "text", "badges", "contra_kinds", "found_kinds", "not_listed_kinds", "unconfirmed_kinds",
    "caution_kinds", "dup", "evidence_ids", "ingredients", "unresolved",
}
BADGE_KEYS = {"kind", "grade", "text", "evidence_id", "note"}  # 등급 불일치일 때만 `source_tail_key`가 더 붙는다

# 계약 예시 1(AG-08 §5 "finalize 출력 계약" ①·②의 JSON과 같은 값): 와파린정(SEQ_A) 식별 + 아스피린정 병용 + 임부 2등급 + 쿠마딘정 성분 중복
EXAMPLE_ROW_SEQ_A = {
    "key": "SEQ_A", "drug": "와파린정", "name": "와파린정", "bucket": "found", "text": fp.BADGE_PAIR,
    "badges": [
        {"kind": "contra_pair", "grade": None, "text": fp.BADGE_PAIR, "evidence_id": PAIR_EID, "note": None},
        {"kind": "pregnancy", "grade": "2", "text": fp.BADGE_PREGNANCY.format(grade="2"), "evidence_id": "pregnancy:SEQ_A", "note": None},
    ],
    "contra_kinds": ["contra_pair", "pregnancy"],
    "found_kinds": ["contra_pair", "pregnancy"], "not_listed_kinds": [], "unconfirmed_kinds": [], "caution_kinds": [],
    "dup": True,
    "evidence_ids": [PAIR_EID, "pregnancy:SEQ_A", "dup_ingredient:SEQ_A:SEQ_C"],
    "ingredients": [{"name": "와파린", "code": "111111ATB", "contra_kinds": ["contra_pair", "pregnancy"], "dup": True,
                     "state_labels": [fp.INGR_STATE_PAIR_CAUSE, fp.INGR_STATE_CAUSE, fp.INGR_STATE_DUP]}],
    "unresolved": False,
}
EXAMPLE_ROW_SEQ_B = {
    "key": "SEQ_B", "drug": "아스피린정", "name": None, "bucket": "found", "text": fp.BADGE_PAIR,
    "badges": [{"kind": "contra_pair", "grade": None, "text": fp.BADGE_PAIR, "evidence_id": PAIR_EID, "note": None}],
    "contra_kinds": ["contra_pair"], "found_kinds": ["contra_pair"], "not_listed_kinds": [], "unconfirmed_kinds": [],
    "caution_kinds": [], "dup": False, "evidence_ids": [PAIR_EID], "ingredients": [], "unresolved": False,
}


def _example_resp() -> dict[str, Any]:
    return finalize([_ident(), _pair(), _preg(), _dup()])


def test_contract_product_row_example_matches_exactly():
    rows = _rows(_example_resp())
    assert rows["SEQ_A"] == EXAMPLE_ROW_SEQ_A
    assert rows["SEQ_B"] == EXAMPLE_ROW_SEQ_B


def test_contract_product_row_and_badge_key_sets_are_fixed():
    resp = finalize([_ident(), _pair(), _preg(), _age(), _dup(), _dose_caution()])
    for r in resp["product_rows"]:
        assert set(r) == PRODUCT_ROW_KEYS, r["key"]
        for b in r["badges"]:
            assert set(b) == BADGE_KEYS
    for b in finalize([{**_preg("1"), "evidence_id": "dur_ingr:pregnancy:SEQ_A", "source_kind": "API_DIRECT",
                        "dataset_key": "dur_ingr"}, _preg("2")])["product_rows"][0]["badges"]:
        assert set(b) == BADGE_KEYS | {"source_tail_key"}  # 불일치 꼬리 칸


def test_contract_row_key_is_tool_drug_key():
    """줄 키는 도구 `drug_keys`(품목기준코드 → 성분 표시명 → 입력 원문)다. 표시 이름으로 묶지 않는다."""
    resp = _example_resp()
    assert [r["key"] for r in resp["product_rows"]] == ["SEQ_A", "SEQ_B", "SEQ_C"]
    renamed = {**_preg(), "drugs": ["와파린정(다른 표기)"]}
    assert set(_rows(finalize([_pair(), renamed]))) == {"SEQ_A", "SEQ_B"}  # 이름이 달라도 키가 같으면 한 줄


def test_contract_badges_one_per_text_in_pair_pregnancy_age_order():
    """한 줄 배지: 금기 종류(병용 → 임부 → 연령)만, 같은 글자는 한 번(병용 쌍이 여럿이어도 병용 배지 하나, AG-08-29 A)."""
    items = [_age(), _preg(), _pair(), _pair(eid="contra_pair:SEQ_A:SEQ_D", b=("클로피도그렐정", "SEQ_D")), _dose_caution()]
    row = _rows(finalize(items))["SEQ_A"]
    assert [b["text"] for b in row["badges"]] == [fp.BADGE_PAIR, fp.BADGE_PREGNANCY.format(grade="2"), fp.BADGE_AGE]
    assert row["text"] == row["badges"][0]["text"]  # 줄 대표 글자 = 첫 배지
    assert row["caution_kinds"] == ["dose"]  # 주의는 배지 없이 종류 키만


def test_contract_pair_lines_stay_in_entries():
    """AG-08-29 A: 제품 줄을 더해도 쌍 줄(`entries`의 `contra_pair`, 근거 ID마다 한 줄)은 그대로 남는다."""
    items = [_pair(), _pair(eid="contra_pair:SEQ_A:SEQ_D", b=("클로피도그렐정", "SEQ_D")), _preg()]
    resp = finalize(items)
    pair_lines = [e for e in resp["entries"] if e["kind"] == "contra_pair"]
    assert [e["evidence_id"] for e in pair_lines] == [PAIR_EID, "contra_pair:SEQ_A:SEQ_D"]
    assert all(e["bucket"] == "found" and e["text"] == fp.BADGE_PAIR for e in pair_lines)
    assert pair_lines[0]["drug"] == "와파린정 · 아스피린정"


def test_contract_row_order_found_not_listed_unconfirmed_identified():
    nl = {**_preg(), "status": "NOT_LISTED", "matches": [], "drug_keys": ["SEQ_N"], "drugs": ["무목록정"], "evidence_id": "pregnancy:SEQ_N"}
    un = {**_age(), "status": "UNIDENTIFIED", "matches": [], "source_kind": None, "flags": ["CODE_NOT_LINKED"],
          "drug_keys": ["SEQ_U"], "drugs": ["미확인정"], "evidence_id": "age:SEQ_U"}
    resp = finalize([un, nl, _dup(), _preg()])
    assert [(r["key"], r["bucket"]) for r in resp["product_rows"]] == [
        ("SEQ_A", "found"), ("SEQ_N", "not_listed"), ("SEQ_U", "unconfirmed"), ("SEQ_C", "identified")]


# --------------------------------------------------------------------------- ② 성분 칩 contra_kinds·dup
def test_contract_single_ingredient_chip_has_contra_kinds_and_dup():
    (ing,) = _rows(_example_resp())["SEQ_A"]["ingredients"]
    assert ing == EXAMPLE_ROW_SEQ_A["ingredients"][0]


def test_contract_single_ingredient_without_contra_has_empty_list_not_missing_key():
    (ing,) = _rows(finalize([_ident(), _dose_caution()]))["SEQ_A"]["ingredients"]
    assert ing == {"name": "와파린", "code": "111111ATB", "contra_kinds": [], "dup": False, "state_labels": []}


def test_contract_multi_ingredient_chips_have_no_contra_or_dup_keys():
    """복합제: 성분별 원인 코드가 도구 결과에 없어 칸 자체를 두지 않는다(값 지어내지 않음). 칸 없음 = 모름, [] = 원인 아님."""
    row = _rows(finalize([_ident(ingredients=("아세트아미노펜", "슈도에페드린"), codes=("C1", "C2")), _preg()]))["SEQ_A"]
    assert row["ingredients"] == [{"name": "아세트아미노펜", "state_labels": []}, {"name": "슈도에페드린", "state_labels": []}]
    assert row["contra_kinds"] == ["pregnancy"]  # 줄 배지는 그대로


def test_contract_code_missing_chip_text():
    (ing,) = _rows(finalize([_ident(codes=(), status="none"), _preg()]))["SEQ_A"]["ingredients"]
    assert ing["code_missing_text"] == fp.INGR_CODE_MISSING_TEXT["ABSENT"] and "code" not in ing


def test_contract_no_identify_item_gives_empty_ingredients():
    row = _rows(finalize([_preg()]))["SEQ_A"]
    assert row["ingredients"] == [] and row["name"] is None


# --------------------------------------------------------------------------- ③ Finding.reasons 원천
def _be_reasons_rule(resp: dict[str, Any], eid: str) -> list[str]:
    """BE `7530fe4` `schemas._pair_reasons`와 같은 규칙의 참조 구현(계약 예시용, BE 코드를 import하지 않는다).
    금기 발견 `contra_pair` 줄의 줄 근거 + 배지 근거 `detail[].rows[].reason`을 근거·행 순서로, 같은 글자 한 번, 용량 숫자 사유 제외."""
    e = next(x for x in resp["entries"] if x["evidence_id"] == eid)
    if e["bucket"] != "found" or e["kind"] != "contra_pair":
        return []
    detail = {d["evidence_id"]: d for d in resp["detail"]}
    ids = dict.fromkeys(x for x in (eid, *(b["evidence_id"] for b in resp["badges"] if b["evidence_id"] == eid)) if x)
    out: list[str] = []
    for i in ids:
        for row in detail[i]["rows"] if i in detail else []:
            r = row.get("reason")
            if isinstance(r, str) and r.strip() and r not in out and unsafe_reason(r) != DOSE_NUMBER:
                out.append(r)
    return out


def test_contract_reasons_source_is_detail_rows_reason_verbatim_unfiltered():
    """`finalize`는 사유를 거르거나 다듬지 않는다: 근거 상세 행에 원문 그대로(용량 숫자 사유 포함, 행 순서) 남긴다."""
    resp = finalize([_pair(reasons=(REASON, DOSE_REASON, REASON))])
    (d,) = [x for x in resp["detail"] if x["evidence_id"] == PAIR_EID]
    assert [row["reason"] for row in d["rows"]] == [REASON, DOSE_REASON, REASON]


def test_contract_reasons_example_follows_be_rule():
    resp = finalize([_pair(), _preg()])
    assert _be_reasons_rule(resp, PAIR_EID) == [REASON]  # 용량 숫자 사유는 카드에서 빠진다(근거 상세에는 남음)
    assert unsafe_reason(DOSE_REASON) == DOSE_NUMBER


def test_contract_finalize_itself_emits_no_reasons_key():
    """`reasons`는 BE가 `detail`에서 만든다. `finalize`의 `entries`·`product_rows`에는 칸이 없다(원천이 한 곳)."""
    resp = finalize([_ident(), _pair(), _preg()])
    assert all("reasons" not in e for e in resp["entries"])
    assert all("reasons" not in r for r in resp["product_rows"])


def test_contract_pair_line_and_its_badge_share_evidence_id_with_detail():
    resp = finalize([_pair()])
    (e,) = resp["entries"]
    assert e["evidence_id"] in {d["evidence_id"] for d in resp["detail"]}
    assert [b["evidence_id"] for b in resp["badges"]] == [e["evidence_id"]]


def test_contract_api_pair_row_text_is_content_not_reason():
    """성분 API 병용 행은 `content`(금기 내용)에 글이 있고 `reason`이 없다 → 지금 BE 규칙으로는 카드 사유가 비어 있다."""
    resp = finalize([_api_pair()])
    (d,) = resp["detail"]
    assert d["rows"][0].get("content") == REASON and "reason" not in d["rows"][0]
    assert _be_reasons_rule(resp, d["evidence_id"]) == []


def test_contract_non_pair_lines_have_no_reason_source_used():
    resp = finalize([_preg(), _age()])
    assert all(_be_reasons_rule(resp, e["evidence_id"]) == [] for e in resp["entries"])


# --------------------------------------------------------------------------- ④ pharmacist_advice_kinds(AG-08-28 A)
_GD_MISSING = [{"grade": "2", "missing_reason": "OUT_OF_SCOPE"}]
_UNRESOLVED = {**_age(), "status": "UNIDENTIFIED", "matches": [], "source_kind": None, "flags": ["CODE_NOT_LINKED"]}


@pytest.mark.parametrize(("items", "gd", "kinds"), [
    ([_preg()], None, []),
    ([_UNRESOLVED], None, [ADVICE_KIND_MISSING]),
    ([_preg()], _GD_MISSING, [ADVICE_KIND_GRADE_DEF]),
    ([_UNRESOLVED, _preg()], _GD_MISSING, [ADVICE_KIND_MISSING, ADVICE_KIND_GRADE_DEF]),
])
def test_advice_kinds_same_length_order_and_kind(items, gd, kinds):
    resp = finalize(items, grade_def_missing=gd)
    assert resp["pharmacist_advice_kinds"] == kinds
    assert len(resp["pharmacist_advice_kinds"]) == len(resp["pharmacist_advice"])
    assert set(resp["pharmacist_advice_kinds"]) <= set(ADVICE_KINDS)


def test_advice_values_and_order_unchanged_by_kinds():
    resp = finalize([_UNRESOLVED, _preg()], grade_def_missing=_GD_MISSING)
    assert resp["pharmacist_advice"] == [
        fp.PHARMACIST_ADVICE.replace("{drugs}을(를)", "와파린정을"), fp.GRADE_DEF_PHARMACIST_ADVICE]
    for line, kind in zip(resp["pharmacist_advice"], resp["pharmacist_advice_kinds"], strict=True):
        assert (line == fp.GRADE_DEF_PHARMACIST_ADVICE) == (kind == ADVICE_KIND_GRADE_DEF)


def test_advice_kinds_no_names_variant_is_missing():
    no_name = {**_UNRESOLVED, "drugs": [], "subject": ["111111ATB"]}
    resp = finalize([no_name])
    assert resp["pharmacist_advice"] == [fp.PHARMACIST_ADVICE_NO_NAMES]
    assert resp["pharmacist_advice_kinds"] == [ADVICE_KIND_MISSING]


def test_advice_kinds_on_refuse_and_limit_paths():
    assert finalize([], refuse_reason="OUT_OF_SCOPE")["pharmacist_advice_kinds"] == []
    resp = finalize([_UNRESOLVED], limit_reached=True)
    assert len(resp["pharmacist_advice_kinds"]) == len(resp["pharmacist_advice"])


def test_advice_kinds_are_not_rendered_in_text():
    resp = finalize([_UNRESOLVED], grade_def_missing=_GD_MISSING)
    assert ADVICE_KIND_MISSING not in resp["text"] and ADVICE_KIND_GRADE_DEF not in resp["text"]
