"""백엔드 LLM 호출 경로용 캐시·원장 어댑터(BE-15, RFP-32·RFP-34-05). 실호출은 하지 않는다(fetch는 호출자가 준다).

- 캐시 모드 규칙은 `evaluation/mock_gen/llm_cache.py`와 같다: LLM_CACHE=off|record|replay(기본 off),
  MEDIAGENT_EVAL=1이면 LLM_CACHE와 상관없이 off로 강제(평가 측정은 항상 캐시 없이).
- off일 때는 llm_cache를 불러오지 않는다(그 모듈은 anthropic·dotenv에 의존). record·replay일 때만 파일 경로로 지연 로드한다.
- 실호출(fetch)은 원장 guard를 먼저 거친다. dev 상한을 넘었으면 BudgetExceeded로 막고 캐시 적중(replay)만 허용된다.
  평가 실행(MEDIAGENT_EVAL=1)의 비용은 eval 몫으로 따로 센다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from app.llm.ledger import CostLedger

MODES = ("off", "record", "replay")
REPO_ROOT = Path(__file__).resolve().parents[3]
_LLM_CACHE_PATH = REPO_ROOT / "evaluation" / "mock_gen" / "llm_cache.py"


def is_eval() -> bool:
    return os.environ.get("MEDIAGENT_EVAL", "").strip() not in ("", "0", "false", "False")


def cache_mode() -> str:
    if is_eval():
        return "off"
    mode = os.environ.get("LLM_CACHE", "off").strip().lower() or "off"
    if mode not in MODES:
        raise ValueError(f"LLM_CACHE는 {MODES} 중 하나여야 한다: {mode!r}")
    return mode


def _load_llm_cache() -> ModuleType:
    name = "_mediagent_llm_cache"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _LLM_CACHE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"llm_cache를 찾을 수 없다: {_LLM_CACHE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def cached_openai_call(
    model: str,
    messages: list,
    args: dict | None,
    fetch: Callable[[], Any],
    *,
    cost_fn: Callable[[Any], float] | None = None,
    estimate_usd: float = 0.0,
    ledger: CostLedger | None = None,
    prompt_files: Sequence[str] = (),
    tag: str = "",
) -> Any:
    """fetch()는 JSON 직렬화 가능한 응답을 돌려주는 실제 호출. cost_fn(응답)은 실제 비용(USD)."""
    ledger = ledger or CostLedger()
    bucket = "eval" if is_eval() else "dev"

    def guarded_fetch() -> Any:
        ledger.guard(estimate_usd, bucket)  # 상한 초과면 여기서 중단(실호출 전)
        resp = fetch()
        if cost_fn is not None:
            ledger.add(cost_fn(resp), bucket)
        return resp

    if cache_mode() == "off":
        return guarded_fetch()
    module = _load_llm_cache()
    return module.cached_call("openai", model, messages, args, guarded_fetch, prompt_files, tag)
