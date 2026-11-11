"""비밀 마스킹(PJ2-Agent-로깅-전략.md 4장 (3) 3번). 모든 모드에 적용한다.

- 값 치환: 환경변수와 `.env`(pydantic `Settings`가 읽는 파일) 중 이름이 _KEY·_SECRET·_DB_URL로 끝나는 것의 값.
  `.env` 값은 파일 경로·수정 시각이 같으면 캐시해 호출마다 `Settings`를 만들지 않는다(S-03, 2026-11-11).
- 패턴 치환: `sk-`·`serviceKey=`·`postgres://`·JWT, Supabase `sb_secret_`·`sb_publishable_`, Upstage `up_`, `Bearer` 토큰,
  libpq key=value의 `password=`, Supabase 프로젝트 ref(`postgres.<ref>`·`<ref>.supabase.co`)(S-02, 2026-11-11).
- 값은 어디에도 기록·출력하지 않는다(여기서는 치환만 한다).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

MASK = "***"
_SECRET_ENV_SUFFIXES = ("_KEY", "_SECRET", "_DB_URL")
_MIN_SECRET_LEN = 6  # 너무 짧은 값("1" 등)은 일반 문자열을 망가뜨리므로 값 치환에서 제외한다
_REPO_ROOT = Path(__file__).resolve().parents[3]

# (패턴, 바꿀 문자열). 앞 접두(키 이름·스킴)를 남겨야 읽기 쉬운 것은 그룹 참조로 바꾼다.
_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), MASK),
    (re.compile(r"(?i)servicekey=[^&\s\"']+"), MASK),
    (re.compile(r"postgres(?:ql)?://[^\s\"']+"), MASK),
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), MASK),  # JWT
    (re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_\-]{8,}"), MASK),  # Supabase 새 키 형식
    (re.compile(r"\bup_[A-Za-z0-9]{16,}"), MASK),  # Upstage
    (re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=\-]{12,}"), r"\1" + MASK),
    (re.compile(r"(?i)\b(password\s*=\s*)(?!\*\*\*)[^\s\"'&;,)]+"), r"\1" + MASK),  # libpq key=value
    (re.compile(r"\b(postgres\.)[a-z0-9]{20}\b"), r"\1" + MASK),  # 비밀번호 없는 Supabase URI의 프로젝트 ref
    (re.compile(r"\b[a-z0-9]{20}(\.supabase\.(?:co|com|in)\b)"), MASK + r"\1"),
]
# 패턴만 쓰는 곳(app/llm/prompts.py의 프롬프트 비밀 검사)과의 호환: 컴파일된 패턴 목록
_PATTERNS: list[re.Pattern[str]] = [pat for pat, _ in _REPLACEMENTS]


def _is_secret_name(name: str) -> bool:
    return name.upper().endswith(_SECRET_ENV_SUFFIXES)


def _env_secret_values() -> list[str]:
    return [v for n, v in os.environ.items() if _is_secret_name(n) and len(v) >= _MIN_SECRET_LEN]


def _dotenv_files() -> tuple[Path, ...]:
    """`Settings`가 읽는 `.env` 후보: 실행 위치와 저장소 루트."""
    seen: list[Path] = []
    for p in (Path.cwd() / ".env", _REPO_ROOT / ".env"):
        rp = p.resolve()
        if rp not in seen:
            seen.append(rp)
    return tuple(seen)


def _plain(value: Any) -> str | None:
    """`SecretStr`·`str`에서 원문을 꺼낸다(프로세스 안에서 치환에만 쓴다)."""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return value if isinstance(value, str) else None


@lru_cache(maxsize=8)
def _dotenv_secret_values_cached(stamp: tuple[tuple[str, int, int], ...]) -> tuple[str, ...]:
    """`.env` 파일만 소스로 하는 `Settings`에서 비밀 이름 필드 값을 모은다. 읽지 못하면 빈 값(오류 문구에 값이 섞일 수 있어 삼킨다)."""
    files = tuple(p for p, _, _ in stamp)
    if not files:
        return ()
    try:
        from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

        from app.config import Settings

        class _DotenvOnly(Settings):
            model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

            @classmethod
            def settings_customise_sources(
                cls,
                settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (init_settings, dotenv_settings)  # 환경변수는 _env_secret_values가 따로 본다(테스트 monkeypatch 값을 캐시에 넣지 않음)

    except Exception:  # noqa: BLE001
        return ()
    out: list[str] = []
    for f in files:  # 파일마다 따로 읽는다(여러 파일을 한 번에 주면 뒤 파일이 같은 이름의 값을 덮어 앞 값이 빠진다)
        try:
            cfg = _DotenvOnly(_env_file=f)
        except Exception:  # noqa: BLE001, S112 - 오류 문구에 .env 값이 섞일 수 있어 기록하지 않고 건너뛴다
            continue
        for name in type(cfg).model_fields:
            if _is_secret_name(name):
                val = _plain(getattr(cfg, name, None))
                if val and len(val) >= _MIN_SECRET_LEN and val not in out:
                    out.append(val)
    return tuple(out)


def settings_secret_values() -> list[str]:
    """`.env`(Settings 출처)의 비밀 값. 파일 경로·크기·수정 시각을 캐시 키로 쓴다."""
    stamp = []
    for p in _dotenv_files():
        try:
            st = p.stat()
        except OSError:
            continue
        stamp.append((str(p), st.st_size, st.st_mtime_ns))
    return list(_dotenv_secret_values_cached(tuple(stamp)))


def secret_values() -> list[str]:
    """환경변수 + `.env`(Settings) 비밀 값, 긴 값부터(부분 겹침 방지). `redact()`와 같은 출처다."""
    return sorted(set(_env_secret_values()) | set(settings_secret_values()), key=len, reverse=True)


def mask_text(text: str) -> str:
    for value in secret_values():
        text = text.replace(value, MASK)
    for pat, repl in _REPLACEMENTS:
        text = pat.sub(repl, text)
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
