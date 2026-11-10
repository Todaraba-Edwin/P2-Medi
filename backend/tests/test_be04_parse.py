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
