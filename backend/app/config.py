"""FastAPI 환경 설정. 환경변수로만 읽는다. 값은 로그·응답에 남기지 않는다.

CLAUDE.md §3의 변수 이름을 필드로 선언. 값은 기본값 없이 선택(없어도 기동 가능).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """환경변수 설정. API 키와 서비스 주소는 필드로 선언하되 기본값 없음."""

    # e약은요 서비스
    drdeasydrug_end_point: str | None = None
    drdeasydrug_api_key: str | None = None

    # 공공 API 클라이언트 공통(BE-02, 비밀 아님). mode: live | snapshot(평가·오프라인, 스냅샷만 읽음)
    mediagent_api_mode: str = "live"
    mediagent_api_cache_dir: str | None = None  # 없으면 메모리 캐시만
    mediagent_api_cache_ttl_seconds: float = 86400.0
    mediagent_api_max_calls: int = 1000

    # 식약처 DUR 품목정보 OpenAPI
    durprdlstinfoservice03_end_point: str | None = None
    durprdlstinfoservice03_api_key: str | None = None

    # 식약처 DUR 성분정보 OpenAPI
    durirdntinfoservice03_end_point: str | None = None
    durirdntinfoservice03_api_key: str | None = None

    # 식약처 의약품 제품 허가정보 OpenAPI
    drugprdtprmsninfoservice08_end_point: str | None = None
    drugprdtprmsninfoservice08_api_key: str | None = None

    # OpenAI
    openai_api_key: str | None = None

    # Anthropic (평가용)
    anthropic_api_key: str | None = None

    # Upstage (평가 질문 생성)
    upstage_api_key: str | None = None

    # Supabase (DB + 인증)
    supabase_db_url: str | None = None
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_jwks_url: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = False


def get_settings() -> Settings:
    """전역 설정 싱글톤."""
    return Settings()
