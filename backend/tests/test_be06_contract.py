"""BE-06 × AG-08 `finalize` 출력 계약 fixture 시험(2026-11-18, AG-08 §5 "finalize 출력 계약", AG-08-28 A·AG-08-29 A).

AG-08 브랜치(`feature/AG-08-finalize-1118`, `83f055a`)가 고정한 계약 예시 JSON을 fixture로 두고, BE `to_chat_response`가 그 계약대로
응답을 만드는지 본다. 대상 완료 조건: BE-06 §2 `:37`(PRD-09-05 성분 칩)·`:41`(PRD-14 식별된 약 한 줄)·`:55`(BE-06-12 제품 줄 배지 묶음).

시험 묶음과 xfail이 풀리는 조건:
- **지금 통과**: fixture 모양(계약 키 집합), 쌍 줄 유지(AG-08-29 A), `Finding.reasons` 원천(③), `pharmacist_advice_kinds` 스키마 칸(④),
  계약 키가 더해진 `finalize` 출력을 지금 변환기가 깨지지 않고 받는지(앞으로 호환).
- `xfail(strict=True)` **AG08_MERGE**: 이 worktree의 `finalize`에는 `product_rows`·`pharmacist_advice_kinds`가 아직 없다.
  AG-08 2차(`83f055a`)가 병합되면 XPASS → strict 실패로 드러나므로 표시를 지운다.
- `xfail(strict=True)` **BE_LINK**: `to_chat_response`가 `product_rows`를 아직 읽지 않는다(연결 초안 `ag08-finalize.md` §5.2는 AG-08 병합 뒤 구현).
  연결을 구현하면 풀린다. 단 `:41`·복합제 칩 시험은 §5.2 초안 그대로는 풀리지 않는다(이유는 각 표시, 결정 후보는 보고 `be06-contract.md`).

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

AG08_MERGE = ("AG-08 finalize 2차(83f055a, feature/AG-08-finalize-1118) 병합 전: 이 worktree의 finalize에 "
              "product_rows·pharmacist_advice_kinds가 없다. 병합 뒤 XPASS면 표시를 지운다")
BE_LINK = ("to_chat_response가 product_rows를 아직 읽지 않는다(ag08-finalize.md §5.2 연결은 AG-08 병합 뒤 BE 구현). "
           "연결을 구현하면 풀린다")

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
    '"evidence_ids":["contra_pair:SEQ_A:SEQ_B","pregnancy:SEQ_A","dup_ingredient:SEQ_A:SEQ_C"],"ingredients":[{"name":"와파린",'
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
@pytest.mark.xfail(strict=True, reason=AG08_MERGE)
def test_finalize_emits_contract_product_rows():
    resp = finalize(ITEMS)
    assert "product_rows" in resp
    rows = {r["key"]: r for r in resp["product_rows"]}
    assert rows["SEQ_A"] == ROW_SEQ_A and rows["SEQ_B"] == ROW_SEQ_B


@pytest.mark.xfail(strict=True, reason=AG08_MERGE)
def test_finalize_emits_advice_kinds_and_response_carries_them():
    resp = finalize([_unconfirmed()], grade_def_missing=GRADE_DEF_MISSING)
    assert resp.get("pharmacist_advice_kinds") == ["missing", "grade_def"]
    assert to_chat_response(resp, end_reason="NORMAL").pharmacist_advice_kinds == ["missing", "grade_def"]


# =========================================================================== BE_LINK: to_chat_response가 product_rows를 읽는지
@pytest.mark.xfail(strict=True, reason=BE_LINK + " (BE-06 :55, BE-06-12 A)")
def test_product_row_is_one_finding_with_ordered_badges():
    """`:55`: 병용+임부가 함께 해당하는 제품이 findings 한 줄에 배지 둘(병용 → 임부)로 나온다. 상대 약도 제품 줄 하나."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    (a,) = [f for f in _product_findings(r, "와파린정") if f.bucket == "found"]
    assert [(b.kind, b.grade, b.text) for b in a.badges] == [
        ("contra_pair", None, fp.BADGE_PAIR), ("pregnancy", "2", fp.BADGE_PREGNANCY.format(grade="2"))]
    assert a.text == fp.BADGE_PAIR and a.reasons == []
    (b,) = _product_findings(r, "아스피린정")
    assert [x.kind for x in b.badges] == ["contra_pair"]


@pytest.mark.xfail(strict=True, reason=BE_LINK + " (BE-06 :37, PRD-09-05)")
def test_product_finding_ingredients_carry_contra_kinds_and_dup():
    """`:37`: 제품 줄 성분 칩에 contra_kinds·dup이 계약 값 그대로 실린다(state_labels는 서버 상수)."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    (a,) = [f for f in _product_findings(r, "와파린정") if f.bucket == "found"]
    assert [i.model_dump(exclude_none=True) for i in a.ingredients] == ROW_SEQ_A["ingredients"]


@pytest.mark.xfail(strict=True, reason=BE_LINK + " (BE-06 :41, PRD-14). §5.2 초안 그대로면 identify 줄이 따로 남아 "
                   "이 시험은 풀리지 않는다: 제품 줄 evidence_ids에 identify 근거가 없음(결정 후보 1)")
def test_identified_drug_is_shown_once_with_ingredients():
    """`:41`: 식별된 약은 한 줄(제품 줄)로 상태와 성분 칩을 함께 가진다. 같은 약의 '찾음' 줄·임부 줄·중복 줄이 따로 나오지 않는다."""
    r = to_chat_response(_contract_resp(), end_reason="NORMAL")
    lines = _product_findings(r, "와파린정")
    assert len(lines) == 1, [(f.kind, f.bucket) for f in lines]
    assert lines[0].bucket == "found" and lines[0].ingredients


@pytest.mark.xfail(strict=True, reason=BE_LINK + ". 연결 뒤에도 Ingredient의 contra_kinds·dup 기본값([]·false)이 "
                   "계약 '칸 없음 = 모름'을 '원인 아님'으로 바꿔 풀리지 않는다(결정 후보 2)")
def test_multi_ingredient_chips_keep_unknown_as_absent():
    """계약 ②: 복합제 칩은 contra_kinds·dup 칸이 없다(모름). 응답이 이를 `[]`·`false`(원인 아님)로 바꾸면 안 된다."""
    r = to_chat_response({**finalize([_preg()]), "product_rows": [ROW_MULTI]}, end_reason="NORMAL")
    (m,) = _product_findings(r, "콜드정")
    dumped = [i.model_dump(exclude_none=True) for i in m.ingredients]
    assert [d["name"] for d in dumped] == ["아세트아미노펜", "슈도에페드린"]
    assert all("contra_kinds" not in d and "dup" not in d for d in dumped)
