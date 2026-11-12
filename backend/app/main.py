"""MediAgent FastAPI 애플리케이션 진입점.

/health: 서비스 상태 확인 → 200 {"status":"ok"}
/chat: BE-06 채팅(NDJSON 스트림 계약 `chat_event@v1`). 그래프 연결 전이라 501(의도된 상태, `app.api.chat`)
"""

from fastapi import FastAPI

from .api import chat as chat_api
from .config import get_settings
from .logging.redact_filter import install_log_redaction

install_log_redaction()  # 서버 로그(uvicorn·httpx 포함)의 비밀값 가리기, httpx INFO URL 차단(S-05·S-06)

app = FastAPI(title="MediAgent")
settings = get_settings()
chat_api.register(app)  # POST /chat(BE-06, 그래프 연결 전이라 501), 요청 형식 오류 422


@app.get("/health")
def health() -> dict:
    """서비스 상태 확인 엔드포인트. 200 OK를 반환한다."""
    return {"status": "ok"}
