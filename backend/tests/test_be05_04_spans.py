"""BE-05-04 C 허가 상세 표 rowspan·colspan 전개 시험. 합성 표와 로컬 스냅샷(있을 때만)의 실제 깨진 사례. 원격·API 호출 없음."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_corpus_l3 as L3  # noqa: E402


def td(*ps: str, rs: int | str | None = None, cs: int | str | None = None) -> str:
    attrs = (f' rowspan="{rs}"' if rs is not None else "") + (f' colspan="{cs}"' if cs is not None else "")
    return f"<td{attrs}>" + "".join(f"<p>{p}</p>" for p in ps) + "</td>"


def tbl(*rows: str) -> str:
    return "<tbody>" + "".join(f"<tr>{r}</tr>" for r in rows) + "</tbody>"


# 리플록신정 사례를 줄인 합성 표: 단위용량 칸이 rowspan=3
RIPLOX = tbl(
    td("적응증") + td("단위용량 및 투여간격") + td("투여기간"),
    td("복잡성 피부 감염") + td("750mg 24시간") + td("10～14일"),
    td("지역사회감염 폐렴") + td("500mg 24시간", rs=3) + td("7일"),
    td("만성기관지염의 급성 세균성 악화") + td("7일"),
    td("급성 부비동염") + td("10～14일"),
)


# ------------------------------------------------------------------ 격자 전개

def test_expand_rowspan_fills_every_covered_row():
    ex = L3.expand_table_spans(RIPLOX)
    assert ex.width == 3 and len(ex.cells) == 5
    assert [ex.cells[r][1] for r in (2, 3, 4)] == [["500mg 24시간"]] * 3
    assert ex.top[2][1] and not ex.top[3][1] and not ex.top[4][1]  # 시작 행만 top
    assert all(ex.padded(r) == 0 for r in range(5))


def test_expand_colspan_and_mixed_spans():
    ex = L3.expand_table_spans(tbl(td("A", rs=2) + td("B", cs=2), td("b1") + td("b2"), td("x") + td("y") + td("z")))
    assert ex.cells[0] == [["A"], ["B"], ["B"]] and ex.cells[1] == [["A"], ["b1"], ["b2"]]
    assert ex.origin[0][1] == ex.origin[0][2] and ex.origin[1][0] == ex.origin[0][0]


@pytest.mark.parametrize(("rs", "cs", "rows", "width"), [
    ("abc", "x", 2, 2),   # 숫자가 아니면 1
    ("99", None, 2, 3),   # 표 끝을 넘는 rowspan은 자른다(행이 늘지 않음, 아래 행 값은 오른쪽으로 밀림)
    ("0", None, 2, 3),    # 0 = 표 끝까지
    (None, "999", 2, L3.MAX_SPAN + 1),  # 큰 colspan은 MAX_SPAN에서 자른다
    (None, "0", 2, 2),    # colspan 0은 1
])
def test_expand_bad_span_values_are_bounded(rs, cs, rows, width):
    ex = L3.expand_table_spans(tbl(td("h1", rs=rs, cs=cs) + td("h2"), td("v1") + td("v2")))
    assert len(ex.cells) == rows and ex.width == width


def test_expand_rowspan_zero_reaches_end():
    ex = L3.expand_table_spans(tbl(td("H") + td("I"), td("g", rs=0) + td("1"), td("2"), td("3")))
    assert [ex.cells[r][0] for r in (1, 2, 3)] == [["g"]] * 3 and all(ex.padded(r) == 0 for r in range(4))


def test_expand_overlap_keeps_first_and_short_row_is_padded():
    # 두 번째 행 colspan이 위 rowspan 칸과 겹치는 잘못된 표: 먼저 놓인 셀을 남기고 예외를 내지 않는다
    ex = L3.expand_table_spans(tbl(td("a") + td("b", rs=2) + td("c"), td("d", cs=3)))
    assert ex.cells[1][1] == ["b"]
    ex2 = L3.expand_table_spans(tbl(td("a") + td("b") + td("c"), td("x")))
    assert ex2.padded(1) == 2


def test_expand_nested_table_text_stays_in_outer_cell_and_empty_input():
    ex = L3.expand_table_spans(tbl(td("A") + td("B"), "<td>x<table><tr><td>in1</td><td>in2</td></tr></table></td>" + td("y")))
    assert ex.width == 2 and len(ex.cells) == 2 and "in1" in " ".join(ex.cells[1][0]) and ex.cells[1][1] == ["y"]
    assert L3.table_chunks_v2("") == ([], [], True) and L3.table_chunks_v2("<tbody><tr></tr></tbody>") == ([], [], True)


# ------------------------------------------------------------------ 열·값 짝(table_chunks_v2)

def test_v2_rowspan_value_paired_on_every_row_riplox_case():
    h, rows, ok = L3.table_chunks_v2(RIPLOX)
    assert ok and h == ["적응증", "단위용량 및 투여간격", "투여기간"]
    assert "적응증=만성기관지염의 급성 세균성 악화; 단위용량 및 투여간격=500mg 24시간; 투여기간=7일" in rows
    assert all("단위용량 및 투여간격=" in r for r in rows)  # "7일"이 단위용량처럼 읽히는 행이 없다
    _, old_rows, old_ok = L3.table_chunks(RIPLOX)
    assert not old_ok and "만성기관지염의 급성 세균성 악화 | 7일" in old_rows  # 기존 규칙은 짝을 만들지 못했다


def test_v2_multirow_header_combines_names():
    h, rows, ok = L3.table_chunks_v2(tbl(td("구분", rs=2) + td("투여량", cs=2), td("성인") + td("소아"), td("1일") + td("2정") + td("1정")))
    assert ok and h == ["구분", "투여량 성인", "투여량 소아"] and rows == ["구분=1일; 투여량 성인=2정; 투여량 소아=1정"]


def test_v2_colspan_header_with_short_subheader_row():
    h, _, _ = L3.table_chunks_v2(tbl(td("구분") + td("용량", cs=2), td("") + td("성인") + td("소아"), td("가") + td("1") + td("2")))
    assert h == ["구분", "용량 성인", "용량 소아"]


def test_v2_body_colspan_value_shared_by_both_columns():
    _, rows, ok = L3.table_chunks_v2(tbl(td("청소율") + td("초회") + td("유지"), td("50～80") + td("조절 불필요", cs=2), td("20～49") + td("750mg") + td("500mg")))
    assert ok and rows[0] == "청소율=50～80; 초회 / 유지=조절 불필요"


def test_v2_subheading_title_and_footnote_rows_keep_text():
    html = tbl(
        td("표 3. 이상반응", cs=3),
        td("기관계") + td("위약") + td("이 약"),
        td("위장관 장애", cs=3),
        td("설사") + td("1%") + td("2%"),
        td("* 이상반응 빈도는 연구자가 판단한 인과관계에 근거한다", cs=3),
    )
    h, rows, ok = L3.table_chunks_v2(html)
    assert ok and h == ["기관계", "위약", "이 약"]
    assert rows[0] == "[표 제목] 표 3. 이상반응"
    assert "[위장관 장애] 기관계=설사; 위약=1%; 이 약=2%" in rows
    assert rows[-1].startswith("[표 주석] * 이상반응")


def test_v2_trailing_subheading_is_not_dropped():
    _, rows, _ = L3.table_chunks_v2(tbl(td("A") + td("B"), td("a") + td("b"), td("1. 기타 참고", cs=2)))
    assert rows[-1] == "1. 기타 참고"


def test_v2_stacked_cells_rule3():
    _, rows, ok = L3.table_chunks_v2(tbl(td("청소율") + td("용량"), td("100", "90") + td("1545", "1390")))
    assert ok and rows == ["청소율=100; 용량=1545", "청소율=90; 용량=1390"]  # 같은 개수 → 행으로 푼다
    _, rows1, ok1 = L3.table_chunks_v2(tbl(td("빈도") + td("기관계"), td("드물게", "(0.1% 미만)") + td("신경계")))
    assert ok1 and rows1 == ["빈도=드물게 / (0.1% 미만); 기관계=신경계"]  # 한 칸만 쌓였으면 풀지 않는다
    _, rows2, ok2 = L3.table_chunks_v2(tbl(td("적응증") + td("농도"), td("정맥", "성인", "소아") + td("300", "350")))
    assert not ok2 and rows2 == ["적응증=정맥 / 성인 / 소아; 농도=300 / 350"]  # 개수가 다르면 짝 확인 필요


def test_v2_dirty_html_unclosed_cells_and_rows():
    h, rows, _ = L3.table_chunks_v2("<tbody><tr><td>A<td>B</tr><tr><td>1<td>2")
    assert h == ["A", "B"] and rows == ["A=1; B=2"]


def test_v2_output_is_grouped_with_header_and_cap():
    html = tbl(td("연령") + td("용량"), td("성인") + td("x" * 2500, rs=3), td("청소년"), td("소아"))
    h, rows, ok = L3.table_chunks_v2(html)
    groups = L3.group_rows(h, rows, 2900, ok)
    assert all(g.startswith("표 열: 연령 | 용량") and len(g) <= 2900 for g in groups)


# ------------------------------------------------------------------ 빌드 경로와 변경 목록

def _prmsn_dir(tmp_path: Path, table_html: str) -> Path:
    d = tmp_path / "prmsn"
    d.mkdir()
    ud = (f'<DOC type="UD"><SECTION><ARTICLE title="용법"><PARAGRAPH tagName="p"><![CDATA[성인 1회 1정]]></PARAGRAPH>'
          f'<PARAGRAPH tagName="table"><![CDATA[{table_html}]]></PARAGRAPH><PARAGRAPH tagName="p"><![CDATA[끝 문단]]></PARAGRAPH></ARTICLE></SECTION></DOC>')
    resp = {"ITEM_SEQ": "111", "ITEM_NAME": "테스트정", "UD_DOC_DATA": ud, "NB_DOC_DATA": "None", "EE_DOC_DATA": "None"}
    (d / "item-111.json").write_text(json.dumps({"response": [resp], "fetched_at": "2026-11-10T07:20:59Z"}, ensure_ascii=False), encoding="utf-8")
    return d


def test_build_default_keeps_old_rule_and_v2_changes_only_tables(tmp_path: Path):
    d = _prmsn_dir(tmp_path, RIPLOX)
    old = L3.build_prmsn_chunks(d)
    assert old == L3.build_prmsn_chunks(d, table_fn=L3.table_chunks)  # 기본값은 기존 규칙(기존 l3_prmsn.jsonl과 같음)
    new = L3.build_prmsn_chunks(d, table_fn=L3.table_chunks_v2)
    assert any("짝은 확인 필요" in c["text"] for c in old) and not any("짝은 확인 필요" in c["text"] for c in new)
    assert [c["text"] for c in old if c["chunk_kind"] == "l3_prmsn_para"] == [c["text"] for c in new if c["chunk_kind"] == "l3_prmsn_para"]
    ch = L3.change_list(old, new)
    assert ch["replaced"] and all(x["locator"].startswith("허가상세 item_seq 111") for x in ch["replaced"])
    assert ch["unchanged"] >= 1  # 표 앞 문단 청크
    assert new == L3.build_prmsn_chunks(d, table_fn=L3.table_chunks_v2)  # 결정적


def test_change_list_pairs_by_locator():
    a = [{"chunk_id": "o1", "locator": "L1"}, {"chunk_id": "same", "locator": "L2"}, {"chunk_id": "o3", "locator": "L3"}]
    b = [{"chunk_id": "n1", "locator": "L1"}, {"chunk_id": "same", "locator": "L2"}, {"chunk_id": "n4", "locator": "L4"}]
    ch = L3.change_list(a, b)
    assert ch["replaced"] == [{"locator": "L1", "old_chunk_id": "o1", "new_chunk_id": "n1"}]
    assert ch["removed"] == [{"locator": "L3", "old_chunk_id": "o3"}] and ch["added"] == [{"locator": "L4", "new_chunk_id": "n4"}]
    assert ch["unchanged"] == 1


def test_audit_table_counts_spanned_cells():
    checked, ok, bad = L3.audit_table(RIPLOX)
    assert checked == ok and not bad and checked >= 8


# ------------------------------------------------------------------ 실제 스냅샷(로컬 전용 data/, 없으면 건너뜀)

SNAP_ITEM = L3.PRMSN_DIR / "item-202002669.json"  # 리플록신정500밀리그램


@pytest.mark.skipif(not SNAP_ITEM.exists(), reason="로컬 허가 상세 스냅샷 없음")
def test_real_riplox_snapshot_7days_row_has_unit_dose():
    tables = [t for t in L3.iter_prmsn_tables(SNAP_ITEM.parent) if t[0] == "202002669" and t[2] == "UD"]
    rows = [r for t in tables for r in L3.table_chunks_v2(t[4])[1]]
    assert "적응증=만성기관지염의 급성 세균성 악화; 단위용량 및 투여간격=500mg 24시간; 투여기간=7일" in rows


@pytest.mark.skipif(not L3.PRMSN_DIR.exists(), reason="로컬 허가 상세 스냅샷 없음")
def test_real_snapshot_no_paragraph_lost_and_grid_rectangular():
    lost = []
    for seq, _, _, _, html in L3.iter_prmsn_tables():
        h, rows, _ = L3.table_chunks_v2(html)
        blob = " ".join(h) + " " + " ".join(rows)
        p = L3._SpanTableParser()
        p.feed(html)
        p.close()
        lost += [(seq, x) for r in p.rows for c in r for x in c.texts if x not in blob]
        ex = L3.expand_table_spans(html)
        assert all(ex.padded(r) == 0 for r in range(len(ex.cells)) if any(ex.cells[r])), seq
    assert lost == []
