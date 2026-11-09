"""mock 데이터 사전 생성(RFP-31) 공용 모듈. 상한 20 USD(사용자 지정 2026-11-04).
RFP-28의 evaluation/credit_use/_common.py를 바탕으로 원장·출력 위치와 상한만 바꿨다.

원래 설명:

- 키는 환경변수 ANTHROPIC_API_KEY로만 읽는다(.env를 dotenv로 로드, 값은 출력·기록하지 않는다).
- 누적 비용이 CAP_USD(20)를 넘기려 하면 호출 전에 중단한다(원장: data/mock/ledger.json).
- 호출 기록(모델·토큰·비용·프롬프트 해시)은 data/mock/calls.jsonl에 남긴다(프롬프트 원문은 각 출력 파일에).
"""
import hashlib, json, os, time
from pathlib import Path
from dotenv import load_dotenv
import anthropic

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "mock"
OUT.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")

CAP_USD = 20.0
PRICES = {  # USD / 100만 토큰 (platform.claude.com 가격표, 2026-11-04 확인)
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
}
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"
LEDGER = OUT / "ledger.json"
CALLS = OUT / "calls.jsonl"
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수
    return _client


def spent():
    return json.loads(LEDGER.read_text())["usd"] if LEDGER.exists() else 0.0


def call(model, system, user, max_tokens=1500, tag=""):  # temperature는 Haiku 4.5·Sonnet 5.5가 거부한다(2026-11-04 확인)
    in_p, out_p = PRICES[model]
    worst = (len(system) + len(user)) / 2 * in_p / 1e6 + max_tokens * out_p / 1e6  # 보수적 상한
    if spent() + worst > CAP_USD:
        raise SystemExit(f"중단: 누적 ${spent():.2f} + 예상 최대 ${worst:.3f} > 상한 ${CAP_USD}")
    for attempt in range(4):
        try:
            kw = {"thinking": {"type": "between_tools"}} if model == SONNET else {}  # Sonnet 5.5는 기본이 사고 켬(비용·변동). 끄려면 between_tools(2026-11-04 확인)
            r = client().messages.create(model=model, max_tokens=max_tokens,
                                         system=system, messages=[{"role": "user", "content": user}], **kw)
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(2 ** attempt * 2)
    else:
        raise SystemExit("API 재시도 실패")
    cost = r.usage.input_tokens * in_p / 1e6 + r.usage.output_tokens * out_p / 1e6
    total = spent() + cost
    LEDGER.write_text(json.dumps({"usd": round(total, 6)}))
    with CALLS.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "tag": tag, "model": model,
                            "in": r.usage.input_tokens, "out": r.usage.output_tokens,
                            "usd": round(cost, 6), "prompt_sha": hashlib.sha1((system + user).encode()).hexdigest()[:10]}) + "\n")
    return "".join(b.text for b in r.content if b.type == "text")


def parse_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    i, j = t.find("["), t.find("{")
    start = min(x for x in (i, j) if x >= 0)
    end = max(t.rfind("]"), t.rfind("}")) + 1
    return json.loads(t[start:end])


def call_json(model, system, user, max_tokens=1500, tag="", tries=3):
    """JSON 파싱에 실패하면 따옴표 이스케이프를 요구해 다시 부른다(실패한 호출도 비용에 포함)."""
    last = None
    for k in range(tries):
        text = call(model, system, user + ("" if k == 0 else "\n\n주의: 문자열 안의 큰따옴표는 \\\"로 이스케이프하고 JSON 배열만 출력한다."),
                    max_tokens=max_tokens, tag=f"{tag}-retry{k}" if k else tag)
        try:
            return parse_json(text)
        except Exception as e:  # noqa: BLE001
            last = e
    raise SystemExit(f"JSON 파싱 반복 실패: {last}")
