"""AG-05-03 A: 되묻기에서 고른 약(품목기준코드)으로 Router 엔티티를 확정한다. LLM·공공 API·원격 DB 호출 0.

- 매칭 규칙: 엔티티가 조회에 쓴 문자열을 사전에 다시 조회한 **제품 후보 집합** 안에 고른 코드가 있을 때만 확정한다(이름은 보지 않는다).
  여러 개가 맞으면 가장 나중에 고른 것. 사전에 없는 코드·후보가 아닌 코드·형식이 틀린 코드는 무시하고 지금 동작(되묻기)을 한다.
- 질문에 없는 약은 더하지 않는다. 빈 입력은 지금과 같다(평가 경로).
- 사전과 질문은 합성(`e2e/golden_synth.py`)이다. 평가 세트·시험셋 문항이 아니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import Q_P3, SEQ_AZI, SEQ_COLD, SEQ_KID, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from app.agent.graph.build import build_graph, initial_state, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.state import NODE_WRITABLE  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.router import (  # noqa: E402
    BRANCH_NORMAL,
    BRANCH_TYPO,
    FLAG_USER_CONFIRMED,
    ST_AMBIGUOUS,
    ST_NOT_FOUND,
    ST_RESOLVED,
    ST_TYPO,
    confirmed_seqs,
    route_input,
)
from app.tools.drug_dict import DrugDict  # noqa: E402

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_SHORT = f"타이레놀이랑 {AZI} 같이 먹어도 되나요?"  # `타이레놀` 후보 2개(정500·콜드-에스정)
Q_TYPO = "이지랙트정 먹어도 되나요?"  # BM25 후보 1개 → 오탈자 의심
Q_UNKNOWN = "가나다라정 먹어도 되나요?"  # 후보 없는 NOT_FOUND


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _ents(res) -> list[tuple[str, str, str | None]]:
    return [(e.raw, e.status, e.item_seq) for e in res.entities]


# --------------------------------------------------------------------------- 확정
def test_confirmed_seq_among_candidates_resolves_entity(dd):
    base = route_input(Q_SHORT, dd)
    assert base.ambiguous and _ents(base)[0] == ("타이레놀", ST_AMBIGUOUS, None)
    res = route_input(Q_SHORT, dd, confirmed_item_seqs=[SEQ_T500])
    e = res.entities[0]
    assert (e.raw, e.status, e.item_seq, e.branch) == ("타이레놀", ST_RESOLVED, SEQ_T500, BRANCH_NORMAL)
    assert e.resolved and not e.needs_clarification and e.options == [] and FLAG_USER_CONFIRMED in e.flags
    assert e.code_status == "linked" and e.matched_by == "product_name"
    assert not res.ambiguous and res.clarify is None and res.branch_label == BRANCH_NORMAL and res.n_pairs == 1
    assert FLAG_USER_CONFIRMED not in res.entities[1].flags  # 질문에서 원래 확정된 약은 표시를 붙이지 않는다


def test_latest_pick_wins_when_several_seqs_match(dd):
    assert route_input(Q_SHORT, dd, confirmed_item_seqs=[SEQ_T500, SEQ_COLD]).entities[0].item_seq == SEQ_COLD
    assert route_input(Q_SHORT, dd, confirmed_item_seqs=[SEQ_COLD, SEQ_T500]).entities[0].item_seq == SEQ_T500


def test_typo_suspect_picked_from_options_resolves(dd):
    base = route_input(Q_TYPO, dd)
    assert _ents(base) == [("이지랙트정", ST_TYPO, None)] and base.branch_label == BRANCH_TYPO
    res = route_input(Q_TYPO, dd, confirmed_item_seqs=[SEQ_AZI])
    assert _ents(res) == [("이지랙트정", ST_RESOLVED, SEQ_AZI)] and res.branch_label == BRANCH_NORMAL and not res.ambiguous


def test_two_tokens_resolving_to_same_pick_are_deduplicated(dd):
    """"타이레놀 콜드-에스"처럼 한 약이 두 토큰으로 나뉘어도 같은 코드로 확정되면 한 번만 남는다(기존 같은 제품 중복 제거)."""
    res = route_input(Q_P3, dd, confirmed_item_seqs=[SEQ_AZI, SEQ_COLD])
    assert [e.item_seq for e in res.entities] == [SEQ_AZI, SEQ_COLD] and not res.ambiguous and res.n_pairs == 1


# --------------------------------------------------------------------------- 무시(지금 동작)
@pytest.mark.parametrize("seqs", [
    ["999999999"],  # 사전에 없는 코드
    [SEQ_KID],  # 사전에 있지만 질문 속 어느 이름의 후보도 아닌 코드: 질문에 없는 약은 더하지 않는다
    ["12", "abcdefghi", None, 202106092, ""],  # 형식이 틀린 값
    [],
    None,
])
def test_unusable_seqs_leave_result_unchanged(dd, seqs):
    for q in (Q_SHORT, Q_P3, Q_TYPO, Q_UNKNOWN):
        assert route_input(q, dd, confirmed_item_seqs=seqs).model_dump() == route_input(q, dd).model_dump()


def test_not_found_without_candidates_stays_not_found(dd):
    res = route_input(Q_UNKNOWN, dd, confirmed_item_seqs=[SEQ_AZI])
    assert _ents(res) == [("가나다라정", ST_NOT_FOUND, None)]


def test_already_resolved_entity_is_not_overridden(dd):
    """질문에 정식 제품명이 있어 이미 확정된 약은 고른 약으로 바꾸지 않는다."""
    q = f"{T500}이랑 {AZI} 같이 먹어도 되나요?"
    assert route_input(q, dd, confirmed_item_seqs=[SEQ_COLD]).model_dump() == route_input(q, dd).model_dump()


def test_confirmed_seqs_filters_format_and_duplicates():
    assert confirmed_seqs([SEQ_AZI, "12", SEQ_AZI, None, SEQ_COLD]) == [SEQ_AZI, SEQ_COLD]
    assert confirmed_seqs(None) == [] and confirmed_seqs(()) == []


# --------------------------------------------------------------------------- 그래프 입력·비기록
def _script(a: str, b: str) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": ["contra_pair:254000ATB:625201ATB"],
     "claim_type": "fact", "citations": []},
    {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}


def test_initial_state_has_no_key_when_empty():
    """평가 경로(`run_question(graph, q, profile)`)의 시작 상태는 바뀌지 않는다."""
    assert initial_state("q") == initial_state("q", None, []) == initial_state("q", None, None) == {"question": "q", "call_count": 0,
                                                                                                    "rewind_count": 0}
    assert initial_state("q", None, [SEQ_AZI])["confirmed_item_seqs"] == [SEQ_AZI]
    assert not any("confirmed_item_seqs" in keys for keys in NODE_WRITABLE.values())  # 입력 전용: 어느 노드도 쓰지 않는다


def test_graph_second_turn_reaches_normal_and_trace_has_no_confirmed_values(dd):
    sink = ListSink()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm, sm = ScriptedToolModel(script=_script(AZI, COLD)), ScriptedSummary([PAIR_DRAFT])
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=sm, system_prompt="시험용 시스템 프롬프트",
                      tracer=GraphTracer(sink=sink, model="gpt-6-luna", api_enabled=ctx.api_enabled))
    graph = build_graph(deps)
    first = run_question(graph, Q_P3)
    assert first["end_reason"] == "CLARIFY" and tm.calls == []
    n_first = len(sink.records)
    second = run_question(graph, Q_P3, None, [SEQ_AZI, SEQ_COLD])
    assert second["end_reason"] == "NORMAL" and second["validation"]["status"] == "PASS"
    assert {it["evidence_id"]: it["status"] for it in second["evidence"]}["contra_pair:254000ATB:625201ATB"] == "FOUND"
    router_ev = next(e for e in second["events"] if e.get("event") == "ROUTER")
    assert router_ev["n_confirmed"] == 2 and set(router_ev) == {"rule", "event", "branch", "ambiguous", "n_entities", "n_confirmed"}
    assert "n_confirmed" not in next(e for e in first["events"] if e.get("event") == "ROUTER")  # 빈 입력이면 이벤트 모양도 그대로
    # router span에는 개수·라벨만 오르고 고른 코드는 오르지 않는다. 코드가 trace에 보이는 곳은 도구 근거 ID(`identify:<item_seq>`)뿐이며,
    # 이는 질문에 정식 제품명을 썼을 때와 같은 일반 조회 결과다(고른 약 입력을 옮긴 것이 아니다)
    second_recs = sink.records[n_first:]
    router_spans = json.dumps([r for r in second_recs if r.get("node") == "router"], ensure_ascii=False, default=str)
    assert router_spans != "[]" and SEQ_AZI not in router_spans and SEQ_COLD not in router_spans
    for r in second_recs:
        for k, v in r.items():
            if SEQ_AZI in json.dumps(v, ensure_ascii=False, default=str):
                assert k == "evidence_ids" and r.get("node") == "tools", (r.get("node"), k)
