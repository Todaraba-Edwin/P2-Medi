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
