"""BE-08 모델별 1회 호출 측정 스크립트 시험(RFP-24-03, 2026-11-18). 가짜 클라이언트만 쓴다(실호출 0)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "evaluation") not in sys.path:
    sys.path.insert(0, str(ROOT / "evaluation"))

import model_probe as P  # noqa: E402


class Raw:
    def __init__(self, parsed: Any, headers: dict[str, str]) -> None:
        self._p, self.headers = parsed, headers

    def parse(self) -> Any:
        return self._p


class FakeOpenAI:
    def __init__(self, reject_temperature: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reject = reject_temperature
        self.chat = NS(completions=NS(with_raw_response=NS(create=self._create)))

    def _create(self, **kw: Any) -> Raw:
        self.calls.append(kw)
        if self.reject and "temperature" in kw:
            err = RuntimeError("bad param")
            err.status_code = 400  # type: ignore[attr-defined]
            raise err
        r = NS(usage=NS(prompt_tokens=100, completion_tokens=50, completion_tokens_details=NS(reasoning_tokens=10)),
               choices=[NS(finish_reason="stop", message=NS(content="합성 답"))])
        return Raw(r, {"x-ratelimit-remaining-requests": "99", "set-cookie": "secret"})


class FakeAnthropic:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = NS(with_raw_response=NS(create=self._create))

    def _create(self, **kw: Any) -> Raw:
        self.calls.append(kw)
        return Raw(NS(usage=NS(input_tokens=120, output_tokens=60), stop_reason="end_turn", content=[NS(text="합성 답")]),
                   {"anthropic-ratelimit-requests-remaining": "49"})


def test_probe_calls_each_model_once_and_records_tokens_cost_latency_limits():
    oa, an, up = FakeOpenAI(), FakeAnthropic(), FakeOpenAI()
    added: list[float] = []
    res = P.run_probe({"openai": oa, "anthropic": an, "upstage": up}, max_usd=0.10, ledger_add=added.append)
    by = {r["name"]: r for r in res["rows"]}
    assert [r["status"] for r in res["rows"]] == ["ok"] * 4 and len(oa.calls) == 1 and len(an.calls) == 2 and len(up.calls) == 1
    assert oa.calls[0]["reasoning_effort"] == "none" and up.calls[0]["temperature"] == 0 and by["solar-pro4"]["temperature_supported"] is True
    assert an.calls[1]["thinking"] == {"type": "between_tools"} and "thinking" not in an.calls[0]  # Sonnet만 사고 끄기
    assert by["gpt-6-luna"]["cost_usd"] == round(100 * 0.10 / 1e6 + 50 * 0.50 / 1e6, 7) and added == [by["gpt-6-luna"]["cost_usd"]]
    assert by["gpt-6-luna"]["rate_limits"] == {"x-ratelimit-remaining-requests": "99"}  # 한도 헤더만, 나머지 헤더는 버린다
    assert res["total_cost_usd"] == round(sum(r["cost_usd"] for r in res["rows"]), 7) and "합성 답" not in str(res)


def test_upstage_temperature_rejection_is_recorded_and_retried_once_without_it():
    up = FakeOpenAI(reject_temperature=True)
    res = P.run_probe({"openai": FakeOpenAI(), "anthropic": FakeAnthropic(), "upstage": up}, max_usd=0.10)
    row = next(r for r in res["rows"] if r["name"] == "solar-pro4")
    assert row["status"] == "ok" and row["temperature_supported"] is False and len(up.calls) == 2 and "temperature" not in up.calls[1]
    assert row["attempts"][0]["status_code"] == 400


def test_budget_skips_calls_whose_worst_case_would_exceed_the_cap():
    res = P.run_probe({"openai": FakeOpenAI(), "anthropic": FakeAnthropic(), "upstage": FakeOpenAI()}, max_usd=0.0012)  # luna·Upstage 최악 비용만 들어간다
    assert [r["status"] for r in res["rows"]] == ["ok", "skipped_budget", "ok", "skipped_budget"]


def test_execute_refuses_without_yes_or_with_a_cap_below_the_worst_case(capsys):
    assert P.worst_case_usd() < 0.10
    assert P.main(["--execute", "--max-usd", "0.10"]) == 2
    assert P.main(["--execute", "--yes", "--max-usd", "0.001"]) == 2
    assert P.main([]) == 0 and "dry-run" in capsys.readouterr().out
