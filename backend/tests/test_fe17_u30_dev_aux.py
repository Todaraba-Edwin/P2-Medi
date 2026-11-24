"""FE-17 U-30-1 개발 보조 문항(`evaluation/eval_set/dev_aux_u30.jsonl`)과 코드 채점(`evaluation/dev_aux_u30.py`) 시험. 합성 사전, LLM·네트워크 호출 0.

- 보조 문항은 평가 세트가 아니다: `manifest.json`에 없고 개발셋 150·시험셋을 건드리지 않는다.
- 합성 사전(`w32_synth`)이 보조 문항의 약(타이레놀정500밀리그람·이지렉트정·어린이타이레놀현탁액·8시간이알서방정)을 가진다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from w32_synth import w32_dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation"))

import dev_aux_u30 as AUX  # noqa: E402
import sealed_guard  # noqa: E402

EVAL_SET = ROOT / "evaluation" / "eval_set"


@pytest.fixture(scope="module")
def dd():
    return w32_dict(protect_names=False)


@pytest.fixture(scope="module")
def rows():
    return AUX.load_aux()


def test_aux_file_shape_and_not_registered_in_manifest(rows):
    assert len(rows) == 8
    kinds = [r["kind"] for r in rows]
    assert {k: kinds.count(k) for k in set(kinds)} == {"dup_pair": 4, "nodup_pair": 2, "three_drugs": 1, "text_only": 1}
    assert len({r["id"] for r in rows}) == 8 and all(r["set"] == "dev_aux_u30" for r in rows)
    assert "dev_aux_u30" not in (EVAL_SET / "manifest.json").read_text(encoding="utf-8")
    assert "SEALED" not in AUX.AUX_PATH.name.upper()
    assert sum("용량주의 겹침" in (r.get("overlap") or "") for r in rows) >= 2          # 같은 성분(용량주의 겹침) 문항 포함
    assert rows[-1]["question"] == "타이레놀정500 먹고 이부프로펜도 먹어도 돼요?"          # 2026-11-24 사용자 사례 원문


def test_dev_set_and_manifest_untouched():
    m = json.loads((EVAL_SET / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((EVAL_SET / "dev_set.jsonl").read_bytes()).hexdigest() == m["sets"]["dev"]["sha256"]


def test_sealed_files_are_refused_before_opening(tmp_path):
    with pytest.raises(sealed_guard.SealedAccessError):
        AUX.load_aux(tmp_path / "x.SEALED.jsonl")


def test_bad_rows_are_rejected(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"id": "a", "set": "dev_aux_u30", "kind": "nope", "question": "q", "expected": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        AUX.load_aux(p)


def test_dedupe_on_passes_every_check(dd, rows):
    rep = AUX.run_all(rows, dd)
    on = rep["configs"]["dedupe_on"]
    assert on["rows_all_pass"] == on["n_rows"] == 8, {k: v for k, v in on["checks"].items() if v["k"] != v["n"]}


def test_dedupe_off_reproduces_the_duplicate_and_is_otherwise_identical(dd, rows):
    """끄면 이전 동작: 중복 문항 5개(dup 4 + 사용자 사례 text_only 1)에서 `not_listed_sentences_le_max`·`n_dropped`가 통과하지 못하고, 중복 없는 문항은 켬과 같다."""
    rep = AUX.run_all(rows, dd)
    off = rep["configs"]["dedupe_off"]
    bad = {rid for rid, cs in off["rows"].items() if not all(c["passed"] for c in cs)}
    assert bad == {r["id"] for r in rows if r["kind"] in ("dup_pair", "text_only")}
    assert off["checks"]["not_listed_sentences_le_max"]["k"] == 3 and off["checks"]["not_listed_sentences_le_max"]["n"] == 8
    for r in rows:
        if r["kind"] in ("nodup_pair", "three_drugs"):
            assert rep["configs"]["dedupe_on"]["rows"][r["id"]] == off["rows"][r["id"]]
    # 안전 안내는 끔·켬 모두 남는다
    assert off["checks"]["keeps_classes"]["k"] == 8 and rep["configs"]["dedupe_on"]["checks"]["keeps_classes"] == {"k": 8, "n": 8}


def test_no_judge_or_network_in_scoring_module():
    src = (ROOT / "evaluation" / "dev_aux_u30.py").read_text(encoding="utf-8")
    for bad in ("anthropic", "openai", "requests", "httpx"):
        assert f"import {bad}" not in src


def test_main_prints_table(dd, rows, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("app.tools.drug_dict.DrugDict.load", classmethod(lambda cls, p: dd))
    out = tmp_path / "r.md"
    assert AUX.main(["--dict-path", str(tmp_path), "--out-md", str(out)]) == 0
    assert "dedupe_on" in capsys.readouterr().out and out.exists()
