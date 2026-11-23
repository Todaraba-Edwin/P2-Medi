"""기본 프로필(대상) `app_users.default_profile_id`·`default_guest` 로컬 Postgres 시험(2026-11-23, FE-17 U-08). 원격 DB·네트워크·LLM 호출 0.

환경변수 `LOCAL_PG_DSN`이 없거나 로컬 주소가 아니면 skip한다(`.env`는 읽지 않음, test_be11_avatar_color_pg.py와 같은 규칙).

① 열이 없는 이전 스키마의 기존 사용자 행이 마이그레이션 SQL로 미설정(null, false)이 되고, 두 번 돌려도 안전하다(재실행 안전)
② CHECK(guest면 프로필 null)·FK(없는 프로필 거부) 존재
③ 저장소 왕복(미설정·guest·프로필·되돌리기)과 타 사용자 프로필 NOT_FOUND
④ 프로필 삭제 시 FK ON DELETE SET NULL로 미설정 복귀, 탈퇴(계정 삭제) 함수도 동작
⑤ RLS 격리: 타 사용자는 값을 읽거나 바꿀 수 없다(authenticated 역할의 열 단위 UPDATE 권한 포함)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.db.account_repo import AccountRepoError, ConsentInput, ProfileInput
from app.db.account_repo_pg import PostgresAccountRepo, migrate_default_target_sql, schema_sql, seed_age14_sql, seed_sql

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
_CREATED: list[str] = []
MISSING_PROFILE = "33333333-3333-4333-8333-333333333333"


def _old_schema() -> str:
    """기본 대상 이전 스키마를 흉내 낸다(열·FK·CHECK·권한 블록 제거)."""
    sql, n = re.subn(r"ALTER TABLE account\.app_users ADD COLUMN IF NOT EXISTS default_profile_id.*?END \$\$;\n"
                     r"-- 본인 행의 이 두 칸만.*?END \$\$;\n", "", schema_sql(), flags=re.S)
    assert n == 1 and "default_profile_id" not in re.sub(r"--[^\n]*", "", sql)
    return sql


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    _CREATED.append(uid)
    return uid


def _as_user(dsn: str, uid: str, sql: str, params: tuple = ()):
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": uid}),))
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


@pytest.fixture(scope="module")
def migrated() -> Iterator[tuple[str, list[str]]]:
    """(dsn, 이전 스키마 때 만든 사용자 id 두 개). 마이그레이션 SQL을 두 번 적용한 상태."""
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    effective = datetime.now(UTC) - timedelta(minutes=1)
    old_users: list[str] = []
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(_old_schema())
        conn.execute(seed_sql(effective))
        conn.execute(seed_age14_sql(effective))
        for _ in range(2):  # 이전 스키마에 이미 있던 사용자 행
            uid = str(uuid.uuid4())
            conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
            _CREATED.append(uid)
            conn.execute("INSERT INTO account.app_users (user_id) VALUES (%s)", (uid,))
            old_users.append(uid)
        has = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'account' "
                           "AND table_name = 'app_users' AND column_name IN ('default_profile_id', 'default_guest')").fetchone()[0]
        assert has == 0  # 이전 스키마가 맞게 흉내 났는지
        for _ in range(2):  # 마이그레이션 SQL 재실행 안전
            conn.execute(migrate_default_target_sql())
    try:
        yield LOCAL_PG_DSN, old_users
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            if _CREATED:
                conn.execute("DELETE FROM auth.users WHERE id = ANY(%s::uuid[])", (_CREATED,))
        _CREATED.clear()


def _onboard(repo: PostgresAccountRepo, uid: str) -> None:
    asyncio.run(repo.ensure_user(uid))
    items = [ConsentInput("terms", 1, "agree"), ConsentInput("privacy_consent", 1, "agree"), ConsentInput("age_14", 1, "agree")]
    asyncio.run(repo.add_consents(uid, items, "onboarding"))


def test_existing_rows_are_unset_and_rerun_is_safe(migrated):
    dsn, old_users = migrated
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT default_profile_id, default_guest FROM account.app_users WHERE user_id = ANY(%s::uuid[])",
                            (old_users,)).fetchall()
        cols = {r[0]: r[1:] for r in conn.execute(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = 'account' "
            "AND table_name = 'app_users' AND column_name IN ('default_profile_id', 'default_guest')")}
        names = [r[0] for r in conn.execute("SELECT conname FROM pg_constraint WHERE conname IN "
                                            "('app_users_default_profile_fk', 'app_users_default_target_check')")]
    assert rows == [(None, False), (None, False)]  # 기존 사용자: 미설정 → 클라이언트가 본인 선택
    assert cols["default_profile_id"][:2] == ("uuid", "YES")
    assert cols["default_guest"][:2] == ("boolean", "NO") and "false" in cols["default_guest"][2]
    assert sorted(names) == ["app_users_default_profile_fk", "app_users_default_target_check"]  # 두 번 돌려도 제약은 하나씩


def test_new_schema_is_also_rerun_safe_over_migrated_db(migrated):
    dsn, _ = migrated
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())  # 신규 설치용 파일을 이미 적용된 DB에 다시
        n = conn.execute("SELECT count(*) FROM pg_constraint WHERE conname IN "
                         "('app_users_default_profile_fk', 'app_users_default_target_check')").fetchone()[0]
    assert n == 2


def test_db_check_and_fk(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    uid = _new_user(dsn)
    _onboard(repo, uid)
    prof = asyncio.run(repo.create_profile(uid, ProfileInput("self")))
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as conn:  # guest면 프로필은 null이어야 한다
        conn.execute("UPDATE account.app_users SET default_guest = true, default_profile_id = %s WHERE user_id = %s", (prof.profile_id, uid))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), psycopg.connect(dsn) as conn:  # 없는 프로필
        conn.execute("UPDATE account.app_users SET default_profile_id = %s WHERE user_id = %s", (MISSING_PROFILE, uid))
    with pytest.raises(psycopg.errors.NotNullViolation), psycopg.connect(dsn) as conn:
        conn.execute("UPDATE account.app_users SET default_guest = NULL WHERE user_id = %s", (uid,))


def test_repo_roundtrip_unset_guest_profile_and_back(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    uid = _new_user(dsn)
    user = asyncio.run(repo.ensure_user(uid))
    assert (user.default_profile_id, user.default_guest, user.default_target) == (None, False, None)  # 새 계정 기본은 미설정
    _onboard(repo, uid)  # 건강 동의 없음: 프로필 선택 상태는 건강 정보가 아니다
    me = asyncio.run(repo.create_profile(uid, ProfileInput("self")))
    kid = asyncio.run(repo.create_profile(uid, ProfileInput("child")))
    assert asyncio.run(repo.set_default_target(uid, "guest")).default_target == "guest"
    assert asyncio.run(repo.get_user(uid)).default_target == "guest"
    got = asyncio.run(repo.set_default_target(uid, kid.profile_id))
    assert (got.default_target, got.default_guest) == (kid.profile_id, False)  # guest → 프로필: guest는 꺼진다
    assert asyncio.run(repo.set_default_target(uid, me.profile_id)).default_target == me.profile_id
    assert asyncio.run(repo.set_default_target(uid, "guest")).default_profile_id is None  # 프로필 → guest: 프로필은 비워진다
    assert asyncio.run(repo.set_default_target(uid, None)).default_target is None
    assert asyncio.run(repo.set_default_target(uid, kid.profile_id)).default_target == kid.profile_id
    # 온보딩 단계 갱신 경로(set_onboarding RETURNING)도 기본 대상을 되돌려 준다
    assert asyncio.run(repo.set_onboarding(uid, "family", None)).default_target == kid.profile_id


def test_other_users_or_missing_profile_is_not_found_and_unchanged(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    a, b = _new_user(dsn), _new_user(dsn)
    _onboard(repo, a)
    _onboard(repo, b)
    a_prof = asyncio.run(repo.create_profile(a, ProfileInput("self")))
    b_prof = asyncio.run(repo.create_profile(b, ProfileInput("self")))
    asyncio.run(repo.set_default_target(a, a_prof.profile_id))
    for bad in (b_prof.profile_id, MISSING_PROFILE):
        with pytest.raises(AccountRepoError) as exc:
            asyncio.run(repo.set_default_target(a, bad))
        assert exc.value.code == "NOT_FOUND"
    assert asyncio.run(repo.get_user(a)).default_target == a_prof.profile_id
    assert asyncio.run(repo.get_user(b)).default_target is None


def test_profile_delete_resets_to_unset_and_account_delete_still_works(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    uid = _new_user(dsn)
    _onboard(repo, uid)
    asyncio.run(repo.create_profile(uid, ProfileInput("self")))
    kid = asyncio.run(repo.create_profile(uid, ProfileInput("child")))
    asyncio.run(repo.set_default_target(uid, kid.profile_id))
    assert asyncio.run(repo.delete_profile(uid, kid.profile_id)) is True
    after = asyncio.run(repo.get_user(uid))
    assert (after.default_profile_id, after.default_guest, after.default_target) == (None, False, None)  # FK ON DELETE SET NULL
    kid2 = asyncio.run(repo.create_profile(uid, ProfileInput("child")))
    asyncio.run(repo.set_default_target(uid, kid2.profile_id))
    summary = asyncio.run(repo.delete_account(uid))  # app_users ↔ profiles 순환 참조에도 탈퇴(전부 파기)가 된다
    assert summary.profiles == 2
    assert asyncio.run(repo.get_user(uid)) is None


def test_rls_other_user_cannot_read_or_change_default_target(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    a, b = _new_user(dsn), _new_user(dsn)
    _onboard(repo, a)
    _onboard(repo, b)
    prof = asyncio.run(repo.create_profile(a, ProfileInput("self")))
    asyncio.run(repo.set_default_target(a, prof.profile_id))
    assert _as_user(dsn, b, "SELECT default_profile_id::text FROM account.app_users WHERE user_id = %s", (a,)) == []
    assert _as_user(dsn, b, "UPDATE account.app_users SET default_guest = true, default_profile_id = NULL WHERE user_id = %s", (a,)) == 0
    assert _as_user(dsn, b, "UPDATE account.app_users SET default_guest = true WHERE user_id = %s", (b,)) == 1  # 본인 행은 고친다
    assert asyncio.run(repo.get_user(a)).default_target == prof.profile_id  # 타 사용자 값은 그대로
    assert asyncio.run(repo.get_user(b)).default_target == "guest"
    # 열 단위 권한: 새 두 칸 말고 다른 칸(가입 경로 등)은 여전히 못 고친다
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_user(dsn, a, "UPDATE account.app_users SET created_at = now() WHERE user_id = %s", (a,))
