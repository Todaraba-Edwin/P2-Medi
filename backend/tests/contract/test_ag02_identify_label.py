"""AG-02 `identify_drug`·`get_label_section` 계약: H17·H18·H26·H29, 길이 제한, 용법용량 원문, 스냅샷·픽스처."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ag02_synth import FakeLabels, ctx, doc

from app.agent.tools import get_label_section as GL
from app.agent.tools.label_source import SNAPSHOT_ROOT, SnapshotLabelProvider, extract_doc_text
from app.agent.tools.registry import invoke

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "api" / "drug-prmsn" / "detail_children_tylenol_suspension.json"


def ident(name, **kw):
    out = invoke("identify_drug", {"name": name}, ctx(**kw))
    assert out["contract_violations"] == []
    return out


# ------------------------------------------------------------------ identify_drug
def test_product_candidate_fields():
    out = ident("타이레놀정")
    (it,) = out["items"]
    assert out["resolved"] and it["status"] == "FOUND" and it["matched_by"] == "product_name"
    assert it["item_seq"] == "100000001" and it["prescription"] == "일반" and it["form"] and it["kids_codes"] == ["100001ATB"]
    assert it["ingredients"][0]["display"] == "아세트아미노펜" and it["api_codes"] == ["D000001"]
    assert it["source_kind"] == "FILE" and it["as_of"] == "2026-11-10" and "NO_PRODUCT_INFO" not in it["flags"]


def test_ingredient_name_blanks_product_fields_h17():
    out = ident("와파린")
    (it,) = out["items"]
    assert it["matched_by"] == "ingredient_name" and it["flags"] == ["NO_PRODUCT_INFO"]
    assert it["item_seq"] is None and it["form"] is None and it["product_age_text"] is None and it["label"] is None
    assert it["label_source"] is None and it["kids_codes"] == ["300001ATB"]


def test_same_name_product_and_ingredient_prefers_product():
    out = ident("이부프로펜")
    assert out["items"][0]["matched_by"] == "product_name" and any("성분명이기도" in n for n in out["notes"])


def test_candidates_capped_at_five_and_ask():
    out = ident("약초")
    assert len(out["items"]) == 5 and out["needs_clarification"] and not out["resolved"] and out["total_candidates"] == 7


def test_mixed_input_is_not_confirmed():
    out = ident("타이레놀이랑 이부프로펜")
    assert not out["resolved"]  # 두 약을 한 번에 넣으면 확정하지 않는다(도구는 약 하나씩)


def test_not_found_gives_retry_name_hint():
    out = ident("wvwvwv")
    (it,) = out["items"]
    assert it["status"] == "UNIDENTIFIED" and it["input_name"] == "wvwvwv" and it["retry_hint"] and it["searched"] and it["retried"] is False
    assert it["source"] is None and out["needs_clarification"] is False


def test_prescription_without_easy_text_h18_with_detail():
    seq = "100000003"  # 와파린정(전문)
    lab = FakeLabels(detail_map={seq: {"item": {}, "collected_at": "2026-11-10T07:00:00Z", "source": "snapshot"}})
    (it,) = ident("와파린정", label_provider=lab)["items"]
    assert "EASY_TEXT_MISSING" in it["flags"] and it["label_source"] == "허가정보 상세" and it["missing_reason"] is None  # 원문 인용, 미확보 아님


def test_prescription_without_any_label_is_out_of_scope():
    (it,) = ident("와파린정", label_provider=FakeLabels())["items"]
    assert "EASY_TEXT_MISSING" in it["flags"] and it["missing_reason"] == "OUT_OF_SCOPE"


def test_easy_text_present_no_flag():
    lab = FakeLabels(eyak_map={"100000001": {"item": {"efcy": "x"}, "collected_at": "t", "source": "live"}})
    (it,) = ident("타이레놀정", label_provider=lab)["items"]
    assert it["flags"] == [] and it["label_source"] == "e약은요"


def test_provider_failure_is_fetch_fail_without_secret():
    out = ident("타이레놀정", label_provider=FakeLabels(fail=True))
    assert out["items"][0]["missing_reason"] == "FETCH_FAIL" and "secret-token" not in str(out)


# ------------------------------------------------------------------ get_label_section
def label(seq, section, lab, **kw):
    out = invoke("get_label_section", {"item_seq": seq, "section": section}, ctx(label_provider=lab, **kw))
    assert out["contract_violations"] == [], out["contract_violations"]
    return out["items"][0]


def test_easy_text_used_when_present():
    it = label("000000001", "효능", FakeLabels(eyak_map={"000000001": {"item": {"efcy": "열을 내려요\n"}, "collected_at": "2026-11-10T00:00:00Z", "source": "snapshot"}}))
    assert it["status"] == "FOUND" and it["label_source"] == "e약은요" and it["text"] == "열을 내려요\n" and it["easy_text"] == it["text"]
    assert it["evidence_id"] == "eyak:000000001:efcy" and it["queried_at_kind"] == "SNAPSHOT_COLLECTED" and "EASY_TEXT_MISSING" not in it["flags"]


def test_prescription_label_uses_detail_only_h18():
    d = {"item": {"EE_DOC_DATA": doc("효능효과", "파킨슨병", "보조요법")}, "collected_at": "2026-11-10T07:00:00Z", "source": "snapshot"}
    it = label("201908146", "효능", FakeLabels(detail_map={"201908146": d}))
    assert it["status"] == "FOUND" and it["label_source"] == "허가정보 상세" and "EASY_TEXT_MISSING" in it["flags"]
    assert it["text"] == "파킨슨병\n보조요법" and it["easy_text"] is None and it["missing_reason"] is None and it["dataset_key"] == "prmsn"
    assert it["matches"][0]["text"] == it["text"]  # 렌더러 인용 색인이 읽는 필드


def test_dosage_is_verbatim_from_detail():
    para = ["성인: 1회 1~2정씩 1일 3-4회 (4-6시간 마다) 필요시 복용한다.", "1일 최대 4 g을 초과하지 않는다 &amp; 주의 &#x2022; 끝"]
    d = {"item": {"UD_DOC_DATA": doc("용법용량", *para)}, "collected_at": "t", "source": "live"}
    e = {"item": {"use_method": "쉬운 용법 문장 9정"}, "collected_at": "t", "source": "live"}
    it = label("202106092", "용법용량", FakeLabels(eyak_map={"202106092": e}, detail_map={"202106092": d}))
    assert it["label_source"] == "허가정보 상세" and para[0] in it["text"] and "& 주의 • 끝" in it["text"] and "9정" not in it["text"]
    assert "EASY_TEXT_MISSING" not in it["flags"] and it["queried_at_kind"] == "FETCHED"


def test_length_limit(monkeypatch):
    monkeypatch.setattr(GL, "MAX_SECTION_CHARS", 30)
    d = {"item": {"NB_DOC_DATA": doc("주의", "가" * 100)}, "collected_at": "t", "source": "live"}
    it = label("201908146", "주의사항", FakeLabels(detail_map={"201908146": d}))
    assert len(it["text"]) == 30 and it["truncated"] and it["text_length"] == 100 and "TRUNCATED" in it["flags"]


def test_default_limit_is_applied():
    d = {"item": {"NB_DOC_DATA": doc("주의", "나" * 5000)}, "collected_at": "t", "source": "live"}
    it = label("201908146", "주의사항", FakeLabels(detail_map={"201908146": d}))
    assert len(it["text"]) == GL.MAX_SECTION_CHARS == 2000 and it["truncated"]


@pytest.mark.parametrize("lab,reason", [
    (FakeLabels(), "OUT_OF_SCOPE"),                                                                                  # 어디에도 없음(전문의약품 스냅샷 없음)
    (FakeLabels(detail_map={"201908146": {"item": {"EE_DOC_DATA": ""}, "collected_at": "t", "source": "live"}}), "ABSENT"),  # 품목은 있고 절만 비어 있음
    (FakeLabels(fail=True), "FETCH_FAIL"),
])
def test_missing_reasons(lab, reason):
    it = label("201908146", "효능", lab)
    assert it["status"] == "NO_EVIDENCE" and it["missing_reason"] == reason and it["text"] is None and it["matches"] == []
    assert "secret-token" not in str(it)


def test_no_provider_is_out_of_scope():
    out = invoke("get_label_section", {"item_seq": "201908146", "section": "효능"}, ctx())
    assert out["items"][0]["missing_reason"] == "OUT_OF_SCOPE"


def test_extract_doc_text_cdata_and_entities():
    assert extract_doc_text(doc("t", "a &lt;b&gt;", "c")) == "a <b>\nc" and extract_doc_text(None) == ""


# ------------------------------------------------------------------ 픽스처·스냅샷
class FixtureProvider:
    """`backend/tests/fixtures/api/drug-prmsn/` 스냅샷 한 건을 허가 상세로 돌려준다."""

    def eyak(self, seq):
        return None

    def prmsn_detail(self, seq):
        it = json.loads(FIX.read_text(encoding="utf-8"))["body"]["items"][0]
        return {"item": it, "collected_at": "2026-11-05T00:00:00Z", "source": "snapshot"} if it["ITEM_SEQ"] == seq else None


def test_fixture_section_and_length(monkeypatch):
    it = label("202200525", "용법용량", FixtureProvider())
    assert it["status"] == "FOUND" and "만 12세 이하의 소아" in it["text"] and it["label_source"] == "허가정보 상세"
    monkeypatch.setattr(GL, "MAX_SECTION_CHARS", 40)
    short = label("202200525", "용법용량", FixtureProvider())
    assert len(short["text"]) == 40 and short["truncated"]


needs_snap = pytest.mark.skipif(not (SNAPSHOT_ROOT / "prmsn-detail").is_dir(), reason="data/mock/api_snapshots 없음")


@needs_snap
def test_snapshot_prescription_drug_present_easy_missing():  # 이지렉트정(전문의약품): 허가 상세만 있고 e약은요 0건
    it = label("201908146", "용법용량", SnapshotLabelProvider())
    assert it["status"] == "FOUND" and "EASY_TEXT_MISSING" in it["flags"] and it["label_source"] == "허가정보 상세" and it["missing_reason"] is None
    assert "1mg" in it["text"] and it["queried_at_kind"] == "SNAPSHOT_COLLECTED"


@needs_snap
def test_snapshot_prescription_drug_absent_is_out_of_scope(tmp_path):  # 스냅샷에 없는 쪽: 같은 도구가 OUT_OF_SCOPE
    it = label("201908146", "효능", SnapshotLabelProvider(root=tmp_path))
    assert it["status"] == "NO_EVIDENCE" and it["missing_reason"] == "OUT_OF_SCOPE"


@needs_snap
def test_snapshot_otc_has_easy_text():
    it = label("202106092", "효능", SnapshotLabelProvider())
    assert it["status"] == "FOUND" and it["label_source"] == "e약은요" and "EASY_TEXT_MISSING" not in it["flags"]
