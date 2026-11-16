"""MediAgent FastAPI 애플리케이션 진입점.

/health: 서비스 상태 확인 → 200 {"status":"ok"}
/chat: BE-06 채팅(NDJSON 스트림 계약 `chat_event@v1`). 설정이 갖춰지지 않으면 501(의도된 상태, `app.api.chat`)

앱 시작(lifespan, BE-06-22 A): 설정을 읽어 필수 값이 다 있으면 지연 실행기를 붙인다(`app.api.service`). 시작 때는 어디에도 접속하지 않고
무거운 자원은 첫 요청에서 만든다. 필수 값이 하나라도 없으면 실행기를 붙이지 않는다(→ 501). 새 환경변수는 없다(BE-06-19 A).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import chat as chat_api
from .api import service
from .config import Settings, get_settings
from .logging.redact_filter import install_log_redaction

install_log_redaction()  # 서버 로그(uvicorn·httpx 포함)의 비밀값 가리기, httpx INFO URL 차단(S-05·S-06)


def load_settings() -> Settings:
    """lifespan이 쓰는 설정 공급 지점(시험은 이 이름을 가짜로 바꾼다)."""
    return get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runner = service.make_service_runner(load_settings())  # 자원을 만들지 않는다(접속 0). 설정이 모자라면 None
    if runner is not None:
        chat_api.set_runner(app, runner)
    yield


app = FastAPI(title="MediAgent", lifespan=lifespan)
settings = get_settings()
chat_api.register(app)  # POST /chat(BE-06, 설정이 갖춰지지 않으면 501), 요청 형식 오류 422


@app.get("/health")
def health() -> dict:
    """서비스 상태 확인 엔드포인트. 200 OK를 반환한다."""
    return {"status": "ok"}
