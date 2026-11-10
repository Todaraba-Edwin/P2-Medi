"""BE-04 표 파서 단위 시험: 합성 표만 쓴다(PDF·data/ 불필요)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import parse_pdf_tables as P  # noqa: E402

RAW = [
    ["연번", "유효성분", "연령기준", "해당 제형"],
    ["1", "acarbose", "18세 이하", "정제"],
    ["2", "atropine", "12세 미만", "점안제(1%)"],
    [None, None, "4세 미만", "점안제(0.125%)"],
    ["3", "Cyanocobala\nmin + Milk", "12세 이하", "캡슐제"],
]


def test_merge_continuation_and_skip_header():
    rows = P.merge_table_rows(RAW)
    assert [r.no for r in rows] == [1, 2, 3]
    assert rows[1].parts == [("12세 미만", "점안제(1%)"), ("4세 미만", "점안제(0.125%)")]


def test_header_repeated_on_next_page_not_duplicated():
    rows = P.merge_table_rows(RAW[:2])
    P.merge_table_rows(RAW[:1] + RAW[2:], rows)
    assert len(rows) == 2 and len(rows[1].parts) == 2 or len(rows) == 3


def test_join_wrapped_midword_vs_word_boundary():
    assert P.join_wrapped("Cyanocobala\nmin") == "Cyanocobalamin"
    assert P.join_wrapped("Pulvis\nSyzygii") == "Pulvis Syzygii"
    assert P.join_wrapped("Ursodeoxycholic\nacid") == "Ursodeoxycholic acid"


def test_markdown_keeps_header_and_multi_part_rows():
    md = P.to_markdown(P.merge_table_rows(RAW))
    lines = md.strip().splitlines()
    assert lines[0] == "| 연번 | 유효성분 | 연령기준 | 해당 제형 |"
    assert "12세 미만<br>4세 미만" in md and len(lines) == 2 + 3


def test_check_sequence_detects_gap():
    rows = P.merge_table_rows(RAW)
    assert P.check_sequence(rows) == []
    assert P.check_sequence(rows[:1] + rows[2:])


def test_numbered_items():
    assert P.parse_numbered_items("[별표]\n1. 타이레놀정(8정)\n2. 판피린티정(3정)") == [
        (1, "타이레놀정(8정)"),
        (2, "판피린티정(3정)"),
    ]


def test_latest_notice_picks_latest_date():
    text = "식품의약품안전처 고시 제2025- 86호(2025. 12. 23, 개정)\n식품의약품안전처 고시 제2026- 52호(2026. 7. 21, 개정)\n식품의약품안전처 고시 제2014- 2호(2014. 1. 9, 제정)"
    assert P.latest_notice(text) == ("제2026-52호", "2026-07-21")
    assert P.latest_notice("고시 없음") is None


def test_filename_date():
    assert P.filename_date("[별표] 안전상비의약품 품목(고시, 2023-12-14 20:38).pdf") == "2023-12-14"
    assert P.filename_date("개정고시 전문.pdf") is None


def test_meta_block_fields_and_no_guess():
    from datetime import UTC, datetime

    block = P.meta_block("a.pdf", "2023-12-14", 13, now=datetime(2026, 11, 10, 1, 2, 3, tzinfo=UTC))
    assert block.startswith("---\n") and block.endswith("---\n\n")
    for want in ("source_pdf: a.pdf", "source_date: 2023-12-14", "latest_distribution_confirmed: 2026-11-10", "rows: 13", "generated_at: 2026-11-10T01:02:03+00:00", "parser: parse_pdf_tables.py"):
        assert want in block


# --- 별표 1·3(4칸 표) 변환 ---
RAW1 = [
    ["연번", "유효성분 '1'", "유효성분 '2'", "비고"],
    ["1", "acemetacin", "diflunisal", ""],
    ["2", "acemetacin", "methotrexate (분류번호 : 421)", "methotrexate 1주에\n15mg 이상 투여시"],
    ["3", "Spironolactone +\nHydrochlorothiazide", "Lithium carbonate", ""],
]
RAW3 = [
    ["연번", "유효성분", "등급", "비고"],
    ["1", "Abacavir", "2등급", ""],
    ["2", "Ritodrine", "2등급 (임신기간 22주에서 37주 사이의", ""],
    [None, None, "임부의 분만억제 사용 시 제외)", None],  # 쪽 경계 이어짐 행
    ["3", "Cyanocobala\nmin", "1등급", ""],
]


def test_wide_merge_header_and_note_lines():
    rows = P.merge_wide_rows(RAW1, 4)
    assert [r.no for r in rows] == [1, 2, 3]
    assert rows[1].cells == ["acemetacin", "methotrexate (분류번호 : 421)", "methotrexate 1주에 15mg 이상 투여시"]
    assert rows[2].cells[0] == "Spironolactone + Hydrochlorothiazide"


def test_wide_merge_continuation_across_page_break():
    rows = P.merge_wide_rows(RAW3[:3], 4)
    P.merge_wide_rows([RAW3[0], RAW3[3], RAW3[4]], 4, rows)  # 다음 쪽: 헤더 반복 + 이어짐 + 새 행
    assert [r.no for r in rows] == [1, 2, 3]
    assert rows[1].cells[1] == "2등급 (임신기간 22주에서 37주 사이의 임부의 분만억제 사용 시 제외)"
    assert rows[2].cells[0] == "Cyanocobalamin"


def test_wide_markdown_and_sequence():
    rows = P.merge_wide_rows(RAW3, 4)
    md = P.wide_markdown(rows, P.BUPYO3_HEADER)
    lines = md.strip().splitlines()
    assert lines[0] == "| 연번 | 유효성분 | 등급 | 비고 |" and lines[1] == "|---|---|---|---|" and len(lines) == 2 + 3
    assert P.check_wide_sequence(rows) == []
    assert P.check_wide_sequence(rows[:1] + rows[2:])


def test_verify_wide_ignores_whitespace_and_reports_missing():
    rows = P.merge_wide_rows(RAW1, 4)
    pages = P.split_pdfkit_pages("=====PAGE 9=====\nacemetacin diflunisal\nacemetacin methotrexate(분류번호:421)\nmethotrexate 1주에15mg 이상 투여시\n")
    v = P.verify_wide(rows, pages, range(9, 10))
    assert v["n"] == 3 and v["loose"] == 2 and [n for n, _ in v["missing"]] == [3]


def test_max_leading_int_row_and_column_layouts():
    assert P.max_leading_int("연번 유효성분\n1 a b\n2 c d\n- 44 -") == 2
    assert P.max_leading_int("연번 1657 1658 1659 유효성분 '1'\nMidostaurin x") == 1659
    assert P.max_leading_int("본문만") is None


def test_bupyo13_real_pdf_if_present():
    import pytest

    if not P.GOSI_PDF.exists():
        pytest.skip("고시 PDF 없음(로컬 전용 data/)")
    rows = P.parse_wide(P.GOSI_PDF, range(51, 53))
    assert rows[0].no == 1 and rows[0].cells[0].startswith("(Micronized)")
    assert P.check_wide_sequence(rows) == []
