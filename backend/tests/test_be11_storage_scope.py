"""BE-11 저장 범위 점검(2026-11-22, BE-11 §2 완료 조건 "저장 항목이 동의한 프로필과 로그인 최소 정보뿐", "질문·대화 내용이 DB에 남지 않음").

원격 DB·네트워크 호출 0. `schema_account.sql`의 열 이름을 허용 목록과 정확히 대조한다(열을 더하면 이 시험이 실패해 검토를 강제한다).
로그 쪽은 `test_be11_account_api.py::test_no_tokens_or_health_values_in_logs_or_error_bodies`·`test_chat_does_not_touch_account_repo_or_verifier`,
`/chat` 경로가 계정 저장소를 import하지 않음은 아래에서 정적으로 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.db.account_repo_pg import schema_sql

APP_API = Path(__file__).resolve().parents[1] / "app" / "api"

NO_COMMENTS = "\n".join(line.split("--", 1)[0] for line in schema_sql().splitlines())
_NOT_COLUMN = {"CHECK", "FOREIGN", "UNIQUE", "PRIMARY", "CONSTRAINT"}

# 허용 열(설계 4장·BE-11 결정 01·02·03·05·07·08·22 A). 질문·대화·이름·이메일·연락처 열은 없다
ALLOWED = {
    "app_users": {"user_id", "signup_provider", "onboarding_step", "onboarding_completed_at", "created_at", "updated_at"},
    "profiles": {"profile_id", "user_id", "relation", "label", "age_band", "pregnancy_status", "sort_order", "created_at", "updated_at", "sex",
                 "avatar_color"},  # avatar_color: 병아리 배경색 8색(2026-11-23 사용자 결정, 건강 정보 아님)
    "profile_medications": {"medication_id", "profile_id", "user_id", "input_text", "item_seq", "confirmed_at", "created_at"},
    "legal_documents": {"document_id", "doc_type", "version", "title", "body_md", "required", "requires_reconsent", "status", "effective_at",
                        "legal_review", "body_sha256", "created_at"},
    "user_consents": {"consent_id", "user_id", "doc_type", "doc_version", "action", "channel", "acted_at"},
    "deletion_log": {"deleted_on", "accounts", "profiles", "medications", "consents"},
}
FORBIDDEN_WORDS = ("question", "message", "conversation", "chat", "prompt", "answer", "content", "email", "phone", "name", "ip_", "address")


def _columns() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS account\.(\w+) \((.*?)\n\);", NO_COMMENTS, re.S):
        cols = set()
        for line in m.group(2).splitlines():
            c = re.match(r"^ {4}(\w+)\s+\S", line)
            if c and c.group(1).upper() not in _NOT_COLUMN:
                cols.add(c.group(1))
        out[m.group(1)] = cols
    for m in re.finditer(r"ALTER TABLE account\.(\w+) ADD COLUMN IF NOT EXISTS (\w+)", NO_COMMENTS):
        out[m.group(1)].add(m.group(2))
    return out


def test_tables_and_columns_match_allowed_list_exactly():
    got = _columns()
    assert set(got) == set(ALLOWED)
    for table, cols in got.items():
        assert cols == ALLOWED[table], table


def test_no_column_can_hold_question_conversation_or_contact_values():
    for table, cols in _columns().items():
        for col in cols:
            assert not any(w in col for w in FORBIDDEN_WORDS), (table, col)


def test_login_minimum_is_user_id_and_provider_only():
    # 이메일·이름·사진은 Supabase `auth.users`에만 있고 account 스키마에는 복제하지 않는다
    assert _columns()["app_users"] & {"email", "name", "avatar_url", "phone"} == set()


def test_chat_path_modules_do_not_import_account_storage():
    for name in ("chat.py", "runner.py", "service.py", "stream.py", "events.py", "request.py"):
        text = (APP_API / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+app\.db\.account|^\s*from\s+(\.|app\.api\s+import)\s*(account|me)\b|from \.(account|me)\b", text, re.M), name
