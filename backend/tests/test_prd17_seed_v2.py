"""PRD-17 ③ 약관·개인정보 v2 시드(PRD-17-05 A: v2 행 추가, v1 유지) 시험(2026-11-19). 원격 DB·네트워크·LLM 호출 0.

1. 정적 검사(항상): `seed_legal_v2.sql`의 4행(version·required·requires_reconsent·머리 문구)과 자리표시 게시 차단.
2. 로컬 Postgres(환경변수 `LOCAL_PG_DSN`이 없거나 로컬 주소가 아니면 skip, `.env`는 읽지 않음):
   ① v1·v2 적용(두 번, 멱등)·게시본 수정 불가 ② 최신 판 = v2 ③ v1 동의자의 재동의 판정
   ④ privacy_policy 동의 기록 거부 ⑤ RLS 본인 동의 기록만 ⑥ body_sha256 일치.
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

from app.api.account import AccountError, consent_states, gate_consents, health_writable, required_ok
from app.db.account_repo import CONSENT_DOC_TYPES, ConsentInput, body_sha256
from app.db.account_repo_pg import (
    SEED_V2_FILE,
    PostgresAccountRepo,
    assert_publishable,
    schema_sql,
    seed_sql,
    unfilled_placeholders,
)

# test_be11_account_pg.py와 같은 규칙: 환경변수에서만 읽고(.env·SUPABASE_DB_URL 폴백 없음) 로컬 주소가 아니면 skip
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

DOC_TYPES = ("terms", "privacy_policy", "privacy_consent", "sensitive_consent")
_ROW_RE = re.compile(
    r"\('(\w+)', (\d+), '([^']*)', \$md\$(.*?)\$md\$, (true|false), (true|false), 'published', '\{\{EFFECTIVE_AT\}\}'\)", re.S)


def _rows(text: str) -> dict[str, dict[str, Any]]:
    return {m[0]: {"version": int(m[1]), "title": m[2], "body": m[3], "required": m[4] == "true", "requires_reconsent": m[5] == "true"}
            for m in _ROW_RE.findall(text)}


V2_TEXT = SEED_V2_FILE.read_text(encoding="utf-8")
V2_ROWS = _rows(V2_TEXT)


# --------------------------------------------------------------------------- 1. 정적 검사
def test_v2_seed_has_four_rows_with_decided_flags():
    assert tuple(V2_ROWS) == DOC_TYPES
    assert {t: r["version"] for t, r in V2_ROWS.items()} == dict.fromkeys(DOC_TYPES, 2)
    # required는 v1과 같다(privacy_policy는 고지 문서라 동의 대상 아님, PRD-17-02 A)
    assert {t: r["required"] for t, r in V2_ROWS.items()} == {
        "terms": True, "privacy_policy": False, "privacy_consent": True, "sensitive_consent": False}
    # 수집 항목·외부 전송이 바뀐 두 동의서만 재동의(legal-review §3 권장, 사용자 승인)
    assert {t: r["requires_reconsent"] for t, r in V2_ROWS.items()} == {
        "terms": False, "privacy_policy": False, "privacy_consent": True, "sensitive_consent": True}
    assert "INSERT INTO account.legal_documents (doc_type, version, title, body_md, required, requires_reconsent, status, effective_at)" in V2_TEXT
    assert V2_TEXT.rstrip().endswith("ON CONFLICT (doc_type, version) DO NOTHING;")


def test_v2_bodies_keep_draft_header_and_approval_line():
    for t, r in V2_ROWS.items():
        lines = r["body"].strip("\n").splitlines()
        assert lines[0].startswith("> 초안·법률 검토 전입니다."), t
        assert lines[1] == "> 원문 승인 2026-11-19(사용자), `{{…}}` 값은 사실 확인 뒤 채움.", t
        assert "$md$" not in r["body"]
    # 만 14세 체크는 동의서 본문이 아니라 화면의 별도 체크(PRD-17-06 A)
    assert "[필수 체크]" not in V2_ROWS["privacy_consent"]["body"]
    assert "Naver" not in V2_ROWS["privacy_policy"]["body"]  # A-2: S2 전에는 적지 않는다


def test_v2_sex_optional_item_in_policy_and_profile_consent():
    """PRD-17 ⑭(PRD-17-13 A, 2026-11-20 사용자 "성별 문구 승인"): 성별(선택)을 처리방침·프로필 동의 두 문서에 적는다."""
    policy = V2_ROWS["privacy_policy"]["body"]
    assert "| 프로필(동의한 경우): 관계, 표시 이름(선택), 연령대, 성별(선택) | 질문할 때 연령대를 자동으로 채워 연령금기를 확인. " \
           "성별은 질문 화면에 임신 여부 선택을 보여 줄지 정하는 데만 씁니다 |" in policy
    assert "가족 구성원의 관계, 표시 이름, 연령대, 성별(선택)(건강 정보는 위와 같음)" in policy
    consent = V2_ROWS["privacy_consent"]["body"]
    assert "- 수집 항목: 관계, 표시 이름(선택), 연령대, 성별(선택, 직접 고른 경우에만). 로그인 정보(" in consent
    assert consent.count("성별은 질문 화면에서 임신 여부 선택을 보여 줄지 정하는 데만 쓰며, 외부 AI 서비스로 전송하지 않습니다. "
                         "간편 로그인 공급자에게서 성별을 받지 않습니다.") == 1
    # 성별은 건강 정보가 아니다: 민감정보 동의서와 약관에는 넣지 않는다
    assert "성별" not in V2_ROWS["sensitive_consent"]["body"] and "성별" not in V2_ROWS["terms"]["body"]


def test_v2_seed_substitutes_effective_at_only():
    sql = seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=2)
    assert "{{EFFECTIVE_AT}}" not in sql and sql.count("'2026-12-01T00:00:00+00:00'") == 4
    assert "{{PRIVACY_CONTACT}}" in sql  # 값을 모르는 자리표시는 그대로 둔다
    with pytest.raises(ValueError):
        seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=3)


def test_placeholders_block_remote_publish_but_not_v1():
    sql_v2 = seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=2)
    left = unfilled_placeholders(sql_v2)
    assert {"{{PRIVACY_CONTACT}}", "{{SUPABASE_REGION}}", "{{BACKUP_RETENTION_DAYS}}"} <= set(left)
    assert any(p.startswith("{{확인 필요:") for p in left)
    # PRD-17 ⑫(2026-11-20, Recap 58): OpenAI 줄의 법인·연락처·국가·보관 기간은 채웠다. 다른 자리표시가 남아 게시 차단은 그대로다
    assert "{{COUNTRY_OPENAI}}" not in left and "{{확인 필요: 기간}}" not in left
    openai_row = next(line for line in V2_ROWS["privacy_policy"]["body"].splitlines() if line.startswith("| OpenAI"))
    assert "{{" not in openai_row
    assert "OpenAI OpCo, L.L.C." in openai_row and "| 미국 / 질문할 때마다 / 인터넷 전송 |" in openai_row and "최대 30일" in openai_row
    assert "{{…}}" not in left  # 승인 원문 머리의 안내 문구는 자리표시가 아니다
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(sql_v2)
    assert_publishable(seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=1))  # v1은 자리표시 없음
    with pytest.raises(ValueError, match="EFFECTIVE_AT"):
        assert_publishable(V2_TEXT)  # 시행 시각을 채우지 않은 원문도 막힌다
    assert unfilled_placeholders("-- {{IN_COMMENT}}\nSELECT 1;") == []


# --------------------------------------------------------------------------- 2. 로컬 Postgres(DSN 없으면 skip)
_CREATED: list[str] = []


def _new_user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    _CREATED.append(uid)
    return uid


def _as_user(dsn: str, uid: str, sql: str, params: Any = ()) -> Any:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": uid}),))
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


@pytest.fixture(scope="module")
def v2_db() -> Iterator[dict[str, str]]:
    """v1만 게시 → 사용자 A(v1 terms·privacy_consent·sensitive_consent 동의)·B(v1 terms·privacy_consent) → v2 게시(두 번, 멱등)."""
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(_LOCAL_HOSTS):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    now = datetime.now(UTC)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(schema_sql())
        conn.execute(seed_sql(now - timedelta(minutes=2), version=1))
    repo = PostgresAccountRepo.from_dsn(LOCAL_PG_DSN)
    a, b = _new_user(LOCAL_PG_DSN), _new_user(LOCAL_PG_DSN)
    for uid, items in ((a, ("terms", "privacy_consent", "sensitive_consent")), (b, ("terms", "privacy_consent"))):
        asyncio.run(repo.ensure_user(uid))
        asyncio.run(repo.add_consents(uid, [ConsentInput(t, 1, "agree") for t in items], "onboarding"))
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        for _ in range(2):
            conn.execute(seed_sql(now - timedelta(minutes=1), version=2))
    try:
        yield {"dsn": LOCAL_PG_DSN, "a": a, "b": b}
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            if _CREATED:
                conn.execute("DELETE FROM auth.users WHERE id = ANY(%s::uuid[])", (_CREATED,))
        _CREATED.clear()


def test_pg_v1_and_v2_applied_and_published_rows_frozen(v2_db):
    dsn = v2_db["dsn"]
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT doc_type::text, version, required, requires_reconsent, legal_review FROM account.legal_documents "
                            "ORDER BY doc_type, version").fetchall()
    assert len(rows) == 8 and {r[1] for r in rows} == {1, 2}
    assert all(r[4] == "not_reviewed" for r in rows)
    assert all(r[3] is False for r in rows if r[1] == 1)  # v1은 열 기본값 그대로
    for version in (1, 2):
        with pytest.raises(psycopg.errors.RaiseException, match="DOCUMENT_FROZEN"), psycopg.connect(dsn) as conn:
            conn.execute("UPDATE account.legal_documents SET body_md = body_md || 'x' WHERE doc_type = 'terms' AND version = %s",
                         (version,))


def test_pg_current_version_is_v2(v2_db):
    repo = PostgresAccountRepo.from_dsn(v2_db["dsn"])
    for t in DOC_TYPES:
        doc = asyncio.run(repo.legal_current(t))
        assert doc is not None and doc.version == 2, t
        assert doc.required is V2_ROWS[t]["required"] and doc.requires_reconsent is V2_ROWS[t]["requires_reconsent"]
    assert [d.version for d in asyncio.run(repo.legal_published("terms"))] == [1, 2]


def test_pg_v1_consent_needs_reconsent_for_consent_docs_only(v2_db):
    repo = PostgresAccountRepo.from_dsn(v2_db["dsn"])
    states = {s.doc_type: s for s in asyncio.run(consent_states(repo, v2_db["a"]))}
    assert tuple(states) == CONSENT_DOC_TYPES
    assert (states["terms"].agreed_version, states["terms"].current_version, states["terms"].needs_reconsent) == (1, 2, False)
    assert states["privacy_consent"].needs_reconsent and not states["privacy_consent"].needs_consent
    assert states["sensitive_consent"].needs_reconsent
    assert not required_ok(states.values()) and not health_writable(states.values())
    with pytest.raises(AccountError) as info:
        gate_consents(list(states.values()), ["terms", "privacy_consent"])
    assert (info.value.status_code, info.value.code) == (403, "RECONSENT_REQUIRED")
    # v2에 다시 동의하면 풀린다(channel=reconsent)
    asyncio.run(repo.add_consents(v2_db["a"], [ConsentInput("privacy_consent", 2, "agree"),
                                               ConsentInput("sensitive_consent", 2, "agree")], "reconsent"))
    states = asyncio.run(consent_states(repo, v2_db["a"]))
    assert required_ok(states) and health_writable(states) and not any(s.needs_reconsent for s in states)
    # B는 sensitive_consent에 동의한 적이 없으므로 재동의가 아니라 '동의 없음'
    b_states = {s.doc_type: s for s in asyncio.run(consent_states(repo, v2_db["b"]))}
    assert b_states["sensitive_consent"].needs_consent and not b_states["sensitive_consent"].needs_reconsent
    assert b_states["privacy_consent"].needs_reconsent and not b_states["terms"].needs_reconsent


def test_pg_privacy_policy_consent_still_rejected(v2_db):
    for version in (1, 2):
        with pytest.raises(psycopg.errors.CheckViolation):
            _as_user(v2_db["dsn"], v2_db["b"], "INSERT INTO account.user_consents (user_id, doc_type, doc_version, action, channel) "
                     "VALUES (%s, 'privacy_policy', %s, 'agree', 'onboarding')", (v2_db["b"], version))


def test_pg_rls_reads_only_own_consents(v2_db):
    dsn, a, b = v2_db["dsn"], v2_db["a"], v2_db["b"]
    owners = {r[0] for r in _as_user(dsn, b, "SELECT user_id::text FROM account.user_consents")}
    assert owners == {b}
    assert _as_user(dsn, b, "SELECT * FROM account.user_consents WHERE user_id = %s", (a,)) == []
    assert {r[0] for r in _as_user(dsn, b, "SELECT user_id::text FROM account.user_consent_current")} == {b}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_user(dsn, b, "UPDATE account.legal_documents SET title = 'x' WHERE version = 2")


def test_pg_v2_body_sha256_matches_seed_file_and_python(v2_db):
    repo = PostgresAccountRepo.from_dsn(v2_db["dsn"])
    for t in DOC_TYPES:
        doc = asyncio.run(repo.legal_version(t, 2))
        assert doc is not None and doc.body_md == V2_ROWS[t]["body"], t  # 파일 본문이 바뀌지 않고 들어갔다
        assert doc.body_sha256 == body_sha256(doc.body_md) == body_sha256(V2_ROWS[t]["body"])
