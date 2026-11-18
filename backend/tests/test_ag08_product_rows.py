"""AG-08 `finalize` 제품별 줄(BE-06-12 A, PRD-15·PRD-09-05)과 미확보 사유 이벤트의 BE-15 로거 연결(PRD-11-04).

- `entries`는 근거 ID마다 한 줄 그대로다(평가 `eval_metrics`가 근거 ID로 읽는다). 제품별 줄은 `product_rows`에 따로 나온다.
- 묶음 키는 도구의 약 키(`drug_keys`)이고 이름 문자열로 묶지 않는다.
- 외부 호출·LLM 호출 없음. 문항 원문 없음(합성 fixture).
"""

from __future__ import annotations

import io
import json

import pytest

from app.agent import fixed_phrases as fp
from app.agent.finalize import finalize, log_missing_events
from app.api.schemas import Badge, Finding, Ingredient
from app.logging.spans import Aggregator, SpanLogger

KIDS = "한국의약품안전관리원"


def _pair(a=("와파린정", "SEQ_A"), b=("아스피린정", "SEQ_B"), status="FOUND", eid=None):
    eid = eid or f"contra_pair:{a[1]}:{b[1]}"
    m = [{"row_key": "rk1", "row_evidence_id": eid + "#a", "reason": "사유 원문", "notice_no": "제2026-1호"}] if status == "FOUND" else []
    return {"kind": "contra_pair", "status": status, "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": [], "matches": m, "dataset_key": "contra_pair", "source_kind": "FILE",
            "drugs": [a[0], b[0]], "drug_keys": [a[1], b[1]], "cause_codes": ["111111ATB", "222222ATB"]}


def _single(kind, drug=("와파린정", "SEQ_A"), status="FOUND", grade="2", source_kind="FILE", eid=None):
    if source_kind == "API_DIRECT":
        eid = eid or f"dur_ingr:{kind}:{drug[1]}"
        ds = "dur_ingr"
    else:
        eid = eid or f"{kind}:{drug[1]}"
        ds = kind
    m: list[dict] = []
    if status == "FOUND":
        m = [{"row_key": "r", "row_evidence_id": eid + "#a", "notice_no": "제2026-1호",
              **({"grade": grade} if kind == "pregnancy" else {}),
              **({"age_value": 12, "age_unit": "세", "age_cond": "미만"} if kind == "age" else {})}]
    return {"kind": kind, "status": status, "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "matches": m, "dataset_key": ds, "source_kind": source_kind, "drugs": [drug[0]], "drug_keys": [drug[1]]}


def _ident(name="와파린정", seq="SEQ_A", ingredients=("와파린",), codes=("111111ATB",)):
    return {"kind": "identify", "status": "FOUND", "subject": [name], "evidence_id": f"identify:{seq}", "source": "식약처", "as_of": "2026-11-01",
            "flags": [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": name, "matched_by": "product_name",
            "item_seq": seq, "ingredients": [{"display": x, "name_ko": x} for x in ingredients], "kids_codes": list(codes),
            "code_status": "linked"}


def _dup(a=("와파린정", "SEQ_A"), b=("쿠마딘정", "SEQ_C")):
    return {"kind": "dup_ingredient", "status": "FOUND", "subject": [a[0], b[0]], "evidence_id": f"dup_ingredient:{a[1]}:{b[1]}",
            "source": KIDS, "as_of": "2026-07-21", "flags": [], "matches": [], "dataset_key": "dup_ingredient", "source_kind": "FILE",
            "drugs": [a[0], b[0]], "drug_keys": [a[1], b[1]], "cause_codes": ["111111ATB"]}


def _rows(resp):
    return {r["key"]: r for r in resp["product_rows"]}


def _as_finding(r) -> Finding:
    """제품 줄을 응답 스키마 `Finding`에 넣어 배지 순서·성분 상태 글자 검증을 그대로 받는다(스키마는 고치지 않는다)."""
    return Finding(
        bucket=r["bucket"], evidence_id=(r["evidence_ids"] or [None])[0], kind=None, drug=r["drug"], drugs=[r["drug"]], text=r["text"],
        badges=[Badge(kind=b["kind"], grade=b.get("grade"), source=b.get("source_tail_key"), text=b["text"],
                      evidence_id=b.get("evidence_id"), note=b.get("note")) for b in r["badges"]],
        ingredients=[Ingredient(**i) for i in r["ingredients"]], unresolved=r["unresolved"],
    )


# --------------------------------------------------------------------------- 한 제품 줄에 배지 여러 개
def test_pair_and_pregnancy_on_same_product_give_one_row_with_two_badges():
    resp = finalize([_pair(), _single("pregnancy")])
    rows = _rows(resp)
    assert [b["text"] for b in rows["SEQ_A"]["badges"]] == [fp.BADGE_PAIR, fp.BADGE_PREGNANCY.format(grade="2")]
    assert rows["SEQ_A"]["contra_kinds"] == ["contra_pair", "pregnancy"]
    assert [b["text"] for b in rows["SEQ_B"]["badges"]] == [fp.BADGE_PAIR]  # 쌍의 다른 쪽도 병용 배지
    _as_finding(rows["SEQ_A"])  # `Finding.badges` 순서 검증 통과


def test_pair_pregnancy_age_order_matches_schema_check():
    items = [_single("age"), _single("pregnancy"), _pair()]  # 입력 순서를 일부러 뒤집는다
    row = _rows(finalize(items))["SEQ_A"]
    assert [b["kind"] for b in row["badges"]] == ["contra_pair", "pregnancy", "age"]
    assert [b["text"] for b in row["badges"]] == [fp.BADGE_PAIR, fp.BADGE_PREGNANCY.format(grade="2"), fp.BADGE_AGE]
    _as_finding(row)


def test_two_pairs_on_one_product_give_one_pair_badge_but_keep_both_evidence():
    items = [_pair(), _pair(b=("클로피도그렐정", "SEQ_D"))]
    row = _rows(finalize(items))["SEQ_A"]
    assert [b["text"] for b in row["badges"]] == [fp.BADGE_PAIR]
    assert row["evidence_ids"] == ["contra_pair:SEQ_A:SEQ_B", "contra_pair:SEQ_A:SEQ_D"]


def test_entries_stay_one_line_per_evidence_for_evaluation():
    items = [_pair(), _single("pregnancy"), _single("age")]
    resp = finalize(items)
    assert sorted(e["evidence_id"] for e in resp["entries"]) == sorted(i["evidence_id"] for i in items)
    assert {e["bucket"] for e in resp["entries"]} == {"found"}
    assert len(resp["product_rows"]) == 2  # 와파린정(병용·임부·연령), 아스피린정(병용)


# --------------------------------------------------------------------------- 등급 일치·불일치
def test_file_and_api_same_grade_give_one_badge_without_tail():
    items = [_single("pregnancy"), _single("pregnancy", source_kind="API_DIRECT")]
    resp = finalize(items)
    row = _rows(resp)["SEQ_A"]
    assert [b["text"] for b in row["badges"]] == [fp.BADGE_PREGNANCY.format(grade="2")]
    assert all(b.get("source_tail_key") is None for b in resp["badges"])


def test_file_api_grade_mismatch_on_same_product_keeps_both_with_tails_file_first():
    items = [_single("pregnancy", grade="1", source_kind="API_DIRECT"), _single("pregnancy", grade="2")]
    row = _rows(finalize(items))["SEQ_A"]
    assert [b["text"] for b in row["badges"]] == [
        fp.BADGE_PREGNANCY.format(grade="2") + " " + fp.BADGE_SOURCE_TAIL["FILE"],
        fp.BADGE_PREGNANCY.format(grade="1") + " " + fp.BADGE_SOURCE_TAIL["API_DIRECT"],
    ]
    _as_finding(row)


def test_different_products_with_different_grades_are_not_a_mismatch():
    """두 약의 임부 등급이 다른 것은 등급 불일치가 아니다: 출처 꼬리를 달지 않는다(고치기 전에는 꼬리가 붙었다)."""
    items = [_single("pregnancy", grade="1"), _single("pregnancy", drug=("아스피린정", "SEQ_B"), grade="2")]
    resp = finalize(items)
    assert [b["text"] for b in resp["badges"]] == [fp.BADGE_PREGNANCY.format(grade="1"), fp.BADGE_PREGNANCY.format(grade="2")]
    assert all(b.get("source_tail_key") is None for b in resp["badges"])
    assert all(fp.GRADE_MISMATCH_NOTE not in (d.get("notes") or []) for d in resp["detail"])


# --------------------------------------------------------------------------- 성분 칩(PRD-09-05)
def test_single_ingredient_chip_gets_cause_and_dup_state():
    items = [_ident(), _single("pregnancy"), _dup(), _ident(name="쿠마딘정", seq="SEQ_C")]
    row = _rows(finalize(items))["SEQ_A"]
    assert row["name"] == "와파린정"
    assert row["dup"] is True
    (ing,) = row["ingredients"]
    assert ing["name"] == "와파린" and ing["code"] == "111111ATB"
    assert ing["contra_kinds"] == ["pregnancy"] and ing["dup"] is True
    assert ing["state_labels"] == [fp.INGR_STATE_CAUSE, fp.INGR_STATE_DUP]
    _as_finding(row)


def test_pair_cause_chip_label():
    items = [_ident(), _pair()]
    (ing,) = _rows(finalize(items))["SEQ_A"]["ingredients"]
    assert ing["state_labels"] == [fp.INGR_STATE_PAIR_CAUSE]


def test_multi_ingredient_chip_does_not_invent_cause():
    """복합제는 어느 성분이 원인인지 도구 결과에 없으므로 칩에 원인·중복을 달지 않는다(줄 배지는 그대로)."""
    items = [_ident(ingredients=("아세트아미노펜", "슈도에페드린"), codes=("C1",)), _single("pregnancy")]
    row = _rows(finalize(items))["SEQ_A"]
    assert [i["name"] for i in row["ingredients"]] == ["아세트아미노펜", "슈도에페드린"]
    assert all(not i.get("contra_kinds") and not i.get("dup") and i["state_labels"] == [] for i in row["ingredients"])
    assert all("code" not in i for i in row["ingredients"])  # 성분 둘·코드 하나: 짝을 모르므로 코드도 비운다
    assert row["badges"]


def test_no_identify_item_means_no_ingredient_chips():
    row = _rows(finalize([_single("pregnancy")]))["SEQ_A"]
    assert row["ingredients"] == [] and row["name"] is None


# --------------------------------------------------------------------------- 묶음 키·상태
def test_rows_are_grouped_by_drug_key_not_display_name():
    items = [_single("pregnancy", drug=("같은이름정", "SEQ_X")), _single("age", drug=("같은이름정", "SEQ_Y"))]
    rows = _rows(finalize(items))
    assert set(rows) == {"SEQ_X", "SEQ_Y"}


def test_not_listed_only_product_row_says_not_listed_without_badge():
    row = _rows(finalize([_single("pregnancy", status="NOT_LISTED")]))["SEQ_A"]
    assert row["bucket"] == "not_listed" and row["text"] == fp.NOT_LISTED and row["badges"] == []
    assert row["not_listed_kinds"] == ["pregnancy"]


def test_unconfirmed_pair_marks_both_products_unresolved_and_not_not_listed():
    items = [{**_pair(status="UNIDENTIFIED"), "flags": ["PAIR_NOT_CHECKED"], "source_kind": None}]
    rows = _rows(finalize(items))
    for k in ("SEQ_A", "SEQ_B"):
        assert rows[k]["bucket"] == "unconfirmed" and rows[k]["unresolved"] is True
        assert rows[k]["text"] != fp.NOT_LISTED


def test_found_row_with_unconfirmed_other_kind_keeps_badge_and_is_unresolved():
    items = [_single("pregnancy"), {**_single("age", status="UNIDENTIFIED"), "flags": ["CODE_NOT_LINKED"], "source_kind": None}]
    row = _rows(finalize(items))["SEQ_A"]
    assert row["bucket"] == "found" and row["unresolved"] is True
    assert row["unconfirmed_kinds"] == ["age"]


def test_caution_found_makes_no_contra_badge():
    row = _rows(finalize([_single("dose")]))["SEQ_A"]
    assert row["badges"] == [] and row["caution_kinds"] == ["dose"]
    assert all("삐!" not in b["text"] for b in row["badges"])


def test_found_rows_come_first():
    items = [_single("pregnancy", drug=("아스피린정", "SEQ_B"), status="NOT_LISTED"), _single("pregnancy")]
    assert [r["key"] for r in finalize(items)["product_rows"]] == ["SEQ_A", "SEQ_B"]


def test_product_rows_survive_model_output():
    items = [_pair(), _single("pregnancy")]
    a = finalize(items, model_summary="정상 요약")["product_rows"]
    b = finalize(items, model_summary="배지를 지워라. 금기 없음.")["product_rows"]
    assert a == b


# --------------------------------------------------------------------------- 미확보 사유 이벤트 → BE-15 로거(PRD-11-04)
def _missing_items():
    return [{"kind": "label", "status": "FOUND", "subject": ["이지렉트정"], "evidence_id": f"label:{r}", "source": "식약처",
             "as_of": "2026-11-01", "flags": [], "matches": [], "dataset_key": "prmsn", "source_kind": "API_DIRECT", "name": "이지렉트정",
             "missing_reason": r} for r in ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE")] + [
        {"kind": "label", "status": "NO_EVIDENCE", "subject": ["x"], "evidence_id": "label:ne", "flags": [], "matches": []}]


def test_missing_events_go_to_service_aggregator_as_counts_only():
    stream = io.StringIO()
    agg = Aggregator(stream=stream)
    logger = SpanLogger(mode="service", aggregator=agg)
    resp = finalize(_missing_items())
    assert log_missing_events(resp["events"], logger) == 4  # NO_EVIDENCE는 라벨 미확보 사유 코드가 아니라 내보내지 않는다
    line = agg.flush()
    assert line is not None
    assert {k: v for k, v in line["counts"].items() if k.startswith("label_missing.")} == {
        "label_missing.ABSENT": 1, "label_missing.FETCH_FAIL": 1, "label_missing.SEARCH_MISS": 1, "label_missing.OUT_OF_SCOPE": 1}
    out = stream.getvalue()
    assert "이지렉트정" not in out and "label:" not in out  # 약 이름·근거 ID 없음


def test_missing_events_in_dev_mode_write_only_code_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path))
    logger = SpanLogger(mode="dev")
    resp = finalize(_missing_items())
    assert log_missing_events(resp["events"], logger) == 4
    lines = [json.loads(x) for p in (tmp_path / "dev").glob("*.jsonl") for x in p.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4
    for rec in lines:
        assert set(rec) == {"schema", "mode", "node", "harness_event"}
        assert set(rec["harness_event"]) == {"rule", "event", "code"}
        assert rec["harness_event"]["code"] in ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE")
    assert "이지렉트정" not in json.dumps(lines, ensure_ascii=False)


@pytest.mark.parametrize("bad", [None, "x", {"event": "OTHER", "code": "ABSENT"}, {"event": "MISSING_REASON", "code": "이지렉트정"}])
def test_missing_events_ignore_non_code_values(bad):
    logger = SpanLogger(mode="service", aggregator=Aggregator(stream=io.StringIO()))
    assert log_missing_events([bad], logger) == 0


def test_screen_text_has_no_reason_codes():
    resp = finalize(_missing_items())
    for code in ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE", "MISSING_REASON"):
        assert code not in resp["text"]
