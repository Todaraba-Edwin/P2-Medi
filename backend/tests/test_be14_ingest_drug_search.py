"""`POST /ingest/drugs/search`(게스트 허용 약 이름 검색, 2026-11-23 아스피린 A) 시험. LLM·네트워크·DB 호출 0. 합성 사전(`golden_dict`) 사용."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_T500, golden_dict  # noqa: E402

from app.api import chat as chat_api  # noqa: E402
from app.api import drugs as drugs_api  # noqa: E402
from app.api import ingest as ingest_api  # noqa: E402
from app.api import me as me_api  # noqa: E402

MARKER = "비밀검색표지QZ8"
EXACT = "타이레놀정500밀리그람"


@pytest.fixture(autouse=True)
def _reset_rate() -> None:
    ingest_api._rate_hits.clear()


def _app(provider: Any = golden_dict) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    drugs_api.register(app)
    ingest_api.register(app)
    if provider is not None:
        drugs_api.set_provider(app, provider)
    return TestClient(app)


def _post(c: TestClient, q: Any, **h: str) -> Any:
    return c.post("/ingest/drugs/search", json={"q": q}, headers=h)


def test_guest_candidates_and_same_shape_as_drugs_search() -> None:
    r = _post(_app(), "타이레놀")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"candidates", "needs_confirmation", "dict_version"}
    assert body["candidates"]
    assert body == drugs_api.to_out(golden_dict(), "타이레놀").model_dump(mode="json")


@pytest.mark.parametrize("h", [{}, {"Authorization": "Bearer " + "garbage.token.value"}])
def test_exact_and_token_not_read(h: dict[str, str]) -> None:
    r = _post(_app(), EXACT, **h)
    assert r.status_code == 200
    c0 = r.json()["candidates"][0]
    assert c0["item_seq"] == SEQ_T500 and c0["match_type"] == "exact"


@pytest.mark.parametrize("q", ["가", " 가 ", "", "x" * 101])
def test_length_422(q: str) -> None:
    r = _post(_app(), q)
    assert r.status_code == 422 and "x" * 101 not in r.text


def test_rate_limit_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_api, "SEARCH_RATE_MAX", 3)
    c = _app()
    assert [_post(c, "타이").status_code for _ in range(3)] == [200] * 3
    r = _post(c, "타이")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


def test_no_provider_501_and_failure_503_without_q(caplog: pytest.LogCaptureFixture) -> None:
    assert _post(_app(None), MARKER).status_code == 501

    def boom() -> Any:
        raise ConnectionError(MARKER)

    caplog.set_level(logging.DEBUG)
    r = _post(_app(boom), MARKER)
    assert r.status_code == 503 and r.json()["code"] == "DICT_UNAVAILABLE"
    assert MARKER not in r.text and MARKER not in caplog.text


def test_q_not_in_logs_or_response(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    r = _post(_app(), MARKER)
    assert r.status_code == 200 and MARKER not in r.text
    assert MARKER not in caplog.text


def test_get_not_allowed_and_in_openapi() -> None:
    c = _app()
    assert c.get("/ingest/drugs/search", params={"q": "타이"}).status_code == 405
    assert "/ingest/drugs/search" in c.get("/openapi.json").json()["paths"]
