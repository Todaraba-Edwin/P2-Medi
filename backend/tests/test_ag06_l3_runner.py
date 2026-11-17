"""AG-06 L3 실행기 시험(goal 6회차): 연속 오류 중단(AG-06-09 A), 개발 안전 핵심 부분집합, 반복 실행의 `pass^3`·`pass@3`·일치율과 비교 출력.

LLM·judge·공공 API·원격 DB 호출 0, `.env` 미사용. 그래프는 가짜(스크립트 결과)이고 문항은 합성이다(평가 세트 문항 아님).
개발셋은 표시 수만 센다(질문 문장을 읽거나 출력하지 않는다). 시험셋 파일은 열지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation"))

import eval_metrics as M  # noqa: E402
import eval_runner as R  # noqa: E402

PH = M.Phrases.from_backend()
OK = "ok"          # 정상 종료(답 있음)
BOOM = "boom"      # 예외
EMPTY = "empty"    # 예외는 없는데 답이 비어 있음
BLOCK = "block"    # 하네스 차단(검증 두 번 실패 → 코드 문구 답)
REFUSE = "refuse"  # 범위 밖 거절(코드 문구 답)


class ScriptGraph:
    """문항 순서대로 정해 둔 결과를 내는 가짜 그래프. 모델·도구를 부르지 않는다."""

    def __init__(self, script: list[str]) -> None:
        self.script, self.i = script, 0

    def invoke(self, state: Any) -> dict[str, Any]:
        kind = self.script[self.i % len(self.script)]
        self.i += 1
        if kind == BOOM:
            raise RuntimeError("가짜 실행 오류")
        if kind == EMPTY:
            return {"answer": {}, "end_reason": None, "events": []}
        if kind == BLOCK:
            return {"answer": {"summary": "코드 문구"}, "end_reason": "VALIDATION_FALLBACK",
                    "events": [{"rule": "H2", "event": "VALIDATION_FALLBACK", "reasons": ["X"]}]}
        if kind == REFUSE:
            return {"answer": {"summary": "코드 문구"}, "end_reason": "REFUSE", "events": []}
        return {"answer": {"summary": "안내"}, "end_reason": "NORMAL", "events": []}


def _items(n: int) -> list[dict[str, Any]]:
    return [{"id": f"syn-{i:03d}", "question": "합성 질문", "branch_label": "병용", "composition_group": "정상-병용",
             "expected_response_type": "found", "required_elements": [], "expected_path": {}, "answer": {"items": []}} for i in range(n)]


def _run(script: list[str], n: int, **kw: Any) -> tuple[dict[str, Any], ScriptGraph]:
    g = ScriptGraph(script)
    res = R.run_eval(_items(n), R.GraphAdapter(g), sealed=kw.pop("sealed", False), phrases=PH, skip_judge=True,
                     max_consecutive_errors=kw.pop("max_consecutive_errors", R.MAX_CONSECUTIVE_ERRORS), **kw)
    return res, g


# =========================================================================== 1. 연속 오류 중단(AG-06-09 A)
def test_three_consecutive_errors_stop_the_run_and_record_where(tmp_path):
    res, g = _run([OK, BOOM, BOOM, BOOM, OK, OK], 6)
    assert g.i == 4  # 네 번째 문항(연속 3번째 오류)에서 멈추고 남은 문항은 부르지 않는다
    assert [r["id"] for r in res["items"]] == ["syn-000", "syn-001", "syn-002", "syn-003"]
    st = res["stopped"]
    assert st["reason"] == R.STOP_CONSECUTIVE_ERRORS == "CONSECUTIVE_ERRORS" and st["threshold"] == 3 == R.MAX_CONSECUTIVE_ERRORS
    assert st["run"] == 1 and st["index"] == 3 and st["item_id"] == "syn-003" and st["skipped"] == 2
    assert st["errors"] == ["RuntimeError"] * 3
    assert res["skipped_error_stop"] == ["syn-004", "syn-005"]
    assert res["errors"] == {"items": 3, "total": 3}
    assert res["metrics"]["n_items"] == 4
    json.dumps(res, ensure_ascii=False, default=str)  # 결과 파일로 쓸 수 있다


def test_a_success_between_errors_resets_the_streak():
    res, g = _run([BOOM, BOOM, OK, BOOM, BOOM, OK, BOOM, OK], 8)
    assert g.i == 8 and "stopped" not in res and "skipped_error_stop" not in res
    assert res["errors"] == {"items": 5, "total": 5} and len(res["items"]) == 8


def test_harness_blocks_and_refusals_are_not_errors():
    """하네스 차단·거절은 코드가 만든 답으로 끝난 정상 종료다(오류로 세지 않고, 오류 연속도 끊는다)."""
    res, g = _run([BLOCK, BLOCK, BLOCK, REFUSE, BLOCK], 5)
    assert g.i == 5 and "stopped" not in res and res["errors"] == {"items": 0, "total": 0}
    assert [r["aux"]["harness_blocks"] for r in res["items"]] == [1, 1, 1, 0, 1]
    res, g = _run([BOOM, BOOM, BLOCK, BOOM, BOOM, REFUSE], 6)
    assert g.i == 6 and "stopped" not in res and res["errors"]["items"] == 4


def test_empty_answer_without_exception_counts_as_error():
    res, g = _run([EMPTY, BOOM, EMPTY, OK], 4)
    assert g.i == 3 and res["stopped"]["errors"] == ["NO_ANSWER", "RuntimeError", "NO_ANSWER"]


def test_is_item_error_reads_only_error_and_answer():
    assert R.is_item_error(M.RunRecord(answer={}, error="X")) and R.is_item_error(M.RunRecord(answer={}))
    assert not R.is_item_error(M.RunRecord(answer={"summary": "s"}, end_reason="VALIDATION_FALLBACK", harness_blocks=1))
    assert not R.is_item_error(M.RunRecord(answer={"summary": "s"}, end_reason="LIMIT"))


def test_streak_carries_across_repeats_and_later_runs_are_skipped():
    # 1회차: OK OK BOOM / 2회차: BOOM BOOM → 회차 경계를 넘어 3건 연속
    res, g = _run([OK, OK, BOOM, BOOM, BOOM, OK, OK, OK, OK], 3, repeats=3)
    assert g.i == 5
    st = res["stopped"]
    assert st["run"] == 2 and st["index"] == 1 and st["item_id"] == "syn-001" and st["skipped"] == 4  # 2회차 1개 + 3회차 3개
    assert res["skipped_error_stop"] == []  # 1회차는 끝까지 돌았다
    assert res["errors"] == {"items": 1, "total": 3}
    assert res["reliability"]["items"] == 0  # 3회를 다 채운 문항이 없다


def test_sealed_result_keeps_position_but_not_item_ids():
    res, _ = _run([BOOM], 5, sealed=True)
    assert "item_id" not in res["stopped"] and res["stopped"]["index"] == 2 and res["skipped_error_stop"] == 2


def test_without_the_option_nothing_stops_and_no_new_keys():
    g = ScriptGraph([BOOM])
    res = R.run_eval(_items(5), R.GraphAdapter(g), sealed=False, phrases=PH)
    assert g.i == 5 and not {"stopped", "skipped_error_stop", "errors"} & set(res)


class _Res:
    def __init__(self, script: list[str]) -> None:
        self.graph = ScriptGraph(script)
        self.total = 0.0


def _cli(tmp_path: Path, monkeypatch: Any, script: list[str], n: int, *extra: str) -> tuple[int, dict[str, Any], ScriptGraph]:
    """CLI를 가짜 그래프로 돈다(자원 생성·그래프 조립을 가짜로 바꾼다. 설정은 이름만 채운 가짜)."""
    from app.config import Settings

    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    g = ScriptGraph(script)

    class FakeAgent(R.GraphAdapter):
        def __init__(self, resources: Any, *, info: dict[str, Any] | None = None) -> None:
            super().__init__(g, info=info)

    monkeypatch.setattr(R, "GraphAgent", FakeAgent)
    p = tmp_path / "synth.jsonl"
    rows = [{**it, "set": "dev", "set_version": "synth", "dev_reliability_core": i % 2 == 0, "dev_golden": False} for i, it in enumerate(_items(n))]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    out = tmp_path / "out.json"
    rc = R.main(["--set", str(p), "--agent", "graph", "--max-usd", "1", "--out", str(out), *extra],
                settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d"),
                resources_factory=lambda settings, **kw: R.GraphResources(deps=None, cost_total=lambda: 0.0))
    return rc, json.loads(out.read_text(encoding="utf-8")), g


def test_graph_cli_stops_after_three_consecutive_errors_by_default(tmp_path, monkeypatch, capsys):
    rc, res, g = _cli(tmp_path, monkeypatch, [OK, BOOM, BOOM, BOOM, OK], 6)
    assert rc == 0 and g.i == 4 and res["stopped"]["item_id"] == "syn-003" and res["skipped_error_stop"] == ["syn-004", "syn-005"]
    printed = capsys.readouterr().out
    assert "연속 오류" in printed and "syn-003" in printed


def test_offline_fixed_cli_result_has_no_stop_keys(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps({**it, "set": "dev"}, ensure_ascii=False) for it in _items(2)) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    assert R.main(["--set", str(p), "--out", str(out)]) == 0
    assert set(json.loads(out.read_text(encoding="utf-8"))) == {"meta", "metrics", "items"}


# =========================================================================== 2. 개발 안전 핵심 부분집합·반복 지표
def test_dev_reliability_core_subset_selects_the_40_marked_dev_rows():
    rows = [json.loads(x) for x in (ROOT / "evaluation" / "eval_set" / "dev_set.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    picked = R.select_subset(rows, "dev_reliability_core")
    assert len(picked) == 40 and all(r["set"] == "dev" for r in picked)
    by_type: dict[str, int] = {}
    for r in picked:
        by_type[r["expected_response_type"]] = by_type.get(r["expected_response_type"], 0) + 1
    assert by_type == {"emergency": 10, "not_listed": 10, "correct": 20}  # 응급 10·목록에 없는 약 10·오정보 20(5장 (2))
    assert set(R.SUBSETS) == {"dev_golden", "dev_reliability_core"}  # 시험셋 표시(`reliability_core`·`golden`)는 고르지 않는다
    with pytest.raises(R.RunnerConfigError):
        R.select_subset(rows, "reliability_core")


def test_cli_subset_and_repeats_put_reliability_in_the_result(tmp_path, monkeypatch):
    rc, res, g = _cli(tmp_path, monkeypatch, [OK], 6, "--subset", "dev_reliability_core", "--repeats", "3")
    assert rc == 0 and g.i == 9 and res["meta"]["subset"] == "dev_reliability_core" and res["meta"]["repeats"] == 3
    rel = res["reliability"]
    assert rel["repeats"] == 3 and rel["items"] == 3 and {"pass^k", "pass@k", "judgment_agreement", "pass^k_code_part", "pass@k_code_part"} <= set(rel)


def _row(qid: str, *, safety: dict[str, Any] | None, verdict: str = "Pass", got: str = "found") -> dict[str, Any]:
    return {"id": qid, "safety": safety, "trajectory": {"verdict": verdict},
            "judgment": {"applicable": True, "correct": True, "items": [{"evidence_id": "e", "got": got, "got_grades": ["1"]}]}}


def test_reliability_follows_the_definition_and_reports_code_part_separately():
    """§7.7: 성공 = 안전 응답 확정 통과 + 판정 정답 + 경로 Pass/Warn. judge 보류 문항은 정의대로는 미정이고, 코드 요소만 본 값은 따로 낸다."""
    ok = {"code_pass": True, "pending_judge": [], "pass": True}
    pend = {"code_pass": True, "pending_judge": ["J4"], "pass": None}
    pend_bad = {"code_pass": False, "pending_judge": ["J4"], "pass": False}
    runs = [
        [_row("a", safety=ok), _row("b", safety=ok), _row("c", safety=pend), _row("d", safety=pend), _row("e", safety=None)],
        [_row("a", safety=ok), _row("b", safety=ok, verdict="Fail"), _row("c", safety=pend), _row("d", safety=pend_bad), _row("e", safety=None, got="nl")],
        [_row("a", safety=ok), _row("b", safety=ok, verdict="Warn"), _row("c", safety=pend), _row("d", safety=pend), _row("e", safety=None)],
    ]
    rel = M.reliability(runs)
    assert rel["repeats"] == 3 and rel["items"] == 5 and rel["undecided_pending_judge"] == 2  # c·d는 judge 없이는 정할 수 없다
    assert rel["pass^k"] == M.kn(2, 3) and rel["pass@k"] == M.kn(3, 3) and rel["unstable_items"] == ["b"]  # a·e 모두 성공, b는 1회 실패
    assert rel["judgment_agreement"] == M.kn(4, 5)  # e는 판정이 한 번 달랐다
    assert rel["pass^k_code_part"] == M.kn(3, 5) and rel["pass@k_code_part"] == M.kn(5, 5)  # a·c·e / 전부
    assert rel["unstable_items_code_part"] == ["b", "d"] and "judge" in rel["code_part_note"]


# =========================================================================== 3. 비교 출력
def _result(label: str, n: int, *, rel: dict[str, Any] | None = None, fallback: int = 0, errors: int = 0, stopped: bool = False) -> dict[str, Any]:
    items = []
    for i in range(n):
        end = "VALIDATION_FALLBACK" if i < fallback else "NORMAL"
        fails = ["RUN_ERROR"] if n - errors <= i else []
        items.append({"id": f"dev-{i:03d}", "trajectory": {"verdict": "Fail" if fails else "Pass", "end_reason": end, "fails": fails},
                      "aux": dict.fromkeys(M.AUX_FIELDS, 0)})
    res: dict[str, Any] = {"meta": {"versions": {"prompt": {"set": label}}}, "items": items, "cost_usd": {"total": 0.01},
                           "metrics": {"n_items": n, "contra_judgment_accuracy": {**M.kn(n - 1, n), "by_group": {}, "target": "t"}}}
    if rel is not None:
        res["reliability"] = rel
    if stopped:
        res["stopped"] = {"reason": R.STOP_CONSECUTIVE_ERRORS, "threshold": 3, "run": 1, "index": n - 1, "skipped": 7}
    return res


def test_compare_shows_reliability_judgment_fallback_and_stop():
    rel_a = {"repeats": 3, "items": 40, "pass^k": M.kn(8, 10), "pass@k": M.kn(10, 10), "undecided_pending_judge": 30, "unstable_items": ["x"],
             "judgment_agreement": M.kn(40, 40), "pass^k_code_part": M.kn(30, 40), "pass@k_code_part": M.kn(36, 40)}
    rel_b = {**rel_a, "pass^k": M.kn(7, 10), "pass^k_code_part": M.kn(28, 40)}
    cmp = R.compare_results(_result("prompt_set@v2", 10, rel=rel_a, fallback=2), _result("prompt_set@v3", 10, rel=rel_b, errors=3, stopped=True))
    sa, sb = cmp["sides"]
    assert sa["pass_all"] == M.kn(8, 10) and sb["pass_all"] == M.kn(7, 10) and sa["pass_any"] == M.kn(10, 10)
    assert sa["pass_all_code_part"] == M.kn(30, 40) and sb["pass_all_code_part"] == M.kn(28, 40) and sa["pass_any_code_part"] == M.kn(36, 40)
    assert sa["judgment_agreement"] == M.kn(40, 40) and sa["repeats"] == 3 and sa["undecided_pending_judge"] == 30
    assert sa["contra_judgment"] == M.kn(9, 10) and sa["validation_fallback"] == 2 and sb["validation_fallback"] == 0
    assert sa["run_errors"] == 0 and sb["run_errors"] == 3 and sa["stopped"] is None and "CONSECUTIVE_ERRORS" in sb["stopped"]
    text = R.format_compare(cmp)
    for needle in ("pass^3", "pass@3", "판정 일치율", "금기 판정", "VALIDATION_FALLBACK", "오류 문항", "중단", "8/10", "7/10", "30/40", "28/40"):
        assert needle in text
    assert "개선됐" not in text and "향상" not in text and "채택" not in text  # 판정하지 않고 값만 나란히 둔다


def test_compare_without_repeats_leaves_reliability_cells_empty():
    cmp = R.compare_results(_result("prompt_set@v2", 4), _result("prompt_set@v3", 4))
    assert all(s["pass_all"] is None and s["repeats"] is None and s["judgment_agreement"] is None for s in cmp["sides"])
    assert "pass^k" in R.format_compare(cmp)


def test_end_reason_name_matches_the_graph_code():
    from app.agent.graph import state

    assert R.END_FALLBACK == state.END_FALLBACK == "VALIDATION_FALLBACK"
