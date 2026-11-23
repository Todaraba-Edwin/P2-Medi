"""RFP-02 조건 2(게스트 비저장)·조건 4(서비스 모드 DB 쓰기 0·`logs/` 새 파일 0) 통합 시험. RFP-12 비저장·H13 조건과 공유.

LLM·공공 API·원격 DB·네트워크 호출 0. 가짜 그래프(`test_be06_l4_metrics._runner`)·가짜 비전(`test_be14_ingest_image.FakeClient`)만 쓴다.
모드 스위치: `MEDIAGENT_MODE`(`app/logging/spans.py:get_mode`, 기본 service). `SpanLogger.path()`가 service면 None(파일 없음), dev면
`MEDIAGENT_LOG_DIR`(없으면 저장소 `logs/`) 아래 파일을 쓴다. 두 모드를 구분해 시험한다.
"""

from __future__ import annotations

import ast
import base64
import io
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import test_be06_l4_metrics as l4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from golden_synth import golden_dict
from test_be14_ingest_image import PNG, FakeClient, MemLedger, _comp, _data_url, _drug

from app.api import chat as chat_api
from app.api import drugs as drugs_api
from app.api import ingest as ingest_api
from app.db.account_repo_pg import PostgresAccountRepo
from app.logging import SpanLogger
from app.logging.spans import REPO_ROOT, Aggregator

WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "COPY", "CREATE", "DROP", "ALTER", "TRUNCATE")
EMAIL = "guest.person@example.com"
TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.guestTokenZZ9.sig"  # guard: fake
CTX = {"age": {"lower": 4, "upper": 4, "unit": "세"}, "pregnant": True}
IMG_Q = "사진질문표지WK3 이 약 뭐예요"


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")} if root.exists() else set()


@pytest.fixture
def db_spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """DB 연결 생성·계정 저장소 진입을 막고 호출을 기록한다(호출되면 예외도 던져 시험이 실패한다)."""
    import psycopg

    calls: dict[str, list[Any]] = {"connect": [], "repo": []}

    def boom_connect(*a: Any, **k: Any) -> Any:
        calls["connect"].append(a)
        raise AssertionError("서비스 모드 게스트 요청이 DB 연결을 만들었다")

    def boom_repo(self: Any, *a: Any, **k: Any) -> Any:
        calls["repo"].append(a)
        raise AssertionError("서비스 모드 게스트 요청이 계정 저장소를 썼다")

    monkeypatch.setattr(psycopg, "connect", boom_connect)
    monkeypatch.setattr(PostgresAccountRepo, "_run_sync", boom_repo)
    try:
        import psycopg_pool

        monkeypatch.setattr(psycopg_pool.ConnectionPool, "__init__", lambda *a, **k: calls["connect"].append("pool"))
    except ImportError:
        pass
    return calls


@pytest.fixture
def service_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEDIAGENT_MODE", "service")
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def _recording_runner(sql: list[str]) -> Any:
    """판정 도구가 쓰는 SQL을 기록하는 가짜 연결(sqlite 메모리)을 단 그래프 실행기."""
    from golden_synth import FakeDur, golden_conn

    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel
    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.api.runner import GraphRunner

    def factory() -> sqlite3.Connection:
        c = golden_conn()
        c.set_trace_callback(sql.append)
        return c

    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=factory)
    return GraphRunner.from_deps(build_deps(dd, ctx, tool_model=ScriptedToolModel(script=list(l4.SCRIPT)),
                                            summary_model=ScriptedSummary([l4.GOOD]), system_prompt="시험용"))


def _chat_app(runner: Any, out: io.StringIO) -> tuple[TestClient, Aggregator]:
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=SpanLogger(mode="service", aggregator=agg))
    return TestClient(app), agg


def _ingest_app() -> tuple[TestClient, FakeClient]:
    fake = FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None}))
    app = FastAPI()
    chat_api.register(app)
    drugs_api.register(app)
    ingest_api.register(app)
    drugs_api.set_provider(app, golden_dict)
    ingest_api.set_vision(app, client=fake, ledger=MemLedger())
    return TestClient(app), fake


# ---------------------------------------------------------------- 모드 스위치
def test_mode_switch_service_has_no_log_path_dev_has(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("MEDIAGENT_MODE", raising=False)
    assert SpanLogger().mode == "service" and SpanLogger().path() is None  # 값이 없으면 가장 엄격한 service
    monkeypatch.setenv("MEDIAGENT_MODE", "bogus")
    assert SpanLogger().mode == "service"
    assert SpanLogger(mode="dev").path() is not None  # 개발 모드는 파일을 쓸 수 있다(대조)


def test_dev_mode_does_write_files_so_the_service_check_is_meaningful(service_env: Path):
    SpanLogger(mode="dev").log(node="chat", end_reason="NORMAL")
    assert any(p.suffix == ".jsonl" for p in (service_env / "logs").rglob("*"))


# ---------------------------------------------------------------- /chat 게스트
def test_guest_chat_no_db_write_no_new_files_no_question_in_logs(service_env: Path, db_spies, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    real_logs = REPO_ROOT / "logs"
    before_real, before_tmp = _tree(real_logs), _tree(service_env)
    sql: list[str] = []
    out = io.StringIO()
    client, agg = _chat_app(_recording_runner(sql), out)
    r = client.post("/chat", json={"question": l4.Q_PAIR, "context": CTX}, headers={"X-User-Email": EMAIL})  # 인증 헤더 없음 = 게스트
    assert r.status_code == 200
    agg.flush()
    # DB 쓰기 0
    assert db_spies == {"connect": [], "repo": []}
    assert sql, "판정 도구가 가짜 연결로 읽었어야 한다(시험 자체 점검)"
    assert not [s for s in sql if s.lstrip().upper().startswith(WRITE_SQL)], sql
    # logs/ 새 파일 0
    assert _tree(service_env) == before_tmp and not (service_env / "logs").exists()
    assert _tree(real_logs) == before_real
    # 로그·집계 출력에 질문·프로필·이메일 없음
    text = out.getvalue() + "\n".join(rec.getMessage() + str(rec.args) for rec in caplog.records)
    assert out.getvalue().strip()
    for s in (l4.MARKER, l4.Q_PAIR, EMAIL, "pregnant"):
        assert s not in text, s
    assert EMAIL not in r.text and l4.MARKER not in r.text  # 응답에 헤더 값·질문 표지가 되돌아오지 않는다


def test_chat_with_bearer_header_still_writes_nothing(service_env: Path, db_spies):
    """토큰이 와도 /chat은 계정 저장소를 쓰지 않는다(로그인 여부와 무관, 질문·대화 비저장)."""
    client, _agg = _chat_app(_recording_runner([]), io.StringIO())
    r = client.post("/chat", json={"question": l4.Q_PAIR, "context": CTX}, headers={"Authorization": TOKEN})
    assert r.status_code == 200
    assert db_spies == {"connect": [], "repo": []} and not (service_env / "logs").exists()
    assert TOKEN not in r.text


# ---------------------------------------------------------------- /ingest/image 게스트
def test_guest_ingest_image_no_db_write_no_files_no_data_url(service_env: Path, db_spies, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    before_real = _tree(REPO_ROOT / "logs")
    client, fake = _ingest_app()
    r = client.post("/ingest/image", json={"image": _data_url(PNG), "question": IMG_Q})  # 인증 헤더 없음
    assert r.status_code == 200 and r.json()["status"] == "OK" and len(fake.calls) == 1
    assert db_spies == {"connect": [], "repo": []}
    assert _tree(service_env) == set() and _tree(REPO_ROOT / "logs") == before_real
    b64 = base64.b64encode(PNG).decode()
    text = caplog.text + " ".join(str(rec.args) for rec in caplog.records)
    for s in (b64[:40], "data:image", IMG_Q, "사진질문표지WK3"):
        assert s not in text and s not in r.text, s


def test_chat_and_ingest_modules_do_not_import_account_repo_or_psycopg():
    app_dir = Path(chat_api.__file__).parent
    for name in ("chat.py", "ingest.py", "vision.py"):
        tree = ast.parse((app_dir / name).read_text(encoding="utf-8"))
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not [m for m in mods if "account_repo" in m or m.startswith("psycopg")], (name, mods)
