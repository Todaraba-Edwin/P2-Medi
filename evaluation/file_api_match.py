"""BE-08 파일 판정·DUR API 일치율 **관찰** 스크립트(PJ2-RFP.md 5.1절 (7)·9.4절, BE-08 §2 "파일·API 일치율은 평가 점수와 별도 관찰값").

평가 지표가 아니다. 평가 실행(`eval_runner`)은 API를 끈 채 파일로만 판정하고, 이 스크립트는 **API를 켠 소규모 실행**으로 같은 질문의 파일 판정과
실시간 DUR 응답이 얼마나 같은지(`API_SAME` / 비교된 항목)를 따로 기록한다. 모델(LLM)은 부르지 않고 판정 도구 `check_contraindications`만 직접 부른다.

입력: 기본은 개발셋의 금기 판정 문항(정상-병용·연령·임부 35개, 제품 이름·프로필). `--input FILE.jsonl`이면 한 줄에
`{"id", "drugs": [이름...], "age": {"value", "unit"} | null, "pregnant": bool}`(데모·실제 질문). 시험셋은 받지 않는다(가드 경유 금지).

두 단계:
  1) dry-run(기본, 호출 0): 사전(로컬 파일)만으로 약을 식별하고 문항별 **예상 API 호출 수**(쌍·임부·연령)와 합계를 낸다. DB·API·네트워크 없음.
  2) `--execute --yes --max-calls N`: 원격 DB(읽기 전용) 파일 판정 + DUR API 실호출. **사용자 승인 뒤에만**(호출 수 상한 N을 넘기면 그 뒤는 실패 꼬리표로 남긴다).
출력(JSON, `logs/eval/file-api-match-<UTC>.json`, 로컬 전용): 문항 ID·종류별 꼬리표 건수(`API_SAME`·`FILE_ONLY`·`API_ONLY`·`API_FAIL`·
`API_PAIR_INCOMPLETE`)·일치율(k/n, Wilson 95%), 파일 기준일, 실제 호출 수. 약 이름·질문·응답 원문은 남기지 않는다.

사용(저장소 루트):
    backend/.venv/bin/python evaluation/file_api_match.py                       # dry-run: 예상 호출 수
    backend/.venv/bin/python evaluation/file_api_match.py --execute --yes --max-calls 120   # 승인 뒤 실호출
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_metrics as M  # noqa: E402
import sealed_guard as G  # noqa: E402

DEV_SET = HERE / "eval_set" / "dev_set.jsonl"
OUT_DIR = ROOT / "logs" / "eval"
JUDGMENT_GROUPS = ("정상-병용", "정상-연령", "정상-임부")
MATCH_FLAGS = ("API_SAME", "FILE_ONLY", "API_ONLY")          # 비교가 된 항목(일치율의 분모)
NOT_COMPARED_FLAGS = ("API_FAIL", "API_PAIR_INCOMPLETE")      # 비교하지 못한 항목(분모에서 뺀다, 따로 센다)
VERSION = "file-api-match@v1"


class CallCapReached(RuntimeError):
    """실호출 상한(`--max-calls`)에 닿았다. 도구는 이 예외를 실패 꼬리표로 바꾼다."""


def load_inputs(input_path: Path | None) -> list[dict[str, Any]]:
    """관찰 입력 목록 `{"id", "drugs", "age", "pregnant"}`. 시험셋 파일은 열지 않는다."""
    if input_path is not None:
        if G.is_sealed(input_path):
            raise G.SealedAccessError("일치율 관찰은 시험셋을 쓰지 않는다")
        rows = [json.loads(ln) for ln in input_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [{"id": str(r["id"]), "drugs": list(r["drugs"]), "age": r.get("age"), "pregnant": bool(r.get("pregnant"))} for r in rows]
    out = []
    for r in G.load_jsonl(DEV_SET):
        if r.get("composition_group") not in JUDGMENT_GROUPS:
            continue
        prof = r.get("profile") or {}
        out.append({"id": str(r["id"]), "drugs": list(r.get("products") or []), "age": prof.get("age"), "pregnant": bool(prof.get("pregnant"))})
    return out


def tool_args(inp: dict[str, Any]) -> Any:
    from app.agent.tools.schemas import AgeArg, CheckContraArgs, DrugArg

    age = inp.get("age")
    return CheckContraArgs(drugs=[DrugArg(name=n) for n in inp["drugs"]], pregnancy=bool(inp.get("pregnant")),
                           age=AgeArg(value=age["value"], unit=age["unit"]) if age else None)


def planned_calls(inp: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """dry-run: 사전만으로 약을 식별해 도구가 API를 몇 번 부를지 센다(상한 추정: 쌍은 두 약의 DUR 코드 조합 수, 임부·연령은 약별 DUR 코드 수).
    도구 규칙(`check_contraindications`: 약당 코드 상한·코드 형식 검사·식별 못 한 약은 호출 없음)을 그대로 따른다."""
    from itertools import combinations, product

    from app.agent.tools import check_contraindications as cc

    args = tool_args(inp)
    drugs = [cc._resolve(ctx, a) for a in args.drugs]

    def codes(d: Any) -> list[str]:
        return [c for c in d.api_codes[: cc.MAX_API_CODES_PER_DRUG] if cc.DUR_CODE_RE.match(c)]

    pair = sum(len(codes(a)) * len(codes(b)) for a, b in combinations(drugs, 2)
               if a.ok and b.ok and any(x != y for x, y in product(a.kids_codes, b.kids_codes)))
    ok = [d for d in drugs if d.ok]
    preg = sum(len(codes(d)) for d in ok) if args.pregnancy else 0
    age = sum(len(codes(d)) for d in ok) if args.age is not None else 0
    return {"id": inp["id"], "n_drugs": len(drugs), "identified": len(ok), "no_api_code": sum(1 for d in ok if not codes(d)),
            "calls": {"pair": pair, "pregnancy": preg, "age": age}, "total": pair + preg + age}


def dry_run(inputs: Sequence[dict[str, Any]], drug_dict: Any) -> dict[str, Any]:
    from app.agent.tools.context import ToolContext

    ctx = ToolContext(drug_dict=drug_dict, api_enabled=False)
    rows = [planned_calls(i, ctx) for i in inputs]
    return {"version": VERSION, "mode": "dry-run", "n_inputs": len(rows), "planned_calls_total": sum(r["total"] for r in rows),
            "planned_by_kind": {k: sum(r["calls"][k] for r in rows) for k in ("pair", "pregnancy", "age")},
            "inputs_without_api_call": sum(1 for r in rows if r["total"] == 0), "items": rows,
            "note": "상한 추정(파일 쌍 조회 결과가 없으면 그 쌍의 API 호출은 없다). LLM·DB·API 호출 0"}


def capped(fn: Callable[..., Any] | None, counter: dict[str, int], max_calls: int) -> Callable[..., Any] | None:
    """API 함수에 호출 수 상한을 씌운다. 상한에 닿으면 호출하지 않고 예외(도구가 `API_FAIL`로 기록)."""
    if fn is None:
        return None

    def wrapped(*a: Any, **k: Any) -> Any:
        if counter["calls"] >= max_calls:
            counter["refused"] += 1
            raise CallCapReached("max-calls")
        counter["calls"] += 1
        return fn(*a, **k)

    return wrapped


def tally(inp_id: str, out: dict[str, Any]) -> dict[str, Any]:
    """도구 결과 하나에서 꼬리표를 센다(내용·이름은 읽지 않는다). 파일 항목(`source_kind`가 API가 아닌 것)만 센다."""
    by_kind: dict[str, dict[str, int]] = {}
    for it in out.get("items") or []:
        if str(it.get("source_kind") or "").startswith("API"):
            continue  # API 원문 행(병기용 별도 항목)은 세지 않는다
        for f in it.get("flags") or []:
            if f in MATCH_FLAGS or f in NOT_COMPARED_FLAGS:
                k = by_kind.setdefault(str(it.get("kind")), {})
                k[f] = k.get(f, 0) + 1
    return {"id": inp_id, "flags_by_kind": by_kind}


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tot: dict[str, int] = {}
    kinds: dict[str, dict[str, int]] = {}
    for r in rows:
        for kind, fl in r["flags_by_kind"].items():
            for f, n in fl.items():
                tot[f] = tot.get(f, 0) + n
                kinds.setdefault(kind, {})[f] = kinds.setdefault(kind, {}).get(f, 0) + n

    def rate(d: dict[str, int]) -> dict[str, Any]:
        return M.kn(d.get("API_SAME", 0), sum(d.get(f, 0) for f in MATCH_FLAGS))

    return {"flags": tot, "match_rate": rate(tot), "by_kind": {k: {"flags": v, "match_rate": rate(v)} for k, v in sorted(kinds.items())},
            "not_compared": {f: tot.get(f, 0) for f in NOT_COMPARED_FLAGS}}


def execute(inputs: Sequence[dict[str, Any]], ctx: Any, *, max_calls: int, counter: dict[str, int] | None = None) -> dict[str, Any]:
    """판정 도구를 API를 켠 컨텍스트로 직접 부른다(`ctx.api_*_fn`은 이미 상한이 씌워진 것). 오류는 문항별 예외 종류만 남긴다."""
    from app.agent.tools.check_contraindications import check_contraindications

    counter = counter if counter is not None else {"calls": 0, "refused": 0}
    rows = []
    for inp in inputs:
        try:
            rows.append(tally(inp["id"], check_contraindications(tool_args(inp), ctx)))
        except Exception as e:  # noqa: BLE001 - 문항 하나의 실패로 관찰을 멈추지 않는다(내용 없이 종류만)
            rows.append({"id": inp["id"], "flags_by_kind": {}, "error_type": type(e).__name__})
    return {"version": VERSION, "mode": "execute", "n_inputs": len(rows), "api_calls": counter["calls"], "api_calls_refused_by_cap": counter["refused"],
            "max_calls": max_calls, **summarize(rows), "items": rows,
            "note": "관찰값(9장 지표 아님). 일치율 = API_SAME / (API_SAME + FILE_ONLY + API_ONLY). 평가 지표 계산에 섞지 않는다"}


def _live_context(max_calls: int, counter: dict[str, int]) -> Any:  # pragma: no cover - 실호출 경로(승인 뒤에만)
    import psycopg

    from app.agent.graph.wiring import build_tool_context
    from app.config import reveal
    from app.main import load_settings
    from app.tools.drug_dict import DrugDict

    settings = load_settings()
    dsn = reveal(settings.supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True
        return conn

    ctx = build_tool_context(DrugDict.load(), settings=settings, api_enabled=True, conn_factory=conn_factory, paramstyle="format")
    ctx.api_pair_fn = capped(ctx.api_pair_fn, counter, max_calls)
    ctx.api_age_fn = capped(ctx.api_age_fn, counter, max_calls)
    ctx.api_pregnancy_fn = capped(ctx.api_pregnancy_fn, counter, max_calls)
    return ctx


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", type=Path, help="관찰 입력 JSONL(없으면 개발셋 금기 판정 35문항)")
    ap.add_argument("--execute", action="store_true", help="원격 DB 읽기 + DUR API 실호출(사용자 승인 뒤에만)")
    ap.add_argument("--yes", action="store_true", help="--execute 확인")
    ap.add_argument("--max-calls", type=int, default=0, help="--execute의 API 호출 수 상한(필수, dry-run의 예상 합계 이상 권장)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    inputs = load_inputs(a.input)
    if a.execute:
        if not a.yes or a.max_calls <= 0:
            print("--execute는 --yes와 --max-calls(0보다 큼)가 모두 있어야 한다. 실행하지 않았다")
            return 2
        counter = {"calls": 0, "refused": 0}
        res = execute(inputs, _live_context(a.max_calls, counter), max_calls=a.max_calls, counter=counter)
    else:
        from app.tools.drug_dict import DrugDict

        res = dry_run(inputs, DrugDict.load())
    from app.db import loaders

    res["created_utc"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    res["file_as_of"] = {"kids_pregnancy_age_dose": loaders.AS_OF_KIDS, "kids_contra_pair": loaders.AS_OF_COMBO}
    out = a.out or OUT_DIR / f"file-api-match-{res['mode']}-{res['created_utc'].replace(':', '').replace('-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if res["mode"] == "dry-run":
        print(f"[dry-run] 입력 {res['n_inputs']}개, 예상 API 호출 {res['planned_calls_total']}회 {res['planned_by_kind']}, "
              f"호출 없는 입력 {res['inputs_without_api_call']}개 → {out}")
    else:
        mr = res["match_rate"]
        print(f"[execute] 입력 {res['n_inputs']}개, API 호출 {res['api_calls']}회(상한 거절 {res['api_calls_refused_by_cap']}), "
              f"일치 {mr['k']}/{mr['n']} {mr['wilson95']} → {out}")
    return 0


if __name__ == "__main__":
    from app.security.redact import install_excepthook  # noqa: E402

    install_excepthook()
    raise SystemExit(main())
