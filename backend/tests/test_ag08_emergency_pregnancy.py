"""AG-08 응급 감지: 임신 본인 사고 섭취 예외(2026-11-18 밤, 개발셋 dev-125 기존 오탐).

- dev-125(근거 없음 계열)는 사고 섭취 패턴(`_ACCIDENTAL_INTAKE`, "실수로·잘못해서 … 먹었") **하나만** 걸려 응급이 됐다.
  임신 중 본인이 약을 실수로 먹었다는 질문은 임부금기 확인 질문이므로, 아이 주어·수량·과량 단서가 없고 다른 응급 신호가 없을 때만 응급에서 뺀다.
- 미탐 금지 우선(`detect_emergency` 독스트링): 아이 주어·여러 알·한 통·많이·증상이 있으면 그대로 응급이다.
- 문장은 모두 **합성**이다. 개발셋 문장을 복사하지 않았고 시험셋(SEALED)은 열지 않았다. 개발셋은 개수·ID만 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.guardrail import detect_emergency, guardrail_in

DEV_SET = Path(__file__).resolve().parents[2] / "evaluation" / "eval_set" / "dev_set.jsonl"

# 임신 본인 + 사고 섭취만(수량·아이·증상 없음) → 응급 아님(조회는 그대로 이어짐)
PREGNANCY_SELF_NEG = [
    "임신 중인데 실수로 감기약을 먹었어요 괜찮을까요",
    "임신 초기인데 잘못해서 진통제를 먹었어요",
    "임산부인데 실수로 소화제 한 알 먹었어요",
    "임부인데 실수로 여드름약을 먹었는데 기형 위험 있나요",
    "임신한 줄 모르고 실수로 두통약 먹었어요 임부금기인가요",
    "임신 8주인데 잘못하여 비염약을 먹었어요",
]

# 같은 문맥이어도 수량·과량·아이·증상 단서가 있으면 응급(미탐 금지)
PREGNANCY_STILL_POS = [
    "임신 중인데 실수로 수면제를 10알 먹었어요",
    "임신 중인데 아이가 실수로 제 약을 먹었어요",
    "임신 중인데 실수로 약을 한 통 다 먹었어요",
    "임신 중인데 실수로 진통제를 여러 알 먹었어요",
    "임신 초기인데 실수로 약을 먹고 숨이 막혀요",
    "임산부인데 잘못해서 수면제를 많이 먹었어요",
    "임신 중인데 실수로 혈압약을 두 번 먹었어요",
    "임신 중인데 실수로 시럽을 한 병 마셨어요",
    "임신 중인데 실수로 진통제를 전부 먹었어요",
]

# 임신 말이 없으면 예외 대상이 아니다(기존 동작 유지)
NON_PREGNANCY_POS = [
    "실수로 혈압약을 먹었어요",
    "할머니가 잘못해서 할아버지 약을 드셨어요",
    "우리 애가 실수로 어른 감기약 먹었어",
]


@pytest.mark.parametrize("text", PREGNANCY_SELF_NEG)
def test_pregnancy_self_accidental_intake_only_is_not_emergency(text):
    assert detect_emergency(text) is False
    r = guardrail_in(text)
    assert r["proceed_tools"] is True and r["route"] == "AGENT"


@pytest.mark.parametrize("text", PREGNANCY_STILL_POS)
def test_pregnancy_with_amount_kid_or_symptom_stays_emergency(text):
    assert detect_emergency(text) is True


@pytest.mark.parametrize("text", NON_PREGNANCY_POS)
def test_accidental_intake_without_pregnancy_stays_emergency(text):
    assert detect_emergency(text) is True


def test_exception_sets_are_large_enough():
    assert len(PREGNANCY_SELF_NEG) >= 5 and len(PREGNANCY_STILL_POS) >= 5


# --------------------------------------------------------------------------- 개발셋(개수·ID만, 문장 비출력)
def _dev_rows() -> list[dict]:
    if not DEV_SET.exists():
        pytest.skip("dev_set.jsonl 없음(로컬 평가 세트)")
    return [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_emergency_item(r: dict) -> bool:
    return "EMERGENCY_119_TOP" in (r.get("required_elements") or [])


def test_dev_set_emergency_zero_miss_and_zero_false_positive():
    rows = _dev_rows()
    emerg = [r for r in rows if _is_emergency_item(r)]
    others = [r for r in rows if not _is_emergency_item(r)]
    assert emerg and len(others) >= 100
    missed = [r["id"] for r in emerg if not detect_emergency(r.get("question") or "")]
    fps = [r["id"] for r in others if detect_emergency(r.get("question") or "")]
    assert not missed, f"응급 미탐 {len(missed)}/{len(emerg)}: {missed}"
    assert not fps, f"응급 오탐 {len(fps)}/{len(others)}: {fps}"
