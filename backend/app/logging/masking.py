"""비밀 마스킹(PJ2-Agent-로깅-전략.md 4장 (3) 3번). 모든 모드에 적용한다.

- 환경변수 중 이름이 _KEY·_SECRET·_DB_URL로 끝나는 것의 값, `sk-`·`serviceKey=`·`postgres://`·JWT 패턴을 `***`로 바꾼다.
- 값은 어디에도 기록·출력하지 않는다(여기서는 치환만 한다).
"""

from __future__ import annotations

import os
import re
from typing import Any

MASK = "***"
_SECRET_ENV_SUFFIXES = ("_KEY", "_SECRET", "_DB_URL")
_MIN_SECRET_LEN = 6  # 너무 짧은 값("1" 등)은 일반 문자열을 망가뜨리므로 환경변수 값 치환에서 제외한다

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)servicekey=[^&\s\"']+"),
    re.compile(r"postgres(?:ql)?://[^\s\"']+"),
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT
]


def _env_secret_values() -> list[str]:
    values = []
    for name, value in os.environ.items():
        if name.upper().endswith(_SECRET_ENV_SUFFIXES) and len(value) >= _MIN_SECRET_LEN:
            values.append(value)
    return sorted(values, key=len, reverse=True)  # 긴 값부터 바꿔 부분 겹침을 막는다


def mask_text(text: str) -> str:
    for value in _env_secret_values():
        text = text.replace(value, MASK)
    for pat in _PATTERNS:
        text = pat.sub(MASK, text)
    return text


def mask_value(value: Any) -> Any:
    """dict·list·tuple 안의 문자열(키 포함)까지 재귀로 마스킹한다."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {mask_text(str(k)): mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value
