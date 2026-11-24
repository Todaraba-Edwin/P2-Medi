"""AG-01 조립 배선: 도구 컨텍스트(`ToolContext`)에 DUR 성분정보 API 클라이언트를 붙이고 그래프 의존성(`GraphDeps`)을 만든다.

- `DurClient`(BE-03, 식약처 DUR 품목·성분정보)는 **서비스·개발 모드 기본 on, 평가 모드 off**다(RFP 5.1절 (7), BE-08: 평가는 파일 판정만, API 호출 0).
  평가 모드 판단: `MEDIAGENT_MODE=eval` 또는 `MEDIAGENT_EVAL=1`. 평가 모드에서는 클라이언트를 **만들지도 않는다**(호출 0을 구조로 보장).
- 주소·키는 `Settings`의 환경변수 이름(`DURPrdlstInfoService03_*`, `DURIrdntInfoService03_*`)으로만 읽고, 이 모듈은 값을 보거나 남기지 않는다.
  `MEDIAGENT_API_MODE=snapshot`이면 `DurClient`가 스냅샷만 읽는다(오프라인 개발).
- 그래프 기본 프롬프트는 `agent_system@v2`(AG-01-03 A). 기본 묶음은 `prompt_set@v3`(= `agent_system@v2` + `answer_summary@v1`,
  2026-11-17 사용자 결정으로 v3 채택). 묶음에 `answer_summary`가 없으면(v1·v2) 요약 지시는 코드 상수 `nodes.SUMMARY_INSTRUCTION`이다.
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
DEFAULT_PROMPT_SET = "prompt_set@v3"  # 서비스·평가 공통 기본 묶음(2026-11-17 v3 채택). 결과 meta·trace의 `prompt_set`이 이 값이 된다
# 서비스 배선(`build_deps(service=True)`)의 오탈자 보정(AG-10) 기본값. BE-06-35 A(2026-11-17)로 프런트 `ChatResponseSchema`(strictObject)가
# `name_corrections` 칸을 받기 전까지 껐고, 프런트가 칸을 받은 뒤(`9205b8c`) AG-11 기준선 측정 종결(AG-11-15 A) 다음 2026-11-18에 켰다.
# 명시 인자 `typo_correct=False`는 이 값과 무관하게 끈다. 평가·개발 경로(service=False)의 기본은 여전히 끔이다.
SERVICE_TYPO_CORRECT_DEFAULT = True


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
    typo_correct: bool | None = None,
    layer_check: bool = False,
    model_name: str | None = None,
    safety_in_self_harm: bool = True,
    safety_in_self_judge: bool = True,
    safety_out_sensor: bool = True,
) -> GraphDeps:
    """그래프 의존성을 조립한다. 모델을 주지 않으면 `gpt-6-luna`(Chat Completions, `reasoning_effort="none"`) 객체를 만든다(호출은 하지 않음).

    `service=True`(앱 서버 `/chat`, BE-06-23 A)면 모델 래퍼가 개발 원장·개발 LLM 캐시를 거치지 않는다(`ledger`를 함께 주면 `ValueError`).
    기본값 False는 평가(`mode=eval`)·개발 경로이며 원장·캐시 동작은 예전과 같다.

    `typo_correct`(오탈자 보정 후 진행, AG-10): 주지 않으면 서비스 경로는 `SERVICE_TYPO_CORRECT_DEFAULT`(지금 True, BE-06-35 A:
    프런트가 응답 `name_corrections` 칸을 받은 뒤 2026-11-18 켬), 평가·개발 경로는 끔이다. 명시 인자(`True`/`False`)는 그대로 따른다.
    평가 실행기는 자원을 만든 뒤 비교 조건에 맞춰 `deps.typo_correct`를 직접 적는다(`eval_runner.apply_typo_correct`).

    요약 지시: `prompt_set`을 주지 않으면 기본 묶음 `DEFAULT_PROMPT_SET`(`prompt_set@v3`)을 쓴다. 묶음에 `answer_summary`가 있으면 그 파일 본문을,
    없으면(v1·v2) 코드 상수 `nodes.SUMMARY_INSTRUCTION`을 쓴다. draft 프롬프트가 든 묶음은 `allow_draft=True`를 명시해야 한다
    (검토 카드 승인 전에는 기준선에 넣지 않는다, PRD-16-03. 채택된 묶음은 명시 없이 읽힌다).
    `summary_instruction`을 직접 주면 그 값이 우선한다(시험용). 시스템 프롬프트는 이 인자와 무관하게 `prompt_name`·`system_prompt`로 정한다.

    `model_name`(AG-01 `:31`, 모델 객체를 여기서 만들 때만 쓴다): 명시하면 그 이름을 쓴다. 주지 않으면 서비스 경로(`service=True`)는
    설정 `Settings.mediagent_agent_model`(환경변수 `MEDIAGENT_AGENT_MODEL`, 기본 `gpt-6-luna`)을, 평가·개발 경로는 `llm.MODEL`을 쓴다
    (평가 고정: `.env` 값으로 평가 대상 모델이 바뀌지 않게, 결과 meta의 `llm.MODEL`과 어긋나지 않게). 비용 추정 단가는 `gpt-6-luna` 기준이다.

    `layer_check`(AG-07 계층·주장 유형 누락 검사, AG-13 C3 장치): 기본 끔. 비교 조건 C3에서만 켜며, 평가 실행기는 조건으로 그래프를 고를 때
    `pipeline.build.build_for_condition`이 정한다(C3만 켬). 서비스 경로(`service=True`)는 채택 결정 전까지 켤 수 없다(`ValueError`).
    """
    if service and ledger is not None:
        raise ValueError("서비스 경로는 개발 원장을 쓰지 않는다(ledger=None이어야 한다, BE-06-23 A)")
    if service and layer_check:
        raise ValueError("서비스 경로는 계층 검사(C3 장치)를 켜지 않는다(AG-13 측정 뒤 채택 결정 전)")
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
        name = _resolve_model_name(settings, service=service, model_name=model_name)
        if tool_model is None:
            tool_model = CachedToolModel(llm.bind_tools_model(llm.make_chat_model(settings, purpose="tools", model=name), tools),
                                         model=name, estimate_usd=est, ledger=ledger, service=service)
        if summary_model is None:
            structured = llm.make_chat_model(settings, purpose="summary", model=name).with_structured_output(
                llm.answer_draft_json_schema(), method="json_schema", strict=True, include_raw=True)
            summary_model = CachedSummary(structured, model=name, estimate_usd=est, ledger=ledger, service=service)
    if summary_instruction is None:
        summary_instruction = load_summary_instruction(prompt_set or DEFAULT_PROMPT_SET, allow_draft=allow_draft)  # 묶음에 요약 프롬프트가 없으면 None(상수)
    kwargs: dict[str, Any] = {}
    if registry is not None:
        kwargs["registry"] = registry
    return GraphDeps(drug_dict=drug_dict, tool_model=tool_model, summary_model=summary_model, tools=tools, tool_ctx=tool_ctx,
                     system_prompt=system_prompt if system_prompt is not None else load_system_prompt(prompt_name), tracer=tracer, grade_def_fn=grade_def_fn,
                     summary_instruction=summary_instruction, typo_correct=_resolve_typo_correct(service, typo_correct), layer_check=bool(layer_check), safety_in_self_harm=bool(safety_in_self_harm),
                     safety_in_self_judge=bool(safety_in_self_judge), safety_out_sensor=bool(safety_out_sensor), **kwargs)


def _resolve_model_name(settings: Any, *, service: bool, model_name: str | None) -> str:
    """에이전트 모델 이름: 명시 인자 → (서비스 경로만) 설정 `mediagent_agent_model` → `llm.MODEL`. 빈 값은 건너뛴다(AG-01 `:31`)."""
    from app.agent import llm

    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()
    if service:
        configured = getattr(settings, "mediagent_agent_model", None)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    return llm.MODEL


def _resolve_typo_correct(service: bool, typo_correct: bool | None) -> bool:
    """오탈자 보정 스위치: 명시 인자가 우선이고, 없으면 서비스 경로는 `SERVICE_TYPO_CORRECT_DEFAULT`, 그 밖은 False(BE-06-35 A)."""
    if typo_correct is not None:
        return bool(typo_correct)
    return SERVICE_TYPO_CORRECT_DEFAULT if service else False
