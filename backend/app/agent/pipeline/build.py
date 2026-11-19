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
평가 설정 식별자(C1·C1+·C2)로 그래프를 고르는 `build_for_condition`을 둔다(BE-08·eval_runner 연결용).

C1+(강화, AG-16-06 A 2026-11-17): C1과 **같은 그래프·같은 규칙**에 오탈자 보정 후 재검색 1회만 더한다(RFP-23 §5.2). 보정은 새 코드가 아니라
`router` 노드가 쓰는 AG-10 보정(`router.correct_typo`: 자모 유사도 0.90 이상·2위와 0.05 이상 차이·숫자 불변·보정 이름으로 사전 1회 재조회)을
그대로 켠 것이다. 뚜렷하지 않으면 C1과 똑같이 되묻기(예외 규칙 2)로 끝난다. 보정한 답에는 공유 `finalize`가 보정 고지를 붙인다.
C1은 주입된 의존성의 보정 스위치가 켜져 있어도 **항상 끈다**(조건의 뜻이 섞이지 않게 여기서 강제한다).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.graph.build import build_graph, initial_state, run_question
from app.agent.graph.nodes import GraphDeps, after_guardrail, after_router, after_validator, guard_node
from app.agent.pipeline.nodes import after_identify, make_pipeline_nodes
from app.agent.pipeline.state import PIPELINE_WRITABLE, PipelineState

PIPELINE_VERSION = "c1-pipeline@v1"  # 결과 파일 `graph_version`용. 규칙을 바꾸면 올리고 이전 결과와 섞지 않는다(RFP 9.6절, BE-08 RFP-34-04)
PIPELINE_PLUS_VERSION = "c1plus-pipeline@v1"  # C1+ 규칙 버전(C1 규칙 + 오탈자 보정 후 재검색 1회). 보정 기준을 바꾸면 올린다
RECURSION_LIMIT = 30  # 노드 9개 + 되감기 1회를 넉넉히 덮는다
CONDITION_C1, CONDITION_C1_PLUS, CONDITION_C2 = "C1", "C1+", "C2"
# C3 = C2(같은 ReAct 그래프·도구·프롬프트) + AG-13 개선 장치. 한 번에 하나씩 더한다(ablation, 9.5절). 지금 장치는 AG-07 Validator 계층·주장 유형
# 누락 검사(⑭~⑯, AG-13-08 A) 하나다. 장치를 더하거나 바꾸면 `C3_VERSION`을 올리고 이전 C3 결과와 섞지 않는다
CONDITION_C3 = "C3"
# v1(2026-11-18): ⑭~⑯ 검사. v2(2026-11-19, AG-13-17 B): ⑯ 되감기 메시지에 빠진 주장 유형·FOUND 판정(금기 종류·성분명·근거 ID) 인용 지시를 더함
# v3(2026-11-19, AG-13-23 A): 마지막 되감기 메시지(⑥·⑧·⑯ 등 모든 사유)를 요약 호출 지시 뒤에도 붙임(C3만, C1·C1+·C2 요약 입력 불변)
# v4(2026-11-20, AG-13-29 A·32 A): ⑯은 되감기 대신 기록만(AG-13-09 → B, `validation.recorded`·span `recorded`), ⑥ 되감기 메시지에 약사 권고가 빠진
# 미확보 근거 ID를 코드로 붙임(v3 요약 호출 전달 경로 그대로). 장치 이름은 그대로(AG-13-25 A), C1·C1+·C2 입력·출력 불변
C3_VERSION = "c3-layer-check@v4"
C3_IMPROVEMENTS = ("AG07_LAYER_CHECK",)
HARNESS_VERSION = "harness@v1"
# 조건별 하네스 적용표(RFP-33-03 A, PJ2-Agent-Harness.md 7.2절). 기준선 장치는 공통, 개선 단계 선택 제한 장치는 C3에서만 ablation으로 더한다
HARNESS_BASELINE = ("ARG_SCHEMA", "TOOL_OUTPUT_CONTRACT", "STATE_KEY_LIMIT", "FINALIZE_PHRASES")


@dataclass(frozen=True)
class PipelineConfig:
    """C1(기본)·C1+(강화) 전환. `typo_retry=True`가 C1+(오탈자 보정 후 재검색 1회, Router의 AG-10 보정 재사용)다."""

    typo_retry: bool = False

    @property
    def condition(self) -> str:
        return CONDITION_C1_PLUS if self.typo_retry else CONDITION_C1


def build_pipeline(deps: GraphDeps, config: PipelineConfig | None = None) -> Any:
    cfg = config or PipelineConfig()
    # 보정 스위치는 조건이 정한다: C1은 끔, C1+는 켬. 계층 검사(C3 장치)는 항상 끈다. 주입된 `deps`는 바꾸지 않는다(사본)
    deps = replace(deps, typo_correct=cfg.typo_retry, layer_check=False)
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
    """평가 설정 식별자 → 컴파일된 그래프. `C1`·`C1+`는 고정 파이프라인, `C2`는 ReAct 그래프(`graph.build.build_graph`),
    `C3`는 같은 ReAct 그래프에 개선 장치(`C3_IMPROVEMENTS`)를 켠 것이다. 장치 스위치는 조건이 정한다(C3만 켬, C1·C1+·C2는 주입값과 무관하게 끔).
    주입된 `deps`는 바꾸지 않는다(사본). 그 밖은 오류."""
    if condition == CONDITION_C1:
        return build_pipeline(deps)
    if condition == CONDITION_C1_PLUS:
        return build_pipeline(deps, PipelineConfig(typo_retry=True))
    if condition == CONDITION_C2:
        return build_graph(replace(deps, layer_check=False))
    if condition == CONDITION_C3:
        return build_graph(replace(deps, layer_check=True))
    raise ValueError(f"그래프를 만들 수 없는 조건: {condition!r} (C1·C1+·C2·C3 중 하나)")


def pipeline_version(condition: str) -> str | None:
    """조건의 파이프라인 규칙 버전. 고정 파이프라인이 아니면(C2) None."""
    return {CONDITION_C1: PIPELINE_VERSION, CONDITION_C1_PLUS: PIPELINE_PLUS_VERSION}.get(condition)


def harness_profile(condition: str) -> dict[str, Any]:
    """결과 파일에 적을 조건별 하네스 적용표(`harness@v1`). 기준선 장치는 C1·C1+·C2 공통이다(RFP-33-03 A).
    개선 단계 장치(`known_ids`·단위 보조 차단·반복 경고)는 C3 ablation 행이 따로 적는다. 모르는 조건은 오류다(표에 없는 조건을 조용히 적지 않는다).
    C3 행은 기준선 장치가 같고, 선택 제한 장치는 아직 더하지 않았다(빈 목록). 지금 C3 장치(Validator 계층 검사)는 `improvements`에 따로 적는다."""
    if condition not in (CONDITION_C1, CONDITION_C1_PLUS, CONDITION_C2, CONDITION_C3):
        raise ValueError(f"하네스 적용표에 없는 조건: {condition!r} (C1·C1+·C2·C3 중 하나)")
    row: dict[str, Any] = {"version": HARNESS_VERSION, "condition": condition, "baseline": list(HARNESS_BASELINE), "selection_limits": []}
    if condition == CONDITION_C3:
        row["improvements"] = list(C3_IMPROVEMENTS)
        row["c3_version"] = C3_VERSION
    return row


__all__ = ["C3_IMPROVEMENTS", "C3_VERSION", "CONDITION_C1", "CONDITION_C1_PLUS", "CONDITION_C2", "CONDITION_C3", "HARNESS_VERSION",
           "PIPELINE_PLUS_VERSION", "PIPELINE_VERSION", "PipelineConfig", "build_for_condition", "build_pipeline", "harness_profile", "initial_state",
           "pipeline_version", "run_question"]
