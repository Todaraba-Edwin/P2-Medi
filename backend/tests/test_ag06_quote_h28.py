"""AG-06·AG-07 H28 인용 글자 일치(`QUOTE_MISMATCH`) 시험. LLM·외부 호출 없음, 청크·문장은 모두 합성이다(평가 세트 아님).

검사: 문장에 연결된 근거에 원문 인용 대상(`CORPUS_QUOTE` 청크·라벨 항목)이 있으면, 큰따옴표·낫표 안 글자가
연결된 근거 원문 **하나**에 글자 그대로 있어야 한다(공백·줄바꿈 제거만 허용, 생략은 `…`).
양성(걸러야 함)과 음성(정상 문장, 오탐 0)을 나누어 본다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "contract"))
from ag06_fixtures import S, label_items  # noqa: E402

from app.agent.answer_schema import AnswerDraft, Citation  # noqa: E402
from app.agent.sentence_filter import NO_EVIDENCE, UNKNOWN_EVIDENCE, filter_sentences  # noqa: E402
from app.agent.tools.search_common import chunk_item  # noqa: E402
from app.agent.validator import FIXED, PASS, QUOTE_MISMATCH, validate  # noqa: E402

C1, C2, C_EASY_MISS, C_EMPTY = "chunk:l3:synthA#p1", "chunk:l3:synthA#p2", "chunk:l3:synthB#p1", "chunk:l3:synthC#p1"
T1 = "이 약은 위장 장애가 있는 환자에게 신중히 투여한다.\n임부에게는 치료상의 유익성이 위험성을 상회한다고 판단되는 경우에만 투여한다."
T2 = "졸음이 올 수 있으므로 운전이나 기계 조작을 피한다."
T_PRMSN = "다음 환자에는 투여하지 말 것. 이 약에 과민증이 있는 환자"
PREG = "pregnancy:300001ATB"


def _chunk(cid: str, text: str, *, label: bool = False, doc_type: str = "허가정보 상세") -> dict:
    return {"chunk_id": cid, "chunk_kind": "l3_prmsn_para", "text": text, "issuer": "식품의약품안전처", "source_ref": "합성|1",
            "base_date": "2026-07-21", "layer": "L3", "item_seq": "999999999", "section": "주의사항", "item_name": "합성정", "doc_type": doc_type}


def _items() -> list[dict]:
    its = [chunk_item(_chunk(C1, T1), relation="hit", from_id=None, hit=None),
           chunk_item(_chunk(C2, T2), relation="section", from_id=C1, hit=None),
           # 쉬운 설명(e약은요)이 없는 품목: 허가 상세 원문만 있다(search_label H18)
           chunk_item(_chunk(C_EASY_MISS, T_PRMSN), relation="hit", from_id=None, hit=None, label=True, flags=["EASY_TEXT_MISSING"]),
           # 원문이 빈 청크
           chunk_item(_chunk(C_EMPTY, ""), relation="hit", from_id=None, hit=None, label=True, flags=["EASY_TEXT_MISSING"])]
    its.append({"kind": "pregnancy", "status": "FOUND", "evidence_id": PREG, "source_kind": "FILE", "flags": [], "dataset_key": "pregnancy",
                "source": "한국의약품안전관리원", "as_of": "2026-07-21",
                "matches": [{"grade": "2", "detail": "태아 독성 우려가 보고되어 있음", "row_evidence_id": PREG + "#a", "row_key": "a"}]})
    return its


ITEMS = _items()


def run(text: str, ids, ct: str = "fact", cites=(), items=None):
    r = validate(AnswerDraft(sentences=[S(text, list(ids), ct, list(cites))]), items or ITEMS)
    return r, [i.check for i in r.issues]


# ---------------------------------------------------------------------------------------- 양성: 걸러야 한다
POSITIVE = [
    # (설명, 문장, 근거 ID)
    ("글자 한 자 다름", "허가사항 원문에 “임부에게는 치료상의 유익성이 위험성을 상외한다고 판단되는 경우에만 투여한다”라고 나와요.", [C1]),
    ("글자 한 자 더함", "원문은 \"졸음이 올 수 있으므로 운전이나 기계 조작을 꼭 피한다\"예요.", [C2]),
    ("의역", "원문에는 “임신 중에는 이득이 클 때만 쓴다”고 되어 있어요.", [C1]),
    ("청크를 가로지르는 인용(두 근거 모두 연결)", "원문에 “경우에만 투여한다. 졸음이 올 수 있으므로”라고 이어져 있어요.", [C1, C2]),
    ("연결하지 않은 청크의 문장 인용", "원문에 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”라고 나와요.", [C1]),
    ("원문이 빈 청크(EASY_TEXT_MISSING) 인용", "쉬운 설명에 “이 약은 열을 내리는 약이에요”라고 나와요.", [C_EMPTY]),
    ("쉬운 설명이 없는 품목에 쉬운 설명식 인용", "쉬운 설명에 “과민증이 있는 분은 먹으면 안 돼요”라고 되어 있어요.", [C_EASY_MISS]),
    ("생략 조각 순서 뒤바뀜", "원문은 “경우에만 투여한다…임부에게는 치료상의”예요.", [C1]),
    ("생략을 점 세 개로 씀(허용 안 함)", "원문은 “임부에게는 치료상의...경우에만 투여한다”예요.", [C1]),
    ("인용 둘 중 하나만 틀림", "원문에 “신중히 투여한다”와 “운전이나 기계 조작을 반드시 피한다”가 있어요.", [C1, C2]),
    ("낫표 인용 불일치", "원문은 「위장 장애가 있는 환자에게는 투여하지 않는다」예요.", [C1]),
    ("낫표 겹 인용 불일치", "원문은 『이 약에 과민증이 있는 어린이』예요.", [C_EASY_MISS]),
    ("지어낸 인용 안의 안전 단정도 인용 불일치로 먼저 걸린다", "원문에 “함께 먹어도 괜찮다고 판단되는 경우”라고 나와요.", [C1]),
    ("근거가 FILE과 청크 함께인데 어느 쪽에도 없음", "원문에 “태아 독성 우려가 없다고 보고되어 있음”이라고 나와요.", [C1, PREG]),
]


@pytest.mark.parametrize(("why", "text", "ids"), POSITIVE, ids=[p[0] for p in POSITIVE])
def test_positive_quote_mismatch_dropped(why, text, ids):
    r, reasons = run(text, ids)
    assert reasons == [QUOTE_MISMATCH], (why, reasons)
    assert r.kept == []
    ev = r.events[0]
    assert ev["reasons"] == {QUOTE_MISMATCH: 1} and ev["dropped"] == 1


def test_label_api_item_mismatch_dropped():
    """라벨 항목(get_label_section, `is_label`)도 원문 인용 대상이다(H28 'API 원문')."""
    items = label_items()
    eid = items[0]["evidence_id"]
    r, reasons = run("허가사항 원문에 “성인은 증상에 따라 적절히 증감한다”라고 나와요.", [eid], items=items)
    assert reasons == [QUOTE_MISMATCH]


# ---------------------------------------------------------------------------------------- 음성: 정상 문장은 통과(오탐 0)
NEGATIVE = [
    ("정확 인용(굽은 큰따옴표)", "허가사항 원문에 “임부에게는 치료상의 유익성이 위험성을 상회한다고 판단되는 경우에만 투여한다”라고 나와요.", [C1], "fact"),
    ("정확 인용(곧은 큰따옴표)", "원문은 \"졸음이 올 수 있으므로 운전이나 기계 조작을 피한다\"예요.", [C2], "fact"),
    ("마침표까지 정확 인용", "원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다.”예요.", [C2], "fact"),
    ("공백이 더 많음", "원문은 “졸음이  올 수   있으므로 운전이나 기계 조작을 피한다”예요.", [C2], "fact"),
    ("띄어쓰기 빠짐", "원문은 “졸음이 올수 있으므로 운전이나 기계조작을 피한다”예요.", [C2], "fact"),
    ("원문 줄바꿈을 공백으로 인용", "원문은 “신중히 투여한다. 임부에게는 치료상의 유익성이”로 이어져요.", [C1], "fact"),
    ("인용부호 안 앞뒤 공백", "원문은 “ 위장 장애가 있는 환자에게 신중히 투여한다 ”예요.", [C1], "fact"),
    ("탭 문자 섞임", "원문은 “위장 장애가\t있는 환자에게”로 시작해요.", [C1], "fact"),
    ("생략 부호 … 정상 순서", "원문은 “임부에게는 치료상의…경우에만 투여한다”예요.", [C1], "fact"),
    ("낫표 정확 인용", "원문은 「위장 장애가 있는 환자에게 신중히 투여한다」예요.", [C1], "fact"),
    ("겹낫표 정확 인용", "원문은 『이 약에 과민증이 있는 환자』예요.", [C_EASY_MISS], "fact"),
    ("두 청크를 각각 정확 인용", "원문에 “신중히 투여한다”와 “운전이나 기계 조작을 피한다”가 있어요.", [C1, C2], "fact"),
    ("두 근거 연결, 둘째 청크만 인용", "원문에 “운전이나 기계 조작을 피한다”라고 나와요.", [C1, C2], "fact"),
    ("쉬운 설명 없는 품목의 허가 상세 원문 정확 인용", "허가사항 원문에 “다음 환자에는 투여하지 말 것”이라고 나와요.", [C_EASY_MISS], "fact"),
    ("짧은 강조 인용(6자 미만)은 보지 않음", "이 약은 “신중 투여” 항목에 들어 있어요.", [C1], "fact"),
    ("약 이름 짧은 따옴표", "“합성정” 허가사항에 주의 문장이 있어요.", [C1], "fact"),
    ("작은따옴표 강조는 보지 않음", "이 약은 '임신 중 주의가 필요한 약'으로 분류돼 있어요.", [C1], "fact"),
    ("인용 없는 평서문", "이 약은 위장 장애가 있는 분에게 주의가 필요하다고 나와 있어요.", [C1], "fact"),
    ("결론 문장 정확 인용", "임신 중이라면 “치료상의 유익성이 위험성을 상회한다고 판단되는 경우에만”이라는 조건을 약사와 확인하세요.", [C1], "conclusion"),
    ("근거 없는 확인 안내 속 따옴표(원문 대상 아님)", "약사에게 “지금 먹고 있는 약이 있어요”라고 알려 주세요.", [], "guidance"),
    ("파일 근거만 연결, 원문 인용 대상 아님", "목록 설명에 “태아 독성 우려가 보고되어 있음”이라고 되어 있어요.", [PREG], "fact"),
    ("파일 근거만 연결, 따옴표 안이 근거에 없어도 이 검사 대상 아님", "약사에게 “임신 중인데 같이 써도 될까요”라고 물어보세요.", [PREG], "guidance"),
    ("빈 따옴표", "원문 인용은 “ ” 없이 근거 상세에서 보여 드려요.", [C1], "fact"),
    ("파일 근거 행 ID + 청크, 청크 정확 인용", "원문에 “위장 장애가 있는 환자에게”라고 나와요.", [C1, PREG + "#a"], "fact"),
]


@pytest.mark.parametrize(("why", "text", "ids", "ct"), NEGATIVE, ids=[n[0] for n in NEGATIVE])
def test_negative_normal_sentences_pass(why, text, ids, ct):
    r, reasons = run(text, ids, ct)
    assert reasons == [] and r.status == PASS, (why, reasons)


def test_negative_count_at_least_20():
    assert len(NEGATIVE) >= 20 and len(POSITIVE) >= 10


def test_quote_with_resolved_citation_passes():
    """인용 지정 `{start, end}`로 코드가 자른 글자와 같은 인용은 통과."""
    start = T1.index("임부에게는")
    end = start + len("임부에게는 치료상의 유익성이")
    r, reasons = run("원문은 “임부에게는 치료상의 유익성이”로 시작해요.", [C1], cites=[Citation(evidence_id=C1, start=start, end=end)])
    assert reasons == [] and r.status == PASS


def test_label_api_item_exact_quote_passes():
    """라벨 항목 원문 정확 인용(근거 상세 쪽 문장, 공백만 다름)은 통과."""
    items = label_items()
    eid = items[0]["evidence_id"]
    r, reasons = run("허가사항 원문(용법용량): “성인 1회 1~2정씩  1일 3회 복용한다.”", [eid], items=items)
    assert QUOTE_MISMATCH not in reasons


# ---------------------------------------------------------------------------------------- 혼합 답변·이벤트
def test_mixed_answer_fixed_and_event_has_no_text():
    sents = [S("원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”예요.", [C2]),
             S("원문은 “졸음이 오지 않으므로 운전해도 된다”예요.", [C2]),
             S("이 약은 위장 장애가 있는 분에게 주의가 필요하다고 나와 있어요.", [C1])]
    r = validate(AnswerDraft(sentences=sents), ITEMS)
    assert r.status == FIXED and len(r.kept) == 2
    assert [(i.index, i.check) for i in r.issues] == [(1, QUOTE_MISMATCH)]
    ev = r.events[0]
    assert ev["rule"] == "H2" and ev["reasons"] == {QUOTE_MISMATCH: 1}
    assert "졸음" not in repr(r.events)   # 이벤트에 문장 원문을 넣지 않는다


# ---------------------------------------------------------------------------------------- ② 근거 ID 연결 검사가 인용 경로에서도 막는다
def test_filter_unknown_evidence_with_quote():
    d = AnswerDraft(sentences=[S("원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”예요.", ["chunk:l3:nowhere#p9"],
                                 cites=[Citation(evidence_id="chunk:l3:nowhere#p9", start=0, end=5)])])
    f = filter_sentences(d, ITEMS)
    assert [x.reason for x in f.dropped] == [UNKNOWN_EVIDENCE] and f.kept == []


def test_filter_no_evidence_with_quote_and_citation():
    """근거 ID 없이 인용 지정만 있는 사실 문장도 NO_EVIDENCE로 걸린다(인용 지정은 근거 ID를 대신하지 않는다)."""
    d = AnswerDraft(sentences=[S("원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”예요.", [],
                                 cites=[Citation(evidence_id=C2, start=0, end=5)])])
    f = filter_sentences(d, ITEMS)
    assert [x.reason for x in f.dropped] == [NO_EVIDENCE]


def test_filter_mixed_known_unknown_ids_with_quote():
    d = AnswerDraft(sentences=[S("원문에 “신중히 투여한다”가 있어요.", [C1, "chunk:fake#1"])])
    f = filter_sentences(d, ITEMS)
    assert [x.reason for x in f.dropped] == [UNKNOWN_EVIDENCE]


def test_filter_citation_not_linked_counted_as_bad_quote():
    """문장의 근거 ID에 없는 근거로 인용 지정하면 문장은 남고 bad_quotes로 센다(기존 동작 유지)."""
    d = AnswerDraft(sentences=[S("이 약은 주의가 필요하다고 나와 있어요.", [C1], cites=[Citation(evidence_id=C2, start=0, end=5)])])
    f = filter_sentences(d, ITEMS)
    assert f.dropped == [] and f.bad_quotes == 1 and f.events[0]["bad_quotes"] == 1


def test_pipeline_filter_then_validator_like_graph():
    """그래프(nodes.py)와 같은 순서: 필터 → validate(fr.kept). 근거 ID 오류는 H1, 인용 불일치는 H2에 남는다."""
    sents = [S("원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”예요.", [C2]),
             S("원문은 “졸음이 올 수 있으므로 운전이나 기계 조작을 피한다”예요.", ["chunk:fake#1"]),
             S("원문은 “운전이나 기계 조작은 해도 된다”예요.", [C2]),
             S("원문은 “운전이나 기계 조작을 피한다”예요.", [], "fact")]
    f = filter_sentences(AnswerDraft(sentences=sents), ITEMS)
    assert f.events[0]["reasons"] == {UNKNOWN_EVIDENCE: 1, NO_EVIDENCE: 1}
    v = validate(f.kept, ITEMS)
    assert v.events[0]["reasons"] == {QUOTE_MISMATCH: 1} and len(v.kept) == 1
