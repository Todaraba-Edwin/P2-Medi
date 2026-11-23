"""BE-11 계정 스키마 SQL·Postgres 저장소 시험(2026-11-18). 원격 DB·네트워크 호출 0.

1. 정적 검사(항상): `schema_account.sql`·`seed_legal_v1.sql`이 결정(06·07·08·09·12·22 A)과 맞는지 문자열로 본다.
2. 가짜 연결(항상): `PostgresAccountRepo`가 트랜잭션마다 `SET LOCAL ROLE`·`request.jwt.claims`를 먼저 실행하는지, 오류를 어떻게 옮기는지.
3. 로컬 Postgres RLS 시험(설계 13장 T1~T3, BE-11-14 A): 환경변수 `LOCAL_PG_DSN`이 **없으면 skip**한다(`.env`는 읽지 않음).
   로컬 주소(localhost·127.0.0.1·소켓)가 아니면 돌지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from app.db import account_repo_pg as pg
from app.db.account_repo import (
    AGE_BANDS,
    AccountRepoError,
    ConsentInput,
    MedicationInput,
    ProfileInput,
    RepoUnavailable,
    body_sha256,
)
from app.db.account_repo_pg import PostgresAccountRepo, schema_sql, seed_age14_sql, seed_sql

SCHEMA = schema_sql()
NO_COMMENTS = "\n".join(line.split("--", 1)[0] for line in SCHEMA.splitlines())


# --------------------------------------------------------------------------- 1. 정적 검사
def _create_table(name: str) -> str:
    m = re.search(rf"CREATE TABLE IF NOT EXISTS account\.{name} \((.*?)\n\);", NO_COMMENTS, re.S)
    assert m, name
    return m.group(1)


def test_schema_tables_all_in_account_schema_with_rls():
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\S+) \(", NO_COMMENTS)
    assert tables == ["account.app_users", "account.profiles", "account.profile_medications", "account.legal_documents",
                      "account.user_consents", "account.deletion_log"]
    for t in tables:
        assert f"ALTER TABLE {t}" in NO_COMMENTS and re.search(rf"ALTER TABLE {re.escape(t)}\s+ENABLE ROW LEVEL SECURITY", NO_COMMENTS)
    for forbidden in ("DROP TABLE", "TRUNCATE", "DROP SCHEMA", "public.", "TABLE IF NOT EXISTS auth.", "CREATE TABLE auth.", "ALTER TABLE auth."):
        assert forbidden not in NO_COMMENTS


def test_schema_enums_match_decisions():
    assert "'m0_2', 'm3_5', 'm6_11', 'y1', 'y2', 'y3_5', 'y6_11', 'y12_14', 'y15_18', 'y19_64', 'y65_plus'" in SCHEMA  # 07 A
    assert len(AGE_BANDS) == 11
    assert "('self', 'child', 'parent', 'spouse', 'other')" in SCHEMA  # 08 A
    assert "week" not in _create_table("profiles")  # 09 A: 임신 주차 열 없음


def test_consents_cascade_on_account_delete_and_deletion_log_has_no_identifier():
    consents = _create_table("user_consents")
    assert "REFERENCES account.app_users (user_id) ON DELETE CASCADE" in consents  # 22 A: 즉시 파기
    assert "anonymized_at" not in NO_COMMENTS
    # SET NULL은 기본 프로필 FK(프로필 삭제 → 미설정, 2026-11-23 FE-17 U-08) 하나뿐이다. 익명화 용도의 SET NULL은 없다
    assert NO_COMMENTS.count("SET NULL") == 1 and "FOREIGN KEY (default_profile_id) REFERENCES account.profiles (profile_id) ON DELETE SET NULL" in NO_COMMENTS
    log = _create_table("deletion_log")
    cols = [line.split()[0] for line in log.strip().splitlines()]
    assert cols == ["deleted_on", "accounts", "profiles", "medications", "consents"]
    assert "uuid" not in log and "timestamptz" not in log  # 식별자·시각 없음, 일자만
    assert "REVOKE ALL ON account.deletion_log FROM authenticated" in NO_COMMENTS
    assert "REVOKE ALL ON account.deletion_log FROM anon" in NO_COMMENTS


def test_security_definer_functions_pin_search_path_and_limit_execute():
    for fn in ("log_account_deletion", "delete_my_account"):
        m = re.search(rf"FUNCTION account\.{fn}\(\).*?AS \$\$", NO_COMMENTS, re.S)
        assert m and "SECURITY DEFINER SET search_path = ''" in m.group(0)
        assert f"REVOKE ALL ON FUNCTION account.{fn}() FROM PUBLIC" in NO_COMMENTS
    assert "GRANT EXECUTE ON FUNCTION account.delete_my_account() TO authenticated" in NO_COMMENTS
    assert "REVOKE DELETE ON account.app_users FROM authenticated" in NO_COMMENTS
    assert "REVOKE UPDATE, DELETE ON account.user_consents FROM authenticated" in NO_COMMENTS


def test_triggers_cover_limits_health_and_withdraw():
    for code in ("PROFILE_LIMIT", "MEDICATION_LIMIT", "CONSENT_REQUIRED:sensitive_consent", "USE_ACCOUNT_DELETE", "DOCUMENT_FROZEN"):
        assert f"'{code}'" in NO_COMMENTS
        assert code in pg._RULE_CODES
    assert "relation <> 'self'" in NO_COMMENTS and ">= 3" in NO_COMMENTS and ">= 4" in NO_COMMENTS  # 본인 1 + 가족 3
    assert "BEFORE INSERT OR UPDATE OF relation ON account.profiles" in NO_COMMENTS
    withdraw = re.search(r"FUNCTION account\.on_consent_withdraw\(\).*?\$\$;", NO_COMMENTS, re.S)
    assert withdraw and "DELETE FROM account.profiles WHERE user_id = NEW.user_id" in withdraw.group(0)  # 12 A
    assert "app_users" not in withdraw.group(0)  # 철회로 계정을 지우지 않는다


def test_schema_sex_column_and_age_14_doc_type():
    """GROUP-03 B1: 성별 enum(female·male, '기타' 없음)·이미 적용된 DB에도 더하는 ALTER 두 줄·age_14 철회 금지."""
    assert "CREATE TYPE account.sex AS ENUM ('female', 'male');" in NO_COMMENTS
    assert "'sensitive_consent', 'age_14', 'terms_guest');" in NO_COMMENTS  # 새 DB
    assert "ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'age_14';" in NO_COMMENTS  # 이미 적용된 DB
    assert "ALTER TABLE account.profiles ADD COLUMN IF NOT EXISTS sex account.sex;" in NO_COMMENTS
    health = re.search(r"FUNCTION account\.enforce_health_consent_profile\(\).*?\$\$;", NO_COMMENTS, re.S)
    assert health and "sex" not in health.group(0)  # 성별은 건강 동의 검사 대상이 아니다(PRD-17-13 A)
    withdraw = re.search(r"FUNCTION account\.on_consent_withdraw\(\).*?\$\$;", NO_COMMENTS, re.S)
    assert withdraw and "IN ('terms', 'age_14')" in withdraw.group(0)


def test_age_14_seed_uses_approved_sentence_and_needs_timezone():
    sql = seed_age14_sql(datetime(2026, 12, 1, tzinfo=UTC))
    assert "{{EFFECTIVE_AT}}" not in sql and "'2026-12-01T00:00:00+00:00'" in sql
    assert "('age_14', 1, '만 14세 이상입니다.', $md$만 14세 이상입니다.$md$, true, false, 'published'," in sql  # PRD-17-09 A 승인 문구
    assert "ON CONFLICT (doc_type, version) DO NOTHING" in sql
    pg.assert_publishable(sql)  # 자리표시가 없어 원격 게시를 막지 않는다
    with pytest.raises(ValueError):
        seed_age14_sql(datetime(2026, 12, 1))  # noqa: DTZ001 - 시간대 없는 값 거부 확인


def test_profile_sex_column_in_select_insert_update():
    conn = FakeConn(rows=[("p1",), [("p1", "self", None, None, None, 0, "male", "yellow")], []])
    prof = asyncio.run(PostgresAccountRepo(lambda: conn).create_profile(UID, ProfileInput("self", sex="male")))
    assert prof.sex == "male"
    insert = next((s, a) for s, a in conn.log if s.startswith("INSERT INTO account.profiles"))
    assert "sort_order, sex, avatar_color)" in insert[0] and insert[1][-2:] == ("male", "yellow")
    assert any("sort_order, sex::text, avatar_color FROM account.profiles" in s for s, _ in conn.log)


def test_seed_is_marked_draft_and_needs_timezone():
    sql = seed_sql(datetime(2026, 12, 1, tzinfo=UTC))
    assert "{{EFFECTIVE_AT}}" not in sql and "'2026-12-01T00:00:00+00:00'" in sql
    body = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))  # 머리 주석 제외
    assert body.count("> 초안·법률 검토 전") == 4 and body.count("(초안)") + body.count(", 초안)") == 4
    assert "ON CONFLICT (doc_type, version) DO NOTHING" in sql
    assert "동의 기록도 즉시 지우며" in sql and "확정 전입니다" not in sql.split("## 4. 보관과 파기")[1].split("##")[0]
    with pytest.raises(ValueError):
        seed_sql(datetime(2026, 12, 1))  # noqa: DTZ001 - 시간대 없는 값 거부 확인


# --------------------------------------------------------------------------- 2. 가짜 연결
class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.rowcount = 0

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.log.append((sql, params))
        if self.conn.raise_on and self.conn.raise_on in sql:
            raise self.conn.exc
        self.rowcount = 1

    def fetchone(self) -> Any:
        return self.conn.rows.pop(0) if self.conn.rows else None

    def fetchall(self) -> list[Any]:
        return self.conn.rows.pop(0) if self.conn.rows else []


class FakeConn:
    def __init__(self, rows: list[Any] | None = None, raise_on: str | None = None, exc: Exception | None = None) -> None:
        self.log: list[tuple[str, Any]] = []
        self.rows = rows or []
        self.raise_on = raise_on
        self.exc = exc
        self.closed = False
        self.exited_with: Any = "never"

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, exc_type: Any, *a: Any) -> None:
        self.exited_with = exc_type

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


UID = "33333333-3333-4333-8333-333333333333"


def test_user_calls_set_role_and_claims_first_in_same_transaction():
    conn = FakeConn(rows=[(UID, "consent", None, None, False)])
    repo = PostgresAccountRepo(lambda: conn)
    user = asyncio.run(repo.get_user(UID))
    assert user is not None and user.user_id == UID
    sqls = [s for s, _ in conn.log]
    assert sqls[0] == "SET LOCAL ROLE authenticated"
    assert sqls[1].startswith("SELECT set_config('request.jwt.claims', %s, true)")
    assert json.loads(conn.log[1][1][0]) == {"sub": UID, "role": "authenticated", "aud": "authenticated"}
    assert all("WHERE user_id = %s" in s for s in sqls[2:])  # RLS에 더해 질의도 본인 행만
    assert conn.closed and conn.exited_with is None


def test_legal_runs_as_anon_without_claims():
    conn = FakeConn()
    assert asyncio.run(PostgresAccountRepo(lambda: conn).legal_current("terms")) is None
    sqls = [s for s, _ in conn.log]
    assert sqls[0] == "SET LOCAL ROLE anon" and not any("request.jwt.claims" in s for s in sqls)


def test_delete_account_uses_definer_function():
    conn = FakeConn(rows=[(2, 1, 3)])
    summary = asyncio.run(PostgresAccountRepo(lambda: conn).delete_account(UID))
    assert (summary.profiles, summary.medications, summary.consents) == (2, 1, 3)
    assert any("account.delete_my_account()" in s for s, _ in conn.log)
    assert not any(s.lstrip().upper().startswith("DELETE FROM ACCOUNT.APP_USERS") for s, _ in conn.log)


def test_connection_and_driver_errors_become_repo_unavailable_without_details():
    def refuse() -> Any:
        raise psycopg.OperationalError("connection to server at secret-host failed: password=hunter2")

    with pytest.raises(RepoUnavailable) as info:
        asyncio.run(PostgresAccountRepo(refuse).get_user(UID))
    assert str(info.value) == "OperationalError" and info.value.__cause__ is None
    conn = FakeConn(raise_on="FROM account.app_users", exc=psycopg.errors.UndefinedTable("relation account.app_users does not exist"))
    with pytest.raises(RepoUnavailable) as info:
        asyncio.run(PostgresAccountRepo(lambda: conn).get_user(UID))
    assert str(info.value) == "UndefinedTable" and conn.closed and conn.exited_with is not None  # 예외 → 롤백


def test_connect_timeout_is_15s_and_repo_unavailable_carries_cause_and_elapsed(monkeypatch):
    from app.db import account_repo_pg as mod

    assert mod.CONNECT_TIMEOUT_S == 15  # 풀러 첫 연결 7초 측정(2026-11-22)
    seen: dict[str, Any] = {}

    def fake_connect(dsn: str, **kw: Any) -> Any:
        seen.update(kw)
        raise psycopg.OperationalError("secret-host password=hunter2") from TimeoutError("secret-host timed out")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    repo = PostgresAccountRepo.from_dsn("postgresql://u:hunter2@secret-host/db")
    with pytest.raises(RepoUnavailable) as info:
        asyncio.run(repo.get_user(UID))
    assert seen == {"connect_timeout": 15}
    exc = info.value
    assert str(exc) == "OperationalError" and exc.cause == "TimeoutError" and exc.elapsed_s is not None
    d = exc.diagnostics()
    assert d.startswith("원인=TimeoutError ") and d.endswith("s")
    assert "hunter2" not in d and "secret-host" not in d and exc.__cause__ is None


def test_foreign_key_violation_means_no_account():
    conn = FakeConn(raise_on="INSERT INTO account.user_consents", exc=psycopg.errors.ForeignKeyViolation("fk"))
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(PostgresAccountRepo(lambda: conn).add_consents(UID, [ConsentInput("terms", 1, "agree")], "onboarding"))
    assert info.value.code == "NO_ACCOUNT"


def test_repr_hides_dsn():
    repo = PostgresAccountRepo.from_dsn("postgresql://u:pw-secret@db.example.test:5432/postgres")  # guard: fake
    assert "pw-secret" not in repr(repo) and "example" not in repr(repo)


# --------------------------------------------------------------------------- 3. 로컬 Postgres RLS(DSN 없으면 skip)
# BE-11-14 A(Recap 40): 변수 이름 LOCAL_PG_DSN. 환경변수에서만 읽는다(.env·SUPABASE_DB_URL 폴백 없음 — 원격 DB를 타지 않게)
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


_CREATED_AUTH_USERS: list[str] = []  # 시험이 auth.users 스텁에 넣은 행. 끝나면 이것만 지운다


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 RLS 시험)")
    info = psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN)
    host = str(info.get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    effective = datetime.now(UTC) - timedelta(minutes=1)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만(앞선 실행이 중단돼 남은 것 정리)
        conn.execute(AUTH_STUB)
        for _ in range(2):  # 스키마·시드가 멱등인지(두 번 적용해도 오류 없음)도 함께 본다
            conn.execute(schema_sql())
            conn.execute(seed_sql(effective))
            conn.execute(seed_age14_sql(effective))  # 스키마(ALTER TYPE … ADD VALUE) 커밋 뒤 별도 문장(autocommit)
    try:
        yield LOCAL_PG_DSN
    finally:  # 같은 DB에서 다시 돌려도 통과하도록 시험이 만든 것을 지운다(역할·auth 스텁 구조는 남겨도 멱등)
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            if _CREATED_AUTH_USERS:
                conn.execute("DELETE FROM auth.users WHERE id = ANY(%s::uuid[])", (_CREATED_AUTH_USERS,))
        _CREATED_AUTH_USERS.clear()


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    _CREATED_AUTH_USERS.append(uid)
    return uid


def _as_user(dsn: str, uid: str, sql: str, params: Any = ()) -> Any:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": uid}),))
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


def _onboard(repo: PostgresAccountRepo, uid: str, *, health: bool = False) -> None:
    asyncio.run(repo.ensure_user(uid))
    items = [ConsentInput("terms", 1, "agree"), ConsentInput("privacy_consent", 1, "agree"), ConsentInput("age_14", 1, "agree")]
    if health:
        items.append(ConsentInput("sensitive_consent", 1, "agree"))
    asyncio.run(repo.add_consents(uid, items, "onboarding"))


def test_pg_rls_isolates_accounts(pg_dsn):
    repo = PostgresAccountRepo.from_dsn(pg_dsn)
    a, b = _new_user(pg_dsn), _new_user(pg_dsn)
    _onboard(repo, a, health=True)
    _onboard(repo, b)
    prof = asyncio.run(repo.create_profile(a, ProfileInput("self", medications=(MedicationInput("타이레놀"),))))
    assert asyncio.run(repo.list_profiles(b)) == []
    assert _as_user(pg_dsn, b, "SELECT * FROM account.profiles WHERE profile_id = %s", (prof.profile_id,)) == []
    assert _as_user(pg_dsn, b, "SELECT * FROM account.profile_medications") == []
    assert _as_user(pg_dsn, b, "SELECT * FROM account.user_consents WHERE user_id = %s", (a,)) == []
    assert _as_user(pg_dsn, b, "UPDATE account.profiles SET label = 'x' WHERE profile_id = %s", (prof.profile_id,)) == 0
    assert _as_user(pg_dsn, b, "DELETE FROM account.profiles WHERE profile_id = %s", (prof.profile_id,)) == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_user(pg_dsn, b, "INSERT INTO account.profiles (user_id, relation) VALUES (%s, 'child')", (a,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_user(pg_dsn, a, "UPDATE account.user_consents SET action = 'agree'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_user(pg_dsn, a, "SELECT * FROM account.deletion_log")


def test_pg_limits_health_withdraw_and_delete(pg_dsn):
    repo = PostgresAccountRepo.from_dsn(pg_dsn)
    a = _new_user(pg_dsn)
    _onboard(repo, a)
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.create_profile(a, ProfileInput("self", pregnancy_status="pregnant")))
    assert info.value.code == "CONSENT_REQUIRED:sensitive_consent"
    asyncio.run(repo.create_profile(a, ProfileInput("self")))
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.create_profile(a, ProfileInput("self")))
    assert info.value.code == "SELF_EXISTS"
    for _ in range(3):
        asyncio.run(repo.create_profile(a, ProfileInput("child")))
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.create_profile(a, ProfileInput("parent")))
    assert info.value.code == "PROFILE_LIMIT"
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.add_consents(a, [ConsentInput("terms", 1, "withdraw")], "settings"))
    assert info.value.code == "USE_ACCOUNT_DELETE"
    asyncio.run(repo.add_consents(a, [ConsentInput("privacy_consent", 1, "withdraw")], "settings"))
    assert asyncio.run(repo.list_profiles(a)) == [] and asyncio.run(repo.get_user(a)) is not None  # 12 A
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.add_consents(a, [ConsentInput("age_14", 1, "withdraw")], "settings"))
    assert info.value.code == "USE_ACCOUNT_DELETE"  # PRD-17-12 A: 만 14세 확인도 철회 대신 탈퇴
    # 동의 기록 = 온보딩 agree 3 + privacy_consent withdraw 1. 거부된 terms 철회는 트랜잭션째 롤백되어 남지 않는다
    # (메모리 저장소도 기록 전에 거부, account_repo.py add_consents)
    with psycopg.connect(pg_dsn) as conn:
        rows = conn.execute("SELECT doc_type::text, action::text FROM account.user_consents WHERE user_id = %s ORDER BY consent_id",
                            (a,)).fetchall()
    assert rows == [("terms", "agree"), ("privacy_consent", "agree"), ("age_14", "agree"), ("privacy_consent", "withdraw")]
    summary = asyncio.run(repo.delete_account(a))
    assert (summary.profiles, summary.consents) == (0, 4)
    assert asyncio.run(repo.get_user(a)) is None
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM account.user_consents WHERE user_id = %s", (a,)).fetchone()[0] == 0
        row = conn.execute("SELECT accounts, consents FROM account.deletion_log WHERE deleted_on = (now() AT TIME ZONE 'UTC')::date"
                           ).fetchone()
        assert row is not None and row[0] >= 1 and row[1] >= 4


def test_pg_deleted_auth_user_cannot_recreate_account(pg_dsn):
    # BE-11-24 A: 탈퇴(앱 데이터 삭제 → auth.users 삭제) 뒤 남은 토큰으로 /me를 불러도 FK 때문에 빈 계정이 다시 생기지 않는다
    repo = PostgresAccountRepo.from_dsn(pg_dsn)
    a = _new_user(pg_dsn)
    _onboard(repo, a)
    asyncio.run(repo.delete_account(a))
    with psycopg.connect(pg_dsn, autocommit=True) as conn:  # Admin API 삭제 대신 auth.users 스텁 행을 지운다(로컬만)
        conn.execute("DELETE FROM auth.users WHERE id = %s", (a,))
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(repo.ensure_user(a))
    assert info.value.code == "NO_ACCOUNT"  # API에서는 401 AUTH_INVALID
    assert asyncio.run(repo.get_user(a)) is None


def test_pg_legal_body_sha256_matches_python(pg_dsn):
    # 생성 열 body_sha256(account.utf8_sha256_hex)이 API가 쓰는 Python 해시와 같다. anon으로 게시 문서를 읽는다
    repo = PostgresAccountRepo.from_dsn(pg_dsn)
    doc = asyncio.run(repo.legal_current("terms"))
    assert doc is not None and doc.version == 1
    assert doc.body_sha256 == body_sha256(doc.body_md) and len(doc.body_sha256) == 64


# --------------------------------------------------------------------------- 4. lifespan 저장소 연결(BE-11-23 A, 2026-11-22)
# 앱 lifespan이 `SUPABASE_DB_URL`로 저장소를 붙이는지 본다. 설정은 `main.load_settings`를 바꿔 생성자 인자로만 준다(`.env` 0).
# 가짜 DSN 시험은 `psycopg.connect`를 가짜로 바꿔 접속 0이다. 로컬 왕복은 `LOCAL_PG_DSN`(로컬 주소)이 있을 때만 돈다.
FAKE_REMOTE_DSN = "postgresql://u:pw-lifespan-secret@db.example.test:5432/postgres"  # guard: fake
LIFE_TOKEN = "eyJhbGciOiJFUzI1NiJ9.eyJsaWZlIjoiMSJ9.c2lnLWw"
_AUTH_HEADER = {"Authorization": f"Bearer {LIFE_TOKEN}"}


class _OneTokenVerifier:
    def __init__(self, uid: str) -> None:
        self.uid = uid

    async def verify(self, token: str) -> str:
        from app.security.auth import TokenInvalid

        if token == LIFE_TOKEN:
            return self.uid
        raise TokenInvalid("rejected")


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    for name in Settings.model_fields:  # 앞선 시험이 올린 실제 env(`load_dotenv`)가 설정에 섞이지 않게
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def main_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from app import main
    from app.api import account as account_api
    from app.security import auth, auth_admin

    _clear_settings_env(monkeypatch)
    try:
        yield main
    finally:  # 다른 시험에 새지 않게 뗀다
        account_api.set_repo(main.app, None, item_seq_checker=None)
        auth.set_verifier(main.app, None)
        auth_admin.set_auth_admin(main.app, None)


def _settings(**kw: Any) -> Any:
    from app.config import Settings

    return Settings(_env_file=None, **kw)


def _repo_of(main: Any) -> Any:
    from app.api import account as account_api

    return getattr(main.app.state, account_api.REPO_STATE_KEY, None)


def test_lifespan_without_dsn_keeps_account_api_501(main_app, monkeypatch):
    from fastapi.testclient import TestClient

    from app.security import auth

    monkeypatch.setattr(main_app, "load_settings", lambda: _settings())
    with TestClient(main_app.app) as c:
        assert _repo_of(main_app) is None
        auth.set_verifier(main_app.app, _OneTokenVerifier(str(uuid.uuid4())))
        r = c.get("/me", headers=_AUTH_HEADER)
        assert (r.status_code, r.json()) == (501, {"code": "NOT_IMPLEMENTED", "fields": []})


def test_lifespan_with_dsn_attaches_repo_without_connecting_and_detaches_on_shutdown(main_app, monkeypatch):
    from fastapi.testclient import TestClient

    calls: list[Any] = []

    def no_connect(*a: Any, **_k: Any) -> Any:
        calls.append(a)
        raise AssertionError("시작 때 접속하면 안 된다")

    monkeypatch.setattr(psycopg, "connect", no_connect)
    monkeypatch.setattr(main_app, "load_settings", lambda: _settings(supabase_db_url=FAKE_REMOTE_DSN))
    with TestClient(main_app.app):
        repo = _repo_of(main_app)
        assert isinstance(repo, PostgresAccountRepo)
        assert "pw-lifespan-secret" not in repr(repo)
        assert calls == []  # 시작 때 접속·쓰기 0
    assert _repo_of(main_app) is None  # 종료 때 뗀다


def test_lifespan_repo_connect_failure_is_503_not_startup_error(main_app, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from app.security import auth

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise psycopg.OperationalError(f"connection to {FAKE_REMOTE_DSN} refused")

    monkeypatch.setattr(psycopg, "connect", refuse)
    monkeypatch.setattr(main_app, "load_settings", lambda: _settings(supabase_db_url=FAKE_REMOTE_DSN))
    with TestClient(main_app.app) as c:  # 접속할 수 없어도 서버는 뜬다
        assert c.get("/health").status_code == 200
        auth.set_verifier(main_app.app, _OneTokenVerifier(str(uuid.uuid4())))
        r = c.get("/me", headers=_AUTH_HEADER)
        assert (r.status_code, r.json()) == (503, {"code": "ACCOUNT_UNAVAILABLE", "fields": []})
    assert "pw-lifespan-secret" not in caplog.text + r.text


def test_lifespan_malformed_dsn_is_501_and_value_not_logged(main_app, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    bad = "host=db.example.test password=pw-lifespan-secret port='"  # guard: fake, 따옴표가 닫히지 않은 conninfo
    monkeypatch.setattr(main_app, "load_settings", lambda: _settings(supabase_db_url=bad))
    with TestClient(main_app.app):
        assert _repo_of(main_app) is None
    assert "SUPABASE_DB_URL 형식 오류" in caplog.text and "pw-lifespan-secret" not in caplog.text


def test_lifespan_local_pg_first_me_returns_consent_step(pg_dsn, main_app, monkeypatch):
    # 로컬 왕복: lifespan이 붙인 저장소로 첫 /me가 계정 행을 만들고 `consent` 단계를 돌려준다(원격 0, LOCAL_PG_DSN만)
    from fastapi.testclient import TestClient

    from app.security import auth

    uid = _new_user(pg_dsn)
    monkeypatch.setattr(main_app, "load_settings", lambda: _settings(supabase_db_url=pg_dsn))
    with TestClient(main_app.app) as c:
        auth.set_verifier(main_app.app, _OneTokenVerifier(uid))
        r = c.get("/me", headers=_AUTH_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["user_id"], body["is_guest"], body["onboarding_step"]) == (uid, False, "consent")
        assert r.headers["Cache-Control"] == "no-store"
        assert c.get("/legal/terms").json()["version"] == 1  # anon 약관 조회도 같은 저장소
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM account.app_users WHERE user_id = %s", (uid,)).fetchone()[0] == 1
