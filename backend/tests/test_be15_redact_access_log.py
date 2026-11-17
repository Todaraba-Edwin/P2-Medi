"""로그 가리기 ↔ uvicorn access log 호환 시험(BE-06 개발 서버에서 발견, 2026-11-17). 네트워크·`.env` 열람 0.

- 예전 `redact_record`는 `record.args = None`으로 지워 uvicorn `AccessFormatter`(args를 5개로 풀어 씀)가 `TypeError`를 냈다.
- 이제 인자 단위로 가리고 인자 모양(튜플·매핑)을 유지한다. 가리기 강도는 예전(합친 메시지 전체 가리기)과 같아야 한다.
- 비밀 값은 모두 가짜다.
"""

from __future__ import annotations

import io
import logging

import pytest
from uvicorn.logging import AccessFormatter

from app.logging.redact_filter import RedactFilter, install_log_redaction, redact_record, uninstall_log_redaction

FAKE_KEY = "QQQQ-access-log-key-QQQQQQQQ"  # 환경변수로 넣는 가짜 비밀 값
REALISH = "".join(["aB3d", "E5gH", "7jK9", "mN2p", "R4tV", "6xY8"])  # 쿼리 문자열의 serviceKey 값(가짜, 실제 모양)
ACCESS_MSG = '%s - "%s %s HTTP/%s" %d'  # uvicorn httptools/h11 access log 메시지 형식


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DRDEASYDRUG_API_KEY", FAKE_KEY)
    yield
    uninstall_log_redaction()


def _access_logger(name: str) -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream, handler


def _log_access(logger: logging.Logger, path: str, status: int = 200) -> None:
    logger.info(ACCESS_MSG, "127.0.0.1:50000", "GET", path, "1.1", status)


@pytest.mark.parametrize("path", [
    f"/proxy?serviceKey={REALISH}&a=1",
    f"/proxy?key={FAKE_KEY}&a=1",
    f"/x/{FAKE_KEY}/y?a=1",
])
def test_access_log_with_factory_formats_without_error_and_hides_secret(path, capsys):
    install_log_redaction()
    logger, stream, handler = _access_logger("uvicorn.access.test1")
    try:
        _log_access(logger, path)
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "Logging error" not in capsys.readouterr().err  # 서식 오류 없음(logging.raiseExceptions가 stderr에 쓰는 문구)
    assert REALISH not in out and FAKE_KEY not in out
    assert out.startswith("INFO:") and '127.0.0.1:50000 - "GET /' in out and "HTTP/1.1\" 200" in out and "a=1" in out


def test_access_log_with_handler_filter_only(capsys):
    """레코드 팩토리 없이 처리기 필터만 있을 때도 같다."""
    logger, stream, handler = _access_logger("uvicorn.access.test2")
    handler.addFilter(RedactFilter())
    try:
        _log_access(logger, f"/proxy?serviceKey={REALISH}&a=1", 404)
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert "Logging error" not in capsys.readouterr().err
    assert REALISH not in out and 'HTTP/1.1" 404' in out


def test_args_keep_shape_and_numbers():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, ACCESS_MSG, ("127.0.0.1:1", "GET", f"/p?key={FAKE_KEY}", "1.1", 200), None)
    redact_record(rec)
    assert isinstance(rec.args, tuple) and len(rec.args) == 5 and rec.args[4] == 200
    assert FAKE_KEY not in rec.args[2] and FAKE_KEY not in rec.getMessage()


def test_mapping_args_keep_shape():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "k=%(k)s n=%(n)d", ({"k": FAKE_KEY, "n": 3},), None)
    redact_record(rec)
    assert isinstance(rec.args, dict) and rec.args["n"] == 3
    assert FAKE_KEY not in rec.getMessage() and rec.getMessage().endswith("n=3")


def test_object_arg_str_is_redacted():
    class Url:
        def __str__(self) -> str:
            return f"https://apis.example/x?serviceKey={REALISH}"

    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "GET %s", (Url(),), None)
    redact_record(rec)
    assert REALISH not in rec.getMessage() and all(REALISH not in str(a) for a in rec.args)


def test_secret_split_across_args_falls_back_to_whole_message():
    """비밀이 인자 둘에 걸치면 인자 단위로는 못 가린다 → 합친 메시지 전체 가리기(예전과 같은 강도)로 돌아간다."""
    head, tail = FAKE_KEY[:12], FAKE_KEY[12:]
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "key=%s%s", (head, tail), None)
    redact_record(rec)
    msg = rec.getMessage()
    assert FAKE_KEY not in msg and head not in msg and tail not in msg
    assert rec.args == ()


def test_format_mismatch_falls_back_safely():
    """%d 자리에 객체(→ 가린 문자열)가 와 서식이 깨지면 예전 방식으로 돌아간다(예외 없이)."""

    class Weird:
        def __int__(self) -> int:
            return 7

        def __index__(self) -> int:
            return 7

        def __str__(self) -> str:
            return FAKE_KEY

    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "n=%d", (Weird(),), None)
    redact_record(rec)
    assert rec.getMessage() == "n=7" and rec.args == ()


def test_no_args_message_is_redacted_and_args_untouched():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, f"plain {FAKE_KEY}", None, None)
    redact_record(rec)
    assert FAKE_KEY not in rec.getMessage() and rec.args is None
