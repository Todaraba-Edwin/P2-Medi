"""FastAPI 환경 설정. 환경변수로만 읽는다. 값은 로그·응답에 남기지 않는다.

CLAUDE.md §3의 변수 이름을 필드로 선언. 값은 기본값 없이 선택(없어도 기동 가능).
키·DSN 필드(`*_api_key`·`*_secret_key`·`*_publishable_key`·`supabase_db_url`)는 `SecretStr`이라 `repr`·`str`·`model_dump()`에
원문이 나오지 않는다(S-04, 2026-11-11). 원문은 쓰는 곳에서 `reveal(settings.x)`로만 꺼낸다.
"""

from pathlib import Path
from typing import Any, Literal

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


# 사용자 최종 결정 2026-11-23: only OpenAI(gpt-6-luna 비전). Upstage 코드는 삭제하지 않고 `MEDIAGENT_VISION_PROVIDER=upstage`로만 켠다.
# Upstage를 서비스에 켜려면 처리방침(사진 수탁자 Upstage)·사진 고지·요금제 조건을 먼저 맞출 것.
DEFAULT_VISION_PROVIDER: Literal["upstage", "openai"] = "openai"


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

    # 에이전트(도구 선택·요약) 모델 이름(AG-01 `:31`, 비밀 아님, 환경변수 `MEDIAGENT_AGENT_MODEL`). 기본은 `llm.MODEL`과 같은 값이다
    # (시험이 맞춘다). 서비스 경로(`build_deps(service=True)`)만 이 칸을 따른다. 평가·개발 경로는 평가 고정(PJ2-RFP.md 5장·9장)이라
    # 이 칸과 무관하게 `llm.MODEL`을 쓰고, 다른 모델이 필요하면 `build_deps(model_name=...)`를 명시한다. 비용 단가는 `gpt-6-luna` 기준이다.
    mediagent_agent_model: str = "gpt-6-luna"

    # 서버 시작 직후 백그라운드 자원 준비(BE-17-01·02 A). 기본 켬. `MEDIAGENT_WARMUP=0`(false·off)이면 지금처럼 첫 요청에서 만든다
    mediagent_warmup: bool = True

    # HTTP 요청 소요 시간 로그(`메서드 경로템플릿 상태 ms` 한 줄, 식별·쿼리·본문 없음). 기본 켬. `MEDIAGENT_REQUEST_TIMING=0`(false·off)이면 끈다
    mediagent_request_timing: bool = True

    # 사진 약 이름 판독 제공자(BE-14, 비밀 아님, 환경변수 `MEDIAGENT_VISION_PROVIDER`). `upstage`는 OCR + solar-pro4, `openai`는 gpt-6-luna 비전.
    # 사용자 최종 결정 2026-11-23: 기본값 openai, Upstage는 `MEDIAGENT_VISION_PROVIDER=upstage`로만 켠다(켜기 전 처리방침·고지·요금제 조건 확인).
    # 처방전·약봉투 사진 고지: 현재 처리방침은 v7(최종안, 2026-11-23 게시)이고 기본이 OpenAI라 사진 고지는 "OpenAI"로 복원됨(커밋 fcd785e). Upstage를 켤 때만 처리방침 수탁자·고지·요금제 조건을 먼저 맞출 것.
    mediagent_vision_provider: Literal["upstage", "openai"] = DEFAULT_VISION_PROVIDER
    # Upstage 사진 판독 엔드포인트·모델(비밀 아님, 선택). 비면 글로벌 `https://api.upstage.ai/v1`·`solar-pro4`. 한국 리전(`kr.api.upstage.ai`,
    # Closed Beta) 접근 승인 뒤 `UPSTAGE_BASE_URL`(https 필수, `/v1` 생략 가능)과 `UPSTAGE_MODEL`(한국 리전 목록의 모델)만 넣으면 전환된다.
    # 값은 로그·오류에 남기지 않는다(검증 실패는 변수 이름만 알린다).
    upstage_base_url: str | None = None
    upstage_model: str | None = None

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

    # 로컬 Postgres RLS 시험 전용 DSN(BE-11-14 A). 런타임 코드는 쓰지 않는다. 선언만 해 두는 이유: `.env`에 이 줄이 있을 때
    # 선언이 없으면 기본 extra="forbid"로 `get_settings()`가 실패한다(2026-11-19 재현). 시험은 환경변수에서만 읽는다.
    local_pg_dsn: SecretStr | None = None

    # 프런트(@supabase/ssr 로그인)용 공개 변수(BE-11-18 A). 백엔드 런타임은 쓰지 않는다. 루트 `.env`에 함께 있어
    # 선언이 없으면 extra="forbid"로 `get_settings()`가 실패한다(2026-11-19 메인 재현). publishable 키도 원문 비노출로 SecretStr
    next_public_supabase_url: str | None = None
    next_public_supabase_publishable_key: SecretStr | None = None

    # 사용자 본인 테스트 계정 식별자(개인정보, 2026-11-20). 서비스 동작에 쓰지 않고 로그·응답에 남기지 않는다. 루트 `.env`에
    # 있어 선언이 없으면 extra="forbid"로 `get_settings()`가 실패한다(2026-11-20 메인 재현). 원문 비노출로 SecretStr
    tester_id: SecretStr | None = None

    # 개인정보 보호책임자 이름·연락 이메일(개인정보, PRD-17 ⑫, 2026-11-20). 약관 시드 게시(be11_account_migrate) 때
    # `{{PRIVACY_CONTACT}}` 칸을 채우는 데만 쓰고 저장소·로그·응답에 남기지 않는다. 루트 `.env`에 있어 선언이 없으면
    # extra="forbid"로 `get_settings()`가 실패한다(2026-11-20 메인 재현). 원문 비노출로 SecretStr
    privacy_officer_name: SecretStr | None = None
    privacy_officer_email: SecretStr | None = None

    # OpenAI 관리자 키(사용량·비용 조회 Costs/Usage API 전용, DevOps 사용량 보고, 2026-11-22). 서비스·평가 호출에는 쓰지 않고
    # (일반 `OPENAI_API_KEY`와 다른 키) 로그·응답에 남기지 않는다. 루트 `.env`에 있어 선언이 없으면 extra="forbid"로
    # `get_settings()`가 실패한다. 원문 비노출로 SecretStr
    openai_admin_key: SecretStr | None = None

    # 운영자 카카오톡 "나에게 보내기" 알림(DevOps, 2026-11-24). 키가 없으면 완전 비활성. 값은 로그·응답에 남기지 않는다(SecretStr).
    # `MEDIAGENT_NOTIFY=0`(false·off)이면 키가 있어도 끈다(비밀 아님, 기본 켬).
    kakao_rest_api_key: SecretStr | None = None
    kakao_client_secret: SecretStr | None = None
    kakao_refresh_token: SecretStr | None = None
    mediagent_notify: bool = True

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
