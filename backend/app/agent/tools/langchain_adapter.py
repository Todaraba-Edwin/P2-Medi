"""AG-01 LangChain `@tool` 어댑터: `REGISTRY`의 도구를 `StructuredTool`로 감싼다(도구 본문은 `registry.invoke` 경로 그대로).

- 모델에는 `args_model`의 JSON 스키마를 보여 주되(`args_schema`를 dict로 줌), 인자 검증은 LangChain이 아니라 `invoke`의 Pydantic이 한다.
  그래서 형식이 틀린 호출은 도구 본문을 실행하지 않고 `ARG_SCHEMA` 응답(이유·다음 행동·남은 호출 수)으로 막힌다(RFP-33-02, H21).
- 도구 결과는 `content_and_artifact`: 모델에게 가는 내용은 데이터 블록 구분자로 감싼 텍스트(`out["text"]`, H8), 원본 `out` dict는 artifact에 남아
  `tools` 노드가 `items[]`를 상태 `evidence`에 쌓는다.
- 이 모듈은 외부 호출을 하지 않는다. 도구가 쓰는 DB·API는 `ToolContext`에 주입된 것만 쓴다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY, ToolSpec, invoke


def _make_tool(spec: ToolSpec, ctx: ToolContext, registry: dict[str, ToolSpec]) -> StructuredTool:
    def _run(**raw_args: Any) -> tuple[str, dict[str, Any]]:
        out = invoke(spec.name, raw_args, ctx, registry)
        text = out.get("text")
        if text is None:  # 차단 응답(ARG_SCHEMA·UNKNOWN_TOOL)에는 데이터 블록이 없다: 오류 요약만 모델에 준다
            err = out.get("error") or {}
            text = f"[HARNESS] {err.get('code')}: {err.get('reason')} / 다음 행동: {err.get('next_action')} / 남은 호출 {err.get('remaining_calls')}"
        return text, out

    return StructuredTool(
        name=spec.name,
        description=spec.description,
        func=_run,
        args_schema=spec.args_model.model_json_schema(),
        response_format="content_and_artifact",
    )


def build_tools(ctx: ToolContext, registry: dict[str, ToolSpec] | None = None) -> list[StructuredTool]:
    """레지스트리의 도구 전부를 `StructuredTool`로 만든다(등록 순서 유지)."""
    reg = registry if registry is not None else REGISTRY
    return [_make_tool(spec, ctx, reg) for spec in reg.values()]
