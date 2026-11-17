"""AG-16 C1 고정 파이프라인 조립(LangGraph `StateGraph`, 호출 순서 고정). 간선도:

    START → guardrail_in ─(범위 외 거절, 응급 아님)→ finalize → END
                │
              router ─(되묻기, 예외 규칙 2)→ finalize
                │
          identify_drug ─(식별 0건, 예외 규칙 1)→ finalize
                │
    check_contraindications → search_reason → search_label → model(요약 1회) → validator ─(실패 1회)→ model(되감기)
                                                                                   │ (통과 / 두 번째 실패)
                                                                                 finalize → END

같은 모델·같은 도구 함수·같은 Guardrail·Validator·고정 문구(`GraphDeps`를 ReAct 그래프와 그대로 공유). 차이는 도구를 부르는 순서·횟수를 누가 정하나(코드 대 LLM)뿐이다.
평가 설정 식별자(C1·C1+·C2)로 그래프를 고르는 `build_for_condition`을 둔다(BE-08·eval_runner 연결용). C1+는 설정 자리만 있다(AG-10 뒤 구현).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.graph.build import build_graph, initial_state, run_question
from app.agent.graph.nodes import GraphDeps, after_guardrail, after_router, after_validator, guard_node
from app.agent.pipeline.nodes import after_identify, make_pipeline_nodes
from app.agent.pipeline.state import PIPELINE_WRITABLE, PipelineState

PIPELINE_VERSION = "c1-pipeline@v1"  # 결과 파일 `graph_version`용. 규칙을 바꾸면 올리고 이전 결과와 섞지 않는다(RFP 9.6절, BE-08 RFP-34-04)
RECURSION_LIMIT = 30  # 노드 9개 + 되감기 1회를 넉넉히 덮는다
CONDITION_C1, CONDITION_C1_PLUS, CONDITION_C2 = "C1", "C1+", "C2"
HARNESS_VERSION = "harness@v1"
# 조건별 하네스 적용표(RFP-33-03 A, PJ2-Agent-Harness.md 7.2절). 기준선 장치는 공통, 개선 단계 선택 제한 장치는 C3에서만 ablation으로 더한다
HARNESS_BASELINE = ("ARG_SCHEMA", "TOOL_OUTPUT_CONTRACT", "STATE_KEY_LIMIT", "FINALIZE_PHRASES")


@dataclass(frozen=True)
class PipelineConfig:
    """C1(기본)·C1+(강화) 전환. `typo_retry=True`가 C1+(오탈자 보정 후 재검색 1회)이며 구현은 AG-10 뒤로 미룬다(지금은 `NotImplementedError`)."""

    typo_retry: bool = False

    @property
    def condition(self) -> str:
        return CONDITION_C1_PLUS if self.typo_retry else CONDITION_C1


def build_pipeline(deps: GraphDeps, config: PipelineConfig | None = None) -> Any:
    cfg = config or PipelineConfig()
    if cfg.typo_retry:
        raise NotImplementedError("C1+(오탈자 보정 후 재검색 1회)는 AG-10 오탈자 보정 뒤에 구현한다(RFP-23 §5.2). 지금은 설정 자리만 있다")
    nodes = {name: guard_node(deps, name, fn, PIPELINE_WRITABLE) for name, fn in make_pipeline_nodes(deps).items()}
    g = StateGraph(PipelineState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "guardrail_in")
    g.add_conditional_edges("guardrail_in", after_guardrail, {"finalize": "finalize", "router": "router"})
    g.add_conditional_edges("router", after_router, {"finalize": "finalize", "model": "identify_drug"})  # 되묻기 → finalize(예외 규칙 2)
    g.add_conditional_edges("identify_drug", after_identify, {"finalize": "finalize", "check_contraindications": "check_contraindications"})
    g.add_edge("check_contraindications", "search_reason")
    g.add_edge("search_reason", "search_label")
    g.add_edge("search_label", "model")
    g.add_edge("model", "validator")
    g.add_conditional_edges("validator", after_validator, {"model": "model", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})


def build_for_condition(deps: GraphDeps, condition: str) -> Any:
    """평가 설정 식별자 → 컴파일된 그래프. `C1`·`C1+`는 고정 파이프라인, `C2`는 ReAct 그래프(`graph.build.build_graph`). 그 밖은 오류."""
    if condition == CONDITION_C1:
        return build_pipeline(deps)
    if condition == CONDITION_C1_PLUS:
        return build_pipeline(deps, PipelineConfig(typo_retry=True))
    if condition == CONDITION_C2:
        return build_graph(deps)
    raise ValueError(f"그래프를 만들 수 없는 조건: {condition!r} (C1·C1+·C2 중 하나)")


def harness_profile(condition: str) -> dict[str, Any]:
    """결과 파일에 적을 조건별 하네스 적용표(`harness@v1`). 개선 단계 장치(`known_ids`·단위 보조 차단·반복 경고)는 C3 ablation 행이 따로 적는다."""
    return {"version": HARNESS_VERSION, "condition": condition, "baseline": list(HARNESS_BASELINE), "selection_limits": []}


__all__ = ["CONDITION_C1", "CONDITION_C1_PLUS", "CONDITION_C2", "HARNESS_VERSION", "PIPELINE_VERSION", "PipelineConfig", "build_for_condition",
           "build_pipeline", "harness_profile", "initial_state", "run_question"]
