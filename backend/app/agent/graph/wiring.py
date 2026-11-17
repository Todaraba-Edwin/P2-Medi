"""AG-01 조립 배선: 도구 컨텍스트(`ToolContext`)에 DUR 성분정보 API 클라이언트를 붙이고 그래프 의존성(`GraphDeps`)을 만든다.

- `DurClient`(BE-03, 식약처 DUR 품목·성분정보)는 **서비스·개발 모드 기본 on, 평가 모드 off**다(RFP 5.1절 (7), BE-08: 평가는 파일 판정만, API 호출 0).
  평가 모드 판단: `MEDIAGENT_MODE=eval` 또는 `MEDIAGENT_EVAL=1`. 평가 모드에서는 클라이언트를 **만들지도 않는다**(호출 0을 구조로 보장).
- 주소·키는 `Settings`의 환경변수 이름(`DURPrdlstInfoService03_*`, `DURIrdntInfoService03_*`)으로만 읽고, 이 모듈은 값을 보거나 남기지 않는다.
  `MEDIAGENT_API_MODE=snapshot`이면 `DurClient`가 스냅샷만 읽는다(오프라인 개발).
- 그래프 기본 프롬프트는 `agent_system@v2`(AG-01-03 A). 묶음 이름은 `prompt_set@v2`.
- 이 모듈은 외부 호출을 하지 않는다. 모델 객체·클라이언트 객체를 만들 뿐이고, 호출은 그래프 실행 때 일어난다. 시험은 가짜 클라이언트·가짜 모델을 넣는다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.agent.graph.nodes import GraphDeps
from app.agent.graph.prompt import load_summary_instruction, load_system_prompt
from app.agent.tools.context import ToolContext, ingredient_api_fns
from app.agent.tools.langchain_adapter import build_tools
from app.tools.drug_dict import DrugDict

DEFAULT_PROMPT = "agent_system@v2"
DEFAULT_PROMPT_SET = "prompt_set@v2"


def is_eval_mode(mode: str | None = None) -> bool:
    """평가 모드면 True. `mode` 인자가 없으면 환경변수(`MEDIAGENT_MODE`·`MEDIAGENT_EVAL`)를 본다(값을 읽을 뿐 검증은 L1 `get_mode`가 한다)."""
    m = (mode if mode is not None else os.environ.get("MEDIAGENT_MODE", "")).strip().lower()
    flag = os.environ.get("MEDIAGENT_EVAL", "").strip() not in ("", "0", "false", "False")
    return m == "eval" or (mode is None and flag)


def _default_dur_factory(settings: Any) -> Any:
    from app.tools.dur import DurClient

    return DurClient.from_settings(settings)


def build_tool_context(
    drug_dict: DrugDict,
    *,
    settings: Any = None,
    mode: str | None = None,
    api_enabled: bool | None = None,
    dur_client: Any = None,
    dur_factory: Callable[[Any], Any] | None = None,
    **ctx_kwargs: Any,
) -> ToolContext:
    """도구 컨텍스트를 만든다. API 병기(`api_pair_fn`·`api_age_fn`·`api_pregnancy_fn`)는 켜진 경우에만 `DurClient`로 채운다.

    - `api_enabled`가 None이면 모드로 정한다(평가 → False, 그 밖 → True).
    - `dur_client`를 주면 그것을 쓰고(시험·재사용), 없으면 `dur_factory(settings)`(기본 `DurClient.from_settings`)로 만든다.
    - 꺼져 있으면 클라이언트를 만들지 않고 세 함수 모두 None(도구는 `api_enabled=False`로 API 꼬리표 없이 파일 판정만 한다).
    """
    enabled = (not is_eval_mode(mode)) if api_enabled is None else bool(api_enabled)
    if not enabled:
        return ToolContext(drug_dict=drug_dict, api_enabled=False, api_pair_fn=None, api_age_fn=None, api_pregnancy_fn=None, **ctx_kwargs)
    client = dur_client if dur_client is not None else (dur_factory or _default_dur_factory)(settings)
    age_fn, preg_fn = ingredient_api_fns(client)
    return ToolContext(drug_dict=drug_dict, api_enabled=True, api_pair_fn=client.usjnt_pair_by_ingredient, api_age_fn=age_fn,
                       api_pregnancy_fn=preg_fn, **ctx_kwargs)


def build_deps(
    drug_dict: DrugDict,
    tool_ctx: ToolContext,
    *,
    tool_model: Any = None,
    summary_model: Any = None,
    settings: Any = None,
    prompt_name: str = DEFAULT_PROMPT,
    system_prompt: str | None = None,
    registry: dict[str, Any] | None = None,
    tracer: Any = None,
    ledger: Any = None,
    grade_def_fn: Any = None,
    prompt_set: str | None = None,
    allow_draft: bool = False,
    summary_instruction: str | None = None,
    service: bool = False,
) -> GraphDeps:
    """그래프 의존성을 조립한다. 모델을 주지 않으면 `gpt-6-luna`(Chat Completions, `reasoning_effort="none"`) 객체를 만든다(호출은 하지 않음).

    `service=True`(앱 서버 `/chat`, BE-06-23 A)면 모델 래퍼가 개발 원장·개발 LLM 캐시를 거치지 않는다(`ledger`를 함께 주면 `ValueError`).
    기본값 False는 평가(`mode=eval`)·개발 경로이며 원장·캐시 동작은 예전과 같다.

    요약 지시: `prompt_set`을 주지 않으면(기본 `prompt_set@v2`) 코드 상수를 쓴다(동작 불변). 묶음을 명시하고 그 묶음에 `answer_summary`가 있으면
    그 파일 본문을 쓴다. draft 프롬프트가 든 묶음은 `allow_draft=True`를 명시해야 한다(검토 카드 승인 전에는 기준선에 넣지 않는다, PRD-16-03).
    `summary_instruction`을 직접 주면 그 값이 우선한다(시험용). 시스템 프롬프트는 이 인자와 무관하게 `prompt_name`·`system_prompt`로 정한다.
    """
    if service and ledger is not None:
        raise ValueError("서비스 경로는 개발 원장을 쓰지 않는다(ledger=None이어야 한다, BE-06-23 A)")
    tools = build_tools(tool_ctx, registry)
    if tool_model is None or summary_model is None:
        from app.agent import llm

        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        from app.agent.graph.metered import CachedSummary, CachedToolModel

        # 실제 모델은 llm_cache·개발 원장 경로로 감싼다(캐시 상태 hit/miss가 L2 `cache` 필드로, 요약 토큰은 include_raw로 계측된다).
        # 서비스 경로(service=True)는 같은 래퍼를 쓰되 원장·캐시를 건너뛴다(BE-06-23 A).
        est = llm.MAX_COMPLETION_TOKENS * llm.PRICE_OUT / 1e6
        if tool_model is None:
            tool_model = CachedToolModel(llm.bind_tools_model(llm.make_chat_model(settings, purpose="tools"), tools),
                                         model=llm.MODEL, estimate_usd=est, ledger=ledger, service=service)
        if summary_model is None:
            structured = llm.make_chat_model(settings, purpose="summary").with_structured_output(
                llm.answer_draft_json_schema(), method="json_schema", strict=True, include_raw=True)
            summary_model = CachedSummary(structured, model=llm.MODEL, estimate_usd=est, ledger=ledger, service=service)
    if summary_instruction is None and prompt_set is not None:
        summary_instruction = load_summary_instruction(prompt_set, allow_draft=allow_draft)  # 묶음에 요약 프롬프트가 없으면 None(상수)
    kwargs: dict[str, Any] = {}
    if registry is not None:
        kwargs["registry"] = registry
    return GraphDeps(drug_dict=drug_dict, tool_model=tool_model, summary_model=summary_model, tools=tools, tool_ctx=tool_ctx,
                     system_prompt=system_prompt if system_prompt is not None else load_system_prompt(prompt_name), tracer=tracer, grade_def_fn=grade_def_fn,
                     summary_instruction=summary_instruction, **kwargs)
