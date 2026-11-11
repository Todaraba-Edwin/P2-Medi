"""RFP-03 점검: AG-02 도구(서비스 경로, api_enabled=True)로 e약은요·DUR를 실제 호출해 결과에 조회 시각·출처가 함께 오는지 필드 단위로 확인한다.

- 기본은 dry-run(계획과 호출 예산만 출력, 네트워크·파일 적재 없음). `--run --yes`를 함께 줄 때만 실호출한다.
- 저장소 루트에서 실행: `cd <repo> && backend/.venv/bin/python backend/scripts/rfp03_live_check.py [--run --yes]`
- 키·주소는 `app.config`(환경변수)로만 읽고 출력하지 않는다. 응답 원문은 쓰지 않고, 필드 존재·형식 요약만 `data/mock/api_live_check/`에 쓴다.
- 총 HTTP 요청은 서비스별 `max_calls`와 합계 상한(기본 20)으로 막고, 재시도는 0이다. 401·429·인증·한도 오류면 즉시 중단한다.
- 병용금기 파일 판정은 로컬 `data/`의 병용금기 JSON을 메모리 SQLite에 스트리밍 적재해서 쓴다(원격 DB 없음).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.tools.context import ToolContext, ingredient_api_fns  # noqa: E402
from app.agent.tools.registry import invoke  # noqa: E402
from app.db import loaders  # noqa: E402
from app.db.source_files import COMBO_JSON_NAME  # noqa: E402
from app.tools import _http  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402
from app.tools.dur import INGR_ALIAS, ITEM_ALIAS, DurClient  # noqa: E402
from app.tools.eyak import SERVICE_ALIAS as EYAK_ALIAS  # noqa: E402
from app.tools.eyak import EyakClient  # noqa: E402
from app.tools.prmsn import SERVICE_ALIAS as PRMSN_ALIAS  # noqa: E402
from app.tools.prmsn import PrmsnClient  # noqa: E402

DATA = ROOT / "data"
OUT_DIR = DATA / "mock" / "api_live_check"
TOTAL_CAP = 20
# 서비스별 HTTP 요청 상한(합계 18 ≤ TOTAL_CAP). dur-item은 이 점검에서 쓰지 않는다.
BUDGET = {EYAK_ALIAS: 3, PRMSN_ALIAS: 3, ITEM_ALIAS: 0, INGR_ALIAS: 12}
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
STOP_KINDS = {"auth", "rate_limit", "config", "call_budget"}

# 점검 시나리오(상비약). 이름은 사전이 풀고, 판정에 쓰는 것은 도구 안의 코드다.
LABEL_NAME = "타이레놀정500mg"
LABEL_SECTION = "용법용량"
# 사전에서 DUR API 성분코드(api_codes)가 붙은 성분은 8개뿐이라(2026-11-11 확인) 그중 병용금기 가능성이 있는 쌍을 코드로 직접 준다.
# 라사길린(D000698) × 슈도에페드린(D000448). 타이레놀 쌍은 사전에 api_codes가 있는 상대가 없어 API_PAIR_INCOMPLETE가 된다.
PAIR_DRUGS = [{"ingredient_code": "D000698"}, {"ingredient_code": "D000448"}]
AGE_DRUG = "타이레놀정500mg"
AGE = {"value": 2, "unit": "세"}


class LiveLabelProvider:
    """`LabelProvider` 실호출 판. 허가 상세·e약은요를 공공 API에서 받아 `{"item", "collected_at", "source"}`로 돌려준다."""

    def __init__(self, eyak: EyakClient, prmsn: PrmsnClient) -> None:
        self.eyak_client, self.prmsn_client = eyak, prmsn

    def eyak(self, item_seq: str) -> dict[str, Any] | None:
        r = self.eyak_client.get_by_item_seq(item_seq)
        if not r.ok:
            raise RuntimeError(f"eyak:{r.error.kind if r.error else 'unknown'}")
        if not r.items:
            return None
        return {"item": r.items[0].model_dump(), "collected_at": r.queried_at_utc, "source": r.source or "live"}

    def prmsn_detail(self, item_seq: str) -> dict[str, Any] | None:
        r = self.prmsn_client.detail_by_item_seq(item_seq)
        if not r.ok:
            raise RuntimeError(f"prmsn:{r.error.kind if r.error else 'unknown'}")
        if not r.raw_items:
            return None
        return {"item": r.raw_items[0], "collected_at": r.queried_at_utc, "source": r.source or "live"}


def _http_clients(settings: Any) -> dict[str, _http.ApiHttpClient]:
    cache = _http.cache_from_settings(settings)
    spec = {
        EYAK_ALIAS: (settings.drdeasydrug_end_point, settings.drdeasydrug_api_key),
        PRMSN_ALIAS: (settings.drugprdtprmsninfoservice08_end_point, settings.drugprdtprmsninfoservice08_api_key),
        ITEM_ALIAS: (settings.durprdlstinfoservice03_end_point, settings.durprdlstinfoservice03_api_key),
        INGR_ALIAS: (settings.durirdntinfoservice03_end_point, settings.durirdntinfoservice03_api_key),
    }
    return {
        a: _http.ApiHttpClient(a, url, key, mode="live", cache=cache, max_retries=0, max_calls=BUDGET[a])
        for a, (url, key) in spec.items()
    }


def _load_file_db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    parts = {}
    for name, norm, table in [
        ("한국의약품안전관리원_연령금기_20260721.csv", loaders.normalize_age, "age_contra"),
        ("한국의약품안전관리원_임부금기약물_20260721.csv", loaders.normalize_pregnancy, "pregnancy_contra"),
    ]:
        if (DATA / name).is_file():
            parts[name] = loaders.read_source(DATA / name, norm, table, loaders.AS_OF_KIDS)
    contra = DATA / COMBO_JSON_NAME
    if contra.is_file():
        parts[contra.name] = loaders.read_source(contra, loaders.normalize_contra_json, "contra_pair", loaders.AS_OF_KIDS)
    loaders.load_into(c, parts)
    return c


class _KeepOpen:
    def __init__(self, c: sqlite3.Connection) -> None:
        self._c = c

    def cursor(self) -> Any:
        return self._c.cursor()

    def close(self) -> None:
        pass


def _field_report(it: dict[str, Any]) -> dict[str, Any]:
    """값은 싣지 않고 존재·형식만 요약한다."""
    api = it.get("api") if isinstance(it.get("api"), dict) else {}
    ts = it.get("queried_at_utc")
    api_ts = api.get("queried_at_utc")
    return {
        "kind": it.get("kind"), "status": it.get("status"), "dataset_key": it.get("dataset_key"),
        "has_source": bool(it.get("source")), "has_source_kind": bool(it.get("source_kind")), "source_kind": it.get("source_kind"),
        "has_as_of": bool(it.get("as_of")), "as_of_fmt_ok": bool(re.match(r"^\d{4}-\d{2}-\d{2}$", str(it.get("as_of") or ""))),
        "has_evidence_id": bool(it.get("evidence_id")),
        "queried_at_utc_present": bool(ts), "queried_at_utc_fmt_ok": bool(ts and UTC_RE.match(str(ts))),
        "queried_at_kind": it.get("queried_at_kind"),
        "api_block_present": bool(api), "api_outcome": api.get("outcome"),
        "api_queried_at_utc_present": bool(api_ts), "api_queried_at_utc_fmt_ok": bool(api_ts and UTC_RE.match(str(api_ts))),
        "flags": it.get("flags"), "missing_reason": it.get("missing_reason"),
    }


def _summ(name: str, out: dict[str, Any]) -> dict[str, Any]:
    items = [_field_report(i) for i in out.get("items", [])]
    return {"call": name, "n_items": len(items), "contract_violations": out.get("contract_violations", []),
            "error": out.get("error"), "items": items}


def plan() -> dict[str, Any]:
    return {
        "mode": "dry-run", "total_http_cap": TOTAL_CAP, "per_service_budget": BUDGET, "retries": 0,
        "scenarios": [
            {"tool": "identify_drug", "args": {"name": LABEL_NAME}, "http": 0},
            {"tool": "get_label_section", "args": {"name": LABEL_NAME, "section": LABEL_SECTION}, "http": "e약은요 1 + 허가 상세 1"},
            {"tool": "check_contraindications", "args": {"pair": [d["ingredient_code"] for d in PAIR_DRUGS]}, "http": "DUR 성분정보 쌍 조회(양방향)"},
            {"tool": "check_contraindications", "args": {"drug": AGE_DRUG, "age": AGE, "pregnancy": True}, "http": "DUR 성분정보 연령 1 + 임부 1"},
        ],
        "note": "실호출은 --run --yes 로만 한다. 기본값에서는 네트워크를 쓰지 않는다.",
    }


def run() -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    clients = _http_clients(settings)
    missing = [a for a, c in clients.items() if BUDGET[a] > 0 and not (c.base_url and c.api_key)]
    if missing:
        return {"aborted": "config", "services_without_config": missing}
    dur = DurClient(clients[ITEM_ALIAS], clients[INGR_ALIAS], max_pages=2)
    labels = LiveLabelProvider(EyakClient(clients[EYAK_ALIAS]), PrmsnClient(clients[PRMSN_ALIAS]))
    age_fn, preg_fn = ingredient_api_fns(dur)
    conn = _load_file_db()
    ctx = ToolContext(
        DrugDict.load(), conn_factory=lambda: _KeepOpen(conn), api_enabled=True,
        api_pair_fn=dur.usjnt_pair_by_ingredient, api_age_fn=age_fn, api_pregnancy_fn=preg_fn, label_provider=labels,
    )
    results: list[dict[str, Any]] = []
    stopped: str | None = None

    def total_calls() -> int:
        return sum(c.calls for c in clients.values())

    ident = invoke("identify_drug", {"name": LABEL_NAME}, ctx)
    results.append(_summ("identify_drug", ident))
    seq = next((i.get("item_seq") for i in ident.get("items", []) if i.get("item_seq")), None)

    steps: list[tuple[str, str, dict[str, Any]]] = []
    if seq:
        steps.append(("get_label_section", "get_label_section", {"item_seq": seq, "section": LABEL_SECTION}))
    steps.append(("check_contraindications(pair)", "check_contraindications", {"drugs": PAIR_DRUGS}))
    steps.append(("check_contraindications(age+pregnancy)", "check_contraindications",
                  {"drugs": [{"name": AGE_DRUG}], "age": AGE, "pregnancy": True}))
    for label, tool, args in steps:
        if total_calls() >= TOTAL_CAP:
            stopped = "total_cap"
            break
        out = invoke(tool, args, ctx)
        s = _summ(label, out)
        results.append(s)
        errs = [i.get("api", {}).get("outcome") for i in out.get("items", []) if isinstance(i.get("api"), dict)]
        kinds = {i.get("missing_reason") for i in out.get("items", [])}
        if "FETCH_FAIL" in kinds or any(e == "API_UNAVAILABLE" for e in errs):
            s["note"] = "API 실패 신호(FETCH_FAIL·API_UNAVAILABLE): 이후 호출 중단"
            stopped = "api_failure"
            break
    return {
        "mode": "run", "ran_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "http_calls": {a: c.calls for a, c in clients.items()}, "http_total": total_calls(), "http_cap": TOTAL_CAP,
        "stopped": stopped, "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true", help="실제 호출(--yes 필요)")
    ap.add_argument("--yes", action="store_true", help="실호출 확인")
    args = ap.parse_args(argv)
    if not (args.run and args.yes):
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0
    report = run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"rfp03_live_check_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"saved: {out.relative_to(ROOT)}")
    return 1 if report.get("aborted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
