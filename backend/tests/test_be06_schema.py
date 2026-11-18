"""BE-06 응답 스키마 시험(`chat_response@v1`, 형식만, 외부 호출 0). 근거 항목은 합성(RFP-21 §4.6 표의 공개 예시 모양)이다.

v0 골격 시험(아래 앞부분)은 v1에서도 그대로 통과해야 한다(불변식 약화 금지). v1 추가분은 파일 끝 "v1" 절에 있다.

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
    assert r.findings[-1].input_name == "쿵쿵정" and [s.model_dump() for s in r.findings[-1].searched] == [{"dataset": "허가정보", "count": 0}]
    # v1: 배지는 판정 줄에 붙는다(최상위 `badges` 없음). 제품 줄(약마다, 병용 → 임부) → 쌍 줄 순서(BE-06-12 A 연결, 2026-11-18)
    assert [(f.target, f.drugs, [b.kind for b in f.badges]) for f in r.findings if f.badges] == [
        ("product", [A_DRUG], ["contra_pair", "pregnancy"]), ("product", [B_DRUG], ["contra_pair"]),
        ("pair", [A_DRUG, B_DRUG], ["contra_pair"])]
    assert "badges" not in ChatResponse.model_fields


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


# =========================================================================== v1(`chat_response@v1`, BE-06-01~08·FE-07-18)
from app.api.schemas import (  # noqa: E402
    DATE_LABEL_PUBLISHED,
    NOTICE_TEXTS,
    SCHEMA_VERSION,
    Badge,
    DetailItem,
    Emergency,
    Finding,
    response_from_state,
)
from app.tools.provenance import CITATION_DATE_LABELS  # noqa: E402

A_DRUG, B_DRUG = "타이레놀콜드-에스정", "이지렉트정"


def test_v1_schema_version():
    assert SCHEMA_VERSION == "chat_response@v1" and _resp([contra_file()]).schema_version == "chat_response@v1"
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**_resp([contra_file()]).model_dump(), "schema_version": "chat_response@v0"})


# --------------------------------------------------------------------------- BE-06-08 A: 월 단위 날짜·발간일 라벨
def test_be06_08_month_values_allowed_day_values_still_pass():
    assert CITATION_DATE_LABELS["published"] == "발간일" == DATE_LABEL_PUBLISHED and DATE_LABEL_PUBLISHED in DATE_LINE_LABELS
    for label in ("발간일", "기준일", "고시일"):
        assert DateLine(label=label, value="2025-11").value == "2025-11"  # 없는 날(1일)을 붙이지 않는다
        assert DateLine(label=label, value="2026-07-21").value == "2026-07-21"
    assert DateLine(label="조회", value="2026-11-09").value == "2026-11-09"


@pytest.mark.parametrize("label,value", [
    ("조회", "2026-11"),            # 조회는 하루 단위만
    ("발간일", "2025-13"), ("기준일", "2026-00"), ("기준일", "2026-6"), ("기준일", "2026-02-30"), ("고시일", "2025-11-"),
    ("발간일", "2025.11"), ("발간일", "2025년 11월"), ("발간일", None),
])
def test_be06_08_bad_date_values_rejected(label, value):
    with pytest.raises(ValidationError):
        DateLine(label=label, value=value)


def test_month_as_of_passes_through_unchanged():
    r = _resp([contra_file(as_of="2026-06")])
    kids = next(c for c in r.citations if c.dataset == "병용금기 파일")
    assert ("기준일", "2026-06") in [(d.label, d.value) for d in kids.dates]


# --------------------------------------------------------------------------- BE-06-01 A: 쌍 줄, PRD-15 배지(줄별·순서)
def test_be06_01_pair_finding_is_its_own_line():
    r = _resp([contra_file(), preg_file()])
    (pair,) = [f for f in r.findings if f.target == "pair"]
    assert pair.kind == "contra_pair" and pair.drugs == [A_DRUG, B_DRUG]
    # 임부 판정은 그 약의 제품 줄 배지다(제품 줄 하나에 병용 → 임부, BE-06-12 A 연결, 2026-11-18)
    (preg,) = [f for f in r.findings if f.target == "product" and f.drugs == [A_DRUG]]
    assert [b.kind for b in pair.badges] == ["contra_pair"] and [b.kind for b in preg.badges] == ["contra_pair", "pregnancy"]
    preg_badge = preg.badges[1]
    assert preg_badge.grade == "2" and preg_badge.source is None  # 등급이 하나면 출처 꼬리 없음
    with pytest.raises(ValidationError):
        Finding(target="pair", bucket="found", evidence_id="x", kind="contra_pair", drug=A_DRUG, drugs=[A_DRUG], text="t")


def test_badge_order_kind_then_source_is_enforced():
    def f(badges):
        return Finding(bucket="found", evidence_id="x", kind="pregnancy", drug="d", text="t", badges=badges)

    pair, preg, age = (Badge(kind=k, text="t") for k in ("contra_pair", "pregnancy", "age"))
    assert [b.kind for b in f([pair, preg, age]).badges] == ["contra_pair", "pregnancy", "age"]
    for bad in ([preg, pair], [age, preg], [Badge(kind="pregnancy", grade="1", source="API_DIRECT", text="t"),
                                            Badge(kind="pregnancy", grade="2", source="FILE", text="t")]):
        with pytest.raises(ValidationError):
            f(bad)
    with pytest.raises(ValidationError):
        Finding(bucket="not_listed", evidence_id="x", kind="pregnancy", drug="d", text="t", badges=[preg])  # 배지는 금기 발견 줄에만
    with pytest.raises(ValidationError):
        Badge(kind="pregnancy", grade="3", text="t")  # 등급은 1·2·M 또는 없음


def test_grade_mismatch_badges_carry_source_file_then_api():
    it = preg_file()
    it["matches"] = [{"row_key": "p0", "row_evidence_id": "pregnancy:448001ATB#0", "grade": "2", "source_kind": "FILE"},
                     {"row_key": "p1", "row_evidence_id": "pregnancy:448001ATB#1", "grade": "1", "source_kind": "API_DIRECT"}]
    r = _resp([it])
    badges = r.findings[0].badges
    assert [(b.grade, b.source) for b in badges] == [("2", "FILE"), ("1", "API_DIRECT")]
    assert badges[0].text.endswith(fp.BADGE_SOURCE_TAIL["FILE"]) and badges[1].text.endswith(fp.BADGE_SOURCE_TAIL["API_DIRECT"])


# --------------------------------------------------------------------------- BE-06-02 A: 응급은 필드로만
def test_be06_02_no_emergency_end_reason_and_emergency_is_constant():
    base = _resp([contra_file()]).model_dump()
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**base, "end_reason": "EMERGENCY"})
    e = to_chat_response(finalize([contra_file()], model_summary="x", emergency=True), end_reason="NORMAL")
    assert e.emergency is not None and e.end_reason == "NORMAL"  # 금기 조회와 병행
    for bad in ({"text": "다른 문구", "tel": fp.EMERGENCY_119_TEL}, {"text": fp.EMERGENCY_119, "tel": "119"}, {"text": fp.EMERGENCY_119}):
        with pytest.raises(ValidationError):
            Emergency.model_validate(bad)


# --------------------------------------------------------------------------- BE-06-03 A: 되묻기 후보는 응답의 candidates[]
CLARIFY = {"question": "q", "target_raw": "타이레놀", "pending_raws": [],
           "options": [{"name": "타이레놀정500밀리그람", "item_seq": "200000001", "entp_name": "가제약", "prescription": "일반", "matched_by": "product_name", "score": 1.0},
                       {"name": "타이레놀8시간이알서방정", "item_seq": None, "entp_name": None, "prescription": None, "matched_by": "product_name", "score": 0.9}]}


def test_be06_03_candidates_only_on_clarify():
    raw = finalize([], model_summary="'타이레놀'에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요.")
    r = to_chat_response(raw, end_reason="CLARIFY", clarify=CLARIFY)
    assert [(c.input_name, c.name, c.item_seq) for c in r.candidates] == [
        ("타이레놀", "타이레놀정500밀리그람", "200000001"), ("타이레놀", "타이레놀8시간이알서방정", None)]
    assert "score" not in r.candidates[0].model_dump()  # 내부 점수는 싣지 않는다
    assert to_chat_response(raw, end_reason="NORMAL", clarify=CLARIFY).candidates == []
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**r.model_dump(), "end_reason": "NORMAL"})
    st = response_from_state({"answer": raw, "end_reason": "CLARIFY", "clarify": CLARIFY, "question": "타이레놀 먹어도 돼?"})
    assert len(st.candidates) == 2 and "먹어도 돼" not in st.model_dump_json()


# --------------------------------------------------------------------------- BE-06-04 B·06 A·07 B: 표 구조·새 배너·시각 필드 없음
def _schema_keys(model) -> set[str]:
    js = model.model_json_schema()
    keys: set[str] = set()
    for d in [js, *js.get("$defs", {}).values()]:
        keys |= set(d.get("properties", {}))
    return keys


def test_be06_04_06_07_no_dose_table_no_banner_field_no_time_field():
    keys = _schema_keys(ChatResponse)
    assert not any("dose" in k or "table" in k for k in keys)            # BE-06-04 B: 원문 인용 텍스트만
    assert not {"banner", "api_notice", "api_failure", "alert"} & keys   # BE-06-06 A: 기존 notice만
    assert not any(k.endswith("_at") or "time" in k for k in keys)       # BE-06-07 B: 시각 필드 없음
    assert "notice" in ChatResponse.model_fields


def test_be06_06_notice_reuses_constant_only():
    lim = to_chat_response(finalize([contra_file()], limit_reached=True), end_reason="LIMIT")
    assert lim.notice == fp.LIMIT_REACHED and lim.notice in NOTICE_TEXTS
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**lim.model_dump(), "notice": "지어낸 배너"})


# --------------------------------------------------------------------------- BE-06-05 A: 출처 행의 고시 번호·판·쪽
def test_be06_05_citation_row_has_notice_no_edition_pages():
    r = _resp([contra_file(), preg_file(), contra_api()])
    rows = {c.dataset: c for c in r.citations}
    assert rows["병용금기 파일"].notice_nos == ["20250046"] and rows["임부금기 파일"].notice_nos == ["20200061"]
    assert rows["DUR 성분정보 API"].notice_nos == []  # 원문에 번호가 없으면 지어내지 않는다
    assert all(c.edition is None and c.pages == [] for c in r.citations)  # 판·쪽 원문 값은 아직 입력에 없다(AG 이행)
    ok = Citation(publisher=KDB, dataset="병용금기 파일", dates=[DateLine(label="발간일", value="2025-11")], edition="2026년판", pages=["12"])
    assert ok.edition == "2026년판"


# --------------------------------------------------------------------------- 고정 문구 불변식 강화(v1)
def test_fixed_notice_must_contain_constant_and_disclaimer_must_be_constant():
    base = _resp([contra_file()]).model_dump()
    for patch in ({"fixed_notice": ["다른 문구"]}, {"disclaimer": "다른 고지"}):
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({**base, **patch})


# --------------------------------------------------------------------------- detail: 약 이름·항목명·missing_text
def test_detail_drug_name_section_and_missing_text():
    miss = {"kind": "label", "status": "NO_EVIDENCE", "subject": ["202106954"], "evidence_id": "eyak:202106954:dose", "source": None, "as_of": None,
            "flags": [], "dataset_key": None, "source_kind": None, "drugs": ["타이레놀정500밀리그람"], "section": "사용법",
            "missing_reason": "FETCH_FAIL", "matches": []}
    r = _resp([contra_file(), miss, eyak_quote()])
    by_id = {d.evidence_id: d for d in r.detail}
    m = by_id["eyak:202106954:dose"]
    assert (m.drug_name, m.section, m.missing_reason, m.missing_text) == ("타이레놀정500밀리그람", "사용법", "FETCH_FAIL", fp.MISSING_FETCH_FAIL)
    assert by_id["contra_pair:254000ATB:625201ATB"].drug_name is None  # 쌍 근거는 drugs로
    assert by_id["eyak:202106954:intrc"].section == "상호작용"
    with pytest.raises(ValidationError):
        DetailItem(evidence_id="x", kind=None, status=None, source_kind=None, dataset_key=None, dataset=None, publisher=None,
                   dates=[DateLine(label="날짜 없음", value=None)], missing_text="문구")


# --------------------------------------------------------------------------- PRD-14 미식별, PRD-09-05 성분, FE-07-18 나이 기준
def test_unidentified_retried_flag_and_ingredients_age_fields():
    u = unid()
    u["retried"] = True
    r = _resp([contra_file(), u])
    f = r.findings[-1]
    assert f.retried is True and f.retried_line == fp.UNIDENTIFIED_RETRIED and f.input_name == "쿵쿵정"
    assert _resp([unid()]).findings[-1].retried is False
    assert r.findings[0].retried is None  # 미식별 줄이 아니면 칸 없음
    assert r.findings[0].ingredients == [] and r.findings[0].age_criteria == []  # 입력(finalize)에 값이 없어 비움(AG 이행)
    ok = Finding(bucket="found", evidence_id="age:X", kind="age", drug="d", text="t", age_criteria=["만 12세 미만"])
    assert ok.age_criteria == ["만 12세 미만"] and ok.age_info_line is None
    with pytest.raises(ValidationError):
        Finding(bucket="found", evidence_id="age:X", kind="age", drug="d", text="t", age_info_line="승인 전 문구")  # 문구 대기
