"""AG-19 도구 선택 사전 점검(개발용 합성 질의 약 30개, 기대 도구 경로는 규칙으로 확정). **실호출 `run`은 사용자 승인 뒤에만 `--yes`로 실행한다.**

하위 명령(작업 위치 `backend/`):
  plan                          질의 수·예상 토큰·예상 비용만 출력(호출 0, 네트워크·키 사용 없음)
  run --yes --max-usd 0.05      실호출(질의당 1회, 첫 단계 도구 호출만 본다). 이번 작업에서는 실행하지 않았다.

규칙:
- 질의는 템플릿 × 약 이름 풀로 코드가 만든다(평가 세트·시험셋·페르소나 질문 아님, RFP-26-04). 기대 경로도 같은 규칙에서 나온다.
- 판정은 코드가 한다: 첫 단계 도구 선택(허용 도구 집합), 인자 정확도(Pydantic 통과 + 의미 규칙), 병렬(두 약 병용 질의에서 한 응답의 도구 호출 ≥ 2).
- 결과는 k/n과 Wilson 95% 구간으로 쓴다. 칸당 n이 8 이하이면 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절).
- 키는 `Settings`로만 읽고 출력하지 않는다. 결과 파일(`data/mock/dict/ag19_tool_selection.json`, 로컬 전용)에는 키·헤더가 없다.
- 호출 전 `--max-usd` 하드 상한과 개발 원장(`app.llm.ledger`) guard를 모두 지킨다. 호출 뒤 비용은 원장에 기록한다(`LedgerCallback`).
- 단가(USD/100만 토큰): 입력 0.10, 캐시 입력 0.01, 출력 0.50(`gpt-6-luna`).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.utils.function_calling import convert_to_openai_tool  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.agent.graph.prompt import load_system_prompt  # noqa: E402
from app.agent.llm import PRICE_IN, PRICE_OUT, LedgerCallback, bind_tools_model, make_chat_model  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.langchain_adapter import build_tools  # noqa: E402
from app.agent.tools.registry import REGISTRY  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.ledger import BudgetExceeded, CostLedger  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402

install_excepthook()

HARD_CAP_USD = 0.05
EXPECTED_OUT_TOKENS = 150     # 도구 호출 응답 길이 어림(상한 추정에는 쓰지 않고 예상 비용에만 쓴다)
CALL_OUT_CAP = 400            # 첫 단계 점검은 도구 호출만 보므로 출력 상한을 낮게 둔다(상한 추정에 쓴다)
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "mock" / "dict" / "ag19_tool_selection.json"

DRUGS = ["타이레놀정", "부루펜정", "와파린정", "아스피린프로텍트정", "게보린정", "슈도에페드린정"]
CATS = ("single", "pair", "age_preg", "label", "notice", "reason")
FIRST_TOOLS = {  # 카테고리별 첫 단계로 허용하는 도구
    "single": {"identify_drug"},
    "pair": {"identify_drug", "check_contraindications"},
    "age_preg": {"identify_drug", "check_contraindications"},
    "label": {"identify_drug", "search_label"},
    "notice": {"search_notice"},
    "reason": {"identify_drug", "check_contraindications", "search_reason"},
}


@dataclass(frozen=True)
class Query:
    qid: str
    cat: str
    text: str
    drugs: tuple[str, ...] = ()
    pregnancy: bool = False
    age: int | None = None
    parallel_needed: bool = False
    expected: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


def build_queries() -> list[Query]:
    """합성 질의 30개. 템플릿과 약 이름 풀의 조합이라 규칙으로 재현된다."""
    out: list[Query] = []
    d = DRUGS
    single_t = ["{a}은 어떤 약인가요", "{a} 성분이 뭔지 알려 주세요", "{a}이 무슨 약인지 설명해 주세요", "{a} 약 정보를 찾아 주세요", "{a}이 어떤 약인지 궁금해요", "집에 {a}이 있는데 이게 뭔 약이에요"]
    for i, t in enumerate(single_t):
        out.append(Query(f"ag19-s{i + 1:02d}", "single", t.format(a=d[i]), (d[i],)))
    pair_t = ["{a}이랑 {b} 같이 먹으면 안 되는 조합인가요", "{a}과 {b}를 함께 복용해도 되는지 확인해 주세요", "{a}, {b} 병용금기인가요",
              "{a} 먹고 {b}도 먹었는데 같이 먹으면 문제 되나요", "{a}하고 {b} 동시에 먹을 수 있나요", "{a}와 {b}의 병용 주의가 있는지 알려 주세요"]
    for i, t in enumerate(pair_t):
        a, b = d[i], d[(i + 2) % len(d)]
        out.append(Query(f"ag19-p{i + 1:02d}", "pair", t.format(a=a, b=b), (a, b), parallel_needed=True))
    ap = [("임신 중인데 {a} 먹어도 되는지 확인해 줘", True, None), ("임산부가 {a}을 먹어도 되나요", True, None), ("임신 초기인데 {a} 복용 가능한가요", True, None),
          ("{n}살 아이가 {a} 먹어도 되나요", False, 5), ("{n}살 아이에게 {a}을 줘도 되는지 확인해 주세요", False, 3), ("{n}세 어린이가 {a} 복용해도 되나요", False, 8)]
    for i, (t, preg, age) in enumerate(ap):
        out.append(Query(f"ag19-a{i + 1:02d}", "age_preg", t.format(a=d[i], n=age), (d[i],), pregnancy=preg, age=age))
    label_t = ["{a} 허가사항에 주의사항이 어떻게 적혀 있나요", "{a}의 사용상 주의사항을 보여 주세요", "{a} 효능 효과가 뭐라고 되어 있어요", "{a} 용법용량 허가사항 원문을 알려 주세요"]
    for i, t in enumerate(label_t):
        out.append(Query(f"ag19-l{i + 1:02d}", "label", t.format(a=d[i + 1]), (d[i + 1],)))
    notice_t = ["병용금기 지정 규정에서 용어를 어떻게 정의하나요", "임부금기 1등급이 고시에서 어떤 뜻으로 정의되어 있나요",
                "고시 별표에 병용금기로 지정된 성분 목록이 있나요", "병용금기 성분 지정에 관한 규정의 조문을 찾아 주세요"]
    for i, t in enumerate(notice_t):
        out.append(Query(f"ag19-n{i + 1:02d}", "notice", t))
    reason_t = ["{a}과 {b}가 병용금기인 이유가 뭔가요", "{a}와 {b}를 같이 먹으면 안 되는 사유를 알려 주세요", "{a}이 임부금기인 이유가 상세정보에 뭐라고 나와 있나요", "{a}의 연령금기 사유를 알려 주세요"]
    for i, t in enumerate(reason_t):
        a, b = d[i], d[(i + 3) % len(d)]
        out.append(Query(f"ag19-r{i + 1:02d}", "reason", t.format(a=a, b=b), (a, b) if "{b}" in t else (a,)))
    return out


# --------------------------------------------------------------------------- 판정(코드)
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _covers(text: Any, names: Sequence[str]) -> bool:
    s = json.dumps(text, ensure_ascii=False)
    return all(n[:2] in s for n in names)  # 약 이름 앞 두 글자 포함(조사·표기 변이를 허용하는 느슨한 규칙)


def judge(q: Query, calls: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """`calls`는 `[{"name":..., "args":{...}}]`. 첫 단계 도구 선택·인자·병렬을 코드로 판정한다."""
    names = [c.get("name") for c in calls]
    tool_ok = bool(calls) and all(n in FIRST_TOOLS[q.cat] for n in names)
    valid = bool(calls)
    for c in calls:
        spec = REGISTRY.get(str(c.get("name")))
        if spec is None:
            valid = False
            continue
        try:
            spec.args_model.model_validate(c.get("args") or {})
        except ValidationError:
            valid = False
    sem = valid
    if valid and q.drugs:
        if q.cat == "pair":
            sem = _covers([c["args"] for c in calls], q.drugs)
        else:
            sem = _covers([c["args"] for c in calls], q.drugs[:1])
    if valid and q.cat == "age_preg":
        for c in calls:
            if c["name"] == "check_contraindications":
                a = c["args"]
                if q.pregnancy and a.get("pregnancy") is not True:
                    sem = False
                if q.age is not None and not (a.get("age") and float(a["age"].get("value", -1)) == float(q.age)):
                    sem = False
    args_ok = bool(calls) and valid and sem
    parallel = len(calls) >= 2
    return {"qid": q.qid, "cat": q.cat, "names": names, "tool_ok": tool_ok, "args_ok": args_ok, "parallel": parallel,
            "single_call_covers_pair": q.cat == "pair" and len(calls) == 1 and tool_ok and args_ok}


def summarize(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def cell(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
        k, n = sum(1 for r in rows if r[key]), len(rows)
        lo, hi = wilson(k, n)
        return {"k": k, "n": n, "wilson95": [round(lo, 3), round(hi, 3)], "claim_significance": n > 8}

    out: dict[str, Any] = {"overall": {m: cell(results, m) for m in ("tool_ok", "args_ok")}, "by_cat": {}}
    for c in CATS:
        rows = [r for r in results if r["cat"] == c]
        if rows:
            out["by_cat"][c] = {m: cell(rows, m) for m in ("tool_ok", "args_ok")}
    pair = [r for r in results if r["cat"] == "pair"]
    if pair:
        out["pair_parallel"] = cell(pair, "parallel")
    return out


# --------------------------------------------------------------------------- 요청·비용
def request_body(q: Query, system_prompt: str, tool_defs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"model": "gpt-6-luna", "reasoning_effort": "none", "parallel_tool_calls": True, "max_completion_tokens": CALL_OUT_CAP,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": q.text}], "tools": tool_defs}


def estimate_usd(body: dict[str, Any]) -> float:
    """상한 추정: 입력은 직렬화 글자 수를 토큰 수로 보수적으로 보고, 출력은 상한 전체로 잡는다."""
    return len(json.dumps(body, ensure_ascii=False)) * PRICE_IN / 1e6 + CALL_OUT_CAP * PRICE_OUT / 1e6


def _tool_defs() -> list[dict[str, Any]]:
    return [convert_to_openai_tool(t) for t in build_tools(ToolContext(drug_dict=None))]  # type: ignore[arg-type]


def plan(max_usd: float = HARD_CAP_USD) -> dict[str, Any]:
    qs = build_queries()
    sp = load_system_prompt(allow_draft=True)  # 초안 프롬프트로 점검한다(사용자 승인 전, 채택 아님)
    defs = _tool_defs()
    bodies = [request_body(q, sp, defs) for q in qs]
    chars = [len(json.dumps(b, ensure_ascii=False)) for b in bodies]
    upper = sum(estimate_usd(b) for b in bodies)
    expected = sum(c * PRICE_IN / 1e6 + EXPECTED_OUT_TOKENS * PRICE_OUT / 1e6 for c in chars)
    by_cat = {c: sum(1 for q in qs if q.cat == c) for c in CATS}
    return {"calls": len(qs), "by_cat": by_cat, "input_tokens_conservative": sum(chars), "expected_usd": round(expected, 5),
            "upper_bound_usd": round(upper, 5), "max_usd": max_usd, "within_cap": upper <= max_usd, "max_completion_tokens": CALL_OUT_CAP,
            "parallel_tool_calls": True, "reasoning_effort": "none", "calls_per_query": 1}


# --------------------------------------------------------------------------- 실행
def run(max_usd: float, ledger: CostLedger, *, http_client: Any = None, out_path: Path = OUT_PATH, queries: Sequence[Query] | None = None) -> dict[str, Any]:
    """질의마다 1회 호출한다. 상한을 넘길 호출은 하지 않고 skipped로 둔다."""
    qs = list(queries) if queries is not None else build_queries()
    sp = load_system_prompt(allow_draft=True)
    defs = _tool_defs()
    tools = build_tools(ToolContext(drug_dict=None))  # type: ignore[arg-type]
    cb = LedgerCallback(ledger, estimate_usd=CALL_OUT_CAP * PRICE_OUT / 1e6)
    model = bind_tools_model(make_chat_model(get_settings(), http_client=http_client, callbacks=[cb]), tools).bind(max_completion_tokens=CALL_OUT_CAP)
    rows: list[dict[str, Any]] = []
    spent, stopped = 0.0, ""
    for q in qs:
        est = estimate_usd(request_body(q, sp, defs))
        if stopped or spent + est > max_usd:
            stopped = stopped or f"--max-usd ${max_usd:.4f} 초과 예상. 호출 전에 중단"
            rows.append({"qid": q.qid, "status": "skipped", "reason": stopped})
            continue
        before = cb.cost_usd
        try:
            msg = model.invoke([("system", sp), ("user", q.text)])
        except BudgetExceeded as exc:
            stopped = str(exc)
            rows.append({"qid": q.qid, "status": "skipped", "reason": "원장 상한"})
            continue
        spent += cb.cost_usd - before
        calls = [{"name": c["name"], "args": c["args"]} for c in msg.tool_calls]
        rows.append({"status": "ok", "calls": calls, **judge(q, calls)})
    done = [r for r in rows if r.get("status") == "ok"]
    result = {"spent_usd": round(spent, 6), "n_ok": len(done), "n_skipped": len(rows) - len(done), "summary": summarize(done), "rows": rows,
              "note": "개발용 합성 질의, 소표본. 칸당 n≤8이면 유의성을 주장하지 않는다."}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--max-usd", type=float, default=HARD_CAP_USD)
    r = sub.add_parser("run")
    r.add_argument("--yes", action="store_true", help="실호출 확인(사용자 승인 뒤에만)")
    r.add_argument("--max-usd", type=float, default=HARD_CAP_USD)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        print(json.dumps(plan(a.max_usd), ensure_ascii=False, indent=2))
        return 0
    if not a.yes:
        print("실호출은 사용자 승인 뒤 `--yes`와 함께 실행한다. `plan`으로 호출 수·예상 비용을 먼저 본다.", file=sys.stderr)
        return 2
    if a.max_usd > HARD_CAP_USD:
        print(f"--max-usd는 {HARD_CAP_USD} 이하만 허용한다.", file=sys.stderr)
        return 2
    if not get_settings().openai_api_key:
        print("OPENAI_API_KEY를 찾지 못했다(환경변수 또는 작업 위치의 .env). 저장소 루트에서 실행한다.", file=sys.stderr)
        return 2
    res = run(a.max_usd, CostLedger())
    print(json.dumps({k: res[k] for k in ("spent_usd", "n_ok", "n_skipped", "summary")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
