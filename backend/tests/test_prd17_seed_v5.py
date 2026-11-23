"""PRD-17 처리방침 v5(사진 판독 OpenAI만 확정·쿠키 7일·카카오 필수 표기·이름 기본값, 2026-11-23) 시험. 원격 DB·네트워크·LLM 호출 0.

1. 정적: v5 = privacy_policy 한 행(requires_reconsent=false), v4와의 본문 차이는 네 곳(2절 줄·3절 OpenAI 줄·3절 Upstage 줄 삭제·1절 로그인 줄·8절 쿠키 문장)뿐.
2. 사진·수탁자는 v3 원문으로 복원(Upstage 0건), 쿠키 7일·72시간, 카카오 필수 표기, 이름 기본값 문장.
3. 표 구조, 렌더링·해시·게시 거부, 로컬 Postgres(`LOCAL_PG_DSN`, 없으면 skip).
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
    SEED_V3_FILE,
    SEED_V4_FILE,
    SEED_V5_FILE,
    PostgresAccountRepo,
    assert_publishable,
    render_privacy_contact,
    schema_sql,
    seed_age14_sql,
    seed_sql,
    unfilled_placeholders,
)

NOW = datetime(2026, 12, 1, tzinfo=UTC)
NAME, EMAIL = "가짜책임자", "officer@example.invalid"
V3 = _rows(SEED_V3_FILE.read_text(encoding="utf-8"))["privacy_policy"]
V4 = _rows(SEED_V4_FILE.read_text(encoding="utf-8"))["privacy_policy"]
V5_TEXT = SEED_V5_FILE.read_text(encoding="utf-8")
V5_ROWS = _rows(V5_TEXT)
V5 = V5_ROWS["privacy_policy"]
CHANGED_PREFIXES = ("질문과 대화 내용은", "| OpenAI(", "| Upstage(", "| 로그인 정보:", "로그인하면 로그인 상태를")


def _diff(a: str, b: str) -> tuple[list[str], list[str]]:
    removed, added = [], []
    for d in difflib.ndiff(a.splitlines(), b.splitlines()):
        if d.startswith("- "):
            removed.append(d[2:])
        elif d.startswith("+ "):
            added.append(d[2:])
    return removed, added


def _line(body: str, start: str) -> str:
    return next(line for line in body.splitlines() if line.startswith(start))


def test_v5_is_single_privacy_policy_row_without_reconsent():
    assert tuple(V5_ROWS) == ("privacy_policy",)
    assert V5["version"] == 5 and V5["title"] == V4["title"]
    assert (V5["required"], V5["requires_reconsent"]) == (False, False)
    assert V5_TEXT.rstrip().endswith("ON CONFLICT (doc_type, version) DO NOTHING;")


def test_v5_differs_from_v4_only_in_the_four_places():
    removed, added = _diff(V4["body"], V5["body"])
    assert all(r.startswith(CHANGED_PREFIXES) for r in removed + added)
    # 지운 줄: 2절·OpenAI·Upstage·로그인 정보·쿠키(5줄). 넣은 줄: 2절·OpenAI·로그인 정보·쿠키(4줄)
    assert len(removed) == 5 and len(added) == 4
    assert [a[:6] for a in added] == [r[:6] for r in removed if not r.startswith("| Upstage(")]


def test_v5_photo_and_processor_text_is_restored_to_v3():
    # 사진 문장·OpenAI 줄은 v3 줄과 한 자도 다르지 않다
    for start in ("질문과 대화 내용은", "| OpenAI("):
        assert _line(V5["body"], start) == _line(V3["body"], start)
    assert "약봉투 사진을 올리면 약 이름을 읽기 위해 사진이 외부 AI 서비스(OpenAI)로 전송되며, 그곳의 보관은 3절과 같습니다." in V5["body"]
    assert "답변 생성, 약봉투 사진에서 약 이름 읽기" in _line(V5["body"], "| OpenAI(")
    assert "Upstage" not in V5["body"] and "upstage" not in V5["body"].lower()


def test_v5_cookie_sentence_is_7_days_and_72_hours():
    c = _line(V5["body"], "로그인하면 로그인 상태를")
    assert c == ("로그인하면 로그인 상태를 유지하기 위한 쿠키(`sb-…-auth-token`)를 사용합니다. 이 쿠키에는 로그인 토큰과 사용자 정보(이메일 포함)가 담기며, "
                 "로그인한 지 7일이 지나거나 3일(72시간) 동안 사용하지 않으면 로그인이 풀리고, 로그아웃하면 이 브라우저에서 삭제됩니다. "
                 "브라우저 설정에서 쿠키를 거부할 수 있으나 로그인이 되지 않을 수 있습니다.")
    assert "400일" not in V5["body"]


def test_v5_login_row_kakao_required_and_name_default():
    row = _line(V5["body"], "| 로그인 정보:")
    assert "Kakao는 닉네임·이메일(필수 동의)" in row and "프로필 사진 주소(선택 동의한 경우)" in row
    assert "Google은 계정 식별자·이메일·이름" in row
    assert "이 중 계정 식별자만 씁니다" not in row
    assert ("Kakao 로그인 닉네임은 본인 프로필의 이름 칸 기본값으로만 불러오며(수정할 수 있고 저장 버튼을 누르기 전에는 서버로 보내지 않습니다), "
            "저장되는 이름은 사용자가 확인해 저장한 이름뿐입니다") in row
    assert len(row.strip().strip("|").split("|")) == 3


def test_v5_only_privacy_contact_placeholder_remains():
    assert re.findall(r"\{\{(?!…)[^}]*\}\}", V5["body"]) == ["{{PRIVACY_CONTACT}}"]
    sql = seed_sql(NOW, version=5)
    assert unfilled_placeholders(sql) == ["{{PRIVACY_CONTACT}}"]
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(sql)


def test_v5_tables_keep_column_structure_for_markdown_renderer():
    lines = V5["body"].splitlines()
    assert lines.count("|---|---|---|---|---|---|") == 1 and lines.count("|---|---|---|") == 1
    rows3 = [ln for ln in lines if ln.startswith(("| OpenAI(", "| Upstage(", "| Supabase("))]
    assert len(rows3) == 2 and all(len(ln.strip().strip("|").split("|")) == 6 for ln in rows3)
    for i, line in enumerate(lines):
        if line.startswith("| ") and i + 1 < len(lines) and lines[i + 1].startswith("|---"):
            cols = len(line.strip().strip("|").split("|"))
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                assert len(lines[j].strip().strip("|").split("|")) == cols and lines[j].rstrip().endswith("|")
                j += 1


def test_render_v5_is_publishable_and_hash_follows_filled_body():
    out = render_privacy_contact(seed_sql(NOW, version=5), NAME, EMAIL)
    assert unfilled_placeholders(out) == []
    assert_publishable(out)
    filled = _rows(out.replace("'2026-12-01T00:00:00+00:00'", "'{{EFFECTIVE_AT}}'"))["privacy_policy"]
    assert filled["body"] == V5["body"].replace("{{PRIVACY_CONTACT}}", f"개인정보 보호책임자: {NAME}\\\n문의: {EMAIL}")
    assert body_sha256(filled["body"]) != body_sha256(V5["body"]) and body_sha256(V5["body"]) != body_sha256(V4["body"])


# --------------------------------------------------------------------------- 로컬 Postgres
LOCAL_PG_DSN = os.environ.get("LOCAL_PG_DSN") or None


@pytest.fixture(scope="module")
def v5_db():
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
        conn.execute(seed_sql(now - timedelta(minutes=5), version=1))
        conn.execute(seed_age14_sql(now - timedelta(minutes=5)))
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    repo = PostgresAccountRepo.from_dsn(LOCAL_PG_DSN)
    asyncio.run(repo.ensure_user(uid))
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        for v, m in ((2, 4), (3, 3), (4, 2)):
            conn.execute(render_privacy_contact(seed_sql(now - timedelta(minutes=m), version=v), NAME, EMAIL))
    asyncio.run(repo.add_consents(
        uid, [ConsentInput("terms", 3, "agree"), ConsentInput("privacy_consent", 2, "agree"), ConsentInput("age_14", 1, "agree")],
        "onboarding"))
    sql5 = render_privacy_contact(seed_sql(now - timedelta(minutes=1), version=5), NAME, EMAIL)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        for _ in range(2):  # 멱등
            conn.execute(sql5)
    try:
        yield {"dsn": LOCAL_PG_DSN, "uid": uid, "repo": repo}
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            conn.execute("DELETE FROM auth.users WHERE id = %s::uuid", (uid,))


def test_pg_current_privacy_policy_is_v5_others_unchanged(v5_db):
    repo = v5_db["repo"]
    cur = {t: asyncio.run(repo.legal_current(t)).version for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent")}
    assert cur == {"terms": 3, "privacy_policy": 5, "privacy_consent": 2, "sensitive_consent": 2}


def test_pg_no_reconsent_after_v5(v5_db):
    states = {s.doc_type: s for s in asyncio.run(consent_states(v5_db["repo"], v5_db["uid"]))}
    assert all(s.needs_reconsent is False for s in states.values())
    assert required_ok(list(states.values()))


def test_pg_v4_body_stays_and_v5_body_has_no_upstage(v5_db):
    repo = v5_db["repo"]
    v4 = asyncio.run(repo.legal_version("privacy_policy", 4))
    v5 = asyncio.run(repo.legal_version("privacy_policy", 5))
    assert "| Upstage(" in v4.body_md and "400일" in v4.body_md  # v4 게시본 불변
    assert "Upstage" not in v5.body_md and "72시간" in v5.body_md
    assert v5.body_sha256 == body_sha256(v5.body_md) and re.fullmatch(r"[0-9a-f]{64}", v5.body_sha256)
    with pytest.raises(psycopg.errors.Error), psycopg.connect(v5_db["dsn"], autocommit=True) as conn:
        conn.execute("UPDATE account.legal_documents SET body_md = 'x' WHERE doc_type = 'privacy_policy' AND version = 4")
