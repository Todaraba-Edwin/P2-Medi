"""BE-17 후속 시험: 서버 준비 단계 로그가 터미널(stderr)에 보인다(2026-11-19). LLM·공공 API·원격 DB 호출 0, `.env` 미사용.

- 원인: uvicorn은 `uvicorn.*` 로거에만 처리기를 붙이고 루트에는 붙이지 않아 `app.*` INFO가 `logging.lastResort`(WARNING)에서 버려졌다.
- 고침: `app.logging.console.install_app_console_logging()`이 `app` 로거에 stderr 처리기 하나(비밀값 가리기 필터 포함)를 붙인다.
- 단계 줄: `default_resources`가 `{warmup|resources}: {단계} starting/done in N.NNs (개수)`를 남긴다. 실제 접속·로더는 가짜로 바꾼다.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import golden_dict  # noqa: E402

import app.main as main_mod  # noqa: E402
from app.agent.graph import wiring  # noqa: E402
from app.agent.tools import corpus_remote  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import service  # noqa: E402
from app.config import Settings  # noqa: E402
from app.logging.console import app_console_handlers, install_app_console_logging  # noqa: E402
from app.tools import drug_dict as drug_dict_mod  # noqa: E402
from app.tools import dur as dur_mod  # noqa: E402

SECRET = "QQQQ-가짜비밀표지-7731"
FAKE_KEY = "sk-FAKEFAKEFAKE12345678"
ENV_NAMES = service.REQUIRED_ENV
STEPS = ["db connection", "drug dictionary", "corpus (fetch + bm25 index)", "agent wiring"]
CHUNKS = [{"chunk_id": f"c{i}", "text": f"합성 근거 문장 {i}", "layer": "L1"} for i in range(3)]


@pytest.fixture(autouse=True)
def _console(monkeypatch):
    for n in ENV_NAMES:
        for name in (n, n.upper(), n.lower()):
            monkeypatch.delenv(name, raising=False)
    install_app_console_logging()
    yield


def _settings(**override: Any) -> Settings:
    vals: dict[str, Any] = {n.lower(): f"{SECRET}-{i}" for i, n in enumerate(ENV_NAMES)}
    vals["supabase_db_url"] = f"postgresql://user:{SECRET}@db.example.invalid:5432/postgres"
    vals["mediagent_warmup"] = True
    vals.update(override)
    return Settings(_env_file=None, **{k: v for k, v in vals.items() if v is not None})


def _app_lines(err: str) -> list[str]:
    """stderr에서 이 처리기가 쓴 `app.api.service` 줄의 메시지 부분만."""
    prefix = "app.api.service: "
    return [ln.split(prefix, 1)[1] for ln in err.splitlines() if prefix in ln]


class FakeConn:
    def __init__(self, log: list[str]) -> None:
        self.read_only = False
        self.closed = False
        self._log = log

    def close(self) -> None:
        self.closed = True
        self._log.append("close")


@pytest.fixture
def fake_backend(monkeypatch):
    """`default_resources`의 접속·로더·배선을 가짜로 바꾼다. 연결 수와 DSN 전달만 기록한다(DSN은 어디에도 찍지 않는다)."""
    import psycopg

    state: dict[str, Any] = {"connects": 0, "log": [], "chunks": list(CHUNKS)}

    def connect(dsn: str) -> FakeConn:
        assert SECRET in dsn
        state["connects"] += 1
        return FakeConn(state["log"])

    def dict_from_db(conn_factory, *, paramstyle="format", **_kw):  # noqa: ARG001
        conn = conn_factory()
        state["dict_conn"] = conn
        conn.close()
        return golden_dict()

    def load_chunks(conn_factory, *, batch=5000):  # noqa: ARG001
        conn = conn_factory()
        state["corpus_conn"] = conn
        conn.close()
        return list(state["chunks"]), ["chunk_id", "text"]

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(drug_dict_mod.DrugDict, "from_db", classmethod(lambda cls, f, **kw: dict_from_db(f, **kw)))
    monkeypatch.setattr(corpus_remote, "load_chunks_from_db", load_chunks)
    monkeypatch.setattr(dur_mod.DurClient, "from_settings", classmethod(lambda cls, s: object()))
    monkeypatch.setattr(wiring, "build_tool_context", lambda *a, **kw: "ctx")
    monkeypatch.setattr(wiring, "build_deps", lambda *a, **kw: "deps")
    return state


def _expected(label: str) -> list[str]:
    out = [f"{label} starting"]
    for s in STEPS:
        out += [f"{label}: {s} starting", f"{label}: {s} done"]
    return [*out, f"{label} done"]


def _shape(lines: list[str]) -> list[str]:
    """`... done in 1.23s (n chunks)` → `... done` 꼴로 줄여 순서만 비교한다."""
    return [ln.split(" in ", 1)[0] if " done in " in ln else ln for ln in lines]


# --------------------------------------------------------------------------- 처리기
def test_console_handler_is_single_after_repeated_install_and_lifespans(monkeypatch):
    monkeypatch.setattr(main_mod, "load_settings", lambda: Settings(_env_file=None, mediagent_warmup=False))
    for _ in range(3):
        install_app_console_logging()
    try:
        for _ in range(2):
            with TestClient(main_mod.app) as client:
                assert client.get("/health").status_code == 200
    finally:
        chat_api.set_runner(main_mod.app, None)
    assert len(app_console_handlers()) == 1
    assert logging.getLogger("app").getEffectiveLevel() == logging.INFO


def test_app_info_goes_to_stderr_with_uvicorn_like_prefix(capsys):
    service.logger.info("warmup starting")
    err = capsys.readouterr().err
    assert "INFO:     app.api.service: warmup starting" in err.splitlines()


def test_secrets_are_redacted_through_the_real_handler(capsys):
    service.logger.info("probe %s %s", FAKE_KEY, f"postgresql://u:{SECRET}@h/db")
    err = capsys.readouterr().err
    assert "probe" in err and FAKE_KEY not in err and SECRET not in err


def test_no_duplicate_when_root_already_prints_to_console(capsys):
    root = logging.getLogger()
    h = logging.StreamHandler(sys.stderr)
    root.addHandler(h)
    try:
        service.logger.warning("dedupe-probe-1")
    finally:
        root.removeHandler(h)
    assert capsys.readouterr().err.count("dedupe-probe-1") == 1


def test_cause_root_warning_drops_info_unless_app_logger_is_set():
    """원인 재현: 루트 수준이 WARNING(uvicorn 기본, 루트 처리기 없음)이면 `app` 밖의 로거는 INFO를 버린다.
    `app` 로거는 INFO로 두었으므로 INFO가 처리기까지 간다. lastResort는 WARNING 이상만 찍는다."""
    root = logging.getLogger()
    old = root.level
    root.setLevel(logging.WARNING)
    try:
        assert not logging.getLogger("notapp.probe").isEnabledFor(logging.INFO)
        assert logging.getLogger("app.api.service").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(old)
    assert logging.lastResort is not None and logging.lastResort.level == logging.WARNING


# --------------------------------------------------------------------------- 단계 줄
def test_warmup_logs_each_step_in_order_with_counts(fake_backend, capsys):
    runner = service.make_service_runner(_settings())
    assert runner.warm() is True and runner.ready
    err = capsys.readouterr().err
    lines = [ln for ln in _app_lines(err) if ln.startswith("warmup")]
    assert _shape(lines) == _expected("warmup")
    gd = golden_dict()
    assert any(ln.startswith("warmup: drug dictionary done in ")
               and ln.endswith(f"({len(gd.products)} products, {len(gd.ingredients)} ingredients)") for ln in lines)
    assert any(ln.startswith("warmup: corpus (fetch + bm25 index) done in ") and ln.endswith(f"({len(CHUNKS)} chunks)") for ln in lines)
    assert lines[-1].startswith("warmup done in ") and lines[-1].endswith("s")
    assert SECRET not in err and "postgresql://" not in err and "db.example" not in err
    # 첫 연결(db connection 단계)을 사전이 그대로 쓴다: 연결은 사전 1 + 코퍼스 1 = 2개, 모두 닫혔다
    assert fake_backend["connects"] == 2 and fake_backend["dict_conn"].read_only and fake_backend["corpus_conn"].read_only
    assert fake_backend["dict_conn"] is not fake_backend["corpus_conn"] and fake_backend["log"] == ["close", "close"]


def test_first_request_path_uses_resources_prefix(fake_backend, capsys):  # noqa: ARG001
    runner = service.make_service_runner(_settings(mediagent_warmup=False))
    assert service.start_warmup(runner, _settings(mediagent_warmup=False)) is None
    assert runner._resources() == "deps"  # 라우트가 첫 요청에서 부르는 경로
    lines = _app_lines(capsys.readouterr().err)
    assert "chat resources warmup disabled (MEDIAGENT_WARMUP); resources are built on the first request" in lines
    assert _shape([ln for ln in lines if ln.startswith("resources")]) == _expected("resources")
    assert not any(ln.startswith("warmup") for ln in lines)


def test_failed_step_logs_type_and_overall_failure_only(fake_backend, capsys):
    fake_backend["chunks"] = []  # 원격 코퍼스 미적재
    runner = service.make_service_runner(_settings())
    assert runner.warm() is False and not runner.ready
    lines = _app_lines(capsys.readouterr().err)
    assert any(ln.startswith("warmup: corpus (fetch + bm25 index) failed: RuntimeError after ") for ln in lines)
    assert lines[-1].startswith("warmup failed: RuntimeError after ")
    assert not any("agent wiring" in ln for ln in lines)
    assert not any("corpus_chunks" in ln for ln in lines)  # 예외 메시지는 남기지 않는다(종류 이름만)


def test_missing_settings_line_is_visible(capsys):
    assert service.make_service_runner(_settings(supabase_db_url=None)) is None
    lines = _app_lines(capsys.readouterr().err)
    assert "chat runner not attached (/chat stays 501); missing settings: SUPABASE_DB_URL" in lines


def test_primed_factory_hands_out_first_conn_once_even_concurrently():
    made: list[object] = []

    def connect() -> object:
        o = object()
        made.append(o)
        return o

    first = object()
    f = service.PrimedConnFactory(connect, first)
    got: list[object] = []
    ts = [threading.Thread(target=lambda: got.append(f())) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert got.count(first) == 1 and len(made) == 7
