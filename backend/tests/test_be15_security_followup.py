"""BE-15 §3 후속 S-02~S-09(security-engineer 보고 2026-11-11) 시험.

가짜 값은 알려진 형태(`QQQQ…`)로만 쓰고, 가드가 막아야 하는 '실제 모양' 값은 시험 안에서 조각을 이어 붙여 만든다
(소스 한 줄에 실제 모양 값이 그대로 남지 않게). 실제 `.env`·원격 DB·외부 API는 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app import config as config_mod
from app.config import Settings, reveal
from app.logging import masking
from app.logging.masking import mask_text, settings_secret_values
from app.logging.redact_filter import (
    QUIET_LOGGERS,
    RedactFilter,
    install_log_redaction,
    redact_record,
    uninstall_log_redaction,
)
from app.security import redact as redact_mod

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "scripts"))

SPEC = importlib.util.spec_from_file_location("precommit_guard_s", REPO / "scripts" / "precommit_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

Q = "QQQQ" * 6  # 알려진 가짜 몸통(24자)
# '실제 모양'(가짜 표지 없음) 몸통: 조각을 이어 붙여 만든다
REALISH = "".join(["aB3d", "E5gH", "7jK9", "mN2p", "R4tV", "6xY8"])
REF = "".join(["abcdefghij", "0123456789"])  # 20자 소문자·숫자(프로젝트 ref 모양)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("MEDIAGENT_MODE", raising=False)
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    yield
    uninstall_log_redaction()


def _secrets(body: str) -> dict[str, str]:
    """형식별 비밀 모양 문자열(본문 body)."""
    return {
        "sb_secret": "sb_" + "secret_" + body,
        "sb_publishable": "sb_" + "publishable_" + body,
        "upstage": "up" + "_" + body,
        "bearer": "Authorization: " + "Bearer " + body,
        "libpq": "host=db.example user=postgres " + "pass" + "word=" + body + " dbname=postgres",
        "pg_ref": "postgres" + "." + REF,
        "supabase_host": "https://" + REF + ".supabase" + ".co/rest/v1",
    }


# ---------------------------------------------------------------- S-02 마스킹
@pytest.mark.parametrize("kind", list(_secrets(Q)))
def test_s02_mask_removes_new_formats(kind):
    text = _secrets(REALISH)[kind]
    out = mask_text(f"앞 {text} 뒤")
    secret_part = REF if kind in ("pg_ref", "supabase_host") else REALISH
    assert secret_part not in out and "***" in out and out.startswith("앞 ") and out.endswith(" 뒤")


def test_s02_mask_keeps_labels_and_ordinary_text():
    assert mask_text("Authorization: Bearer " + REALISH) == "Authorization: Bearer ***"
    assert mask_text("password=" + REALISH + " host=h") == "password=*** host=h"
    for ordinary in ("setup_" + REALISH, "Bearer 토큰을 쓴다", "lookup_abcdefghijklmnopqrstuvwxyz", "postgres.short", "update_query"):
        assert mask_text(ordinary) == ordinary, ordinary


# ---------------------------------------------------------------- S-02 pre-commit 가드
def _write(tmp_path: Path, rel: str, text: str) -> None:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text + "\n", encoding="utf-8")


@pytest.mark.parametrize("kind", list(_secrets(Q)))
def test_s02_guard_blocks_new_formats_in_app_code(tmp_path, kind):
    _write(tmp_path, "backend/app/x.py", f"V = {_secrets(REALISH)[kind]!r}")
    assert any("비밀 패턴" in p for p in guard.check("backend/app/x.py", tmp_path)), kind


@pytest.mark.parametrize("line", [
    "Authorization: Bearer <token>",
    "Authorization: Bearer ${TOKEN}",
    "host=localhost user=postgres password=[YOUR-PASSWORD] dbname=postgres",
    "conn = psycopg.connect(password=password, host=host)",
    "https://[프로젝트ref].supabase.co",
    "postgres.[ref]",
    "def setup_abcdefghijklmnopqrstuvwxyz(): pass",
])
def test_s02_guard_allows_placeholders(tmp_path, line):
    _write(tmp_path, "P2-doc/x.md", line)
    assert guard.check("P2-doc/x.md", tmp_path) == []


# ---------------------------------------------------------------- S-03 mask_text가 Settings(.env) 값도 가린다
def test_s03_mask_text_uses_dotenv_settings_values(tmp_path, monkeypatch):
    fake = "QQQQ-dotenv-only-" + "QQQQ" * 3
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"UPSTAGE_API_KEY={fake}\n", encoding="utf-8")
    found = fake in settings_secret_values()  # 목록을 assert 식에 두지 않는다(실패 시 실제 .env 값이 출력되지 않게)
    assert found
    assert mask_text(f"x {fake} y") == "x *** y"
    assert fake not in redact_mod.redact(f"x {fake} y")  # redact()와 같은 출처


def test_s03_span_logger_masks_dotenv_value(tmp_path, monkeypatch):
    from app.logging import SpanLogger

    fake = "QQQQ-span-dotenv-" + "QQQQ" * 3
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={fake}\n", encoding="utf-8")
    logger = SpanLogger(mode="dev")
    logger.log(input_text=f"합성 {fake}", node="model")
    text = logger.path().read_text(encoding="utf-8")
    assert fake not in text and "***" in text


def test_s03_dotenv_values_cached_until_file_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=QQQQ-first-QQQQQQQQ\n", encoding="utf-8")
    masking._dotenv_secret_values_cached.cache_clear()
    settings_secret_values()
    settings_secret_values()
    info = masking._dotenv_secret_values_cached.cache_info()
    assert info.misses == 1 and info.hits >= 1  # 호출마다 Settings를 만들지 않는다
    env.write_text("ANTHROPIC_API_KEY=QQQQ-second-changed-QQQQQQQQ\n", encoding="utf-8")
    found = "QQQQ-second-changed-QQQQQQQQ" in settings_secret_values()  # 크기·수정 시각이 바뀌면 다시 읽는다
    assert found


def test_s03_env_values_not_cached_in_dotenv_cache(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "QQQQ-env-only-QQQQQQQQ")
    cached = "QQQQ-env-only-QQQQQQQQ" in settings_secret_values()  # 환경변수는 캐시하지 않고 호출마다 본다
    assert not cached
    assert mask_text("a QQQQ-env-only-QQQQQQQQ b") == "a *** b"


# ---------------------------------------------------------------- S-04 SecretStr
SECRET_FIELDS = [n for n in Settings.model_fields
                 if n.endswith(("_api_key", "_secret_key", "_publishable_key")) or n in ("supabase_db_url", "local_pg_dsn")]


def test_s04_secret_fields_are_secretstr_and_hidden():
    # 10 + local_pg_dsn(BE-11-14 A) + next_public_supabase_publishable_key(BE-11-18 A), 2026-11-19
    assert len(SECRET_FIELDS) == 12
    fakes = {n: f"QQQQ-{n}-QQQQQQQQ" for n in SECRET_FIELDS}
    s = Settings(_env_file=None, **fakes)
    dumped = s.model_dump()
    for text in (repr(s), str(s), repr(dumped), str(dumped), s.model_dump_json()):
        for v in fakes.values():
            assert v not in text
    for n, v in fakes.items():
        assert isinstance(getattr(s, n), SecretStr) and reveal(getattr(s, n)) == v


def test_s04_reveal_handles_plain_none_and_empty():
    assert reveal(None) is None and reveal("") is None and reveal(SecretStr("")) is None
    assert reveal("QQQQ-plain") == "QQQQ-plain"  # 시험용 SimpleNamespace 설정(평문 str)과 호환


def test_s04_clients_receive_plain_key():
    from app.tools.dur import DurClient
    from app.tools.eyak import EyakClient
    from app.tools.prmsn import PrmsnClient

    s = Settings(_env_file=None, drdeasydrug_end_point="http://e.example", drdeasydrug_api_key="QQQQ-eyak",
                 drugprdtprmsninfoservice08_end_point="http://p.example", drugprdtprmsninfoservice08_api_key="QQQQ-prmsn",
                 durprdlstinfoservice03_end_point="http://i.example", durprdlstinfoservice03_api_key="QQQQ-item",
                 durirdntinfoservice03_end_point="http://g.example", durirdntinfoservice03_api_key="QQQQ-ingr",
                 mediagent_api_mode="snapshot")
    assert EyakClient.from_settings(s)._http.api_key == "QQQQ-eyak"
    assert PrmsnClient.from_settings(s)._http.api_key == "QQQQ-prmsn"
    dur = DurClient.from_settings(s)
    assert dur._http["item"].api_key == "QQQQ-item" and dur._http["ingr"].api_key == "QQQQ-ingr"
    ns = SimpleNamespace(drdeasydrug_end_point="http://e.example", drdeasydrug_api_key="QQQQ-ns",
                         mediagent_api_mode="snapshot", mediagent_api_cache_dir=None,
                         mediagent_api_cache_ttl_seconds=1.0, mediagent_api_max_calls=1)
    assert EyakClient.from_settings(ns)._http.api_key == "QQQQ-ns"


def test_s04_chat_model_gets_plain_key():
    from app.agent.llm import make_chat_model

    m = make_chat_model(Settings(_env_file=None, openai_api_key="QQQQ-openai-QQQQQQQQ"))
    assert m.openai_api_key.get_secret_value() == "QQQQ-openai-QQQQQQQQ"


def test_s04_load_corpus_resolve_dsn_reveals_secretstr(monkeypatch):
    import load_corpus

    class _Fake(BaseSettings):
        supabase_db_url: SecretStr | None = SecretStr("QQQQ-dsn-QQQQQQQQ")

        @classmethod
        def settings_customise_sources(cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource,
                                       env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource,
                                       file_secret_settings: PydanticBaseSettingsSource) -> tuple[PydanticBaseSettingsSource, ...]:
            return (init_settings,)  # 실제 .env를 읽지 않는다

    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr(config_mod, "Settings", _Fake)
    assert load_corpus.resolve_dsn("SUPABASE_DB_URL") == "QQQQ-dsn-QQQQQQQQ"  # '**********'가 아니다


def test_s04_luna_probe_reveals(tmp_path, monkeypatch):
    import luna_probe

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=QQQQ-luna-QQQQQQQQ\n", encoding="utf-8")
    assert luna_probe.resolve_openai_key(env_files=(str(env),)) == "QQQQ-luna-QQQQQQQQ"


# ---------------------------------------------------------------- S-05 스크립트 excepthook
KEY_SCRIPT_MARKERS = ("OPENAI_API_KEY", "SUPABASE_DB_URL", "from_settings", "make_chat_model", "get_settings", "resolve_dsn", "psycopg")


def _key_scripts() -> list[Path]:
    out = []
    for p in sorted((BACKEND / "scripts").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if any(m in text for m in KEY_SCRIPT_MARKERS) and "__main__" in text:
            out.append(p)
    return out


def test_s05_key_scripts_install_excepthook():
    scripts = _key_scripts()
    names = {p.name for p in scripts}
    assert {"be16_remote_migrate.py", "load_corpus.py", "ag03_remote_smoke.py"} <= names
    missing = [p.name for p in scripts if "install_excepthook()" not in p.read_text(encoding="utf-8")]
    assert missing == []


def test_s05_install_excepthook_also_installs_log_redaction(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "QQQQ-hook-log-QQQQQQQQ")
    redact_mod.install_excepthook()
    rec = logging.getLogger("mediagent.test.s05").makeRecord("x", logging.ERROR, __file__, 1, "키 %s", ("QQQQ-hook-log-QQQQQQQQ",), None)
    assert "QQQQ-hook-log-QQQQQQQQ" not in rec.getMessage()


# ---------------------------------------------------------------- S-06 로깅 필터·httpx
def _capture_logger(name: str) -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream, handler


def test_s06_httpx_loggers_quiet_after_install():
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    install_log_redaction()
    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
        assert not logging.getLogger(name).isEnabledFor(logging.INFO)


def test_s06_record_factory_masks_message_args_and_exception(monkeypatch):
    monkeypatch.setenv("DRDEASYDRUG_API_KEY", "QQQQ-public-api-QQQQQQQQ")
    install_log_redaction()
    logger, stream, handler = _capture_logger("mediagent.test.s06")
    try:
        logger.warning("HTTP Request: GET %s", "https://apis.example/x?serviceKey=" + REALISH + "&a=1")
        try:
            raise RuntimeError("실패 QQQQ-public-api-QQQQQQQQ " + "postgresql://u:" + REALISH + "@h/db")
        except RuntimeError:
            logger.exception("처리 실패")
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert REALISH not in out and "QQQQ-public-api-QQQQQQQQ" not in out
    assert "a=1" in out and "RuntimeError" in out and "Traceback" in out


def test_s06_redact_filter_on_handler_without_factory(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "QQQQ-filter-only-QQQQQQQQ")
    logger, stream, handler = _capture_logger("mediagent.test.s06b")
    handler.addFilter(RedactFilter())
    try:
        logger.error("키=%s", "QQQQ-filter-only-QQQQQQQQ")
    finally:
        logger.removeHandler(handler)
    assert "QQQQ-filter-only-QQQQQQQQ" not in stream.getvalue() and "***" in stream.getvalue()


def test_s06_redact_record_failure_drops_content(monkeypatch):
    import app.logging.redact_filter as rf

    monkeypatch.setattr(rf, "_redact", lambda _t: (_ for _ in ()).throw(OSError("boom")))
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "원문 %s", ("QQQQ-x",), None)
    redact_record(rec)
    assert "QQQQ-x" not in rec.getMessage() and "redact 실패" in rec.getMessage()


def test_s06_install_is_idempotent():
    install_log_redaction()
    first = logging.getLogRecordFactory()
    install_log_redaction()
    assert logging.getLogRecordFactory() is first
    uninstall_log_redaction()
    assert logging.getLogRecordFactory() is not first


def test_s06_server_installs_redaction():
    text = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "install_log_redaction()" in text


# ---------------------------------------------------------------- S-07 롤백 메시지 가리기
def test_s07_rollback_message_redacted():
    import be16_remote_migrate as mig

    class _Cur:
        def execute(self, *_a, **_k):
            return None

    class _Conn:
        rolled = False

        def cursor(self):
            return _Cur()

        def commit(self):
            raise AssertionError("커밋하면 안 된다")

        def rollback(self):
            self.rolled = True

    def boom(_cur):
        raise RuntimeError("DETAIL: " + "postgresql://postgres." + REF + ":" + REALISH + "@h:5432/db " + "password=" + REALISH)

    logs: list[str] = []
    conn = _Conn()
    with pytest.raises(mig.StageAbort):
        mig.transaction(conn, "단계X", boom, log=logs.append)
    assert conn.rolled and len(logs) == 1
    assert REALISH not in logs[0] and REF not in logs[0] and "롤백: RuntimeError" in logs[0]


# ---------------------------------------------------------------- S-08 시험 폴더 줄 단위 예외
@pytest.mark.parametrize("line", [
    "KEY = '" + "sk-" + REALISH + "'",
    "DSN = '" + "postgresql://" + "u:" + REALISH + "@h/db'",
    "TOKEN = '" + "sb_" + "secret_" + REALISH + "'",
])
def test_s08_real_looking_secret_in_tests_is_blocked(tmp_path, line):
    _write(tmp_path, "backend/tests/test_x.py", line)
    problems = guard.check("backend/tests/test_x.py", tmp_path)
    assert any("비밀 패턴" in p and "줄 1" in p for p in problems)
    assert all(REALISH not in p for p in problems)  # 값은 출력하지 않는다


@pytest.mark.parametrize("line", [
    "KEY = '" + "sk-" + Q + "'",
    "KEY = '" + "sk-" + "test-NOT-A-REAL-KEY-0000" + "'",
    "KEY = '" + "sk-" + REALISH + "'  # guard" + ": fake",
    "DSN = '" + "postgresql://" + "u:pw" + "@h/db'",
    "DSN = '" + "postgresql://" + "u:SECRETPW" + "@h/db'",
    "TOKEN = '" + "sb_" + "publishable_" + Q + "'",
])
def test_s08_known_fakes_in_tests_pass(tmp_path, line):
    _write(tmp_path, "backend/tests/test_x.py", line)
    assert guard.check("backend/tests/test_x.py", tmp_path) == []


def test_s08_fake_mark_only_exempts_tests(tmp_path):
    _write(tmp_path, "backend/app/x.py", "KEY = '" + "sk-" + REALISH + "'  # guard" + ": fake")
    assert guard.check("backend/app/x.py", tmp_path)


def test_s08_current_test_files_pass_guard():
    blocked = {}
    for p in sorted((BACKEND / "tests").rglob("*.py")):
        rel = p.relative_to(REPO).as_posix()
        if "__pycache__" in rel:
            continue
        probs = guard.check(rel, REPO)
        if probs:
            blocked[rel] = probs
    assert blocked == {}


# ---------------------------------------------------------------- S-09 봉인 시험셋
@pytest.mark.parametrize("rel", ["evaluation/eval_set/test_set.SEALED.jsonl", "evaluation/other/x.SEALED.jsonl", "a.SEALED.jsonl"])
def test_s09_sealed_files_blocked_anywhere(tmp_path, rel):
    assert any("SEALED" in p for p in guard.check(rel, tmp_path))


def test_s09_manifest_and_dev_set_allowed(tmp_path):
    for rel in ("evaluation/eval_set/manifest.json", "evaluation/eval_set/dev_set.jsonl"):
        assert guard.check(rel, tmp_path) == []


def test_s02_guard_main_prints_path_and_reason_only(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "backend/app/x.py", "V = '" + "up" + "_" + REALISH + "'")
    monkeypatch.chdir(tmp_path)
    assert guard.main(["backend/app/x.py"]) == 1
    out = capsys.readouterr().out
    assert "BLOCK backend/app/x.py" in out and "Upstage" in out and REALISH not in out
    assert REALISH not in json.dumps(guard.check("backend/app/x.py", tmp_path), ensure_ascii=False)
