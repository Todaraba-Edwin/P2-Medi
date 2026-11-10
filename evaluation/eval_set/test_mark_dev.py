"""PRD-16-02 개발셋 표시(mark_dev_subsets.py) 시험. 시험셋은 열지 않는다."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import mark_dev_subsets as M

HERE = Path(__file__).resolve().parent
DEV = [json.loads(line) for line in (HERE / "dev_set.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
MAN = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))["sets"]["dev"]


def test_reliability_core_40_by_type_10_10_20():
    core = [x for x in DEV if x["dev_reliability_core"]]
    assert len(core) == 40
    assert Counter(x["composition_group"] for x in core) == {"정상-응급": 10, "정상-목록에없는약": 10, "오정보": 20}


def test_golden_20_two_per_group_and_exclusions():
    gold = [x for x in DEV if x["dev_golden"]]
    assert len(gold) == 20
    assert set(Counter(x["composition_group"] for x in gold).values()) == {2}
    assert len({x["composition_group"] for x in gold}) == 10
    for x in gold:
        hr = x["human_review"]
        assert not (hr.get("fixed") or hr.get("error_found") or x.get("bad_answer_sample"))
    # provisional은 모호 group 예외만
    assert {x["composition_group"] for x in gold if x.get("provisional")} <= {"모호"}


def test_marking_does_not_touch_other_fields():
    assert not any(x["reliability_core"] or x["golden"] or x["golden_verified"] for x in DEV)


def test_mark_is_idempotent_and_matches_file():
    rows = json.loads(json.dumps(DEV))
    M.mark(rows)
    assert [(x["dev_golden"], x["dev_reliability_core"]) for x in rows] == [(x["dev_golden"], x["dev_reliability_core"]) for x in DEV]
    M.mark(rows)
    assert M.summarize(rows)["dev_golden"] == 20


def test_manifest_counts_and_hash():
    assert MAN["dev_golden"] == 20 and MAN["dev_reliability_core"] == 40
    assert MAN["dev_reliability_core_by_group"] == {"정상-응급": 10, "정상-목록에없는약": 10, "오정보": 20}
    assert hashlib.sha256((HERE / "dev_set.jsonl").read_bytes()).hexdigest() == MAN["sha256"]


# --- AG-04-01 A: 수정 행 일관성 (dev-117 가상 약 2개, dev-143 범위 외 refuse)
def _row(i):
    return next(x for x in DEV if x["id"] == i)


def test_dev117_question_products_consistent_and_fake():
    r = _row("dev-117")
    assert len(r["products"]) == 2 and all(p in r["question"] for p in r["products"])
    assert "릴리애정" not in json.dumps(r["products"], ensure_ascii=False) and r["ingredient_codes"] == []
    assert r["expected_response_type"] == "no_evidence" and "SAYS_NOT_FOUND" in r["required_elements"]
    assert r["answer"]["items"] and all(i["status"] == "UNIDENTIFIED" for i in r["answer"]["items"])
    assert "check_contraindications" in r["expected_path"]["forbidden"]


def test_dev117_fake_names_not_in_dict():
    import sys
    sys.path.insert(0, str(HERE.parents[1] / "backend"))
    try:
        from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict
    except ImportError:  # pragma: no cover
        return
    if not DEFAULT_DICT_PATH.exists():
        return
    d = DrugDict.load()
    for p in _row("dev-117")["products"]:
        res = d.lookup_name(p)
        assert not res.resolved and all(c.name.split("(")[0].strip() != p for c in res.candidates)


def test_dev143_out_of_scope_refuse():
    r = _row("dev-143")
    oos = [x for x in DEV if x["composition_group"] == "범위 외" and x["subtype"] in ("복용 중단·감량", "의료진 우회")]
    assert r["expected_response_type"] == "refuse"
    assert all(x["expected_response_type"] == "refuse" for x in oos)
    assert r["expected_path"]["forbidden"] == _row("dev-141")["expected_path"]["forbidden"]
    assert r["required_elements"] == _row("dev-141")["required_elements"]
