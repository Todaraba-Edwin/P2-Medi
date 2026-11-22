"""AG-01 `:31`: 에이전트 모델 이름을 설정으로 바꿀 수 있다(2026-11-20). LLM·공공 API·원격 DB 호출 0, `.env` 미사용.

- `Settings.mediagent_agent_model`(환경변수 `MEDIAGENT_AGENT_MODEL`, 기본 `gpt-6-luna` = `llm.MODEL`).
- 서비스 경로(`build_deps(service=True)`)만 설정을 따른다. 평가·개발 경로는 설정 값과 무관하게 `llm.MODEL`(평가 고정).
- `build_deps(model_name=...)` 명시가 가장 우선한다. 모델 객체는 만들기만 하고 호출하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import llm  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.config import Settings  # noqa: E402

OTHER = "gpt-시험용-다른모델"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDIAGENT_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """`llm.make_chat_model`이 받은 (purpose, model)을 기록한다(실제 객체는 원래 함수가 만든다, 호출은 없음)."""
    seen: list[tuple[str, str]] = []
    real = llm.make_chat_model

    def wrapped(settings: Any, **kw: Any) -> Any:
        seen.append((kw.get("purpose", "tools"), kw.get("model", llm.MODEL)))
        return real(settings, **kw)

    monkeypatch.setattr(llm, "make_chat_model", wrapped)
    return seen


def _deps(settings: Settings, **kw: Any) -> Any:
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service" if kw.get("service") else "eval", dur_client=FakeDur(), conn_factory=golden_conn)
    return build_deps(dd, ctx, settings=settings, system_prompt="시험용 시스템 프롬프트", **kw)


def test_default_matches_llm_model() -> None:
    assert Settings(_env_file=None).mediagent_agent_model == llm.MODEL == "gpt-6-luna"


def test_env_var_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIAGENT_AGENT_MODEL", OTHER)
    assert Settings(_env_file=None).mediagent_agent_model == OTHER


def test_service_path_follows_setting(spy: list[tuple[str, str]]) -> None:
    deps = _deps(Settings(_env_file=None, mediagent_agent_model=OTHER), service=True)
    assert spy == [("tools", OTHER), ("summary", OTHER)]
    assert deps.tool_model.model == OTHER and deps.summary_model.model == OTHER


def test_service_path_default_unchanged(spy: list[tuple[str, str]]) -> None:
    deps = _deps(Settings(_env_file=None), service=True)
    assert spy == [("tools", llm.MODEL), ("summary", llm.MODEL)]
    assert deps.tool_model.model == llm.MODEL and deps.summary_model.model == llm.MODEL


def test_eval_path_ignores_setting(spy: list[tuple[str, str]]) -> None:
    """평가·개발 경로(service=False)는 설정에 다른 이름이 있어도 `llm.MODEL`(평가 고정, 결과 meta와 같은 값)."""
    deps = _deps(Settings(_env_file=None, mediagent_agent_model=OTHER), service=False)
    assert spy == [("tools", llm.MODEL), ("summary", llm.MODEL)]
    assert deps.tool_model.model == llm.MODEL and deps.summary_model.model == llm.MODEL


@pytest.mark.parametrize("service", [True, False])
def test_explicit_model_name_wins(spy: list[tuple[str, str]], service: bool) -> None:
    deps = _deps(Settings(_env_file=None, mediagent_agent_model="무시될이름"), service=service, model_name=OTHER)
    assert spy == [("tools", OTHER), ("summary", OTHER)]
    assert deps.tool_model.model == OTHER


def test_blank_setting_falls_back(spy: list[tuple[str, str]]) -> None:
    _deps(Settings(_env_file=None, mediagent_agent_model="  "), service=True)
    assert spy == [("tools", llm.MODEL), ("summary", llm.MODEL)]


def test_chat_model_receives_name() -> None:
    m = llm.make_chat_model(Settings(_env_file=None), purpose="tools", model=OTHER)
    assert m.model_name == OTHER and m.reasoning_effort == "none" and m.use_responses_api is False
