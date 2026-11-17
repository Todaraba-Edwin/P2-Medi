"""AG-01 L2 후속(2026-11-11): 그래프 모델 호출을 `llm_cache`·개발 원장 경로에 태우고 캐시 상태·요약 호출 토큰을 계측에 넘긴다.

- `CachedToolModel`: 도구 노드용 모델(`bind_tools_model` 결과)을 감싼다. 응답 `AIMessage`를 직렬화해 캐시에 두고,
  돌려줄 때 `response_metadata["mediagent_cache"]`에 상태(`off`·`hit`·`miss`)를 적는다. `GraphTracer`가 이 값을 `cache` 필드로 쓴다.
- `CachedSummary`: 요약용 구조화 출력 모델을 `include_raw=True`로 만든 것을 감싼다. `{"raw": AIMessage, "parsed": dict, "parsing_error": None}`을
  돌려주고, 그래프 `model` 노드가 `parsed`만 초안으로 쓰고 `raw`의 토큰·캐시 상태를 요약 호출 span으로 남긴다.
  파싱 오류는 예전(`include_raw=False`)처럼 예외로 올리고 캐시에 저장하지 않는다(동작 불변).
- 캐시 모드 규칙·평가 강제 off·원장 guard는 `app.llm.cache.cached_openai_call_status`가 그대로 한다(이 모듈은 직렬화만).
- 캐시 키에는 메시지 종류·내용·도구 호출(이름·인자·id)만 넣는다. 비밀값은 메시지에 없다(키는 `Settings`에서 모델 객체로만 간다).
- **서비스 경로(BE-06-23 A, 2026-11-17)**: `service=True`면 `cached_openai_call_status`를 거치지 않고 바로 호출한다. 개발 원장(`CostLedger`,
  `data/mock/openai_ledger.json`, `DEV_CAP_USD`)과 개발 LLM 캐시(`llm_cache`)를 만들지도 읽지도 쓰지도 않는다. 상태는 늘 `off`이고,
  호출 수·토큰·추정 비용은 메모리 합계(`usage`, 고정 크기)로만 센다. `mode=eval`·개발 경로(`service=False`, 기본)는 예전과 같다.
- 캐시 상태 기록은 상태별 횟수(`status_counts`, 키는 `off`·`hit`·`stored`·`miss` 넷뿐)만 둔다. 예전 `statuses` 목록은 호출마다 늘어
  모델 객체를 요청 사이에 공유하는 서버에서 메모리가 커졌다(BE-06-28 A 메모).
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict

from app.llm.cache import cached_openai_call_status
from app.llm.ledger import CostLedger

CACHE_META_KEY = "mediagent_cache"


def message_key(m: Any) -> dict[str, Any]:
    """캐시 키용 메시지 표현(종류·내용·도구 호출·도구 호출 id). 응답 메타데이터·토큰은 넣지 않는다."""
    if not isinstance(m, BaseMessage):
        return {"type": "raw", "content": str(m)}
    out: dict[str, Any] = {"type": m.type, "content": m.content}
    tcs = getattr(m, "tool_calls", None)
    if tcs:
        out["tool_calls"] = [{"name": tc.get("name"), "args": tc.get("args"), "id": tc.get("id")} for tc in tcs]
    if getattr(m, "tool_call_id", None):
        out["tool_call_id"] = m.tool_call_id  # type: ignore[attr-defined]
    return out


def usage_of(msg: Any) -> tuple[int, int, int]:
    """(입력, 출력, 캐시 읽기) 토큰. 없으면 0."""
    um = getattr(msg, "usage_metadata", None) or {}
    return (int(um.get("input_tokens") or 0), int(um.get("output_tokens") or 0),
            int(((um.get("input_token_details") or {}).get("cache_read")) or 0))


def _with_cache(msg: AIMessage, status: str) -> AIMessage:
    meta = dict(msg.response_metadata or {})
    meta[CACHE_META_KEY] = status
    return msg.model_copy(update={"response_metadata": meta})


def _default_cost(prompt: int, completion: int, cached: int) -> float:
    from app.agent.llm import estimate_cost_usd  # 단가 원본은 llm.py 한 곳(지연 import: 시험에서 ChatOpenAI 불필요)

    return estimate_cost_usd(prompt, completion, cached)


class _CachedBase:
    def __init__(self, inner: Any, *, model: str, purpose: str, ledger: CostLedger | None = None,
                 cost_fn: Callable[[int, int, int], float] | None = None, estimate_usd: float = 0.0,
                 prompt_files: Sequence[str] = (), service: bool = False) -> None:
        if service and ledger is not None:
            raise ValueError("서비스 경로는 개발 원장을 쓰지 않는다(ledger=None이어야 한다, BE-06-23 A)")
        self.inner = inner
        self.model = model
        self.purpose = purpose
        self.ledger = ledger
        self.cost_fn = cost_fn or _default_cost
        self.estimate_usd = estimate_usd
        self.prompt_files = tuple(prompt_files)
        self.service = service
        self._lock = threading.Lock()  # 서버에서는 한 객체를 여러 요청 스레드가 함께 쓴다
        self.status_counts: Counter[str] = Counter()  # 캐시 상태별 호출 수(키 4개 이하, 내용 없음)
        self.usage: dict[str, float] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}  # 서비스 경로 메모리 합계

    def _call(self, messages: Sequence[Any], fetch: Callable[[], Any], cost_of: Callable[[Any], float]) -> tuple[Any, str]:
        if self.service:
            resp, status = fetch(), "off"  # 원장·캐시를 거치지 않는다(파일 읽기·쓰기 0)
            cost = cost_of(resp)
            with self._lock:
                self.usage["calls"] += 1
                self.usage["cost_usd"] += cost
                self.status_counts[status] += 1
            return resp, status
        resp, status = cached_openai_call_status(
            self.model, [message_key(m) for m in messages], {"purpose": self.purpose}, fetch,
            cost_fn=cost_of, estimate_usd=self.estimate_usd, ledger=self.ledger, prompt_files=self.prompt_files, tag=self.purpose)
        with self._lock:
            self.status_counts[status] += 1
        return resp, status

    def _count_tokens(self, msg: Any) -> None:
        if not self.service:
            return
        inp, out, _cached = usage_of(msg)
        with self._lock:
            self.usage["input_tokens"] += inp
            self.usage["output_tokens"] += out


class CachedToolModel(_CachedBase):
    """`.invoke(messages) -> AIMessage`(도구 호출 포함). 캐시 상태를 응답 메타데이터에 적는다."""

    def __init__(self, inner: Any, *, model: str = "gpt-6-luna", **kw: Any) -> None:
        super().__init__(inner, model=model, purpose="tools", **kw)

    def invoke(self, messages: Sequence[Any], **kwargs: Any) -> AIMessage:
        def fetch() -> dict[str, Any]:
            return message_to_dict(self.inner.invoke(list(messages), **kwargs))

        def cost_of(d: dict[str, Any]) -> float:
            return self.cost_fn(*usage_of(messages_from_dict([d])[0]))

        resp, status = self._call(messages, fetch, cost_of)
        msg = messages_from_dict([resp])[0]
        if not isinstance(msg, AIMessage):  # pragma: no cover — 모델은 AIMessage만 돌려준다
            raise TypeError(f"도구 모델 응답 종류가 AIMessage가 아니다: {type(msg).__name__}")
        self._count_tokens(msg)
        return _with_cache(msg, status)


class CachedSummary(_CachedBase):
    """`.invoke(messages) -> {"raw": AIMessage, "parsed": dict, "parsing_error": None}`. 내부 모델은 `include_raw=True` 구조화 출력이어야 한다."""

    def __init__(self, inner: Any, *, model: str = "gpt-6-luna", **kw: Any) -> None:
        super().__init__(inner, model=model, purpose="summary", **kw)

    def invoke(self, messages: Sequence[Any], **kwargs: Any) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            res = self.inner.invoke(list(messages), **kwargs)
            if not (isinstance(res, dict) and "raw" in res and "parsed" in res):
                raise TypeError("CachedSummary 내부 모델은 include_raw=True 구조화 출력이어야 한다")
            if res.get("parsing_error") is not None:  # 예전처럼 예외로(저장하지 않음)
                raise res["parsing_error"]
            return {"raw": message_to_dict(res["raw"]), "parsed": res["parsed"]}

        def cost_of(d: dict[str, Any]) -> float:
            return self.cost_fn(*usage_of(messages_from_dict([d["raw"]])[0]))

        resp, status = self._call(messages, fetch, cost_of)
        raw = messages_from_dict([resp["raw"]])[0]
        self._count_tokens(raw)
        return {"raw": _with_cache(raw, status) if isinstance(raw, AIMessage) else raw, "parsed": resp["parsed"], "parsing_error": None}


def unwrap_summary(res: Any) -> tuple[Any, Any]:
    """요약 모델 결과 → (초안 dict, 원 응답 메시지 또는 None). 가짜(`ScriptedSummary`)처럼 초안 dict만 주면 (그 dict, None)."""
    if isinstance(res, dict) and "raw" in res and "parsed" in res and set(res) <= {"raw", "parsed", "parsing_error"}:
        if res.get("parsing_error") is not None:
            raise res["parsing_error"]
        return res["parsed"], res["raw"]
    return res, None


__all__ = ["CACHE_META_KEY", "CachedSummary", "CachedToolModel", "message_key", "unwrap_summary", "usage_of"]
