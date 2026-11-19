"""BE-06 × AG-08 `finalize` 출력 계약 fixture 시험(2026-11-18, AG-08 §5 "finalize 출력 계약", AG-08-28 A·AG-08-29 A).

AG-08 브랜치(`feature/AG-08-finalize-1118`, `83f055a`)가 고정한 계약 예시 JSON을 fixture로 두고, BE `to_chat_response`가 그 계약대로
응답을 만드는지 본다. 대상 완료 조건: BE-06 §2 `:37`(PRD-09-05 성분 칩)·`:41`(PRD-14 식별된 약 한 줄)·`:55`(BE-06-12 제품 줄 배지 묶음).

시험 묶음:
- fixture 모양(계약 키 집합), 쌍 줄 유지(AG-08-29 A), `Finding.reasons` 원천(③), `pharmacist_advice_kinds` 스키마 칸(④).
- `finalize`가 계약 칸을 낸다(AG-08 병합 뒤 xfail 표시 제거, 2026-11-18).
- 제품 줄 연결(BE-06-39 A 식별 근거 흡수·BE-06-40 A 성분 칩 "모름" = None·BE-06-41 A 제품 줄 `evidence_id` None, 2026-11-18):
  `:55`·`:37`·`:41`·복합제 칩 시험(xfail 표시 제거)과 정보 보존(주의·꼬리 안내·확인하지 못함 줄) 시험.

외부 호출·LLM 호출 0. 근거 항목·약 이름·코드는 합성(AG-08 계약 시험과 같은 값, 평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.agent import fixed_phrases as fp
from app.agent.finalize import finalize
from app.api.events import answer, encode_event
from app.api.schemas import SCHEMA_VERSION, ChatResponse, Finding, to_chat_response
from app.main import app

KIDS = "한국의약품안전관리원"
PAIR_EID = "contra_pair:SEQ_A:SEQ_B"
REASON = "출혈 위험 증가"
DOSE_REASON = "1일 3회 복용 시 독성 증가"

# --------------------------------------------------------------------------- 계약 fixture(AG-08 §5 메모의 JSON 원문 그대로)
# ① 제품 줄 예시: 와파린정(SEQ_A) 식별 + 아스피린정 병용 + 임부 2등급 + 쿠마딘정 성분 중복
ROW_SEQ_A: dict[str, Any] = json.loads(
    '{"key":"SEQ_A","drug":"와파린정","name":"와파린정","bucket":"found","text":"삐! 병용금기","badges":[{"kind":"contra_pair",'
    '"grade":null,"text":"삐! 병용금기","evidence_id":"contra_pair:SEQ_A:SEQ_B","note":null},{"kind":"pregnancy","grade":"2",'
    '"text":"삐! 임부금기 2등급","evidence_id":"pregnancy:SEQ_A","note":null}],"contra_kinds":["contra_pair","pregnancy"],'
    '"found_kinds":["contra_pair","pregnancy"],"not_listed_kinds":[],"unconfirmed_kinds":[],"caution_kinds":[],"dup":true,'
    '"evidence_ids":["contra_pair:SEQ_A:SEQ_B","pregnancy:SEQ_A","dup_ingredient:SEQ_A:SEQ_C","identify:SEQ_A"],'
    '"ingredients":[{"name":"와파린",'
    '"code":"111111ATB","contra_kinds":["contra_pair","pregnancy"],"dup":true,"state_labels":["병용금기 원인","금기 원인","중복"]}],'
    '"unresolved":false}'
)
# 같은 예시의 상대 약 줄(AG-08 `test_ag08_contract.py` `EXAMPLE_ROW_SEQ_B`와 같은 값)
ROW_SEQ_B: dict[str, Any] = json.loads(
    '{"key":"SEQ_B","drug":"아스피린정","name":null,"bucket":"found","text":"삐! 병용금기","badges":[{"kind":"contra_pair",'
    '"grade":null,"text":"삐! 병용금기","evidence_id":"contra_pair:SEQ_A:SEQ_B","note":null}],"contra_kinds":["contra_pair"],'
    '"found_kinds":["contra_pair"],"not_listed_kinds":[],"unconfirmed_kinds":[],"caution_kinds":[],"dup":false,'
    '"evidence_ids":["contra_pair:SEQ_A:SEQ_B"],"ingredients":[],"unresolved":false}'
)
# ② 복합제 칩 예시(칸 없음 = 모름). 줄의 나머지 칸은 계약 규칙으로 채운 합성 값이다(AG-08 예시에 줄 전체는 없음)
CHIPS_MULTI: list[dict[str, Any]] = json.loads('[{"name":"아세트아미노펜","state_labels":[]},{"name":"슈도에페드린","state_labels":[]}]')
ROW_MULTI: dict[str, Any] = {
    "key": "SEQ_M", "drug": "콜드정", "name": "콜드정", "bucket": "found", "text": fp.BADGE_PREGNANCY.format(grade="2"),
    "badges": [{"kind": "pregnancy", "grade": "2", "text": fp.BADGE_PREGNANCY.format(grade="2"), "evidence_id": "pregnancy:SEQ_M",
                "note": None}],
    "contra_kinds": ["pregnancy"], "found_kinds": ["pregnancy"], "not_listed_kinds": [], "unconfirmed_kinds": [], "caution_kinds": [],
    "dup": False, "evidence_ids": ["pregnancy:SEQ_M"], "ingredients": CHIPS_MULTI, "unresolved": False,
}
# ④ 권고 종류 예시
ADVICE_KINDS_EXAMPLE: list[str] = json.loads('["missing","grade_def"]')

PRODUCT_ROW_KEYS = {
    "key", "drug", "name", "bucket", "text", "badges", "contra_kinds", "found_kinds", "not_listed_kinds", "unconfirmed_kinds",
    "caution_kinds", "dup", "evidence_ids", "ingredients", "unresolved",
}
BADGE_KEYS = {"kind", "grade", "text", "evidence_id", "note"}


# --------------------------------------------------------------------------- 합성 도구 항목(AG-08 계약 시험과 같은 값)
def _pair(eid: str = PAIR_EID, reasons: tuple[str, ...] = (REASON, DOSE_REASON)) -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE",
            "drugs": ["와파린정", "아스피린정"], "drug_keys": ["SEQ_A", "SEQ_B"], "cause_codes": ["111111ATB", "222222ATB"],
            "matches": [{"row_key": f"rk{i}", "row_evidence_id": f"{eid}#{i}", "reason": r, "notice_no": "제2026-1호"}
                        for i, r in enumerate(reasons)]}


def _api_pair() -> dict:
    eid = "dur_ingr:usjnt:SEQ_A"
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["와파린정"], "evidence_id": eid, "source": "식약처 DUR 성분정보",
            "as_of": None, "queried_at_utc": "2026-11-18T01:00:00Z", "flags": [], "dataset_key": "dur_ingr", "source_kind": "API_DIRECT",
            "drugs": ["와파린정", "아스피린정"], "drug_keys": ["SEQ_A", "SEQ_B"],
            "matches": [{"row_key": "a0", "row_evidence_id": f"{eid}#0", "content": REASON, "notice_date": "2017-11-06"}]}


def _preg() -> dict:
    eid = "pregnancy:SEQ_A"
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["와파린정"], "drug_keys": ["SEQ_A"],
            "matches": [{"row_key": "r", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호", "grade": "2"}]}


def _dup() -> dict:
    return {"kind": "dup_ingredient", "status": "FOUND", "subject": ["와파린정", "쿠마딘정"], "evidence_id": "dup_ingredient:SEQ_A:SEQ_C",
            "source": KIDS, "as_of": "2026-07-21", "flags": [], "matches": [], "dataset_key": "dup_ingredient", "source_kind": "FILE",
            "drugs": ["와파린정", "쿠마딘정"], "drug_keys": ["SEQ_A", "SEQ_C"], "cause_codes": ["111111ATB"]}


def _ident() -> dict:
    return {"kind": "identify", "status": "FOUND", "subject": ["와파린정"], "evidence_id": "identify:SEQ_A", "source": "식약처",
            "as_of": "2026-11-01", "flags": [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": "와파린정",
            "matched_by": "product_name", "item_seq": "SEQ_A", "ingredients": [{"display": "와파린", "name_ko": "와파린"}],
            "kids_codes": ["111111ATB"], "code_status": "linked"}


def _unconfirmed() -> dict:
    """확인하지 못한 항목(미확보 권고 `missing`이 생기는 경로)."""
    return {"kind": "age", "status": "UNIDENTIFIED", "subject": ["111111ATB"], "evidence_id": "age:SEQ_U", "source": KIDS,
            "as_of": "2026-07-21", "flags": ["CODE_NOT_LINKED"], "dataset_key": "age", "source_kind": None, "drugs": ["미확인정"],
            "drug_keys": ["SEQ_U"], "matches": []}


GRADE_DEF_MISSING = [{"grade": "2", "missing_reason": "FETCH_FAIL"}]
ITEMS = [_ident(), _pair(), _preg(), _dup()]


def _contract_resp(rows: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """지금 `finalize` 출력에 계약 칸(`product_rows`)을 fixture로 얹은 것 = AG-08 병합 뒤 `finalize`가 낼 모양."""
    return {**finalize(ITEMS), "product_rows": [ROW_SEQ_A, ROW_SEQ_B] if rows is None else rows, **extra}


def _product_findings(r: ChatResponse, drug: str) -> list[Finding]:
    return [f for f in r.findings if f.target == "product" and f.drugs == [drug]]


# =========================================================================== fixture 모양(계약 원문 복사 확인)
def test_fixture_rows_have_contract_key_sets():
    for row in (ROW_SEQ_A, ROW_SEQ_B, ROW_MULTI):
        assert set(row) == PRODUCT_ROW_KEYS
        assert all(set(b) == BADGE_KEYS for b in row["badges"])
    assert ROW_SEQ_A["text"] == fp.BADGE_PAIR and ROW_SEQ_A["badges"][1]["text"] == fp.BADGE_PREGNANCY.format(grade="2")
    assert ROW_SEQ_A["ingredients"][0]["state_labels"] == fp.ingredient_state_labels(["contra_pair", "pregnancy"], True)
    assert all(set(c) == {"name", "state_labels"} for c in CHIPS_MULTI)  # 복합제: contra_kinds·dup 칸 자체가 없다


def test_current_converter_accepts_contract_keys_without_error():
    """앞으로 호환: 계약 칸(`product_rows`·`pharmacist_advice_kinds`)이 더해진 출력을 지금 변환기가 깨지지 않고 받는다."""
    resp = _contract_resp()
    r = to_chat_response(resp, end_reason="NORMAL")
    assert r.schema_version == SCHEMA_VERSION and r.findings


# =========================================================================== AG-08-29 A: 쌍 줄은 entries에 그대로
def test_pair_line_stays_one_per_pair_evidence():
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    pairs = [f for f in r.findings if f.target == "pair"]
    assert [(f.evidence_id, f.drugs) for f in pairs] == [(PAIR_EID, ["와파린정", "아스피린정"])]
    assert [b.kind for b in pairs[0].badges] == ["contra_pair"]


# =========================================================================== ③ Finding.reasons 원천
def test_reasons_follow_contract_example():
    """계약 ③ 예시: 행 reason 둘 → 근거 상세에는 둘 다 원문, 쌍 줄 reasons에는 용량 숫자 없는 것만."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    (pair,) = [f for f in r.findings if f.target == "pair"]
    assert pair.reasons == [REASON]
    detail = next(d for d in r.detail if d.evidence_id == PAIR_EID)
    assert [row.get("reason") for row in detail.rows] == [REASON, DOSE_REASON]
    assert all(f.reasons == [] for f in r.findings if f.target == "product")


def test_finalize_itself_emits_no_reasons_key():
    """원천은 한 곳(`detail[].rows[].reason`): finalize는 entries에 reasons 칸을 만들지 않는다(계약 ③)."""
    resp = finalize(ITEMS)
    assert all("reasons" not in e for e in resp["entries"])
    assert all("reasons" not in row for row in resp.get("product_rows") or [])


def test_api_pair_row_content_is_not_card_reason():
    r = to_chat_response(finalize([_api_pair()]), end_reason="NORMAL")
    (pair,) = [f for f in r.findings if f.target == "pair"]
    assert pair.reasons == []
    assert [row.get("content") for row in r.detail[0].rows] == [REASON]  # 근거 상세에는 남는다


# =========================================================================== ④ pharmacist_advice_kinds 스키마 칸(AG-08-28 A)
def _advice_resp(**extra: Any) -> dict[str, Any]:
    return {**finalize([_unconfirmed()], grade_def_missing=GRADE_DEF_MISSING), **extra}


def test_advice_kinds_pass_through_same_length_order():
    resp = _advice_resp(pharmacist_advice_kinds=ADVICE_KINDS_EXAMPLE)
    r = to_chat_response(resp, end_reason="NORMAL")
    assert r.pharmacist_advice == resp["pharmacist_advice"] and len(r.pharmacist_advice) == 2
    assert r.pharmacist_advice[1] == fp.GRADE_DEF_PHARMACIST_ADVICE
    assert r.pharmacist_advice_kinds == ["missing", "grade_def"]
    assert json.loads(r.model_dump_json())["pharmacist_advice_kinds"] == ["missing", "grade_def"]


def test_advice_kinds_default_empty_when_finalize_has_none():
    """finalize 상태에 값이 없으면 빈 목록이고(하위 호환), 빈 목록은 응답 글자에 싣지 않는다(프런트 strictObject 보호)."""
    resp = _advice_resp()
    resp.pop("pharmacist_advice_kinds", None)
    r = to_chat_response(resp, end_reason="NORMAL")
    assert r.pharmacist_advice and r.pharmacist_advice_kinds == []
    assert "pharmacist_advice_kinds" not in json.loads(r.model_dump_json())
    assert "pharmacist_advice_kinds" not in r.model_dump()
    raw = json.loads(encode_event(answer(1, r)))
    assert "pharmacist_advice_kinds" not in raw["response"]


def test_advice_kinds_sent_in_stream_when_present():
    r = to_chat_response(_advice_resp(pharmacist_advice_kinds=["missing", "grade_def"]), end_reason="NORMAL")
    raw = json.loads(encode_event(answer(1, r)))
    assert raw["response"]["pharmacist_advice_kinds"] == ["missing", "grade_def"]


@pytest.mark.parametrize("kinds", [["missing"], ["missing", "grade_def", "missing"]])
def test_advice_kinds_length_mismatch_is_rejected(kinds: list[str]):
    with pytest.raises(ValidationError, match="같은 길이"):
        to_chat_response(_advice_resp(pharmacist_advice_kinds=kinds), end_reason="NORMAL")


def test_advice_kinds_without_advice_is_rejected():
    resp = finalize([_preg()])
    assert resp["pharmacist_advice"] == []
    with pytest.raises(ValidationError, match="같은 길이"):
        to_chat_response({**resp, "pharmacist_advice_kinds": ["missing"]}, end_reason="NORMAL")


def test_advice_kinds_unknown_value_is_rejected():
    with pytest.raises(ValidationError):
        to_chat_response(_advice_resp(pharmacist_advice_kinds=["missing", "other"]), end_reason="NORMAL")


def test_advice_kinds_in_openapi_as_enum_array():
    prop = app.openapi()["components"]["schemas"]["ChatResponse"]["properties"]["pharmacist_advice_kinds"]
    assert prop["type"] == "array" and prop["items"]["enum"] == ["missing", "grade_def"]


def test_advice_kinds_roundtrip_keeps_v1():
    r = to_chat_response(_advice_resp(pharmacist_advice_kinds=ADVICE_KINDS_EXAMPLE), end_reason="NORMAL")
    again = ChatResponse.model_validate_json(r.model_dump_json())
    assert again == r and again.schema_version == "chat_response@v1"


# =========================================================================== AG08_MERGE: finalize가 계약 칸을 내는지
def test_finalize_emits_contract_product_rows():
    resp = finalize(ITEMS)
    assert "product_rows" in resp
    rows = {r["key"]: r for r in resp["product_rows"]}
    # FE-11-05 A(2026-11-19, AG-08-29 A 대체): finalize는 제품 줄에서 병용 배지를 빼고 짝 참조(`pair_ref`)·구역(`section`)을 낸다.
    # 위 fixture(병용 배지가 있는 이전 모양)는 응답 변환 입력 시험에 그대로 쓰고, 여기서는 바뀐 칸만 덮어 비교한다
    ref = {"count": 1, "evidence_ids": [PAIR_EID], "text": fp.PAIR_REF_LINE.format(n=1)}
    want_a = {**ROW_SEQ_A, "text": fp.BADGE_PREGNANCY.format(grade="2"), "badges": ROW_SEQ_A["badges"][1:],
              "section": "core", "pair_ref": ref, "caution_desc": None}
    want_b = {**ROW_SEQ_B, "bucket": "identified", "text": fp.IDENTIFIED_LINE, "badges": [],
              "section": "core", "pair_ref": ref, "caution_desc": None}
    assert rows["SEQ_A"] == want_a and rows["SEQ_B"] == want_b


def test_finalize_emits_advice_kinds_and_response_carries_them():
    resp = finalize([_unconfirmed()], grade_def_missing=GRADE_DEF_MISSING)
    assert resp.get("pharmacist_advice_kinds") == ["missing", "grade_def"]
    assert to_chat_response(resp, end_reason="NORMAL").pharmacist_advice_kinds == ["missing", "grade_def"]


# =========================================================================== BE_LINK: to_chat_response가 product_rows를 읽는지
def test_product_row_is_one_finding_with_ordered_badges():
    """`:55`: 병용+임부가 함께 해당하는 제품이 findings 한 줄에 배지 둘(병용 → 임부)로 나온다. 상대 약도 제품 줄 하나."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    (a,) = [f for f in _product_findings(r, "와파린정") if f.bucket == "found"]
    assert [(b.kind, b.grade, b.text) for b in a.badges] == [
        ("contra_pair", None, fp.BADGE_PAIR), ("pregnancy", "2", fp.BADGE_PREGNANCY.format(grade="2"))]
    assert a.text == fp.BADGE_PAIR and a.reasons == []
    (b,) = _product_findings(r, "아스피린정")
    assert [x.kind for x in b.badges] == ["contra_pair"]


def test_product_finding_ingredients_carry_contra_kinds_and_dup():
    """`:37`: 제품 줄 성분 칩에 contra_kinds·dup이 계약 값 그대로 실린다(state_labels는 서버 상수)."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    (a,) = [f for f in _product_findings(r, "와파린정") if f.bucket == "found"]
    assert [i.model_dump(exclude_none=True) for i in a.ingredients] == ROW_SEQ_A["ingredients"]


def test_identified_drug_is_shown_once_with_ingredients():
    """`:41`: 식별된 약은 한 줄(제품 줄)로 상태와 성분 칩을 함께 가진다. 같은 약의 '찾음' 줄·임부 줄·중복 줄이 따로 나오지 않는다."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    lines = _product_findings(r, "와파린정")
    assert len(lines) == 1, [(f.kind, f.bucket) for f in lines]
    assert lines[0].bucket == "found" and lines[0].ingredients


def test_multi_ingredient_chips_keep_unknown_as_absent():
    """계약 ②: 복합제 칩은 contra_kinds·dup 칸이 없다(모름). 응답이 이를 `[]`·`false`(원인 아님)로 바꾸면 안 된다."""
    r = to_chat_response({**finalize([_preg()]), "product_rows": [ROW_MULTI]}, end_reason="NORMAL")
    (m,) = _product_findings(r, "콜드정")
    dumped = [i.model_dump(exclude_none=True) for i in m.ingredients]
    assert [d["name"] for d in dumped] == ["아세트아미노펜", "슈도에페드린"]
    assert all("contra_kinds" not in d and "dup" not in d for d in dumped)


# =========================================================================== BE-06-40 A: Ingredient "모름"(None)은 응답 글자에 싣지 않는다
def test_unknown_chip_fields_are_none_and_absent_from_wire():
    r = to_chat_response({**finalize([_preg()]), "product_rows": [ROW_MULTI]}, end_reason="NORMAL")
    (m,) = _product_findings(r, "콜드정")
    # BE-06-42 A: 원인 모름 칩에는 서버가 승인 문구 `원인 확인 못 함`을 싣는다(finalize의 [] → 응답 검증기가 채움)
    assert all(i.contra_kinds is None and i.dup is None and i.state_labels == [fp.INGR_STATE_UNKNOWN] for i in m.ingredients)
    raw = json.loads(encode_event(answer(1, r)))  # 스트림 바이트(exclude_none 없이 직렬화하는 경로)
    chips = next(f for f in raw["response"]["findings"] if f["drugs"] == ["콜드정"])["ingredients"]
    assert chips == [{"code": None, "name": "아세트아미노펜", "state_labels": ["원인 확인 못 함"], "code_missing_text": None},
                     {"code": None, "name": "슈도에페드린", "state_labels": ["원인 확인 못 함"], "code_missing_text": None}]


# =========================================================================== BE-06-42 A: 원인 모름 칩의 상태 글자
@pytest.mark.parametrize("contra_kinds, dup, expected", [
    (None, None, [fp.INGR_STATE_UNKNOWN]),                       # 모름
    ([], False, []),                                            # 원인 아님·중복 아님: 글자 없음
    (["pregnancy"], False, [fp.INGR_STATE_CAUSE]),              # 원인 앎
    (None, True, [fp.INGR_STATE_UNKNOWN, fp.INGR_STATE_DUP]),    # 원인 모름 + 중복(순서: 원인 확인 못 함 → 중복)
    ([], None, []),                                             # 원인 아님 + 중복 모름: '원인' 글자가 아니므로 없음
    (["contra_pair"], None, [fp.INGR_STATE_PAIR_CAUSE]),
])
def test_be06_42_state_labels_for_none_empty_false(contra_kinds, dup, expected):
    from app.api.schemas import Ingredient

    assert fp.ingredient_state_labels(contra_kinds, dup) == expected
    ing = Ingredient(name="성분", contra_kinds=contra_kinds, dup=dup)  # 검증기가 서버 상수로 채운다
    assert ing.state_labels == expected
    Ingredient(name="성분", contra_kinds=contra_kinds, dup=dup, state_labels=expected)  # 같은 글자는 통과
    if expected != [fp.INGR_STATE_UNKNOWN]:
        with pytest.raises(ValidationError, match="state_labels"):
            Ingredient(name="성분", contra_kinds=contra_kinds, dup=dup, state_labels=[fp.INGR_STATE_UNKNOWN])


def _ident_line_chips(r: ChatResponse) -> list[Any]:
    (line,) = [f for f in r.findings if f.kind == "identify" and f.bucket == "identified"]
    return line.ingredients


@pytest.mark.parametrize("multi", [False, True])
def test_decision4_not_judged_drug_chips_have_no_unknown_label(multi: bool):
    """결정 후보 4 B(2026-11-18): 금기 판정 항목이 없는 약의 "찾음" 줄 칩에는 `원인 확인 못 함`을 싣지 않는다(판정 대상 아님 = 원인 아님)."""
    ident = _ident() if not multi else {**_ident(), "ingredients": [{"display": "아세트아미노펜"}, {"display": "슈도에페드린"}],
                                         "kids_codes": ["C1", "C2"]}
    r = to_chat_response(finalize([ident]), end_reason="NORMAL")
    chips = _ident_line_chips(r)
    assert chips and all(c.state_labels == [] and c.contra_kinds == [] and c.dup is False for c in chips)
    wire = json.loads(encode_event(answer(1, r)))["response"]["findings"]
    assert all(c["state_labels"] == [] for f in wire for c in f["ingredients"])


def test_decision4_not_listed_only_drug_chips_have_no_unknown_label():
    nl = {**_preg(), "status": "NOT_LISTED", "matches": []}
    r = to_chat_response(finalize([_ident(), nl]), end_reason="NORMAL")
    assert all(c.state_labels == [] for c in _ident_line_chips(r))


def test_decision4_unconfirmed_drug_chips_keep_unknown_label():
    """판정을 시도했지만 확인하지 못한 약은 모름 그대로(`원인 확인 못 함`, BE-06-42 A)."""
    r = to_chat_response(finalize([_ident(), _age_unlinked()]), end_reason="NORMAL")
    assert all(c.state_labels == [fp.INGR_STATE_UNKNOWN] and c.contra_kinds is None for c in _ident_line_chips(r))


def test_decision4_product_row_multi_chips_keep_unknown_label():
    """판정이 있는 복합제 제품 줄의 칩은 성분별 원인을 몰라 `원인 확인 못 함` 그대로다(결정 4는 판정 없는 약에만)."""
    multi = {**_ident(), "ingredients": [{"display": "아세트아미노펜"}, {"display": "슈도에페드린"}], "kids_codes": ["C1", "C2"]}
    r = to_chat_response(finalize([multi, _preg()]), end_reason="NORMAL")
    (a,) = _product_findings(r, "와파린정")
    assert [c.state_labels for c in a.ingredients] == [[fp.INGR_STATE_UNKNOWN], [fp.INGR_STATE_UNKNOWN]]


def test_be06_42_unknown_label_cannot_be_dropped_or_replaced():
    from app.api.schemas import Ingredient

    for bad in ([fp.INGR_STATE_CAUSE], ["모름"], [fp.INGR_STATE_UNKNOWN, fp.INGR_STATE_UNKNOWN]):
        with pytest.raises(ValidationError, match="state_labels"):
            Ingredient(name="성분", state_labels=bad)


def test_be06_42_unknown_phrase_passes_sentence_filter_and_screen_checks():
    """승인 문구(BE-06-42 A) 글자 고정, 문장 필터(`unsafe_reason`)·화면 금지어·안전 암시어 검사 통과."""
    from app.agent.sentence_filter import unsafe_reason

    text = fp.INGR_STATE_UNKNOWN
    assert text == "원인 확인 못 함" and "INGR_STATE_UNKNOWN" not in fp.DRAFT_KEYS
    assert unsafe_reason(text) is None
    assert not any(t in text for t in fp.FORBIDDEN_SCREEN_TERMS)
    assert not any(w in text for w in ("안전", "괜찮", "문제없", "문제 없", "삐!", "의사"))
    assert text not in (fp.INGR_STATE_CAUSE, fp.INGR_STATE_PAIR_CAUSE, fp.INGR_STATE_DUP)


def test_known_not_cause_chip_keeps_empty_list_and_false_on_wire():
    """`[]`·`false`(원인 아님)는 "모름"과 달리 그대로 싣는다(AG-08 계약 ② 단일 성분, 금기 없음)."""
    row = {**ROW_MULTI, "badges": [], "contra_kinds": [], "found_kinds": [], "caution_kinds": ["dose"], "bucket": "identified",
           "text": fp.IDENTIFIED_LINE, "ingredients": [{"name": "와파린", "code": "111111ATB", "contra_kinds": [], "dup": False,
                                                       "state_labels": []}]}
    r = to_chat_response({**finalize([_preg()]), "product_rows": [row]}, end_reason="NORMAL")
    (m,) = _product_findings(r, "콜드정")
    chip = json.loads(m.model_dump_json())["ingredients"][0]
    assert chip["contra_kinds"] == [] and chip["dup"] is False


def test_unknown_chip_rejects_state_labels_without_cause():
    with pytest.raises(ValidationError, match="state_labels"):
        to_chat_response({**finalize([_preg()]), "product_rows": [
            {**ROW_MULTI, "ingredients": [{"name": "아세트아미노펜", "state_labels": [fp.INGR_STATE_CAUSE]}]}]}, end_reason="NORMAL")


# =========================================================================== BE-06-41 A: 제품 줄 evidence_id = None
def test_product_findings_have_no_evidence_id_and_ids_stay_unique():
    r = to_chat_response(finalize(ITEMS), end_reason="NORMAL")
    products = [f for f in r.findings if f.target == "product" and f.badges]
    assert products and all(f.evidence_id is None for f in products)
    # 줄 대표 종류 = 첫 배지 종류(text = 첫 배지 글자와 짝). FE-11-05 A로 병용 배지는 제품 줄에 없어 배지 있는 제품 줄은 임부 줄 하나다
    assert [f.kind for f in products] == ["pregnancy"]
    ids = [f.evidence_id for f in r.findings if f.evidence_id is not None]
    assert ids == [PAIR_EID]  # 쌍 줄만 근거 ID를 가진다: ID로 줄을 찾아도 겹치지 않는다
    assert {b.evidence_id for f in products for b in f.badges} <= {d.evidence_id for d in r.detail}  # 배지 ID로 근거 상세를 연다


def test_real_finalize_output_links_end_to_end():
    """실제 finalize 출력(fixture를 얹지 않음)으로 `:41`·`:55`: 와파린정 한 줄(배지 둘·칩), 아스피린정 한 줄, 쌍 줄 하나."""
    r = to_chat_response(finalize(ITEMS), end_reason="NORMAL")
    (a,) = _product_findings(r, "와파린정")
    # 병용 배지는 짝 줄에만(FE-11-05 A). 성분 칩 원인 글자("병용금기 원인")는 그대로
    assert [b.kind for b in a.badges] == ["pregnancy"] and a.ingredients[0].state_labels == ROW_SEQ_A["ingredients"][0][
        "state_labels"]
    assert a.sub_line == "와파린"  # 흡수한 "찾음" 줄의 보조줄(성분 이름)은 버리지 않는다
    assert [f.drugs for f in r.findings if f.target == "pair"] == [["와파린정", "아스피린정"]]
    (c,) = _product_findings(r, "쿠마딘정")  # 성분 중복 상대 약: 배지 없이 '성분 중복' 표시를 notes로 유지
    assert c.bucket == "identified" and c.kind == "dup_ingredient" and fp.CAUTION_LABELS["dup_ingredient"] in c.notes
    assert fp.CAUTION_LABELS["dup_ingredient"] in a.notes


def _dose() -> dict:
    eid = "dose:SEQ_A"
    return {"kind": "dose", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": ["API_SAME"], "dataset_key": "dose", "source_kind": "FILE", "drugs": ["와파린정"], "drug_keys": ["SEQ_A"],
            "matches": [{"row_key": "d", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호"}]}


def _age_unlinked() -> dict:
    return {"kind": "age", "status": "UNIDENTIFIED", "subject": ["111111ATB"], "evidence_id": "age:SEQ_A", "source": KIDS,
            "as_of": "2026-07-21", "flags": ["CODE_NOT_LINKED"], "dataset_key": "age", "source_kind": None, "drugs": ["와파린정"],
            "drug_keys": ["SEQ_A"], "matches": []}


def test_absorbed_caution_and_notes_are_kept_on_product_line():
    """주의(용량) 줄을 합쳐도 그 표시(`용량 주의`)와 꼬리 안내는 제품 줄 notes에 남는다(정보를 버리지 않음)."""
    resp = finalize([_ident(), _preg(), _dose()])
    dose_entry = next(e for e in resp["entries"] if e["kind"] == "dose")
    r = to_chat_response(resp, end_reason="NORMAL")
    (a,) = _product_findings(r, "와파린정")
    assert fp.CAUTION_LABELS["dose"] in a.notes and all(n in a.notes for n in dose_entry["notes"])
    assert [b.kind for b in a.badges] == ["pregnancy"]


def test_unconfirmed_and_not_listed_lines_stay_separate():
    """확인하지 못함·목록에 없음 줄은 글자가 종류를 말하지 않아 합치지 않는다: 근거 ID·종류를 가진 줄로 따로 남는다."""
    nl = {**_preg(), "kind": "age", "status": "NOT_LISTED", "matches": [], "evidence_id": "age:SEQ_A", "dataset_key": "age"}
    r = to_chat_response(finalize([_ident(), _preg(), _age_unlinked()]), end_reason="NORMAL")
    lines = _product_findings(r, "와파린정")
    assert [(f.kind, f.bucket, f.evidence_id) for f in lines] == [("pregnancy", "found", None), ("age", "unconfirmed", "age:SEQ_A")]
    assert lines[0].unresolved and r.pharmacist_advice
    r2 = to_chat_response(finalize([_ident(), _preg(), nl]), end_reason="NORMAL")
    assert [(f.kind, f.bucket) for f in _product_findings(r2, "와파린정")] == [("pregnancy", "found"), ("age", "not_listed")]


def test_row_without_found_or_identified_is_not_emitted():
    """판정이 확인하지 못함뿐인 약은 제품 줄을 내지 않고 근거 줄(찾음 줄 포함)을 지금처럼 둔다(같은 글자 두 번 방지)."""
    r = to_chat_response(finalize([_ident(), _age_unlinked()]), end_reason="NORMAL")
    # 구역 순서(GROUP-01 3단계, FE-11-04 A): 확인 못 함(접지 않음) 줄이 나머지(찾음) 줄보다 앞
    assert [(f.kind, f.bucket, f.section) for f in _product_findings(r, "와파린정")] == [
        ("age", "unconfirmed", "unconfirmed"), ("identify", "identified", "rest")]


# =========================================================================== FE 계약 확인(goal-fe-sync.md §5, 2026-11-18 메인 추가 지시)
def test_fe5_7_product_evidence_id_key_is_sent_as_null():
    """§5-7: `Finding.evidence_id`는 키를 지우지 않고 null로 싣는다(exclude_none 금지). 스트림 바이트로 확인."""
    raw = json.loads(encode_event(answer(1, to_chat_response(finalize(ITEMS), end_reason="NORMAL"))))
    products = [f for f in raw["response"]["findings"] if f["target"] == "product"]
    assert products and all("evidence_id" in f and f["evidence_id"] is None for f in products)


def test_fe5_1_openapi_keeps_ingredient_fields_nullable():
    """§5-1·2: `exclude_if`로 값을 빼도 OpenAPI 스키마에는 칸이 남고(이름 집합 불변), 모름(null)을 허용한다."""
    schemas = app.openapi()["components"]["schemas"]
    ing = schemas["Ingredient"]["properties"]
    assert {"code", "name", "contra_kinds", "dup", "state_labels", "code_missing_text"} == set(ing)
    assert {"array", "null"} == {x.get("type") for x in ing["contra_kinds"]["anyOf"]}
    assert {"boolean", "null"} == {x.get("type") for x in ing["dup"]["anyOf"]}
    assert "evidence_id" in schemas["Finding"]["properties"]


def test_fe5_2_null_and_absent_unknown_both_accepted_and_partial_null():
    """§5-2: 모름은 null·칸 생략 둘 다 받고 한 칸만 null인 조합도 받는다. 응답 글자에서는 둘 다 키 생략으로 나간다."""
    from app.api.schemas import Ingredient

    for raw in ({"name": "a"}, {"name": "a", "contra_kinds": None, "dup": None}, {"name": "a", "contra_kinds": None, "dup": False},
                {"name": "a", "contra_kinds": ["pregnancy"], "dup": None, "state_labels": [fp.INGR_STATE_CAUSE]}):
        ing = Ingredient(**raw)
        dumped = json.loads(ing.model_dump_json())
        assert all(k in dumped for k in ("contra_kinds", "dup") if raw.get(k) is not None)
        assert all(k not in dumped for k in ("contra_kinds", "dup") if raw.get(k) is None)


@pytest.mark.parametrize("kinds", [["missing"], ["grade_def"], ["missing", "grade_def"]])
def test_fe5_4_advice_kinds_enum_only_two_values(kinds: list[str]):
    """§5-4: 값은 missing·grade_def뿐(OpenAPI enum, 다른 값 거부는 `test_advice_kinds_unknown_value_is_rejected`)."""
    assert set(kinds) <= set(app.openapi()["components"]["schemas"]["ChatResponse"]["properties"]["pharmacist_advice_kinds"]["items"]["enum"])
    assert app.openapi()["components"]["schemas"]["ChatResponse"]["properties"]["pharmacist_advice_kinds"]["items"]["enum"] == [
        "missing", "grade_def"]


def _ident_label_missing(reason: str) -> dict:
    """식별은 됐지만 허가사항 원문을 확보하지 못한 항목(`identify_drug._label_state`: FETCH_FAIL·OUT_OF_SCOPE)."""
    return {**_ident(), "missing_reason": reason, "label_source": None, "flags": ["EASY_TEXT_MISSING"]}


@pytest.mark.parametrize("reason", ["FETCH_FAIL", "OUT_OF_SCOPE"])
@pytest.mark.parametrize("extra", [[], [_preg()]])
def test_fe5_5_label_missing_evidence_always_has_one_missing_advice(reason: str, extra: list[dict]):
    """§5-5: 근거 상세에 미확보 근거(`missing_reason`)가 있으면 `missing` 권고 줄이 정확히 1줄 있다(약이 식별된 경우 포함)."""
    resp = finalize([_ident_label_missing(reason), *extra], grade_def_missing=None)
    r = to_chat_response(resp, end_reason="NORMAL")
    assert any(d.missing_reason for d in r.detail)
    assert r.pharmacist_advice_kinds.count("missing") == 1 and len(r.pharmacist_advice_kinds) == len(r.pharmacist_advice)
    assert r.fixed_notice[0] == fp.PHARMACIST_ADVICE_FIXED  # 미확보가 있으면 약사 확인 권고 고정 줄


def test_fe5_5_every_missing_reason_path_gets_missing_advice():
    """§5-5 일반형: 미확보 사유가 붙은 항목 종류(식별·허가사항 절·근거 검색)마다 `missing` 권고가 생긴다."""
    label = {"kind": "label", "status": "NO_EVIDENCE", "subject": ["와파린정"], "evidence_id": "prmsn:SEQ_A:용법용량", "source": None,
             "as_of": None, "flags": [], "matches": [], "dataset_key": "prmsn", "source_kind": None, "drugs": ["와파린정"],
             "section": "용법용량", "text": None, "missing_reason": "FETCH_FAIL"}
    for it in (_ident_label_missing("FETCH_FAIL"), label):
        resp = finalize([it])
        assert resp["pharmacist_advice_kinds"].count("missing") == 1, it["kind"]


def test_without_product_rows_output_is_one_line_per_entry():
    """`product_rows`가 없는 출력(이전 finalize 모양)은 근거 줄마다 한 줄이다(하위 호환)."""
    resp = finalize(ITEMS)
    resp.pop("product_rows")
    r = to_chat_response(resp, end_reason="NORMAL")
    assert [f.evidence_id for f in r.findings] == [e["evidence_id"] for e in resp["entries"]]
