"""DUR 성분정보 API 7 op **무필터 페이징** 수집기(BE-10-14 A, 2026-11-17).

목적: 사전 `api_codes`(DUR `D######` 성분코드)가 성분 1,581개 중 8개뿐이라 상비약 쌍이 `API_PAIR_INCOMPLETE`가 된다
(`data/mock/briefs/reports/lane-D.md` §3). 성분정보 API는 `ingrName` 필터를 무시하지만 무필터 조회는 되므로
7 op을 `numOfRows=100`으로 끝까지 받아 `data/mock/api_snapshots/dur-ingr/<op>/page-N.json`에 둔다.
빌더(`build_drug_dict.py`)가 이 파일에서 `INGR_CODE`·`MIXTURE_INGR_CODE`·`MIX_INGR` 등의 D 코드를 수확한다.

규칙:
  - 기본은 **dry-run**(호출 계획만 출력, 실호출 0). `--apply`가 있어야 호출한다.
  - `--max-calls N`(기본 60): 이 실행에서 보낼 HTTP 요청 상한(재시도 포함, `ApiHttpClient.max_calls`로도 걸어 둔다).
  - 호출 간 `--delay`초(기본 0.2) 지연. 이미 받은 페이지(`page-N.json`)는 건너뛰어 재개한다.
  - 응답 오류(`ApiError`)가 나면 그 자리에서 **중단**하고 `_nofilter_manifest.json`에 기록한다(종료 코드 1).
  - 인증키는 환경변수(`DURIrdntInfoService03_API_KEY`)로만 읽고 출력·저장하지 않는다. 메시지는 `app.security.redact`로 가린다.
  - 상태·목록 파일은 `dur-ingr/` **바로 아래**에 둔다(빌더의 `*/*.json` glob·재료 해시는 op 하위 폴더만 보므로 영향 없음).

사용(저장소 루트 `.env`를 읽는다. 실행은 메인 pane이 한다):
  cd backend && .venv/bin/python scripts/collect_dur_ingr_all.py                 # dry-run 계획
  cd backend && .venv/bin/python scripts/collect_dur_ingr_all.py --apply --max-calls 60
  cd backend && .venv/bin/python scripts/collect_dur_ingr_all.py --apply --ops getPwnmTabooInfoList02 --max-calls 15
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.security.redact import install_excepthook, redact, safe_exc
from app.tools._http import ApiError, ApiHttpClient, extract_items, format_utc
from app.tools.dur import INGR_ALIAS

install_excepthook()

ROOT = Path(__file__).resolve().parents[2]
SNAP_DIR = ROOT / "data" / "mock" / "api_snapshots" / "dur-ingr"
MANIFEST_NAME = "_nofilter_manifest.json"

# 7 op과 무필터 조회 totalCount(2026-11-01 `data/api_samples/dur-ingr__<op>__nofilter.json`, lane-D §3).
# dry-run 계획에만 쓰는 **추정치**이고 `--apply`는 첫 쪽 응답의 totalCount를 쓴다. `--assume-total OP=N`으로 덮어쓸 수 있다.
OPS: dict[str, tuple[str, int]] = {
    "getUsjntTabooInfoList02": ("병용금기", 1836),
    "getPwnmTabooInfoList02": ("임부금기", 1459),
    "getSpcifyAgrdeTabooInfoList02": ("연령금기", 233),
    "getCpctyAtentInfoList02": ("용량주의", 708),
    "getEfcyDplctInfoList02": ("효능군중복주의", 406),
    "getMdctnPdAtentInfoList02": ("투여기간주의", 98),
    "getOdsnAtentInfoList02": ("노인주의", 112),
}
DEFAULT_ROWS = 100
DEFAULT_MAX_CALLS = 60
DEFAULT_DELAY_S = 0.2
_PAGE_RE = re.compile(r"^page-(\d+)\.json$")


def pages_for(total: int, rows: int) -> int:
    return max(1, (max(int(total), 0) + rows - 1) // rows)


def page_path(snap_dir: Path, op: str, page: int) -> Path:
    return snap_dir / op / f"page-{page}.json"


def _read_page(path: Path) -> dict[str, Any] | None:
    """저장된 페이지가 온전하면(`body` 있음) 돌려준다. 깨졌으면 None(다시 받는다)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("body"), dict) else None


def existing_pages(snap_dir: Path, op: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    d = snap_dir / op
    if not d.is_dir():
        return out
    for p in d.iterdir():
        m = _PAGE_RE.match(p.name)
        if m:
            data = _read_page(p)
            if data is not None:
                out[int(m.group(1))] = data
    return out


def _total_of(body: dict[str, Any]) -> int | None:
    try:
        return int(body.get("totalCount"))
    except (TypeError, ValueError):
        return None


@dataclass
class OpPlan:
    op: str
    label: str
    total: int            # 추정(dry-run) 또는 저장된 페이지의 totalCount
    pages: int
    have: int             # 이미 받은 페이지 수
    todo: int             # 이번에 받을 페이지 수
    total_source: str     # "assumed" | "saved"


@dataclass
class Collector:
    """무필터 페이징 수집. `http`는 `ApiHttpClient` 호환(`get(operation, params) -> ApiResponse`)이면 된다(시험은 가짜 주입)."""

    http: Any
    snap_dir: Path
    max_calls: int = DEFAULT_MAX_CALLS
    delay: float = DEFAULT_DELAY_S
    rows: int = DEFAULT_ROWS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    out: Callable[[str], None] = print
    calls: int = field(default=0, init=False)
    _last_call: float | None = field(default=None, init=False)

    # ---- 계획(실호출 0) ----
    def plan(self, ops: Iterable[str], totals: dict[str, int] | None = None) -> list[OpPlan]:
        plans: list[OpPlan] = []
        for op in ops:
            label, est = OPS.get(op, (op, 0))
            have = existing_pages(self.snap_dir, op)
            saved_total = next((t for t in (_total_of(d["body"]) for d in have.values()) if t is not None), None)
            total, src = (saved_total, "saved") if saved_total is not None else ((totals or {}).get(op, est), "assumed")
            pages = pages_for(total, self.rows)
            todo = len([n for n in range(1, pages + 1) if n not in have])
            plans.append(OpPlan(op, label, total, pages, len(have), todo, src))
        return plans

    @staticmethod
    def format_plan(plans: list[OpPlan], max_calls: int) -> str:
        lines = ["| op | 유형 | totalCount | 쪽 | 받음 | 받을 것 | total 출처 |", "|---|---|---|---|---|---|---|"]
        for p in plans:
            lines.append(f"| {p.op} | {p.label} | {p.total} | {p.pages} | {p.have} | {p.todo} | {p.total_source} |")
        todo = sum(p.todo for p in plans)
        lines.append(f"예상 호출 {todo}회 (상한 {max_calls}회{', 상한 초과: 여러 번 나눠 실행' if todo > max_calls else ''}). 실호출 0(dry-run).")
        return "\n".join(lines)

    # ---- 실행 ----
    def _wait(self) -> None:
        now = self.clock()
        if self._last_call is not None:
            gap = self.delay - (now - self._last_call)
            if gap > 0:
                self.sleep(gap)
        self._last_call = self.clock()

    def _fetch(self, op: str, page: int) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            raise _Budget()
        self._wait()
        self.calls += 1
        resp = self.http.get(op, {"pageNo": page, "numOfRows": self.rows})
        return {"header": resp.parsed.get("header", {}), "body": resp.body,
                "_meta": {"operation": op, "pageNo": page, "numOfRows": self.rows, "filter": None,
                          "fetched_at": format_utc(resp.fetched_at), "request_hash": resp.request_hash, "source": resp.source}}

    def run(self, ops: Iterable[str]) -> dict[str, Any]:
        """op마다 1쪽부터 끝까지. 돌려주는 manifest의 `status`: done | budget | error. 오류면 뒤 op은 시도하지 않는다."""
        manifest = self._load_manifest()
        manifest["max_calls"] = self.max_calls
        manifest["rows"] = self.rows
        overall = "done"
        for op in ops:
            info = manifest["ops"].setdefault(op, {"label": OPS.get(op, (op, 0))[0]})
            info.update(status="running", error=None)
            have = existing_pages(self.snap_dir, op)
            page, total, saved, items = 1, None, 0, 0
            try:
                while True:
                    data = have.get(page)
                    if data is None:
                        data = self._fetch(op, page)
                        path = page_path(self.snap_dir, op, page)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                        saved += 1
                        info["last_fetched_at"] = data["_meta"]["fetched_at"]
                    rows = extract_items(data["body"])
                    items += len(rows)
                    total = _total_of(data["body"]) if total is None else total
                    self.out(f"{op}: [{page}/{pages_for(total or 0, self.rows)}] {len(rows)}행 (호출 {self.calls}/{self.max_calls})")
                    if not rows or total is None or page * self.rows >= total:
                        break
                    page += 1
            except _Budget:
                info.update(status="budget", next_page=page)
                overall = "budget"
            except ApiError as err:
                info.update(status="error", next_page=page,
                            error={"kind": err.kind, "http_status": err.http_status, "result_code": err.result_code, "message": redact(err.message)})
                self.out(f"{op}: {page}쪽 오류로 중단: {safe_exc(err)}")
                overall = "error"
            else:
                info.update(status="done", next_page=None)
            info.update(total_count=total, pages=len(existing_pages(self.snap_dir, op)), pages_saved_now=saved, items_seen=items, calls=self.calls)
            self._save_manifest(manifest, overall)
            if overall != "done":
                break
        manifest["status"] = overall
        manifest["calls"] = self.calls
        self._save_manifest(manifest, overall)
        return manifest

    # ---- manifest ----
    def _load_manifest(self) -> dict[str, Any]:
        p = self.snap_dir / MANIFEST_NAME
        if p.exists():
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(m, dict) and isinstance(m.get("ops"), dict):
                    return m
            except (OSError, ValueError):
                pass
        return {"ops": {}, "note": "DUR 성분정보 무필터 페이징(BE-10-14 A). 인증키·URL은 저장하지 않는다."}

    def _save_manifest(self, manifest: dict[str, Any], status: str) -> None:
        manifest["status"] = status
        manifest["calls"] = self.calls
        manifest["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        (self.snap_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


class _Budget(Exception):
    """호출 상한 도달(오류가 아니라 정상 중단)."""


# ---------------------------------------------------------------------------------------------
def _live_http(max_calls: int) -> ApiHttpClient:
    """저장소 루트 `.env`의 `DURIrdntInfoService03_*`로 live 클라이언트를 만든다. 캐시 없음(응답은 페이지 파일로만 남긴다)."""
    from pydantic_settings import SettingsConfigDict

    from app.config import Settings, reveal

    class _CollectSettings(Settings):
        model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    s = _CollectSettings(_env_file=(str(ROOT / ".env"), ".env"), mediagent_api_mode="live")
    return ApiHttpClient(INGR_ALIAS, s.durirdntinfoservice03_end_point, reveal(s.durirdntinfoservice03_api_key),
                         mode="live", cache=None, max_calls=max_calls)


def _parse_assume(values: list[str] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values or []:
        op, _, n = v.partition("=")
        if op not in OPS or not n.isdigit():
            raise SystemExit(f"--assume-total 형식: OP=N (OP는 {', '.join(OPS)} 중 하나): {v!r}")
        out[op] = int(n)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DUR 성분정보 7 op 무필터 페이징 수집(기본 dry-run)")
    ap.add_argument("--apply", action="store_true", help="실호출. 없으면 계획만 출력(호출 0)")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help=f"이 실행의 HTTP 요청 상한(기본 {DEFAULT_MAX_CALLS})")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_S, help=f"호출 간 지연 초(기본 {DEFAULT_DELAY_S})")
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS, help=f"numOfRows(기본 {DEFAULT_ROWS})")
    ap.add_argument("--ops", default=",".join(OPS), help="쉼표로 나눈 op 목록(기본 7개 전부)")
    ap.add_argument("--assume-total", action="append", metavar="OP=N", help="dry-run 계획용 totalCount 덮어쓰기")
    ap.add_argument("--snap-dir", default=str(SNAP_DIR))
    args = ap.parse_args(argv)

    ops = [o.strip() for o in args.ops.split(",") if o.strip()]
    bad = [o for o in ops if o not in OPS]
    if bad:
        raise SystemExit(f"모르는 op: {bad}")
    if args.max_calls < 1 or args.rows < 1 or args.delay < 0:
        raise SystemExit("--max-calls·--rows는 1 이상, --delay는 0 이상이어야 합니다")
    snap = Path(args.snap_dir)

    if not args.apply:
        c = Collector(http=None, snap_dir=snap, max_calls=args.max_calls, rows=args.rows)
        print(Collector.format_plan(c.plan(ops, _parse_assume(args.assume_total)), args.max_calls))
        return 0

    c = Collector(http=_live_http(args.max_calls), snap_dir=snap, max_calls=args.max_calls, delay=args.delay, rows=args.rows)
    print(Collector.format_plan(c.plan(ops, _parse_assume(args.assume_total)), args.max_calls))
    manifest = c.run(ops)
    summary = {op: {k: v for k, v in info.items() if k in ("status", "total_count", "pages", "pages_saved_now", "items_seen")}
               for op, info in manifest["ops"].items() if op in ops}
    print(json.dumps({"status": manifest["status"], "calls": c.calls, "ops": summary}, ensure_ascii=False, indent=1))
    return 0 if manifest["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
