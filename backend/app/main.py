"""MediAgent FastAPI 애플리케이션 진입점.

/health: 서비스 상태 확인 → 200 {"status":"ok"}
/chat: BE-06 채팅(NDJSON 스트림 계약 `chat_event@v1`). 설정이 갖춰지지 않으면 501(의도된 상태, `app.api.chat`)
/me·/legal/{doc_type}·/consents·/profiles: BE-11 계정 API(`app.api.me`·`app.api.account`, 토큰 검증 `app.security.auth`).
  검증기가 없으면 토큰이 온 요청은 501, 계정 저장소(`account.set_repo`)가 없으면 계정 API는 501. 원격 `account` 스키마가 아직 적용 전이라
  lifespan은 저장소를 붙이지 않는다(적용 뒤 `PostgresAccountRepo.from_dsn`을 붙이는 한 줄을 더한다).

앱 시작(lifespan, BE-06-22 A·BE-17-01 A): 설정을 읽어 필수 값이 다 있으면 지연 실행기를 붙이고, 백그라운드 스레드로 무거운 자원을
한 번 만들기 시작한다. lifespan 자체는 접속을 기다리지 않고 바로 끝난다(`/health` 즉시 응답). 스위치 `MEDIAGENT_WARMUP`을 끄면
첫 요청에서 만든다. 필수 값이 하나라도 없으면 실행기도 준비도 없다(→ 501). 필수 설정에 새 환경변수는 없다(BE-06-19 A).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import chat as chat_api
from .api import drugs as drugs_api
from .api import me as me_api
from .api import service
from .config import Settings, get_settings
from .logging.console import install_app_console_logging
from .logging.redact_filter import install_log_redaction
from .security import auth

install_log_redaction()  # 서버 로그(uvicorn·httpx 포함)의 비밀값 가리기, httpx INFO URL 차단(S-05·S-06)
install_app_console_logging()  # BE-17 후속: `app.*` INFO 줄을 stderr에(uvicorn은 루트 처리기를 두지 않아 INFO가 버려졌다). 멱등


def load_settings() -> Settings:
    """lifespan이 쓰는 설정 공급 지점(시험은 이 이름을 가짜로 바꾼다)."""
    return get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    install_app_console_logging()  # 시작 뒤 로깅 설정이 바뀌었어도 처리기 하나를 보장한다(이미 있으면 그대로)
    settings_now = load_settings()
    runner =service.make_service_runner(settings_now)  # 자원을 만들지 않는다(접속 0). 설정이 모자라면 None
    if runner is not None:
        chat_api.set_runner(app, runner)
        service.start_warmup(runner, settings_now)  # BE-17-01 A: 백그라운드 스레드만 띄우고 기다리지 않는다(스위치 끔이면 안 띄움)
    # FE-04-13 A: 프로필 약 검색은 채팅 자원의 사전을 공유한다(DB 추가 조회 0). 실행기가 없으면 공급자 없음 → 501
    drugs_api.set_provider(app, runner.drug_dict if isinstance(runner, service.LazyGraphRunner) else None)
    auth.set_verifier(app, auth.build_verifier(settings_now))  # 접속 0. 설정이 모자라면 None → 토큰이 온 /me는 501
    yield


app = FastAPI(title="MediAgent", lifespan=lifespan)
settings = get_settings()
chat_api.register(app)  # POST /chat(BE-06, 설정이 갖춰지지 않으면 501), 요청 형식 오류 422. 게스트 허용, 토큰을 읽지 않는다
me_api.register(app)  # BE-11 계정 API(chat 뒤에 등록: 요청 형식 오류 처리기를 계정 경로 분기로 바꾼다), 인증 오류 401·501·503
drugs_api.register(app)  # POST /drugs/search 프로필 약 사전 검색(FE-04-13 A, 로그인 필요, 계정 오류 처리기 공유)


@app.get("/health")
def health() -> dict:
    """서비스 상태 확인 엔드포인트. 200 OK를 반환한다."""
    return {"status": "ok"}
