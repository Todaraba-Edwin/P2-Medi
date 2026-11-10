"""BE-15 gpt-6-luna 기능 확인 스크립트 시험. 실제 HTTP·키·원장 파일을 쓰지 않는다(가짜 post, 임시 원장)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import luna_feature_check as L  # noqa: E402

from app.llm.ledger import CostLedger  # noqa: E402

SECRET = "sk-test-SECRETVALUE1234567890abcdef"


def _chat(message: dict[str, Any], finish: str = "stop", p: int = 300, c: int = 100) -> dict[str, Any]:
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {"prompt_tokens": p, "completion_tokens": c}}


def _tc(name: str, args: str = '{"drug_name":"a","check":"combination"}') -> dict[str, Any]:
    return {"id": "x", "type": "function", "function": {"name": name, "arguments": args}}


GOOD_DRAFT = json.dumps({"sentences": [
    {"text": "병용 시 주의가 필요하다.", "evidence_ids": ["E1"], "claim_type": "fact", "citations": []},
    {"text": "약사에게 확인하세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]})


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_CACHE", "off")
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))


def _fake_post(calls: list[dict[str, Any]]) -> L.PostFn:
    def post(body: dict[str, Any]) -> tuple[int, Any]:
        calls.append(body)
        if "response_format" in body:
            return 200, _chat({"content": GOOD_DRAFT})
        n = 1 if body.get("parallel_tool_calls") is False else 2
        return 200, _chat({"content": None, "tool_calls": [_tc("check_contraindications")] * n}, "tool_calls")

    return post


def test_plan_makes_no_call_and_prints_cost(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(L, "http_post_factory", lambda key: (_ for _ in ()).throw(AssertionError("plan은 호출하지 않는다")))
    assert L.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "최대 4회" in out and "호출 0" in out and "$" in out


def test_run_requires_yes_and_cap(capsys: pytest.CaptureFixture[str]) -> None:
    assert L.main(["run"]) == 2
    assert L.main(["run", "--yes", "--max-usd", "0.5"]) == 2


def test_strict_schema_requires_all_properties_and_no_refs() -> None:
    s = L.to_strict_schema(L.AnswerDraft.model_json_schema())
    text = json.dumps(s)
    assert "$ref" not in text and "$defs" not in text and "default" not in text
    item = s["properties"]["sentences"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"text", "evidence_ids", "claim_type", "citations"}


def test_judge_structured_variants() -> None:
    assert L.judge_structured(_chat({"content": GOOD_DRAFT}))["verdict"] == "ok"
    assert L.judge_structured(_chat({"content": "not json"}))["verdict"] == "parse_fail"
    bad = json.dumps({"sentences": [{"text": "x", "evidence_ids": [], "claim_type": "opinion", "citations": []}]})
    assert L.judge_structured(_chat({"content": bad}))["verdict"] == "schema_invalid"
    assert L.judge_structured(_chat({"content": None, "refusal": "거절"}))["verdict"] == "refusal"
    assert L.judge_structured({"unexpected": 1})["verdict"] == "format_mismatch"
    unknown = json.dumps({"sentences": [{"text": "x", "evidence_ids": ["E9"], "claim_type": "fact", "citations": []}]})
    assert L.judge_structured(_chat({"content": unknown}))["unknown_evidence_ids"] == ["E9"]


def test_judge_parallel_variants() -> None:
    two = _chat({"tool_calls": [_tc("a"), _tc("b")]}, "tool_calls")
    assert L.judge_parallel(two, True)["verdict"] == "parallel"
    assert L.judge_parallel(two, False)["verdict"] == "off_ignored"
    one = _chat({"tool_calls": [_tc("a")]}, "tool_calls")
    assert L.judge_parallel(one, None)["verdict"] == "single"
    assert L.judge_parallel(one, False)["verdict"] == "off_honored"
    assert L.judge_parallel(_chat({"content": "text"}), True)["verdict"] == "no_tool_call"
    assert L.judge_parallel(_chat({"tool_calls": [_tc("a", "{bad")]}), True)["arguments_valid_json"] is False
    assert L.judge_parallel("???", True)["verdict"] == "format_mismatch"


def test_execute_runs_four_calls_records_cost_and_hides_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[dict[str, Any]] = []
    ledger = CostLedger()
    out = tmp_path / "out.json"
    report, _ = L.execute(_fake_post(calls), [r["label"] for r in L.build_requests()], 0.05, ledger, out)
    assert len(calls) == 4
    assert [r["judgement"]["verdict"] for r in report["results"]] == ["ok", "parallel", "off_honored", "parallel"]
    assert ledger.spent() == pytest.approx(report["spent_usd"])
    assert SECRET not in out.read_text(encoding="utf-8")
    assert "parallel_tool_calls" not in json.dumps(calls[3])  # 기본(옵션 생략) 호출


def test_execute_stops_before_call_when_cap_would_be_exceeded(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    report, _ = L.execute(_fake_post(calls), ["structured", "parallel_true"], 0.0001, CostLedger(), tmp_path / "o.json")
    assert calls == []
    assert [r["status"] for r in report["results"]] == ["skipped", "skipped"]


def test_http_error_is_recorded_not_raised_and_secret_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)

    def post(body: dict[str, Any]) -> tuple[int, Any]:
        return 400, {"error": {"message": f"unsupported response_format (key {SECRET})"}}

    out = tmp_path / "o.json"
    report, _ = L.execute(post, ["structured"], 0.05, CostLedger(), out)
    assert report["results"][0]["status"] == "http_error" and report["results"][0]["http_status"] == 400
    assert SECRET not in out.read_text(encoding="utf-8")
    assert all(SECRET not in line for line in L.summarize(report))
