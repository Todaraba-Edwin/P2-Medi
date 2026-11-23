"""PRD-17-22~25(2026-11-23) 게스트판 이용약관 terms_guest·처리방침 v6 시험. 원격 DB·네트워크·LLM 호출 0.

- 22 A: terms_guest는 별도 문서 종류(GET /legal 읽기만, 게스트 허용). 23 A: v6 = v5 본문 + 게스트 안내 절 하나(다른 글자 불변).
- 24 A: 연락처는 {{PRIVACY_CONTACT}} 자리표시자 그대로. 25 B: 게스트판에 "책임의 한계" 절을 넣지 않는다.
- 동의 기록 로직에는 terms_guest를 넣지 않는다(고지·열람용): CONSENT_DOC_TYPES·POST /consents.
"""

from __future__ import annotations

import difflib
import re
from datetime import UTC, datetime

import pytest
from tests.test_be11_account_api import NOW, UID_A, UID_B, Env, _doc, _docs, _err
from tests.test_prd17_seed_v2 import _rows

from app.db.account_repo import CONSENT_DOC_TYPES, DOC_TYPES, InMemoryAccountRepo
from app.db.account_repo_pg import (
    MIGRATE_GUEST_ENUM_FILE,
    SCHEMA_FILE,
    SEED_GUEST_FILE,
    SEED_V3_FILE,
    SEED_V5_FILE,
    SEED_V6_FILE,
    assert_publishable,
    migrate_guest_enum_sql,
    seed_guest_sql,
    seed_sql,
    unfilled_placeholders,
)

EFF = datetime(2026, 12, 1, tzinfo=UTC)
GUEST_TEXT = SEED_GUEST_FILE.read_text(encoding="utf-8")
GUEST = _rows(GUEST_TEXT)["terms_guest"]
V5_TEXT = SEED_V5_FILE.read_text(encoding="utf-8")
V5 = _rows(V5_TEXT)["privacy_policy"]
V6_TEXT = SEED_V6_FILE.read_text(encoding="utf-8")
V6 = _rows(V6_TEXT)["privacy_policy"]


# --------------------------------------------------------------------------- 시드(정적)
def test_guest_seed_is_single_non_consent_row():
    assert list(_rows(GUEST_TEXT)) == ["terms_guest"]
    assert (GUEST["version"], GUEST["required"], GUEST["requires_reconsent"]) == (1, False, False)
    assert GUEST_TEXT.rstrip().endswith("ON CONFLICT (doc_type, version) DO NOTHING;")
    assert "초안·법률 검토 전" in GUEST["body"]  # 프런트 표지(LEGAL_NOT_REVIEWED_TAG)와 같은 문구


def _sections(body: str) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in re.finditer(r"## (\d)\. .*?(?=\n\n## |\Z)", body, re.S)}


def test_guest_policy_sections_identical_to_member_v3_and_only_member_parts_differ():
    member = _rows(SEED_V3_FILE.read_text(encoding="utf-8"))["terms"]["body"]
    ms, gs = _sections(member), _sections(GUEST["body"])
    assert gs["1"] == ms["1"] and gs["3"] == ms["3"]  # 서비스의 성격·주의(119·약사 확인)는 한 글자도 다르지 않다
    assert gs["5"] == ms["6"].replace("## 6.", "## 5.")  # 문의(번호만 변경)
    assert gs["4"] == "## 4. 약관의 변경\n약관을 바꾸면 버전과 시행일을 표시합니다."
    assert ms["5"].startswith(gs["4"].replace("## 4.", "## 5."))  # 재동의 문장만 뺐다
    assert "계정 해지" not in GUEST["body"] and "다시 동의" not in GUEST["body"]
    # 2절 문장은 모두 회원판 v3 2절 또는 처리방침 v5 2절에 있다(새 문장 없음, 보관 참조만 "개인정보 처리방침 3절")
    policy2 = re.search(r"## 2\. 처리하지 않는 항목\n(.*?)\n\n## 3", V5["body"], re.S).group(1)
    allowed = ms["2"] + " " + policy2
    for sent in re.split(r"(?<=다\.) ", gs["2"].split("\n", 1)[1]):
        assert sent.replace("개인정보 처리방침 3절", "3절") in allowed, sent
    assert "책임의 한계" not in GUEST["body"] and "보증하지" not in GUEST["body"] and "답변에 표시" not in GUEST["body"]  # PRD-17-25 B


def test_guest_contact_is_placeholder_only():
    assert unfilled_placeholders(GUEST_TEXT.replace("{{EFFECTIVE_AT}}", "x")) == ["{{PRIVACY_CONTACT}}"]
    assert "@" not in GUEST["body"]
    with pytest.raises(ValueError, match="PRIVACY_CONTACT"):
        assert_publishable(seed_guest_sql(EFF))  # 값이 없으면 게시 거부(24 A)


def test_v6_equals_v5_plus_one_guest_section_nothing_else():
    assert V6["version"] == 6 and V6["required"] is False and V6["requires_reconsent"] is False
    diff = list(difflib.ndiff(V5["body"].splitlines(), V6["body"].splitlines()))
    assert [d for d in diff if d.startswith(("- ", "? "))] == []  # v5의 글자는 하나도 빠지거나 바뀌지 않았다
    added = [d[2:] for d in diff if d.startswith("+ ")]
    assert added[0] == "## 게스트(로그인하지 않음) 안내" and added[-1] == "" and len(added) == 3
    assert "아무것도 저장하지 않습니다" in added[1] and "쿠키" not in added[1]  # v5 2절 문장, 새 쿠키 문장 없음
    assert V6["title"] == V5["title"] and "{{PRIVACY_CONTACT}}" in V6["body"]
    assert "원문 승인 2026-11-19" in V6["body"] and "초안·법률 검토 전" in V6["body"]


def test_v6_seed_text_apart_from_header_matches_v5_seed():
    a = V5_TEXT.split("INSERT INTO", 1)[1].splitlines()
    b = V6_TEXT.split("INSERT INTO", 1)[1].splitlines()
    changed = [d for d in difflib.ndiff(a, b) if d[:2] in ("- ", "+ ")]
    assert [d for d in changed if d.startswith("- ")] == ["- ('privacy_policy', 5, '개인정보 처리방침(초안)', $md$"]
    assert len([d for d in changed if d.startswith("+ ")]) == 4  # v6 행 머리 + 게스트 절 3줄(제목·문장·빈 줄)
    filled = seed_sql(EFF, 6)
    assert "{{EFFECTIVE_AT}}" not in filled and "'2026-12-01T00:00:00+00:00')" in filled


# --------------------------------------------------------------------------- 열거형 마이그레이션
def test_enum_migration_is_idempotent_and_standalone():
    stmts = [ln for ln in migrate_guest_enum_sql().splitlines() if ln.strip() and not ln.lstrip().startswith("--")]
    assert stmts == ["ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'terms_guest';"]
    assert MIGRATE_GUEST_ENUM_FILE.name == "migrate_doc_type_terms_guest.sql"


def test_schema_file_knows_terms_guest_for_new_and_existing_installs():
    s = SCHEMA_FILE.read_text(encoding="utf-8")
    assert "'age_14', 'terms_guest');" in s  # 신규 설치(CREATE TYPE)
    assert "ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'terms_guest';" in s  # 이미 있는 열거형


# --------------------------------------------------------------------------- 코드 값 집합·API
def test_terms_guest_is_doc_type_but_not_consent_type():
    assert "terms_guest" in DOC_TYPES and "terms_guest" not in CONSENT_DOC_TYPES


def _env(with_guest: bool = True) -> Env:
    docs = [*_docs(), _doc("terms_guest", required=False)] if with_guest else _docs()
    return Env(InMemoryAccountRepo(docs, clock=lambda: NOW, auth_users={UID_A, UID_B}))


def test_get_legal_terms_guest_for_guest():
    env = _env()
    r = env.req("GET", "/legal/terms_guest", token=None)
    assert r.status_code == 200
    body = r.json()
    assert (body["doc_type"], body["required"], body["legal_review"]) == ("terms_guest", False, "not_reviewed")
    assert env.verifier.calls == 0  # 게스트 읽기는 토큰을 보지 않는다
    assert env.req("GET", "/legal/terms_guest?version=1", None).status_code == 200


def test_terms_guest_absent_is_404_not_500():
    assert _err(_env(with_guest=False).req("GET", "/legal/terms_guest", None)) == (404, "NOT_FOUND", [])


def test_consent_rejects_terms_guest():
    env = _env()
    assert env.req("GET", "/me").status_code == 200
    status, code, _ = _err(env.consent(("terms_guest", 1, "agree")))
    assert (status, code) == (422, "INVALID_REQUEST")
    assert asyncio_latest(env) == {}  # 아무 동의도 저장되지 않았다


def asyncio_latest(env: Env) -> dict:
    import asyncio

    return asyncio.run(env.repo.latest_consents(UID_A))


def test_openapi_legal_has_terms_guest_but_consent_item_does_not():
    spec = _env().app.openapi()
    legal_param = next(p for p in spec["paths"]["/legal/{doc_type}"]["get"]["parameters"] if p["name"] == "doc_type")
    assert "terms_guest" in legal_param["schema"]["enum"]
    assert "terms_guest" in str(spec["components"]["schemas"]["LegalDocumentOut"]["properties"]["doc_type"])
    assert "terms_guest" not in str(spec["components"]["schemas"]["ConsentItem"]["properties"]["doc_type"])


def test_plan_lists_new_steps_read_only_and_apply_gate_unchanged(monkeypatch):
    from tests.test_be11_account_migrate import (
        FAKE_REMOTE,
        Conn,
        Factory,
        applied_answers,
        m,  # scripts/be11_account_migrate(경로 설정은 그 시험 모듈이 한다)
        writes,
    )

    monkeypatch.setenv(m.DSN_ENV, FAKE_REMOTE)
    conn = Conn(applied_answers(legal=[], current=[], enum=("terms", "privacy_policy", "privacy_consent", "sensitive_consent", "age_14")))
    plan = m.main(["plan"], connect_fn=Factory(conn), log=lambda s: None, contact=(None, None))["plan"]
    assert [s["step"] for s in plan["steps"]][-5:] == ["8 enum terms_guest", "9 seed terms_guest v1", "10 seed v6", "11 migrate profiles.avatar_color",
                                                              "12 migrate app_users.default_target"]
    assert {"terms_guest v1", "privacy_policy v6"} <= set(plan["seed_rows_to_insert"])
    assert plan["publishable"] is False  # 보호책임자 값이 없으면 자리표시가 남는다
    assert conn.read_only and writes(conn) == [] and conn.commits == 0
    with pytest.raises(m.Refused, match="--yes"):  # apply 안전장치는 그대로
        m.main(["apply", "--effective-at", "2026-11-21T00:00:00+09:00"], connect_fn=Factory(conn), log=lambda s: None)
