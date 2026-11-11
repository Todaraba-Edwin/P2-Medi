"""BE-16 KIDS 노인주의약물 CSV: 파일명·기준일, 정규화(kind 분리·행 키), 판정 경로 불변, L2 청크, 최신본 점검."""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_corpus_l2 as b  # noqa: E402
import check_doc_freshness as fresh  # noqa: E402

from app.db import loaders  # noqa: E402
from app.db import source_files as sf  # noqa: E402
from app.db.doc_meta import DOC_META, chunk_meta  # noqa: E402
from app.tools import lookup  # noqa: E402

ROWS = [
    {"성분코드": "172848BIJ", "성분명": "ibuprofen", "제품코드": "1", "제품명": "글로펜주", "업소명": "A", "급여구분": "급여"},
    {"성분코드": "172848BIJ", "성분명": "ibuprofen", "제품코드": "2", "제품명": "부펜솔주", "업소명": "B", "급여구분": "급여"},
    {"성분코드": "172848BIJ", "성분명": "ibuprofen", "제품코드": "3", "제품명": "이부프리믹스", "업소명": "C", "급여구분": "급여"},
    {"성분코드": "172848BIJ", "성분명": "ibuprofen", "제품코드": "4", "제품명": "넷째주", "업소명": "D", "급여구분": "급여"},
    {"성분코드": "100901ACH", "성분명": "aceclofenac", "제품코드": "5", "제품명": "에이서캡슐", "업소명": "E", "급여구분": "급여"},
    {"성분코드": "", "성분명": "빈코드", "제품코드": "6", "제품명": "x", "업소명": "F", "급여구분": "급여"},
]


def test_file_name_and_as_of() -> None:
    assert sf.ELDERLY_KIDS_CSV_NAME == "한국의약품안전관리원_노인주의약물_20261001.csv"
    assert loaders.AS_OF_ELDERLY_KIDS == "2026-10-01"
    assert DOC_META[sf.ELDERLY_KIDS_CSV_NAME].modified_date == "2026-10-01"
    # 다른 파일의 기준일은 그대로
    assert (loaders.AS_OF_KIDS, loaders.AS_OF_COMBO, loaders.AS_OF_LACTATION) == ("2026-07-21", "2026-07-31", "2025-11-27")
    assert loaders.EXTENSION_SOURCES[sf.ELDERLY_KIDS_CSV_NAME][0:2] == ("caution", loaders.normalize_elderly_kids)


def test_normalize_separate_kind_and_key_includes_source() -> None:
    r = loaders.normalize_elderly_kids(ROWS[0])
    assert r["kind"] == "elderly_kids" and r["source"] == "한국의약품안전관리원" and r["as_of"] == "2026-10-01"
    assert r["detail"] == "" and r["notice_no"] == ""
    assert loaders.normalize_elderly_kids(ROWS[5]) is None
    hira = loaders.normalize_elderly({"성분코드": "172848BIJ", "성분명": "ibuprofen", "공고번호": "", "공고일자": "", "약품상세정보": ""})
    assert hira["row_key"] != r["row_key"]  # 심평원 행과 키가 겹치지 않는다
    assert loaders.normalize_elderly_kids(ROWS[0])["row_key"] != loaders.normalize_elderly_kids(ROWS[1])["row_key"]


def test_check_contraindications_output_unchanged_by_kids_rows() -> None:
    """KIDS 노인주의 행을 적재해도 check_contraindications 결과(항목·상태)가 같다(이중 판정 없음)."""
    code = "172848BIJ"

    def run(with_kids: bool):
        c = sqlite3.connect(":memory:")
        loaders.apply_schema(c)
        cols = {}
        if with_kids:
            cols["k.csv"] = loaders.collect(ROWS, loaders.normalize_elderly_kids, "caution", "k.csv", loaders.AS_OF_ELDERLY_KIDS)
            loaders.load_into(c, cols)
        else:
            loaders.apply_schema(c)
        return lookup.check_contraindications(c, [code], include_cautions=True).to_dict()

    assert run(True) == run(False)
    assert {i["kind"] for i in run(True)["items"]} == {"dose", "lactation", "elderly"}


def test_elderly_chunks_are_ingredient_level_facts_only() -> None:
    chunks = b.build_elderly_chunks(ROWS)
    assert [c["ingr_codes"] for c in chunks] == [["100901ACH"], ["172848BIJ"]]  # 코드 정렬, 빈 코드 제외
    ibu = chunks[1]
    assert ibu["chunk_kind"] == "l2_elderly" and ibu["layer"] == "L2" and ibu["chunk_id"].startswith("l2e-")
    assert "한국의약품안전관리원 노인주의약물 목록에 포함된 성분" in ibu["text"]
    assert "해당 제품 4개" in ibu["text"] and "대표 제품: 글로펜주, 넷째주, 부펜솔주" in ibu["text"]  # 이름순 3개
    assert "이부프리믹스" not in ibu["text"]  # 대표 제품은 3개까지
    assert ibu["base_date"] == "2026-10-01" and ibu["license"] == b.LICENSE_KIDS
    meta = chunk_meta(sf.ELDERLY_KIDS_CSV_NAME)
    assert (ibu["year"], ibu["source_file"], ibu["effective_date"]) == (meta["year"], meta["source_file"], meta["effective_date"])
    assert list(ibu) == list(b.FIELDS)  # 기존 L2 청크 스키마와 같은 필드
    assert b.build_elderly_chunks(ROWS) == chunks  # 결정적
    for banned in ("안전하", "복용하", "금기입니다", "피해야"):
        assert banned not in ibu["text"]


def test_freshness_flags_file_saved_before_portal_modified_date(tmp_path: Path) -> None:
    for m in DOC_META.values():
        if m.modified_date:
            (tmp_path / m.source_file).write_text("x")
    fake = {sf.COMBO_JSON_NAME: date(2026, 8, 14)}
    rows = fresh.check(tmp_path, mtime_of=lambda p: fake.get(p.name, date(2026, 11, 11)))
    status = {r["file"]: r["status"] for r in rows}
    assert status[sf.COMBO_JSON_NAME] == fresh.STALE
    assert [f for f, s in status.items() if s == fresh.STALE] == [sf.COMBO_JSON_NAME]
    assert "최신본 아님" in fresh.render(rows)
    # 파일이 없으면 판정하지 않고 '파일 없음'
    assert {r["status"] for r in fresh.check(tmp_path / "none", mtime_of=lambda p: date(2026, 1, 1))} == {fresh.NO_FILE}


def test_freshness_equal_dates_are_ok(tmp_path: Path) -> None:
    (tmp_path / sf.ELDERLY_KIDS_CSV_NAME).write_text("x")
    rows = fresh.check(tmp_path, mtime_of=lambda p: date(2026, 10, 1))
    assert {r["file"]: r["status"] for r in rows}[sf.ELDERLY_KIDS_CSV_NAME] == fresh.OK


@pytest.mark.parametrize("name", [sf.ELDERLY_KIDS_CSV_NAME, sf.SAFE_GOSI_PDF_NAME, sf.SAFE_BYEOLPYO_PDF_NAME])
def test_renamed_files_are_registered_in_doc_meta(name: str) -> None:
    assert name in DOC_META
