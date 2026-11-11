"""BE-06 응답 스키마 골격 시험(형식만, 외부 호출 0). 근거 항목은 합성(RFP-21 §4.6 표의 공개 예시 모양)이다.

- 출처 표(`citations[]`)가 PRD-12 §5(한 날짜 = 한 줄, 라벨 상수)·§4.5(순서)·§6(데이터 계약)과 AG-08-03 B(자료별 기준일)를 표현하는지
- 필수 칸(고정 문구·고지·응급)·금지 칸(내부 필드, 서비스 이름 기관, 잘못된 날짜 형식)
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agent import fixed_phrases as fp
from app.agent.answer_schema import Sentence
from app.agent.finalize import finalize
from app.api.schemas import (
    DATE_LABEL_AS_OF,
    DATE_LABEL_NONE,
    DATE_LABEL_NOTICE,
    DATE_LABEL_QUERIED,
    DATE_LINE_LABELS,
    ChatResponse,
    Citation,
    DateLine,
    queried_date_kst,
    to_chat_response,
)

KDB, MFDS = "한국의약품안전관리원", "식약처"


def contra_file(as_of: str = "2026-07-31", notices: tuple[str, ...] = ("2025-07-14",)) -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["254000ATB", "625201ATB"], "evidence_id": "contra_pair:254000ATB:625201ATB",
            "source": KDB, "as_of": as_of, "flags": ["API_SAME"], "dataset_key": "contra_pair", "source_kind": "FILE",
            "drugs": ["타이레놀콜드-에스정", "이지렉트정"],
            "matches": [{"row_key": f"rk{i}", "row_evidence_id": f"contra_pair:254000ATB:625201ATB#{i}", "reason": "경련, 반사항진, 이상고열, 혼수 등",
                         "notice_no": "20250046", "notice_date": d} for i, d in enumerate(notices)]}


def contra_api(queried: str = "2026-11-09T01:00:00Z") -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["타이레놀콜드-에스정"], "evidence_id": "dur_ingr:usjnt:D000200",
            "source": "식약처 DUR 성분정보", "as_of": None, "queried_at_utc": queried, "flags": ["API_SAME"], "dataset_key": "dur_ingr",
            "source_kind": "API_DIRECT", "drugs": ["타이레놀콜드-에스정", "이지렉트정"],
            "matches": [{"row_key": "a0", "row_evidence_id": "dur_ingr:usjnt:D000200#0", "content": "경련, 반사항진, 이상고열, 혼수 등",
                         "notice_date": "2017-11-06"}]}


def preg_file() -> dict:
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["448001ATB"], "evidence_id": "pregnancy:448001ATB", "source": KDB,
            "as_of": "2026-07-21", "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["타이레놀콜드-에스정"],
            "matches": [{"row_key": "p0", "row_evidence_id": "pregnancy:448001ATB#0", "grade": "2", "notice_no": "20200061", "notice_date": "2020-06-30"}]}


def eyak_quote() -> dict:
    return {"kind": "label", "status": "FOUND", "subject": ["202106954"], "evidence_id": "eyak:202106954:intrc", "source": "식약처 e약은요",
            "as_of": None, "queried_at_utc": "2026-11-09T02:00:00Z", "flags": [], "dataset_key": "eyak", "source_kind": "CORPUS_QUOTE",
            "label_source": "e약은요", "item_seq": "202106954", "section": "상호작용", "is_label": True, "name": "타이레놀콜드-에스정",
            "matches": [{"row_key": "e0", "row_evidence_id": "eyak:202106954:intrc#0", "text": "MAO 억제제와 함께 복용하지 마십시오."}]}


def unid() -> dict:
    return {"kind": "identify", "status": "UNIDENTIFIED", "subject": ["쿵쿵정"], "evidence_id": "identify:쿵쿵정", "source": None, "as_of": None,
            "flags": [], "matches": [], "dataset_key": None, "source_kind": None, "input_name": "쿵쿵정", "searched": [{"dataset": "허가정보", "count": 0}],
            "retried": False}


SENTS = [Sentence(text="두 약은 함께 먹으면 안 되는 조합으로 올라 있어요.", evidence_ids=["contra_pair:254000ATB:625201ATB"], claim_type="fact")]


def _resp(items: list[dict], **kw) -> ChatResponse:
    return to_chat_response(finalize(items, model_summary=" ".join(s.text for s in SENTS), sentences=SENTS, **kw), end_reason="NORMAL")


# --------------------------------------------------------------------------- 출처 표: PRD-12 날짜 줄·순서
def test_p3_source_table_rows_dates_and_order():
    r = _resp([contra_file(), contra_api(), eyak_quote()])
    rows = [(c.publisher, c.dataset, [(d.label, d.value) for d in c.dates]) for c in r.citations]
    assert rows == [
        (MFDS, "DUR 성분정보 API", [("고시일", "2017-11-06"), ("조회", "2026-11-09")]),   # 판정 자료(API) 먼저
        (MFDS, "e약은요 쉬운 설명", [("조회", "2026-11-09")]),                           # 같은 기관 안: 허가사항 근거 자료는 뒤
        (KDB, "병용금기 파일", [("고시일", "2025-07-14"), ("기준일", "2026-07-31")]),     # 파일과 API는 각각 행(PRD-09 G8)
    ]
    assert r.citations[0].source_kind == "API_DIRECT" and r.citations[2].source_kind == "FILE"
    assert r.citations[2].evidence_ids == ["contra_pair:254000ATB:625201ATB"]


def test_one_date_per_line_and_labels_are_constants():
    r = _resp([contra_file(notices=("2025-07-14", "2020-12-28", "2025-07-14")), contra_api(), preg_file(), eyak_quote()])
    for c in r.citations:
        for d in c.dates:
            assert d.label in DATE_LINE_LABELS
            assert d.value is None or (len(d.value) == 10 and "·" not in d.value and " " not in d.value)  # 한 항목 = 날짜 하나
    kids = next(c for c in r.citations if c.dataset == "병용금기 파일")
    assert [(d.label, d.value) for d in kids.dates] == [("고시일", "2020-12-28"), ("고시일", "2025-07-14"), ("기준일", "2026-07-31")]  # 고시일 여럿은 줄마다, 중복 제거
    js = json.loads(r.model_dump_json())
    assert js["citations"][0]["dates"] == [{"label": "고시일", "value": "2017-11-06"}, {"label": "조회", "value": "2026-11-09"}]


def test_each_dataset_keeps_its_own_as_of_ag08_03_b():
    """병용 2026-07-31·임부 2026-07-21: 어느 한쪽 날짜로 합치지 않고 자료마다 기준일을 따로 보인다(AG-08-03 B)."""
    r = _resp([contra_file(), preg_file()])
    as_of = {c.dataset: [d.value for d in c.dates if d.label == DATE_LABEL_AS_OF] for c in r.citations}
    assert as_of == {"병용금기 파일": ["2026-07-31"], "임부금기 파일": ["2026-07-21"]}
    assert all(c.publisher == KDB for c in r.citations)
    assert [c.dataset for c in r.citations] == ["병용금기 파일", "임부금기 파일"]


def test_detail_items_carry_dates_dataset_and_no_llm_text():
    r = _resp([contra_file(), contra_api(), eyak_quote(), unid()])
    by_id = {d.evidence_id: d for d in r.detail}
    f = by_id["contra_pair:254000ATB:625201ATB"]
    assert (f.publisher, f.dataset, f.source_kind) == (KDB, "병용금기 파일", "FILE")
    assert [(x.label, x.value) for x in f.dates] == [(DATE_LABEL_NOTICE, "2025-07-14"), (DATE_LABEL_AS_OF, "2026-07-31")]
    a = by_id["dur_ingr:usjnt:D000200"]
    assert [(x.label, x.value) for x in a.dates] == [(DATE_LABEL_NOTICE, "2017-11-06"), (DATE_LABEL_QUERIED, "2026-11-09")]
    u = by_id["identify:쿵쿵정"]
    assert u.source_kind is None and [(x.label, x.value) for x in u.dates] == [(DATE_LABEL_NONE, None)]
    assert SENTS[0].text not in json.dumps([d.model_dump() for d in r.detail], ensure_ascii=False)  # detail에는 LLM 문장 없음
    assert r.summary == SENTS[0].text
    assert all(c.publisher for c in r.citations) and "identify:쿵쿵정" not in [e for c in r.citations for e in c.evidence_ids]  # 출처 없는 근거는 출처 표에 없음


def test_sentence_refs_link_summary_to_evidence():
    r = _resp([contra_file(), contra_api()])
    assert [(s.evidence_id, s.sentence_index) for s in r.sentence_refs] == [("contra_pair:254000ATB:625201ATB", 0)]


def test_queried_date_is_kst_calendar_date():
    assert queried_date_kst("2026-11-09T16:30:00Z") == "2026-11-10"  # UTC 16:30 = KST 다음날 01:30
    assert queried_date_kst("2026-11-09T01:00:00+00:00") == "2026-11-09"
    assert queried_date_kst("unknown") is None and queried_date_kst(None) is None and queried_date_kst("어제") is None


# --------------------------------------------------------------------------- 필수 칸
def test_required_fixed_texts_always_present_and_pharmacist_line_when_unresolved():
    r = _resp([contra_file(), unid()])
    assert r.fixed_notice[-1] == fp.FIXED_NOTICE and r.disclaimer == fp.DISCLAIMER
    assert r.fixed_notice[0] == fp.PHARMACIST_ADVICE_FIXED  # 미확보가 있으면 약사 확인 권고가 fixed_notice에 한 줄(BE-06 PRD-11-03)
    r2 = _resp([contra_file()])
    assert r2.fixed_notice == [fp.FIXED_NOTICE]


def test_emergency_refuse_and_limit_shapes():
    e = to_chat_response(finalize([contra_file()], model_summary="x", emergency=True), end_reason="NORMAL")
    assert e.emergency is not None and e.emergency.text == fp.EMERGENCY_119 and e.emergency.tel == fp.EMERGENCY_119_TEL
    ref = to_chat_response(finalize([], refuse_reason="PRESCRIPTION"), end_reason="REFUSE")
    assert ref.route == "REFUSE" and ref.summary == fp.REFUSE_MESSAGES["PRESCRIPTION"] and ref.citations == [] and ref.fixed_notice
    lim = to_chat_response(finalize([contra_file()], limit_reached=True), end_reason="LIMIT")
    assert lim.summary is None and lim.notice == fp.LIMIT_REACHED and lim.findings[0].bucket == "found" and lim.citations


def test_findings_and_badges_follow_finalize_order():
    r = _resp([preg_file(), contra_file(), unid()])
    assert [f.bucket for f in r.findings][:2] == ["found", "found"] and r.findings[-1].bucket == "unconfirmed"
    assert r.findings[-1].input_name == "쿵쿵정" and r.findings[-1].searched == [{"dataset": "허가정보", "count": 0}]
    assert [b.kind for b in r.badges] == ["contra_pair", "pregnancy"]


# --------------------------------------------------------------------------- 금지 칸·형식
def test_internal_fields_not_in_response():
    raw = finalize([contra_file()], model_summary="요약", sentences=SENTS)
    assert {"events", "warnings", "text"} <= set(raw)
    dumped = to_chat_response(raw).model_dump()
    assert not {"events", "warnings", "text", "emergency_tel", "pharmacist_advice_fixed", "LLM_SUMMARY"} & set(dumped)
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**dumped, "text": "x"})  # 모르는 칸 거부(extra=forbid)


def test_publisher_must_be_official_and_dates_well_formed():
    ok = DateLine(label="기준일", value="2026-07-21")
    with pytest.raises(ValidationError):
        Citation(publisher="삐약", dataset="병용금기 파일", dates=[ok])
    with pytest.raises(ValidationError):
        Citation(publisher=KDB, dataset="병용금기 파일", dates=[])  # 날짜 줄 최소 1(없으면 '날짜 없음')
    for bad in [("기준일", "2026.07.21"), ("기준일", "고시일 2025-07-14 · 기준일 2026-07-21"), ("기준일", None), ("날짜 없음", "2026-07-21"), ("최신", "2026-07-21")]:
        with pytest.raises(ValidationError):
            DateLine(label=bad[0], value=bad[1])  # type: ignore[arg-type]


def test_fixed_notice_and_disclaimer_cannot_be_empty():
    base = to_chat_response(finalize([contra_file()], model_summary="요약")).model_dump()
    for patch in ({"fixed_notice": []}, {"fixed_notice": [" "]}, {"disclaimer": ""}):
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({**base, **patch})


def test_corpus_item_without_dataset_key_uses_official_source_or_is_left_out():
    notice = {"kind": "notice", "status": "FOUND", "subject": ["x"], "evidence_id": "L1:notice:3", "source": "식약처 고시", "as_of": "2026-06-21",
              "flags": [], "dataset_key": None, "source_kind": "CORPUS_QUOTE", "matches": []}
    odd = {**notice, "evidence_id": "L1:odd", "source": "삐약 내부 메모"}
    r = _resp([contra_file(), notice, odd])
    names = [(c.publisher, c.dataset) for c in r.citations]
    assert (MFDS, "식약처 고시") in names and all(p != "삐약 내부 메모" for p, _ in names)
