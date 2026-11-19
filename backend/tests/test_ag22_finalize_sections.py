"""AG-22·FE-11(2026-11-19): `finalize`의 구역(`sections`·제품 줄 `section`)·짝 참조(`pair_ref`)·요약(`result_summary`)·
용량주의 되묻기(`dose_check`·`dose_notice`)·재복용 고지(`redose_notice`)와 승인 문구(①~⑧). **`entries`는 그대로**(평가 원본).

LLM·외부 호출 없음. 약 3개 합성 입력(타이레놀콜드-에스정 A · 이지렉트정 B · 게보린 C, ISSUE-022 모양)을 쓴다.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from app.agent import fixed_phrases as fp
from app.agent.finalize import SECTIONS, finalize, render_text
from app.agent.sentence_filter import _DECISION_PATTERNS, unsafe_reason
from app.api.schemas import to_chat_response

KIDS = "한국의약품안전관리원"
A, B, C = ("타이레놀콜드-에스정", "SEQ_A"), ("이지렉트정0.5밀리그램", "SEQ_B"), ("게보린릴랙스연질캡슐", "SEQ_C")


def _base(kind: str, status: str, eid: str, drugs: list[tuple[str, str]], **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "status": status, "subject": [d[0] for d in drugs], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": kind, "source_kind": "FILE", "drugs": [d[0] for d in drugs], "drug_keys": [d[1] for d in drugs],
            "notes": [], "matches": [{"row_key": "rk", "row_evidence_id": f"{eid}#a", "notice_no": "20250046", "notice_date": "2025-07-14",
                                      "reason": "경련, 반사항진, 이상고열, 혼수 등"}] if status == "FOUND" else [], **kw}


def _pair(a: tuple[str, str], b: tuple[str, str], status: str = "FOUND", **kw: Any) -> dict[str, Any]:
    return _base("contra_pair", status, f"contra_pair:{a[1]}:{b[1]}", [a, b], **kw)


def _caution(kind: str, d: tuple[str, str], status: str) -> dict[str, Any]:
    return _base(kind, status, f"{kind}:{d[1]}", [d])


def _chunk(subject: str = "188903ATB") -> dict[str, Any]:
    """검색 근거 항목(`search_common.chunk_item` 모양: `drugs` 칸 없음, `subject`는 품목기준코드·성분코드·위치 중 하나)."""
    return {"kind": "chunk", "status": "FOUND", "subject": [subject], "evidence_id": "l2p-abc", "source": f"{KIDS} x", "as_of": "2026-07-21",
            "flags": [], "matches": [], "dataset_key": "contra_pair", "source_kind": "CORPUS_QUOTE", "text": "경련 등 보고",
            "verdict_allowed": False}


def three_drugs() -> list[dict[str, Any]]:
    """ISSUE-022 모양: A·B 병용 FOUND, 나머지 짝 목록에 없음, A 용량주의 FOUND, B·C 용량주의 목록에 없음, 짝 하나 확인 못 함 없음."""
    return [_pair(A, B), _pair(A, C, "NOT_LISTED"), _pair(B, C, "NOT_LISTED"),
            _caution("dose", A, "FOUND"), _caution("dose", B, "NOT_LISTED"), _caution("dose", C, "NOT_LISTED")]


def _rows(resp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["key"]: r for r in resp["product_rows"]}


# --------------------------------------------------------------------------- 승인 문구 ①~⑧(2026-11-19, 글자 그대로)
APPROVED = {
    "DOSE_CHECK_QUESTION": "오늘 이 약(같은 성분)을 이미 드셨나요?",
    "DOSE_CHECK_YES": "예",
    "DOSE_CHECK_NO": "아니요",
    "DOSE_NOTICE": "오늘 이미 드셨다면 하루 최대량을 넘을 수 있어요. 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",
    "DOSE_CAUTION_DESC": "하루 최대량이 정해진 성분이에요. 오늘 이미 드신 약이 있으면 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",
    "RESULT_SUMMARY_FOUND": "약 {n}개를 함께 먹을 때: 병용금기 {k}건({pairs})",
    "RESULT_SUMMARY_NONE": "약 {n}개를 함께 먹을 때: 병용금기 목록에 오른 짝 없음(안전하다는 뜻이 아님)",
    "RESULT_SUMMARY_UNCHECKED_TAIL": " · 확인하지 못한 짝 {u}건",
    "RESULT_SUMMARY_PAIR_JOIN": " + ",
    "RESULT_SUMMARY_PAIRS_SEP": ", ",
    "PAIR_ONLY_NOTICE": "병용금기는 두 약씩 짝으로 확인해요. 세 약 이상을 함께 먹을 때의 규칙은 자료에 따로 없어요.",
    "REST_FOLD_LINE": "나머지 확인 {n}건: 금기·주의 목록에 없음(안전하다는 뜻이 아님)",
    "REST_FOLD_OPEN": "펼치기",
    "REST_FOLD_CLOSE": "접기",
    "REDOSE_NOTICE": "추가 복용 여부·간격은 정해 드릴 수 없어요. 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요.",  # AG-22-01 A
    "PAIR_REF_LINE": "병용금기 짝 {n}건에 포함",  # FE-11-05 A
}


@pytest.mark.parametrize("name", sorted(APPROVED))
def test_approved_phrase_text_is_exact_and_not_draft(name: str) -> None:
    assert getattr(fp, name) == APPROVED[name] and name not in fp.DRAFT_KEYS


def test_dose_caution_label_replaced() -> None:
    assert fp.CAUTION_LABELS["dose"] == "하루 최대량 주의 성분 포함"


@pytest.mark.parametrize("name", sorted(APPROVED))
def test_approved_phrases_have_no_number_dose_order_or_internal_term(name: str) -> None:
    text = re.sub(r"\{[a-z]+\}", "", getattr(fp, name))
    assert not re.search(r"\d", text)  # 숫자 없음(RFP-21-03)
    assert unsafe_reason(text) is None and not any(p.search(re.sub(r"\s+", "", text)) for p in _DECISION_PATTERNS)
    assert not any(t in text for t in fp.FORBIDDEN_SCREEN_TERMS)


def test_question_mark_counts() -> None:
    assert fp.DOSE_CHECK_QUESTION.count("?") == 1
    assert all(getattr(fp, n).count("?") == 0 for n in APPROVED if n != "DOSE_CHECK_QUESTION")


# --------------------------------------------------------------------------- entries 불변(평가 원본)
def test_entries_identical_with_and_without_new_inputs() -> None:
    items = [*three_drugs(), _chunk()]
    plain = finalize(copy.deepcopy(items), "요약")
    full = finalize(copy.deepcopy(items), "요약", intake_question=True, redose_question=True, took_today=True, n_drugs=3)
    assert plain["entries"] == full["entries"] and plain["summary"] == full["summary"] == "요약"


# --------------------------------------------------------------------------- 약 3개: 행·구역·배지·요약
def test_three_drugs_sections_rows_and_badges() -> None:
    resp = finalize(three_drugs(), None, n_drugs=3)
    sec = resp["sections"]
    assert sec["contra_pair:SEQ_A:SEQ_B"] == "core"
    assert sec["contra_pair:SEQ_A:SEQ_C"] == sec["contra_pair:SEQ_B:SEQ_C"] == "rest"
    assert sec["dose:SEQ_A"] == "caution" and sec["dose:SEQ_B"] == sec["dose:SEQ_C"] == "rest"
    assert set(sec.values()) <= set(SECTIONS)
    rows = _rows(resp)
    # A: 병용 짝 + 용량주의 → 배지 없음(병용 배지는 짝 줄에만), 짝 참조 1, 구역 core, 용량주의 설명
    assert rows["SEQ_A"]["badges"] == [] and rows["SEQ_A"]["pair_ref"]["count"] == 1 and rows["SEQ_A"]["section"] == "core"
    assert rows["SEQ_A"]["pair_ref"]["text"] == "병용금기 짝 1건에 포함" and rows["SEQ_A"]["caution_desc"] == fp.DOSE_CAUTION_DESC
    assert rows["SEQ_A"]["contra_kinds"] == ["contra_pair"]  # 칩 원인 글자는 유지
    # B: 짝에만 걸림 → 배지 없는 "찾음" 줄 + 짝 참조, core(C-4 A)
    assert rows["SEQ_B"]["bucket"] == "identified" and rows["SEQ_B"]["text"] == fp.IDENTIFIED_LINE and rows["SEQ_B"]["section"] == "core"
    # C: 걸린 것 없음 → 목록에 없음 줄(응답 변환이 제품 줄로 내지 않음), rest
    assert rows["SEQ_C"]["bucket"] == "not_listed" and rows["SEQ_C"]["pair_ref"] is None and rows["SEQ_C"]["section"] == "rest"
    # "삐! 병용금기"는 짝 줄(entries)에만
    assert [e["text"] for e in resp["entries"] if e["kind"] == "contra_pair" and e["bucket"] == "found"] == [fp.BADGE_PAIR]
    assert not any(b["kind"] == "contra_pair" for r in resp["product_rows"] for b in r["badges"])


def test_three_drugs_result_summary_and_pair_only_notice() -> None:
    rs = finalize(three_drugs(), None, n_drugs=3)["result_summary"]
    assert rs["text"] == "약 3개를 함께 먹을 때: 병용금기 1건(타이레놀콜드-에스정 + 이지렉트정0.5밀리그램)"
    assert rs["n_pairs"] == 3 and rs["n_pairs_unchecked"] == 0 and rs["pair_only_notice"] == fp.PAIR_ONLY_NOTICE
    assert rs["pairs_found"] == [{"drugs": [A[0], B[0]], "evidence_ids": ["contra_pair:SEQ_A:SEQ_B"]}]


def test_result_summary_none_unchecked_two_drugs_and_absent_cases() -> None:
    none = finalize([_pair(A, B, "NOT_LISTED")], None, n_drugs=2)["result_summary"]
    assert none["text"] == "약 2개를 함께 먹을 때: 병용금기 목록에 오른 짝 없음(안전하다는 뜻이 아님)" and none["pair_only_notice"] is None
    unchecked = _pair(A, C, "UNIDENTIFIED", flags=["PAIR_NOT_CHECKED"])
    part = finalize([_pair(A, B, "NOT_LISTED"), unchecked, _pair(B, C, "NOT_LISTED")], None, n_drugs=3)["result_summary"]
    assert part["n_pairs_unchecked"] == 1 and part["text"].endswith(" · 확인하지 못한 짝 1건")  # 0건이 "안전"으로 읽히지 않게
    missing = finalize([_pair(A, B, "NOT_LISTED")], None, n_drugs=3)["result_summary"]  # 결과에 없는 짝 2개 = 확인 못 함
    assert missing["n_pairs_unchecked"] == 2
    assert finalize([_caution("dose", A, "FOUND")], None, n_drugs=2)["result_summary"] is None  # 짝 조회가 없으면 지어내지 않는다
    assert finalize(three_drugs(), None)["result_summary"] is None  # 약 수를 모르면(1개 이하) 없음
    assert finalize(three_drugs(), None, n_drugs=3, refuse_reason="PRESCRIPTION")["result_summary"] is None


# --------------------------------------------------------------------------- C-3 B: 판정이 아닌 검색 근거 줄
def test_search_evidence_line_reaches_findings_but_has_no_section() -> None:
    """먼저 확인한 사실(2026-11-19): 검색 근거(`chunk`) 줄은 지금 응답 `findings`에 나간다. `subject`가 성분코드면 근거 줄 그대로 한 줄,
    위치(`제3조`)면 그 글자를 키로 한 "찾음" 제품 줄이 된다. 구역은 값 없음(None, C-3 B)이라 화면은 근거 상세에만 둔다(응답 변환은 3단계 BE)."""
    resp = finalize([_pair(A, B), _chunk("188903ATB")], None, n_drugs=2)
    assert resp["sections"]["l2p-abc"] is None
    r = to_chat_response(resp, end_reason="NORMAL")
    assert [f.kind for f in r.findings if f.evidence_id == "l2p-abc"] == ["chunk"]
    loc = finalize([_pair(A, B), _chunk("제3조")], None, n_drugs=2)
    assert _rows(loc)["제3조"]["section"] is None  # 검색 근거만 모인 줄은 구역 없음(주의 구역으로 잡지 않는다)
    assert {_rows(loc)[k]["section"] for k in ("SEQ_A", "SEQ_B")} == {"core"}


# --------------------------------------------------------------------------- 되묻기 4경우 + 답
@pytest.mark.parametrize("dose_found,intake_q,asks", [(True, True, True), (True, False, False), (False, True, False), (False, False, False)])
def test_dose_check_four_cases(dose_found: bool, intake_q: bool, asks: bool) -> None:
    items = [_pair(A, B, "NOT_LISTED"), _caution("dose", A, "FOUND" if dose_found else "NOT_LISTED")]
    resp = finalize(items, None, intake_question=intake_q, n_drugs=2)
    if asks:
        assert resp["dose_check"] == {"question": fp.DOSE_CHECK_QUESTION, "options": ["예", "아니요"], "drugs": [A[0]],
                                      "evidence_ids": ["dose:SEQ_A"]}
    else:
        assert resp["dose_check"] is None
    assert resp["dose_notice"] is None


@pytest.mark.parametrize("took,check,notice", [(None, True, False), (True, False, True), (False, False, False)])
def test_took_today_answer(took: bool | None, check: bool, notice: bool) -> None:
    resp = finalize([_caution("dose", A, "FOUND")], None, intake_question=True, took_today=took)
    assert (resp["dose_check"] is not None) is check and (resp["dose_notice"] == fp.DOSE_NOTICE) is notice
    if notice:  # "예"면 결과 맨 위(119·배너 다음), 요약보다 앞
        lines = render_text({**resp, "summary": "요약"}).splitlines()
        assert lines.index(fp.DOSE_NOTICE) < lines.index("요약")


def test_dose_notice_sits_below_119() -> None:
    resp = finalize([_caution("dose", A, "FOUND")], "요약", emergency=True, intake_question=True, took_today=True)
    lines = resp["text"].splitlines()
    assert lines[0] == fp.EMERGENCY_119 and lines[1] == fp.DOSE_NOTICE


def test_refuse_path_has_no_dose_or_redose() -> None:
    resp = finalize([_caution("dose", A, "FOUND")], None, refuse_reason="DOSAGE", intake_question=True, redose_question=True)
    assert resp["dose_check"] is None and resp["redose_notice"] is None and resp["route"] == "REFUSE"


def test_redose_notice_is_separate_from_summary() -> None:
    resp = finalize(three_drugs(), "모델 요약", redose_question=True, n_drugs=3)
    assert resp["redose_notice"] == fp.REDOSE_NOTICE and resp["summary"] == "모델 요약"
    assert fp.REDOSE_NOTICE in resp["text"] and resp["entries"]  # 거절로 끝나지 않고 결과를 그대로 낸다


def test_caution_descs_only_for_dose_found() -> None:
    resp = finalize(three_drugs(), None, n_drugs=3)
    assert resp["caution_descs"] == {"dose:SEQ_A": fp.DOSE_CAUTION_DESC}
    entry = next(e for e in resp["entries"] if e["evidence_id"] == "dose:SEQ_A")
    assert entry["text"] == "하루 최대량 주의 성분 포함" and "caution_desc" not in entry  # 설명은 entries가 아니라 별도 칸


def test_new_output_keys_default_shape() -> None:
    """기본 입력(새 인자 없음)이면 새 칸은 비어 있다: 이전 호출부(평가 러너 등)의 출력과 판정 칸이 같다."""
    resp = finalize(three_drugs(), None)
    assert resp["dose_check"] is None and resp["dose_notice"] is None and resp["redose_notice"] is None and resp["result_summary"] is None
