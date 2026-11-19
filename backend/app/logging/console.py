"""앱 로거(`app.*`)의 INFO 줄을 서버 터미널(stderr)에 보이게 하는 처리기(BE-17 후속, 2026-11-19).

원인: uvicorn 기본 설정(`uvicorn.config.LOGGING_CONFIG`)은 `uvicorn`·`uvicorn.access` 로거에만 처리기를 붙이고 루트에는 붙이지 않는다.
그래서 `app.*` 레코드는 처리기를 찾지 못해 `logging.lastResort`(WARNING 이상만)로 가고 INFO 줄은 버려진다.

- `install_app_console_logging()`: `app` 로거에 stderr 처리기 **하나**를 붙인다(멱등: 표지 속성으로 찾아 다시 붙이지 않는다).
  처리기에는 `RedactFilter`를 붙이므로 레코드 팩토리(`install_log_redaction`)와 함께 비밀값을 두 겹으로 가린다.
- `propagate`는 그대로 둔다(True): 시험의 `caplog`(루트 처리기)가 계속 받는다. 대신 루트가 이미 터미널(stderr·stdout)에 찍는
  처리기를 가졌으면(예: `logging.basicConfig`, 사용자 log_config) 이 처리기는 찍지 않아 같은 줄이 두 번 나오지 않는다.
- `app` 로거 수준이 정해지지 않았으면(NOTSET) INFO로 둔다. 이미 정했으면(사용자 설정) 바꾸지 않는다.
- 형식은 uvicorn 줄과 나란히 읽히게 `INFO:     app.api.service: warmup starting` 꼴이다.
- L4 집계 JSON 줄(`mediagent.agg@v1`, `spans.Aggregator`)은 stdout에 직접 쓰므로 이 처리기와 무관하다.
"""

from __future__ import annotations

import logging
import sys

from app.logging.redact_filter import RedactFilter

APP_LOGGER = "app"
_MARK = "_mediagent_console"
_FORMAT = "%(levelprefix)s %(name)s: %(message)s"


class _StderrHandler(logging.StreamHandler):
    """그때그때의 `sys.stderr`에 쓰는 처리기(표준 `logging._StderrHandler`와 같은 방식). 시험의 stderr 바꿔치기도 따른다."""

    def __init__(self, level: int = logging.NOTSET) -> None:
        logging.Handler.__init__(self, level)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:  # noqa: ARG002 - 고정 대상(sys.stderr)이라 바꾸지 않는다
        return


class _ConsoleFormatter(logging.Formatter):
    """uvicorn `DefaultFormatter`처럼 `INFO:     ` 접두(수준 이름 + 콜론, 9칸 맞춤)를 붙인다. 색은 쓰지 않는다."""

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - 표준 API 이름
        record.levelprefix = f"{record.levelname}:".ljust(9)
        return super().formatMessage(record)


class _DeferToRootConsole(logging.Filter):
    """루트가 이미 터미널에 찍는 처리기를 가졌으면 이 처리기는 찍지 않는다(중복 출력 방지)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: ARG002
        for h in logging.getLogger().handlers:
            if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (sys.stderr, sys.stdout):
                return False
        return True


def app_console_handlers(logger_name: str = APP_LOGGER) -> list[logging.Handler]:
    """이 모듈이 붙인 처리기 목록(시험·점검용)."""
    return [h for h in logging.getLogger(logger_name).handlers if getattr(h, _MARK, False)]


def install_app_console_logging(level: int = logging.INFO, logger_name: str = APP_LOGGER) -> logging.Handler:
    """`app` 로거에 stderr 처리기를 한 번만 붙이고 그 처리기를 돌려준다. 여러 번 불러도 처리기는 하나다."""
    logger = logging.getLogger(logger_name)
    if logger.level == logging.NOTSET:
        logger.setLevel(level)
    existing = app_console_handlers(logger_name)
    if existing:
        return existing[0]
    handler = _StderrHandler(level)
    handler.setFormatter(_ConsoleFormatter(_FORMAT))
    handler.addFilter(RedactFilter())
    handler.addFilter(_DeferToRootConsole())
    setattr(handler, _MARK, True)
    logger.addHandler(handler)
    return handler


def uninstall_app_console_logging(logger_name: str = APP_LOGGER) -> None:
    """시험용: 이 모듈이 붙인 처리기를 뗀다(로거 수준은 그대로)."""
    logger = logging.getLogger(logger_name)
    for h in app_console_handlers(logger_name):
        logger.removeHandler(h)


__all__ = ["APP_LOGGER", "app_console_handlers", "install_app_console_logging", "uninstall_app_console_logging"]
