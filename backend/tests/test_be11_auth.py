"""BE-11 S1 인증 골격 시험(2026-11-18). 네트워크·원격 DB·LLM 호출 0.

- 토큰 검증은 가짜 검증기(`FakeVerifier`)와 `httpx.MockTransport`(Supabase `/auth/v1/user` 흉내)로만 한다.
- 시험 토큰은 합성 JWS 모양 문자열이다(서명 없음, 실제 키·계정 아님).
- `/chat` 회귀는 `test_be06_chat_stream`과 같은 합성 그래프(가짜 모델·합성 소사전)로 토큰 유무에 따라 결과가 같은지 본다.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app import main as main_mod  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import account as account_api  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import me as me_api  # noqa: E402
from app.api.runner import GraphRunner  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.account_repo import InMemoryAccountRepo  # noqa: E402
from app.security import auth  # noqa: E402
from app.security.auth import (  # noqa: E402
    GUEST,
    Principal,
    SupabaseUserEndpointVerifier,
    TokenExpired,
    TokenInvalid,
    VerifierUnavailable,
)

USER_ID = "3f1c2b9e-8d4a-4c11-9f0e-2a7b6c5d4e3f"
NOW = 1_800_000_000  # 고정 시각(시계 주입)
SB_URL = "https://example-ref.supabase.test"
PUB_KEY = "sb_publishable_QQQQQQQQQQQQQQQQ"  # guard: fake (합성 값, 실제 키 아님)


def _b64(obj: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _jwt(**payload: Any) -> str:
    """서명 없는 합성 JWS 모양 토큰. 식별 표지(`jti`)를 넣어 로그·본문에 새는지 찾기 쉽게 한다."""
    body = {"sub": USER_ID, "aud": "authenticated", "exp": NOW + 3600, "jti": uuid.uuid4().hex, **payload}
    return f"{_b64({'alg': 'ES256', 'kid': 'k1', 'typ': 'JWT'})}.{_b64(body)}.c2lnbmF0dXJlLXRlc3Qtb25seQ"


GOOD = _jwt()
BAD = _jwt(note="forged")
EXPIRED = _jwt(exp=NOW - 10, note="expired")
DOWN = _jwt(note="down")
NOT_UUID = _jwt(note="notuuid")


class FakeVerifier:
    """GOOD → USER_ID, EXPIRED → TokenExpired, DOWN → VerifierUnavailable, NOT_UUID → 이상한 id, 나머지 → TokenInvalid."""

    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, token: str) -> str:
        self.calls += 1
        if token == GOOD:
            return USER_ID
        if token == EXPIRED:
            raise TokenExpired("expired")
        if token == DOWN:
            raise VerifierUnavailable("ConnectError")
        if token == NOT_UUID:
            return "not-a-uuid"
        raise TokenInvalid("rejected")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app(verifier: Any = None, repo: Any = None) -> FastAPI:
    """`/me` + 주체를 그대로 돌려주는 시험용 `/whoami` + `/chat`(실행기 없음 → 501). 계정 저장소는 메모리 가짜(없으면 501)."""
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    auth.set_verifier(app, verifier)
    account_api.set_repo(app, repo)

    @app.get("/whoami")
    async def whoami(p: Annotated[Principal, Depends(auth.get_principal)]) -> dict[str, Any]:
        return {"user_id": p.user_id, "is_guest": p.is_guest}

    return app


@pytest.fixture
def fake() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def client(fake: FakeVerifier) -> TestClient:
    return TestClient(_app(fake, InMemoryAccountRepo()))


# --------------------------------------------------------------------------- 주체
def test_principal_invariant():
    assert GUEST == Principal(user_id=None, is_guest=True)
    assert Principal.user(USER_ID).is_guest is False
    with pytest.raises(ValueError):
        Principal(user_id=None, is_guest=False)
    with pytest.raises(ValueError):
        Principal(user_id=USER_ID, is_guest=True)


# --------------------------------------------------------------------------- get_principal
def test_no_header_is_guest_without_calling_verifier(client, fake):
    r = client.get("/whoami")
    assert r.status_code == 200 and r.json() == {"user_id": None, "is_guest": True}
    assert fake.calls == 0


def test_no_header_is_guest_even_without_verifier():
    r = TestClient(_app(None)).get("/whoami")
    assert r.status_code == 200 and r.json()["is_guest"] is True


def test_valid_token_gives_user_id(client, fake):
    r = client.get("/whoami", headers=_bearer(GOOD))
    assert r.status_code == 200 and r.json() == {"user_id": USER_ID, "is_guest": False}
    assert fake.calls == 1


def test_bearer_scheme_is_case_insensitive(client):
    r = client.get("/whoami", headers={"Authorization": f"bearer {GOOD}"})
    assert r.status_code == 200 and r.json()["user_id"] == USER_ID


@pytest.mark.parametrize("token", [BAD, EXPIRED, NOT_UUID])
def test_invalid_expired_or_bad_subject_is_401_not_guest(client, token):
    r = client.get("/whoami", headers=_bearer(token))
    assert r.status_code == 401
    assert r.json() == {"code": "AUTH_INVALID", "fields": []}
    assert r.headers["www-authenticate"] == "Bearer" and r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("header", [
    "Basic dXNlcjpwYXNz", "Bearer", "Bearer ", "Bearer not-a-jwt", f"Token {GOOD}", f"Bearer {GOOD} extra",
    "Bearer " + "a" * 5000 + "." + "b" * 5000 + ".c", "",
])
def test_malformed_header_is_401_without_calling_verifier(client, fake, header):
    r = client.get("/whoami", headers={"Authorization": header})
    assert r.status_code == 401 and r.json()["code"] == "AUTH_INVALID"
    assert fake.calls == 0


def test_token_without_verifier_is_501():
    r = TestClient(_app(None)).get("/whoami", headers=_bearer(GOOD))
    assert r.status_code == 501 and r.json() == {"code": "NOT_IMPLEMENTED", "fields": []}


def test_verifier_unavailable_is_503_not_401(client):
    r = client.get("/whoami", headers=_bearer(DOWN))
    assert r.status_code == 503 and r.json()["code"] == "AUTH_UNAVAILABLE"
    assert "www-authenticate" not in r.headers


# --------------------------------------------------------------------------- GET /me
def test_me_guest_is_401_auth_required(client, fake):
    r = client.get("/me")
    assert r.status_code == 401 and r.json() == {"code": "AUTH_REQUIRED", "fields": []}
    assert r.headers["www-authenticate"] == "Bearer" and fake.calls == 0


def test_me_with_valid_token(client):
    r = client.get("/me", headers=_bearer(GOOD))
    assert r.status_code == 200 and r.json() == {
        "user_id": USER_ID, "is_guest": False, "onboarding_step": "consent", "onboarding_completed_at": None,
        "consents": [], "health_consent_active": False, "profile_limit": 4,
    }  # 약관 문서가 없는 빈 저장소: 동의 상태 목록이 비고 첫 단계(BE-11-10 A로 계정 행 생성)
    assert r.headers["cache-control"] == "no-store"


def test_me_with_token_but_no_account_repo_is_501_and_guest_still_401():
    app = _app(FakeVerifier(), None)
    c = TestClient(app)
    assert c.get("/me", headers=_bearer(GOOD)).json() == {"code": "NOT_IMPLEMENTED", "fields": []}
    assert c.get("/me").status_code == 401  # 인증 검사가 저장소 검사보다 먼저


@pytest.mark.parametrize("token", [BAD, EXPIRED])
def test_me_invalid_or_expired_is_401(client, token):
    r = client.get("/me", headers=_bearer(token))
    assert r.status_code == 401 and r.json()["code"] == "AUTH_INVALID"


def test_me_in_openapi_with_error_bodies():
    paths = TestClient(_app(None)).get("/openapi.json").json()["paths"]
    responses = paths["/me"]["get"]["responses"]
    assert {"200", "401", "501", "503"} <= set(responses)
    assert {"get", "delete"} <= set(paths["/me"])
    assert "/legal/{doc_type}" in paths and "get" in paths["/legal/{doc_type}"]  # BE-11-06 A 뒤 계정 API(2026-11-18)
    for name in ("401", "501", "503"):
        assert responses[name]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorBody")


def test_main_app_registers_me(monkeypatch):
    fake = FakeVerifier()
    monkeypatch.setattr(main_mod.app.state, auth.VERIFIER_STATE_KEY, fake, raising=False)
    monkeypatch.setattr(main_mod.app.state, account_api.REPO_STATE_KEY, InMemoryAccountRepo(), raising=False)
    c = TestClient(main_mod.app)  # lifespan 없이(설정 읽기·접속 0)
    assert c.get("/me").status_code == 401
    body = c.get("/me", headers=_bearer(GOOD)).json()
    assert (body["user_id"], body["is_guest"], body["onboarding_step"]) == (USER_ID, False, "consent")


# --------------------------------------------------------------------------- /chat: 게스트 허용, 토큰을 읽지 않음
def test_chat_ignores_authorization_without_runner(client, fake):
    """실행기가 없을 때 /chat은 토큰 유무·유효성과 상관없이 같은 501이다(401로 바뀌지 않는다)."""
    q = {"question": "타이레놀 먹어도 돼요?"}
    expected = client.post("/chat", json=q)
    for headers in ({}, _bearer(GOOD), _bearer(BAD), {"Authorization": "Basic zzz"}):
        r = client.post("/chat", json=q, headers=headers)
        assert (r.status_code, r.json()) == (expected.status_code, expected.json()) == (501, {"code": "NOT_IMPLEMENTED", "fields": []})
    assert fake.calls == 0


AZI, COLD = "이지렉트정1.0밀리그램", "타이레놀콜드-에스정"
PAIR_EID = "contra_pair:254000ATB:625201ATB"


def _runner() -> GraphRunner:
    dd = golden_dict()
    script = [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]
    draft = {"sentences": [
        {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
        {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
    ]}
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([draft]),
                      system_prompt="시험용 시스템 프롬프트")
    return GraphRunner.from_deps(deps)


def _chat_events(headers: dict[str, str]) -> tuple[int, list[dict[str, Any]]]:
    fake = FakeVerifier()
    app = _app(fake)
    chat_api.set_runner(app, _runner(), metrics=None)
    r = TestClient(app).post("/chat", json={"question": f"엄마가 {AZI}을 드시는데 {COLD}을 같이 먹어도 되나요?"}, headers=headers)
    assert fake.calls == 0  # /chat은 검증기를 부르지 않는다
    rows = [ev.ChatEvent.model_validate_json(x).root.model_dump() for x in r.content.split(b"\n") if x]
    return r.status_code, rows


def test_chat_stream_same_with_or_without_token():
    base_status, base = _chat_events({})
    assert base_status == 200 and base[-1]["type"] == "done" and base[-1]["end_reason"] == "NORMAL"
    for headers in (_bearer(GOOD), _bearer(BAD), _bearer(EXPIRED)):
        status, rows = _chat_events(headers)
        assert status == 200 and rows == base


# --------------------------------------------------------------------------- 로그·본문에 토큰 없음
def test_tokens_never_in_logs_or_bodies(client, caplog):
    caplog.set_level(logging.DEBUG)  # 모든 로거(httpx·fastapi·app) 수집
    bodies: list[str] = []
    for token in (GOOD, BAD, EXPIRED, DOWN, NOT_UUID):
        for path in ("/me", "/whoami"):
            bodies.append(client.get(path, headers=_bearer(token)).text)
    bodies.append(client.post("/chat", json={"question": "타이레놀"}, headers=_bearer(GOOD)).text)
    text = caplog.text + "\n".join(bodies)
    for token in (GOOD, BAD, EXPIRED, DOWN, NOT_UUID):
        for piece in token.split("."):
            assert piece not in text
    assert any("인증 검증 서버 응답 없음: VerifierUnavailable" in r.getMessage() for r in caplog.records)  # 종류 이름만


# --------------------------------------------------------------------------- unverified_exp
def test_unverified_exp():
    assert auth.unverified_exp(GOOD) == NOW + 3600
    assert auth.unverified_exp(f"{_b64({})}.{_b64({'sub': 'x'})}.") is None
    assert auth.unverified_exp(f"{_b64({})}.{_b64({'exp': True})}.") is None
    for broken in ("a.b", "a.%%%.c", f"{_b64({})}.{_b64([1, 2])}.c", "a.bm90LWpzb24.c"):
        with pytest.raises(TokenInvalid):
            auth.unverified_exp(broken)


# --------------------------------------------------------------------------- httpx 검증기(MockTransport)
class Recorder:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def _verifier(handler: Any, **kw: Any) -> tuple[SupabaseUserEndpointVerifier, Recorder]:
    rec = Recorder(handler)
    client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
    return SupabaseUserEndpointVerifier(SB_URL + "/", PUB_KEY, client=client, clock=lambda: NOW, **kw), rec


async def test_httpx_verifier_ok_sends_expected_request():
    v, rec = _verifier(lambda req: httpx.Response(200, json={"id": USER_ID.upper(), "email": "x@example.test", "aud": "authenticated"}))
    assert await v.verify(GOOD) == USER_ID  # UUID 정규화(소문자)
    (req,) = rec.requests
    assert req.method == "GET" and str(req.url) == f"{SB_URL}/auth/v1/user"
    assert req.headers["authorization"] == f"Bearer {GOOD}" and req.headers["apikey"] == PUB_KEY


@pytest.mark.parametrize("status", [401, 403])
async def test_httpx_verifier_rejected(status):
    v, _ = _verifier(lambda req: httpx.Response(status, json={"code": status, "error_code": "bad_jwt"}))
    with pytest.raises(TokenInvalid):
        await v.verify(BAD)


async def test_httpx_verifier_expired_short_circuits_without_network():
    v, rec = _verifier(lambda req: httpx.Response(200, json={"id": USER_ID}))
    with pytest.raises(TokenExpired):
        await v.verify(EXPIRED)
    assert rec.requests == []


async def test_httpx_verifier_leeway():
    v, _ = _verifier(lambda req: httpx.Response(200, json={"id": USER_ID}), leeway_s=30)
    assert await v.verify(EXPIRED) == USER_ID  # 10초 전 만료 + 30초 여유 → 서버 판단에 맡긴다


async def test_httpx_verifier_malformed_token_no_network():
    v, rec = _verifier(lambda req: httpx.Response(200, json={"id": USER_ID}))
    with pytest.raises(TokenInvalid):
        await v.verify("a.%%%.c")
    assert rec.requests == []


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="oops"), httpx.Response(429), httpx.Response(200, text="not json"), httpx.Response(200, json=[1]),
])
async def test_httpx_verifier_unavailable(response):
    v, _ = _verifier(lambda req: response)
    with pytest.raises(VerifierUnavailable):
        await v.verify(GOOD)


async def test_httpx_verifier_connect_error_has_no_token_in_exception():
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed for {req.headers['authorization']}", request=req)

    v, _ = _verifier(boom)
    with pytest.raises(VerifierUnavailable) as info:
        await v.verify(GOOD)
    assert str(info.value) == "ConnectError" and info.value.__cause__ is None and info.value.__suppress_context__


@pytest.mark.parametrize("body", [{"id": "not-a-uuid"}, {"id": 123}, {}])
async def test_httpx_verifier_bad_subject(body):
    v, _ = _verifier(lambda req: httpx.Response(200, json=body))
    with pytest.raises(TokenInvalid):
        await v.verify(GOOD)


def test_httpx_verifier_repr_hides_key_and_rejects_bad_url():
    v = SupabaseUserEndpointVerifier(SB_URL, PUB_KEY)
    assert PUB_KEY not in repr(v) and SB_URL not in repr(v)
    with pytest.raises(ValueError):
        SupabaseUserEndpointVerifier("ftp://x", PUB_KEY)


async def test_httpx_verifier_through_api_end_to_end():
    v, rec = _verifier(lambda req: httpx.Response(200, json={"id": USER_ID})
                       if req.headers["authorization"] == f"Bearer {GOOD}" else httpx.Response(401))
    transport = httpx.ASGITransport(app=_app(v, InMemoryAccountRepo()))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        ok = await c.get("/me", headers=_bearer(GOOD))
        bad = await c.get("/me", headers=_bearer(BAD))
    assert ok.status_code == 200 and ok.json()["user_id"] == USER_ID
    assert bad.status_code == 401 and bad.json()["code"] == "AUTH_INVALID"
    assert len(rec.requests) == 2


# --------------------------------------------------------------------------- build_verifier
def test_build_verifier_needs_url_and_publishable_key(monkeypatch):
    """JWKS 주소가 없을 때의 대안 경로((b) httpx 검증기). JWKS 기본 경로는 test_be11_jwks.py."""
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)
    assert auth.build_verifier(Settings(_env_file=None)) is None
    assert auth.build_verifier(Settings(_env_file=None, supabase_url=SB_URL)) is None
    v = auth.build_verifier(Settings(_env_file=None, supabase_url=SB_URL, supabase_publishable_key=PUB_KEY))
    assert isinstance(v, SupabaseUserEndpointVerifier) and isinstance(v, auth.TokenVerifier)
    assert auth.build_verifier(Settings(_env_file=None, supabase_url="not-a-url", supabase_publishable_key=PUB_KEY)) is None


def test_clock_default_is_time():
    v = SupabaseUserEndpointVerifier(SB_URL, PUB_KEY)
    assert v._clock is time.time
