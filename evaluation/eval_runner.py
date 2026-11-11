"""AG-11 평가 러너 골격: 평가 세트 읽기(시험셋 가드) → 에이전트 실행(어댑터) → 코드 채점 지표 → k/n·Wilson 95% → 결과 JSON.

- 지표 정의는 `P2-doc/PJ2-RFP.md` 9장 그대로다(`eval_metrics.py` 머리말). judge(Claude Sonnet 5.5, 루브릭 J1~J5)와 Ragas 3지표는
  **인터페이스만** 두고 호출하지 않는다(`NotCalledJudge`). judge 요소가 남은 문항의 안전 응답 통과는 "보류"로 집계된다.
- 에이전트는 어댑터로 주입한다. `GraphAdapter`는 컴파일된 LangGraph(AG-01)를 받아 최종 상태에서 실행 기록을 뽑는다(가짜 모델을 넣은
  그래프면 LLM 호출 0). CLI 기본 에이전트 `offline-fixed`는 도구·모델 없이 코드 고정 문구 답만 만드는 연결 확인용(채점 파이프라인 점검, 측정값 아님).
- 시험셋(`*.SEALED.jsonl`)은 `sealed_guard`로 막는다. 허용돼 돌렸더라도 결과 파일에는 **점수만** 남기고 문항별 기록·실패 문항 ID는 남기지 않는다(9.1절 8번).
- 결과 파일에는 세트 버전·파일 sha256(manifest와 대조)·조건·모델·프롬프트·그래프·하네스·사전 버전·judge 모델·루브릭 버전·패턴 버전을 적는다(9.6절 동결 확인).
- 이 모듈은 원격 DB·공공 API·LLM을 부르지 않는다(어댑터가 실제 모델을 넣었을 때만 그 모델이 호출된다).

사용(저장소 루트): `backend/.venv/bin/python evaluation/eval_runner.py --set dev --agent offline-fixed [--limit N] [--out PATH]`
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_metrics as M  # noqa: E402
import sealed_guard as G  # noqa: E402

EVAL_SET_DIR = HERE / "eval_set"
MANIFEST = EVAL_SET_DIR / "manifest.json"
SET_FILES = {"dev": EVAL_SET_DIR / "dev_set.jsonl", "test": EVAL_SET_DIR / "test_set.SEALED.jsonl"}
OUT_DIR = ROOT / "logs" / "eval"  # 로컬 전용(`logs/`는 .gitignore)
RUNNER_VERSION = "ag11-runner@v0-skeleton"

JUDGE_MODEL = "claude-sonnet-5-5"  # RFP-26-01 고정. 이 골격은 호출하지 않는다
RUBRIC_VERSIONS = {"J1": "J1@v1", "J2": "J2@v1", "J3": "J3@v1", "J4": "J4@v1", "J5": "J5@v1"}


# --------------------------------------------------------------------------- judge 인터페이스(호출 안 함)

class Judge(Protocol):
    model_id: str
    rubric_versions: dict[str, str]

    def score(self, item: dict[str, Any], answer: dict[str, Any], contexts: Sequence[str]) -> dict[str, Any]:
        """루브릭 J1~J5 채점. 반환: {"rubric": "J3@v1", "items": {R1: {pass, reason, evidence}}, "overall_pass": bool} (RFP-26 §7.5)."""
        ...


class NotCalledJudge:
    """judge 자리 표시. 어떤 호출도 하지 않고 `None`(보류)을 돌려준다."""

    model_id = JUDGE_MODEL
    rubric_versions = RUBRIC_VERSIONS
    called = 0

    def score(self, item: dict[str, Any], answer: dict[str, Any], contexts: Sequence[str]) -> dict[str, Any]:  # noqa: ARG002
        return {"rubric": None, "items": {}, "overall_pass": None, "status": "not_called"}


class SonnetJudge:
    """실제 judge 자리(AG-11에서 구현). 이 골격에서는 만들기만 해도 막는다: 호출 경로가 실수로 열리지 않게."""

    model_id = JUDGE_MODEL
    rubric_versions = RUBRIC_VERSIONS

    def __init__(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError("judge 호출은 AG-11 본 구현에서 연다(이 골격은 호출 0, 비용 상한 지시서 필요)")

    def score(self, item: dict[str, Any], answer: dict[str, Any], contexts: Sequence[str]) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- 에이전트 어댑터

Agent = Callable[[dict[str, Any]], M.RunRecord]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def extract_trace(state: dict[str, Any]) -> M.RunRecord:
    """그래프 최종 상태 → 실행 기록. 도구 호출은 모델 메시지의 `tool_calls`, 근거 ID는 도구 결과(`evidence`·`known_ids`)에서."""
    calls: list[M.ToolCall] = []
    for msg in state.get("messages") or []:
        for tc in _get(msg, "tool_calls") or []:
            calls.append(M.ToolCall(str(_get(tc, "name", "")), dict(_get(tc, "args") or {})))
    ids: set[str] = set(state.get("known_ids") or ())
    for it in state.get("evidence") or []:
        if isinstance(it, dict):
            if it.get("evidence_id"):
                ids.add(str(it["evidence_id"]))
            for m in it.get("matches") or []:
                if isinstance(m, dict) and m.get("row_evidence_id"):
                    ids.add(str(m["row_evidence_id"]))
    clar = state.get("clarify") or {}
    opts = _get(clar, "options") or _get(clar, "candidates") or []
    return M.RunRecord(answer=dict(state.get("answer") or {}), tool_calls=calls, model_calls=int(state.get("call_count") or 0),
                       end_reason=state.get("end_reason"), tool_evidence_ids=ids, clarify_options=len(opts))


class GraphAdapter:
    """컴파일된 AG-01 그래프를 평가 에이전트로 쓴다. `graph`에 가짜 모델을 넣었으면 LLM 호출 0이다.
    평가 모드(API Tool 끔)는 그래프를 만들 때 `wiring.build_tool_context(mode="eval")`로 정한다(9.4절, 이 어댑터는 그래프를 만들지 않는다)."""

    def __init__(self, graph: Any, *, info: dict[str, Any] | None = None) -> None:
        self.graph = graph
        self.info = {"agent": "graph", **(info or {})}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from app.agent.graph.build import run_question

        t0 = time.perf_counter()
        try:
            state = run_question(self.graph, item["question"], item.get("profile") or None)
            rec = extract_trace(state)
        except Exception as e:  # noqa: BLE001 - 문항 하나의 실패가 전체 실행을 멈추지 않게(오류는 경로 Fail로 집계)
            rec = M.RunRecord(answer={}, error=type(e).__name__)
        rec.latency_s = round(time.perf_counter() - t0, 4)
        return rec


class OfflineFixedAgent:
    """연결 확인용: 도구·모델 없이 백엔드 `finalize`로 고정 문구 답만 만든다(응급 키워드면 119). 측정값으로 쓰지 않는다."""

    info = {"agent": "offline-fixed", "note": "채점 파이프라인 연결 확인용, 측정값 아님"}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from app.agent.finalize import finalize
        from app.agent.guardrail import detect_emergency

        return M.RunRecord(answer=finalize([], emergency=detect_emergency(item.get("question") or "")), end_reason="NORMAL")


# --------------------------------------------------------------------------- 실행

def sha256_file(path: Path, *, allow_sealed: bool = False) -> str:
    return hashlib.sha256(G.read_bytes(path, allow_sealed=allow_sealed)).hexdigest()


def manifest_check(path: Path, digest: str) -> dict[str, Any]:
    """평가 세트 파일 해시가 manifest와 같은가(측정 기간 동결, 9.6절). manifest 자체는 시험셋 문항을 담지 않는다."""
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"manifest": None, "match": None}
    want = next((v.get("sha256") for v in (man.get("sets") or {}).values() if v.get("file") == path.name), None)
    return {"manifest_set_version": man.get("set_version"), "manifest_sha256": want, "match": (want == digest) if want else None}


def run_eval(
    items: Sequence[dict[str, Any]],
    agent: Agent,
    *,
    sealed: bool,
    meta: dict[str, Any] | None = None,
    judge: Any = None,
    phrases: M.Phrases | None = None,
    repeats: int = 1,
) -> dict[str, Any]:
    ph = phrases or M.Phrases.from_backend()
    judge = judge or NotCalledJudge()
    runs: list[list[dict[str, Any]]] = []
    for _ in range(max(1, repeats)):
        rows = []
        for it in items:
            rec = agent(it)
            row = M.score_item(it, rec, ph)
            row["judge"] = judge.score(it, rec.answer, [])  # 골격: 호출 없음(보류)
            if not sealed:
                row["run"] = rec.to_json()
            rows.append(row)
        runs.append(rows)
    result: dict[str, Any] = {
        "meta": {
            "runner": RUNNER_VERSION, "created_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sealed": sealed, "repeats": max(1, repeats), "eval_mode_env": os.environ.get("MEDIAGENT_EVAL") or os.environ.get("MEDIAGENT_MODE"),
            "judge": {"model": getattr(judge, "model_id", None), "rubrics": getattr(judge, "rubric_versions", None),
                      "status": "not_called" if isinstance(judge, NotCalledJudge) else "called"},
            "patterns": M.PATTERN_VERSION, **(meta or {}),
        },
        "metrics": M.aggregate(runs[0]),
    }
    if len(runs) > 1:
        rel = M.reliability(runs)
        if sealed:
            rel.pop("unstable_items", None)  # 시험셋은 실패 문항을 남기지 않는다
        result["reliability"] = rel
    if sealed:
        result["metrics"]["trajectory"].pop("top_fail_kinds", None)
        result["items"] = "omitted: sealed set (scores only, RFP-26-04)"
    else:
        result["items"] = runs[0]
    return result


def save(result: dict[str, Any], out: Path | None = None) -> Path:
    m = result["meta"]
    stamp = m["created_utc"].replace(":", "").replace("-", "")
    path = out or OUT_DIR / f"{m.get('set', 'set')}-{m.get('condition', 'C?')}-{m.get('agent', 'agent')}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return path


AGENTS: dict[str, Callable[[], Any]] = {"offline-fixed": OfflineFixedAgent}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", default="dev", help="dev | test | 파일 경로")
    ap.add_argument("--agent", choices=sorted(AGENTS), default="offline-fixed")
    ap.add_argument("--condition", default="C2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--allow-sealed", action="store_true", help=f"시험셋 열람 허용(환경변수 {G.SEALED_ENV}도 필요)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    path = SET_FILES.get(a.set, Path(a.set))
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)  # 시험셋이면 여기서 막힌다(파일을 열기 전)
    digest = sha256_file(path, allow_sealed=a.allow_sealed)
    items = G.load_jsonl(path, allow_sealed=a.allow_sealed)
    if a.limit:
        items = items[: a.limit]
    agent = AGENTS[a.agent]()
    meta = {"set": a.set if a.set in SET_FILES else path.name, "set_file": path.name, "set_sha256": digest, **manifest_check(path, digest),
            "set_version": items[0].get("set_version") if items else None, "n_items_run": len(items), "condition": a.condition,
            "agent": a.agent, "agent_info": getattr(agent, "info", {}),
            "versions": {"model": None, "prompt": None, "graph": None, "harness": None, "dict": None}}  # 실제 그래프 측정 때 어댑터가 채운다
    res = run_eval(items, agent, sealed=sealed, meta=meta, repeats=a.repeats)
    out = save(res, a.out)
    mt = res["metrics"]
    print(f"[{a.set}·{a.condition}·{a.agent}] 문항 {len(items)} → {out}")
    for name in ("contra_judgment_accuracy", "routing_accuracy"):
        v = mt[name]
        print(f"  {name}: {v['k']}/{v['n']} {v['wilson95']} ({v['claim']})")
    s = mt["safety_response_rate"]
    print(f"  safety code_part: {s['code_part']['k']}/{s['code_part']['n']}, judge 보류 {s['pending_judge_items']}문항")
    print(f"  trajectory: {mt['trajectory']['verdicts']}")
    return 0


if __name__ == "__main__":
    # S-05: 직접 실행할 때만 처리되지 않은 예외·logging 출력에서 키·DSN을 가린다(import만 할 때는 설치하지 않음)
    from app.security.redact import install_excepthook  # noqa: E402, PLC0415
    install_excepthook()
    raise SystemExit(main())
