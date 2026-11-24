"""도구가 쓰는 주입 의존성. 외부 호출(DB·API·LLM)은 전부 여기로 주입하고, 시험은 가짜를 넣는다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.tools.drug_dict import DrugDict
from app.tools.dur import DurResult

# (api 성분코드 A, api 성분코드 B) → 병용금기 조회 결과(BE-03 `DurClient.usjnt_pair_by_ingredient` 형식)
ApiPairFn = Callable[[str, str], DurResult]
# api 성분코드 → 그 성분의 연령·임부 금기 조회 결과(BE-03 `DurClient.by_ingredient("age"|"pregnancy", code)` 형식)
ApiIngredientFn = Callable[[str], DurResult]


def ingredient_api_fns(client: Any) -> tuple[ApiIngredientFn, ApiIngredientFn]:
    """`DurClient`(또는 같은 `by_ingredient(kind, code)`를 가진 객체)를 (연령 함수, 임부 함수)로 감싸는 어댑터. 호출 자체는 클라이언트가 한다."""
    return (lambda code: client.by_ingredient("age", code)), (lambda code: client.by_ingredient("pregnancy", code))


class LabelProvider(Protocol):
    """허가 상세·e약은요 원문 공급자. 없으면 None, 가져오지 못하면 예외(`FETCH_FAIL`)."""

    def eyak(self, item_seq: str) -> dict[str, Any] | None: ...  # {"item": e약은요 항목 dict, "collected_at": str, "source": "snapshot|live|cache"}

    def prmsn_detail(self, item_seq: str) -> dict[str, Any] | None: ...  # {"item": 허가 상세 dict, "collected_at": str, "source": ...}


@dataclass
class ToolContext:
    drug_dict: DrugDict
    conn_factory: Callable[[], Any] | None = None  # DB 연결 팩토리(호출마다 새 연결, 호출자가 닫는다)
    paramstyle: str = "qmark"
    api_enabled: bool = True                      # 평가 모드에서는 False(RFP 5.1절 (7), BE-08): API 호출 없음, 꼬리표 없음
    api_pair_fn: ApiPairFn | None = None
    api_age_fn: ApiIngredientFn | None = None            # 성분 단위 연령금기 API 병기(AG-02 후속). None이면 API_FAIL 꼬리표
    api_pregnancy_fn: ApiIngredientFn | None = None     # 성분 단위 임부금기 API 병기
    label_provider: LabelProvider | None = None
    corpus: Any = None                            # AG-03 `CorpusIndex`(로컬 청크 인덱스). None이면 검색 도구는 OUT_OF_SCOPE
    vector_search_fn: Any = None                  # AG-03 `VectorSearchFn`(주입, 원격 pgvector 어댑터). None이면 BM25 단독
    remaining_calls: int = 6                      # ARG_SCHEMA 메시지에 알릴 남은 도구 호출 수(H21, 그래프가 갱신)
    # 이번 요청에서 조회할 주의 종류(AG-22-04 A, `intake.caution_kinds`). 그래프 `tools` 노드가 상태로 갱신한다(요청마다 새 ToolContext).
    # 비어 있으면 주의 3종을 조회하지 않는다(LLM 인자 `include_cautions`는 없앴다, C-1 A)
    caution_kinds: frozenset[str] = frozenset()
    # 안전장치·표시 정리 스위치(AG-13-44·AG-13-46 b, 2026-11-24). 그래프 `tools` 노드가 `GraphDeps`의 스위치 값을 호출마다 옮겨 적는다.
    # 이 dataclass의 기본값은 False(이전 동작)라 `ToolContext`만 만들어 부르는 시험·스크립트는 달라지지 않는다. 켜는 곳은 `GraphDeps`(기본 켬)다
    identify_arg_check: bool = False   # `identify_drug` 인자가 시각·횟수·수량 표현뿐이면 `ARG_SCHEMA`로 거절(사전 이름과 일치하면 허용)
    display_name_fix: bool = False     # 판정하지 못한 약의 표시명을 사전 제품명 또는 `원문 → 제품명`으로(코드·제품 단위 식별 표시명 정정)
