"""BE-11 S1 `JwksTokenVerifier` 시험(BE-11-17 A PyJWT, 2026-11-18). 네트워크·원격·LLM 호출 0.

- 키쌍은 시험 안에서 만든다(EC P-256·RSA 2048, 실제 키 아님). JWKS는 `fetch_data`를 덮은 `PyJWKClient`가 돌려준다.
- 검증 규칙: ES256·RS256만, `aud="authenticated"`, `iss={SUPABASE_URL}/auth/v1`, `exp`·`sub` 필수, JWKS 캐시 ≤10분,
  키 목록 조회 실패 → `VerifierUnavailable`(API 503 `AUTH_UNAVAILABLE`, BE-11-20 A), 모르는 `kid`·서명 불일치 → `TokenInvalid`(401).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.api import account as account_api
from app.api import chat as chat_api
from app.api import me as me_api
from app.config import Settings
from app.db.account_repo import InMemoryAccountRepo
from app.security import auth
from app.security.auth import JwksTokenVerifier, SupabaseUserEndpointVerifier, TokenExpired, TokenInvalid, VerifierUnavailable

SB_URL = "https://example-ref.supabase.test"
ISS = f"{SB_URL}/auth/v1"
JWKS_URL = f"{ISS}/.well-known/jwks.json"
USER_ID = "7a0d3c55-1b2e-4f6a-9c8d-0e1f2a3b4c5d"

EC_KEY = ec.generate_private_key(ec.SECP256R1())
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_EC = ec.generate_private_key(ec.SECP256R1())


def _jwk(alg: str, key: Any, kid: str) -> dict[str, Any]:
    algo = ECAlgorithm if alg == "ES256" else RSAAlgorithm
    d = algo.to_jwk(key.public_key(), as_dict=True)
    return {**d, "kid": kid, "alg": alg, "use": "sig"}


JWKS = {"keys": [_jwk("ES256", EC_KEY, "k-ec"), _jwk("RS256", RSA_KEY, "k-rsa")]}


class FakeJwksClient(jwt.PyJWKClient):
    """`fetch_data`만 덮는다(네트워크 0). `payload`가 예외면 던진다. 호출 수를 센다."""

    def __init__(self, payload: Any = None, *, lifespan: float = 600) -> None:
        super().__init__(JWKS_URL, cache_jwk_set=True, lifespan=lifespan)
        self.payload = JWKS if payload is None else payload
        self.fetches = 0

    def fetch_data(self) -> Any:
        self.fetches += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        if self.jwk_set_cache is not None and isinstance(self.payload, dict):
            self.jwk_set_cache.put(self.payload)
        return self.payload


def _claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {"sub": USER_ID, "aud": "authenticated", "iss": ISS, "exp": now + 3600, "iat": now, "role": "authenticated",
            "jti": uuid.uuid4().hex}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _token(alg: str = "ES256", kid: str = "k-ec", key: Any = None, **over: Any) -> str:
    key = key if key is not None else (EC_KEY if alg == "ES256" else RSA_KEY)
    return jwt.encode(_claims(**over), key, algorithm=alg, headers={"kid": kid})


def _verifier(client: FakeJwksClient | None = None) -> tuple[JwksTokenVerifier, FakeJwksClient]:
    c = client or FakeJwksClient()
    return JwksTokenVerifier(JWKS_URL, ISS, jwks_client=c), c


# --------------------------------------------------------------------------- 수락
@pytest.mark.parametrize(("alg", "kid"), [("ES256", "k-ec"), ("RS256", "k-rsa")])
async def test_valid_token_returns_normalized_user_id(alg, kid):
    v, c = _verifier()
    assert await v.verify(_token(alg, kid, sub=USER_ID.upper())) == USER_ID
    assert c.fetches == 1


async def test_jwks_is_cached_between_calls():
    v, c = _verifier()
    for _ in range(3):
        assert await v.verify(_token()) == USER_ID
    assert c.fetches == 1


def test_default_client_caches_at_most_ten_minutes_and_rejects_longer():
    v = JwksTokenVerifier(JWKS_URL, ISS)
    assert v._client.jwk_set_cache is not None and v._client.jwk_set_cache.lifespan <= 600
    with pytest.raises(ValueError):
        JwksTokenVerifier(JWKS_URL, ISS, cache_s=601)
    with pytest.raises(ValueError):
        JwksTokenVerifier("ftp://x", ISS)
    assert JWKS_URL not in repr(v) and ISS not in repr(v)


# --------------------------------------------------------------------------- 거부(401)
async def test_expired_is_token_expired():
    v, _ = _verifier()
    with pytest.raises(TokenExpired):
        await v.verify(_token(exp=int(time.time()) - 30))


@pytest.mark.parametrize("over", [
    {"aud": "anon"}, {"iss": "https://evil.supabase.test/auth/v1"}, {"sub": None}, {"sub": "not-a-uuid"}, {"exp": None},
    {"aud": None}, {"iss": None},
])
async def test_wrong_or_missing_claims_are_invalid(over):
    v, _ = _verifier()
    with pytest.raises(TokenInvalid) as info:
        await v.verify(_token(**over))
    assert not isinstance(info.value, TokenExpired)


async def test_signature_from_other_key_with_known_kid_is_invalid():
    v, _ = _verifier()
    with pytest.raises(TokenInvalid):
        await v.verify(_token("ES256", "k-ec", key=OTHER_EC))


async def test_unknown_kid_is_invalid_after_one_refresh():
    v, c = _verifier()
    with pytest.raises(TokenInvalid):
        await v.verify(_token("ES256", "k-unknown", key=OTHER_EC))
    assert c.fetches == 2  # 처음 + 키 교체 대비 한 번 다시 받기


async def test_alg_kid_mismatch_is_invalid():
    """RS256 헤더에 EC 키의 kid → 키와 알고리즘이 맞지 않아 거부."""
    v, _ = _verifier()
    token = jwt.encode(_claims(), RSA_KEY, algorithm="RS256", headers={"kid": "k-ec"})
    with pytest.raises(TokenInvalid):
        await v.verify(token)


@pytest.mark.parametrize("token_fn", [
    lambda: jwt.encode(_claims(), "shared-secret-for-test-only-32bytes!!", algorithm="HS256", headers={"kid": "k-ec"}),
    lambda: jwt.encode(_claims(), None, algorithm="none", headers={"kid": "k-ec"}),
    lambda: jwt.encode(_claims(), EC_KEY, algorithm="ES256"),  # kid 없음
    lambda: "not.a.jwt",
    lambda: "a.b",
])
async def test_disallowed_alg_missing_kid_or_garbage_rejected_without_fetch(token_fn):
    v, c = _verifier()
    with pytest.raises(TokenInvalid):
        await v.verify(token_fn())
    assert c.fetches == 0  # 키 조회 전에 거른다


# --------------------------------------------------------------------------- 검증 서버 장애(503)
@pytest.mark.parametrize("payload", [
    jwt.PyJWKClientConnectionError("Fail to fetch data from the url, err: timed out"),
    [1, 2, 3],
    {"keys": []},
    {"nokeys": True},
])
async def test_jwks_unavailable_or_broken_is_verifier_unavailable(payload):
    v, _ = _verifier(FakeJwksClient(payload))
    with pytest.raises(VerifierUnavailable) as info:
        await v.verify(_token())
    assert info.value.__cause__ is None and info.value.__suppress_context__


# --------------------------------------------------------------------------- API 연결
def _app(verifier: Any) -> FastAPI:
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    auth.set_verifier(app, verifier)
    account_api.set_repo(app, InMemoryAccountRepo())
    return app


def test_api_ok_401_and_503(caplog):
    caplog.set_level(logging.DEBUG)
    good = _verifier()[0]
    tokens = [_token(), _token(exp=int(time.time()) - 5), _token(aud="anon")]
    c = TestClient(_app(good))
    assert c.get("/me", headers={"Authorization": f"Bearer {tokens[0]}"}).json()["user_id"] == USER_ID
    for t in tokens[1:]:
        r = c.get("/me", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 401 and r.json() == {"code": "AUTH_INVALID", "fields": []}
    down = _verifier(FakeJwksClient(jwt.PyJWKClientConnectionError("boom")))[0]
    r = TestClient(_app(down)).get("/me", headers={"Authorization": f"Bearer {tokens[0]}"})
    assert r.status_code == 503 and r.json() == {"code": "AUTH_UNAVAILABLE", "fields": []}
    assert "www-authenticate" not in r.headers
    text = caplog.text
    for t in tokens:
        for piece in t.split("."):
            assert piece not in text


# --------------------------------------------------------------------------- build_verifier
def test_build_verifier_prefers_jwks_and_opens_no_connection(monkeypatch):
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)

    def no_net(*a: Any, **kw: Any) -> Any:
        raise AssertionError("build_verifier가 접속했다")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", no_net)
    v = auth.build_verifier(Settings(_env_file=None, supabase_url=SB_URL + "/", supabase_jwks_url=JWKS_URL,
                                     supabase_publishable_key="sb_publishable_ZZZZ"))  # guard: fake
    assert isinstance(v, JwksTokenVerifier) and isinstance(v, auth.TokenVerifier)
    assert v._issuer == ISS
    # JWKS 주소만 있고 SUPABASE_URL이 없으면 iss를 정할 수 없다 → None
    assert auth.build_verifier(Settings(_env_file=None, supabase_jwks_url=JWKS_URL)) is None
    # JWKS 주소가 없으면 대안 검증기
    alt = auth.build_verifier(Settings(_env_file=None, supabase_url=SB_URL, supabase_publishable_key="sb_publishable_ZZZZ"))
    assert isinstance(alt, SupabaseUserEndpointVerifier)
    assert auth.build_verifier(Settings(_env_file=None, supabase_url=SB_URL, supabase_jwks_url="not-a-url")) is None
