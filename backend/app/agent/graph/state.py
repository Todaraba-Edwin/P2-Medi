"""AG-01 그래프 상태(RFP-23 §4.4 + AG-05 `RouterResult` 제안 필드) 와 쓰기 제한(H8).

- 키 소유는 노드별 `NODE_WRITABLE`로 고정한다. 노드가 자기 몫 밖의 키를 반환하면 `restrict_update`가 버리고 키 이름만 이벤트로 남긴다.
- `emergency`·`route`는 reducer가 한 번 올라가면 내려가지 않게 막는다(도구 결과·모델 출력이 되돌릴 수 없다, H4·H8).
- 도구 결과가 쓸 수 있는 키는 `POST_WRITABLE_KEYS`(`evidence`·`known_ids`·`input_units`·`events`)뿐이다. `messages`는 모델 입력용 대화 기록이다.
- 상태에는 질문 원문이 들어 있다(`question`·`messages`). 로그에는 넣지 않는다(H13, 로깅은 BE-15·BE-06 몫).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from app.agent.guardrail import ROUTE_REFUSE
from app.agent.router import ROUTER_WRITABLE_KEYS
from app.agent.tools.schemas import POST_WRITABLE_KEYS

MAX_MODEL_CALLS = 8  # RFP-22-05 A: 모델 호출 상한. 하네스 차단 뒤 재호출·요약 호출·되감기 호출도 센다
MAX_REWIND = 1       # 검증 실패 되감기 상한(이번 기준선은 1회, 개선 단계 2회는 AG-13)

END_NORMAL, END_CLARIFY, END_REFUSE, END_LIMIT, END_FALLBACK = "NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"


def _or(a: bool | None, b: bool | None) -> bool:
    return bool(a) or bool(b)


def _sticky_route(a: str | None, b: str | None) -> str | None:
    """`REFUSE`가 한 번 정해지면 다른 값으로 덮이지 않는다."""
    return ROUTE_REFUSE if ROUTE_REFUSE in (a, b) else (b or a)


def _merge_evidence(a: list[dict[str, Any]] | None, b: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = list(a or [])
    seen = {it.get("evidence_id") for it in out if it.get("evidence_id")}
    for it in b or []:
        eid = it.get("evidence_id")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        out.append(it)
    return out


def _union(a: set[str] | None, b: set[str] | None) -> set[str]:
    return set(a or ()) | set(b or ())


def _merge_dict(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    return {**(a or {}), **(b or {})}


class AgentState(TypedDict, total=False):
    # 입력
    question: str
    # guardrail_in(AG-08)
    emergency: Annotated[bool, _or]
    route: Annotated[str, _sticky_route]
    refuse_reason: str | None
    injection: bool
    proceed_tools: bool
    # router(AG-05)
    profile: dict[str, Any]
    drug_mentions: list[str]
    intent: list[str]
    entities: list[dict[str, Any]]
    branch_label: str
    ambiguous: bool
    clarify: dict[str, Any] | None
    truncated: bool
    required_claims: list[str]  # AG-05: 필요한 주장 유형(코드 규칙 부분). 쓰는 쪽은 router뿐이다
    # model ⇄ tools
    messages: Annotated[list[Any], add_messages]
    call_count: int
    limit_reached: bool
    draft: Any
    # tools 결과(POST_WRITABLE_KEYS)
    evidence: Annotated[list[dict[str, Any]], _merge_evidence]
    known_ids: Annotated[set[str], _union]
    input_units: Annotated[dict[str, Any], _merge_dict]
    events: Annotated[list[dict[str, Any]], operator.add]
    # validator·finalize
    validation: dict[str, Any]
    rewind_count: int
    final_sentences: list[dict[str, Any]]
    end_reason: str
    answer: dict[str, Any]


# 노드가 쓸 수 있는 키(이 밖의 키는 `restrict_update`가 버린다)
NODE_WRITABLE: dict[str, frozenset[str]] = {
    "guardrail_in": frozenset({"emergency", "route", "refuse_reason", "injection", "proceed_tools", "events"}),
    "router": frozenset(ROUTER_WRITABLE_KEYS | {"events"}),
    "model": frozenset({"messages", "call_count", "limit_reached", "draft", "events"}),
    "tools": frozenset(POST_WRITABLE_KEYS | {"messages"}),
    "validator": frozenset({"validation", "rewind_count", "final_sentences", "draft", "messages", "events"}),
    "finalize": frozenset({"answer", "end_reason", "events"}),
}


def restrict_update(node: str, update: dict[str, Any]) -> dict[str, Any]:
    """노드 반환값에서 `NODE_WRITABLE[node]` 밖의 키를 버린다. 버린 키 이름은 `events`에 내용 없이 남긴다(H8)."""
    allowed = NODE_WRITABLE[node]
    kept = {k: v for k, v in (update or {}).items() if k in allowed}
    dropped = sorted(set(update or {}) - allowed)
    if dropped:
        kept["events"] = [*kept.get("events", []), {"rule": "H8", "event": "STATE_KEY_BLOCKED", "node": node, "keys": dropped}]
    return kept
