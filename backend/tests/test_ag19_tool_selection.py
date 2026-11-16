"""AG-19 점검 스크립트(`scripts/ag19_tool_selection.py`) 시험. 외부 호출 0(`httpx.MockTransport`), 실호출 `run`은 하지 않는다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ag19_tool_selection as S  # noqa: E402

from app.llm.ledger import CostLedger  # noqa: E402
from app.llm.prompts import DEV_SET_PATH, load_dev_questions  # noqa: E402


def test_thirty_unique_synthetic_queries_covering_all_categories():
    qs = S.build_queries()
    assert len(qs) == 30 and len({q.text for q in qs}) == 30 and len({q.qid for q in qs}) == 30
    assert {q.cat for q in qs} == set(S.CATS)
    assert sum(q.parallel_needed for q in qs) == 6


def test_queries_do_not_reuse_dev_set_questions():
    dev = set(load_dev_questions(DEV_SET_PATH).values()) if DEV_SET_PATH.exists() else set()
    norm = lambda t: "".join(t.split())  # noqa: E731
    assert not ({norm(q.text) for q in S.build_queries()} & dev)  # 시험셋은 열지 않았다(개발셋과의 중복만 확인)


def test_plan_within_cap_and_no_network():
    p = S.plan()
    assert p["calls"] == 30 and p["within_cap"] and p["upper_bound_usd"] < 0.05 and p["reasoning_effort"] == "none"


def test_judge_rules():
    qs = {q.qid: q for q in S.build_queries()}
    pair = qs["ag19-p01"]
    two = [{"name": "identify_drug", "args": {"name": pair.drugs[0]}}, {"name": "identify_drug", "args": {"name": pair.drugs[1]}}]
    r = S.judge(pair, two)
    assert r["tool_ok"] and r["args_ok"] and r["parallel"]
    one = [{"name": "check_contraindications", "args": {"drugs": [{"name": pair.drugs[0]}, {"name": pair.drugs[1]}]}}]
    r = S.judge(pair, one)
    assert r["tool_ok"] and r["args_ok"] and not r["parallel"] and r["single_call_covers_pair"]
    assert not S.judge(pair, [{"name": "identify_drug", "args": {"name": pair.drugs[0]}}])["args_ok"]  # 한 약만 덮음
    assert not S.judge(pair, [{"name": "search_notice", "args": {"query": "x"}}])["tool_ok"]
    assert not S.judge(pair, [{"name": "identify_drug", "args": {"nam": "x"}}])["args_ok"]  # Pydantic 위반
    assert not S.judge(pair, [])["tool_ok"]
    preg = qs["ag19-a01"]
    assert S.judge(preg, [{"name": "check_contraindications", "args": {"drugs": [{"name": preg.drugs[0]}], "pregnancy": True}}])["args_ok"]
    assert not S.judge(preg, [{"name": "check_contraindications", "args": {"drugs": [{"name": preg.drugs[0]}]}}])["args_ok"]
    age = qs["ag19-a04"]
    assert S.judge(age, [{"name": "check_contraindications", "args": {"drugs": [{"name": age.drugs[0]}], "age": {"value": 5, "unit": "세"}}}])["args_ok"]


def test_wilson_and_summary_small_n_no_significance():
    lo, hi = S.wilson(5, 6)
    assert 0.4 < lo < 0.6 and 0.9 < hi < 1.0 and S.wilson(0, 0) == (0.0, 0.0)
    rows = [{"cat": "pair", "tool_ok": True, "args_ok": True, "parallel": i < 3} for i in range(6)]
    s = S.summarize(rows)
    assert s["pair_parallel"]["k"] == 3 and s["pair_parallel"]["n"] == 6 and s["pair_parallel"]["claim_significance"] is False


def test_run_refused_without_yes(capsys):
    assert S.main(["run"]) == 2
    assert S.main(["run", "--yes", "--max-usd", "1"]) == 2  # 상한을 올릴 수 없다


def test_run_with_mock_transport_records_and_respects_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-NOT-A-REAL-KEY-0000")
    n_req = []

    def handler(req: httpx.Request) -> httpx.Response:
        n_req.append(json.loads(req.content))
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "identify_drug", "arguments": json.dumps({"name": "타이레놀정"})}}]}
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "gpt-6-luna",
                                         "choices": [{"index": 0, "finish_reason": "tool_calls", "message": msg}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})

    qs = S.build_queries()[:3]
    out = tmp_path / "res.json"
    res = S.run(0.05, CostLedger(tmp_path / "led.json", cap_usd=1.0), http_client=httpx.Client(transport=httpx.MockTransport(handler)), out_path=out, queries=qs)
    assert res["n_ok"] == 3 and len(n_req) == 3 and all(b["reasoning_effort"] == "none" and b["parallel_tool_calls"] is True for b in n_req)
    assert all(b["max_completion_tokens"] == S.CALL_OUT_CAP for b in n_req)
    assert "sk-test" not in out.read_text(encoding="utf-8")
    saved = json.loads(out.read_text(encoding="utf-8"))  # 결과 파일에 프롬프트 버전과 호출 설정을 남긴다
    assert saved["prompt"] == S.PROMPT_NAME == "agent_system@v2"
    assert saved["call_settings"] == {"model": "gpt-6-luna", "reasoning_effort": "none", "parallel_tool_calls": True, "max_completion_tokens": S.CALL_OUT_CAP}
    # 상한이 너무 낮으면 호출하지 않고 skipped
    n_req.clear()
    res2 = S.run(0.00001, CostLedger(tmp_path / "led2.json", cap_usd=1.0), http_client=httpx.Client(transport=httpx.MockTransport(handler)), out_path=out, queries=qs)
    assert res2["n_ok"] == 0 and n_req == [] and res2["n_skipped"] == 3


@pytest.mark.parametrize("flag", ["--yes"])
def test_script_has_no_live_default(flag):
    assert flag in S.__doc__
