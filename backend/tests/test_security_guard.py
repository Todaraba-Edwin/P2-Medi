"""sec-guard 시험: 설정 검증 오류 값 숨김, redact·excepthook, 출력 패턴 정적 점검, pre-commit 규칙. 값은 가짜(`fake-key-0000…`)만 쓴다."""

import importlib.util
import sys
import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security import redact as redact_mod
from app.security.redact import install_excepthook, redact, safe_exc

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("precommit_guard", REPO / "scripts" / "precommit_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

FAKE_KEY = "fake-key-0000abcd1234wxyz"  # 앞 조각 'fake', 뒤 조각 'wxyz'
FAKE_BAD = "fake-key-0000zzzz9999badv"


# ---------- 1. 설정 검증 오류가 .env 값을 담지 않는다 ----------
def test_settings_validation_error_hides_env_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text(f"UNKNOWN_FAKE_VAR={FAKE_KEY}\nMEDIAGENT_API_MAX_CALLS={FAKE_BAD}\n", encoding="utf-8")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=str(env))
    err = info.value
    try:
        raise err
    except ValidationError:
        tb = traceback.format_exc()
    for text in (str(err), repr(err), tb):
        assert FAKE_KEY not in text and FAKE_BAD not in text
        assert "input_value" not in text or "input_value=" not in text.replace("input_type", "")


# ---------- 2. redact ----------
def test_redact_masks_full_value_and_fragments(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    out = redact(f"전체 {FAKE_KEY} 앞조각 {FAKE_KEY[:4]} 뒤조각 {FAKE_KEY[-4:]}")
    assert FAKE_KEY not in out and "wxyz" not in out and "fake" not in out
    assert "***" in out


def test_redact_keeps_ordinary_text_and_masks_patterns(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert redact("정상 문장 http://example.com 입니다") == "정상 문장 http://example.com 입니다"
    assert "***" in redact("serviceKey=abcdef123456&x=1")


def test_redact_ignores_short_secret_values(monkeypatch):
    monkeypatch.setenv("FAKE_SHORT_KEY", "ab")
    assert redact("ab cd") == "ab cd"


def test_redact_does_not_mangle_url_prefix(monkeypatch):
    monkeypatch.setenv("FAKE_ENDPOINT_DB_URL", "http://fake-host-0000.example/db")
    assert redact("see http://other.example") == "see http://other.example"


def test_safe_exc_one_line(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    line = safe_exc(RuntimeError(f"실패 key={FAKE_KEY}"))
    assert line.startswith("RuntimeError: ") and FAKE_KEY not in line and "\n" not in line


# ---------- 3. excepthook ----------
def test_excepthook_redacts_message_traceback_and_chain(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    install_excepthook()
    try:
        try:
            raise ValueError(f"안쪽 {FAKE_KEY}")
        except ValueError as inner:
            raise RuntimeError(f"바깥 {FAKE_KEY[:4]}…{FAKE_KEY[-4:]}") from inner
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    err = capsys.readouterr().err
    assert FAKE_KEY not in err and "wxyz" not in err and "fake" not in err
    assert "RuntimeError" in err and "ValueError" in err and "test_security_guard.py" in err  # 종류·파일 보존


def test_excepthook_failure_falls_back_to_type_only(monkeypatch, capsys):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(redact_mod, "format_redacted", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    install_excepthook()
    sys.excepthook(ValueError, ValueError(FAKE_KEY), None)
    err = capsys.readouterr().err
    assert FAKE_KEY not in err and "ValueError" in err


# ---------- 4. 정적 점검: 설정·환경 통째 출력 패턴이 없다 ----------
def _scan_files():
    for scope in ("backend/app", "backend/scripts", "scripts"):
        for p in (REPO / scope).rglob("*.py"):
            rel = p.relative_to(REPO).as_posix()
            if "/.venv/" in rel or "__pycache__" in rel or rel in guard.OUTPUT_ALLOW:
                continue
            yield rel, p.read_bytes()


def test_source_has_no_whole_settings_or_environ_output():
    hits = [f"{rel}: {label}" for rel, data in _scan_files() for label, pat in guard.OUTPUT_PATTERNS.items() if pat.search(data)]
    assert hits == []


# ---------- 5. pre-commit 규칙 ----------
BAD_LINES = [
    "print(settings)",
    "print(get_settings())",
    'print(f"설정 {settings}")',
    "print(os.environ)",
    "print(dict(os.environ))",
    "repr(settings)",
    "print(cfg.model_dump())",
    "logger.info(cfg.model_dump())",
    "traceback.print_exc()",
]
OK_LINES = [
    "print(settings.mediagent_api_mode)",
    'print("settings 를 읽었다")',
    "print(os.environ.get('HOME'))",
    "x = settings.model_dump()  # 출력하지 않음",
    "print(redact(traceback.format_exc()))",
]


def _write(tmp_path, rel, line):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(line + "\n", encoding="utf-8")


@pytest.mark.parametrize("line", BAD_LINES)
def test_precommit_blocks_output_patterns(tmp_path, line):
    _write(tmp_path, "backend/app/x.py", line)
    assert any("통째 출력" in p for p in guard.check("backend/app/x.py", tmp_path))


@pytest.mark.parametrize("line", OK_LINES)
def test_precommit_allows_safe_lines(tmp_path, line):
    _write(tmp_path, "backend/scripts/x.py", line)
    assert guard.check("backend/scripts/x.py", tmp_path) == []


def test_precommit_ignores_docs_tests_and_redact_module(tmp_path):
    for rel in ("P2-doc/예시.md", "backend/tests/test_x.py", "backend/app/security/redact.py"):
        _write(tmp_path, rel, "print(settings)")
        assert guard.check(rel, tmp_path) == []
