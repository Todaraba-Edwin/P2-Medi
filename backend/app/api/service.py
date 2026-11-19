"""BE-06 앱 시작 배선(BE-06-22 A·BE-06-19 A): 설정 판정과 지연 생성 실행기.

- `missing_settings(settings)`: 서비스 실행기에 꼭 필요한 설정 중 비어 있는 것의 **환경변수 이름**을 돌려준다. 값은 비었는지만 본다.
- `make_service_runner(settings)`: 빠진 이름이 있으면 None(→ `/chat` 501 유지). 다 있으면 **아무것도 만들지 않고** 지연 실행기를 돌려준다.
  무거운 자원(사전·코퍼스·DB 연결 팩토리·DUR 클라이언트·모델 객체)은 한 번만 만든다.
- `start_warmup(runner, settings)`(BE-17-01·02 A, 2026-11-19): lifespan이 부르면 **백그라운드 스레드**가 자원 전체를 한 번 만든다.
  lifespan은 기다리지 않고 바로 끝난다(`/health` 즉시 응답). 그동안 온 요청은 같은 잠금에서 기다렸다가 같은 자원을 쓴다.
  스위치 `MEDIAGENT_WARMUP`(기본 켬)을 끄면 BE-06-27 A처럼 첫 요청 때(라우트가 띄운 스레드 안) 만든다.
  만들다 실패하면 저장하지 않는다: 준비 스레드는 종류 이름만 로그에 남기고, 요청 중 실패는 예외를 올려(스트림은 `error` → `done`)
  다음 요청에서 다시 시도한다.
- 요청마다 `ToolContext`를 새로 만들어 새 그래프를 쓴다(`request_deps`): `remaining_calls` 같은 요청 상태가 동시 요청 사이에 섞이지 않는다.
  무거운 자원과 모델 객체는 공유한다. 판정은 바뀌지 않는다.
- 필수 설정에 새 환경변수를 더하지 않는다(BE-06-19 A). 선택 스위치 `MEDIAGENT_WARMUP` 하나만 BE-17-01 A로 더했다. 로그에는 "붙임/안 붙임"과 빠진 변수 **이름**만 남기고 값·접속 문자열·키는 남기지 않는다.
- 서비스 경로는 trace를 켜지 않는다(RFP-22-06 A): `tracer=None`.
- L4 요청 단위 사용량(BE-06-36 A): 스트림이 그래프 스레드에 `REQUEST_USAGE`를 넣으면 `request_deps`가 두 모델을 `UsageMeter`로 감싸
  호출 수·토큰·추정 비용(숫자만)을 그 요청의 `RequestUsage`에 더한다. 메시지·모델 출력은 보지 않는다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any

from app.agent.graph.build import build_graph
from app.agent.graph.metered import usage_of
from app.agent.graph.nodes import GraphDeps
from app.agent.tools.context import ToolContext
from app.agent.tools.langchain_adapter import build_tools
from app.api.runner import ChatRunner, ConfirmedInput, GraphRunner, NodeUpdate
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

    def connect() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True  # 이 연결의 트랜잭션은 읽기 전용
        return conn

    label = BUILD_LABEL.get()
    with build_step(label, "db connection"):
        conn_factory = PrimedConnFactory(connect, connect())  # 첫 연결을 여기서 열어 사전 읽기에 넘긴다(추가 연결 0)
    with build_step(label, "drug dictionary") as step:
        drug_dict = DrugDict.from_db(conn_factory, paramstyle="format")
        step.detail = f"{len(drug_dict.products)} products, {len(drug_dict.ingredients)} ingredients"
    # 코퍼스: 로더(`CorpusIndex.from_db`, 평가 공용)를 그대로 부르고 밖에서 감싼다. 읽기와 BM25 색인 구성이 한 단계 안에 있다.
    with build_step(label, "corpus (fetch + bm25 index)") as step:
        corpus = CorpusIndex.from_db(conn_factory)
        step.detail = f"{len(corpus)} chunks"
    with build_step(label, "agent wiring"):
        ctx = build_tool_context(drug_dict, settings=settings, mode="service", dur_client=DurClient.from_settings(settings),
                                 conn_factory=conn_factory, paramstyle="format", corpus=corpus, vector_search_fn=None, label_provider=None)
        return build_deps(drug_dict, ctx, settings=settings, tracer=None, ledger=None, grade_def_fn=corpus_grade_def_fn(corpus),
                          service=True)


# --------------------------------------------------------------------------- 자원 준비 단계 로그(BE-17 후속, 2026-11-19)
# 준비 스레드는 접두 `warmup`, 스위치를 끄고 첫 요청에서 만들 때는 `resources`. 줄에는 단계 이름·소요 초·개수만 남긴다
# (값·연결 문자열·키·질문은 남기지 않는다. 실패는 예외 **종류 이름**만).
BUILD_LABEL: ContextVar[str] = ContextVar("mediagent_build_label", default="resources")


class _Step:
    detail: str | None = None


@contextmanager
def build_step(label: str, name: str) -> Iterator[_Step]:
    """`{label}: {name} starting` → `... done in N.NNs (detail)` 또는 `... failed: Type after N.NNs`(예외는 그대로 올린다)."""
    step = _Step()
    started = time.monotonic()
    logger.info("%s: %s starting", label, name)
    try:
        yield step
    except BaseException as exc:
        logger.warning("%s: %s failed: %s after %.2fs", label, name, type(exc).__name__, time.monotonic() - started)
        raise
    suffix = f" ({step.detail})" if step.detail else ""
    logger.info("%s: %s done in %.2fs%s", label, name, time.monotonic() - started, suffix)


class PrimedConnFactory:
    """첫 호출에는 미리 연 연결을 돌려주고, 그다음부터는 호출마다 새 연결을 연다(받은 쪽이 닫는다).

    준비 단계에서 접속 시간을 따로 재되 연결을 하나 더 열지 않으려는 것이다. 동시 호출에도 미리 연 연결은 한 번만 건넨다."""

    def __init__(self, connect: Callable[[], Any], first: Any) -> None:
        self._connect = connect
        self._first = first
        self._lock = threading.Lock()

    def __call__(self) -> Any:
        with self._lock:
            conn, self._first = self._first, None
        return conn if conn is not None else self._connect()


# --------------------------------------------------------------------------- L4 요청 단위 사용량(BE-06-36 A)
# 서비스 모델 객체는 요청 사이에 공유되므로(`metered._CachedBase.usage`는 프로세스 누적) 요청 하나의 합계를 따로 센다.
# 요청 귀속: 스트림이 그래프 스레드 안에서 `REQUEST_USAGE`에 그 요청의 합계 객체를 넣고, `request_deps`가 그 객체에 묶인
# 얇은 계량 래퍼(`UsageMeter`)를 요청 전용 의존성에 끼운다. 동시 요청은 각자 다른 래퍼·합계 객체를 쓰므로 섞이지 않는다.
# 세는 것은 **숫자만**(호출 수·입력/출력/캐시 토큰·추정 비용)이다. 메시지·도구 인자·모델 출력은 보지도 남기지도 않는다.


@dataclass
class RequestUsage:
    """요청 하나의 모델 사용량 합계(내용 없음). 그래프 안의 병렬 노드가 함께 쓸 수 있어 잠근다."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, tokens_in: int, tokens_out: int, tokens_cached: int, cost_usd: float) -> None:
        with self._lock:
            self.calls += 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            self.tokens_cached += tokens_cached
            self.cost_usd += cost_usd

    def fields(self) -> dict[str, float]:
        """L4 집계 칸(`SERVICE_FIELDS`의 `tokens_in`·`tokens_out`·`cost_usd`). 모델 호출이 없었으면 빈 사전(칸을 0으로 지어내지 않는다)."""
        with self._lock:
            if not self.calls:
                return {}
            return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost_usd": round(self.cost_usd, 8)}


REQUEST_USAGE: ContextVar[RequestUsage | None] = ContextVar("mediagent_request_usage", default=None)

CostFn = Callable[[int, int, int], float]


def _default_cost(tokens_in: int, tokens_out: int, tokens_cached: int) -> float:
    from app.agent.llm import estimate_cost_usd  # noqa: PLC0415 - 단가 원본은 llm.py 한 곳(지연 import)

    return estimate_cost_usd(tokens_in, tokens_out, tokens_cached)


def _usage_message(result: Any) -> Any:
    """모델 결과에서 토큰이 붙은 메시지. 도구 모델은 `AIMessage`, 요약 모델은 `{"raw": AIMessage, ...}`(가짜는 초안 dict뿐 → None)."""
    if isinstance(result, dict):
        return result.get("raw")
    return result


class UsageMeter:
    """모델 객체를 감싸 `.invoke` 결과의 토큰 수만 요청 합계에 더하는 사용량 콜백. 결과는 손대지 않고 그대로 돌려준다.

    기록 실패가 응답을 망치지 않게 집계 중 예외는 삼키고 종류 이름만 로그에 남긴다(모델 호출 자체의 예외는 그대로 올린다)."""

    def __init__(self, inner: Any, usage: RequestUsage, cost_fn: CostFn | None = None) -> None:
        self.inner = inner
        self._usage = usage
        self._cost_fn = cost_fn or _default_cost

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        result = self.inner.invoke(*args, **kwargs)
        try:
            tin, tout, tcached = usage_of(_usage_message(result))
            self._usage.add(tin, tout, tcached, self._cost_fn(tin, tout, tcached) if (tin or tout) else 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.error("usage meter failed: %s", type(exc).__name__)
        return result

    def __getattr__(self, name: str) -> Any:  # 그 밖의 속성(`usage`·`status_counts` 등)은 원본 그대로
        return getattr(self.inner, name)


def request_deps(base: GraphDeps, usage: RequestUsage | None = None, *, cost_fn: CostFn | None = None) -> GraphDeps:
    """요청 하나가 쓸 의존성. `ToolContext`와 그에 묶인 도구 목록만 새로 만들고 나머지(사전·모델·프롬프트)는 원본을 공유한다.

    `usage`(없으면 지금 맥락의 `REQUEST_USAGE`)가 있으면 두 모델을 그 합계에 묶인 `UsageMeter`로 감싼다(BE-06-36 A)."""
    ctx = replace(base.tool_ctx, remaining_calls=_DEFAULT_REMAINING_CALLS)
    deps = replace(base, tool_ctx=ctx, tools=build_tools(ctx, base.registry), tracer=None)
    usage = usage if usage is not None else REQUEST_USAGE.get()
    if usage is None:
        return deps
    return replace(deps, tool_model=UsageMeter(base.tool_model, usage, cost_fn), summary_model=UsageMeter(base.summary_model, usage, cost_fn))


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
                    self._base = self._build()
        return self._base

    def _build(self) -> GraphDeps:
        """자원을 만들며 전체 시작·완료 줄을 남긴다(접두는 `BUILD_LABEL`: 준비 스레드 `warmup`, 첫 요청 `resources`)."""
        label = BUILD_LABEL.get()
        started = time.monotonic()
        logger.info("%s starting", label)
        try:
            base = self._factory(self._settings)
        except Exception as exc:
            logger.warning("%s failed: %s after %.1fs", label, type(exc).__name__, time.monotonic() - started)
            raise
        logger.info("%s done in %.1fs", label, time.monotonic() - started)
        return base

    @property
    def ready(self) -> bool:
        """자원이 이미 만들어졌는지(내용 없음)."""
        return self._base is not None

    def warm(self) -> bool:
        """자원을 미리 한 번 만든다(BE-17-01·02 A: 자원 전체). 성공하면 True.

        `_resources()`와 같은 잠금을 쓰므로 그동안 들어온 요청은 잠금에서 기다렸다가 같은 자원을 쓴다(생성 1회).
        실패하면 저장하지 않고(→ 다음 요청이 다시 시도) 예외를 삼킨다. 로그에는 예외 **종류 이름**과 소요 초만 남긴다
        (`warmup starting` … `warmup done in N.Ns` / `warmup failed: Type after N.Ns`, `_build`가 남긴다). 이미 만들었으면 줄 없이 True."""
        token = BUILD_LABEL.set("warmup")
        try:
            self._resources()
        except Exception:  # noqa: BLE001 — 백그라운드 스레드: `_build`가 종류 이름을 남겼다. 다음 요청의 재시도에 맡긴다
            return False
        finally:
            BUILD_LABEL.reset(token)
        return True

    def start_warmup(self) -> threading.Thread:
        """`warm()`을 데몬 스레드로 띄우고 바로 돌아온다(lifespan을 막지 않는다)."""
        thread = threading.Thread(target=self.warm, daemon=True, name="chat-warmup")
        thread.start()
        return thread

    def updates(self, question: str, profile: dict[str, Any] | None,
                confirmed_item_seqs: Sequence[ConfirmedInput] = ()) -> Iterator[NodeUpdate]:
        graph = build_graph(request_deps(self._resources()))
        yield from GraphRunner(lambda: graph).updates(question, profile, confirmed_item_seqs)


def start_warmup(runner: ChatRunner | None, settings: Any) -> threading.Thread | None:
    """서버 시작 백그라운드 준비(BE-17-01 A). 실행기가 없거나(설정 없음 → 501) 스위치(`MEDIAGENT_WARMUP`)가 꺼졌으면 띄우지 않는다.

    스레드만 띄우고 기다리지 않는다. 자원 생성(접속)은 그 스레드 안에서 일어난다."""
    if not isinstance(runner, LazyGraphRunner):
        return None
    if not getattr(settings, "mediagent_warmup", True):
        logger.info("chat resources warmup disabled (MEDIAGENT_WARMUP); resources are built on the first request")
        return None
    return runner.start_warmup()


def make_service_runner(settings: Any, *, resources_factory: ResourcesFactory | None = None) -> ChatRunner | None:
    """설정이 갖춰졌으면 지연 실행기, 아니면 None. 이 함수는 자원을 만들지 않고 어디에도 접속하지 않는다."""
    missing = missing_settings(settings)
    if missing:
        logger.info("chat runner not attached (/chat stays 501); missing settings: %s", ", ".join(missing))
        return None
    logger.info("chat runner attached (resources are built once, by the startup warmup or the first request)")
    return LazyGraphRunner(settings, resources_factory or default_resources)


__all__ = ["BUILD_LABEL", "REQUEST_USAGE", "REQUIRED_ENV", "LazyGraphRunner", "PrimedConnFactory", "RequestUsage", "UsageMeter",
           "build_step", "default_resources", "make_service_runner", "missing_settings", "request_deps", "start_warmup"]
