"""BE-06-23 A 시험(2026-11-17): 서비스 경로 모델 호출을 개발 원장·개발 LLM 캐시에서 분리, `statuses` 누적 제거(BE-06-28 메모).

LLM·공공 API·원격 DB 호출 0, `.env` 미사용. 모델은 `llm.make_chat_model`을 가짜로 바꿔 **실제 래퍼**(`CachedToolModel`·`CachedSummary`)를
`build_deps`가 만들게 한다(래퍼를 건너뛰는 가짜 모델로는 원장·캐시 경로를 시험하지 못하므로). 질문은 합성이다(평가 세트·시험셋 문항 아님).

확인하는 것(지시서 §1):
  ① 원장 파일이 없거나(쓸 수 없는 경로) 개발 누적이 상한에 닿은 환경에서도 서비스 `/chat`이 `INTERNAL_ERROR`로 끝나지 않는다
     (같은 환경에서 개발 경로는 `INTERNAL_ERROR`로 끝나 시험이 차이를 잡는다는 것도 함께 본다)
  ② 서비스 경로는 `data/mock/`를 읽거나 쓰지 않는다(원장·캐시 객체도 만들지 않는다)
  ③ `mode=eval`·개발 경로의 원장·캐시 동작은 그대로다
  ④ 오래 켜 두어도 캐시 상태 기록이 늘지 않는다(상태별 횟수만, 키 4개 이하)
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import llm  # noqa: E402
from app.agent.graph import metered  # noqa: E402
from app.agent.graph.fakes import ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.metered import CachedSummary, CachedToolModel  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import service  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm import cache as llm_cache  # noqa: E402
from app.llm import ledger as ledger_mod  # noqa: E402
from app.llm.ledger import DEV_CAP_USD, CostLedger  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
ENV_NAMES = ("OPENAI_API_KEY", "SUPABASE_DB_URL", "DURPrdlstInfoService03_END_POINT", "DURPrdlstInfoService03_API_KEY",
             "DURIrdntInfoService03_END_POINT", "DURIrdntInfoService03_API_KEY")
USAGE = {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050}
PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
    {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}
MOCK_MARK = os.sep + os.path.join("data", "mock")


def _one_script() -> list[AIMessage]:
    msgs = [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]
    return [m.model_copy(update={"usage_metadata": USAGE}) for m in msgs]


class RawSummary:
    """`include_raw=True` 구조화 출력 모양의 가짜(토큰 메타 포함)."""

    def __init__(self, draft: dict[str, Any]) -> None:
        self.draft, self.calls = draft, 0

    def invoke(self, messages: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
        self.calls += 1
        return {"raw": AIMessage("{}", usage_metadata=USAGE), "parsed": self.draft, "parsing_error": None}


class FakeChat:
    """`llm.make_chat_model` 자리: 도구 묶기·구조화 출력만 흉내 낸다(외부 호출 0)."""

    def __init__(self, n_requests: int) -> None:
        self.n_requests = n_requests

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedToolModel:  # noqa: ARG002
        return ScriptedToolModel(script=[m for _ in range(self.n_requests) for m in _one_script()])

    def with_structured_output(self, *args: Any, **kwargs: Any) -> RawSummary:  # noqa: ARG002
        return RawSummary(PAIR_DRAFT)


def _settings() -> Settings:
    return Settings(_env_file=None, **{n.lower(): f"가짜값-{i}" for i, n in enumerate(ENV_NAMES)})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for n in ENV_NAMES:
        for name in (n, n.upper(), n.lower()):
            monkeypatch.delenv(name, raising=False)
    for name in ("MEDIAGENT_MODE", "MEDIAGENT_EVAL", "LLM_CACHE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm, "make_chat_model", lambda settings, purpose="tools", **kw: FakeChat(4))  # noqa: ARG005


def _cap_ledger(tmp_path: Path) -> Path:
    p = tmp_path / "ledger" / "openai_ledger.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"dev": DEV_CAP_USD, "eval": 0.0}), encoding="utf-8")
    return p


def _factory(*, service_path: bool, built: list[Any] | None = None) -> Any:
    def make(settings: Any) -> Any:
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
        deps = build_deps(dd, ctx, settings=settings, system_prompt="시험용 시스템 프롬프트", service=service_path)
        if built is not None:
            built.append(deps)
        return deps

    return make


def _chat(factory: Any, question: str = Q_PAIR, n: int = 1) -> list[list[ev.ChatEvent]]:
    runner = service.make_service_runner(_settings(), resources_factory=factory)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=None)
    client = TestClient(app)
    out = []
    for _ in range(n):
        r = client.post("/chat", json={"question": question})
        assert r.status_code == 200
        out.append([ev.ChatEvent.model_validate_json(x) for x in r.content.split(b"\n") if x])
    return out


def _types(events: list[ev.ChatEvent]) -> list[str]:
    return [e.root.type for e in events]


def _normal(events: list[ev.ChatEvent]) -> bool:
    return _types(events)[-2:] == ["answer", "done"] and events[-1].root.end_reason == "NORMAL"


# --------------------------------------------------------------------------- ① 상한·원장 파일 없음
def test_service_chat_is_normal_when_dev_ledger_is_at_cap(monkeypatch, tmp_path):
    ledger = _cap_ledger(tmp_path)
    before = ledger.read_bytes()
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(ledger))
    built: list[Any] = []
    (events,) = _chat(_factory(service_path=True, built=built))
    assert _normal(events) and "error" not in _types(events)
    assert ledger.read_bytes() == before  # 서비스 호출은 개발 원장에 더하지 않는다
    tm, sm = built[0].tool_model, built[0].summary_model
    assert tm.service and sm.service and tm.ledger is None and sm.ledger is None
    assert tm.usage["calls"] == 3 and sm.usage["calls"] == 1  # 비용·토큰은 메모리 합계로만
    assert tm.usage["input_tokens"] == 3 * USAGE["input_tokens"] and tm.usage["cost_usd"] > 0


def test_dev_path_in_same_env_ends_internal_error_so_the_test_can_tell(monkeypatch, tmp_path):
    """대조: 개발 경로(service=False)는 같은 환경에서 상한에 걸려 `INTERNAL_ERROR`로 끝난다(예전 서비스 동작)."""
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(_cap_ledger(tmp_path)))
    (events,) = _chat(_factory(service_path=False))
    assert _types(events)[-2:] == ["error", "done"] and "answer" not in _types(events)
    assert [e.root.code for e in events if e.root.type == "error"] == ["INTERNAL_ERROR"]


def test_service_chat_is_normal_when_ledger_path_cannot_exist(monkeypatch, tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(blocker / "openai_ledger.json"))  # 부모가 파일이라 원장을 만들 수 없다
    (events,) = _chat(_factory(service_path=True))
    assert _normal(events)
    assert not (blocker / "openai_ledger.json").exists()


def test_dev_path_with_unwritable_ledger_fails_for_contrast(monkeypatch, tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(blocker / "openai_ledger.json"))
    (events,) = _chat(_factory(service_path=False))
    assert [e.root.code for e in events if e.root.type == "error"] == ["INTERNAL_ERROR"]


# --------------------------------------------------------------------------- ② data/mock 접근 0
def test_service_path_never_reads_or_writes_data_mock_nor_builds_ledger_or_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "record")  # 개발 캐시를 켜 두어도 서비스는 타지 않는다
    touched: list[str] = []
    real_open = builtins.open

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if MOCK_MARK in os.fspath(file) if isinstance(file, (str, os.PathLike)) else False:
            touched.append(os.fspath(file))
            raise AssertionError("서비스 경로가 data/mock 파일을 열었다")
        return real_open(file, *args, **kwargs)

    def boom(*a: Any, **kw: Any) -> Any:
        touched.append("ledger-or-cache")
        raise AssertionError("서비스 경로가 개발 원장·캐시를 썼다")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(metered, "cached_openai_call_status", boom)
    monkeypatch.setattr(llm_cache, "_load_llm_cache", boom)
    monkeypatch.setattr(ledger_mod.CostLedger, "__init__", boom)
    monkeypatch.setattr(ledger_mod, "default_path", boom)
    results = _chat(_factory(service_path=True), n=2)
    assert all(_normal(evs) for evs in results)
    assert touched == []


def test_service_and_ledger_together_are_rejected():
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    with pytest.raises(ValueError, match="원장"):
        build_deps(dd, ctx, settings=_settings(), system_prompt="p", service=True, ledger=CostLedger(Path("/nonexistent/l.json")))
    with pytest.raises(ValueError, match="원장"):
        CachedToolModel(object(), ledger=CostLedger(Path("/nonexistent/l.json")), service=True)


def test_default_resources_builds_service_models():
    src = Path(service.__file__).read_text(encoding="utf-8")
    body = src.split("def default_resources", 1)[1].split("\ndef ", 1)[0]
    assert "service=True" in body and "ledger=None" in body and "DrugDict.load(" not in body


# --------------------------------------------------------------------------- ③ 평가·개발 경로 그대로
def _inner_tool() -> ScriptedToolModel:
    return ScriptedToolModel(script=[AIMessage("끝", usage_metadata=USAGE)], repeat_last=True)


@pytest.fixture
def cache_env(monkeypatch, tmp_path):
    """llm_cache를 tmp에 두고(실제 data/mock 캐시를 건드리지 않게) 원장도 tmp로(`test_ag01_followup`의 같은 이름 고정물과 같은 방식)."""
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setitem(sys.modules, "anthropic", sys.modules.get("anthropic") or types.ModuleType("anthropic"))
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)
    yield tmp_path
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)


def test_default_build_deps_is_dev_path_with_ledger(monkeypatch, tmp_path):
    led = CostLedger(tmp_path / "l.json")
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="eval")
    deps = build_deps(dd, ctx, settings=_settings(), system_prompt="p", ledger=led)
    assert not deps.tool_model.service and not deps.summary_model.service
    assert deps.tool_model.ledger is led and deps.summary_model.ledger is led


def test_dev_path_still_guards_and_records_ledger(tmp_path):
    led = CostLedger(tmp_path / "l.json")
    tm = CachedToolModel(_inner_tool(), ledger=led, estimate_usd=0.001)
    tm.invoke([AIMessage("질문")])
    assert led.spent("dev") == pytest.approx(llm.estimate_cost_usd(1000, 50)) and tm.status_counts == {"off": 1}
    led2 = CostLedger(tmp_path / "cap.json")
    led2.add(DEV_CAP_USD)
    with pytest.raises(ledger_mod.BudgetExceeded):
        CachedToolModel(_inner_tool(), ledger=led2, estimate_usd=0.001).invoke([AIMessage("질문")])


def test_eval_mode_still_counts_eval_bucket_and_cache_off(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    monkeypatch.setenv("LLM_CACHE", "record")
    led = CostLedger(tmp_path / "l.json")
    led.add(DEV_CAP_USD)  # dev 상한이어도 eval 몫은 막지 않는다(예전과 같음)
    tm = CachedToolModel(_inner_tool(), ledger=led, estimate_usd=0.001)
    tm.invoke([AIMessage("질문")])
    assert tm.status_counts == {"off": 1} and led.spent("eval") == pytest.approx(llm.estimate_cost_usd(1000, 50))


def test_dev_record_mode_still_stores_in_cache(monkeypatch, cache_env):
    monkeypatch.setenv("LLM_CACHE", "record")
    led = CostLedger(cache_env / "l.json")
    inner = _inner_tool()
    tm = CachedToolModel(inner, ledger=led, estimate_usd=0.001)
    tm.invoke([AIMessage("질문")])
    monkeypatch.setenv("LLM_CACHE", "replay")
    tm2 = CachedToolModel(_inner_tool(), ledger=led, estimate_usd=0.001)
    tm2.invoke([AIMessage("질문")])
    assert tm.status_counts == {"stored": 1} and tm2.status_counts == {"hit": 1}
    assert list((cache_env / "cache").glob("*.json"))


# --------------------------------------------------------------------------- ④ 기록이 늘지 않음
def test_long_running_service_model_keeps_constant_size_records():
    tm = CachedToolModel(_inner_tool(), service=True)
    sm = CachedSummary(RawSummary(PAIR_DRAFT), service=True)
    for _ in range(500):
        tm.invoke([AIMessage("질문")])
        sm.invoke([AIMessage("질문")])
    assert not hasattr(tm, "statuses") and not hasattr(sm, "statuses")
    assert tm.status_counts == {"off": 500} and sm.status_counts == {"off": 500}
    assert set(tm.usage) == {"calls", "input_tokens", "output_tokens", "cost_usd"}
    assert tm.usage["calls"] == 500 and tm.usage["output_tokens"] == 500 * USAGE["output_tokens"]


def test_dev_path_status_record_is_also_bounded(tmp_path):
    tm = CachedToolModel(_inner_tool(), ledger=CostLedger(tmp_path / "l.json"))
    for _ in range(300):
        tm.invoke([AIMessage("질문")])
    assert tm.status_counts == {"off": 300} and len(tm.status_counts) == 1


def test_shared_service_model_counts_are_exact_under_threads():
    tm = CachedToolModel(_inner_tool(), service=True)

    def go() -> None:
        for _ in range(50):
            tm.invoke([AIMessage("질문")])

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert tm.usage["calls"] == 400 and tm.status_counts == {"off": 400}
