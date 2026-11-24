# ruff: noqa: S101  (시험 파일: assert 허용)
"""`ag_u30_real.py` 시험: 가짜 모델·가짜 원장만 쓴다(LLM·네트워크·원격 DB 0).

실행: `backend/.venv/bin/python -m pytest -q evaluation/test_ag_u30_real.py` (저장소 루트)
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
for _p in (str(ROOT / "backend"), str(EVAL)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ag_smoke_real as S  # noqa: E402
import ag_u30_real as A  # noqa: E402
import dev_aux_u30 as U  # noqa: E402

DICT = ROOT / "data" / "mock" / "dict" / "drug_dict.json"
needs_dict = pytest.mark.skipif(not DICT.exists(), reason="로컬 사전 파일 없음")
SECRET = "s" + "k-testsecret1234567890abcdef"  # noqa: S105  (가짜 값, 시험 전용)


# --------------------------------------------------------------------------- 도우미
def _dd() -> Any:
    from app.tools.drug_dict import DrugDict

    return DrugDict.load(DICT)


def _ledger(tmp_path: Path, *, spent: float = 0.0, cap: float = 2.5, run_cap: float = 0.10) -> S.RunBudgetLedger:
    from app.llm.ledger import CostLedger

    inner = CostLedger(tmp_path / "ledger.json", cap_usd=cap)
    if spent:
        inner.add(spent)
    return S.RunBudgetLedger(inner, run_cap_usd=run_cap)


def _fake_graph_outcome(dd: Any, row: dict[str, Any], arm_name: str, sentences: list[dict[str, Any]], *, v5_system: str = "set") -> A.Outcome:
    """실제 그래프·실제 `finalize`에 가짜 모델만 붙여 한 번 돌린다(LLM 0). 도구 선택 모델은 Router가 정리한 약만 부른다(`dev_aux_u30.observe_graph`와 같다)."""
    from langchain_core.messages import AIMessage

    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call
    from app.agent.graph.wiring import build_tool_context
    from app.agent.router import route_input

    pre = route_input(row["question"], dd, None)
    drugs = [{"item_seq": e.item_seq} for e in pre.entities if e.status == "RESOLVED" and e.item_seq]
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": drugs}, "chk")]), AIMessage("조회를 마쳤다")] if drugs else [AIMessage("조회 없음")]
    ctx = build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=U._empty_conn)
    deps = A.build_arm_deps(dd, ctx, A.ARM_BY_NAME[arm_name], v5_system=v5_system, tool_model=ScriptedToolModel(script=script),
                            summary_model=ScriptedSummary([{"sentences": sentences}]))
    return A.run_arm(A.make_arm_graph(deps), row)


def _sents(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"text": s["text"], "evidence_ids": [], "claim_type": s["claim_type"], "citations": []} for s in row["fake_sentences"]]


def _runner_factory(*, cost_each: float = 0.001, calls: list[str] | None = None, merged_for_v5: bool = True, boom_first: bool = False):
    """문항 `fake_sentences`를 가짜 요약으로 쓰는 실행기. v5 묶음은 중복 문장을 합친 요약을 내는 것으로 가정한다(첫 문장만)."""
    def factory(dd: Any, ledger: Any, **kw: Any):
        state = {"n": 0}

        def run(arm_name: str, row: Any) -> A.Outcome:
            if calls is not None:
                calls.append(f"{row['id']}|{arm_name}")
            state["n"] += 1
            if boom_first and state["n"] == 1:
                raise RuntimeError(f"401 invalid key {SECRET}")
            ledger.guard(0.00075)
            ledger.add(cost_each)
            sents = _sents(row)
            if merged_for_v5 and arm_name == "v5":
                sents = sents[:1]
            out = _fake_graph_outcome(dd, row, arm_name, sents, v5_system=kw.get("v5_system", "set"))
            if state["n"] == 2 and out.state.get("answer"):
                out.state["answer"]["summary"] = f"{out.state['answer'].get('summary') or ''} {SECRET}"
            return out

        return run

    return factory


def _synthetic_outcome(summary_off: str, summary_on: str, texts_off: list[str], texts_on: list[str] | None = None, *, dropped: int = 0, end_reason: str = "NORMAL",
                       emergency: bool = False, events_dropped: int | None = None) -> A.Outcome:
    st = {"end_reason": end_reason, "entities": [{"raw": "a"}, {"raw": "b"}], "messages": [], "final_sentences": [{"text": t, "evidence_ids": [], "claim_type": "conclusion", "citations": []} for t in texts_off],
          "answer": {"summary": summary_off, "emergency": "119" if emergency else None, "entries": [], "route": "AGENT"}}
    on = {"summary": summary_on, "emergency": st["answer"]["emergency"], "entries": [], "route": "AGENT"}
    ev = [{"rule": "H1", "event": "SUMMARY_DEDUPE", "dropped": dropped if events_dropped is None else events_dropped}] if (dropped or events_dropped) else []
    return A.Outcome(st, 1, on, ev, True, True)


ROW = {"id": "r1", "kind": "dup_pair", "question": "질문 하나", "expected": {"max_not_listed_sentences": 1}}
NL1 = "자료에는 두 약의 조합이 금기 목록에 없다고 되어 있습니다."
NL2 = "두 약의 병용은 금기 목록에 올라 있지 않습니다."
DISC = "다만 이것만으로 안전하다고 판단할 수는 없습니다."
PHARM = "복용 전 약사에게 확인해 주세요."


# --------------------------------------------------------------------------- 문항·4칸 구성
@needs_dict
def test_rows_include_user_case_once() -> None:
    rows = A.load_rows()
    assert len(rows) == 8 and [r["id"] for r in rows].count("u30-text-008") == 1
    assert sum(r["question"] == A.USER_CASE_QUESTION for r in rows) == 1      # 중복 추가 금지


def test_rows_adds_user_case_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    base = [{"id": "x", "question": "다른 질문", "kind": "dup_pair", "expected": {"max_not_listed_sentences": 1}}]
    monkeypatch.setattr(U, "load_aux", lambda path=None: [dict(r) for r in base])
    rows = A.load_rows()
    assert [r["question"] for r in rows] == ["다른 질문", A.USER_CASE_QUESTION]
    assert rows[1]["expected"]["max_not_listed_sentences"] == 1


def test_four_cells_and_plan_order() -> None:
    assert A.CELLS == (("v3", "off"), ("v3", "on"), ("v5", "off"), ("v5", "on"))
    assert [A.CELL_LABEL[c][0] for c in A.CELLS] == ["①", "②", "③", "④"]
    rows = [{"id": f"q{i}"} for i in range(3)]
    runs = A.plan_runs(rows, 2)
    assert len(runs) == 3 * 2 * 2                                             # 문항 x 묶음 x 반복
    assert [r["run_id"] for r in runs[:6]] == ["q0|v3|r1", "q0|v5|r1", "q1|v3|r1", "q1|v5|r1", "q2|v3|r1", "q2|v5|r1"]   # 반복 회차가 바깥
    assert {r["rep"] for r in runs[6:]} == {2}


# --------------------------------------------------------------------------- 프롬프트 묶음
@needs_dict
def test_prompt_arms_build_distinct_deps() -> None:
    from langchain_core.messages import AIMessage

    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel
    from app.agent.graph.wiring import build_tool_context

    dd = _dd()
    ctx = build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=U._empty_conn)

    def deps(arm: str, **kw: Any) -> Any:
        return A.build_arm_deps(dd, ctx, A.ARM_BY_NAME[arm], tool_model=ScriptedToolModel(script=[AIMessage("x")]), summary_model=ScriptedSummary([{"sentences": []}]), **kw)

    d3, d5, d5s = deps("v3"), deps("v5"), deps("v5", v5_system="same")
    assert "같은 말을 두 번 쓰지 않는다" not in d3.summary_instruction and "같은 말을 두 번 쓰지 않는다" in d5.summary_instruction
    assert "약 사용 경험을 묻거나 부추기지 않는다" not in d3.system_prompt and "약 사용 경험을 묻거나 부추기지 않는다" in d5.system_prompt   # agent_system@v3(draft)
    assert d5s.system_prompt == d3.system_prompt and d5s.summary_instruction == d5.summary_instruction                 # same: 요약 프롬프트만 v5
    assert d3.summary_dedupe is d5.summary_dedupe is False                                                          # 끔 그래프
    assert A.resolve_prompts(A.ARM_BY_NAME["v5"])["system"] == "agent_system@v3"
    assert A.resolve_prompts(A.ARM_BY_NAME["v5"], v5_system="same")["system"] == "agent_system@v2"
    assert A.prompt_status("answer_summary@v2") == "draft" and A.prompt_status("answer_summary@v1") == "adopted"


# --------------------------------------------------------------------------- 켬 오프라인 적용 = 그래프 후처리
@needs_dict
@pytest.mark.parametrize("rid", ["u30-dup-001", "u30-dup-002", "u30-dup-003", "u30-dup-004", "u30-nodup-005", "u30-nodup-006", "u30-three-007"])
def test_offline_on_equals_graph_dedupe_path(rid: str) -> None:
    dd = _dd()
    row = next(r for r in U.load_aux() if r["id"] == rid)
    out = _fake_graph_outcome(dd, row, "v3", _sents(row))
    assert out.state["answer"]["summary"] == U.observe_graph(row, dd, dedupe=False)["summary"]       # 끔 = 이전 동작
    assert out.on_answer["summary"] == U.observe_graph(row, dd, dedupe=True)["summary"]              # 켬(오프라인) = 켠 채 돌린 실제 그래프 결과
    assert out.replay_equal is True and out.replay_summary_equal is True                             # 끔 finalize 재적용이 원래 응답과 같다
    f = A.outcome_fields(row, out)
    assert f["on_consistent"] is True and f["fixed_fields_equal"] is True
    assert f["cells"]["on"]["n_sentences"] <= f["cells"]["off"]["n_sentences"]                       # 켬은 줄이거나 같다
    assert f["lost_required"] == []                                                                  # 안전 문구를 깎지 않는다
    assert f["n_dropped"] == row["expected"]["n_dropped"]
    assert f["cells"]["on"]["dup"] is False and f["cells"]["on"]["unsafe"] == []
    if row["kind"] == "dup_pair":
        assert f["cells"]["off"]["dup"] is True and f["summary_changed"] is True                     # 끔은 중복이 남고 켬이 지운다
    else:
        assert f["summary_changed"] is False


@needs_dict
def test_clarify_path_summary_unchanged_and_not_measurable() -> None:
    dd = _dd()
    row = next(r for r in U.load_aux() if r["id"] == "u30-text-008")                                  # 파일 사전에 없는 약 이름: Router 되묻기
    out = _fake_graph_outcome(dd, row, "v3", _sents(row))
    f = A.outcome_fields(row, out)
    assert f["end_reason"] != "NORMAL" and f["cells"]["off"]["n_sentences"] == 0 and f["cells"]["on"]["n_sentences"] == 0
    assert f["summary_changed"] is False and f["n_dropped"] == 0 and f["summary_on"] == f["summary_off"] and f["fixed_fields_equal"] is True


def test_lost_required_phrase_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import summary_dedupe as sd

    def drop_last(sentences: Any, *, n_drugs: Any = None) -> Any:       # 실제 함수는 약사 확인만 있는 문장을 지우지 않는다: 손실 검출 로직만 보려고 마지막 문장을 지우는 가짜로 바꾼다
        return sd.DedupeResult(sentences=list(sentences)[:-1], dropped=[sd.Dropped(len(sentences) - 1, 0, ("PHARMACIST",))])

    monkeypatch.setattr(sd, "dedupe_sentences", drop_last)
    out = _synthetic_outcome(f"{NL1} {DISC} {PHARM}", f"{NL1} {DISC}", [NL1, DISC, PHARM], [NL1, DISC], dropped=1)
    f = A.outcome_fields(ROW, out)
    assert f["lost_required"] == ["PHARMACIST"]                                                       # 후처리 전후 비교로 안전 문구 손실을 잡는다


def test_inconsistent_on_detected_when_event_and_function_disagree() -> None:
    out = _synthetic_outcome(f"{NL1} {NL2}", f"{NL1} {NL2}", [NL1, NL2], [NL1, NL2], dropped=0, events_dropped=3)
    assert A.outcome_fields(ROW, out)["on_consistent"] is False


def test_unsafe_text_counted_in_cell() -> None:
    out = _synthetic_outcome("하루 3번 500mg 드세요. 이 조합은 안전합니다.", "하루 3번 500mg 드세요. 이 조합은 안전합니다.", ["하루 3번 500mg 드세요.", "이 조합은 안전합니다."])
    f = A.outcome_fields(ROW, out)
    assert f["cells"]["off"]["unsafe"] and S.SAFE_ASSERTION in f["cells"]["on"]["unsafe"]


def test_emergency_and_non_normal_invariants_in_aggregate() -> None:
    changed = A.outcome_fields(ROW, _synthetic_outcome(f"{NL1} {NL2}", NL1, [NL1, NL2], [NL1], dropped=1, emergency=True))
    clar = A.outcome_fields(ROW, _synthetic_outcome("되묻기 질문", "되묻기 질문", [], [], end_reason="CLARIFY"))
    recs = [{"status": "ok", "arm": "v3", "id": "a", **changed}, {"status": "ok", "arm": "v3", "id": "b", **clar}]
    x = A.aggregate(recs)["arms"]["v3"]
    assert x["emergency_runs"] == 1 and x["emergency_changed"] == 1 and x["non_normal_runs"] == 1 and x["non_normal_changed"] == 0
    assert x["applied_runs"] == 1 and x["dropped_sum"] == 1 and x["lost_runs"] == 0


def test_aggregate_counts_and_wilson() -> None:
    def rec(arm: str, rid: str, off_dup: bool, on_dup: bool) -> dict[str, Any]:
        cell = lambda dup: {"n_sentences": 3, "dup": dup, "dup_excess": 1 if dup else 0, "n_disclaimer": 1, "n_pharmacist": 1, "unsafe": [], "classes": []}  # noqa: E731
        return {"status": "ok", "arm": arm, "id": rid, "cells": {"off": cell(off_dup), "on": cell(on_dup)}, "n_dropped": int(off_dup and not on_dup),
                "end_reason": "NORMAL", "on_consistent": True, "summary_off": rid}

    agg = A.aggregate([rec("v3", "a", True, False), rec("v3", "b", False, False), rec("v5", "a", False, False), rec("v5", "b", False, False)])
    assert agg["cells"]["v3|off"]["nodup"]["k"] == 1 and agg["cells"]["v3|off"]["nodup"]["n"] == 2
    assert agg["cells"]["v3|on"]["nodup"]["k"] == 2 and agg["cells"]["v5|off"]["nodup"]["k"] == 2
    assert agg["cells"]["v3|off"]["dup_excess_sum"] == 1 and agg["cells"]["v3|off"]["items_all_nodup"] == {"k": 1, "n": 2}
    lo, hi = agg["cells"]["v3|off"]["nodup"]["wilson"]
    assert 0 < lo < 0.5 < hi < 1
    assert agg["per_item"]["a"]["v3|off"] == [1, 1] and agg["per_item"]["a"]["v3|on"] == [0, 1]


# --------------------------------------------------------------------------- 비용 통제
def _plan_runs(n: int) -> list[dict[str, Any]]:
    return A.plan_runs([{"id": f"q{i}", "kind": "dup_pair", "question": f"질문{i}", "expected": {"max_not_listed_sentences": 1}} for i in range(n)], 1)


def _plain_runner(ledger: Any, cost: float, seen: list[str] | None = None):
    def run(arm: str, row: Any) -> A.Outcome:
        if seen is not None:
            seen.append(f"{row['id']}|{arm}")
        ledger.guard(0.00075)
        ledger.add(cost)
        return _synthetic_outcome(f"{NL1} {DISC}", f"{NL1} {DISC}", [NL1, DISC])

    return run


def test_precheck_stops_when_measured_total_plus_bound_exceeds_cap(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, run_cap=0.10)
    seen: list[str] = []
    res = A.execute_runs(_plan_runs(8), runner=_plain_runner(ledger, 0.02, seen), ledger=ledger, per_item_bound=0.006, run_cap=0.10, say=lambda s: None)
    assert len(seen) == 5                                                  # 0.02 x 5 = 0.10, 6번째는 0.10 + 0.006 > 0.10
    assert [r["status"] for r in res] == ["ok"] * 5 + ["not_run"] * 11
    assert ledger.run_spent == pytest.approx(0.10)
    assert all(r["real_call"] is False and r["cost_usd"] == 0.0 for r in res[5:])


def test_in_flight_guard_marks_rest_not_run(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, run_cap=0.10)
    seen: list[str] = []
    res = A.execute_runs(_plan_runs(4), runner=_plain_runner(ledger, 0.0996, seen), ledger=ledger, per_item_bound=0.0001, run_cap=0.10, say=lambda s: None)
    assert len(seen) == 2 and res[0]["status"] == "ok"                    # 두 번째: 사전 점검 0.0996+0.0001은 통과하지만 guard(0.00075)에서 상한 초과
    assert res[1]["status"] == "budget_stop" and all(r["status"] == "not_run" for r in res[2:])


def test_dev_ledger_precheck(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, spent=2.499, cap=2.5)
    seen: list[str] = []
    res = A.execute_runs(_plan_runs(2), runner=_plain_runner(ledger, 0.001, seen), ledger=ledger, per_item_bound=0.006, run_cap=0.10, say=lambda s: None)
    assert seen == [] and all(r["status"] == "not_run" for r in res)


def test_error_recorded_without_retry_and_continues(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    seen: list[str] = []

    def run(arm: str, row: Any) -> A.Outcome:
        seen.append(f"{row['id']}|{arm}")
        if len(seen) == 1:
            raise RuntimeError("일시 오류")
        ledger.add(0.001)
        return _synthetic_outcome(NL1, NL1, [NL1])

    res = A.execute_runs(_plan_runs(2), runner=run, ledger=ledger, per_item_bound=0.006, run_cap=0.10, say=lambda s: None)
    assert seen == ["q0|v3", "q0|v5", "q1|v3", "q1|v5"]                    # 같은 항목 재시도 없음
    assert [r["status"] for r in res] == ["error", "ok", "ok", "ok"]


# --------------------------------------------------------------------------- main
def test_run_cap_above_approved_limit_is_rejected(tmp_path: Path) -> None:
    called: list[str] = []
    out: list[str] = []
    rc = A.main(["--yes", "--run-cap", "0.11", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), say=out.append)
    assert rc == 5 and called == [] and not (tmp_path / "o").exists() and "0.1" in "\n".join(out)
    assert A.main(["--yes", "--run-cap", "0.45"], runner_factory=_runner_factory(calls=called), say=lambda s: None) == 5
    assert A.main(["--per-item-bound", "0.2"], say=lambda s: None) == 5    # 항목당 점검 상한은 상한 이하여야 한다
    assert A.main(["--repeats", "0"], say=lambda s: None) == 5
    assert called == []


@needs_dict
def test_dry_run_makes_zero_calls_and_writes_nothing(tmp_path: Path) -> None:
    called: list[str] = []
    out: list[str] = []
    rc = A.main(["--out-dir", str(tmp_path / "o"), "--report-md", str(tmp_path / "r.md"), "--smoke-dir", str(tmp_path / "none")],
                runner_factory=_runner_factory(calls=called), ledger_inner=_ledger(tmp_path).inner, say=out.append)
    text = "\n".join(out)
    assert rc == 0 and called == []
    assert "DRY-RUN" in text and "실행 32회" in text and "예상 비용" in text and "최악 합계 보장이 아니다" in text and "prompt_set@v5" in text
    assert "모델 경로 문항 7개" in text and "u30-text-008" in text            # 파일 사전에서는 사용자 사례가 되묻기로 끝난다는 경고
    assert not (tmp_path / "o").exists() and not (tmp_path / "r.md").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ledger.json"] or not list(tmp_path.glob("*.jsonl"))


@needs_dict
def test_dry_run_flag_wins_over_yes(tmp_path: Path) -> None:
    called: list[str] = []
    rc = A.main(["--dry-run", "--yes", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), ledger_inner=_ledger(tmp_path).inner, say=lambda s: None)
    assert rc == 0 and called == [] and not (tmp_path / "o").exists()


@needs_dict
def test_main_refuses_eval_mode_dev_limit_and_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: list[str] = []
    for d in ("b", "c"):
        (tmp_path / d).mkdir()
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.delenv("LLM_CACHE", raising=False)
    rc = A.main(["--yes", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), ledger_inner=_ledger(tmp_path, spent=2.45).inner, say=lambda s: None)
    assert rc == 3 and called == []                                                           # 개발 한도 초과 예상
    monkeypatch.setenv("LLM_CACHE", "record")
    rc = A.main(["--yes", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), ledger_inner=_ledger(tmp_path / "b").inner, say=lambda s: None)
    assert rc == 6 and called == []                                                           # 캐시가 켜지면 반복이 의미 없다
    monkeypatch.delenv("LLM_CACHE")
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    rc = A.main(["--yes", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), ledger_inner=_ledger(tmp_path / "c").inner, say=lambda s: None)
    assert rc == 4 and called == [] and not (tmp_path / "o").exists()


@needs_dict
def test_main_stops_when_price_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom() -> S.Prices:
        raise S.PriceUnavailable("PRICE_OUT 없음")

    monkeypatch.setattr(S, "load_prices", boom)
    called: list[str] = []
    assert A.main(["--yes", "--out-dir", str(tmp_path / "o")], runner_factory=_runner_factory(calls=called), say=lambda s: None) == 2
    assert called == [] and not (tmp_path / "o").exists()


@needs_dict
def test_main_run_writes_results_and_summary_without_bodies_or_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.delenv("LLM_CACHE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    calls: list[str] = []
    out: list[str] = []
    argv = ["--yes", "--out-dir", str(tmp_path / "o"), "--report-md", str(tmp_path / "r.md")]
    rc = A.main(argv, runner_factory=_runner_factory(calls=calls, boom_first=True), ledger_inner=_ledger(tmp_path).inner, today=dt.date(2026, 11, 24), say=out.append)
    assert rc == 0 and len(calls) == 32                                                       # 8문항 x 2묶음 x 2반복
    files = list((tmp_path / "o").glob("20261124-ag-u30-real*.jsonl"))
    assert [f.name for f in files] == ["20261124-ag-u30-real.jsonl"]
    text = files[0].read_text(encoding="utf-8")
    recs = [json.loads(line) for line in text.splitlines()]
    assert len(recs) == 32 and {r["status"] for r in recs} == {"ok", "error"}
    assert SECRET not in text and "[REDACTED]" in text
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    blob = md + "\n".join(out)
    assert SECRET not in blob and ("s" + "k-test") not in blob
    for r in U.load_aux():                                                                    # 요약 md·출력에 질문·응답 본문이 없다(문항 ID는 있다)
        assert r["question"] not in blob
        assert all(s["text"] not in blob for s in r["fake_sentences"])
        assert f"`{r['id']}`" in md or r["id"] == "u30-text-008"
    assert "① v3+끔" in md and "④ v5+켬" in md and "Wilson" in md and "유의성을 주장하지 않는다" in md and "최악 합계 보장이 아님" in md
    assert any(r["id"] == "u30-text-008" and r["status"] == "ok" and r["cells"]["off"]["n_sentences"] == 0 for r in recs)   # 되묻기 문항은 측정 불가로 기록
    # 같은 날 다시 실행하면 -2로 만든다(덮어쓰지 않는다)
    (tmp_path / "second").mkdir()
    rc = A.main(argv, runner_factory=_runner_factory(), ledger_inner=_ledger(tmp_path / "second").inner, today=dt.date(2026, 11, 24), say=lambda s: None)
    assert rc == 0 and (tmp_path / "o" / "20261124-ag-u30-real-2.jsonl").exists() and (tmp_path / "r-2.md").exists()


@needs_dict
def test_main_stops_at_cap_and_records_not_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.delenv("LLM_CACHE", raising=False)
    calls: list[str] = []
    rc = A.main(["--yes", "--out-dir", str(tmp_path / "o"), "--report-md", str(tmp_path / "r.md")], runner_factory=_runner_factory(cost_each=0.02, calls=calls),
                ledger_inner=_ledger(tmp_path).inner, today=dt.date(2026, 11, 24), say=lambda s: None)
    assert rc == 0 and len(calls) == 5                                                        # 0.02 x 5 = 0.10 -> 6번째부터 사전 점검에서 중단
    recs = [json.loads(line) for line in (tmp_path / "o" / "20261124-ag-u30-real.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in recs].count("not_run") == 27 and "미실행 27회" in (tmp_path / "r.md").read_text(encoding="utf-8")
