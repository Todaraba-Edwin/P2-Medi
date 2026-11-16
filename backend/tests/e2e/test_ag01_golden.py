"""AG-01 정상 경로 회귀(RFP-33-04)·L2 계측(RFP-34-02)·DurClient 배선 시험. LLM·공공 API·DB 원격 호출 0.

- 골든 P1~P3 = RFP-21 §4.8 평가 문항 초안의 '정상' 3문항(페르소나 P1·P2·P3, RFP-21 §4.4~§4.6 질문).
- 도구 본문은 **실제**(`identify_drug`·`check_contraindications`)이고, 데이터만 합성 소사전·소규모 SQLite(`golden_synth`)다.
  DUR API는 가짜 `DurClient`(`FakeDur`)를 `build_tool_context`로 배선한다.
- 모델은 가짜 스크립트(`ScriptedToolModel`·`ScriptedSummary`)다. 기대 경로(Trajectory)는 노드 순서·도구 호출 순서·모델 호출 수로 단언한다.
- RFP-21 원문 질문은 약 이름이 짧게 쓰여(예 "콜드-에스") Router가 되묻기로 끝낸다(AG-05 설계: 접두·부분 일치는 하나로 고르지 않음).
  그래서 정상 경로는 **되묻기에 답한 뒤의 질문**(정식 제품명으로 바꾼 문장, `*_CONFIRMED`)으로 돌리고, 원문은 되묻기 후보에 정답 제품이 있는지를 본다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from golden_synth import (
    D_PSE,
    Q_P1,
    Q_P2,
    Q_P3,
    SEQ_COLD,
    SEQ_KID,
    SEQ_T500,
    FakeDur,
    golden_conn,
    golden_dict,
)
from langchain_core.messages import AIMessage

from app.agent import fixed_phrases as fp
from app.agent.graph.build import build_graph, run_question
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call
from app.agent.graph.prompt import load_system_prompt
from app.agent.graph.trace import HARNESS_ACTIONS, GraphTracer, ListSink, count_block_warn, harness_events
from app.agent.graph.wiring import DEFAULT_PROMPT, build_deps, build_tool_context, is_eval_mode
from app.logging import SpanLogger
from app.tools.drug_dict import DrugDict

T500, COLD, KID, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "어린이타이레놀현탁액", "이지렉트정1.0밀리그램"

# 되묻기에 답한 뒤의 질문(정식 제품명). 내용·프로필 신호(만 2세·임신 14주)는 원문과 같다
Q_P1_CONFIRMED = f"도윤이(만 2세)가 열이 나서 {KID}을 먹였는데 기침도 해요. 집에 있는 {COLD}을 반 알 줘도 되나요?"
Q_P2_CONFIRMED = f"임신 14주인데 열이 나요. 집에 {T500}이랑 {COLD}이 있는데 먹어도 되나요?"
Q_P3_CONFIRMED = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"

NODES_NORMAL = ["guardrail_in", "router", "model", "tools", "model", "tools", "model", "validator", "finalize"]
TOOLS_NORMAL = ["identify_drug", "identify_drug", "check_contraindications"]


def _script(a: str, b: str, **check: Any) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}], **check}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


def _guide() -> dict[str, Any]:
    return {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


def _fact(text: str, *eids: str) -> dict[str, Any]:
    return {"text": text, "evidence_ids": list(eids), "claim_type": "fact", "citations": []}


GOLDEN: dict[str, dict[str, Any]] = {
    "P1": {
        "q": Q_P1_CONFIRMED, "raw_q": Q_P1, "script": _script(KID, COLD, age={"value": 2, "unit": "세"}),
        "draft": {"sentences": [_fact("두 약은 연령 금기 목록에서 해당 항목이 조회되지 않았어요.", f"age:{SEQ_COLD}"), _guide()]},  # "만 2세"를 넣으면 Validator가 근거 밖 숫자로 지운다
        "profile": {"age_years": 2.0, "pregnant": None},
        "expect": {f"contra_pair:{SEQ_KID}:{SEQ_COLD}": ("contra_pair", "NOT_LISTED"), f"age:{SEQ_COLD}": ("age", "NOT_LISTED")},
        "raw_options": {KID, COLD},
    },
    "P2": {
        "q": Q_P2_CONFIRMED, "raw_q": Q_P2, "script": _script(T500, COLD, pregnancy=True),
        "draft": {"sentences": [_fact("타이레놀콜드-에스정에 든 성분이 임부금기 목록에 올라 있어요.", "pregnancy:448001ATB"), _guide()]},
        "profile": {"age_years": None, "pregnant": True},
        "expect": {"pregnancy:448001ATB": ("pregnancy", "FOUND"), "pregnancy:101300ATB": ("pregnancy", "NOT_LISTED"),
                   f"contra_pair:{SEQ_T500}:{SEQ_COLD}": ("contra_pair", "NOT_LISTED")},
        "raw_options": {T500, COLD},
    },
    "P3": {
        "q": Q_P3_CONFIRMED, "raw_q": Q_P3, "script": _script(AZI, COLD),
        "draft": {"sentences": [_fact("두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "contra_pair:254000ATB:625201ATB"), _guide()]},
        "profile": {"age_years": None, "pregnant": None},
        "expect": {"contra_pair:254000ATB:625201ATB": ("contra_pair", "FOUND")},
        "raw_options": {AZI, COLD},
    },
}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _run(dd: DrugDict, key: str, *, mode: str = "service", sink: Any = None) -> tuple[dict[str, Any], FakeDur, ListSink, ScriptedToolModel, ScriptedSummary]:
    g = GOLDEN[key]
    fd = FakeDur()
    ctx = build_tool_context(dd, mode=mode, dur_client=fd, conn_factory=golden_conn)
    tm, sm = ScriptedToolModel(script=list(g["script"])), ScriptedSummary([g["draft"]])
    sink = sink if sink is not None else ListSink()
    tracer = GraphTracer(sink=sink, prompt_version=DEFAULT_PROMPT, prompt_set="prompt_set@v2", graph_version="test", model="gpt-6-luna",
                         api_enabled=ctx.api_enabled)
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=sm, system_prompt="시험용 시스템 프롬프트", tracer=tracer)
    st = run_question(build_graph(deps), g["q"])
    return st, fd, sink, tm, sm


def _node_spans(sink: ListSink) -> list[dict[str, Any]]:
    return [r for r in sink.records if r.get("node") and "tool" not in r and "harness_event" not in r]


# --------------------------------------------------------------------------- ① 골든 정상 경로: 판정 도달·차단 0·기대 경로
@pytest.mark.parametrize("key", ["P1", "P2", "P3"])
def test_golden_normal_path_reaches_judgement_with_zero_harness_blocks(dd, key):
    g = GOLDEN[key]
    st, fd, sink, tm, sm = _run(dd, key)
    # 판정 도달
    assert st["end_reason"] == "NORMAL" and st["validation"]["status"] == "PASS" and st["rewind_count"] == 0
    by_id = {it["evidence_id"]: it for it in st["evidence"]}
    for eid, (kind, status) in g["expect"].items():
        assert eid in by_id, eid
        assert (by_id[eid]["kind"], by_id[eid]["status"]) == (kind, status)
    buckets = [e["bucket"] for e in st["answer"]["entries"]]
    assert {"found", "not_listed"} & set(buckets)
    assert buckets == sorted(buckets, key=["found", "not_listed", "identified", "unconfirmed"].index)  # FOUND 먼저
    # 하네스 차단·경고 0건(append·flag는 세지 않음)
    assert count_block_warn(st["events"]) == 0, harness_events(st["events"])
    assert not [e for e in st["events"] if e.get("event") in ("STATE_KEY_BLOCKED", "TOOL_KEY_DROPPED", "ARG_SCHEMA", "UNKNOWN_TOOL", "TOOL_ERROR")]
    # 기대 경로(Trajectory): 노드 순서·도구 순서·모델 호출 수(도구 노드용 3 + 요약 1)
    assert [r["node"] for r in _node_spans(sink)] == NODES_NORMAL
    assert [r["tool"] for r in sink.records if r.get("tool")] == TOOLS_NORMAL
    assert st["call_count"] == 4 and len(tm.calls) == 3 and len(sm.calls) == 1
    # 입력 정리(router): 프로필 신호, 되묻기 없음, 응급·거절 아님
    assert not st["ambiguous"] and st["route"] == "AGENT" and st["emergency"] is False
    assert {k: st["profile"].get(k) for k in ("age_years", "pregnant")} == g["profile"]
    # 고정 문구는 코드
    a = st["answer"]
    assert a["fixed_notice"] == fp.FIXED_NOTICE and a["disclaimer"] == fp.DISCLAIMER and a["emergency"] is None


def test_golden_p2_file_and_api_both_shown(dd):
    """P2 기대 동작 "두 출처 병기": 파일 임부금기 FOUND에 API 대조 꼬리표, 성분정보 API 항목(`API_DIRECT`)이 따로 있다.

    AG-01-09 A: 콜드-에스정은 API 성분 코드가 3개라 한도(2)로 잘린다. 대조가 끝나지 않았으므로 꼬리표는 `API_SAME`이 아니라 `API_FAIL`이다
    (파일 판정 FOUND·API 항목·호출 수는 그대로).
    """
    st, fd, *_ = _run(dd, "P2")
    by_id = {it["evidence_id"]: it for it in st["evidence"]}
    cold = by_id["pregnancy:448001ATB"]
    assert cold["status"] == "FOUND" and cold["api"]["codes_truncated"] is True
    assert set(cold["flags"]) & {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"} == {"API_FAIL"}
    api_items = [it for it in st["evidence"] if it.get("source_kind") == "API_DIRECT" and it["kind"] == "pregnancy"]
    assert api_items and any(m.get("grade") == "2등급" for it in api_items for m in it["matches"])
    assert ("by_ingredient", "pregnancy", D_PSE) in fd.calls


def test_golden_p3_contra_found_with_reason_and_api_cross_check(dd):
    st, fd, *_ = _run(dd, "P3")
    it = next(i for i in st["evidence"] if i["evidence_id"] == "contra_pair:254000ATB:625201ATB")
    assert it["matches"][0]["reason"] == "경련, 반사항진, 이상고열, 혼수 등" and it["matches"][0]["notice_no"] == "20250046"
    # 파일↔API 대조 꼬리표가 하나 붙는다. 콜드-에스정은 API 성분 코드가 3개라 한도(2)로 잘려 `API_PAIR_INCOMPLETE`다(AG-01-04 A)
    assert set(it["flags"]) & {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"} == {"API_PAIR_INCOMPLETE"}
    assert any(c[0] == "usjnt_pair_by_ingredient" for c in fd.calls)


@pytest.mark.parametrize("key", ["P1", "P2", "P3"])
def test_golden_raw_wording_clarifies_with_correct_products_in_options(dd, key):
    """RFP-21 원문(짧은 이름)은 되묻기로 끝나고(모델·도구 호출 0), 되묻기 후보에 정답 제품이 들어 있다."""
    g = GOLDEN[key]
    fd = FakeDur()
    ctx = build_tool_context(dd, mode="service", dur_client=fd, conn_factory=golden_conn)
    tm, sm = ScriptedToolModel(script=[]), ScriptedSummary([])
    st = run_question(build_graph(build_deps(dd, ctx, tool_model=tm, summary_model=sm, system_prompt="x")), g["raw_q"])
    assert st["end_reason"] == "CLARIFY" and tm.calls == [] and fd.calls == []
    cands = {o["name"] for e in st["entities"] for o in (e.get("options") or [])}  # 엔티티별 후보(한 번에 하나만 묻고 나머지는 다음 턴)
    assert g["raw_options"] <= cands, cands
    assert {o["name"] for o in st["clarify"]["options"]} & g["raw_options"]


# --------------------------------------------------------------------------- ② L2 계측
def test_trace_spans_hierarchy_and_header(dd):
    st, fd, sink, *_ = _run(dd, "P3")
    recs = sink.records
    trace_ids = {r["trace_id"] for r in recs}
    assert len(trace_ids) == 1
    nodes = _node_spans(sink)
    tools_spans = [r for r in recs if r.get("tool")]
    tools_nodes = [r["span_id"] for r in nodes if r["node"] == "tools"]
    assert all(t["parent_id"] in tools_nodes for t in tools_spans)  # 도구 span은 tools 노드 span의 자식
    assert [t["parent_id"] for t in tools_spans] == [tools_nodes[0], tools_nodes[0], tools_nodes[1]]  # 병렬 2개는 같은 step
    chk = tools_spans[-1]
    assert chk["evidence_ids"] and "contra_pair:254000ATB:625201ATB" in chk["evidence_ids"]
    assert chk["input_summary"]["n_drugs"] == 2 and chk["output_summary"]["statuses"].get("FOUND", 0) >= 1
    assert chk["source"] in ("file", "file+api") and chk["data_as_of"]
    model_spans = [r for r in nodes if r["node"] == "model"]
    assert [r["model_calls_so_far"] for r in model_spans] == [1, 2, 4] and all(r["cache"] == "off" for r in model_spans)
    v = next(r for r in nodes if r["node"] == "validator")
    assert v["verdict"] == "pass" and v["violations"] == []
    fin = next(r for r in nodes if r["node"] == "finalize")
    assert fin["end_reason"] == "NORMAL"
    head = next(r for r in recs if r["span_id"] == "s-0000")
    assert head["end_reason"] == "NORMAL" and head["api_enabled"] is True and head["model_calls_so_far"] == 4
    assert head["prompt_version"] == "agent_system@v2" and head["prompt_set"] == "prompt_set@v2"
    assert not [r for r in recs if "harness_event" in r]  # 정상 경로: 하네스 이벤트 span 0
    dump = json.dumps(recs, ensure_ascii=False)
    for secret_like in (Q_P3_CONFIRMED, "엄마가", "감기라서", COLD, AZI):  # 질문·약 이름 원문을 싣지 않는다
        assert secret_like not in dump


def test_trace_tokens_and_cost_from_usage_metadata(dd):
    from app.agent.llm import estimate_cost_usd

    g = GOLDEN["P3"]
    script = [m.model_copy(update={"usage_metadata": {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050}}) for m in g["script"]]
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    sink = ListSink()
    tracer = GraphTracer(sink=sink, model="gpt-6-luna", cost_fn=lambda i, o, c: estimate_cost_usd(i, o, c))
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([g["draft"]]), system_prompt="x", tracer=tracer)
    run_question(build_graph(deps), g["q"])
    ms = [r for r in sink.records if r.get("node") == "model" and "tokens_in" in r]
    assert len(ms) == 3 and all(r["tokens_in"] == 1000 and r["tokens_out"] == 50 for r in ms)
    head = next(r for r in sink.records if r["span_id"] == "s-0000")
    assert head["tokens_in"] == 3000 and head["total_cost_usd"] == pytest.approx(3 * estimate_cost_usd(1000, 50), rel=1e-6)


def test_trace_harness_events_for_limit_and_arg_schema(dd):
    bad = AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": []}, "bad")])
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    sink = ListSink()
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[bad], repeat_last=True), summary_model=ScriptedSummary([]),
                      system_prompt="x", tracer=GraphTracer(sink=sink))
    st = run_question(build_graph(deps), Q_P3_CONFIRMED)
    assert st["end_reason"] == "LIMIT"
    hs = [r["harness_event"] for r in sink.records if "harness_event" in r]
    assert {"rule": "H12", "action": "block", "detail": "CALL_LIMIT"} in hs
    assert sum(1 for h in hs if h["detail"] == "ARG_SCHEMA") == 8  # 모델 호출 8번이 모두 잘못된 도구 호출 → 도구 노드 8번 모두 인자 차단, 9번째 모델 진입에서 상한
    assert count_block_warn(st["events"]) == 9
    tool_errs = [r for r in sink.records if r.get("tool") and r["output_summary"].get("error_code") == "ARG_SCHEMA"]
    assert len(tool_errs) == 8


def test_harness_event_mapping_is_content_free():
    evs = [{"rule": "H4", "event": "GUARDRAIL_IN", "emergency": True, "route": "REFUSE", "reason": "STOP_DOSE_CHANGE"},
           {"rule": "H2", "event": "REWIND", "reasons": ["X"]}, {"rule": "H8", "event": "INJECTION_IN_TOOL_RESULT", "tool": "t"},
           {"rule": "H1", "event": "SENTENCE_FILTER", "dropped": 1}, {"rule": "H2", "event": "VALIDATOR", "status": "FIXED"},
           {"rule": "H11", "event": "ROUTER"}]
    hs = harness_events(evs)
    assert [h["action"] for h in hs] == ["append", "block", "rollback", "flag", "warn", "warn"]
    assert all(set(h) == {"rule", "action", "detail"} for h in hs)
    assert count_block_warn(evs) == 4
    assert set(HARNESS_ACTIONS.values()) <= {"block", "warn", "flag", "rollback"}


def test_span_logger_dev_writes_jsonl_and_service_writes_no_file(dd, tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    _run(dd, "P2", sink=SpanLogger(mode="dev"))
    files = list((tmp_path / "dev").glob("*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(x) for x in files[0].read_text(encoding="utf-8").splitlines()]
    assert lines and all(x["schema"] == "mediagent.span@v1" for x in lines)
    assert any(x.get("tool") == "check_contraindications" for x in lines) and any(x.get("span_id") == "s-0000" for x in lines)

    import io

    from app.logging import Aggregator

    svc_dir = tmp_path / "svc"
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(svc_dir))
    buf = io.StringIO()
    agg = Aggregator(stream=buf)
    _run(dd, "P2", sink=SpanLogger(mode="service", aggregator=agg))
    line = agg.flush()
    assert not svc_dir.exists()  # 서비스 모드는 파일을 만들지 않는다(RFP-22-06)
    assert line and line["counts"].get("node=tools") == 5 and line["counts"].get("tool=check_contraindications") == 1 and line["counts"].get("end_reason=NORMAL") == 1
    assert "타이레놀" not in buf.getvalue()


# --------------------------------------------------------------------------- ③ DurClient 배선
def test_service_mode_wires_dur_client_and_calls_it(dd):
    st, fd, *_ = _run(dd, "P2", mode="service")
    assert fd.calls and any(c[0] == "by_ingredient" for c in fd.calls)


def test_eval_mode_makes_zero_api_calls_and_builds_no_client(dd):
    built: list[Any] = []
    ctx = build_tool_context(dd, mode="eval", dur_factory=lambda s: built.append(s) or FakeDur(), conn_factory=golden_conn)
    assert ctx.api_enabled is False and ctx.api_pair_fn is None and ctx.api_age_fn is None and ctx.api_pregnancy_fn is None and built == []
    st, fd, *_ = _run(dd, "P2", mode="eval")
    assert fd.calls == []
    assert st["end_reason"] == "NORMAL"
    for it in st["evidence"]:
        assert not set(it.get("flags") or []) & {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL"}
        assert it.get("source_kind") != "API_DIRECT"


def test_default_factory_uses_settings_via_dur_factory(dd):
    seen: list[Any] = []
    sentinel = object()
    fd = FakeDur()
    ctx = build_tool_context(dd, settings=sentinel, mode="dev", dur_factory=lambda s: seen.append(s) or fd)
    assert seen == [sentinel] and ctx.api_enabled is True
    assert ctx.api_pair_fn == fd.usjnt_pair_by_ingredient
    ctx.api_pregnancy_fn("D000448")  # type: ignore[misc]
    ctx.api_age_fn("D000147")  # type: ignore[misc]
    assert fd.calls == [("by_ingredient", "pregnancy", "D000448"), ("by_ingredient", "age", "D000147")]


def test_real_dur_client_from_settings_without_network(dd, monkeypatch):
    """기본 팩토리는 실제 `DurClient.from_settings`를 쓴다(객체 생성만, 호출 0). 키 값은 다루지 않는다."""
    from app.config import Settings
    from app.tools.dur import DurClient

    s = Settings(_env_file=None, mediagent_api_mode="snapshot")  # type: ignore[call-arg]
    ctx = build_tool_context(dd, settings=s, mode="service")
    assert ctx.api_enabled and isinstance(ctx.api_pair_fn.__self__, DurClient)  # type: ignore[union-attr]


@pytest.mark.parametrize("env,expected", [({"MEDIAGENT_MODE": "eval", "MEDIAGENT_EVAL": "1"}, True), ({"MEDIAGENT_MODE": "service"}, False),
                                          ({"MEDIAGENT_MODE": "dev"}, False), ({}, False), ({"MEDIAGENT_EVAL": "1"}, True)])
def test_is_eval_mode_from_env(monkeypatch, env, expected):
    for k in ("MEDIAGENT_MODE", "MEDIAGENT_EVAL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert is_eval_mode() is expected


# --------------------------------------------------------------------------- ④ 기본 프롬프트 v2
def test_build_deps_default_prompt_is_agent_system_v2(dd):
    ctx = build_tool_context(dd, api_enabled=False)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[]), summary_model=ScriptedSummary([]))
    assert DEFAULT_PROMPT == "agent_system@v2"
    assert deps.system_prompt == load_system_prompt("agent_system@v2") == load_system_prompt()
    assert deps.system_prompt != load_system_prompt("agent_system@v1")


# --------------------------------------------------------------------------- N5 연결: 골든 최종 상태 → BE-06 응답 골격
def test_golden_state_converts_to_chat_response(dd):
    from app.api.schemas import DATE_LABEL_AS_OF, DATE_LABEL_QUERIED, response_from_state

    st, *_ = _run(dd, "P2")
    r = response_from_state(st)
    assert r.end_reason == "NORMAL" and r.route == "AGENT" and r.fixed_notice[-1] == fp.FIXED_NOTICE
    rows = {(c.publisher, c.dataset): c for c in r.citations}
    preg = rows[("한국의약품안전관리원", "임부금기 파일")]
    assert [(d.label, d.value) for d in preg.dates if d.label == DATE_LABEL_AS_OF] == [("기준일", "2026-07-21")]
    combo = rows[("한국의약품안전관리원", "병용금기 파일")]
    assert [(d.label, d.value) for d in combo.dates if d.label == DATE_LABEL_AS_OF] == [("기준일", "2026-07-31")]  # 자료별 기준일(AG-08-03 B)
    api = rows[("식약처", "DUR 성분정보 API")]
    assert [(d.label, d.value) for d in api.dates if d.label == DATE_LABEL_QUERIED] == [("조회", "2026-11-11")]
    assert r.citations[0].publisher == "식약처"  # 두 기관 모두 판정 자료가 있으면 식약처 → 한국의약품안전관리원(PRD-12 §4.5)
    dumped = r.model_dump_json()
    assert Q_P2_CONFIRMED not in dumped and "임신 14주" not in dumped  # 질문 원문은 응답에 싣지 않는다
