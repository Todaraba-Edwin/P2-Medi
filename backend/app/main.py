"""MediAgent FastAPI 애플리케이션 진입점.

/health: 서비스 상태 확인 → 200 {"status":"ok"}
"""

from fastapi import FastAPI

from .config import get_settings
from .logging.redact_filter import install_log_redaction

install_log_redaction()  # 서버 로그(uvicorn·httpx 포함)의 비밀값 가리기, httpx INFO URL 차단(S-05·S-06)

app = FastAPI(title="MediAgent")
settings = get_settings()


@app.get("/health")
def health() -> dict:
    """서비스 상태 확인 엔드포인트. 200 OK를 반환한다."""
    return {"status": "ok"}
