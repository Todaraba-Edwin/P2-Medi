"""서비스 헬스 체크 테스트.

/health 엔드포인트가 200을 반환하는지 확인.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(app)


def test_health_returns_200(client: TestClient) -> None:
    """GET /health가 200 OK를 반환한다."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
