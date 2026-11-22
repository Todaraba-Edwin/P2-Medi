"""BE-06 앱 시작 배선 시험(goal 3회차 §2-1~4·6, BE-06-22 A·BE-06-19 A). LLM·공공 API·원격 DB 호출 0, `.env` 미사용.

- 설정은 항상 `Settings(_env_file=None, ...)`(가짜 값)이고 관련 환경변수는 지운다. 실제 자원 생성 함수(`service.default_resources`)는
  가짜로 바꾼다. 이 둘을 바꾸지 않은 채 lifespan을 돌리는 시험은 없다.
- 가짜 자원은 가짜 모델·합성 소사전·소규모 SQLite·가짜 `DurClient`(`e2e/golden_synth.py`)로 만든 `GraphDeps`다.
- 시험 질문은 합성이다(평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import asyncio
import logging
import socket
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
from app.agent.tools.context import ToolContext  # noqa: E402
from app.api import account as account_api  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import service  # noqa: E402
from app.api.stream import chat_events  # noqa: E402
from app.config import Settings  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
SECRET = "QQQQ-가짜비밀표지-7731"  # 로그·응답에 나오면 안 되는 가짜 값
BOOM = "폭발표지ZK9"
ENV_NAMES = ("OPENAI_API_KEY", "SUPABASE_DB_URL", "DURPrdlstInfoService03_END_POINT", "DURPrdlstInfoService03_API_KEY",
             "DURIrdntInfoService03_END_POINT", "DURIrdntInfoService03_API_KEY")
DEFAULT_REMAINING = ToolContext.__dataclass_fields__["remaining_calls"].default


def _settings(**drop_or_override: Any) -> Settings:
    """필수 값을 모두 가짜로 채운 설정. `x=None`을 주면 그 칸만 비운다."""
    vals: dict[str, Any] = {n.lower(): f"{SECRET}-{i}" for i, n in enumerate(ENV_NAMES)}
    vals["mediagent_warmup"] = True  # 시험 공통은 끔(conftest). 여기서는 실제 기본값(켬)으로 lifespan을 본다(BE-17-01 A)
    vals.update(drop_or_override)
    return Settings(_env_file=None, **{k: v for k, v in vals.items() if v is not None})


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    for n in ENV_NAMES:  # 환경변수는 대소문자 두 모양 모두 지운다
        for name in (n, n.upper(), n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MEDIAGENT_MODE", raising=False)
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)


def _one_script() -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
    {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}


class FakeResources:
    """가짜 자원 팩토리(호출 수 기록). 요청 `n_requests`번을 돌릴 만큼의 스크립트를 가진 가짜 모델로 `GraphDeps`를 만든다."""

    def __init__(self, n_requests: int = 3, *, fail_times: int = 0, max_calls: int | None = None) -> None:
        self.calls = 0
        self.max_calls = max_calls
        self.fail_times = fail_times
        self.n_requests = n_requests
        self.deps: Any = None

    def __call__(self, settings: Any) -> Any:  # noqa: ARG002
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{BOOM} {SECRET}")
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
        script = [m for _ in range(self.n_requests) for m in _one_script()]
        self.deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([PAIR_DRAFT]),
                               system_prompt="시험용 시스템 프롬프트")
        if self.max_calls is not None:
            self.deps = replace(self.deps, max_calls=self.max_calls)
        return self.deps


def _client(runner: Any) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=None)
    return TestClient(app)


def _post(client: TestClient, question: str = Q_PAIR) -> tuple[Any, list[ev.ChatEvent]]:
    r = client.post("/chat", json={"question": question})
    events = [ev.ChatEvent.model_validate_json(x) for x in r.content.split(b"\n") if x]
    return r, events


def _types(events: list[ev.ChatEvent]) -> list[str]:
    return [e.root.type for e in events]


def _logged(caplog) -> str:
    return "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)


# --------------------------------------------------------------------------- §2-1 ①② 설정 판정
def test_required_env_names_are_the_six_in_definition_order():
    assert service.REQUIRED_ENV == ENV_NAMES


def test_missing_all_returns_six_names_in_order_and_no_runner():
    s = Settings(_env_file=None)
    assert service.missing_settings(s) == list(ENV_NAMES)
    assert service.make_service_runner(s, resources_factory=FakeResources()) is None


@pytest.mark.parametrize("name", ENV_NAMES)
def test_one_missing_returns_only_that_name_and_no_runner(name):
    fake = FakeResources()
    s = _settings(**{name.lower(): None})
    assert service.missing_settings(s) == [name]
    assert service.make_service_runner(s, resources_factory=fake) is None and fake.calls == 0


def test_blank_value_counts_as_missing():
    assert service.missing_settings(_settings(openai_api_key="   ")) == ["OPENAI_API_KEY"]


# --------------------------------------------------------------------------- §2-1 ③ 지연 생성(한 번만)
def test_runner_is_lazy_and_builds_resources_once():
    fake = FakeResources()
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    assert runner is not None and fake.calls == 0  # 실행기를 만들 때는 아무것도 만들지 않는다
    client = _client(runner)
    r1, e1 = _post(client)
    assert r1.status_code == 200 and fake.calls == 1
    r2, e2 = _post(client)
    assert fake.calls == 1 and _types(e1)[-1] == _types(e2)[-1] == "done"


def test_concurrent_first_requests_build_resources_once():
    class Slow(FakeResources):
        def __call__(self, settings: Any) -> Any:
            time.sleep(0.05)
            return super().__call__(settings)

    fake = Slow(n_requests=4)
    runner = service.make_service_runner(_settings(), resources_factory=fake)
    done: list[int] = []

    def go() -> None:
        done.append(len(list(runner.updates(Q_PAIR, None))))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert fake.calls == 1 and len(done) == 4 and all(n > 0 for n in done)


# --------------------------------------------------------------------------- §2-1 ④ 자원 생성 실패
def test_resource_failure_is_error_then_done_and_retried_next_request(caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeResources(fail_times=1)
    client = _client(service.make_service_runner(_settings(), resources_factory=fake))
    r, events = _post(client)
    assert r.status_code == 200 and _types(events) == ["error", "done"] and events[0].root.code == "INTERNAL_ERROR"
    body = r.content.decode("utf-8")
    assert BOOM not in body and SECRET not in body and "RuntimeError" not in body
    assert BOOM not in _logged(caplog) and SECRET not in _logged(caplog)
    r2, events2 = _post(client)  # 실패는 저장하지 않는다: 다음 요청에서 다시 만든다
    assert fake.calls == 2 and _types(events2)[-2:] == ["answer", "done"]
    _post(client)
    assert fake.calls == 2


# --------------------------------------------------------------------------- §2-1 ⑤ 로그: 이름만
def test_logs_name_missing_variables_but_never_values(caplog):
    caplog.set_level(logging.DEBUG)
    assert service.make_service_runner(_settings(supabase_db_url=None), resources_factory=FakeResources()) is None
    text = _logged(caplog)
    assert "SUPABASE_DB_URL" in text and "OPENAI_API_KEY" not in text  # 빠진 이름만
    fake = FakeResources()
    _post(_client(service.make_service_runner(_settings(), resources_factory=fake)))
    assert fake.calls == 1
    text = _logged(caplog)
    assert SECRET not in text and "QQQQ" not in text
    assert any(r.levelno == logging.INFO and r.name == service.logger.name for r in caplog.records)


# --------------------------------------------------------------------------- §2-1 ⑥ 정상 스트림
def test_lazy_runner_normal_pair_stream_is_ordered_and_ends_normal():
    r, events = _post(_client(service.make_service_runner(_settings(), resources_factory=FakeResources())))
    assert r.status_code == 200 and r.headers["content-type"].startswith(ev.NDJSON_MEDIA_TYPE)
    ev.check_event_order(events, complete=True)
    assert _types(events) == ["progress", "progress", "answer", "done"]
    assert events[-1].root.end_reason == "NORMAL"
    a = next(e.root.response for e in events if e.root.type == "answer")
    assert any(f.bucket == "found" and f.target == "pair" for f in a.findings)


# --------------------------------------------------------------------------- §2-3 요청별 ToolContext·그래프
def test_each_request_gets_its_own_tool_context_with_default_remaining_calls(monkeypatch):
    seen: list[tuple[ToolContext, int, Any]] = []
    real = service.build_graph

    def spy(deps: Any) -> Any:
        seen.append((deps.tool_ctx, deps.tool_ctx.remaining_calls, deps))
        return real(deps)

    monkeypatch.setattr(service, "build_graph", spy)
    fake = FakeResources(max_calls=7)  # 도구 노드가 적는 값(상한 - 호출 수)이 기본값과 겹치지 않게 상한을 7로 둔다
    client = _client(service.make_service_runner(_settings(), resources_factory=fake))
    _post(client)
    _post(client)
    (ctx1, start1, deps1), (ctx2, start2, deps2) = seen
    assert ctx1 is not ctx2 and ctx1 is not fake.deps.tool_ctx and ctx2 is not fake.deps.tool_ctx
    assert start1 == start2 == DEFAULT_REMAINING  # 앞 요청이 줄여도 다음 요청의 시작 값은 기본값
    assert ctx1.remaining_calls < DEFAULT_REMAINING  # 첫 요청의 그래프가 자기 컨텍스트만 줄였다
    assert fake.deps.tool_ctx.remaining_calls == DEFAULT_REMAINING  # 공유 원본은 그대로
    # 무거운 자원은 공유한다(사전·DB 팩토리·모델). 도구 목록은 요청의 컨텍스트에 묶인 새 것이다
    assert ctx1.drug_dict is ctx2.drug_dict is fake.deps.drug_dict and ctx1.conn_factory is ctx2.conn_factory
    # 모델 객체도 공유한다. 요청마다 다른 것은 그 위의 얇은 사용량 래퍼뿐이다(BE-06-36 A: 요청 단위 토큰·비용 귀속)
    assert deps1.tool_model.inner is deps2.tool_model.inner is fake.deps.tool_model and deps1.tools is not deps2.tools
    assert deps1.summary_model.inner is deps2.summary_model.inner is fake.deps.summary_model
    assert deps1.tool_model is not deps2.tool_model
    assert deps1.tracer is None and deps2.tracer is None  # 서비스 경로 trace 없음(RFP-22-06 A)


def test_request_deps_resets_remaining_calls_even_if_base_was_mutated():
    base = FakeResources()(None)
    base.tool_ctx.remaining_calls = 1
    assert service.request_deps(base).tool_ctx.remaining_calls == DEFAULT_REMAINING


def test_per_request_graph_build_cost_is_small():
    base = FakeResources()(None)
    t0 = time.perf_counter()
    n = 20
    for _ in range(n):
        service.build_graph(service.request_deps(base))
    per_ms = (time.perf_counter() - t0) * 1000 / n
    assert per_ms < 200, per_ms  # 느슨한 상한(측정값은 보고에 적는다)


# --------------------------------------------------------------------------- §2-4 연결 끊김(동작 고정 시험, 구현 변경 없음)
class CountingSlowRunner:
    """갱신 사이에 쉬는 가짜 실행기. 낸 갱신 수를 기록한다."""

    def __init__(self, total: int = 8, delay_s: float = 0.03) -> None:
        self.total, self.delay_s = total, delay_s
        self.emitted = 0
        self.finished = threading.Event()

    def updates(self, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        try:
            for _ in range(self.total):
                self.emitted += 1
                yield {"model": {"messages": [AIMessage("", tool_calls=[tool_call("identify_drug", {"name": "x"}, f"c{self.emitted}")])]}}
                time.sleep(self.delay_s)
        finally:
            self.finished.set()


def test_closing_stream_stops_runner_at_next_boundary():
    runner = CountingSlowRunner()

    class Sink:
        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []

        def log(self, **fields: Any) -> None:
            self.rows.append(fields)

    sink = Sink()

    async def go() -> int:
        gen = chat_events(runner, "먹어도 돼?", None, sink)
        first = await gen.__anext__()  # 첫 갱신이 이벤트로 나온 시점에 닫는다
        assert first.type == "progress"
        at_close = runner.emitted
        await gen.aclose()
        return at_close

    at_close = asyncio.run(go())
    assert runner.finished.wait(5)  # 스레드가 끝까지 돌지 않고 멈춘다
    assert runner.emitted <= at_close + 1 < runner.total  # 닫은 뒤로는 다음 경계까지만(갱신 하나 이하)
    assert any(row.get("error_type") == "ClientDisconnected" for row in sink.rows)


# --------------------------------------------------------------------------- §2-2 lifespan(main.py)
@pytest.fixture
def wired(monkeypatch):
    """`app.main`의 설정 공급·자원 생성을 가짜로 바꾸고, 끝나면 실행기를 뗀다(다른 시험의 501에 새지 않게)."""
    fake = FakeResources()
    monkeypatch.setattr(service, "default_resources", fake)
    holder: dict[str, Any] = {"settings": Settings(_env_file=None), "fake": fake}
    monkeypatch.setattr(main_mod, "load_settings", lambda: holder["settings"])
    try:
        yield holder
    finally:
        chat_api.set_runner(main_mod.app, None)
        account_api.set_item_seq_checker(main_mod.app, None)


def test_lifespan_without_settings_keeps_501_and_health(wired):
    with TestClient(main_mod.app) as client:
        r = client.post("/chat", json={"question": Q_PAIR})
        assert r.status_code == 501 and r.json() == {"code": "NOT_IMPLEMENTED", "fields": []}
        assert client.get("/health").json() == {"status": "ok"}
        paths = set(client.get("/openapi.json").json()["paths"])
        assert paths == {"/health", "/chat", *ACCOUNT_PATHS, *INGEST_PATHS} and client.get("/docs").status_code == 200  # §2-6 스모크(계정: BE-11)
    assert wired["fake"].calls == 0


def test_lifespan_with_settings_attaches_lazy_runner_and_streams(wired):
    wired["settings"] = _settings()
    with TestClient(main_mod.app) as client:
        assert client.get("/health").status_code == 200
        r, events = _post(client)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ev.NDJSON_MEDIA_TYPE)
        # BE-17-01 A: 시작 준비 스레드와 첫 요청이 같은 잠금을 쓰므로 누가 먼저든 자원은 한 번만 만든다
        assert _types(events)[-1] == "done" and events[-1].root.end_reason == "NORMAL" and wired["fake"].calls == 1


def test_lifespan_attaches_item_seq_checker_sharing_chat_dict(wired):
    """FE-04-13 남음 ②(GROUP-03 B2): 프로필 약 `item_seq` 재확인 함수를 채팅 자원의 사전으로 붙인다. 사전에 없는 번호는 버린다.

    계정 저장소는 붙이지 않는다(BE-11-23 A: 원격 적용 뒤). 설정이 없으면 확인 함수도 없다."""
    with TestClient(main_mod.app):
        assert getattr(main_mod.app.state, account_api.ITEM_SEQ_CHECKER_STATE_KEY) is None
    wired["settings"] = _settings(mediagent_warmup=False)
    with TestClient(main_mod.app):
        checker = getattr(main_mod.app.state, account_api.ITEM_SEQ_CHECKER_STATE_KEY)
        assert checker is not None and getattr(main_mod.app.state, account_api.REPO_STATE_KEY, None) is None
        assert wired["fake"].calls == 0  # 붙이기만 하고 자원은 만들지 않는다(첫 확인 때 만든다)
        known = next(iter(golden_dict()._by_seq))
        assert asyncio.run(checker([known, "000000000"])) == {known}
        assert wired["fake"].calls == 1  # 채팅 자원의 사전을 공유한다(따로 적재 0)


def test_lifespan_with_warmup_off_builds_on_first_request(wired):
    """스위치를 끄면(`MEDIAGENT_WARMUP=0`) 이전 동작(BE-06-27 A): 시작만으로는 자원을 만들지 않고 첫 요청에서 만든다."""
    wired["settings"] = _settings(mediagent_warmup=False)
    with TestClient(main_mod.app) as client:
        assert client.get("/health").status_code == 200 and wired["fake"].calls == 0
        _post(client)
        assert wired["fake"].calls == 1


def test_lifespan_itself_does_not_wait_for_network(wired, monkeypatch):
    """BE-17-01 A로 의미를 바꾼 시험(이전: "시작 구간 네트워크 0").

    이제 시작 직후 백그라운드 스레드가 자원을 만들므로 접속은 **그 스레드 안에서** 일어난다. 이 시험은 lifespan 자체(실행기 붙이기·
    스레드 띄우기)가 접속하지 않고, 자원 생성이 끝나기를 기다리지 않으며, 그동안 `/health`가 바로 답하는지를 본다.
    자원 생성은 문이 열릴 때까지 막히는 가짜라 실제 접속은 일어나지 않는다."""
    import psycopg

    def no_net(*a: Any, **kw: Any) -> Any:
        raise AssertionError("시작 중 네트워크 접속 시도")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket.socket, "connect_ex", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(psycopg, "connect", no_net)
    gate, entered = threading.Event(), threading.Event()
    fake = wired["fake"]

    def gated(settings: Any) -> Any:
        entered.set()
        assert gate.wait(10)
        return fake(settings)

    monkeypatch.setattr(service, "default_resources", gated)
    threads: list[threading.Thread] = []
    real_start = service.start_warmup

    def spy_start(runner: Any, settings: Any) -> Any:
        t = real_start(runner, settings)
        threads.append(t)
        return t

    monkeypatch.setattr(service, "start_warmup", spy_start)
    wired["settings"] = _settings()
    t0 = time.monotonic()
    try:
        with TestClient(main_mod.app) as client:
            assert getattr(main_mod.app.state, chat_api.RUNNER_STATE_KEY) is not None
            assert entered.wait(5) and fake.calls == 0  # 준비 스레드는 생성 중(막힘)인데 lifespan은 이미 끝났다
            assert client.get("/health").status_code == 200 and fake.calls == 0
            assert time.monotonic() - t0 < 5
            gate.set()
            assert len(threads) == 1 and threads[0] is not None
            threads[0].join(5)
            assert not threads[0].is_alive() and fake.calls == 1
    finally:
        gate.set()


def test_runner_does_not_leak_after_fixture_and_openapi_is_unchanged(wired):
    before = main_mod.app.openapi()
    wired["settings"] = _settings()
    with TestClient(main_mod.app):
        assert main_mod.app.openapi() == before  # 배선이 OpenAPI를 바꾸지 않는다(gen:api 재생성 불필요)
    chat_api.set_runner(main_mod.app, None)
    assert TestClient(main_mod.app).post("/chat", json={"question": Q_PAIR}).status_code == 501


ACCOUNT_PATHS = {"/me", "/legal/{doc_type}", "/consents", "/profiles", "/profiles/{profile_id}",  # BE-11 계정 API(2026-11-18)
                 "/drugs/search"}  # FE-04-13 A 프로필 약 사전 검색(2026-11-20)
INGEST_PATHS = {"/ingest/image"}  # BE-14 사진 약 이름 추출(2026-11-22, 게스트 허용)


def test_openapi_matches_committed_export_shape():
    schema = main_mod.app.openapi()
    paths = schema["paths"]
    assert set(paths) == {"/health", "/chat", *ACCOUNT_PATHS, *INGEST_PATHS}
    assert set(paths["/chat"]["post"]["responses"]) == {"200", "422", "501"}
    assert set(paths["/me"]["get"]["responses"]) == {"200", "401", "501", "503"}
    assert set(paths["/me"]["delete"]["responses"]) == {"204", "401", "501", "502", "503"}  # 502 AUTH_DELETE_FAILED(BE-11-24 A)
    assert set(paths["/me"]) == {"get", "delete"} and set(paths["/legal/{doc_type}"]) == {"get"}
    assert set(paths["/consents"]) == {"post"} and set(paths["/profiles"]) == {"get", "post"}
    assert set(paths["/profiles/{profile_id}"]) == {"patch", "delete"}
    assert set(paths["/legal/{doc_type}"]["get"]["responses"]) == {"200", "404", "422", "501", "503"}
    assert {"201", "401", "403", "404", "409", "422", "501", "503"} <= set(paths["/consents"]["post"]["responses"])
    assert "security" not in paths["/legal/{doc_type}"]["get"]  # 게스트 허용
    assert set(paths["/drugs/search"]) == {"post"}  # 질문을 URL 쿼리에 싣지 않는다(access 로그)
    assert set(paths["/drugs/search"]["post"]["responses"]) == {"200", "401", "422", "501", "503"}
    assert set(paths["/ingest/image"]) == {"post"} and set(paths["/ingest/image"]["post"]["responses"]) == {"200", "422"}
    assert "security" not in paths["/ingest/image"]["post"]  # 게스트 허용(BE-14 〔D3〕 A)


def test_default_resources_is_not_called_by_tests_and_psycopg_is_imported_lazily():
    src = Path(service.__file__).read_text(encoding="utf-8")
    head = src.split("\ndef ", 1)[0]
    assert "import psycopg" not in head  # 모듈 맨 위에서 import하지 않는다(실제 연결을 여는 함수 안에서만)
    assert "psycopg_conn_factory" not in src and "openai_query_embedder" not in src and "resolve_dsn" not in src
