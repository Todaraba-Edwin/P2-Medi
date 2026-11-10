"""공통 비노출 모듈(sec-guard, 2026-11-10).

- `redact(text)`: `app.logging.masking.mask_text`(전체 값·패턴)에 더해, 환경·`.env`에 로드된 비밀 값의
  **앞 4자·뒤 4자 조각**도 `***`로 가린다(키가 잘려 출력돼도 노출되지 않게).
- `install_excepthook()`: 처리되지 않은 예외의 메시지·트레이스백 전체를 redact한 뒤 stderr에 출력한다.
- `safe_exc(exc)`: 예외 한 줄 요약(종류 + redact된 메시지).
비밀 값 목록은 호출 시점에 모으며 값 자체를 로그·반환 문자열에 넣지 않는다.
"""

from __future__ import annotations

import os
import sys
import traceback
from types import TracebackType

from app.logging.masking import _MIN_SECRET_LEN, _SECRET_ENV_SUFFIXES, MASK, mask_text

_FRAGMENT_LEN = 4
# 조각이 일반 단어·URL 접두라 본문을 망가뜨리는 것은 제외한다(전체 값·패턴 마스킹은 그대로 적용된다)
_COMMON_FRAGMENTS = frozenset({"http", "post", "ostg", "tgre", "tps:", "ttp:", "s://", "sql:", "gres"})


def _settings_secret_values() -> list[str]:
    """`Settings`(.env 포함)에서 비밀 이름 필드의 값을 모은다. 읽지 못하면 조용히 건너뛴다(값은 출력하지 않는다)."""
    try:
        from pydantic_settings import SettingsConfigDict

        from app.config import Settings

        class _Reader(Settings):
            model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

        cfg = _Reader()
        root_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
        try:
            cfg2 = _Reader(_env_file=(".env", root_env))
        except Exception:  # noqa: BLE001 - 읽기 실패 시 메시지에 값이 섞일 수 있어 삼킨다
            cfg2 = cfg
    except Exception:  # noqa: BLE001
        return []
    values: list[str] = []
    for obj in (cfg, cfg2):
        for name in type(obj).model_fields:
            val = getattr(obj, name, None)
            if isinstance(val, str) and name.upper().endswith(_SECRET_ENV_SUFFIXES):
                values.append(val)
    return values


def _secret_values() -> list[str]:
    values = [v for n, v in os.environ.items() if n.upper().endswith(_SECRET_ENV_SUFFIXES)]
    values += _settings_secret_values()
    return sorted({v for v in values if len(v) >= _MIN_SECRET_LEN}, key=len, reverse=True)


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


def install_excepthook() -> None:
    """처리되지 않은 예외 출력을 redact하도록 `sys.excepthook`을 설치한다(스크립트 진입점 첫 줄에서 호출)."""
    sys.excepthook = _hook
