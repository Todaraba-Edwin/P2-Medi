"""`search_notice`: 고시 조문·정의·별표 행(L1)을 찾는다.

- 대상 문서: 「의약품 병용금기 성분 등의 지정에 관한 규정」(식약처 고시)의 조·호·목과 별표 1(병용금기)·2(특정연령대)·3(임부금기) 행.
- 쓰는 질문 유형 예시: ① "임부금기 1등급은 고시에서 어떻게 정의하나요?"(정의 조문) ② "별표 3에 에날라프릴이 있나요?"(별표 행, 성분명 필터).
- 경계: 병용·임부·연령 금기 **판정**은 `check_contraindications`가 한다. 사례별 금기 사유 설명은 `search_reason`, 제품 허가사항·쉬운 설명은 `search_label`이 맡는다.
  이 도구는 고시 문구를 찾아 인용할 뿐 금기 여부를 말하지 않는다.
- 결과는 `notice_no`·`locator`(조항·별표 연번)를 단 항목이다. 찾은 청크의 부모(표·조문)·참조(별표 N)는 코드가 붙인다.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.tools.context import ToolContext
from app.agent.tools.corpus import ChunkFilter
from app.agent.tools.search_common import DEFAULT_TOP_K, MAX_TOP_K, Query, no_control, run_search

TOOL = "search_notice"
NOTICE_NO_RE = re.compile(r"^[0-9]{8}$")  # 연도 4자리 + 번호 4자리
_ANNEX_KINDS = {1: ("l1_bupyo1_table", "l1_bupyo1_row"), 2: ("l1_bupyo2_table", "l1_bupyo2_row"), 3: ("l1_bupyo3_table", "l1_bupyo3_row")}
_ARTICLE_KINDS = ("l1_notice_article", "l1_notice_item", "l1_notice_sub")


class SearchNoticeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Query
    notice_no: str | None = None
    scope: Literal["article", "annex1", "annex2", "annex3"] | None = None  # 조문류 / 별표 1·2·3
    ingr_names: list[Query] | None = Field(default=None, max_length=4)    # 별표 행의 성분명(영문·부분 일치)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)

    @field_validator("query")
    @classmethod
    def _q(cls, v: str) -> str:
        return no_control(v)

    @field_validator("ingr_names")
    @classmethod
    def _names(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [no_control(x) for x in v]

    @field_validator("notice_no")
    @classmethod
    def _no(cls, v: str | None) -> str | None:
        if v is not None and not NOTICE_NO_RE.match(v):
            raise ValueError("고시번호는 숫자 8자리")
        return v


def build_filter(args: SearchNoticeArgs) -> ChunkFilter:
    kinds: frozenset[str] | None = None
    if args.scope == "article":
        kinds = frozenset(_ARTICLE_KINDS)
    elif args.scope:
        kinds = frozenset(_ANNEX_KINDS[int(args.scope[-1])])
    return ChunkFilter(layers=frozenset({"L1"}), chunk_kinds=kinds, notice_no=args.notice_no,
                       ingr_names=frozenset(args.ingr_names) if args.ingr_names else None)


def search_notice(args: SearchNoticeArgs, ctx: ToolContext) -> dict[str, Any]:
    flt = build_filter(args)
    return run_search(TOOL, ctx, query=args.query, flt=flt, top_k=args.top_k, miss_key=args.model_dump(), expand=True)
