"""BE-11 계정 저장소: 인터페이스(`AccountRepo`)·도메인 값·메모리 가짜 구현(2026-11-18).

- 설계 원본: `P2-doc/PJ2-계정-프로필-데이터.md` 4~8장. 사용자 결정(2026-11-18 "권장대로"): BE-11-06 A(`account` 스키마 + RLS),
  07 A(연령대 11구간), 08 A(관계 5값), 09 A(임신 주차 열 없음), 10 A(`app_users`는 첫 `GET /me`에 생성),
  12 A(필수 개인정보 동의 철회 → 프로필만 삭제, 계정 유지), 22 A(탈퇴 시 동의 기록 포함 즉시 전부 파기, 파기 사실은 일자·건수만).
- `InMemoryAccountRepo`는 SQL(`app/db/schema_account.sql`)의 트리거 규칙(프로필 상한·본인 1행·건강 동의·철회 삭제·약관 철회 거부·
  파기 집계)을 같은 동작으로 흉내 낸다. API 시험과 DB 없는 개발에 쓴다. Postgres 구현은 `app/db/account_repo_pg.py`.
- 2026-11-20 GROUP-03 B1: 프로필 성별 선택 칸 `sex`(`female`·`male`, None = 미입력, FE-11-09 C·PRD-17-13 A, 건강 정보 아님)와
  동의 문서 종류 `age_14`(만 14세 이상 확인, PRD-17-12 A, 첫 로그인 필수, 철회는 `terms`처럼 `USE_ACCOUNT_DELETE`).
- 저장소 메서드는 **호출자가 검증한 사용자 ID만** 받는다(토큰 검증 뒤 `Principal.user_id`). 값(건강 정보 등)을 로그에 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Final, Literal, Protocol, runtime_checkable

# --------------------------------------------------------------------------- 값 집합(SQL enum과 같다)
DocType = Literal["terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14", "terms_guest"]
ConsentDocType = Literal["terms", "privacy_consent", "sensitive_consent", "age_14"]
ConsentAction = Literal["agree", "withdraw"]
ConsentChannel = Literal["onboarding", "settings", "reconsent"]
Relation = Literal["self", "child", "parent", "spouse", "other"]
PregnancyStatus = Literal["pregnant", "not_pregnant", "unknown"]
AvatarColor = Literal["yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray"]  # 병아리 배경색 8색(2026-11-23). 건강 정보 아님
AVATAR_COLORS: Final = ("yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray")
DEFAULT_AVATAR_COLOR: Final = "yellow"
Sex = Literal["female", "male"]  # "기타" 없음, None = 미입력(FE-11-09 C: 남성 프로필만 임신 여부 선택을 숨기는 데 쓴다)
AgeBand = Literal["m0_2", "m3_5", "m6_11", "y1", "y2", "y3_5", "y6_11", "y12_14", "y15_18", "y19_64", "y65_plus"]
OnboardingStep = Literal["consent", "profile_self", "family", "done"]
LegalReview = Literal["not_reviewed", "reviewed"]

DOC_TYPES: Final = ("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14", "terms_guest")
# privacy_policy·terms_guest는 고지·열람용 문서(동의 대상 아님, PRD-17-22 A: 게스트판 이용약관은 동의를 저장하지 않는다)
CONSENT_DOC_TYPES: Final = ("terms", "privacy_consent", "sensitive_consent", "age_14")
HEALTH_DOC: Final = "sensitive_consent"
PROFILE_DOC: Final = "privacy_consent"
TERMS_DOC: Final = "terms"
AGE_14_DOC: Final = "age_14"  # 만 14세 이상 확인(PRD-17-12 A). 첫 로그인 필수
REQUIRED_CONSENT_DOCS: Final = (TERMS_DOC, PROFILE_DOC, AGE_14_DOC)  # 온보딩·프로필 저장에 필요한 동의
WITHDRAW_BLOCKED_DOCS: Final = (TERMS_DOC, AGE_14_DOC)  # 철회 대신 탈퇴(DELETE /me)로만 → USE_ACCOUNT_DELETE
SEXES: Final = ("female", "male")
AGE_BANDS: Final = ("m0_2", "m3_5", "m6_11", "y1", "y2", "y3_5", "y6_11", "y12_14", "y15_18", "y19_64", "y65_plus")

PROFILE_LIMIT: Final = 4  # 본인 1 + 가족 3(BE-11-01 B)
FAMILY_LIMIT: Final = 3
MEDICATION_LIMIT: Final = 10  # `CONFIRMED_DRUGS_MAX`(app/api/request.py)와 같다
LABEL_MAX_CHARS: Final = 20
MEDICATION_TEXT_MAX_CHARS: Final = 100  # `DRUG_NAME_MAX_CHARS`와 같다


# --------------------------------------------------------------------------- 오류
class AccountRepoError(Exception):
    """저장소 규칙 위반. `code`는 SQL 트리거의 `RAISE EXCEPTION` 문자열과 같다(값·ID를 담지 않는다)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RepoUnavailable(Exception):  # noqa: N818 - 도메인 이름(저장소 장애)
    """DB에 닿지 못했거나 스키마가 없다. 메시지는 예외 종류 이름만.

    진단용으로 안쪽 원인의 종류 이름(`cause`)과 소요 시간(`elapsed_s`)을 속성으로 싣는다(메시지·DSN·SQL은 싣지 않는다).
    """

    def __init__(self, kind: str, *, cause: str = "-", elapsed_s: float | None = None) -> None:
        super().__init__(kind)
        self.cause = cause
        self.elapsed_s = elapsed_s

    def diagnostics(self) -> str:
        """로그용 한 조각: `원인=TimeoutError 4.9s`. 종류 이름과 초만 담는다."""
        return f"원인={self.cause}" + ("" if self.elapsed_s is None else f" {self.elapsed_s:.1f}s")


# 규칙 코드(SQL과 공유)
PROFILE_LIMIT_CODE: Final = "PROFILE_LIMIT"
SELF_EXISTS_CODE: Final = "SELF_EXISTS"
MEDICATION_LIMIT_CODE: Final = "MEDICATION_LIMIT"
HEALTH_CONSENT_CODE: Final = "CONSENT_REQUIRED:sensitive_consent"
USE_ACCOUNT_DELETE_CODE: Final = "USE_ACCOUNT_DELETE"
NOT_FOUND_CODE: Final = "NOT_FOUND"
GUEST_TARGET: Final = "guest"  # 기본 대상 값: 게스트로 이용
NO_ACCOUNT_CODE: Final = "NO_ACCOUNT"


# --------------------------------------------------------------------------- 값
@dataclass(frozen=True, slots=True)
class LegalDoc:
    doc_type: DocType
    version: int
    title: str
    body_md: str
    required: bool
    requires_reconsent: bool
    effective_at: datetime
    legal_review: LegalReview
    body_sha256: str


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    doc_type: ConsentDocType
    doc_version: int
    action: ConsentAction
    channel: ConsentChannel
    acted_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentInput:
    doc_type: ConsentDocType
    version: int
    action: ConsentAction


@dataclass(frozen=True, slots=True)
class AppUser:
    user_id: str
    onboarding_step: OnboardingStep
    onboarding_completed_at: datetime | None
    # 기본 프로필(대상, 2026-11-23 FE-17 U-08): 마지막으로 고른 대상을 새 세션의 기본값으로 저장한다. 미설정 = (None, False).
    # 프로필 선택 상태이지 건강 정보가 아니며 프로필 저장 동의가 있는 계정 경로의 최소 항목이다(CLAUDE.md 1장). 둘은 동시에 설정되지 않는다.
    default_profile_id: str | None = None
    default_guest: bool = False

    @property
    def default_target(self) -> str | None:
        """API 값: `"guest"`, 프로필 UUID 문자열, 미설정이면 None."""
        return GUEST_TARGET if self.default_guest else self.default_profile_id


@dataclass(frozen=True, slots=True)
class Medication:
    medication_id: str
    input_text: str
    item_seq: str | None
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MedicationInput:
    input_text: str
    item_seq: str | None = None  # 사전에서 확인된 것만(API가 거른다). None이면 원문만


@dataclass(frozen=True, slots=True)
class Profile:
    profile_id: str
    relation: Relation
    label: str | None
    age_band: AgeBand | None
    pregnancy_status: PregnancyStatus | None
    sort_order: int
    medications: tuple[Medication, ...] = ()
    sex: Sex | None = None  # 선택(건강 정보 아님)
    avatar_color: AvatarColor = "yellow"  # 병아리 배경색. 건강 정보가 아니라 동의한 최소 항목(CLAUDE.md 1장)


class _Unset:
    _inst: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final = _Unset()  # PATCH에서 "보내지 않은 칸"(None = 지움과 구분)


@dataclass(frozen=True, slots=True)
class ProfileInput:
    relation: Relation
    label: str | None = None
    age_band: AgeBand | None = None
    pregnancy_status: PregnancyStatus | None = None
    medications: tuple[MedicationInput, ...] = ()
    sex: Sex | None = None  # 건강 동의 없이 저장(privacy_consent만 필요)
    avatar_color: AvatarColor = "yellow"  # 건강 동의 불필요


@dataclass(frozen=True, slots=True)
class ProfilePatch:
    relation: Relation | _Unset = UNSET
    label: str | None | _Unset = UNSET
    age_band: AgeBand | None | _Unset = UNSET
    pregnancy_status: PregnancyStatus | None | _Unset = UNSET
    medications: tuple[MedicationInput, ...] | _Unset = UNSET  # 보내면 목록 전체 교체
    sex: Sex | None | _Unset = UNSET
    avatar_color: AvatarColor | _Unset = UNSET  # null 불가(지우면 기본값이 아니라 거부)


@dataclass(frozen=True, slots=True)
class DeletionSummary:
    """탈퇴 때 지운 건수(BE-11-22 A). 식별자 없음."""

    profiles: int
    medications: int
    consents: int


def body_sha256(body_md: str) -> str:
    return hashlib.sha256(body_md.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- 인터페이스
@runtime_checkable
class AccountRepo(Protocol):
    """계정 저장소. 사용자별 메서드는 그 사용자 행만 읽고 쓴다(Postgres는 RLS, 메모리는 dict 키)."""

    async def legal_current(self, doc_type: DocType) -> LegalDoc | None:
        """시행 중 게시본 중 최신 버전(설계 8장 `legal_current`)."""
        ...

    async def legal_version(self, doc_type: DocType, version: int) -> LegalDoc | None:
        """게시된(시행 전 포함 X) 특정 버전."""
        ...

    async def legal_published(self, doc_type: DocType) -> list[LegalDoc]:
        """시행 중 게시본 전부(버전 오름차순). 재동의 판정용."""
        ...

    async def ensure_user(self, user_id: str) -> AppUser:
        """`app_users` 행을 없으면 만들고 돌려준다(BE-11-10 A, 첫 `GET /me`)."""
        ...

    async def get_user(self, user_id: str) -> AppUser | None: ...

    async def set_onboarding(self, user_id: str, step: OnboardingStep, completed_at: datetime | None) -> AppUser: ...

    async def set_default_target(self, user_id: str, target: str | None) -> AppUser:
        """기본 대상 저장(`"guest"`·본인 프로필 UUID 문자열·None=미설정). 본인 소유가 아니거나 없는 프로필이면 `NOT_FOUND`(소유 여부 비노출)."""
        ...

    async def latest_consents(self, user_id: str) -> dict[str, ConsentRecord]:
        """문서 종류별 가장 최근 기록."""
        ...

    async def add_consents(self, user_id: str, items: Sequence[ConsentInput], channel: ConsentChannel) -> None:
        """한 트랜잭션으로 기록을 더한다. 철회는 즉시 삭제를 일으킨다(6.3절). `terms` 철회는 `USE_ACCOUNT_DELETE`."""
        ...

    async def list_profiles(self, user_id: str) -> list[Profile]: ...

    async def get_profile(self, user_id: str, profile_id: str) -> Profile | None: ...

    async def create_profile(self, user_id: str, data: ProfileInput) -> Profile: ...

    async def update_profile(self, user_id: str, profile_id: str, patch: ProfilePatch) -> Profile: ...

    async def delete_profile(self, user_id: str, profile_id: str) -> bool: ...

    async def delete_account(self, user_id: str) -> DeletionSummary:
        """계정 행과 프로필·약·동의 기록을 즉시 모두 지우고, 파기 집계(일자·건수)만 남긴다(BE-11-22 A). 없으면 0건."""
        ...


# --------------------------------------------------------------------------- 메모리 가짜
@dataclass
class _UserData:
    user: AppUser
    profiles: dict[str, Profile] = field(default_factory=dict)
    consents: list[ConsentRecord] = field(default_factory=list)


@dataclass
class DeletionLogRow:
    deleted_on: date
    accounts: int
    profiles: int
    medications: int
    consents: int


class InMemoryAccountRepo:
    """메모리 가짜 저장소. SQL 트리거 규칙을 같은 순서로 흉내 낸다. 프로세스 안에서만 살고 스레드 안전을 보장하지 않는다(시험·개발용)."""

    def __init__(self, documents: Sequence[LegalDoc] = (), *, clock: Callable[[], datetime] = utcnow,
                 id_factory: Callable[[], str] = lambda: str(uuid.uuid4()), auth_users: set[str] | None = None) -> None:
        self._docs: dict[tuple[str, int], LegalDoc] = {(d.doc_type, d.version): d for d in documents}
        # `app_users.user_id → auth.users(id)` FK 흉내(BE-11-24 A 시험). 주면 이 집합에 없는 사용자는 ensure_user가 NO_ACCOUNT
        # (PG의 ForeignKeyViolation과 같은 결과). None이면 검사하지 않는다(이전 동작)
        self.auth_users = auth_users
        self._users: dict[str, _UserData] = {}
        self._clock = clock
        self._new_id = id_factory
        self.deletion_log: dict[date, DeletionLogRow] = {}
        self.calls = 0  # 시험: /chat이 저장소를 부르지 않음을 확인

    def __repr__(self) -> str:
        return f"{type(self).__name__}(users={len(self._users)})"

    # ---- 시험 도우미
    def add_document(self, doc: LegalDoc) -> None:
        self._docs[(doc.doc_type, doc.version)] = doc

    def user_count(self) -> int:
        return len(self._users)

    # ---- 약관
    def _effective(self, doc_type: str) -> list[LegalDoc]:
        now = self._clock()
        return sorted((d for (t, _), d in self._docs.items() if t == doc_type and d.effective_at <= now), key=lambda d: d.version)

    async def legal_current(self, doc_type: DocType) -> LegalDoc | None:
        self.calls += 1
        docs = self._effective(doc_type)
        return docs[-1] if docs else None

    async def legal_version(self, doc_type: DocType, version: int) -> LegalDoc | None:
        self.calls += 1
        doc = self._docs.get((doc_type, version))
        return doc if doc is not None and doc.effective_at <= self._clock() else None

    async def legal_published(self, doc_type: DocType) -> list[LegalDoc]:
        self.calls += 1
        return self._effective(doc_type)

    # ---- 계정
    def _data(self, user_id: str) -> _UserData:
        data = self._users.get(user_id)
        if data is None:
            raise AccountRepoError(NO_ACCOUNT_CODE)
        return data

    async def ensure_user(self, user_id: str) -> AppUser:
        self.calls += 1
        data = self._users.get(user_id)
        if data is None:
            if self.auth_users is not None and user_id not in self.auth_users:
                raise AccountRepoError(NO_ACCOUNT_CODE)
            data = self._users[user_id] = _UserData(AppUser(user_id, "consent", None))
        return data.user

    async def get_user(self, user_id: str) -> AppUser | None:
        self.calls += 1
        data = self._users.get(user_id)
        return data.user if data else None

    async def set_onboarding(self, user_id: str, step: OnboardingStep, completed_at: datetime | None) -> AppUser:
        self.calls += 1
        data = self._data(user_id)
        data.user = replace(data.user, onboarding_step=step, onboarding_completed_at=completed_at)
        return data.user

    async def set_default_target(self, user_id: str, target: str | None) -> AppUser:
        self.calls += 1
        data = self._data(user_id)
        if target is not None and target != GUEST_TARGET and target not in data.profiles:
            raise AccountRepoError(NOT_FOUND_CODE)
        data.user = replace(data.user, default_guest=target == GUEST_TARGET,
                            default_profile_id=target if target not in (None, GUEST_TARGET) else None)
        return data.user

    # ---- 동의
    def _latest(self, data: _UserData) -> dict[str, ConsentRecord]:
        out: dict[str, ConsentRecord] = {}
        for rec in data.consents:  # 추가 순서 = 시각 순서
            out[rec.doc_type] = rec
        return out

    async def latest_consents(self, user_id: str) -> dict[str, ConsentRecord]:
        self.calls += 1
        return self._latest(self._data(user_id))

    def _health_active(self, data: _UserData) -> bool:
        rec = self._latest(data).get(HEALTH_DOC)
        return rec is not None and rec.action == "agree"

    async def add_consents(self, user_id: str, items: Sequence[ConsentInput], channel: ConsentChannel) -> None:
        self.calls += 1
        data = self._data(user_id)
        for it in items:  # 트랜잭션처럼: 먼저 전부 검사
            if it.doc_type not in CONSENT_DOC_TYPES or (it.doc_type, it.version) not in self._docs:
                raise AccountRepoError(NOT_FOUND_CODE)
            if it.action == "withdraw" and it.doc_type in WITHDRAW_BLOCKED_DOCS:
                raise AccountRepoError(USE_ACCOUNT_DELETE_CODE)
        now = self._clock()
        for it in items:
            data.consents.append(ConsentRecord(it.doc_type, it.version, it.action, channel, now))
            if it.action != "withdraw":
                continue
            if it.doc_type == HEALTH_DOC:  # 임신 여부 NULL, 약 전부 삭제
                data.profiles = {k: replace(p, pregnancy_status=None, medications=()) for k, p in data.profiles.items()}
            elif it.doc_type == PROFILE_DOC:  # 프로필 전부 삭제(성별 포함), 계정 유지(BE-11-12 A)
                data.profiles = {}

    # ---- 프로필
    def _sorted(self, data: _UserData) -> list[Profile]:
        return sorted(data.profiles.values(), key=lambda p: (p.sort_order, p.profile_id))

    async def list_profiles(self, user_id: str) -> list[Profile]:
        self.calls += 1
        return self._sorted(self._data(user_id))

    async def get_profile(self, user_id: str, profile_id: str) -> Profile | None:
        self.calls += 1
        return self._data(user_id).profiles.get(profile_id)

    def _meds(self, items: Sequence[MedicationInput]) -> tuple[Medication, ...]:
        if len(items) > MEDICATION_LIMIT:
            raise AccountRepoError(MEDICATION_LIMIT_CODE)
        now = self._clock()
        return tuple(Medication(self._new_id(), m.input_text, m.item_seq, now if m.item_seq else None) for m in items)

    def _check_relation(self, data: _UserData, relation: str, exclude: str | None = None) -> None:
        others = [p for k, p in data.profiles.items() if k != exclude]
        if relation == "self":
            if any(p.relation == "self" for p in others):
                raise AccountRepoError(SELF_EXISTS_CODE)
        elif sum(p.relation != "self" for p in others) >= FAMILY_LIMIT:
            raise AccountRepoError(PROFILE_LIMIT_CODE)
        if len(others) >= PROFILE_LIMIT:
            raise AccountRepoError(PROFILE_LIMIT_CODE)

    async def create_profile(self, user_id: str, data_in: ProfileInput) -> Profile:
        self.calls += 1
        data = self._data(user_id)
        self._check_relation(data, data_in.relation)
        if (data_in.pregnancy_status is not None or data_in.medications) and not self._health_active(data):
            raise AccountRepoError(HEALTH_CONSENT_CODE)
        used = {p.sort_order for p in data.profiles.values()}
        order = 0 if data_in.relation == "self" else min(i for i in range(1, PROFILE_LIMIT) if i not in used)
        prof = Profile(self._new_id(), data_in.relation, data_in.label, data_in.age_band, data_in.pregnancy_status, order,
                       self._meds(data_in.medications), sex=data_in.sex, avatar_color=data_in.avatar_color)
        data.profiles[prof.profile_id] = prof
        return prof

    async def update_profile(self, user_id: str, profile_id: str, patch: ProfilePatch) -> Profile:
        self.calls += 1
        data = self._data(user_id)
        cur = data.profiles.get(profile_id)
        if cur is None:
            raise AccountRepoError(NOT_FOUND_CODE)
        changes: dict[str, object] = {}
        if not isinstance(patch.relation, _Unset) and patch.relation != cur.relation:
            self._check_relation(data, patch.relation, exclude=profile_id)
            changes["relation"] = patch.relation
        for name in ("label", "age_band", "pregnancy_status", "sex", "avatar_color"):
            value = getattr(patch, name)
            if not isinstance(value, _Unset):
                changes[name] = value
        new_preg = changes.get("pregnancy_status", cur.pregnancy_status)
        if "pregnancy_status" in changes and new_preg is not None and new_preg != cur.pregnancy_status \
                and not self._health_active(data):
            raise AccountRepoError(HEALTH_CONSENT_CODE)
        if not isinstance(patch.medications, _Unset):
            if patch.medications and not self._health_active(data):
                raise AccountRepoError(HEALTH_CONSENT_CODE)
            changes["medications"] = self._meds(patch.medications)
        new = replace(cur, **changes)  # type: ignore[arg-type]
        data.profiles[profile_id] = new
        return new

    async def delete_profile(self, user_id: str, profile_id: str) -> bool:
        self.calls += 1
        data = self._data(user_id)
        removed = data.profiles.pop(profile_id, None) is not None
        if removed and data.user.default_profile_id == profile_id:  # PG의 FK ON DELETE SET NULL 흉내: 미설정으로 복귀
            data.user = replace(data.user, default_profile_id=None)
        return removed

    # ---- 탈퇴
    async def delete_account(self, user_id: str) -> DeletionSummary:
        self.calls += 1
        data = self._users.pop(user_id, None)
        if data is None:
            return DeletionSummary(0, 0, 0)
        summary = DeletionSummary(
            profiles=len(data.profiles),
            medications=sum(len(p.medications) for p in data.profiles.values()),
            consents=len(data.consents),
        )
        today = self._clock().date()
        row = self.deletion_log.setdefault(today, DeletionLogRow(today, 0, 0, 0, 0))
        row.accounts += 1
        row.profiles += summary.profiles
        row.medications += summary.medications
        row.consents += summary.consents
        return summary


__all__ = [
    "AGE_14_DOC", "AGE_BANDS", "CONSENT_DOC_TYPES", "DOC_TYPES", "FAMILY_LIMIT", "HEALTH_DOC", "MEDICATION_LIMIT", "PROFILE_DOC",
    "PROFILE_LIMIT", "REQUIRED_CONSENT_DOCS", "SEXES", "TERMS_DOC", "WITHDRAW_BLOCKED_DOCS", "UNSET", "AccountRepo", "AccountRepoError", "AppUser", "ConsentInput", "ConsentRecord", "DeletionLogRow",
    "DeletionSummary", "GUEST_TARGET", "InMemoryAccountRepo", "LegalDoc", "Medication", "MedicationInput", "Profile", "ProfileInput", "ProfilePatch",
    "RepoUnavailable", "body_sha256", "utcnow",
]
