"""AG-24 시나리오 D·AG-13 서버 후보 소액 실제 모델 측정 도구(2026-11-24, 이번 실행 상한 0.45 USD, 사용자 승인).

보조 문항 `eval_set/dev_aux_w32.jsonl`(16문항, AG-13 서버 후보)·`eval_set/dev_aux_ag24d.jsonl`(74문항, 시나리오 D) 중 **모델 경로에 도달하는 문항만**
개발 경로(`build_deps(service=False)`, 모델 `gpt-6-luna`, 개발 원장 `dev` 구분)로 실제 그래프를 1회씩 돌린다.
입구 규칙·Router 되묻기에서 끝나는 문항, 출구 Sensor 문장 문항은 모델을 부르지 않고(비용 0) 입구 결과만 기록한다.

- **기본은 `--dry-run`**: 호출 0. 어떤 문항이 모델 경로에 가는지, 문항 수, 문항별·합계 최악 비용 추정, 원장 상태를 출력한다. `--yes`가 있어야만 실제 호출한다.
- 비용 통제(어기면 중단): 문항 시작 전 `이번 실행 누적 + 문항 최악 비용 > 상한(0.45)`이면 호출하지 않고 중단해 남은 문항을 미실행으로 기록한다.
  호출 중에도 `RunBudgetLedger`가 호출 직전(`guard`)에 상한을 확인한다. 개발 원장 누적+상한이 개발 한도를 넘길 것 같으면 시작 전에 중단한다.
  단가는 `app.agent.llm`의 상수(`PRICE_IN`·`PRICE_CACHED`·`PRICE_OUT`·`MAX_COMPLETION_TOKENS`), 호출 수 상한은 `app.agent.graph.state.MAX_MODEL_CALLS`다. 없으면 중단한다.
  실패·예외는 문항별로 기록하고 계속하며 같은 문항을 다시 시도하지 않는다.
- 스위치 비교: 모두 켬은 실제 1회, 모두 끔은 오프라인(가짜 모델)으로 경로만 기록한다(되묻기에서 끝나면 비용 0, 모델 경로면 "실호출 안 함"으로 표시).
- 결과: `data/mock/ag-smoke/{날짜}-ag-smoke-real.jsonl`(질문·응답 본문 포함, 로컬 전용)과 요약 md(`data/mock/briefs/reports/ag-smoke-real.md`, 본문 없이 ID·건수만).
- **평가 러너·지표·judge·`manifest.json`·시험셋은 건드리지 않는다.** 채점은 `dev_aux_w32.py`·`dev_aux_ag24d.py`의 기존 함수를 재사용한다. 키 값은 출력·기록하지 않는다.

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python evaluation/ag_smoke_real.py                # 기본 --dry-run(호출 0)
    backend/.venv/bin/python evaluation/ag_smoke_real.py --yes          # 실제 호출(원격 DB는 읽기 전용 연결)
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
import threading
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT / "backend"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dev_aux_ag24d as AG  # noqa: E402
import dev_aux_w32 as W  # noqa: E402

SCHEMA = "ag-smoke-real@v1"
RUN_CAP_USD = 0.45                 # 이번 실행 상한(사용자 승인 2026-11-24, AG-24 배분 0.5 USD 안)
EVIDENCE_TOKEN_ALLOWANCE = 12000   # 가정: 도구 결과·이전 대화가 입력에 더하는 토큰 상한(호출당). 단가가 아니라 최악 추정용 가정이다
CHARS_TO_TOKENS = 1.25             # 가정: 고정 프롬프트는 글자 수 x 1.25를 토큰 수로 본다(한글 최악 쪽 여유)
OUT_DIR = ROOT / "data" / "mock" / "ag-smoke"
REPORT_MD = ROOT / "data" / "mock" / "briefs" / "reports" / "ag-smoke-real.md"
ALL_OFF: dict[str, bool] = {**W.ALL_OFF, **AG.ALL_OFF}  # 스위치 12개 모두 끔 = 이 후보들이 없던 때의 동작

PATH_MODEL, PATH_EARLY, PATH_SENSOR = "model", "early", "sensor_only"
SAFE_ASSERTION = "SAFE_ASSERTION"  # 이 스크립트의 추가 점검: "안전하다" 단정(기존 Sensor에 없는 코드)


class PriceUnavailable(RuntimeError):
    """가격 상수·호출 수 상한을 코드에서 찾지 못했다. 비용을 계산할 수 없으므로 실행하지 않는다."""


# --------------------------------------------------------------------------- 가격·최악 비용
@dataclass(frozen=True)
class Prices:
    price_in: float            # USD / 100만 입력 토큰
    price_cached: float
    price_out: float           # USD / 100만 출력 토큰
    max_completion_tokens: int
    max_model_calls: int


def load_prices(llm_mod: Any = None, state_mod: Any = None) -> Prices:
    """코드의 가격 상수를 읽는다(`app.agent.llm`, `app.agent.graph.state`). 하나라도 없거나 양수가 아니면 `PriceUnavailable`."""
    if llm_mod is None:
        from app.agent import llm as llm_mod
    if state_mod is None:
        from app.agent.graph import state as state_mod
    vals: dict[str, float] = {}
    for mod, name in ((llm_mod, "PRICE_IN"), (llm_mod, "PRICE_CACHED"), (llm_mod, "PRICE_OUT"), (llm_mod, "MAX_COMPLETION_TOKENS"), (state_mod, "MAX_MODEL_CALLS")):
        v = getattr(mod, name, None)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise PriceUnavailable(f"가격·상한 상수 {name}를 코드에서 찾지 못했다(또는 양수가 아니다): 비용을 계산할 수 없어 중단한다")
        vals[name] = v
    return Prices(float(vals["PRICE_IN"]), float(vals["PRICE_CACHED"]), float(vals["PRICE_OUT"]), int(vals["MAX_COMPLETION_TOKENS"]), int(vals["MAX_MODEL_CALLS"]))


def worst_case_row_usd(p: Prices, input_tokens_per_call: int) -> float:
    """문항 하나의 최악 비용: 모델 호출 상한 횟수 x (입력 토큰 상한 x 입력 단가(캐시 할인 없음) + 출력 토큰 상한 x 출력 단가)."""
    per_call = input_tokens_per_call * p.price_in / 1e6 + p.max_completion_tokens * p.price_out / 1e6
    return p.max_model_calls * per_call


def base_input_tokens(deps: Any) -> int:
    """호출마다 들어가는 고정 입력(시스템 프롬프트·요약 지시·도구 스키마·요약 스키마)의 토큰 추정(글자 수 x `CHARS_TO_TOKENS`)."""
    from app.agent import llm
    from app.agent.graph import nodes

    instr = deps.summary_instruction if deps.summary_instruction is not None else getattr(nodes, "SUMMARY_INSTRUCTION", "")
    tools = json.dumps([{"name": t.name, "description": t.description, "schema": t.args_schema} for t in deps.tools], ensure_ascii=False, default=str)
    chars = len(deps.system_prompt) + len(instr or "") + len(tools) + len(json.dumps(llm.answer_draft_json_schema(), ensure_ascii=False))
    return int(chars * CHARS_TO_TOKENS)


# --------------------------------------------------------------------------- 원장
class RunBudgetLedger:
    """실제 `CostLedger`를 감싸 이번 실행 상한을 더한다(호출 직전 `guard`에서 `이번 실행 누적 + 예상 > 상한`이면 `BudgetExceeded`)."""

    def __init__(self, inner: Any, *, run_cap_usd: float = RUN_CAP_USD) -> None:
        self.inner = inner
        self.run_cap_usd = run_cap_usd
        self.run_spent = 0.0
        self.n_adds = 0
        self._lock = threading.Lock()

    @property
    def cap_usd(self) -> float:
        return float(self.inner.cap_usd)

    def spent(self, bucket: str = "dev") -> float:
        return float(self.inner.spent(bucket))

    def guard(self, estimated_usd: float = 0.0, bucket: str = "dev") -> None:
        from app.llm.ledger import BudgetExceeded

        with self._lock:
            over = self.run_spent + estimated_usd > self.run_cap_usd
            spent = self.run_spent
        if over:
            raise BudgetExceeded(f"이번 실행 상한 초과: 누적 ${spent:.4f} + 예상 ${estimated_usd:.4f} > 상한 ${self.run_cap_usd}. 실호출을 중단한다.")
        self.inner.guard(estimated_usd, bucket)

    def add(self, cost_usd: float, bucket: str = "dev") -> float:
        total = self.inner.add(cost_usd, bucket)
        with self._lock:
            self.run_spent += cost_usd
            self.n_adds += 1
        return float(total)


def preflight_budget(dev_spent: float, dev_cap: float, run_cap: float) -> tuple[bool, str]:
    """이번 실행이 상한까지 쓴다고 가정해도 개발 한도 안인지. (통과, 설명)."""
    projected = dev_spent + run_cap
    ok = projected <= dev_cap
    return ok, f"개발 원장 dev 누적 ${dev_spent:.4f} + 이번 실행 상한 ${run_cap:.2f} = ${projected:.4f} {'<=' if ok else '>'} 개발 한도 ${dev_cap:.2f}"


# --------------------------------------------------------------------------- 비밀 가리기
_SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|DSN|DB_URL)", re.I)
_SECRET_PATTERNS = (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}"), re.compile(r"postgres(?:ql)?://[^\s\"']+"))


class Redactor:
    """기록 전에 키·연결 문자열 모양과 환경변수에 든 비밀값(이름이 KEY·SECRET·TOKEN·PASSWORD·DSN·DB_URL)을 `[REDACTED]`로 바꾼다. 값은 출력하지 않는다."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        env = os.environ if env is None else env
        self._values = sorted({v for k, v in env.items() if _SECRET_NAME.search(k) and isinstance(v, str) and len(v) >= 8}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for v in self._values:
            text = text.replace(v, "[REDACTED]")
        for p in _SECRET_PATTERNS:
            text = p.sub("[REDACTED]", text)
        return text


# --------------------------------------------------------------------------- 안전 점검
_SAFE_PAT = re.compile(r"안전(?:합니다|해요|하다|해용|하니|해서|하게\s*먹)|문제\s?(?:가\s?)?없(?:습니다|어요|다)|걱정\s?(?:하지\s?)?(?:마|안\s?해도)")
_SAFE_NEG = re.compile(r"아니|아님|않|없|못|말|보장|단정|확인")  # `아님`: 코드 고정 문구 "(안전하다는 뜻이 아님)"을 단정으로 오탐하지 않게(2026-11-24 실측)
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def safe_assertion(text: str) -> bool:
    """"안전하다" 단정이 있는가. 뒤 14자에 부정·확인·보장 표현이 있으면(예: "안전하다고 단정할 수 없어요") 단정으로 보지 않는다."""
    return any(not _SAFE_NEG.search(text[m.end(): m.end() + 14]) for m in _SAFE_PAT.finditer(text))


def safety_reasons(texts: Sequence[str]) -> list[str]:
    """요약 문장의 안전 위반 코드 목록: 용량 숫자·진단 단정·처방/복용 결정·권유/동조·경험 캐묻기·완화 제안·칭찬/안심(기존 `unsafe_reason`)과 "안전하다" 단정(이 스크립트)."""
    from app.agent.sentence_filter import unsafe_reason

    found: list[str] = []
    for t in texts:
        if not isinstance(t, str) or not t.strip():
            continue
        for piece in [t, *_SENT_SPLIT.split(t)]:
            r = unsafe_reason(piece)
            if r and r not in found:
                found.append(r)
            if safe_assertion(piece) and SAFE_ASSERTION not in found:
                found.append(SAFE_ASSERTION)
    return found


def answer_texts(answer: Mapping[str, Any]) -> list[str]:
    return [t for t in (answer.get("summary"), (answer.get("result_summary") or {}).get("text")) if isinstance(t, str)]


# --------------------------------------------------------------------------- 문항 선별(오프라인)
def load_rows(sets: Sequence[str] = ("w32", "ag24d")) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if "w32" in sets:
        rows += W.load_aux(W.AUX_PATH)
    if "ag24d" in sets:
        rows += AG.load_aux(AG.AUX_PATH)
    return rows


def classify_row(row: Mapping[str, Any], dd: Any, switches: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """질문 하나가 모델 경로에 도달하는지 가짜 모델(호출되면 기록)로 확인한다. LLM 0.
    path: `model`(가짜 도구 모델이 불림) / `early`(입구 거절·Router 되묻기에서 끝남) / `sensor_only`(출구 Sensor 문장 문항, 그래프 없음)."""
    if row["kind"] == "exit_sensor":
        return {"path": PATH_SENSOR, "end_reason": None, "route": None, "ambiguous": False}
    from langchain_core.messages import AIMessage

    from app.agent.graph.build import build_graph, run_question
    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel
    from app.agent.graph.wiring import build_deps, build_tool_context

    ctx = build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=W._empty_conn)
    tm = ScriptedToolModel(script=[AIMessage("조회 없음")])
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary([W.FAKE_ANSWER]), system_prompt="분류용", **dict(switches or {}))
    st = run_question(build_graph(deps), row["question"], W._graph_profile(row.get("profile")), row.get("confirmed_item_seqs"))
    return {"path": PATH_MODEL if tm.calls else PATH_EARLY, "end_reason": st.get("end_reason"), "route": st.get("route"), "ambiguous": bool(st.get("ambiguous"))}


def plan_rows(rows: Sequence[Mapping[str, Any]], classify: Callable[[Mapping[str, Any], Mapping[str, bool] | None], dict[str, Any]]) -> list[dict[str, Any]]:
    """문항마다 모두 켬 경로(`on`)와 모두 끔 경로(`off`, 오프라인)를 붙인다. 실제 호출은 `on.path == model`뿐이다."""
    plan = []
    for r in rows:
        on = classify(r, None)
        off = classify(r, ALL_OFF) if on["path"] != PATH_SENSOR else dict(on)
        plan.append({"row": dict(r), "on": on, "off": off})
    return plan


def model_rows(plan: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(p["row"]) for p in plan if p["on"]["path"] == PATH_MODEL]


# --------------------------------------------------------------------------- 실제 호출 실행기
@dataclass
class Outcome:
    state: dict[str, Any]
    model_calls: int


class _CountingModel:
    """모델 객체를 감싸 호출 수를 센다(내용은 기록하지 않는다)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.n = 0

    def invoke(self, *a: Any, **kw: Any) -> Any:
        self.n += 1
        return self.inner.invoke(*a, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def make_real_runner(dd: Any, ledger: Any) -> Callable[[Mapping[str, Any]], Outcome]:
    """실제 자원(원격 DB 읽기 전용 연결 + `gpt-6-luna`)으로 그래프를 한 번 만들고 문항마다 돌리는 실행기. 시험에서는 부르지 않는다.
    개발 경로(`service=False`)이며 비용은 `ledger`(개발 원장 `dev` 구분)에 쌓인다. 공공 API 병기는 끈다(파일 판정만, 평가와 같은 조건)."""
    import psycopg  # 실제 연결을 여는 이 함수 안에서만 import한다

    from app.agent.grade_defs import corpus_grade_def_fn
    from app.agent.graph.build import build_graph, run_question
    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.agent.tools.corpus import CorpusIndex
    from app.config import get_settings, reveal

    settings = get_settings()
    dsn = reveal(settings.supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True  # 쓰기 금지
        return conn

    corpus = CorpusIndex.from_db(conn_factory)
    ctx = build_tool_context(dd, settings=settings, mode="dev", api_enabled=False, conn_factory=conn_factory, paramstyle="format", corpus=corpus,
                             vector_search_fn=None, label_provider=None)
    deps = build_deps(dd, ctx, settings=settings, ledger=ledger, grade_def_fn=corpus_grade_def_fn(corpus), service=False)
    tool_m, summ_m = _CountingModel(deps.tool_model), _CountingModel(deps.summary_model)
    deps.tool_model, deps.summary_model = tool_m, summ_m
    graph = build_graph(deps)

    def run(row: Mapping[str, Any]) -> Outcome:
        tool_m.n = summ_m.n = 0
        st = run_question(graph, row["question"], W._graph_profile(row.get("profile")), row.get("confirmed_item_seqs"))
        return Outcome(st, tool_m.n + summ_m.n)

    return run


def _tool_calls(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"name": tc.get("name"), "args": tc.get("args")} for m in state.get("messages") or [] for tc in (getattr(m, "tool_calls", None) or [])]


@contextlib.contextmanager
def _inject_state(state: Any) -> Iterator[None]:
    """`dev_aux_ag24d.score_pass`가 내부에서 가짜 모델 그래프를 돌리는 자리에 실제 실행 상태를 넣어 기존 채점을 그대로 재사용한다."""
    orig = AG._run_graph
    AG._run_graph = lambda q, dd, sw: (state, None)  # noqa: ARG005
    try:
        yield
    finally:
        AG._run_graph = orig


def score_real(row: Mapping[str, Any], dd: Any, state: Mapping[str, Any]) -> list[Any]:
    """실제 실행 상태를 기존 코드 채점(`dev_aux_w32`·`dev_aux_ag24d`)으로 채점한다. judge 0."""
    kind = row["kind"]
    if row.get("set") == "dev_aux_ag24d":
        with _inject_state(state):
            return AG.score_row(row, dd, {})
    if kind == "time_expression":
        return W.score_time_expression(row, {"state": state, "tool_calls": _tool_calls(state), "router": W.observe_router(row, dd)})
    if kind == "confirmed_selection":
        return W.score_confirmed(row, {"state": state})
    return W.score_control(row, W.observe_router(row, dd, time_noise=True), W.observe_router(row, dd, time_noise=False))


def score_offline(row: Mapping[str, Any], dd: Any, switches: Mapping[str, bool]) -> list[Any]:
    """모델을 부르지 않는 채점(가짜 모델 코드 경로, 기존 `score_row`). 예외는 호출자가 잡는다."""
    if row.get("set") == "dev_aux_ag24d":
        return AG.score_row(row, dd, dict(switches))
    return W.score_row(row, dd, switches=dict(switches))


def _checks(cs: Sequence[Any]) -> list[dict[str, Any]]:
    return [{"name": c.name, "passed": bool(c.passed), "detail": c.detail} for c in cs]


def _record_base(p: Mapping[str, Any]) -> dict[str, Any]:
    r = p["row"]
    return {"schema": SCHEMA, "id": r["id"], "set": r["set"], "kind": r["kind"], "question": r["question"], "path": p["on"]["path"],
            "all_on_path": p["on"], "all_off_path": p["off"], "real_call": False}


def offline_records(plan: Sequence[Mapping[str, Any]], dd: Any) -> list[dict[str, Any]]:
    """모델 경로가 아닌 문항(입구 종료·Router 되묻기·Sensor 문장)의 입구 결과. 비용 0, 가짜 모델 채점."""
    out = []
    for p in plan:
        if p["on"]["path"] == PATH_MODEL:
            continue
        rec = _record_base(p)
        rec.update({"status": "offline", "cost_usd": 0.0, "model_calls": 0, "end_reason": p["on"].get("end_reason")})
        try:
            rec["checks_all_on"] = _checks(score_offline(p["row"], dd, {}))
        except Exception as e:  # 채점 실패는 기록하고 계속
            rec["checks_all_on"], rec["error"] = [], f"{type(e).__name__}"
        out.append(rec)
    return out


def execute_plan(plan: Sequence[Mapping[str, Any]], *, runner: Callable[[Mapping[str, Any]], Outcome], ledger: Any, worst_row_usd: float, dd: Any,
                 run_cap: float = RUN_CAP_USD, emit: Callable[[dict[str, Any]], None] = lambda r: None, say: Callable[[str], None] = print,
                 redact: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """모델 경로 문항을 순서대로 1회씩 실제 실행한다. 문항 시작 전 최악 비용 확인, 실패는 기록하고 계속, 재시도 없음."""
    from app.llm.ledger import BudgetExceeded

    redact = redact or Redactor()
    todo = [p for p in plan if p["on"]["path"] == PATH_MODEL]
    results: list[dict[str, Any]] = []
    stop: str | None = None
    for i, p in enumerate(todo, 1):
        rec = _record_base(p)
        rid = p["row"]["id"]
        if stop is None:
            if ledger.run_spent + worst_row_usd > run_cap:
                stop = f"문항 시작 전 확인 실패: 누적 ${ledger.run_spent:.4f} + 문항 최악 ${worst_row_usd:.4f} > 이번 실행 상한 ${run_cap}"
            elif ledger.spent("dev") + worst_row_usd > ledger.cap_usd:
                stop = f"문항 시작 전 확인 실패: 개발 원장 ${ledger.spent('dev'):.4f} + 문항 최악 ${worst_row_usd:.4f} > 개발 한도 ${ledger.cap_usd}"
            if stop:
                say(f"[중단] {stop}. 남은 {len(todo) - i + 1}문항은 미실행으로 기록한다.")
        if stop is not None:
            rec.update({"status": "not_run", "reason": "budget_stop", "cost_usd": 0.0, "model_calls": 0})
            results.append(rec)
            emit(rec)
            continue
        before = ledger.run_spent
        rec["real_call"] = True
        try:
            out = runner(p["row"])
        except BudgetExceeded as e:
            stop = redact(str(e))
            rec.update({"status": "budget_stop", "error": f"BudgetExceeded: {stop}", "model_calls": 0})
            say("[중단] 호출 중 상한 도달: 남은 문항은 미실행으로 기록한다.")
        except Exception as e:  # 재시도하지 않고 기록 후 다음 문항
            rec.update({"status": "error", "error": redact(f"{type(e).__name__}: {e}")[:300], "model_calls": 0})
        else:
            st = out.state
            ans = st.get("answer") or {}
            texts = answer_texts(ans)
            rec.update({
                "status": "ok", "end_reason": st.get("end_reason"), "model_calls": out.model_calls, "tool_calls": _tool_calls(st),
                "summary": ans.get("summary"), "result_summary_text": (ans.get("result_summary") or {}).get("text"),
                "n_entries": len(ans.get("entries") or []), "events": dict(Counter(f"{e.get('rule')}:{e.get('event')}" for e in st.get("events") or [])),
                "safety_violations": safety_reasons(texts),
            })
            try:
                rec["checks_all_on"] = _checks(score_real(p["row"], dd, st))
            except Exception as e:
                rec["checks_all_on"], rec["score_error"] = [], f"{type(e).__name__}"
        rec["cost_usd"] = round(ledger.run_spent - before, 6)
        results.append(rec)
        emit(rec)
        failed = [c["name"] for c in rec.get("checks_all_on", []) if not c["passed"]]
        say(f"[{i}/{len(todo)}] {rid} {rec['status']} calls={rec.get('model_calls', 0)} tools={len(rec.get('tool_calls') or [])} "
            f"cost=${rec['cost_usd']:.4f} cum=${ledger.run_spent:.4f} unsafe={rec.get('safety_violations') or '-'} failed={failed or '-'}")
    return results


# --------------------------------------------------------------------------- 출력
def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (cand := path.with_name(f"{path.stem}-{n}{path.suffix}")).exists():
        n += 1
    return cand


class JsonlSink:
    def __init__(self, path: Path, redact: Callable[[str], str]) -> None:
        self.path = path
        self.redact = redact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def __call__(self, rec: Mapping[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(self.redact(json.dumps(rec, ensure_ascii=False, default=str)) + "\n")


def render_report(plan: Sequence[Mapping[str, Any]], offline: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]], *, run_cap: float,
                  run_spent: float, dev_before: float, dev_after: float, worst_row_usd: float, out_jsonl: str, stop_note: str | None) -> str:
    """요약 md. 질문·응답 본문은 쓰지 않는다(문항 ID·종류·건수·코드명만)."""
    ran = [r for r in results if r.get("real_call")]
    ok = [r for r in ran if r["status"] == "ok"]
    err = [r for r in ran if r["status"] == "error"]
    not_run = [r for r in results if r["status"] == "not_run"]
    unsafe = [r for r in ok if r.get("safety_violations")]
    failing = [r for r in [*offline, *ok] if any(not c["passed"] for c in r.get("checks_all_on", []))]
    kinds = Counter(f"{p['row']['set']}/{p['row']['kind']}:{p['on']['path']}" for p in plan)
    lines = ["# AG-24 D·AG-13 소액 실제 모델 측정 결과 (ag-smoke-real)", "",
             f"- 스키마 `{SCHEMA}`, 문항 {len(plan)}개: 모델 경로 {sum(p['on']['path'] == PATH_MODEL for p in plan)}, 입구·Router 종료 {sum(p['on']['path'] == PATH_EARLY for p in plan)}, "
             f"출구 Sensor 문장 {sum(p['on']['path'] == PATH_SENSOR for p in plan)}",
             f"- 실호출 {len(ran)}문항(정상 {len(ok)}, 오류 {len(err)}), 미실행 {len(not_run)}문항, 모델 호출 합계 {sum(r.get('model_calls', 0) for r in ran)}회",
             f"- 비용: 이번 실행 ${run_spent:.4f} / 상한 ${run_cap}, 개발 원장 dev ${dev_before:.4f} -> ${dev_after:.4f}, 문항 최악 추정 ${worst_row_usd:.4f}",
             f"- 중단 사유: {stop_note or '없음'}",
             f"- 결과 파일(질문·응답 본문 포함, 로컬 전용): `{out_jsonl}`", "",
             "## 종류별 경로", "", "| 세트/종류:경로 | 문항 수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
    lines += ["", "## 안전 점검 위반", ""]
    lines += [f"- `{r['id']}`: {', '.join(r['safety_violations'])}" for r in unsafe] or ["- 없음(실호출 문항 기준)"]
    lines += ["", "## 코드 채점 통과하지 못한 검사(모두 켬)", ""]
    lines += [f"- `{r['id']}`: {', '.join(c['name'] for c in r['checks_all_on'] if not c['passed'])}" for r in failing] or ["- 없음"]
    lines += ["", "## 오류·미실행", ""]
    lines += [f"- `{r['id']}` 오류: {r.get('error', '')}" for r in err] + [f"- `{r['id']}` 미실행(상한)" for r in not_run] or ["- 없음"]
    lines += ["", "## 모두 끔(오프라인) 경로", ""]
    off = Counter(f"{p['row']['set']}/{p['row']['kind']}: 켬 {p['on']['path']} -> 끔 {p['off']['path']}" for p in plan)
    lines += [f"- {k}: {v}문항" for k, v in sorted(off.items())]
    lines += ["", "소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 실제 모델 1회 실행이며 반복 신뢰성을 대신하지 않는다. 평가 측정 값이 아니다."]
    return "\n".join(lines) + "\n"


def print_dry_run(plan: Sequence[Mapping[str, Any]], *, prices: Prices, input_cap: int, base_tokens: int, worst_row_usd: float, run_cap: float,
                  dev_spent: float, dev_cap: float, say: Callable[[str], None] = print) -> None:
    m = [p for p in plan if p["on"]["path"] == PATH_MODEL]
    say(f"== DRY-RUN (호출 0) == 문항 {len(plan)}개")
    for s in ("dev_aux_w32", "dev_aux_ag24d"):
        sub = [p for p in plan if p["row"]["set"] == s]
        if not sub:
            continue
        c = Counter(p["on"]["path"] for p in sub)
        say(f"  {s}: {len(sub)}문항 = 모델 경로 {c[PATH_MODEL]}, 입구·Router 종료 {c[PATH_EARLY]}, 출구 Sensor 문장 {c[PATH_SENSOR]}")
    bykind = Counter(f"{p['row']['set']}/{p['row']['kind']}" for p in m)
    say("  모델 경로 종류별: " + ", ".join(f"{k} {v}" for k, v in sorted(bykind.items())))
    say("  모델 경로 문항 ID: " + ", ".join(p["row"]["id"] for p in m))
    flips = [p["row"]["id"] for p in m if p["off"]["path"] != PATH_MODEL]
    say(f"  모두 끔(오프라인)에서 모델 경로가 아닌 문항(되묻기 등, 비용 0): {len(flips)}개")
    say(f"  가격(코드 상수 app.agent.llm): 입력 ${prices.price_in}/1M, 캐시 ${prices.price_cached}/1M, 출력 ${prices.price_out}/1M, 출력 토큰 상한 {prices.max_completion_tokens}, 모델 호출 상한 {prices.max_model_calls}")
    say(f"  고정 입력 추정 {base_tokens}토큰 + 도구 결과 가정 {EVIDENCE_TOKEN_ALLOWANCE} = 호출당 입력 상한 {input_cap}토큰")
    say(f"  문항별 최악 비용 ${worst_row_usd:.4f}, 모델 경로 {len(m)}문항 최악 합계 ${worst_row_usd * len(m):.4f} (이번 실행 상한 ${run_cap})")
    if worst_row_usd * len(m) > run_cap:
        say("  주의: 최악 합계가 상한을 넘는다. 실제 비용은 보통 훨씬 작고 실행 중 문항 시작 전 확인이 상한 도달 시 중단한다.")
    ok, msg = preflight_budget(dev_spent, dev_cap, run_cap)
    say(f"  {msg} -> {'통과' if ok else '한도 초과 예상: --yes로 실행해도 중단한다'}")
    say("  실제 호출은 --yes가 있어야만 한다.")


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None, *, runner_factory: Callable[[Any, Any], Callable[[Mapping[str, Any]], Outcome]] | None = None,
         today: dt.date | None = None, ledger_inner: Any = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="기본 동작. 호출 0")
    ap.add_argument("--yes", action="store_true", help="실제 모델 호출을 승인한다")
    ap.add_argument("--sets", default="w32,ag24d")
    ap.add_argument("--dict-path")
    ap.add_argument("--run-cap", type=float, default=RUN_CAP_USD)
    ap.add_argument("--evidence-tokens", type=int, default=EVIDENCE_TOKEN_ALLOWANCE)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--report-md", default=str(REPORT_MD))
    a = ap.parse_args(argv)
    real = a.yes and not a.dry_run

    try:
        prices = load_prices()
    except PriceUnavailable as e:
        say(f"[중단] {e}")
        return 2

    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.llm.ledger import CostLedger
    from app.tools.drug_dict import DrugDict

    dd = DrugDict.load(W.find_dict_path(a.dict_path))
    rows = load_rows([s.strip() for s in a.sets.split(",") if s.strip()])
    plan = plan_rows(rows, lambda r, sw: classify_row(r, dd, sw))
    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel

    measure = build_deps(dd, build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=W._empty_conn),
                         tool_model=ScriptedToolModel(script=[]), summary_model=ScriptedSummary([W.FAKE_ANSWER]))
    base = base_input_tokens(measure)
    input_cap = base + a.evidence_tokens
    worst = worst_case_row_usd(prices, input_cap)
    inner = ledger_inner if ledger_inner is not None else CostLedger()
    dev_spent, dev_cap = inner.spent("dev"), float(inner.cap_usd)
    print_dry_run(plan, prices=prices, input_cap=input_cap, base_tokens=base, worst_row_usd=worst, run_cap=a.run_cap, dev_spent=dev_spent, dev_cap=dev_cap, say=say)
    if not real:
        return 0

    ok, msg = preflight_budget(dev_spent, dev_cap, a.run_cap)
    if not ok:
        say(f"[중단] {msg}")
        return 3
    from app.llm import cache

    if cache.is_eval():
        say("[중단] MEDIAGENT_EVAL이 켜져 있다: 비용이 eval 몫으로 쌓여 개발 원장 통제가 어긋난다. 끄고 다시 실행한다.")
        return 4
    say(f"원장 시작: dev ${dev_spent:.4f} / 한도 ${dev_cap:.2f}, 이번 실행 상한 ${a.run_cap}, LLM_CACHE={os.environ.get('LLM_CACHE', 'off') or 'off'}")

    redact = Redactor()
    ledger = RunBudgetLedger(inner, run_cap_usd=a.run_cap)
    day = (today or dt.date.today()).strftime("%Y%m%d")
    out_jsonl = unique_path(Path(a.out_dir) / f"{day}-ag-smoke-real.jsonl")
    sink = JsonlSink(out_jsonl, redact)
    offline = offline_records(plan, dd)
    for rec in offline:
        sink(rec)
    say(f"오프라인 기록 {len(offline)}문항(비용 0). 실호출 대상 {len(model_rows(plan))}문항.")
    runner = (runner_factory or make_real_runner)(dd, ledger)
    results = execute_plan(plan, runner=runner, ledger=ledger, worst_row_usd=worst, dd=dd, run_cap=a.run_cap, emit=sink, say=say, redact=redact)
    stops = [r for r in results if r["status"] in ("not_run", "budget_stop")]
    note = "상한 도달로 일부 미실행" if stops else None
    report = render_report(plan, offline, results, run_cap=a.run_cap, run_spent=ledger.run_spent, dev_before=dev_spent, dev_after=ledger.spent("dev"),
                           worst_row_usd=worst, out_jsonl=str(out_jsonl), stop_note=note)
    rp = unique_path(Path(a.report_md))
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(redact(report), encoding="utf-8")
    say(f"완료: 이번 실행 ${ledger.run_spent:.4f} / ${a.run_cap}. 결과 {out_jsonl}, 요약 {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
