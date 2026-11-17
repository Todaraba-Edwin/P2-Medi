"""BE-06 개발 전용 가짜 자원 서버(`scripts/dev_fake_server.py`) 시험. LLM·공공 API·원격 DB 호출 0, `.env` 미사용, 소켓을 열지 않는다.

- 시나리오마다 실제 라우트(`chat_api.register`)·실제 지연 실행기(`service.make_service_runner`)·실제 그래프로 `chat_event@v1` 계약을 낸다.
- 앱 본체(`app/main.py`·`app/api/`)에 가짜 모드 스위치가 없는지 문자열로 검사한다.
- 바인딩은 `127.0.0.1` 고정(외부 바인딩 옵션 없음)인지 본다. `uvicorn.run`은 가짜로 바꿔 실제로 띄우지 않는다.
- 시험 질문은 합성이다(평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import dev_fake_server as dfs  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import service  # noqa: E402

SRC = (BACKEND / "scripts" / "dev_fake_server.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(dfs.create_app(slow_seconds=0.0, metrics=None))


def _post(client: TestClient, question: str) -> tuple[Any, list[ev.ChatEvent], list[bytes]]:
    r = client.post("/chat", json={"question": question})
    lines = r.content.split(b"\n")
    assert lines[-1] == b""  # 마지막 줄도 `\n`으로 끝난다
    events = [ev.ChatEvent.model_validate_json(x) for x in lines[:-1] if x]
    return r, events, lines[:-1]


def _run(client: TestClient, name: str) -> tuple[list[str], Any, ev.ChatEvent]:
    r, events, _ = _post(client, dfs.SCENARIOS[name])
    assert r.status_code == 200 and r.headers["content-type"].startswith(ev.NDJSON_MEDIA_TYPE)
    ev.check_event_order(events, complete=True)
    assert [e.root.seq for e in events] == list(range(len(events)))
    assert all(e.root.schema_version == ev.EVENT_SCHEMA_VERSION for e in events)
    answer = next((e.root.response for e in events if e.root.type == "answer"), None)
    return [e.root.type for e in events], answer, events[-1]


def _fixed_phrases_ok(a: Any) -> None:
    assert fp.FIXED_NOTICE in a.fixed_notice and a.disclaimer == fp.DISCLAIMER


# --------------------------------------------------------------------------- 시나리오별 계약
def test_normal_found_pair(client):
    types, a, last = _run(client, "normal_found")
    assert types == ["progress", "progress", "answer", "done"] and last.root.end_reason == "NORMAL"
    assert [f.bucket for f in a.findings if f.target == "pair"] == ["found"]
    assert a.emergency is None
    _fixed_phrases_ok(a)


def test_not_found_is_not_listed_and_never_says_safe(client):
    types, a, last = _run(client, "not_found")
    assert types == ["progress", "progress", "answer", "done"] and last.root.end_reason == "NORMAL"
    assert [f.bucket for f in a.findings if f.target == "pair"] == ["not_listed"]
    assert "안전합니다" not in (a.summary or "")
    _fixed_phrases_ok(a)


def test_clarify_has_two_candidates(client):
    types, a, last = _run(client, "clarify")
    assert types == ["answer", "done"] and last.root.end_reason == "CLARIFY"
    assert len(a.candidates) == 2 and a.candidates_line == fp.CLARIFY_PICK_LINE and not a.findings


@pytest.mark.parametrize("seq,bucket", [("202106092", "not_listed"), ("202106954", "found")])
def test_clarify_resend_with_picked_candidate_reaches_result(client, seq, bucket):
    """되묻기 뒤 재전송(같은 질문 + 고른 후보 코드)은 다시 묻지 않고 고른 약으로 조회한다(AG-05-03 A)."""
    _, first, _ = _post(client, dfs.SCENARIOS["clarify"])
    picked = next(e.root.response for e in first if e.root.type == "answer").candidates
    assert seq in {c.item_seq for c in picked}  # 첫 턴 후보에서 고른 코드다
    body = {"question": dfs.SCENARIOS["clarify"], "context": {"confirmed_drugs": [{"name": "고른 약", "item_seq": seq}]}}
    r = client.post("/chat", json=body)
    events = [ev.ChatEvent.model_validate_json(x) for x in r.content.split(b"\n") if x]
    ev.check_event_order(events, complete=True)
    assert [e.root.type for e in events] == ["progress", "progress", "answer", "done"] and events[-1].root.end_reason == "NORMAL"
    a = events[-2].root.response
    assert not a.candidates and [f.bucket for f in a.findings if f.target == "pair"] == [bucket]
    _fixed_phrases_ok(a)


def test_emergency_is_first_event_and_lookup_still_runs(client):
    types, a, last = _run(client, "emergency")
    assert types[0] == "emergency" and types[-2:] == ["answer", "done"] and "progress" in types
    _, events, _ = _post(client, dfs.SCENARIOS["emergency"])
    first = events[0].root
    assert first.seq == 0 and first.emergency.text == fp.EMERGENCY_119 and first.emergency.tel == fp.EMERGENCY_119_TEL
    assert a.emergency is not None and any(f.bucket == "found" for f in a.findings)  # 금기 조회는 막지 않는다
    _fixed_phrases_ok(a)


def test_out_of_scope_refuse(client):
    types, a, last = _run(client, "refuse")
    assert types == ["answer", "done"] and last.root.end_reason == "REFUSE"
    assert a.route == "REFUSE" and a.summary == fp.REFUSE_MESSAGES["PRESCRIPTION"]


def test_server_error_is_error_then_done_without_leak(client):
    r, events, _ = _post(client, dfs.SCENARIOS["server_error"])
    assert r.status_code == 200
    ev.check_event_order(events, complete=True)
    assert [e.root.type for e in events] == ["error", "done"] and events[0].root.code == "INTERNAL_ERROR"
    body = r.content.decode("utf-8")
    assert "RuntimeError" not in body and "scripted server error" not in body


def test_scenarios_repeat_identically_on_shared_resources(client):
    """가짜 모델은 상태가 없다: 같은 자원으로 순서를 바꿔 돌려도 결과가 같다."""
    first = [_run(client, n)[0] for n in ("not_found", "normal_found")]
    again = [_run(client, n)[0] for n in ("normal_found", "not_found")]
    assert first == list(reversed(again))


def test_slow_scenario_sends_heartbeat_blank_lines(monkeypatch):
    monkeypatch.setattr(ev, "HEARTBEAT_INTERVAL_S", 0.02)
    slow = TestClient(dfs.create_app(slow_seconds=0.25, metrics=None))
    r, events, lines = _post(slow, dfs.SCENARIOS["slow"])
    assert r.status_code == 200 and lines.count(b"") >= 2  # 첫 이벤트 전 빈 줄(하트비트)
    ev.check_event_order(events, complete=True)
    assert [e.root.type for e in events] == ["progress", "progress", "answer", "done"]


def test_health_and_request_validation(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.post("/chat", json={"question": ""})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"


def test_pick_scenario_keywords():
    assert dfs.pick_scenario(dfs.SCENARIOS["server_error"]) == "server_error"
    assert dfs.pick_scenario(dfs.SCENARIOS["slow"]) == "slow"
    assert dfs.pick_scenario(dfs.SCENARIOS["not_found"]) == "not_found"
    assert dfs.pick_scenario(dfs.SCENARIOS["normal_found"]) == "normal_found"


# --------------------------------------------------------------------------- 설정·환경변수 비사용
def test_fake_settings_do_not_read_environment(monkeypatch):
    for name in service.REQUIRED_ENV:
        monkeypatch.setenv(name, "REAL-LOOKING-VALUE-SHOULD-NOT-BE-USED")
    s = dfs.fake_settings()
    assert service.missing_settings(s) == []
    assert all(getattr(s, n.lower()) == dfs.FAKE_SETTING for n in service.REQUIRED_ENV)


def test_script_does_not_import_app_main_or_open_env():
    for bad in ("import app.main", "from app.main", "from app import main", "get_settings", "load_dotenv", "os.environ", "getenv", '".env"'):
        assert bad not in SRC, bad


# --------------------------------------------------------------------------- 앱 본체에 가짜 스위치 없음
APP_BODY = [BACKEND / "app" / "main.py", *sorted((BACKEND / "app" / "api").glob("*.py"))]
FORBIDDEN = ("dev_fake", "DEV_FAKE", "fake_server", "FAKE_MODE", "fake_mode", "MEDIAGENT_FAKE", "KeywordToolModel", "KeywordSummary",
             "golden_synth", "ScriptedToolModel", "ScriptedSummary", "graph.fakes")


@pytest.mark.parametrize("path", APP_BODY, ids=lambda p: p.name)
def test_app_body_has_no_fake_switch(path):
    text = path.read_text(encoding="utf-8")
    hits = [w for w in FORBIDDEN if w in text]
    assert hits == [], f"{path.name}: {hits}"


# --------------------------------------------------------------------------- 바인딩 127.0.0.1 고정
def test_bind_host_is_loopback_and_not_configurable(monkeypatch):
    assert dfs.HOST == "127.0.0.1" and dfs.DEFAULT_PORT == 8000
    with pytest.raises(SystemExit):
        dfs.parse_args(["--host", "0.0.0.0"])  # noqa: S104 - 외부 바인딩 옵션이 없음을 확인하는 입력
    for bad in (["--port", "0"], ["--port", "70000"], ["--slow-seconds", "-1"]):
        with pytest.raises(SystemExit):
            dfs.parse_args(bad)

    import uvicorn

    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    dfs.main(["--port", "8123"])
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8123
