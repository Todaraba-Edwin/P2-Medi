"""BE-11 S1 `GET /me` 라우트와 인증 오류 처리기(2026-11-18).

- 로그인 필수: 토큰이 없으면 401 `AUTH_REQUIRED`, 검증 실패·만료는 401 `AUTH_INVALID`(`app.security.auth`).
- 지금은 DB 없이 `{user_id, is_guest: false}`만 돌려준다. `app_users` 행 생성(첫 호출)은 BE-11-10 결정 뒤에 붙인다.
  `GET /legal/{doc_type}` 등 DB가 필요한 계정 API는 BE-11-06 등 결정 뒤에 만든다.
- 오류 본문은 `/chat`과 같은 `ErrorBody{code, fields}`이고 토큰·입력 값을 싣지 않는다. 401에는 `WWW-Authenticate: Bearer`를,
  계정 응답에는 `Cache-Control: no-store`를 붙인다(`P2-doc/PJ2-계정-프로필-데이터.md` 9.1절).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.chat import ErrorBody
from app.security.auth import AuthError, Principal, require_user

NO_STORE = "no-store"


class MeResponse(BaseModel):
    """`GET /me` 응답(S1 골격). 온보딩 상태 등은 `app_users` 결정 뒤에 더한다."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    is_guest: bool = False


router = APIRouter()

_AUTH_ERRORS = {
    401: {"model": ErrorBody, "description": "토큰 없음(AUTH_REQUIRED) 또는 검증 실패·만료(AUTH_INVALID)."},
    501: {"model": ErrorBody, "description": "토큰 검증기 미설정(의도된 상태)."},
    503: {"model": ErrorBody, "description": "검증 서버에 닿지 못함(AUTH_UNAVAILABLE)."},
}


@router.get("/me", response_model=MeResponse, responses=_AUTH_ERRORS, summary="로그인한 사용자 정보(S1: user_id만)")
async def me(principal: Annotated[Principal, Depends(require_user)], response: Response) -> MeResponse:
    response.headers["Cache-Control"] = NO_STORE
    assert principal.user_id is not None  # noqa: S101 - require_user가 게스트를 막는다(타입 좁히기)
    return MeResponse(user_id=principal.user_id)


async def _auth_error(_: Request, exc: Exception) -> JSONResponse:
    status, code = (exc.status_code, exc.code) if isinstance(exc, AuthError) else (500, "INTERNAL")
    headers = {"Cache-Control": NO_STORE}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=ErrorBody(code=code).model_dump(), headers=headers)


def register(app: FastAPI) -> None:
    """`/me` 라우트와 인증 오류 처리기를 붙인다(main.py 한 줄)."""
    app.include_router(router)
    app.add_exception_handler(AuthError, _auth_error)


__all__ = ["MeResponse", "register", "router"]
