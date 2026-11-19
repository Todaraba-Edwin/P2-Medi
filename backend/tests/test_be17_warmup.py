"""BE-17 첫 응답 지연 시험(BE-17-01·02·03 A, 2026-11-19). LLM·공공 API·원격 DB 호출 0, `.env` 미사용.

- BE-17-01·02 A: 서버 시작 직후 백그라운드 스레드가 자원 전체를 한 번 만든다. lifespan은 기다리지 않는다.
  준비 중 들어온 요청은 같은 잠금에서 기다려 같은 자원을 쓴다(생성 1회). 실패하면 저장하지 않고 다음 요청이 다시 만든다.
  스위치(`MEDIAGENT_WARMUP`)를 끄거나 필수 설정이 없으면 준비를 시작하지 않는다.
- BE-17-03 A: router가 모델로 넘기면(되묻기 아님) 모델 호출 전에 `progress: drug_lookup`을 한 번 낸다.
- 자원은 가짜(가짜 모델·합성 소사전·소규모 SQLite·가짜 `DurClient`, `e2e/golden_synth.py`)이고 질문은 합성이다(평가 세트 아님).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

import app.main as main_mod  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import service, stream  # noqa: E402
from app.api.runner import GraphRunner  # noqa: E402
from app.api.stream import chat_events  # noqa: E402
from app.config import Settings  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
Q_CLARIFY = "엄마가 이지렉트정을 드시는데 타이레놀 콜드-에스를 같이 먹어도 되나요?"
Q_REFUSE = f"{AZI} 처방해 줘"
Q_EMERGENCY = f"숨쉬기 힘들어요. {AZI}이랑 {COLD}을 같이 먹었어요"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
SECRET = "QQQQ-가짜비밀표지-5521"
BOOM = "폭발표지WU3"
ENV_NAMES = service.REQUIRED_ENV
PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
    {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    for n in ENV_NAMES:
        for name in (n, n.upper(), n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MEDIAGENT_MODE", raising=False)
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)


def _settings(**override: Any) -> Settings:
    vals: dict[str, Any] = {n.lower(): f"{SECRET}-{i}" for i, n in enumerate(ENV_NAMES)}
    vals["mediagent_warmup"] = True
    vals.update(override)
    return Settings(_env_file=None, **{k: v for k, v in vals.items() if v is not None})


def _script(first_tools: list[tuple[str, dict[str, Any]]] | None = None) -> list[AIMessage]:
    first = first_tools or [("identify_drug", {"name": AZI}), ("identify_drug", {"name": COLD})]
    return [
        AIMessage("", tool_calls=[tool_call(n, a, f"c{i}") for i, (n, a) in enumerate(first)]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "cx")]),
        AIMessage("조회를 마쳤다"),
    ]


def _deps(script: list[AIMessage] | None = None, n_requests: int = 1) -> Any:
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    msgs = [m for _ in range(n_requests) for m in (script or _script())]
    return build_deps(dd, ctx, tool_model=ScriptedToolModel(script=msgs), summary_model=ScriptedSummary([PAIR_DRAFT] * n_requests),
                      system_prompt="시험용 시스템 프롬프트")


class GatedResources:
    """문(`gate`)이 열릴 때까지 막히는 가짜 자원 팩토리. 호출 수와 들어온 시점을 기록한다."""

    def __init__(self, *, fail_times: int = 0, n_requests: int = 4, open_gate: bool = False) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.n_requests = n_requests
        self.gate = threading.Event()
        self.entered = threading.Event()
        if open_gate:
            self.gate.set()

    def __call__(self, settings: Any) -> Any:  # noqa: ARG002
        self.calls += 1
        self.entered.set()
        assert self.gate.wait(10)
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{BOOM} {SECRET}")
        return _deps(n_requests=self.n_requests)


def _logged(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- BE-17-01·02 A 백그라운드 준비
def test_start_warmup_returns_immediately_and_builds_once_in_background():
    fake = GatedResources()
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    t0 = time.monotonic()
    th = service.start_warmup(runner, _settings())
    assert th is not None and time.monotonic() - t0 < 1  # 기다리지 않는다
    assert fake.entered.wait(5) and not runner.ready
    fake.gate.set()
    th.join(5)
    assert not th.is_alive() and runner.ready and fake.calls == 1


def test_requests_during_warmup_wait_and_share_one_build():
    """준비 중 동시 요청 2개: 같은 잠금에서 기다렸다가 같은 자원을 쓴다(생성 1회)."""
    fake = GatedResources(n_requests=2)
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    th = runner.start_warmup()
    assert fake.entered.wait(5)
    results: list[int] = []

    def go() -> None:
        results.append(len(list(runner.updates(Q_PAIR, None))))

    reqs = [threading.Thread(target=go) for _ in range(2)]
    for t in reqs:
        t.start()
    time.sleep(0.05)
    assert results == [] and fake.calls == 1  # 요청은 생성이 끝나기를 기다린다
    fake.gate.set()
    for t in [th, *reqs]:
        t.join(10)
    assert fake.calls == 1 and len(results) == 2 and all(n > 0 for n in results)


def test_warmup_failure_is_not_stored_and_next_request_retries(caplog):
    caplog.set_level(logging.DEBUG)
    fake = GatedResources(fail_times=1, open_gate=True)
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    assert runner.warm() is False and not runner.ready and fake.calls == 1
    text = _logged(caplog)
    assert "warmup failed: RuntimeError" in text  # 종류 이름만
    assert BOOM not in text and SECRET not in text and "QQQQ" not in text
    client = _client(runner)
    r = client.post("/chat", json={"question": Q_PAIR})
    types = [ev.ChatEvent.model_validate_json(x).root.type for x in r.content.split(b"\n") if x]
    assert types[-2:] == ["answer", "done"] and fake.calls == 2 and runner.ready


def test_warmup_logs_start_and_done_with_seconds_only(caplog):
    caplog.set_level(logging.INFO)
    fake = GatedResources(open_gate=True)
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    assert runner.warm() is True
    msgs = [r.getMessage() for r in caplog.records if r.name == service.logger.name]
    assert "warmup starting" in msgs
    assert any(m.startswith("warmup done in ") and m.endswith("s") for m in msgs)
    assert SECRET not in "\n".join(msgs)
    assert runner.warm() is True and fake.calls == 1  # 이미 만들었으면 다시 만들지 않는다


def test_warmup_switch_off_does_not_start():
    fake = GatedResources(open_gate=True)
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    assert service.start_warmup(runner, _settings(mediagent_warmup=False)) is None
    assert fake.calls == 0 and not runner.ready


@pytest.mark.parametrize("raw,expected", [("0", False), ("false", False), ("off", False), ("1", True), ("true", True)])
def test_warmup_switch_env_name_is_mediagent_warmup(monkeypatch, raw, expected):
    monkeypatch.setenv("MEDIAGENT_WARMUP", raw)
    assert Settings(_env_file=None).mediagent_warmup is expected


def test_warmup_default_is_on(monkeypatch):
    monkeypatch.delenv("MEDIAGENT_WARMUP", raising=False)  # 시험 공통 끔(conftest)을 걷어 실제 기본값을 본다
    assert Settings(_env_file=None).mediagent_warmup is True


def test_missing_settings_means_no_runner_and_no_warmup():
    fake = GatedResources(open_gate=True)
    s = _settings(supabase_db_url=None)
    runner = service.make_service_runner(s, resources_factory=fake)
    assert runner is None and service.start_warmup(runner, s) is None and fake.calls == 0


@pytest.fixture
def wired(monkeypatch):
    fake = GatedResources(open_gate=True)
    monkeypatch.setattr(service, "default_resources", fake)
    holder: dict[str, Any] = {"settings": Settings(_env_file=None, mediagent_warmup=True), "fake": fake}
    monkeypatch.setattr(main_mod, "load_settings", lambda: holder["settings"])
    try:
        yield holder
    finally:
        chat_api.set_runner(main_mod.app, None)


def _wait_ready(app: FastAPI, timeout: float = 5) -> bool:
    runner = getattr(app.state, chat_api.RUNNER_STATE_KEY)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if runner.ready:
            return True
        time.sleep(0.01)
    return False


def test_lifespan_starts_warmup_and_first_request_reuses_it(wired):
    wired["settings"] = _settings()
    with TestClient(main_mod.app) as client:
        assert _wait_ready(main_mod.app) and wired["fake"].calls == 1  # 요청 없이도 시작 직후 만들어졌다
        r = client.post("/chat", json={"question": Q_PAIR})
        assert r.status_code == 200 and wired["fake"].calls == 1


def test_lifespan_without_settings_starts_no_warmup(wired):
    with TestClient(main_mod.app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/chat", json={"question": Q_PAIR}).status_code == 501
    assert wired["fake"].calls == 0


def test_lifespan_with_switch_off_starts_no_warmup(wired):
    wired["settings"] = _settings(mediagent_warmup=False)
    with TestClient(main_mod.app) as client:
        assert client.get("/health").status_code == 200
        time.sleep(0.05)
        assert wired["fake"].calls == 0


# --------------------------------------------------------------------------- BE-17-03 A router 통과 때 drug_lookup
def _client(runner: Any) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=None)
    return TestClient(app)


def _stream(question: str, script: list[AIMessage] | None = None) -> list[ev.ChatEvent]:
    r = _client(GraphRunner.from_deps(_deps(script))).post("/chat", json={"question": question})
    assert r.status_code == 200
    events = [ev.ChatEvent.model_validate_json(x) for x in r.content.split(b"\n") if x]
    ev.check_event_order(events, complete=True)
    return events


def _stages(events: list[ev.ChatEvent]) -> list[str]:
    return [e.root.stage for e in events if e.root.type == "progress"]


def test_router_to_model_emits_drug_lookup_even_without_identify_drug():
    """모델이 `identify_drug`를 부르지 않아도(개발셋 대부분) router가 약을 찾고 모델로 넘기면 "약 찾는 중"이 켜진다."""
    script = _script([("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]})])
    events = _stream(Q_PAIR, script)
    assert events[0].root.type == "progress" and events[0].root.stage == "drug_lookup"
    assert _stages(events) == ["drug_lookup", "contraindication_check"]


def test_following_identify_drug_does_not_duplicate_drug_lookup():
    assert _stages(_stream(Q_PAIR)) == ["drug_lookup", "contraindication_check"]


@pytest.mark.parametrize("question,end_reason", [(Q_CLARIFY, "CLARIFY"), (Q_REFUSE, "REFUSE")])
def test_clarify_and_refuse_paths_emit_no_progress(question, end_reason):
    events = _stream(question, [])
    assert [e.root.type for e in events] == ["answer", "done"] and events[-1].root.end_reason == end_reason


def test_emergency_stays_seq_zero_and_drug_lookup_follows():
    events = _stream(Q_EMERGENCY)
    assert events[0].root.type == "emergency" and events[0].root.seq == 0
    assert events[1].root.type == "progress" and events[1].root.stage == "drug_lookup"
    assert _stages(events).count("drug_lookup") == 1


class _GatedModel:
    """첫 `.invoke`를 문이 열릴 때까지 막는 모델 래퍼(나머지 속성은 원본 그대로)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.gate = threading.Event()
        self.invoked = threading.Event()

    def invoke(self, *a: Any, **kw: Any) -> Any:
        self.invoked.set()
        assert self.gate.wait(10)
        return self.inner.invoke(*a, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def test_drug_lookup_arrives_before_the_first_model_call_finishes():
    base = _deps()
    gated = _GatedModel(base.tool_model)
    runner = GraphRunner.from_deps(replace(base, tool_model=gated))

    async def go() -> tuple[Any, bool]:
        gen = chat_events(runner, Q_PAIR, None)
        first = await asyncio.wait_for(gen.__anext__(), 5)
        still_waiting = not gated.gate.is_set()
        gated.gate.set()
        async for _ in gen:
            pass
        return first, still_waiting

    first, still_waiting = asyncio.run(go())
    assert first.type == "progress" and first.stage == "drug_lookup" and still_waiting


def test_router_update_without_ambiguous_key_emits_nothing():
    assert stream._router_goes_to_model({"entities": []}) is False
    assert stream._router_goes_to_model({"ambiguous": True}) is False
    assert stream._router_goes_to_model({"ambiguous": False}) is True
    assert stream.ROUTER_STAGE == "drug_lookup"
