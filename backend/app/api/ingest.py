"""BE-14 `POST /ingest/image` 사진 약 이름 추출 API(PRD-08-07 A, 〔D1〕~〔D8〕 A 2026-11-22).

요청(〔D1〕 A): JSON `{"image": "data:image/jpeg;base64,…" | "data:image/png;base64,…", "question": "선택, 500자 이하"}`.
- 디코드 뒤 8MB 이하, 형식은 머리 바이트로(JPEG·PNG만), 픽셀 수 상한 4000만(압축 폭탄). 위반은 422 `INVALID_REQUEST` fields=["image"]
  (질문 길이 초과는 fields=["question"]). 오류 본문은 `/chat`과 같은 `ErrorBody{code, fields}`이고 입력 값을 싣지 않는다.
- 인증(〔D3〕 A): 게스트 허용(`/chat`과 같음, 토큰을 읽지 않는다). 남용은 원장 `vision` 상한(0.30 USD, 〔D4〕 A)이 막는다.

응답(200, `IngestImageOut`): `status` OK | UNREADABLE | UNAVAILABLE, `reason` 코드, `drugs[]`(읽은 글자·성분 글자·용량/제형 + 사전 후보 ≤5,
기본 선택 칸 없음, 확신도 없음), `emergency`(질문 글자에 `guardrail.detect_emergency`와 **같은 함수**, 판독 결과와 무관, RFP-35-07),
`dict_unavailable`, `dict_version`. 판정·설명·요약 칸은 없다. 질문은 되돌려 주지 않는다. `Cache-Control: no-store`.

H19(〔D7〕 A): 이 모듈과 `app.api.vision`은 `app.agent.tools`·`app.agent.graph`를 import하지 않고 판정 도구를 부르지 않는다.
사용자가 확인 카드에서 고른 약만 FE가 `/chat`의 `context.confirmed_drugs`로 보낸다(계약 변경 없음).

로그(RFP-34-01): 요청 1건당 한 줄에 상태·이유 코드·약 개수·지연·토큰·비용만. 이미지·base64·약 이름·질문·모델 출력은 남기지 않는다.
예외는 종류 이름만. 요청 본문을 로깅하는 미들웨어는 없다(uvicorn access 로그는 경로만).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.agent import fixed_phrases as fp
from app.agent.guardrail import detect_emergency  # guardrail_in과 같은 함수(키워드 목록을 이 모듈에 두지 않는다)
from app.api import vision
from app.api.chat import ErrorBody
from app.api.drugs import PROVIDER_STATE_KEY, DictProvider, DrugCandidateOut, to_out
from app.api.schemas import Emergency, _Strict
from app.llm.ledger import CostLedger

logger = logging.getLogger(__name__)

CLIENT_STATE_KEY = "vision_client"  # `app.state`의 비전 클라이언트(시험은 가짜). 없으면 첫 요청에서 OpenAI 클라이언트를 만든다
LEDGER_STATE_KEY = "vision_ledger"  # `app.state`의 원장. 없으면 기본 원장(`CostLedger()`)
QUESTION_MAX_LEN = 500
CANDIDATE_LIMIT = 5
CODE_INVALID_REQUEST = "INVALID_REQUEST"
NO_STORE = "no-store"


class IngestImageIn(_Strict):
    """요청 본문. 길이·형식은 핸들러가 검사해 칸 이름(`image`·`question`)을 422 `fields`에 싣는다."""

    image: str
    question: str | None = None


class IngestDrugOut(BaseModel):
    """사진에서 읽은 약 하나. 읽은 글자와 사전 후보를 병기한다. 기본 선택·확신도 칸은 없다."""

    model_config = ConfigDict(extra="forbid")

    read_name: str | None
    read_ingredient: str | None
    strength_or_form: str | None
    candidates: list[DrugCandidateOut]


class IngestImageOut(BaseModel):
    """`POST /ingest/image` 응답. 판정·설명·요약 칸은 없다."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["OK", "UNREADABLE", "UNAVAILABLE"]
    reason: Literal["NONE_READ", "MODEL_ERROR", "REFUSED", "PARSE_ERROR", "CAP_REACHED"] | None
    drugs: list[IngestDrugOut]
    emergency: Emergency | None
    dict_unavailable: bool  # 사전 공급자가 없거나 적재 실패면 true(후보 빈 목록, 오류로 막지 않는다)
    dict_version: str


def set_vision(app: FastAPI, *, client: vision.VisionClient | None = None, ledger: CostLedger | None = None) -> None:
    """비전 클라이언트·원장을 붙인다(시험·서비스 공용). None이면 기본값을 첫 요청에서 만든다."""
    setattr(app.state, CLIENT_STATE_KEY, client)
    setattr(app.state, LEDGER_STATE_KEY, ledger)


def _client_provider(app: FastAPI) -> vision.VisionClient | Callable[[], vision.VisionClient]:
    cl = getattr(app.state, CLIENT_STATE_KEY, None)
    if cl is not None:
        return cl

    def make() -> vision.VisionClient:
        made = vision.OpenAIVisionClient()
        setattr(app.state, CLIENT_STATE_KEY, made)
        return made

    return make


def _ledger(app: FastAPI) -> CostLedger:
    led = getattr(app.state, LEDGER_STATE_KEY, None)
    if led is None:
        led = CostLedger()
        setattr(app.state, LEDGER_STATE_KEY, led)
    return led


def _invalid(field: str) -> JSONResponse:
    return JSONResponse(status_code=422, content=ErrorBody(code=CODE_INVALID_REQUEST, fields=[field]).model_dump(),
                        headers={"Cache-Control": NO_STORE})


def _candidates(provider: DictProvider | None, drugs: list[dict[str, str | None]]) -> tuple[list[IngestDrugOut], bool, str]:
    dd = None
    if provider is not None:
        try:
            dd = provider()
        except Exception as exc:  # noqa: BLE001 - 사전 적재 실패는 후보 없음으로(종류 이름만)
            logger.warning("ingest image dictionary unavailable: %s", type(exc).__name__)
            dd = None
    out: list[IngestDrugOut] = []
    for d in drugs:
        name = d["product_name"] or d["ingredient_name"] or ""
        cands = to_out(dd, name, limit=CANDIDATE_LIMIT).candidates if dd is not None and name else []
        out.append(IngestDrugOut(read_name=d["product_name"], read_ingredient=d["ingredient_name"], strength_or_form=d["strength_or_form"],
                                 candidates=cands[:CANDIDATE_LIMIT]))
    version = str(getattr(dd, "version", "") or "") if dd is not None else ""
    return out, dd is None, version


router = APIRouter()


@router.post("/ingest/image", response_model=IngestImageOut,
             summary="약봉투 사진에서 약 이름 후보를 읽는다(gpt-6-luna 1회, 판정 없음, 게스트 허용, 사진·질문 비저장)",
             responses={422: {"model": ErrorBody, "description": "INVALID_REQUEST(fields=[\"image\"] 형식·크기·픽셀, [\"question\"] 500자 초과). "
                                                              "입력 값은 되돌려 주지 않는다."}})
async def ingest_image(body: IngestImageIn, request: Request) -> JSONResponse:
    t0 = time.monotonic()
    question = body.question or ""
    if len(question) > QUESTION_MAX_LEN:
        return _invalid("question")
    try:
        data = vision.decode_data_url(body.image)
        await run_in_threadpool(vision.check_image, data)
    except vision.InvalidImage:
        logger.info("ingest image rejected: INVALID_IMAGE")
        return _invalid("image")
    emergency = Emergency(text=fp.EMERGENCY_119, tel=fp.EMERGENCY_119_TEL) if question and detect_emergency(question) else None
    app = request.app
    try:
        res = await run_in_threadpool(vision.extract, data, client=_client_provider(app), ledger=_ledger(app))
    except vision.InvalidImage:  # 머리는 맞았으나 디코드 중 실패(잘린 파일 등)
        logger.info("ingest image rejected: INVALID_IMAGE")
        return _invalid("image")
    del data
    provider: DictProvider | None = getattr(app.state, PROVIDER_STATE_KEY, None)
    drugs, dict_unavailable, dict_version = await run_in_threadpool(_candidates, provider, res.drugs)
    out = IngestImageOut(status=res.status, reason=res.reason, drugs=drugs, emergency=emergency, dict_unavailable=dict_unavailable,
                         dict_version=dict_version)
    logger.info("ingest image status=%s reason=%s drugs=%d attempts=%d latency_ms=%d in_tokens=%d out_tokens=%d usd=%.6f emergency=%s",
                res.status, res.reason or "-", len(drugs), res.attempts, int((time.monotonic() - t0) * 1000), res.in_tokens,
                res.out_tokens, res.usd, emergency is not None)
    return JSONResponse(content=out.model_dump(mode="json"), headers={"Cache-Control": NO_STORE})


def register(app: FastAPI) -> None:
    """`/ingest/image`를 붙인다(main.py 한 줄). 요청 형식 오류(모르는 칸·타입)는 앱의 기존 422 처리기가 맡는다."""
    app.include_router(router)


__all__ = ["CLIENT_STATE_KEY", "LEDGER_STATE_KEY", "IngestDrugOut", "IngestImageIn", "IngestImageOut", "register", "router", "set_vision"]
