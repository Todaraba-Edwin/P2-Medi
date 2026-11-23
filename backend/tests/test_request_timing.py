"""요청 소요 시간 로그: 형식·템플릿 경로·비노출·끔 스위치·느린 요청 경고. 네트워크 0."""

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging import request_timing as rt

UUID = "123e4567-e89b-12d3-a456-426614174000"


def _app(enabled=True):
    app = FastAPI()

    @app.get("/profiles/{pid}")
    def prof(pid: str):
        return {"id": pid, "email": "a@b.c"}

    @app.post("/chat")
    def chat(body: dict):
        return {"answer": "secret-answer"}

    app.add_middleware(rt.RequestTimingMiddleware, enabled=enabled)
    return TestClient(app)


def _lines(caplog):
    return [r for r in caplog.records if r.name == "app.request_timing"]


def test_line_format_and_template(caplog):
    caplog.set_level(logging.INFO)
    _app().get(f"/profiles/{UUID}?q=타이레놀&token=abc", headers={"Authorization": "Bearer tok-xyz"})
    (rec,) = _lines(caplog)
    assert rec.levelno == logging.INFO
    assert re.fullmatch(r"req GET /profiles/\{pid\} 200 \d+ms", rec.getMessage())


def test_no_identifiers_query_body_headers(caplog):
    caplog.set_level(logging.DEBUG)
    c = _app()
    c.get(f"/profiles/{UUID}?q=타이레놀", headers={"Authorization": "Bearer tok-xyz", "X-Forwarded-For": "203.0.113.9"})
    c.post("/chat", json={"question": "아스피린 같이 먹어도 돼요?"})
    c.get(f"/nope/{UUID}/12345/x?q=secret")
    text = "\n".join(r.getMessage() for r in _lines(caplog))
    assert len(_lines(caplog)) == 3
    for s in (UUID, "타이레놀", "tok-xyz", "203.0.113.9", "아스피린", "secret", "12345", "a@b.c", "testclient"):
        assert s not in text, s
    assert "req POST /chat 200" in text
    assert "req GET /nope/{id}/{id} 404" in text


def test_disabled_switch(caplog):
    caplog.set_level(logging.DEBUG)
    assert _app(enabled=False).get("/profiles/1").status_code == 200
    assert not _lines(caplog)


def test_slow_request_warns(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rt, "SLOW_MS", 0.0)
    _app().get("/profiles/1")
    (rec,) = _lines(caplog)
    assert rec.levelno == logging.WARNING and rec.getMessage().startswith("slow req GET /profiles/{pid} 200")


@pytest.mark.parametrize("val,exp", [(None, True), ("0", False), ("false", False), ("off", False), ("1", True)])
def test_setting_env(monkeypatch, val, exp):
    monkeypatch.delenv("MEDIAGENT_REQUEST_TIMING", raising=False)
    if val is not None:
        monkeypatch.setenv("MEDIAGENT_REQUEST_TIMING", val)
    assert Settings(_env_file=None).mediagent_request_timing is exp
