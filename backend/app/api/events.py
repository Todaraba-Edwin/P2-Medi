"""BE-06 스트림 이벤트 `chat_event@v1`(NDJSON)와 순서 규칙·하트비트.

## 전송 형식
`Content-Type: application/x-ndjson`, UTF-8, 한 줄에 JSON 객체 하나, 줄 끝 `\\n`. 판별 키는 `type`이고 필드는 평평하다
(`PJ2-프론트-기술스택.md` 4장 (4) 초안 형식. 로컬 mock의 `event`+`data` 형식은 쓰지 않는다). 공통 필드: `type`·`seq`·`schema_version`.

| type | 필드 |
|---|---|
| `progress` | `stage`(`drug_lookup`·`contraindication_check`·`evidence_search`), `label`(서버 상수 `fixed_phrases.PROGRESS_LABELS[stage]`, BE-06-09 A) |
| `emergency` | `emergency`(`ChatResponse.emergency`와 같은 모양, 상수 그대로) |
| `answer` | `response`(`ChatResponse` 전체, `chat_response@v1`) |
| `error` | `code`(`ERROR_CODES`), `message`(오류 문구 상수 `fixed_phrases.ERROR_MESSAGES[code]`, 2026-11-12 승인) |
| `done` | `end_reason`(`answer`가 있으면 그 `response.end_reason`과 같은 값, `error` 뒤면 null) |

## 순서 규칙(`check_event_order`가 코드로 검사한다)
1. `seq`는 0에서 시작해 이벤트마다 1씩 늘어난다(빠짐·역순 없음). 하트비트 빈 줄은 이벤트가 아니라 `seq`가 없다.
2. **응급 첫 이벤트(PRD-01-02)**: 응급이면 `emergency`가 `seq` 0이다. 입구 `guardrail_in`(코드)이 LLM 호출 전에 감지해 보낸다.
   `emergency`는 한 번만, 첫 자리에만 온다. `answer.response.emergency`가 있으면 첫 이벤트가 `emergency`여야 하고, 그 반대도 같다.
3. `progress`는 0번 이상, `answer`·`error` 전에만 온다(단계 순서는 강제하지 않는다. 도구 호출이 되돌아갈 수 있다).
4. `answer`와 `error`는 한 스트림에 둘 중 하나만, 한 번만 온다. 그 뒤에는 `done`만 온다(`answer` 뒤 `error` 없음).
5. `done`은 마지막 이벤트이고 한 번만 온다. **`answer` 없는 `done`은 `error` 뒤에만 허용한다**(정상 종료면 반드시 `answer`가 먼저).
6. `done` 없이 끝난 스트림은 서버 규칙 위반이 아니라 전송 끊김이다(프런트 처리: 기술스택 4장 (3)).

## 하트비트(BE-06-10 A)
이벤트 사이가 `HEARTBEAT_INTERVAL_S`보다 길면 서버는 빈 줄(`\\n`)을 보낸다. 프런트는 빈 줄을 이벤트로 파싱하지 않고 건너뛰되
**무응답 시계는 다시 돌린다**(서버 생존 신호). 주기는 프런트 무응답 상한(`CLIENT_IDLE_TIMEOUT_S`, 가정 60초, BE-13에서 확정)보다 짧아야 한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import Annotated, Literal

from pydantic import Field, RootModel, model_validator

from app.agent import fixed_phrases as fp
from app.api.schemas import ChatResponse, Emergency, EndReason, _Strict

EVENT_SCHEMA_VERSION = "chat_event@v1"
NDJSON_MEDIA_TYPE = "application/x-ndjson"

Stage = Literal["drug_lookup", "contraindication_check", "evidence_search"]
STAGES: tuple[str, ...] = tuple(fp.PROGRESS_LABELS)

# 오류 코드(스트림 중 실패). 문구는 `fixed_phrases.ERROR_MESSAGES` 상수 그대로다(0-E 1-1~1-3 승인, 2026-11-12)
ErrorCode = Literal["INTERNAL_ERROR", "TIMEOUT", "UPSTREAM_UNAVAILABLE"]
ERROR_CODES: tuple[str, ...] = ("INTERNAL_ERROR", "TIMEOUT", "UPSTREAM_UNAVAILABLE")
ERROR_MESSAGES: dict[str, str | None] = {code: fp.ERROR_MESSAGES[code] for code in ERROR_CODES}

# 하트비트(BE-06-10 A)
HEARTBEAT_LINE = b"\n"
HEARTBEAT_INTERVAL_S = 15.0  # 가정: 프런트 무응답 상한보다 충분히 짧게
CLIENT_IDLE_TIMEOUT_S = 60.0  # 가정: 프런트 `STREAM_IDLE_TIMEOUT_MS`(60000)와 같은 값. BE-13(Vercel 시간 상한)에서 확정
if not HEARTBEAT_INTERVAL_S < CLIENT_IDLE_TIMEOUT_S:  # pragma: no cover - 상수 정의 오류
    raise RuntimeError("HEARTBEAT_INTERVAL_S는 CLIENT_IDLE_TIMEOUT_S보다 짧아야 한다")


class _Event(_Strict):
    seq: int = Field(ge=0)
    schema_version: Literal["chat_event@v1"] = EVENT_SCHEMA_VERSION


class ProgressEvent(_Event):
    type: Literal["progress"] = "progress"
    stage: Stage
    label: str  # 서버 상수에서만(BE-06-09 A)

    @model_validator(mode="after")
    def _label_is_constant(self) -> ProgressEvent:
        if self.label != fp.PROGRESS_LABELS[self.stage]:
            raise ValueError("progress.label은 fixed_phrases.PROGRESS_LABELS[stage] 그대로여야 한다")
        return self


class EmergencyEvent(_Event):
    type: Literal["emergency"] = "emergency"
    emergency: Emergency


class AnswerEvent(_Event):
    type: Literal["answer"] = "answer"
    response: ChatResponse


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None

    @model_validator(mode="after")
    def _message_is_constant(self) -> ErrorEvent:
        if self.message != ERROR_MESSAGES[self.code]:
            raise ValueError("error.message는 오류 문구 상수(ERROR_MESSAGES) 그대로여야 한다")
        return self


class DoneEvent(_Event):
    type: Literal["done"] = "done"
    end_reason: EndReason | None = None


AnyEvent = ProgressEvent | EmergencyEvent | AnswerEvent | ErrorEvent | DoneEvent


class ChatEvent(RootModel[Annotated[AnyEvent, Field(discriminator="type")]]):
    """스트림 이벤트 한 줄(판별 유니온, 키 `type`). OpenAPI에 `ChatEvent`로 노출된다."""


# ---------------------------------------------------------------- 만들기(라벨·문구는 상수에서만)
def progress(seq: int, stage: str) -> ProgressEvent:
    return ProgressEvent(seq=seq, stage=stage, label=fp.PROGRESS_LABELS[stage])  # type: ignore[arg-type]


def emergency(seq: int) -> EmergencyEvent:
    return EmergencyEvent(seq=seq, emergency=Emergency(text=fp.EMERGENCY_119, tel=fp.EMERGENCY_119_TEL))


def answer(seq: int, response: ChatResponse) -> AnswerEvent:
    return AnswerEvent(seq=seq, response=response)


def error(seq: int, code: str) -> ErrorEvent:
    return ErrorEvent(seq=seq, code=code, message=ERROR_MESSAGES[code])  # type: ignore[arg-type]


def done(seq: int, end_reason: str | None) -> DoneEvent:
    return DoneEvent(seq=seq, end_reason=end_reason)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 순서 규칙
class EventOrderError(ValueError):
    """순서 규칙 위반. `rule`은 모듈 설명의 규칙 번호."""

    def __init__(self, rule: int, message: str) -> None:
        super().__init__(f"규칙 {rule}: {message}")
        self.rule = rule


def _unwrap(e: AnyEvent | ChatEvent) -> AnyEvent:
    return e.root if isinstance(e, ChatEvent) else e


def check_event_order(events: Sequence[AnyEvent | ChatEvent], *, complete: bool = True) -> None:
    """이벤트 목록이 순서 규칙을 지키는지 본다. `complete=False`면 아직 진행 중인 앞부분(`done` 전)으로 본다."""
    evs = [_unwrap(e) for e in events]
    answered: AnswerEvent | None = None
    errored = False
    for i, e in enumerate(evs):
        if e.seq != i:
            raise EventOrderError(1, f"seq는 0부터 1씩 늘어야 한다(위치 {i}, seq {e.seq})")
        if i > 0 and isinstance(evs[i - 1], DoneEvent):
            raise EventOrderError(5, "done 뒤에는 이벤트가 없다")
        if isinstance(e, EmergencyEvent) and i != 0:
            raise EventOrderError(2, "emergency는 첫 이벤트에만 온다")
        if isinstance(e, ProgressEvent) and (answered or errored):
            raise EventOrderError(3, "progress는 answer·error 전에만 온다")
        if isinstance(e, AnswerEvent | ErrorEvent):
            if answered or errored:
                raise EventOrderError(4, "answer·error는 한 스트림에 하나만 온다")
            if isinstance(e, AnswerEvent):
                answered = e
            else:
                errored = True
        if isinstance(e, DoneEvent):
            if not (answered or errored):
                raise EventOrderError(5, "answer 없는 done은 error 뒤에만 허용한다")
            expected = answered.response.end_reason if answered else None
            if e.end_reason != expected:
                raise EventOrderError(5, "done.end_reason은 answer.response.end_reason과 같아야 한다(error 뒤면 null)")
    first_is_emergency = bool(evs) and isinstance(evs[0], EmergencyEvent)
    if answered is not None and (answered.response.emergency is not None) != first_is_emergency:
        raise EventOrderError(2, "응답에 emergency가 있으면 첫 이벤트가 emergency여야 하고, 그 반대도 같다")
    if complete and not (evs and isinstance(evs[-1], DoneEvent)):
        raise EventOrderError(5, "완결된 스트림은 done으로 끝난다")


class EventSequence:
    """이벤트에 `seq`를 매기고 순서 규칙을 그때그때 검사하며 만든다(그래프 연결 때 스트림 생성기가 쓴다)."""

    def __init__(self) -> None:
        self.events: list[AnyEvent] = []

    def _add(self, e: AnyEvent) -> AnyEvent:
        check_event_order([*self.events, e], complete=False)
        self.events.append(e)
        return e

    @property
    def next_seq(self) -> int:
        return len(self.events)

    def emergency(self) -> AnyEvent:
        return self._add(emergency(self.next_seq))

    def progress(self, stage: str) -> AnyEvent:
        return self._add(progress(self.next_seq, stage))

    def answer(self, response: ChatResponse) -> AnyEvent:
        return self._add(answer(self.next_seq, response))

    def error(self, code: str) -> AnyEvent:
        return self._add(error(self.next_seq, code))

    def done(self) -> AnyEvent:
        a = next((e for e in self.events if isinstance(e, AnswerEvent)), None)
        return self._add(done(self.next_seq, a.response.end_reason if a else None))


# ---------------------------------------------------------------- NDJSON 인코딩·하트비트
def encode_event(e: AnyEvent | ChatEvent) -> bytes:
    """이벤트 한 줄(UTF-8 JSON + `\\n`). 한 줄 안에 개행이 들어가지 않는다(JSON 문자열의 개행은 `\\n`으로 이스케이프된다)."""
    ev = _unwrap(e)
    # `name_corrections`(AG-10-02 A)는 보정이 있을 때만 싣는다. 보정이 없는 응답의 글자가 칸을 더하기 전과 같아야, 모르는 키를 거부하는
    # 프런트 검증(`strictObject`)이 이 칸을 받기 전에도 기존 응답이 깨지지 않는다. 스키마(OpenAPI)에는 칸이 그대로 있다(기본 빈 목록).
    exclude = {"response": {"name_corrections"}} if isinstance(ev, AnswerEvent) and not ev.response.name_corrections else None
    return ev.model_dump_json(exclude=exclude).encode("utf-8") + b"\n"


async def ndjson_with_heartbeat(
    events: AsyncIterable[AnyEvent | ChatEvent], interval_s: float = HEARTBEAT_INTERVAL_S
) -> AsyncIterator[bytes]:
    """이벤트를 NDJSON 줄로 내보내고, 다음 이벤트가 `interval_s` 넘게 없으면 빈 줄을 보낸다(BE-06-10 A).

    기다리는 동안 원본 생성기를 끊지 않는다(대기 시간이 지나도 같은 `__anext__`를 계속 기다린다).
    """
    it = aiter(events)
    pending: asyncio.Future[AnyEvent | ChatEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(it))
            finished, _ = await asyncio.wait({pending}, timeout=interval_s)
            if not finished:
                yield HEARTBEAT_LINE
                continue
            task, pending = pending, None
            try:
                ev = task.result()
            except StopAsyncIteration:
                return
            yield encode_event(ev)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
