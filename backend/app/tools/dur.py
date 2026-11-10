"""식약처 DUR 조회 도구(BE-03, FR-02): 병용·연령·임부 금기, 품목 단위와 성분 단위.

- 판정의 1차는 파일(BE-09 `lookup.py`)이다. 이 모듈은 API로 **병기·교차 점검**한다(RFP 5.1절 (7)).
- 공통 HTTP·캐시·조회 시각 계층(`_http.py`)과 `ToolError`(`eyak.py`)를 그대로 쓴다.
- 임부금기 `GRADE`·`PROHBT_CONTENT`는 원문 그대로 둔다(M·1·2로 바꾸지 않는다). 품목정보에는 `GRADE`·`AGE_BASE`가 없다.
- 성분정보 병용금기는 쌍의 A쪽 성분 기준으로만 나오므로 쌍 조회는 **양쪽 성분을 모두 조회**한다(BE-03 메모 2026-11-05).
  한쪽이라도 실패하면 "없음"으로 말하지 않고 오류로 돌려준다.
- 0건은 "API 목록에 없음"이지 안전하다는 뜻이 아니다. 고시일자는 파일과 다를 수 있어 둘 다 보여 주고
  "API가 더 최신"이라고 단정하지 않는다.
- 실패는 예외가 아니라 `DurResult.error`로 돌려준다(도구 호출이 그래프를 깨지 않게).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.tools._http import (
    ApiError,
    ApiHttpClient,
    ApiResponse,
    cache_from_settings,
    extract_items,
    format_display,
    format_utc,
)
from app.tools.eyak import ToolError

ITEM_ALIAS = "dur-item"      # DURPrdlstInfoService03 (품목 단위)
INGR_ALIAS = "dur-ingr"      # DURIrdntInfoService03 (성분 단위)
SOURCE_ITEM = "식약처 DUR 품목정보"
SOURCE_INGR = "식약처 DUR 성분정보"
MAX_ROWS = 100
DEFAULT_MAX_PAGES = 10        # 한 조회에서 읽는 쪽 수 상한(호출 폭주 방지)

Kind = Literal["usjnt", "pregnancy", "age"]
Level = Literal["item", "ingr"]

OPERATIONS: dict[tuple[Level, Kind], str] = {
    ("item", "usjnt"): "getUsjntTabooInfoList03",
    ("item", "pregnancy"): "getPwnmTabooInfoList03",
    ("item", "age"): "getSpcifyAgrdeTabooInfoList03",
    ("ingr", "usjnt"): "getUsjntTabooInfoList02",
    ("ingr", "pregnancy"): "getPwnmTabooInfoList02",
    ("ingr", "age"): "getSpcifyAgrdeTabooInfoList02",
}

NOT_SAFE_NOTE = "API 목록에 없다는 뜻이며 안전하다는 뜻이 아닙니다. 약사에게 확인하세요."

_SEQ_RE = re.compile(r"^\d{9}$")
_INGR_RE = re.compile(r"^D\d{6}$")


def iso_date(value: Any) -> str | None:
    """`20090303` → `2009-03-03`(`YYYY-MM-DD`). 해석할 수 없으면 None(원문은 `notification_date_raw`에 남는다)."""
    v = str(value or "").strip()
    return f"{v[:4]}-{v[4:6]}-{v[6:]}" if re.fullmatch(r"\d{8}", v) else None


class DurRow(BaseModel):
    """DUR 응답 한 행. 문장·등급 필드는 원문 그대로이고 원본 전체는 `raw`에 둔다."""

    kind: Kind
    level: Level
    ingr_code: str | None = None              # 성분 단위 기준 성분(쌍이면 A쪽)
    item_seq: str | None = None               # 품목 단위 기준 품목(쌍이면 A쪽)
    item_name: str | None = None
    pair_ingr_code: str | None = None         # 병용금기 B쪽
    pair_item_seq: str | None = None
    pair_item_name: str | None = None
    grade: str | None = None                  # 임부금기 성분정보 원문(예 `1등급`). 변환하지 않는다
    age_base: str | None = None               # 연령금기 성분정보 원문(예 `18세 이하`)
    content: str | None = None                # PROHBT_CONTENT 원문(개행 포함)
    remark: str | None = None
    notification_date_raw: str | None = None  # NOTIFICATION_DATE 원문
    notification_date: str | None = None      # `YYYY-MM-DD`
    grade_norm: Literal["1", "2", "M"] | None = None   # 파일(BE-09)과 같은 형식. 원문 `grade`는 그대로 둔다
    flags: list[str] = Field(default_factory=list)     # 예: `GRADE_UNPARSED`
    evidence_id: str | None = None            # 행 단위 근거 ID(출처를 식별하는 값만, 표시 문구 아님)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


GRADE_UNPARSED = "GRADE_UNPARSED"
_GRADE_RE = re.compile(r"^\s*([12]|M)\s*(?:등급)?\s*$", re.IGNORECASE)


def normalize_grade(grade: Any) -> tuple[Literal["1", "2", "M"] | None, bool]:
    """임부금기 등급 원문(`1등급`·`2등급`·`M`…) → (`'1'`·`'2'`·`'M'` 또는 None, 해석 실패 여부).

    값이 없으면 (None, False). 값이 있는데 해석할 수 없으면 (None, True)이며 추측하지 않는다.
    """
    text = str(grade or "").strip()
    if not text:
        return None, False
    m = _GRADE_RE.match(text)
    if not m:
        return None, True
    return m.group(1).upper(), False  # type: ignore[return-value]


def _clean(raw: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip(): v for k, v in raw.items()}   # 끝 공백 키(`TYPE_NAME  `) 정리


def _row(level: Level, kind: Kind, raw: dict[str, Any]) -> DurRow:
    r = _clean(raw)
    pair = kind == "usjnt"
    date_raw = r.get("NOTIFICATION_DATE")
    grade_norm, unparsed = normalize_grade(r.get("GRADE"))
    return DurRow(
        grade_norm=grade_norm,
        flags=[GRADE_UNPARSED] if unparsed else [],
        kind=kind,
        level=level,
        ingr_code=r.get("INGR_CODE"),
        item_seq=r.get("ITEM_SEQ"),
        item_name=r.get("ITEM_NAME"),
        pair_ingr_code=r.get("MIXTURE_INGR_CODE") if pair else None,
        pair_item_seq=r.get("MIXTURE_ITEM_SEQ") if pair else None,
        pair_item_name=r.get("MIXTURE_ITEM_NAME") if pair else None,
        grade=r.get("GRADE"),
        age_base=r.get("AGE_BASE"),
        content=r.get("PROHBT_CONTENT"),
        remark=r.get("REMARK"),
        notification_date_raw=date_raw,
        notification_date=iso_date(date_raw),
        raw=r,
    )


class DurResult(BaseModel):
    """DUR 조회 결과. `ok=False`이면 `error`를 본다(그때 `rows`가 비어 있어도 '없음'이 아니다)."""

    ok: bool
    kind: Kind
    level: Level
    rows: list[DurRow] = Field(default_factory=list)
    total_count: int = 0                      # 서버가 알려 준 전체 건수(쌍 조회는 필터 전 합계)
    truncated: bool = False                   # 쪽 수 상한으로 다 읽지 못했으면 True
    query: dict[str, str] = Field(default_factory=dict)
    request_hash: str | None = None           # 첫 조회의 응답 해시(= request_hashes[0])
    request_hashes: list[str] = Field(default_factory=list)   # 조회마다 첫 쪽 해시(단일 1개, 쌍 2개)
    partial: Literal["A", "B"] | None = None  # 쌍 조회에서 **한쪽만 실패**했을 때 실패한 쪽(A=첫째 인자). 둘 다 실패면 None
    source_name: str
    queried_at_utc: str | None = Field(None, description="공공 API에서 데이터를 받은 시각(UTC ISO 8601, 캐시면 처음 받은 시각)")
    queried_at_display: str | None = None
    from_cache: bool = False
    source: Literal["live", "cache", "snapshot"] | None = None
    error: ToolError | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def empty(self) -> bool:
        """정상 응답이고 0건. 안전하다는 뜻이 아니다."""
        return self.ok and not self.rows and not self.truncated

    @computed_field  # type: ignore[prop-decorator]
    @property
    def note(self) -> str | None:
        return NOT_SAFE_NOTE if self.empty else None


def _fail(kind: Kind, level: Level, err: ApiError, query: dict[str, str] | None = None) -> DurResult:
    return DurResult(ok=False, kind=kind, level=level, query=query or {},
                     source_name=SOURCE_ITEM if level == "item" else SOURCE_INGR,
                     error=ToolError.from_api_error(err))


class DurClient:
    def __init__(self, item_http: ApiHttpClient, ingr_http: ApiHttpClient, *, max_pages: int = DEFAULT_MAX_PAGES) -> None:
        self._http: dict[Level, ApiHttpClient] = {"item": item_http, "ingr": ingr_http}
        self.max_pages = max(1, int(max_pages))

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> DurClient:
        """환경변수 이름(`DURPrdlstInfoService03_*`, `DURIrdntInfoService03_*`)은 설정 모듈로만 읽는다."""
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        mode = "snapshot" if settings.mediagent_api_mode == "snapshot" else "live"
        cache = cache_from_settings(settings)
        common = dict(mode=mode, cache=cache, max_calls=settings.mediagent_api_max_calls)
        return cls(
            ApiHttpClient(ITEM_ALIAS, settings.durprdlstinfoservice03_end_point, settings.durprdlstinfoservice03_api_key, **common),
            ApiHttpClient(INGR_ALIAS, settings.durirdntinfoservice03_end_point, settings.durirdntinfoservice03_api_key, **common),
        )

    # ---- 단일 조회(품목 또는 성분 하나) ----
    def by_item(self, kind: Kind, item_seq: str) -> DurResult:
        """품목기준코드(9자리)로 그 품목의 병용·연령·임부 금기를 조회한다(품목 단위)."""
        seq = str(item_seq or "").strip()
        if not _SEQ_RE.fullmatch(seq):
            return _fail(kind, "item", ApiError("invalid_request", "품목기준코드는 숫자 9자리여야 합니다."))
        return self._collect(kind, "item", {"itemSeq": seq})

    def by_ingredient(self, kind: Kind, ingr_code: str) -> DurResult:
        """DUR 성분코드(`D######`)로 조회한다(성분 단위). 임부 `GRADE`·연령 `AGE_BASE`는 이 경로에서만 나온다."""
        code = str(ingr_code or "").strip().upper()
        if not _INGR_RE.fullmatch(code):
            return _fail(kind, "ingr", ApiError("invalid_request", "DUR 성분코드는 D와 숫자 6자리여야 합니다."))
        return self._collect(kind, "ingr", {"ingrCode": code})

    # ---- 병용금기 쌍 조회(양쪽 모두 조회) ----
    def usjnt_pair_by_item(self, seq_a: str, seq_b: str) -> DurResult:
        return self._pair("item", "itemSeq", "ITEM_SEQ", "MIXTURE_ITEM_SEQ", seq_a, seq_b, _SEQ_RE)

    def usjnt_pair_by_ingredient(self, code_a: str, code_b: str) -> DurResult:
        return self._pair("ingr", "ingrCode", "INGR_CODE", "MIXTURE_INGR_CODE",
                          str(code_a or "").strip().upper(), str(code_b or "").strip().upper(), _INGR_RE)

    def _pair(self, level: Level, param: str, a_key: str, b_key: str, x: str, y: str, pattern: re.Pattern[str]) -> DurResult:
        x, y = str(x or "").strip(), str(y or "").strip()
        if not pattern.fullmatch(x) or not pattern.fullmatch(y) or x == y:
            return _fail("usjnt", level, ApiError("invalid_request", "서로 다른 올바른 코드 두 개가 필요합니다."))
        first = self._collect("usjnt", level, {param: x})
        second = self._collect("usjnt", level, {param: y})
        if not first.ok or not second.ok:   # 한쪽이라도 실패하면 '없음'이라고 말할 수 없다
            bad = first if not first.ok else second
            partial: Literal["A", "B"] | None = None
            if first.ok != second.ok:
                partial = "B" if first.ok else "A"
            return DurResult(ok=False, kind="usjnt", level=level, query={"a": x, "b": y},
                             source_name=bad.source_name, error=bad.error, partial=partial,
                             request_hashes=[h for h in (first.request_hash, second.request_hash) if h],
                             request_hash=first.request_hash or second.request_hash)
        rows: list[DurRow] = []
        seen: set[tuple[Any, ...]] = set()
        for res, mine, other in ((first, x, y), (second, y, x)):
            for r in res.rows:
                if str(r.raw.get(a_key)) == mine and str(r.raw.get(b_key)) == other:
                    sig = (frozenset((r.raw.get(a_key), r.raw.get(b_key))), r.raw.get("DUR_SEQ"), r.raw.get("MIXTURE_DUR_SEQ"),
                           r.notification_date_raw, r.content)
                    if sig not in seen:
                        seen.add(sig)
                        rows.append(r)
        older = min((first, second), key=lambda z: z.queried_at_utc or "")
        return DurResult(
            ok=True, kind="usjnt", level=level, rows=rows,
            total_count=first.total_count + second.total_count,
            truncated=first.truncated or second.truncated,
            query={"a": x, "b": y}, source_name=first.source_name,
            request_hash=first.request_hash, request_hashes=[first.request_hash or "", second.request_hash or ""],
            queried_at_utc=older.queried_at_utc, queried_at_display=older.queried_at_display,
            from_cache=first.from_cache and second.from_cache,
            source=first.source if first.source == second.source else ("cache" if first.from_cache or second.from_cache else "live"),
        )

    # ---- 내부 ----
    def _collect(self, kind: Kind, level: Level, filters: dict[str, str]) -> DurResult:
        operation = OPERATIONS[(level, kind)]
        http = self._http[level]
        source_name = SOURCE_ITEM if level == "item" else SOURCE_INGR
        rows: list[DurRow] = []
        first: ApiResponse | None = None
        total = 0
        truncated = False
        try:
            for page in range(1, self.max_pages + 1):
                resp = http.get(operation, {**filters, "pageNo": page, "numOfRows": MAX_ROWS})
                first = first or resp
                items = extract_items(resp.body)
                rows.extend(_row(level, kind, it) for it in items)
                try:
                    total = int(resp.body.get("totalCount", len(rows)))
                except (TypeError, ValueError):
                    total = len(rows)
                if not items or len(rows) >= total:
                    break
            else:
                truncated = len(rows) < total
        except ApiError as err:
            return _fail(kind, level, err, filters)
        assert first is not None
        alias = ITEM_ALIAS if level == "item" else INGR_ALIAS
        subject = next(iter(filters.values()), "")
        for n, row in enumerate(rows):
            seq = str(row.raw.get("DUR_SEQ") or "").strip() or f"r{n}"
            other = row.pair_ingr_code or row.pair_item_seq
            row.evidence_id = f"{alias}:{kind}:{subject}{':' + other if other else ''}:{seq}"
        return DurResult(
            ok=True, kind=kind, level=level, rows=rows, total_count=total, truncated=truncated,
            query=dict(filters), source_name=source_name,
            request_hash=first.request_hash, request_hashes=[first.request_hash],
            queried_at_utc=format_utc(first.fetched_at), queried_at_display=format_display(first.fetched_at),
            from_cache=first.from_cache, source=first.source,
        )


# ---------------------------------------------------------------------------------------------
# 파일(BE-09) 판정과의 병기·교차
# ---------------------------------------------------------------------------------------------
CrossOutcome = Literal["BOTH_FOUND", "BOTH_NOT_LISTED", "FILE_ONLY", "API_ONLY", "API_UNAVAILABLE", "FILE_UNIDENTIFIED"]


HarnessFlag = Literal["API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"]

# `CrossCheck.outcome` → 하네스 꼬리표(PJ2-Agent-Harness.md 3장 `api_flag`). 한 곳에서만 정의한다.
# BOTH_NOT_LISTED는 "양쪽 모두 목록에 없음"이라 API_SAME으로 본다(후보). FILE_UNIDENTIFIED는 API 병기 대상이 아니라 꼬리표 없음.
OUTCOME_TO_HARNESS_FLAG: dict[str, HarnessFlag | None] = {
    "BOTH_FOUND": "API_SAME",
    "BOTH_NOT_LISTED": "API_SAME",
    "FILE_ONLY": "FILE_ONLY",
    "API_ONLY": "API_ONLY",
    "API_UNAVAILABLE": "API_FAIL",
    "FILE_UNIDENTIFIED": None,
}


def harness_flag(outcome: str, *, truncated: bool = False, partial: str | None = None) -> HarnessFlag | None:
    """교차 결과를 하네스 꼬리표로 바꾼다. 쌍 조회 한쪽 실패는 `API_PAIR_INCOMPLETE`,
    쪽 수 상한으로 다 읽지 못한 경우(`truncated`)는 "실시간 확인을 하지 못함"이라 `API_FAIL`로 다룬다."""
    flag = OUTCOME_TO_HARNESS_FLAG[outcome]
    if flag is None:
        return None
    if outcome == "API_UNAVAILABLE":
        return "API_PAIR_INCOMPLETE" if partial else "API_FAIL"
    if truncated:
        return "API_FAIL"
    return flag


class CrossCheck(BaseModel):
    """파일 1차 판정과 API 병기 결과. 판정은 파일이 하고 API는 병기·교차용이다(AG-02가 4경우를 처리)."""

    outcome: CrossOutcome
    api_flag: HarnessFlag | None = None
    file_status: str
    api_ok: bool
    file_notice_dates: list[str] = Field(default_factory=list)   # `YYYY-MM-DD`
    api_notice_dates: list[str] = Field(default_factory=list)
    dates_differ: bool = False
    note: str = "고시일자가 다르면 둘 다 보여 줍니다. API가 파일보다 최신이라고 단정하지 않습니다."


def _file_parts(file_item: Any) -> tuple[str, list[str]]:
    get = (lambda k: file_item.get(k)) if isinstance(file_item, dict) else (lambda k: getattr(file_item, k, None))
    dates = sorted({str(m.get("notice_date")) for m in (get("matches") or []) if m.get("notice_date")})
    return str(get("status")), dates


def cross_check(file_item: Any, api_result: DurResult) -> CrossCheck:
    """`lookup.Item`(또는 `to_dict()` 결과)과 `DurResult`를 나란히 놓는다. 파일 판정은 바꾸지 않는다."""
    status, file_dates = _file_parts(file_item)
    api_dates = sorted({r.notification_date for r in api_result.rows if r.notification_date})
    base = dict(file_status=status, api_ok=api_result.ok, file_notice_dates=file_dates, api_notice_dates=api_dates)
    if status == "UNIDENTIFIED":
        return CrossCheck(outcome="FILE_UNIDENTIFIED", api_flag=None, **base)
    if not api_result.ok:
        return CrossCheck(outcome="API_UNAVAILABLE", api_flag=harness_flag("API_UNAVAILABLE", partial=api_result.partial), **base)
    api_found = bool(api_result.rows)
    file_found = status == "FOUND"
    outcome: CrossOutcome = (
        "BOTH_FOUND" if file_found and api_found else
        "FILE_ONLY" if file_found else
        "API_ONLY" if api_found else
        "BOTH_NOT_LISTED"
    )
    return CrossCheck(outcome=outcome, api_flag=harness_flag(outcome, truncated=api_result.truncated), dates_differ=bool(file_dates and api_dates and file_dates != api_dates), **base)
