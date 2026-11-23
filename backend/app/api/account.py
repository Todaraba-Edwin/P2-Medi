"""BE-11 계정 API: 약관·동의·프로필 라우트, 응답 스키마, 공통 규칙(2026-11-18). `/me`(조회·탈퇴)는 `app.api.me`.

- 설계 `P2-doc/PJ2-계정-프로필-데이터.md` 6·8·9장 + 사용자 결정(2026-11-18 "권장대로"): BE-11-12 A(privacy_consent 철회 → 프로필만 삭제),
  20 A(검증 장애 503 `AUTH_UNAVAILABLE`), 21 A(오류 본문 `{code, fields}`), 22 A(탈퇴 시 전부 즉시 파기).
- 저장소는 `app.state.account_repo`(`AccountRepo`)다. 없으면 501 `NOT_IMPLEMENTED`(`/chat`의 실행기 미주입과 같은 규칙).
- 오류 본문은 `ErrorBody{code, fields}`이고 **입력 값·ID·토큰을 싣지 않는다**. `fields`에는 칸 이름이나 문서 종류(`doc_type`)만 싣는다.
  - 401 `AUTH_REQUIRED`·`AUTH_INVALID`(계정 행 없음 포함), 403 `CONSENT_REQUIRED`·`RECONSENT_REQUIRED`(fields=문서 종류),
    404 `NOT_FOUND`(남의 행도 404), 409 `VERSION_MISMATCH`·`USE_ACCOUNT_DELETE`·`SELF_EXISTS`·`SELF_REQUIRED`·`SELF_FIXED`,
    422 `INVALID_REQUEST`·`PROFILE_LIMIT`·`MEDICATION_LIMIT`·`HEALTH_CONSENT_REQUIRED`(건강 정보 동의 없이 임신 여부·복용 약 저장),
    501 `NOT_IMPLEMENTED`, 503 `ACCOUNT_UNAVAILABLE`(저장소 장애).
- 건강 정보(임신 여부·복용 약)는 `sensitive_consent`가 유효(동의 + 재동의 대기 아님)할 때만 저장한다. 조용히 버리지 않고 422로 알린다.
- 본문·건강 정보·ID를 로그에 쓰지 않는다. 응답에는 `Cache-Control: no-store`(약관은 `public, max-age=300`).
- 복용 약의 `item_seq`는 `app.state.account_item_seq_checker`(사전 확인 함수)가 확인한 것만 저장한다. 없으면 원문만 저장(설계 9.3절).
  확인 함수는 lifespan이 저장소와 따로 붙인다(`set_item_seq_checker`, FE-04-13 남음 ②). `set_repo`는 인자를 주지 않으면 그대로 둔다.
- 2026-11-20 GROUP-03 B1: 프로필 `sex`(선택, `female`·`male`, null = 미입력)는 건강 정보가 아니라 `privacy_consent`만 있으면 저장한다
  (PRD-17-13 A). 간편 로그인 공급자 정보에서 채우지 않고 `/chat` 요청에도 없다. 만 14세 확인 `age_14`는 첫 로그인 필수 동의이고
  철회는 `terms`처럼 409 `USE_ACCOUNT_DELETE`(PRD-17-12 A).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.api.chat import ErrorBody
from app.api.schemas import _Strict
from app.db.account_repo import (
    CONSENT_DOC_TYPES,
    FAMILY_LIMIT,
    HEALTH_CONSENT_CODE,
    HEALTH_DOC,
    MEDICATION_LIMIT,
    PROFILE_LIMIT,
    REQUIRED_CONSENT_DOCS,
    TERMS_DOC,
    UNSET,
    WITHDRAW_BLOCKED_DOCS,
    AccountRepo,
    AccountRepoError,
    AgeBand,
    AppUser,
    AvatarColor,
    ConsentAction,
    ConsentChannel,
    ConsentDocType,
    ConsentInput,
    DocType,
    LegalDoc,
    LegalReview,
    MedicationInput,
    OnboardingStep,
    PregnancyStatus,
    Profile,
    ProfileInput,
    ProfilePatch,
    Relation,
    RepoUnavailable,
    Sex,
    _Unset,
    utcnow,
)
from app.security.auth import Principal, require_user

logger = logging.getLogger(__name__)

REPO_STATE_KEY = "account_repo"
ITEM_SEQ_CHECKER_STATE_KEY = "account_item_seq_checker"
NO_STORE = "no-store"
LEGAL_CACHE = "public, max-age=300"

ItemSeqChecker = Callable[[Sequence[str]], Awaitable[set[str]]]

# 오류 코드
CODE_INVALID_REQUEST = "INVALID_REQUEST"
CODE_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
CODE_AUTH_INVALID = "AUTH_INVALID"
CODE_CONSENT_REQUIRED = "CONSENT_REQUIRED"
CODE_RECONSENT_REQUIRED = "RECONSENT_REQUIRED"
CODE_NOT_FOUND = "NOT_FOUND"
CODE_VERSION_MISMATCH = "VERSION_MISMATCH"
CODE_USE_ACCOUNT_DELETE = "USE_ACCOUNT_DELETE"
CODE_SELF_EXISTS = "SELF_EXISTS"
CODE_SELF_REQUIRED = "SELF_REQUIRED"
CODE_SELF_FIXED = "SELF_FIXED"
CODE_PROFILE_LIMIT = "PROFILE_LIMIT"
CODE_MEDICATION_LIMIT = "MEDICATION_LIMIT"
CODE_HEALTH_CONSENT_REQUIRED = "HEALTH_CONSENT_REQUIRED"
CODE_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"


class AccountError(Exception):
    """API 계층 오류 → `ErrorBody{code, fields}`. 메시지·필드에 값을 담지 않는다."""

    def __init__(self, status_code: int, code: str, fields: Sequence[str] = ()) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.fields = list(fields)


# --------------------------------------------------------------------------- 스키마
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
MedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ItemSeq = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]


class LegalDocumentOut(BaseModel):
    """`GET /legal/{doc_type}`. `legal_review="not_reviewed"`이면 프런트가 "초안·법률 검토 전" 표지를 그린다."""

    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    version: int
    title: str
    body_md: str
    required: bool
    requires_reconsent: bool
    effective_at: datetime
    legal_review: LegalReview
    body_sha256: str


class ConsentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: ConsentDocType
    required: bool
    agreed_version: int | None  # 최신 기록이 agree면 그 버전
    acted_at: datetime | None
    current_version: int
    needs_consent: bool
    needs_reconsent: bool


class ConsentItem(_Strict):
    doc_type: ConsentDocType
    version: int = Field(ge=1, le=100_000)  # 현재본과 다르면 409 VERSION_MISMATCH
    action: ConsentAction


class ConsentRequest(_Strict):
    items: list[ConsentItem] = Field(min_length=1, max_length=len(CONSENT_DOC_TYPES))  # 문서 종류당 한 번(첫 로그인 4종)
    channel: ConsentChannel

    @model_validator(mode="after")
    def _unique_doc_types(self) -> ConsentRequest:
        if len({i.doc_type for i in self.items}) != len(self.items):
            raise ValueError("items의 doc_type이 겹친다")
        return self


class MedicationIn(_Strict):
    input_text: MedText
    item_seq: ItemSeq | None = None  # 서버가 사전에서 다시 확인. 확인 못 하면 None으로 저장


class MedicationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_id: str
    input_text: str
    item_seq: str | None
    confirmed_at: datetime | None


class ProfileOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    relation: Relation
    label: str | None
    age_band: AgeBand | None
    pregnancy_status: PregnancyStatus | None
    sort_order: int
    medications: list[MedicationOut]
    sex: Sex | None  # 선택. null = 미입력
    avatar_color: AvatarColor  # 병아리 배경색 8색(항상 포함, 기본 yellow). 건강 정보 아님: 동의한 최소 항목(CLAUDE.md 1장)


class ProfileCreate(_Strict):
    relation: Relation
    label: Label | None = None
    age_band: AgeBand | None = None
    pregnancy_status: PregnancyStatus | None = None  # 건강 동의 없이 값이 오면 422 HEALTH_CONSENT_REQUIRED
    medications: list[MedicationIn] = Field(default_factory=list, max_length=MEDICATION_LIMIT)
    sex: Sex | None = None  # 선택, 건강 동의 불필요(PRD-17-13 A)
    avatar_color: AvatarColor = "yellow"  # 선택(없으면 yellow), 허용 밖 값·null은 422 INVALID_REQUEST


class ProfileUpdate(_Strict):
    """보낸 칸만 바꾼다. `null`은 지움. `medications`를 보내면 목록 전체 교체."""

    relation: Relation | None = None
    label: Label | None = None
    age_band: AgeBand | None = None
    pregnancy_status: PregnancyStatus | None = None
    medications: list[MedicationIn] | None = Field(default=None, max_length=MEDICATION_LIMIT)
    sex: Sex | None = None  # null = 지움
    avatar_color: AvatarColor | None = None  # 색만 바꾸는 요청 허용. null은 거부

    @model_validator(mode="after")
    def _no_null_required(self) -> ProfileUpdate:
        for name in ("relation", "medications", "avatar_color"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name}은 null일 수 없다")
        return self


class MeResponse(BaseModel):
    """`GET /me`·`POST /consents` 응답. 이메일 등 로그인 정보는 싣지 않는다(설계 9.3절)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    is_guest: bool = False
    onboarding_step: OnboardingStep
    onboarding_completed_at: datetime | None
    consents: list[ConsentState]
    health_consent_active: bool  # 건강 정보를 지금 저장할 수 있는가(동의 + 재동의 대기 아님)
    profile_limit: int = PROFILE_LIMIT


# --------------------------------------------------------------------------- 의존성·공통
def get_repo(request: Request) -> AccountRepo:
    repo: AccountRepo | None = getattr(request.app.state, REPO_STATE_KEY, None)
    if repo is None:
        raise AccountError(501, CODE_NOT_IMPLEMENTED)
    return repo


def set_repo(app: Any, repo: AccountRepo | None, *, item_seq_checker: ItemSeqChecker | None | _Unset = UNSET) -> None:
    """계정 저장소(와 선택적으로 품목 확인 함수)를 붙인다. 저장소가 None이면 뗀다 → 계정 API 501.

    `item_seq_checker`를 주지 않으면 이미 붙은 확인 함수(lifespan의 `set_item_seq_checker`)를 그대로 둔다. None을 주면 뗀다.
    """
    setattr(app.state, REPO_STATE_KEY, repo)
    if not isinstance(item_seq_checker, _Unset):
        set_item_seq_checker(app, item_seq_checker)


def set_item_seq_checker(app: Any, checker: ItemSeqChecker | None) -> None:
    """복용 약 `item_seq` 재확인 함수를 붙인다(None이면 뗀다 → 원문만 저장). 저장소 연결(BE-11-23 A)과 따로 붙일 수 있다."""
    setattr(app.state, ITEM_SEQ_CHECKER_STATE_KEY, checker)


UserDep = Annotated[Principal, Depends(require_user)]
RepoDep = Annotated[AccountRepo, Depends(get_repo)]


def user_id_of(principal: Principal) -> str:
    if principal.user_id is None:  # require_user가 막지만 타입 좁히기
        raise AccountError(401, "AUTH_REQUIRED")
    return principal.user_id


async def require_account(repo: AccountRepo, user_id: str) -> AppUser:
    """`app_users` 행이 있어야 한다(첫 `GET /me`에서 생성, BE-11-10 A). 없으면 401 `AUTH_INVALID`(설계 7.3절: 탈퇴 뒤 남은 토큰 포함)."""
    user = await repo.get_user(user_id)
    if user is None:
        raise AccountError(401, CODE_AUTH_INVALID)
    return user


async def consent_states(repo: AccountRepo, user_id: str) -> list[ConsentState]:
    """문서 종류별 동의 상태(설계 8장 재동의 판정). 현재본이 없는 문서는 빠진다."""
    latest = await repo.latest_consents(user_id)
    out: list[ConsentState] = []
    for t in CONSENT_DOC_TYPES:
        current = await repo.legal_current(t)
        if current is None:
            continue
        rec = latest.get(t)
        agreed = rec is not None and rec.action == "agree"
        v_u = rec.doc_version if agreed and rec is not None else None
        needs_reconsent = False
        if v_u is not None and v_u < current.version:
            published = await repo.legal_published(t)
            needs_reconsent = any(d.requires_reconsent for d in published if v_u < d.version <= current.version)
        out.append(ConsentState(
            doc_type=t, required=current.required, agreed_version=v_u, acted_at=rec.acted_at if rec else None,
            current_version=current.version, needs_consent=not agreed, needs_reconsent=needs_reconsent,
        ))
    return out


def _state(states: Sequence[ConsentState], doc_type: str) -> ConsentState | None:
    return next((s for s in states if s.doc_type == doc_type), None)


def health_writable(states: Sequence[ConsentState]) -> bool:
    s = _state(states, HEALTH_DOC)
    return s is not None and not s.needs_consent and not s.needs_reconsent


def required_ok(states: Sequence[ConsentState]) -> bool:
    for t in REQUIRED_CONSENT_DOCS:  # terms·privacy_consent·age_14(PRD-17-12 A)
        s = _state(states, t)
        if s is None or s.needs_consent or s.needs_reconsent:
            return False
    return True


def gate_consents(states: Sequence[ConsentState], doc_types: Sequence[str]) -> None:
    """필수 동의 검사. 없음 → 403 `CONSENT_REQUIRED`, 재동의 대기 → 403 `RECONSENT_REQUIRED`(fields=문서 종류)."""
    missing = [t for t in doc_types if (s := _state(states, t)) is None or s.needs_consent]
    if missing:
        raise AccountError(403, CODE_CONSENT_REQUIRED, missing)
    stale = [t for t in doc_types if (s := _state(states, t)) is not None and s.needs_reconsent]
    if stale:
        raise AccountError(403, CODE_RECONSENT_REQUIRED, stale)


def next_step(user: AppUser, states: Sequence[ConsentState], profiles: Sequence[Profile]) -> tuple[OnboardingStep, datetime | None]:
    """온보딩 단계(설계 10장)를 상태에서 다시 계산한다. `done`은 가족 3명을 채웠을 때만 자동(건너뛰기는 후속 `PATCH /me/onboarding`)."""
    has_self = any(p.relation == "self" for p in profiles)
    family = sum(p.relation != "self" for p in profiles)
    step: OnboardingStep
    if not required_ok(states):
        step = "consent"
    elif not has_self:
        step = "profile_self"
    elif family >= FAMILY_LIMIT:
        step = "done"
    elif user.onboarding_step in ("consent", "profile_self"):
        step = "family"
    else:
        step = user.onboarding_step
    if step != "done":
        return step, None
    return step, user.onboarding_completed_at or utcnow()


async def sync_onboarding(repo: AccountRepo, user: AppUser, states: Sequence[ConsentState] | None = None) -> AppUser:
    states = await consent_states(repo, user.user_id) if states is None else states
    profiles = await repo.list_profiles(user.user_id)
    step, completed = next_step(user, states, profiles)
    if (step, completed) == (user.onboarding_step, user.onboarding_completed_at):
        return user
    return await repo.set_onboarding(user.user_id, step, completed)


async def build_me(repo: AccountRepo, user: AppUser) -> MeResponse:
    states = await consent_states(repo, user.user_id)
    user = await sync_onboarding(repo, user, states)
    return MeResponse(
        user_id=user.user_id, onboarding_step=user.onboarding_step, onboarding_completed_at=user.onboarding_completed_at,
        consents=states, health_consent_active=health_writable(states),
    )


def profile_out(p: Profile) -> ProfileOut:
    return ProfileOut(
        profile_id=p.profile_id, relation=p.relation, label=p.label, age_band=p.age_band, pregnancy_status=p.pregnancy_status,
        sort_order=p.sort_order, sex=p.sex, avatar_color=p.avatar_color,
        medications=[MedicationOut(medication_id=m.medication_id, input_text=m.input_text, item_seq=m.item_seq,
                                   confirmed_at=m.confirmed_at) for m in p.medications],
    )


async def _confirmed_meds(request: Request, items: Sequence[MedicationIn]) -> tuple[MedicationInput, ...]:
    """`item_seq`는 확인 함수가 돌려준 것만 남긴다. 확인 함수가 없거나 실패하면 원문만 저장(None)."""
    seqs = [m.item_seq for m in items if m.item_seq]
    known: set[str] = set()
    checker: ItemSeqChecker | None = getattr(request.app.state, ITEM_SEQ_CHECKER_STATE_KEY, None)
    if seqs and checker is not None:
        try:
            known = set(await checker(seqs))
        except Exception as exc:  # noqa: BLE001 - 사전 확인 실패는 원문 저장으로 낮춘다(값은 남기지 않음)
            logger.warning("품목 확인 실패, 원문만 저장: %s", type(exc).__name__)
    return tuple(MedicationInput(m.input_text, m.item_seq if m.item_seq in known else None) for m in items)


# --------------------------------------------------------------------------- 라우트
router = APIRouter()

_ERR = {"model": ErrorBody}
_ACCOUNT_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {**_ERR, "description": "AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함)."},
    403: {**_ERR, "description": "CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류)."},
    422: {**_ERR, "description": "INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다."},
    501: {**_ERR, "description": "토큰 검증기 또는 계정 저장소 미설정(의도된 상태)."},
    503: {**_ERR, "description": "AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소)."},
}


def _responses(*extra: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    out = dict(_ACCOUNT_ERRORS)
    for status, desc in extra:
        out[status] = {**_ERR, "description": desc}
    return out


@router.get("/legal/{doc_type}", response_model=LegalDocumentOut, summary="약관·동의 문서 현재본(게스트 허용)",
            responses={404: {**_ERR, "description": "게시된 문서 없음."}, 422: _ACCOUNT_ERRORS[422],
                       501: _ACCOUNT_ERRORS[501], 503: _ACCOUNT_ERRORS[503]})
async def get_legal(doc_type: DocType, repo: RepoDep, response: Response,
                    version: Annotated[int | None, Query(ge=1, le=100_000)] = None) -> LegalDocumentOut:
    """토큰을 읽지 않는다(`/chat`처럼 게스트 경로). `version`을 주면 그 게시 버전."""
    doc = await (repo.legal_current(doc_type) if version is None else repo.legal_version(doc_type, version))
    if doc is None:
        raise AccountError(404, CODE_NOT_FOUND)
    response.headers["Cache-Control"] = LEGAL_CACHE
    return _legal_out(doc)


def _legal_out(doc: LegalDoc) -> LegalDocumentOut:
    return LegalDocumentOut(
        doc_type=doc.doc_type, version=doc.version, title=doc.title, body_md=doc.body_md, required=doc.required,
        requires_reconsent=doc.requires_reconsent, effective_at=doc.effective_at, legal_review=doc.legal_review,
        body_sha256=doc.body_sha256,
    )


@router.post("/consents", response_model=MeResponse, status_code=201, summary="동의·철회 기록(철회는 즉시 삭제를 일으킨다)",
             responses=_responses((404, "현재본 없는 문서."), (409, "VERSION_MISMATCH·USE_ACCOUNT_DELETE(fields=문서 종류).")))
async def post_consents(body: ConsentRequest, principal: UserDep, repo: RepoDep, response: Response) -> MeResponse:
    response.headers["Cache-Control"] = NO_STORE
    uid = user_id_of(principal)
    await require_account(repo, uid)
    for it in body.items:
        current = await repo.legal_current(it.doc_type)
        if current is None:
            raise AccountError(404, CODE_NOT_FOUND, [it.doc_type])
        if current.version != it.version:
            raise AccountError(409, CODE_VERSION_MISMATCH, [it.doc_type])
        if it.action == "withdraw" and it.doc_type in WITHDRAW_BLOCKED_DOCS:
            raise AccountError(409, CODE_USE_ACCOUNT_DELETE, [it.doc_type])  # 약관·만 14세 확인 철회는 탈퇴(DELETE /me)로만
    await repo.add_consents(uid, [ConsentInput(i.doc_type, i.version, i.action) for i in body.items], body.channel)
    user = await require_account(repo, uid)
    return await build_me(repo, user)


@router.get("/profiles", response_model=list[ProfileOut], summary="내 프로필 목록(본인 1 + 가족 최대 3)", responses=_ACCOUNT_ERRORS)
async def list_profiles(principal: UserDep, repo: RepoDep, response: Response) -> list[ProfileOut]:
    response.headers["Cache-Control"] = NO_STORE
    uid = user_id_of(principal)
    await require_account(repo, uid)
    return [profile_out(p) for p in await repo.list_profiles(uid)]


def _health_fields(pregnancy_changed: bool, meds_written: bool) -> list[str]:
    return [name for name, on in (("pregnancy_status", pregnancy_changed), ("medications", meds_written)) if on]


@router.post("/profiles", response_model=ProfileOut, status_code=201, summary="프로필 추가",
             responses=_responses((409, "SELF_EXISTS(본인 프로필은 1개).")))
async def create_profile(body: ProfileCreate, principal: UserDep, repo: RepoDep, request: Request, response: Response) -> ProfileOut:
    response.headers["Cache-Control"] = NO_STORE
    uid = user_id_of(principal)
    user = await require_account(repo, uid)
    states = await consent_states(repo, uid)
    gate_consents(states, REQUIRED_CONSENT_DOCS)
    health = _health_fields(body.pregnancy_status is not None, bool(body.medications))
    if health and not health_writable(states):
        raise AccountError(422, CODE_HEALTH_CONSENT_REQUIRED, health)
    meds = await _confirmed_meds(request, body.medications)
    prof = await repo.create_profile(uid, ProfileInput(body.relation, body.label, body.age_band, body.pregnancy_status, meds,
                                                       sex=body.sex, avatar_color=body.avatar_color))
    await sync_onboarding(repo, user, states)
    return profile_out(prof)


@router.patch("/profiles/{profile_id}", response_model=ProfileOut, summary="프로필 수정(보낸 칸만, 약은 목록 전체 교체)",
              responses=_responses((404, "없는 프로필(남의 것 포함)."), (409, "SELF_EXISTS·SELF_FIXED(본인 관계는 바꾸지 않는다).")))
async def update_profile(profile_id: uuid.UUID, body: ProfileUpdate, principal: UserDep, repo: RepoDep, request: Request,
                         response: Response) -> ProfileOut:
    response.headers["Cache-Control"] = NO_STORE
    uid = user_id_of(principal)
    user = await require_account(repo, uid)
    pid = str(profile_id)
    cur = await repo.get_profile(uid, pid)
    if cur is None:
        raise AccountError(404, CODE_NOT_FOUND)
    states = await consent_states(repo, uid)
    gate_consents(states, REQUIRED_CONSENT_DOCS)
    sent = body.model_fields_set
    if "relation" in sent and body.relation != cur.relation and "self" in (body.relation, cur.relation):
        raise AccountError(409, CODE_SELF_FIXED, ["relation"])
    health = _health_fields(
        "pregnancy_status" in sent and body.pregnancy_status is not None and body.pregnancy_status != cur.pregnancy_status,
        "medications" in sent and bool(body.medications),
    )
    if health and not health_writable(states):
        raise AccountError(422, CODE_HEALTH_CONSENT_REQUIRED, health)
    meds = await _confirmed_meds(request, body.medications or []) if "medications" in sent else UNSET
    patch = ProfilePatch(
        relation=body.relation if "relation" in sent and body.relation is not None else UNSET,
        label=body.label if "label" in sent else UNSET,
        age_band=body.age_band if "age_band" in sent else UNSET,
        pregnancy_status=body.pregnancy_status if "pregnancy_status" in sent else UNSET,
        medications=meds,
        sex=body.sex if "sex" in sent else UNSET,
        avatar_color=body.avatar_color if "avatar_color" in sent and body.avatar_color is not None else UNSET,
    )
    prof = await repo.update_profile(uid, pid, patch)
    await sync_onboarding(repo, user, states)
    return profile_out(prof)


@router.delete("/profiles/{profile_id}", status_code=204, summary="가족 프로필 삭제(본인 프로필은 409 SELF_REQUIRED)",
               responses=_responses((404, "없는 프로필(남의 것 포함)."), (409, "SELF_REQUIRED.")))
async def delete_profile(profile_id: uuid.UUID, principal: UserDep, repo: RepoDep) -> Response:
    uid = user_id_of(principal)
    user = await require_account(repo, uid)
    pid = str(profile_id)
    cur = await repo.get_profile(uid, pid)
    if cur is None:
        raise AccountError(404, CODE_NOT_FOUND)
    if cur.relation == "self":
        raise AccountError(409, CODE_SELF_REQUIRED)
    if not await repo.delete_profile(uid, pid):
        raise AccountError(404, CODE_NOT_FOUND)
    await sync_onboarding(repo, user)
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


# --------------------------------------------------------------------------- 오류 처리기
_REPO_ERRORS: dict[str, tuple[int, str, tuple[str, ...]]] = {
    "PROFILE_LIMIT": (422, CODE_PROFILE_LIMIT, ("relation",)),
    "SELF_EXISTS": (409, CODE_SELF_EXISTS, ("relation",)),
    "MEDICATION_LIMIT": (422, CODE_MEDICATION_LIMIT, ("medications",)),
    HEALTH_CONSENT_CODE: (422, CODE_HEALTH_CONSENT_REQUIRED, ()),
    "USE_ACCOUNT_DELETE": (409, CODE_USE_ACCOUNT_DELETE, (TERMS_DOC,)),
    "NOT_FOUND": (404, CODE_NOT_FOUND, ()),
    "NO_ACCOUNT": (401, CODE_AUTH_INVALID, ()),
}


def _json(status: int, code: str, fields: Sequence[str] = ()) -> JSONResponse:
    headers = {"Cache-Control": NO_STORE}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=ErrorBody(code=code, fields=list(fields)).model_dump(), headers=headers)


async def account_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, AccountError):
        return _json(exc.status_code, exc.code, exc.fields)
    if isinstance(exc, AccountRepoError):
        status, code, fields = _REPO_ERRORS.get(exc.code, (500, "INTERNAL", ()))
        return _json(status, code, fields)
    if isinstance(exc, RepoUnavailable):
        logger.warning("계정 저장소 응답 없음: %s (%s)", exc, exc.diagnostics())  # 종류 이름·안쪽 원인 종류·초만(DSN·SQL·ID 없음)
        return _json(503, CODE_ACCOUNT_UNAVAILABLE)
    return _json(500, "INTERNAL")


# 요청 형식 오류: 계정 경로는 계정 요청 모델의 칸 이름만 `fields`에 싣는다(사용자가 보낸 임의 키·값은 싣지 않는다)
ACCOUNT_PATH_PREFIXES = ("/me", "/legal", "/consents", "/profiles", "/drugs")  # `/drugs`: 프로필 약 사전 검색(`app.api.drugs`)
_ACCOUNT_FIELDS = frozenset(
    {name for m in (ConsentRequest, ConsentItem, ProfileCreate, ProfileUpdate, MedicationIn) for name in m.model_fields}
    | {"profile_id", "doc_type", "version", "q"}
)


def is_account_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in ACCOUNT_PATH_PREFIXES)


def validation_fields(exc: RequestValidationError) -> list[str]:
    fields: list[str] = []
    for err in exc.errors():
        parts: list[str] = []
        for p in tuple(err.get("loc") or ())[1:]:  # 첫 칸은 body·path·query
            if isinstance(p, int):
                if not parts:
                    break
                parts.append(str(p))
            elif p in _ACCOUNT_FIELDS:
                parts.append(p)
            else:
                break
        path = ".".join(parts) or "body"
        if path not in fields:
            fields.append(path)
    return fields


__all__ = [
    "ACCOUNT_PATH_PREFIXES", "ITEM_SEQ_CHECKER_STATE_KEY", "REPO_STATE_KEY", "AccountError", "ConsentRequest", "ConsentState",
    "LegalDocumentOut", "MeResponse", "ProfileCreate", "ProfileOut", "ProfileUpdate", "account_error_handler", "build_me",
    "consent_states", "get_repo", "is_account_path", "router", "set_item_seq_checker", "set_repo", "validation_fields",
]
