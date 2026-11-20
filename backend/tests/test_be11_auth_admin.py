"""BE-11-24 A 시험: 탈퇴 때 Supabase `auth.users` 삭제(Admin API, 2026-11-20). 네트워크·DB·LLM 호출 0.

- Admin API는 `httpx.MockTransport` 가짜 서버(`FakeAuthServer`)만 쓴다. 키는 시험용 가짜 문자열이다(실제 키 아님).
- 확인: 요청 모양(메서드·경로·헤더·본문), 200·204·404 성공(404 멱등), 5xx·연결 오류·이상한 ID → `AuthAdminError`,
  `DELETE /me` 순서(앱 데이터 먼저 → auth.users), 실패·미설정 502 `AUTH_DELETE_FAILED`(앱 데이터는 지워짐, 재요청 멱등),
  탈퇴 뒤 같은 토큰으로 `/me`가 빈 계정을 다시 만들지 않음(FK 흉내), 키·토큰·사용자 ID가 로그·응답·repr에 없음(sec-guard `redact`),
  `build_auth_admin` 설정 조건, lifespan 연결.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import account as account_api
from app.api import chat as chat_api
from app.api import me as me_api
from app.config import Settings
from app.db.account_repo import InMemoryAccountRepo, LegalDoc, body_sha256
from app.security import auth, auth_admin
from app.security.auth import TokenInvalid
from app.security.auth_admin import AuthAdminError, SupabaseAuthAdmin, build_auth_admin
from app.security.redact import redact

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(days=1)
BASE = "https://unit-test.supabase.invalid"
FAKE_SECRET = "QQQQ-FAKE-ADMIN-UNITTEST-9f3kQz7Lw2"  # 시험용 가짜 키(실제 값 아님, 헤더라 ASCII). 새면 찾기 쉬운 표지
UID = "33333333-3333-4333-8333-333333333333"
TOK = "eyJhbGciOiJFUzI1NiJ9.eyJ1c2VyIjoiYyJ9.c2lnLWM"
MED_SECRET = "비밀약이름정"


class FakeAuthServer:
    """가짜 Supabase Auth Admin. `DELETE /auth/v1/admin/users/{id}`가 `users`에서 지운다. `status`를 주면 그 상태로 답한다."""

    def __init__(self, users: set[str], *, status: int | None = None, error: Exception | None = None) -> None:
        self.users = users
        self.status = status
        self.error = error
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status is not None:
            return httpx.Response(self.status, json={"msg": f"echo {FAKE_SECRET}"})  # 본문에 키가 섞여도 읽지 않아야 한다
        prefix = "/auth/v1/admin/users/"
        if request.method != "DELETE" or not request.url.path.startswith(prefix):
            return httpx.Response(405)
        uid = request.url.path[len(prefix):]
        if uid not in self.users:
            return httpx.Response(404, json={"code": 404, "msg": "User not found"})
        self.users.discard(uid)
        return httpx.Response(200, json={})

    def admin(self) -> SupabaseAuthAdmin:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return SupabaseAuthAdmin(BASE, FAKE_SECRET, client=client)


class TokenOne:
    async def verify(self, token: str) -> str:
        if token == TOK:
            return UID
        raise TokenInvalid("rejected")


def _docs() -> list[LegalDoc]:
    out = []
    for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"):
        body = f"{t} v1 본문"
        out.append(LegalDoc(t, 1, f"{t} v1", body, t in ("terms", "privacy_consent", "age_14"), False, PAST, "not_reviewed",
                            body_sha256(body)))
    return out


def _env(server: FakeAuthServer | None, users: set[str]) -> tuple[TestClient, InMemoryAccountRepo]:
    repo = InMemoryAccountRepo(_docs(), clock=lambda: NOW, auth_users=users)
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    auth.set_verifier(app, TokenOne())
    auth_admin.set_auth_admin(app, server.admin() if server is not None else None)
    account_api.set_repo(app, repo)
    return TestClient(app), repo


def _h() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOK}"}


def _onboard(c: TestClient) -> None:
    assert c.get("/me", headers=_h()).status_code == 200
    items = [{"doc_type": t, "version": 1, "action": "agree"} for t in ("terms", "privacy_consent", "age_14", "sensitive_consent")]
    assert c.post("/consents", headers=_h(), json={"items": items, "channel": "onboarding"}).status_code == 201
    assert c.post("/profiles", headers=_h(), json={"relation": "self", "medications": [{"input_text": MED_SECRET}]}).status_code == 201


# --------------------------------------------------------------------------- 1. 클라이언트 단위
def test_delete_user_request_shape_and_success():
    users = {UID}
    server = FakeAuthServer(users)
    asyncio.run(server.admin().delete_user(UID))
    (req,) = server.requests
    assert req.method == "DELETE" and str(req.url) == f"{BASE}/auth/v1/admin/users/{UID}"
    assert req.headers["apikey"] == FAKE_SECRET and req.headers["authorization"] == f"Bearer {FAKE_SECRET}"
    assert json.loads(req.content) == {"should_soft_delete": False}  # 하드 삭제(supabase-js 기본과 같음)
    assert users == set()


@pytest.mark.parametrize("status", [200, 204, 404])
def test_delete_user_success_statuses_including_404_idempotent(status):
    asyncio.run(FakeAuthServer({UID}, status=status).admin().delete_user(UID))


@pytest.mark.parametrize(("server", "kind"), [
    (FakeAuthServer(set(), status=500), "status 500"),
    (FakeAuthServer(set(), status=401), "status 401"),  # 키가 틀림 → 실패(성공으로 삼키지 않는다)
    (FakeAuthServer(set(), error=httpx.ConnectError("boom")), "ConnectError"),
    (FakeAuthServer(set(), error=httpx.ReadTimeout("slow")), "ReadTimeout"),
])
def test_delete_user_failures_carry_kind_only(server, kind):
    with pytest.raises(AuthAdminError) as info:
        asyncio.run(server.admin().delete_user(UID))
    assert str(info.value) == kind and info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__  # httpx 예외(요청·헤더) 체인 끊김
    assert FAKE_SECRET not in str(info.value)


@pytest.mark.parametrize("bad", ["../users", "not-a-uuid", f"{UID}/../x", ""])
def test_delete_user_rejects_non_uuid_without_network(bad):
    server = FakeAuthServer({UID})
    with pytest.raises(AuthAdminError):
        asyncio.run(server.admin().delete_user(bad))
    assert server.requests == []


def test_repr_and_constructor_hide_key():
    admin = SupabaseAuthAdmin(BASE, FAKE_SECRET)
    assert FAKE_SECRET not in repr(admin) and BASE not in repr(admin)
    with pytest.raises(ValueError):
        SupabaseAuthAdmin("ftp://x", FAKE_SECRET)
    with pytest.raises(ValueError):
        SupabaseAuthAdmin(BASE, "")


def test_build_auth_admin_needs_url_and_secret_key():
    assert build_auth_admin(Settings(_env_file=None, supabase_url=None, supabase_secret_key=FAKE_SECRET)) is None
    assert build_auth_admin(Settings(_env_file=None, supabase_url=BASE, supabase_secret_key=None)) is None
    assert build_auth_admin(Settings(_env_file=None, supabase_url="not-a-url", supabase_secret_key=FAKE_SECRET)) is None
    assert isinstance(build_auth_admin(Settings(_env_file=None, supabase_url=BASE, supabase_secret_key=FAKE_SECRET)),
                      SupabaseAuthAdmin)


# --------------------------------------------------------------------------- 2. DELETE /me
def test_delete_me_removes_auth_user_and_same_token_cannot_recreate_account():
    users = {UID}
    server = FakeAuthServer(users)
    c, repo = _env(server, users)
    _onboard(c)
    r = c.delete("/me", headers=_h())
    assert r.status_code == 204 and r.headers["cache-control"] == "no-store"
    assert repo.user_count() == 0 and users == set() and len(server.requests) == 1
    # 같은 토큰(만료 전)으로 다시 불러도 빈 계정이 생기지 않는다: auth.users FK → NO_ACCOUNT → 401
    r = c.get("/me", headers=_h())
    assert (r.status_code, r.json()) == (401, {"code": "AUTH_INVALID", "fields": []})
    assert repo.user_count() == 0
    assert c.delete("/me", headers=_h()).status_code == 204  # 재요청 멱등(Admin 404 → 성공)
    assert len(server.requests) == 2


def test_auth_delete_failure_is_502_after_app_data_is_erased_then_retry_completes(caplog):
    caplog.set_level(logging.DEBUG)
    users = {UID}
    server = FakeAuthServer(users, status=503)
    c, repo = _env(server, users)
    _onboard(c)
    r = c.delete("/me", headers=_h())
    assert (r.status_code, r.json()) == (502, {"code": "AUTH_DELETE_FAILED", "fields": []})
    assert r.headers["cache-control"] == "no-store"
    assert repo.user_count() == 0 and sum(row.accounts for row in repo.deletion_log.values()) == 1  # 앱 데이터는 먼저 지워짐
    assert users == {UID}  # 로그인 계정은 남음(7.1절 4단계: 다시 로그인하면 빈 계정)
    assert "로그인 계정 삭제 실패: status 503" in caplog.text
    server.status = None  # Auth 서버 복구 → 재요청이 이어서 지운다
    assert c.delete("/me", headers=_h()).status_code == 204
    assert users == set() and sum(row.accounts for row in repo.deletion_log.values()) == 1
    assert c.get("/me", headers=_h()).status_code == 401


def test_connection_error_is_502():
    users = {UID}
    c, repo = _env(FakeAuthServer(users, error=httpx.ConnectError("down")), users)
    _onboard(c)
    assert c.delete("/me", headers=_h()).json() == {"code": "AUTH_DELETE_FAILED", "fields": []}
    assert repo.user_count() == 0


def test_admin_not_configured_is_502_not_silent_success(caplog):
    caplog.set_level(logging.DEBUG)
    users = {UID}
    c, repo = _env(None, users)
    _onboard(c)
    r = c.delete("/me", headers=_h())
    assert (r.status_code, r.json()["code"]) == (502, "AUTH_DELETE_FAILED")
    assert repo.user_count() == 0 and users == {UID}
    assert "Auth 관리 클라이언트 미설정" in caplog.text


def test_guest_delete_me_is_401_and_calls_nothing():
    users = {UID}
    server = FakeAuthServer(users)
    c, _ = _env(server, users)
    assert c.delete("/me").status_code == 401
    assert server.requests == [] and users == {UID}


# --------------------------------------------------------------------------- 3. 비밀값 비노출(sec-guard)
def test_secret_token_and_user_id_not_in_logs_or_bodies(caplog, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", FAKE_SECRET)  # 비밀값 가드(redact)가 이 이름의 값을 가리는지도 함께 본다
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []
    for status in (500, 401, None):
        users = {UID}
        c, _ = _env(FakeAuthServer(users, status=status), users)
        _onboard(c)
        bodies.append(c.delete("/me", headers=_h()).text)  # 탈퇴 응답(오류 본문)만 본다. 성공한 GET /me는 본인 user_id를 싣는다
    users = {UID}
    c, _ = _env(FakeAuthServer(users, error=httpx.ConnectError(f"refused {FAKE_SECRET}")), users)
    _onboard(c)
    bodies.append(c.delete("/me", headers=_h()).text)
    text = caplog.text + "\n".join(bodies)
    for secret in (FAKE_SECRET, FAKE_SECRET[:8], FAKE_SECRET[-8:], UID, MED_SECRET, *TOK.split(".")):
        assert secret not in text
    assert FAKE_SECRET not in redact(f"Authorization: Bearer {FAKE_SECRET}")  # 기존 가드도 이 변수를 가린다


# --------------------------------------------------------------------------- 4. lifespan 연결
def test_lifespan_attaches_admin_only_with_url_and_secret(monkeypatch):
    from app import main

    try:
        monkeypatch.setattr(main, "load_settings",
                            lambda: Settings(_env_file=None, supabase_url=BASE, supabase_secret_key=FAKE_SECRET))
        with TestClient(main.app):  # 접속 0(클라이언트만 만든다)
            assert isinstance(auth_admin.get_auth_admin(main.app), SupabaseAuthAdmin)
        monkeypatch.setattr(main, "load_settings", lambda: Settings(_env_file=None))
        with TestClient(main.app):
            assert auth_admin.get_auth_admin(main.app) is None
    finally:  # 다른 시험에 새지 않게 뗀다
        auth_admin.set_auth_admin(main.app, None)
        auth.set_verifier(main.app, None)
        account_api.set_item_seq_checker(main.app, None)
