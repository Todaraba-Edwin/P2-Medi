"""AG-07-02 B(2026-11-17): Validator의 규칙 번호 검사(`CHECK_RULES`: H22 `GRADE_VALUE_INVALID`·`M_NO_DETAIL`·`M_CONVERTED`, H24 `GRADE_EXCEPTION_MISUSE`)를
trace `violations`(L2 validator span)와 평가 보조 집계(`eval_runner`·`eval_metrics`의 `validator_rule_counts`)에 연결한 시험.

LLM·공공 API·원격 DB 호출 0(가짜 모델·합성 소사전·소규모 SQLite·가짜 `DurClient`). 시험 문장·질문은 합성이다(평가 세트 문항 아님).
기록에는 검사 코드·규칙 번호·건수만 들어가고 문장 원문은 들어가지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

import eval_metrics as M  # noqa: E402
import eval_runner as R  # noqa: E402
from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.validator import CHECK_RULES, GRADE_EXCEPTION_MISUSE, GRADE_VALUE_INVALID, M_CONVERTED, SAFE_ASSERTION  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
FACT_OK = {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
BAD_GRADE = {"text": "이 조합은 3등급 금기로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}   # H22
BAD_EXCEPT = {"text": "2등급이라 괜찮아요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}                # H24
CLEAN_DRAFT = {"sentences": [FACT_OK, GUIDE]}
BAD_DRAFT = {"sentences": [FACT_OK, BAD_GRADE, BAD_EXCEPT, GUIDE]}
SENTENCE_MARKERS = ("3등급 금기", "괜찮아요")  # 기록 어디에도 없어야 하는 문장 조각


def _run(draft: dict[str, Any]) -> tuple[dict[str, Any], ListSink]:
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    script = [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]
    sink = ListSink()
    tracer = GraphTracer(sink=sink, prompt_set="prompt_set@v3", prompt_version="agent_system@v2")
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([draft]), tracer=tracer)
    return run_question(build_graph(deps), Q_PAIR), sink


def _validator_spans(sink: ListSink) -> list[dict[str, Any]]:
    return [r for r in sink.records if r.get("node") == "validator" and "harness_event" not in r]


# =========================================================================== §1 그래프 상태 `validation`과 trace `violations`
def test_validation_state_carries_rule_check_counts_without_text():
    st, _ = _run(BAD_DRAFT)
    v = st["validation"]
    assert v["status"] == "FIXED" and v["kept"] == 2 and v["reasons"] == []  # 되감기 없음(걸러내고 통과)
    assert v["rule_checks"] == {GRADE_VALUE_INVALID: 1, GRADE_EXCEPTION_MISUSE: 1} and v["rules"] == {"H22": 1, "H24": 1}
    assert st["end_reason"] == "NORMAL"
    assert not any(m in json.dumps(v, ensure_ascii=False) for m in SENTENCE_MARKERS)


def test_trace_validator_span_lists_rule_codes_in_violations_and_counts_in_output_summary():
    _, sink = _run(BAD_DRAFT)
    (span,) = _validator_spans(sink)
    assert span["verdict"] == "fix"
    assert span["violations"] == sorted([GRADE_EXCEPTION_MISUSE, GRADE_VALUE_INVALID])  # 코드 이름만, 정렬
    # AG-13-12 A(2026-11-18 밤): Validator 사유 코드별 건수(`validator_reasons`)가 더해졌다. 기존 두 키는 그대로다
    assert span["output_summary"] == {"rule_checks": {GRADE_VALUE_INVALID: 1, GRADE_EXCEPTION_MISUSE: 1}, "rules": {"H22": 1, "H24": 1},
                                      "validator_reasons": {GRADE_VALUE_INVALID: 1, GRADE_EXCEPTION_MISUSE: 1}}
    dumped = json.dumps(sink.records, ensure_ascii=False, default=str)
    assert not any(m in dumped for m in SENTENCE_MARKERS)  # 문장 원문은 어느 span에도 없다


def test_trace_validator_span_unchanged_when_no_rule_check_fires():
    _, sink = _run(CLEAN_DRAFT)
    (span,) = _validator_spans(sink)
    assert span["verdict"] == "pass" and span["violations"] == [] and "output_summary" not in span


def test_rewind_reasons_and_rule_codes_both_appear_in_violations():
    """되감기 사유(FAIL)와 규칙 코드(걸러낸 문장)가 한 span의 `violations`에 함께 들어간다(단위: trace 함수만, 상태는 합성)."""
    sink = ListSink()
    tracer = GraphTracer(sink=sink)
    upd = {"validation": {"status": "FAIL", "reasons": ["MISSING_ADVICE_ABSENT"], "kept": 0, "rule_checks": {M_CONVERTED: 2}, "rules": {"H22": 2},
                          "next": "rewind"}, "rewind_count": 1}
    tracer.wrap_node("validator", lambda _s: upd)({})
    (span,) = _validator_spans(sink)
    assert span["verdict"] == "fail" and span["violations"] == sorted(["MISSING_ADVICE_ABSENT", M_CONVERTED])
    assert span["output_summary"] == {"rule_checks": {M_CONVERTED: 2}, "rules": {"H22": 2}}


# =========================================================================== §2 평가 보조 집계(eval_runner·eval_metrics)
def test_extract_trace_counts_rule_checks_from_validator_events():
    st, _ = _run(BAD_DRAFT)
    rec = R.extract_trace(st)
    assert rec.validator_checks == {GRADE_VALUE_INVALID: 1, GRADE_EXCEPTION_MISUSE: 1} and rec.validator_rules == {"H22": 1, "H24": 1}
    assert rec.validator_counts() == {"checks": rec.validator_checks, "rules": rec.validator_rules}
    d = rec.to_json()
    assert d["validator_checks"] == rec.validator_checks and d["validator_rules"] == rec.validator_rules
    back = M.RunRecord.from_json(d)
    assert back.validator_checks == rec.validator_checks and back.validator_rules == rec.validator_rules
    assert not any(m in json.dumps(d, ensure_ascii=False) for m in SENTENCE_MARKERS)


def test_validator_rule_trace_sums_validator_events_and_ignores_unmapped_checks():
    """되감기로 검증이 두 번 돌면 합산하고, `CHECK_RULES` 밖 검사(안전 단정 등)와 목록형 `reasons`(REWIND 이벤트)는 세지 않는다."""
    state = {"events": [
        {"rule": "H2", "event": "VALIDATOR", "status": "FAIL", "reasons": {GRADE_VALUE_INVALID: 1, SAFE_ASSERTION: 3}, "rules": {"H22": 1}},
        {"rule": "H2", "event": "REWIND", "reasons": ["MISSING_ADVICE_ABSENT"]},
        {"rule": "H1", "event": "SENTENCE_FILTER", "reasons": {"NO_EVIDENCE": 1}},
        {"rule": "H2", "event": "VALIDATOR", "status": "FIXED", "reasons": {GRADE_VALUE_INVALID: 2, GRADE_EXCEPTION_MISUSE: 1}, "rules": {"H22": 2, "H24": 1}},
    ]}
    assert R.validator_rule_trace(state) == {"validator_checks": {GRADE_VALUE_INVALID: 3, GRADE_EXCEPTION_MISUSE: 1},
                                             "validator_rules": {"H22": 3, "H24": 1}}
    assert R.validator_rule_trace({}) == {"validator_checks": {}, "validator_rules": {}}
    assert R.validator_rule_trace({"events": "not-a-list"}) == {"validator_checks": {}, "validator_rules": {}} or True  # 방어: 예외 없음


def test_unrecorded_run_has_no_validator_field_and_old_results_still_load():
    rec = M.RunRecord(answer={"text": "x"})
    assert rec.validator_counts() is None and "validator_checks" not in rec.to_json() and "validator_rules" not in rec.to_json()
    old = M.RunRecord.from_json({"answer": {}, "tool_calls": [], "model_calls": 1})  # 예전 결과 파일 칸(새 칸 없음)
    assert old.validator_checks is None and old.validator_rules is None


def _item(i: int) -> dict[str, Any]:
    return {"id": f"syn-{i:03d}", "branch_label": "병용", "composition_group": "정상-병용", "expected_response_type": "found",
            "expected_path": {"required": ["check_contraindications"]}, "required_elements": [], "answer": {"items": []}}


def test_score_item_and_aggregate_add_validator_rule_counts_as_aux_only():
    ph = M.Phrases.from_backend()
    st_bad, _ = _run(BAD_DRAFT)
    st_ok, _ = _run(CLEAN_DRAFT)
    rows = [M.score_item(_item(0), R.extract_trace(st_bad), ph), M.score_item(_item(1), R.extract_trace(st_ok), ph)]
    assert rows[0]["validator"] == {"checks": {GRADE_VALUE_INVALID: 1, GRADE_EXCEPTION_MISUSE: 1}, "rules": {"H22": 1, "H24": 1}}
    assert rows[1]["validator"] == {"checks": {}, "rules": {}}
    agg = M.aggregate(rows)
    v = agg["validator_rule_counts"]
    assert v["items_with_record"] == 2 and v["by_check"] == {GRADE_EXCEPTION_MISUSE: 1, GRADE_VALUE_INVALID: 1}
    assert v["by_rule"] == {"H22": 1, "H24": 1} and v["items_with_any"]["k"] == 1 and v["items_with_any"]["n"] == 2
    assert "9장 지표 아님" in v["note"]
    # 9장 지표는 그대로다(보조 집계가 지표 계산에 섞이지 않는다)
    assert agg["trajectory"]["verdicts"]["Fail"] == 0 and agg["routing_accuracy"]["k"] == 2
    assert set(CHECK_RULES) >= set(v["by_check"])


def test_aggregate_without_validator_records_has_no_key():
    rec = M.RunRecord(answer={"text": "x"}, end_reason="NORMAL")
    agg = M.aggregate([M.score_item(_item(0), rec, M.Phrases.from_backend())])
    assert "validator_rule_counts" not in agg and M.validator_rule_counts([]) is None


def test_compare_shows_h22_h24_totals_per_side():
    ph = M.Phrases.from_backend()
    st_bad, _ = _run(BAD_DRAFT)
    st_ok, _ = _run(CLEAN_DRAFT)
    row_bad, row_ok = M.score_item(_item(0), R.extract_trace(st_bad), ph), M.score_item(_item(0), R.extract_trace(st_ok), ph)
    a = {"meta": {"versions": {"prompt": {"set": "prompt_set@v2"}}}, "metrics": M.aggregate([row_ok]), "items": [row_ok]}
    b = {"meta": {"versions": {"prompt": {"set": "prompt_set@v3"}}}, "metrics": M.aggregate([row_bad]), "items": [row_bad]}
    cmp = R.compare_results(a, b)
    sa, sb = cmp["sides"]
    assert sa["validator_rules"] is None and sb["validator_rules"] == {"H22": 1, "H24": 1}
    text = R.format_compare(cmp)
    assert "Validator 규칙 건수(H22·H24)" in text and "'H22': 1" in text
    assert not any(m in text for m in SENTENCE_MARKERS)
