"""개발 중 LLM 호출 record/replay 캐시(RFP-32-02 A). 같은 입력의 반복 호출을 막아 크레딧을 아낀다.

- 환경변수 LLM_CACHE = off(기본) | record | replay.
    off    : 캐시를 쓰지 않고 그대로 호출한다.
    record : 적중하면 저장본을 돌려주고(호출·비용 없음), 없으면 호출한 뒤 저장한다.
    replay : 적중하면 저장본, 없으면 CacheMiss 예외(절대 호출하지 않는다).
- **평가 측정에서는 항상 off.** 환경변수 MEDIAGENT_EVAL=1(평가 실행 표시)이면 LLM_CACHE 값과 상관없이 off로 강제한다.
- 키 = sha256(제공자, 모델, messages, 호출 인자, 프롬프트 파일 내용 해시). 프롬프트를 고치면 키가 달라져 캐시가 무효가 된다.
- 저장 위치: mock/llm_cache/<키>.json (로컬 전용, .gitignore의 mock/). 환경변수 LLM_CACHE_DIR로 바꿀 수 있다(시험용).
- 비용: 캐시 적중은 비용 0이라 원장(mock/ledger.json)·호출 기록(mock/calls.jsonl)에 쓰지 않는다.
  실제 호출은 반드시 evaluation/mock_gen/_common.py의 call()을 거치므로 누적 20 USD 상한은 그대로 지켜진다(캐시를 끼워도 우회 불가).
- 실패한 호출은 저장하지 않는다. 키·연결 문자열은 저장하지 않는다(messages와 응답 텍스트만).

사용 예:
    from scripts.mock import llm_cache
    text = llm_cache.claude_call(llm_cache.HAIKU, system, user, max_tokens=300, tag="dev", prompt_files=["prompts/x.md"])
    # OpenAI 등 다른 제공자: llm_cache.cached_call("openai", "gpt-6-luna", messages, {"temperature": 0}, fetch=lambda: ..., prompt_files=[...])
시험: .venv/bin/python evaluation/mock_gen/llm_cache.py selftest      (Haiku 2건: 첫 호출은 기록, 둘째는 적중해야 한다)
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    from . import _common as C
except ImportError:  # 스크립트로 직접 실행
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common as C

assert C.CAP_USD == 20.0 and C.OUT.name == "mock", "evaluation/mock_gen/_common의 상한 20 USD 규칙이 바뀌었다"

HAIKU, SONNET = C.HAIKU, C.SONNET
MODES = ("off", "record", "replay")
stats = {"hit": 0, "miss": 0, "stored": 0}


class CacheMiss(RuntimeError):
    """replay 모드에서 저장본이 없을 때."""


def mode() -> str:
    if os.environ.get("MEDIAGENT_EVAL", "").strip() not in ("", "0", "false", "False"):
        return "off"                      # 평가 측정은 항상 캐시 없이
    m = os.environ.get("LLM_CACHE", "off").strip().lower() or "off"
    if m not in MODES:
        raise ValueError(f"LLM_CACHE는 {MODES} 중 하나여야 한다: {m!r}")
    return m


def cache_dir() -> Path:
    d = Path(os.environ.get("LLM_CACHE_DIR") or (C.OUT / "llm_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_hashes(prompt_files) -> dict:
    out = {}
    for p in prompt_files or ():
        path = Path(p)
        if not path.is_absolute():
            path = C.ROOT / path
        out[str(Path(p))] = hashlib.sha256(path.read_bytes()).hexdigest()    # 파일이 없으면 FileNotFoundError(조용히 넘기지 않는다)
    return out


def cache_key(provider: str, model: str, messages: list, args: dict | None = None, prompt_files=()) -> str:
    raw = json.dumps({"provider": provider, "model": model, "messages": messages, "args": args or {}, "prompt_files": file_hashes(prompt_files)},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read(key: str):
    p = cache_dir() / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None                        # 깨진 파일은 없는 것으로 본다


def _write(key: str, entry: dict):
    d = cache_dir()
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
    os.replace(tmp, d / f"{key}.json")      # 원자적 교체
    stats["stored"] += 1


def cached_call(provider: str, model: str, messages: list, args: dict | None, fetch, prompt_files=(), tag: str = ""):
    """fetch()는 JSON 직렬화 가능한 응답(보통 문자열)을 돌려주는 실제 호출. 캐시 모드에 따라 건너뛴다."""
    m = mode()
    if m == "off":
        return fetch()
    key = cache_key(provider, model, messages, args, prompt_files)
    hit = _read(key)
    if hit is not None:
        stats["hit"] += 1
        return hit["response"]
    stats["miss"] += 1
    if m == "replay":
        raise CacheMiss(f"replay 모드: 저장본 없음 key={key[:12]} model={model} tag={tag}")
    resp = fetch()                         # 실패하면 예외가 그대로 올라가고 아무것도 저장하지 않는다
    _write(key, {"key": key, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "provider": provider, "model": model, "tag": tag,
                 "messages": messages, "args": args or {}, "prompt_files": file_hashes(prompt_files), "response": resp})
    return resp


def claude_call(model, system, user, max_tokens=1500, tag="", prompt_files=()):
    """_common.call()을 캐시로 감싼다. 실제 호출은 _common을 거치므로 상한 20 USD·원장 기록이 그대로 적용된다."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    args = {"max_tokens": max_tokens, "thinking": "between_tools" if model == SONNET else None}
    return cached_call("anthropic", model, messages, args, lambda: C.call(model, system, user, max_tokens=max_tokens, tag=tag), prompt_files, tag)


# ---------------------------------------------------------------------------------------------
def selftest() -> int:
    """(1) 가짜 fetch로 4개 모드·평가 강제 off·프롬프트 파일 변경 무효화를 비용 0으로 확인, (2) Haiku 2건으로 실제 적중을 확인."""
    saved = {k: os.environ.get(k) for k in ("LLM_CACHE", "LLM_CACHE_DIR", "MEDIAGENT_EVAL")}
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg)
        ok = ok and cond

    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LLM_CACHE_DIR"] = tmp
            os.environ.pop("MEDIAGENT_EVAL", None)
            calls = []
            fetch = lambda: calls.append(1) or "응답"        # noqa: E731
            msgs = [{"role": "user", "content": "x"}]
            pf = Path(tmp) / "prompt.md"
            pf.write_text("v1", encoding="utf-8")
            os.environ["LLM_CACHE"] = "off"
            cached_call("t", "m", msgs, {}, fetch); cached_call("t", "m", msgs, {}, fetch)
            check(len(calls) == 2 and not list(Path(tmp).glob("*.json")), "off: 매번 호출하고 저장하지 않는다")
            os.environ["LLM_CACHE"] = "replay"
            try:
                cached_call("t", "m", msgs, {}, fetch)
                check(False, "replay: 저장본이 없으면 예외")
            except CacheMiss:
                check(len(calls) == 2, "replay: 저장본이 없으면 CacheMiss, 호출하지 않는다")
            os.environ["LLM_CACHE"] = "record"
            cached_call("t", "m", msgs, {}, fetch, [pf]); cached_call("t", "m", msgs, {}, fetch, [pf])
            check(len(calls) == 3, "record: 첫 호출은 기록, 같은 입력의 둘째 호출은 적중")
            pf.write_text("v2", encoding="utf-8")
            cached_call("t", "m", msgs, {}, fetch, [pf])
            check(len(calls) == 4, "프롬프트 파일 내용이 바뀌면 키가 달라져 다시 호출")
            cached_call("t", "m", msgs, {"max_tokens": 5}, fetch, [pf])
            check(len(calls) == 5, "호출 인자가 바뀌면 키가 달라진다")
            os.environ["MEDIAGENT_EVAL"] = "1"
            cached_call("t", "m", msgs, {}, fetch, [pf])
            check(len(calls) == 6 and mode() == "off", "MEDIAGENT_EVAL=1이면 record여도 캐시를 쓰지 않는다")
            os.environ.pop("MEDIAGENT_EVAL")
            os.environ["LLM_CACHE"] = "bogus"
            try:
                mode(); check(False, "잘못된 LLM_CACHE 값은 예외")
            except ValueError:
                check(True, "잘못된 LLM_CACHE 값은 예외")

        # ---- 실제 Haiku 2건 (같은 입력을 두 번) ----
        os.environ.pop("LLM_CACHE_DIR", None)
        os.environ["LLM_CACHE"] = "record"
        system, user = "짧게 답한다.", f"llm_cache 시험: '삐약'이라고만 출력하세요. (시험 {int(time.time()) // 86400})"
        key = cache_key("anthropic", HAIKU, [{"role": "system", "content": system}, {"role": "user", "content": user}], {"max_tokens": 20, "thinking": None})
        cached_before = (cache_dir() / f"{key}.json").exists()
        n_calls = lambda: sum(1 for _ in C.CALLS.open()) if C.CALLS.exists() else 0       # noqa: E731
        c0, usd0 = n_calls(), C.spent()
        a = claude_call(HAIKU, system, user, max_tokens=20, tag="llm_cache_selftest")
        c1, usd1 = n_calls(), C.spent()
        b = claude_call(HAIKU, system, user, max_tokens=20, tag="llm_cache_selftest")
        c2, usd2 = n_calls(), C.spent()
        print(f"첫 응답: {a!r} / 둘째 응답: {b!r} / 호출 기록 {c0}->{c1}->{c2} / 누적 USD {usd0:.6f}->{usd1:.6f}->{usd2:.6f} / 이전 저장본 있었음: {cached_before}")
        check(a == b, "둘째 응답이 첫 응답과 같다")
        check(c2 == c1 and usd2 == usd1, "둘째 호출(적중)은 호출 기록·원장을 늘리지 않는다 (비용 0)")
        check(c1 == c0 + (0 if cached_before else 1), "첫 호출은 기록 모드에서 실제로 한 번만 호출했다(이미 저장본이 있었으면 0번)")
        check(C.spent() <= C.CAP_USD, f"누적 비용 {C.spent():.4f} USD ≤ 상한 {C.CAP_USD}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("selftest", "통과" if ok else "실패", stats)
    return 0 if ok else 1


if __name__ == "__main__":
    # S-05: 직접 실행할 때만 처리되지 않은 예외·logging 출력에서 키·DSN을 가린다(import만 할 때는 설치하지 않음)
    sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))  # app.security(공통 비노출 모듈)
    from app.security.redact import install_excepthook  # noqa: E402, PLC0415
    install_excepthook()
    sys.exit(selftest() if sys.argv[1:] == ["selftest"] else print(__doc__) or 2)
