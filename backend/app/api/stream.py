"""BE-06 `/chat` 스트림 생성기: 실행기의 노드 갱신 → `chat_event@v1` 이벤트.

- 실행기(동기)는 **스레드**에서 돌린다(이벤트 루프를 막지 않는다). 갱신은 큐로 넘어오고 여기서 이벤트로 바꾼다.
- 대응 규칙(순서 규칙은 `EventSequence`가 그때그때 검사한다):
  - `guardrail_in` 갱신의 `emergency`가 참 → `emergency`(`seq` 0, LLM 호출 전)
  - `model` 갱신의 도구 호출 이름 → `progress` 단계(`TOOL_STAGE`). 같은 단계가 연달아 오면 한 번만
  - `finalize` 갱신의 `answer` → `answer`(`response_from_state`와 같은 변환) → `done`
- 오류(실행·응답 변환·순서 규칙 위반·`answer` 없이 끝남)는 `error`(`INTERNAL_ERROR`) → `done`으로 끝낸다. 스트림과 로그에는 예외 문자열·질문을
  싣지 않는다(로그는 예외 **종류 이름**만, PRD-07-01 A). `TIMEOUT`·`UPSTREAM_UNAVAILABLE`은 내는 규칙이 문서에 없어 아직 내지 않는다.
- 연결이 끊기면 생성기가 닫히며 `stop`을 세운다. 스레드는 다음 노드 경계에서 멈춘다(진행 중인 노드 하나는 끝까지 돈다).
- 서비스 집계 지표 L4(RFP-34-01·03 A, H13): 요청이 끝나면 **내용 없는 값만** `metrics.log(...)`에 넘긴다 — 요청 한 건(`node="chat"`,
  지연, 종료 사유 또는 오류 유형)과 하네스 **차단** 이벤트의 규칙 ID. 질문·약 이름·프로필·모델 출력은 넘기지 않는다. 분 단위 합산과 표준 출력은
  L1 `SpanLogger(mode="service")`·`Aggregator`가 한다(앱은 파일로 저장하지 않는다). 토큰·비용(BE-06-36 A)은 요청 단위 합계(`RequestUsage`)를
  그래프 스레드 맥락(`REQUEST_USAGE`)에 넣어 서비스 실행기(`service.LazyGraphRunner`)의 요청 전용 모델 래퍼(`UsageMeter`)가 숫자만 더하고,
  끝에 `tokens_in`·`tokens_out`·`cost_usd` 칸으로 넘긴다. 그 래퍼를 쓰지 않는 실행기(시험용 `GraphRunner` 등)는 칸이 없다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from app.agent.graph.trace import harness_events
from app.api.events import AnswerEvent, AnyEvent, ErrorEvent, EventSequence
from app.api.runner import ChatRunner, ConfirmedInput
from app.api.schemas import response_from_state
from app.api.service import REQUEST_USAGE, RequestUsage

logger = logging.getLogger(__name__)

# 도구 이름 → 진행 단계(`fixed_phrases.PROGRESS_LABELS`의 키). 표에 없는 이름(등록되지 않은 도구)은 진행 이벤트를 내지 않는다
TOOL_STAGE: dict[str, str] = {
    "identify_drug": "drug_lookup",
    "check_contraindications": "contraindication_check",
    "search_reason": "evidence_search",
    "search_notice": "evidence_search",
    "search_label": "evidence_search",
    "get_label_section": "evidence_search",
}
_DONE = object()
METRICS_NODE = "chat"  # 집계에서 요청 수를 세는 이름(`counts["node=chat"]`)
ERROR_CLIENT_GONE = "ClientDisconnected"  # 응답을 다 보내기 전에 연결이 끊긴 요청의 오류 유형


class MetricsSink(Protocol):
    """집계 기록기(`SpanLogger(mode="service")`와 같은 `.log(**fields)`)."""

    def log(self, **fields: Any) -> Any: ...


def _record_metrics(metrics: MetricsSink | None, *, latency_ms: float, end_reason: str | None, error_type: str | None,
                    block_rules: list[str], usage: RequestUsage | None = None) -> None:
    """요청 한 건의 내용 없는 값을 집계기에 넘긴다. 기록 실패가 응답을 망치지 않게 예외는 종류 이름만 로그에 남긴다.

    `usage`(요청 단위 모델 사용량, BE-06-36 A)는 숫자 칸 `tokens_in`·`tokens_out`·`cost_usd`로만 더한다(모델 호출이 없었으면 칸 없음)."""
    if metrics is None:
        return
    try:
        fields: dict[str, Any] = {"node": METRICS_NODE, "latency_ms": round(latency_ms, 1)}
        if end_reason:
            fields["end_reason"] = end_reason
        if error_type:
            fields["error_type"] = error_type
        if usage is not None:
            fields.update(usage.fields())
        metrics.log(**fields)
        for rule in block_rules:
            metrics.log(harness_event={"rule": rule})  # 규칙 ID만(L1이 `harness_rule`로 센다)
    except Exception as exc:  # noqa: BLE001
        logger.error("chat metrics failed: %s", type(exc).__name__)


def _run_in_thread(runner: ChatRunner, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Sequence[ConfirmedInput],
                   loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[Any], stop: threading.Event,
                   usage: RequestUsage | None = None) -> None:
    if usage is not None:
        REQUEST_USAGE.set(usage)  # 이 스레드(= 이 요청)의 맥락에만. 실행기가 요청 전용 모델 래퍼를 이 합계에 묶는다

    def put(item: Any) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # 루프가 이미 닫혔다(연결 끊김 뒤): 버린다
            stop.set()

    try:
        for chunk in runner.updates(question, profile, confirmed_item_seqs):
            if stop.is_set():
                return
            put(chunk)
        put(_DONE)
    except BaseException as exc:  # noqa: BLE001 — 내용은 넘기지 않고 예외 객체만(받는 쪽이 종류 이름만 쓴다)
        put(exc)


def _tool_stages(update: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for msg in update.get("messages") or []:
        for tc in getattr(msg, "tool_calls", None) or []:
            stage = TOOL_STAGE.get(tc.get("name", "") if isinstance(tc, dict) else "")
            if stage:
                out.append(stage)
    return out


async def chat_events(runner: ChatRunner, question: str, profile: dict[str, Any] | None,
                      metrics: MetricsSink | None = None, *, confirmed_item_seqs: Sequence[ConfirmedInput] = ()) -> AsyncIterator[AnyEvent]:
    """질문 하나의 이벤트 스트림. 항상 `done`으로 끝난다(정상이면 `answer` 뒤, 실패면 `error` 뒤).

    `confirmed_item_seqs`(되묻기에서 고른 약의 품목기준코드, AG-05-03 A)는 실행기로만 넘기고 지표·로그에 싣지 않는다."""
    started = time.monotonic()
    block_rules: list[str] = []  # 하네스 차단 이벤트의 규칙 ID(내용 없음)
    error_type: str | None = None
    finished = False
    seq = EventSequence()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    stop = threading.Event()
    usage = RequestUsage()  # 이 요청의 모델 사용량(숫자만, BE-06-36 A)
    threading.Thread(target=_run_in_thread, args=(runner, question, profile, tuple(confirmed_item_seqs), loop, queue, stop, usage),
                     daemon=True, name="chat-graph").start()
    final: dict[str, Any] = {}  # 응답 변환에 쓰는 값만 모은다(`answer`·`end_reason`·`clarify`·`entities`)
    last_stage: str | None = None
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            if isinstance(item, BaseException):
                raise item
            for node, update in item.items():
                if not isinstance(update, dict):
                    continue
                block_rules.extend(h["rule"] for h in harness_events(update.get("events") or []) if h["action"] == "block" and h["rule"])
                if node == "guardrail_in" and update.get("emergency"):
                    yield seq.emergency()
                elif node == "router":
                    # 되묻기 묶음과 확정 엔티티(표시 이름 표에만 씀, 이슈 F3). 지표·로그에는 싣지 않는다
                    final.update({k: update[k] for k in ("clarify", "entities") if k in update})
                elif node == "model":
                    for stage in _tool_stages(update):
                        if stage != last_stage:
                            last_stage = stage
                            yield seq.progress(stage)
                elif node == "finalize":
                    final.update({k: update[k] for k in ("answer", "end_reason") if k in update})
        yield seq.answer(response_from_state(final))
        yield seq.done()
        finished = True
    except Exception as exc:  # noqa: BLE001 — 스트림 중 실패는 오류 이벤트로 끝낸다
        error_type = type(exc).__name__
        logger.error("chat stream failed: %s", error_type)  # 예외 종류 이름만(메시지·질문은 남기지 않는다)
        if not any(isinstance(e, AnswerEvent | ErrorEvent) for e in seq.events):
            yield seq.error("INTERNAL_ERROR")
        if any(isinstance(e, AnswerEvent | ErrorEvent) for e in seq.events):
            yield seq.done()
        finished = True
    finally:
        stop.set()
        answered = next((e for e in seq.events if isinstance(e, AnswerEvent)), None)
        if not finished and error_type is None:  # 생성기가 중간에 닫혔다(연결 끊김)
            error_type = ERROR_CLIENT_GONE
        _record_metrics(metrics, latency_ms=(time.monotonic() - started) * 1000,
                        end_reason=answered.response.end_reason if answered and error_type is None else None,
                        error_type=error_type, block_rules=block_rules, usage=usage)


__all__ = ["METRICS_NODE", "TOOL_STAGE", "MetricsSink", "chat_events"]
