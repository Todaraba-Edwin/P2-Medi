"""gpt-6-luna 호출 확인 스크립트(BE-15). **사용자가 승인한 뒤에만 `--yes`로 실행한다. 자동·시험에서는 실행하지 않는다.**

한 번의 호출로 지연·토큰·(단가를 주면) 비용을 잰다. 키는 환경변수 OPENAI_API_KEY로만 읽고 출력하지 않는다.
호출 전 개발 원장 guard를 거치고, 호출 뒤 비용을 원장(dev 몫)에 더한다.

실행(1회): cd backend && .venv/bin/python scripts/luna_probe.py --yes --price-in <USD/1M입력> --price-out <USD/1M출력>
구조화 출력·병렬 도구 호출·임베딩 지원 여부는 이 한 번으로 알 수 없다. 결과를 보고 필요한 항목만 사용자가 추가 승인한다.
OpenAI 호환 chat completions 엔드포인트 형식을 가정했으며 응답 형식이 다르면 사용자 확인 뒤 고친다(확인하지 못함).
"""

import argparse
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.llm.ledger import CostLedger  # noqa: E402

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="실호출 승인")
    ap.add_argument("--price-in", type=float, required=True)
    ap.add_argument("--price-out", type=float, required=True)
    ap.add_argument("--max-tokens", type=int, default=30)
    args = ap.parse_args()
    if not args.yes:
        print("실호출 1회가 필요하다. 승인 뒤 --yes로 다시 실행한다.")
        return 2
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY 환경변수가 없다.")
        return 2
    ledger = CostLedger()
    ledger.guard(args.max_tokens * args.price_out / 1e6 + 0.001)
    body = {"model": MODEL, "max_completion_tokens": args.max_tokens, "messages": [{"role": "user", "content": "'삐약'이라고만 답하세요."}]}
    t0 = time.perf_counter()
    r = httpx.post(ENDPOINT, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    print(f"status={r.status_code} latency_ms={latency_ms}")
    if r.status_code != 200:
        print(r.text[:300].replace(key, "***"))
        return 1
    usage = r.json().get("usage", {})
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    cost = tin * args.price_in / 1e6 + tout * args.price_out / 1e6
    total = ledger.add(cost)
    print(f"tokens_in={tin} tokens_out={tout} cost_usd={cost:.6f} dev_ledger_usd={total:.6f}")
    print("rate-limit headers:", {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
