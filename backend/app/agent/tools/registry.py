"""도구 등록 레지스트리와 호출기(`invoke`).

LangChain `@tool` 어댑터는 AG-01/AG-19가 `REGISTRY`를 감싸서 만든다(이 모듈은 langchain을 import하지 않는다).
`invoke`는 인자를 Pydantic으로 검증하고, 틀리면 도구 본문을 실행하지 않고 `ARG_SCHEMA` 응답을 돌려준다(RFP-33-02).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.nondrug_tokens import is_non_drug_token
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
    arg_schema_response,
)
from app.agent.tools.search_label import SearchLabelArgs, search_label
from app.agent.tools.search_notice import SearchNoticeArgs, search_notice
from app.agent.tools.search_reason import SearchReasonArgs, search_reason
from app.tools.drug_dict import MATCH_EXACT, MATCH_NORMALIZED


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
    # AG-03 문서 검색 도구(검색은 판정하지 않는다)
    "search_notice": ToolSpec("search_notice", SearchNoticeArgs, search_notice,
                              "고시 조문·정의·별표 행(L1)을 찾아 인용한다. 금기 판정은 하지 않는다."),
    "search_reason": ToolSpec("search_reason", SearchReasonArgs, search_reason,
                              "병용금기 사유·임부금기·연령금기 상세정보(L2)를 성분코드·성분쌍으로 찾아 인용한다. 판정은 하지 않는다."),
    "search_label": ToolSpec("search_label", SearchLabelArgs, search_label,
                             "품목 허가사항·e약은요 문장(L3)을 찾아 절 전체와 함께 인용한다. 판정은 하지 않는다."),
}


# 없앤 옛 인자(C-1 A, 2026-11-19): 들어오면 검증 전에 조용히 버리고 개수만 이벤트로 남긴다(`ARG_SCHEMA`로 막으면 모델이 한 번 더 호출해야 한다).
# `include_cautions`는 주의 3종 조회를 코드 규칙으로 옮기며 뺐다(AG-22-04 A, `ToolContext.caution_kinds`). 캐시된 옛 응답·모델 환각 대비다
IGNORED_ARGS: dict[str, tuple[str, ...]] = {"check_contraindications": ("include_cautions",)}
EVENT_ARG_IGNORED = "ARG_IGNORED"


_EXACT_NAME_TYPES = frozenset({MATCH_EXACT, MATCH_NORMALIZED})


def _non_drug_name(value: str, ctx: ToolContext) -> bool:
    """`identify_drug` 인자가 비약 토큰(시각·횟수·수량 표현뿐)인가. 사전에 이름이 **정확·정규화로 같으면** 약 이름이라 허용한다.
    Router의 보호(접두·중간 일치까지)보다 좁다: 수량 토큰("500밀리그람")은 제품명 중간에 우연히 들어 있어(`contains`) 넓은 보호가 거절을 무력화한다.
    제품명 일부로 적은 토큰은 Router가 후보로 남기고(접두 보호) 도구는 사전 이름 그대로를 받는다."""
    if not is_non_drug_token(value):
        return False
    res = ctx.drug_dict.lookup_name(value, top_k=1)
    return not (not res.empty and res.match_type in _EXACT_NAME_TYPES)


def invoke(name: str, raw_args: dict[str, Any], ctx: ToolContext, registry: dict[str, ToolSpec] | None = None) -> dict[str, Any]:
    """도구 호출 1건. 반환: `{"items": [...], ...}`(+ `text` 데이터 블록, `contract_violations`, `writable`)."""
    spec = (registry or REGISTRY).get(name)
    if spec is None:
        return {"items": [], "blocked": True, "error": {
            "code": "UNKNOWN_TOOL", "tool": name, "reason": "등록되지 않은 도구", "next_action": "등록된 도구 이름으로 호출한다",
            "remaining_calls": max(ctx.remaining_calls, 0)}}
    ignored = [k for k in IGNORED_ARGS.get(name, ()) if isinstance(raw_args, dict) and k in raw_args]
    if ignored:
        raw_args = {k: v for k, v in raw_args.items() if k not in ignored}
    try:
        args = spec.args_model.model_validate(raw_args)
    except ValidationError as e:
        return arg_schema_error(name, e, ctx.remaining_calls)  # 본문 실행 없음
    if name == "identify_drug" and ctx.identify_arg_check and _non_drug_name(args.name, ctx):
        # AG-13-44 C-2: 약 이름 자리에 시각·횟수·수량 표현뿐인 값이 왔다. 도구 본문(사전 조회)을 실행하지 않고 기존 `ARG_SCHEMA` 응답으로 막는다
        return arg_schema_response(name, ["name: non_drug_token"], ctx.remaining_calls)
    out = spec.func(args, ctx)
    items = out["items"]
    out["contract_violations"] = check_items(name, items)
    out["text"] = render_data_block(name, items)
    out["writable"] = writable_update(out)
    if ignored:  # 개수만(인자 값은 남기지 않는다)
        out["writable"]["events"].append({"rule": "H21", "event": EVENT_ARG_IGNORED, "tool": name, "n": len(ignored)})
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
