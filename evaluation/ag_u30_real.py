"""AG-13 FE-17 U-30 요약 중복 개선 소액 실제 모델 측정 도구(2026-11-24, 이번 실행 상한 0.10 USD, 사용자 "요약 중복 실측 승인", AG-24 배정 잔여 안).

개발 보조 문항 `eval_set/dev_aux_u30.jsonl`(8문항, 사용자 사례 `u30-text-008` 포함)을 **실제 그래프·실제 모델(`gpt-6-luna`)**로 돌려
요약 문장 중복(U-30-1)이 프롬프트 묶음과 코드 후처리로 얼마나 줄어드는지 본다. 채점은 코드(`dev_aux_u30.py`의 "금기 목록에 없음" 계열 문장 수 기준, judge 0)다.

설계(비용을 아끼는 핵심): `summary_dedupe`는 LLM 출력 **뒤**의 결정론 후처리(`graph/nodes.py` `finalize_node`가 `summary_dedupe.dedupe_sentences`를 부름)이므로
켬/끔으로 모델을 두 번 부르지 않는다. 프롬프트 묶음(`prompt_set@v3` 대 `prompt_set@v5`)만 실제 호출로 바꾸고, 각 호출은 `summary_dedupe` **끔**으로 그래프를 돌려 원래 요약을 얻는다.
**켬** 결과는 같은 최종 상태(`final_sentences`·`entities`·`evidence`)에 같은 `finalize` 노드(`make_raw_nodes(켬 deps)["finalize"]`)를 한 번 더 적용해 만든다
(노드 코드 그대로이므로 `H1 SUMMARY_DEDUPE` 이벤트·근거 ID 이동·요약 문자열이 실제 켬 경로와 같다. 호출 0). 끔 `finalize`를 같은 상태에 다시 적용했을 때 원래 응답과 같은지도
`replay_equal`로 매 실행 기록한다(오프라인 적용이 충실하다는 확인).

비교 4칸: ① v3+끔(이전 동작 기준선) ② v3+켬(코드 후처리만) ③ v5+끔(프롬프트 묶음만) ④ v5+켬(둘 다). 기준선 ①에서 한 번에 하나만 바꾼 ②·③과 합친 ④를 본다.
주의: `prompt_set@v5`는 `agent_system@v3`(draft, AG-24 안내 전용 규칙 포함) + `answer_summary@v2`(draft)라 ③·④는 요약 프롬프트 외에 시스템 프롬프트도 함께 바뀐다.
요약 프롬프트만 따로 보려면 `--v5-system same`(v5 묶음 요약 지시 + v3 묶음의 시스템 프롬프트 `agent_system@v2`).

- **기본은 `--dry-run`**: 호출 0·파일 쓰기 0. `--yes`가 있어야만 실제 호출한다. `--run-cap` 기본 0.10, **0.10 초과는 거부**한다.
- 비용 통제: 호출 직전 `이번 실행 누적 + 항목당 사전 점검 상한(--per-item-bound, 기본 0.006) > 상한`이면 중단하고 남은 항목을 `not_run`으로 기록한다(재시도 없음).
  누적은 매 호출 뒤 원장(`RunBudgetLedger`)에서 읽은 **실측값**이다. 호출 중에도 `RunBudgetLedger.guard`가 상한 초과를 막는다.
  사전 점검 상한 0.006은 2026-11-24 22문항 실측 최대 $0.0037의 약 1.6배다. **이 방식은 최악 합계 보장이 아니다**(한 항목이 0.006을 넘을 수 있고, 항목 수 x 0.006은 0.10을 넘는다).
  그래도 한 항목 안의 호출 직전 `guard`와 실측 누적 점검이 상한을 넘기지 못하게 막는다. 원장 dev 한도(2.50)·`MEDIAGENT_EVAL` 켜짐·가격 상수 없음은 `ag_smoke_real.py`처럼 거부한다.
  `LLM_CACHE`가 off가 아니면 반복이 캐시를 읽어 의미가 없으므로 거부한다.
- 반복 순서: 반복 회차 -> 문항 -> 묶음. 상한으로 중간에 멈춰도 앞 회차는 두 묶음 모두 끝나 있다.
- 결과: `data/mock/ag-smoke/{날짜}-ag-u30-real.jsonl`(질문·응답 본문 포함, 로컬 전용)과 요약 md(`data/mock/briefs/reports/ag-u30-real.md`, 문항 ID·건수·표만, 질문·응답 본문 없음).
  기록 직전 `ag_smoke_real.Redactor`로 환경변수 비밀값·키·연결 문자열 모양을 가린다.
- 소표본이라 k/n과 Wilson 95% 구간으로만 쓰고 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). **평가 러너·지표·judge·`manifest.json`·시험셋은 건드리지 않는다.**

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python evaluation/ag_u30_real.py                       # 기본 --dry-run(호출 0)
    backend/.venv/bin/python evaluation/ag_u30_real.py --yes                 # 실제 호출(원격 DB는 읽기 전용 연결)
    backend/.venv/bin/python evaluation/ag_u30_real.py --yes --repeats 3 --v5-system same
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT / "backend"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ag_smoke_real as S  # noqa: E402
import dev_aux_u30 as U  # noqa: E402
import dev_aux_w32 as W  # noqa: E402
from eval_metrics import wilson  # noqa: E402

SCHEMA = "ag-u30-real@v1"
MAX_RUN_CAP_USD = 0.10             # 사용자 승인 상한(2026-11-24). 이보다 큰 --run-cap은 거부한다
RUN_CAP_USD = 0.10
PER_ITEM_BOUND_USD = 0.006         # 항목당 사전 점검 상한: 2026-11-24 22문항 실측 최대 $0.0037의 약 1.6배(최악 보장이 아니다)
FALLBACK_MEAN_USD = 0.0011         # 실측 파일을 못 읽을 때의 가정(2026-11-24 22문항 평균)
FALLBACK_MAX_USD = 0.0037
DEFAULT_REPEATS = 2
MAX_REPEATS = 5
USER_CASE_QUESTION = "타이레놀정500 먹고 이부프로펜도 먹어도 돼요?"   # 2026-11-24 사용자 사례(`u30-text-008`과 같은 질문)
OUT_DIR = ROOT / "data" / "mock" / "ag-smoke"
SMOKE_DIR = OUT_DIR
REPORT_MD = ROOT / "data" / "mock" / "briefs" / "reports" / "ag-u30-real.md"
REQUIRED_CLASSES = ("DISCLAIMER", "PHARMACIST")   # 요약에 남아야 하는 안내 뜻: 안전하다고 판단할 수 없다 / 약사 확인
FIXED_FIELDS = ("emergency", "route", "entries", "fixed_notice", "pharmacist_advice")  # 후처리가 바꾸면 안 되는 응답 칸


@dataclass(frozen=True)
class Arm:
    name: str          # 결과 칸 이름
    prompt_set: str    # 프롬프트 묶음 파일 이름(backend/prompts/<prompt_set>.yaml)


ARMS = (Arm("v3", "prompt_set@v3"), Arm("v5", "prompt_set@v5"))
ARM_BY_NAME = {a.name: a for a in ARMS}
CELLS: tuple[tuple[str, str], ...] = tuple((a.name, d) for a in ARMS for d in ("off", "on"))
CELL_LABEL = {("v3", "off"): "① v3+끔", ("v3", "on"): "② v3+켬", ("v5", "off"): "③ v5+끔", ("v5", "on"): "④ v5+켬"}


# --------------------------------------------------------------------------- 문항
def load_rows(path: str | Path = U.AUX_PATH) -> list[dict[str, Any]]:
    """`dev_aux_u30.jsonl` 문항 + 사용자 사례 질문(이미 있으면 더하지 않는다). 시험셋은 `load_aux`가 열기 전에 거절한다."""
    rows = U.load_aux(path)
    if not any(r["question"].strip() == USER_CASE_QUESTION for r in rows):
        rows.append({"id": "u30-user-case", "set": "dev_aux_u30", "kind": "text_only", "question": USER_CASE_QUESTION, "n_drugs": 2,
                     "fake_sentences": [{"text": "-", "claim_type": "conclusion"}], "expected": {"n_dropped": 0, "max_not_listed_sentences": 1}})
    return rows


def plan_runs(rows: Sequence[Mapping[str, Any]], repeats: int, arms: Sequence[Arm] = ARMS) -> list[dict[str, Any]]:
    """실행 순서: 반복 회차 -> 문항 -> 묶음(중간에 멈춰도 앞 회차는 모든 문항·묶음이 끝나 있다)."""
    return [{"run_id": f"{r['id']}|{a.name}|r{rep}", "row": dict(r), "arm": a.name, "rep": rep}
            for rep in range(1, repeats + 1) for r in rows for a in arms]


# --------------------------------------------------------------------------- 프롬프트 묶음 -> 그래프 의존성
def _refs(prompt_set: str) -> dict[str, str]:
    from app.llm.prompts import PROMPTS_DIR, load_prompt_set

    return {r.split("@", 1)[0]: r for r in load_prompt_set(PROMPTS_DIR / f"{prompt_set}.yaml").prompts}


def resolve_prompts(arm: Arm, *, v5_system: str = "set") -> dict[str, str]:
    """묶음이 가리키는 시스템 프롬프트·요약 프롬프트 파일. `v5_system="same"`이면 v5의 시스템 프롬프트를 v3 묶음의 것(`agent_system@v2`)으로 둔다."""
    refs = _refs(arm.prompt_set)
    system_ref = refs["agent_system"]
    if arm.name != ARMS[0].name and v5_system == "same":
        system_ref = _refs(ARMS[0].prompt_set)["agent_system"]
    return {"prompt_set": arm.prompt_set, "system": system_ref, "summary": refs["answer_summary"]}


def prompt_status(ref: str) -> str:
    from app.llm.prompts import PROMPTS_DIR, split_frontmatter

    fm, _ = split_frontmatter((PROMPTS_DIR / f"{ref}.md").read_text(encoding="utf-8"))
    return str((fm or {}).get("status", "?"))


def build_arm_deps(dd: Any, ctx: Any, arm: Arm, *, v5_system: str = "set", **deps_kw: Any) -> Any:
    """묶음 하나의 그래프 의존성(`summary_dedupe` 끔, 나머지 스위치는 기본 켬 = 서비스 기본과 같다).

    `wiring.build_deps(prompt_set=...)`는 **요약 지시**만 고르고 시스템 프롬프트는 `prompt_name`·`system_prompt`로 따로 정한다(wiring.py `build_deps` 인자 `prompt_name`·`prompt_set`).
    그리고 `build_deps` 안의 `load_system_prompt(prompt_name)`은 draft를 허용하지 않으므로 draft인 `agent_system@v3`는 여기서 `allow_draft=True`로 읽어 `system_prompt`로 직접 넘긴다.
    """
    from app.agent.graph.prompt import load_summary_instruction, load_system_prompt
    from app.agent.graph.wiring import build_deps

    p = resolve_prompts(arm, v5_system=v5_system)
    return build_deps(dd, ctx, system_prompt=load_system_prompt(p["system"], allow_draft=True),
                      summary_instruction=load_summary_instruction(p["prompt_set"], allow_draft=True), prompt_set=arm.prompt_set, allow_draft=True,
                      summary_dedupe=False, **deps_kw)


# --------------------------------------------------------------------------- 그래프 한 번 실행 + 켬 오프라인 적용
@dataclass
class Outcome:
    state: dict[str, Any]
    model_calls: int
    on_answer: dict[str, Any] | None = None        # 같은 상태에 켬 `finalize`를 적용한 응답
    on_events: Sequence[Mapping[str, Any]] = ()
    replay_equal: bool | None = None               # 끔 `finalize`를 같은 상태에 다시 적용한 응답이 원래 응답과 같은가(전체)
    replay_summary_equal: bool | None = None       # 요약만
    on_error: str | None = None                    # 켬 적용이 예외로 실패하면 예외 종류만


@dataclass
class ArmGraph:
    deps: Any
    graph: Any
    nodes_off: dict[str, Callable[[Any], dict[str, Any]]]
    nodes_on: dict[str, Callable[[Any], dict[str, Any]]]
    tool_m: Any
    summ_m: Any


def make_arm_graph(deps: Any) -> ArmGraph:
    """`deps`(끔)로 그래프를 만들고, 같은 deps에서 `summary_dedupe`만 켠 복사본의 원시 노드(`finalize` 포함)를 함께 만든다."""
    from app.agent.graph.build import build_graph
    from app.agent.graph.nodes import make_raw_nodes

    tool_m, summ_m = S._CountingModel(deps.tool_model), S._CountingModel(deps.summary_model)
    deps.tool_model, deps.summary_model = tool_m, summ_m
    graph = build_graph(deps)
    deps_on = dataclasses.replace(deps, summary_dedupe=True)
    return ArmGraph(deps, graph, make_raw_nodes(deps), make_raw_nodes(deps_on), tool_m, summ_m)


def run_arm(ag: ArmGraph, row: Mapping[str, Any]) -> Outcome:
    """질문 하나를 끔 그래프로 끝까지 돌리고(실호출), 같은 최종 상태에 켬 `finalize`를 적용한다(호출 0)."""
    from app.agent.graph.build import run_question

    ag.tool_m.n = ag.summ_m.n = 0
    st = run_question(ag.graph, row["question"], W._graph_profile(row.get("profile")), row.get("confirmed_item_seqs"))
    calls = ag.tool_m.n + ag.summ_m.n
    try:
        on = ag.nodes_on["finalize"](st)
        replay = ag.nodes_off["finalize"](st)
    except Exception as e:  # 켬 적용 실패는 기록하고 이 실행의 켬 칸만 비운다
        return Outcome(st, calls, on_error=type(e).__name__)
    ans = st.get("answer") or {}
    return Outcome(st, calls, on.get("answer"), list(on.get("events") or []), replay.get("answer") == st.get("answer"),
                   (replay.get("answer") or {}).get("summary") == ans.get("summary"))


def make_real_runner(dd: Any, ledger: Any, *, v5_system: str = "set") -> Callable[[str, Mapping[str, Any]], Outcome]:
    """실제 자원(원격 DB 읽기 전용 연결 + `gpt-6-luna`)으로 묶음마다 그래프를 한 번 만들고 문항마다 돌리는 실행기. 시험에서는 부르지 않는다.
    `ag_smoke_real.make_real_runner`와 같은 개발 경로(`service=False`, 공공 API 병기 끔)이며 비용은 `ledger`(개발 원장 `dev` 구분)에 쌓인다."""
    import psycopg  # 실제 연결을 여는 이 함수 안에서만 import한다

    from app.agent.grade_defs import corpus_grade_def_fn
    from app.agent.graph.wiring import build_tool_context
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
    graphs: dict[str, ArmGraph] = {}

    def run(arm_name: str, row: Mapping[str, Any]) -> Outcome:
        if arm_name not in graphs:
            deps = build_arm_deps(dd, ctx, ARM_BY_NAME[arm_name], v5_system=v5_system, settings=settings, ledger=ledger,
                                  grade_def_fn=corpus_grade_def_fn(corpus), service=False)
            graphs[arm_name] = make_arm_graph(deps)
        return run_arm(graphs[arm_name], row)

    return run


# --------------------------------------------------------------------------- 채점(코드, judge 0)
def _n_drugs(state: Mapping[str, Any]) -> int | None:
    """`finalize_node`와 같은 식(Router 엔티티 수, 0이면 None)."""
    return sum(1 for e in state.get("entities") or [] if isinstance(e, dict)) or None


def sentence_lists(state: Mapping[str, Any], answer_off: Mapping[str, Any] | None, on_answer: Mapping[str, Any] | None,
                   on_events: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str], int, bool]:
    """(끔 문장, 켬 문장, 지운 수, 켬 적용이 이벤트·요약과 맞는가). 모델 문장이 요약이 아닌 경로(되묻기·거절·상한·폴백)는 빈 목록이다.
    켬 문장은 `finalize_node`와 같은 인자의 `dedupe_sentences`로 구하고, `finalize`가 낸 `SUMMARY_DEDUPE` 이벤트 수·켬 요약 글자와 맞는지 확인한다."""
    from app.agent.answer_schema import Sentence
    from app.agent.summary_dedupe import dedupe_sentences

    sents = [Sentence.model_validate(s) for s in state.get("final_sentences") or []]
    off_texts = [s.text for s in sents]
    summary_off = (answer_off or {}).get("summary") or ""
    if not off_texts or not summary_off.startswith(" ".join(off_texts)):
        return [], [], 0, True
    on_texts, dropped = off_texts, 0
    if len(sents) > 1:
        res = dedupe_sentences(sents, n_drugs=_n_drugs(state))
        on_texts, dropped = [s.text for s in res.sentences], len(res.dropped)
    ev = sum(int(e.get("dropped") or 0) for e in on_events if e.get("event") == "SUMMARY_DEDUPE")
    consistent = ev == dropped and ((on_answer or {}).get("summary") or "").startswith(" ".join(on_texts))
    return off_texts, on_texts, dropped, consistent


def cell_metrics(row: Mapping[str, Any], texts: Sequence[str], answer: Mapping[str, Any] | None) -> dict[str, Any]:
    """칸 하나(묶음 x 끔/켬)의 점검. `dev_aux_u30.score`와 같은 기준: "금기 목록에 없음" 계열 문장 수 <= 문항 기준이면 중복 없음."""
    from app.agent.summary_dedupe import DISCLAIMER, NOT_LISTED, PHARMACIST, classes_of

    cl = [classes_of(t) for t in texts]
    n_nl = sum(NOT_LISTED in c for c in cl)
    allowed = int(row["expected"]["max_not_listed_sentences"])
    return {"n_sentences": len(texts), "n_not_listed": n_nl, "allowed": allowed, "dup": n_nl > allowed, "dup_excess": max(0, n_nl - allowed),
            "n_disclaimer": sum(DISCLAIMER in c for c in cl), "n_pharmacist": sum(PHARMACIST in c for c in cl),
            "classes": sorted(set().union(*cl)) if cl else [], "unsafe": S.safety_reasons(S.answer_texts(answer or {})),
            "summary_chars": len((answer or {}).get("summary") or "")}


def outcome_fields(row: Mapping[str, Any], out: Outcome) -> dict[str, Any]:
    st = out.state
    off_ans = st.get("answer") or {}
    on_ans = out.on_answer
    off_t, on_t, dropped, consistent = sentence_lists(st, off_ans, on_ans, out.on_events)
    f: dict[str, Any] = {
        "status": "ok", "end_reason": st.get("end_reason"), "model_calls": out.model_calls, "emergency": bool(off_ans.get("emergency")),
        "n_entities": sum(1 for e in st.get("entities") or [] if isinstance(e, dict)), "summary_off": off_ans.get("summary"),
        "sentences_off": off_t, "sentences_on": on_t, "n_dropped": dropped, "on_consistent": consistent, "replay_equal": out.replay_equal,
        "replay_summary_equal": out.replay_summary_equal, "tool_calls": S._tool_calls(st),
        "cells": {"off": cell_metrics(row, off_t, off_ans)},
    }
    if on_ans is None:
        f.update({"on_error": out.on_error or "NoOnAnswer", "summary_on": None})
        return f
    f["summary_on"] = on_ans.get("summary")
    f["cells"]["on"] = cell_metrics(row, on_t, on_ans)
    f["events_on"] = dict(Counter(f"{e.get('rule')}:{e.get('event')}" for e in out.on_events))
    f["fixed_fields_equal"] = all(on_ans.get(k) == off_ans.get(k) for k in FIXED_FIELDS)
    f["summary_changed"] = on_ans.get("summary") != off_ans.get("summary")
    off_classes, on_classes = set(f["cells"]["off"]["classes"]), set(f["cells"]["on"]["classes"])
    f["lost_required"] = sorted((off_classes & set(REQUIRED_CLASSES)) - on_classes)
    return f


# --------------------------------------------------------------------------- 실행
def base_record(run: Mapping[str, Any]) -> dict[str, Any]:
    r = run["row"]
    return {"schema": SCHEMA, "run_id": run["run_id"], "id": r["id"], "kind": r["kind"], "arm": run["arm"], "rep": run["rep"],
            "question": r["question"], "real_call": False}


def execute_runs(runs: Sequence[Mapping[str, Any]], *, runner: Callable[[str, Mapping[str, Any]], Outcome], ledger: Any, per_item_bound: float,
                 run_cap: float, emit: Callable[[dict[str, Any]], None] = lambda r: None, say: Callable[[str], None] = print,
                 redact: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """실행 목록을 순서대로 한 번씩 실행한다. 호출 전에 `실측 누적 + 항목당 사전 점검 상한 > 상한`이면 중단하고 남은 항목을 `not_run`으로 기록한다. 실패는 기록하고 계속, 재시도 없음."""
    from app.llm.ledger import BudgetExceeded

    redact = redact or S.Redactor()
    results: list[dict[str, Any]] = []
    stop: str | None = None
    for i, run in enumerate(runs, 1):
        rec = base_record(run)
        if stop is None:
            if ledger.run_spent + per_item_bound > run_cap:
                stop = f"호출 전 확인 실패: 실측 누적 ${ledger.run_spent:.4f} + 항목당 사전 점검 상한 ${per_item_bound} > 이번 실행 상한 ${run_cap}"
            elif ledger.spent("dev") + per_item_bound > ledger.cap_usd:
                stop = f"호출 전 확인 실패: 개발 원장 ${ledger.spent('dev'):.4f} + 항목당 사전 점검 상한 ${per_item_bound} > 개발 한도 ${ledger.cap_usd}"
            if stop:
                say(f"[중단] {stop}. 남은 {len(runs) - i + 1}회는 not_run으로 기록한다.")
        if stop is not None:
            rec.update({"status": "not_run", "reason": "budget_stop", "cost_usd": 0.0, "model_calls": 0})
            results.append(rec)
            emit(rec)
            continue
        before = ledger.run_spent
        rec["real_call"] = True
        try:
            out = runner(run["arm"], run["row"])
        except BudgetExceeded as e:
            stop = redact(str(e))
            rec.update({"status": "budget_stop", "error": f"BudgetExceeded: {stop}"[:300], "model_calls": 0})
            say("[중단] 호출 중 상한 도달: 남은 항목은 not_run으로 기록한다.")
        except Exception as e:  # 재시도하지 않고 기록 후 다음 항목
            rec.update({"status": "error", "error": redact(f"{type(e).__name__}: {e}")[:300], "model_calls": 0})
        else:
            try:
                rec.update(outcome_fields(run["row"], out))
            except Exception as e:  # 채점 실패도 기록하고 계속(호출은 이미 일어났다)
                rec.update({"status": "error", "error": f"score:{type(e).__name__}", "model_calls": out.model_calls})
        rec["cost_usd"] = round(ledger.run_spent - before, 6)
        results.append(rec)
        emit(rec)
        c = rec.get("cells") or {}
        say(f"[{i}/{len(runs)}] {rec['run_id']} {rec['status']} calls={rec.get('model_calls', 0)} cost=${rec['cost_usd']:.4f} cum=${ledger.run_spent:.4f} "
            f"문장 끔={c.get('off', {}).get('n_sentences', '-')} 켬={c.get('on', {}).get('n_sentences', '-')} "
            f"중복 끔={c.get('off', {}).get('dup', '-')} 켬={c.get('on', {}).get('dup', '-')} unsafe={c.get('off', {}).get('unsafe') or '-'}/{c.get('on', {}).get('unsafe') or '-'}")
    return results


# --------------------------------------------------------------------------- 집계
def _frac(k: int, n: int) -> dict[str, Any]:
    w = wilson(k, n)
    return {"k": k, "n": n, "wilson": None if w is None else [round(w[0], 3), round(w[1], 3)]}


def _fmt(f: Mapping[str, Any]) -> str:
    if not f["n"]:
        return "-"
    lo, hi = f["wilson"]
    return f"{f['k']}/{f['n']} [{lo:.2f}-{hi:.2f}]"


def aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ok = [r for r in records if r.get("status") == "ok"]
    out: dict[str, Any] = {"n_records": len(records), "n_ok": len(ok), "n_error": sum(r.get("status") == "error" for r in records),
                           "n_not_run": sum(r.get("status") in ("not_run", "budget_stop") for r in records), "cells": {}, "per_item": {}, "arms": {}}
    for arm, d in CELLS:
        rs = [r for r in ok if r["arm"] == arm and (r.get("cells") or {}).get(d)]
        meas = [r for r in rs if r["cells"][d]["n_sentences"] > 0]
        cs = [r["cells"][d] for r in meas]
        codes = Counter(c for x in cs for c in x["unsafe"])
        ids = sorted({r["id"] for r in meas})
        all_nodup = sum(all(not x["cells"][d]["dup"] for x in meas if x["id"] == i) for i in ids)
        out["cells"][f"{arm}|{d}"] = {
            "runs": len(rs), "measurable": len(meas), "nodup": _frac(sum(not c["dup"] for c in cs), len(cs)), "dup_excess_sum": sum(c["dup_excess"] for c in cs),
            "mean_sentences": round(sum(c["n_sentences"] for c in cs) / len(cs), 2) if cs else None,
            "unsafe_runs": sum(bool(c["unsafe"]) for c in cs), "unsafe_codes": dict(codes),
            "has_disclaimer": _frac(sum(c["n_disclaimer"] > 0 for c in cs), len(cs)), "has_pharmacist": _frac(sum(c["n_pharmacist"] > 0 for c in cs), len(cs)),
            "items_all_nodup": {"k": all_nodup, "n": len(ids)}}
    for rr in ok:
        if rr.get("cells"):
            for d, c in rr["cells"].items():
                if c["n_sentences"] > 0:
                    cell = out["per_item"].setdefault(rr["id"], {}).setdefault(f"{rr['arm']}|{d}", [0, 0])
                    cell[0] += bool(c["dup"])
                    cell[1] += 1
    for a in ARMS:
        rs = [r for r in ok if r["arm"] == a.name and r.get("cells", {}).get("on")]
        meas = [r for r in rs if r["cells"]["on"]["n_sentences"] > 0 or r["cells"]["off"]["n_sentences"] > 0]
        lost = Counter(c for r in meas for c in r.get("lost_required", []))
        non_normal = [r for r in rs if r.get("end_reason") != "NORMAL"]
        emerg = [r for r in rs if r.get("emergency")]
        by_id: dict[str, set[str]] = {}
        for r in ok:
            if r["arm"] == a.name:
                by_id.setdefault(r["id"], set()).add(hashlib.sha256((r.get("summary_off") or "").encode()).hexdigest())
        out["arms"][a.name] = {
            "runs_with_on": len(rs), "applied_runs": sum(r.get("n_dropped", 0) > 0 for r in rs), "dropped_sum": sum(r.get("n_dropped", 0) for r in rs),
            "lost_required": dict(lost), "lost_runs": sum(bool(r.get("lost_required")) for r in meas),
            "on_inconsistent": sum(r.get("on_consistent") is False for r in rs), "replay_unequal": sum(r.get("replay_equal") is False for r in rs),
            "replay_summary_unequal": sum(r.get("replay_summary_equal") is False for r in rs),
            "fixed_fields_unequal": sum(r.get("fixed_fields_equal") is False for r in rs),
            "changed_without_drop": sum(bool(r.get("summary_changed")) and r.get("n_dropped", 0) == 0 for r in rs),
            "non_normal_runs": len(non_normal), "non_normal_changed": sum(bool(r.get("summary_changed")) for r in non_normal),
            "emergency_runs": len(emerg), "emergency_changed": sum(bool(r.get("summary_changed")) for r in emerg),
            "items": len(by_id), "items_varying_across_repeats": sum(len(v) > 1 for v in by_id.values()),
            "on_errors": sum(bool(r.get("on_error")) for r in ok if r["arm"] == a.name)}
    return out


def render_report(plan_info: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *, run_cap: float, per_item_bound: float, run_spent: float,
                  dev_before: float, dev_after: float, out_jsonl: str, stop_note: str | None, repeats: int, v5_system: str) -> str:
    """요약 md. 질문·응답 본문은 쓰지 않는다(문항 ID·건수·표·코드명만)."""
    agg = aggregate(records)
    ran = [r for r in records if r.get("real_call")]
    errs = [r for r in records if r.get("status") == "error"]
    L = ["# AG-13 U-30 요약 중복 개선 소액 실제 모델 측정 결과 (ag-u30-real)", "",
         f"- 스키마 `{SCHEMA}`, 문항 {plan_info['n_rows']}개 x 묶음 2 x 반복 {repeats} = 계획 {plan_info['n_runs']}회, 실호출 {len(ran)}회(정상 {agg['n_ok']}, 오류 {agg['n_error']}), 미실행 {agg['n_not_run']}회, "
         f"모델 호출 합계 {sum(r.get('model_calls', 0) for r in ran)}회",
         f"- 비용: 이번 실행 ${run_spent:.4f} / 상한 ${run_cap}, 개발 원장 dev ${dev_before:.4f} -> ${dev_after:.4f}, 항목당 사전 점검 상한 ${per_item_bound}(최악 합계 보장이 아님)",
         f"- 프롬프트: v3 = {plan_info['v3']}, v5 = {plan_info['v5']}(`--v5-system {v5_system}`)", f"- 중단 사유: {stop_note or '없음'}",
         f"- 결과 파일(질문·응답 본문 포함, 로컬 전용): `{out_jsonl}`", "",
         "## 1. 4칸 비교 (중복 점검: \"금기 목록에 없음\" 계열 문장 수 <= 문항 기준, 코드 채점·judge 0)", "",
         "| 칸 | 중복 없음 k/n [Wilson 95%] | 초과 문장 합 | 평균 문장 수 | 안전 점검 위반 실행 | 안전 판단 불가 문구 | 약사 확인 문구 |", "|---|---|---|---|---|---|---|"]
    for arm, d in CELLS:
        c = agg["cells"][f"{arm}|{d}"]
        L.append(f"| {CELL_LABEL[(arm, d)]} | {_fmt(c['nodup'])} | {c['dup_excess_sum']} | {c['mean_sentences'] if c['mean_sentences'] is not None else '-'} | "
                 f"{c['unsafe_runs']}/{c['measurable']} {c['unsafe_codes'] or ''} | {_fmt(c['has_disclaimer'])} | {_fmt(c['has_pharmacist'])} |")
    L += ["", "측정 가능 = 요약에 모델 문장이 있는 실행(되묻기·거절·상한·폴백은 제외). 실행 단위 k/n이고 같은 문항의 반복은 독립 표본이 아니다.", "",
          "문항 단위(모든 반복에서 중복 없음인 문항 수/측정 문항 수): " + ", ".join(
              f"{CELL_LABEL[(a, d)]} {agg['cells'][f'{a}|{d}']['items_all_nodup']['k']}/{agg['cells'][f'{a}|{d}']['items_all_nodup']['n']}" for a, d in CELLS), "",
          "## 2. 켬 후처리 영향 (같은 원래 요약에 `finalize` 적용, 끔 대비)", "",
          "| 묶음 | 지운 실행 | 지운 문장 합 | 필수 문구 손실 실행 | 응급 변경/응급 | 비정상 종료 변경/비정상 | 켬 불일치 | 끔 재적용 불일치(전체/요약) | 고정 칸 불일치 |", "|---|---|---|---|---|---|---|---|---|"]
    for a in ARMS:
        x = agg["arms"][a.name]
        L.append(f"| {a.name} | {x['applied_runs']}/{x['runs_with_on']} | {x['dropped_sum']} | {x['lost_runs']} {x['lost_required'] or ''} | "
                 f"{x['emergency_changed']}/{x['emergency_runs']} | {x['non_normal_changed']}/{x['non_normal_runs']} | {x['on_inconsistent']} | "
                 f"{x['replay_unequal']}/{x['replay_summary_unequal']} | {x['fixed_fields_unequal']} |")
    L += ["", "필수 문구 손실 = 끔 요약에 있던 \"안전하다고 판단할 수 없다\"(DISCLAIMER)·약사 확인(PHARMACIST) 뜻이 켬 요약에서 사라진 실행(0이어야 한다). "
          "켬 불일치 = 이 도구가 구한 켬 문장이 `finalize`의 `SUMMARY_DEDUPE` 이벤트·켬 요약과 다름. 끔 재적용 불일치 = 같은 상태에 끔 `finalize`를 다시 적용한 응답이 원래 응답과 다름(0이면 오프라인 적용이 충실).", "",
          "## 3. 문항별 중복 실행 수 (중복 실행/측정 실행)", "", "| 문항 | " + " | ".join(CELL_LABEL[c] for c in CELLS) + " |", "|---|" + "---|" * len(CELLS)]
    for iid in sorted(agg["per_item"]):
        cells = agg["per_item"][iid]
        L.append(f"| `{iid}` | " + " | ".join((f"{cells[f'{a}|{d}'][0]}/{cells[f'{a}|{d}'][1]}" if f"{a}|{d}" in cells else "-") for a, d in CELLS) + " |")
    L += ["", "## 4. 반복 변동 (같은 문항·같은 묶음의 끔 요약이 반복마다 다른 문항 수)", "", "| 묶음 | 변동 문항/문항 |", "|---|---|"]
    L += [f"| {a.name} | {agg['arms'][a.name]['items_varying_across_repeats']}/{agg['arms'][a.name]['items']} |" for a in ARMS]
    L += ["", "## 5. 오류·미실행", ""]
    items = [f"- `{r['run_id']}` 오류: {str(r.get('error', '')).split(':', 1)[0]}" for r in errs]
    if agg["n_not_run"]:
        items.append(f"- 미실행 {agg['n_not_run']}회(상한)")
    L += items or ["- 없음"]
    L += ["", "소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 실제 모델 소수 회 실행이며 평가 측정 값이 아니다. 시험셋·judge·지표 정의는 쓰지 않았다."]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- dry-run
def observed_costs(smoke_dir: Path) -> tuple[float, float, int, bool]:
    """오늘 22문항 실측 파일(`*-ag-smoke-real*.jsonl`)의 항목당 실측 비용 (평균, 최대, 건수, 파일에서 읽었는가). 없으면 고정 가정값."""
    vals: list[float] = []
    for p in sorted(Path(smoke_dir).glob("*-ag-smoke-real*.jsonl")) if Path(smoke_dir).exists() else []:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("real_call") and isinstance(r.get("cost_usd"), (int, float)):
                vals.append(float(r["cost_usd"]))
    if not vals:
        return FALLBACK_MEAN_USD, FALLBACK_MAX_USD, 0, False
    return sum(vals) / len(vals), max(vals), len(vals), True


def print_dry_run(rows: Sequence[Mapping[str, Any]], paths: Mapping[str, str], runs: Sequence[Mapping[str, Any]], *, prices: S.Prices, repeats: int,
                  run_cap: float, per_item_bound: float, obs: tuple[float, float, int, bool], dev_spent: float, dev_cap: float,
                  arm_info: Mapping[str, Mapping[str, str]], dict_source: str = "file", say: Callable[[str], None] = print) -> None:
    mean, mx, n_obs, from_file = obs
    model_ids = [r["id"] for r in rows if paths[r["id"]] == S.PATH_MODEL]
    n_model_runs = len(model_ids) * len(ARMS) * repeats
    say(f"== DRY-RUN (호출 0, 파일 쓰기 0) == 문항 {len(rows)}개 x 묶음 {len(ARMS)} x 반복 {repeats} = 실행 {len(runs)}회")
    for a in ARMS:
        i = arm_info[a.name]
        say(f"  묶음 {a.name}: {i['prompt_set']} = 시스템 {i['system']}({i['system_status']}) + 요약 {i['summary']}({i['summary_status']}), 문항 {len(rows)}개 x 반복 {repeats} = {len(rows) * repeats}회")
    say("  문항 ID와 경로: " + ", ".join(f"{r['id']}:{paths[r['id']]}" for r in rows))
    say(f"  모델 경로 문항 {len(model_ids)}개 -> 모델을 실제로 부르는 실행 {n_model_runs}회(나머지는 입구·Router에서 끝나 비용 0)")
    early = [r["id"] for r in rows if paths[r["id"]] != S.PATH_MODEL]
    if early:
        say(f"  주의: {', '.join(early)}는 사전({dict_source})에서 약 이름을 찾지 못해 Router 되묻기로 끝난다(모델을 안 부름, 측정 불가). "
            "서비스와 같은 사전으로 보려면 --dict-source db(읽기 전용 DB 연결 1회).")
    say(f"  가격(코드 상수 app.agent.llm): 입력 ${prices.price_in}/1M, 캐시 ${prices.price_cached}/1M, 출력 ${prices.price_out}/1M, 출력 토큰 상한 {prices.max_completion_tokens}, 모델 호출 상한 {prices.max_model_calls}")
    src = f"{n_obs}건 실측 파일" if from_file else "파일 없음, 2026-11-24 22문항 실측 평균·최대를 가정값으로 사용"
    say(f"  항목당 실측 비용({src}): 평균 ${mean:.4f}, 최대 ${mx:.4f}")
    say(f"  예상 비용(문항당 실측 평균 x 모델 호출 실행 {n_model_runs}회) = ${mean * n_model_runs:.4f} / 이번 실행 상한 ${run_cap} "
        f"(v5 시스템 프롬프트가 더 길어 약간 클 수 있다)")
    say(f"  항목당 사전 점검 상한 ${per_item_bound} x 모델 호출 실행 {n_model_runs}회 = ${per_item_bound * n_model_runs:.4f}(합계가 상한을 넘을 수 있으나 시작 조건이 아니다)")
    say(f"  사전 점검 방식: 호출 직전 `실측 누적 + ${per_item_bound} > ${run_cap}`이면 중단. 이것은 최악 합계 보장이 아니다: 한 항목이 ${per_item_bound}를 넘을 수 있고, "
        f"그래도 호출 직전 RunBudgetLedger.guard가 상한 초과를 막는다.")
    ok, msg = S.preflight_budget(dev_spent, dev_cap, run_cap)
    say(f"  {msg} -> {'통과' if ok else '한도 초과 예상: --yes로 실행해도 중단한다'}")
    say("  실제 호출은 --yes가 있어야만 한다.")


# --------------------------------------------------------------------------- CLI
def load_dict(a: argparse.Namespace) -> Any:
    """약품명 사전. 기본은 로컬 파일(오프라인). `--dict-source db`는 서비스와 같은 DB 사전을 읽기 전용 연결로 한 번 읽는다(쓰기 없음, LLM 호출 아님)."""
    from app.tools.drug_dict import DrugDict

    if a.dict_source == "file":
        return DrugDict.load(W.find_dict_path(a.dict_path))
    import psycopg

    from app.config import get_settings, reveal

    dsn = reveal(get_settings().supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True
        return conn

    return DrugDict.from_db(conn_factory, paramstyle="format")


def main(argv: list[str] | None = None, *, runner_factory: Callable[..., Callable[[str, Mapping[str, Any]], Outcome]] | None = None,
         today: dt.date | None = None, ledger_inner: Any = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="기본 동작. 호출 0")
    ap.add_argument("--yes", action="store_true", help="실제 모델 호출을 승인한다")
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help=f"문항·묶음마다 반복 횟수(기본 {DEFAULT_REPEATS}, 최대 {MAX_REPEATS})")
    ap.add_argument("--run-cap", type=float, default=RUN_CAP_USD, help=f"이번 실행 상한 USD(기본·최대 {MAX_RUN_CAP_USD})")
    ap.add_argument("--per-item-bound", type=float, default=PER_ITEM_BOUND_USD, help="항목당 사전 점검 상한 USD(최악 보장이 아님)")
    ap.add_argument("--v5-system", choices=("set", "same"), default="set", help="set: v5 묶음의 agent_system@v3(draft) 그대로 / same: v3 묶음의 agent_system@v2로 두고 요약 프롬프트만 v5")
    ap.add_argument("--aux", default=str(U.AUX_PATH))
    ap.add_argument("--dict-path")
    ap.add_argument("--dict-source", choices=("file", "db"), default="file",
                    help="file: 로컬 사전 파일(기본, 오프라인) / db: 서비스와 같은 DB 사전(읽기 전용 연결 1회). 파일 사전에 없는 약(이부프로펜 등)이 든 사용자 사례 문항은 db여야 모델 경로에 간다")
    ap.add_argument("--smoke-dir", default=str(SMOKE_DIR), help="항목당 실측 비용을 읽을 폴더(dry-run 예상 비용용)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--report-md", default=str(REPORT_MD))
    a = ap.parse_args(argv)
    real = a.yes and not a.dry_run

    if not (0 < a.run_cap <= MAX_RUN_CAP_USD):
        say(f"[중단] --run-cap은 0 초과 {MAX_RUN_CAP_USD} 이하여야 한다(승인 상한 ${MAX_RUN_CAP_USD}): {a.run_cap}")
        return 5
    if not (0 < a.per_item_bound <= a.run_cap):
        say(f"[중단] --per-item-bound는 0 초과 --run-cap 이하여야 한다: {a.per_item_bound}")
        return 5
    if not (1 <= a.repeats <= MAX_REPEATS):
        say(f"[중단] --repeats는 1 이상 {MAX_REPEATS} 이하여야 한다: {a.repeats}")
        return 5
    try:
        prices = S.load_prices()
    except S.PriceUnavailable as e:
        say(f"[중단] {e}")
        return 2

    from app.llm.ledger import CostLedger
    dd = load_dict(a)
    rows = load_rows(a.aux)
    paths = {r["id"]: S.classify_row(r, dd)["path"] for r in rows}
    runs = plan_runs(rows, a.repeats)
    arm_info = {}
    for arm in ARMS:
        p = resolve_prompts(arm, v5_system=a.v5_system)
        arm_info[arm.name] = {**p, "system_status": prompt_status(p["system"]), "summary_status": prompt_status(p["summary"])}
    inner = ledger_inner if ledger_inner is not None else CostLedger()
    dev_spent, dev_cap = inner.spent("dev"), float(inner.cap_usd)
    obs = observed_costs(Path(a.smoke_dir))
    print_dry_run(rows, paths, runs, prices=prices, repeats=a.repeats, run_cap=a.run_cap, per_item_bound=a.per_item_bound, obs=obs, dev_spent=dev_spent,
                  dev_cap=dev_cap, arm_info=arm_info, dict_source=a.dict_source, say=say)
    if not real:
        return 0

    ok, msg = S.preflight_budget(dev_spent, dev_cap, a.run_cap)
    if not ok:
        say(f"[중단] {msg}")
        return 3
    from app.llm import cache

    if cache.is_eval():
        say("[중단] MEDIAGENT_EVAL이 켜져 있다: 비용이 eval 몫으로 쌓여 개발 원장 통제가 어긋난다. 끄고 다시 실행한다.")
        return 4
    if cache.cache_mode() != "off":
        say(f"[중단] LLM_CACHE={cache.cache_mode()}: 반복이 캐시를 읽어 실제 모델 비결정성을 볼 수 없다. LLM_CACHE=off로 다시 실행한다.")
        return 6
    say(f"원장 시작: dev ${dev_spent:.4f} / 한도 ${dev_cap:.2f}, 이번 실행 상한 ${a.run_cap}, 항목당 사전 점검 상한 ${a.per_item_bound}, LLM_CACHE=off")

    redact = S.Redactor()
    ledger = S.RunBudgetLedger(inner, run_cap_usd=a.run_cap)
    day = (today or dt.date.today()).strftime("%Y%m%d")
    out_jsonl = S.unique_path(Path(a.out_dir) / f"{day}-ag-u30-real.jsonl")
    sink = S.JsonlSink(out_jsonl, redact)
    runner = (runner_factory or make_real_runner)(dd, ledger, v5_system=a.v5_system)
    results = execute_runs(runs, runner=runner, ledger=ledger, per_item_bound=a.per_item_bound, run_cap=a.run_cap, emit=sink, say=say, redact=redact)
    stops = [r for r in results if r["status"] in ("not_run", "budget_stop")]
    note = "상한 도달로 일부 미실행" if stops else None
    info = {"n_rows": len(rows), "n_runs": len(runs), **{k: f"{v['system']}+{v['summary']}" for k, v in arm_info.items()}}
    report = render_report(info, results, run_cap=a.run_cap, per_item_bound=a.per_item_bound, run_spent=ledger.run_spent, dev_before=dev_spent,
                           dev_after=ledger.spent("dev"), out_jsonl=str(out_jsonl), stop_note=note, repeats=a.repeats, v5_system=a.v5_system)
    rp = S.unique_path(Path(a.report_md))
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(redact(report), encoding="utf-8")
    say(f"완료: 이번 실행 ${ledger.run_spent:.4f} / ${a.run_cap}. 결과 {out_jsonl}, 요약 {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
