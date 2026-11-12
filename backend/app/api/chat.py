"""BE-06 `POST /chat` 라우트 선언(그래프 연결 전).

- **의도된 상태: 501 Not Implemented.** 요청 형식 검사(`ChatRequest`)까지만 하고 그래프를 부르지 않는다. 그래프 호출 연결은
  선행 AG-05~09가 끝난 뒤 BE-06 하위 작업 "그래프 호출 연결"에서 한다. 이 상태는 TODO가 아니라 계약 고정 단계의 결과이며 시험이 고정한다.
- 성공 응답(연결 뒤)은 `application/x-ndjson` 스트림이고 줄마다 `ChatEvent`(`app.api.events`)다. OpenAPI에는 200 응답 스키마로 `ChatEvent`를 싣는다.
- 오류 본문은 `ErrorBody{code, fields}`다. 4xx·5xx 본문에 **입력 값(질문 등)을 되돌려 주지 않는다**(FastAPI 기본 422 본문의 `input`을 쓰지 않음).
  오류 문구 상수는 승인 전이라 본문에 문구가 없다(문구 대기, 화면은 상태 코드로 처리한다).
- 질문·대화 상태는 저장·로그하지 않는다(PRD-07-01 A, RFP 7장). 요청 본문을 로깅하는 미들웨어를 두지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.events import NDJSON_MEDIA_TYPE, ChatEvent
from app.api.request import AgeInput, ChatRequest, ConfirmedDrug, ConversationContext
from app.api.schemas import _Strict

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
def chat(request: ChatRequest) -> JSONResponse:
    del request  # 저장·로그하지 않는다. 그래프 연결 전이라 쓰지 않는다
    return JSONResponse(status_code=501, content=ErrorBody(code=CODE_NOT_IMPLEMENTED).model_dump())


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


__all__ = ["ErrorBody", "NDJSONResponse", "register", "router"]
