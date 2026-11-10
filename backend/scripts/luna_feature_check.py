"""gpt-6-luna 구조화 출력·병렬 도구 호출 확인(BE-15, AG-01·AG-06-02의 전제). **실호출은 사용자가 `--yes`로 직접 실행한다.**

하위 명령(작업 위치 `backend/`):
  plan                          호출 수·예상 비용만 출력(호출 0, 네트워크·키 사용 없음)
  run --yes --max-usd 0.05      실호출 최대 4회(structured, parallel_true, parallel_false, parallel_default)

규칙:
- 키는 OPENAI_API_KEY(환경변수, 없으면 `app.config` 설정)로만 읽고 출력하지 않는다. 헤더·요청 본문은 화면에 찍지 않는다.
- 호출 전: `--max-usd` 하드 상한(호출 전 추정 + 실제 누적)과 개발 원장 guard(`app.llm.cache`)를 모두 지킨다. 호출 뒤 비용을 원장에 기록한다.
- 입력은 합성 고정 근거 3개와 도구 스키마뿐이다(평가 세트·페르소나 질문·허구 약 이름 없음). 실제 함수는 실행하지 않는다.
- 판정은 코드가 한다: 구조화=JSON 파싱+Pydantic(`AnswerDraft`) 검증, 병렬=`len(tool_calls) >= 2`. 응답 형식이 예상과 다르면 `format_mismatch`로 두고 원문을 저장한다.
- 응답 원문은 `data/mock/dict/luna_feature_check.json`(로컬 전용, 키 없음)에 저장한다.
- 단가(USD/100만 토큰): 입력 0.10, 캐시 입력 0.01, 출력 0.50(`gpt-6-luna`, 2026-11-10 웹확인, BE-15 참조).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import ValidationError  # noqa: E402

from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.llm.cache import cache_mode, cached_openai_call  # noqa: E402
from app.llm.ledger import BudgetExceeded, CostLedger  # noqa: E402
from app.security.redact import install_excepthook, redact  # noqa: E402

install_excepthook()

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.10, 0.01, 0.50  # USD / 100만 토큰
HARD_CAP_USD = 0.05
MAX_COMPLETION_TOKENS = 1500  # 추론 토큰을 포함한 출력 상한. 비용 상한 추정에도 쓴다
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "mock" / "dict" / "luna_feature_check.json"

# 합성 고정 근거(공공 데이터에서 알려진 일반 사실의 짧은 요약. 시험용 문구이며 서비스 문구가 아니다).
EVIDENCE = [
    {"evidence_id": "E1", "text": "와파린과 아스피린을 함께 복용하면 출혈 위험이 커질 수 있어 병용 시 주의가 필요하다. (식약처 DUR 병용주의 요약, 시험용 문구)"},
    {"evidence_id": "E2", "text": "이부프로펜 같은 비스테로이드 소염진통제는 임신 후기에 사용을 피하도록 안내된다. (식약처 허가사항 요약, 시험용 문구)"},
    {"evidence_id": "E3", "text": "아세트아미노펜은 허가사항에 정해진 1일 최대 용량을 넘지 않도록 안내된다. (식약처 허가사항 요약, 시험용 문구)"},
]
EVIDENCE_IDS = {e["evidence_id"] for e in EVIDENCE}

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "identify_drug", "description": "약 이름으로 제품·성분을 식별한다.", "parameters": {
        "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "check_contraindications", "description": "약 한 가지의 병용·연령·임부 금기를 조회한다.", "parameters": {
        "type": "object", "properties": {"drug_name": {"type": "string"}, "check": {"type": "string", "enum": ["combination", "age", "pregnancy"]}},
        "required": ["drug_name", "check"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "search_docs", "description": "허가사항·e약은요 문서에서 근거 문장을 검색한다.", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}}},
]


# --------------------------------------------------------------------------- 엄격 스키마

_STRIP = {"title", "default", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems"}


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic `model_json_schema()`를 Structured Outputs strict 규칙에 맞춘다.

    `$ref` 인라인, 모든 속성을 required, additionalProperties=false, 기본값·길이·범위 키워드 제거.
    (원본 Pydantic 모델의 검증 규칙은 그대로 두고, 응답을 받은 뒤 `AnswerDraft`로 다시 검증한다.)
    """
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
        out = {k: walk(v) for k, v in node.items() if k not in _STRIP and k != "$defs"}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    return walk(schema)  # type: ignore[no-any-return]


def structured_format() -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "answer_draft", "strict": True, "schema": to_strict_schema(AnswerDraft.model_json_schema())}}


# --------------------------------------------------------------------------- 요청

def build_requests() -> list[dict[str, Any]]:
    ev = "\n".join(f"[{e['evidence_id']}] {e['text']}" for e in EVIDENCE)
    structured = {
        "model": MODEL, "max_completion_tokens": MAX_COMPLETION_TOKENS, "response_format": structured_format(),
        "messages": [
            {"role": "system", "content": "주어진 근거만 사용해 쉬운 한국어 문장 2~3개로 답한다. fact 문장은 evidence_ids에 근거 ID를 넣고, 확인 안내(guidance) 문장은 약사 확인을 권한다. citations는 빈 배열로 둔다."},
            {"role": "user", "content": f"근거:\n{ev}\n\n질문: 이 근거로 알 수 있는 주의점을 요약해 주세요."},
        ],
    }
    par_messages = [
        {"role": "system", "content": "도구로 사실을 확인한다. 서로 독립인 조회는 한 번에 함께 요청한다."},
        {"role": "user", "content": "아세트아미노펜과 이부프로펜의 병용금기를 각각 확인해 주세요."},
    ]
    base = {"model": MODEL, "max_completion_tokens": MAX_COMPLETION_TOKENS, "messages": par_messages, "tools": TOOLS}
    return [
        {"label": "structured", "body": structured},
        {"label": "parallel_true", "body": {**base, "parallel_tool_calls": True}},
        {"label": "parallel_false", "body": {**base, "parallel_tool_calls": False}},
        {"label": "parallel_default", "body": dict(base)},
        # 2026-11-10 1차 실행에서 400: gpt-6-luna는 Chat Completions에서 reasoning_effort가 켜져 있으면 함수 도구를 거절한다
        # ("set reasoning_effort to 'none'"). 아래 3종은 reasoning_effort='none'으로 다시 확인한다.
        {"label": "parallel_true_noreason", "body": {**base, "reasoning_effort": "none", "parallel_tool_calls": True}},
        {"label": "parallel_false_noreason", "body": {**base, "reasoning_effort": "none", "parallel_tool_calls": False}},
        {"label": "parallel_default_noreason", "body": {**base, "reasoning_effort": "none"}},
    ]


def estimate_usd(body: dict[str, Any]) -> float:
    """호출 전 상한 추정. 입력은 직렬화 문자 수를 토큰 수로 보수적으로 어림하고, 출력은 상한 전체로 잡는다."""
    tokens_in = len(json.dumps(body, ensure_ascii=False))
    return tokens_in * PRICE_IN / 1e6 + MAX_COMPLETION_TOKENS * PRICE_OUT / 1e6


def real_cost(resp: dict[str, Any]) -> float:
    u = (resp.get("body") or {}).get("usage") or {}
    p, c = int(u.get("prompt_tokens", 0)), int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
    return (p - c) * PRICE_IN / 1e6 + c * PRICE_CACHED / 1e6 + int(u.get("completion_tokens", 0)) * PRICE_OUT / 1e6


# --------------------------------------------------------------------------- 판정(코드)

def _message(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        ch = body["choices"][0]
        return ch["message"], ch.get("finish_reason")
    except (KeyError, IndexError, TypeError):
        return None, None


def judge_structured(body: Any, allowed_ids: set[str] = EVIDENCE_IDS) -> dict[str, Any]:
    """verdict: ok | refusal | parse_fail | schema_invalid | format_mismatch."""
    msg, finish = _message(body)
    if msg is None:
        return {"verdict": "format_mismatch", "finish_reason": None}
    if msg.get("refusal"):
        return {"verdict": "refusal", "finish_reason": finish}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        return {"verdict": "format_mismatch", "finish_reason": finish, "note": "content 없음"}
    try:
        json.loads(content)
    except json.JSONDecodeError:
        return {"verdict": "parse_fail", "finish_reason": finish}
    try:
        draft = AnswerDraft.model_validate_json(content)
    except ValidationError as e:
        return {"verdict": "schema_invalid", "finish_reason": finish, "errors": e.error_count()}
    cited = {i for s in draft.sentences for i in s.evidence_ids}
    return {
        "verdict": "ok", "finish_reason": finish, "sentences": len(draft.sentences),
        "claim_types": sorted({s.claim_type for s in draft.sentences}), "unknown_evidence_ids": sorted(cited - allowed_ids),
        "fact_without_evidence": sum(1 for s in draft.sentences if s.claim_type == "fact" and not s.evidence_ids),
    }


def judge_parallel(body: Any, parallel_option: bool | None) -> dict[str, Any]:
    """tool_calls 개수로 판정한다. parallel_option이 False면 기대는 `<=1`, 그 밖에는 `>=2`가 병렬 성공."""
    msg, finish = _message(body)
    if msg is None:
        return {"verdict": "format_mismatch", "finish_reason": None}
    calls = msg.get("tool_calls") or []
    if not isinstance(calls, list):
        return {"verdict": "format_mismatch", "finish_reason": finish, "note": "tool_calls가 목록이 아님"}
    names, args_ok = [], True
    for c in calls:
        try:
            names.append(c["function"]["name"])
            json.loads(c["function"]["arguments"])
        except (KeyError, TypeError, json.JSONDecodeError):
            args_ok = False
    n = len(calls)
    out: dict[str, Any] = {"finish_reason": finish, "tool_calls": n, "names": names, "arguments_valid_json": args_ok, "parallel": n >= 2}
    if parallel_option is False:
        out["verdict"] = "off_honored" if n <= 1 else "off_ignored"
    else:
        out["verdict"] = "parallel" if n >= 2 else ("single" if n == 1 else "no_tool_call")
    return out


def judge(label: str, body: Any) -> dict[str, Any]:
    if label == "structured":
        return judge_structured(body)
    option = {"parallel_true": True, "parallel_false": False, "parallel_true_noreason": True, "parallel_false_noreason": False}.get(label)
    return judge_parallel(body, option)


# --------------------------------------------------------------------------- 실행

class CallFailed(RuntimeError):
    """HTTP 비 200. 메시지는 비밀 값을 가린 응답 앞부분이다."""

    def __init__(self, status: int, text: str) -> None:
        super().__init__(f"status={status} {text}")
        self.status, self.text = status, text


PostFn = Callable[[dict[str, Any]], tuple[int, Any]]


def http_post_factory(key: str) -> PostFn:
    import httpx

    def post(body: dict[str, Any]) -> tuple[int, Any]:
        r = httpx.post(ENDPOINT, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    return post


def _ensure_cache_importable() -> None:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        sys.modules["anthropic"] = types.ModuleType("anthropic")


def execute(post: PostFn, labels: Sequence[str], max_usd: float, ledger: CostLedger, out_path: Path = OUT_PATH) -> tuple[dict[str, Any], int]:
    """호출을 순서대로 실행한다. 상한을 넘길 호출은 하지 않고 skipped로 둔다. 결과 파일에는 키가 없다."""
    reqs = {r["label"]: r["body"] for r in build_requests()}
    spent = 0.0
    results: list[dict[str, Any]] = []
    stopped = ""
    for label in labels:
        body = reqs[label]
        est = estimate_usd(body)
        entry: dict[str, Any] = {"label": label, "request": body}
        if stopped or spent + est > max_usd:
            entry["status"] = "skipped"
            entry["reason"] = stopped or f"--max-usd ${max_usd:.4f} 초과 예상(누적 ${spent:.6f} + 추정 ${est:.6f}). 호출 전에 중단"
            stopped = entry["reason"]
            results.append(entry)
            continue
        t0 = time.perf_counter()

        def fetch(body: dict[str, Any] = body) -> dict[str, Any]:
            status, data = post(body)
            if status != 200:
                text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                raise CallFailed(status, redact(text)[:600])
            return {"status": status, "body": data}

        try:
            resp = cached_openai_call(MODEL, body["messages"], {k: v for k, v in body.items() if k != "messages"}, fetch,
                                      cost_fn=real_cost, estimate_usd=est, ledger=ledger, tag=f"luna-check:{label}")
        except CallFailed as exc:
            entry.update(status="http_error", http_status=exc.status, error_body=exc.text, verdict="unsupported_or_rejected")
            results.append(entry)
            continue
        except BudgetExceeded as exc:
            entry.update(status="skipped", reason=redact(str(exc)))
            stopped = entry["reason"]
            results.append(entry)
            continue
        cost = real_cost(resp)
        spent += cost
        entry.update(status="ok", latency_ms=int((time.perf_counter() - t0) * 1000), usage=resp["body"].get("usage") if isinstance(resp["body"], dict) else None,
                     cost_usd=round(cost, 6), response=resp["body"], judgement=judge(label, resp["body"]))
        results.append(entry)
        if spent > max_usd:
            stopped = f"--max-usd ${max_usd:.4f} 도달(실제 ${spent:.6f})"
    report = {"model": MODEL, "max_usd": max_usd, "spent_usd": round(spent, 6), "price_per_1M": {"in": PRICE_IN, "cached_in": PRICE_CACHED, "out": PRICE_OUT},
              "results": results}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(redact(json.dumps(report, ensure_ascii=False, indent=1)), encoding="utf-8")
    return report, 0


def summarize(report: dict[str, Any]) -> list[str]:
    lines = [f"누적 비용 ${report['spent_usd']:.6f} (상한 ${report['max_usd']})"]
    for r in report["results"]:
        if r["status"] == "ok":
            j = r["judgement"]
            lines.append(f"- {r['label']}: {j['verdict']} (tool_calls={j.get('tool_calls', '-')}, {r['latency_ms']}ms, ${r['cost_usd']:.6f})")
        elif r["status"] == "http_error":
            lines.append(f"- {r['label']}: HTTP {r['http_status']} 거절 — 원문은 저장 파일 참조")
        else:
            lines.append(f"- {r['label']}: 건너뜀 — {r['reason']}")
    return lines


# --------------------------------------------------------------------------- 명령

def cmd_plan(_: argparse.Namespace) -> int:
    reqs = build_requests()
    print(f"모델 {MODEL}, 실호출 최대 {len(reqs)}회, 하드 상한 ${HARD_CAP_USD} (plan은 호출 0)")
    total_est = 0.0
    for r in reqs:
        est = estimate_usd(r["body"])
        total_est += est
        print(f"- {r['label']}: 입력 ≲{len(json.dumps(r['body'], ensure_ascii=False))}토큰(보수), 출력 상한 {MAX_COMPLETION_TOKENS}, 상한 기준 추정 ${est:.5f}")
    realistic = sum(len(json.dumps(r["body"], ensure_ascii=False)) for r in reqs) * PRICE_IN / 1e6 + len(reqs) * 600 * PRICE_OUT / 1e6
    print(f"합계: 출력을 모두 상한까지 쓴 최악 ${total_est:.5f}, 출력 호출당 600토큰 가정 ${realistic:.5f}")
    print(f"단가 USD/100만: 입력 {PRICE_IN}, 캐시 입력 {PRICE_CACHED}, 출력 {PRICE_OUT}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.yes:
        print("실호출이 필요하다. 승인 뒤 --yes로 다시 실행한다.")
        return 2
    if not 0 < args.max_usd <= HARD_CAP_USD:
        print(f"--max-usd는 0 초과 {HARD_CAP_USD} 이하여야 한다")
        return 2
    from luna_probe import resolve_openai_key  # 지연 import: plan·시험에서는 쓰지 않는다

    key = resolve_openai_key()
    if not key:
        print("OPENAI_API_KEY를 환경변수나 .env 설정에서 찾지 못했다.")
        return 2
    if os.environ.get("MEDIAGENT_EVAL", "").strip() in ("", "0", "false", "False"):
        os.environ.setdefault("LLM_CACHE", "record")  # 재실행 시 비용 중복 방지
    if cache_mode() == "off":
        print("LLM_CACHE=off에서는 실행하지 않는다(재실행 시 중복 비용). LLM_CACHE=record로 실행한다.")
        return 2
    _ensure_cache_importable()
    labels = args.only or [r["label"] for r in build_requests()]
    report, _ = execute(http_post_factory(key), labels, args.max_usd, CostLedger())
    print("\n".join(summarize(report)))
    print(f"원문 저장: {OUT_PATH.name} (data/mock/dict, 로컬 전용)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("--yes", action="store_true", help="실호출 승인")
    r.add_argument("--max-usd", type=float, default=HARD_CAP_USD)
    r.add_argument("--only", nargs="+", choices=[x["label"] for x in build_requests()], help="일부 호출만 실행")
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
