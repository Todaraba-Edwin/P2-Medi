"""도구가 쓰는 주입 의존성. 외부 호출(DB·API·LLM)은 전부 여기로 주입하고, 시험은 가짜를 넣는다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.tools.drug_dict import DrugDict
from app.tools.dur import DurResult

# (api 성분코드 A, api 성분코드 B) → 병용금기 조회 결과(BE-03 `DurClient.usjnt_pair_by_ingredient` 형식)
ApiPairFn = Callable[[str, str], DurResult]


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
    label_provider: LabelProvider | None = None
    remaining_calls: int = 6                      # ARG_SCHEMA 메시지에 알릴 남은 도구 호출 수(H21, 그래프가 갱신)
