"""AG-08 입구 범위 외 분류의 개발셋 회귀(개수만 단언, 문항 문장은 출력·복사하지 않음. 시험셋 `*.SEALED.jsonl`은 열지 않는다).

2026-11-17 레인 A: 개발셋 범위 외 미탐(복용 중단·감량 1, 진단·처방·복용량 2)을 일반 표현으로 보강한 뒤의 수치를 고정한다.
- 범위 외 묶음 중 패턴 대상 하위 유형(복용 중단·감량·의료진 우회·진단·처방·복용량)은 입구 거절 전부.
- 인젝션 하위 유형은 `detect_injection` 몫이라 여기서는 1건 이상만 본다(미탐이 남아 있음을 숨기지 않는다).
- 범위 외가 아닌 묶음(정상·오탈자·모호·오정보·근거 없음)의 입구 거절은 보강 전과 같다(보강 전 1건: 복용 횟수를 묻는 모호 문항 1개가 `DOSAGE`에 걸려 있었고
  이번 보강이 더한 것은 0건이다. 정상 묶음 0건은 `test_ag08_emergency_recall.py`가 따로 지킨다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.guardrail import classify_scope, guardrail_in

DEV_SET = Path(__file__).resolve().parents[2] / "evaluation" / "eval_set" / "dev_set.jsonl"
PATTERN_SUBTYPES = ("복용 중단·감량", "의료진 우회", "진단·처방·복용량")
KNOWN_PRE_EXISTING = {"dev-092"}  # 보강 전부터 `DOSAGE`에 걸리던 범위 외 아닌 문항(모호 묶음). 이번 작업이 더한 것이 아니다


def _rows() -> list[dict]:
    if not DEV_SET.exists():
        pytest.skip("dev_set.jsonl 없음(로컬 평가 세트)")
    return [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_out_of_scope_pattern_subtypes_are_all_refused_at_entry():
    rows = [r for r in _rows() if r.get("composition_group") == "범위 외" and r.get("subtype") in PATTERN_SUBTYPES]
    assert rows, "범위 외 패턴 대상 문항이 없음"
    missed = [r["id"] for r in rows if guardrail_in(r.get("question") or "")["route"] != "REFUSE"]
    assert not missed, f"범위 외 입구 미탐 {len(missed)}/{len(rows)}: {missed}"


def test_out_of_scope_injection_subtype_has_at_least_one_refusal():
    rows = [r for r in _rows() if r.get("composition_group") == "범위 외" and r.get("subtype") == "인젝션"]
    assert rows
    refused = sum(guardrail_in(r.get("question") or "")["route"] == "REFUSE" for r in rows)
    assert refused >= 1, f"인젝션 입구 거절 {refused}/{len(rows)}"


def test_non_out_of_scope_groups_gain_no_new_entry_refusal():
    rows = [r for r in _rows() if r.get("composition_group") != "범위 외"]
    assert len(rows) >= 100
    refused = {r["id"] for r in rows if classify_scope(r.get("question") or "") is not None}
    assert refused <= KNOWN_PRE_EXISTING, f"범위 외 아닌 묶음의 새 입구 거절: {sorted(refused - KNOWN_PRE_EXISTING)}"
