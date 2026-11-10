"""공공 API 도구(BE-02 e약은요, BE-03 DUR 등)가 함께 쓰는 얇은 HTTP·캐시 계층.

- 요청 한 번의 규칙(타임아웃, 재시도 한도, 호출 횟수 상한)과 응답 캐시, 오프라인 스냅샷 재생, 조회 시각을 맡는다.
- 서비스별 파싱·모델은 각 도구 모듈(`eyak.py` 등)이 맡는다. 이 모듈은 응답을 `dict`로 돌려주기까지만 한다.
- 인증키는 호출 URL을 만들 때만 쓰고 로그·예외·응답 객체에 남기지 않는다(`mask_secret`).
- 캐시는 LLM 응답 캐시(`LLM_CACHE`)와 별개다. 공공 API 응답 원문만 담는다.
- `mode="snapshot"`은 평가·오프라인 시험용이다. 네트워크를 쓰지 않고 `data/mock/api_snapshots/`의 응답만 읽는다.

BE-03이 이어서 쓰는 공개 인터페이스: `ApiHttpClient(...).get(operation, params) -> ApiResponse`,
`ApiError`, `ResponseCache`, `extract_items`, `request_hash`, `format_utc`, `format_display`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote, urlencode

import httpx

# 저장소 루트의 스냅샷 폴더(로컬 전용, RFP-32). 이 파일은 backend/app/tools/ 아래에 있다.
DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parents[3] / "data" / "mock" / "api_snapshots"

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MAX_RETRIES = 2          # 재시도 횟수 상한(네트워크 오류·타임아웃·5xx만)
MAX_RETRIES_CAP = 3
DEFAULT_BACKOFF_S = 0.5
DEFAULT_MAX_CALLS = 1000          # 클라이언트 하나의 HTTP 요청 상한(재시도 포함)
DEFAULT_CACHE_TTL_S = 24 * 3600.0

KST = timezone(timedelta(hours=9))

ErrorKind = Literal[
    "config", "invalid_request", "rate_limit", "auth", "timeout", "network",
    "http", "service", "parse", "call_budget", "snapshot_miss",
]
Mode = Literal["live", "snapshot"]

_OPERATION_RE = re.compile(r"^[A-Za-z0-9_]{1,80}$")

# data.go.kr 공통 오류 코드(returnReasonCode / resultCode) 분류
_RATE_LIMIT_CODES = {"22"}
_AUTH_CODES = {"20", "30", "31", "32", "33"}


class ApiError(Exception):
    """공공 API 호출 실패. 메시지에는 인증키가 들어가지 않는다."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        http_status: int | None = None,
        result_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message
        self.http_status = http_status
        self.result_code = result_code
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "http_status": self.http_status,
            "result_code": self.result_code,
            "retryable": self.retryable,
        }


# ---------------------------------------------------------------------------------------------
# 시간·비밀·요청 키
# ---------------------------------------------------------------------------------------------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(dt: datetime) -> str:
    """UTC ISO 8601(초 단위, `Z`). 예: 2026-11-10T05:03:21Z"""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_display(dt: datetime) -> str:
    """화면 표시용 한국 시각. 예: 2026-11-10 14:03 (KST)"""
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M") + " (KST)"


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def mask_secret(text: str, secret: str | None) -> str:
    """메시지에 인증키(원문·퍼센트 인코딩)가 섞여 나오지 않게 가린다."""
    if not secret:
        return text
    return text.replace(secret, "***").replace(quote(secret, safe=""), "***")


def norm_params(params: dict[str, Any] | None) -> dict[str, str]:
    """기본값을 채우고 문자열로 맞춘다. `evaluation/mock_gen/api_snapshot.py`의 규칙과 같아야 해시가 일치한다."""
    full = {"pageNo": 1, "numOfRows": 100, "type": "json", **(params or {})}
    return {k: str(v) for k, v in sorted(full.items())}


def request_hash(service: str, operation: str, params: dict[str, Any] | None) -> str:
    """캐시 키 겸 스냅샷 파일 이름(서비스·오퍼레이션·파라미터, 인증키 제외)."""
    raw = json.dumps([service, operation, norm_params(params)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def extract_items(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    """`items`를 객체 목록으로 꺼낸다. 0건이면 `items` 키가 없다. 성분정보의 `{"item": {...}}` 한 겹도 벗긴다."""
    items = (body or {}).get("items")
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and set(it) == {"item"} and isinstance(it["item"], dict):
            it = it["item"]
        if isinstance(it, dict):
            out.append(it)
    return out


# ---------------------------------------------------------------------------------------------
# 응답 판정
# ---------------------------------------------------------------------------------------------
def _classify_code(code: str | None, message: str, http_status: int | None) -> ApiError:
    code = (code or "").strip() or None
    if code in _RATE_LIMIT_CODES:
        return ApiError("rate_limit", "호출 제한(일일 트래픽) 초과로 조회하지 못했습니다.", http_status=http_status, result_code=code)
    if code in _AUTH_CODES:
        return ApiError("auth", "서비스 인증 오류로 조회하지 못했습니다.", http_status=http_status, result_code=code)
    return ApiError("service", f"공공 API가 오류를 돌려주었습니다: {message[:120]}", http_status=http_status, result_code=code)


def parse_response(text: str, http_status: int | None = 200) -> dict[str, Any]:
    """응답 원문을 JSON `dict`로 풀고 data.go.kr 오류 형식을 `ApiError`로 바꾼다."""
    try:
        parsed = json.loads(text)
    except ValueError:
        m = re.search(r"<returnReasonCode>\s*([^<\s]+)\s*<", text) or re.search(r"<resultCode>\s*([^<\s]+)\s*<", text)
        msg = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>\s*([^<]*)<", text)
        if m or "OpenAPI_ServiceResponse" in text:
            raise _classify_code(m.group(1) if m else None, msg.group(1).strip() if msg else "오류 응답", http_status)
        raise ApiError("parse", "응답을 JSON으로 읽지 못했습니다.", http_status=http_status)
    if not isinstance(parsed, dict):
        raise ApiError("parse", "응답 형식이 예상과 다릅니다.", http_status=http_status)

    wrapper = parsed.get("OpenAPI_ServiceResponse")
    hdr = (wrapper or {}).get("cmmMsgHeader") if isinstance(wrapper, dict) else parsed.get("cmmMsgHeader")
    if isinstance(hdr, dict):
        raise _classify_code(str(hdr.get("returnReasonCode", "")), str(hdr.get("returnAuthMsg") or hdr.get("errMsg") or "오류 응답"), http_status)

    body = parsed.get("body")
    header = parsed.get("header")
    if parsed.get("response") and isinstance(parsed["response"], dict):  # 일부 서비스는 한 겹 더 싸여 있다
        header = parsed["response"].get("header", header)
        body = parsed["response"].get("body", body)
    if isinstance(header, dict):
        code = str(header.get("resultCode", "")).strip()
        if code not in ("00", "0"):
            raise _classify_code(code, str(header.get("resultMsg", "")), http_status)
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ApiError("parse", "응답에 header/body가 없습니다.", http_status=http_status)
    return {"header": header, "body": body}


# ---------------------------------------------------------------------------------------------
# 캐시
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CachedEntry:
    text: str
    fetched_at: datetime


class ResponseCache:
    """공공 API 응답 원문 캐시(키 = 요청 해시, TTL). 메모리와 선택적 파일 저장소.

    `directory`를 주면 프로세스를 다시 띄워도 남는다(파일당 한 응답, 원자적 쓰기). 오류 응답은 넣지 않는다.
    """

    def __init__(self, directory: Path | str | None = None, ttl_seconds: float = DEFAULT_CACHE_TTL_S, clock: Callable[[], float] = time.time) -> None:
        self.directory = Path(directory) if directory else None
        self.ttl = float(ttl_seconds)
        self._clock = clock
        self._mem: dict[str, tuple[float, CachedEntry]] = {}
        self._lock = threading.Lock()
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path | None:
        return self.directory / f"{key}.json" if self.directory and re.fullmatch(r"[0-9a-f]{16}", key) else None

    def get(self, key: str) -> CachedEntry | None:
        now = self._clock()
        with self._lock:
            hit = self._mem.get(key)
            if hit and now - hit[0] <= self.ttl:
                return hit[1]
            self._mem.pop(key, None)
        path = self._path(key)
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                stored, entry = float(data["stored_epoch"]), CachedEntry(str(data["text"]), parse_utc(data["fetched_at"]))
            except (ValueError, KeyError, TypeError, OSError):
                return None
            if now - stored <= self.ttl:
                with self._lock:
                    self._mem[key] = (stored, entry)
                return entry
        return None

    def put(self, key: str, text: str, fetched_at: datetime) -> None:
        now = self._clock()
        entry = CachedEntry(text, fetched_at)
        with self._lock:
            self._mem[key] = (now, entry)
        path = self._path(key)
        if path:
            payload = json.dumps({"stored_epoch": now, "fetched_at": format_utc(fetched_at), "text": text}, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, path)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def clear(self) -> None:
        with self._lock:
            self._mem.clear()
        if self.directory:
            for p in self.directory.glob("*.json"):
                p.unlink(missing_ok=True)


def cache_from_settings(settings: Any) -> ResponseCache:
    """설정(`app.config.Settings`)의 캐시 항목으로 `ResponseCache`를 만든다."""
    return ResponseCache(settings.mediagent_api_cache_dir, settings.mediagent_api_cache_ttl_seconds)


# ---------------------------------------------------------------------------------------------
# HTTP 클라이언트
# ---------------------------------------------------------------------------------------------
@dataclass
class ApiResponse:
    """성공한 응답. `parsed`는 `{"header": ..., "body": ...}`."""

    parsed: dict[str, Any]
    text: str
    source: Literal["live", "cache", "snapshot"]
    fetched_at: datetime          # 공공 API에서 이 데이터를 받은 시각(캐시·스냅샷이면 그때의 시각)
    request_hash: str

    @property
    def from_cache(self) -> bool:
        return self.source != "live"

    @property
    def body(self) -> dict[str, Any]:
        return self.parsed["body"]


@dataclass
class ApiHttpClient:
    """서비스 하나(`alias`: eyak, dur-item, …)에 대한 GET 클라이언트."""

    alias: str
    base_url: str | None
    api_key: str | None = field(default=None, repr=False)
    mode: Mode = "live"
    cache: ResponseCache | None = None
    timeout: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    max_calls: int = DEFAULT_MAX_CALLS
    backoff: float = DEFAULT_BACKOFF_S
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    http_client: httpx.Client | None = None
    sleep: Callable[[float], None] = time.sleep
    calls: int = field(default=0, init=False)          # 지금까지 나간 HTTP 요청 수(재시도 포함)

    def __post_init__(self) -> None:
        self.max_retries = max(0, min(int(self.max_retries), MAX_RETRIES_CAP))
        self._lock = threading.Lock()

    # ---- 공개 ----
    def get(self, operation: str, params: dict[str, Any] | None = None) -> ApiResponse:
        if not _OPERATION_RE.fullmatch(operation or ""):
            raise ApiError("invalid_request", "오퍼레이션 이름이 올바르지 않습니다.")
        key = request_hash(self.alias, operation, params)
        if self.mode == "snapshot":
            return self._from_snapshot(operation, key)
        if self.cache:
            hit = self.cache.get(key)
            if hit:
                try:
                    return ApiResponse(parse_response(hit.text), hit.text, "cache", hit.fetched_at, key)
                except ApiError:
                    pass  # 깨진 캐시는 무시하고 다시 받는다
        text, fetched_at = self._fetch(operation, norm_params(params))
        parsed = parse_response(text)
        if self.cache:
            self.cache.put(key, text, fetched_at)
        return ApiResponse(parsed, text, "live", fetched_at, key)

    # ---- 내부 ----
    def _from_snapshot(self, operation: str, key: str) -> ApiResponse:
        path = self.snapshot_dir / self.alias / operation / f"{key}.json"
        if not path.exists():
            raise ApiError("snapshot_miss", "저장된 응답 스냅샷에 없는 요청입니다(평가 모드에서는 실호출하지 않습니다).")
        text = path.read_text(encoding="utf-8")
        fetched = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return ApiResponse(parse_response(text), text, "snapshot", fetched, key)

    def _client(self) -> httpx.Client:
        if self.http_client is None:
            self.http_client = httpx.Client(timeout=self.timeout, follow_redirects=False)
        return self.http_client

    def _url(self, operation: str, params: dict[str, str]) -> str:
        base = (self.base_url or "").rstrip("/")
        url = base if base.endswith(operation) else f"{base}/{operation}"
        key = self.api_key or ""
        key_q = key if "%" in key else quote(key, safe="")   # 포털 키가 이미 인코딩된 형태면 그대로 쓴다
        return f"{url}?serviceKey={key_q}&{urlencode(params)}"

    def _fetch(self, operation: str, params: dict[str, str]) -> tuple[str, datetime]:
        if not self.base_url or not self.api_key:
            raise ApiError("config", f"{self.alias} 서비스의 호출 주소 또는 인증키 설정이 비어 있습니다.")
        url = self._url(operation, params)
        last: ApiError | None = None
        for attempt in range(self.max_retries + 1):
            with self._lock:
                if self.calls >= self.max_calls:
                    raise ApiError("call_budget", f"호출 횟수 상한({self.max_calls})에 도달해 더 호출하지 않습니다.")
                self.calls += 1
            try:
                resp = self._client().get(url, timeout=self.timeout)
            except httpx.TimeoutException:
                last = ApiError("timeout", "공공 API 응답이 제한 시간 안에 오지 않았습니다.", retryable=True)
            except httpx.HTTPError as exc:   # 예외 문자열에는 URL(인증키)이 들어갈 수 있어 형식 이름만 쓴다
                last = ApiError("network", f"공공 API에 연결하지 못했습니다({type(exc).__name__}).", retryable=True)
            else:
                text = mask_secret(resp.text, self.api_key)
                status = resp.status_code
                if status == 429:
                    raise ApiError("rate_limit", "호출 제한(일일 트래픽) 초과로 조회하지 못했습니다.", http_status=status)
                if status >= 500:
                    last = ApiError("http", f"공공 API 서버 오류(HTTP {status}).", http_status=status, retryable=True)
                elif status in (401, 403):
                    try:
                        parse_response(text, status)
                    except ApiError as e:
                        raise e if e.kind in ("rate_limit", "auth") else ApiError("auth", "서비스 인증 오류로 조회하지 못했습니다.", http_status=status, result_code=e.result_code)
                    raise ApiError("auth", "서비스 인증 오류로 조회하지 못했습니다.", http_status=status)
                elif status >= 400:
                    try:
                        parse_response(text, status)
                    except ApiError as e:
                        raise e
                    raise ApiError("http", f"공공 API 요청 오류(HTTP {status}).", http_status=status)
                else:
                    return text, utc_now()
            if attempt < self.max_retries:
                self.sleep(self.backoff * (2 ** attempt))
        assert last is not None
        raise last
