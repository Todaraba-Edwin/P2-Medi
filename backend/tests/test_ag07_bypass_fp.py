"""AG-07 후속: 출구 우회 패턴(② DOSE_CHANGE_OR_BYPASS) 오탐 시험. 문장은 모두 합성이다(평가 세트 아님, LLM·외부 호출 없음).

- 양성(통과해야 함): 의사·약사 상의 권유, 숨기지 말라는 권유, 임의 변경 금지 권유. 프롬프트(agent_system@v2)가 지시하는 문장형이다.
- 음성(차단해야 함): 의료진 우회 조장, 알리지 않아도 된다는 말, 임의 복용 변경 지시.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import S, check_items_pair  # noqa: E402

from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.agent.validator import DOSE_CHANGE_OR_BYPASS, PASS, validate  # noqa: E402


@pytest.fixture(scope="module")
def items():
    return check_items_pair(age={"value": 5, "unit": "세"})


def _check(text, items):
    r = validate(AnswerDraft(sentences=[S(text, [], "guidance")]), items)
    return r.status, [i.check for i in r.issues]


ADVICE_OK = [
    "의사에게 숨기지 말고 알려 주세요.",
    "의사나 약사와 상의하세요.",
    "말씀하지 않고 끊지 마세요.",
    "의사와 말씀하지 않고 끊지 마세요.",
    "약사에게 꼭 물어보세요.",
    "먹고 있는 약은 의사·약사에게 모두 알려 주세요.",
    "의사 선생님께 숨기지 마시고 꼭 이야기하세요.",
    "약사에게 비밀로 하지 마세요.",
    "의사 몰래 약을 끊지 마세요.",
    "임의로 끊지 마세요.",
    "임의로 줄이거나 끊지 마세요.",
    "의사와 상의하지 않고 임의로 중단하지 마세요.",
    "약 봉투를 병원에 가지고 가서 보여 주세요.",
    "약국에 가지고 가서 약사에게 확인하세요.",
    "의사에게 알리지 않은 약이 있다면 지금 알려 주세요.",
    "의사에게 말씀 못 드렸다면 다음 진료 때 꼭 말씀하세요.",
    "의사에게 알리지 않으면 안 돼요.",
    "다른 약을 먹고 있다는 사실을 약사에게 숨겨서는 안 돼요.",
    "스스로 용량을 바꾸지 마세요.",
    "마음대로 늘리지 마시고 처방한 의사에게 물어보세요.",
    "의사에게 말하지 않고 약을 바꾸면 안 돼요.",
    "복용 중인 약을 약사에게 빠짐없이 말씀해 주세요.",
    "알아서 조절하지 말고 의사와 상의하세요.",
    "담당 의사에게 숨김없이 알려 주세요.",
    "혼자 판단해서 약을 중단하지 마시고 약사와 상의하세요.",
    "의료진에게 숨기지 않고 말하는 것이 중요해요.",
]

BYPASS_BAD = [
    "의사에게는 말씀 안 드려도 돼요.",
    "알리지 않아도 됩니다.",
    "알아서 줄이세요.",
    "약사에게는 비밀로 하세요.",
    "의사 몰래 약을 끊으세요.",
    "의사한테 말할 필요 없어요.",
    "약사에게 알릴 필요가 없습니다.",
    "병원에 갈 필요 없어요.",
    "병원에 안 가도 돼요.",
    "의사에게 얘기하지 말고 그냥 줄이세요.",
    "선생님께는 이야기하지 않아도 돼요.",
    "약사와 상의하지 않아도 돼요.",
    "의사 모르게 복용량을 늘리세요.",
    "마음대로 조절해도 돼요.",
    "임의로 끊어도 돼요.",
    "처방을 무시하고 스스로 줄이세요.",
    "의사에게 숨겨도 돼요.",
    "약사한테 말 안 해도 돼요.",
    "의료진에게 알리지 말고 약을 바꾸세요.",
    "의사에게 말하지 말고 복용을 멈추세요.",
    "진료받으러 병원에 가지 마세요.",
    "의사에게는 굳이 안 알려도 돼요.",
    "약사 몰래 약을 끊고 지켜보세요.",
    "상의하지 말고 알아서 끊으세요.",
    "약사에게는 물어보지 않아도 돼요.",
    "의사에게 숨기고 약을 줄이세요.",
    "의사한테 알리지 않고 약을 줄이세요.",
    "의사에게 말하지 않은 채로 복용을 중단해 보세요.",
    # 뒤쪽 금지형이 다른 동사에 붙은 경우(권유로 착각하면 안 된다)
    "알아서 줄이고 다른 약은 바꾸지 마세요.",
    "의사 몰래 약을 줄이고 다른 약은 바꾸지 마세요.",
    "의사에게 알리지 않은 채 약을 줄이고 나중에 약사에게 물어보세요.",
    "상의하지 않고 약을 줄이고 늘리지는 마세요.",
]

# 우회와 무관한 사실·조회 범위 설명 문장(새 패턴이 잘못 걸면 안 된다)
NEUTRAL_OK = [
    "임부 금기는 이번에 확인하지 않았어요.",
    "약 봉투를 약국에 가지고 가면 약사가 확인해 줄 수 있어요.",
    "나도 모르게 두 번 먹었을 수 있다면 약사에게 물어보세요.",
]


@pytest.mark.parametrize("text", NEUTRAL_OK)
def test_neutral_sentences_pass(text, items):
    status, why = _check(text, items)
    assert status == PASS, (text, why)


def test_case_counts():
    assert len(ADVICE_OK) >= 20 and len(BYPASS_BAD) >= 20


@pytest.mark.parametrize("text", ADVICE_OK)
def test_consult_advice_passes(text, items):
    status, why = _check(text, items)
    assert status == PASS, (text, why)


@pytest.mark.parametrize("text", BYPASS_BAD)
def test_bypass_or_dose_change_blocked(text, items):
    status, why = _check(text, items)
    assert why == [DOSE_CHANGE_OR_BYPASS], (text, why)


def test_fp_kn_summary(items, capsys):
    ok = sum(_check(t, items)[0] == PASS for t in ADVICE_OK)
    bad = sum(_check(t, items)[1] == [DOSE_CHANGE_OR_BYPASS] for t in BYPASS_BAD)
    print(f"상의 권유 통과 {ok}/{len(ADVICE_OK)}, 우회·변경 차단 {bad}/{len(BYPASS_BAD)} (합성, 소표본)")
    assert (ok, bad) == (len(ADVICE_OK), len(BYPASS_BAD))
