"""BE-11 `GET /me`·`DELETE /me` 라우트와 계정 API 등록(2026-11-18).

- 로그인 필수: 토큰이 없으면 401 `AUTH_REQUIRED`, 검증 실패·만료는 401 `AUTH_INVALID`, 검증 서버 장애 503 `AUTH_UNAVAILABLE`
  (`app.security.auth`, BE-11-20 A). 계정 저장소가 없으면 501 `NOT_IMPLEMENTED`(`app.api.account`).
- `GET /me`: 첫 호출에 `app_users` 행을 만든다(BE-11-10 A). 응답은 온보딩 단계·완료 시각·문서별 동의 상태·건강 정보 저장 가능 여부.
- `DELETE /me`: 설계 7.1절 순서. ① 계정 행·프로필·복용 약·동의 기록을 즉시 모두 지운다(BE-11-22 A, 파기 사실은 일자별 건수만).
  ② Supabase Admin API로 `auth.users` 사용자를 지운다(BE-11-24 A, `app.security.auth_admin`, 서버 전용 `SUPABASE_SECRET_KEY`).
  ②가 실패하거나 Admin 클라이언트가 없으면 502 `AUTH_DELETE_FAILED`(앱 데이터는 이미 지워짐, 재요청하면 ①②를 다시 한다·멱등).
  ②가 끝나면 `app_users.user_id → auth.users` FK 때문에 남은 access token(만료 전)으로 `GET /me`를 불러도 빈 계정이 다시 생기지 않고
  401 `AUTH_INVALID`다(저장소 `NO_ACCOUNT`).
- 오류 본문은 `/chat`과 같은 `ErrorBody{code, fields}`이고 토큰·입력 값을 싣지 않는다(BE-11-21 A). 401에는 `WWW-Authenticate: Bearer`,
  계정 응답에는 `Cache-Control: no-store`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import account
from app.api import chat as chat_api
from app.api.account import NO_STORE, MeResponse, RepoDep, UserDep, build_me, user_id_of
from app.api.chat import ErrorBody
from app.db.account_repo import AccountRepoError, RepoUnavailable
from app.security.auth import AuthError
from app.security.auth_admin import CODE_AUTH_DELETE_FAILED, AuthAdminError, get_auth_admin

logger = logging.getLogger(__name__)

router = account.router  # 계정 라우트는 한 라우터에 모은다(/legal·/consents·/profiles는 account 모듈)

_ME_ERRORS = {k: account._ACCOUNT_ERRORS[k] for k in (401, 501, 503)}  # /me는 동의·형식 오류가 없다
_DELETE_ME_ERRORS = {**_ME_ERRORS, 502: {"model": ErrorBody, "description": "AUTH_DELETE_FAILED: 앱 데이터는 지웠고 로그인 계정 "
                                         "삭제가 실패했다. 다시 요청하면 이어서 지운다(멱등)."}}


@router.get("/me", response_model=MeResponse, responses=_ME_ERRORS,
            summary="로그인한 사용자 정보(첫 호출에 계정 행 생성, 온보딩·동의 상태)")
async def me(principal: UserDep, repo: RepoDep, response: Response) -> MeResponse:
    response.headers["Cache-Control"] = NO_STORE
    user = await repo.ensure_user(user_id_of(principal))
    return await build_me(repo, user)


@router.delete("/me", status_code=204, responses=_DELETE_ME_ERRORS,
               summary="계정 삭제(프로필·복용 약·동의 기록 즉시 전부 파기 뒤 로그인 계정 삭제)")
async def delete_me(principal: UserDep, repo: RepoDep, request: Request) -> Response:
    user_id = user_id_of(principal)
    # ① 앱 데이터 먼저(7.1절 2단계): Auth API가 죽어 있어도 건강 정보는 바로 지운다
    summary = await repo.delete_account(user_id)
    # 식별자 없이 건수만(BE-11-22 A). 사용자 ID·토큰·값은 남기지 않는다
    logger.info("계정 파기: 프로필 %d건, 복용 약 %d건, 동의 기록 %d건", summary.profiles, summary.medications, summary.consents)
    # ② auth.users 삭제(7.1절 3·4단계, BE-11-24 A). 실패는 오류 유형만 남기고 502
    admin = get_auth_admin(request.app)
    if admin is None:
        logger.warning("로그인 계정 삭제 안 함: Auth 관리 클라이언트 미설정")
        return _delete_failed()
    try:
        await admin.delete_user(user_id)
    except AuthAdminError as exc:
        logger.warning("로그인 계정 삭제 실패: %s", exc)  # 상태 번호·예외 종류 이름만 담겨 있다
        return _delete_failed()
    logger.info("로그인 계정 삭제 완료")
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


def _delete_failed() -> JSONResponse:
    return JSONResponse(status_code=502, content=ErrorBody(code=CODE_AUTH_DELETE_FAILED).model_dump(),
                        headers={"Cache-Control": NO_STORE})


async def _auth_error(_: Request, exc: Exception) -> JSONResponse:
    status, code = (exc.status_code, exc.code) if isinstance(exc, AuthError) else (500, "INTERNAL")
    headers = {"Cache-Control": NO_STORE}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=ErrorBody(code=code).model_dump(), headers=headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    """계정 경로는 계정 칸 이름으로, 그 밖(`/chat`)은 기존 처리기로 넘긴다(본문은 둘 다 `{code, fields}`, 입력 값 없음)."""
    if isinstance(exc, RequestValidationError) and account.is_account_path(request.url.path):
        return JSONResponse(status_code=422, content=ErrorBody(code=account.CODE_INVALID_REQUEST,
                                                               fields=account.validation_fields(exc)).model_dump(),
                            headers={"Cache-Control": NO_STORE})
    return await chat_api._validation_error(request, exc)


def register(app: FastAPI) -> None:
    """계정 라우트(`/me`·`/legal`·`/consents`·`/profiles`)와 오류 처리기를 붙인다(main.py 한 줄).

    `chat_api.register` **뒤에** 불러야 한다: 요청 형식 오류 처리기를 계정 경로 분기가 있는 것으로 바꾼다(`/chat` 동작은 그대로).
    """
    app.include_router(router)
    app.add_exception_handler(AuthError, _auth_error)
    for exc_type in (account.AccountError, AccountRepoError, RepoUnavailable):
        app.add_exception_handler(exc_type, account.account_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error)


__all__ = ["MeResponse", "register", "router"]
