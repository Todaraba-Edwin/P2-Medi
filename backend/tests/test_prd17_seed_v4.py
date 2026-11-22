"""PRD-17 처리방침 v4(사진 판독 제공자 Upstage 전환 고지, BE-14-09 A, 2026-11-22) 시험. 원격 DB·네트워크·LLM 호출 0.

1. 정적: v4 = privacy_policy 한 행(requires_reconsent=false, ★A 잠정), v3와의 본문 차이는 세 곳(2절 마지막 문장·3절 OpenAI 줄·3절 Upstage 줄)뿐.
2. 정직성: Upstage 처리 국가를 "확인하지 못했습니다"로 쓰고, 요금제 미확인 한계를 보유·이용 칸에 쓴다. 자리표시는 {{PRIVACY_CONTACT}}뿐.
3. 표 구조: 3절 표 6열, 1절 표 3열(프런트 Markdown 표 렌더 호환: 파이프 줄 수·열 수·칸 안 파이프 없음).
4. 렌더링·해시·게시 거부, 로컬 Postgres(`LOCAL_PG_DSN`, 없으면 skip): v3 동의자 needs_reconsent=false, 최신판 privacy_policy v4, v3 본문 불변.
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
V4_TEXT = SEED_V4_FILE.read_text(encoding="utf-8")
V4_ROWS = _rows(V4_TEXT)
V4 = V4_ROWS["privacy_policy"]


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


def test_v4_is_single_privacy_policy_row_without_reconsent():
    assert tuple(V4_ROWS) == ("privacy_policy",)
    assert V4["version"] == 4 and V4["title"] == V3["title"]
    assert (V4["required"], V4["requires_reconsent"]) == (False, False)  # ★A 잠정: 재동의 없음(고지 문서)
    assert V4_TEXT.rstrip().endswith("ON CONFLICT (doc_type, version) DO NOTHING;")


def test_v4_differs_from_v3_only_in_three_places():
    removed, added = _diff(V3["body"], V4["body"])
    # 지운 줄: 2절 한 줄 + OpenAI 줄. 넣은 줄: 2절 한 줄 + OpenAI 줄 + Upstage 줄
    assert len(removed) == 2 and len(added) == 3
    assert removed[0].startswith("질문과 대화 내용은") and added[0].startswith("질문과 대화 내용은")
    assert removed[1].startswith("| OpenAI(") and added[1].startswith("| OpenAI(") and added[2].startswith("| Upstage(")
    # 2절 줄: 마지막 문장만 다르다
    old, new = removed[0], added[0]
    cut = old.index("약봉투 사진을 올리면")
    assert new.startswith(old[:cut]) and new[cut:] != old[cut:]
    assert "외부 AI 서비스(Upstage)로 전송" in new[cut:] and "OpenAI로 전송될 수 있습니다" in new[cut:]
    # 3절 OpenAI 줄: 사진 문구가 없고 법인·보관 칸은 그대로
    o_old, o_new = removed[1].strip(), added[1].strip()
    assert "사진" in o_old and "사진" not in o_new and "약봉투" not in o_new
    cells_old, cells_new = o_old.strip("|").split(" | "), o_new.strip("|").split(" | ")
    assert cells_old[0] == cells_new[0] and cells_old[4] == cells_new[4]
    assert cells_new[1].strip() == "답변 생성"
    # 바뀐 줄만 되돌리면 v3와 한 자도 다르지 않다
    restored = V4["body"].replace(added[0], removed[0]).replace(added[1] + "\n" + added[2], removed[1])
    assert restored == V3["body"]


def test_v4_upstage_row_is_honest_about_country_and_plan():
    row = _line(V4["body"], "| Upstage(")
    cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
    assert len(cells) == 6
    assert "Upstage Co., Ltd." in cells[0] and "infosec@upstage.ai" in cells[0]
    country = cells[3]
    assert "확인하지 못했습니다" in country and "글로벌 엔드포인트" in country and "국외에서 처리될 수 있습니다" in country
    assert not country.startswith(("대한민국 /", "대한민국("))  # 처리 국가를 대한민국으로 단정하지 않는다
    assert country.count(" / ") == 2 and country.endswith("사진을 올릴 때마다 / 인터넷 전송")
    retention = cells[4]
    assert "저장하지 않습니다" in retention and "요금제를 확인하지 못했으며" in retention and "모델 학습에 쓰지 않고" in retention
    assert "직접 입력할 수 있습니다" in cells[5]


def test_v4_only_privacy_contact_placeholder_remains():
    assert "확인 필요" not in V4["body"]
    sql = seed_sql(NOW, version=4)
    assert unfilled_placeholders(sql) == ["{{PRIVACY_CONTACT}}"]
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(sql)


def test_v4_tables_keep_column_structure_for_markdown_renderer():
    lines = V4["body"].splitlines()
    tables = 0
    for i, line in enumerate(lines):
        if not (line.startswith("| ") and i + 1 < len(lines) and lines[i + 1].startswith("|---")):
            continue
        tables += 1
        cols = len(line.strip().strip("|").split("|"))
        j, n = i + 2, 0
        while j < len(lines) and lines[j].startswith("|"):
            assert len(lines[j].strip().strip("|").split("|")) == cols, lines[j][:40]  # 칸 안에 파이프 없음
            assert lines[j].rstrip().endswith("|")
            j, n = j + 1, n + 1
        assert n >= 1
    assert tables == 2
    assert lines.count("|---|---|---|---|---|---|") == 1 and lines.count("|---|---|---|") == 1
    rows3 = [ln for ln in lines if ln.startswith(("| OpenAI(", "| Upstage(", "| Supabase("))]
    assert len(rows3) == 3 and all(len(ln.strip().strip("|").split("|")) == 6 for ln in rows3)


def test_render_v4_is_publishable_and_hash_follows_filled_body():
    out = render_privacy_contact(seed_sql(NOW, version=4), NAME, EMAIL)
    assert unfilled_placeholders(out) == []
    assert_publishable(out)
    filled = _rows(out.replace("'2026-12-01T00:00:00+00:00'", "'{{EFFECTIVE_AT}}'"))["privacy_policy"]
    assert filled["body"] == V4["body"].replace("{{PRIVACY_CONTACT}}", f"개인정보 보호책임자: {NAME}\\\n문의: {EMAIL}")
    assert body_sha256(filled["body"]) != body_sha256(V4["body"]) and body_sha256(V4["body"]) != body_sha256(V3["body"])


# --------------------------------------------------------------------------- 로컬 Postgres
LOCAL_PG_DSN = os.environ.get("LOCAL_PG_DSN") or None


@pytest.fixture(scope="module")
def v4_db():
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
        conn.execute(seed_sql(now - timedelta(minutes=4), version=1))
        conn.execute(seed_age14_sql(now - timedelta(minutes=4)))
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    repo = PostgresAccountRepo.from_dsn(LOCAL_PG_DSN)
    asyncio.run(repo.ensure_user(uid))
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute(render_privacy_contact(seed_sql(now - timedelta(minutes=3), version=2), NAME, EMAIL))
        conn.execute(render_privacy_contact(seed_sql(now - timedelta(minutes=2), version=3), NAME, EMAIL))
    asyncio.run(repo.add_consents(
        uid, [ConsentInput("terms", 3, "agree"), ConsentInput("privacy_consent", 2, "agree"), ConsentInput("age_14", 1, "agree")],
        "onboarding"))
    sql4 = render_privacy_contact(seed_sql(now - timedelta(minutes=1), version=4), NAME, EMAIL)
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        for _ in range(2):  # 멱등
            conn.execute(sql4)
    try:
        yield {"dsn": LOCAL_PG_DSN, "uid": uid, "repo": repo}
    finally:
        with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS account CASCADE")
            conn.execute("DELETE FROM auth.users WHERE id = %s::uuid", (uid,))


def test_pg_current_privacy_policy_is_v4_others_unchanged(v4_db):
    repo = v4_db["repo"]
    cur = {t: asyncio.run(repo.legal_current(t)).version for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent")}
    assert cur == {"terms": 3, "privacy_policy": 4, "privacy_consent": 2, "sensitive_consent": 2}


def test_pg_v3_consenter_needs_no_reconsent_after_v4(v4_db):
    states = {s.doc_type: s for s in asyncio.run(consent_states(v4_db["repo"], v4_db["uid"]))}
    assert all(s.needs_reconsent is False for s in states.values())
    assert (states["terms"].agreed_version, states["terms"].current_version) == (3, 3)
    assert required_ok(list(states.values()))


def test_pg_v3_privacy_policy_body_stays_and_v4_body_has_upstage(v4_db):
    repo = v4_db["repo"]
    v3 = asyncio.run(repo.legal_version("privacy_policy", 3))
    v4 = asyncio.run(repo.legal_version("privacy_policy", 4))
    assert "| Upstage(" not in v3.body_md and "외부 AI 서비스(OpenAI)로 전송되며" in v3.body_md
    assert "| Upstage(" in v4.body_md and "확인하지 못했습니다" in v4.body_md
    assert v4.body_sha256 == body_sha256(v4.body_md) and re.fullmatch(r"[0-9a-f]{64}", v4.body_sha256)
    with pytest.raises(psycopg.errors.Error), psycopg.connect(v4_db["dsn"], autocommit=True) as conn:
        conn.execute("UPDATE account.legal_documents SET body_md = 'x' WHERE doc_type = 'privacy_policy' AND version = 3")
