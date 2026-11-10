"""BE-15 LLM 캐시 어댑터(강제 off)와 개발 비용 원장(상한) 시험. 실호출 없음(fetch는 가짜)."""

import sys
import types

import pytest

from app.llm import BudgetExceeded, CostLedger, cache_mode, cached_openai_call
from app.llm.ledger import DEV_CAP_USD

MSGS = [{"role": "user", "content": "합성 질문"}]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_CACHE", raising=False)
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    # llm_cache가 불러오는 _common은 anthropic을 import한다. 백엔드 venv에는 없으므로 가짜 모듈로 대신한다(실호출 없음).
    monkeypatch.setitem(sys.modules, "anthropic", sys.modules.get("anthropic") or types.ModuleType("anthropic"))
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)
    yield
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)


def make_fetch(calls, cost=0.01):
    def fetch():
        calls.append(1)
        return "응답"

    return fetch


# ---- 캐시 모드 ----
def test_cache_mode_default_and_values(monkeypatch):
    assert cache_mode() == "off"
    monkeypatch.setenv("LLM_CACHE", "record")
    assert cache_mode() == "record"
    monkeypatch.setenv("LLM_CACHE", "bogus")
    with pytest.raises(ValueError):
        cache_mode()


def test_eval_flag_forces_cache_off(monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "record")
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    assert cache_mode() == "off"
    monkeypatch.setenv("LLM_CACHE", "replay")
    assert cache_mode() == "off"


def test_eval_never_uses_cache_even_if_record(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "record")
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    calls = []
    for _ in range(2):
        cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls))
    assert len(calls) == 2  # 매번 호출, 저장·적중 없음
    assert not list(tmp_path.glob("cache/*.json"))


def test_off_does_not_load_llm_cache_module():
    calls = []
    cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls))
    assert calls == [1] and "_mediagent_llm_cache" not in sys.modules


def test_record_then_hit_costs_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "record")
    ledger = CostLedger(tmp_path / "ledger.json")
    calls = []
    kw = dict(cost_fn=lambda _r: 0.01, ledger=ledger)
    a = cached_openai_call("gpt-6-luna", MSGS, {"t": 0}, make_fetch(calls), **kw)
    b = cached_openai_call("gpt-6-luna", MSGS, {"t": 0}, make_fetch(calls), **kw)
    assert a == b == "응답" and len(calls) == 1
    assert ledger.spent("dev") == pytest.approx(0.01)  # 적중은 비용 0


def test_replay_miss_raises_without_calling(monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "replay")
    calls = []
    with pytest.raises(Exception, match="replay"):
        cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls))
    assert calls == []


# ---- 원장 ----
def test_ledger_accumulates_and_persists(tmp_path):
    path = tmp_path / "l.json"
    CostLedger(path).add(0.5)
    assert CostLedger(path).add(0.25) == pytest.approx(0.75)
    assert CostLedger(path).spent("dev") == pytest.approx(0.75)


def test_ledger_default_cap_is_2_5():
    assert DEV_CAP_USD == 2.5


def test_ledger_blocks_real_call_over_cap(tmp_path):
    ledger = CostLedger(tmp_path / "l.json")
    ledger.add(2.4)
    ledger.guard(0.1)  # 정확히 상한이면 허용
    with pytest.raises(BudgetExceeded):
        ledger.guard(0.2)


def test_over_cap_blocks_fetch_but_allows_cache_hit(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "record")
    ledger = CostLedger(tmp_path / "l.json")
    calls = []
    cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls), cost_fn=lambda _r: 2.5, ledger=ledger)
    assert ledger.spent() == pytest.approx(2.5)
    # 같은 입력: 저장본 적중이라 상한과 무관
    assert cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls), estimate_usd=0.01, ledger=ledger) == "응답"
    # 다른 입력: 실호출이 필요하므로 중단
    with pytest.raises(BudgetExceeded):
        cached_openai_call("gpt-6-luna", [{"role": "user", "content": "다른"}], {}, make_fetch(calls), estimate_usd=0.01, ledger=ledger)
    assert len(calls) == 1


def test_off_mode_over_cap_stops_real_call(tmp_path):
    ledger = CostLedger(tmp_path / "l.json")
    ledger.add(2.5)
    calls = []
    with pytest.raises(BudgetExceeded):
        cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls), estimate_usd=0.01, ledger=ledger)
    assert calls == []


def test_eval_cost_counted_separately_and_not_capped(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    ledger = CostLedger(tmp_path / "l.json")
    ledger.add(2.5)  # dev 몫이 상한이어도
    calls = []
    cached_openai_call("gpt-6-luna", MSGS, {}, make_fetch(calls), cost_fn=lambda _r: 0.3, ledger=ledger)
    assert calls == [1] and ledger.spent("eval") == pytest.approx(0.3) and ledger.spent("dev") == pytest.approx(2.5)


def test_ledger_warns_near_cap(tmp_path, caplog):
    ledger = CostLedger(tmp_path / "l.json")
    with caplog.at_level("WARNING"):
        ledger.add(2.1)
    assert "개발 비용 원장" in caplog.text


def test_ledger_rejects_bad_input(tmp_path):
    ledger = CostLedger(tmp_path / "l.json")
    with pytest.raises(ValueError):
        ledger.add(-1)
    with pytest.raises(ValueError):
        ledger.add(1, bucket="x")
