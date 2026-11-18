"""BE-08 L3 요약·병목 리포트 시험(RFP-34-02·03, RFP-32-02, 2026-11-18). 합성 span만 쓴다(호출 0)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "evaluation") not in sys.path:
    sys.path.insert(0, str(ROOT / "evaluation"))

import l3_report as L  # noqa: E402


def _trace(item: str, *, cache: str = "off", end: str = "NORMAL", calls: int = 2, cost: float = 0.001, mode: str = "eval") -> list[dict[str, Any]]:
    base = {"schema": L.SPAN_SCHEMA, "mode": mode, "run_id": "r1", "trace_id": f"t-{item}", "item_id": item, "condition": "C2"}
    rows = [{**base, "node": "guardrail_in", "latency_ms": 0}, {**base, "node": "router", "latency_ms": 20}]
    for i in range(calls):
        rows.append({**base, "node": "model", "step": i + 1, "latency_ms": 1000 + i, "model": "gpt-6-luna", "cache": cache,
                     "tokens_in": 100, "tokens_out": 10, "tokens_cached": 50, "cost_usd": cost / calls, "input_summary": {"x": "내용"}})
    rows += [{**base, "node": "tools", "latency_ms": 300}, {**base, "node": "tools", "tool": "check_contraindications", "latency_ms": 290},
             {**base, "node": "validator", "latency_ms": 1, "harness_event": [{"rule": "H2", "action": "warn"}]},
             {**base, "node": "finalize", "latency_ms": 0, "end_reason": end},
             {**base, "model": "gpt-6-luna", "end_reason": end, "total_latency_ms": 2400, "total_cost_usd": cost, "model_calls_so_far": calls}]
    return rows


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    p = tmp_path / "logs" / "r1" / "spans.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def test_summary_tables_count_nodes_tools_end_reasons_limit_and_cost(tmp_path):
    rows = _trace("a") + _trace("b", end="LIMIT", calls=8, cost=0.004)
    s = L.summarize(L.read_spans(_write(tmp_path, rows)), call_limit=8)
    assert s["traces"] == 2 and s["items"] == 2
    assert s["by_node"]["model"]["calls"] == 10 and s["by_node"]["model"]["tokens_in"] == 1000 and s["by_node"]["model"]["tokens_cached"] == 500
    assert s["by_tool"]["check_contraindications"]["n"] == 2 and s["by_tool"]["check_contraindications"]["sum_ms"] == 580
    assert s["end_reasons"] == {"NORMAL": 1, "LIMIT": 1} and s["limit_reached_items"] == 1
    assert s["harness_events"] == {"H2·warn": 2}
    assert s["cost"]["span_model_sum"] == s["cost"]["trace_head_sum"] == 0.005
    assert "tools" in s["by_node"] and s["by_node"]["tools"]["n"] == 2  # 도구 하위 span은 노드 칸에 섞이지 않는다


def test_checks_pass_for_a_clean_eval_run_and_compare_the_ledger(tmp_path):
    p = _write(tmp_path, _trace("a") + _trace("b"))
    result = {"meta": {"eval_mode_env": "1", "n_items_run": 2, "repeats": 1, "agent_info": {"run_id": "r1"}, "run_settings": {"call_limit": 8}},
              "cost_usd": {"total": 0.002}}
    rp = tmp_path / "res.json"
    rp.write_text(json.dumps(result), encoding="utf-8")
    assert L.spans_path_for(result, tmp_path / "logs") == p
    assert L.main(["--result", str(rp), "--log-dir", str(tmp_path / "logs"), "--json", str(tmp_path / "out.json")]) == 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert all(c["ok"] for c in out["checks"]) and "내용" not in (tmp_path / "out.json").read_text(encoding="utf-8")


def test_a_cache_hit_or_non_eval_mode_fails_the_check(tmp_path):
    p = _write(tmp_path, _trace("a", cache="hit") + _trace("b", mode="dev"))
    assert L.main(["--spans", str(p)]) == 1
    s = L.summarize(L.read_spans(p))
    assert s["llm_cache"]["hit"] == 2 and s["llm_cache"]["hit_rate"] == 0.5
    bad = {c["item"] for c in L.checks(s, None) if not c["ok"]}
    assert any("캐시" in b for b in bad) and any("mode=eval" in b for b in bad)


def test_ledger_mismatch_and_wrong_eval_flag_are_reported(tmp_path):
    _write(tmp_path, _trace("a"))
    s = L.summarize(L.read_spans(tmp_path / "logs" / "r1" / "spans.jsonl"))
    res = {"meta": {"eval_mode_env": None, "n_items_run": 1, "repeats": 1}, "cost_usd": {"total": 0.5}}
    bad = [c["item"] for c in L.checks(s, res) if not c["ok"]]
    assert any("원장" in b for b in bad) and any("MEDIAGENT_EVAL" in b for b in bad)


def test_broken_lines_are_counted_not_fatal(tmp_path):
    p = _write(tmp_path, _trace("a"))
    with p.open("a", encoding="utf-8") as f:
        f.write("{broken\n")
    s = L.summarize(L.read_spans(p))
    assert s["bad_lines"] == 1 and s["traces"] == 1
