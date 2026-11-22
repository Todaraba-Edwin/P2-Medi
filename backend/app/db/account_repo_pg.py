"""BE-11 계정 저장소 Postgres 구현(psycopg 3, 2026-11-18). 스키마는 `app/db/schema_account.sql`.

- BE-11-06 A: 사용자 메서드는 **한 트랜잭션** 안에서 `SET LOCAL ROLE authenticated`와
  `set_config('request.jwt.claims', {"sub","role","aud"}, true)`를 먼저 실행해 RLS 아래에서 돈다(설계 5.2절). 약관 조회는 `anon`.
  `SET LOCAL`은 트랜잭션이 끝나면 풀리므로 풀 연결에 역할이 남지 않는다. claims에는 **검증을 통과한 사용자 ID만** 넣는다.
- 규칙 위반은 SQL 트리거의 `P0001` 메시지(`PROFILE_LIMIT` 등)를 `AccountRepoError(code)`로 옮긴다. 연결·스키마 오류는 `RepoUnavailable`
  (예외 종류 이름만, DSN·값·SQL 매개변수를 싣지 않는다).
- 연결은 `conn_factory()`(호출마다 새 연결, 기본 `psycopg.connect(dsn)`)로 연다. psycopg가 동기라 메서드는 스레드에서 돈다.
- 원격 적용·접속은 이 모듈을 import하는 것만으로 일어나지 않는다(접속은 메서드 호출 때). 시험은 로컬 DSN이 있을 때만 돈다.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from app.db.account_repo import (
    NO_ACCOUNT_CODE,
    NOT_FOUND_CODE,
    SELF_EXISTS_CODE,
    AccountRepoError,
    AppUser,
    ConsentChannel,
    ConsentInput,
    ConsentRecord,
    DeletionSummary,
    DocType,
    LegalDoc,
    Medication,
    MedicationInput,
    OnboardingStep,
    Profile,
    ProfileInput,
    ProfilePatch,
    RepoUnavailable,
    _Unset,
)

DB_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = DB_DIR / "schema_account.sql"
SEED_FILE = DB_DIR / "seed_legal_v1.sql"
SEED_V2_FILE = DB_DIR / "seed_legal_v2.sql"  # PRD-17-05 A: v2 행 추가(v1 유지)
SEED_V3_FILE = DB_DIR / "seed_legal_v3.sql"  # PRD-17-18 A: terms·privacy_policy v3(보호책임자 연락처 줄 구분)
SEED_FILES = {1: SEED_FILE, 2: SEED_V2_FILE, 3: SEED_V3_FILE}
SEED_AGE14_FILE = DB_DIR / "seed_legal_age14.sql"  # PRD-17-12 A: 만 14세 확인 문서 v1. 스키마를 커밋한 뒤 따로 실행
_EFFECTIVE_PLACEHOLDER = "{{EFFECTIVE_AT}}"
# 값이 아직 없는 자리표시({{PRIVACY_CONTACT}}는 render_privacy_contact가 원격 적용 직전에 채운다). 승인 원문 머리의 안내 문구 `{{…}}`(말줄임표 한 글자)는
# 자리표시가 아니라 본문 문장이므로 제외한다. 주석 줄(--)은 보지 않는다
_PLACEHOLDER_RE = re.compile(r"\{\{(?!…\}\})[^{}\n]+\}\}")
_RULE_CODES = ("PROFILE_LIMIT", "MEDICATION_LIMIT", "USE_ACCOUNT_DELETE", "CONSENT_REQUIRED:sensitive_consent",
               "PROFILE_OWNER_MISMATCH", "AUTH_REQUIRED", "DOCUMENT_FROZEN")

T = TypeVar("T")


def schema_sql() -> str:
    return SCHEMA_FILE.read_text(encoding="utf-8")


def seed_sql(effective_at: datetime, version: int = 1) -> str:
    """약관 시드 SQL(`version` = 1·2·3). 시행 시각은 시간대가 있는 datetime만 받는다(자리표시자에 임의 문자열을 끼우지 않는다).

    `{{EFFECTIVE_AT}}`만 채운다. 그 밖의 자리표시는 그대로 남으므로 원격 게시 전에는 `assert_publishable()`을 거친다.
    """
    if effective_at.tzinfo is None:
        raise ValueError("effective_at에는 시간대가 있어야 한다")
    if version not in SEED_FILES:
        raise ValueError(f"없는 시드 버전: {version}")
    return SEED_FILES[version].read_text(encoding="utf-8").replace(_EFFECTIVE_PLACEHOLDER, effective_at.isoformat())


def seed_age14_sql(effective_at: datetime) -> str:
    """만 14세 확인 문서(`age_14` v1) 시드 SQL. `{{EFFECTIVE_AT}}`만 채운다(`seed_sql`과 같은 규칙).

    `schema_account.sql`의 `ALTER TYPE … ADD VALUE 'age_14'`가 커밋된 뒤 **다른 트랜잭션**에서 실행한다.
    """
    if effective_at.tzinfo is None:
        raise ValueError("effective_at에는 시간대가 있어야 한다")
    return SEED_AGE14_FILE.read_text(encoding="utf-8").replace(_EFFECTIVE_PLACEHOLDER, effective_at.isoformat())


def unfilled_placeholders(sql: str) -> list[str]:
    """SQL(주석 줄 제외)에 남은 `{{…}}` 자리표시를 나온 순서대로(중복 제거) 돌려준다. `{{EFFECTIVE_AT}}`도 남아 있으면 포함한다."""
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(body)))


def assert_publishable(sql: str) -> None:
    """자리표시가 남은 문서는 원격에 게시하지 않는다(PRD-17 ③). 원격 적용 스크립트가 실행 직전에 부른다. 로컬 시험은 부르지 않는다."""
    left = unfilled_placeholders(sql)
    if left:
        raise ValueError(f"자리표시가 남아 원격 게시 불가: {', '.join(left)}")


PRIVACY_CONTACT_PLACEHOLDER = "{{PRIVACY_CONTACT}}"
# 보호책임자 값은 $md$…$md$ 본문 안에 들어간다. 달러 인용·자리표시·표 칸·HTML·줄바꿈을 깨뜨릴 문자는 받지 않는다
_CONTACT_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f${}|<>`\\]")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def render_privacy_contact(sql: str, name: str | None, email: str | None) -> str:
    """`{{PRIVACY_CONTACT}}`를 채운다(PRD-17 ⑫, 2026-11-20). 같은 줄(v2)이면 `개인정보 보호책임자: <이름>, 문의: <이메일>`, 홀로 선 줄(v3, PRD-17-18)이면 `…: <이름>\\` + 줄바꿈 + `문의: <이메일>`.

    값은 env `PRIVACY_OFFICER_NAME`·`PRIVACY_OFFICER_EMAIL`(Settings)에서 원격 적용 직전에만 받는다(저장소에 넣지 않음).
    값이 없거나 비면 ValueError(게시 거부). 오류 메시지에는 값을 싣지 않는다. `body_sha256`은 DB 생성 열이라 채운 본문으로 계산된다.
    """
    name, email = (name or "").strip(), (email or "").strip()
    if not name or not email:
        raise ValueError("PRIVACY_OFFICER_NAME·PRIVACY_OFFICER_EMAIL 값이 없어 {{PRIVACY_CONTACT}}를 채울 수 없다(게시 거부)")
    if _CONTACT_BAD_CHARS.search(name) or _CONTACT_BAD_CHARS.search(email):
        raise ValueError("PRIVACY_OFFICER_NAME·PRIVACY_OFFICER_EMAIL에 허용하지 않는 문자(줄바꿈·$·{}·|·<>·`·\\)가 있다")
    if not _EMAIL_RE.fullmatch(email):
        raise ValueError("PRIVACY_OFFICER_EMAIL이 이메일 형식이 아니다")
    inline = f"개인정보 보호책임자: {name}, 문의: {email}"  # v2: 자리표시가 `· ` 뒤 같은 줄에 있다(게시본 v2 형식 유지)
    split = f"개인정보 보호책임자: {name}\\\n문의: {email}"  # v3(PRD-17-18): 자리표시가 홀로 선 줄 → 두 줄, 줄 끝 `\`는 GFM 강제 줄바꿈

    def fill(line: str) -> str:
        if line.lstrip().startswith("--"):  # 주석 줄(--)은 그대로 둔다(unfilled_placeholders와 같은 규칙). 값이 SQL 주석에 실리지 않게
            return line
        if line.strip() == PRIVACY_CONTACT_PLACEHOLDER:
            return line.replace(PRIVACY_CONTACT_PLACEHOLDER, split)
        return line.replace(PRIVACY_CONTACT_PLACEHOLDER, inline)

    return "".join(fill(line) for line in sql.splitlines(keepends=True))


def _claims(user_id: str) -> str:
    return json.dumps({"sub": user_id, "role": "authenticated", "aud": "authenticated"})


_PROFILE_COLS = "profile_id::text, relation::text, label, age_band::text, pregnancy_status::text, sort_order, sex::text"
_LEGAL_COLS = "doc_type::text, version, title, body_md, required, requires_reconsent, effective_at, legal_review, body_sha256"


class PostgresAccountRepo:
    """`AccountRepo`의 Postgres 구현. 각 메서드 = 연결 1개 + 트랜잭션 1개."""

    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._connect = conn_factory

    def __repr__(self) -> str:  # DSN을 싣지 않는다
        return f"{type(self).__name__}(conn=<set>)"

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresAccountRepo:
        def connect() -> Any:
            import psycopg  # 접속하는 함수 안에서만 import(앱 시작 때 접속 0)

            return psycopg.connect(dsn, connect_timeout=5)

        return cls(connect)

    # ---- 실행 틀
    async def _run(self, role: str, user_id: str | None, fn: Callable[[Any], T]) -> T:
        return await asyncio.to_thread(self._run_sync, role, user_id, fn)

    def _run_sync(self, role: str, user_id: str | None, fn: Callable[[Any], T]) -> T:
        import psycopg
        from psycopg import errors

        try:
            conn = self._connect()
        except psycopg.Error as exc:
            raise RepoUnavailable(type(exc).__name__) from None
        try:
            with conn:  # 정상 종료면 COMMIT, 예외면 ROLLBACK
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL ROLE authenticated" if role == "authenticated" else "SET LOCAL ROLE anon")
                    if user_id is not None:
                        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (_claims(user_id),))
                    return fn(cur)
        except errors.RaiseException as exc:
            msg = (exc.diag.message_primary or "").strip()
            if msg in _RULE_CODES:
                raise AccountRepoError(msg) from None
            raise RepoUnavailable("RaiseException") from None
        except errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_profiles_self":
                raise AccountRepoError(SELF_EXISTS_CODE) from None
            raise RepoUnavailable("UniqueViolation") from None
        except errors.ForeignKeyViolation:
            raise AccountRepoError(NO_ACCOUNT_CODE) from None  # app_users 없음(첫 /me 전) 또는 없는 문서 버전
        except psycopg.Error as exc:
            raise RepoUnavailable(type(exc).__name__) from None
        finally:
            conn.close()

    # ---- 변환
    @staticmethod
    def _legal(row: Sequence[Any]) -> LegalDoc:
        return LegalDoc(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8])

    @staticmethod
    def _profiles(cur: Any, user_id: str, profile_id: str | None = None) -> list[Profile]:
        where, args = ("WHERE user_id = %s", [user_id]) if profile_id is None else \
            ("WHERE user_id = %s AND profile_id = %s", [user_id, profile_id])
        cur.execute(f"SELECT {_PROFILE_COLS} FROM account.profiles {where} ORDER BY sort_order, profile_id", args)  # noqa: S608 - 상수 조각만
        rows = cur.fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        cur.execute(
            "SELECT profile_id::text, medication_id::text, input_text, item_seq, confirmed_at FROM account.profile_medications "
            "WHERE profile_id = ANY(%s::uuid[]) ORDER BY created_at, medication_id", (ids,))
        meds: dict[str, list[Medication]] = {}
        for pid, mid, text, seq, at in cur.fetchall():
            meds.setdefault(pid, []).append(Medication(mid, text, seq.strip() if seq else None, at))
        return [Profile(r[0], r[1], r[2], r[3], r[4], r[5], tuple(meds.get(r[0], ())), sex=r[6]) for r in rows]

    @staticmethod
    def _user(row: Sequence[Any] | None) -> AppUser | None:
        return None if row is None else AppUser(row[0], row[1], row[2])

    @staticmethod
    def _insert_meds(cur: Any, user_id: str, profile_id: str, items: Sequence[MedicationInput]) -> None:
        for m in items:
            cur.execute(
                "INSERT INTO account.profile_medications (profile_id, user_id, input_text, item_seq, confirmed_at) "
                "VALUES (%s, %s, %s, %s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END)",
                (profile_id, user_id, m.input_text, m.item_seq, m.item_seq))

    # ---- 약관(anon)
    async def legal_current(self, doc_type: DocType) -> LegalDoc | None:
        def q(cur: Any) -> LegalDoc | None:
            cur.execute(f"SELECT {_LEGAL_COLS} FROM account.legal_current WHERE doc_type = %s", (doc_type,))  # noqa: S608
            row = cur.fetchone()
            return None if row is None else self._legal(row)

        return await self._run("anon", None, q)

    async def legal_version(self, doc_type: DocType, version: int) -> LegalDoc | None:
        def q(cur: Any) -> LegalDoc | None:
            cur.execute(f"SELECT {_LEGAL_COLS} FROM account.legal_documents WHERE doc_type = %s AND version = %s "  # noqa: S608
                        "AND status = 'published' AND effective_at <= now()", (doc_type, version))
            row = cur.fetchone()
            return None if row is None else self._legal(row)

        return await self._run("anon", None, q)

    async def legal_published(self, doc_type: DocType) -> list[LegalDoc]:
        def q(cur: Any) -> list[LegalDoc]:
            cur.execute(f"SELECT {_LEGAL_COLS} FROM account.legal_documents WHERE doc_type = %s "  # noqa: S608
                        "AND status = 'published' AND effective_at <= now() ORDER BY version", (doc_type,))
            return [self._legal(r) for r in cur.fetchall()]

        return await self._run("anon", None, q)

    # ---- 계정
    async def ensure_user(self, user_id: str) -> AppUser:
        def q(cur: Any) -> AppUser:
            cur.execute("INSERT INTO account.app_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
            cur.execute("SELECT user_id::text, onboarding_step, onboarding_completed_at FROM account.app_users WHERE user_id = %s",
                        (user_id,))
            user = self._user(cur.fetchone())
            if user is None:
                raise AccountRepoError(NO_ACCOUNT_CODE)
            return user

        return await self._run("authenticated", user_id, q)

    async def get_user(self, user_id: str) -> AppUser | None:
        def q(cur: Any) -> AppUser | None:
            cur.execute("SELECT user_id::text, onboarding_step, onboarding_completed_at FROM account.app_users WHERE user_id = %s",
                        (user_id,))
            return self._user(cur.fetchone())

        return await self._run("authenticated", user_id, q)

    async def set_onboarding(self, user_id: str, step: OnboardingStep, completed_at: datetime | None) -> AppUser:
        def q(cur: Any) -> AppUser:
            cur.execute("UPDATE account.app_users SET onboarding_step = %s, onboarding_completed_at = %s WHERE user_id = %s "
                        "RETURNING user_id::text, onboarding_step, onboarding_completed_at", (step, completed_at, user_id))
            user = self._user(cur.fetchone())
            if user is None:
                raise AccountRepoError(NO_ACCOUNT_CODE)
            return user

        return await self._run("authenticated", user_id, q)

    # ---- 동의
    async def latest_consents(self, user_id: str) -> dict[str, ConsentRecord]:
        def q(cur: Any) -> dict[str, ConsentRecord]:
            cur.execute("SELECT doc_type::text, doc_version, action::text, channel, acted_at FROM account.user_consent_current "
                        "WHERE user_id = %s", (user_id,))
            return {r[0]: ConsentRecord(r[0], r[1], r[2], r[3], r[4]) for r in cur.fetchall()}

        return await self._run("authenticated", user_id, q)

    async def add_consents(self, user_id: str, items: Sequence[ConsentInput], channel: ConsentChannel) -> None:
        def q(cur: Any) -> None:
            for it in items:  # 같은 트랜잭션의 now()는 같으므로 순서는 consent_id로 갈린다(뷰 정렬 2순위)
                cur.execute("INSERT INTO account.user_consents (user_id, doc_type, doc_version, action, channel) "
                            "VALUES (%s, %s, %s, %s, %s)", (user_id, it.doc_type, it.version, it.action, channel))

        await self._run("authenticated", user_id, q)

    # ---- 프로필
    async def list_profiles(self, user_id: str) -> list[Profile]:
        return await self._run("authenticated", user_id, lambda cur: self._profiles(cur, user_id))

    async def get_profile(self, user_id: str, profile_id: str) -> Profile | None:
        def q(cur: Any) -> Profile | None:
            rows = self._profiles(cur, user_id, profile_id)
            return rows[0] if rows else None

        return await self._run("authenticated", user_id, q)

    async def create_profile(self, user_id: str, data: ProfileInput) -> Profile:
        def q(cur: Any) -> Profile:
            if data.relation == "self":
                order = 0
            else:  # 1~3 중 빈 자리(동시 삽입 경합은 트리거의 advisory lock과 상한 검사가 막는다)
                cur.execute("SELECT sort_order FROM account.profiles WHERE user_id = %s", (user_id,))
                used = {r[0] for r in cur.fetchall()}
                free = [i for i in (1, 2, 3) if i not in used]
                order = free[0] if free else 3  # 자리가 없으면 트리거가 PROFILE_LIMIT으로 거부한다
            cur.execute(
                "INSERT INTO account.profiles (user_id, relation, label, age_band, pregnancy_status, sort_order, sex) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING profile_id::text",
                (user_id, data.relation, data.label, data.age_band, data.pregnancy_status, order, data.sex))
            pid = cur.fetchone()[0]
            self._insert_meds(cur, user_id, pid, data.medications)
            return self._profiles(cur, user_id, pid)[0]

        return await self._run("authenticated", user_id, q)

    async def update_profile(self, user_id: str, profile_id: str, patch: ProfilePatch) -> Profile:
        def q(cur: Any) -> Profile:
            sets: list[str] = []
            args: list[Any] = []
            for name in ("relation", "label", "age_band", "pregnancy_status", "sex"):  # 열 이름은 이 상수 목록에서만
                value = getattr(patch, name)
                if not isinstance(value, _Unset):
                    sets.append(f"{name} = %s")
                    args.append(value)
            if sets:
                cur.execute(f"UPDATE account.profiles SET {', '.join(sets)} WHERE user_id = %s AND profile_id = %s "  # noqa: S608
                            "RETURNING profile_id", [*args, user_id, profile_id])
                if cur.fetchone() is None:
                    raise AccountRepoError(NOT_FOUND_CODE)
            elif not self._profiles(cur, user_id, profile_id):
                raise AccountRepoError(NOT_FOUND_CODE)
            if not isinstance(patch.medications, _Unset):
                cur.execute("DELETE FROM account.profile_medications WHERE user_id = %s AND profile_id = %s", (user_id, profile_id))
                self._insert_meds(cur, user_id, profile_id, patch.medications)
            return self._profiles(cur, user_id, profile_id)[0]

        return await self._run("authenticated", user_id, q)

    async def delete_profile(self, user_id: str, profile_id: str) -> bool:
        def q(cur: Any) -> bool:
            cur.execute("DELETE FROM account.profiles WHERE user_id = %s AND profile_id = %s", (user_id, profile_id))
            return bool(cur.rowcount)

        return await self._run("authenticated", user_id, q)

    # ---- 탈퇴
    async def delete_account(self, user_id: str) -> DeletionSummary:
        def q(cur: Any) -> DeletionSummary:
            cur.execute("SELECT n_profiles, n_medications, n_consents FROM account.delete_my_account()")
            row = cur.fetchone()
            return DeletionSummary(*(int(x or 0) for x in row)) if row else DeletionSummary(0, 0, 0)

        return await self._run("authenticated", user_id, q)


__all__ = ["SCHEMA_FILE", "SEED_AGE14_FILE", "SEED_FILE", "SEED_FILES", "SEED_V2_FILE", "SEED_V3_FILE", "PostgresAccountRepo", "assert_publishable",
           "schema_sql", "seed_age14_sql", "seed_sql", "unfilled_placeholders"]
