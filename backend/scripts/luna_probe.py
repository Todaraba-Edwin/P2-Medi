"""gpt-6-luna 호출 확인 스크립트(BE-15). **사용자가 승인한 뒤에만 `--yes`로 실행한다. 자동·시험에서는 실행하지 않는다.**

한 번의 호출로 지연·토큰·(단가를 주면) 비용을 잰다. 키는 OPENAI_API_KEY(환경변수, 없으면 app.config Settings의 .env)로만 읽고 출력하지 않는다.
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
from pydantic_settings import SettingsConfigDict  # noqa: E402

from app.config import Settings  # noqa: E402
from app.llm.ledger import CostLedger  # noqa: E402
from app.security.redact import install_excepthook, safe_exc  # noqa: E402

install_excepthook()  # 처리되지 않은 예외의 메시지·트레이스백에서 비밀 값을 가린다

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"


class _ProbeSettings(Settings):
    """프로브는 OPENAI_API_KEY만 필요하다. 다른 .env 변수(이름이 Settings와 다른 것 포함)는 무시한다."""

    model_config = SettingsConfigDict(extra="ignore")


def resolve_openai_key(env_files=None) -> str | None:
    """환경변수 우선, 없으면 Settings(pydantic-settings env_file)로 읽는다. 값은 호출자만 쓰고 출력하지 않는다."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    files = env_files if env_files is not None else (".env", os.path.join(root, ".env"))
    try:
        return _ProbeSettings(_env_file=files).openai_api_key or None
    except Exception as exc:  # noqa: BLE001 - 검증 오류 메시지에 .env 값이 섞일 수 있어 종류만 알린다
        print(f"설정(.env)을 읽지 못했다: {safe_exc(exc)}")
        return None


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
    key = resolve_openai_key()
    if not key:
        print("OPENAI_API_KEY를 환경변수나 .env 설정에서 찾지 못했다.")
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
