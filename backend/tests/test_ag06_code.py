"""AG-06 코드 부분 시험: 가짜 `items[]`(BE-09 `ToolResult.to_dict()` 형식)로 LLM·DB 없이 확인한다."""

from __future__ import annotations

import copy

import pytest

from app.agent.answer_schema import AnswerDraft, Citation, Sentence, parse_draft
from app.agent.patterns import (
    find_codes,
    has_code,
    is_dur_code,
    is_kids_code,
    tool_grades,
    unsupported_identifiers,
)
from app.agent.quote_check import build_text_index, resolve_citation, verify_quote_text
from app.agent.renderer import render
from app.agent.sentence_filter import (
    CODE_IN_TEXT,
    NO_EVIDENCE,
    UNKNOWN_EVIDENCE,
    filter_sentences,
    known_evidence_ids,
)
from app.tools.lookup import FOUND, NOT_LISTED, UNIDENTIFIED, Item, ToolResult

KIDS = "한국의약품안전관리원"


def _preg(code, grade, detail, rk):
    eid = f"pregnancy:{code}"
    m = {"ingr_code": code, "ingr_name": "성분", "grade": grade, "detail": detail, "notice_no": "제2026-1호",
         "notice_date": "2026-07-21", "row_key": rk, "row_evidence_id": f"{eid}#{rk[:12]}"}
    return Item("pregnancy", FOUND, (code,), eid, KIDS, "2026-07-21", matches=[m])


def _items():
    pair_row = {"code_a": "111111ATB", "code_b": "222222ATB", "reason": "병용 시 위험 증가", "remark": None,
                "notice_no": "제2026-2호", "notice_date": "2026-07-21", "row_key": "abcdef0123456789",
                "row_evidence_id": "contra_pair:111111ATB:222222ATB#abcdef012345"}
    return ToolResult([
        Item("contra_pair", FOUND, ("111111ATB", "222222ATB"), "contra_pair:111111ATB:222222ATB", KIDS,
             "2026-07-21", matches=[pair_row]),
        _preg("333333ATB", "1", "임부에게 투여하지 말 것", "1111aaaa2222bbbb"),
        _preg("444444ATB", "2", "치료상 유익성이 클 때만 투여", "3333cccc4444dddd"),
        _preg("555555ATB", "M", "상병에 따라 1등급 또는 2등급", "5555eeee6666ffff"),
        Item("pregnancy", NOT_LISTED, ("666666ATB",), "pregnancy:666666ATB", KIDS, "2026-07-21"),
        Item("identify", UNIDENTIFIED, ("XYZ",), "identify:XYZ", KIDS, "2026-07-21", ["INVALID_CODE"]),
    ]).to_dict()["items"]


@pytest.fixture
def items():
    return _items()


def S(text, ids=(), ct="fact", cites=()):
    return Sentence(text=text, evidence_ids=list(ids), claim_type=ct, citations=list(cites))


# ---------------------------------------------------------------- 스키마
def test_schema_rejects_unknown_field_and_bad_type():
    d, err = parse_draft({"sentences": [{"text": "a", "claim_type": "fact", "evidence_ids": [], "extra": 1}]})
    assert d is None and err.startswith("SCHEMA_INVALID")
    assert parse_draft({"sentences": [{"text": "a", "claim_type": "opinion"}]})[0] is None
    assert parse_draft({"sentences": [{"text": "  ", "claim_type": "fact"}]})[0] is None
    assert parse_draft("not json")[0] is None


def test_schema_ok_and_citation_range():
    d, err = parse_draft('{"sentences":[{"text":"결론","claim_type":"conclusion"}]}')
    assert err is None and d.sentences[0].evidence_ids == []
    with pytest.raises(ValueError):
        Citation(evidence_id="x", start=5, end=5)


# ---------------------------------------------------------------- 문장 필터
def test_filter_drops_no_evidence_unknown_and_code(items):
    d = AnswerDraft(sentences=[
        S("병용 주의가 있어요.", ["contra_pair:111111ATB:222222ATB"]),
        S("근거 없는 사실 문장이에요."),
        S("모르는 근거예요.", ["pregnancy:999999ATB"]),
        S("결론: 확인이 필요해요.", [], "conclusion"),
        S("약사에게 확인하세요.", [], "guidance"),
        S("성분 111111ATB 때문이에요.", ["contra_pair:111111ATB:222222ATB"]),
        S("결론인데 모르는 ID.", ["nope"], "conclusion"),
    ])
    r = filter_sentences(d, items)
    assert [x.text for x in r.kept] == ["병용 주의가 있어요.", "결론: 확인이 필요해요.", "약사에게 확인하세요."]
    assert [(x.index, x.reason) for x in r.dropped] == [
        (1, NO_EVIDENCE), (2, UNKNOWN_EVIDENCE), (5, CODE_IN_TEXT), (6, UNKNOWN_EVIDENCE)]
    ev = r.events[0]
    assert ev["rule"] == "H1" and ev["dropped"] == 4 and ev["kept"] == 3 and ev["total"] == 7
    assert ev["reasons"] == {NO_EVIDENCE: 1, UNKNOWN_EVIDENCE: 2, CODE_IN_TEXT: 1}


def test_filter_accepts_row_level_ids_and_counts_bad_quotes(items):
    rid = "pregnancy:333333ATB#1111aaaa2222"
    assert rid in known_evidence_ids(items)
    ok = Citation(evidence_id=rid, start=0, end=4)
    far = Citation(evidence_id=rid, start=0, end=500)
    other = Citation(evidence_id="pregnancy:444444ATB", start=0, end=2)  # 문장 근거 ID에 없음
    r = filter_sentences(AnswerDraft(sentences=[S("임부금기예요.", [rid], cites=[ok, far, other])]), items)
    assert len(r.kept) == 1 and r.bad_quotes == 2 and r.events[0]["bad_quotes"] == 2


def test_filter_empty_items_drops_all_facts():
    r = filter_sentences(AnswerDraft(sentences=[S("사실", ["a"])]), [])
    assert r.dropped_count == 1 and r.dropped[0].reason == UNKNOWN_EVIDENCE


# ---------------------------------------------------------------- 인용 글자 일치
def test_resolve_citation_cuts_text_by_code(items):
    idx = build_text_index(items)
    rid = "pregnancy:333333ATB#1111aaaa2222"
    assert idx[rid] == "임부에게 투여하지 말 것"
    r = resolve_citation(Citation(evidence_id=rid, start=0, end=4), idx)
    assert r.ok and r.text == "임부에게"
    assert resolve_citation(Citation(evidence_id=rid, start=0, end=99), idx).reason == "OUT_OF_RANGE"
    assert resolve_citation(Citation(evidence_id="zz", start=0, end=1), idx).reason == "UNKNOWN_EVIDENCE"


def test_item_level_text_joins_rows(items):
    idx = build_text_index(items)
    assert "병용 시 위험 증가" in idx["contra_pair:111111ATB:222222ATB"]
    assert idx["pregnancy:666666ATB"] == ""  # NOT_LISTED는 원문 없음


@pytest.mark.parametrize("quote,ok", [
    ("임부에게 투여하지 말 것", True),
    ("임부에게…말 것", True),                 # 생략은 …로만
    ("…투여하지…", True),
    ("임부에게는 투여하지 마세요", False),      # 의역
    ("말 것…임부에게", False),                 # 순서 바뀜
    ("임부에게 투여하지 말것", False),          # 공백 한 글자 차이
    ("…", False),
    ("", False),
])
def test_verify_quote_text(quote, ok):
    assert verify_quote_text(quote, "임부에게 투여하지 말 것") is ok


# ---------------------------------------------------------------- 정규식
@pytest.mark.parametrize("s", ["D000123", "123456ATB", "123456ATB 입니다"])
def test_code_regex_match(s):
    assert has_code(s)


@pytest.mark.parametrize("s", ["D00012", "D0001234", "12345ATB", "1234567ATB", "123456AT", "abcD000123",
                               "쉬운 요약이에요", "2026-07-21"])
def test_code_regex_no_match(s):
    assert not has_code(s)


def test_find_codes_order_and_kind():
    assert find_codes("D000123 와 123456ATB, D000456") == ["D000123", "123456ATB", "D000456"]
    assert is_dur_code("D000123") and not is_dur_code("123456ATB")
    assert is_kids_code("123456ATB") and not is_kids_code("D000123")


def test_unsupported_identifiers(items):
    assert unsupported_identifiers("기준일 2026-07-21, 1등급이에요", items) == []
    assert unsupported_identifiers("333333ATB는 1등급, 기준일 2026-07-21", items) == []
    bad = unsupported_identifiers("999999ATB는 2026-01-01 기준 1등급", items)
    assert bad == ["999999ATB", "2026-01-01"]
    assert "3등급" not in unsupported_identifiers("3등급", items)  # 정규식은 1·2등급만 본다
    assert unsupported_identifiers("2등급", []) == ["2등급"]
    assert tool_grades([{"matches": [{"grade": "1등급"}, {"grade": "m"}]}]) == {"1", "M"}


# ---------------------------------------------------------------- 렌더러
def test_render_without_llm_builds_detail_citations_badges(items):
    cid = "pregnancy:333333ATB#1111aaaa2222"
    sents = [S("병용 주의가 있어요.", ["contra_pair:111111ATB:222222ATB"]),
             S("임부금기예요.", [cid], cites=[Citation(evidence_id=cid, start=0, end=4)]),
             S("같은 근거 한 번 더.", ["contra_pair:111111ATB:222222ATB"])]
    out = render(items, sents)
    # FOUND 먼저, 나머지는 입력 순서
    assert [d["status"] for d in out.detail] == [FOUND] * 4 + [NOT_LISTED, UNIDENTIFIED]
    assert [d["evidence_id"] for d in out.detail][:2] == ["contra_pair:111111ATB:222222ATB", "pregnancy:333333ATB"]
    # 출처 표: 문장 순서, 중복 ID 한 번, 행 ID면 row_key 연결
    assert [c["evidence_id"] for c in out.citations] == ["contra_pair:111111ATB:222222ATB", cid]
    assert out.citations[0]["row_key"] is None and out.citations[1]["row_key"] == "1111aaaa2222bbbb"
    assert out.citations[1]["quotes"] == [{"start": 0, "end": 4, "text": "임부에게"}]
    assert out.citations[0]["publisher"] == KIDS and out.citations[0]["as_of"] == "2026-07-21"
    # 배지: FOUND만, 등급은 1·2·M 원문 그대로, 병용은 등급 None
    assert [(b["kind"], b["grade"]) for b in out.badges] == [
        ("contra_pair", None), ("pregnancy", "1"), ("pregnancy", "2"), ("pregnancy", "M")]
    # 행 단위 row_key 통과
    assert out.detail[1]["rows"][0]["row_key"] == "1111aaaa2222bbbb"


def test_render_missing_values_pass_as_none_with_warning(items):
    out = render(items, [])
    assert all(d["source_kind"] is None for d in out.detail)
    assert len([w for w in out.warnings if w["code"] == "MISSING_SOURCE_KIND"]) == len(items)
    # row_key가 없는 행은 None
    it = copy.deepcopy(items[1])
    it["matches"][0].pop("row_key")
    it["matches"][0].pop("row_evidence_id")
    assert render([it], []).detail[0]["rows"][0]["row_key"] is None


def test_render_passes_source_kind_through(items):
    items[0]["source_kind"] = "FILE_LOOKUP"
    items[0]["queried_at_utc"] = "2026-11-10T00:00:00Z"
    out = render(items, [S("병용", [items[0]["evidence_id"]])])
    assert out.detail[0]["source_kind"] == "FILE_LOOKUP" and out.detail[0]["queried_at"] == "2026-11-10T00:00:00Z"
    assert out.citations[0]["source_kind"] == "FILE_LOOKUP"


def test_render_never_uses_llm_sentence_text(items):
    marker = "LLM_SUMMARY_마커문장"
    out = render(items, [S(marker, ["contra_pair:111111ATB:222222ATB"])])
    assert marker not in repr(out) and "LLM_SUMMARY" not in repr(out)


def test_render_unresolved_quote_warns_and_is_dropped(items):
    eid = "contra_pair:111111ATB:222222ATB"
    out = render(items, [S("병용", [eid], cites=[Citation(evidence_id=eid, start=0, end=999)])])
    assert out.citations[0]["quotes"] == [] and out.warnings[-1]["code"] == "QUOTE_NOT_RESOLVED"


def test_render_empty_items():
    out = render([], [])
    assert out.detail == out.citations == out.badges == []


def test_end_to_end_filter_then_render(items):
    d = AnswerDraft(sentences=[S("지어낸 문장", ["fake"]), S("임부금기예요.", ["pregnancy:333333ATB"])])
    f = filter_sentences(d, items)
    out = render(items, f.kept)
    assert [c["evidence_id"] for c in out.citations] == ["pregnancy:333333ATB"]
