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
    render_privacy_contact,
    schema_sql,
    seed_age14_sql,
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


def test_v2_policy_recap45_facts():
    """Recap 45(2026-11-20 사용자 "초안 승인·⑧ B"): 로그인 저장 항목·쿠키·안전성 조치·보존 정보 문장을 승인 초안 그대로 둔다.
    사진은 필수 기능(2026-11-20 사용자 정정, 축소는 음성만)이므로 ⑦ 사진 전송 문장((a) 2절·(b) 3절 OpenAI 줄)도 넣는다."""
    policy = V2_ROWS["privacy_policy"]["body"]
    assert "| 로그인 정보: 소셜 로그인 공급자(Google·Kakao)가 넘기는 계정 식별자·이메일·이름(Kakao는 닉네임)·프로필 사진 주소" \
           "(Kakao는 선택 동의한 경우), 가입·마지막 로그인 시각. 로그인 처리(Supabase)가 보관하며, 이 서비스는 이 중 계정 식별자만 씁니다 |" in policy
    assert "로그인하면 로그인 상태를 유지하기 위한 쿠키(`sb-…-auth-token`)를 사용합니다. 이 쿠키에는 로그인 토큰과 사용자 정보(이메일 포함)가 " \
           "담기며, 로그아웃하지 않으면 최대 400일 동안 이 브라우저에 남습니다. 로그아웃하면 이 브라우저에서 삭제됩니다. " \
           "브라우저 설정에서 쿠키를 거부할 수 있으나 로그인이 되지 않을 수 있습니다." in policy
    assert "세션 쿠키" not in policy  # 지속 쿠키(maxAge 400일)라 "세션 쿠키"는 사실과 다르다
    assert "본인 계정만 읽고 수정·삭제할 수 있도록 행 수준 보안을 적용하고, 서버도 같은 규칙 아래에서 데이터베이스를 읽고 씁니다. " \
           "로그인 토큰은 서버가 서명과 만료를 확인한 뒤에만 받아들입니다. 비밀값(키·토큰)은 코드와 로그에 남기지 않고, " \
           "계정 정보 응답은 브라우저에 캐시하지 않습니다.\n" in policy
    assert "HTTPS" not in policy  # 배포 주소가 모두 https인지 확인한 뒤 더한다
    # ⑧ B: 서버 접근 로그를 끄므로 보존 정보는 없다는 문장만, 2절 서버 로그 문장은 그대로 사실이다
    assert "\n법령에 따라 보존해야 하는 정보는 없습니다.\n" in policy
    assert "서버 로그에는 시각·걸린 시간·종료 사유·개수만 남고 질문 문장은 남지 않습니다." in policy
    assert "약봉투 사진과 음성은 저장하지 않습니다. 약봉투 사진을 올리면 약 이름을 읽기 위해 사진이 외부 AI 서비스(OpenAI)로 전송되며, " \
           "그곳의 보관은 3절과 같습니다.\n" in policy
    openai_row = next(line for line in policy.splitlines() if line.startswith("| OpenAI"))
    cells = [c.strip() for c in openai_row.strip("|").split(" | ")]
    assert len(cells) == 6 and cells[1] == "답변 생성, 약봉투 사진에서 약 이름 읽기"
    assert cells[2].endswith("로그인하지 않고 질문에 적은 내용도 같습니다. 약봉투 사진을 올린 경우 그 사진(사진에 인쇄된 이름·약국 정보 등이 함께 담길 수 있음)")
    assert cells[3] == "미국 / 질문하거나 사진을 올릴 때마다 / 인터넷 전송"
    assert cells[5].endswith("사진을 올리지 않으면 사진은 전송되지 않으며, 약 이름을 직접 입력할 수 있습니다.")
    assert "{{확인 필요" not in policy


def test_v2_policy_supabase_row_recap45_134():
    """Recap 45 ①③④(2026-11-20 사용자 승인): Supabase 줄의 법인·연락처·리전·백업 보존을 승인 문구 글자 그대로 채웠다.
    출처 https://supabase.com/privacy · /docs/guides/platform/backups · /docs/guides/platform/regions(읽은 날 2026-11-20)."""
    policy = V2_ROWS["privacy_policy"]["body"]
    row = next(line for line in policy.splitlines() if line.startswith("| Supabase"))
    cells = [c.strip() for c in row.strip("|").split(" | ")]
    assert len(cells) == 6 and "{{" not in row
    assert cells[0] == "Supabase(Supabase Pte. Ltd. · 문의 privacy@supabase.com)"
    assert cells[3] == "대한민국(서울, Supabase 리전 ap-northeast-2) / 계정을 만들거나 저장할 때 / 인터넷 전송"
    assert cells[4] == "삭제·철회·탈퇴 때까지(백업은 7일 뒤 순환 삭제, Supabase Pro 일간 백업, Supabase 정책에 따름)"
    for gone in ("{{SUPABASE_REGION}}", "{{BACKUP_RETENTION_DAYS}}", "{{확인 필요: 법인 명칭·연락처}}"):
        assert gone not in V2_TEXT.split("INSERT INTO", 1)[1]  # 본문(주석 머리 제외)에 남지 않는다


def test_render_privacy_contact_fills_and_unblocks():
    sql = seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=2)
    out = render_privacy_contact(sql, " 가짜책임자 ", "officer@example.invalid")
    assert unfilled_placeholders(out) == [] and out.count("개인정보 보호책임자: 가짜책임자, 문의: officer@example.invalid") == 2
    assert_publishable(out)
    filled = _rows(out.replace("'2026-12-01T00:00:00+00:00'", "'{{EFFECTIVE_AT}}'"))
    assert body_sha256(filled["privacy_policy"]["body"]) != body_sha256(V2_ROWS["privacy_policy"]["body"])  # 해시는 채운 본문 기준
    for name, email in [(None, "officer@example.invalid"), ("가짜책임자", ""), ("", "")]:
        with pytest.raises(ValueError, match="PRIVACY_OFFICER") as ei:
            render_privacy_contact(sql, name, email)
        assert "officer@example.invalid" not in str(ei.value) and "가짜책임자" not in str(ei.value)


def test_v2_seed_substitutes_effective_at_only():
    sql = seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=2)
    assert "{{EFFECTIVE_AT}}" not in sql and sql.count("'2026-12-01T00:00:00+00:00'") == 4
    assert "{{PRIVACY_CONTACT}}" in sql  # 값을 모르는 자리표시는 그대로 둔다
    with pytest.raises(ValueError):
        seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=4)


def test_placeholders_block_remote_publish_but_not_v1():
    sql_v2 = seed_sql(datetime(2026, 12, 1, tzinfo=UTC), version=2)
    left = unfilled_placeholders(sql_v2)
    # Recap 45 ①③④(2026-11-20 사용자 승인) 뒤 남는 자리표시는 ② 연락처뿐이다(env에서 게시 때 채움, render_privacy_contact)
    assert left == ["{{PRIVACY_CONTACT}}"]
    # PRD-17 ⑫(2026-11-20, Recap 58): OpenAI 줄의 법인·연락처·국가·보관 기간은 채웠다. 다른 자리표시가 남아 게시 차단은 그대로다
    assert "{{COUNTRY_OPENAI}}" not in left and "{{확인 필요: 기간}}" not in left
    openai_row = next(line for line in V2_ROWS["privacy_policy"]["body"].splitlines() if line.startswith("| OpenAI"))
    assert "{{" not in openai_row
    assert "OpenAI OpCo, L.L.C." in openai_row and "| 미국 / 질문하거나 사진을 올릴 때마다 / 인터넷 전송 |" in openai_row and "최대 30일" in openai_row
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
        conn.execute(seed_age14_sql(now - timedelta(minutes=2)))  # PRD-17-12 A: 필수 동의 판정에 age_14가 들어간다
    repo = PostgresAccountRepo.from_dsn(LOCAL_PG_DSN)
    a, b = _new_user(LOCAL_PG_DSN), _new_user(LOCAL_PG_DSN)
    for uid, items in ((a, ("terms", "privacy_consent", "sensitive_consent", "age_14")), (b, ("terms", "privacy_consent", "age_14"))):
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
                            "WHERE doc_type <> 'age_14' ORDER BY doc_type, version").fetchall()  # age_14 v1은 별도 시드
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
