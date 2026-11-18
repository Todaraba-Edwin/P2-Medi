"""BE-06 `Finding.reasons`(FE-02-06 A, 2026-11-18) 시험: 결과 카드 병용금기 줄의 사유 원문 칸. 형식만, 외부 호출 0.

- 금기 발견(`bucket == "found"`) 쌍 금기(`kind in PAIR_KINDS`) 줄에만, 줄·배지 근거의 `detail[].rows[].reason` 원문 그대로(자르지 않음),
  근거·행 순서 유지·같은 글자 중복 제거. 연령·임부·목록에 없음·미식별 줄은 빈 목록.
- 용량 숫자가 든 사유는 카드 칸에서 빼고 근거 상세(`detail[].rows`)에는 원문 그대로 남는다(RFP-21-03).
- 하위 호환: 칸 추가, 기본 빈 목록, `chat_response@v1` 유지.
근거 항목은 합성이다(사유 문구는 공개 병용금기 파일의 사유 모양을 흉내 낸 것, 평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.answer_schema import Sentence
from app.agent.finalize import finalize
from app.agent.sentence_filter import DOSE_NUMBER, unsafe_reason
from app.api.schemas import SCHEMA_VERSION, ChatResponse, Finding, _has_dose_number, to_chat_response

KDB = "한국의약품안전관리원"
EID = "contra_pair:254000ATB:625201ATB"
API_EID = "dur_ingr:usjnt:D000200"
DRUGS = ["타이레놀콜드-에스정", "이지렉트정"]
R1 = "경련, 반사항진, 이상고열, 혼수 등"
R2 = "QT간격 연장 등 심부정맥 위험 증가"
# 실제 병용금기 파일에 있는 모양의 긴 사유(쉼표·괄호·영문 포함). 자르지 않는지 본다
LONG = ("해당 약물 병용 시 gimeracil에 의해 fluoropyrimidine 계열 약물의 대사가 감소하여 항암제의 독성이 증가, "
        "gimeracil/oteracil/tegafur 투여 중 및 종료 후 칠일 간 해당 성분 투여 금기")
DOSE = "Sildenafil 혈중농도 증가, 병용투여 할 경우에는 Sildenafil의 투여용량이 25mg을 초과하지 않도록 하며, 48시간 내 재투여 금지"


def contra_file(reasons: list[str | None], eid: str = EID) -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["254000ATB", "625201ATB"], "evidence_id": eid,
            "source": KDB, "as_of": "2026-07-31", "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": DRUGS,
            "matches": [{"row_key": f"rk{i}", "row_evidence_id": f"{eid}#{i}", "notice_no": "20250046", "notice_date": "2025-07-14",
                         **({"reason": r} if r is not None else {})} for i, r in enumerate(reasons)]}


def contra_api(content: str = R1) -> dict:
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["타이레놀콜드-에스정"], "evidence_id": API_EID,
            "source": "식약처 DUR 성분정보", "as_of": None, "queried_at_utc": "2026-11-09T01:00:00Z", "flags": [], "dataset_key": "dur_ingr",
            "source_kind": "API_DIRECT", "drugs": DRUGS,
            "matches": [{"row_key": "a0", "row_evidence_id": f"{API_EID}#0", "content": content, "notice_date": "2017-11-06"}]}


def contra_not_listed() -> dict:
    return {"kind": "contra_pair", "status": "NOT_LISTED", "subject": ["254000ATB", "625201ATB"], "evidence_id": "contra_pair:none",
            "source": KDB, "as_of": "2026-07-31", "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": DRUGS,
            "matches": []}


def preg_file() -> dict:
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["448001ATB"], "evidence_id": "pregnancy:448001ATB", "source": KDB,
            "as_of": "2026-07-21", "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": [DRUGS[0]],
            "matches": [{"row_key": "p0", "row_evidence_id": "pregnancy:448001ATB#0", "grade": "2", "reason": "태아 독성 우려",
                         "notice_no": "20200061", "notice_date": "2020-06-30"}]}


def age_file() -> dict:
    return {"kind": "age", "status": "FOUND", "subject": ["448001ATB"], "evidence_id": "age:448001ATB", "source": KDB,
            "as_of": "2026-07-21", "flags": [], "dataset_key": "age", "source_kind": "FILE", "drugs": [DRUGS[0]],
            "matches": [{"row_key": "g0", "row_evidence_id": "age:448001ATB#0", "reason": "12세 미만 소아에서 안전성 및 유효성 미확립",
                         "notice_no": "20200061", "notice_date": "2020-06-30"}]}


SENTS = [Sentence(text="두 약은 함께 먹으면 안 되는 조합으로 올라 있어요.", evidence_ids=[EID], claim_type="fact")]


def _resp(items: list[dict]) -> ChatResponse:
    return to_chat_response(finalize(items, model_summary=SENTS[0].text, sentences=SENTS), end_reason="NORMAL")


def _pair(r: ChatResponse, eid: str = EID) -> Finding:
    return next(f for f in r.findings if f.evidence_id == eid)


def _detail_reasons(r: ChatResponse, eid: str = EID) -> list[str]:
    return [row["reason"] for d in r.detail if d.evidence_id == eid for row in d.rows if "reason" in row]


# --------------------------------------------------------------------------- 채우는 조건·원문 보존
def test_found_pair_line_carries_reason_verbatim():
    r = _resp([contra_file([R1])])
    f = _pair(r)
    assert f.target == "pair" and f.bucket == "found" and f.reasons == [R1]


def test_long_reason_is_not_truncated():
    f = _pair(_resp([contra_file([LONG])]))
    assert f.reasons == [LONG] and len(f.reasons[0]) == len(LONG)


def test_no_reason_rows_give_empty_list():
    for reasons in ([], [None], [""], ["   "]):
        assert _pair(_resp([contra_file(reasons)])).reasons == [], reasons


def test_duplicate_reasons_appear_once_in_row_order():
    f = _pair(_resp([contra_file([R2, R1, R2, R1])]))
    assert f.reasons == [R2, R1]


def test_whitespace_variant_is_kept_as_its_own_original_text():
    # 원문을 다듬지 않는다: 글자가 다르면(뒤 공백) 다른 원문이다
    f = _pair(_resp([contra_file([R1, R1 + " "])]))
    assert f.reasons == [R1, R1 + " "]


def test_multiple_badges_and_evidence_collect_each_reason_in_order():
    # 같은 두 약의 쌍 근거가 둘(파일 두 근거)이면 줄이 각각이고, 각 줄은 자기 근거·배지의 사유만 갖는다
    other = "contra_pair:254000ATB:999999ATB"
    r = _resp([contra_file([R1]), contra_file([R2, R1], eid=other)])
    assert _pair(r).reasons == [R1] and _pair(r, other).reasons == [R2, R1]


def test_badge_evidence_rows_are_collected_too():
    # 배지 근거가 줄 근거와 다를 때(파일·API처럼) 배지 근거의 rows도 본다. 변환 함수에 직접 넣어 확인한다
    from app.api import schemas as S

    alt = "contra_pair:alt"
    fin = finalize([contra_file([R1]), contra_file([R2, R1], eid=alt)], model_summary="x")
    by_id = {d.evidence_id: d for d in (S._detail_item(x) for x in fin["detail"]) if d.evidence_id}
    entry = next(e for e in fin["entries"] if e["evidence_id"] == EID)
    badges = [S.Badge(kind="contra_pair", text="t", evidence_id=EID), S.Badge(kind="contra_pair", text="t", evidence_id=alt),
              S.Badge(kind="contra_pair", text="t", evidence_id=alt)]
    f = S._finding(entry, by_id, {EID: badges})
    assert f.reasons == [R1, R2]  # 줄 근거 먼저, 그다음 배지 근거(같은 근거 ID·같은 글자는 한 번)


def test_api_row_content_is_not_read_as_reason():
    # 브리프 범위: `rows[].reason`만 옮긴다. API 행의 `content`(PROHBT_CONTENT)는 근거 상세에만 남는다(보고의 확인 필요 항목)
    r = _resp([contra_file([R1]), contra_api(R2)])
    assert _pair(r).reasons == [R1] and _pair(r, API_EID).reasons == []
    assert any(row.get("content") == R2 for d in r.detail if d.evidence_id == API_EID for row in d.rows)


# --------------------------------------------------------------------------- 연령·임부·목록에 없음 줄은 빈 목록
def test_age_and_pregnancy_lines_have_no_reasons_even_with_row_reason():
    r = _resp([contra_file([R1]), preg_file(), age_file()])
    assert _pair(r).reasons == [R1]
    # 임부·연령 판정은 제품 줄의 배지로 나온다(BE-06-12 A 연결, 2026-11-18). 제품 줄은 사유 칸이 비어 있다
    (prod,) = [f for f in r.findings if f.target == "product" and f.drugs == [DRUGS[0]]]
    assert [b.kind for b in prod.badges] == ["contra_pair", "pregnancy", "age"]
    assert all(f.reasons == [] for f in r.findings if f.target == "product")
    assert _detail_reasons(r, "age:448001ATB") == ["12세 미만 소아에서 안전성 및 유효성 미확립"]  # 근거 상세는 그대로


def test_not_listed_pair_line_has_no_reasons():
    r = _resp([contra_not_listed()])
    assert [f.bucket for f in r.findings] == ["not_listed"] and r.findings[0].reasons == []


# --------------------------------------------------------------------------- 용량 숫자(RFP-21-03)
def test_dose_number_reason_is_dropped_from_card_but_kept_in_detail():
    r = _resp([contra_file([DOSE, R1])])
    assert _pair(r).reasons == [R1]
    assert _detail_reasons(r) == [DOSE, R1]  # 근거 상세 원문은 그대로


@pytest.mark.parametrize("text", [
    "Tadalafil 혈중농도 증가, 병용투여 할 경우에는 Tadalafil의 투여용량이 10mg을 초과하지 않도록 하며, 72시간 내 재투여 금지",
    "고용량의 Ritonavir(>200mg, 1일 2회)와 병용투여 금기",
    "1일 3회 복용 시 독성 증가",
])
def test_dose_patterns_are_caught(text):
    assert _has_dose_number(text)


@pytest.mark.parametrize("text", [
    R1, R2, LONG,
    "12세 미만 소아에서 안전성 및 유효성 미확립",
    "안전성 및 유효성이 확립되지 않음",
    "횡문근융해증",
    "간 독성",
    "72시간 내 재투여 금지",
    "CYP3A4 저해로 혈중농도 상승",
])
def test_ordinary_reasons_are_not_dose_numbers(text):
    assert not _has_dose_number(text)


def test_decision_like_original_text_is_not_dropped_only_dose_counts():
    # 요약 문장용 결정 패턴은 원문 사유에 쓰지 않는다: unsafe_reason()은 이 원문을 결정 문장으로 보지만 카드에서는 빼지 않는다
    text = "중증 저혈압 위험이 있으므로 병용투여하지 마십시오"
    assert unsafe_reason(text) not in (None, DOSE_NUMBER)
    assert not _has_dose_number(text)
    assert _pair(_resp([contra_file([text])])).reasons == [text]


# --------------------------------------------------------------------------- 스키마 불변식·하위 호환
def _base() -> dict:
    return {"bucket": "found", "evidence_id": EID, "kind": "contra_pair", "drug": "a · b", "target": "pair", "drugs": DRUGS, "text": "t"}


def test_model_rejects_reasons_on_wrong_lines_or_with_dose_numbers():
    assert Finding(**_base(), reasons=[R1]).reasons == [R1]
    for bad in ({"kind": "pregnancy", "target": "product", "drugs": [DRUGS[0]]}, {"bucket": "not_listed"}):
        with pytest.raises(ValidationError):
            Finding(**{**_base(), **bad}, reasons=[R1])
    for bad_reason in ("", "  ", DOSE):
        with pytest.raises(ValidationError):
            Finding(**_base(), reasons=[bad_reason])


def test_backward_compatible_default_and_schema_version():
    assert Finding(**_base()).reasons == []
    r = _resp([contra_file([R1])])
    dumped = r.model_dump(mode="json")
    assert dumped["schema_version"] == SCHEMA_VERSION == "chat_response@v1"
    old = {**dumped, "findings": [{k: v for k, v in f.items() if k != "reasons"} for f in dumped["findings"]]}
    again = ChatResponse.model_validate(old)  # `reasons` 없는 예전 응답도 그대로 읽힌다
    assert all(f.reasons == [] for f in again.findings)
    assert _pair(ChatResponse.model_validate_json(r.model_dump_json())).reasons == [R1]  # 왕복(쌍 줄, 제품 줄이 앞에 온다)


def test_openapi_finding_has_optional_reasons_list():
    props = ChatResponse.model_json_schema()["$defs"]["Finding"]
    assert props["properties"]["reasons"]["type"] == "array" and props["properties"]["reasons"]["items"]["type"] == "string"
    assert "reasons" not in props.get("required", [])


# --------------------------------------------------------------------------- /chat 라우트(가짜 자원 서버): 새 칸이 계약을 깨지 않는다
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))


@pytest.fixture(scope="module")
def fake_client() -> TestClient:
    import dev_fake_server as dfs

    return TestClient(dfs.create_app(slow_seconds=0.0, metrics=None))


@pytest.mark.parametrize("name", ["normal_found", "not_found", "emergency"])
def test_chat_route_answer_validates_with_reasons_field(fake_client, name):
    import dev_fake_server as dfs

    from app.api import events as ev

    res = fake_client.post("/chat", json={"question": dfs.SCENARIOS[name]})
    assert res.status_code == 200
    events = [ev.ChatEvent.model_validate_json(x) for x in res.content.split(b"\n") if x]
    ev.check_event_order(events, complete=True)
    answer = next(e.root.response for e in events if e.root.type == "answer")
    for f in answer.findings:
        assert isinstance(f.reasons, list)
        if f.reasons:
            assert f.bucket == "found" and f.kind == "contra_pair" and f.target == "pair"
    if name == "not_found":
        assert all(f.reasons == [] for f in answer.findings)
    raw = next(x for x in res.content.split(b"\n") if b'"answer"' in x)
    assert b'"reasons"' in raw  # 직렬화된 응답에 칸이 실제로 나간다
