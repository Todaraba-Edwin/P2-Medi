"""BE-11 S1 인증 골격: 요청 주체(`Principal`)와 토큰 검증기(2026-11-18, RFP-30-08 A·PRD-01-09 A′).

- `get_principal`(FastAPI 의존성): `Authorization` 헤더가 **없으면 게스트**, `Bearer <토큰>`이면 검증기로 검증한다.
  헤더가 있는데 형식이 틀리거나 검증에 실패하거나 만료됐으면 게스트로 떨어뜨리지 않고 401 `AUTH_INVALID`다
  (`P2-doc/PJ2-계정-프로필-데이터.md` 9.1절). `require_user`는 게스트를 401 `AUTH_REQUIRED`로 막는다(`GET /me` 등 계정 API).
- `/chat`은 이 의존성을 쓰지 않는다(응급 상황 게스트 원칙 CLAUDE.md 1장, 같은 문서 11장 "토큰이 붙어 와도 읽지 않는다").
- 검증은 `TokenVerifier` 프로토콜 뒤에 둔다(PyJWT는 BE-11-17 A로 2026-11-18 승인).
  - (a) 기본: `JwksTokenVerifier`는 PyJWT `PyJWKClient`로 `SUPABASE_JWKS_URL`의 공개 키(`kid`)를 골라 `ES256`·`RS256`만,
    `aud="authenticated"`, `iss={SUPABASE_URL}/auth/v1`, `exp`를 로컬에서 검증한다. JWKS는 10분 이하로 캐시한다.
    키 목록을 가져오지 못하면(연결 오류·이상한 JWKS) 503 `AUTH_UNAVAILABLE`(BE-11-20 A), 모르는 `kid`·서명 불일치는 401.
  - (b) 대안: `SupabaseUserEndpointVerifier`는 이미 있는 `httpx`로 `{SUPABASE_URL}/auth/v1/user`를 불러 Supabase가 검증하게 한다.
    `SUPABASE_JWKS_URL`이 없을 때만 `build_verifier`가 고른다. 시험은 `httpx.MockTransport`만 쓴다.
- **토큰·클레임·응답 본문을 로그·예외 메시지·응답 본문에 남기지 않는다**(sec-guard, `app.security.redact`). 이 모듈은 토큰을 로그에 쓰지 않고,
  예외 메시지는 고정 문구만 담는다. 검증기 연결 실패 경고에도 예외 종류 이름만 쓴다.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, runtime_checkable

import httpx
import jwt
from fastapi import Depends, Request

from app.config import Settings, reveal

logger = logging.getLogger(__name__)

VERIFIER_STATE_KEY = "token_verifier"  # `app.state`의 검증기 자리. 없으면 토큰이 온 요청은 501(설정 전, `/chat`의 실행기 미주입과 같은 규칙)

CODE_AUTH_REQUIRED = "AUTH_REQUIRED"  # 401: 로그인이 필요한 API에 토큰 없음
CODE_AUTH_INVALID = "AUTH_INVALID"  # 401: 헤더 형식 오류·서명·만료 등 검증 실패
CODE_AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"  # 503: 검증 서버에 닿지 못함(사용자 잘못이 아니므로 401로 로그아웃시키지 않는다)
CODE_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # 501: 검증기 미설정

MAX_TOKEN_LEN = 8192  # 비정상적으로 긴 헤더는 검증 서버로 보내지 않고 거부한다
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")  # JWS compact(base64url 세 조각)
_BEARER_RE = re.compile(r"Bearer +(\S+)", re.IGNORECASE)


# --------------------------------------------------------------------------- 주체
@dataclass(frozen=True, slots=True)
class Principal:
    """요청 주체. 게스트는 `user_id=None, is_guest=True`, 로그인 사용자는 Supabase `sub`(UUID 문자열)."""

    user_id: str | None
    is_guest: bool

    def __post_init__(self) -> None:
        if self.is_guest != (self.user_id is None):
            raise ValueError("Principal: 게스트는 user_id가 없고 로그인 사용자는 user_id가 있어야 한다")

    @classmethod
    def guest(cls) -> Principal:
        return cls(user_id=None, is_guest=True)

    @classmethod
    def user(cls, user_id: str) -> Principal:
        return cls(user_id=user_id, is_guest=False)


GUEST = Principal.guest()


# --------------------------------------------------------------------------- 오류
class AuthError(Exception):
    """API 계층이 `ErrorBody{code}`로 바꾸는 인증 오류. 메시지에 토큰·클레임을 담지 않는다(코드만)."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class TokenInvalid(Exception):  # noqa: N818 - 도메인 이름(검증 실패)
    """토큰이 유효하지 않다(형식·서명·대상·발급자). 메시지는 고정 문구만."""


class TokenExpired(TokenInvalid):
    """토큰 만료(`exp`가 지났다)."""


class VerifierUnavailable(Exception):  # noqa: N818 - 도메인 이름(검증 서버 장애)
    """검증 서버에 닿지 못했거나 예상 밖 응답(5xx 등). 토큰 잘못이 아니다.

    진단용으로 안쪽 원인의 종류 이름(`cause`)·소요 시간(`elapsed_s`)을 속성으로 싣는다(토큰·URL·헤더·본문은 싣지 않는다).
    """

    def __init__(self, kind: str, *, cause: str = "-", elapsed_s: float | None = None) -> None:
        super().__init__(kind)
        self.cause = cause
        self.elapsed_s = elapsed_s

    def diagnostics(self) -> str:
        """로그용 한 조각: `원인=TimeoutError 4.9s`·`원인=status 503 0.3s`."""
        return f"원인={self.cause}" + ("" if self.elapsed_s is None else f" {self.elapsed_s:.1f}s")


VERIFY_TIMEOUT_S = 10.0  # 검증 서버(JWKS·/auth/v1/user) 조회 제한. 공개 키 조회가 1.5~2.4초, 풀러 지연이 큰 날이 있어 5→10초(2026-11-22)


def _inner_cause(exc: BaseException) -> str:
    """안쪽 원인의 종류 이름만(메시지는 읽지 않는다). `URLError`는 `reason`이 예외면 그 종류, 없으면 `-`."""
    inner = exc.__cause__ or exc.__context__
    reason = getattr(inner, "reason", None)
    if isinstance(reason, BaseException):
        inner = reason
    return type(inner).__name__ if inner is not None else "-"


# --------------------------------------------------------------------------- 검증기
@runtime_checkable
class TokenVerifier(Protocol):
    """토큰을 검증해 사용자 ID(Supabase `sub`, UUID 문자열)를 돌려준다.

    실패하면 `TokenInvalid`(만료는 `TokenExpired`), 검증 서버 장애면 `VerifierUnavailable`을 던진다. 토큰을 로그에 쓰지 않는다.
    """

    async def verify(self, token: str) -> str: ...


def unverified_exp(token: str) -> int | None:
    """서명을 확인하지 **않고** payload의 `exp`만 읽는다. 만료 토큰을 네트워크 없이 먼저 거르는 용도로만 쓴다(수락 근거로 쓰지 않음).

    payload를 읽지 못하면 `TokenInvalid`, `exp`가 없거나 정수가 아니면 None.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalid("malformed")
    seg = parts[1]
    try:
        raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise TokenInvalid("malformed") from None  # 원 예외 메시지에 토큰 조각이 들 수 있어 체인을 끊는다
    if not isinstance(payload, dict):
        raise TokenInvalid("malformed")
    exp = payload.get("exp")
    return exp if isinstance(exp, int) and not isinstance(exp, bool) else None


def _valid_user_id(value: Any) -> str:
    if not isinstance(value, str):
        raise TokenInvalid("no subject")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise TokenInvalid("bad subject") from None


class SupabaseUserEndpointVerifier:
    """(b) 새 의존성 없는 검증: `GET {SUPABASE_URL}/auth/v1/user`(헤더 `Authorization: Bearer`, `apikey: publishable`).

    - 먼저 서명 없이 읽은 `exp`로 만료를 거른다(네트워크 0). 수락 여부는 Supabase 응답(200 + `id`)으로만 정한다.
    - 401·403 → `TokenInvalid`, 그 밖의 상태·연결 오류·시간 초과·이상한 본문 → `VerifierUnavailable`.
    - 응답 본문(이메일 등)은 `id` 말고 읽지 않고 남기지 않는다. 클라이언트를 주면 그것을 쓰고(시험: `MockTransport`), 없으면 호출마다 만든다.
    """

    def __init__(self, supabase_url: str, publishable_key: str, *, client: httpx.AsyncClient | None = None,
                 timeout_s: float = VERIFY_TIMEOUT_S, clock: Callable[[], float] = time.time, leeway_s: int = 0) -> None:
        base = supabase_url.rstrip("/")
        if not base.startswith("https://") and not base.startswith("http://"):
            raise ValueError("supabase_url은 http(s) 주소여야 한다")
        self._url = f"{base}/auth/v1/user"
        self._key = publishable_key
        self._client = client
        self._timeout = timeout_s
        self._clock = clock
        self._leeway = leeway_s

    def __repr__(self) -> str:  # 키를 repr에 싣지 않는다
        return f"{type(self).__name__}(url=<set>, key=<set>)"

    async def verify(self, token: str) -> str:
        exp = unverified_exp(token)
        if exp is not None and exp + self._leeway <= self._clock():
            raise TokenExpired("expired")
        headers = {"Authorization": f"Bearer {token}", "apikey": self._key, "Accept": "application/json"}
        t0 = time.monotonic()
        try:
            if self._client is not None:
                resp = await self._client.get(self._url, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(self._url, headers=headers)
        except httpx.HTTPError as exc:
            raise VerifierUnavailable(type(exc).__name__, cause=_inner_cause(exc), elapsed_s=time.monotonic() - t0) from None  # 요청 객체(헤더 포함)를 예외 체인에 남기지 않는다
        if resp.status_code in (401, 403):
            raise TokenInvalid("rejected")
        if resp.status_code != 200:
            raise VerifierUnavailable(f"status {resp.status_code}", cause=f"status {resp.status_code}", elapsed_s=time.monotonic() - t0)
        try:
            body = resp.json()
        except ValueError:
            raise VerifierUnavailable("bad body") from None
        if not isinstance(body, dict):
            raise VerifierUnavailable("bad body")
        return _valid_user_id(body.get("id"))


JWT_ALGORITHMS = ("ES256", "RS256")  # 비대칭만. HS256(공유 비밀)·none은 받지 않는다
JWT_AUDIENCE = "authenticated"
JWKS_CACHE_MAX_S = 600.0  # JWKS 캐시 상한 10분(설계 9.1절, Supabase 엣지 캐시와 같음)


def _http_base(url: str, name: str) -> str:
    base = url.rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://"):
        raise ValueError(f"{name}은 http(s) 주소여야 한다")
    return base


class JwksTokenVerifier:
    """(a) PyJWT 로컬 검증: `SUPABASE_JWKS_URL`의 공개 키로 서명·`aud`·`iss`·`exp`·`sub`를 확인한다.

    - 헤더의 `alg`가 `ES256`·`RS256`이 아니거나 `kid`가 없으면 키 조회 전에 `TokenInvalid`(네트워크 0).
    - 키 목록 조회 실패(연결 오류·시간 초과·JSON 아님·서명 키 없음) → `VerifierUnavailable`(→ 503 `AUTH_UNAVAILABLE`).
      목록은 받았는데 `kid`가 없으면(한 번 새로 받은 뒤에도) 위조로 보고 `TokenInvalid`.
    - JWKS는 `PyJWKClient`가 `cache_s`(≤10분) 동안 캐시한다. `PyJWKClient`는 동기(urllib)라 스레드에서 돌린다.
    - 시험은 `jwks_client`에 `fetch_data`를 덮은 `PyJWKClient`를 넣는다(네트워크 0). 예외 메시지·로그에 토큰·클레임을 싣지 않는다.
    """

    def __init__(self, jwks_url: str, issuer: str, *, audience: str = JWT_AUDIENCE, cache_s: float = JWKS_CACHE_MAX_S,
                 timeout_s: float = VERIFY_TIMEOUT_S, leeway_s: int = 0, jwks_client: jwt.PyJWKClient | None = None) -> None:
        if not 0 < cache_s <= JWKS_CACHE_MAX_S:
            raise ValueError("cache_s는 0 초과 600초 이하")
        self._issuer = _http_base(issuer, "issuer")
        self._audience = audience
        self._leeway = leeway_s
        self._client = jwks_client or jwt.PyJWKClient(
            _http_base(jwks_url, "jwks_url"), cache_jwk_set=True, lifespan=cache_s, timeout=int(max(1, timeout_s)))

    def __repr__(self) -> str:  # 주소를 repr에 싣지 않는다
        return f"{type(self).__name__}(jwks=<set>, iss=<set>)"

    async def verify(self, token: str) -> str:
        return await asyncio.to_thread(self._verify_sync, token)

    def _signing_key(self, kid: str) -> Any:
        t0 = time.monotonic()
        try:
            self._client.get_signing_keys()  # 캐시 적중이면 네트워크 0. 목록 자체를 못 얻으면 검증 서버 장애다
        except (jwt.PyJWKClientError, jwt.PyJWKSetError, jwt.PyJWKError) as exc:
            raise VerifierUnavailable(type(exc).__name__, cause=_inner_cause(exc), elapsed_s=time.monotonic() - t0) from None
        try:
            return self._client.get_signing_key(kid)
        except jwt.PyJWKClientConnectionError as exc:  # 모르는 kid로 다시 받으려다 연결 실패
            raise VerifierUnavailable(type(exc).__name__, cause=_inner_cause(exc), elapsed_s=time.monotonic() - t0) from None
        except (jwt.PyJWKClientError, jwt.PyJWKSetError, jwt.PyJWKError):
            raise TokenInvalid("unknown key") from None

    def _verify_sync(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenInvalid("malformed") from None
        kid = header.get("kid")
        if header.get("alg") not in JWT_ALGORITHMS or not isinstance(kid, str) or not kid:
            raise TokenInvalid("bad header")
        key = self._signing_key(kid)
        try:
            claims = jwt.decode(
                token, key=key, algorithms=list(JWT_ALGORITHMS), audience=self._audience, issuer=self._issuer,
                leeway=self._leeway, options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpired("expired") from None
        except jwt.PyJWTError:  # 서명·aud·iss·필수 클레임·키와 알고리즘 불일치
            raise TokenInvalid("rejected") from None
        return _valid_user_id(claims.get("sub"))


def build_verifier(settings: Settings) -> TokenVerifier | None:
    """앱 시작 때 붙일 검증기. 접속하지 않는다(JWKS는 첫 토큰 검증 때 받는다). 설정이 없으면 None(→ 토큰이 온 요청은 501).

    1. `SUPABASE_JWKS_URL`·`SUPABASE_URL`이 있으면 (a) `JwksTokenVerifier`(BE-11-17 A, 기본).
    2. 아니면 `SUPABASE_URL`·`SUPABASE_PUBLISHABLE_KEY`로 (b) `SupabaseUserEndpointVerifier`(대안).
    새 환경변수는 없다. 형식 오류는 값 없이 경고만 남긴다.
    """
    url = settings.supabase_url
    if not url:
        return None
    if settings.supabase_jwks_url:
        try:
            return JwksTokenVerifier(settings.supabase_jwks_url, f"{url.rstrip('/')}/auth/v1")
        except ValueError:
            logger.warning("JWKS 검증기를 만들지 않았다: SUPABASE_JWKS_URL·SUPABASE_URL 형식 오류")  # 값은 남기지 않는다
            return None
    key = reveal(settings.supabase_publishable_key)
    if not key:
        return None
    try:
        return SupabaseUserEndpointVerifier(url, key)
    except ValueError:
        logger.warning("인증 검증기를 만들지 않았다: SUPABASE_URL 형식 오류")  # 값은 남기지 않는다
        return None


# --------------------------------------------------------------------------- FastAPI 의존성
def _bearer_token(header: str) -> str:
    m = _BEARER_RE.fullmatch(header.strip())
    if m is None:
        raise AuthError(401, CODE_AUTH_INVALID)
    token = m.group(1)
    if len(token) > MAX_TOKEN_LEN or _TOKEN_RE.fullmatch(token) is None:
        raise AuthError(401, CODE_AUTH_INVALID)
    return token


async def get_principal(request: Request) -> Principal:
    """`Authorization` 없음 → 게스트. `Bearer` 있음 → 검증(실패·만료 401 `AUTH_INVALID`, 검증 서버 장애 503, 검증기 없음 501)."""
    header = request.headers.get("authorization")
    if header is None:
        return GUEST
    token = _bearer_token(header)
    verifier: TokenVerifier | None = getattr(request.app.state, VERIFIER_STATE_KEY, None)
    if verifier is None:
        raise AuthError(501, CODE_NOT_IMPLEMENTED)
    try:
        user_id = await verifier.verify(token)
    except TokenInvalid:  # TokenExpired 포함. 만료와 위조를 응답에서 구분하지 않는다
        raise AuthError(401, CODE_AUTH_INVALID) from None
    except VerifierUnavailable as exc:
        logger.warning("인증 검증 서버 응답 없음: %s (%s)", type(exc).__name__, exc.diagnostics())  # 종류·원인 종류·초만. 토큰·URL·응답 본문은 남기지 않는다
        raise AuthError(503, CODE_AUTH_UNAVAILABLE) from None
    return Principal.user(_valid_user_id_or_401(user_id))


def _valid_user_id_or_401(user_id: Any) -> str:
    try:
        return _valid_user_id(user_id)
    except TokenInvalid:
        raise AuthError(401, CODE_AUTH_INVALID) from None


async def require_user(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    """로그인 필수 API용. 게스트면 401 `AUTH_REQUIRED`."""
    if principal.is_guest:
        raise AuthError(401, CODE_AUTH_REQUIRED)
    return principal


def set_verifier(app: Any, verifier: TokenVerifier | None) -> None:
    """검증기를 `app.state`에 붙인다(None이면 뗀다 → 토큰이 온 요청 501)."""
    setattr(app.state, VERIFIER_STATE_KEY, verifier)


__all__ = [
    "GUEST", "AuthError", "JwksTokenVerifier", "Principal", "SupabaseUserEndpointVerifier", "TokenExpired", "TokenInvalid", "TokenVerifier",
    "VerifierUnavailable", "build_verifier", "get_principal", "require_user", "set_verifier", "unverified_exp",
]
