"""AG-06 통합: AG-02 실제 도구 출력(`items[]`)을 렌더러·문장 필터·인용 검사에 먹인다(LLM·외부 호출 없음, 합성 재료)."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
from ag06_fixtures import (
    DOSE_TEXT,
    LABEL_SEQ,
    S,
    ambiguous_items,
    by_kind,
    check_items_pair,
    easy_label_items,
    identify_items,
    label_items,
    label_provider,
)

from app.agent.answer_schema import AnswerDraft, Citation
from app.agent.patterns import has_code
from app.agent.quote_check import build_text_index, resolve_citation
from app.agent.renderer import W_BAD_QUOTE, W_NO_SOURCE_KIND, render
from app.agent.sentence_filter import (
    CODE_IN_TEXT,
    DIAGNOSIS_CLAIM,
    DOSE_NUMBER,
    NO_EVIDENCE,
    PRESCRIPTION_OR_DOSE_DECISION,
    UNKNOWN_EVIDENCE,
    filter_sentences,
    known_evidence_ids,
)
from app.agent.tools.contract import check_items, known_ids
from app.agent.tools.schemas import API_FLAGS, STATUS_BY_TOOL

PAIR_ID = "contra_pair:200001ATB:300001ATB"
PREG_ID = "pregnancy:300001ATB"
HARNESS = Path(__file__).resolve().parents[3] / "P2-doc" / "PJ2-Agent-Harness.md"


@pytest.fixture(scope="module")
def checked():
    return check_items_pair(age={"value": 5, "unit": "세"})


def detail_of(res, eid):
    return next(d for d in res.detail if d["evidence_id"] == eid)


# ------------------------------------------------------------------ 1. detail·citations·badges 계약
def test_render_real_check_output_detail_citations_badges(checked):
    pair_row = by_kind(checked, "contra_pair", "FOUND")[0]["matches"][0]["row_evidence_id"]
    sents = [S("이 조합은 주의가 필요해요.", [PAIR_ID], "conclusion"),
             S("임부 금기 목록에 있어요.", [PREG_ID, pair_row])]
    res = render(checked, sents)
    assert len(res.detail) == len(checked)                       # 항목을 빠뜨리지 않는다(H31 후보)
    assert [d["status"] for d in res.detail[:2]] == ["FOUND", "FOUND"]  # FOUND 먼저
    assert {c["evidence_id"] for c in res.citations} == {PAIR_ID, PREG_ID, pair_row}
    c = next(x for x in res.citations if x["evidence_id"] == pair_row)
    assert c["row_key"] == by_kind(checked, "contra_pair", "FOUND")[0]["matches"][0]["row_key"]
    assert c["dataset_key"] == "contra_pair" and c["source_kind"] == "FILE" and c["as_of"] == "2026-07-21"
    assert [(b["kind"], b["grade"]) for b in res.badges] == [("contra_pair", None), ("pregnancy", "2")]   # FOUND만, 등급 원문 그대로
    assert all(b["status"] == "FOUND" for b in res.badges)


def test_render_never_emits_llm_text_for_real_items(checked):
    marker = "LLM이_쓴_사실문장_마커"
    res = render(checked, [S(marker, [PAIR_ID])])
    assert marker not in repr(res)


# ------------------------------------------------------------------ 2. 식별값 보존
def test_ids_and_provenance_survive_render(checked):
    res = render(checked, [])
    for it in checked:
        d = detail_of(res, it["evidence_id"])
        assert (d["kind"], d["status"], d["dataset_key"], d["source_kind"], d["publisher"], d["as_of"], d["queried_at"]) == (
            it["kind"], it["status"], it["dataset_key"], it["source_kind"], it["source"], it["as_of"], it["queried_at_utc"])
        assert [r["row_evidence_id"] for r in d["rows"]] == [m["row_evidence_id"] for m in it.get("matches") or []]
        assert [r["row_key"] for r in d["rows"]] == [m["row_key"] for m in it.get("matches") or []]


def test_all_known_ids_are_resolvable_by_filter_and_renderer(checked):
    ids = known_evidence_ids(checked)
    assert ids <= known_ids(checked)
    d = filter_sentences(AnswerDraft(sentences=[S("조회 결과예요.", [i]) for i in sorted(ids)]), checked)
    assert d.dropped_count == 0
    res = render(checked, d.kept)
    assert {c["evidence_id"] for c in res.citations} == ids


# ------------------------------------------------------------------ 3. 꼬리표·부가 필드 보존
def test_flags_notes_and_reference_only_survive(checked):
    res = render(checked, [])
    ref = detail_of(res, "pregnancy:100000004")
    assert {"CODE_NOT_LINKED", "REFERENCE_ONLY"} <= set(ref["flags"]) and ref["status"] == "UNIDENTIFIED"
    assert any("이 제품 판정 아님" in n or "제품 단위 판정 아님" in n for n in ref["notes"])     # 참고 전용 안내가 사라지지 않는다
    assert detail_of(res, "identify:100000007")["flags"] == ["CODE_NOT_LINKED"]
    assert detail_of(res, PAIR_ID)["cause_codes"] == ["200001ATB", "300001ATB"] and detail_of(res, PAIR_ID)["drugs"] == ["이부정", "와파린정"]
    assert not any(d["status"] == "NOT_LISTED" and "CODE_NOT_LINKED" in d["flags"] for d in res.detail)  # 코드 없음은 NOT_LISTED가 아니다


def test_ambiguous_name_candidates_survive():
    items = ambiguous_items()
    res = render(items, [])
    amb = next(d for d in res.detail if d["kind"] == "identify")
    assert amb["flags"] == ["AMBIGUOUS_NAME"] and amb["status"] == "UNIDENTIFIED" and len(amb["candidates"]) == 2
    assert not res.badges or all(b["kind"] != "identify" for b in res.badges)


def test_api_only_caveat_note_survives():
    from ag02_synth import ctx

    from app.agent.tools.registry import invoke
    from app.tools.dur import DurResult, DurRow
    row = DurRow(kind="usjnt", level="ingr", content="API 병용금기 합성", notification_date="2026-01-01", evidence_id="abcdef012345")
    fn = lambda a, b: DurResult(ok=True, kind="usjnt", level="ingr", rows=[row], source_name="식약처 DUR 성분정보", queried_at_utc="2026-11-10T12:00:00Z", request_hashes=["h"])  # noqa: E731
    out = invoke("check_contraindications", {"drugs": [{"name": "타이레놀정"}, {"name": "이부정"}]}, ctx(api_pair_fn=fn))
    res = render(out["items"], [])
    file_item = next(d for d in res.detail if d["source_kind"] == "FILE" and d["kind"] == "contra_pair")
    assert file_item["status"] == "NOT_LISTED" and "API_ONLY" in file_item["flags"]
    assert any("안전하다는 뜻이 아니" in n for n in file_item["notes"])
    api = next(d for d in res.detail if d["source_kind"] == "API_DIRECT")
    assert api["dataset_key"] == "dur_ingr" and api["queried_at"] == "2026-11-10T12:00:00Z" and api["status"] == "FOUND"


def test_label_fields_survive_label_source_and_missing_reason():
    res = render(label_items(), [])
    d = res.detail[0]
    assert d["label_source"] == "허가정보 상세" and d["dataset_key"] == "prmsn" and d["source_kind"] == "API_DIRECT"
    assert "EASY_TEXT_MISSING" in d["flags"] and d["rows"][0]["text"] == DOSE_TEXT and d["queried_at"]
    assert render(easy_label_items(), []).detail[0]["label_source"] == "e약은요"      # "허가사항 원문"이 붙지 않는다(PRD-11-05)
    missing = render(label_items("효능", label_provider(), seq=LABEL_SEQ.replace("8", "7")), []).detail[0]
    assert missing["status"] == "NO_EVIDENCE" and missing["missing_reason"] == "OUT_OF_SCOPE" and missing["rows"] == []
    assert W_NO_SOURCE_KIND not in {w["code"] for w in render(label_items("효능", label_provider(), seq=LABEL_SEQ.replace("8", "7")), []).warnings}


# ------------------------------------------------------------------ 4. 출처 None 항목
def test_sourceless_items_pass_renderer_without_warning(checked):
    sourceless = [i for i in checked if i["source"] is None]
    assert {i["kind"] for i in sourceless} == {"identify", "pregnancy", "age", "contra_pair"} and all(i["status"] == "UNIDENTIFIED" for i in sourceless)
    pair_nc = by_kind(checked, "contra_pair", "UNIDENTIFIED")
    assert pair_nc and all(i["flags"] == ["PAIR_NOT_CHECKED"] for i in pair_nc)
    res = render(checked, [])
    assert [w for w in res.warnings if w["code"] == W_NO_SOURCE_KIND] == []      # 조회하지 못한 항목은 출처가 없는 것이 정상
    for i in pair_nc:
        d = detail_of(res, i["evidence_id"])
        assert d["source_kind"] is None and d["publisher"] is None and d["as_of"] is None and d["rows"] == []


def test_sourceless_items_citable_without_crash_and_quote_empty(checked):
    eid = "identify:100000007"
    res = render(checked, [S("약을 찾지 못했어요.", [eid], "guidance", [Citation(evidence_id=eid, start=0, end=1)])])
    assert res.citations[0]["evidence_id"] == eid and res.citations[0]["source_kind"] is None and res.citations[0]["quotes"] == []
    assert res.warnings[-1]["code"] == W_BAD_QUOTE and res.warnings[-1]["reason"] == "OUT_OF_RANGE"   # 원문이 없는 항목은 글자를 자를 수 없다
    assert build_text_index(checked)[eid] == ""


def test_identify_items_through_renderer():
    res = render(identify_items("와파린"), [])
    d = res.detail[0]
    assert d["status"] == "FOUND" and d["matched_by"] == "ingredient_name" and d["flags"] == ["NO_PRODUCT_INFO"] and d["source_kind"] == "FILE"
    missing = render(identify_items("wvwvwv"), []).detail[0]
    assert missing["status"] == "UNIDENTIFIED" and missing["input_name"] == "wvwvwv" and missing["retry_hint"] and missing["searched"] and missing["retried"] is False
    assert not render(identify_items("wvwvwv"), []).warnings
    assert render(identify_items("와파린"), []).badges[0]["grade"] is None


# ------------------------------------------------------------------ 5. 인용 글자 일치
def test_quote_cut_from_row_and_item_text_agree(checked):
    row = by_kind(checked, "pregnancy", "FOUND")[0]["matches"][0]
    idx = build_text_index(checked)
    assert idx[row["row_evidence_id"]] == row["detail"] and idx[PREG_ID] == row["detail"]        # 행 하나면 항목 = 행
    r = resolve_citation(Citation(evidence_id=PREG_ID, start=0, end=2), idx)
    assert r.ok and r.text == row["detail"][:2]
    res = render(checked, [S("임부 안내", [PREG_ID], cites=[Citation(evidence_id=PREG_ID, start=0, end=7)])])
    assert res.citations[0]["quotes"][0]["text"] == row["detail"][:7]


def test_label_item_text_is_not_doubled():
    items = label_items()
    idx = build_text_index(items)
    assert idx[items[0]["evidence_id"]] == DOSE_TEXT == idx[items[0]["matches"][0]["row_evidence_id"]]
    assert resolve_citation(Citation(evidence_id=items[0]["evidence_id"], start=0, end=len(DOSE_TEXT) + 1), idx).reason == "OUT_OF_RANGE"


def test_quote_range_and_unknown_id_counted_not_rendered(checked):
    bad = [Citation(evidence_id=PREG_ID, start=0, end=9999), Citation(evidence_id="nope", start=0, end=2)]
    f = filter_sentences(AnswerDraft(sentences=[S("임부", [PREG_ID], cites=bad)]), checked)
    assert f.bad_quotes == 2 and f.kept
    res = render(checked, f.kept)
    assert res.citations[0]["quotes"] == [] and [w["code"] for w in res.warnings if w["code"] == W_BAD_QUOTE] == [W_BAD_QUOTE] * 2


def test_quote_of_unlinked_id_in_sentence_counted(checked):
    other = by_kind(checked, "pregnancy", "FOUND")[0]["matches"][0]["row_evidence_id"]
    f = filter_sentences(AnswerDraft(sentences=[S("임부", [PREG_ID], cites=[Citation(evidence_id=other, start=0, end=2)])]), checked)
    assert f.bad_quotes == 1     # 문장에 연결되지 않은 ID로 인용하면 글자가 맞아도 센다


# ------------------------------------------------------------------ 6. 문장 필터 맞물림
def test_filter_with_real_ids(checked):
    d = AnswerDraft(sentences=[
        S("사실인데 근거가 없어요."),
        S("지어낸 근거예요.", ["pregnancy:999999ATB"]),
        S("이 약 성분은 300001ATB 예요.", [PREG_ID]),
        S("D000003 성분이에요.", [PREG_ID]),
        S("확인해 보세요.", [], "guidance"),
        S("주의가 필요해요.", [PAIR_ID], "conclusion"),
        S("임부 금기에 있어요.", [PREG_ID]),
    ])
    f = filter_sentences(d, checked)
    assert [x.reason for x in f.dropped] == [NO_EVIDENCE, UNKNOWN_EVIDENCE, CODE_IN_TEXT, CODE_IN_TEXT]
    assert [s.claim_type for s in f.kept] == ["guidance", "conclusion", "fact"]
    assert f.events[0]["dropped"] == 4 and f.events[0]["reasons"] == {NO_EVIDENCE: 1, UNKNOWN_EVIDENCE: 1, CODE_IN_TEXT: 2}
    assert not any(has_code(s.text) for s in f.kept)


def test_filter_unknown_when_tool_returned_nothing():
    f = filter_sentences(AnswerDraft(sentences=[S("근거 없이 말해요.", [PREG_ID])]), [])
    assert f.dropped[0].reason == UNKNOWN_EVIDENCE and render([], f.kept).citations == []


def test_filter_pipeline_label_dose_in_detail_not_summary():
    items = label_items()
    eid = items[0]["evidence_id"]
    f = filter_sentences(AnswerDraft(sentences=[S("허가사항에 용법용량 안내가 있어요.", [eid], "fact", [Citation(evidence_id=eid, start=0, end=len(DOSE_TEXT))])]), items)
    res = render(items, f.kept)
    assert res.citations[0]["quotes"][0]["text"] == DOSE_TEXT                   # 용량 숫자는 근거 상세(인용)에만 있다
    assert not re.search(r"\d", f.kept[0].text) and DOSE_TEXT not in repr(f.kept)


@pytest.mark.parametrize(("text", "reason"), [
    ("하루 3회 500mg씩 드세요.", DOSE_NUMBER),
    ("이 증상은 위염으로 진단돼요.", DIAGNOSIS_CLAIM),
    ("이 약을 처방해 드릴게요.", PRESCRIPTION_OR_DOSE_DECISION),
])
def test_filter_should_drop_dose_diagnosis_prescription(text, reason, checked):
    f = filter_sentences(AnswerDraft(sentences=[S(text, [PREG_ID], "conclusion")]), checked)
    assert f.dropped_count == 1 and f.dropped[0].reason == reason


# ------------------------------------------------------------------ 7. 계약 대조
def test_renderer_input_fields_match_contract(checked):
    """렌더러가 읽는 필드는 계약 검사가 보장하는 필드와 같다: 모든 실제 항목이 `check_items`를 통과하고 렌더러 필수 키를 가진다."""
    must = {"evidence_id", "kind", "status", "flags", "dataset_key", "source_kind", "source", "as_of", "queried_at_utc"}
    for tool, items in [("check_contraindications", checked), ("check_contraindications", ambiguous_items()), ("get_label_section", label_items()),
                        ("get_label_section", easy_label_items()), ("identify_drug", identify_items("와파린")), ("identify_drug", identify_items("wvwvwv"))]:
        assert check_items(tool, items) == []
        assert all(must <= it.keys() for it in items), [m for it in items for m in must - it.keys()]
    # 계약이 요구하는 출처 3종이 없는 FOUND는 렌더러가 경고로 되돌려준다(계약 위반과 같은 기준)
    broken = copy.deepcopy(by_kind(checked, "pregnancy", "FOUND"))
    broken[0]["source_kind"] = None
    assert check_items("check_contraindications", broken) and [w["code"] for w in render(broken, []).warnings] == [W_NO_SOURCE_KIND]


def test_renderer_status_values_equal_harness_34():
    tool_union = set().union(*STATUS_BY_TOOL.values())
    assert tool_union == {"FOUND", "NOT_LISTED", "UNIDENTIFIED", "NO_EVIDENCE"}              # 하네스 3.4 상태 4종
    assert {i["status"] for i in render(check_items_pair(), []).detail} <= tool_union
    assert API_FLAGS == {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"}


@pytest.mark.skipif(not HARNESS.exists(), reason="P2-doc 없음")
def test_flags_documented_in_harness_table_match_code():
    text = HARNESS.read_text(encoding="utf-8")
    table = re.findall(r"^\| `([A-Z_]+)`", text, flags=re.M)
    assert {"FOUND", "NOT_LISTED", "UNIDENTIFIED", "NO_EVIDENCE", "NO_PRODUCT_INFO", "EASY_TEXT_MISSING", "INVALID_CODE", "PAIR_NOT_CHECKED"} <= set(table)
    produced = {f for it in check_items_pair() + ambiguous_items() + label_items() for f in it["flags"]}
    assert produced <= set(table) | {"CODE_NOT_LINKED", "REFERENCE_ONLY", "AMBIGUOUS_NAME", "SNAPSHOT_TIME"} | API_FLAGS   # 표에 없는 꼬리표는 이 넷뿐(어휘 표 등록 대기)
