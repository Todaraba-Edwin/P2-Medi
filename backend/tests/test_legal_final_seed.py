"""약관·처리방침 최종안 반영 시드(seed_legal_final.sql, 2026-11-23 사용자 지시) 시험. 원격 DB·네트워크·LLM 호출 0.

- 정적: 본문 차이 = 제거한 안내 인용문 줄(+뒤 빈 줄 하나)뿐, 제목의 "(초안)"만 제거, required 유지, requires_reconsent false,
  legal_review를 시드가 건드리지 않음(기본값 not_reviewed), 자리표시자 유지, age_14는 새 버전 없음.
- 재동의: 기존 동의(직전 판)가 새 판에서도 유효(needs_reconsent False).
- 마이그레이션 단계 12: plan·verify(be11 시험이 대부분 담당, 여기서는 시드 키·게시 거부).
- 로컬 Postgres(LOCAL_PG_DSN이 로컬 주소일 때만): 전체 단계 적용·재실행·현재 판 조회·불변 트리거.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from tests.test_be11_account_migrate import FAKE_EMAIL, FAKE_NAME, m
from tests.test_prd17_seed_v2 import AUTH_STUB, _rows

from app.api.account import consent_states
from app.db.account_repo import ConsentInput, InMemoryAccountRepo, LegalDoc, body_sha256
from app.db.account_repo_pg import (
    DB_DIR,
    SEED_AGE14_FILE,
    SEED_FINAL_FILE,
    SEED_GUEST_FILE,
    SEED_V2_FILE,
    SEED_V3_FILE,
    SEED_V6_FILE,
    PostgresAccountRepo,
    assert_publishable,
    render_privacy_contact,
    seed_final_sql,
    unfilled_placeholders,
)

EFF = datetime(2026, 12, 1, tzinfo=UTC)
FINAL_TEXT = SEED_FINAL_FILE.read_text(encoding="utf-8")
FINAL = _rows(FINAL_TEXT)

# 문서 종류 -> (직전 최신 시드 파일, 직전 버전, 새 버전, 새 제목, 제거한 줄 전문)
APPROVAL = "> 원문 승인 2026-11-19(사용자), `{{…}}` 값은 사실 확인 뒤 채움."
HEAD = "> 초안·법률 검토 전입니다. 실제 공개·상용 전에 법률 검토가 필요합니다."
SENSITIVE_SENTENCE = "건강에 관한 정보는 법에 따라 다른 동의와 별도로 동의를 받아야 하는 정보(민감정보)로 보여 별도 선택 동의를 받습니다."
SPEC = {
    "terms": (SEED_V3_FILE, 3, 4, "Can I PPiyak 이용약관", [HEAD, APPROVAL]),
    "privacy_policy": (SEED_V6_FILE, 6, 7, "개인정보 처리방침", [HEAD, APPROVAL]),
    "privacy_consent": (SEED_V2_FILE, 2, 3, "개인정보 수집·이용 동의(필수)", ["> 초안·법률 검토 전입니다.", APPROVAL]),
    "sensitive_consent": (SEED_V2_FILE, 2, 3, "건강 정보(민감정보) 처리 동의(선택)", [
        "> 초안·법률 검토 전입니다. 건강에 관한 정보는 법에 따라 다른 동의와 별도로 동의를 받아야 하는 정보(민감정보)로 보여 "
        "별도 선택 동의를 받습니다. 구체적인 적용은 법률 검토가 필요합니다.", APPROVAL]),
    "terms_guest": (SEED_GUEST_FILE, 1, 2, "Can I PPiyak 게스트판 이용약관", [HEAD]),
}


def _source(doc_type: str) -> dict:
    f, v, *_ = SPEC[doc_type]
    row = _rows(f.read_text(encoding="utf-8"))[doc_type]
    assert row["version"] == v
    return row


# --------------------------------------------------------------------------- 정적
def test_final_seed_has_exactly_the_five_new_versions_and_no_age14():
    assert list(FINAL) == list(SPEC)
    assert {t: r["version"] for t, r in FINAL.items()} == {t: s[2] for t, s in SPEC.items()}
    assert "age_14" not in FINAL_TEXT.split("INSERT INTO", 1)[1]  # 본문·제목에 안내 문구가 없어 새 버전을 만들지 않는다
    assert "초안" not in SEED_AGE14_FILE.read_text(encoding="utf-8").split("INSERT INTO", 1)[1]
    assert FINAL_TEXT.rstrip().endswith("ON CONFLICT (doc_type, version) DO NOTHING;")


@pytest.mark.parametrize("doc_type", list(SPEC))
def test_body_differs_from_previous_latest_only_by_removed_notice_lines(doc_type):
    src, new = _source(doc_type), FINAL[doc_type]
    removed_lines = SPEC[doc_type][4]
    new_lines = new["body"].splitlines()
    if doc_type == "sensitive_consent":
        # 사용자 답 2026-11-23 A: 첫 줄에서 초안 문구 두 문장만 빼고 설명 문장은 인용 표기 없는 일반 문장으로 남긴다
        first = removed_lines[0]
        assert first == f"> 초안·법률 검토 전입니다. {SENSITIVE_SENTENCE} 구체적인 적용은 법률 검토가 필요합니다."
        assert src["body"].splitlines() == ["", first, removed_lines[1], *new_lines[2:]]
        assert new_lines[:3] == ["", SENSITIVE_SENTENCE, ""]  # 문장 뒤 빈 줄(뒤따르는 목록과 분리)
        assert new["body"].replace(SENSITIVE_SENTENCE, "").count("초안") == 0
        diff = list(difflib.ndiff(src["body"].splitlines(), new_lines))
        assert [d[2:] for d in diff if d.startswith("+ ")] == [SENSITIVE_SENTENCE]
        return
    diff = list(difflib.ndiff(src["body"].splitlines(), new_lines))
    assert [d for d in diff if d.startswith(("+ ", "? "))] == []  # 더해지거나 바뀐 글자 없음
    # 직전 본문 = 맨 앞 빈 줄 + 제거한 안내 줄들 + 빈 줄 하나 + 새 본문의 나머지(한 글자도 다르지 않음)
    assert src["body"].splitlines() == ["", *removed_lines, "", *new_lines[1:]]
    assert new_lines[0] == ""
    assert new["body"].startswith("\n") and not new["body"].startswith("\n\n") and new["body"].endswith("\n")


@pytest.mark.parametrize("doc_type", list(SPEC))
def test_no_user_visible_draft_or_review_wording_left(doc_type):
    body, title = FINAL[doc_type]["body"], FINAL[doc_type]["title"]
    assert title == SPEC[doc_type][3]
    for word in ("초안", "법률 검토", "원문 승인", "{{…}}", "사실 확인 뒤"):
        assert word not in body and word not in title, (doc_type, word)
    assert "$md$" not in body


@pytest.mark.parametrize("doc_type", list(SPEC))
def test_flags_required_kept_reconsent_false(doc_type):
    assert FINAL[doc_type]["required"] is _source(doc_type)["required"]
    assert FINAL[doc_type]["requires_reconsent"] is False


def test_seed_does_not_touch_legal_review_column():
    code = "\n".join(ln for ln in FINAL_TEXT.splitlines() if not ln.lstrip().startswith("--"))
    assert "legal_review" not in code and "reviewed" not in code  # 열 기본값 not_reviewed 그대로(검토 완료로 속이지 않는다)
    assert "(doc_type, version, title, body_md, required, requires_reconsent, status, effective_at)" in code


def test_placeholders_kept_and_publish_blocked_until_contact_filled():
    assert unfilled_placeholders(FINAL_TEXT.replace("{{EFFECTIVE_AT}}", "x")) == ["{{PRIVACY_CONTACT}}"]
    assert FINAL_TEXT.count("{{EFFECTIVE_AT}}") == 5
    # 연락처 줄은 직전 판과 같은 개수(terms·privacy_policy·terms_guest)
    assert [t for t, r in FINAL.items() if "{{PRIVACY_CONTACT}}" in r["body"]] == ["terms", "privacy_policy", "terms_guest"]
    sql = seed_final_sql(EFF)
    assert "{{EFFECTIVE_AT}}" not in sql and sql.count("'2026-12-01T00:00:00+00:00'") == 5
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(sql)
    assert_publishable(render_privacy_contact(sql, FAKE_NAME, FAKE_EMAIL))
    with pytest.raises(ValueError):
        seed_final_sql(datetime(2026, 12, 1))  # 시간대 없음


def test_original_seed_files_untouched_by_this_work():
    assert (DB_DIR / "seed_legal_v6.sql").read_text(encoding="utf-8").count("초안·법률 검토 전입니다.") == 1  # 게시본 원문 보존


# --------------------------------------------------------------------------- 재동의 영향
def _legal(doc_type: str, version: int, row: dict, effective: datetime) -> LegalDoc:
    return LegalDoc(doc_type, version, row["title"], row["body"], row["required"], row["requires_reconsent"], effective,
                    "not_reviewed", body_sha256(row["body"]))


@pytest.mark.parametrize("doc_type", ["terms", "privacy_consent", "sensitive_consent"])
def test_existing_consent_stays_valid_on_final_version(doc_type):
    _, v_old, v_new, *_ = SPEC[doc_type]
    old = _legal(doc_type, v_old, _source(doc_type), EFF - timedelta(days=2))
    new = _legal(doc_type, v_new, FINAL[doc_type], EFF - timedelta(days=1))
    repo = InMemoryAccountRepo([old, new], clock=lambda: EFF, auth_users={"u1"})
    asyncio.run(repo.ensure_user("u1"))
    asyncio.run(repo.add_consents("u1", [ConsentInput(doc_type, v_old, "agree")], "onboarding"))
    (state,) = asyncio.run(consent_states(repo, "u1"))
    assert (state.agreed_version, state.current_version) == (v_old, v_new)
    assert state.needs_consent is False and state.needs_reconsent is False  # 직전 판 동의가 그대로 유효


# --------------------------------------------------------------------------- 마이그레이션 단계 12(로컬, 연결 0)
def test_step_12_is_last_seed_with_five_keys_and_blocks_publish_without_contact():
    steps = m.build_steps(EFF)
    last = steps[-1]
    assert last.name == "12 seed final legal docs" and last.kind == "seed" and last.source == SEED_FINAL_FILE
    assert last.keys == [("terms", 4), ("privacy_policy", 7), ("privacy_consent", 3), ("sensitive_consent", 3), ("terms_guest", 2)]
    assert last.placeholders == ["{{PRIVACY_CONTACT}}"]
    with pytest.raises(m.Refused, match="seed_legal_final.sql"):
        m.check_publishable(steps)
    filled = m.build_steps(EFF, (FAKE_NAME, FAKE_EMAIL))[-1]
    assert filled.placeholders == [] and filled.masked == (FAKE_NAME, FAKE_EMAIL)


# --------------------------------------------------------------------------- 로컬 Postgres 전체 적용
LOCAL_PG_DSN = os.environ.get("LOCAL_PG_DSN") or None


@pytest.fixture(scope="module")
def local_dsn():
    if not LOCAL_PG_DSN:
        pytest.skip("환경변수 LOCAL_PG_DSN 없음(BE-11-14 A 로컬 시험)")
    host = str(psycopg.conninfo.conninfo_to_dict(LOCAL_PG_DSN).get("host") or "/")
    if not host.startswith(("localhost", "127.0.0.1", "::1", "/")):
        pytest.skip("로컬 주소가 아니면 돌지 않는다(원격 쓰기 금지)")
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")  # 로컬 시험 DB에서만
        conn.execute(AUTH_STUB)
    yield LOCAL_PG_DSN
    with psycopg.connect(LOCAL_PG_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS account CASCADE")


def _apply(dsn: str) -> dict:
    return m.main(["apply", "--yes", "--effective-at", (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "--local-dsn", dsn],
                  log=lambda s: None, contact=(FAKE_NAME, FAKE_EMAIL))


def test_pg_apply_all_steps_twice_then_verify_and_current_versions(local_dsn):
    first = _apply(local_dsn)["apply"]
    assert first["12 seed final legal docs"]["inserted"] == 5
    second = _apply(local_dsn)["apply"]  # 재실행 안전: 행이 늘지 않는다
    assert second["12 seed final legal docs"]["inserted"] == 0
    out = m.main(["verify", "--local-dsn", local_dsn], log=lambda s: None, contact=(FAKE_NAME, FAKE_EMAIL))["verify"]
    assert out["ok"] is True, out["checks"]
    repo = PostgresAccountRepo.from_dsn(local_dsn)
    cur = {t: asyncio.run(repo.legal_current(t)) for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "terms_guest", "age_14")}
    assert {t: d.version for t, d in cur.items()} == {"terms": 4, "privacy_policy": 7, "privacy_consent": 3, "sensitive_consent": 3,
                                                       "terms_guest": 2, "age_14": 1}
    assert all(d.legal_review == "not_reviewed" for d in cur.values())  # 검토 완료로 바뀌지 않았다
    assert cur["terms"].required and cur["privacy_consent"].required and not cur["sensitive_consent"].required
    for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "terms_guest"):
        assert "초안" not in cur[t].title and "초안" not in cur[t].body_md and "{{" not in cur[t].body_md, t
    assert "{{PRIVACY_CONTACT}}" not in cur["terms"].body_md and FAKE_EMAIL in cur["terms"].body_md
    assert all(d.requires_reconsent is False for t, d in cur.items() if t != "age_14")


def test_pg_v2_consenter_not_asked_to_reconsent_and_final_rows_frozen(local_dsn):
    uid = str(uuid.uuid4())
    with psycopg.connect(local_dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id) VALUES (%s)", (uid,))
    try:
        repo = PostgresAccountRepo.from_dsn(local_dsn)
        asyncio.run(repo.ensure_user(uid))
        items = [ConsentInput("terms", 3, "agree"), ConsentInput("privacy_consent", 2, "agree"),
                 ConsentInput("sensitive_consent", 2, "agree"), ConsentInput("age_14", 1, "agree")]
        asyncio.run(repo.add_consents(uid, items, "onboarding"))
        states = {s.doc_type: s for s in asyncio.run(consent_states(repo, uid))}
        assert all(not s.needs_reconsent and not s.needs_consent for s in states.values()), states
        assert (states["terms"].current_version, states["privacy_consent"].current_version) == (4, 3)
        with pytest.raises(psycopg.errors.RaiseException, match="DOCUMENT_FROZEN"), psycopg.connect(local_dsn) as conn:
            conn.execute("UPDATE account.legal_documents SET body_md = body_md || 'x' WHERE doc_type = 'terms' AND version = 4")
    finally:
        with psycopg.connect(local_dsn, autocommit=True) as conn:
            conn.execute("DELETE FROM auth.users WHERE id = %s::uuid", (uid,))
