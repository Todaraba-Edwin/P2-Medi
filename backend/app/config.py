"""FastAPI 환경 설정. 환경변수로만 읽는다. 값은 로그·응답에 남기지 않는다.

CLAUDE.md §3의 변수 이름을 필드로 선언. 값은 기본값 없이 선택(없어도 기동 가능).
키·DSN 필드(`*_api_key`·`*_secret_key`·`*_publishable_key`·`supabase_db_url`)는 `SecretStr`이라 `repr`·`str`·`model_dump()`에
원문이 나오지 않는다(S-04, 2026-11-11). 원문은 쓰는 곳에서 `reveal(settings.x)`로만 꺼낸다.
"""

from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 저장소 루트(backend/app/config.py → parents[2]). `cd backend`로 띄워도 루트 `.env`를 찾게 한다(2026-11-17 /chat 501 재현).
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


def default_env_files() -> tuple[str, ...]:
    """읽을 `.env` 후보. 현재 폴더 `.env`가 우선이고, 없으면 저장소 루트 `.env`를 읽는다.

    pydantic-settings는 튜플에서 **뒤 파일이 앞 파일을 덮고** 없는 파일은 건너뛰므로 우선순위가 높은 현재 폴더를 뒤에 둔다.
    `REPO_ROOT`는 호출할 때 읽는다(시험에서 monkeypatch로 가짜 폴더로 바꿀 수 있게).
    """
    return (str(REPO_ROOT / ".env"), ".env")


class Settings(BaseSettings):
    """환경변수 설정. API 키와 서비스 주소는 필드로 선언하되 기본값 없음."""

    # e약은요 서비스
    drdeasydrug_end_point: str | None = None
    drdeasydrug_api_key: SecretStr | None = None

    # 공공 API 클라이언트 공통(BE-02, 비밀 아님). mode: live | snapshot(평가·오프라인, 스냅샷만 읽음)
    mediagent_api_mode: str = "live"
    mediagent_api_cache_dir: str | None = None  # 없으면 메모리 캐시만
    mediagent_api_cache_ttl_seconds: float = 86400.0
    mediagent_api_max_calls: int = 1000

    # 식약처 DUR 품목정보 OpenAPI
    durprdlstinfoservice03_end_point: str | None = None
    durprdlstinfoservice03_api_key: SecretStr | None = None

    # 식약처 DUR 성분정보 OpenAPI
    durirdntinfoservice03_end_point: str | None = None
    durirdntinfoservice03_api_key: SecretStr | None = None

    # 식약처 의약품 제품 허가정보 OpenAPI
    drugprdtprmsninfoservice08_end_point: str | None = None
    drugprdtprmsninfoservice08_api_key: SecretStr | None = None

    # OpenAI
    openai_api_key: SecretStr | None = None

    # Anthropic (평가용)
    anthropic_api_key: SecretStr | None = None

    # Upstage (평가 질문 생성)
    upstage_api_key: SecretStr | None = None

    # Supabase (DB + 인증)
    supabase_db_url: SecretStr | None = None
    supabase_url: str | None = None
    supabase_publishable_key: SecretStr | None = None
    supabase_secret_key: SecretStr | None = None
    supabase_jwks_url: str | None = None

    # hide_input_in_errors: 검증 오류(ValidationError)에 .env 입력 값(input_value=…)을 담지 않는다(sec-guard)
    model_config = SettingsConfigDict(env_file=default_env_files(), case_sensitive=False, hide_input_in_errors=True)


def get_settings() -> Settings:
    """전역 설정. 현재 폴더와 저장소 루트의 `.env`를 차례로 본다(`default_env_files`)."""
    return Settings(_env_file=default_env_files())


def reveal(value: Any) -> str | None:
    """`SecretStr`(또는 시험의 평문 `str`)에서 원문을 꺼낸다. 비었으면 None. 꺼낸 값은 호출에만 쓰고 출력하지 않는다."""
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return raw if isinstance(raw, str) and raw else None
