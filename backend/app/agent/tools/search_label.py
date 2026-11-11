"""`search_label`: 품목 허가사항·e약은요 쉬운 설명(L3) 문장을 찾는다.

- 대상 문서: 의약품 제품 허가정보 허가 상세(효능효과·용법용량·사용상의주의사항 문단·표)와 e약은요(효능·사용법·경고·주의사항·상호작용·이상반응).
- 쓰는 질문 유형 예시: ① "이 약은 어떤 증상에 쓰나요?"(품목기준코드 `item_seq` + 효능) ② "이 약과 술을 같이 먹어도 되나요?"(주의사항·상호작용 문장 검색).
- 경계: 제품 단위 문서다. 성분코드만 있으면 라벨이 없어 `NO_EVIDENCE`(`NO_PRODUCT_INFO`)로 돌려준다(H17). 병용·임부·연령 금기 판정은 `check_contraindications`,
  절 하나의 원문 전체는 `get_label_section`, 고시는 `search_notice`, 사유 상세는 `search_reason`. 용법용량은 허가사항 원문 인용용이고 요약에 숫자를 쓰지 않는다.
- `item_seq`와 `section`을 주면 문단 번호 순으로 **절 전체**를 붙여 돌려준다(H16). e약은요 쉬운 설명이 없는 품목은 `EASY_TEXT_MISSING`을 단다(H18).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.corpus import ChunkFilter
from app.agent.tools.schemas import DUR_CODE_RE, ITEM_SEQ_RE, KIDS_CODE_RE, SectionName
from app.agent.tools.search_common import DEFAULT_TOP_K, MAX_TOP_K, miss_item, no_control, run_search

TOOL = "search_label"
# 절 이름 → (e약은요 절 이름들, 허가 상세 절 코드 접두)
SECTION_MAP: dict[str, tuple[frozenset[str], str | None]] = {
    "효능": (frozenset({"효능"}), "EE"),
    "용법용량": (frozenset({"사용법"}), "UD"),
    "사용법": (frozenset({"사용법"}), None),
    "경고": (frozenset({"경고"}), None),
    "주의사항": (frozenset({"주의사항"}), "NB"),
    "상호작용": (frozenset({"상호작용"}), None),
    "부작용": (frozenset({"이상반응"}), None),
}


class SearchLabelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=200)
    item_seq: str | None = None
    ingredient_code: str | None = None  # 성분코드로 불리면 라벨이 없다(H17)
    section: SectionName | None = None
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)

    @field_validator("query")
    @classmethod
    def _q(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = no_control(v.strip())
        return v or None

    @field_validator("item_seq")
    @classmethod
    def _seq(cls, v: str | None) -> str | None:
        if v is not None and not ITEM_SEQ_RE.match(v):
            raise ValueError("품목기준코드는 숫자 9자리")
        return v

    @field_validator("ingredient_code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and not (KIDS_CODE_RE.match(v) or DUR_CODE_RE.match(v)):
            raise ValueError("성분코드 형식 아님")
        return v

    @model_validator(mode="after")
    def _need(self) -> SearchLabelArgs:
        if not (self.query or self.item_seq or self.ingredient_code):
            raise ValueError("질의·품목기준코드·성분코드 중 하나가 필요하다")
        return self


def build_filter(args: SearchLabelArgs) -> ChunkFilter:
    secs, prefix = SECTION_MAP[args.section] if args.section else (None, None)
    return ChunkFilter(layers=frozenset({"L3"}), item_seq=args.item_seq, sections=secs, section_prefix=prefix)


def search_label(args: SearchLabelArgs, ctx: ToolContext) -> dict[str, Any]:
    if args.ingredient_code and not args.item_seq:  # 성분 단위에는 제품 라벨이 없다(H17). 코드를 되풀이하지 않고 틀 그대로 돌려준다
        items = [miss_item(TOOL, {"ingredient_code": True}, reason="OUT_OF_SCOPE", flags=["NO_PRODUCT_INFO"])]
        items[0]["matched_by"] = "ingredient_code"
        return {"items": items, "known_ids": sorted(known_ids(items))}
    index = ctx.corpus

    def label_flags(c: dict[str, Any]) -> list[str]:
        if index is None or c.get("layer") != "L3" or not c.get("item_seq") or c.get("doc_type") == "e약은요":
            return []
        has_easy = bool(index.candidates(ChunkFilter(item_seq=c["item_seq"], doc_types=frozenset({"e약은요"}))))
        return [] if has_easy else ["EASY_TEXT_MISSING"]  # 허가 상세만 있는 품목(전문의약품 등, H18)

    return run_search(TOOL, ctx, query=args.query or "", flt=build_filter(args), top_k=args.top_k, miss_key=args.model_dump(), expand=True, label=True,
                      label_flags_for=label_flags)
