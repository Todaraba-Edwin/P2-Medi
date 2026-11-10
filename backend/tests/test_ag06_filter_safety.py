"""AG-06 문장 필터 안전 검사: 진단·처방·복용 결정 금지와 요약 용량 숫자 금지(RFP-21-03). LLM·외부 호출 없음, 시험 문장은 합성."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import DOSE_TEXT, S, label_items  # noqa: E402

from app.agent.answer_schema import AnswerDraft, Citation  # noqa: E402
from app.agent.renderer import render  # noqa: E402
from app.agent.sentence_filter import (  # noqa: E402
    DIAGNOSIS_CLAIM,
    DOSE_NUMBER,
    PRESCRIPTION_OR_DOSE_DECISION,
    filter_sentences,
    unsafe_reason,
)

EID = "pregnancy:300001ATB"
ITEMS = [{"evidence_id": EID, "kind": "pregnancy", "status": "FOUND", "flags": []}]

DOSE_UNITS = ["이 약은 500mg을 드는 약이에요.", "한 번에 2.5 ml 정도예요.", "10cc를 넣어요.", "5000IU 용량이에요.",
              "3정이면 돼요.", "2알씩이에요.", "5밀리그램이에요.", "한 알이에요.", "1티스푼이에요.", "20방울이에요.",
              "250 mg", "0.5g 사용"]
DOSE_FREQ = ["하루 3회예요.", "1일 2회 먹어요.", "매일 두 번이에요.", "8시간마다 간격을 둬요.", "6시간 간격이에요.",
             "7일간 복용해요.", "2주 동안 사용해요.", "하루에 한 번이에요.", "3회 복용이에요."]
DIAG = ["이 증상은 위염으로 진단돼요.", "당신은 폐렴입니다.", "고혈압병이에요.", "이건 천식증이에요.",
        "진단이 내려졌어요.", "지금 상태는 방광염일 가능성이 높아요.", "감기로 진단됩니다.", "환자분은 당뇨병이에요."]
PRESC = ["이 약을 처방해 드릴게요.", "처방합니다.", "이 약을 드세요.", "식후에 복용하세요.", "먹으세요.",
         "먹어도 돼요.", "복용하지 마세요.", "용량을 정해 드려요.", "당신에게 맞는 용량이 있어요."]
CHANGE = ["복용량을 늘리세요.", "약을 줄이세요.", "약을 끊으세요.", "복용을 중단하세요.", "복용을 중지하세요.",
          "용량을 조절하세요.", "줄여야 해요.", "바꿔도 돼요."]
PASS = ["12세 미만은 주의 항목에 올라 있어요.", "만 2세 미만 영아 항목이 있어요.", "6개월 미만 영아는 목록이 있어요.",
        "임신 후기에는 주의가 필요하다고 올라 있어요.", "임신 3개월 이내 항목이 있어요.", "2등급으로 올라 있어요.",
        "M등급은 상병에 따라 1등급 또는 2등급이라고 설명돼 있어요.", "고시 제3조 제3호의 정의를 따라요.", "연번 15 항목이에요.",
        "쪽 12에 나와요.", "기준일은 2026-07-21이에요.", "허가사항에 용법용량 안내가 있어요.", "병용 시 출혈 위험이 커질 수 있어요.",
        "약사에게 확인하세요.", "함께 복용하면 안 된다고 목록에 있어요.", "와파린과 병용하면 안 되는 약으로 올라 있어요.",
        "복용 전에 약사와 상의하세요.", "의사의 처방이 필요한 약이에요.", "처방전이 있으면 약사에게 보여 주세요.",
        "드시기 전에 약사에게 확인하세요.", "금기 목록에서 찾지 못했어요. 안전하다는 뜻은 아니에요.", "정보가 부족해요.",
        "한국의약품안전관리원 자료예요."]


def one(text, ct="fact"):
    return filter_sentences(AnswerDraft(sentences=[S(text, [EID], ct)]), ITEMS)


@pytest.mark.parametrize("text", DOSE_UNITS + DOSE_FREQ)
def test_dose_number_dropped(text):
    f = one(text)
    assert f.dropped_count == 1 and f.dropped[0].reason == DOSE_NUMBER and f.kept == []


@pytest.mark.parametrize("text", DIAG)
def test_diagnosis_dropped(text):
    assert unsafe_reason(text) == DIAGNOSIS_CLAIM
    f = one(text, "conclusion")
    assert f.dropped[0].reason == DIAGNOSIS_CLAIM


@pytest.mark.parametrize("text", PRESC + CHANGE)
def test_prescription_or_decision_dropped(text):
    f = one(text, "guidance")
    assert f.dropped_count == 1 and f.dropped[0].reason == PRESCRIPTION_OR_DOSE_DECISION and f.kept == []


@pytest.mark.parametrize("text", PASS)
def test_boundary_passes(text):
    assert unsafe_reason(text) is None
    f = one(text)
    assert f.dropped_count == 0 and [s.text for s in f.kept] == [text]


def test_pass_and_drop_counts_meet_minimum():
    assert len(PASS) >= 15 and len(DOSE_UNITS + DOSE_FREQ + DIAG + PRESC + CHANGE) >= 15
    assert len(DOSE_UNITS) >= 5 and len(DOSE_FREQ) >= 5 and len(DIAG) >= 5 and len(PRESC) >= 5 and len(CHANGE) >= 5


def test_spacing_variant_is_dropped():
    assert unsafe_reason("하 루 3 회  5 0 0 mg 씩") == DOSE_NUMBER


def test_events_reasons_and_no_text_leak():
    secret = "비밀문장 하루 3회 500mg 복용하세요"
    d = AnswerDraft(sentences=[S("하루 3회 500mg씩 드세요.", [EID]), S("위염으로 진단돼요.", [EID], "conclusion"),
                               S("처방해 드릴게요.", [EID], "guidance"), S(secret, [EID]), S("약사에게 확인하세요.", [], "guidance")])
    f = filter_sentences(d, ITEMS)
    ev = f.events[0]
    assert ev["total"] == 5 and ev["kept"] == 1 and ev["dropped"] == 4
    assert ev["reasons"] == {DOSE_NUMBER: 2, DIAGNOSIS_CLAIM: 1, PRESCRIPTION_OR_DOSE_DECISION: 1}
    assert "비밀문장" not in repr(f.events) and "500mg" not in repr(f.events)
    assert [s.text for s in f.kept] == ["약사에게 확인하세요."]


def test_evidence_checks_take_priority():
    f = filter_sentences(AnswerDraft(sentences=[S("하루 3회 500mg씩 드세요.", ["x:999"])]), ITEMS)
    assert f.dropped[0].reason == "UNKNOWN_EVIDENCE"
    f = filter_sentences(AnswerDraft(sentences=[S("하루 3회 500mg씩 드세요.")]), ITEMS)
    assert f.dropped[0].reason == "NO_EVIDENCE"


def test_detail_quote_with_dose_unaffected_by_summary_filter():
    items = label_items()
    eid = items[0]["evidence_id"]
    d = AnswerDraft(sentences=[S("허가사항에 용법용량 안내가 있어요.", [eid], "fact", [Citation(evidence_id=eid, start=0, end=len(DOSE_TEXT))])])
    f = filter_sentences(d, items)
    assert f.dropped_count == 0 and f.bad_quotes == 0
    res = render(items, f.kept)
    assert res.citations[0]["quotes"][0]["text"] == DOSE_TEXT           # 원문 용량 숫자는 근거 상세에 그대로
    assert any(c.isdigit() for c in DOSE_TEXT)
