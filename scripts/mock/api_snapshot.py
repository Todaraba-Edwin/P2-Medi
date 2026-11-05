"""공공 API 응답 원문 스냅샷 수집기(RFP-32). 개발 중 API·LLM 호출을 아끼려고 실제 사례 약의 응답을 미리 받아 둔다.

- 키는 환경변수로만 읽는다(.env는 dotenv로 로드, 값은 출력·저장하지 않는다). 저장하는 URL에서 serviceKey를 뺀다.
- 요청 해시(서비스·오퍼레이션·파라미터)가 같은 응답 파일이 이미 있으면 다시 호출하지 않는다.
- 호출 간 지연 0.3초 이상, 재시도 2회 이하, **한 번 실행 호출 상한 600**(재시도 포함), HTTP 403/429이거나
  오류율이 20%를 넘으면(표본 5건 이상) 즉시 멈춘다. 멈추면 지금까지 저장한 것은 남고 사유를 출력한다.
- 응답 원문을 mock/api_snapshots/<서비스>/<오퍼레이션>/<요청해시>.json|xml 로 그대로 저장한다(0건 응답도 저장).
  오류 응답은 <요청해시>.error.json|xml|txt 로 따로 저장하고 캐시로 보지 않는다.
- 조회 시각·파라미터(키 제외)·HTTP 상태·건수는 mock/api_snapshots/manifest.jsonl 에 호출마다 한 줄. 실행 요약은 runs.jsonl.
- 로컬 전용(mock/은 .gitignore). 공공 API 응답 원문의 재배포·이용 조건은 확인하지 못했다(법률 검토 보류).

사용: .venv/bin/python scripts/mock/api_snapshot.py {identify|items|ingr|permit|all} [--dry]
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "mock" / "api_snapshots"
MANIFEST = SNAP / "manifest.jsonl"
RUNS = SNAP / "runs.jsonl"
load_dotenv(ROOT / ".env")

SERVICES = {  # 서비스 별칭 -> 환경변수 접두사 (scripts/api_probe/probe.py와 같다)
    "eyak": "DRDEASYDRUG",
    "dur-item": "DURPrdlstInfoService03",
    "dur-ingr": "DURIrdntInfoService03",
    "drug-prmsn": "DrugPrdtPrmsnInfoService08",
}

CALL_CAP = 600          # 한 번 실행의 HTTP 요청 상한(재시도 포함)
MIN_DELAY = 0.3         # 요청 사이 최소 간격(초)
MAX_RETRIES = 2         # 재시도 횟수 상한(네트워크 오류·5xx만)
ERR_RATE_LIMIT = 0.2    # 오류율 상한
ERR_MIN_SAMPLE = 5      # 오류율 판정에 필요한 최소 요청 수
TIMEOUT = 60.0


class StopRun(Exception):
    """403/429, 오류율 초과, 호출 상한 도달 시 실행을 멈춘다."""


def _env(service: str) -> tuple[str, str]:
    prefix = SERVICES[service]
    end_point = os.environ.get(f"{prefix}_END_POINT", "")
    api_key = os.environ.get(f"{prefix}_API_KEY", "")
    if not end_point or not api_key:
        raise StopRun(f"{prefix}_END_POINT / {prefix}_API_KEY 환경변수가 비어 있다")
    return end_point.rstrip("/"), api_key


def extract_items(body: dict) -> list:
    """items 배열을 꺼낸다. 0건이면 items 키가 없고, 성분정보는 {"item": {...}} 한 겹이 더 싸여 있다."""
    items = (body or {}).get("items")
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return [it["item"] if isinstance(it, dict) and set(it) == {"item"} and isinstance(it["item"], dict) else it for it in items]


def norm_params(params: dict) -> dict:
    full = {"pageNo": 1, "numOfRows": 100, "type": "json", **params}
    return {k: str(v) for k, v in sorted(full.items())}


def request_hash(service: str, operation: str, params: dict) -> str:
    raw = json.dumps([service, operation, norm_params(params)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def snap_path(service: str, operation: str, h: str) -> Path | None:
    d = SNAP / service / operation
    for ext in ("json", "xml"):
        p = d / f"{h}.{ext}"
        if p.exists():
            return p
    return None


def load_snapshot(service: str, operation: str, params: dict):
    """저장된 스냅샷을 (parsed 또는 None, 원문 텍스트)로 돌려준다. 없으면 (None, None). 네트워크를 쓰지 않는다."""
    p = snap_path(service, operation, request_hash(service, operation, params))
    if p is None:
        return None, None
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text), text
    except ValueError:
        return None, text


class Snapshotter:
    def __init__(self, cap: int = CALL_CAP, dry: bool = False, stage: str = ""):
        self.cap, self.dry, self.stage = cap, dry, stage
        self.calls = 0          # HTTP 요청 수(재시도 포함)
        self.finished = 0       # 끝난 요청(성공+실패) 수
        self.errors = 0         # 최종 실패한 요청 수
        self.hits = 0           # 캐시(파일 있음)로 건너뛴 요청 수
        self.planned = 0        # dry: 호출이 필요했을 요청 수
        self.stopped = ""
        self._last = 0.0
        self._clients: dict[str, httpx.Client] = {}

    # ---- 내부 ----
    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < MIN_DELAY:
            time.sleep(MIN_DELAY - gap)
        self._last = time.monotonic()

    def _log(self, rec: dict):
        SNAP.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @staticmethod
    def _judge(text: str):
        """(parsed, fmt, result_code, total_count, item_count, ok) — 응답 본문 판정."""
        try:
            parsed = json.loads(text)
        except ValueError:
            m = re.search(r"<(?:resultCode|returnReasonCode)>\s*([^<\s]+)\s*<", text)
            code = m.group(1) if m else None
            is_err = "OpenAPI_ServiceResponse" in text or "cmmMsgHeader" in text
            t = re.search(r"<totalCount>\s*(\d+)\s*<", text)
            return None, "xml" if text.lstrip().startswith("<") else "txt", code, int(t.group(1)) if t else None, None, (not is_err and code in ("00", "0"))
        header = parsed.get("header") or (parsed.get("response") or {}).get("header") or {}
        body = parsed.get("body") or (parsed.get("response") or {}).get("body") or {}
        code = header.get("resultCode")
        total = body.get("totalCount")
        return parsed, "json", code, total, len(extract_items(body)), code == "00"

    # ---- 공개 ----
    def fetch(self, service: str, operation: str, params: dict | None = None, purpose: str = "") -> dict:
        """한 요청을 가져온다. 같은 해시의 파일이 있으면 호출하지 않는다.
        반환: {cached, ok, parsed, text, path, total, items, http_status, request_hash}"""
        params = norm_params(params or {})
        h = request_hash(service, operation, params)
        hit = snap_path(service, operation, h)
        if hit:
            self.hits += 1
            text = hit.read_text(encoding="utf-8")
            parsed, fmt, code, total, n, ok = self._judge(text)
            return dict(cached=True, ok=ok, parsed=parsed, text=text, path=hit, total=total, items=extract_items((parsed or {}).get("body") or {}),
                        http_status=200, request_hash=h)
        if self.dry:
            self.planned += 1
            return dict(cached=False, ok=False, parsed=None, text="", path=None, total=None, items=[], http_status=None, request_hash=h, planned=True)

        base, key = _env(service)
        key_q = key if "%" in key else quote(key, safe="")
        url = base if base.endswith(operation) else f"{base}/{operation}"
        clean_url = f"{re.sub(r'^https?://', '', url)}?{urlencode(params)}"      # serviceKey 없음
        full = f"{url}?serviceKey={key_q}&{urlencode(params)}"
        attempts, last_err, resp, text, elapsed = 0, "", None, "", 0
        while attempts <= MAX_RETRIES:
            if self.calls >= self.cap:
                self.stopped = f"호출 상한 {self.cap} 도달"
                raise StopRun(self.stopped)
            self._wait()
            self.calls += 1
            attempts += 1
            t0 = time.perf_counter()
            try:
                resp = httpx.get(full, timeout=TIMEOUT)
                elapsed = int((time.perf_counter() - t0) * 1000)
            except Exception as exc:  # noqa: BLE001  네트워크 오류: 재시도 대상
                last_err = type(exc).__name__
                resp = None
                continue
            if resp.status_code in (403, 429):
                break
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                continue
            break

        masked = False
        if resp is not None:
            text = resp.text
            for k in {key, key_q}:
                if k and k in text:
                    text, masked = text.replace(k, "***"), True
        status = resp.status_code if resp is not None else None
        parsed, fmt, code, total, n_items, ok = self._judge(text) if resp is not None else (None, "txt", None, None, None, False)
        ok = bool(resp is not None and status == 200 and ok)
        self.finished += 1
        if not ok:
            self.errors += 1

        d = SNAP / service / operation
        d.mkdir(parents=True, exist_ok=True)
        ext = "json" if fmt == "json" else ("xml" if fmt == "xml" else "txt")
        path = d / (f"{h}.{ext}" if ok else f"{h}.error.{ext}")
        if resp is not None:
            path.write_text(text, encoding="utf-8")                  # 원문 그대로(키가 섞였으면 ***로 가림)
        rec = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), stage=self.stage, service=service, operation=operation, params={k: v for k, v in params.items()},
                   url=clean_url, request_hash=h, http_status=status, result_code=code, total_count=total, item_count=n_items,
                   bytes=len(text.encode("utf-8")), elapsed_ms=elapsed, attempts=attempts, ok=ok, file=str(path.relative_to(ROOT)) if resp is not None else None,
                   purpose=purpose, masked=masked, error=None if ok else (last_err or f"HTTP {status} / resultCode {code}"))
        self._log(rec)

        if status in (403, 429):
            self.stopped = f"HTTP {status} ({service}/{operation})"
            raise StopRun(self.stopped)
        if self.finished >= ERR_MIN_SAMPLE and self.errors / self.finished > ERR_RATE_LIMIT:
            self.stopped = f"오류율 {self.errors}/{self.finished} > {ERR_RATE_LIMIT:.0%}"
            raise StopRun(self.stopped)
        return dict(cached=False, ok=ok, parsed=parsed, text=text, path=path, total=total, items=extract_items((parsed or {}).get("body") or {}),
                    http_status=status, request_hash=h)

    def fetch_pages(self, service: str, operation: str, params: dict, purpose: str = "", max_pages: int = 3) -> list[dict]:
        """totalCount가 한 쪽을 넘으면 다음 쪽도 가져온다(최대 max_pages쪽). 모자라면 마지막 결과에 truncated=True."""
        out = []
        rows = int(norm_params(params)["numOfRows"])
        for page in range(1, max_pages + 1):
            r = self.fetch(service, operation, {**params, "pageNo": page}, purpose=f"{purpose} p{page}" if page > 1 else purpose)
            out.append(r)
            total = r.get("total") or 0
            if not r["ok"] or page * rows >= int(total or 0):
                break
        else:
            out[-1]["truncated"] = True
        if out and out[-1].get("total") and len(out) * rows < int(out[-1]["total"]):
            out[-1]["truncated"] = True
        return out

    def summary(self) -> dict:
        return dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), stage=self.stage, http_requests=self.calls, finished=self.finished, errors=self.errors,
                    cache_hits=self.hits, planned_dry=self.planned, stopped=self.stopped or None, cap=self.cap)

    def write_run(self):
        if self.dry:
            return
        SNAP.mkdir(parents=True, exist_ok=True)
        with RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.summary(), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------------------------
# 확보 계획 (RFP-32 §4.1·§4.2). 약 목록은 PRD 15.3 시나리오와 RFP-21 §4 페르소나, RFP-31 M1이 쓴 약이다.
# ---------------------------------------------------------------------------------------------
# (키, 시나리오, 제품명 접두사). 접두사로 허가 목록(item_name 포함 검색)의 결과를 골라 품목기준코드를 정한다.
TARGETS = [
    ("tylenol_500", "S1·S2·S4·S8", "타이레놀정500밀리그람"),
    ("tylenol_8h", "S3·S4", "타이레놀8시간이알서방정"),
    ("tylenol_500_san", "S4", "타이레놀산500밀리그램"),
    ("tylenol_cold_s", "S1·S2·S3·S4·S8", "타이레놀콜드-에스정"),
    ("womens_tylenol", "S4", "우먼스타이레놀정"),
    ("children_san_160", "S3·S4", "어린이타이레놀산160밀리그램"),
    ("children_susp", "S3·S4", "어린이타이레놀현탁액"),
    ("easerect", "S2", "이지렉트정1.0밀리그램"),
    ("esomezol", "S5", "에소메졸캡슐40밀리그램"),
    ("mipron", "S1·S6a", "미프론정4mg"),
    ("simvarod", "S1", "심바로드정20"),
    ("rovasc", "S1", "로바스크정"),
]
NAME_QUERIES = ["타이레놀", "이지렉트", "에소메졸", "미프론", "심바로드", "로바스크", "라모시넥스"]   # 라모시넥스정은 S6b의 가상 약(0건 확인 대상)
ITEM_OPS = [  # DUR 품목정보 (오퍼레이션 이름은 …List03)
    "getUsjntTabooInfoList03", "getSpcifyAgrdeTabooInfoList03", "getPwnmTabooInfoList03", "getOdsnAtentInfoList03",
    "getCpctyAtentInfoList03", "getMdctnPdAtentInfoList03", "getEfcyDplctInfoList03", "getSeobangjeongPartitnAtentInfoList03",
]
INGR_OPS = [  # DUR 성분정보 (서비스는 …Service03이지만 오퍼레이션 이름은 …List02)
    "getUsjntTabooInfoList02", "getSpcifyAgrdeTabooInfoList02", "getPwnmTabooInfoList02", "getOdsnAtentInfoList02",
    "getCpctyAtentInfoList02", "getMdctnPdAtentInfoList02", "getEfcyDplctInfoList02",
]
KNOWN_INGR = {  # RFP-21 §4에서 2026-11-01에 확인한 성분코드
    "D000147": "아세트아미노펜", "D000448": "슈도에페드린", "D000200": "덱스트로메토르판", "D000698": "라사길린",
}
TARGETS_FILE = SNAP / "targets.json"


def stage_identify(s: Snapshotter):
    """제품 찾기: 이름으로 e약은요·DUR 품목정보·허가 목록을 조회하고, 허가 목록에서 품목기준코드를 정한다."""
    for q in NAME_QUERIES:
        s.fetch("eyak", "getDrbEasyDrugList", {"itemName": q}, purpose=f"identify {q}")
        s.fetch("dur-item", "getDurPrdlstInfoList03", {"itemName": q}, purpose=f"identify {q}")
        s.fetch("drug-prmsn", "getDrugPrdtPrmsnInq08", {"item_name": q}, purpose=f"identify {q}")
    if s.dry:
        return
    resolved, cands = {}, {}
    for q in NAME_QUERIES:
        r = s.fetch("drug-prmsn", "getDrugPrdtPrmsnInq08", {"item_name": q})
        cands[q] = [(x.get("ITEM_SEQ"), x.get("ITEM_NAME"), x.get("CANCEL_NAME")) for x in r["items"]]
    allc = [c for v in cands.values() for c in v]
    for key, sc, prefix in TARGETS:
        hit = [(sq, nm) for sq, nm, _ in allc if nm and nm.startswith(prefix)]
        hit = sorted(set(hit))
        resolved[key] = dict(scenarios=sc, prefix=prefix, items=[dict(item_seq=sq, item_name=nm) for sq, nm in hit])
    TARGETS_FILE.write_text(json.dumps(dict(resolved=resolved, candidates=cands), ensure_ascii=False, indent=1), encoding="utf-8")
    for key, v in resolved.items():
        print(f"{key:18} {v['prefix']:22} -> {[(i['item_seq'], i['item_name']) for i in v['items']]}")
    print("후보 수:", {q: len(v) for q, v in cands.items()})


def _target_seqs(limit_per_key: int = 3) -> list[tuple[str, str, str]]:
    cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    out = []
    for key, v in cfg["resolved"].items():
        for it in v["items"][:limit_per_key]:
            out.append((key, it["item_seq"], it["item_name"]))
    return out


def stage_items(s: Snapshotter):
    """금기 확인(품목 단위): DUR 품목정보 오퍼레이션 9개를 itemSeq로 조회한다. 같은 쪽에서 성분코드도 모은다."""
    codes = {}
    for key, seq, name in _target_seqs():
        rs = [s.fetch("dur-item", "getDurPrdlstInfoList03", {"itemSeq": seq}, purpose=f"item {key} {name}")]
        for op in ITEM_OPS:
            rs += s.fetch_pages("dur-item", op, {"itemSeq": seq}, purpose=f"item {key} {name}", max_pages=3)
        for r in rs:
            for it in r["items"]:
                if isinstance(it, dict) and it.get("INGR_CODE"):
                    codes.setdefault(it["INGR_CODE"], it.get("INGR_NAME") or it.get("INGR_KOR_NAME") or "")
    if not s.dry:
        (SNAP / "ingr_codes.json").write_text(json.dumps(codes, ensure_ascii=False, indent=1), encoding="utf-8")
        print("품목 응답에서 모은 성분코드:", codes)


def stage_ingr(s: Snapshotter):
    """성분 풀기 → 금기 확인(성분 단위): 성분코드마다 DUR 성분정보 오퍼레이션 7개를 ingrCode로 조회한다."""
    codes = dict(KNOWN_INGR)
    f = SNAP / "ingr_codes.json"
    if f.exists():
        codes.update({k: v or codes.get(k, "") for k, v in json.loads(f.read_text(encoding="utf-8")).items()})
    extra = SNAP / "ingr_codes_extra.json"          # 수동으로 확인한 성분코드(예: 에스오메프라졸)를 더하는 자리
    if extra.exists():
        codes.update(json.loads(extra.read_text(encoding="utf-8")))
    for code, nm in codes.items():
        for op in INGR_OPS:
            s.fetch_pages("dur-ingr", op, {"ingrCode": code}, purpose=f"ingr {code} {nm}", max_pages=3)
    print("성분코드:", codes)


def stage_permit(s: Snapshotter):
    """제품 찾기·성분 풀기·근거: 허가 상세(본문 XML)와 주성분 상세를 조회한다. 라벨은 e약은요도 이름으로 조회한다."""
    for key, seq, name in _target_seqs():
        s.fetch("drug-prmsn", "getDrugPrdtPrmsnDtlInq08", {"item_seq": seq}, purpose=f"permit detail {key} {name}")
        s.fetch("drug-prmsn", "getDrugPrdtMcpnDtlInq08", {"Prduct": name}, purpose=f"permit ingredients {key} {name}")
        s.fetch("eyak", "getDrbEasyDrugList", {"itemSeq": seq}, purpose=f"eyak by seq {key} {name}")


STAGES = {"identify": stage_identify, "items": stage_items, "ingr": stage_ingr, "permit": stage_permit}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry" in argv
    which = args[0] if args else "all"
    names = list(STAGES) if which == "all" else [which]
    if any(n not in STAGES for n in names):
        print("사용: api_snapshot.py {identify|items|ingr|permit|all} [--dry]")
        return 2
    s = Snapshotter(dry=dry, stage=which)
    code = 0
    try:
        for n in names:
            print(f"== 단계 {n}")
            STAGES[n](s)
    except StopRun as e:
        print(f"중단: {e}")
        s.stopped = s.stopped or str(e)
        code = 1
    finally:
        s.write_run()
        print(json.dumps(s.summary(), ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
