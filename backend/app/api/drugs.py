"""프로필 약 사전 검색 API(FE-04-13 A·FE-04 (나) A, 2026-11-20).

`POST /drugs/search` 본문 `{"q": "..."}`: 서버가 이미 메모리에 올린 사전(`DrugDict`, BE-17 warmup 자원 = `/chat`과 같은 판)으로 약 이름 후보를 돌려준다.

- 순서: `DrugDict.lookup_name`의 계약 그대로 **제품 사전 → 성분 사전**(제품명 정확·정규화 → 성분명 → 제품명 앞부분 → 중간 → BM25).
  에이전트의 `identify_drug`와 같은 함수를 써서, 프로필에 고른 약과 채팅에서 확정되는 약이 같은 기준으로 맞는다.
- 후보 최대 10개. 칸: 이름·`item_seq`·회사·전문/일반·일치 단위(`matched_by`)·일치 종류(`match_type`). 판정·코드·성분 상세는 싣지 않는다.
- LLM 호출 0. DB 추가 조회 0(사전은 서버 자원으로 한 번 적재된 것을 공유한다. 자원이 아직 없으면 `/chat` 첫 요청처럼 그때 한 번 만든다).
- 로그인 필요(`require_user`, 프로필 약 입력은 로그인 사용자 기능). 계정 행·동의는 보지 않는다(사전 검색은 개인 정보를 읽거나 쓰지 않는다).
- **질문 문자열(`q`)은 로그·오류 본문·응답에 싣지 않는다.** 그래서 GET 쿼리가 아니라 POST 본문으로 받는다(uvicorn access 로그는
  경로와 쿼리 문자열을 그대로 찍는다). 실패 로그는 예외 종류 이름만. 응답은 `Cache-Control: no-store`.
- 오류: 422 `INVALID_REQUEST`(fields=["q"]: 빈 값·100자 초과), 401(인증), 501 `NOT_IMPLEMENTED`(사전 공급자 없음),
  503 `DICT_UNAVAILABLE`(사전 적재 실패).
- 저장 계약(FE-04 (나) A): 후보를 고르면 `POST/PATCH /profiles`의 `medications[]`에 `{input_text: 후보 name, item_seq}`를 보낸다.
  사전에 없으면 **"확인 안 된 약"**으로 `{input_text: 입력 글자}`만 보낸다(`item_seq` 없음). 저장된 행의 `item_seq is null`이 곧
  "확인 안 된 약(직접 입력)"이다(별도 출처 칸 없음). 사진(OCR, FE-04 (가) A)도 같은 후보 고르기를 거쳐 같은 모양으로 저장한다(구현은 FE-05).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.api.account import _ACCOUNT_ERRORS, NO_STORE, AccountError, ItemSeqChecker, UserDep
from app.api.chat import ErrorBody
from app.api.schemas import _Strict
from app.tools.drug_dict import MATCHED_BY_INGREDIENT, MATCHED_BY_PRODUCT, DrugDict

logger = logging.getLogger(__name__)

PROVIDER_STATE_KEY = "drug_dict_provider"
SEARCH_LIMIT = 10
QUERY_MAX_LEN = 100  # 프로필 약 `input_text` 상한과 같다(`account.MedText`)
CODE_DICT_UNAVAILABLE = "DICT_UNAVAILABLE"
CODE_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

DictProvider = Callable[[], DrugDict]
MatchedBy = Literal["product_name", "ingredient_name"]


class DrugSearchIn(_Strict):
    """검색 본문. 질문을 URL 쿼리에 두지 않는다(서버 access 로그·브라우저 기록·프록시 로그에 경로째 남기 때문)."""

    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=QUERY_MAX_LEN)]


class DrugCandidateOut(BaseModel):
    """후보 하나. `item_seq`가 없는 후보(성분명 일치, 허가번호 없는 KIDS 제품 행)는 골라도 `item_seq` 없이 글자만 저장된다."""

    model_config = ConfigDict(extra="forbid")

    name: str
    item_seq: str | None
    entp_name: str | None
    prescription: str | None  # 전문 | 일반 | None
    matched_by: MatchedBy  # product_name(제품 사전) | ingredient_name(성분 사전)
    match_type: str  # exact | normalized | prefix | contains | bm25


class DrugSearchOut(BaseModel):
    """`POST /drugs/search` 응답. 질문 문자열은 되돌려 주지 않는다."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[DrugCandidateOut]
    needs_confirmation: bool  # 후보가 여럿이거나 비슷한 이름 후보(앞부분·중간·BM25)라 사용자가 골라야 한다
    dict_version: str


def set_provider(app: FastAPI, provider: DictProvider | None) -> None:
    """검색이 쓸 사전 공급자를 붙인다(None이면 뗀다 → 501). 서비스는 `LazyGraphRunner.drug_dict`를 붙인다."""
    setattr(app.state, PROVIDER_STATE_KEY, provider)


def to_out(dd: DrugDict, q: str, limit: int = SEARCH_LIMIT) -> DrugSearchOut:
    """사전 조회 결과 → 응답. 같은 `item_seq`는 한 번만, 제품·성분 후보만 남긴다(순서는 `lookup_name` 그대로)."""
    res = dd.lookup_name(q, top_k=limit)
    seen: set[str] = set()
    out: list[DrugCandidateOut] = []
    for c in res.candidates:
        if c.matched_by not in (MATCHED_BY_PRODUCT, MATCHED_BY_INGREDIENT):
            continue
        key = c.item_seq or f"{c.matched_by}:{c.name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(DrugCandidateOut(name=c.name, item_seq=c.item_seq, entp_name=c.entp_name, prescription=c.prescription,
                                    matched_by=c.matched_by, match_type=c.match_type))  # type: ignore[arg-type]
        if len(out) >= limit:
            break
    return DrugSearchOut(candidates=out, needs_confirmation=bool(out) and not res.resolved, dict_version=res.dict_version)


def dict_item_seq_checker(provider: DictProvider) -> ItemSeqChecker:
    """프로필 저장 때 `item_seq` 재확인 함수(`account.set_repo(..., item_seq_checker=)`)를 사전으로 만든다. 사전에 있는 것만 돌려준다."""

    async def check(seqs: Sequence[str]) -> set[str]:
        dd = await run_in_threadpool(provider)
        return {s for s in seqs if dd.has_item_seq(s)}

    return check


router = APIRouter()


@router.post("/drugs/search", response_model=DrugSearchOut, summary="프로필 약 이름 사전 검색(제품 → 성분, 최대 10개, LLM 0)",
             responses={401: _ACCOUNT_ERRORS[401], 422: {"model": ErrorBody, "description": "INVALID_REQUEST(fields=[\"q\"])."},
                        501: {"model": ErrorBody, "description": "토큰 검증기 또는 사전 공급자 미설정."},
                        503: {"model": ErrorBody, "description": "AUTH_UNAVAILABLE 또는 DICT_UNAVAILABLE(사전 적재 실패)."}})
async def search_drugs(body: DrugSearchIn, _: UserDep, request: Request, response: Response) -> DrugSearchOut:
    response.headers["Cache-Control"] = NO_STORE
    text = body.q
    provider: DictProvider | None = getattr(request.app.state, PROVIDER_STATE_KEY, None)
    if provider is None:
        raise AccountError(501, CODE_NOT_IMPLEMENTED)
    try:
        dd = await run_in_threadpool(provider)
    except Exception as exc:  # noqa: BLE001 - 적재 실패는 503. 종류 이름만 남긴다(질문·연결 정보 없음)
        logger.warning("drug search dictionary unavailable: %s", type(exc).__name__)
        raise AccountError(503, CODE_DICT_UNAVAILABLE) from None
    return await run_in_threadpool(to_out, dd, text)


def register(app: FastAPI) -> None:
    """`/drugs/search`를 붙인다. 오류 처리기는 계정 API 것을 쓴다(`me.register` 뒤에 부른다)."""
    app.include_router(router)


__all__ = ["CODE_DICT_UNAVAILABLE", "PROVIDER_STATE_KEY", "SEARCH_LIMIT", "DrugCandidateOut", "DrugSearchOut", "dict_item_seq_checker",
           "register", "router", "set_provider", "to_out"]
