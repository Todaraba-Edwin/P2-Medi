"""BE-06 `/chat` 그래프 실행기와 요청 묶음 → 그래프 입력 변환.

- 실행기(`ChatRunner`)는 `updates(question, profile)`로 **노드 갱신**(`{노드 이름: 갱신 dict}`)을 차례로 낸다. 라우트는 이 갱신만 읽어
  이벤트로 바꾼다(`app.api.stream`). 실행기가 주입되지 않으면 라우트는 501이다(`app.api.chat`).
- `GraphRunner`는 AG-01 그래프(`build_graph`)를 `stream_mode="updates"`로 돌린다. **서비스 경로는 trace를 켜지 않는다**(RFP-22-06 A):
  `from_deps`는 받은 의존성의 `tracer`를 떼고 그래프를 만든다.
- 이 모듈은 모델·DB·API 객체를 만들지 않는다. 의존성(`GraphDeps`)은 호출자가 만들어 준다(앱 시작 때 실제 의존성을 붙이는 일은 이 모듈 밖).
- 질문·프로필은 저장·로그하지 않는다(PRD-07-01 A).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from typing import Any, Protocol

from app.agent.graph.build import build_graph, initial_state
from app.agent.graph.nodes import GraphDeps
from app.api.request import _YEARS_PER_UNIT, ConversationContext

NodeUpdate = dict[str, Any]  # {노드 이름: 그 노드가 쓴 상태 갱신}


class ChatRunner(Protocol):
    """질문 하나를 끝까지 돌리며 노드 갱신을 차례로 내는 실행기(동기, 라우트가 스레드에서 돌린다)."""

    def updates(self, question: str, profile: dict[str, Any] | None) -> Iterable[NodeUpdate]: ...


class GraphRunner:
    """AG-01 그래프 실행기. `graph_factory`는 요청마다 불려 그래프(컴파일된 `StateGraph`)를 돌려준다."""

    def __init__(self, graph_factory: Callable[[], Any]) -> None:
        self._graph_factory = graph_factory

    @classmethod
    def from_deps(cls, deps: GraphDeps) -> GraphRunner:
        """의존성 하나로 그래프를 한 번 만들어 재사용한다. 계측기(`tracer`)는 떼어 낸다(서비스 모드 trace 끔)."""
        graph = build_graph(replace(deps, tracer=None))
        return cls(lambda: graph)

    def updates(self, question: str, profile: dict[str, Any] | None) -> Iterator[NodeUpdate]:
        for chunk in self._graph_factory().stream(initial_state(question, profile), stream_mode="updates"):
            if isinstance(chunk, dict):
                yield chunk


def profile_from_context(context: ConversationContext) -> dict[str, Any] | None:
    """요청 묶음 → 그래프 `profile`(`router.ProfileState` 모양). 값이 하나도 없으면 None.

    - 나이는 **한 나이**(`lower == upper`)일 때만 세 단위로 환산해 넘긴다. 구간이면 넘기지 않는다(FE-07-18 A: 특정할 수 없으면 판정하지 않음).
    - 질문 문장에 나이·임신 여부가 있으면 그 값이 우선한다(`router.extract_profile`).
    - `confirmed_drugs`는 쓰지 않는다(AG-05 동작 변경이라 결정 뒤).
    """
    age = context.age
    age_years = round(age.lower * _YEARS_PER_UNIT[age.unit], 2) if age is not None and age.lower == age.upper else None
    if age_years is None and context.pregnant is None:
        return None
    return {"age_years": age_years, "pregnant": context.pregnant}


__all__ = ["ChatRunner", "GraphRunner", "NodeUpdate", "profile_from_context"]
