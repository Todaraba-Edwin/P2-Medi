"""AG-11 평가 러너 골격: 평가 세트 읽기(시험셋 가드) → 에이전트 실행(어댑터) → 코드 채점 지표 → k/n·Wilson 95% → 결과 JSON.

- 지표 정의는 `P2-doc/PJ2-RFP.md` 9장 그대로다(`eval_metrics.py` 머리말). judge(Claude Sonnet 5.5, 루브릭 J1~J5)와 Ragas 3지표는
  **인터페이스만** 두고 호출하지 않는다(`NotCalledJudge`). judge 요소가 남은 문항의 안전 응답 통과는 "보류"로 집계된다.
- 에이전트는 어댑터로 주입한다. `GraphAdapter`는 컴파일된 LangGraph(AG-01)를 받아 최종 상태에서 실행 기록을 뽑는다(가짜 모델을 넣은
  그래프면 LLM 호출 0). CLI 기본 에이전트 `offline-fixed`는 도구·모델 없이 코드 고정 문구 답만 만드는 연결 확인용(채점 파이프라인 점검, 측정값 아님).
- 시험셋(`*.SEALED.jsonl`)은 `sealed_guard`로 막는다. 허용돼 돌렸더라도 결과 파일에는 **점수만** 남기고 문항별 기록·실패 문항 ID는 남기지 않는다(9.1절 8번).
- 결과 파일에는 세트 버전·파일 sha256(manifest와 대조)·조건·모델·프롬프트·그래프·하네스·사전 버전·judge 모델·루브릭 버전·패턴 버전을 적는다(9.6절 동결 확인).
- 이 모듈은 원격 DB·공공 API·LLM을 부르지 않는다(어댑터가 실제 모델을 넣었을 때만 그 모델이 호출된다).

사용(저장소 루트): `backend/.venv/bin/python evaluation/eval_runner.py --set dev --agent offline-fixed [--limit N] [--out PATH]`

L2(개발 골든 스모크, AG-06-06 A): `--agent graph --subset dev_golden --prompt-set prompt_set@vN [--allow-draft] --max-usd X`는 서비스와 같은 부품으로
실제 그래프를 만들어 돌린다(평가 모드: API 병기 끔, LLM 캐시 끔). **실제 모델을 부르고 원격 DB를 읽으므로 비용 상한이 필수다.** judge는 붙이지 않는다.
`--compare A.json B.json`은 두 결과를 나란히 보여 준다(회귀 경보 전용).
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
                       end_reason=state.get("end_reason"), tool_evidence_ids=ids, clarify_options=len(opts),
                       **source_missing_counts(state))  # 보조 집계(AG-06-07 A, 9장 지표 아님)


class ProfileFormatError(ValueError):
    """평가 세트 프로필을 그래프 프로필로 바꿀 수 없다(모르는 단위·키·값). 조용히 버리지 않고 실행을 멈춘다."""


_PROFILE_KEYS = frozenset({"age", "pregnant"})


def _age_years(age: Any) -> float | None:
    if age is None:
        return None
    if not isinstance(age, dict) or set(age) != {"value", "unit"}:
        raise ProfileFormatError(f"age 형식은 None 또는 {{value, unit}}이어야 한다: {type(age).__name__}")
    value, unit = age["value"], age["unit"]
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ProfileFormatError(f"age.value는 0 이상의 숫자여야 한다: {value!r}")
    if unit == "세":
        return float(value)
    if unit == "개월":
        return round(value / 12, 2)  # router `_AGE_MONTH_RE` 처리와 같은 규칙(개월/12, 소수 둘째 자리)
    raise ProfileFormatError(f"처리하지 못하는 age.unit: {unit!r}")


def to_graph_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """평가 세트 프로필 `{"age": None | {"value", "unit"}, "pregnant": bool | None}` → 그래프 `ProfileState` 입력
    `{"age_years", "pregnant"}`(값이 있는 키만). 둘 다 없으면 None. 모르는 키·단위·값은 `ProfileFormatError`."""
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ProfileFormatError(f"profile은 dict여야 한다: {type(profile).__name__}")
    extra = set(profile) - _PROFILE_KEYS
    if extra:
        raise ProfileFormatError(f"모르는 profile 키: {sorted(extra)}")
    pregnant = profile.get("pregnant")
    if pregnant is not None and not isinstance(pregnant, bool):
        raise ProfileFormatError(f"pregnant는 bool 또는 None이어야 한다: {pregnant!r}")
    out: dict[str, Any] = {}
    age = _age_years(profile.get("age"))
    if age is not None:
        out["age_years"] = age
    if pregnant is not None:
        out["pregnant"] = pregnant
    return out or None


class GraphAdapter:
    """컴파일된 AG-01 그래프를 평가 에이전트로 쓴다. `graph`에 가짜 모델을 넣었으면 LLM 호출 0이다.
    평가 모드(API Tool 끔)는 그래프를 만들 때 `wiring.build_tool_context(mode="eval")`로 정한다(9.4절, 이 어댑터는 그래프를 만들지 않는다)."""

    def __init__(self, graph: Any, *, info: dict[str, Any] | None = None) -> None:
        self.graph = graph
        self.info = {"agent": "graph", **(info or {})}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from app.agent.graph.build import run_question

        profile = to_graph_profile(item.get("profile"))  # 형식 오류는 에이전트 실패(경로 Fail)로 섞지 않고 실행을 멈춘다
        t0 = time.perf_counter()
        try:
            state = run_question(self.graph, item["question"], profile)
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
    budget: CostBudget | None = None,
    skip_judge: bool = False,
) -> dict[str, Any]:
    """`budget`을 주면 문항을 시작하기 전마다 누적 비용을 보고, 상한에 닿았으면 남은 문항을 건너뛴다(`skipped_cost_cap`).
    `skip_judge`면 judge 자리를 비운다(결과 `judge: null`). 둘 다 주지 않으면 예전 동작·결과 형식 그대로다."""
    ph = phrases or M.Phrases.from_backend()
    judge = judge or NotCalledJudge()
    runs: list[list[dict[str, Any]]] = []
    skipped: list[str] = []
    cost_by_item: dict[str, float] = {}
    for n_run in range(max(1, repeats)):
        rows = []
        for it in items:
            if budget is not None and budget.exhausted():
                if n_run == 0:
                    skipped.append(str(it.get("id")))
                continue
            rec = agent(it)
            row = M.score_item(it, rec, ph)
            row["judge"] = None if skip_judge else judge.score(it, rec.answer, [])  # 골격: 호출 없음(보류)
            if budget is not None:
                row["cost_usd"] = round(budget.item_cost(), 6)
                cost_by_item[str(it.get("id"))] = round(cost_by_item.get(str(it.get("id")), 0.0) + row["cost_usd"], 6)
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
    if skip_judge:
        result["meta"]["judge"] = None
        result["judge"] = None  # judge 프롬프트 확정·보정 전이라 이번 실행에는 붙이지 않는다(자리만 둔다)
    if budget is not None:
        result["meta"]["n_items_run"] = len(runs[0])
        result["cost_usd"] = {"total": round(budget.spent(), 6), "max_usd": budget.max_usd, "cap_reached": bool(skipped) or budget.exhausted(),
                              "skipped": len(skipped), "by_item": {} if sealed else cost_by_item}
        result["skipped_cost_cap"] = len(skipped) if sealed else skipped  # 시험셋은 문항 ID를 남기지 않는다
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


# --------------------------------------------------------------------------- L2 실행기: 실제 그래프·개발 골든·비용 상한(AG-06-06 A)

GRAPH_AGENT = "graph"
GRAPH_REQUIRED_ENV = ("OPENAI_API_KEY", "SUPABASE_DB_URL")  # 평가 모드는 API 병기를 끄므로 DUR 변수는 요구하지 않는다
SUBSETS = {"dev_golden": "dev_golden"}  # 고를 수 있는 표시 칸(개발셋 표시만. 시험셋 골든 표시는 고르지 않는다)
REASON_NO_EVIDENCE = "NO_EVIDENCE"        # `app.agent.sentence_filter.NO_EVIDENCE`(시험이 같은 값인지 확인한다)
REASON_QUOTE_MISMATCH = "QUOTE_MISMATCH"  # `app.agent.validator.QUOTE_MISMATCH`
COMPARE_CLAIM = "회귀 경보 전용(개선 주장에 쓰지 않는다)"


class RunnerConfigError(ValueError):
    """실행 전에 막는 설정 오류(묶음·부분집합·비용 상한·비교 대상)."""


class GraphResources:
    """그래프 에이전트가 쓰는 자원 묶음. `deps`는 그래프 의존성, `cost_total()`은 누적 비용(USD), `dict_meta`는 사전 버전·기준일."""

    def __init__(self, *, deps: Any, cost_total: Callable[[], float], dict_meta: dict[str, Any] | None = None) -> None:
        self.deps = deps
        self.cost_total = cost_total
        self.dict_meta = dict(dict_meta or {})


class CostBudget:
    """이번 실행의 비용 상한. 누적은 `total_fn()`(원장 등)에서 읽고, 시작 시점 값을 빼 이번 실행 몫만 센다."""

    def __init__(self, max_usd: float, total_fn: Callable[[], float]) -> None:
        if not max_usd or max_usd <= 0:
            raise RunnerConfigError("비용 상한(--max-usd)은 0보다 커야 한다")
        self.max_usd = float(max_usd)
        self._total = total_fn
        self._start = float(total_fn())
        self._mark = self._start

    def spent(self) -> float:
        return max(0.0, float(self._total()) - self._start)

    def exhausted(self) -> bool:
        """다음 문항을 시작하기 전에 본다. 누적이 상한에 닿았으면 True."""
        return self.spent() >= self.max_usd - 1e-12

    def item_cost(self) -> float:
        """직전 호출 뒤로 늘어난 비용(문항 하나 몫)."""
        now = float(self._total())
        cost, self._mark = max(0.0, now - self._mark), now
        return cost


def ledger_cost_total(ledger: Any) -> Callable[[], float]:
    """원장의 평가 몫 누적을 읽는 함수. 평가 모드(`MEDIAGENT_EVAL=1`) 호출은 eval 몫으로 쌓인다(`app.llm.cache`)."""
    return lambda: float(ledger.spent("eval"))


def select_subset(items: Sequence[dict[str, Any]], subset: str | None) -> list[dict[str, Any]]:
    if subset is None:
        return list(items)
    if subset not in SUBSETS:
        raise RunnerConfigError(f"--subset은 {sorted(SUBSETS)} 중 하나")
    return [it for it in items if it.get(SUBSETS[subset]) is True]


def _sha256_of(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def prompt_versions(prompt_set: str) -> dict[str, Any]:
    """묶음 이름과 파일별 `id@version`·상태·sha256(프롬프트 파일 내용 전체)."""
    from app.llm import prompts as lp

    ps = lp.load_prompt_set(lp.PROMPTS_DIR / f"{prompt_set}.yaml")
    files = []
    for ref, path in zip(ps.prompts, ps.files(lp.PROMPTS_DIR), strict=True):
        raw = path.read_bytes()
        fm, _ = lp.split_frontmatter(raw.decode("utf-8"))
        fm = fm or {}
        files.append({"ref": ref, "id": fm.get("id"), "version": fm.get("version"), "status": fm.get("status"),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    return {"set": ps.name, "files": files}


def check_system_prompt(prompt_set: str, prompt_name: str) -> None:
    """묶음이 가리키는 시스템 프롬프트와 그래프가 실제로 쓰는 것이 다르면 시작 전에 멈춘다(`build_deps`는 묶음에서 시스템 프롬프트를 고르지 않는다)."""
    from app.llm import prompts as lp

    ps = lp.load_prompt_set(lp.PROMPTS_DIR / f"{prompt_set}.yaml")
    base = prompt_name.split("@", 1)[0]
    ref = next((r for r in ps.prompts if r.split("@", 1)[0] == base), None)
    if ref != prompt_name:
        raise RunnerConfigError(f"묶음 {prompt_set}의 시스템 프롬프트({ref})와 그래프가 쓰는 프롬프트({prompt_name})가 다르다")


def code_versions() -> dict[str, str]:
    """그래프·하네스 소스 파일 내용 해시(버전 상수가 따로 없어 내용 해시로 적는다)."""
    agent = ROOT / "backend" / "app" / "agent"
    harness = [agent / f"{n}.py" for n in ("guardrail", "validator", "sentence_filter", "finalize", "fixed_phrases", "quote_check", "renderer")]
    return {"graph": f"graph-src@{_sha256_of(sorted((agent / 'graph').glob('*.py')))}",
            "harness": f"harness-src@{_sha256_of([p for p in harness if p.is_file()])}"}


def source_missing_counts(state: dict[str, Any]) -> dict[str, int]:
    """그래프 최종 상태에서 보조 집계 값을 센다(내용은 읽지 않고 사유 코드와 문장 종류만 본다)."""
    from app.agent.graph.trace import harness_events

    events = [e for e in state.get("events") or [] if isinstance(e, dict)]

    def reason_total(event: str, reason: str) -> int:
        return sum(int((e.get("reasons") or {}).get(reason) or 0) for e in events
                   if e.get("event") == event and isinstance(e.get("reasons"), dict))

    uncited = sum(1 for s in state.get("final_sentences") or []
                  if isinstance(s, dict) and s.get("claim_type") == "fact" and not s.get("evidence_ids"))
    return {"no_evidence_dropped": reason_total("SENTENCE_FILTER", REASON_NO_EVIDENCE), "uncited_fact_sentences": uncited,
            "quote_mismatch": reason_total("VALIDATOR", REASON_QUOTE_MISMATCH),
            "harness_blocks": sum(1 for h in harness_events(events) if h["action"] == "block")}


def make_tracer(*, prompt_set: str, run_id: str, condition: str | None = None, sink: Any = None) -> Any:
    """평가 실행용 계측기. `prompt_set`에 묶음 이름을 넣는다. `sink`가 없으면 평가 모드 기록기(`logs/eval/<run_id>/spans.jsonl`)를 쓴다."""
    from app.agent import llm
    from app.agent.graph.trace import GraphTracer
    from app.agent.graph.wiring import DEFAULT_PROMPT

    if sink is None:
        from app.logging import SpanLogger

        sink = SpanLogger(mode="eval", run_id=run_id)
    return GraphTracer(sink=sink, prompt_set=prompt_set, prompt_version=DEFAULT_PROMPT, model=llm.MODEL, api_enabled=False,
                       condition=condition, cost_fn=llm.estimate_cost_usd)


def default_graph_resources(settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> GraphResources:
    """실제 자원으로 평가 모드 그래프 의존성을 만든다(`app.api.service.default_resources`와 같은 부품, 단 API 병기 끔). 시험에서는 부르지 않는다.

    원격 DB(읽기 전용)에서 코퍼스를 읽고 모델 객체를 만든다. 모델 호출 비용은 원장의 평가 몫으로 쌓인다.
    """
    import psycopg  # 실제 연결을 여는 이 함수 안에서만 import한다
    from app.agent.grade_defs import corpus_grade_def_fn
    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.agent.tools.corpus import CorpusIndex
    from app.config import reveal
    from app.llm.ledger import CostLedger
    from app.tools.drug_dict import DrugDict

    dsn = reveal(settings.supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True
        return conn

    drug_dict = DrugDict.load()
    corpus = CorpusIndex.from_db(conn_factory)
    ctx = build_tool_context(drug_dict, settings=settings, mode="eval", conn_factory=conn_factory, paramstyle="format", corpus=corpus,
                             vector_search_fn=None, label_provider=None)
    ledger = CostLedger()
    deps = build_deps(drug_dict, ctx, settings=settings, tracer=make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2"), ledger=ledger,
                      grade_def_fn=corpus_grade_def_fn(corpus), prompt_set=prompt_set, allow_draft=allow_draft)
    return GraphResources(deps=deps, cost_total=ledger_cost_total(ledger),
                          dict_meta={"version": drug_dict.version, "built_at": drug_dict.meta.get("built_at")})


class GraphAgent(GraphAdapter):
    """자원으로 그래프를 만들어 돌리는 에이전트. 문항 ID를 계측기에 알린다(질문 원문은 넘기지 않는다)."""

    def __init__(self, resources: GraphResources, *, info: dict[str, Any] | None = None) -> None:
        from app.agent.graph.build import build_graph

        super().__init__(build_graph(resources.deps), info=info)
        self.resources = resources

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        tracer = getattr(self.resources.deps, "tracer", None)
        if tracer is not None:
            tracer.item_id = str(item.get("id")) if item.get("id") is not None else None
        return super().__call__(item)


def _default_settings() -> Any:
    from app.main import load_settings

    return load_settings()


# --------------------------------------------------------------------------- 두 결과 비교(회귀 경보 전용)

def _side(res: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    items = res.get("items")
    if not isinstance(items, list):
        raise RunnerConfigError("문항별 기록이 없는 결과(시험셋 결과)는 비교하지 않는다")
    meta = res.get("meta") or {}
    aux = (res.get("metrics") or {}).get("aux_source_missing") or M.aux_summary(items) or {}
    cost = res.get("cost_usd") or {}
    n = len(items)
    passed = sum(1 for r in items if (r.get("trajectory") or {}).get("verdict") == "Pass")
    not_fail = sum(1 for r in items if (r.get("trajectory") or {}).get("verdict") in ("Pass", "Warn"))
    side = {
        "label": ((meta.get("versions") or {}).get("prompt") or {}).get("set") or meta.get("agent") or "?",
        "n_items": n, "trajectory_pass": M.kn(passed, n), "trajectory_pass_or_warn": M.kn(not_fail, n),
        "harness_blocks": aux.get("harness_blocks_total"), "no_evidence_dropped": aux.get("no_evidence_dropped_total"),
        "uncited_fact_sentences": aux.get("uncited_fact_sentences_total"), "quote_mismatch": aux.get("quote_mismatch_total"),
        "source_missing_zero_items": aux.get("source_missing_zero_items"),
        "cost_usd": cost.get("total"), "skipped_cost_cap": len(res.get("skipped_cost_cap") or []),
    }
    return side, {str(r.get("id")): r for r in items}


def _item_sig(row: dict[str, Any]) -> tuple[Any, ...]:
    t = row.get("trajectory") or {}
    a = row.get("aux") or {}
    return (t.get("verdict"), t.get("end_reason"), tuple(a.get(k) for k in M.AUX_FIELDS))


def compare_results(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """두 결과(예: 묶음 v2 대 v3)를 나란히 놓는다. 문항 차이는 ID만 낸다. 소표본이라 **회귀 경보로만** 읽는다(9.1절)."""
    sa, ia = _side(a)
    sb, ib = _side(b)
    both = sorted(set(ia) & set(ib))
    return {"claim": COMPARE_CLAIM, "sides": [sa, sb], "n_common": len(both),
            "diff_ids": [i for i in both if _item_sig(ia[i]) != _item_sig(ib[i])],
            "only_in_one": sorted(set(ia) ^ set(ib))}


def format_compare(cmp: dict[str, Any]) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, dict) and "k" in v:
            return f"{v['k']}/{v['n']} {v['wilson95']} ({v['claim']})"
        if isinstance(v, float):
            return f"{v:.4f}"
        return "-" if v is None else str(v)

    rows = [("묶음", "label"), ("문항 수", "n_items"), ("경로 Pass", "trajectory_pass"), ("경로 Pass+Warn", "trajectory_pass_or_warn"),
            ("하네스 차단 수", "harness_blocks"), ("근거 없음으로 걸러진 문장", "no_evidence_dropped"),
            ("남은 빈 근거 사실 문장", "uncited_fact_sentences"), ("인용 불일치", "quote_mismatch"),
            ("출처 누락 0건 문항", "source_missing_zero_items"), ("비용 USD", "cost_usd"), ("상한으로 건너뛴 문항", "skipped_cost_cap")]
    a, b = cmp["sides"]
    lines = [f"[{cmp['claim']}] 소표본이므로 차이가 보여도 다시 볼 문항을 고르는 데만 쓴다"]
    lines += [f"  {name}: {cell(a.get(key))} | {cell(b.get(key))}" for name, key in rows]
    lines.append(f"  공통 문항 {cmp['n_common']}개 중 결과가 다른 문항(ID): {', '.join(cmp['diff_ids']) or '없음'}")
    if cmp["only_in_one"]:
        lines.append(f"  한쪽에만 있는 문항(ID): {', '.join(cmp['only_in_one'])}")
    return "\n".join(lines)


AGENTS: dict[str, Callable[[], Any]] = {"offline-fixed": OfflineFixedAgent}


def _run_graph_cli(a: argparse.Namespace, items: list[dict[str, Any]], *, settings_fn: Callable[[], Any] | None,
                   resources_factory: Callable[..., GraphResources] | None) -> tuple[Any, CostBudget, dict[str, Any]] | None:
    """그래프 에이전트 준비. 필수 설정이 없으면 이름만 출력하고 None(0건). 자원을 만들기 전에 묶음·draft 규칙을 확인한다."""
    from app.agent import llm
    from app.agent.graph.prompt import load_summary_instruction
    from app.agent.graph.wiring import DEFAULT_PROMPT
    from app.api.service import missing_settings

    os.environ["MEDIAGENT_EVAL"] = "1"  # 평가 모드 강제: LLM 캐시 off, 비용은 원장의 평가 몫으로
    settings = (settings_fn or _default_settings)()
    missing = [n for n in missing_settings(settings) if n in GRAPH_REQUIRED_ENV]
    if missing:
        print(f"필수 환경변수가 없어 실행하지 않았다(0건): {', '.join(missing)}")
        return None
    check_system_prompt(a.prompt_set, DEFAULT_PROMPT)
    load_summary_instruction(a.prompt_set, allow_draft=a.allow_draft)  # draft 묶음은 --allow-draft 없이는 여기서 멈춘다
    run_id = f"l2-{a.prompt_set.replace('@', '-')}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    resources = (resources_factory or default_graph_resources)(settings, prompt_set=a.prompt_set, allow_draft=a.allow_draft, run_id=run_id)
    agent = GraphAgent(resources, info={"prompt_set": a.prompt_set, "run_id": run_id, "api_enabled": False})
    versions = {"model": {"agent": llm.MODEL, "summary": llm.MODEL}, "prompt": prompt_versions(a.prompt_set), **code_versions(),
                "dict": resources.dict_meta}
    del items
    return agent, CostBudget(a.max_usd, resources.cost_total), versions


def main(argv: Sequence[str] | None = None, *, settings_fn: Callable[[], Any] | None = None,
         resources_factory: Callable[..., GraphResources] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", default="dev", help="dev | test | 파일 경로")
    ap.add_argument("--agent", choices=sorted([*AGENTS, GRAPH_AGENT]), default="offline-fixed")
    ap.add_argument("--condition", default="C2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--allow-sealed", action="store_true", help=f"시험셋 열람 허용(환경변수 {G.SEALED_ENV}도 필요)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--subset", choices=sorted(SUBSETS), help="표시 행만 고른다(dev_golden = 개발 골든)")
    ap.add_argument("--prompt-set", default="prompt_set@v2", help="graph 에이전트의 프롬프트 묶음")
    ap.add_argument("--allow-draft", action="store_true", help="draft 프롬프트가 든 묶음 허용(검토 중인 초안 점검용)")
    ap.add_argument("--max-usd", type=float, help="graph 에이전트 비용 상한(필수). 닿으면 남은 문항을 건너뛴다")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A.json", "B.json"), help="두 결과 파일을 나란히 본다(실행 없음)")
    a = ap.parse_args(argv)
    if a.compare:
        print(format_compare(compare_results(*(json.loads(p.read_text(encoding="utf-8")) for p in a.compare))))
        return 0
    is_graph = a.agent == GRAPH_AGENT
    if is_graph and not (a.max_usd and a.max_usd > 0):
        print("graph 에이전트는 --max-usd(0보다 큰 비용 상한)가 있어야 시작한다")
        return 2
    path = SET_FILES.get(a.set, Path(a.set))
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)  # 시험셋이면 여기서 막힌다(파일을 열기 전)
    digest = sha256_file(path, allow_sealed=a.allow_sealed)
    items = select_subset(G.load_jsonl(path, allow_sealed=a.allow_sealed), a.subset)
    if a.limit:
        items = items[: a.limit]
    versions: dict[str, Any] = {"model": None, "prompt": None, "graph": None, "harness": None, "dict": None}  # 실제 그래프 측정 때 채운다
    budget: CostBudget | None = None
    if is_graph:
        prepared = _run_graph_cli(a, items, settings_fn=settings_fn, resources_factory=resources_factory)
        if prepared is None:
            return 0
        agent, budget, versions = prepared
    else:
        agent = AGENTS[a.agent]()
    meta = {"set": a.set if a.set in SET_FILES else path.name, "set_file": path.name, "set_sha256": digest, **manifest_check(path, digest),
            "set_version": items[0].get("set_version") if items else None, "n_items_run": len(items), "condition": a.condition,
            "agent": a.agent, "agent_info": getattr(agent, "info", {}), "versions": versions}
    if is_graph:
        meta.update({"subset": a.subset, "n_items_selected": len(items), "prompt_set": a.prompt_set})
    res = run_eval(items, agent, sealed=sealed, meta=meta, repeats=a.repeats, budget=budget, skip_judge=is_graph)
    out = save(res, a.out)
    mt = res["metrics"]
    print(f"[{a.set}·{a.condition}·{a.agent}] 문항 {res['meta']['n_items_run']} → {out}")
    for name in ("contra_judgment_accuracy", "routing_accuracy"):
        v = mt[name]
        print(f"  {name}: {v['k']}/{v['n']} {v['wilson95']} ({v['claim']})")
    s = mt["safety_response_rate"]
    print(f"  safety code_part: {s['code_part']['k']}/{s['code_part']['n']}, judge 보류 {s['pending_judge_items']}문항")
    print(f"  trajectory: {mt['trajectory']['verdicts']}")
    if budget is not None:
        c = res["cost_usd"]
        print(f"  cost: ${c['total']:.4f} / 상한 ${c['max_usd']}, 상한으로 건너뛴 문항 {c['skipped']}")
        aux = mt.get("aux_source_missing")
        if aux:
            z = aux["source_missing_zero_items"]
            print(f"  보조(출처 누락 0건 문항): {z['k']}/{z['n']}, 인용 불일치 {aux['quote_mismatch_total']}, 하네스 차단 {aux['harness_blocks_total']}")
    return 0


if __name__ == "__main__":
    # S-05: 직접 실행할 때만 처리되지 않은 예외·logging 출력에서 키·DSN을 가린다(import만 할 때는 설치하지 않음)
    from app.security.redact import install_excepthook  # noqa: E402, PLC0415
    install_excepthook()
    raise SystemExit(main())
