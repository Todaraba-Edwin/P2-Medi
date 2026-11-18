"""BE-11 계정 스키마 SQL·Postgres 저장소 시험(2026-11-18). 원격 DB·네트워크 호출 0.

1. 정적 검사(항상): `schema_account.sql`·`seed_legal_v1.sql`이 결정(06·07·08·09·12·22 A)과 맞는지 문자열로 본다.
2. 가짜 연결(항상): `PostgresAccountRepo`가 트랜잭션마다 `SET LOCAL ROLE`·`request.jwt.claims`를 먼저 실행하는지, 오류를 어떻게 옮기는지.
3. 로컬 Postgres RLS 시험(설계 13장 T1~T3, BE-11-14 A): **로컬 DSN이 없으면 skip**한다. DSN을 읽을 환경변수 이름은 아직 정하지 않았다
   (보고서 결정 후보). 정해지면 `LOCAL_PG_DSN`을 그 값으로 읽게 한 줄만 바꾼다. 로컬 주소(localhost·127.0.0.1·소켓)가 아니면 돌지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
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
)
from app.db.account_repo_pg import PostgresAccountRepo, schema_sql, seed_sql

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
    assert "anonymized_at" not in NO_COMMENTS and "SET NULL" not in NO_COMMENTS
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
    conn = FakeConn(rows=[(UID, "consent", None)])
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


def test_foreign_key_violation_means_no_account():
    conn = FakeConn(raise_on="INSERT INTO account.user_consents", exc=psycopg.errors.ForeignKeyViolation("fk"))
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(PostgresAccountRepo(lambda: conn).add_consents(UID, [ConsentInput("terms", 1, "agree")], "onboarding"))
    assert info.value.code == "NO_ACCOUNT"


def test_repr_hides_dsn():
    repo = PostgresAccountRepo.from_dsn("postgresql://u:pw-secret@db.example.test:5432/postgres")  # guard: fake
    assert "pw-secret" not in repr(repo) and "example" not in repr(repo)


# --------------------------------------------------------------------------- 3. 로컬 Postgres RLS(DSN 없으면 skip)
LOCAL_PG_DSN: str | None = None  # 환경변수 이름 미정(결정 후보). 이름을 정하면 os.environ.get(<이름>)으로 바꾼다
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


@pytest.fixture(scope="module")
def pg_dsn() -> str:
    if not LOCAL_PG_DSN:
        pytest.skip("로컬 Postgres DSN 없음(환경변수 이름 미정, BE-11-14 A 로컬 시험)")
    info = psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN)
    host = str(info.get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(schema_sql())
        conn.execute(seed_sql(datetime.now(UTC) - timedelta(minutes=1)))
    return LOCAL_PG_DSN


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    return uid


def _as_user(dsn: str, uid: str, sql: str, params: Any = ()) -> Any:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": uid}),))
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


def _onboard(repo: PostgresAccountRepo, uid: str, *, health: bool = False) -> None:
    asyncio.run(repo.ensure_user(uid))
    items = [ConsentInput("terms", 1, "agree"), ConsentInput("privacy_consent", 1, "agree")]
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
    summary = asyncio.run(repo.delete_account(a))
    assert (summary.profiles, summary.consents) == (0, 4)
    assert asyncio.run(repo.get_user(a)) is None
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM account.user_consents WHERE user_id = %s", (a,)).fetchone()[0] == 0
        row = conn.execute("SELECT accounts, consents FROM account.deletion_log WHERE deleted_on = (now() AT TIME ZONE 'UTC')::date"
                           ).fetchone()
        assert row is not None and row[0] >= 1 and row[1] >= 4
