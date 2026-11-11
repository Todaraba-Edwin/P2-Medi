"""문서 메타 표 시험. 원본 파일이 없으면 대조는 skip한다(`data/`는 로컬 전용)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import source_files as sf
from app.db.doc_meta import DOC_META, chunk_meta, get_meta, parse_base_date

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (sf.PREG_CSV_NAME, "2026-07-21"),
        (sf.AGE_CSV_NAME, "2026-07-21"),
        (sf.DOSE_CSV_NAME, "2026-07-21"),
        (sf.LACT_CSV_NAME, "2025-11-27"),
        (sf.COMBO_JSON_NAME, "2026-07-31"),
        ("의약품안전사용서비스(DUR)_임부금기 품목리스트 2026.6.csv", "2026-06"),
        ("의약품안전사용서비스(DUR)_노인주의(해열진통소염제) 품목리스트 2026.12.csv", "2026-12"),
        ("약사법_제2항.pdf", None),
        ("x_20261340.csv", None),  # 월이 잘못된 날짜
    ],
)
def test_parse_base_date(name: str, expected: str | None) -> None:
    assert parse_base_date(name) == expected


def test_table_shape() -> None:
    assert len(DOC_META) >= 10
    assert all(k == m.source_file for k, m in DOC_META.items())
    assert all(m.source_url is None or m.source_url.startswith("http") for m in DOC_META.values())
    assert all(m.source_url is None for m in DOC_META.values())  # 사용자가 알려 주기 전까지 지어내지 않는다


def test_base_date_matches_filename_for_file_data() -> None:
    for m in DOC_META.values():
        if m.base_date and m.source_file.endswith((".csv", ".json")):
            assert m.base_date == parse_base_date(m.source_file)
            assert m.year == int(m.base_date[:4])


def test_chunk_meta_values() -> None:
    cm = chunk_meta(sf.COMBO_JSON_NAME)
    assert cm == {"year": 2026, "source_file": sf.COMBO_JSON_NAME, "effective_date": None}
    assert get_meta(sf.GOSI_PDF_NAME).notice_no == "제2026-52호"
    with pytest.raises(KeyError):
        chunk_meta("없는 파일.csv")


def _first_text(path: Path) -> str:
    if path.suffix != ".pdf":
        return path.read_text(encoding="utf-8")
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(path) as pdf:
        return "".join((pg.extract_text() or "") for pg in pdf.pages[:2])


@pytest.mark.parametrize("meta", [m for m in DOC_META.values() if m.source_file.endswith(".pdf")], ids=lambda m: m.source_file[:30])
def test_pdf_first_page_contains_issuer_and_notice(meta) -> None:  # noqa: ANN001
    path = DATA / meta.source_file
    if not path.exists():
        pytest.skip("data/ 원본 없음(로컬 전용)")
    text = _first_text(path).replace(" ", "")
    if not text.strip():
        pytest.skip("텍스트 층 없는 PDF(미확인 칸은 None)")
    if meta.issuer:
        assert meta.issuer.replace(" ", "") in text
    if meta.notice_no and meta.doc_type == "발간물":
        assert meta.notice_no in text
    elif meta.notice_no:
        num = meta.notice_no.removeprefix("제").removesuffix("호")  # '2026-52' / '1181' / '21525'
        assert num.replace("-", "") in text.replace("-", "").replace("제", "") or num in text
