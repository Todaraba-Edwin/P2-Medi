"""AG-08 응급 키워드 재현율 보강 시험(2026-11-11 3차 A3).

- 문장은 모두 **합성**이다. 개발셋 문장을 복사하지 않고, 누락 유형(약 이름이 사이에 낀 "실수로 … 먹었어",
  "먹어 버렸어"·"주워 먹었어" 같은 구어체, 남의 약을 아이가 먹음, 눈에 들어감, 복통·구토 동반, 갑작스런 어지럼)을
  질문 형태로 일반화해 새로 만들었다.
- 입구 정밀도 우선(AG-08-02 A): 정상 금기 확인 질문의 응급 오탐 0을 함께 고정한다.
- 개발셋 정상 계열 전체의 응급 오탐·입구 거절 0건은 개수로만 확인한다(문장은 출력하지 않는다). 시험셋(SEALED)은 열지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import fixed_phrases as fp
from app.agent.guardrail import detect_emergency, guardrail_in

ROOT = Path(__file__).resolve().parents[2]
DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"

# --------------------------------------------------------------------------- 양성(응급으로 잡아야 함)
POSITIVE = [
    # 1) 약 이름이 사이에 낀 "실수로·모르고·잘못 … 먹었/삼켰"
    "딸이 실수로 아빠 혈압약 노바스크정 먹었어요",
    "아들이 실수로 엄마 갑상선약을 두 알 삼켰어요",
    "동생이 모르고 할머니 당뇨약 한 알 먹었대",
    "애가 잘못해서 수면제를 먹은 것 같아요",
    "아이가 실수로 어른 진통제 캡슐을 먹었는데 어떡해요",
    "손녀가 모르고 고지혈증약 집어 먹었어요",
    # 2) 구어체 완료형("먹어 버렸어", "삼켜 버림", "주워 먹음", "집어 먹음")
    "세 살 아기가 진통제를 한 알 먹어 버렸어",
    "우리 애가 엄마 영양제랑 약을 먹어버림",
    "아기가 바닥에 떨어진 알약을 주워 먹었어요",
    "아이가 식탁 위 약을 집어먹었어 괜찮을까",
    "꼬마가 감기약 시럽을 통째 마셔버렸어요",
    "아이가 기침약 병을 다 마셔 버렸어",
    # 3) 개수 모름·여러 개
    "아이가 약통에서 몇 알을 먹었는지 모르겠어요",
    "애가 혈압약을 몇 개 먹었어요",
    "손주가 수면유도제를 여러 알 먹었어요",
    "할머니가 약을 한꺼번에 다섯 알 드셨어요",
    "아빠가 진통제를 두 배로 먹었다는데 괜찮아요?",
    # 4) 남의 약을 아이가 먹음
    "할아버지가 드시는 협심증약을 손주가 먹었어",
    "엄마가 먹는 피임약을 딸이 먹었는데 어떻게 해",
    "아빠가 복용하는 당뇨약을 아이가 삼켰어요",
    # 5) 눈·입에 들어감
    "아이 눈에 연고가 들어갔어요",
    "아기 눈에 소독약이 튀었어요 어떡해요",
    # 6) 복용 뒤 복통·구토·갑작스런 증상
    "아이가 약 먹고 배가 아프다며 구토해요",
    "약 먹은 뒤로 계속 토해요 위험한 상황인가요",
    "엄마가 혈압약 드시다가 갑자기 어지럽다고 하세요",
    "할아버지가 약 드시고 갑자기 쓰러질 것 같다고 하세요",
    "약 먹었는데 얼굴이 퉁퉁 부었어요",
    "아버지가 약 드시고 갑자기 말이 어눌해졌어요",
    "할머니가 약 먹은 후 식은땀을 흘리며 축 처졌어요",
    "엄마가 갑자기 정신이 혼미하다고 해요",
    # 7) 띄어쓰기·조사 변이(정규화 확인)
    "애 가 실 수 로 약 을 먹 었 어 요",
    "아기가실수로알약을먹었어요",
    "아이가 약을 삼켰어!!",
]

# --------------------------------------------------------------------------- 음성(정상 금기 확인 질문, 응급 아님)
NEGATIVE = [
    "타이레놀이랑 이부프로펜 같이 먹어도 돼요?",
    "임신 중인데 감기약 먹어도 되나요",
    "수유 중에 판콜 먹어도 괜찮나요",
    "다섯 살 아이한테 이 해열제 먹여도 되나요",
    "아이가 감기약을 먹었는데 해열제도 같이 먹여도 되나요",
    "아침에 혈압약 먹었는데 저녁에 감기약 먹어도 돼요?",
    "어제 진통제 먹었는데 오늘 소화제 먹어도 돼요",
    "이 약 먹으면 어지러울 수 있나요",
    "어지럼증 부작용이 있는 약인가요",
    "구토 증상 있을 때 먹는 약이랑 같이 먹어도 돼?",
    "멀미약이 구토를 막아 주나요",
    "배가 아플 때 먹는 약과 진통제 병용 괜찮나요",
    "눈에 넣는 안약이랑 먹는 약 같이 써도 되나요",
    "할머니가 드시는 혈압약과 감기약 같이 드셔도 되나요",
    "엄마가 먹는 갑상선약이랑 철분제 같이 먹어도 돼?",
    "아빠가 복용하는 와파린과 아스피린 병용금기인가요",
    "실수로 약 이름을 잘못 적었어요 다시 확인해 주세요",
    "약 이름을 모르고 사진만 있는데 찾아 주세요",
    "몇 살부터 먹을 수 있는 약인가요",
    "이 약 연령금기가 있나요",
    "65세 이상 어르신이 먹어도 되는 감기약 있나요",
    "여러 알 먹는 영양제랑 혈압약 같이 먹어도 돼요",
    "두 가지 약을 같이 먹어도 되는지 알려 주세요",
    "아기가 약을 잘 안 먹어요 시럽으로 바꿔도 될까요",
    "아이가 약을 안 먹었어요 다른 약이랑 같이 줘도 돼요",
    "약을 깜빡하고 안 먹었는데 다른 약이랑 같이 먹어도 되나요",
    "이 연고 얼굴에 발라도 되나요",
    "임신 초기인데 갑자기 감기에 걸렸어요 먹어도 되는 약 있나요",
    "갑자기 생각났는데 이 두 약 병용금기 있나요",
    "통째로 삼키기 어려운 정제는 쪼개도 되나요",
    "주워들은 이야기인데 이 약이랑 술 같이 먹으면 안 되나요",
    "위험한 약 조합이 있는지 확인해 주세요",
    # 정밀도 함정: "모르고·잘못 알고 먹었는데"는 임부·병용 확인 질문이다
    "임신인 줄 모르고 감기약 먹었는데 괜찮나요",
    "병용금기인 줄 모르고 두 약을 같이 먹었어요 확인해 주세요",
    "잘못 알고 진통제를 먹었는데 임부금기 약인가요",
    "엄마가 먹는 약을 아이가 먹어도 되나요",
    "한꺼번에 먹어도 되는 약들인가요",
    "눈이 침침할 때 넣는 안약이랑 혈압약 같이 써도 돼요",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_emergency_recall_synthetic_positive(text):
    assert detect_emergency(text) is True


@pytest.mark.parametrize("text", NEGATIVE)
def test_emergency_precision_synthetic_negative(text):
    assert detect_emergency(text) is False


def test_synthetic_sets_are_large_enough():
    assert len(POSITIVE) >= 30 and len(NEGATIVE) >= 30


@pytest.mark.parametrize("text", POSITIVE[:10])
def test_new_patterns_keep_lookup_and_fixed_119(text):
    r = guardrail_in(text)
    assert r["emergency"] is True and r["proceed_tools"] is True
    # 119 문구는 코드 상수 그대로(키워드 보강이 문구를 바꾸지 않음)
    assert "119" in fp.EMERGENCY_119


# --------------------------------------------------------------------------- 개발셋 정상 계열(개수만, 문장 비출력)
def _dev_rows() -> list[dict]:
    if not DEV_SET.exists():
        pytest.skip("dev_set.jsonl 없음(로컬 평가 세트)")
    return [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_dev_set_normal_groups_have_zero_emergency_false_positive():
    rows = [r for r in _dev_rows() if str(r.get("composition_group", "")).startswith("정상-")
            and r.get("composition_group") != "정상-응급"]
    assert rows, "정상 계열 문항이 없음"
    fp_count = sum(detect_emergency(r.get("question") or "") for r in rows)
    assert fp_count == 0, f"정상 계열 응급 오탐 {fp_count}/{len(rows)}"


def test_dev_set_normal_groups_have_zero_entry_refusal():
    """AG-08-02 A 회귀: 정상 계열(응급 포함) 전체의 입구 거절 0건."""
    rows = [r for r in _dev_rows() if str(r.get("composition_group", "")).startswith("정상-")]
    refused = sum(guardrail_in(r.get("question") or "")["route"] != "AGENT" for r in rows)
    assert refused == 0, f"정상 계열 입구 거절 {refused}/{len(rows)}"
