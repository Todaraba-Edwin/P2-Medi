"""AG-01·AG-19 모델 팩토리(LangChain `ChatOpenAI`, Chat Completions, `reasoning_effort="none"` 고정).

- 결정 AG-01-01 A: 도구를 쓰는 ReAct 노드는 Chat Completions + `reasoning_effort='none'`이다(`gpt-6-luna`는 추론을 켠 채 함수 도구를 쓰면 HTTP 400).
- **도구 호출과 구조화 출력은 한 호출에 섞지 않는다.** `purpose="tools"`는 `bind_tools`용, `purpose="summary"`는 도구 없이
  `with_structured_output`(strict)으로 `AnswerDraft`만 받는 최종 요약용이다(AG-19 ④).
- API 키는 `Settings`에서만 읽고 `SecretStr`로 넘긴다. 이 모듈은 키를 출력·기록하지 않는다.
- 이 모듈은 외부 호출을 하지 않는다(모델 객체를 만들 뿐). 호출 횟수 상한 8(RFP-22)은 그래프(`graph/nodes.py`)가 센다.
- 개발 원장 연결: `LedgerCallback`이 호출 전 `CostLedger.guard`, 호출 뒤 사용 토큰으로 비용을 `add`한다(단가 입력 $0.10·출력 $0.50 per 1M).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agent.answer_schema import AnswerDraft
from app.config import Settings, reveal
from app.llm.ledger import CostLedger

MODEL = "gpt-6-luna"
REASONING_EFFORT = "none"
MAX_COMPLETION_TOKENS = 1500
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.10, 0.01, 0.50  # USD / 100만 토큰(BE-15, 2026-11-10)
Purpose = Literal["tools", "summary"]

_STRIP = {"title", "default", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems"}


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic 스키마를 Structured Outputs strict 규칙에 맞춘다(`$ref` 인라인, 전부 required, additionalProperties=false, 길이·범위 키워드 제거).

    `backend/scripts/luna_feature_check.py`의 같은 이름 함수와 동작이 같다(app이 scripts를 import하지 않으려고 복사). 응답은 받은 뒤 `AnswerDraft`로 다시 검증한다.
    """
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
        out = {k: walk(v) for k, v in node.items() if k not in _STRIP and k != "$defs"}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    return walk(schema)  # type: ignore[no-any-return]


def answer_draft_json_schema() -> dict[str, Any]:
    """`with_structured_output(method="json_schema")`에 넘기는 `AnswerDraft` 변환 스키마(이름·strict 포함 dict)."""
    return {"name": "answer_draft", "strict": True, "schema": to_strict_schema(AnswerDraft.model_json_schema())}


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    return (prompt_tokens - cached_tokens) * PRICE_IN / 1e6 + cached_tokens * PRICE_CACHED / 1e6 + completion_tokens * PRICE_OUT / 1e6


class LedgerCallback(BaseCallbackHandler):
    """호출 전 원장 guard(상한 초과면 `BudgetExceeded`), 호출 뒤 토큰 사용량으로 비용 기록. 호출 수·토큰만 남기고 내용은 남기지 않는다."""

    raise_error = True  # guard 예외가 호출을 막도록 전파한다

    def __init__(self, ledger: CostLedger | None = None, *, bucket: str = "dev", estimate_usd: float = MAX_COMPLETION_TOKENS * PRICE_OUT / 1e6) -> None:
        self.ledger = ledger or CostLedger()
        self.bucket = bucket
        self.estimate_usd = estimate_usd
        self.calls = 0
        self.cost_usd = 0.0

    def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, **kwargs: Any) -> None:
        self.ledger.guard(self.estimate_usd, self.bucket)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage: dict[str, Any] = (response.llm_output or {}).get("token_usage") or {}
        if not usage:  # 일부 경로는 메시지 메타데이터에만 있다
            try:
                um = response.generations[0][0].message.usage_metadata  # type: ignore[union-attr]
                usage = {"prompt_tokens": um.get("input_tokens", 0), "completion_tokens": um.get("output_tokens", 0)}
            except (AttributeError, IndexError, TypeError):
                usage = {}
        cost = estimate_cost_usd(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
        self.calls += 1
        self.cost_usd += cost
        self.ledger.add(cost, self.bucket)


def make_chat_model(
    settings: Settings,
    *,
    purpose: Purpose = "tools",
    http_client: Any = None,
    callbacks: Sequence[BaseCallbackHandler] | None = None,
    model: str = MODEL,
) -> BaseChatModel:
    """`ChatOpenAI`를 만든다(Chat Completions 고정, `reasoning_effort="none"` 고정). 호출은 하지 않는다.

    `purpose`는 쓰임새를 구분하는 표지다. 도구 노드용(`tools`)은 호출자가 `bind_tools_model`로 도구를 묶고, 요약용(`summary`)은 `summary_model`로 구조화 출력만 묶는다.
    같은 객체에 둘을 모두 묶지 않는다(도구 호출과 구조화 출력은 한 호출에 섞지 않는다).
    """
    if purpose not in ("tools", "summary"):
        raise ValueError(f"purpose는 tools|summary: {purpose!r}")
    key = reveal(settings.openai_api_key)  # S-04: Settings 키는 SecretStr(평문 str도 허용)
    kwargs: dict[str, Any] = {}
    if http_client is not None:
        kwargs["http_client"] = http_client
    return ChatOpenAI(
        model=model,
        api_key=SecretStr(key) if key else SecretStr("missing"),  # 키가 없으면 호출 시 인증 오류가 난다(시험은 외부 호출 0)
        reasoning_effort=REASONING_EFFORT,
        use_responses_api=False,
        max_retries=0,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        callbacks=list(callbacks) if callbacks else None,
        tags=[f"purpose:{purpose}"],
        **kwargs,
    )


def bind_tools_model(model: BaseChatModel, tools: Sequence[Any], *, parallel: bool = True) -> Any:
    """도구 노드용: 도구 묶기 + `parallel_tool_calls`. 구조화 출력은 묶지 않는다."""
    return model.bind_tools(list(tools), parallel_tool_calls=parallel)


def summary_model(model: BaseChatModel) -> Any:
    """최종 요약용: 도구 없이 `AnswerDraft` strict 변환 스키마 구조화 출력(출력은 dict, 받은 뒤 `parse_draft`로 검증)."""
    return model.with_structured_output(answer_draft_json_schema(), method="json_schema", strict=True)
