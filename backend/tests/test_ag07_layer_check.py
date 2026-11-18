"""AG-07 (개선) 허용 근거 계층(⑭·⑮)·주장 유형 누락(⑯) 시험(AG-13-08 A). LLM·외부 호출 없음, 항목·문장은 합성이다(평가 세트 아님).

규칙의 근거는 개발셋 C2 judge 1회 실패 표(`AG07_LAYER_MISSING` 28행)의 관찰이며, 문장은 그 관찰을 본뜬 합성 문장이다(개발셋 문장을 옮기지 않았다).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import S, by_kind, check_items_pair, label_items  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.agent import validator as V  # noqa: E402
from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.agent.validator import (  # noqa: E402
    CHECK_ACTIONS,
    CLAIM_LAYER_NOT_ALLOWED,
    CLAIM_OMITTED,
    DROPPED,
    FAIL,
    FIXED,
    GAP_ANSWER_OMIT,
    GAP_RETRIEVAL_MISS,
    INGREDIENT_NOT_IN_EVIDENCE,
    PASS,
    REWIND,
    validate,
)

PREG = "pregnancy:900001ATB"
PAIR = "contra_pair:900001ATB:900002ATB"
CHUNK = "l2p-0000000000000001"
LABEL = "l3p-0000000000000001"
MISS = "search:search_label:000000000001"
REQ = [R.CLAIM_CONTRA_STATUS, R.CLAIM_LIMITATION]


def preg(status="FOUND", detail="합성 상세: 동물실험에서 생식 독성 보고.", eid=PREG):
    return {"kind": "pregnancy", "status": status, "evidence_id": eid, "source_kind": "FILE", "flags": [], "dataset_key": "pregnancy",
            "source": "한국의약품안전관리원", "as_of": "2026-07-21", "subject": ["900001ATB"], "drugs": ["합성정"],
            "matches": [{"grade": "2", "detail": detail, "row_evidence_id": eid + "#a", "row_key": "a"}] if status == "FOUND" else []}


def pair(status="NOT_LISTED"):
    return {"kind": "contra_pair", "status": status, "evidence_id": PAIR, "source_kind": "FILE", "flags": [], "dataset_key": "contra_pair",
            "source": "한국의약품안전관리원", "as_of": "2026-07-31", "subject": ["900001ATB", "900002ATB"], "drugs": ["합성정", "다른정"],
            "matches": [{"detail": "합성 사유", "row_evidence_id": PAIR + "#b", "row_key": "b"}] if status == "FOUND" else []}


def chunk(eid=CHUNK, text="합성 사유 문장: 혈중 농도가 올라갈 수 있다.", layer="L2"):
    return {"kind": "chunk", "status": "FOUND", "evidence_id": eid, "source_kind": "CORPUS_QUOTE", "flags": [], "matches": [],
            "verdict_allowed": False, "layer": layer, "text": text, "source": "합성 출처", "as_of": "2026-07-31", "subject": ["900001ATB"]}


def miss():
    return {"kind": "search_miss", "status": "NO_EVIDENCE", "evidence_id": MISS, "flags": [], "matches": [], "subject": []}


def draft(*sents):
    return AnswerDraft(sentences=list(sents))


def checks(r):
    return [i.check for i in r.issues]


def on(d, items, required=None):
    return validate(d, items, layer_check=True, required_claims=required)


# ------------------------------------------------------------------ 기본 꺼짐: 기준선과 같다
def test_constants_match_router_and_actions():
    assert V.CLAIM_CONTRA_STATUS == R.CLAIM_CONTRA_STATUS
    assert CHECK_ACTIONS[CLAIM_LAYER_NOT_ALLOWED] == DROPPED and CHECK_ACTIONS[INGREDIENT_NOT_IN_EVIDENCE] == DROPPED
    assert CHECK_ACTIONS[CLAIM_OMITTED] == REWIND


@pytest.mark.parametrize("text,ids,items", [
    ("해당 약의 성분은 데노수맙이며, 동물실험에서 생식 독성이 보고됐어요.", [PREG], lambda: [preg()]),
    ("금기 조회 결과에는 항목이 없어요.", [], lambda: [miss()]),
    ("합성정은 금기 목록에 올라 있지 않아요.", [CHUNK], lambda: [chunk()]),
])
def test_switch_off_is_baseline(text, ids, items):
    """꺼져 있으면(기본·`required_claims`만 줘도) 새 검사가 돌지 않고 이벤트 모양도 기준선과 같다."""
    d = draft(S(text, ids, "fact" if ids else "conclusion"))
    a, b = validate(d, items()), validate(d, items(), required_claims=REQ)
    assert a.status == b.status == PASS and a.issues == b.issues == [] and a.claim_gaps == b.claim_gaps == []
    assert "layer_check" not in a.events[0] and "claim_gaps" not in a.events[0]
    assert on(d, items(), REQ).status != PASS   # 켜면 걸린다(같은 입력)


# ------------------------------------------------------------------ ⑭ 금기 여부 문장은 L0 판정 항목을 인용해야 한다
def test_status_claim_citing_only_chunk_is_dropped():
    r = on(draft(S("합성정은 금기 목록에 올라 있지 않아요.", [CHUNK]), S("동물실험 보고가 있어요.", [PREG])), [chunk(), preg()])
    assert checks(r) == [CLAIM_LAYER_NOT_ALLOWED] and r.status == FIXED and len(r.kept) == 1


def test_status_claim_citing_verdict_item_passes():
    r = on(draft(S("합성정과 다른정은 병용금기 목록에 올라 있지 않아요.", [PAIR]), S("임부금기 2등급으로 올라 있어요.", [PREG + "#a"])),
           [pair(), preg()])
    assert r.status == PASS and r.issues == []


def test_uncited_status_conclusion_needs_verdict_item_in_bundle():
    """근거 ID 없이 쓸 수 있는 결론 문장: 묶음이 검색 실패뿐이면 금기 여부를 말할 수 없다(관찰: 검색 실패만 인용하고 "금기 조회 결과에 없음")."""
    bad = on(draft(S("허가사항은 찾지 못했어요.", [MISS]), S("금기 조회 결과에는 항목이 없지만, 이것만으로 안전하다고 볼 수는 없어요.", [], "conclusion")),
             [miss()])
    assert checks(bad) == [CLAIM_LAYER_NOT_ALLOWED] and bad.status == FIXED
    ok = on(draft(S("금기 목록에 올라 있지 않아요.", [], "conclusion")), [pair()])
    assert ok.status == PASS


@pytest.mark.parametrize("text", [
    "병용금기 사유로는 혈중 농도가 올라갈 수 있다는 내용이 있어요.",        # 사유 설명(L2 허용)
    "금기 여부는 이 자료에서 확인하지 못했어요.",                           # 확인 못 함을 전함
    "임부금기 자료에는 동물실험 보고가 있다고 적혀 있어요.",                 # 사유·보고 설명
])
def test_reason_or_unconfirmed_sentences_are_not_status_claims(text):
    r = on(draft(S(text, [CHUNK])), [chunk()])
    assert CLAIM_LAYER_NOT_ALLOWED not in checks(r)


def test_tool_items_layer_classification():
    """실제 도구 출력: 판정 항목(병용·임부 FOUND)은 L0, 허가사항 라벨·청크는 L0가 아니다."""
    items = check_items_pair()
    found = by_kind(items, "contra_pair", "FOUND") + by_kind(items, "pregnancy", "FOUND")
    assert found and all(V.is_verdict_item(it) for it in found)
    labels = label_items()
    assert labels and not any(V.is_verdict_item(it) for it in labels)
    assert not V.is_verdict_item(chunk()) and not V.is_verdict_item(miss())
    assert not V.is_verdict_item({**preg(), "flags": ["REFERENCE_ONLY"]})   # 참고 전용은 판정이 아니다


# ------------------------------------------------------------------ ⑮ 근거에 없는 성분명
def test_ingredient_name_not_in_evidence_is_dropped():
    r = on(draft(S("임부금기 2등급으로 올라 있어요.", [PREG]), S("해당 약의 성분은 데노수맙이며, 동물실험에서 생식 독성이 보고됐어요.", [PREG + "#a"])),
           [preg()])
    assert checks(r) == [INGREDIENT_NOT_IN_EVIDENCE] and r.status == FIXED and len(r.kept) == 1


def test_ingredient_name_in_evidence_passes():
    r = on(draft(S("해당 약의 성분은 데노수맙이며, 동물실험에서 생식 독성이 보고됐어요.", [PREG + "#a"])),
           [preg(detail="데노수맙: 동물실험에서 생식 독성 보고.")])
    assert r.status == PASS


def test_ingredient_list_one_missing_name_drops():
    items = [preg(detail="알로글립틴 25mg/메트포르민염산염 2,000 mg")]
    ok = on(draft(S("이 약의 성분인 알로글립틴·메트포르민염산염을 함께 확인했어요.", [PREG])), items)
    assert ok.status == PASS
    bad = on(draft(S("이 약의 성분인 알로글립틴·시타글립틴을 함께 확인했어요.", [PREG])), items)
    assert checks(bad) == [INGREDIENT_NOT_IN_EVIDENCE]


@pytest.mark.parametrize("text", [
    "이 약의 성분은 자료에서 확인되지 않았어요.",
    "두 약의 성분이 같은지는 약사에게 확인하세요.",
    "성분 정보는 제공되지 않았어요.",
])
def test_descriptive_ingredient_phrases_are_not_name_claims(text):
    r = on(draft(S(text, [PREG])), [preg()])
    assert INGREDIENT_NOT_IN_EVIDENCE not in checks(r)


# ------------------------------------------------------------------ ⑯ 주장 유형 누락(금기 여부)
def test_found_contra_not_cited_is_answer_omit_and_rewinds():
    """AG-07 §2 `:41`: 유형 하나(금기 여부)를 일부러 뺀 답변이 걸러진다. 묶음에는 있는데 답이 말하지 않았다(ANSWER_OMIT)."""
    r = on(draft(S("허가사항 안내에는 임부는 복용 전 상의하라고 적혀 있어요.", [LABEL])), [preg(), chunk(LABEL, "임부는 복용 전 상의할 것", "L3")], REQ)
    assert checks(r) == [CLAIM_OMITTED] and r.status == FAIL and r.kept    # 문장은 남기고 답변 단위 되감기
    assert r.claim_gaps == [{"claim": R.CLAIM_CONTRA_STATUS, "gap": GAP_ANSWER_OMIT, "evidence_id": PREG}]
    assert [i.action for i in r.issues] == [REWIND] and r.issues[0].text == PREG
    ev = r.events[0]
    assert ev["layer_check"] is True and ev["claim_gaps"] == {GAP_ANSWER_OMIT: 1} and ev["reasons"] == {CLAIM_OMITTED: 1}


@pytest.mark.parametrize("ids", [[PREG], [PREG + "#a"]])
def test_found_contra_cited_by_item_or_row_has_no_gap(ids):
    """"금기" 낱말까지는 요구하지 않는다(정상 답 다수가 "주의가 필요한 것으로 조회됐어요"로 쓰고 표지는 `finalize`가 붙인다)."""
    r = on(draft(S("임신 중에는 주의가 필요한 약으로 조회됐어요.", ids)), [preg()], REQ)
    assert r.status == PASS and r.claim_gaps == []


def test_not_listed_only_needs_no_sentence():
    r = on(draft(S("허가사항 안내를 확인해 보세요.", [], "guidance")), [pair("NOT_LISTED")], REQ)
    assert r.status == PASS and r.claim_gaps == []


def test_no_verdict_item_is_retrieval_miss_recorded_only():
    """묶음에 판정 항목이 없다(조회 누락): 기록만 하고 되감지 않는다(나이·임신 정보가 없어 조회 자체를 못 한 경우가 있다)."""
    r = on(draft(S("허가사항에는 소아 투여 주의가 있어요.", [LABEL])), [chunk(LABEL, "소아 투여 주의", "L3")], REQ)
    assert r.status == PASS and r.issues == []
    assert r.claim_gaps == [{"claim": R.CLAIM_CONTRA_STATUS, "gap": GAP_RETRIEVAL_MISS, "evidence_id": None}]
    assert r.events[0]["claim_gaps"] == {GAP_RETRIEVAL_MISS: 1}


@pytest.mark.parametrize("required", [None, [], [R.CLAIM_LIMITATION, R.CLAIM_PRODUCT_CAUTION]])
def test_gap_check_needs_contra_status_in_required_claims(required):
    r = on(draft(S("허가사항 안내에는 상의하라고 적혀 있어요.", [LABEL])), [preg(), chunk(LABEL, "상의할 것", "L3")], required)
    assert r.claim_gaps == [] and r.status == PASS


def test_gap_check_counts_only_kept_sentences():
    """다른 검사로 지워진 문장의 인용은 세지 않는다(남은 문장만 화면에 나간다)."""
    r = on(draft(S("이 약은 안전합니다.", [PREG]), S("허가사항에는 상의하라고 적혀 있어요.", [LABEL])),
           [preg(), chunk(LABEL, "상의할 것", "L3")], REQ)
    assert checks(r) == [V.SAFE_ASSERTION, CLAIM_OMITTED] and r.status == FAIL


def test_event_and_gaps_hold_no_sentence_text():
    text = "해당 약의 성분은 데노수맙이며, 동물실험에서 생식 독성이 보고됐어요."
    r = on(draft(S(text, [PREG])), [preg(), pair("FOUND")], REQ)
    dumped = json.dumps([r.events, r.claim_gaps], ensure_ascii=False)
    assert "데노수맙" not in dumped and "생식" not in dumped
