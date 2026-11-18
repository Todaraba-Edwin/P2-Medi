"""BE-08 모델별 1회 호출 측정(RFP-24-03, PJ2-RFP.md 9.7절 평가 실행 예산표 입력): `gpt-6-luna`·Claude Haiku 4.5·Upstage `solar-pro4`·
Claude Sonnet 5.5에 **같은 합성 질문 하나**를 1회씩 보내 토큰·비용·지연·한도(응답 헤더의 rate limit 값)를 잰다.

- 기본은 dry-run(호출 0): 보낼 호출 4개와 최악 비용(입력 추정 + `max_tokens` 전부 출력)을 보여 준다.
- `--execute --yes --max-usd X`: 최악 비용 합이 X를 넘으면 **시작하지 않는다**. 호출 사이에도 실제 누적이 X를 넘으면 남은 호출을 건너뛴다.
- Upstage `temperature` 지원 확인: `temperature=0`을 붙여 1회 호출하고, 그 인자로 거절(4xx)되면 같은 호출을 인자 없이 1회 더 한다(기록에 남긴다).
- 키는 설정(`app.config.load_settings`, 저장소 `.env`)에서 읽어 SDK에 넘기고 어디에도 남기지 않는다. 결과에는 응답 본문 대신 글자 수만 남긴다.
- 단가(USD/100만 토큰)는 문서 조회 값이다(본 측정 전 계정 화면에서 재확인): luna 0.10/0.50(`app.agent.llm`), Sonnet 5.5 2/10, Haiku 4.5 1/5
  (9.7절·`mock_gen/_common.py`), Upstage `solar-pro4` 0.30/1.20(서드파티 가격 페이지, 2026-11-18 조회, **공식 미확인**).

사용(LLM 실호출 때는 cwd를 메인 저장소로, 지시서 절대 규칙):
    backend/.venv/bin/python evaluation/model_probe.py                                   # dry-run
    MEDIAGENT_EVAL=1 backend/.venv/bin/python evaluation/model_probe.py --execute --yes --max-usd 0.10 --out logs/eval/model-probe.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

VERSION = "model-probe@v1"
# 합성 질문(공공 데이터 기반 일반 질문, 개인 정보·평가 문항 아님). 모든 모델에 같은 입력을 준다
PROMPT_SYSTEM = "너는 의약품 안전 정보를 쉽게 설명하는 도우미다. 복용 여부와 용량은 정하지 않고, 근처 약국·약사에게 확인하도록 안내한다."
PROMPT_USER = "감기약과 해열진통제를 같이 먹어도 되는지 확인하려면 어떤 정보를 봐야 하나요? 세 문장으로 답해 주세요."
MAX_TOKENS = 800  # solar-pro4는 추론이 기본으로 켜져 있다는 보고가 있어 출력 여유를 둔다
EST_INPUT_TOKENS = 200  # 최악 비용 계산용 입력 추정(시스템 + 질문, 한글)
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"

# (이름, 공급자, 모델 ID, 입력 단가, 출력 단가, 단가 출처)
MODELS: tuple[tuple[str, str, str, float, float, str], ...] = (
    ("gpt-6-luna", "openai", "gpt-6-luna", 0.10, 0.50, "app.agent.llm PRICE_IN/OUT(BE-15, 2026-11-10)"),
    ("haiku-4.5", "anthropic", "claude-haiku-4-5-20251001", 1.0, 5.0, "evaluation/mock_gen/_common.py PRICES(2026-11-04)"),
    ("solar-pro4", "upstage", "solar-pro4", 0.30, 1.20, "서드파티 가격 페이지 2026-11-18 조회(공식 미확인)"),
    ("sonnet-5.5", "anthropic", "claude-sonnet-5-5", 2.0, 10.0, "PJ2-RFP.md 9.7절·sonnet_judge.py(2026-11-04)"),
)
RATE_HEADER_PREFIXES = ("x-ratelimit-", "anthropic-ratelimit-", "ratelimit-")  # 한도 헤더만(그 밖 헤더는 남기지 않는다)


def cost(in_tok: int, out_tok: int, p_in: float, p_out: float) -> float:
    return in_tok * p_in / 1e6 + out_tok * p_out / 1e6


def worst_case_usd() -> float:
    """모든 호출이 `max_tokens`를 다 쓰고 Upstage가 temperature 거절로 한 번 더 부르는 최악 비용."""
    per = {name: cost(EST_INPUT_TOKENS, MAX_TOKENS, pi, po) for name, _, _, pi, po, _ in MODELS}
    return round(sum(per.values()) + per["solar-pro4"], 6)


def rate_headers(headers: Any) -> dict[str, str]:
    try:
        items = dict(headers).items()
    except Exception:  # noqa: BLE001 - 헤더가 없으면 빈 칸
        return {}
    return {k.lower(): str(v) for k, v in items if k.lower().startswith(RATE_HEADER_PREFIXES)}


def call_openai_compatible(client: Any, model: str, *, extra: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    raw = client.chat.completions.with_raw_response.create(
        model=model, messages=[{"role": "system", "content": PROMPT_SYSTEM}, {"role": "user", "content": PROMPT_USER}], **extra)
    lat = time.perf_counter() - t0
    r = raw.parse()
    u = r.usage
    details = getattr(u, "completion_tokens_details", None)
    return {"latency_s": round(lat, 3), "input_tokens": int(u.prompt_tokens), "output_tokens": int(u.completion_tokens),
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details else None,
            "finish_reason": r.choices[0].finish_reason, "answer_chars": len(r.choices[0].message.content or ""), "rate_limits": rate_headers(raw.headers)}


def call_anthropic(client: Any, model: str, *, thinking: dict[str, Any] | None) -> dict[str, Any]:
    kw: dict[str, Any] = {"thinking": thinking} if thinking else {}
    t0 = time.perf_counter()
    raw = client.messages.with_raw_response.create(model=model, max_tokens=MAX_TOKENS, system=PROMPT_SYSTEM,
                                                   messages=[{"role": "user", "content": PROMPT_USER}], **kw)
    lat = time.perf_counter() - t0
    r = raw.parse()
    text = "".join(getattr(b, "text", "") for b in r.content)
    return {"latency_s": round(lat, 3), "input_tokens": int(r.usage.input_tokens), "output_tokens": int(r.usage.output_tokens),
            "finish_reason": r.stop_reason, "answer_chars": len(text), "rate_limits": rate_headers(raw.headers)}


def is_param_rejection(exc: Exception) -> bool:
    """`temperature` 인자 거절로 보이는 4xx인가(상태 코드 400·422). 인증·한도 오류는 아니다."""
    status = getattr(exc, "status_code", None)
    return status in (400, 422)


def run_probe(clients: dict[str, Any], *, max_usd: float, ledger_add: Callable[[float], None] | None = None) -> dict[str, Any]:
    """`clients`: {"openai": OpenAI, "anthropic": Anthropic, "upstage": OpenAI(base_url=Upstage)}. 시험에서는 가짜를 넣는다."""
    rows: list[dict[str, Any]] = []
    spent = 0.0
    for name, provider, model, p_in, p_out, src in MODELS:
        row: dict[str, Any] = {"name": name, "provider": provider, "model": model, "price_usd_per_m": [p_in, p_out], "price_source": src}
        if spent + cost(EST_INPUT_TOKENS, MAX_TOKENS, p_in, p_out) > max_usd:
            rows.append({**row, "status": "skipped_budget"})
            continue
        attempts: list[dict[str, Any]] = []
        try:
            if provider == "openai":
                res = call_openai_compatible(clients["openai"], model, extra={"reasoning_effort": "none", "max_completion_tokens": MAX_TOKENS})
            elif provider == "upstage":
                try:
                    res = call_openai_compatible(clients["upstage"], model, extra={"max_tokens": MAX_TOKENS, "temperature": 0})
                    row["temperature_supported"] = True
                except Exception as e:  # noqa: BLE001 - 인자 거절이면 인자 없이 한 번 더
                    if not is_param_rejection(e):
                        raise
                    attempts.append({"temperature": 0, "error_type": type(e).__name__, "status_code": getattr(e, "status_code", None)})
                    row["temperature_supported"] = False
                    res = call_openai_compatible(clients["upstage"], model, extra={"max_tokens": MAX_TOKENS})
            else:
                thinking = {"type": "between_tools"} if "sonnet" in model else None  # Sonnet 5.5 사고 끄기(RFP-28 §7), Haiku는 인자 없음
                res = call_anthropic(clients["anthropic"], model, thinking=thinking)
                row["thinking"] = thinking
        except Exception as e:  # noqa: BLE001 - 호출 실패는 종류·상태 코드만 남긴다(메시지에 키가 섞일 수 있다)
            rows.append({**row, "status": "error", "error_type": type(e).__name__, "status_code": getattr(e, "status_code", None), "attempts": attempts})
            continue
        c = round(cost(res["input_tokens"], res["output_tokens"], p_in, p_out), 7)
        spent += c
        if provider == "openai" and ledger_add is not None:
            ledger_add(c)  # OpenAI 원장(평가 몫)에 더한다
        rows.append({**row, "status": "ok", **res, "cost_usd": c, "attempts": attempts})
    return {"version": VERSION, "max_usd": max_usd, "worst_case_usd": worst_case_usd(), "total_cost_usd": round(spent, 7),
            "prompt": {"system_chars": len(PROMPT_SYSTEM), "user_chars": len(PROMPT_USER), "max_tokens": MAX_TOKENS}, "rows": rows,
            "note": "1회 호출 측정(RFP-24-03). 짧은 합성 질문이라 에이전트·judge 실제 호출(입력 수천 토큰)보다 작다. 9.7절 값은 보고에만 적는다"}


def _live_clients() -> tuple[dict[str, Any], Callable[[float], None]]:  # pragma: no cover - 실호출 경로
    from anthropic import Anthropic
    from openai import OpenAI

    from app.config import reveal
    from app.llm.ledger import CostLedger
    from app.main import load_settings

    s = load_settings()
    missing = [n for n, v in (("OPENAI_API_KEY", s.openai_api_key), ("ANTHROPIC_API_KEY", s.anthropic_api_key), ("UPSTAGE_API_KEY", s.upstage_api_key)) if not v]
    if missing:
        raise SystemExit(f"필수 환경변수가 없어 실행하지 않았다: {', '.join(missing)}")
    ledger = CostLedger()
    clients = {"openai": OpenAI(api_key=reveal(s.openai_api_key), max_retries=0),
               "anthropic": Anthropic(api_key=reveal(s.anthropic_api_key), max_retries=0),
               "upstage": OpenAI(api_key=reveal(s.upstage_api_key), base_url=UPSTAGE_BASE_URL, max_retries=0)}
    return clients, lambda usd: ledger.add(usd, "eval")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--execute", action="store_true", help="실제 호출(사용자 승인 뒤에만)")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0, help="이번 측정 비용 상한(최악 비용이 넘으면 시작하지 않는다)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    worst = worst_case_usd()
    if not a.execute:
        print(f"[dry-run] 호출 {len(MODELS)}개(+ Upstage temperature 거절 시 1개), 최악 비용 ${worst:.4f}, 입력 추정 {EST_INPUT_TOKENS}·max_tokens {MAX_TOKENS}")
        for name, _, model, p_in, p_out, src in MODELS:
            print(f"  {name}: {model} · ${p_in}/${p_out} per 1M · {src}")
        return 0
    if not a.yes or a.max_usd <= 0 or worst > a.max_usd:
        print(f"--execute는 --yes와 --max-usd(> 최악 비용 ${worst:.4f})가 있어야 한다. 실행하지 않았다")
        return 2
    clients, ledger_add = _live_clients()
    res = run_probe(clients, max_usd=a.max_usd, ledger_add=ledger_add)
    res["created_utc"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = a.out or ROOT / "logs" / "eval" / f"model-probe-{res['created_utc'].replace(':', '').replace('-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in res["rows"]:
        print(f"  {r['name']}: {r['status']} " + (f"in {r['input_tokens']} out {r['output_tokens']} ${r['cost_usd']:.6f} {r['latency_s']}s" if r["status"] == "ok"
                                                   else str(r.get("error_type") or "")))
    print(f"합계 ${res['total_cost_usd']:.6f} / 상한 ${a.max_usd} → {out}")
    return 0


if __name__ == "__main__":
    from app.security.redact import install_excepthook  # noqa: E402

    install_excepthook()
    raise SystemExit(main())
