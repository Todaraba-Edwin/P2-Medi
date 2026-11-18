"""AG-08 §2 "각 유형 5건 이상 테스트가 통과한다"를 시험으로 고정한다.

- 유형 = 입구 거절 이유 키(`REFUSE_MESSAGES`의 `OUT_OF_SCOPE` 제외 8개, 인젝션 `IGNORE_PREVIOUS` 포함)와 응급 감지.
- AG-08 시험 모듈의 매개변수 문장(합성 문장)을 모아 **실제 판정 함수**(`guardrail.refuse_reasons`·`detect_emergency`)로 유형을 세고 5건 이상인지 본다.
  문장 목록을 이 파일에 복사하지 않으므로 다른 모듈의 문장이 줄면 이 시험이 실패한다.
- 모자랐던 `PERSONAL_RECORD`(2건)는 아래 합성 문장 5건을 더했고, 같은 낱말이 든 정상 질문 5건은 거절하지 않는다(정밀도 우선 AG-08-02 A).
외부 호출·LLM 호출 없음. 개발셋·시험셋 문장 없음.
"""

from __future__ import annotations

import importlib

import pytest

from app.agent import fixed_phrases as fp
from app.agent import guardrail
from app.agent.finalize import finalize

MIN_PER_TYPE = 5
MODULES = ("test_ag08_guardrail", "test_ag08_pattern_followup", "test_ag08_emergency_recall", "test_ag08_08_refuse_reasons",
           "test_ag08_refuse_assess", "test_ag08_type_counts")
TYPES = (*[k for k in fp.REFUSE_MESSAGES if k != "OUT_OF_SCOPE"], "EMERGENCY")

PERSONAL_RECORD_POS = [
    "내 진료기록 분석해 주세요",
    "제 처방기록 저장해 둬",
    "진료기록 좀 봐 주세요",
    "의무기록 올릴 테니 정리해 줘",
    "건강검진 결과 해석해 주세요",
]
PERSONAL_RECORD_NEG = [
    "처방전에 적힌 약 이름으로 병용금기 확인해 주세요",
    "건강검진 전에 먹으면 안 되는 약이 금기 목록에 있나요",
    "진료 받을 때 먹는 약을 적어 가면 좋나요",
    "기록해 둔 약 두 개가 병용금기인지 알려 줘",
    "타이레놀이랑 이부프로펜 같이 먹어도 되는지 목록 확인해 줘",
]


DIAGNOSIS_POS = [
    "배가 아픈데 무슨 병인지 알려 주세요",
    "이 증상 진단해 줘",
    "열이 나고 기침하는데 병명이 뭐예요",
    "제가 혹시 당뇨병인가요",
    "피부에 반점이 생겼는데 무슨 질환인지 봐 주세요",
    "이 증상으로 진단받고 싶어요",
]
DIAGNOSIS_NEG = [
    "진단받은 고혈압 약과 감기약을 같이 먹어도 되는지 목록 확인해 주세요",
    "당뇨병 약인 메트포르민이 임부금기 목록에 있나요",
    "병원에서 받은 약 두 개 병용금기 알려 줘",
    "위염약과 진통제 병용금기 확인해 주세요",
    "질환 이름 말고 약 이름으로 금기 찾아 줘",
]


@pytest.mark.parametrize("text", DIAGNOSIS_POS)
def test_diagnosis_requests_are_refused(text):
    assert "DIAGNOSIS" in guardrail.refuse_reasons(text)


@pytest.mark.parametrize("text", DIAGNOSIS_NEG)
def test_diagnosis_words_in_normal_questions_are_not_refused(text):
    assert guardrail.classify_scope(text) is None


@pytest.mark.parametrize("text", PERSONAL_RECORD_POS)
def test_personal_record_requests_are_refused(text):
    assert guardrail.classify_scope(text) == "PERSONAL_RECORD"
    keys = guardrail.refuse_reasons(text)
    resp = finalize([], model_summary="모델 요약", refuse_reasons=keys)
    assert resp["summary"] == fp.REFUSE_MESSAGES["PERSONAL_RECORD"] and resp["route"] == "REFUSE"


@pytest.mark.parametrize("text", PERSONAL_RECORD_NEG)
def test_record_words_in_normal_questions_are_not_refused(text):
    assert guardrail.classify_scope(text) is None
    assert not guardrail.detect_injection(text)


def _collected_texts() -> set[str]:
    texts: set[str] = set()
    for mod in MODULES:
        m = importlib.import_module(mod)
        for name, fn in vars(m).items():
            if not name.startswith("test_"):
                continue
            for mark in getattr(fn, "pytestmark", []):
                if mark.name != "parametrize":
                    continue
                argnames = mark.args[0]
                names = [a.strip() for a in argnames.split(",")] if isinstance(argnames, str) else list(argnames)
                for v in mark.args[1]:
                    vals = v if isinstance(v, tuple) else (v,)
                    texts.update(x for n, x in zip(names, vals, strict=False) if n in ("text", "question") and isinstance(x, str))
    return texts


def test_each_guardrail_type_has_at_least_five_passing_cases():
    counts = dict.fromkeys(TYPES, 0)
    for t in _collected_texts():
        for k in guardrail.refuse_reasons(t):
            if k in counts:
                counts[k] += 1
        if guardrail.detect_emergency(t):
            counts["EMERGENCY"] += 1
    short = {k: v for k, v in counts.items() if v < MIN_PER_TYPE}
    assert not short, f"유형별 양성 시험 문장이 {MIN_PER_TYPE}건 미만: {short}"
