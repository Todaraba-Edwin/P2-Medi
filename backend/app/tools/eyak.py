"""e약은요(의약품개요정보) 조회 도구(BE-02, FR-02).

- 제품명(포함 검색)·품목기준코드로 조회하고 응답을 `EasyDrugInfo`로 정리한다.
- 효능·사용법·경고·주의사항·상호작용·부작용 문장형 필드는 원문 그대로 보존한다(앞뒤 공백·개행도 고치지 않는다).
- 결과마다 조회 시각(UTC ISO와 한국 표시용)과 캐시 여부를 담는다.
- 실패(호출 제한·타임아웃 등)는 예외가 아니라 `EyakResult.error`로 돌려준다(도구 호출이 그래프를 깨지 않게).
- 성분 필드는 e약은요에 없다. 성분은 DUR 품목정보와 `itemSeq`로 잇는다(BE-03).
- 전문의약품은 e약은요에 없다(0건). 0건은 "e약은요에 없음"일 뿐 안전하다는 뜻이 아니다.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, field_validator

from app.tools._http import (
    ApiError,
    ApiHttpClient,
    ApiResponse,
    cache_from_settings,
    extract_items,
    format_display,
    format_utc,
)

SERVICE_ALIAS = "eyak"
OPERATION = "getDrbEasyDrugList"
SOURCE_NAME = "식약처 e약은요(의약품개요정보)"
MAX_NAME_LEN = 100
MAX_ROWS = 100

# 문장형 라벨 필드: 필드 이름 → 표시용 한글 이름. 원문 인용과 retrieval의 원천이다.
LABEL_FIELDS: dict[str, str] = {
    "efcy": "효능",
    "use_method": "사용법",
    "atpn_warn": "경고",
    "atpn": "주의사항",
    "intrc": "상호작용",
    "se": "부작용",
}


def _parse_date(value: str | None) -> date | None:
    """`20241231` 또는 `2026-10-22`. 다른 형식은 None(원문은 그대로 남아 있다)."""
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


class EasyDrugInfo(BaseModel):
    """의약품 개요 한 건(필드 14개, `P2-doc/PJ2-API-엔티티.md` 3장)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    item_seq: str = Field(alias="itemSeq", description="품목기준코드(다른 서비스와 잇는 키)")
    item_name: str | None = Field(None, alias="itemName")
    entp_name: str | None = Field(None, alias="entpName")
    efcy: str | None = Field(None, alias="efcyQesitm")
    use_method: str | None = Field(None, alias="useMethodQesitm")
    atpn_warn: str | None = Field(None, alias="atpnWarnQesitm")
    atpn: str | None = Field(None, alias="atpnQesitm")
    intrc: str | None = Field(None, alias="intrcQesitm")
    se: str | None = Field(None, alias="seQesitm")
    deposit_method: str | None = Field(None, alias="depositMethodQesitm")
    open_de: str | None = Field(None, alias="openDe", description="공개일자 원문(YYYYMMDD)")
    update_de: str | None = Field(None, alias="updateDe", description="수정일자 원문(YYYY-MM-DD)")
    item_image: str | None = Field(None, alias="itemImage")
    bizrno: str | None = Field(None, alias="bizrno")

    @field_validator("item_seq", mode="before")
    @classmethod
    def _seq_to_str(cls, v: Any) -> Any:
        return str(v).strip() if isinstance(v, (int, str)) and str(v).strip() else v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open_date(self) -> date | None:
        return _parse_date(self.open_de)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def update_date(self) -> date | None:
        return _parse_date(self.update_de)

    def label_sections(self) -> dict[str, str]:
        """값이 있는 문장형 필드를 `{한글 이름: 원문}`으로 돌려준다(근거 상세·인용용)."""
        return {label: getattr(self, name) for name, label in LABEL_FIELDS.items() if getattr(self, name)}


class ToolError(BaseModel):
    """도구가 돌려주는 오류 객체. 인증키·URL은 들어가지 않는다."""

    kind: str
    message: str
    http_status: int | None = None
    result_code: str | None = None
    retryable: bool = False

    @classmethod
    def from_api_error(cls, err: ApiError) -> "ToolError":
        return cls(**err.as_dict())


class EyakResult(BaseModel):
    """e약은요 조회 결과. `ok=False`이면 `error`를 본다."""

    ok: bool
    items: list[EasyDrugInfo] = Field(default_factory=list)
    total_count: int = 0
    page_no: int = 1
    num_of_rows: int = MAX_ROWS
    query: dict[str, str] = Field(default_factory=dict)
    source_name: str = SOURCE_NAME
    queried_at_utc: str | None = Field(None, description="공공 API에서 이 데이터를 받은 시각(UTC ISO 8601, 캐시면 처음 받은 시각)")
    queried_at_display: str | None = None
    from_cache: bool = False
    source: Literal["live", "cache", "snapshot"] | None = None
    error: ToolError | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def empty(self) -> bool:
        """정상 응답인데 0건. 전문의약품이면 e약은요에 없는 것이 정상이다."""
        return self.ok and self.total_count == 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_more(self) -> bool:
        return self.ok and self.page_no * self.num_of_rows < self.total_count


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip(): v for k, v in raw.items()}   # 끝 공백이 붙은 키를 다듬는다(값은 그대로)


class EyakClient:
    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "EyakClient":
        """환경변수(`app.config`)로 만든다. `DRDEASYDRUG_END_POINT`·`DRDEASYDRUG_API_KEY`는 설정 모듈로만 읽는다."""
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        http = ApiHttpClient(
            SERVICE_ALIAS,
            settings.drdeasydrug_end_point,
            settings.drdeasydrug_api_key,
            mode="snapshot" if settings.mediagent_api_mode == "snapshot" else "live",
            cache=cache_from_settings(settings),
            max_calls=settings.mediagent_api_max_calls,
        )
        return cls(http)

    # ---- 조회 ----
    def search_by_name(self, item_name: str, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> EyakResult:
        """제품명에 그 글자가 들어간 품목을 찾는다(포함 검색, 성분명 검색이 아니다)."""
        name = (item_name or "").strip()
        if not name or len(name) > MAX_NAME_LEN or re.search(r"[\x00-\x1f]", name):
            return self._invalid("제품명은 1~100자의 한 줄 문자열이어야 합니다.", page_no, num_of_rows)
        return self._query({"itemName": name}, page_no, num_of_rows)

    def get_by_item_seq(self, item_seq: str) -> EyakResult:
        """품목기준코드(9자리)로 한 품목을 조회한다."""
        seq = str(item_seq or "").strip()
        if not re.fullmatch(r"\d{9}", seq):
            return self._invalid("품목기준코드는 숫자 9자리여야 합니다.", 1, MAX_ROWS)
        return self._query({"itemSeq": seq}, 1, MAX_ROWS)

    def list_page(self, *, page_no: int = 1, num_of_rows: int = MAX_ROWS) -> EyakResult:
        """필터 없이 전체 목록의 한 쪽(전체 건수·페이지 이동 확인용, BE-12 수집 보조)."""
        return self._query({}, page_no, num_of_rows)

    # ---- 내부 ----
    @staticmethod
    def _invalid(message: str, page_no: int, num_of_rows: int) -> EyakResult:
        err = ApiError("invalid_request", message)
        return EyakResult(ok=False, page_no=_to_int(page_no, 1), num_of_rows=_to_int(num_of_rows, MAX_ROWS), error=ToolError.from_api_error(err))

    def _query(self, filters: dict[str, str], page_no: int, num_of_rows: int) -> EyakResult:
        if not isinstance(page_no, int) or isinstance(page_no, bool) or page_no < 1 or not isinstance(num_of_rows, int) or isinstance(num_of_rows, bool) or not 1 <= num_of_rows <= MAX_ROWS:
            return self._invalid(f"페이지는 1 이상, 한 쪽 건수는 1~{MAX_ROWS}이어야 합니다.", 1, MAX_ROWS)
        params = {**filters, "pageNo": page_no, "numOfRows": num_of_rows}
        query = {k: str(v) for k, v in params.items()}
        try:
            resp = self._http.get(OPERATION, params)
            return self._build(resp, query)
        except ApiError as err:
            return EyakResult(ok=False, page_no=page_no, num_of_rows=num_of_rows, query=query, error=ToolError.from_api_error(err))

    @staticmethod
    def _build(resp: ApiResponse, query: dict[str, str]) -> EyakResult:
        body = resp.body
        try:
            items = [EasyDrugInfo.model_validate(_normalize_item(r)) for r in extract_items(body)]
        except ValidationError:
            raise ApiError("parse", "응답 품목의 필수 필드(itemSeq)를 읽지 못했습니다.") from None
        return EyakResult(
            ok=True,
            items=items,
            total_count=_to_int(body.get("totalCount"), len(items)),
            page_no=_to_int(body.get("pageNo"), int(query["pageNo"])),
            num_of_rows=_to_int(body.get("numOfRows"), int(query["numOfRows"])),
            query=query,
            queried_at_utc=format_utc(resp.fetched_at),
            queried_at_display=format_display(resp.fetched_at),
            from_cache=resp.from_cache,
            source=resp.source,
        )
