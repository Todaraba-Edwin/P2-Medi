"""평가 실행 색인(BE-08-05 A, 2026-11-18): 러너가 끝날 때 `logs/eval/registry.jsonl`에 실행 한 줄을 더한다. 모델·네트워크 호출 0.

한 줄 = 한 실행: run_id·상태·조건·세트·커밋(`git_commit`·`git_dirty`)·동결 해시 요약·비용(에이전트·judge)·결과 경로·trace 경로·집계 지표.
결과 파일을 여럿 열지 않고도 "언제 무엇으로 몇 번 돌렸고 얼마 들었나"를 이 파일 하나로 찾게 한다(병목 점검 B-1).

- **시험셋은 집계 키만**: 문항 ID·문항 원문·실패 문항 목록·중단 위치의 문항 ID를 담지 않는다. 지표도 k/n·구간 같은 집계 값만 옮긴다(9.1절 8번, RFP-26-04).
  개발셋도 같은 모양이다(문항별 정보는 결과 파일에 있다).
- 색인은 결과 파일을 고치지 않는다(덧붙이기만, 줄 단위 JSON). `logs/`는 로컬 전용이다.
- 동결 해시 요약 `freeze.sha256`은 `freeze_check.freeze_values`(동결 항목 값 전체)의 sha256 앞 16자다. 같은 값이면 같은 동결 조건으로 잰 것이다
  (조건이 정하는 항목도 들어 있어 조건이 다르면 값이 다르다. 조건을 뺀 비교는 `freeze_check --same`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REGISTRY_VERSION = "eval-registry@v1"
REGISTRY_PATH = ROOT / "logs" / "eval" / "registry.jsonl"
STATUS_OK, STATUS_PARTIAL, STATUS_STOPPED, STATUS_ERROR = "ok", "partial", "stopped", "error"
# 색인에 옮기는 집계 지표(k/n·구간만). 값 모양이 {k, n, rate, wilson95, claim}인 것만 옮긴다
METRIC_KEYS = ("contra_judgment_accuracy", "routing_accuracy")


def git_state(root: Path = ROOT) -> dict[str, Any]:
    """지금 작업 트리의 커밋과 추적 파일 변경 여부(BE-08-06 A). 로컬 git 명령만 쓴다. git이 없거나 실패하면 None."""
    def run(*args: str) -> str | None:
        try:
            p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False)  # noqa: S603, S607
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout if p.returncode == 0 else None

    head = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")
    return {"git_commit": head.strip() if head else None, "git_dirty": (bool(status.strip()) if status is not None else None)}


def freeze_digest(result: Mapping[str, Any]) -> dict[str, Any]:
    """동결 값 요약: 전체 해시와 사람이 볼 대표 값(세트 해시 앞 12자·모델·judge·채점 코드 해시)."""
    import freeze_check as FZ

    fv = FZ.freeze_values(dict(result))
    full = hashlib.sha256(json.dumps(fv, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    s = fv.get("set_sha256")
    jp = fv.get("judge_prompt_sha256")
    return {"sha256": full[:16], "set_sha256": s[:12] if isinstance(s, str) else None, "model": fv.get("model"),
            "dict_version": fv.get("dict_version"), "metrics_src": fv.get("metrics_src"), "judge_model": fv.get("judge_model"),
            "judge_prompt_sha256": jp[:12] if isinstance(jp, str) else None}


def _kn(v: Any) -> dict[str, Any] | None:
    if isinstance(v, Mapping) and "k" in v and "n" in v:
        return {k: v.get(k) for k in ("k", "n", "rate", "wilson95") if k in v}
    return None


def metric_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """집계 지표만(k/n·구간). 문항 단위 정보는 넣지 않는다."""
    mt = result.get("metrics") or {}
    out: dict[str, Any] = {k: _kn(mt.get(k)) for k in METRIC_KEYS if k in mt}
    s = mt.get("safety_response_rate") or {}
    for k in ("code_part", "final", "final_excl_j5"):
        if _kn(s.get(k)):
            out[f"safety_{k}"] = _kn(s.get(k))
    t = mt.get("trajectory") or {}
    if isinstance(t.get("verdicts"), Mapping):
        out["trajectory_verdicts"] = dict(t["verdicts"])
    rel = result.get("reliability") or {}
    for k in ("pass^k", "pass@k", "pass^k_excl_j5", "judgment_agreement"):
        if _kn(rel.get(k)):
            out[f"reliability_{k}"] = _kn(rel.get(k))
    return out


def run_status(result: Mapping[str, Any]) -> str:
    if result.get("stopped"):
        return STATUS_STOPPED
    cost = result.get("cost_usd") or {}
    ju = result.get("judge_usage") or {}
    if cost.get("cap_reached") or ju.get("cap_reached"):
        return STATUS_PARTIAL
    return STATUS_OK


def _rel(p: Path | None) -> str | None:
    if p is None:
        return None
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def trace_path(run_id: str | None, root: Path = ROOT) -> Path | None:
    """평가 모드 span 기록(`app.logging.SpanLogger`: `logs/eval/<run_id>/spans.jsonl`)이 있으면 그 경로."""
    if not run_id:
        return None
    p = root / "logs" / "eval" / str(run_id) / "spans.jsonl"
    return p if p.is_file() else None


def build_entry(result: Mapping[str, Any], *, result_path: Path | None, status: str | None = None, git: Mapping[str, Any] | None = None,
                error: str | None = None, root: Path = ROOT) -> dict[str, Any]:
    """결과 하나 → 색인 한 줄. 시험셋이어도 같은 함수다(넣는 값이 모두 집계·버전 값이다)."""
    m = result.get("meta") or {}
    info = m.get("agent_info") or {}
    run_id = info.get("run_id") or (Path(result_path).stem if result_path else None)
    cost = result.get("cost_usd") or {}
    ju = result.get("judge_usage") or {}
    g = dict(git) if git is not None else {"git_commit": m.get("git_commit"), "git_dirty": m.get("git_dirty")}
    stop = result.get("stopped") or {}
    entry: dict[str, Any] = {
        "registry": REGISTRY_VERSION, "logged_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": run_id,
        "status": status or run_status(result), "created_utc": m.get("created_utc"), "set": m.get("set"), "sealed": bool(m.get("sealed")),
        "subset": m.get("subset"), "condition": m.get("condition"), "agent": m.get("agent"), "repeats": m.get("repeats"),
        "n_items_run": m.get("n_items_run"), "git_commit": g.get("git_commit"), "git_dirty": g.get("git_dirty"),
        "freeze": freeze_digest(result),
        "cost_usd": {"agent": cost.get("total"), "agent_max": cost.get("max_usd"), "judge": ju.get("cost_usd"), "judge_max": ju.get("max_usd")},
        "judge_transport": (ju.get("transport") or None) if ju else None,
        "result": _rel(result_path), "trace": _rel(trace_path(run_id, root)), "metrics": metric_summary(result),
    }
    if stop:
        entry["stopped"] = {"reason": stop.get("reason"), "run": stop.get("run")}  # 문항 ID·위치는 넣지 않는다
    if error:
        entry["error"] = error[:200]
    return entry


def append(entry: Mapping[str, Any], path: Path = REGISTRY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return path


def read(path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
