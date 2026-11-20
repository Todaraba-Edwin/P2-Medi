"""GROUP-03 B1 로컬 Postgres 시험: 프로필 성별(`sex`)·만 14세 확인(`age_14`)(2026-11-20). 원격 DB·네트워크·LLM 호출 0.

환경변수 `LOCAL_PG_DSN`이 없거나 로컬 주소가 아니면 skip한다(`.env`는 읽지 않음, test_be11_account_pg.py와 같은 규칙).

① 이전 스키마(age_14·sex 없음)가 적용된 DB에 새 `schema_account.sql`을 다시 적용하면 enum 값·열이 더해진다(재실행 안전, 두 번)
② `age_14` 시드는 스키마 커밋 뒤 따로 실행해 게시되고, 필수 동의 판정(`required_ok`)에 들어간다
③ `age_14` 철회는 트리거가 `USE_ACCOUNT_DELETE`로 막는다
④ 성별은 건강 동의 없이 저장·수정·지우기, 잘못된 값은 DB가 거부, `privacy_consent` 철회 때 프로필과 함께 지워진다
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.api.account import consent_states, required_ok
from app.db.account_repo import AccountRepoError, ConsentInput, ProfileInput, ProfilePatch
from app.db.account_repo_pg import PostgresAccountRepo, schema_sql, seed_age14_sql, seed_sql

LOCAL_PG_DSN: str | None = os.environ.get("LOCAL_PG_DSN") or None
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "/")
AUTH_STUB = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claims', true)::json->>'sub', '')::uuid $$;
GRANT USAGE ON SCHEMA auth TO anon, authenticated;
GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated;
"""


def _old_schema() -> str:
    """B1 이전 스키마를 흉내 낸다: doc_type에 age_14 없음, sex enum·열 없음, 철회 트리거는 terms만."""
    sql = schema_sql()
    for new, old in (
        ("'sensitive_consent', 'age_14');", "'sensitive_consent');"),
        ("ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'age_14';", ""),
        ("ALTER TABLE account.profiles ADD COLUMN IF NOT EXISTS sex account.sex;", ""),
        ("IF NEW.doc_type IN ('terms', 'age_14') THEN", "IF NEW.doc_type = 'terms' THEN"),
    ):
        assert sql.count(new) == 1, new
        sql = sql.replace(new, old)
    sql = sql.replace("CREATE TYPE account.sex AS ENUM ('female', 'male');", "NULL;")
    return sql


_CREATED: list[str] = []


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    _CREATED.append(uid)
    return uid


@pytest.fixture(scope="module")
def migrated_dsn() -> Iterator[str]:
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    effective = datetime.now(UTC) - timedelta(minutes=1)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(_old_schema())
        conn.execute(seed_sql(effective))
        before = conn.execute("SELECT enum_range(NULL::account.doc_type)::text[]").fetchone()[0]
        assert "age_14" not in before  # 이전 스키마가 맞게 흉내 났는지
        for _ in range(2):  # 이전 DB 위에 새 스키마·시드를 두 번(재실행 안전)
            conn.execute(schema_sql())
            conn.execute(seed_age14_sql(effective))
    try:
        yield LOCAL_PG_DSN
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            if _CREATED:
                conn.execute("DELETE FROM auth.users WHERE id = ANY(%s::uuid[])", (_CREATED,))
        _CREATED.clear()


def _onboard(repo: PostgresAccountRepo, uid: str, *, age_14: bool = True) -> None:
    asyncio.run(repo.ensure_user(uid))
    items = [ConsentInput("terms", 1, "agree"), ConsentInput("privacy_consent", 1, "agree")]
    if age_14:
        items.append(ConsentInput("age_14", 1, "agree"))
    asyncio.run(repo.add_consents(uid, items, "onboarding"))


def test_pg_migration_adds_enum_values_and_column(migrated_dsn):
    with psycopg.connect(migrated_dsn) as conn:
        doc_types = conn.execute("SELECT enum_range(NULL::account.doc_type)::text[]").fetchone()[0]
        sexes = conn.execute("SELECT enum_range(NULL::account.sex)::text[]").fetchone()[0]
        col = conn.execute("SELECT data_type, udt_name, is_nullable FROM information_schema.columns "
                           "WHERE table_schema = 'account' AND table_name = 'profiles' AND column_name = 'sex'").fetchone()
        n_age14 = conn.execute("SELECT count(*) FROM account.legal_documents WHERE doc_type = 'age_14'").fetchone()[0]
    assert doc_types.count("age_14") == 1 and sexes == ["female", "male"]
    assert col == ("USER-DEFINED", "sex", "YES")
    assert n_age14 == 1  # 두 번 적용해도 한 행


def test_pg_age_14_published_and_required(migrated_dsn):
    repo = PostgresAccountRepo.from_dsn(migrated_dsn)
    doc = asyncio.run(repo.legal_current("age_14"))
    assert doc is not None and (doc.version, doc.required, doc.body_md, doc.legal_review) == (1, True, "만 14세 이상입니다.", "not_reviewed")
    a = _new_user(migrated_dsn)
    _onboard(repo, a, age_14=False)
    assert not required_ok(asyncio.run(consent_states(repo, a)))
    asyncio.run(repo.add_consents(a, [ConsentInput("age_14", 1, "agree")], "onboarding"))
    assert required_ok(asyncio.run(consent_states(repo, a)))


def test_pg_age_14_withdraw_blocked_by_trigger(migrated_dsn):
    repo = PostgresAccountRepo.from_dsn(migrated_dsn)
    a = _new_user(migrated_dsn)
    _onboard(repo, a)
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.add_consents(a, [ConsentInput("age_14", 1, "withdraw")], "settings"))
    assert info.value.code == "USE_ACCOUNT_DELETE"


def test_pg_sex_without_health_consent_and_deleted_with_profiles(migrated_dsn):
    repo = PostgresAccountRepo.from_dsn(migrated_dsn)
    a = _new_user(migrated_dsn)
    _onboard(repo, a)  # sensitive_consent 없음
    me = asyncio.run(repo.create_profile(a, ProfileInput("self", sex="female")))
    kid = asyncio.run(repo.create_profile(a, ProfileInput("child")))
    assert (me.sex, kid.sex) == ("female", None)
    assert asyncio.run(repo.update_profile(a, kid.profile_id, ProfilePatch(label="첫째"))).sex is None  # 보내지 않으면 그대로
    assert asyncio.run(repo.update_profile(a, kid.profile_id, ProfilePatch(sex="male"))).sex == "male"
    assert asyncio.run(repo.update_profile(a, me.profile_id, ProfilePatch(sex=None))).sex is None
    with pytest.raises(psycopg.errors.InvalidTextRepresentation), psycopg.connect(migrated_dsn) as conn:
        conn.execute("UPDATE account.profiles SET sex = 'other' WHERE profile_id = %s", (me.profile_id,))
    asyncio.run(repo.add_consents(a, [ConsentInput("privacy_consent", 1, "withdraw")], "settings"))
    assert asyncio.run(repo.list_profiles(a)) == []
