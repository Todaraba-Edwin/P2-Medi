"""프로필 병아리 배경색 `avatar_color` 로컬 Postgres 시험(2026-11-23). 원격 DB·네트워크·LLM 호출 0.

환경변수 `LOCAL_PG_DSN`이 없거나 로컬 주소가 아니면 skip한다(`.env`는 읽지 않음, test_be11_sex_age14_pg.py와 같은 규칙).

① 열이 없는 이전 스키마의 기존 프로필 행이 마이그레이션 SQL로 기본 `yellow`가 되고, 두 번 돌려도 안전하다(재실행 안전)
② CHECK: 8색 밖 값·NULL은 DB가 거부한다
③ 저장소 왕복(기본값·8색·색만 수정)과 RLS 격리(타 사용자는 색을 읽거나 바꿀 수 없다)
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.db.account_repo import AVATAR_COLORS, ConsentInput, ProfileInput, ProfilePatch
from app.db.account_repo_pg import PostgresAccountRepo, migrate_avatar_color_sql, schema_sql, seed_age14_sql, seed_sql

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


def _old_schema() -> str:
    """avatar_color 이전 스키마를 흉내 낸다(열·CHECK 블록 제거)."""
    sql, n = re.subn(r"ALTER TABLE account\.profiles ADD COLUMN IF NOT EXISTS avatar_color.*?END \$\$;\n", "", schema_sql(), flags=re.S)
    assert n == 1 and "avatar_color" not in re.sub(r"--[^\n]*", "", sql)
    return sql


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    _CREATED.append(uid)
    return uid


def _as_user(dsn: str, uid: str, sql: str, params: tuple = ()):
    import json

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": uid}),))
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


@pytest.fixture(scope="module")
def migrated() -> Iterator[tuple[str, list[str]]]:
    """(dsn, 이전 스키마 때 만든 프로필 id 두 개). 마이그레이션 SQL을 두 번 적용한 상태."""
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    effective = datetime.now(UTC) - timedelta(minutes=1)
    old_ids: list[str] = []
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(_old_schema())
        conn.execute(seed_sql(effective))
        conn.execute(seed_age14_sql(effective))
        for relation in ("self", "child"):  # 이전 스키마에 이미 있던 행
            uid = str(uuid.uuid4())
            conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
            _CREATED.append(uid)
            conn.execute("INSERT INTO account.app_users (user_id) VALUES (%s)", (uid,))
            row = conn.execute("INSERT INTO account.profiles (user_id, relation, sort_order) VALUES (%s, %s, %s) "
                               "RETURNING profile_id::text", (uid, relation, 0 if relation == "self" else 1)).fetchone()
            old_ids.append(row[0])
        has = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'account' "
                           "AND table_name = 'profiles' AND column_name = 'avatar_color'").fetchone()[0]
        assert has == 0  # 이전 스키마가 맞게 흉내 났는지
        for _ in range(2):  # 마이그레이션 SQL 재실행 안전
            conn.execute(migrate_avatar_color_sql())
    try:
        yield LOCAL_PG_DSN, old_ids
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


def test_existing_rows_become_yellow_and_rerun_is_safe(migrated):
    dsn, old_ids = migrated
    with psycopg.connect(dsn) as conn:
        colors = [r[0] for r in conn.execute("SELECT avatar_color FROM account.profiles WHERE profile_id = ANY(%s::uuid[])", (old_ids,))]
        col = conn.execute("SELECT data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = 'account' "
                           "AND table_name = 'profiles' AND column_name = 'avatar_color'").fetchone()
        n_checks = conn.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'profiles_avatar_color_check'").fetchone()[0]
    assert colors == ["yellow", "yellow"]
    assert col[0] == "text" and col[1] == "NO" and "yellow" in col[2]
    assert n_checks == 1  # 두 번 돌려도 제약은 하나


def test_new_schema_is_also_rerun_safe_over_migrated_db(migrated):
    dsn, _ = migrated
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())  # 신규 설치용 파일을 이미 적용된 DB에 다시
        n = conn.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'profiles_avatar_color_check'").fetchone()[0]
    assert n == 1


@pytest.mark.parametrize("bad", ["red", "Yellow", "", "#ffcc00"])
def test_db_check_rejects_outside_values_and_null(migrated, bad):
    dsn, old_ids = migrated
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as conn:
        conn.execute("UPDATE account.profiles SET avatar_color = %s WHERE profile_id = %s", (bad, old_ids[0]))
    with pytest.raises(psycopg.errors.NotNullViolation), psycopg.connect(dsn) as conn:
        conn.execute("UPDATE account.profiles SET avatar_color = NULL WHERE profile_id = %s", (old_ids[0],))


def test_repo_roundtrip_default_eight_colors_and_color_only_patch(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    uid = _new_user(dsn)
    _onboard(repo, uid)  # 건강 동의 없음: 색은 건강 정보가 아니다
    me = asyncio.run(repo.create_profile(uid, ProfileInput("self")))
    assert me.avatar_color == "yellow"
    for color in AVATAR_COLORS:
        assert asyncio.run(repo.update_profile(uid, me.profile_id, ProfilePatch(avatar_color=color))).avatar_color == color
    assert asyncio.run(repo.update_profile(uid, me.profile_id, ProfilePatch(label="나"))).avatar_color == "gray"  # 보내지 않으면 그대로
    kid = asyncio.run(repo.create_profile(uid, ProfileInput("child", avatar_color="teal")))
    assert [p.avatar_color for p in asyncio.run(repo.list_profiles(uid))] == ["gray", "teal"] and kid.avatar_color == "teal"


def test_rls_other_user_cannot_read_or_change_color(migrated):
    dsn, _ = migrated
    repo = PostgresAccountRepo.from_dsn(dsn)
    a, b = _new_user(dsn), _new_user(dsn)
    _onboard(repo, a)
    _onboard(repo, b)
    prof = asyncio.run(repo.create_profile(a, ProfileInput("self", avatar_color="blue")))
    assert _as_user(dsn, b, "SELECT avatar_color FROM account.profiles WHERE profile_id = %s", (prof.profile_id,)) == []
    assert _as_user(dsn, b, "UPDATE account.profiles SET avatar_color = 'pink' WHERE profile_id = %s", (prof.profile_id,)) == 0
    assert asyncio.run(repo.list_profiles(a))[0].avatar_color == "blue"
    assert _as_user(dsn, a, "SELECT avatar_color FROM account.profiles WHERE profile_id = %s", (prof.profile_id,)) == [("blue",)]
