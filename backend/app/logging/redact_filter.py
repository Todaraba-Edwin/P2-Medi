"""표준 `logging` 출력의 비밀값 가리기(BE-15 §3 후속 S-05·S-06, 2026-11-11).

- `RedactFilter`: 처리기(handler)에 붙이는 `logging.Filter`. 메시지·인자(인자 단위, 튜플·매핑 모양 유지)·예외 트레이스백·stack_info를
  `redact()`한다. 인자를 None으로 지우지 않는 것은 uvicorn `AccessFormatter`가 `record.args`를 풀어 쓰기 때문이다(BE-06 개발 서버에서 발견, 2026-11-17).
- `install_log_redaction()`: 프로세스 전역 설치(멱등).
  ① 레코드 팩토리를 감싸 **모든 로거·처리기**(나중에 붙는 uvicorn 처리기 포함)의 레코드를 만들 때 가린다.
  ② `httpx`·`httpcore` 로거를 WARNING으로 고정한다(INFO의 `HTTP Request: GET <URL>`에 `serviceKey=`가 담기므로, S-06).
  ③ 이미 있는 루트 처리기에 `RedactFilter`를 붙인다.
값은 출력하지 않고 치환만 한다. 가리기에 실패하면 메시지를 버리고 고정 문구만 남긴다.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Mapping
from typing import Any

QUIET_LOGGERS = ("httpx", "httpcore")
_FAILED = "(redact 실패, 메시지 생략)"
_installed: dict[str, Any] = {}


def _redact(text: str) -> str:
    from app.security.redact import redact  # 늦게 가져온다(app.logging ↔ app.security 순환 방지)

    return redact(text)


_PLAIN_ARG_TYPES = (int, float, bool, type(None))  # 숫자 서식(%d 등)을 지키려고 그대로 두는 인자 형


def _redact_arg(arg: Any) -> Any:
    """인자 하나를 가린다. 숫자·None은 그대로, 문자열은 가린 문자열, 그 밖의 객체는 `str()`을 가린 문자열로 바꾼다(객체 안의 비밀 차단)."""
    if isinstance(arg, _PLAIN_ARG_TYPES):
        return arg
    return _redact(arg if isinstance(arg, str) else str(arg))


def _redact_msg_and_args(record: logging.LogRecord) -> None:
    """메시지·인자를 가리되 **인자 모양(튜플·매핑)은 유지**한다.

    uvicorn `AccessFormatter`처럼 `record.args`를 직접 풀어 쓰는 서식기가 있으므로 args를 None으로 지우지 않는다.
    인자 단위로 가린 뒤 합친 메시지가 **예전 방식(합친 메시지 전체를 가림)의 결과와 한 글자라도 다르면**(비밀이 msg·인자 경계나 인자 둘에
    걸친 경우, 서식이 맞지 않는 경우 등) 예전 방식 결과를 msg에 두고 args를 빈 튜플로 둔다. 그래서 가리기 강도는 예전과 같다.
    """
    args = record.args
    expected = _redact(record.getMessage())  # 예전 방식의 결과(기준)
    if not args:
        record.msg = expected
        return
    msg = record.msg
    if isinstance(args, Mapping):
        record.args = {k: _redact_arg(v) for k, v in args.items()}
    else:
        record.args = tuple(_redact_arg(a) for a in args)
    record.msg = _redact(msg if isinstance(msg, str) else str(msg))
    try:
        same = record.getMessage() == expected
    except Exception:  # noqa: BLE001 - 바꾼 인자로 서식이 맞지 않으면 예전 방식으로
        same = False
    if not same:
        record.msg, record.args = expected, ()


def redact_record(record: logging.LogRecord) -> logging.LogRecord:
    """레코드의 메시지·인자·예외·stack을 제자리에서 가린다. 이미 가린 레코드는 건너뛴다. 인자 모양(튜플·매핑)은 유지한다."""
    if getattr(record, "_mediagent_redacted", False):
        return record
    try:
        _redact_msg_and_args(record)
        if record.exc_info and not record.exc_text:
            record.exc_text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
        if record.exc_text:
            record.exc_text = _redact(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact(record.stack_info)
    except Exception:  # noqa: BLE001 - 가리지 못하면 원문을 남기지 않는다
        record.msg, record.args, record.exc_text, record.stack_info = _FAILED, (), None, None
        record.exc_info = None
    record._mediagent_redacted = True  # type: ignore[attr-defined]
    return record


class RedactFilter(logging.Filter):
    """처리기용 필터. 레코드를 버리지 않고(항상 True) 내용만 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        redact_record(record)
        return True


def install_log_redaction(quiet_level: int = logging.WARNING) -> None:
    """전역 설치(여러 번 불러도 한 번만 감싼다). 스크립트는 `install_excepthook()`이 함께 부른다."""
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(quiet_level)
    if "factory" not in _installed:
        base: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            return redact_record(base(*args, **kwargs))

        logging.setLogRecordFactory(factory)
        _installed["factory"] = factory
        _installed["base"] = base
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())


def uninstall_log_redaction() -> None:
    """시험용: 레코드 팩토리를 원래대로 돌린다(우리 팩토리가 그대로 걸려 있을 때만)."""
    if "factory" in _installed and logging.getLogRecordFactory() is _installed["factory"]:
        logging.setLogRecordFactory(_installed["base"])
    _installed.clear()
