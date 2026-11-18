"""BE-08 요약·병목 리포트(L3, RFP-34-02·03 A): 평가 trace(`logs/eval/<run_id>/spans.jsonl`, BE-15 L1 `mediagent.span@v1`)를 읽어 표로 낸다.
모델·도구·네트워크 호출 0. 내용 필드(입력·출력 요약, 근거 ID)는 읽지 않고 숫자·열거형 칸만 센다.

표:
  1) 노드별 지연(합·평균·p95·최대)·토큰(입력·출력·공급자 캐시 토큰)·비용   2) 도구별 지연·호출 수
  3) 종료 사유 분포   4) 호출 상한 도달(종료 사유 LIMIT 또는 모델 호출 수 ≥ 상한)   5) 하네스 이벤트(규칙·동작별 건수, 보조 기록)
  6) LLM 캐시(`cache` 칸: off·miss·stored·hit) 비율   7) 비용 대조: span 모델 비용 합 · trace 머리 `total_cost_usd` 합 · 결과 파일 `cost_usd.total`(원장 차이)
점검(종료 코드 1): 평가 측정에 캐시가 섞였는가(모든 모델 span의 `cache`가 `off`가 아니면), `mode`가 `eval`이 아닌 줄, 결과 파일이
`MEDIAGENT_EVAL=1`로 돈 기록이 아닌가(RFP-32-02), 세 비용 합이 허용 오차(기본 1e-4 USD 또는 1%)보다 크게 다른가.
9장 지표가 아니다(보조 기록). 결과 파일을 주면 `meta.agent_info.run_id`로 span 폴더를 찾는다.

사용(저장소 루트):
    backend/.venv/bin/python evaluation/l3_report.py --result logs/eval/RESULT.json [--json OUT.json]
    backend/.venv/bin/python evaluation/l3_report.py --spans logs/eval/<run_id>/spans.jsonl [--call-limit 8]
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG_EVAL = ROOT / "logs" / "eval"
SPAN_SCHEMA = "mediagent.span@v1"
DEFAULT_CALL_LIMIT = 8  # `app.agent.graph.state.MAX_MODEL_CALLS`(결과 `meta.run_settings.call_limit`가 있으면 그 값)
END_LIMIT = "LIMIT"
CACHE_OFF = "off"
COST_ABS_TOL = 1e-4
COST_REL_TOL = 0.01


def read_spans(path: Path) -> list[dict[str, Any]]:
    """JSONL을 읽는다. 깨진 줄은 건너뛰고 수를 센다(`_bad_lines`)."""
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(r, dict):
            rows.append(r)
    if bad:
        rows.append({"_bad_lines": bad})
    return rows


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _p95(xs: Sequence[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def _lat(xs: list[float]) -> dict[str, Any]:
    return {"n": len(xs), "sum_ms": round(sum(xs), 1), "mean_ms": round(sum(xs) / len(xs), 1) if xs else None,
            "p95_ms": _p95(xs), "max_ms": max(xs) if xs else None}


def is_head(r: dict[str, Any]) -> bool:
    """trace 머리 레코드(문항 하나의 합계, 로깅 전략 2장 (3)): 노드가 없고 `total_latency_ms`가 있다."""
    return r.get("node") is None and "total_latency_ms" in r


def summarize(spans: Iterable[dict[str, Any]], *, call_limit: int = DEFAULT_CALL_LIMIT) -> dict[str, Any]:
    rows = [r for r in spans if "_bad_lines" not in r]
    bad = sum(int(r["_bad_lines"]) for r in spans if "_bad_lines" in r)
    nodes: dict[str, dict[str, Any]] = {}
    tools: dict[str, list[float]] = {}
    heads = [r for r in rows if is_head(r)]
    cache: dict[str, int] = {}
    harness: dict[str, int] = {}
    span_cost = 0.0
    for r in rows:
        node, tool = r.get("node"), r.get("tool")
        lat = _num(r.get("latency_ms"))
        if tool:  # 도구 하위 span(노드 `tools` 아래 도구 하나)
            tools.setdefault(str(tool), []).append(lat or 0.0)
            continue
        if node:
            n = nodes.setdefault(str(node), {"lat": [], "tokens_in": 0, "tokens_out": 0, "tokens_cached": 0, "cost_usd": 0.0, "calls": 0})
            if lat is not None:
                n["lat"].append(lat)
            for k in ("tokens_in", "tokens_out", "tokens_cached"):
                n[k] += int(_num(r.get(k)) or 0)
            c = _num(r.get("cost_usd"))
            if c is not None:
                n["cost_usd"] += c
                span_cost += c
            if r.get("model"):
                n["calls"] += 1
                cache[str(r.get("cache") or "none")] = cache.get(str(r.get("cache") or "none"), 0) + 1
        he = r.get("harness_event")
        for ev in he if isinstance(he, list) else [he] if isinstance(he, dict) else []:
            key = f"{ev.get('rule')}·{ev.get('action')}"
            harness[key] = harness.get(key, 0) + 1
    ends: dict[str, int] = {}
    limit_items = 0
    for h in heads:
        end = str(h.get("end_reason"))
        ends[end] = ends.get(end, 0) + 1
        limit_items += end == END_LIMIT or int(_num(h.get("model_calls_so_far")) or 0) >= call_limit
    model_calls = sum(cache.values())
    hit = sum(v for k, v in cache.items() if k == "hit")
    return {
        "spans": len(rows), "bad_lines": bad, "traces": len(heads), "items": len({h.get("item_id") for h in heads}),
        "modes": sorted({str(r.get("mode")) for r in rows}), "conditions": sorted({str(r.get("condition")) for r in rows if r.get("condition")}),
        "by_node": {k: {**_lat(v["lat"]), "calls": v["calls"], "tokens_in": v["tokens_in"], "tokens_out": v["tokens_out"],
                        "tokens_cached": v["tokens_cached"], "cost_usd": round(v["cost_usd"], 6)} for k, v in sorted(nodes.items())},
        "by_tool": {k: _lat(v) for k, v in sorted(tools.items())},
        "end_reasons": dict(sorted(ends.items(), key=lambda x: -x[1])),
        "call_limit": call_limit, "limit_reached_items": limit_items,
        "harness_events": dict(sorted(harness.items())),
        "llm_cache": {"model_calls": model_calls, "by_state": dict(sorted(cache.items())), "hit": hit,
                      "hit_rate": round(hit / model_calls, 4) if model_calls else None},
        "provider_cached_tokens": {"tokens_in": sum(v["tokens_in"] for v in nodes.values()), "tokens_cached": sum(v["tokens_cached"] for v in nodes.values()),
                                   "note": "공급자(OpenAI) 프롬프트 캐시 토큰. 우리 LLM 캐시(`cache`)와 다르며 측정에 섞이는 값이 아니다"},
        "cost": {"span_model_sum": round(span_cost, 6), "trace_head_sum": round(sum(_num(h.get("total_cost_usd")) or 0.0 for h in heads), 6),
                 "head_latency_sum_ms": round(sum(_num(h.get("total_latency_ms")) or 0.0 for h in heads), 1)},
    }


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return True  # 비교할 값이 없으면 대조하지 않는다(표에 None으로 보인다)
    return abs(a - b) <= max(COST_ABS_TOL, COST_REL_TOL * max(abs(a), abs(b)))


def checks(summary: dict[str, Any], result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """측정 위생 점검. 각 행 `{item, ok, value}`."""
    rows = []
    cache = summary["llm_cache"]["by_state"]
    rows.append({"item": "LLM 캐시가 꺼진 측정(모든 모델 span cache=off, RFP-32-02)", "ok": set(cache) <= {CACHE_OFF}, "value": cache})
    rows.append({"item": "평가 모드 trace(mode=eval)", "ok": summary["modes"] == ["eval"], "value": summary["modes"]})
    rows.append({"item": "깨진 줄 없음", "ok": summary["bad_lines"] == 0, "value": summary["bad_lines"]})
    c = summary["cost"]
    rows.append({"item": "span 모델 비용 합 = trace 머리 합", "ok": _close(c["span_model_sum"], c["trace_head_sum"]),
                 "value": [c["span_model_sum"], c["trace_head_sum"]]})
    if result is not None:
        m = result.get("meta") or {}
        rows.append({"item": "결과 파일이 MEDIAGENT_EVAL=1 실행", "ok": str(m.get("eval_mode_env")) in ("1", "eval"), "value": m.get("eval_mode_env")})
        led = _num((result.get("cost_usd") or {}).get("total"))
        rows.append({"item": "원장 대조: 결과 cost_usd.total(원장 증가분, judge 제외) = span 모델 비용 합", "ok": _close(led, c["span_model_sum"]),
                     "value": [led, c["span_model_sum"]]})
        n_res = (m.get("n_items_run") or 0) * int(m.get("repeats") or 1) if not (m.get("first_run")) else None
        rows.append({"item": "trace 수 = 결과 문항 수 × 회차(1회차 재사용 실행은 대조 안 함)",
                     "ok": n_res is None or n_res == summary["traces"], "value": [summary["traces"], n_res]})
    return rows


def spans_path_for(result: dict[str, Any], log_dir: Path = LOG_EVAL) -> Path:
    run_id = ((result.get("meta") or {}).get("agent_info") or {}).get("run_id")
    if not run_id:
        raise FileNotFoundError("결과 meta에 run_id가 없다(graph 에이전트 결과가 아니다)")
    return log_dir / str(run_id) / "spans.jsonl"


def format_md(s: dict[str, Any], chk: Sequence[dict[str, Any]], title: str) -> str:
    out = [f"# L3 요약·병목 리포트: {title}", "",
           f"span {s['spans']} · trace {s['traces']} · 문항 {s['items']} · 조건 {', '.join(s['conditions']) or '-'} · 모드 {', '.join(s['modes'])}", "",
           "## 노드별", "", "| 노드 | span | 지연 합(ms) | 평균 | p95 | 최대 | 모델 호출 | 입력 토큰 | 출력 토큰 | 공급자 캐시 토큰 | 비용 USD |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in s["by_node"].items():
        out.append(f"| {k} | {v['n']} | {v['sum_ms']} | {v['mean_ms']} | {v['p95_ms']} | {v['max_ms']} | {v['calls']} | {v['tokens_in']} | {v['tokens_out']} | "
                   f"{v['tokens_cached']} | {v['cost_usd']} |")
    out += ["", "## 도구별", "", "| 도구 | 호출 | 지연 합(ms) | 평균 | p95 | 최대 |", "|---|---|---|---|---|---|"]
    out += [f"| {k} | {v['n']} | {v['sum_ms']} | {v['mean_ms']} | {v['p95_ms']} | {v['max_ms']} |" for k, v in s["by_tool"].items()]
    out += ["", "## 종료 사유·상한·하네스(보조)", "", "| 항목 | 값 |", "|---|---|",
            f"| 종료 사유 | {json.dumps(s['end_reasons'], ensure_ascii=False)} |",
            f"| 호출 상한({s['call_limit']}) 도달 문항 | {s['limit_reached_items']} / {s['traces']} |",
            f"| 하네스 이벤트(규칙·동작) | {json.dumps(s['harness_events'], ensure_ascii=False) or '-'} |",
            f"| LLM 캐시 | {json.dumps(s['llm_cache']['by_state'], ensure_ascii=False)}, 적중률 {s['llm_cache']['hit_rate']} |",
            f"| 공급자 캐시 토큰 / 입력 토큰 | {s['provider_cached_tokens']['tokens_cached']} / {s['provider_cached_tokens']['tokens_in']} |",
            f"| 비용: span 합 · 머리 합 | {s['cost']['span_model_sum']} · {s['cost']['trace_head_sum']} |"]
    out += ["", "## 점검", "", "| 점검 | 결과 | 값 |", "|---|---|---|"]
    out += [f"| {c['item']} | {'OK' if c['ok'] else 'NG'} | {json.dumps(c['value'], ensure_ascii=False)} |" for c in chk]
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--result", type=Path, help="eval_runner 결과 JSON(run_id로 span 폴더를 찾고 원장 대조를 한다)")
    src.add_argument("--spans", type=Path, help="spans.jsonl 경로(결과 파일 없이 trace만)")
    ap.add_argument("--log-dir", type=Path, default=LOG_EVAL, help="span 폴더의 위치(기본 logs/eval)")
    ap.add_argument("--call-limit", type=int, help=f"모델 호출 상한(기본: 결과 meta.run_settings.call_limit, 없으면 {DEFAULT_CALL_LIMIT})")
    ap.add_argument("--json", type=Path, help="요약·점검을 JSON으로도 쓴다")
    a = ap.parse_args(argv)
    result = json.loads(a.result.read_text(encoding="utf-8")) if a.result else None
    path = a.spans or spans_path_for(result or {}, a.log_dir)
    if not path.is_file():
        print(f"span 파일이 없다: {path}")
        return 2
    limit = a.call_limit or ((result or {}).get("meta") or {}).get("run_settings", {}).get("call_limit") or DEFAULT_CALL_LIMIT
    s = summarize(read_spans(path), call_limit=int(limit))
    chk = checks(s, result)
    print(format_md(s, chk, (a.result or path).name))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"summary": s, "checks": chk}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if all(c["ok"] for c in chk) else 1


if __name__ == "__main__":
    raise SystemExit(main())
