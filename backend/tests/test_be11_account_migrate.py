"""be11_account_migrate(GROUP-03 4단계 B3): 원격 DB·네트워크·LLM 호출 0.

1. 가짜 연결: plan·verify는 쓰기 0(읽기 전용 연결), apply 거부(--yes 없음·승인 파일 없음·시행 시각 없음·자리표시 남음·원격 --local-dsn),
   거부는 연결 전에 일어난다. 단계별 커밋·스키마 사후 확인 실패 시 중단·실행 직전 assert_publishable.
2. 로컬 Postgres(환경변수 `LOCAL_PG_DSN`, 없거나 로컬 주소가 아니면 skip): 버리는 DB를 새로 만들어 plan → apply(자리표시 거부) →
   apply(시험용으로 v2 자리표시를 채움) → 재실행(행 변화 0) → verify. 시험 뒤 DB를 지운다.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import be11_account_migrate as m  # noqa: E402

WRITE_WORDS = ("INSERT", "UPDATE", "ALTER", "DELETE", "DROP", "TRUNCATE", "CREATE", "GRANT", "REVOKE")
FAKE_REMOTE = "postgresql://user@db.example.invalid:5432/postgres"
EFFECTIVE = "2026-11-21T00:00:00+09:00"
ALL_KEYS = [("terms", 1), ("privacy_policy", 1), ("privacy_consent", 1), ("sensitive_consent", 1),
            ("terms", 2), ("privacy_policy", 2), ("privacy_consent", 2), ("sensitive_consent", 2), ("age_14", 1),
            ("terms", 3), ("privacy_policy", 3), ("privacy_policy", 4)]


FAKE_NAME, FAKE_EMAIL = "가짜책임자", "officer@example.invalid"  # 시험용 가짜 값(실제 .env 값을 쓰지 않음)


@pytest.fixture(autouse=True)
def _no_env_contact(monkeypatch):
    """실제 `.env`의 보호책임자 값을 읽지 않는다. 기본은 값 없음(자리표시가 남아 게시 거부)."""
    monkeypatch.setattr(m, "privacy_officer", lambda: (None, None))


def _fill_v2(effective_at, version=1, _orig=m.seed_sql):
    """시험 전용: v2의 남은 자리표시를 시험값으로 채운다(원본 파일은 그대로)."""
    sql = _orig(effective_at, version)
    return re.sub(r"\{\{(?!…\}\})[^{}\n]+\}\}", "시험값", sql) if version in (2, 3, 4) else sql


# --------------------------------------------------------------------------- 가짜 연결

class Cur:
    def __init__(self, conn):
        self.conn, self._res = conn, []

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        self._res = self.conn.answer(sql)

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res


def applied_answers(legal=None, enum=("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14"), sex=True,
                    current=None):
    legal = [(t, v, "published") for t, v in ALL_KEYS] if legal is None else legal
    current = [("age_14", 1), ("terms", 3), ("privacy_policy", 4)] if current is None else current
    return {
        "to_regclass('auth.users')": [(True,)], "to_regprocedure('auth.uid()')": [(True,)],
        "FROM pg_roles": [("anon",), ("authenticated",)],
        "FROM pg_namespace WHERE nspname": [(True,)],
        "relrowsecurity": [(t, True) for t in m.TABLES],
        "pg_enum": [(e,) for e in enum],
        "information_schema.columns": [(sex,)],
        "to_regclass('account.legal_documents')": [(True,)],
        "to_regclass('account.legal_current')": [(True,)],
        "COUNT(*) FROM account.legal_documents": [(len(legal),)],
        "FROM account.legal_documents ORDER BY": legal,
        "FROM account.legal_current": current,
    }


EMPTY = {
    "to_regclass('auth.users')": [(True,)], "to_regprocedure('auth.uid()')": [(True,)],
    "FROM pg_roles": [("anon",), ("authenticated",)], "FROM pg_namespace WHERE nspname": [(False,)],
    "relrowsecurity": [], "pg_enum": [], "information_schema.columns": [(False,)],
    "to_regclass('account.legal_documents')": [(False,)], "to_regclass('account.legal_current')": [(False,)],
}


class Conn:
    def __init__(self, answers):
        self.answers, self.executed, self.commits, self.rollbacks = answers, [], 0, 0
        self.read_only, self.closed = False, False

    def cursor(self):
        return Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def answer(self, sql):
        for key, val in self.answers.items():
            if key in sql:
                return list(val)
        return []


class Factory:
    def __init__(self, conn):
        self.conn, self.calls = conn, 0

    def __call__(self, dsn):
        self.calls += 1
        return self.conn


def writes(conn):
    return [s for s in conn.executed if any(s.lstrip().upper().startswith(w) for w in WRITE_WORDS)]


@pytest.fixture
def remote_env(monkeypatch):
    monkeypatch.setenv(m.DSN_ENV, FAKE_REMOTE)  # .env를 읽지 않게 가짜 값을 환경변수로


@pytest.fixture
def flag(tmp_path):
    p = tmp_path / "be11-account.flag"
    p.write_text("ok")
    return p


def run(argv, conn, flag_path, log=None):
    f = Factory(conn)
    return m.main(argv, connect_fn=f, flag=flag_path, log=log or (lambda s: None)), f


# --------------------------------------------------------------------------- 단계 구성

def test_steps_order_and_keys():
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC))
    assert [s.name for s in steps] == ["1 schema", "2 seed v1", "3 seed v2", "4 seed age_14", "5 seed v3", "6 seed v4"]
    assert m.expected_keys(steps) == ALL_KEYS
    assert steps[0].keys == [] and steps[0].placeholders == []


def test_current_v2_has_placeholders_and_others_do_not():
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC))
    assert steps[2].placeholders  # 지금 커밋된 v2는 자리표시가 남아 있다(Recap 45·58)
    assert steps[1].placeholders == [] and steps[3].placeholders == []
    assert steps[4].placeholders == ["{{PRIVACY_CONTACT}}"]  # v3(PRD-17-18)도 연락처 자리표시만 남는다
    assert steps[5].placeholders == ["{{PRIVACY_CONTACT}}"]  # v4(사진 판독 Upstage 고지)도 같다
    with pytest.raises(m.Refused, match="seed_legal_v2.sql"):
        m.check_publishable(steps)


# --------------------------------------------------------------------------- plan / verify (읽기 전용)

def test_plan_is_read_only(remote_env, flag):
    conn = Conn(EMPTY)
    out, f = run(["plan"], conn, flag)
    plan = out["plan"]
    assert f.calls == 1 and conn.read_only and conn.closed
    assert writes(conn) == [] and conn.commits == 0
    assert plan["schema_needed"] and plan["publishable"] is False
    assert plan["seed_rows_to_insert"] == [f"{t} v{v}" for t, v in ALL_KEYS]
    assert any(s["placeholders_left"] for s in plan["steps"] if s["step"] == "3 seed v2")


def test_plan_on_applied_db_has_nothing_to_insert(remote_env, flag):
    out, _ = run(["plan"], Conn(applied_answers()), flag)
    assert out["plan"]["schema_needed"] is False and out["plan"]["seed_rows_to_insert"] == []


def test_verify_ok_and_read_only(remote_env, flag):
    conn = Conn(applied_answers())
    out, _ = run(["verify"], conn, flag)
    assert out["verify"]["ok"] is True
    assert conn.read_only and writes(conn) == [] and conn.commits == 0


@pytest.mark.parametrize("answers, problem", [
    (applied_answers(enum=("terms", "privacy_policy", "privacy_consent", "sensitive_consent")), "schema_problems"),
    (applied_answers(sex=False), "schema_problems"),
    (applied_answers(legal=[(t, v, "published") for t, v in ALL_KEYS if v == 1]), "seed_rows_missing"),
    (applied_answers(current=[("terms", 2)]), "age_14_current"),
    (applied_answers(current=[("age_14", 1), ("terms", 2), ("privacy_policy", 2)]), "terms_v3_privacy_v4_current"),
    (applied_answers(current=[("age_14", 1), ("terms", 3), ("privacy_policy", 3)]), "terms_v3_privacy_v4_current"),
])
def test_verify_fails_when_something_missing(remote_env, flag, answers, problem):
    out, _ = run(["verify"], Conn(answers), flag)
    assert out["verify"]["ok"] is False
    assert out["verify"]["checks"][problem] not in ([], True)  # 문제 목록이 비지 않았거나 age_14_current가 False


# --------------------------------------------------------------------------- apply 거부(연결 전)

@pytest.mark.parametrize("argv, flag_exists, match", [
    (["apply", "--effective-at", EFFECTIVE], True, "--yes"),
    (["apply", "--yes", "--effective-at", EFFECTIVE], False, "승인 파일"),
    (["apply", "--yes"], True, "--effective-at"),
    (["apply", "--yes", "--effective-at", "2026-11-21T00:00:00"], True, "시간대"),
])
def test_apply_refused_before_connect(remote_env, tmp_path, argv, flag_exists, match):
    p = tmp_path / "be11-account.flag"
    if flag_exists:
        p.write_text("ok")
    conn = Conn(applied_answers())
    f = Factory(conn)
    with pytest.raises(m.Refused, match=match):
        m.main(argv, connect_fn=f, flag=p, log=lambda s: None)
    assert f.calls == 0 and conn.executed == []


def test_apply_refused_when_placeholders_left(remote_env, flag):
    conn = Conn(applied_answers())
    f = Factory(conn)
    with pytest.raises(m.Refused, match="자리표시"):
        m.main(["apply", "--yes", "--effective-at", EFFECTIVE], connect_fn=f, flag=flag, log=lambda s: None)
    assert f.calls == 0 and conn.executed == []


def test_local_dsn_rejects_remote_host(flag):
    f = Factory(Conn(EMPTY))
    with pytest.raises(m.Refused, match="로컬"):
        m.main(["plan", "--local-dsn", FAKE_REMOTE], connect_fn=f, flag=flag)
    assert f.calls == 0


def test_local_dsn_apply_needs_no_flag_but_still_yes(tmp_path):
    f = Factory(Conn(applied_answers()))
    with pytest.raises(m.Refused, match="--yes"):
        m.main(["apply", "--local-dsn", "postgresql://localhost/x", "--effective-at", EFFECTIVE], connect_fn=f,
               flag=tmp_path / "none.flag")
    with pytest.raises(m.Refused, match="자리표시"):  # 로컬도 자리표시 검사는 그대로
        m.main(["apply", "--yes", "--local-dsn", "postgresql://localhost/x", "--effective-at", EFFECTIVE], connect_fn=f,
               flag=tmp_path / "none.flag")
    assert f.calls == 0


# --------------------------------------------------------------------------- apply(가짜 연결)

def test_apply_runs_six_transactions(remote_env, flag, monkeypatch):
    monkeypatch.setattr(m, "seed_sql", _fill_v2)
    conn = Conn(applied_answers())
    out, f = run(["apply", "--yes", "--effective-at", EFFECTIVE], conn, flag)
    assert f.calls == 1 and conn.read_only is False and conn.closed
    assert conn.commits == 6
    rep = out["apply"]
    assert [k for k in rep if k[0].isdigit()] == ["1 schema", "2 seed v1", "3 seed v2", "4 seed age_14", "5 seed v3", "6 seed v4"]
    assert all(rep[k]["inserted"] == 0 for k in ("2 seed v1", "3 seed v2", "4 seed age_14", "5 seed v3", "6 seed v4"))  # 가짜 DB는 이미 적용 상태
    schema_text = m.schema_sql()
    assert schema_text in conn.executed
    seeds = [s for s in conn.executed if "INSERT INTO account.legal_documents" in s]
    assert len(seeds) == 5 and all(m.unfilled_placeholders(s) == [] for s in seeds)


def test_apply_stops_when_schema_postcheck_fails(remote_env, flag, monkeypatch):
    monkeypatch.setattr(m, "seed_sql", _fill_v2)
    conn = Conn(applied_answers(sex=False))
    with pytest.raises(m.StageAbort, match="profiles.sex"):
        run(["apply", "--yes", "--effective-at", EFFECTIVE], conn, flag)
    assert conn.commits == 1  # 스키마만 커밋, 시드는 돌지 않음
    assert not any("INSERT INTO account.legal_documents" in s for s in conn.executed)


def test_apply_stops_when_auth_missing(remote_env, flag, monkeypatch):
    monkeypatch.setattr(m, "seed_sql", _fill_v2)
    answers = applied_answers()
    answers["FROM pg_roles"] = [("authenticated",)]
    conn = Conn(answers)
    with pytest.raises(m.StageAbort, match="auth"):
        run(["apply", "--yes", "--effective-at", EFFECTIVE], conn, flag)
    assert writes(conn) == [] and conn.commits == 0


def test_run_seed_rechecks_placeholders_inside_transaction():
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC))
    conn = Conn(applied_answers())
    with pytest.raises(m.StageAbort, match="자리표시"):
        m.transaction(conn, "3 seed v2", lambda cur: m.run_seed(cur, steps[2]), log=lambda s: None)
    assert (conn.commits, conn.rollbacks) == (0, 1)
    assert not any("INSERT INTO account.legal_documents" in s for s in conn.executed)


def test_do_apply_refuses_unpublishable_steps_before_any_query():
    conn = Conn(applied_answers())
    with pytest.raises(m.Refused):
        m.do_apply(conn, m.build_steps(datetime(2026, 11, 21, tzinfo=UTC)), log=lambda s: None)
    assert conn.executed == []


def test_run_seed_aborts_when_row_not_published():
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC))
    conn = Conn(applied_answers(legal=[(t, v, "published") for t, v in ALL_KEYS if t != "age_14"]))
    with pytest.raises(m.StageAbort):
        m.transaction(conn, "4 seed age_14", lambda cur: m.run_seed(cur, steps[3]), log=lambda s: None)
    assert conn.rollbacks == 1 and conn.commits == 0


# --------------------------------------------------------------------------- 로컬 Postgres

LOCAL_PG_DSN: str | None = os.environ.get("LOCAL_PG_DSN") or None
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


@pytest.fixture
def scratch_dsn() -> Iterator[str]:
    """LOCAL_PG_DSN 서버에 버리는 DB를 만들어 준다(다른 시험의 account 스키마를 건드리지 않게). 끝나면 지운다."""
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(로컬 시험)")
    if not m.is_local_dsn(LOCAL_PG_DSN):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    import psycopg

    name = f"mediagent_b3_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(LOCAL_PG_DSN, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(AUTH_STUB)
        yield dsn
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_local_pg_plan_apply_rerun_verify(scratch_dsn, monkeypatch, tmp_path):
    no_flag = tmp_path / "absent.flag"
    eff = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    quiet = lambda s: None  # noqa: E731

    plan = m.main(["plan", "--local-dsn", scratch_dsn], flag=no_flag, log=quiet)["plan"]
    assert plan["schema_needed"] and plan["auth_ready"] and plan["publishable"] is False
    assert len(plan["seed_rows_to_insert"]) == len(ALL_KEYS)

    with pytest.raises(m.Refused, match="자리표시"):  # 지금 v2 그대로면 로컬도 거부
        m.main(["apply", "--yes", "--local-dsn", scratch_dsn, "--effective-at", eff], flag=no_flag, log=quiet)
    assert m.main(["verify", "--local-dsn", scratch_dsn], flag=no_flag, log=quiet)["verify"]["state"]["account_schema"] is False

    monkeypatch.setattr(m, "seed_sql", _fill_v2)
    first = m.main(["apply", "--yes", "--local-dsn", scratch_dsn, "--effective-at", eff], flag=no_flag, log=quiet)["apply"]
    assert [first[k]["inserted"] for k in ("2 seed v1", "3 seed v2", "4 seed age_14", "5 seed v3", "6 seed v4")] == [4, 4, 1, 2, 1]
    after = first["after"]
    assert "age_14" in after["doc_type_values"] and after["sex_column"] and after["rls_off"] == []
    assert sorted(after["legal_current"]) == sorted([["age_14", 1], ["privacy_consent", 2], ["privacy_policy", 4],
                                                      ["sensitive_consent", 2], ["terms", 3]])

    second = m.main(["apply", "--yes", "--local-dsn", scratch_dsn, "--effective-at", eff], flag=no_flag, log=quiet)["apply"]
    assert [second[k]["inserted"] for k in ("2 seed v1", "3 seed v2", "4 seed age_14", "5 seed v3", "6 seed v4")] == [0, 0, 0, 0, 0]
    assert second["after"]["legal_rows"] == after["legal_rows"]

    ver = m.main(["verify", "--local-dsn", scratch_dsn], flag=no_flag, log=quiet)["verify"]
    assert ver["ok"] is True, ver["checks"]
    plan2 = m.main(["plan", "--local-dsn", scratch_dsn], flag=no_flag, log=quiet)["plan"]
    assert plan2["schema_needed"] is False and plan2["seed_rows_to_insert"] == []


# --------------------------------------------------------------------------- 보호책임자 연락처 렌더링(PRD-17 ⑫, 2026-11-20)

def test_build_steps_renders_privacy_contact_from_env_values():
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC), (FAKE_NAME, FAKE_EMAIL))
    v2 = steps[2].sql
    assert steps[2].placeholders == []  # 본문에는 남지 않는다(주석 줄의 설명 문구는 그대로)
    line = f"Can I PPiyak 운영자(개발자) · 개인정보 보호책임자: {FAKE_NAME}, 문의: {FAKE_EMAIL}"
    assert v2.count(line) == 2  # terms §6 문의 + privacy_policy §7 보호책임자
    m.check_publishable(steps)  # 남은 자리표시 0 → 게시 가능
    assert steps[2].masked == (FAKE_NAME, FAKE_EMAIL) and steps[0].masked == ()


@pytest.mark.parametrize("contact", [None, (None, None), ("", FAKE_EMAIL), (FAKE_NAME, "  ")])
def test_missing_contact_keeps_placeholder_and_refuses(contact):
    steps = m.build_steps(datetime(2026, 11, 21, tzinfo=UTC), contact)
    assert steps[2].placeholders == ["{{PRIVACY_CONTACT}}"]
    with pytest.raises(m.Refused, match="PRIVACY_CONTACT"):
        m.check_publishable(steps)


@pytest.mark.parametrize("contact", [(FAKE_NAME, "not-an-email"), ("이름$md$", FAKE_EMAIL), ("이름\n둘째 줄", FAKE_EMAIL),
                                     ("{{X}}", FAKE_EMAIL), ("a|b", FAKE_EMAIL)])
def test_bad_contact_refused_without_echoing_value(contact):
    with pytest.raises(m.Refused) as ei:
        m.build_steps(datetime(2026, 11, 21, tzinfo=UTC), contact)
    assert contact[0] not in str(ei.value) and contact[1] not in str(ei.value)


def test_plan_masks_contact_and_logs_no_value(remote_env, flag):
    logs: list[str] = []
    out = m.main(["plan"], connect_fn=Factory(Conn(EMPTY)), flag=flag, log=logs.append, contact=(FAKE_NAME, FAKE_EMAIL))
    plan = out["plan"]
    assert plan["publishable"] is True and plan["privacy_contact"] == "<설정됨>"
    text = "\n".join(logs) + repr(out)
    assert FAKE_NAME not in text and FAKE_EMAIL not in text


def test_plan_without_contact_says_none(remote_env, flag):
    out, _ = run(["plan"], Conn(EMPTY), flag)
    assert out["plan"]["privacy_contact"] == "<없음>" and out["plan"]["publishable"] is False


def test_apply_with_contact_inserts_rendered_seed_and_logs_no_value(remote_env, flag):
    conn, logs = Conn(applied_answers()), []
    out = m.main(["apply", "--yes", "--effective-at", EFFECTIVE], connect_fn=Factory(conn), flag=flag, log=logs.append,
                 contact=(FAKE_NAME, FAKE_EMAIL))
    seeds = [s for s in conn.executed if "INSERT INTO account.legal_documents" in s]
    assert len(seeds) == 5 and all(m.unfilled_placeholders(s) == [] for s in seeds)
    assert any(f"개인정보 보호책임자: {FAKE_NAME}, 문의: {FAKE_EMAIL}" in s for s in seeds)
    text = "\n".join(logs) + repr(out)
    assert FAKE_NAME not in text and FAKE_EMAIL not in text


def test_apply_without_env_contact_refused_before_connect(remote_env, flag):
    f = Factory(Conn(applied_answers()))
    with pytest.raises(m.Refused, match="PRIVACY_CONTACT"):
        m.main(["apply", "--yes", "--effective-at", EFFECTIVE], connect_fn=f, flag=flag, log=lambda s: None)
    assert f.calls == 0


def test_stage_abort_message_scrubs_contact():
    class Boom(Exception):
        pass

    def fn(cur):
        raise Boom(f"LINE 1: ... 개인정보 보호책임자: {FAKE_NAME}, 문의: {FAKE_EMAIL} ...")

    logs: list[str] = []
    with pytest.raises(m.StageAbort) as ei:
        m.transaction(Conn(applied_answers()), "3 seed v2", fn, log=logs.append, masked=(FAKE_NAME, FAKE_EMAIL))
    text = str(ei.value) + "\n".join(logs)
    assert FAKE_NAME not in text and FAKE_EMAIL not in text and "<설정됨>" in text


def test_local_pg_body_sha256_is_of_rendered_body(scratch_dsn, tmp_path):
    """채운 뒤 본문으로 body_sha256(DB 생성 열)이 계산된다."""
    import psycopg

    from app.db.account_repo import body_sha256

    eff = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    m.main(["apply", "--yes", "--local-dsn", scratch_dsn, "--effective-at", eff], flag=tmp_path / "absent.flag",
           log=lambda s: None, contact=(FAKE_NAME, FAKE_EMAIL))
    with psycopg.connect(scratch_dsn) as conn:
        rows = conn.execute("SELECT doc_type::text, body_md, body_sha256 FROM account.legal_documents "
                            "WHERE version = 2 AND doc_type IN ('terms', 'privacy_policy')").fetchall()
    assert len(rows) == 2
    for _, body, digest in rows:
        assert "{{PRIVACY_CONTACT}}" not in body and f"보호책임자: {FAKE_NAME}, 문의: {FAKE_EMAIL}" in body
        assert digest == body_sha256(body)
