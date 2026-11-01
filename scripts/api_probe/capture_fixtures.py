"""공공 API 3종의 실제 응답을 목(mock) 픽스처로 저장한다. 서비스마다 3건.

저장 위치: tests/fixtures/api/<service>/<case>.json (응답 본문 그대로, 인증키 없음)
          tests/fixtures/api/manifest.json (사례 목록), tests/fixtures/api/field_survey.json (오퍼레이션별 필드 조사)
사용: .venv/bin/python scripts/api_probe/capture_fixtures.py
키는 .env의 환경변수로만 읽고 어디에도 쓰지 않는다. 저장 뒤 키 문자열이 파일에 없는지 스스로 검사한다.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.api_probe import probe  # noqa: E402

OUT = probe.ROOT / "tests" / "fixtures" / "api"

# (서비스, 사례 이름, 오퍼레이션, 요청 파라미터, 이 사례가 보여 주는 것)
CASES = [
    ("eyak", "hit_tylenol", "getDrbEasyDrugList", {"itemName": "타이레놀", "numOfRows": 3}, "일반의약품이 조회되는 정상 응답. 문장형 필드 7개"),
    ("eyak", "empty_rx_methotrexate", "getDrbEasyDrugList", {"itemName": "메토트렉세이트", "numOfRows": 3}, "전문의약품은 e약은요에 없다. 결과 0건일 때의 응답 모양"),
    ("eyak", "page2_no_filter", "getDrbEasyDrugList", {"pageNo": 2, "numOfRows": 3}, "필터 없이 전체 건수(totalCount)와 페이지 이동"),
    ("dur-item", "product_tylenol", "getDurPrdlstInfoList03", {"itemName": "타이레놀", "numOfRows": 3}, "품목 정보(전문/일반 구분, 성분 문자열, 문서 ID)"),
    ("dur-item", "age_taboo_tylenol", "getSpcifyAgrdeTabooInfoList03", {"itemName": "타이레놀", "numOfRows": 3}, "특정연령대금기: 품목 단위, 성분코드·고시일자 포함"),
    ("dur-item", "usjnt_methotrexate_injection", "getUsjntTabooInfoList03", {"itemSeq": "197900070", "numOfRows": 3}, "병용금기: 품목 단위, itemSeq 필터(460건)"),
    ("dur-ingr", "usjnt_itraconazole", "getUsjntTabooInfoList02", {"ingrCode": "D000762", "numOfRows": 3}, "병용금기: 성분 단위, ingrCode 필터, 상대 성분(MIXTURE_*)"),
    ("dur-ingr", "pwnm_grade", "getPwnmTabooInfoList02", {"numOfRows": 3}, "임부금기: 성분 단위, 등급(GRADE)"),
    ("dur-ingr", "age_base", "getSpcifyAgrdeTabooInfoList02", {"numOfRows": 3}, "특정연령대금기: 성분 단위, 연령 기준(AGE_BASE)"),
]

# 오퍼레이션별 필드 조사: 결과가 있는 조건으로 호출한다(후보를 순서대로 시도).
SURVEY = [
    ("dur-item", "getDurPrdlstInfoList03", [{"itemName": "타이레놀"}]),
    ("dur-item", "getUsjntTabooInfoList03", [{"itemSeq": "197900070"}]),
    ("dur-item", "getSpcifyAgrdeTabooInfoList03", [{"itemName": "타이레놀"}]),
    ("dur-item", "getPwnmTabooInfoList03", [{"itemName": "프로게스테론"}, {"itemName": "메토트렉세이트"}, {"itemName": "이소트레티노인"}]),
    ("dur-item", "getOdsnAtentInfoList03", [{"itemName": "디아제팜"}, {"itemName": "클로르디아제폭시드"}, {"itemName": "아티반"}]),
    ("dur-item", "getCpctyAtentInfoList03", [{"itemName": "타이레놀"}]),
    ("dur-item", "getMdctnPdAtentInfoList03", [{"itemName": "졸피뎀"}, {"itemName": "스틸녹스"}, {"itemName": "트리아졸람"}]),
    ("dur-item", "getEfcyDplctInfoList03", [{"itemName": "타이레놀"}]),
    ("dur-item", "getSeobangjeongPartitnAtentInfoList03", [{"itemName": "타이레놀"}]),
    ("eyak", "getDrbEasyDrugList", [{"itemName": "타이레놀"}]),
] + [("dur-ingr", op, [{}]) for op in probe.DUR_INGR_OPS]


def get_json(service: str, operation: str, params: dict) -> tuple[int, dict | None, str]:
    base, key = probe._env(service)
    q = {"pageNo": 1, "numOfRows": 3, "type": "json", **params}
    key_q = key if "%" in key else quote(key, safe="")
    resp = httpx.get(f"{base}/{operation}?serviceKey={key_q}&{urlencode(q)}", timeout=60.0)
    text = probe._mask(resp.text, key_q)
    try:
        return resp.status_code, json.loads(text), text
    except ValueError:
        return resp.status_code, None, text


def _types(values: list) -> str:
    kinds = sorted({("null" if v is None else type(v).__name__) for v in values})
    return "/".join(kinds)


def survey_one(items: list[dict]) -> list[dict]:
    fields: dict[str, list] = {}
    for it in items:
        for k, v in it.items():
            fields.setdefault(k, []).append(v)
    out = []
    for k, vals in fields.items():
        filled = [v for v in vals if v not in (None, "")]
        null_str = sum(1 for v in vals if isinstance(v, str) and v.strip().lower() == "null")
        ex = next((v for v in filled if not (isinstance(v, str) and v.strip().lower() == "null")), None)
        out.append({"name": k, "type": _types(vals), "filled": f"{len(filled)}/{len(vals)}", "null_string": null_str, "example": probe._trim(ex, 48) if ex is not None else None})
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    keys = {os.environ.get(f"{p}_API_KEY", "") for p in probe.SERVICES.values()} - {""}
    captured = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest = []
    for service, case, op, params, purpose in CASES:
        status, parsed, text = get_json(service, op, params)
        d = OUT / service
        d.mkdir(exist_ok=True)
        path = d / f"{case}.json"
        path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else text, encoding="utf-8")
        body = (parsed or {}).get("body", {})
        manifest.append({"service": service, "case": case, "operation": op, "params": {k: v for k, v in params.items()}, "http_status": status,
                         "total_count": body.get("totalCount"), "purpose": purpose, "file": f"tests/fixtures/api/{service}/{case}.json", "captured_at": captured})
        print(f"{service:9} {case:30} http={status} total={body.get('totalCount')}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    survey = []
    for service, op, candidates in SURVEY:
        used, items, total = None, [], None
        for params in candidates:
            status, parsed, _ = get_json(service, op, {**params, "numOfRows": 20})
            body = (parsed or {}).get("body", {})
            total = body.get("totalCount")
            items = probe._extract_items(body)
            if items:
                used = params
                break
        survey.append({"service": service, "operation": op, "params": used, "total_count": total, "sampled": len(items), "fields": survey_one(items)})
        print(f"survey {service:9} {op:42} total={total} sampled={len(items)} fields={len(survey[-1]['fields'])}")
    (OUT / "field_survey.json").write_text(json.dumps(survey, ensure_ascii=False, indent=2), encoding="utf-8")

    leaked = [str(p) for p in OUT.rglob("*.json") if any(k in p.read_text(encoding="utf-8") for k in keys)]
    print("키 문자열이 들어간 파일:", leaked or "없음")


if __name__ == "__main__":
    main()
