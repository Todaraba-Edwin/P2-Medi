"""PRD-17 ⑫ ⑧ B(2026-11-20 사용자 "Recap 45 초안 승인·⑧ B"): 서버 접근 로그를 끈다. 네트워크·LLM·원격 DB·`.env` 열람 0.

개인정보 처리방침 v2 §4는 "법령에 따라 보존해야 하는 정보는 없습니다."만 적고, §2는 "서버 로그에는 시각·걸린 시간·종료 사유·개수만
남고 질문 문장은 남지 않습니다."라고 적는다. uvicorn 접근 로그는 요청마다 접속 IP·요청 경로를 찍으므로 모든 실행 경로에서 끈다.

1. 실행 경로: `backend/Dockerfile` CMD, `README.md`·`P2-doc/PJ2-배포-로컬-터널.md`의 `app.main:app` 실행 명령(launchd plist 포함),
   `backend/scripts/dev_fake_server.py`가 접근 로그를 끈다. 명령은 uvicorn CLI 파서로 풀어 `access_log=False`인지 본다.
2. 앱 로그: 서비스 모드 `/chat` 한 요청의 집계 출력과 모든 로거 레코드에 접속 IP·질문 문장이 없다.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import test_be06_l4_metrics as l4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.main import main as uvicorn_cli

from app.api import chat as chat_api
from app.logging import SpanLogger
from app.logging.spans import Aggregator

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DOC_FILES = (REPO / "README.md", REPO / "P2-doc" / "PJ2-배포-로컬-터널.md")
CLIENT_IP = "203.0.113.77"  # 문서용 주소(RFC 5737)


def _parse(args: list[str]) -> dict[str, Any]:
    """uvicorn CLI 파서로 인자를 풀어 본다(서버는 띄우지 않는다)."""
    ctx = uvicorn_cli.make_context("uvicorn", list(args), resilient_parsing=False)
    return ctx.params


def _dockerfile_cmd() -> list[str]:
    line = next(x for x in (BACKEND / "Dockerfile").read_text(encoding="utf-8").splitlines() if x.startswith("CMD "))
    cmd = json.loads(line[len("CMD "):])
    assert cmd[0] == "uvicorn"
    return cmd[1:]


def test_parser_default_keeps_access_log_so_the_flag_matters():
    assert _parse(["app.main:app"])["access_log"] is True
    assert _parse(["app.main:app", "--no-access-log"])["access_log"] is False


def test_dockerfile_cmd_disables_access_log():
    params = _parse(_dockerfile_cmd())
    assert params["access_log"] is False
    assert params["app"] == "app.main:app" and params["proxy_headers"] is True and params["workers"] == 1


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_documented_run_commands_disable_access_log(doc: Path):
    text = doc.read_text(encoding="utf-8")
    cmds = [ln.strip() for ln in text.splitlines() if re.search(r"-m uvicorn app\.main:app", ln)]
    assert cmds, doc
    for c in cmds:
        args = shlex.split(c.strip("`"))
        assert _parse(args[args.index("uvicorn") + 1:])["access_log"] is False, c


def test_launchd_plist_disables_access_log():
    text = (REPO / "P2-doc" / "PJ2-배포-로컬-터널.md").read_text(encoding="utf-8")
    block = re.search(r"<key>ProgramArguments</key>\s*<array>(.*?)</array>", text, re.S)
    assert block is not None
    args = re.findall(r"<string>(.*?)</string>", block[1])
    assert "uvicorn" in args
    assert _parse(args[args.index("uvicorn") + 1:])["access_log"] is False


def test_dev_fake_server_disables_access_log(monkeypatch):
    import uvicorn

    monkeypatch.syspath_prepend(str(BACKEND / "scripts"))
    import dev_fake_server as dfs  # noqa: PLC0415

    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    dfs.main(["--port", "8124"])
    assert seen["access_log"] is False


def test_service_chat_logs_have_no_client_ip_or_question(caplog):
    caplog.set_level(logging.DEBUG)
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, l4._runner(l4.SCRIPT, [l4.GOOD]), metrics=SpanLogger(mode="service", aggregator=agg))
    r = TestClient(app).post("/chat", json={"question": l4.Q_PAIR, "context": {}}, headers={"X-Forwarded-For": CLIENT_IP})
    assert r.status_code == 200
    agg.flush()
    text = out.getvalue() + "\n".join(rec.getMessage() for rec in caplog.records)
    assert out.getvalue().strip()  # 집계 한 줄은 남는다
    for s in (CLIENT_IP, "testclient", l4.MARKER, l4.Q_PAIR):
        assert s not in text, s
