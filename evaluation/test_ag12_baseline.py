# ruff: noqa: S101  (시험 파일: assert 허용)
"""`ag12_baseline.py` 시험: 합성 결과 JSON만 쓴다(실제 평가 결과·시험셋 파일을 읽지 않는다, LLM 0).

실행(저장소 루트): `PYTHONPATH=backend backend/.venv/bin/python -m pytest evaluation/test_ag12_baseline.py -q -p no:cacheprovider`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

EVAL = Path(__file__).resolve().parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import ag12_baseline as ab  # noqa: E402
from eval_metrics import kn  # noqa: E402
from sealed_guard import SealedAccessError  # noqa: E402


def _metrics(*, saf_k: int = 7, typo: tuple[int, int] = (4, 2)) -> dict[str, Any]:
    return {
        "n_items": 20,
        "contra_judgment_accuracy": {**kn(3, 4), "by_group": {"정상-임부": kn(1, 1), "정상-병용": kn(2, 3)}},
        "typo_robustness": {"pairs": 4, "paired_normal": kn(typo[0], 4), "typo": kn(typo[1], 4),
                            "drop_pp": round(100 * (typo[0] - typo[1]) / 4, 1)},
        "safety_response_rate": {
            "code_part": kn(9, 10), "final": kn(saf_k - 1, 10), "final_excl_j5": kn(saf_k, 10), "pending_judge_items_excl_j5": 0,
            "by_type_code_part": {"correct": kn(2, 2), "refuse": kn(2, 2), "no_evidence": kn(2, 2),
                                  "emergency": kn(1, 2), "not_listed": kn(2, 2)},
        },
        "required_elements_code": {"EMERGENCY_119_TOP": kn(1, 2), "NOT_SAFE_NOTICE": kn(2, 2), "ONE_QUESTION": kn(0, 1)},
        "judge_rubric_pass": {"J3": {"pass": kn(1, 2)}, "J4": {"pass": kn(1, 2)}, "J5": {"pass": kn(2, 2)}},
    }


def _sealed_result(passes: list[bool], elements: list[list[str]] | None = None, sha: str = "s1") -> dict[str, Any]:
    els = elements or [["PREMISE_CORRECTED"]] * len(passes)
    ij = [{"id": f"#{i}", "safety": {"pass_excl_j5": p}, "judge_elements": dict.fromkeys(e)} for i, (p, e) in enumerate(zip(passes, els, strict=True))]
    return {"meta": {"sealed": True, "set": "test", "condition": "C2", "set_sha256": sha}, "metrics": _metrics(),
            "items_judge": ij, "items": "omitted: sealed set (scores only, RFP-26-04)"}


def test_mcnemar_exact_values() -> None:
    assert ab.mcnemar_exact(0, 0) is None
    assert ab.mcnemar_exact(5, 0) == pytest.approx(0.0625)
    assert ab.mcnemar_exact(5, 3) == pytest.approx(0.7265625)
    assert ab.mcnemar_exact(3, 5) == ab.mcnemar_exact(5, 3)
    assert ab.mcnemar_exact(4, 4) == 1.0
    with pytest.raises(ValueError):
        ab.mcnemar_exact(-1, 2)


def test_headline_recomputes_wilson_and_drop() -> None:
    h = ab.headline({"meta": {"sealed": True}, "metrics": _metrics()})
    assert h["wilson_mismatches"] == []
    assert h["typo"]["drop_pp_recalc"] == 50.0
    assert set(h["elements"]) == {"EMERGENCY_119_TOP", "NOT_SAFE_NOTICE"}  # 요약에 쓰지 않는 요소는 뺀다


def test_headline_flags_tampered_interval() -> None:
    m = _metrics()
    m["contra_judgment_accuracy"]["wilson95"] = [0.1, 0.2]
    h = ab.headline({"meta": {}, "metrics": m})
    assert any(s.startswith("contra:") for s in h["wilson_mismatches"])


def test_headline_requires_main_safety_metric() -> None:
    m = _metrics()
    del m["safety_response_rate"]["final_excl_j5"]
    with pytest.raises(ab.BaselineError):
        ab.headline({"meta": {}, "metrics": m})


def test_derived_by_type_sum_must_match() -> None:
    h = ab.headline({"meta": {}, "metrics": _metrics(saf_k=7)})  # 1+1(J3·J4) + 2+1+2(코드 유형) = 7
    d = ab.derived_by_type(h)
    assert d["consistent"] is True and d["by_type"]["correct"]["k"] == 1 and d["by_type"]["emergency"]["k"] == 1
    bad = ab.derived_by_type(ab.headline({"meta": {}, "metrics": _metrics(saf_k=8)}))
    assert bad["consistent"] is False and bad["by_type"] is None


def test_derived_by_type_refuses_when_code_part_not_full() -> None:
    m = _metrics()
    m["safety_response_rate"]["by_type_code_part"]["correct"] = kn(1, 2)
    d = ab.derived_by_type(ab.headline({"meta": {}, "metrics": m}))
    assert d["consistent"] is False


def test_paired_safety_counts_only() -> None:
    a = _sealed_result([True, True, False, False, True])
    b = _sealed_result([True, False, True, False, False])
    p = ab.paired_safety(a, b)
    assert p["computed"] and (p["both_pass"], p["only_a_pass"], p["only_b_pass"], p["both_fail"]) == (1, 2, 1, 1)
    assert "#0" not in json.dumps(p)  # 문항 순번을 내지 않는다


def test_paired_safety_refuses_misaligned() -> None:
    a = _sealed_result([True, False])
    assert ab.paired_safety(a, _sealed_result([True, False], sha="other"))["computed"] is False
    assert ab.paired_safety(a, _sealed_result([True]))["computed"] is False
    other_els = _sealed_result([True, False], elements=[["PREMISE_CORRECTED"], ["REFUSAL_WITH_REASON"]])
    assert ab.paired_safety(a, other_els)["computed"] is False


def test_dev_breakdown_rejects_sealed_result() -> None:
    with pytest.raises(ab.BaselineError):
        ab.dev_breakdown(_sealed_result([True]), [])


def _dev_item(i: str, **kw: Any) -> dict[str, Any]:
    base = {"id": i, "branch_label": "정상", "composition_group": None, "expected_response_type": None, "pair_of": None,
            "judgment": None, "elements": {}}
    return {**base, **kw}


def test_dev_breakdown_on_synthetic_rows() -> None:
    ok = {"applicable": True, "correct": True, "items": []}
    ng = {"applicable": True, "correct": False, "items": []}
    items = [
        _dev_item("dev-1", composition_group="정상-임부", expected_response_type="judgment", judgment=ok),
        _dev_item("dev-2", composition_group="정상-병용", expected_response_type="judgment", judgment=ok),
        _dev_item("dev-3", branch_label="오탈자", composition_group="오탈자", pair_of="dev-1", judgment=ng),
        _dev_item("dev-4", composition_group="정상-응급", expected_response_type="emergency",
                  elements={"EMERGENCY_119_TOP": True, "CONTRA_CHECK_PARALLEL": False}),
        _dev_item("dev-5", composition_group="정상-목록없음", expected_response_type="not_listed",
                  elements={"NOT_SAFE_NOTICE": True, "PHARMACIST_NOTICE": True}),
    ]
    ij = [{"id": "dev-4", "safety": {"pass_excl_j5": False}}, {"id": "dev-5", "safety": {"pass_excl_j5": True}}]
    res = {"meta": {"sealed": False}, "metrics": {}, "items": items, "items_judge": ij}
    dev_rows = [{"id": "dev-1", "set": "dev", "subtype": "임부(M)"}, {"id": "dev-2", "set": "dev", "subtype": "병용"}]
    d = ab.dev_breakdown(res, dev_rows)
    assert (d["contra_grade_m"]["k"], d["contra_grade_m"]["n"]) == (1, 1)
    assert (d["emergency_119_top_and_parallel"]["k"], d["emergency_119_top_and_parallel"]["n"]) == (0, 1)
    assert (d["not_listed_notice_and_pharmacist"]["k"], d["not_listed_notice_and_pharmacist"]["n"]) == (1, 1)
    assert d["typo_pairs_mcnemar"] == {"pairs": 1, "normal_only_correct": 1, "typo_only_correct": 0, "mcnemar_exact_p": 1.0}
    assert d["safety_final_excl_j5_by_type"]["not_listed"]["k"] == 1


def test_required_elements_table_marks_scorer() -> None:
    rows = [{"id": "dev-1", "set": "dev", "expected_response_type": "no_evidence",
             "required_elements": ["SAYS_NOT_FOUND", "PHARMACIST_NOTICE"]}]
    t = ab.required_elements_table(rows)
    assert t["no_evidence"]["elements"]["SAYS_NOT_FOUND"] == {"items": 1, "scorer": "J5", "aux_only": True}
    assert t["no_evidence"]["elements"]["PHARMACIST_NOTICE"]["scorer"] == "code"
    assert t["refuse"]["n_items"] == 0


def test_load_result_refuses_sealed_set_file(tmp_path: Path) -> None:
    f = tmp_path / "x.SEALED.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SealedAccessError):
        ab.load_result(f)
    with pytest.raises(SealedAccessError):
        ab.load_dev_set(f)


def test_load_result_rejects_non_result(tmp_path: Path) -> None:
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"meta": {}}), encoding="utf-8")
    with pytest.raises(ab.BaselineError):
        ab.load_result(f)


def test_load_dev_set_rejects_non_dev(tmp_path: Path) -> None:
    f = tmp_path / "d.jsonl"
    f.write_text(json.dumps({"id": "t-1", "set": "test"}) + "\n", encoding="utf-8")
    with pytest.raises(ab.BaselineError):
        ab.load_dev_set(f)


def test_main_writes_outputs(tmp_path: Path) -> None:
    r = tmp_path / "res.json"
    r.write_text(json.dumps(_sealed_result([True, False])), encoding="utf-8")
    dev = tmp_path / "dev.jsonl"
    dev.write_text(json.dumps({"id": "dev-1", "set": "dev", "expected_response_type": "correct",
                               "required_elements": ["PREMISE_CORRECTED"]}) + "\n", encoding="utf-8")
    out_j, out_m = tmp_path / "o.json", tmp_path / "o.md"
    rc = ab.main(["--result", f"a={r}", "--result", f"b={r}", "--pair", "a,b", "--dev-set", str(dev),
                  "--json", str(out_j), "--md", str(out_m)])
    assert rc == 0
    rep = json.loads(out_j.read_text(encoding="utf-8"))
    assert rep["pairs"]["a vs b"]["mcnemar_exact_p"] is None and rep["dev_breakdown"] == {}
    assert "## 1. 3지표 요약" in out_m.read_text(encoding="utf-8")
