"""BE-06 `POST /chat` 라우트.

- **실행기가 주입되지 않았으면 501 Not Implemented**(의도된 상태). 실행기(`app.api.runner.ChatRunner`)는 `set_runner(app, runner)`로
  `app.state`에 붙인다. 이 모듈은 실행기를 스스로 만들지 않는다(실제 모델·DB·API 의존성을 앱 시작 때 붙이는 일은 따로 정한다).
- 실행기가 있으면 요청 묶음을 그래프 입력으로 옮겨(`runner.profile_from_context`) 그래프를 돌리고, 노드 갱신을 이벤트로 바꿔
  (`app.api.stream.chat_events`) NDJSON으로 보낸다. 이벤트 사이가 길면 하트비트 빈 줄을 보낸다(BE-06-10 A).
- 성공 응답은 `application/x-ndjson` 스트림이고 줄마다 `ChatEvent`(`app.api.events`)다. OpenAPI에는 200 응답 스키마로 `ChatEvent`를 싣는다.
  스트림이 시작된 뒤의 실패는 HTTP 상태가 아니라 `error` 이벤트로 알린다(상태는 이미 200이다).
- 오류 본문은 `ErrorBody{code, fields}`다. 4xx·5xx 본문에 **입력 값(질문 등)을 되돌려 주지 않는다**(FastAPI 기본 422 본문의 `input`을 쓰지 않음).
  오류 문구 상수는 승인 전이라 본문에 문구가 없다(문구 대기, 화면은 상태 코드로 처리한다).
- 질문·대화 상태는 저장·로그하지 않는다(PRD-07-01 A, RFP 7장). 요청 본문을 로깅하는 미들웨어를 두지 않는다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api import events
from app.api.events import NDJSON_MEDIA_TYPE, ChatEvent
from app.api.request import AgeInput, ChatRequest, ConfirmedDrug, ConversationContext
from app.api.runner import ChatRunner, confirmed_from_context, profile_from_context
from app.api.schemas import _Strict
from app.api.stream import MetricsSink, chat_events
from app.logging import SpanLogger

RUNNER_STATE_KEY = "chat_runner"  # `app.state`의 실행기 자리. 없으면 501
METRICS_STATE_KEY = "chat_metrics"  # `app.state`의 서비스 집계 기록기 자리(L4). None이면 집계하지 않는다
_DEFAULT_METRICS: Any = object()

CODE_INVALID_REQUEST = "INVALID_REQUEST"
CODE_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

# 422 본문 `fields`에 쓸 수 있는 칸 이름(요청 모델의 칸 이름만. 사용자가 보낸 임의의 키 이름은 싣지 않는다)
_KNOWN_FIELDS = frozenset(
    name for m in (ChatRequest, ConversationContext, AgeInput, ConfirmedDrug) for name in m.model_fields
)


class ErrorBody(_Strict):
    """4xx·5xx JSON 본문. 입력 값·내부 정보는 싣지 않는다."""

    code: str
    fields: list[str] = []


class NDJSONResponse(StreamingResponse):
    """실제 스트림 응답(그래프 연결 뒤 라우트가 돌려준다)."""

    media_type = NDJSON_MEDIA_TYPE


class _NDJSONDoc(JSONResponse):
    """OpenAPI 문서용 응답 클래스. 비 JSON 응답 클래스면 FastAPI가 200 스키마에 `type: string`을 덧붙이므로 이 클래스로 선언한다."""

    media_type = NDJSON_MEDIA_TYPE


router = APIRouter()


@router.post(
    "/chat",
    response_class=_NDJSONDoc,
    responses={
        200: {"model": ChatEvent, "description": "NDJSON 스트림. 줄마다 ChatEvent 하나(순서 규칙은 app.api.events)."},
        422: {"model": ErrorBody, "description": "요청 형식 오류(빈 질문·길이 초과·모르는 칸). 입력 값은 되돌려 주지 않는다."},
        501: {"model": ErrorBody, "description": "그래프 연결 전(의도된 상태)."},
    },
    summary="질문을 받아 진행·응급·최종 응답 이벤트를 NDJSON으로 보낸다",
)
async def chat(request: ChatRequest, http_request: Request) -> Response:
    runner: ChatRunner | None = getattr(http_request.app.state, RUNNER_STATE_KEY, None)
    if runner is None:  # 실행기 미주입(의도된 상태)
        return JSONResponse(status_code=501, content=ErrorBody(code=CODE_NOT_IMPLEMENTED).model_dump())
    # 질문·요청 묶음은 저장·로그하지 않고 그래프 입력으로만 쓴다(PRD-07-01 A).
    # `context.confirmed_drugs`는 품목기준코드만 Router 확정 입력으로 넘긴다(AG-05-03 A, 이름은 넘기지 않는다)
    metrics: MetricsSink | None = getattr(http_request.app.state, METRICS_STATE_KEY, None)
    stream = chat_events(runner, request.question, profile_from_context(request.context), metrics,
                         confirmed_item_seqs=confirmed_from_context(request.context))
    return NDJSONResponse(events.ndjson_with_heartbeat(stream, interval_s=events.HEARTBEAT_INTERVAL_S))


def set_runner(app: FastAPI, runner: ChatRunner | None, *, metrics: MetricsSink | None = _DEFAULT_METRICS) -> None:
    """`/chat`이 쓸 실행기를 붙인다(None이면 뗀다 → 501).

    `metrics`를 주지 않으면 서비스 집계 기록기(`SpanLogger(mode="service")`: 내용 없는 분 단위 합계를 표준 출력으로, 파일 없음)를 붙인다.
    None을 주면 집계하지 않는다.
    """
    setattr(app.state, RUNNER_STATE_KEY, runner)
    if metrics is _DEFAULT_METRICS:
        metrics = SpanLogger(mode="service") if runner is not None else None
    setattr(app.state, METRICS_STATE_KEY, metrics)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    fields: list[str] = []
    for err in exc.errors() if isinstance(exc, RequestValidationError) else []:
        parts: list[str] = []
        for p in tuple(err.get("loc") or ())[1:]:  # 첫 칸은 "body"
            if isinstance(p, int):
                if not parts:  # JSON 구문 오류 위치(글자 번호)는 칸이 아니다
                    break
                parts.append(str(p))
            elif p in _KNOWN_FIELDS:
                parts.append(p)
            else:
                break
        path = ".".join(parts) or "body"
        if path not in fields:
            fields.append(path)
    return JSONResponse(status_code=422, content=ErrorBody(code=CODE_INVALID_REQUEST, fields=fields).model_dump())


_JSON_ERROR_STATUS = ("422", "501")


def _fix_error_media_types(schema: dict) -> dict:
    """`/chat`의 4xx·5xx 본문은 JSON이다. FastAPI는 추가 응답을 라우트 미디어 타입(ndjson) 아래에 두므로 `application/json`으로 옮긴다."""
    responses = schema.get("paths", {}).get("/chat", {}).get("post", {}).get("responses", {})
    for code in _JSON_ERROR_STATUS:
        content = responses.get(code, {}).get("content", {})
        if NDJSON_MEDIA_TYPE in content:
            content["application/json"] = content.pop(NDJSON_MEDIA_TYPE)
    return schema


def register(app: FastAPI) -> None:
    """`/chat` 라우트와 요청 형식 오류 처리기를 붙인다(main.py 한 줄)."""
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, _validation_error)
    base = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = _fix_error_media_types(base())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


__all__ = ["ErrorBody", "NDJSONResponse", "register", "router", "set_runner"]
