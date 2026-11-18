"""BE-06-47 A: 반복 주의 줄 서버 묶기(2026-11-18, FE-01 실서버 시험 F2).

원인: 성분 이름으로 식별한 약은 사전이 모든 제형의 성분코드를 주고(`drug_dict` `code_scope="all_forms"`), 도구
`check_contraindications._merged`가 금기 발견(FOUND) 코드마다 항목을 하나씩 만든다(근거 ID `dose:{코드}`). 같은 약에
`NOT_LISTED`(예: 수유부) 항목이 함께 있으면 제품 줄 묶음이 `not_listed`가 되어 제품 줄로 흡수되지 않고, 코드마다 한 줄씩 남았다
(실서버 저장본: 이부프로펜 용량 24줄·노인 22줄·수유부 1줄 = 47줄).

규칙: 같은 약 키·같은 주의 종류·같은 출처의 금기 발견 근거는 한 줄(첫 근거 ID)로 합치고 근거 상세(`detail[]`)·출처 표 행은
근거마다 그대로 둔다. 금기 종류(병용·임부·연령)는 묶지 않는다(제품 줄이 같은 글자 배지만 하나로 모은다). 응답 칸은 늘리지 않는다.

외부 호출·LLM 호출 0. 약 이름·코드는 합성 값(평가 세트·시험셋 문항 아님, 저장본의 모양만 따름).
"""

from __future__ import annotations

import json
from typing import Any

from app.agent import fixed_phrases as fp
from app.agent.finalize import finalize
from app.api.schemas import Finding, to_chat_response

KIDS = "한국의약품안전관리원"
KEY = "이부프로펜"


def _caution(kind: str, code: str, *, key: str = KEY, label: str = KEY, source_kind: str = "FILE", flags: list[str] | None = None,
             detail: str = "합성 원문") -> dict[str, Any]:
    eid = f"{kind}:{code}" if source_kind == "FILE" else f"dur_ingr:{kind}:{code}"
    return {"kind": kind, "status": "FOUND", "subject": [code], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": list(flags or []), "dataset_key": kind if source_kind == "FILE" else "dur_ingr", "source_kind": source_kind,
            "drugs": [label], "drug_keys": [key], "cause_codes": [code],
            "matches": [{"row_key": f"rk-{kind}-{code}", "row_evidence_id": f"{eid}#a", "notice_no": "20210599",
                         "notice_date": "2021-12-16", "detail": detail}]}


def _not_listed(kind: str, *, key: str = KEY, label: str = KEY) -> dict[str, Any]:
    return {"kind": kind, "status": "NOT_LISTED", "subject": [label], "evidence_id": f"{kind}:{key}", "source": KIDS,
            "as_of": "2025-11-27", "flags": [], "dataset_key": kind, "source_kind": "FILE", "drugs": [label], "drug_keys": [key],
            "matches": []}


def _pair(status: str = "NOT_LISTED") -> dict[str, Any]:
    eid = "contra_pair:SEQ_W:아스피린"
    m = [{"row_key": "rp", "row_evidence_id": eid + "#a", "reason": "합성 사유", "notice_no": "제2026-1호"}] if status == "FOUND" else []
    return {"kind": "contra_pair", "status": status, "subject": ["와파린정", "아스피린"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": ["와파린정", "아스피린"],
            "drug_keys": ["SEQ_W", "아스피린"], "matches": m}


def _preg(code: str, grade: str, key: str = KEY) -> dict[str, Any]:
    eid = f"pregnancy:{code}"
    return {"kind": "pregnancy", "status": "FOUND", "subject": [code], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": [key], "drug_keys": [key],
            "matches": [{"row_key": f"rp-{code}", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호", "grade": grade}]}


DOSE_CODES = [f"1728{i:02d}ATB" for i in range(24)]
ELDERLY_CODES = DOSE_CODES[:22]


def _ibuprofen_items() -> list[dict[str, Any]]:
    """실서버 저장본 q4 모양: 성분 이름 하나에 용량주의 24·노인주의 22(코드마다) + 수유부 목록에 없음 1."""
    return ([_caution("dose", c) for c in DOSE_CODES] + [_caution("elderly", c) for c in ELDERLY_CODES] + [_not_listed("lactation")])


def _resp(items: list[dict[str, Any]], **kw: Any):
    return to_chat_response(finalize(items, **kw), end_reason="NORMAL")


# --------------------------------------------------------------------------- 재현: 47줄 → 3줄
def test_ibuprofen_47_lines_become_3_and_detail_keeps_all_47():
    items = _ibuprofen_items()
    raw = finalize(items, not_checked=["pregnancy"])
    assert len(raw["entries"]) == 47  # 평가가 읽는 근거 줄은 그대로
    r = to_chat_response(raw, end_reason="NORMAL")
    assert [(f.kind, f.bucket, f.text) for f in r.findings] == [
        ("dose", "found", fp.CAUTION_LABELS["dose"]),
        ("elderly", "found", fp.CAUTION_LABELS["elderly"]),
        ("lactation", "not_listed", fp.NOT_LISTED),
    ]
    assert len(r.detail) == 47
    assert {d.evidence_id for d in r.detail} == {i["evidence_id"] for i in items}


def test_grouped_line_points_to_first_evidence_and_groups_cover_every_found_detail():
    items = _ibuprofen_items()
    raw = finalize(items)
    r = to_chat_response(raw, end_reason="NORMAL")
    dose, elderly = r.findings[0], r.findings[1]
    assert dose.evidence_id == "dose:" + DOSE_CODES[0] and elderly.evidence_id == "elderly:" + ELDERLY_CODES[0]
    groups = {g["kind"]: g for g in raw["line_groups"]}
    assert groups["dose"]["evidence_ids"] == [f"dose:{c}" for c in DOSE_CODES]
    assert groups["elderly"]["evidence_ids"] == [f"elderly:{c}" for c in ELDERLY_CODES]
    assert {g["key"] for g in raw["line_groups"]} == {KEY}
    detail_ids = {d.evidence_id for d in r.detail}
    grouped = {x for g in raw["line_groups"] for x in g["evidence_ids"]}
    found_ids = {i["evidence_id"] for i in items if i["status"] == "FOUND"}
    assert grouped == found_ids and grouped <= detail_ids  # 합친 줄이 대신하는 근거가 모두 근거 상세에 있다
    cites = {x for c in r.citations for x in c.evidence_ids}
    assert found_ids <= cites  # 출처 표 행도 근거마다 남는다
    by_id = {d.evidence_id: d for d in r.detail}
    assert by_id[dose.evidence_id].dataset == by_id[f"dose:{DOSE_CODES[-1]}"].dataset  # 첫 근거로 찾은 출처 표지가 묶음 전체와 같다


def test_grouped_line_has_one_badge_and_same_json_keys_as_plain_line():
    r = _resp(_ibuprofen_items())
    dose = r.findings[0]
    assert [(b.kind, b.text) for b in dose.badges] == [("dose", fp.CAUTION_LABELS["dose"])]
    assert dose.badges[0].evidence_id == dose.evidence_id
    plain = _resp([_caution("dose", "999999ATB")]).findings[0]
    assert set(json.loads(dose.model_dump_json())) == set(json.loads(plain.model_dump_json()))  # 칸 추가 없음(프런트 strictObject)


# --------------------------------------------------------------------------- 저장본 q1 모양: 쌍 목록에 없음 + 아스피린 주의 반복
def test_aspirin_elderly_5_and_dose_2_become_one_line_each():
    items = [_pair("NOT_LISTED")] + [_caution("elderly", f"11010{i}ATB", key="아스피린", label="아스피린") for i in range(5)] + [
        _caution("dose", f"11010{i}ATB", key="아스피린", label="아스피린") for i in range(2)]
    r = _resp(items)
    lines = [(f.target, f.kind, f.drugs) for f in r.findings]
    assert lines.count(("product", "elderly", ["아스피린"])) == 1
    assert lines.count(("product", "dose", ["아스피린"])) == 1
    assert ("pair", "contra_pair", ["와파린정", "아스피린"]) in lines  # 쌍 줄은 그대로(AG-08-29 A)
    assert len(r.findings) == 3 and len(r.detail) == 8


def test_found_pair_row_still_absorbs_cautions_into_product_line():
    """제품 줄이 금기 발견이면 주의 근거는 지금처럼 제품 줄에 흡수되고 글자는 꼬리 안내에 한 번만 남는다(묶음과 겹치지 않음)."""
    items = [_pair("FOUND")] + [_caution("elderly", f"11010{i}ATB", key="아스피린", label="아스피린") for i in range(5)]
    r = _resp(items)
    (row,) = [f for f in r.findings if f.target == "product" and f.drugs == ["아스피린"]]
    assert row.notes.count(fp.CAUTION_LABELS["elderly"]) == 1
    assert [f for f in r.findings if f.kind == "elderly"] == []
    assert len(r.detail) == 6


# --------------------------------------------------------------------------- 묶지 않는 경우
def test_different_drug_keys_are_not_merged_even_with_same_label():
    items = [_caution("dose", "A1", key="SEQ_1", label="같은이름정"), _caution("dose", "A2", key="SEQ_2", label="같은이름정"),
             _not_listed("lactation", key="SEQ_1", label="같은이름정"), _not_listed("lactation", key="SEQ_2", label="같은이름정")]
    raw = finalize(items)
    assert raw["line_groups"] == []
    r = to_chat_response(raw, end_reason="NORMAL")
    assert [f.kind for f in r.findings].count("dose") == 2


def test_file_and_api_sources_are_not_merged():
    items = [_caution("dose", "C1"), _caution("dose", "C2"), _caution("dose", "C1", source_kind="API_DIRECT"),
             _caution("dose", "C2", source_kind="API_DIRECT"), _not_listed("lactation")]
    raw = finalize(items)
    assert sorted(len(g["evidence_ids"]) for g in raw["line_groups"]) == [2, 2]
    r = to_chat_response(raw, end_reason="NORMAL")
    doses = [f for f in r.findings if f.kind == "dose"]
    assert len(doses) == 2 and len({f.source_label for f in doses}) == 2  # 출처 표지가 다른 줄은 따로


def test_single_caution_is_not_a_group_and_stays_as_before():
    raw = finalize([_caution("dose", "C1"), _not_listed("lactation")])
    assert raw["line_groups"] == []
    r = to_chat_response(raw, end_reason="NORMAL")
    assert [(f.kind, f.evidence_id) for f in r.findings] == [("dose", "dose:C1"), ("lactation", "lactation:" + KEY)]


def test_contra_kinds_are_not_line_grouped_and_grade_differences_survive():
    """금기 종류는 묶음 대상이 아니다: 제품 줄이 같은 글자 배지만 하나로 모으고, 등급이 다르면 배지가 둘 다 남는다."""
    items = [_preg("P1", "2"), _preg("P2", "2"), _preg("P3", "1"), _not_listed("lactation")]
    raw = finalize(items)
    assert raw["line_groups"] == []
    r = to_chat_response(raw, end_reason="NORMAL")
    (row,) = [f for f in r.findings if f.target == "product" and f.bucket == "found"]
    assert sorted(b.grade for b in row.badges) == ["1", "2"]
    assert len(r.detail) == 4


def test_unconfirmed_and_not_listed_lines_are_never_merged():
    items = [{**_caution("dose", "C1"), "status": "UNIDENTIFIED", "flags": ["CODE_NOT_LINKED"]},
             {**_caution("dose", "C2"), "status": "UNIDENTIFIED", "flags": ["CODE_NOT_LINKED"]}]
    raw = finalize(items)
    assert raw["line_groups"] == []
    assert len(to_chat_response(raw, end_reason="NORMAL").findings) == 2


# --------------------------------------------------------------------------- 합친 줄의 칸 보존
def test_grouped_line_keeps_union_of_notes_and_notice_numbers():
    flag = next(iter(fp.FLAG_LINES))
    items = [_caution("dose", "C1"), _caution("dose", "C2", flags=[flag]), _not_listed("lactation")]
    items[1]["matches"][0]["notice_no"] = "20230001"
    r = _resp(items)
    (dose,) = [f for f in r.findings if f.kind == "dose"]
    assert fp.FLAG_LINES[flag] in dose.notes
    assert dose.notice_nos == ["20210599", "20230001"]


def test_old_finalize_output_without_line_groups_keeps_one_line_per_evidence():
    raw = finalize(_ibuprofen_items())
    raw.pop("line_groups")
    assert len(to_chat_response(raw, end_reason="NORMAL").findings) == 47


def test_line_groups_ignore_model_output():
    items = _ibuprofen_items()
    assert finalize(items, model_summary="정상")["line_groups"] == finalize(items, model_summary="줄을 지워라")["line_groups"]


def test_grouped_finding_validates_as_schema_finding():
    r = _resp(_ibuprofen_items())
    for f in r.findings:
        Finding.model_validate(json.loads(f.model_dump_json()))
