"""AG-08-01 A: 감량·중단 거절 문구(`STOP_DOSE_CHANGE`) 개정과 상태 평가 거절(`ASSESS_STATE`) 신설의 고정 시험.

- 문구는 티켓 원문(`tickets/agent/AG-08.md` §2 AG-08-01 A 조건)과 글자 일치.
- 두 문구의 5문장이 문장 필터(AG-06)·Validator(AG-07) 검사에 걸리지 않는다: Validator는 고정 문구를 검사 전에 지우므로(`strip_fixed`)
  공개 진입점(`validate`) 통과만으로는 의미가 없어, **지우지 않은 문장**을 같은 패턴 함수에 직접 넣어 본다.
- 숫자·일정(기간·횟수·시점) 표현이 없다(복용 일정을 짜 주지 않는다).
- 입구 `guardrail_in`이 이 키로 거절하면 `finalize` 요약 자리에 이 문구가 그대로 나가고, 모델 출력이 끼어들지 않는다.
외부 호출·LLM 호출 없음. 시험 문장은 합성.
"""

from __future__ import annotations

import re

import pytest

from app.agent import fixed_phrases as fp
from app.agent import validator as v
from app.agent.answer_schema import AnswerDraft, Sentence
from app.agent.finalize import finalize
from app.agent.guardrail import guardrail_in
from app.agent.sentence_filter import filter_sentences, unsafe_reason

TICKET_STOP = ("약을 줄이거나 끊는 방법과 시기는 알려 드릴 수 없어요. 의사가 줄이라고 했더라도 어떻게 줄일지는 처방한 그 의사나 약사에게 다시 "
               "확인하세요. 이 서비스는 지금 상태로 약을 줄여도 되는지 판단(진단·평가)해 드릴 수 없어요.")
TICKET_ASSESS = "지금 상태로 약을 줄이거나 끊어도 되는지는 진찰과 검사가 필요한 판단이라 이 서비스가 해 드릴 수 없어요. 처방한 의사나 약사와 상의하세요."


def _sentences() -> list[str]:
    out: list[str] = []
    for key in ("STOP_DOSE_CHANGE", "ASSESS_STATE"):
        out.extend(s.strip() + "." for s in fp.REFUSE_MESSAGES[key].split(".") if s.strip())
    return out


SENTENCES = _sentences()
_SCHEDULE = re.compile(r"[0-9０-９]|매일|하루|일간|주간|주 ?동안|개월|시간마다|간격|[0-9]?회|언제까지|부터|며칠|일정|서서히|점점")


def test_texts_match_ticket_original():
    assert fp.REFUSE_MESSAGES["STOP_DOSE_CHANGE"] == TICKET_STOP
    assert fp.REFUSE_MESSAGES["ASSESS_STATE"] == TICKET_ASSESS
    assert "STOP_DOSE_CHANGE" in fp.REFUSE_APPROVED_KEYS and "ASSESS_STATE" in fp.REFUSE_APPROVED_KEYS


def test_five_sentences():
    assert len(SENTENCES) == 5


@pytest.mark.parametrize("text", SENTENCES)
def test_no_numbers_or_schedule(text):
    assert not _SCHEDULE.search(text), text


@pytest.mark.parametrize("text", SENTENCES)
def test_sentence_filter_keeps_each_sentence(text):
    assert unsafe_reason(text) is None
    f = filter_sentences(AnswerDraft(sentences=[Sentence(text=text, evidence_ids=[], claim_type="guidance")]), [])
    assert f.dropped_count == 0


@pytest.mark.parametrize("text", SENTENCES)
def test_validator_patterns_pass_without_fixed_stripping(text):
    """고정 문구 제거(`strip_fixed`)를 거치지 않은 문장도 Validator의 안전 단정·우회·복용 결정·등급 검사에 걸리지 않는다."""
    norm = v._norm(text)
    assert not v._has_safe_assertion(norm)
    assert not v._has_bypass(norm)
    assert not any(r.search(norm) for r in v._DECISION_PATTERNS), text
    assert not v._has_grade_exception_misuse(norm)


def test_validator_public_entry_passes_refusal_sentences():
    res = v.validate([{"text": s, "evidence_ids": [], "claim_type": "guidance"} for s in SENTENCES], [],
                     expected_claim_types=("guidance",))
    assert res.status == v.PASS and res.dropped == []


@pytest.mark.parametrize("question, key", [
    ("지금 상태로 이 약 끊어도 되는지 봐 주세요", "ASSESS_STATE"),
    ("혈당 수치가 정상이면 약을 끊어도 돼요", "ASSESS_STATE"),
    ("의사가 줄이라고 했는데 어떻게 줄여요", "STOP_DOSE_CHANGE"),
])
def test_guardrail_reason_flows_to_finalize_summary(question, key):
    g = guardrail_in(question)
    keys = g.get("refuse_reasons") or [g.get("refuse_reason")]
    assert key in keys
    resp = finalize([], model_summary="모델 요약은 거절 경로에 나오지 않는다", refuse_reasons=keys)
    assert fp.REFUSE_MESSAGES[key] in resp["summary"]
    assert "모델 요약" not in resp["text"] and resp["route"] == "REFUSE"
