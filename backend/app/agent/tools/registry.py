"""도구 등록 레지스트리와 호출기(`invoke`).

LangChain `@tool` 어댑터는 AG-01/AG-19가 `REGISTRY`를 감싸서 만든다(이 모듈은 langchain을 import하지 않는다).
`invoke`는 인자를 Pydantic으로 검증하고, 틀리면 도구 본문을 실행하지 않고 `ARG_SCHEMA` 응답을 돌려준다(RFP-33-02).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.tools.check_contraindications import check_contraindications
from app.agent.tools.context import ToolContext
from app.agent.tools.contract import check_items, render_data_block
from app.agent.tools.get_label_section import get_label_section
from app.agent.tools.identify_drug import identify_drug
from app.agent.tools.schemas import (
    POST_WRITABLE_KEYS,
    CheckContraArgs,
    GetLabelSectionArgs,
    IdentifyDrugArgs,
    arg_schema_error,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[BaseModel]
    func: Callable[[Any, ToolContext], dict[str, Any]]
    description: str


REGISTRY: dict[str, ToolSpec] = {
    "identify_drug": ToolSpec("identify_drug", IdentifyDrugArgs, identify_drug, "약 이름으로 후보(최대 5개)를 찾는다. 판정하지 않는다."),
    "check_contraindications": ToolSpec("check_contraindications", CheckContraArgs, check_contraindications,
                                        "약 여러 개의 병용·임부·연령(·주의) 금기를 성분코드 정확 일치로 조회한다."),
    "get_label_section": ToolSpec("get_label_section", GetLabelSectionArgs, get_label_section,
                                  "품목기준코드와 절 이름으로 허가사항·쉬운 설명 절 본문을 가져온다."),
}


def invoke(name: str, raw_args: dict[str, Any], ctx: ToolContext, registry: dict[str, ToolSpec] | None = None) -> dict[str, Any]:
    """도구 호출 1건. 반환: `{"items": [...], ...}`(+ `text` 데이터 블록, `contract_violations`, `writable`)."""
    spec = (registry or REGISTRY).get(name)
    if spec is None:
        return {"items": [], "blocked": True, "error": {
            "code": "UNKNOWN_TOOL", "tool": name, "reason": "등록되지 않은 도구", "next_action": "등록된 도구 이름으로 호출한다",
            "remaining_calls": max(ctx.remaining_calls, 0)}}
    try:
        args = spec.args_model.model_validate(raw_args)
    except ValidationError as e:
        return arg_schema_error(name, e, ctx.remaining_calls)  # 본문 실행 없음
    out = spec.func(args, ctx)
    items = out["items"]
    out["contract_violations"] = check_items(name, items)
    out["text"] = render_data_block(name, items)
    out["writable"] = writable_update(out)
    return out


def writable_update(out: dict[str, Any]) -> dict[str, Any]:
    """도구가 상태에 쓸 수 있는 값. `POST_WRITABLE_KEYS` 밖의 키는 만들지 않는다(emergency·route·profile·confirmed_mentions 불가)."""
    upd = {
        "evidence": list(out["items"]),
        "known_ids": set(out.get("known_ids", [])),
        "input_units": dict(out.get("input_units", {})),
        "events": [],
    }
    if not set(upd) <= POST_WRITABLE_KEYS:
        raise RuntimeError("POST_WRITABLE_KEYS 밖의 키")
    return upd
