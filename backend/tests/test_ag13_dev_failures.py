"""AG-13 개발셋 실패 표 시험(AG-13-02 A, 2026-11-18). 합성 결과 행만 쓴다(LLM·원격·실데이터 0)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "evaluation") not in sys.path:
    sys.path.insert(0, str(ROOT / "evaluation"))

import dev_failures as D  # noqa: E402
import sealed_guard  # noqa: E402


def _row(iid: str = "dev-001", *, ert: str = "judgment", branch: str = "정상", group: str = "정상-임부",
         verdict: str = "Pass", fails: list[str] | None = None, warns: list[str] | None = None, end: str = "NORMAL",
         elements: dict[str, Any] | None = None, safety: dict[str, Any] | None = None, judgment: dict[str, Any] | None = None,
         judge: Any = None, aux: dict[str, int] | None = None, hallucinated: list[str] | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "id": iid, "expected_response_type": ert, "branch_label": branch, "composition_group": group,
        "trajectory": {"verdict": verdict, "fails": fails or [], "warns": warns or [], "end_reason": end,
                       "hallucinated_citations": hallucinated or [], "model_calls": 3},
        "elements": elements or {}, "safety": safety, "judgment": judgment, "judge": judge,
        "aux": {"no_evidence_dropped": 0, "uncited_fact_sentences": 0, "quote_mismatch": 0, "harness_blocks": 0, **(aux or {})},
        "run": {"answer": {"text": "원문은 표에 들어가면 안 된다"}, "error": error, "end_reason": end},
    }


def _result(rows: list[dict[str, Any]], *, set_: str = "dev", sealed: bool = False, repeats: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"meta": {"set": set_, "sealed": sealed, "condition": "C2", "repeats": 1 + len(repeats or []),
                                  "trajectory_rule": "traj@v2", "prompt_set": "prompt_set@v3"}, "items": rows}
    if repeats is not None:
        d["items_repeats"] = repeats
    return d


def _cls(**kw: Any) -> list[str]:
    return D.classify(D.normalize(_row(**kw), source="t", run=1))


# --------------------------------------------------------------------------- 규칙 상수 고정


def test_rule_keys_and_order_fixed() -> None:
    assert [r.key for r in D.RULES] == [
        "RUN_ERROR", "ENTRY_MISS", "ENTRY_FALSE_REFUSE", "FAKE_DRUG_CLARIFY", "TYPO_CLARIFY", "EMERGENCY_CLARIFY",
        "OVER_CLARIFY", "OVERSEARCH_LIMIT", "PAIR_NOT_PARALLEL", "JUDGMENT_TOOL_SKIPPED", "PATH_VIOLATION",
        "VALIDATION_FALLBACK", "JUDGMENT_WRONG", "NOT_LISTED_BLUR", "EVIDENCE_GAP", "CLARIFY_FORMAT", "SAFETY_ELEMENT",
        "JUDGE_J1", "JUDGE_J2", "JUDGE_J3", "JUDGE_J4", "JUDGE_J5", "PATH_WARN_ONLY",
    ]
    assert D.RULESET_VERSION == "ag13-cause-rules@v1"


def test_every_rule_candidate_exists_and_memo_candidates_present() -> None:
    for r in (*D.RULES, D.UNCLASSIFIED):
        assert r.candidates, r.key
        for c in r.candidates:
            assert c in D.CANDIDATES, (r.key, c)
    # AG-13 §5 메모의 수기 후보가 분류 이름에 반영되어 있다
    for k in ("V3_PARALLEL_PROMPT", "PARALLEL_CODE", "V3_ENTRY_FEWSHOT", "H12_REPEAT_WARN", "JAMO_SIMILARITY",
              "ROUTER_CLASSIFIER", "AG06_BUNDLE_MAPREDUCE", "AG07_LAYER_MISSING", "GRADE_DEF_H23_H25", "H21_KNOWN_IDS"):
        assert k in D.CANDIDATES
    used = {c for r in (*D.RULES, D.UNCLASSIFIED) for c in r.candidates}
    assert used == set(D.CANDIDATES)  # 쓰이지 않는 후보가 없다


def test_judge_elements_mapping_comes_from_frozen_metrics() -> None:
    import eval_metrics as EM

    assert D.EM.JUDGE_ELEMENTS is EM.JUDGE_ELEMENTS


# --------------------------------------------------------------------------- 규칙별 분류


@pytest.mark.parametrize(("kw", "primary"), [
    ({"error": "boom", "fails": ["RUN_ERROR"], "verdict": "Fail"}, "RUN_ERROR"),
    ({"ert": "refuse", "end": "NORMAL", "fails": ["FORBIDDEN_CALLED"], "verdict": "Fail"}, "ENTRY_MISS"),
    ({"ert": "judgment", "end": "REFUSE"}, "ENTRY_FALSE_REFUSE"),
    ({"ert": "no_evidence", "end": "CLARIFY"}, "FAKE_DRUG_CLARIFY"),
    ({"ert": "judgment", "branch": "오탈자", "end": "CLARIFY", "fails": ["REQUIRED_MISSING", "JUDGMENT_TOOL_SKIPPED"], "verdict": "Fail"}, "TYPO_CLARIFY"),
    ({"ert": "emergency", "end": "CLARIFY", "fails": ["REQUIRED_MISSING"], "verdict": "Fail"}, "EMERGENCY_CLARIFY"),
    ({"ert": "correct", "end": "CLARIFY"}, "OVER_CLARIFY"),
    ({"ert": "correct", "end": "LIMIT", "fails": ["MODEL_CALL_LIMIT"], "verdict": "Fail"}, "OVERSEARCH_LIMIT"),
    ({"group": "정상-병용", "fails": ["REQUIRED_MISSING"], "verdict": "Fail"}, "PAIR_NOT_PARALLEL"),
    ({"elements": {"CONTRA_CHECK_PARALLEL": False}}, "PAIR_NOT_PARALLEL"),
    ({"fails": ["JUDGMENT_TOOL_SKIPPED"], "verdict": "Fail"}, "JUDGMENT_TOOL_SKIPPED"),
    ({"fails": ["UNIDENTIFIED_ITEM"], "verdict": "Fail"}, "PATH_VIOLATION"),
    ({"end": "VALIDATION_FALLBACK"}, "VALIDATION_FALLBACK"),
    ({"judgment": {"applicable": True, "correct": False, "items": [{"evidence_id": "contra_pair:A:B", "want": "found", "got": "not_listed", "ok": False}]}},
     "JUDGMENT_WRONG"),
    ({"ert": "not_listed", "elements": {"NOT_LISTED_DISTINCT": False}}, "NOT_LISTED_BLUR"),
    ({"aux": {"uncited_fact_sentences": 2}}, "EVIDENCE_GAP"),
    ({"hallucinated": ["x:1"], "fails": ["CITATION_NOT_FROM_TOOLS"], "verdict": "Fail"}, "EVIDENCE_GAP"),
    ({"ert": "clarify", "end": "CLARIFY", "elements": {"ONE_QUESTION": False}}, "CLARIFY_FORMAT"),
    ({"elements": {"NO_DOSE_DECISION": False}}, "SAFETY_ELEMENT"),
    ({"ert": "correct", "safety": {"code_pass": False, "pending_judge": [], "pass": False}}, "SAFETY_ELEMENT"),
    ({"judge": {"status": "ok", "rubrics": {"J1": {"status": "ok", "overall_pass": False}}}}, "JUDGE_J1"),
    ({"judge": {"status": "ok", "rubrics": {"J2": {"status": "ok", "overall_pass": False}}}}, "JUDGE_J2"),
    ({"ert": "correct", "judge": {"status": "ok", "rubrics": {}, "elements": {"PREMISE_CORRECTED": False}}}, "JUDGE_J3"),
    ({"ert": "refuse", "end": "REFUSE", "judge": {"status": "ok", "rubrics": {"J4": {"status": "ok", "overall_pass": False}}}}, "JUDGE_J4"),
    ({"ert": "no_evidence", "judge": {"status": "ok", "rubrics": {}, "elements": {"SAYS_NOT_FOUND": False}}}, "JUDGE_J5"),
    ({"warns": ["RECOMMENDED_MISSING", "EXTRA_TOOL"], "verdict": "Warn"}, "PATH_WARN_ONLY"),
])
def test_primary_cause(kw: dict[str, Any], primary: str) -> None:
    assert _cls(**kw)[0] == primary


def test_clean_pass_has_no_signal() -> None:
    x = D.normalize(_row(), source="t", run=1)
    assert not x.has_signal()
    assert x.signals() == {}


def test_expected_clarify_and_refuse_end_are_not_signals() -> None:
    assert not D.normalize(_row(ert="clarify", end="CLARIFY"), source="t", run=1).has_signal()
    assert not D.normalize(_row(ert="refuse", end="REFUSE"), source="t", run=1).has_signal()


def test_generic_rules_suppressed_by_specific() -> None:
    ks = _cls(ert="judgment", branch="오탈자", end="CLARIFY", warns=["RECOMMENDED_MISSING"])
    assert "OVER_CLARIFY" not in ks and "PATH_WARN_ONLY" not in ks and ks[0] == "TYPO_CLARIFY"
    ks = _cls(end="VALIDATION_FALLBACK", warns=["EXTRA_TOOL"])
    assert ks == ["VALIDATION_FALLBACK"]
    # 전용 규칙이 있는 요소는 SAFETY_ELEMENT로 중복 세지 않는다
    ks = _cls(ert="clarify", end="CLARIFY", elements={"ONE_QUESTION": False})
    assert "SAFETY_ELEMENT" not in ks


def test_unclassified_when_warn_code_unknown() -> None:
    assert _cls(warns=["NEW_WARN_CODE"], verdict="Warn") == ["UNCLASSIFIED"]


def test_judge_absent_or_not_called_falls_back_to_code_signals() -> None:
    for j in (None, {"status": "not_called", "reason": "JUDGE_BUDGET", "rubrics": {}}):
        x = D.normalize(_row(end="VALIDATION_FALLBACK", judge=j), source="t", run=1)
        assert x.judge_failed == () and D.classify(x)[0] == "VALIDATION_FALLBACK"


def test_judge_error_is_not_failure() -> None:
    x = D.normalize(_row(judge={"status": "ok", "rubrics": {"J1": {"status": "error", "overall_pass": None}}}), source="t", run=1)
    assert x.judge_failed == () and x.judge_errors == ("J1:error",)
    assert not x.has_signal()


def test_fail_only_drops_warn_only_rows() -> None:
    x = D.normalize(_row(warns=["RECOMMENDED_MISSING"], verdict="Warn"), source="t", run=1)
    assert x.has_signal() and not x.has_signal(fail_only=True)
    y = D.normalize(_row(fails=["REQUIRED_MISSING"], verdict="Fail"), source="t", run=1)
    assert y.has_signal(fail_only=True)


# --------------------------------------------------------------------------- 집계·원문 제외


def test_repeats_aggregate_per_item() -> None:
    r1 = [_row("dev-001", ert="correct", end="LIMIT", fails=["MODEL_CALL_LIMIT"], verdict="Fail"), _row("dev-002")]
    r2 = [_row("dev-001"), _row("dev-002")]
    r3 = [_row("dev-001", ert="correct", end="LIMIT", fails=["MODEL_CALL_LIMIT"], verdict="Fail"), _row("dev-002")]
    data = _result(r1, repeats=[{"run": 2, "items": r2}, {"run": 3, "items": r3}])
    rep = D.build_report([("x.json", data)])
    assert [r["id"] for r in rep["rows"]] == ["dev-001"]
    row = rep["rows"][0]
    assert (row["runs_flagged"], row["runs_total"]) == (2, 3)
    assert row["primary_cause"] == "OVERSEARCH_LIMIT"
    assert row["signals"]["path"] == {"MODEL_CALL_LIMIT": 2}
    assert row["candidates"][0] == "H12_REPEAT_WARN"
    assert rep["sources"][0]["n_runs"] == 3


def test_primary_tie_broken_by_priority() -> None:
    assert D._pick_primary(["VALIDATION_FALLBACK", "ENTRY_MISS"]) == "ENTRY_MISS"
    assert D._pick_primary(["VALIDATION_FALLBACK", "VALIDATION_FALLBACK", "ENTRY_MISS"]) == "VALIDATION_FALLBACK"


def test_outputs_have_no_answer_or_question_text(tmp_path: Path) -> None:
    rows = [_row("dev-001", end="VALIDATION_FALLBACK",
                 judge={"status": "ok", "rubrics": {"J1": {"status": "ok", "overall_pass": False,
                                                          "claims": [{"text": "주장 원문 비밀", "reason": "사유 원문"}]}}})]
    rows[0]["question"] = "질문 원문 비밀"
    p = tmp_path / "dev.json"
    p.write_text(json.dumps(_result(rows), ensure_ascii=False), encoding="utf-8")
    md, js = tmp_path / "o.md", tmp_path / "o.json"
    assert D.main([str(p), "--out-md", str(md), "--out-json", str(js)]) == 0
    for out in (md.read_text(encoding="utf-8"), js.read_text(encoding="utf-8")):
        for secret in ("질문 원문 비밀", "주장 원문 비밀", "사유 원문", "원문은 표에 들어가면 안 된다"):
            assert secret not in out
    assert "| dev-001 |" in md.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["schema"] == D.SCHEMA


def test_summary_top_candidates_exclude_observe() -> None:
    rows = [_row(f"dev-{i:03d}", warns=["RECOMMENDED_MISSING"], verdict="Warn") for i in range(5)]
    rows.append(_row("dev-100", ert="no_evidence", end="CLARIFY"))
    rep = D.build_report([("x.json", _result(rows))])
    assert "OBSERVE" not in rep["summary"]["top_candidates"]
    assert rep["summary"]["top_candidates"][0] == "JAMO_SIMILARITY"
    assert rep["summary"]["by_primary_cause"] == {"PATH_WARN_ONLY": 5, "FAKE_DRUG_CLARIFY": 1}


# --------------------------------------------------------------------------- 전후 비교


def test_compare_mode_changes() -> None:
    before = _result([_row("dev-001", end="VALIDATION_FALLBACK"), _row("dev-002", ert="no_evidence", end="CLARIFY"),
                      _row("dev-003"), _row("dev-004", end="VALIDATION_FALLBACK"), _row("dev-009")])
    after = _result([_row("dev-001"), _row("dev-002", ert="no_evidence", end="CLARIFY"),
                     _row("dev-003", end="VALIDATION_FALLBACK"), _row("dev-004", aux={"quote_mismatch": 1}), _row("dev-010")])
    rep = D.build_report([("a.json", after)], before=[("b.json", before)])
    c = rep["compare"]
    ch = {r["id"]: r["change"] for r in c["rows"]}
    assert ch == {"dev-001": "해소", "dev-002": "지속", "dev-003": "신규", "dev-004": "원인 변경"}
    assert c["only_before"] == ["dev-009"] and c["only_after"] == ["dev-010"]
    assert c["by_primary_cause"]["VALIDATION_FALLBACK"] == [2, 1]
    assert "## 3. 전후 비교" in D.render_md(rep)


def test_cli_compare(tmp_path: Path) -> None:
    b, a = tmp_path / "b.json", tmp_path / "a.json"
    b.write_text(json.dumps(_result([_row("dev-001", end="LIMIT", ert="correct", fails=["MODEL_CALL_LIMIT"])])), encoding="utf-8")
    a.write_text(json.dumps(_result([_row("dev-001", ert="correct")])), encoding="utf-8")
    md = tmp_path / "c.md"
    assert D.main(["--before", str(b), "--after", str(a), "--out-md", str(md)]) == 0
    assert "해소" in md.read_text(encoding="utf-8")


def test_cli_argument_errors(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        D.main(["--before", "x.json", "--out-md", str(tmp_path / "o.md")])
    with pytest.raises(SystemExit):
        D.main(["--out-md", str(tmp_path / "o.md")])


# --------------------------------------------------------------------------- 시험셋 거절(RFP-26-04)


def test_rejects_test_set_result_by_meta(tmp_path: Path) -> None:
    for data in (_result([_row()], set_="test"), _result([_row()], sealed=True),
                 {"meta": {"set": "dev"}, "items": "omitted"}):
        p = tmp_path / "x.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(D.NotDevResultError):
            D.load_result(p)
        assert D.main([str(p), "--out-md", str(tmp_path / "o.md")]) == 2
    assert not (tmp_path / "o.md").exists()


def test_rejects_test_result_name_before_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real = Path.read_text

    def spy(self: Path, *a: Any, **k: Any) -> str:
        opened.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    for name in ("ag11-test2-C2.json", "ag11-test-C1.json", "eval.SEALED.jsonl", "x.sealed.json"):
        p = tmp_path / name
        p.write_bytes(json.dumps(_result([_row()])).encode("utf-8"))
        with pytest.raises((D.NotDevResultError, sealed_guard.SealedAccessError)):
            D.load_result(p)
    assert opened == []


def test_sealed_env_does_not_open_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sealed_guard.SEALED_ENV, sealed_guard.SEALED_ENV_VALUE)
    p = tmp_path / "test.sealed.json"
    p.write_text(json.dumps(_result([_row()])), encoding="utf-8")
    with pytest.raises((D.NotDevResultError, sealed_guard.SealedAccessError)):
        D.load_result(p)
