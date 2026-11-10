"""의약품 제품 허가정보 조회 도구(BE-12).

- 제품명(포함 검색)·품목기준코드로 허가 품목 목록·상세를 조회한다.
- 주성분 상세(제품당 성분 행)는 제품명으로 조회한다.
- 오퍼레이션:
  - getDrugPrdtPrmsnInq08(목록): 필터 item_name(포함), item_seq(정확)
  - getDrugPrdtPrmsnDtlInq08(상세): 필터 item_seq(정확), item_name(포함)
  - getDrugPrdtMcpnDtlInq08(성분): 필터 Prduct(제품명 정확 일치, 대문자 P)
- 결과마다 조회 시각(UTC ISO와 한국 표시용)과 캐시 여부를 담는다.
- 실패(호출 제한·타임아웃 등)는 예외가 아니라 `PrmsnResult.error`로 돌려준다.
- 전체 건수는 1쪽의 `totalCount`와 재개 때 페이지 단위 합산용이다.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.tools._http import (
    ApiError,
    ApiHttpClient,
    ApiResponse,
    cache_from_settings,
    extract_items,
    format_display,
    format_utc,
)

SERVICE_ALIAS = "drug-prmsn"
MAX_NAME_LEN = 100
MAX_ROWS = 100

# 오퍼레이션 목록(수집 스크립트에서 쓴다)
OPERATIONS = {
    "list": "getDrugPrdtPrmsnInq08",
    "detail": "getDrugPrdtPrmsnDtlInq08",
    "ingredients": "getDrugPrdtMcpnDtlInq08",
}


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ToolError(BaseModel):
    """도구가 돌려주는 오류 객체. 인증키·URL은 들어가지 않는다."""

    kind: str
    message: str
    http_status: int | None = None
    result_code: str | None = None
    retryable: bool = False

    @classmethod
    def from_api_error(cls, err: ApiError) -> ToolError:
        return cls(**err.as_dict())


class PrmsnItem(BaseModel):
    """허가 목록 한 건(필드 14개 정도, `P2-doc/PJ2-API-엔티티.md` §9 참조)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    item_seq: str = Field(alias="ITEM_SEQ", description="품목기준코드(9자리, 다른 서비스와 잇는 키)")
    item_name: str | None = Field(None, alias="ITEM_NAME")
    entp_name: str | None = Field(None, alias="ENTP_NAME")
    item_permit_date: str | None = Field(None, alias="ITEM_PERMIT_DATE", description="허가일(YYYYMMDD)")
    spclty_pblc: str | None = Field(None, alias="SPCLTY_PBLC", description="전문/일반 구분")
    prduct_type: str | None = Field(None, alias="PRDUCT_TYPE", description="분류(`[01140]해열.진통.소염제`)")
    item_ingr_name: str | None = Field(None, alias="ITEM_INGR_NAME", description="영문 성분명(한국어 아님)")
    edi_code: str | None = Field(None, alias="EDI_CODE", description="EDI 코드(KIDS 연결 후보)")
    cancel_name: str | None = Field(None, alias="CANCEL_NAME", description="취하/취소 상태(정상/취소 등)")

    @field_validator("item_seq", mode="before")
    @classmethod
    def _seq_to_str(cls, v: Any) -> Any:
        return str(v).strip() if isinstance(v, (int, str)) and str(v).strip() else v


class PrmsnResult(BaseModel):
    """허가정보 조회 결과. `ok=False`이면 `error`를 본다."""

    ok: bool
    items: list[PrmsnItem] = Field(default_factory=list)
    raw_items: list[dict[str, Any]] = Field(default_factory=list, description="응답 항목 원본(상세 API의 효능·용법·주의사항 등 모델에 없는 필드 보존)")
    total_count: int = 0
    page_no: int = 1
    num_of_rows: int = MAX_ROWS
    query: dict[str, str] = Field(default_factory=dict)
    request_hash: str | None = None
    queried_at_utc: str | None = Field(None, description="공공 API에서 이 데이터를 받은 시각(UTC ISO 8601)")
    queried_at_display: str | None = None
    from_cache: bool = False
    source: Literal["live", "cache", "snapshot"] | None = None
    error: ToolError | None = None


class PrmsnClient:
    """허가정보 API 클라이언트."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> PrmsnClient:
        """환경변수(`app.config`)로 만든다. `DrugPrdtPrmsnInfoService08_END_POINT`·`DrugPrdtPrmsnInfoService08_API_KEY`는 설정 모듈로만 읽는다."""
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        http = ApiHttpClient(
            SERVICE_ALIAS,
            settings.drugprdtprmsninfoservice08_end_point,
            settings.drugprdtprmsninfoservice08_api_key,
            mode="snapshot" if settings.mediagent_api_mode == "snapshot" else "live",
            cache=cache_from_settings(settings),
            max_calls=settings.mediagent_api_max_calls,
        )
        return cls(http)

    # ---- 조회 ----
    def list_by_name(self, item_name: str, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> PrmsnResult:
        """제품명에 그 글자가 들어간 품목을 찾는다(포함 검색)."""
        name = (item_name or "").strip()
        if not name or len(name) > MAX_NAME_LEN or re.search(r"[\x00-\x1f]", name):
            return self._invalid("제품명은 1~100자의 한 줄 문자열이어야 합니다.", page_no, num_of_rows)
        return self._query(OPERATIONS["list"], {"item_name": name}, page_no, num_of_rows)

    def list_by_item_seq(self, item_seq: str, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> PrmsnResult:
        """품목기준코드(9자리)로 조회한다."""
        seq = str(item_seq or "").strip()
        if not re.fullmatch(r"\d{9}", seq):
            return self._invalid("품목기준코드는 숫자 9자리여야 합니다.", 1, MAX_ROWS)
        return self._query(OPERATIONS["list"], {"item_seq": seq}, page_no, num_of_rows)

    def detail_by_item_seq(self, item_seq: str) -> PrmsnResult:
        """품목기준코드로 상세 정보를 조회한다. 응답은 1건 또는 0건."""
        seq = str(item_seq or "").strip()
        if not re.fullmatch(r"\d{9}", seq):
            return self._invalid("품목기준코드는 숫자 9자리여야 합니다.", 1, MAX_ROWS)
        return self._query(OPERATIONS["detail"], {"item_seq": seq}, 1, MAX_ROWS)

    def ingredients_by_product(self, product_name: str, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> PrmsnResult:
        """제품명(정확 일치, 대문자 P)으로 성분 정보를 조회한다."""
        name = (product_name or "").strip()
        if not name or len(name) > MAX_NAME_LEN or re.search(r"[\x00-\x1f]", name):
            return self._invalid("제품명은 1~100자의 한 줄 문자열이어야 합니다.", page_no, num_of_rows)
        return self._query(OPERATIONS["ingredients"], {"Prduct": name}, page_no, num_of_rows)

    def list_page(self, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> PrmsnResult:
        """필터 없이 전체 목록의 한 쪽(수집용, 첫 쪽의 totalCount로 전체 건수를 알 수 있다)."""
        return self._query(OPERATIONS["list"], {}, page_no, num_of_rows)

    # ---- 내부 ----
    @staticmethod
    def _invalid(message: str, page_no: int, num_of_rows: int) -> PrmsnResult:
        err = ApiError("invalid_request", message)
        return PrmsnResult(
            ok=False,
            page_no=_to_int(page_no, 1),
            num_of_rows=_to_int(num_of_rows, MAX_ROWS),
            error=ToolError.from_api_error(err),
        )

    def _query(self, operation: str, filters: dict[str, str], page_no: int, num_of_rows: int) -> PrmsnResult:
        if (
            not isinstance(page_no, int)
            or isinstance(page_no, bool)
            or page_no < 1
            or not isinstance(num_of_rows, int)
            or isinstance(num_of_rows, bool)
            or not 1 <= num_of_rows <= MAX_ROWS
        ):
            return self._invalid(f"페이지는 1 이상, 한 쪽 건수는 1~{MAX_ROWS}이어야 합니다.", 1, MAX_ROWS)
        params = {**filters, "pageNo": page_no, "numOfRows": num_of_rows}
        query = {k: str(v) for k, v in params.items()}
        try:
            resp = self._http.get(operation, params)
            return self._build(resp, query, operation)
        except ApiError as err:
            return PrmsnResult(ok=False, page_no=page_no, num_of_rows=num_of_rows, query=query, error=ToolError.from_api_error(err))

    @staticmethod
    def _build(resp: ApiResponse, query: dict[str, str], operation: str) -> PrmsnResult:
        body = resp.body
        try:
            items = [PrmsnItem.model_validate(r) for r in extract_items(body)]
        except ValidationError:
            raise ApiError("parse", "응답 품목의 필수 필드(ITEM_SEQ)를 읽지 못했습니다.") from None
        return PrmsnResult(
            ok=True,
            items=items,
            raw_items=[dict(r) for r in extract_items(body)],
            total_count=_to_int(body.get("totalCount"), len(items)),
            page_no=_to_int(body.get("pageNo"), int(query["pageNo"])),
            num_of_rows=_to_int(body.get("numOfRows"), int(query["numOfRows"])),
            query=query,
            request_hash=resp.request_hash,
            queried_at_utc=format_utc(resp.fetched_at),
            queried_at_display=format_display(resp.fetched_at),
            from_cache=resp.from_cache,
            source=resp.source,
        )
