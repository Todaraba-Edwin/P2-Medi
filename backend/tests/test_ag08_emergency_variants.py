"""AG-08-32 A 응급 감지 변형 보강 시험(2026-11-18).

- FE-01 실서버 시험 F1에서 놓친 두 문장("숨을 잘 못 쉬어요", "시럽을 한 병 다 마셨어요")과 그 변형을 **합성**으로 만들었다.
  개발셋 문장을 복사하지 않았고 시험셋(SEALED)은 열지 않았다.
- 변형 축: 증상 말 사이 부사("잘·제대로"), 숨쉬기·호흡 + 힘듦, 과량(한 병·한 통 다·약통의 것을 다·통째로 다·몽땅),
  의식(깨워도 안 일어남·축 늘어짐), 경련(경기·눈 뒤집힘·부들부들 떪), 청색증(입술이 파래짐).
- 입구 정밀도 우선(AG-08-02 A): "숨 쉬는 약", "한 병에 몇 ml", 술·우유 한 병, "경기도" 같은 함정은 응급이 아니어야 한다.
- 개발셋은 개수만 확인한다(문장 비출력). 응급 정답은 `required_elements`의 `EMERGENCY_119_TOP`이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import fixed_phrases as fp
from app.agent.guardrail import detect_emergency, guardrail_in

ROOT = Path(__file__).resolve().parents[2]
DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"

# FE-01 실서버 F1 문장(합성 재현)
LIVE_F1 = [
    "아이가 해열제 시럽을 한 병 다 마셨고 숨을 잘 못 쉬어요",
    "숨을 잘 못 쉬어요",
    "아이가 시럽을 한 병 다 마셨어요",
]

POSITIVE = [
    # 호흡: 부사가 낌·숨쉬기 힘듦·호흡 곤란 변형
    "아기가 숨을 제대로 못 쉬어요",
    "엄마가 숨이 잘 안 쉬어진대요",
    "아빠가 약 먹고 숨쉬기가 힘들다고 해요",
    "할머니가 숨 쉬는 게 너무 힘들대요",
    "호흡이 잘 안 돼요",
    "아이가 숨을 쉬지 않아요",
    "약 먹고 나서 숨을 헐떡거려요",
    # 과량: 한 병·한 통 다, 약통의 것을 다, 통째로 다, 몽땅
    "아이가 기침약 시럽 한 병을 전부 마셨어요",
    "애가 진통제 한 통 몽땅 먹었어요",
    "동생이 해열제 한 통을 다 삼켰어요",
    "아이가 약통에 있던 알약을 다 먹었어요",
    "아기가 물약병에 든 걸 다 마셨어요",
    "아이가 비타민을 통째로 다 먹었어요",
    "아이가 영양제를 몽땅 먹었어요",
    # 의식
    "깨워도 안 일어나요",
    "할아버지가 약 드시고 불러도 대답이 없어요",
    "아이가 축 늘어져 있어요",
    "할머니가 약 드신 뒤로 깨어나지 않아요",
    "아이가 정신을 못 차려요",
    # 경련·청색증
    "아기가 열나더니 경기를 해요",
    "아이가 눈이 뒤집혔어요",
    "몸을 부들부들 떨어요",
    "아이 입술이 파래졌어요",
]

NEGATIVE = [
    # 브리프 함정
    "숨 쉬는 약이랑 감기약 같이 먹어도 돼요?",
    "시럽 한 병에 몇 ml 들어 있어요?",
    # 숨·호흡 말이 있지만 증상이 아님
    "숨쉬기 편하게 해 주는 코 스프레이랑 감기약 같이 써도 돼요?",
    "호흡기 질환 약이랑 혈압약 병용금기 있나요",
    "숨이 잘 쉬어지게 하는 약이 있나요",
    # 병·통·다 먹음이지만 과량 사고가 아님
    "술 한 병 다 마셨는데 타이레놀 먹어도 돼요?",
    "우유 한 병 다 마신 아이에게 해열제 먹여도 되나요",
    "해열제 시럽 한 병 다 먹이면 며칠 치예요?",
    "한 통에 몇 알 들어 있나요",
    "처방받은 약을 다 먹었는데 또 처방받아야 하나요",
    "약통에 든 약 이름을 모르겠어요",
    "통째로 삼켜야 하는 약인가요",
    "약한 통증에 먹는 진통제랑 감기약 같이 먹어도 돼요",
    # 의식·경련·청색증 말이 있지만 증상이 아님
    "아침에 늦게 일어나서 혈압약을 늦게 먹었는데 괜찮나요",
    "경기도에 사는데 이 약 병용금기 확인해 주세요",
    "축구 경기 전에 진통제 먹어도 되나요",
    "몸이 떨리는 부작용이 있는 약인가요",
    "입술이 파래지는 부작용이 있는 약인가요",
    "아기가 시럽을 잘 안 마셔요 섞어 먹여도 돼요?",
    "약사님께 물어보니 술 한 병 정도는 괜찮다던데 맞나요",
]


@pytest.mark.parametrize("text", LIVE_F1)
def test_live_f1_sentences_are_emergency(text):
    assert detect_emergency(text) is True


@pytest.mark.parametrize("text", POSITIVE)
def test_variant_positive(text):
    assert detect_emergency(text) is True


@pytest.mark.parametrize("text", NEGATIVE)
def test_variant_negative(text):
    assert detect_emergency(text) is False


def test_variant_sets_are_large_enough():
    assert len(POSITIVE) >= 15 and len(NEGATIVE) >= 15


@pytest.mark.parametrize("text", LIVE_F1)
def test_live_f1_keeps_lookup_and_fixed_119(text):
    """응급이어도 금기 조회는 이어지고(H4) 119 문구는 코드 상수 그대로다."""
    r = guardrail_in(text)
    assert r["emergency"] is True and r["proceed_tools"] is True and r["route"] == "AGENT"
    assert "119" in fp.EMERGENCY_119


# --------------------------------------------------------------------------- 개발셋(개수만, 문장 비출력)
def _dev_rows() -> list[dict]:
    if not DEV_SET.exists():
        pytest.skip("dev_set.jsonl 없음(로컬 평가 세트)")
    return [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _is_emergency_item(r: dict) -> bool:
    return "EMERGENCY_119_TOP" in (r.get("required_elements") or [])


def test_dev_set_emergency_items_have_zero_miss():
    rows = [r for r in _dev_rows() if _is_emergency_item(r)]
    assert rows, "응급 문항이 없음"
    missed = [r["id"] for r in rows if not detect_emergency(r.get("question") or "")]
    assert not missed, f"응급 미탐 {len(missed)}/{len(rows)}: {missed}"


def test_dev_set_non_emergency_false_positive_not_increased():
    """보강 전 기준선 오탐은 dev-125(근거 없음) 1건이었고, 2026-11-18 밤 임신 본인 사고 섭취 예외로 0건이 됐다(ID만 비교)."""
    rows = [r for r in _dev_rows() if not _is_emergency_item(r)]
    fp_ids = {r["id"] for r in rows if detect_emergency(r.get("question") or "")}
    assert not fp_ids, f"응급 오탐 {sorted(fp_ids)}/{len(rows)}"
