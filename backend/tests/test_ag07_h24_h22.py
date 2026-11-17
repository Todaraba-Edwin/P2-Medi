"""AG-07 H24(`GRADE_EXCEPTION_MISUSE`) 기준선 패턴과 H22 승격(`M_CONVERTED` 등 규칙 번호 명시) 시험.

RFP-29-03 A(2026-11-16), RFP-29 §6 H22·H24. LLM·외부 호출 없음. 시험 문장·항목은 합성이다(평가 세트 아님).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import S, check_items_pair  # noqa: E402

from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.agent.validator import (  # noqa: E402
    CHECK_RULES,
    FAIL,
    GRADE_EXCEPTION_MISUSE,
    GRADE_VALUE_INVALID,
    M_CONVERTED,
    M_NO_DETAIL,
    PASS,
    SAFE_ASSERTION,
    _has_grade_exception_misuse,
    validate,
)

PREG = "pregnancy:300001ATB"          # 합성 fixture의 임부금기 2등급 항목
QUOTE_EID = "pregnancy:900003ATB"
QUOTE_DETAIL = "치료상의 유익성이 위험성을 상회하는 경우 예외적으로 사용 가능"   # 합성 상세 원문(인용 구간 예외 시험용)


def preg_item(grade: str, eid: str, detail: str = "적응증에 따라 등급이 달라요(합성)") -> dict:
    return {"kind": "pregnancy", "status": "FOUND", "evidence_id": eid, "source_kind": "FILE", "flags": [], "dataset_key": "pregnancy",
            "source": "한국의약품안전관리원", "as_of": "2026-07-21",
            "matches": [{"grade": grade, "detail": detail, "row_evidence_id": eid + "#a", "row_key": "a"}]}


@pytest.fixture(scope="module")
def items():
    # 1·2·M 등급이 모두 근거에 있어야 ⑧(근거에 없는 등급) 검사와 섞이지 않는다
    return [*check_items_pair(), preg_item("1", "pregnancy:900001ATB"), preg_item("M", "pregnancy:900002ATB"),
            preg_item("2", QUOTE_EID, QUOTE_DETAIL)]


def run(text: str, items: list, ids=(PREG,), ct: str = "fact"):
    r = validate(AnswerDraft(sentences=[S(text, list(ids), ct)]), items)
    return r, [i.check for i in r.issues]


# ------------------------------------------------------------------ H24 차단 문장(갈래 ⓐ 등급+허용 ⓑ 예외+허용 ⓒ 서열 ⓓ 사유 기재 불필요)
H24_BLOCK = [
    ("2등급이라 괜찮아요.", "ⓐ"),
    ("2등급은 드셔도 돼요.", "ⓐ"),
    ("네, 2등급은 먹어도 괜찮아요.", "ⓐ 오정보 문항 '2등급은 먹어도 되죠?'에 동조"),
    ("2등급이면 의사와 상의 없이 써도 됩니다.", "ⓐ"),
    ("임부금기 2등급 약이라 걱정하지 않으셔도 돼요.", "ⓐ"),
    ("예외로 복용하셔도 돼요.", "ⓑ"),
    ("예외에 해당하니 드셔도 됩니다.", "ⓑ"),
    ("2등급은 예외적으로 복용할 수 있어요.", "ⓑ"),
    ("2등급은 1등급보다 덜 위험해요.", "ⓒ"),
    ("2등급은 약한 금기예요.", "ⓒ"),
    ("M등급은 위험이 낮은 편이에요.", "ⓒ"),
    ("2등급 약은 비교적 안전해요.", "ⓒ"),
    ("처방 사유 기재가 필요 없으니 부담 없이 드셔도 돼요.", "ⓓ"),
    ("사유 기재 불필요 약이라 걱정하지 않아도 돼요.", "ⓓ"),
]

# ------------------------------------------------------------------ H24 통과 문장(오탐 방지)
H24_PASS = [
    "임부금기 2등급으로 올라 있는 금기입니다.",
    "1등급과 2등급 모두 임부에게 원칙적으로 사용을 금하는 금기예요.",
    "2등급이라고 덜 위험한 것은 아니에요.",
    "2등급이라도 먹어도 된다는 뜻은 아니에요.",
    "2등급은 먹어도 되냐고 물으셨는데, 2등급도 임부금기예요.",
    "사유 기재 불필요는 처방 시스템 규칙이고 복용해도 된다는 뜻이 아니에요.",
    "M등급은 상병에 따라 1등급 또는 2등급이라고 설명돼 있어요.",
    "2등급도 1등급처럼 피해야 하는 금기예요.",
    "등급은 위험의 크기 순서를 뜻하지 않아요.",
    "2등급은 의사가 치료상 꼭 필요하다고 판단한 경우에만 쓰는 금기라서 의사·약사와 상의하세요.",
]


@pytest.mark.parametrize(("text", "branch"), H24_BLOCK)
def test_h24_misuse_blocked(text, branch, items):
    r, why = run(text, items)
    assert why == [GRADE_EXCEPTION_MISUSE], (branch, why)
    assert r.status == FAIL and r.kept == []


@pytest.mark.parametrize("text", H24_PASS)
def test_h24_normal_sentences_pass(text, items):
    r, why = run(text, items, ids=(PREG, "pregnancy:900002ATB"))   # M 언급 문장은 M 근거를 인용해야 ④를 통과한다
    assert why == [] and r.status == PASS, why


def test_h24_label_quote_span_is_exempt(items):
    # 근거 상세 원문을 인용부호로 그대로 옮긴 구간은 차단하지 않는다(허가사항·고시 원문 인용 예외)
    quoted = f"상세정보에는 「{QUOTE_DETAIL}」이라고 적혀 있어요."
    assert run(quoted, items, ids=(QUOTE_EID,))[1] == []
    # 같은 글자를 인용부호 없이 모델 문장으로 쓰면 차단한다
    assert run(f"{QUOTE_DETAIL}해요.", items, ids=(QUOTE_EID,))[1] == [GRADE_EXCEPTION_MISUSE]
    # 근거 원문에 없는 글자를 인용부호로 감싸도 예외가 아니다
    assert run("「2등급은 예외로 복용하셔도 돼요」라고 해요.", items, ids=(QUOTE_EID,))[1] == [GRADE_EXCEPTION_MISUSE]


def test_h24_takes_precedence_over_safe_assertion(items):
    # "괜찮아요"는 ① 안전 단정이기도 하지만 등급이 근거로 쓰이면 더 구체적인 H24 코드로 집계한다
    assert run("2등급이라 괜찮아요.", items)[1] == [GRADE_EXCEPTION_MISUSE]
    assert run("이 약은 괜찮아요.", items)[1] == [SAFE_ASSERTION]


def test_h24_pattern_function_direct():
    assert _has_grade_exception_misuse("2등급이라괜찮아요.")
    assert not _has_grade_exception_misuse("2등급이라괜찮다는뜻이아니에요.")
    assert not _has_grade_exception_misuse("2등급은괜찮을까요?라고물으셨어요.")


# ------------------------------------------------------------------ H22 승격: 규칙 번호 명시(동작 불변)
def test_check_rules_mapping():
    assert CHECK_RULES[M_CONVERTED] == "H22"
    assert CHECK_RULES[M_NO_DETAIL] == "H22"
    assert CHECK_RULES[GRADE_VALUE_INVALID] == "H22"
    assert CHECK_RULES[GRADE_EXCEPTION_MISUSE] == "H24"
    assert SAFE_ASSERTION not in CHECK_RULES   # 나머지 검사는 VALIDATOR 이벤트 기본 규칙(H2)으로 남는다


def test_h22_m_converted_event_counts_rule(items):
    r, why = run("M등급은 사실상 2등급이에요.", items, ids=("pregnancy:900002ATB",))
    assert why == [M_CONVERTED]
    ev = r.events[0]
    assert ev["rule"] == "H2" and ev["reasons"] == {M_CONVERTED: 1} and ev["rules"] == {"H22": 1}


def test_h24_event_counts_rule_without_text(items):
    r = validate(AnswerDraft(sentences=[S("2등급이라 괜찮아요.", [PREG]), S("임부금기 2등급으로 올라 있어요.", [PREG])]), items)
    ev = r.events[0]
    assert ev["reasons"] == {GRADE_EXCEPTION_MISUSE: 1} and ev["rules"] == {"H24": 1}
    assert "괜찮" not in repr(ev)


def test_rules_empty_when_nothing_mapped(items):
    assert validate(AnswerDraft(sentences=[S("임부금기 2등급으로 올라 있어요.", [PREG])]), items).events[0]["rules"] == {}
