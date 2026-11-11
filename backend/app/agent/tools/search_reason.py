"""`search_reason`: 병용금기 사유·임부금기·연령금기 **상세정보**(L2, 한국의약품안전관리원 파일 데이터)를 찾는다.

- 대상 문서: 병용금기 성분쌍 사유 청크, 임부금기 성분별 등급·상세정보 청크, 연령금기 성분별 상세정보 청크.
- 쓰는 질문 유형 예시: ① "이 두 약이 왜 같이 먹으면 안 되나요?"(판정된 성분쌍 `pair_ids`로 사유 설명) ② "이 성분의 임부금기 상세정보는 무엇인가요?"(`ingr_codes` 필터).
- 경계: 금기 **여부 판정**은 `check_contraindications`(성분코드 정확 일치)가 한다. 이 도구는 판정된 성분의 사유 문장을 찾아 인용한다.
  고시 조문·별표는 `search_notice`, 제품 라벨은 `search_label`. 임부금기 `M` 등급은 상세정보 원문 그대로 돌려주며 1·2등급으로 바꾸지 않는다.
- `pair_ids`를 주면 쌍마다 일괄로 찾는다(질의는 선택). 사유 청크가 없는 쌍은 `NO_EVIDENCE`이고 안전하다는 뜻이 아니다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.corpus import ChunkFilter
from app.agent.tools.schemas import KIDS_CODE_RE
from app.agent.tools.search_common import DEFAULT_TOP_K, MAX_ITEMS, MAX_TOP_K, miss_item, no_control, run_search
from app.agent.tools.search_common import items_from_hits as _items_from_hits

TOOL = "search_reason"
MAX_PAIRS = 28  # 약 8개의 쌍 수 상한(AG-02와 같다)
_KIND_MAP = {"combo": "l2_combo", "pregnancy": "l2_preg", "age": "l2_age"}
PER_PAIR = 3


def normalize_pair_id(v: str) -> str:
    """`a+b`·`b+a` 모두 정렬된 `lo+hi`로. KIDS 성분코드 두 개가 아니면 오류."""
    parts = v.split("+")
    if len(parts) != 2 or not all(KIDS_CODE_RE.match(p) for p in parts):
        raise ValueError("pair_id는 KIDS 성분코드 두 개를 +로 이은 값")
    return "+".join(sorted(parts))


class SearchReasonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=200)
    ingr_codes: list[str] | None = Field(default=None, min_length=1, max_length=8)
    pair_ids: list[str] | None = Field(default=None, min_length=1, max_length=MAX_PAIRS)
    kinds: list[Literal["combo", "pregnancy", "age"]] | None = Field(default=None, min_length=1, max_length=3)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)

    @field_validator("query")
    @classmethod
    def _q(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = no_control(v.strip())
        return v or None

    @field_validator("ingr_codes")
    @classmethod
    def _codes(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and not all(KIDS_CODE_RE.match(c) for c in v):
            raise ValueError("성분코드 형식 아님")
        return v

    @field_validator("pair_ids")
    @classmethod
    def _pairs(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else sorted({normalize_pair_id(p) for p in v})

    @model_validator(mode="after")
    def _need_one(self) -> SearchReasonArgs:
        if not (self.query or self.ingr_codes or self.pair_ids):
            raise ValueError("질의·성분코드·성분쌍 중 하나가 필요하다")
        return self


def build_filter(args: SearchReasonArgs, *, pair: str | None = None) -> ChunkFilter:
    pairs = frozenset({pair}) if pair else (frozenset(args.pair_ids) if args.pair_ids else None)
    kinds = frozenset(_KIND_MAP[k] for k in args.kinds) if args.kinds else None
    return ChunkFilter(layers=frozenset({"L2"}), chunk_kinds=kinds, ingr_codes=frozenset(args.ingr_codes) if args.ingr_codes else None, pair_ids=pairs)


def search_reason(args: SearchReasonArgs, ctx: ToolContext) -> dict[str, Any]:
    if not args.pair_ids or ctx.corpus is None:
        return run_search(TOOL, ctx, query=args.query or "", flt=build_filter(args), top_k=args.top_k, miss_key=args.model_dump(), expand=True)
    # 성분쌍 일괄: 쌍마다 따로 찾아 한 묶음으로. 질의가 있으면 쌍 안에서 순위를 매긴다.
    items: list[dict[str, Any]] = []
    for p in args.pair_ids:
        hits = ctx.corpus.search(args.query or "", build_filter(args, pair=p), top_k=min(args.top_k, PER_PAIR), vector_fn=ctx.vector_search_fn)
        items += _items_from_hits(TOOL, ctx.corpus, hits, miss_key={"pair_id": p}, expand=False)
    items = items[:MAX_ITEMS] if items else [miss_item(TOOL, args.model_dump())]
    return {"items": items, "known_ids": sorted(known_ids(items))}
