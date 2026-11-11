"""공통 비노출 모듈(sec-guard, 2026-11-10).

- `redact(text)`: `app.logging.masking.mask_text`(전체 값·패턴)에 더해, 환경·`.env`에 로드된 비밀 값의
  **앞 4자·뒤 4자 조각**도 `***`로 가린다(키가 잘려 출력돼도 노출되지 않게).
- `install_excepthook()`: 처리되지 않은 예외의 메시지·트레이스백 전체를 redact한 뒤 stderr에 출력한다.
  표준 `logging` 레코드 가리기(`app.logging.redact_filter`)도 함께 설치한다(S-05·S-06, 2026-11-11).
- `safe_exc(exc)`: 예외 한 줄 요약(종류 + redact된 메시지).
비밀 값 목록은 호출 시점에 모으며 값 자체를 로그·반환 문자열에 넣지 않는다.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from app.logging.masking import _MIN_SECRET_LEN, MASK, mask_text, secret_values, settings_secret_values

_FRAGMENT_LEN = 4
# 조각이 일반 단어·URL 접두라 본문을 망가뜨리는 것은 제외한다(전체 값·패턴 마스킹은 그대로 적용된다)
_COMMON_FRAGMENTS = frozenset({"http", "post", "ostg", "tgre", "tps:", "ttp:", "s://", "sql:", "gres"})


def _settings_secret_values() -> list[str]:
    """`.env`(Settings 출처)의 비밀 값. 출처는 `masking.settings_secret_values`와 같다(S-03: span 로그·redact 공통)."""
    return settings_secret_values()


def _secret_values() -> list[str]:
    return [v for v in secret_values() if len(v) >= _MIN_SECRET_LEN]


def _fragments(values: list[str]) -> list[str]:
    frags: set[str] = set()
    for v in values:
        for frag in (v[:_FRAGMENT_LEN], v[-_FRAGMENT_LEN:]):
            if len(frag) == _FRAGMENT_LEN and frag.lower() not in _COMMON_FRAGMENTS and "://" not in frag:
                frags.add(frag)
    return sorted(frags)


def redact(text: str) -> str:
    """전체 값·패턴(masking.mask_text) + 비밀 값의 앞·뒤 조각을 가린다."""
    values = _secret_values()
    for v in values:
        text = text.replace(v, MASK)
    text = mask_text(text)
    for frag in _fragments(values):
        text = text.replace(frag, MASK)
    return text


def safe_exc(exc: BaseException) -> str:
    """예외 한 줄 요약: `종류: redact된 메시지`."""
    return f"{type(exc).__name__}: {redact(str(exc))}"


def format_redacted(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> str:
    return redact("".join(traceback.format_exception(exc_type, exc, tb)))


def _hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    try:
        text = format_redacted(exc_type, exc, tb)
    except Exception:  # noqa: BLE001 - 가리지 못하면 내용 없이 종류만 낸다
        text = f"{exc_type.__name__}: (redact 실패, 메시지 생략)\n"
    sys.stderr.write(text)


def install_excepthook(*, logs: bool = True) -> None:
    """처리되지 않은 예외 출력을 redact하도록 `sys.excepthook`을 설치한다(스크립트 진입점 첫 줄에서 호출).

    `logs=True`(기본)면 표준 `logging` 레코드 가리기와 `httpx`·`httpcore` WARNING 고정도 함께 설치한다(S-05·S-06).
    excepthook은 처리되지 않은 예외만 맡으므로 `logging.exception` 경로는 이쪽이 맡는다.
    """
    sys.excepthook = _hook
    if logs:
        from app.logging.redact_filter import install_log_redaction  # noqa: PLC0415

        install_log_redaction()
