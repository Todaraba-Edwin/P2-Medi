"""검증 폴백 요약 문구 2종(AG-01·AG-08): 선택·날짜 생략 변형·다른 경로 불변·"안전" 단정 0건."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent import fixed_phrases as fp
from app.agent.answer_schema import AnswerDraft, Sentence
from app.agent.finalize import fallback_summary, finalize
from app.agent.sentence_filter import filter_sentences, unsafe_reason
from app.agent.validator import validate


def _item(status: str, **kw: Any) -> dict[str, Any]:
    base = {"kind": "contra_pair", "status": status, "subject": ["A"], "evidence_id": f"e:{status}", "source": "KIDS", "as_of": "2026-07-21",
            "flags": [], "matches": [], "source_kind": "FILE", "drugs": ["가약", "나약"]}
    base.update(kw)
    return base


FOUND = _item("FOUND")
NOT_LISTED = _item("NOT_LISTED", evidence_id="e:nl")
MISS = _item("NO_EVIDENCE", missing_reason="SEARCH_MISS", as_of=None, source_kind=None, queried_at_display="2026-11-11 09:00 (KST)")


def test_some_when_any_judged_item():
    exp = fp.FALLBACK_SOME_CONFIRMED.format(datasets="병용금기 파일(기준일 2026-07-21)")
    assert fallback_summary([MISS, FOUND]) == exp
    assert fallback_summary([NOT_LISTED]) == exp


def test_none_with_both_dates_and_variants():
    full = _item("NO_EVIDENCE", missing_reason="ABSENT", queried_at_display="2026-11-11 09:00 (KST)")
    assert fallback_summary([full]) == ("검색한 자료(API 조회 2026-11-11 09:00 (KST), 병용금기 파일 기준일 2026-07-21)에서는 확인하지 못했어요. "
                                        "정확한 확인은 약국·약사에게 하세요.")
    assert "기준일" not in fallback_summary([MISS]) and "API 조회 2026-11-11" in fallback_summary([MISS])
    only_doc = _item("NO_EVIDENCE", missing_reason="ABSENT")
    assert fallback_summary([only_doc]) == fp.FALLBACK_NONE_CONFIRMED.format(scope="병용금기 파일 기준일 2026-07-21")
    bare = _item("NO_EVIDENCE", missing_reason="ABSENT", as_of=None)
    assert fallback_summary([bare]) == fp.FALLBACK_NONE_NO_SCOPE == fallback_summary([])


def test_demoted_or_unsourced_judged_items_do_not_count_as_confirmed():
    assert fallback_summary([_item("FOUND", flags=["CODE_NOT_LINKED"])]).startswith("검색한 자료")
    assert fallback_summary([_item("FOUND", source_kind=None)]).startswith("검색한 자료")


def test_some_without_date_omits_it():
    s = fallback_summary([_item("FOUND", as_of=None)])  # 날짜는 없고 자료 이름만(날짜를 지어내지 않는다)
    assert s == fp.FALLBACK_SOME_CONFIRMED.format(datasets="병용금기 파일") and "None" not in s and "기준일" not in s
    unnamed = fallback_summary([_item("FOUND", kind="zzz", as_of=None)])
    assert unnamed == fp.FALLBACK_SOME_NO_DATE


def test_some_lists_each_dataset_date_in_item_order():  # AG-08-03 B
    combo = _item("FOUND", kind="contra_pair", as_of="2026-07-31", evidence_id="e:c")
    preg = _item("FOUND", kind="pregnancy", as_of="2026-07-21", evidence_id="e:p")
    lact = _item("NOT_LISTED", kind="lactation", as_of="2025-11-27", evidence_id="e:l")
    exp = "병용금기 파일(기준일 2026-07-31)·임부금기 파일(기준일 2026-07-21)에서 확인된 내용만 아래에 보여 드려요."
    assert fallback_summary([combo, preg]).startswith(exp)
    assert fallback_summary([preg, combo]).startswith("임부금기 파일(기준일 2026-07-21)·병용금기 파일(기준일 2026-07-31)")  # 순서는 항목 순서
    three = fallback_summary([combo, preg, lact])
    assert "수유부주의 파일(기준일 2025-11-27)" in three and three.count("기준일") == 3
    # 같은 (자료, 날짜)는 한 번만
    dup = fallback_summary([combo, _item("FOUND", kind="contra_pair", as_of="2026-07-31", evidence_id="e:c2"), preg])
    assert dup.count("병용금기 파일") == 1 and dup.count("기준일") == 2
    # 같은 자료의 날짜가 다르면 둘 다, 날짜 없는 같은 자료는 날짜 있는 쪽에 흡수
    two_dates = fallback_summary([combo, _item("FOUND", kind="contra_pair", as_of="2026-08-01", evidence_id="e:c3")])
    assert "2026-07-31" in two_dates and "2026-08-01" in two_dates
    mixed = fallback_summary([_item("FOUND", kind="pregnancy", as_of=None, evidence_id="e:x"), preg])
    assert mixed.count("임부금기 파일") == 1 and "(기준일 2026-07-21)" in mixed
    # 확인되지 않은 항목의 날짜는 SOME 문구에 섞이지 않는다
    assert "수유부" not in fallback_summary([combo, _item("NO_EVIDENCE", kind="lactation", missing_reason="ABSENT", as_of="2025-11-27")])


def test_none_lists_each_dataset_date():
    a = _item("NO_EVIDENCE", kind="contra_pair", missing_reason="ABSENT", as_of="2026-07-31", source_kind=None)
    b = _item("NO_EVIDENCE", kind="pregnancy", missing_reason="ABSENT", as_of="2026-07-21", source_kind=None, queried_at_display="2026-11-11 09:00 (KST)")
    c = _item("NO_EVIDENCE", kind="pregnancy", missing_reason="ABSENT", as_of="2026-07-21", source_kind=None, evidence_id="e:d")
    assert fallback_summary([a, b, c]) == fp.FALLBACK_NONE_CONFIRMED.format(
        scope="API 조회 2026-11-11 09:00 (KST), 병용금기 파일 기준일 2026-07-31, 임부금기 파일 기준일 2026-07-21")
    unnamed = _item("NO_EVIDENCE", kind="zzz", missing_reason="ABSENT", as_of="2026-07-21", source_kind=None)
    assert "문서 기준일 2026-07-21" in fallback_summary([unnamed])


def test_summary_only_on_validation_fallback():
    on = finalize([FOUND], validation_fallback=True)
    assert on["summary"] == fp.FALLBACK_SOME_CONFIRMED.format(datasets="병용금기 파일(기준일 2026-07-21)")
    assert on["summary"] in on["text"]
    off = finalize([FOUND])
    assert off["summary"] is None
    assert finalize([FOUND], model_summary="요약이에요")["summary"] == "요약이에요"
    assert finalize([FOUND], limit_reached=True)["summary"] is None
    assert finalize([], refuse_reason="DOSAGE")["summary"] == fp.REFUSE_MESSAGES["DOSAGE"]
    assert finalize([], model_summary="어느 약이에요?")["summary"] == "어느 약이에요?"


def test_other_fields_unchanged_by_fallback_flag():
    for emergency in (False, True):
        on = finalize([FOUND, MISS], emergency=emergency, validation_fallback=True)
        off = finalize([FOUND, MISS], emergency=emergency)
        for k in on:
            if k not in ("summary", "text"):
                assert on[k] == off[k], k
        assert (on["emergency"] == fp.EMERGENCY_119) is emergency
        if emergency:
            assert on["text"].splitlines()[0] == fp.EMERGENCY_119


_MULTI = [_item("FOUND", kind="contra_pair", as_of="2026-07-31", evidence_id="e:c"), _item("FOUND", kind="pregnancy", evidence_id="e:p")]


@pytest.mark.parametrize("items", [[], [FOUND], [MISS], [_item("FOUND", as_of=None)], [_item("NO_EVIDENCE", as_of=None, source_kind=None)], _MULTI])
def test_phrases_never_assert_safety(items):
    text = fallback_summary(items)
    assert unsafe_reason(text) is None
    assert not any(w in text for w in ("안전", "괜찮", "문제없", "문제 없")) and not any(t in text for t in fp.FORBIDDEN_SCREEN_TERMS)
    for const in (fp.FALLBACK_NONE_CONFIRMED, fp.FALLBACK_NONE_NO_SCOPE, fp.FALLBACK_SOME_CONFIRMED, fp.FALLBACK_SOME_NO_DATE):
        assert unsafe_reason(const.format(scope="x", datasets="x")) is None
    # Recap 0-1 승인(2026-11-12, 하네스 3.4절 표): 폴백 문구는 초안 목록에서 해제됐다
    assert "FALLBACK_SOME_CONFIRMED" not in fp.DRAFT_KEYS and "FALLBACK_NONE_SCOPE_DOC" not in fp.DRAFT_KEYS
    assert "FALLBACK_NONE_CONFIRMED" not in fp.DRAFT_KEYS
    sent = Sentence(text=text, evidence_ids=[], claim_type="guidance", citations=[])
    assert unsafe_reason(sent.text) is None
    fr = filter_sentences(AnswerDraft(sentences=[sent]), items)  # 문장 필터·Validator가 0건 걸러낸다
    assert fr.kept and fr.events[0]["dropped"] == 0
    vr = validate(fr.kept, items)  # 날짜 숫자는 항목 값이라 근거 밖 숫자로 걸리지 않는다
    # 미확보 항목의 약 이름별 권고(MISSING_ADVICE_*)는 finalize가 코드로 붙이는 `pharmacist_advice` 몫이라 요약 한 문장에는 요구하지 않는다
    assert not [i for i in vr.issues if not i.check.startswith("MISSING_ADVICE")]
    assert not [i for i in vr.issues if i.check in ("SAFE_ASSERTION", "MISSING_IMPLIES_NONE")]
