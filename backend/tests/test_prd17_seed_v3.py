"""PRD-17-18 A 약관·처리방침 v3(보호책임자 연락처 줄 구분) 시험(2026-11-22). 원격 DB·네트워크·LLM 호출 0.

1. 정적: v3 = terms·privacy_policy 두 행, v2와 본문 차이는 연락처 줄뿐, requires_reconsent=false.
2. 렌더링: 가짜 값으로 세 줄 형식·v2 형식 불변(v2 해시 유지)·값 없음 게시 거부·값 검사·오류에 값 비노출.
3. 로컬 Postgres(`LOCAL_PG_DSN`, 없으면 skip): v2 동의자는 v3 게시 뒤에도 재동의가 필요 없고 최신판은 terms·privacy_policy v3.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import re
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from tests.test_prd17_seed_v2 import AUTH_STUB, _rows

from app.api.account import consent_states, required_ok
from app.db.account_repo import ConsentInput, body_sha256
from app.db.account_repo_pg import (
    SEED_V2_FILE,
    SEED_V3_FILE,
    PostgresAccountRepo,
    assert_publishable,
    render_privacy_contact,
    schema_sql,
    seed_age14_sql,
    seed_sql,
    unfilled_placeholders,
)

NOW = datetime(2026, 12, 1, tzinfo=UTC)
V2_ROWS = _rows(SEED_V2_FILE.read_text(encoding="utf-8"))
V3_ROWS = _rows(SEED_V3_FILE.read_text(encoding="utf-8"))
OLD_LINE = "Can I PPiyak 운영자(개발자) · {{PRIVACY_CONTACT}}"
NEW_LINES = "Can I PPiyak 운영자(개발자)\\\n{{PRIVACY_CONTACT}}"
NAME, EMAIL = "가짜책임자", "officer@example.invalid"
INLINE = f"Can I PPiyak 운영자(개발자) · 개인정보 보호책임자: {NAME}, 문의: {EMAIL}"
THREE = f"Can I PPiyak 운영자(개발자)\\\n개인정보 보호책임자: {NAME}\\\n문의: {EMAIL}"


def test_v3_has_only_terms_and_privacy_policy_at_version_3():
    assert set(V3_ROWS) == {"terms", "privacy_policy"}
    for t, row in V3_ROWS.items():
        assert row["version"] == 3 and row["title"] == V2_ROWS[t]["title"]
        assert (row["required"], row["requires_reconsent"]) == (V2_ROWS[t]["required"], False)
        assert V2_ROWS[t]["requires_reconsent"] is False  # v2도 false였으므로 재동의 요건이 바뀌지 않는다


@pytest.mark.parametrize("doc_type", ["terms", "privacy_policy"])
def test_v3_body_differs_from_v2_only_in_contact_line(doc_type):
    v2, v3 = V2_ROWS[doc_type]["body"], V3_ROWS[doc_type]["body"]
    assert v2.count(OLD_LINE) == 1 and v3.count(NEW_LINES) == 1 and OLD_LINE not in v3
    assert v2.replace(OLD_LINE, NEW_LINES) == v3  # 그 밖의 글자는 한 자도 다르지 않다
    changed = [d for d in difflib.ndiff(v2.splitlines(), v3.splitlines()) if d[:1] in "+-"]
    assert len(changed) == 3  # 지운 한 줄, 넣은 두 줄


def test_v3_seed_substitutes_effective_at_and_blocks_publish_until_contact_filled():
    sql = seed_sql(NOW, version=3)
    assert "{{EFFECTIVE_AT}}" not in sql and sql.count("'2026-12-01T00:00:00+00:00'") == 2
    assert unfilled_placeholders(sql) == ["{{PRIVACY_CONTACT}}"]
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(sql)


def test_render_v3_makes_three_lines_and_publishable():
    out = render_privacy_contact(seed_sql(NOW, version=3), f" {NAME} ", EMAIL)
    assert unfilled_placeholders(out) == [] and out.count(THREE + "\n") == 2
    assert_publishable(out)
    filled = _rows(out.replace("'2026-12-01T00:00:00+00:00'", "'{{EFFECTIVE_AT}}'"))
    for t in ("terms", "privacy_policy"):
        assert filled[t]["body"] == V3_ROWS[t]["body"].replace(NEW_LINES, THREE)
        assert body_sha256(filled[t]["body"]) != body_sha256(V3_ROWS[t]["body"])  # 해시는 채운 본문 기준


def test_render_v2_keeps_inline_format_so_v2_body_is_unchanged():
    out = render_privacy_contact(seed_sql(NOW, version=2), NAME, EMAIL)
    assert out.count(INLINE) == 2
    assert "\\\n" not in out.split("INSERT INTO", 1)[1]  # v2에는 강제 줄바꿈이 생기지 않는다
    filled = _rows(out.replace("'2026-12-01T00:00:00+00:00'", "'{{EFFECTIVE_AT}}'"))
    for t in ("terms", "privacy_policy"):
        assert filled[t]["body"] == V2_ROWS[t]["body"].replace(OLD_LINE, INLINE)


@pytest.mark.parametrize("name, email", [(None, EMAIL), (NAME, ""), ("", ""), (NAME, "no-at-sign"), ("a\nb", EMAIL),
                                         ("a\\b", EMAIL), (NAME, "a@b.invalid|x")])
def test_render_v3_rejects_missing_or_bad_values_without_echo(name, email):
    with pytest.raises(ValueError) as ei:
        render_privacy_contact(seed_sql(NOW, version=3), name, email)
    for v in (NAME, EMAIL, "no-at-sign"):
        assert v not in str(ei.value)


def test_render_ignores_placeholder_in_sql_comment():
    out = render_privacy_contact("-- {{PRIVACY_CONTACT}}\nx\n{{PRIVACY_CONTACT}}\n", NAME, EMAIL)
    assert out.splitlines()[0] == "-- {{PRIVACY_CONTACT}}" and NAME not in out.splitlines()[0]


# --------------------------------------------------------------------------- 로컬 Postgres
LOCAL_PG_DSN = os.environ.get("LOCAL_PG_DSN") or None


@pytest.fixture(scope="module")
def v3_db():
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(("localhost", "127.0.0.1", "::1", "/")):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    now = datetime.now(UTC)
    uid = str(uuid.uuid4())
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
        conn.execute(schema_sql())
        conn.execute(seed_sql(now - timedelta(minutes=3), version=1))
        conn.execute(seed_age14_sql(now - timedelta(minutes=3)))
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    repo = PostgresAccountRepo.from_dsn(LOCAL_PG_DSN)
    asyncio.run(repo.ensure_user(uid))
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute(render_privacy_contact(seed_sql(now - timedelta(minutes=2), version=2), NAME, EMAIL))
    asyncio.run(repo.add_consents(
        uid, [ConsentInput("terms", 2, "agree"), ConsentInput("privacy_consent", 2, "agree"), ConsentInput("age_14", 1, "agree")],
        "onboarding"))
    sql3 = render_privacy_contact(seed_sql(now - timedelta(minutes=1), version=3), NAME, EMAIL)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        for _ in range(2):  # 멱등
            conn.execute(sql3)
    try:
        yield {"dsn": LOCAL_PG_DSN, "uid": uid, "repo": repo}
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            conn.execute("DELETE FROM auth.users WHERE id = %s::uuid", (uid,))


def test_pg_current_is_v3_for_terms_and_privacy_policy_only(v3_db):
    repo = v3_db["repo"]
    cur = {t: asyncio.run(repo.legal_current(t)).version for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent")}
    assert cur == {"terms": 3, "privacy_policy": 3, "privacy_consent": 2, "sensitive_consent": 2}


def test_pg_v2_consenter_needs_no_reconsent_after_v3(v3_db):
    states = {s.doc_type: s for s in asyncio.run(consent_states(v3_db["repo"], v3_db["uid"]))}
    t = states["terms"]
    assert (t.agreed_version, t.current_version, t.needs_consent, t.needs_reconsent) == (2, 3, False, False)
    assert states["privacy_consent"].needs_reconsent is False and states["privacy_consent"].current_version == 2
    assert required_ok(list(states.values()))


def test_pg_v2_published_body_stays_and_v3_body_has_three_lines(v3_db):
    repo = v3_db["repo"]
    v2 = asyncio.run(repo.legal_version("terms", 2))
    v3 = asyncio.run(repo.legal_version("terms", 3))
    assert INLINE in v2.body_md
    assert v3.body_md.rstrip().endswith(THREE)
    assert v3.body_sha256 == body_sha256(v3.body_md) and re.fullmatch(r"[0-9a-f]{64}", v3.body_sha256)
    with pytest.raises(psycopg.errors.Error), psycopg.connect(v3_db["dsn"], autocommit=True) as conn:
        conn.execute("UPDATE account.legal_documents SET body_md = 'x' WHERE doc_type = 'terms' AND version = 2")
