"""BE-17 계정 DB 연결 풀 시험(2026-11-23). 원격 접속 0.

1. 가짜 풀(항상): 빌림·반납, 고갈(PoolTimeout)·닫힘 → RepoUnavailable(원인·비밀값 없음), 풀 설정 상수, 풀 연결 조건.
2. 실제 `psycopg_pool` + 로컬 Postgres(`LOCAL_PG_DSN`이 로컬 주소일 때만, 없으면 skip): 요청 A가 설정한 신원이 같은 연결을 빌린 요청 B에 보이지 않는다.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from typing import Any

import psycopg
import psycopg_pool
import pytest

from app import main
from app.db import account_repo_pg as mod
from app.db.account_repo import RepoUnavailable
from app.db.account_repo_pg import PostgresAccountRepo

UID = "44444444-4444-4444-8444-444444444444"


class Cur:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def __enter__(self) -> Cur:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.log.append(sql)

    def fetchone(self) -> Any:
        return (UID, "consent", None)


class Conn:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.closed = False

    def cursor(self) -> Cur:
        return Cur(self)

    def close(self) -> None:
        self.closed = True


class FakePool:
    def __init__(self, exc: Exception | None = None) -> None:
        self.conn = Conn()
        self.exc = exc
        self.borrowed = 0
        self.returned = 0
        self.closed = False

    @contextmanager
    def connection(self, *a: Any, **k: Any):
        if self.exc is not None:
            raise self.exc
        self.borrowed += 1
        try:
            yield self.conn
        finally:
            self.returned += 1

    def close(self) -> None:
        self.closed = True


def test_pool_borrows_and_returns_without_closing_connection():
    pool = FakePool()
    repo = PostgresAccountRepo.from_pool(pool)
    for _ in range(2):
        assert asyncio.run(repo.get_user(UID)).user_id == UID
    assert pool.borrowed == pool.returned == 2 and pool.conn.closed is False  # 닫지 않고 반납
    assert pool.conn.log[0] == "SET LOCAL ROLE authenticated" and "set_config('request.jwt.claims'" in pool.conn.log[1]
    assert not any(s.startswith(("SET ROLE", "SET SESSION")) for s in pool.conn.log)  # 세션 수준 설정 없음
    repo.close()
    assert pool.closed


def test_exception_inside_request_still_returns_connection():
    pool = FakePool()
    repo = PostgresAccountRepo.from_pool(pool)

    def boom(cur: Any) -> None:
        raise psycopg.OperationalError("secret-host pw=hunter2")

    with pytest.raises(RepoUnavailable) as info:
        asyncio.run(repo._run("authenticated", UID, boom))
    assert pool.returned == 1 and "hunter2" not in info.value.diagnostics()


@pytest.mark.parametrize("exc", [psycopg_pool.PoolTimeout("couldn't get a connection secret-host"), psycopg_pool.PoolClosed("closed")])
def test_pool_exhausted_or_closed_is_repo_unavailable_without_secrets(exc):
    repo = PostgresAccountRepo.from_pool(FakePool(exc))
    with pytest.raises(RepoUnavailable) as info:
        asyncio.run(repo.get_user(UID))
    assert str(info.value) == type(exc).__name__
    assert "secret-host" not in info.value.diagnostics() and info.value.__cause__ is None


def test_pool_settings_are_small_and_bounded():
    assert (mod.POOL_MIN_SIZE, mod.POOL_MAX_SIZE) == (1, 4)
    pool = mod.build_pool("postgresql://u:pw@127.0.0.1:1/db")  # 열지 않는다(접속 0)
    try:
        assert pool.min_size == 1 and pool.max_size == 4 and pool.closed
        assert pool.timeout == mod.POOL_WAIT_TIMEOUT_S and pool.max_lifetime == mod.POOL_MAX_LIFETIME_S
    finally:
        pool.close()


def test_build_account_repo_uses_pool_only_when_warmup_on(monkeypatch):
    opened: list[Any] = []

    class P(FakePool):
        def open(self, *a: Any, **k: Any) -> None:
            opened.append(self)

    monkeypatch.setattr(main, "build_pool", lambda dsn: P())

    class S:
        supabase_db_url = "postgresql://u:pw@db.example.test:5432/postgres"  # guard: fake
        mediagent_warmup = True

    repo = main.build_account_repo(S())
    assert repo is not None and repo._pool is opened[0]
    S.mediagent_warmup = False
    off = main.build_account_repo(S())
    assert off is not None and off._pool is None and len(opened) == 1  # 준비 끔: 풀 없이 요청별 연결


# --------------------------------------------------------------------------- 실제 풀 + 로컬 Postgres
_LOCAL = os.environ.get("LOCAL_PG_DSN") or None


@pytest.fixture
def local_pool():
    if not _LOCAL:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음")
    host = str(psycopg.conninfo.conninfo_to_dict(_LOCAL).get("host") or "/")
    if not host.startswith(("localhost", "127.0.0.1", "::1", "/")):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 접속 금지)")
    pool = psycopg_pool.ConnectionPool(_LOCAL, min_size=1, max_size=1, open=True, check=psycopg_pool.ConnectionPool.check_connection)
    try:
        yield pool
    finally:
        pool.close()


def _claims(conn: Any) -> str:
    return conn.execute("SELECT current_setting('request.jwt.claims', true)").fetchone()[0] or ""


def test_real_pool_does_not_leak_claims_or_role_to_next_request(local_pool):
    """max_size=1이라 두 요청이 같은 물리 연결을 쓴다. A가 설정한 신원이 B에게 보이면 안 된다(저장소와 같은 트랜잭션 로컬 방식)."""
    with local_pool.connection() as conn:  # 요청 A
        conn.execute("SELECT set_config('request.jwt.claims', %s, true)", ('{"sub": "' + UID + '"}',))
        pid_a = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert UID in _claims(conn)
    with local_pool.connection() as conn:  # 요청 B
        assert conn.execute("SELECT pg_backend_pid()").fetchone()[0] == pid_a  # 같은 연결을 재사용했다
        assert _claims(conn) == ""
        assert conn.execute("SELECT current_user = session_user").fetchone()[0] is True


def test_real_pool_rolls_back_on_error_and_stays_clean(local_pool):
    with pytest.raises(RuntimeError):
        with local_pool.connection() as conn:
            conn.execute("SELECT set_config('request.jwt.claims', 'x', true)")
            raise RuntimeError("request failed")
    with local_pool.connection() as conn:
        assert _claims(conn) == ""


def test_real_pool_with_repo_set_local_role_does_not_leak(local_pool):
    """저장소 경로 그대로: 요청 A(authenticated + claims) 뒤 요청 B(anon, claims 없음)가 A의 신원을 보지 않는다."""
    repo = PostgresAccountRepo.from_pool(local_pool)
    seen: dict[str, str] = {}

    def probe(key: str):
        def fn(cur: Any) -> None:
            cur.execute("SELECT current_user, coalesce(current_setting('request.jwt.claims', true), '')")
            seen[key] = "|".join(cur.fetchone())

        return fn

    try:
        asyncio.run(repo._run("authenticated", UID, probe("a")))
        asyncio.run(repo._run("anon", None, probe("b")))
    except RepoUnavailable:
        pytest.skip("로컬 DB에 anon/authenticated 역할이 없음")
    assert seen["a"].startswith("authenticated|") and UID in seen["a"]
    assert seen["b"] == "anon|"
