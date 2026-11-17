"""BE-06 앱 시작 배선(BE-06-22 A·BE-06-19 A): 설정 판정과 지연 생성 실행기.

- `missing_settings(settings)`: 서비스 실행기에 꼭 필요한 설정 중 비어 있는 것의 **환경변수 이름**을 돌려준다. 값은 비었는지만 본다.
- `make_service_runner(settings)`: 빠진 이름이 있으면 None(→ `/chat` 501 유지). 다 있으면 **아무것도 만들지 않고** 지연 실행기를 돌려준다.
  무거운 자원(사전·코퍼스·DB 연결 팩토리·DUR 클라이언트·모델 객체)은 **첫 요청 때**(라우트가 띄운 스레드 안) 한 번만 만든다.
  앱 시작 때는 어디에도 접속하지 않는다. 만들다 실패하면 저장하지 않고 예외를 올려(스트림은 `error` → `done`) 다음 요청에서 다시 시도한다.
- 요청마다 `ToolContext`를 새로 만들어 새 그래프를 쓴다(`request_deps`): `remaining_calls` 같은 요청 상태가 동시 요청 사이에 섞이지 않는다.
  무거운 자원과 모델 객체는 공유한다. 판정은 바뀌지 않는다.
- 새 환경변수를 만들지 않는다(BE-06-19 A). 로그에는 "붙임/안 붙임"과 빠진 변수 **이름**만 남기고 값·접속 문자열·키는 남기지 않는다.
- 서비스 경로는 trace를 켜지 않는다(RFP-22-06 A): `tracer=None`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from typing import Any

from app.agent.graph.build import build_graph
from app.agent.graph.nodes import GraphDeps
from app.agent.tools.context import ToolContext
from app.agent.tools.langchain_adapter import build_tools
from app.api.runner import ChatRunner, GraphRunner, NodeUpdate
from app.config import reveal

logger = logging.getLogger(__name__)

# 서비스 실행기에 꼭 필요한 환경변수 이름(정의 순서대로 보고한다). `Settings` 필드 이름은 소문자 꼴이다.
REQUIRED_ENV: tuple[str, ...] = (
    "OPENAI_API_KEY",                    # 에이전트 모델
    "SUPABASE_DB_URL",                   # 파일 판정 DB·근거 코퍼스
    "DURPrdlstInfoService03_END_POINT",  # 서비스 모드 API 병기(DUR 품목정보)
    "DURPrdlstInfoService03_API_KEY",
    "DURIrdntInfoService03_END_POINT",   # 서비스 모드 API 병기(DUR 성분정보)
    "DURIrdntInfoService03_API_KEY",
)
_DEFAULT_REMAINING_CALLS: int = ToolContext.__dataclass_fields__["remaining_calls"].default

ResourcesFactory = Callable[[Any], GraphDeps]


def missing_settings(settings: Any) -> list[str]:
    """필수 설정 중 값이 빈 것의 환경변수 이름 목록(정의 순서). 값 자체는 돌려주지도 남기지도 않는다."""
    out: list[str] = []
    for name in REQUIRED_ENV:
        value = reveal(getattr(settings, name.lower(), None))
        if value is None or not value.strip():
            out.append(name)
    return out


def default_resources(settings: Any) -> GraphDeps:
    """실제 자원으로 그래프 의존성 원본을 만든다(첫 요청 때 한 번). 시험에서는 부르지 않는다(가짜로 바꾼다).

    - 접속: 호출마다 새 읽기 전용 연결(`psycopg`, `paramstyle="format"`).
    - 사전: DB `drug_dict_meta`·`drug_dict_entry`에서 가장 늦게 적재한 판(`DrugDict.from_db`, BE-06-24 B). 파일
      `data/mock/dict/drug_dict.json`은 읽지 않는다(런타임 데이터는 DB 원칙, 파일은 개발·평가용).
    - 코퍼스: 원격 `corpus_chunks`를 한 번 읽어 메모리 인덱스로(`CorpusIndex.from_db`). 벡터 검색은 붙이지 않는다(BM25 단독).
    - 라벨 공급자는 없다(None: 식별·라벨 절 도구가 "원문 없음"으로 처리). 등급 정의는 코퍼스에서 읽는다.
    - 모델 객체는 `build_deps(service=True)`가 만든다(호출은 하지 않음). 개발 원장·개발 LLM 캐시를 타지 않는다(BE-06-23 A).
    """
    import psycopg  # noqa: PLC0415 - 실제 연결을 여는 이 함수 안에서만 import한다

    from app.agent.grade_defs import corpus_grade_def_fn  # noqa: PLC0415
    from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: PLC0415
    from app.agent.tools.corpus import CorpusIndex  # noqa: PLC0415
    from app.tools.drug_dict import DrugDict  # noqa: PLC0415
    from app.tools.dur import DurClient  # noqa: PLC0415

    dsn = reveal(settings.supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True  # 이 연결의 트랜잭션은 읽기 전용
        return conn

    drug_dict = DrugDict.from_db(conn_factory, paramstyle="format")
    corpus = CorpusIndex.from_db(conn_factory)
    ctx = build_tool_context(drug_dict, settings=settings, mode="service", dur_client=DurClient.from_settings(settings),
                             conn_factory=conn_factory, paramstyle="format", corpus=corpus, vector_search_fn=None, label_provider=None)
    return build_deps(drug_dict, ctx, settings=settings, tracer=None, ledger=None, grade_def_fn=corpus_grade_def_fn(corpus),
                      service=True)


def request_deps(base: GraphDeps) -> GraphDeps:
    """요청 하나가 쓸 의존성. `ToolContext`와 그에 묶인 도구 목록만 새로 만들고 나머지(사전·모델·프롬프트)는 원본을 공유한다."""
    ctx = replace(base.tool_ctx, remaining_calls=_DEFAULT_REMAINING_CALLS)
    return replace(base, tool_ctx=ctx, tools=build_tools(ctx, base.registry), tracer=None)


class LazyGraphRunner:
    """첫 요청 때 자원을 한 번 만들고, 요청마다 새 `ToolContext`·새 그래프로 돌리는 실행기."""

    def __init__(self, settings: Any, resources_factory: ResourcesFactory) -> None:
        self._settings = settings
        self._factory = resources_factory
        self._lock = threading.Lock()
        self._base: GraphDeps | None = None

    def _resources(self) -> GraphDeps:
        if self._base is None:
            with self._lock:
                if self._base is None:  # 만들다 예외가 나면 저장되지 않는다 → 다음 요청이 다시 시도한다
                    self._base = self._factory(self._settings)
        return self._base

    def updates(self, question: str, profile: dict[str, Any] | None,
                confirmed_item_seqs: Sequence[str] = ()) -> Iterator[NodeUpdate]:
        graph = build_graph(request_deps(self._resources()))
        yield from GraphRunner(lambda: graph).updates(question, profile, confirmed_item_seqs)


def make_service_runner(settings: Any, *, resources_factory: ResourcesFactory | None = None) -> ChatRunner | None:
    """설정이 갖춰졌으면 지연 실행기, 아니면 None. 이 함수는 자원을 만들지 않고 어디에도 접속하지 않는다."""
    missing = missing_settings(settings)
    if missing:
        logger.info("chat runner not attached (/chat stays 501); missing settings: %s", ", ".join(missing))
        return None
    logger.info("chat runner attached (resources are built on the first request)")
    return LazyGraphRunner(settings, resources_factory or default_resources)


__all__ = ["REQUIRED_ENV", "LazyGraphRunner", "default_resources", "make_service_runner", "missing_settings", "request_deps"]
