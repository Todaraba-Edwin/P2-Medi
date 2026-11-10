"""BE-05 L3·L1 청크 빌더 시험. 합성 소표본만 쓰고 원격·API 호출은 없다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_corpus_l2 as L2  # noqa: E402
import build_corpus_l3 as L3  # noqa: E402
import load_corpus as LC  # noqa: E402

CODES = {"111": (["AAA000AAA"], "edi_code:product")}


@pytest.fixture
def eyak_dir(tmp_path: Path) -> Path:
    d = tmp_path / "eyak"
    d.mkdir()
    items = [
        {"item_seq": "111", "item_name": "테스트정", "efcy": "두통에 사용합니다.\n", "use_method": "1회 1정", "atpn_warn": "None",
         "atpn": "임부는 복용하지 마십시오.", "intrc": "None", "se": "None", "deposit_method": "실온 보관"},
        {"item_seq": "222", "item_name": "긴설명정", "efcy": "가나다라. " * 700, "atpn": "None"},
    ]
    (d / "page-1.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return d


def test_eyak_section_chunks_header_codes_and_cap(eyak_dir: Path):
    cs = L3.build_eyak_chunks(eyak_dir, CODES, "2026-11-10")
    ids = {c["chunk_id"] for c in cs}
    assert len(ids) == len(cs) and cs == L3.build_eyak_chunks(eyak_dir, CODES, "2026-11-10")  # 결정적
    c = next(c for c in cs if c["item_name"] == "테스트정" and c["section"] == "효능")
    assert c["text"].startswith("[테스트정 · 효능] 두통에 사용합니다.") and c["base_date"] == "2026-11-10"
    assert c["ingr_codes"] == ["AAA000AAA"] and c["code_status"] == "edi_code:product" and c["item_seq"] == "111"
    assert {c["section"] for c in cs if c["item_seq"] == "111"} == {"효능", "사용법", "주의사항", "보관법"}  # None 항목은 청크 없음
    long = [c for c in cs if c["item_seq"] == "222"]
    assert len(long) >= 2 and all(len(c["text"]) <= L3.EMB_CHAR_CAP for c in long)  # 3,000자 초과 없음
    assert long[0]["ingr_codes"] == [] and long[0]["code_status"] == "none"  # 사전 연결 없음


def test_label_filter_selected(eyak_dir: Path):
    cs = L3.build_eyak_chunks(eyak_dir, CODES)
    sel = [c for c in cs if L3.is_selected(c)]
    assert "보관법" not in {c["section"] for c in sel} and "효능" in {c["section"] for c in sel}
    assert L3.prmsn_selected("UD", "") and L3.prmsn_selected("NB", "6. 상호작용") and not L3.prmsn_selected("NB", "12. 기타")
    assert not L3.prmsn_selected("EE", "효능효과")


# ------------------------------------------------------------------ 허가 상세 표

def tbl(*rows: str) -> str:
    return "<tbody>" + "".join(f"<tr>{r}</tr>" for r in rows) + "</tbody>"


def td(*ps: str) -> str:
    return "<td>" + "".join(f"<p>{p}</p>" for p in ps) + "</td>"


def test_table_stacked_cells_unstack_when_counts_equal():
    h, rows, ok = L3.table_chunks(tbl(td("크레아티닌청소율") + td("용량"), td("100", "90") + td("1545", "1390")))
    assert ok and rows == ["크레아티닌청소율=100; 용량=1545", "크레아티닌청소율=90; 용량=1390"]


def test_table_stacked_cells_unequal_not_split():
    _, rows, ok = L3.table_chunks(tbl(td("A") + td("B"), td("1", "2", "3") + td("x", "y")))
    assert ok and rows == ["A=1 / 2 / 3; B=x / y"]  # 풀지 않고 칸 안에 보존(짝이 틀어지지 않는다)


def test_table_empty_header_combined_and_subheading_prefix():
    h, rows, ok = L3.table_chunks(tbl(td("적응증") + td(""), td("") + td("용량"), td("관절조영") + td("5 mL")))
    assert h == ["적응증", "용량"] and rows == ["적응증=관절조영; 용량=5 mL"]
    _, rows2, _ = L3.table_chunks(tbl(td("적응증") + td("용량"), td("1. 동맥투여") + td(""), td("뇌") + td("5 mL"), td("2. 정맥") + td(""), td("팔") + td("3 mL")))
    assert rows2 == ["[1. 동맥투여] 적응증=뇌; 용량=5 mL", "[2. 정맥] 적응증=팔; 용량=3 mL"]  # 하위 제목은 행이 아니라 머리말


def test_table_ragged_marked_unpaired():
    h, rows, ok = L3.table_chunks(tbl(td("A") + td("B") + td("C"), td("x") + td("y"), td("z")))
    assert not ok and rows == ["x | y", "z"]
    out = L3.group_rows(h, rows, 3000, ok)
    assert "짝은 확인 필요" in out[0]


def test_group_rows_repeats_header_and_respects_cap():
    header = ["열1", "열2"]
    rows = [f"열1={i}; 열2={'가' * 400}" for i in range(20)]
    groups = L3.group_rows(header, rows, 3000)
    assert len(groups) > 1 and all(g.startswith("표 열: 열1 | 열2\n") and len(g) <= 3000 for g in groups)
    huge = L3.group_rows(header, ["열1=" + "나" * 9000], 3000)
    assert len(huge) >= 3 and all(len(g) <= 3000 for g in huge)


def _prmsn_dir(tmp_path: Path) -> Path:
    d = tmp_path / "prmsn"
    d.mkdir()
    big_table = tbl(td("연령") + td("용량"), *[td(f"{i}세") + td("1정") for i in range(14)])
    nb = (f'<DOC type="NB"><SECTION><ARTICLE title="6. 상호작용"><PARAGRAPH tagName="p"><![CDATA[{"가나다라 " * 40}]]></PARAGRAPH>'
          f'<PARAGRAPH tagName="table"><![CDATA[{big_table}]]></PARAGRAPH></ARTICLE><ARTICLE title="12. 기타"><PARAGRAPH tagName="p"><![CDATA[기타 내용]]></PARAGRAPH></ARTICLE></SECTION></DOC>')
    ud = '<DOC type="UD"><SECTION><ARTICLE title=""><PARAGRAPH tagName="p"><![CDATA[성인 1회 1정]]></PARAGRAPH></ARTICLE></SECTION></DOC>'
    resp = {"ITEM_SEQ": "111", "ITEM_NAME": "테스트정", "NB_DOC_DATA": nb, "UD_DOC_DATA": ud, "EE_DOC_DATA": "None"}
    (d / "item-111.json").write_text(json.dumps({"response": [resp], "fetched_at": "2026-11-10T07:20:59Z"}, ensure_ascii=False), encoding="utf-8")
    return d


def test_prmsn_chunks_headers_parent_codes_and_cap(tmp_path: Path):
    cs = L3.build_prmsn_chunks(_prmsn_dir(tmp_path), CODES)
    assert all(len(c["text"]) <= L3.EMB_CHAR_CAP for c in cs) and all(c["base_date"] == "2026-11-10" and c["ingr_codes"] == ["AAA000AAA"] for c in cs)
    paras = [c for c in cs if c["chunk_kind"] == "l3_prmsn_para" and "상호작용" in c["text"]]
    assert paras and paras[0]["text"].startswith("[테스트정 · 사용상의주의사항 · 6. 상호작용] 가나다라")
    tables = [c for c in cs if c["chunk_kind"] == "l3_prmsn_table"]
    assert len(tables) == 3 and all("표 열: 연령 | 용량" in c["text"] for c in tables)  # 14행 → 6+6+2, 묶음마다 열 이름 반복
    assert tables[0]["parent_id"] is None and all(t["parent_id"] == tables[0]["chunk_id"] for t in tables[1:])
    ud = next(c for c in cs if c["section"].startswith("UD"))
    assert ud["text"].startswith("[테스트정 · 용법용량 · 본문]") and L3.is_selected(ud)
    assert sum(L3.is_selected(c) for c in cs if c["section"].startswith("NB 12.")) == 0
    assert cs == L3.build_prmsn_chunks(tmp_path / "prmsn", CODES)  # 결정적


# ------------------------------------------------------------------ L1 고시

NOTICE = """# 고시

### (1) 제1조(목적)

이 규정은 「약사법」 제23조의2제1항에 따라 지정을 목적으로 한다.

### (3) 제3조(정의)

용어의 뜻은 다음과 같다.

1. "병용금기성분"이란 함께 사용하지 않아야 하는 조합을 말한다.
2. "임부금기성분"이란 다음 각 목의 구분에 따른 성분을 말한다.
   - 가. 1등급: 사용금지
   - 나. 2등급: 예외 있음

### (4) 제4조(병용금기성분)

병용금기성분은 별표 1과 같다.

### (5) 제5조(특정연령대금기성분)

특정연령대금기성분은 별표 2와 같으며 제3조에 따른다.
"""

BUP1 = """---
table: 별표 1 (9~44쪽)
---

| 연번 | 유효성분 1 | 유효성분 2 | 비고 |
|---|---|---|---|
| 1 | acemetacin | diflunisal |  |
| 2 | x | <삭제> |  |
| 3 | a | b | 비고 있음 |
"""


@pytest.fixture
def notice(tmp_path: Path):
    n = tmp_path / "n.md"
    n.write_text(NOTICE, encoding="utf-8")
    b1 = tmp_path / "b1.md"
    b1.write_text(BUP1, encoding="utf-8")
    cs, info = L3.build_notice_chunks(n, b1, tmp_path / "missing3.md", bup2_table_id="l1t-fake")
    return cs, info


def test_notice_hierarchy_locators_and_notice_no(notice):
    cs, info = notice
    by_loc = {c["locator"]: c for c in cs}
    art3, ho2, mok = by_loc["제3조"], by_loc["제3조 제2호"], by_loc["제3조 제2호 가목"]
    assert ho2["parent_id"] == art3["chunk_id"] and mok["parent_id"] == ho2["chunk_id"]
    assert mok["text"].startswith("[제3조(정의) 제2호] 가. 1등급") and art3["text"].startswith("제3조(정의) 용어")
    assert all(c["notice_no"] == "20260052" and c["base_date"] == "2026-07-21" and c["layer"] == "L1" for c in cs)
    assert info["skipped"] and "별표 3" in info["skipped"][0]  # 변환본이 없으면 건너뛰고 보고


def test_notice_refs_connection(notice):
    cs, info = notice
    by_id = {c["chunk_id"]: c for c in cs}
    by_loc = {c["locator"]: c for c in cs}
    # 연결 테스트 1: 제4조의 "별표 1" → 별표 1 표 청크, 2: 제4조의 용어 → 제3조 제1호
    refs4 = [by_id[r]["locator"] for r in by_loc["제4조"]["refs"]]
    assert "별표 1" in refs4 and "제3조 제1호" in refs4
    # 3: 제5조의 "별표 2"(L2 빌더의 표 청크 id)와 "제3조" 참조
    assert by_loc["제5조"]["refs"][0] == "l1t-fake" and by_loc["제3조"]["chunk_id"] in by_loc["제5조"]["refs"]
    # 4: 외부 법령 조문은 연결하지 않고 미해결로 기록
    assert by_loc["제1조"]["refs"] == [] and any("제23조의2" in u for u in info["unresolved"])
    ids = {c["chunk_id"] for c in cs} | {"l1t-fake"}
    assert all(r in ids for c in cs for r in c["refs"])


def test_bupyo_rows_exclude_deleted_and_have_headers(notice):
    cs, _ = notice
    rows = [c for c in cs if c["chunk_kind"] == "l1_bupyo1_row"]
    table = next(c for c in cs if c["chunk_kind"] == "l1_bupyo1_table")
    assert len(rows) == 2 and all(r["parent_id"] == table["chunk_id"] for r in rows)  # <삭제> 제외
    assert "연번: 3; 유효성분 1: a; 유효성분 2: b; 비고: 비고 있음" in rows[1]["text"]
    art4 = next(c for c in cs if c["locator"] == "제4조")
    assert table["parent_id"] == art4["chunk_id"]  # 별표 1 표 청크의 상위는 제4조


# ------------------------------------------------------------------ 적재 확장

def test_sqlite_load_with_l3_extra_fields_idempotent(eyak_dir: Path, tmp_path: Path):
    l3 = L3.build_eyak_chunks(eyak_dir, CODES)
    l2_like = [{**{f: ("" if f not in ("refs", "ingr_codes", "ingr_names") else []) for f in L2.FIELDS}, "chunk_id": "x1", "chunk_kind": "l2_combo", "layer": "L2"}]
    db = tmp_path / "a.db"
    first = LC.load_sqlite(l3 + l2_like, db)
    again = LC.load_sqlite(l3 + l2_like, db)
    assert first["inserted"] == len(l3) + 1 and again["inserted"] == 0
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT item_seq, code_status FROM corpus_chunks WHERE chunk_id='x1'").fetchone() == ("", "")  # L2 행은 빈 값
        assert conn.execute("SELECT COUNT(*) FROM corpus_chunks WHERE item_seq='111'").fetchone()[0] == 4
    finally:
        conn.close()


def test_sql_template_has_l3_columns():
    sql = LC.render_sql(512)
    assert all(f in sql for f in L2.EXTRA_FIELDS)


def test_embed_plan_has_batches(eyak_dir: Path):
    plan = LC.embed_plan(L3.build_eyak_chunks(eyak_dir, CODES), 1536)
    assert plan["executed"] is False and plan["batches"] >= 1 and plan["approx_tokens"] > 0
