"""AG-01 후속 시험(2026-11-11 3차 A4). LLM·공공 API·원격 DB 호출 0(가짜 모델·가짜 DurClient·임시 캐시·임시 원장).

① 되묻기 → 확인 문장 경로: RFP-21 원문(짧은 이름)이 되묻기(CLARIFY)로 끝난 뒤, 사용자가 후보 중 정식 제품명으로 확인하는 문장을 보내면
   같은 그래프·계측기로 정상 경로(NORMAL)에 도달한다. 두 턴은 trace가 따로이고 첫 턴은 모델·API 호출 0이다.
   다중 턴 문맥(`confirmed_mentions`)은 아직 없어서, 짧은 확인 답("네, ○○ 맞아요")은 첫 턴의 프로필 신호(임신 등)를 잃는다(xfail로 고정).
② L2: 요약(구조화 출력) 호출 토큰이 `model` 노드 span과 trace 머리 합계에 들어가고(새 span 없음), `llm_cache` 상태가 `cache`에 적힌다.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from golden_synth import D_APAP, D_DXM, D_RASA, FakeDur, golden_conn, golden_dict
from langchain_core.messages import AIMessage
from test_ag01_golden import AZI, COLD, GOLDEN, NODES_NORMAL, T500, _node_spans

from app.agent.graph.build import build_graph, run_question
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel
from app.agent.graph.metered import CachedSummary, CachedToolModel, unwrap_summary
from app.agent.graph.trace import GraphTracer, ListSink
from app.agent.graph.wiring import build_deps, build_tool_context
from app.agent.llm import estimate_cost_usd
from app.agent.tools import check_contraindications as cc
from app.llm import CostLedger
from app.tools.drug_dict import DrugDict
from app.tools.dur import DurRow
from app.tools.provenance import API_REASON_NOTES, FLAG_NOTES

USAGE_TOOL = {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050}
USAGE_SUM = {"input_tokens": 1500, "output_tokens": 200, "total_tokens": 1700}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _deps(dd: DrugDict, tm: Any, sm: Any, sink: ListSink, **tr: Any) -> tuple[Any, FakeDur]:
    fd = FakeDur()
    ctx = build_tool_context(dd, mode="service", dur_client=fd, conn_factory=golden_conn)
    tracer = GraphTracer(sink=sink, model="gpt-6-luna", api_enabled=ctx.api_enabled, **tr)
    return build_deps(dd, ctx, tool_model=tm, summary_model=sm, system_prompt="시험용 시스템 프롬프트", tracer=tracer), fd


def _headers(sink: ListSink) -> list[dict[str, Any]]:
    return [r for r in sink.records if r.get("span_id") == "s-0000"]


# --------------------------------------------------------------------------- ① 되묻기 → 확인 문장
@pytest.mark.parametrize("key", ["P1", "P2", "P3"])
def test_clarify_then_confirmation_sentence_reaches_normal(dd, key):
    g = GOLDEN[key]
    sink = ListSink()
    tm, sm = ScriptedToolModel(script=list(g["script"])), ScriptedSummary([g["draft"]])
    deps, fd = _deps(dd, tm, sm, sink)
    graph = build_graph(deps)

    first = run_question(graph, g["raw_q"])  # 턴 1: 원문 → 되묻기
    assert first["end_reason"] == "CLARIFY" and tm.calls == [] and sm.calls == [] and fd.calls == []
    offered = {o["name"] for e in first["entities"] for o in (e.get("options") or [])}
    assert g["raw_options"] <= offered  # 확인 문장에 쓸 정식 제품명은 첫 턴 후보에서 고른 것이다
    n_first = len(sink.records)

    second = run_question(graph, g["q"])  # 턴 2: 후보에서 고른 정식 제품명으로 다시 묻는 확인 문장
    assert second["end_reason"] == "NORMAL" and second["validation"]["status"] == "PASS"
    assert second["call_count"] == 4 and len(tm.calls) == 3 and len(sm.calls) == 1
    by_id = {it["evidence_id"]: it for it in second["evidence"]}
    for eid, (kind, status) in g["expect"].items():
        assert (by_id[eid]["kind"], by_id[eid]["status"]) == (kind, status)
    assert {k: second["profile"].get(k) for k in ("age_years", "pregnant")} == g["profile"]

    heads = _headers(sink)
    assert [h["end_reason"] for h in heads] == ["CLARIFY", "NORMAL"]
    assert heads[0]["trace_id"] != heads[1]["trace_id"] and heads[0]["model_calls_so_far"] == 0
    turn2 = ListSink()
    turn2.records = [r for r in sink.records[n_first:]]
    assert [r["node"] for r in _node_spans(turn2) if r.get("span_id") != "s-0000"] == NODES_NORMAL


def test_short_confirmation_reply_reaches_normal_p3(dd):
    """확인 답만 짧게 보내도(정식 제품명 두 개) 병용금기 판정에 도달한다(P3에는 프로필 신호가 없어 문맥 손실이 없다)."""
    g = GOLDEN["P3"]
    sink = ListSink()
    tm, sm = ScriptedToolModel(script=list(g["script"])), ScriptedSummary([g["draft"]])
    deps, _ = _deps(dd, tm, sm, sink)
    graph = build_graph(deps)
    assert run_question(graph, g["raw_q"])["end_reason"] == "CLARIFY"
    st = run_question(graph, f"네, {AZI}이랑 {COLD} 맞아요. 같이 먹어도 되나요?")
    assert st["end_reason"] == "NORMAL"
    assert {it["evidence_id"]: it["status"] for it in st["evidence"]}["contra_pair:254000ATB:625201ATB"] == "FOUND"


@pytest.mark.xfail(strict=True, reason="다중 턴 문맥(confirmed_mentions) 미구현: 짧은 확인 답은 첫 턴의 '임신 14주' 신호를 잃는다(AG-05·BE-06 후속)")
def test_short_confirmation_keeps_first_turn_pregnancy_signal(dd):
    g = GOLDEN["P2"]
    sink = ListSink()
    deps, _ = _deps(dd, ScriptedToolModel(script=list(g["script"])), ScriptedSummary([g["draft"]]), sink)
    graph = build_graph(deps)
    assert run_question(graph, g["raw_q"])["end_reason"] == "CLARIFY"
    st = run_question(graph, f"네, {T500}이랑 {COLD} 맞아요.")
    assert st["profile"].get("pregnant") is True


# --------------------------------------------------------------------------- ② 요약 호출 토큰
class RawSummary:
    """`include_raw=True` 구조화 출력 모양의 가짜(토큰 메타 포함). 호출 수만 센다."""

    def __init__(self, draft: dict[str, Any], usage: dict[str, Any] | None = USAGE_SUM, error: Exception | None = None) -> None:
        self.draft, self.usage, self.error, self.calls = draft, usage, error, 0

    def invoke(self, messages: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
        self.calls += 1
        raw = AIMessage("{}", usage_metadata=self.usage) if self.usage else AIMessage("{}")
        return {"raw": raw, "parsed": None if self.error else self.draft, "parsing_error": self.error}


def _script_with_usage(g: dict[str, Any]) -> list[AIMessage]:
    return [m.model_copy(update={"usage_metadata": USAGE_TOOL}) for m in g["script"]]


def test_summary_call_tokens_fold_into_model_node_span_and_header(dd):
    g = GOLDEN["P3"]
    sink = ListSink()
    deps, _ = _deps(dd, ScriptedToolModel(script=_script_with_usage(g)), RawSummary(g["draft"]), sink, cost_fn=estimate_cost_usd)
    st = run_question(build_graph(deps), g["q"])
    assert st["end_reason"] == "NORMAL"
    model_spans = [r for r in _node_spans(sink) if r["node"] == "model" and r.get("span_id") != "s-0000"]
    assert len(model_spans) == 3  # 요약 호출은 새 span을 만들지 않는다(노드 span 6종 유지)
    last = model_spans[-1]
    assert last["tokens_in"] == 1000 + 1500 and last["tokens_out"] == 50 + 200
    assert last["cost_usd"] == pytest.approx(estimate_cost_usd(1000, 50) + estimate_cost_usd(1500, 200), rel=1e-6)
    sc = last["output_summary"]["summary_call"]
    assert sc == {"cache": "off", "parsed": True, "tokens_in": 1500, "tokens_out": 200, "tokens_cached": 0,
                  "cost_usd": pytest.approx(estimate_cost_usd(1500, 200), rel=1e-6)}
    assert all("summary_call" not in r["output_summary"] for r in model_spans[:-1])
    head = _headers(sink)[0]
    assert head["tokens_in"] == 3 * 1000 + 1500 and head["tokens_out"] == 3 * 50 + 200
    assert head["total_cost_usd"] == pytest.approx(3 * estimate_cost_usd(1000, 50) + estimate_cost_usd(1500, 200), rel=1e-6)


def test_plain_dict_summary_still_works_without_usage(dd):
    """가짜 요약(초안 dict만)은 예전처럼 동작하고 요약 내역은 토큰 0·cache off로 남는다."""
    g = GOLDEN["P3"]
    sink = ListSink()
    deps, _ = _deps(dd, ScriptedToolModel(script=list(g["script"])), ScriptedSummary([g["draft"]]), sink)
    assert run_question(build_graph(deps), g["q"])["end_reason"] == "NORMAL"
    last = [r for r in _node_spans(sink) if r["node"] == "model"][-1]
    assert "tokens_in" not in last and last["output_summary"]["summary_call"]["tokens_in"] == 0 and last["cache"] == "off"


def test_unwrap_summary_shapes():
    d = {"sentences": []}
    assert unwrap_summary(d) == (d, None)
    raw = AIMessage("{}")
    assert unwrap_summary({"raw": raw, "parsed": d, "parsing_error": None}) == (d, raw)
    with pytest.raises(ValueError):
        unwrap_summary({"raw": raw, "parsed": None, "parsing_error": ValueError("bad")})


# --------------------------------------------------------------------------- ② llm_cache 상태(hit/stored/off)
@pytest.fixture
def cache_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    # llm_cache가 불러오는 _common은 anthropic을 import한다. 백엔드 venv에는 없으므로 가짜 모듈(실호출 없음, test_be15_llm과 같은 방식)
    monkeypatch.setitem(sys.modules, "anthropic", sys.modules.get("anthropic") or types.ModuleType("anthropic"))
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)
    yield tmp_path
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)


def _cached_run(dd: DrugDict, g: dict[str, Any], script: list[AIMessage], ledger: CostLedger) -> tuple[dict[str, Any], ListSink, Any, Any]:
    inner_tm, inner_sm = ScriptedToolModel(script=script), RawSummary(g["draft"])
    tm = CachedToolModel(inner_tm, ledger=ledger, estimate_usd=0.001)
    sm = CachedSummary(inner_sm, ledger=ledger, estimate_usd=0.001)
    sink = ListSink()
    deps, _ = _deps(dd, tm, sm, sink, cost_fn=estimate_cost_usd)
    return run_question(build_graph(deps), g["q"]), sink, (inner_tm, inner_sm), (tm, sm)


def test_record_then_replay_cache_status_reaches_spans(dd, cache_env, monkeypatch):
    g = GOLDEN["P3"]
    ledger = CostLedger(cache_env / "ledger.json")
    monkeypatch.setenv("LLM_CACHE", "record")
    st1, sink1, (itm1, ism1), (tm1, sm1) = _cached_run(dd, g, _script_with_usage(g), ledger)
    assert st1["end_reason"] == "NORMAL" and len(itm1.calls) == 3 and ism1.calls == 1
    assert tm1.status_counts == {"stored": 3} and sm1.status_counts == {"stored": 1}
    spent = ledger.spent("dev")
    assert spent == pytest.approx(3 * estimate_cost_usd(1000, 50) + estimate_cost_usd(1500, 200), rel=1e-6)  # 실호출만 원장에
    assert [r["cache"] for r in _node_spans(sink1) if r["node"] == "model"] == ["stored"] * 3

    monkeypatch.setenv("LLM_CACHE", "replay")
    st2, sink2, (itm2, ism2), (tm2, sm2) = _cached_run(dd, g, [], ledger)  # 내부 모델 스크립트가 비어도 저장본으로 끝까지 간다
    assert st2["end_reason"] == "NORMAL" and itm2.calls == [] and ism2.calls == 0
    assert tm2.status_counts == {"hit": 3} and sm2.status_counts == {"hit": 1}
    model_spans = [r for r in _node_spans(sink2) if r["node"] == "model"]
    assert [r["cache"] for r in model_spans] == ["hit"] * 3 and model_spans[-1]["output_summary"]["summary_call"]["cache"] == "hit"
    assert ledger.spent("dev") == pytest.approx(spent)  # 적중은 비용 0
    assert {it["evidence_id"]: it["status"] for it in st2["evidence"]} == {it["evidence_id"]: it["status"] for it in st1["evidence"]}


def test_eval_mode_forces_cache_off_even_if_record(dd, cache_env, monkeypatch):
    g = GOLDEN["P3"]
    monkeypatch.setenv("LLM_CACHE", "record")
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    st, sink, (itm, _), (tm, sm) = _cached_run(dd, g, _script_with_usage(g), CostLedger(cache_env / "ledger.json"))
    assert st["end_reason"] == "NORMAL" and len(itm.calls) == 3
    assert tm.status_counts == {"off": 3} and sm.status_counts == {"off": 1}
    assert {r["cache"] for r in _node_spans(sink) if r["node"] == "model"} == {"off"}
    assert not list((cache_env / "cache").glob("*.json"))


def test_summary_parsing_error_is_raised_and_not_cached(dd, cache_env, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "record")
    sm = CachedSummary(RawSummary({"sentences": []}, error=ValueError("schema")), ledger=CostLedger(cache_env / "ledger.json"))
    with pytest.raises(ValueError):
        sm.invoke([AIMessage("x")])
    assert not list((cache_env / "cache").glob("*.json"))


# --------------------------------------------------------------------------- ③ AG-02 MAX_API_CODES_PER_DRUG=2 점검
# 합성 3성분 복합제(타이레놀콜드-에스정: API 성분코드 D_APAP·D_PSE·D_DXM)의 세 번째 성분 쌍은 API에 묻지 않는다(호출 수 그대로).
# AG-01-04 A(2026-11-12 결정, 2026-11-16 이행): 잘린 성분이 있으면 `FILE_ONLY`·`API_SAME` 대신 `API_PAIR_INCOMPLETE`를 붙인다.
# 한도를 3으로 올린 반사실 시험 2건은 그대로다.


def _pair_calls(fd: FakeDur) -> set[frozenset[str]]:
    return {frozenset(c[1:]) for c in fd.calls if c[0] == "usjnt_pair_by_ingredient"}


def _run_tools_only(dd: DrugDict, key: str, fd: FakeDur) -> dict[str, Any]:
    g = GOLDEN[key]
    ctx = build_tool_context(dd, mode="service", dur_client=fd, conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=list(g["script"])), summary_model=ScriptedSummary([g["draft"]]), system_prompt="x")
    return run_question(build_graph(deps), g["q"])


def test_third_ingredient_pair_not_queried_gives_pair_incomplete_on_p3(dd):
    """P3: 파일 병용금기 FOUND인데 API의 해당 쌍(D_DXM×D_RASA)은 세 번째 성분이라 묻지 않는다 → `API_PAIR_INCOMPLETE`
    ("실시간 확인을 하지 못함"). `FILE_ONLY`("해제되었을 수 있어요")로 말하지 않는다(AG-01-04 A)."""
    assert cc.MAX_API_CODES_PER_DRUG == 2
    fd = FakeDur()
    st = _run_tools_only(dd, "P3", fd)
    assert frozenset({D_DXM, D_RASA}) not in _pair_calls(fd) and len(_pair_calls(fd)) == 2
    it = next(i for i in st["evidence"] if i["evidence_id"] == "contra_pair:254000ATB:625201ATB")
    assert it["status"] == "FOUND" and "API_PAIR_INCOMPLETE" in it["flags"]
    assert not {"FILE_ONLY", "TRUNCATED", "API_SAME"} & set(it["flags"])  # 대조가 끝나지 않았으므로 "파일에만 있음"·"같음"은 붙지 않는다
    # 노트는 사유(`TRUNCATED`)별 승인 문구(AG-01-11 A)다. "해제되었을 수 있어요"(FILE_ONLY)로 말하지 않는다
    assert API_REASON_NOTES["TRUNCATED"] in it["notes"] and FLAG_NOTES["FILE_ONLY"] not in it["notes"]
    assert not [i for i in st["evidence"] if i.get("source_kind") == "API_DIRECT" and i["kind"] == "contra_pair"]


def test_p3_counterfactual_limit_3_queries_all_and_agrees(dd, monkeypatch):
    monkeypatch.setattr(cc, "MAX_API_CODES_PER_DRUG", 3)
    fd = FakeDur()
    st = _run_tools_only(dd, "P3", fd)
    assert frozenset({D_DXM, D_RASA}) in _pair_calls(fd)
    it = next(i for i in st["evidence"] if i["evidence_id"] == "contra_pair:254000ATB:625201ATB")
    assert "API_SAME" in it["flags"] and "FILE_ONLY" not in it["flags"]


class _DurThirdOnly(FakeDur):
    """합성: 파일에는 없는 병용 쌍이 API에서는 세 번째 성분(D_DXM)×D_APAP로만 조회된다(기준일 이후 새 지정 가정)."""

    def usjnt_pair_by_ingredient(self, a: str, b: str):  # type: ignore[no-untyped-def]
        res = super().usjnt_pair_by_ingredient(a, b)
        if {a, b} == {D_DXM, D_APAP}:
            res = res.model_copy(update={"rows": [DurRow(kind="usjnt", level="ingr", ingr_code=a, pair_ingr_code=b, content="합성 사유",
                                                         notification_date_raw="20261101", notification_date="2026-11-01")]})
        return res


def test_third_ingredient_api_only_signal_is_lost_but_flag_does_not_say_same(dd):
    """P2 쌍(파일 NOT_LISTED): API에만 있는 세 번째 성분 쌍을 묻지 않아 `API_ONLY`(새 지정 가능)는 여전히 못 잡지만,
    `API_SAME`("같아요") 대신 `API_PAIR_INCOMPLETE`가 붙는다(AG-01-04 A)."""
    fd = _DurThirdOnly()
    st = _run_tools_only(dd, "P2", fd)
    assert frozenset({D_DXM, D_APAP}) not in _pair_calls(fd)
    pair = next(i for i in st["evidence"] if i["kind"] == "contra_pair" and i.get("source_kind") != "API_DIRECT")
    assert pair["status"] == "NOT_LISTED" and "API_PAIR_INCOMPLETE" in pair["flags"]
    assert not {"API_SAME", "API_ONLY", "FILE_ONLY"} & set(pair["flags"])


def test_third_ingredient_counterfactual_limit_3_surfaces_api_only(dd, monkeypatch):
    monkeypatch.setattr(cc, "MAX_API_CODES_PER_DRUG", 3)
    fd = _DurThirdOnly()
    st = _run_tools_only(dd, "P2", fd)
    pair = next(i for i in st["evidence"] if i["kind"] == "contra_pair" and i.get("source_kind") != "API_DIRECT")
    assert "API_ONLY" in pair["flags"]
    assert [i for i in st["evidence"] if i.get("source_kind") == "API_DIRECT" and i["kind"] == "contra_pair"]
