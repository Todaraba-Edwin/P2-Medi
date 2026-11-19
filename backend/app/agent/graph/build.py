"""AG-01 그래프 조립(`StateGraph`, 6노드). 간선도:

    START → guardrail_in ─(범위 외 거절, 응급 아님)→ finalize → END
                │ 그 밖(응급이어도 계속)
                ▼
              router ─(모호·되묻기)→ finalize
                ▼
              model ─(상한 8 도달)→ finalize
                │ ⇅ (tool_calls 있으면 tools, 결과는 model로)
                │ (도구 호출 없음 → 같은 노드에서 구조화 요약 호출 → draft)
                ▼
            validator ─(실패 1회)→ model(되감기) / (두 번째 실패)→ finalize(안전 문구)
                ▼
             finalize → END
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.graph.nodes import GraphDeps, after_guardrail, after_model, after_router, after_validator, make_nodes
from app.agent.graph.state import AgentState

RECURSION_LIMIT = 60  # 모델 호출 상한 8(+도구 노드·되감기)을 넉넉히 덮는다. 실제 종료는 `call_count` 상한이 한다


def build_graph(deps: GraphDeps) -> Any:
    nodes = make_nodes(deps)
    g = StateGraph(AgentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "guardrail_in")
    g.add_conditional_edges("guardrail_in", after_guardrail, {"finalize": "finalize", "router": "router"})
    g.add_conditional_edges("router", after_router, {"finalize": "finalize", "model": "model"})
    g.add_conditional_edges("model", after_model, {"tools": "tools", "validator": "validator", "finalize": "finalize"})
    g.add_edge("tools", "model")
    g.add_conditional_edges("validator", after_validator, {"model": "model", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})


def initial_state(question: str, profile: dict[str, Any] | None = None,
                  confirmed_item_seqs: Sequence[str | dict[str, str]] | None = None) -> dict[str, Any]:
    """그래프 시작 상태. `run_question`과 `/chat` 스트림 실행기가 같은 값을 쓴다.

    `confirmed_item_seqs`(AG-05-03 A, 되묻기에서 고른 약: 품목기준코드 문자열 또는 `{"item_seq", "input_name"}`, FE-09-05 A)가 비어 있으면
    키를 두지 않는다(평가 경로와 같은 시작 상태)."""
    init: dict[str, Any] = {"question": question, "call_count": 0, "rewind_count": 0}
    if profile:
        init["profile"] = profile
    if confirmed_item_seqs:
        init["confirmed_item_seqs"] = list(confirmed_item_seqs)
    return init


def run_question(graph: Any, question: str, profile: dict[str, Any] | None = None,
                 confirmed_item_seqs: Sequence[str | dict[str, str]] | None = None) -> dict[str, Any]:
    """한 줄 호출. 질문 한 개를 끝까지 흘려 최종 상태를 돌려준다."""
    return graph.invoke(initial_state(question, profile, confirmed_item_seqs))  # type: ignore[no-any-return]
