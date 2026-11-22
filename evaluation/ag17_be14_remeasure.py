"""AG-17 사진 입력 재측정: BE-14 구현물 경로(`POST /ingest/image` -> `app.api.vision.extract`)로 같은 4장·같은 검수 정답·3회.

사용(저장소 루트에서):
    PYTHONPATH=backend backend/.venv/bin/python evaluation/ag17_be14_remeasure.py run [--cap 0.05]   # 확대 12회 + 원본 12회 (실호출)
    PYTHONPATH=backend backend/.venv/bin/python evaluation/ag17_be14_remeasure.py grade               # 호출 없이 채점·후보 집계

조건은 직전 측정(AG-17-01, `vision_pouch_test.py`)과 같다: 이미지 `data/mock/medi-packet/` 4장, 검수 정답 `labels_user_reviewed.json`, 기존 채점 규칙
`vision_pouch_test.grade()`·`suggest()`를 그대로 재사용(정규화 완전 일치, 사전 top-5), 조건별 3회. 확대 = BE-14 `resize=True`(긴 변 1400px, JPEG q92), 원본 = 받은 바이트 그대로.
다른 점은 호출 경로뿐이다(BE-14 `vision.extract`: 스키마 제한·정리 규칙·원장 구분 `vision`).

비용 상한: 별도 원장 파일(`--ledger`, 기본 `data/mock/vision_test/ledger_ag17_be14.json`)에 구분 `vision` 상한 `--cap`(기본 0.05 USD)을 걸고,
호출 전 `extract`의 `guard`(누적 + 최악 비용 > 상한이면 호출 없음)와 이 스크립트의 누적 점검 두 겹으로 강제한다. 초과하면 즉시 중단한다.
키는 환경변수로만 읽고 값을 출력·기록하지 않는다. 이미지·base64·OCR 글자는 남기지 않는다(결과 파일에는 약 이름 출력만, 로컬 전용).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MAIN_ROOT = Path("/Users/edwin/develop/P2-Medi")  # 로컬 전용 data/·.env 가 있는 저장소(worktree에는 data/가 없다)
sys.path.insert(0, str(HERE / "mock_gen"))
sys.path.insert(0, str(REPO / "backend"))

import vision_pouch_test as vpt  # noqa: E402

CAP_DEFAULT = 0.05
SUFFIX = "_ag17be14"
RUNS = 3

vpt.ROOT = MAIN_ROOT
vpt.IMG_DIR = MAIN_ROOT / "data" / "mock" / "medi-packet"
vpt.OUT = MAIN_ROOT / "data" / "mock" / "vision_test"
vpt.LABELS = vpt.OUT / "labels_user_reviewed.json"
vpt.PROVIDER = "openai"  # 결과·채점 파일 이름 규칙(results_luna<suffix>[_upscaled].json)을 재사용
vpt.SUFFIX = SUFFIX


class CapturingClient:
    """실제 OpenAI 클라이언트를 감싸 마지막 응답 글자·토큰을 잡아 둔다(정리 전 `raw`의 확신도 채점용, 로그 없음)."""

    def __init__(self, inner):
        self.inner = inner
        self.last = None

    def complete(self, **kw):
        c = self.inner.complete(**kw)
        self.last = c
        return c


def _images() -> list[Path]:
    return sorted(p for p in vpt.IMG_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def run(cap: float, ledger_path: Path) -> None:
    from dotenv import load_dotenv
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import ingest, vision
    from app.llm.ledger import CostLedger

    load_dotenv(MAIN_ROOT / ".env")  # 값은 읽기만(출력·기록 안 함)
    led = CostLedger(ledger_path, bucket_caps={"vision": cap})
    cl = CapturingClient(vision.OpenAIVisionClient())
    app = FastAPI()
    ingest.register(app)
    ingest.set_vision(app, client=cl, ledger=led)
    http = TestClient(app)
    log = REPO / "logs" / "ag17_be14_remeasure.jsonl"
    log.parent.mkdir(exist_ok=True)
    import base64

    for upscale in (True, False):
        # 원본 조건은 서비스 엔드포인트가 항상 확대하므로 `resize=False`로 함수를 직접 부른다(같은 함수·원장·정리 규칙).
        results = {"model": vision.MODEL, "runs": RUNS, "path": "be14 /ingest/image" if upscale else "be14 vision.extract(resize=False)",
                   "cap_usd": cap, "upscale_long_side": vpt.UPSCALE_LONG_SIDE if upscale else None, "started": time.strftime("%F %T"),
                   "images": {}}
        for p in _images():
            results["images"][p.name] = []
            data = p.read_bytes()
            for k in range(1, RUNS + 1):
                if led.spent("vision") >= cap:
                    raise SystemExit(f"중단: 누적 ${led.spent('vision'):.6f} >= 상한 ${cap}")
                tag = f"{p.stem}{'-up' if upscale else ''}-run{k}"
                cl.last = None
                t0 = time.monotonic()
                if upscale:
                    mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
                    resp = http.post("/ingest/image", json={"image": f"data:{mime};base64,{base64.b64encode(data).decode()}"})
                    body = resp.json()
                    status, reason, be_drugs = body.get("status"), body.get("reason"), [
                        {k2: d.get(k2) for k2 in ("read_name", "read_ingredient", "strength_or_form")} for d in body.get("drugs", [])]
                    http_code = resp.status_code
                    in_t = cl.last.prompt_tokens if cl.last else 0
                    out_t = cl.last.completion_tokens if cl.last else 0
                else:
                    res = vision.extract(data, client=cl, ledger=led, resize=False)
                    status, reason, http_code = res.status, res.reason, None
                    be_drugs = [{"read_name": d["product_name"], "read_ingredient": d["ingredient_name"], "strength_or_form": d["strength_or_form"]}
                                for d in res.drugs]
                    in_t, out_t = res.in_tokens, res.out_tokens
                latency = round(time.monotonic() - t0, 2)
                usd = vision.actual_cost(in_t, out_t)
                raw = vision.parse_output(cl.last.content) if cl.last else None
                clean, dropped = vpt.sanitize(raw)  # 직전 측정과 같은 채점용 정리(확신도 포함)
                results["images"][p.name].append({
                    "tag": tag, "mode": "be14", "parse_ok": raw is not None, "stop_reason": cl.last.finish_reason if cl.last else None,
                    "refusal": bool(cl.last and cl.last.refusal), "in_tokens": in_t, "out_tokens": out_t, "usd": round(usd, 6), "latency_s": latency,
                    "dropped_keys": dropped, "leak_hits": vpt.leak_hits(clean), "output": clean,
                    "be14": {"status": status, "reason": reason, "http": http_code, "drugs": be_drugs},
                })
                with log.open("a") as f:  # 이름·이미지 없이 수치만
                    f.write(json.dumps({"ts": time.strftime("%F %T"), "tag": tag, "status": status, "reason": reason, "n_drugs": len(be_drugs),
                                        "in": in_t, "out": out_t, "usd": round(usd, 6), "latency_s": latency}) + "\n")
                print(f"{tag}: status={status} reason={reason} n_be14={len(be_drugs)} n_raw={len(clean['drugs'])} ${usd:.5f} "
                      f"누적 ${led.spent('vision'):.6f}/{cap}", flush=True)
        results["finished"] = time.strftime("%F %T")
        results["ledger_usd"] = led.spent("vision")
        res_path, _ = vpt.paths(upscale)
        res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"저장: {res_path.name}")


def grade() -> None:
    for up in (True, False):
        vpt.grade(up)
    vpt.suggest()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    cap = float(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else CAP_DEFAULT
    led = Path(sys.argv[sys.argv.index("--ledger") + 1]) if "--ledger" in sys.argv else vpt.OUT / "ledger_ag17_be14.json"
    if cmd == "run":
        run(cap, led)
        grade()
    elif cmd == "grade":
        grade()
    else:
        raise SystemExit(__doc__)
