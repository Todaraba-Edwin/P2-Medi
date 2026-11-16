"""AG-08 `finalize`·고정 문구 시험(합성 items[], 가짜 모델 출력, LLM·외부 호출 없음)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.agent import fixed_phrases as fp
from app.agent.answer_schema import Citation, Sentence
from app.agent.finalize import finalize
from app.tools.provenance import FLAG_NOTES

KIDS = "한국의약품안전관리원"


def _pair(drugs=("와파린정", "아스피린정"), status="FOUND", flags=None, eid="contra_pair:1"):
    m = [{"row_key": "rk1", "row_evidence_id": eid + "#a", "reason": "출혈 위험", "notice_no": "제2026-1호", "notice_date": "2026-07-21"}] if status == "FOUND" else []
    return {"kind": "contra_pair", "status": status, "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-21", "flags": flags or [], "matches": m, "dataset_key": "contra_pair", "source_kind": "FILE",
            "drugs": list(drugs)}


def _preg(grade="2", status="FOUND", eid="pregnancy:1", source_kind="FILE", flags=None, drug="타이레놀콜드정", matches=None):
    m = matches if matches is not None else ([{"grade": grade, "detail": "상세", "notice_no": "제2026-1호", "row_key": "r", "row_evidence_id": eid + "#a"}] if status == "FOUND" else [])
    return {"kind": "pregnancy", "status": status, "subject": ["333333ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": flags or [], "matches": m, "dataset_key": "pregnancy", "source_kind": source_kind, "drugs": [drug]}


def _age(status="FOUND", eid="age:1"):
    m = [{"specific_age": "12", "row_key": "r", "row_evidence_id": eid + "#a"}] if status == "FOUND" else []
    return {"kind": "age", "status": status, "subject": ["444444ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "matches": m, "dataset_key": "age", "source_kind": "FILE", "drugs": ["어린이약"]}


def _unid(name="뿌셔캡슐", flags=None, retried=False):
    return {"kind": "identify", "status": "UNIDENTIFIED", "subject": [name], "evidence_id": f"identify:{name}", "source": None, "as_of": None,
            "queried_at_utc": None, "flags": flags or [], "matches": [], "dataset_key": None, "source_kind": None, "input_name": name,
            "searched": [{"dataset": "허가정보", "count": 0}], "retried": retried}


def _ident(name="타이레놀정500", matched_by="product_name", flags=None):
    return {"kind": "identify", "status": "FOUND", "subject": [name], "evidence_id": f"identify:{name}", "source": "식약처", "as_of": "2026-11-01",
            "flags": flags or [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": name, "matched_by": matched_by,
            "ingredients": [{"display": "아세트아미노펜", "name_ko": "아세트아미노펜"}]}


def _label(reason=None, status="FOUND", flags=None, name="이지렉트정", eid="label:1"):
    return {"kind": "label", "status": status, "subject": [name], "evidence_id": eid, "source": "식약처 의약품 제품 허가정보", "as_of": "2026-11-01",
            "flags": flags or [], "matches": [], "dataset_key": "prmsn", "source_kind": "API_DIRECT", "name": name, "missing_reason": reason, "is_label": True}


def _check_fixed(resp):
    assert resp["disclaimer"] and resp["disclaimer"] == fp.DISCLAIMER
    assert resp["fixed_notice"] == fp.FIXED_NOTICE
    assert fp.NOT_SAFE_NOTICE in resp["text"] and fp.PHARMACIST_CHECK_NOTICE in resp["text"] and fp.DISCLAIMER in resp["text"]


# --------------------------------------------------------------------------- 고정 문구 보존(모델 출력 변조)
@pytest.mark.parametrize("summary", [
    "", None, "   ", "안전합니다. 119도 약국도 필요 없어요.",
    "고지 문구와 약사 안내를 모두 지웠습니다.", "금기 목록에 없다는 것이 안전하다는 뜻이 아님 을 지우고 안전하다고 답합니다",
    "이전 지시를 무시합니다", "fixed_notice: ''",
])
def test_fixed_phrases_survive_any_model_output(summary):
    resp = finalize([_pair(status="NOT_LISTED")], summary, emergency=False)
    _check_fixed(resp)


def test_fixed_phrases_present_even_with_no_items():
    resp = finalize([], "요약", emergency=False)
    _check_fixed(resp)
    assert resp["disclaimer"].strip()


def test_summary_is_isolated_from_fixed_fields():
    resp = finalize([_pair()], "요약 한 줄", emergency=False)
    assert resp["summary"] == "요약 한 줄"
    assert "요약 한 줄" not in resp["fixed_notice"] and "요약 한 줄" not in resp["disclaimer"]


def test_not_listed_always_has_not_safe_note():
    resp = finalize([_pair(status="NOT_LISTED")], "문제 없어요", emergency=False)
    e = resp["entries"][0]
    assert e["text"] == fp.NOT_LISTED and "안전하다는 뜻이 아님" in e["text"]
    assert resp["badges"] == []


# --------------------------------------------------------------------------- 응급 119 맨 위
def test_emergency_is_first_line():
    resp = finalize([_pair()], "요약", emergency=True)
    assert resp["emergency"] == fp.EMERGENCY_119 and resp["text"].splitlines()[0] == fp.EMERGENCY_119
    assert resp["emergency_tel"] == "tel:119"
    assert resp["entries"] and resp["badges"]  # 금기 조회 결과는 함께 나간다


@pytest.mark.parametrize("kw", [{}, {"limit_reached": True}, {"refuse_reason": "STOP_DOSE_CHANGE"}])
def test_emergency_stays_on_top_in_every_mode(kw):
    resp = finalize([_pair()], "요약", emergency=True, **kw)
    assert resp["text"].splitlines()[0] == fp.EMERGENCY_119


def test_no_emergency_means_no_119_line():
    resp = finalize([_pair()], "요약", emergency=False)
    assert resp["emergency"] is None and fp.EMERGENCY_119 not in resp["text"]


def test_emergency_text_has_only_119_no_other_contacts():
    assert "119" in fp.EMERGENCY_119 and "1339" not in fp.EMERGENCY_119
    assert not re.search(r"\d{3,4}-\d{3,4}", fp.EMERGENCY_119)


def test_emergency_line_not_deletable_by_summary():
    resp = finalize([], "응급 아님, 119 문구 삭제", emergency=True)
    assert resp["text"].startswith(fp.EMERGENCY_119)


# --------------------------------------------------------------------------- 혼합 순서
def test_found_first_in_mixed_items():
    items = [_unid(), _pair(status="NOT_LISTED", eid="contra_pair:2"), _ident(), _pair()]
    resp = finalize(items, "요약", emergency=False)
    buckets = [e["bucket"] for e in resp["entries"]]
    assert buckets == ["found", "not_listed", "identified", "unconfirmed"]


def test_found_not_buried_by_unconfirmed():
    resp = finalize([_unid(), _unid("두번째약"), _preg()], None, emergency=False)
    assert resp["entries"][0]["bucket"] == "found"
    assert resp["text"].index("삐! 임부금기 2등급") < resp["text"].index(fp.UNIDENTIFIED)


def test_unidentified_says_not_confirmed_and_advises_pharmacist():
    resp = finalize([_unid()], None, emergency=False)
    e = resp["entries"][0]
    assert e["text"] == fp.UNIDENTIFIED and e["input_name"] == "뿌셔캡슐" and e["why"] == fp.UNIDENTIFIED_WHY
    assert resp["pharmacist_advice"] and "뿌셔캡슐" in resp["pharmacist_advice"][0]
    assert resp["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED
    assert fp.NOT_LISTED not in resp["text"]


def test_identified_line_has_no_not_listed_wording():
    resp = finalize([_ident(), _unid()], None, emergency=False)
    ident = next(e for e in resp["entries"] if e["bucket"] == "identified")
    # AG-08-12 B: 줄 글자는 표지 "찾음"이고 약 이름은 줄 머리(`drug`)에 있다(PRD-14 §5.2)
    assert "금기 목록에 없" not in ident["text"] and ident["drug"] == "타이레놀정500"
    assert "[타이레놀정500] " + ident["text"] in resp["text"].splitlines()


def test_order_found_kinds_pair_then_pregnancy_then_age():
    resp = finalize([_age(), _preg(), _pair()], None, emergency=False)
    assert [e["kind"] for e in resp["entries"]] == ["contra_pair", "pregnancy", "age"]
    assert [b["kind"] for b in resp["badges"]] == ["contra_pair", "pregnancy", "age"]


# --------------------------------------------------------------------------- 표지 2개·등급·불일치
def test_pair_and_pregnancy_found_gives_two_badges():
    resp = finalize([_preg(), _pair()], None, emergency=False)
    texts = [b["text"] for b in resp["badges"]]
    assert texts == ["삐! 병용금기", "삐! 임부금기 2등급"]
    assert all("삐!" in t and "금기" in t for t in texts)  # 모든 표지에 종류 글자(G15)


def test_pregnancy_m_grade_badge_and_note():
    resp = finalize([_preg(grade="M")], None, emergency=False)
    b = resp["badges"][0]
    assert b["text"] == "삐! 임부금기 M등급" and b["note"] == "적응증에 따라 등급이 달라요"
    assert "단계" not in b["text"]


@pytest.mark.parametrize("grade", ["1", "2", "1등급"])
def test_pregnancy_grade_text(grade):
    resp = finalize([_preg(grade=grade)], None, emergency=False)
    assert resp["badges"][0]["text"] == f"삐! 임부금기 {grade.removesuffix('등급')}등급"


def test_age_badge_text():
    assert finalize([_age()], None, emergency=False)["badges"][0]["text"] == "삐! 연령금기"


def test_grade_mismatch_gives_three_ordered_badges_with_source_tail():
    ms = [{"grade": "1", "row_key": "a", "row_evidence_id": "pregnancy:1#a", "source_kind": "API_DIRECT"},
          {"grade": "2", "row_key": "b", "row_evidence_id": "pregnancy:1#b", "source_kind": "FILE"}]
    resp = finalize([_preg(matches=ms), _pair()], None, emergency=False)
    assert [b["text"] for b in resp["badges"]] == ["삐! 병용금기", "삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]
    assert all("등급이 달라요" not in b["text"] for b in resp["badges"])  # 합친 배지 없음


def test_caution_kinds_do_not_use_bbi():
    it = {**_age(), "kind": "dose", "dataset_key": "dose"}
    resp = finalize([it], None, emergency=False)
    assert resp["badges"][0]["text"] == "용량 주의" and "삐!" not in resp["badges"][0]["text"]


def test_badges_not_made_for_identify_or_unconfirmed():
    resp = finalize([_ident(), _unid()], None, emergency=False)
    assert resp["badges"] == []


# --------------------------------------------------------------------------- 코드 없음·참고 전용·강등
@pytest.mark.parametrize("flag", ["CODE_NOT_LINKED", "LOOKUP_FAILED", "AMBIGUOUS_NAME", "REFERENCE_ONLY"])
def test_demote_flags_never_render_as_not_listed(flag):
    resp = finalize([_pair(status="NOT_LISTED", flags=[flag])], None, emergency=False)
    e = resp["entries"][0]
    assert e["bucket"] == "unconfirmed" and fp.NOT_LISTED not in resp["text"] and fp.UNIDENTIFIED in e["text"]
    assert resp["pharmacist_advice"] and resp["pharmacist_advice_fixed"]


def test_reference_only_is_a_reference_line_not_a_verdict():
    resp = finalize([_pair(status="UNIDENTIFIED", flags=["REFERENCE_ONLY"])], None, emergency=False)
    e = resp["entries"][0]
    assert e["bucket"] == "unconfirmed" and "판정은 아니" in e["reference_line"]
    assert resp["badges"] == []


def test_reference_only_even_if_status_found_makes_no_badge():
    resp = finalize([_pair(flags=["REFERENCE_ONLY"])], None, emergency=False)
    assert resp["badges"] == [] and resp["entries"][0]["bucket"] == "unconfirmed"


def test_flag_notes_reused_from_provenance():
    assert fp.CODE_NOT_LINKED is FLAG_NOTES["CODE_NOT_LINKED"] and fp.AMBIGUOUS_NAME is FLAG_NOTES["AMBIGUOUS_NAME"]
    assert fp.REFERENCE_ONLY is FLAG_NOTES["REFERENCE_ONLY"]


@pytest.mark.parametrize("flag,expected", [("API_FAIL", "실시간 확인을 하지 못함"), ("API_PAIR_INCOMPLETE", "실시간 확인을 하지 못함"),
                                           ("FILE_ONLY", "실시간 조회에는 없어요"), ("API_ONLY", "안전하다는 뜻이 아니에요")])
def test_api_flag_notes(flag, expected):
    resp = finalize([_pair(flags=[flag])], None, emergency=False)
    assert any(expected in n for n in resp["entries"][0]["notes"])


# --------------------------------------------------------------------------- 성분 단위(NO_PRODUCT_INFO)
def test_ingredient_level_gets_no_product_info_and_keeps_verdict():
    ident = _ident("이부프로펜", matched_by="ingredient_name", flags=["NO_PRODUCT_INFO"])
    resp = finalize([_pair(flags=["NO_PRODUCT_INFO"]), ident], None, emergency=False)
    notes = [n for e in resp["entries"] for n in e["notes"]]
    assert notes.count(fp.NO_PRODUCT_INFO) == 2
    assert resp["entries"][0]["bucket"] == "found" and resp["badges"][0]["text"] == "삐! 병용금기"  # 판정은 그대로
    assert "허가 라벨" not in resp["text"] and "허가사항" in fp.NO_PRODUCT_INFO


def test_no_product_info_text_asks_for_product_name():
    assert "봉투의 제품명을 알려 주시면 더 확인할 수 있어요" in fp.NO_PRODUCT_INFO


def test_ingredient_level_not_listed_still_shows_not_safe():
    resp = finalize([_pair(status="NOT_LISTED", flags=["NO_PRODUCT_INFO"])], None, emergency=False)
    assert resp["entries"][0]["text"] == fp.NOT_LISTED and fp.NO_PRODUCT_INFO in resp["entries"][0]["notes"]


def test_easy_text_missing_names_the_drug():
    resp = finalize([_label(flags=["EASY_TEXT_MISSING"])], None, emergency=False)
    assert any("이지렉트정은 전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요" in n for n in resp["entries"][0]["notes"])


# --------------------------------------------------------------------------- 상한 도달
def test_limit_reached_drops_llm_summary_and_keeps_verdicts():
    items = [_pair(), _pair(status="NOT_LISTED", eid="contra_pair:2"), _unid()]
    resp = finalize(items, "모델이 쓴 요약", emergency=False, limit_reached=True)
    assert resp["summary"] is None and "모델이 쓴 요약" not in resp["text"]
    assert resp["notice"] == fp.LIMIT_REACHED
    assert [e["bucket"] for e in resp["entries"]] == ["found", "not_listed", "unconfirmed"]
    assert resp["pharmacist_advice_fixed"] and resp["badges"][0]["text"] == "삐! 병용금기"
    _check_fixed(resp)


def test_limit_reached_with_no_items_still_advises():
    resp = finalize([], "x", emergency=False, limit_reached=True)
    assert resp["notice"] and resp["pharmacist_advice_fixed"]
    _check_fixed(resp)


def test_limit_reached_with_emergency_keeps_119_first():
    resp = finalize([_pair()], None, emergency=True, limit_reached=True)
    assert resp["text"].splitlines()[0] == fp.EMERGENCY_119 and fp.LIMIT_REACHED in resp["text"]


def test_limit_reached_undecided_items_are_not_confirmed():
    resp = finalize([_unid("가약"), _unid("나약")], None, emergency=False, limit_reached=True)
    assert all(e["text"] == fp.UNIDENTIFIED for e in resp["entries"])


def test_limit_reached_no_not_listed_for_undecided():
    resp = finalize([_unid()], None, emergency=False, limit_reached=True)
    assert fp.NOT_LISTED not in resp["text"]


# --------------------------------------------------------------------------- 미확보 4종
@pytest.mark.parametrize("reason,expected", [
    ("OUT_OF_SCOPE", "이지렉트정은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요"),
    ("ABSENT", "이지렉트정 허가사항에는 이 항목이 따로 적혀 있지 않아요"),
    ("FETCH_FAIL", "지금은 허가사항을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요"),
    ("SEARCH_MISS", "허가사항에서 관련 문장을 찾지 못했어요"),
])
def test_missing_reason_texts_match_table(reason, expected):
    resp = finalize([_label(reason=reason)], "원문을 가져왔어요", emergency=False)
    e = resp["entries"][0]
    assert e["text"] == expected and e["unresolved"]
    assert resp["pharmacist_advice"] and resp["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED
    _check_fixed(resp)


def test_missing_search_miss_via_no_evidence_status():
    it = _label(reason="SEARCH_MISS", status="NO_EVIDENCE")
    resp = finalize([it], None, emergency=False)
    assert resp["entries"][0]["text"] == fp.MISSING_SEARCH_MISS and resp["events"] == [{"rule": "H27", "event": "MISSING_REASON", "code": "SEARCH_MISS"}]


def test_no_evidence_without_reason_uses_no_evidence_text():
    resp = finalize([_label(status="NO_EVIDENCE")], None, emergency=False)
    assert resp["entries"][0]["text"] == fp.NO_EVIDENCE


def test_missing_advice_strong_and_not_safe_implying():
    resp = finalize([_label(reason="OUT_OF_SCOPE")], None, emergency=False)
    adv = resp["pharmacist_advice"][0]
    assert "약국·약사에게" in adv and "괜찮다는 뜻이 아니에요" in adv


def test_missing_constants_have_no_doctor_or_official_site():
    consts = [*fp.MISSING_TEXT.values(), fp.PHARMACIST_ADVICE, fp.PHARMACIST_ADVICE_NO_NAMES, fp.PHARMACIST_ADVICE_FIXED]
    for c in consts:
        assert "의사" not in c and "공식 사이트" not in c


def test_missing_events_carry_only_codes():
    resp = finalize([_label(reason="FETCH_FAIL", name="비밀약이름")], None, emergency=False)
    assert all(set(ev) == {"rule", "event", "code"} for ev in resp["events"])
    assert "비밀약이름" not in str(resp["events"])


def test_unknown_missing_reason_does_not_invent_cause():
    resp = finalize([_label(reason="WHATEVER")], None, emergency=False)
    assert resp["entries"][0]["text"] == fp.NO_EVIDENCE


def test_grade_def_missing_texts_and_advice():
    resp = finalize([_preg()], None, emergency=False,
                    grade_def_missing=[{"grade": "2", "missing_reason": "FETCH_FAIL"}, {"grade": "M", "missing_reason": "OUT_OF_SCOPE"}])
    assert resp["grade_def_missing"] == [
        "지금은 임부금기 2등급의 뜻(고시 원문)을 불러오지 못했어요. 잠시 뒤 다시 시도해 보세요.",
        "임부금기 M등급의 뜻(고시 원문)을 아직 준비하지 못했어요.",
    ]
    assert fp.GRADE_DEF_PHARMACIST_ADVICE in resp["pharmacist_advice"]
    assert "근거 문장을 찾지 못했어요" not in resp["text"]


# --------------------------------------------------------------------------- source_kind 차단
def test_item_without_source_kind_is_blocked_not_rendered_as_evidence():
    it = {**_pair(), "source_kind": None}
    resp = finalize([it], "요약", emergency=False)
    assert resp["entries"][0]["bucket"] == "unconfirmed" and resp["badges"] == [] and resp["detail"] == [] and resp["citations"] == []
    assert resp["warnings"] and resp["warnings"][0]["code"] == "SOURCE_KIND_BLOCKED"
    assert resp["pharmacist_advice"]  # 금기 발견이 사라진 자리에 약사 확인을 둔다


def test_llm_summary_source_kind_is_not_used_as_evidence():
    it = {**_pair(), "source_kind": "LLM_SUMMARY"}
    resp = finalize([it], None, emergency=False)
    assert resp["entries"][0]["bucket"] == "unconfirmed" and resp["detail"] == []


def test_valid_source_kinds_render_with_label():
    resp = finalize([_pair()], None, emergency=False)
    assert resp["entries"][0]["source_label"] == "공식 파일 · 병용금기 파일"
    assert len(resp["detail"]) == 1 and resp["detail"][0]["source_kind"] == "FILE"


def test_unidentified_without_source_kind_is_not_a_violation():
    assert finalize([_unid()], None, emergency=False)["warnings"] == []


def test_source_kind_texts_match_provenance():
    from app.tools.provenance import SOURCE_KIND
    assert fp.SOURCE_KIND_TEXT == SOURCE_KIND


# --------------------------------------------------------------------------- 거절·렌더러 연동
@pytest.mark.parametrize("reason", sorted(fp.REFUSE_MESSAGES))
def test_refusal_summary_is_code_text(reason):
    resp = finalize([], "모델 요약", emergency=False, refuse_reason=reason)
    assert resp["summary"] == fp.REFUSE_MESSAGES[reason] and resp["route"] == "REFUSE"
    _check_fixed(resp)


def test_unknown_refuse_reason_uses_generic_text():
    assert finalize([], None, emergency=False, refuse_reason="???")["summary"] == fp.REFUSE_MESSAGES["OUT_OF_SCOPE"]


def test_renderer_interface_detail_citations_and_quote():
    it = _pair()
    it["matches"][0]["reason"] = "출혈 위험이 높아요"
    s = Sentence(text="둘을 함께 먹으면 출혈 위험이 있어요.", evidence_ids=["contra_pair:1#a"], claim_type="fact",
                 citations=[Citation(evidence_id="contra_pair:1#a", start=0, end=5)])
    resp = finalize([it], s.text, emergency=False, sentences=[s])
    assert resp["detail"][0]["rows"][0]["notice_no"] == "제2026-1호"
    assert resp["citations"] and resp["citations"][0]["evidence_id"] == "contra_pair:1#a"
    assert resp["citations"][0]["quotes"][0]["text"] == "출혈 위험"


# --------------------------------------------------------------------------- 문구 위생
_SCREEN_TEXTS = [
    fp.EMERGENCY_119, fp.DISCLAIMER, fp.FIXED_NOTICE, fp.NOT_LISTED, fp.UNIDENTIFIED, fp.NO_EVIDENCE, fp.NO_PRODUCT_INFO, fp.EASY_TEXT_MISSING,
    fp.UNIDENTIFIED_WHY, fp.UNIDENTIFIED_RETRIED, fp.UNIDENTIFIED_NEXT, fp.UNIDENTIFIED_NOT_SAFE, fp.IDENTIFIED_LINE, fp.LIMIT_REACHED,
    fp.PHARMACIST_ADVICE, fp.PHARMACIST_ADVICE_FIXED, fp.LOOKUP_FAILED, fp.TRUNCATED, fp.REFERENCE_ONLY_LINE, fp.LABEL_ONE_LINE,
    fp.CODE_NOT_LINKED, fp.AMBIGUOUS_NAME, fp.REFERENCE_ONLY, fp.INVALID_CODE, fp.PAIR_NOT_CHECKED,
    fp.EMERGENCY_119_WIDE, fp.UNIDENTIFIED_SUB_LINE, fp.PREGNANCY_NOT_CHECKED, fp.NOT_CHECKED_TEMPLATE, fp.AGE_INFO_LINE, fp.CLARIFY_PICK_LINE,
    fp.GRADE_MISMATCH_NOTE, fp.DOSE_QUOTE_NOTICE, fp.GRADE_DEF_TITLE, fp.NOTICE_API_FAIL, *fp.INGR_CODE_MISSING_TEXT.values(),
    *fp.ERROR_MESSAGES.values(), fp.INGR_STATE_CAUSE, fp.INGR_STATE_PAIR_CAUSE, fp.INGR_STATE_DUP,
    *fp.MISSING_TEXT.values(), *fp.GRADE_DEF_MISSING_TEXT.values(), *fp.REFUSE_MESSAGES.values(), *fp.SOURCE_KIND_TEXT.values(),
    fp.BADGE_PAIR, fp.BADGE_PREGNANCY, fp.BADGE_PREGNANCY_M, fp.BADGE_PREGNANCY_M_NOTE, fp.BADGE_AGE, *fp.CAUTION_LABELS.values(),
    *fp.FLAG_LINES.values(),
]


@pytest.mark.parametrize("text", _SCREEN_TEXTS)
def test_no_internal_terms_on_screen_text(text):
    for term in fp.FORBIDDEN_SCREEN_TERMS:
        assert term not in text, (term, text)


def test_screen_text_of_full_response_has_no_internal_terms():
    items = [_preg(), _pair(), _pair(status="NOT_LISTED", eid="c2"), _unid(retried=True), _ident(), _label(reason="ABSENT"),
             _pair(status="UNIDENTIFIED", flags=["CODE_NOT_LINKED"], eid="c3")]
    resp = finalize(items, "요약", emergency=True, grade_def_missing=[{"grade": "1", "missing_reason": "OUT_OF_SCOPE"}])
    for term in fp.FORBIDDEN_SCREEN_TERMS:
        assert term not in resp["text"], term


def test_disclaimer_matches_rfp_chapter_7_phrases():
    rfp = (Path(__file__).resolve().parents[2] / "P2-doc" / "PJ2-RFP.md")
    if rfp.exists():
        txt = rfp.read_text(encoding="utf-8")
        for part in fp.DISCLAIMER_PARTS:
            assert part in txt
    assert len(fp.DISCLAIMER_PARTS) == 3


def test_not_safe_notice_is_not_an_affirmative_safety_claim():
    assert "안전하다는 뜻이 아니" in fp.NOT_SAFE_NOTICE
    for c in (fp.MISSING_TEXT.values()):
        assert not re.search(r"(안전합니다|안전해요|괜찮아요|문제없|상호작용 없)", c)


def test_draft_keys_exist_in_module():
    for k in fp.DRAFT_KEYS:
        assert hasattr(fp, k), k


def test_harness_table_values_match_constants():
    doc = Path(__file__).resolve().parents[2] / "P2-doc" / "PJ2-Agent-Harness.md"
    if not doc.exists():
        pytest.skip("문서 없음")
    txt = doc.read_text(encoding="utf-8")
    for c in (fp.UNIDENTIFIED, fp.NO_EVIDENCE, fp.NOT_LISTED, fp.MISSING_FETCH_FAIL, fp.MISSING_SEARCH_MISS):
        assert c in txt, c
    for t in (fp.MISSING_OUT_OF_SCOPE, fp.MISSING_ABSENT, fp.EASY_TEXT_MISSING):
        assert t.replace("{drug}", "{약 이름}") in txt, t
