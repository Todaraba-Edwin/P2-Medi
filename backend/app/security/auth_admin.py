"""BE-11-24 A: 탈퇴 때 Supabase `auth.users` 사용자 삭제(Admin API, 2026-11-20).

- 설계 `P2-doc/PJ2-계정-프로필-데이터.md` 7.1절 3·4단계. `DELETE /me`가 앱 데이터(프로필·복용 약·동의 기록)를 지운 **뒤** 부른다.
- 호출: `DELETE {SUPABASE_URL}/auth/v1/admin/users/{user_id}`, 헤더 `apikey`·`Authorization: Bearer`에 서버 전용
  `SUPABASE_SECRET_KEY`, 본문 `{"should_soft_delete": false}`(supabase-js `auth.admin.deleteUser` 기본과 같음).
  - 200·204 → 삭제됨. 404 → 이미 없음(재요청·다른 경로 삭제)으로 보고 성공 처리(멱등).
  - 그 밖의 상태·연결 오류·시간 초과 → `AuthAdminError`(API는 502 `AUTH_DELETE_FAILED`).
- **키·요청 헤더·응답 본문을 로그·예외 메시지·repr에 남기지 않는다**(sec-guard). 예외에는 상태 번호나 예외 종류 이름만 담고,
  httpx 예외 체인(요청 객체·헤더 포함)은 `from None`으로 끊는다.
- 시험은 `httpx.MockTransport`를 넣은 클라이언트로만 돈다(원격 호출 0). 앱 시작 때는 접속하지 않는다.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import Settings, reveal

logger = logging.getLogger(__name__)

AUTH_ADMIN_STATE_KEY = "auth_admin"  # `app.state`의 자리. 없으면 탈퇴는 앱 데이터만 지우고 502 `AUTH_DELETE_FAILED`
CODE_AUTH_DELETE_FAILED = "AUTH_DELETE_FAILED"


class AuthAdminError(Exception):
    """Auth 사용자 삭제 실패. 메시지는 오류 유형(상태 번호·예외 종류 이름)만 담는다."""


@runtime_checkable
class AuthAdmin(Protocol):
    """Supabase Auth 관리 작업. 지금은 사용자 삭제 하나다. 실패하면 `AuthAdminError`."""

    async def delete_user(self, user_id: str) -> None: ...


def _http_base(url: str) -> str:
    base = url.rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://"):
        raise ValueError("supabase_url은 http(s) 주소여야 한다")
    return base


class SupabaseAuthAdmin:
    """Supabase Auth Admin API(`/auth/v1/admin/users/{id}`) 클라이언트. 클라이언트를 주면 그것을 쓰고, 없으면 호출마다 만든다."""

    def __init__(self, supabase_url: str, secret_key: str, *, client: httpx.AsyncClient | None = None,
                 timeout_s: float = 5.0) -> None:
        if not secret_key:
            raise ValueError("secret_key가 비었다")
        self._base = f"{_http_base(supabase_url)}/auth/v1/admin/users"
        self._key = secret_key
        self._client = client
        self._timeout = timeout_s

    def __repr__(self) -> str:  # 주소·키를 repr에 싣지 않는다
        return f"{type(self).__name__}(url=<set>, key=<set>)"

    async def delete_user(self, user_id: str) -> None:
        try:
            uid = str(uuid.UUID(user_id))  # 경로에 넣기 전에 UUID만 받는다(경로 조작 방지)
        except (ValueError, TypeError, AttributeError):
            raise AuthAdminError("bad user id") from None
        url = f"{self._base}/{uid}"
        headers = {"apikey": self._key, "Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        body: dict[str, Any] = {"should_soft_delete": False}
        try:
            if self._client is not None:
                resp = await self._client.request("DELETE", url, headers=headers, json=body, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.request("DELETE", url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise AuthAdminError(type(exc).__name__) from None  # 요청 객체(헤더=키 포함)를 예외 체인에 남기지 않는다
        if resp.status_code in (200, 204, 404):  # 404: 이미 없음 → 멱등 성공
            return
        raise AuthAdminError(f"status {resp.status_code}")  # 응답 본문은 읽지 않는다


def build_auth_admin(settings: Settings) -> AuthAdmin | None:
    """앱 시작 때 붙일 Admin 클라이언트. 접속하지 않는다. `SUPABASE_URL`·`SUPABASE_SECRET_KEY`가 없으면 None."""
    url = settings.supabase_url
    key = reveal(settings.supabase_secret_key)
    if not url or not key:
        return None
    try:
        return SupabaseAuthAdmin(url, key)
    except ValueError:
        logger.warning("Auth 관리 클라이언트를 만들지 않았다: SUPABASE_URL 형식 오류")  # 값은 남기지 않는다
        return None


def set_auth_admin(app: Any, admin: AuthAdmin | None) -> None:
    """Admin 클라이언트를 `app.state`에 붙인다(None이면 뗀다 → 탈퇴는 앱 데이터만 지우고 502)."""
    setattr(app.state, AUTH_ADMIN_STATE_KEY, admin)


def get_auth_admin(app: Any) -> AuthAdmin | None:
    return getattr(app.state, AUTH_ADMIN_STATE_KEY, None)


__all__ = [
    "AUTH_ADMIN_STATE_KEY", "CODE_AUTH_DELETE_FAILED", "AuthAdmin", "AuthAdminError", "SupabaseAuthAdmin", "build_auth_admin",
    "get_auth_admin", "set_auth_admin",
]
