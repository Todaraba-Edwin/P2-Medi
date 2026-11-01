"""공공 API 3종 응답 확인용 FastAPI. 실행: .venv/bin/uvicorn scripts.api_probe.app:app --port 8765

BE-01(FastAPI 초기화)·BE-02·BE-03의 응답 샘플 확인에 쓴다. 키는 노출하지 않는다.
"""
from fastapi import FastAPI, HTTPException, Request

from scripts.api_probe import probe

app = FastAPI(title="MediAgent API probe", version="0.1")


@app.get("/health")
def health():
    return {"ok": True, "services": list(probe.SERVICES)}


@app.get("/probe/{service}/{operation}")
def one(service: str, operation: str, request: Request):
    """예: /probe/eyak/getDrbEasyDrugList?itemName=타이레놀"""
    if service not in probe.SERVICES:
        raise HTTPException(404, f"service는 {list(probe.SERVICES)} 중 하나")
    params = dict(request.query_params)
    return probe.call(service, operation, params, tag=params.get("itemName") or params.get("ingrCode") or "adhoc")


@app.get("/battery")
def battery():
    results = probe.battery()
    probe.report(results)
    return [
        {k: r.get(k) for k in ("service", "operation", "params", "http_status", "result_code", "total_count", "item_count", "elapsed_ms", "ok", "error", "error_text", "saved")}
        for r in results
    ]
