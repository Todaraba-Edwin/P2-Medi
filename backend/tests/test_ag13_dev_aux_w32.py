"""W3-2 개발 보조 문항(`evaluation/eval_set/dev_aux_w32.jsonl`)과 코드 채점 모듈(`evaluation/dev_aux_w32.py`) 시험. 합성 사전, LLM·네트워크 호출 0.

- 보조 문항은 평가 세트가 아니다: `manifest.json`에 없고 개발셋 150·시험셋을 건드리지 않는다.
- 합성 사전(`w32_synth`)은 보조 문항이 쓰는 약(타이레놀정500밀리그람·코푸콜드-에스액·타이레놀콜드-에스정)을 같은 품목기준코드로 갖는다.
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

import dev_aux_w32 as AUX  # noqa: E402
import sealed_guard  # noqa: E402

EVAL_SET = ROOT / "evaluation" / "eval_set"


@pytest.fixture(scope="module")
def dd():
    return w32_dict(protect_names=False)


@pytest.fixture(scope="module")
def rows():
    return AUX.load_aux()


def test_aux_file_shape_and_not_registered_in_manifest(rows):
    assert len(rows) == 16
    kinds = [r["kind"] for r in rows]
    assert {k: kinds.count(k) for k in set(kinds)} == {"time_expression": 10, "control_unchanged": 3, "confirmed_selection": 3}
    assert len({r["id"] for r in rows}) == 16 and all(r["set"] == "dev_aux_w32" for r in rows)
    assert "dev_aux_w32" not in (EVAL_SET / "manifest.json").read_text(encoding="utf-8")
    assert "SEALED" not in AUX.AUX_PATH.name.upper()
    # 첫 문항은 2026-11-24 사례 원문 그대로다
    assert rows[0]["question"] == "나 이미 오전 9시에 타이레놀정 500밀리그람 2알을 먹었는데 점심12시에 먹어도 되니?"
    # 확정 선택 문항은 서비스형 입력(품목기준코드)을 갖는다
    conf = [r for r in rows if r["kind"] == "confirmed_selection"]
    assert all(r["confirmed_item_seqs"] for r in conf) and conf[0]["confirmed_item_seqs"][1]["item_seq"] == "201900975"


def test_dev_set_and_manifest_untouched():
    """개발셋 150문항 파일의 sha256이 manifest 기록과 같다(이 작업이 세트를 건드리지 않았다)."""
    m = json.loads((EVAL_SET / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((EVAL_SET / "dev_set.jsonl").read_bytes()).hexdigest() == m["sets"]["dev"]["sha256"]


def test_sealed_files_are_refused_before_opening(tmp_path):
    with pytest.raises(sealed_guard.SealedAccessError):
        AUX.load_aux(tmp_path / "x.SEALED.jsonl")  # 파일이 없어도 열기 전에 거절한다


def test_bad_rows_are_rejected(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"id": "a", "set": "dev_aux_w32", "kind": "nope", "question": "q", "expected": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        AUX.load_aux(p)


def test_all_on_passes_every_check_and_all_off_reproduces_the_failures(dd, rows):
    rep = AUX.run_all(rows, dd)
    on, off = rep["configs"]["all_on"], rep["configs"]["all_off"]
    assert on["rows_all_pass"] == on["n_rows"] == 16
    assert all(v["k"] == v["n"] for v in on["checks"].values())
    # 스위치를 모두 끄면 시각·횟수 문항은 되묻기로 끝나(`end_reason_not_clarify`) 후보 이전 문제가 재현된다
    # (합성 소사전은 BM25 유사 후보가 적어 일부 문항은 되묻기 대신 NOT_FOUND 엔티티가 된다. 실제 사전은 10/10이 되묻기다: 보고서 참고)
    assert off["checks"]["end_reason_not_clarify"]["k"] <= 3 and off["checks"]["no_unresolved_entity"] == {"k": 0, "n": 10}
    assert off["checks"]["redose_notice_fixed"]["k"] <= 3
    assert off["checks"]["unconfirmed_lines_per_drug"]["k"] < off["checks"]["unconfirmed_lines_per_drug"]["n"]
    # 보호 짝은 켜든 끄든 같다
    assert on["checks"]["same_router_result_as_switch_off"] == {"k": 3, "n": 3} == off["checks"]["same_router_result_as_switch_off"]


def test_leaky_and_skip_models_show_confinement_effect(dd, rows):
    rep = AUX.run_all(rows, dd)["configs"]
    for cfg in ("all_on_leaky", "all_on_skip"):
        assert rep[cfg]["rows_all_pass"] == rep[cfg]["n_rows"] == 3
    assert rep["all_off_leaky"]["checks"]["no_out_of_set_items"]["k"] < 3          # 비선택 후보가 판정 근거에 들어옴(문제 재현)
    assert rep["all_off_skip"]["checks"]["no_false_zero_unchecked"]["k"] < 3        # 선택 쌍을 안 봤는데 미확인 0건(문제 재현)
    # 한 번에 하나만 켠 ablation 구성이 모두 있다
    for sw in AUX.SWITCHES:
        assert f"only_{sw}" in rep and f"only_{sw}_skip" in rep
    assert rep["only_router_time_noise"]["checks"]["end_reason_not_clarify"] == {"k": 10, "n": 10}  # 41만 켜도 시각·횟수 문항이 풀린다
    assert rep["only_confine_confirmed_args_skip"]["checks"]["no_out_of_set_items"] == {"k": 3, "n": 3}
    assert rep["only_merge_unconfirmed_lines"]["checks"]["unconfirmed_lines_per_drug"] == {"k": 3, "n": 3}


def test_scoring_uses_existing_sensor_for_summary_text():
    st = {"answer": {"summary": "하루 3번 드세요", "result_summary": None}}
    assert not AUX._summary_checks(st)[0].passed                    # 용량 숫자·복용 지시
    assert AUX._summary_checks({"answer": {"summary": "조회한 결과를 정리했어요."}})[0].passed


def test_eval_runner_and_metrics_are_not_imported_by_scoring_module():
    src = (ROOT / "evaluation" / "dev_aux_w32.py").read_text(encoding="utf-8")
    assert "import eval_runner" not in src and "import eval_metrics" not in src and "from eval_runner" not in src
