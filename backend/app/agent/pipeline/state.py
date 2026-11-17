"""AG-16 C1 고정 파이프라인의 상태·쓰기 표·단계 이름.

- 상태는 ReAct 그래프의 `AgentState`를 그대로 쓰고(같은 키·같은 reducer), 고정 순서의 현재 단계를 적는 `step` 하나만 더한다.
- 노드가 쓸 수 있는 키(`PIPELINE_WRITABLE`)는 ReAct `NODE_WRITABLE`과 같은 규칙(H8)이다. 공유 노드(`guardrail_in`·`router`·`validator`·`finalize`)는
  같은 집합을 그대로 쓰고, 도구 단계 노드는 `tools` 노드 몫(`POST_WRITABLE_KEYS` + `messages`)에 `step`만 더한다. `emergency`·`route`·`profile`은 어느 단계도 못 쓴다.
"""

from __future__ import annotations

from app.agent.graph.state import NODE_WRITABLE, AgentState
from app.agent.tools.schemas import POST_WRITABLE_KEYS

# 고정 순서(RFP-23 §5.2 C1): guardrail_in → router → identify_drug → check_contraindications → search_reason → search_label → model(요약) → validator → finalize
STEP_IDENTIFY, STEP_CONTRA, STEP_REASON, STEP_LABEL, STEP_SUMMARY = "identify", "contra", "reason", "label", "summary"
TOOL_STEPS: tuple[tuple[str, str], ...] = (  # (노드 이름 = 도구 이름, 단계 키)
    ("identify_drug", STEP_IDENTIFY),
    ("check_contraindications", STEP_CONTRA),
    ("search_reason", STEP_REASON),
    ("search_label", STEP_LABEL),
)

# 파이프라인 이벤트 이름(상태 `events`, 내용 없음). 하네스 동작(`trace.HARNESS_ACTIONS`)이 아니라 고정 규칙의 발동 기록이다
EVENT_STEP = "PIPELINE_STEP"                  # 단계 하나 실행(도구 호출 수·건너뜀 사유)
EVENT_UNIDENTIFIED = "PIPELINE_UNIDENTIFIED"  # 예외 규칙 1: 식별 0건 → 요약 호출 없이 미식별 안내로 종료
EVENT_SUMMARY = "PIPELINE_SUMMARY"            # 고정 순서의 유일한 LLM 호출(요약)
RULE_C1 = "C1"


class PipelineState(AgentState, total=False):
    step: str  # 마지막으로 끝난 단계 키(`STEP_*`). 간선 함수가 다음 노드를 고를 때 읽는다


_TOOL_NODE_KEYS = frozenset(POST_WRITABLE_KEYS | {"messages", "step"})
PIPELINE_WRITABLE: dict[str, frozenset[str]] = {
    "guardrail_in": NODE_WRITABLE["guardrail_in"],
    "router": NODE_WRITABLE["router"],
    **{name: _TOOL_NODE_KEYS for name, _ in TOOL_STEPS},
    "model": frozenset({"messages", "call_count", "draft", "events"}),  # 요약 호출만(도구 선택 없음, `limit_reached` 없음)
    "validator": NODE_WRITABLE["validator"],
    "finalize": NODE_WRITABLE["finalize"],
}

__all__ = ["EVENT_STEP", "EVENT_SUMMARY", "EVENT_UNIDENTIFIED", "PIPELINE_WRITABLE", "RULE_C1", "STEP_CONTRA", "STEP_IDENTIFY", "STEP_LABEL",
           "STEP_REASON", "STEP_SUMMARY", "TOOL_STEPS", "PipelineState"]
