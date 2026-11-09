"""공공 API 3종(e약은요, DUR 품목정보, DUR 성분정보)의 실제 응답을 확인하는 프로브.

인증키와 호출 주소는 저장소 루트의 `.env`에서 환경변수로만 읽는다. 키는 출력·저장·반환하지 않는다.
원본 응답은 `data/api_samples/`(git 제외)에 저장한다.
사용: .venv/bin/python backend/backend/scripts/api_probe/probe.py   (또는 app.py를 FastAPI로 띄움)
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "api_samples"
load_dotenv(ROOT / ".env")

# 서비스 별칭 -> 환경변수 접두사 (RFP 5.1절 (6))
SERVICES = {
    "eyak": "DRDEASYDRUG",
    "dur-item": "DURPrdlstInfoService03",
    "dur-ingr": "DURIrdntInfoService03",
    "drug-prmsn": "DrugPrdtPrmsnInfoService08",  # 의약품 제품 허가정보 (2026-11-01 승인)
}


def _env(service: str) -> tuple[str, str]:
    prefix = SERVICES[service]
    end_point = os.environ.get(f"{prefix}_END_POINT", "")
    api_key = os.environ.get(f"{prefix}_API_KEY", "")
    if not end_point or not api_key:
        raise RuntimeError(f"{prefix}_END_POINT / {prefix}_API_KEY 환경변수가 비어 있다")
    return end_point.rstrip("/"), api_key


def _mask(text: str, key: str) -> str:
    """오류 메시지 등에 키가 섞여 나오지 않게 한다."""
    if not key:
        return text
    return text.replace(key, "***").replace(quote(key, safe=""), "***")


def _trim(value, n: int = 70):
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def _extract_items(body: dict) -> list:
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    # 성분정보 서비스는 원소가 {"item": {...}} 한 겹 더 싸여 있다
    return [it["item"] if isinstance(it, dict) and set(it) == {"item"} and isinstance(it["item"], dict) else it for it in items]


def summarize(parsed) -> dict:
    """data.go.kr 응답의 공통 구조(header/body)에서 건수와 필드를 뽑는다."""
    out = {"result_code": None, "result_msg": None, "total_count": None, "item_count": 0, "fields": [], "sample": {}}
    if not isinstance(parsed, dict):
        return out
    header = parsed.get("header") or {}
    body = parsed.get("body") or {}
    out["result_code"] = header.get("resultCode")
    out["result_msg"] = header.get("resultMsg")
    out["total_count"] = body.get("totalCount")
    items = _extract_items(body)
    out["item_count"] = len(items)
    if items and isinstance(items[0], dict):
        fields: dict[str, int] = {}
        for it in items:
            for k, v in it.items():
                fields.setdefault(k, 0)
                if v not in (None, ""):
                    fields[k] += 1
        out["fields"] = [{"name": k, "filled": f"{c}/{len(items)}"} for k, c in fields.items()]
        out["sample"] = {k: _trim(v) for k, v in items[0].items()}
    return out


def call(service: str, operation: str, params: dict | None = None, tag: str = "", key_override: str | None = None) -> dict:
    """한 번 호출하고 요약을 돌려준다. 원본 응답은 data/api_samples/에 저장한다."""
    base, key = _env(service)
    if key_override:
        key = key_override
    params = {"pageNo": 1, "numOfRows": 3, "type": "json", **(params or {})}
    url = base if base.endswith(operation) else f"{base}/{operation}"
    # 포털 키가 이미 퍼센트 인코딩된 형태(%)이면 그대로, 아니면 인코딩해서 붙인다.
    key_q = key if "%" in key else quote(key, safe="")
    full = f"{url}?serviceKey={key_q}&{urlencode(params)}"
    started = time.perf_counter()
    result = {
        "service": service,
        "operation": operation,
        "params": {k: v for k, v in params.items()},
        "url_host_path": re.sub(r"^https?://", "", url),
    }
    try:
        resp = httpx.get(full, timeout=30.0)
    except Exception as exc:  # 네트워크 오류
        result.update(ok=False, error=_mask(f"{type(exc).__name__}: {exc}", key_q), elapsed_ms=int((time.perf_counter() - started) * 1000))
        return result
    elapsed = int((time.perf_counter() - started) * 1000)
    text = _mask(resp.text, key_q)
    result.update(http_status=resp.status_code, content_type=resp.headers.get("content-type", ""), bytes=len(resp.content), elapsed_ms=elapsed)
    parsed = None
    try:
        parsed = json.loads(text)
        result["format"] = "json"
    except ValueError:
        result["format"] = "xml/text"
        m = re.search(r"<returnAuthMsg>([^<]*)</returnAuthMsg>|<resultMsg>([^<]*)</resultMsg>|<errMsg>([^<]*)</errMsg>", text)
        result["error_text"] = _trim(next((g for g in (m.groups() if m else ()) if g), text[:200]), 160)
    result.update(summarize(parsed))
    result["ok"] = resp.status_code == 200 and result.get("result_code") in ("00", None) and parsed is not None
    SAMPLES.mkdir(parents=True, exist_ok=True)
    name = f"{service}__{operation}__{tag or 'sample'}.{'json' if parsed is not None else 'txt'}"
    (SAMPLES / name).write_text(json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else text, encoding="utf-8")
    result["saved"] = f"data/api_samples/{name}"
    return result


# 성분정보 서비스(DURIrdntInfoService03)의 오퍼레이션 이름은 02로 끝난다(2026-11-01 확인).
DUR_INGR_OPS = [
    "getUsjntTabooInfoList02",
    "getSpcifyAgrdeTabooInfoList02",
    "getPwnmTabooInfoList02",
    "getOdsnAtentInfoList02",
    "getCpctyAtentInfoList02",
    "getMdctnPdAtentInfoList02",
    "getEfcyDplctInfoList02",
]

DUR_OPS = [
    "getDurPrdlstInfoList03",
    "getUsjntTabooInfoList03",
    "getSpcifyAgrdeTabooInfoList03",
    "getPwnmTabooInfoList03",
    "getOdsnAtentInfoList03",
    "getCpctyAtentInfoList03",
    "getMdctnPdAtentInfoList03",
    "getEfcyDplctInfoList03",
    "getSeobangjeongPartitnAtentInfoList03",
]


def battery() -> list[dict]:
    """세 API의 확인 항목(RFP 5.1절 (7)의 '확인 전 사항' 포함)을 한 번에 호출한다."""
    runs: list[tuple[str, str, dict, str]] = []
    # e약은요: 일반약, 전문의약품(가설 TC-14·15), 전체 건수
    for tag, name in [("tylenol", "타이레놀"), ("mtx", "메토트렉세이트"), ("alendronate", "알렌드로네이트"), ("fosamax", "포사맥스")]:
        runs.append(("eyak", "getDrbEasyDrugList", {"itemName": name}, tag))
    runs.append(("eyak", "getDrbEasyDrugList", {"numOfRows": 1}, "total"))
    # DUR 품목정보: 오퍼레이션별 응답 (연령금기·노인주의·수유부 유사 항목 포함)
    for op in DUR_OPS:
        runs.append(("dur-item", op, {"itemName": "타이레놀"}, "tylenol"))
    # DUR 성분정보: 필터 없이 구조 확인
    for op in DUR_INGR_OPS:
        runs.append(("dur-ingr", op, {}, "nofilter"))
    results = []
    for s, o, p, t in runs:
        r = call(s, o, p, t)
        # 키 미등록(403)이면 같은 계정의 다른 서비스 키로 한 번 더 시도해 원인을 가른다(진단 전용, 키는 출력하지 않음).
        if s == "dur-ingr" and r.get("http_status") == 403:
            alt = os.environ.get(f"{SERVICES['dur-item']}_API_KEY", "")
            r2 = call(s, o, p, t + "__altkey", key_override=alt)
            r2["diagnostic"] = "성분정보 키 대신 품목정보 키 사용"
            r["alt_http_status"] = r2.get("http_status")
            r["alt_total_count"] = r2.get("total_count")
            results.append(r2)
            continue
        results.append(r)
    return results


def report(results: list[dict]) -> str:
    lines = ["# API 응답 확인 결과", "", "| 서비스 | 오퍼레이션 | 조건 | HTTP | 결과코드 | totalCount | 건수 | 시간(ms) | 비고 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        cond = ",".join(f"{k}={v}" for k, v in r["params"].items() if k not in ("pageNo", "type"))
        note = r.get("error") or r.get("error_text") or ("" if r.get("ok") else r.get("result_msg") or "")
        lines.append(f"| {r['service']} | {r['operation']} | {cond} | {r.get('http_status','-')} | {r.get('result_code')} | {r.get('total_count')} | {r.get('item_count')} | {r.get('elapsed_ms')} | {note} |")
    SAMPLES.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    (SAMPLES / "report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    res = battery()
    print(report(res))
    for r in res:
        if r.get("fields"):
            print(f"\n## {r['service']} / {r['operation']} ({r['params'].get('itemName', '')})")
            print("필드:", ", ".join(f["name"] for f in r["fields"]))
