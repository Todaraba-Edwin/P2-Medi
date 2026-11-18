"""AG-07 ⑬ H29 출처 종류 누락 검사와 실패 처리 표(`CHECK_ACTIONS`) 시험. LLM·외부 호출 없음, 항목·문장은 합성이다(평가 세트 아님)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import S, check_items_pair, easy_label_items, identify_items, label_items  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import validator as V  # noqa: E402
from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.agent.finalize import BUCKET_UNCONFIRMED, _bucket  # noqa: E402
from app.agent.validator import (  # noqa: E402
    CHECK_ACTIONS,
    CHECK_RULES,
    DROPPED,
    FAIL,
    FIXED,
    PASS,
    REWIND,
    SOURCE_KIND_MISSING,
    VALID_SOURCE_KINDS,
    validate,
)

EID = "pregnancy:900001ATB"


def preg_item(sk="FILE", status="FOUND", eid=EID):
    return {"kind": "pregnancy", "status": status, "evidence_id": eid, "source_kind": sk, "flags": [], "dataset_key": "pregnancy",
            "source": "한국의약품안전관리원", "as_of": "2026-07-21", "drugs": ["합성정"],
            "matches": [{"grade": "1", "detail": "합성 상세", "row_evidence_id": eid + "#a", "row_key": "a"}] if status == "FOUND" else []}


def draft(*sents):
    return AnswerDraft(sentences=list(sents))


def checks(r):
    return [i.check for i in r.issues]


# ------------------------------------------------------------------ ⑬ H29
@pytest.mark.parametrize("sk", [None, "", "WEB", "file"])
def test_found_item_without_valid_source_kind_drops_citing_sentence(sk):
    r = validate(draft(S("합성정은 임부금기 1등급으로 올라 있어요.", [EID])), [preg_item(sk)])
    assert checks(r) == [SOURCE_KIND_MISSING] and r.status == FAIL and r.kept == []


def test_not_listed_item_without_source_kind_is_also_checked():
    r = validate(draft(S("합성정은 임부금기 목록에 올라 있지 않아요.", [EID])), [preg_item(None, status="NOT_LISTED")])
    assert checks(r) == [SOURCE_KIND_MISSING]


def test_row_evidence_id_resolves_to_item():
    r = validate(draft(S("합성정은 임부금기 1등급으로 올라 있어요.", [EID + "#a"])), [preg_item(None)])
    assert checks(r) == [SOURCE_KIND_MISSING]


@pytest.mark.parametrize("sk", sorted(VALID_SOURCE_KINDS))
def test_valid_source_kinds_pass(sk):
    r = validate(draft(S("합성정은 임부금기 1등급으로 올라 있어요.", [EID])), [preg_item(sk)])
    assert SOURCE_KIND_MISSING not in checks(r)


def test_unidentified_and_no_evidence_items_are_not_h29():
    """미식별·근거 없음 항목은 원래 출처 종류가 없다(도구 출력 계약). H29가 아니라 ⑪·⑫ 몫이다."""
    for st in ("UNIDENTIFIED", "NO_EVIDENCE"):
        r = validate(draft(S("합성정은 확인하지 못했어요. 약사에게 확인하세요.", [EID], "guidance")), [preg_item(None, status=st)])
        assert SOURCE_KIND_MISSING not in checks(r), st


def test_only_the_citing_sentence_is_dropped_and_counted_as_h29():
    good = {**preg_item("FILE", eid="pregnancy:900002ATB"), "drugs": ["다른정"]}
    r = validate(draft(S("합성정은 임부금기 1등급으로 올라 있어요.", [EID]), S("다른정은 임부금기 1등급으로 올라 있어요.", [good["evidence_id"]])),
                 [preg_item(None), good])
    assert r.status == FIXED and checks(r) == [SOURCE_KIND_MISSING] and len(r.kept) == 1
    ev = r.events[0]
    assert ev["rules"] == {"H29": 1} and ev["reasons"] == {SOURCE_KIND_MISSING: 1} and "합성정" not in str(ev)


def test_uncited_sentence_is_not_affected():
    r = validate(draft(S("약국·약사에게 확인하세요.", [], "guidance")), [preg_item(None)])
    assert r.status == PASS


def test_same_criterion_as_finalize_bucket():
    """finalize가 "확인하지 못함"으로 내리는 판정 항목과 Validator가 H29로 보는 항목이 같다."""
    for sk in (None, "WEB", *VALID_SOURCE_KINDS):
        for st in ("FOUND", "NOT_LISTED"):
            it = preg_item(sk, status=st)
            assert V._source_kind_missing(it) == (_bucket(it) == BUCKET_UNCONFIRMED and sk not in VALID_SOURCE_KINDS), (sk, st)
    assert VALID_SOURCE_KINDS == frozenset(fp.SOURCE_KIND_TEXT)


def test_tool_fixture_items_have_no_h29_hit():
    """오탐 점검(합성 도구 출력): 실제 도구 함수가 만든 항목에서 H29 대상이 0건이다."""
    items = [*check_items_pair(age={"value": 5, "unit": "세"}), *label_items(), *easy_label_items(), *identify_items("타이레놀정")]
    assert items and not [it.get("evidence_id") for it in items if V._source_kind_missing(it)]


# ------------------------------------------------------------------ 실패 처리 표
def _check_names() -> set[str]:
    return {v for k, v in vars(V).items() if isinstance(v, str) and k == v and k.isupper()
            and k not in {V.PASS, V.FIXED, V.FAIL, DROPPED, REWIND}}


def test_every_check_has_an_action():
    assert set(CHECK_ACTIONS) == _check_names()
    assert set(CHECK_ACTIONS.values()) <= {DROPPED, REWIND}
    # 기준선 되감기는 ⑥ 하나, (개선) ⑯ 주장 유형 누락(`layer_check=True`일 때만 생김, AG-13-08 A)이 둘째다
    assert [k for k, v in CHECK_ACTIONS.items() if v == REWIND] == [V.MISSING_ADVICE_ABSENT, V.CLAIM_OMITTED]
    assert set(CHECK_RULES) <= set(CHECK_ACTIONS)


def test_issue_action_comes_from_table():
    r = validate(draft(S("이 약은 안전합니다.", [EID], "conclusion")), [preg_item("FILE")])
    assert [(i.check, i.action) for i in r.issues] == [(V.SAFE_ASSERTION, CHECK_ACTIONS[V.SAFE_ASSERTION])]
