"""FastAPI 환경 설정. 환경변수로만 읽는다. 값은 로그·응답에 남기지 않는다.

CLAUDE.md §3의 변수 이름을 필드로 선언. 값은 기본값 없이 선택(없어도 기동 가능).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """환경변수 설정. API 키와 서비스 주소는 필드로 선언하되 기본값 없음."""

    # e약은요 서비스
    drdeasydrug_end_point: str | None = None
    drdeasydrug_api_key: str | None = None

    # 식약처 DUR 품목정보 OpenAPI
    durprdlstinfoservice03_end_point: str | None = None
    durprdlstinfoservice03_api_key: str | None = None

    # 식약처 DUR 성분정보 OpenAPI
    durirdntinfoservice03_end_point: str | None = None
    durirdntinfoservice03_api_key: str | None = None

    # 식약처 의약품 제품 허가정보 OpenAPI
    drugprdtprmsninfservice08_end_point: str | None = None
    drugprdtprmsninfservice08_api_key: str | None = None

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
