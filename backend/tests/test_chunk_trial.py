"""BE-05-01 청킹 단위 시험. 호출 0: 가짜 임베딩 함수만 쓰고 실제 데이터 파일은 읽지 않는다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import chunk_trial as C  # noqa: E402
import embed_compare as E  # noqa: E402

TABLE = (
    "<tbody><tr><td><p>크레아티닌청소율</p></td><td><p>용량</p></td></tr>"
    "<tr><td><p>100</p><p>90</p></td><td><p>1545</p><p>1390</p></td></tr></tbody>"
)


def _prmsn_parent() -> C.Parent:
    paras = [("p", "성인은 1일 1회 복용한다. 증상에 따라 증감한다."), ("table", TABLE)]
    text = "\n".join(t if k == "p" else C.table_naive(t) for k, t in paras)
    return C.Parent("prmsn:1:UD:00", "1", text, {"name": "테스트정(가나다)", "doc": "UD", "title": "", "paras": paras, "item_seq": "1"})


def _bup(no: str, ing: str, ages: list[str], forms: list[str]) -> C.Parent:
    return C.Parent(f"bupyo2:{no}", f"bupyo2:{no}", f"{ing}", {"no": no, "ing": ing, "ages": ages, "forms": forms})


def test_chunking_is_deterministic_and_ids_stable():
    p = _prmsn_parent()
    for cand in C.CANDIDATES["prmsn"]:
        a = C.chunk_prmsn([p], cand)
        b = C.chunk_prmsn([p], cand)
        assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
        assert len({c.chunk_id for c in a}) == len(a)  # 같은 상위 단위 안에서 중복 없음
        assert all(c.parent_id == p.pid and c.chunk_id.startswith(p.pid + "#") for c in a)


def test_table_naive_loses_pairing_but_struct_keeps_column_names():
    naive = C.table_naive(TABLE)
    assert naive == "크레아티닌청소율 용량 100 90 1545 1390"  # 열 이름과 값의 짝이 사라진다
    header, rows, unstacked = C.table_rows_struct(TABLE)
    assert header == ["크레아티닌청소율", "용량"] and unstacked
    assert rows == ["크레아티닌청소율=100; 용량=1545", "크레아티닌청소율=90; 용량=1390"]


def test_table_row_chunks_carry_column_names():
    chunks = C.chunk_prmsn([_prmsn_parent()], "para_hdr")
    tab = [c for c in chunks if "표 열:" in c.text]
    assert tab and all("크레아티닌청소율" in c.text and "용량=1545" in c.text or "용량=1390" in c.text for c in tab)
    assert all(c.text.startswith("[테스트정(가나다)") for c in chunks)  # 제품명 머리말


def test_bupyo2_row_chunks_have_header_names_and_aligned_pairs():
    p = _bup("9", "atropine", ["12세 미만", "4세 미만"], ["점안제(1%)", "점안제(0.125%)"])
    plain = C.chunk_bupyo2([p], "row_plain")[0].text
    hdr = C.chunk_bupyo2([p], "row_hdr")[0].text
    ctx = C.chunk_bupyo2([p], "row_ctx")[0].text
    assert "연령기준" not in plain
    assert "연령기준" in hdr and "해당 제형" in hdr and "유효성분: atropine" in hdr
    assert "연령기준 4세 미만, 해당 제형 점안제(0.125%)" in ctx and C.BUPYO2_TITLE in ctx


def test_l2_detail_phrase_chunk_covers_all_its_ingredients():
    mk = lambda code, name: C.Parent(f"l2d:preg:{code}", f"l2d:preg:{code}", "x", {"kind": "preg", "code": code, "name": name, "items": [("임부금기 2등급", "임부에 대한 안전성 미확립.")]})  # noqa: E731
    ps = [mk("A1", "acarbose"), mk("B2", "bosentan")]
    ph = C.chunk_l2_detail(ps, "phrase")
    assert len(ph) == 1 and set(ph[0].covers) == {"l2d:preg:A1", "l2d:preg:B2"}
    assert "acarbose" not in ph[0].text  # 성분 이름이 본문에 없다 → 이름 질의로는 찾기 어렵다(시험의 요점)
    ing = C.chunk_l2_detail(ps, "ingredient")
    assert len(ing) == 2 and ing[0].text.startswith("acarbose")


def test_sentence_split_and_none_fields():
    assert C.split_sentences("이 약을 먹습니다. 어린이는 안 됩니다.\n\n보관하십시오.") == ["이 약을 먹습니다.", "어린이는 안 됩니다.", "보관하십시오."]
    assert C.clean_field("None") == "" and C.clean_field(None) == "" and C.clean_field(" a ") == "a"


def test_iter_json_array_streams_objects_across_blocks(tmp_path):
    objs = [{"id": i, "t": "한글" * 5} for i in range(50)]
    f = tmp_path / "a.json"
    f.write_text(json.dumps(objs, ensure_ascii=False, indent=1), encoding="utf-8")
    assert list(C.iter_json_array(f, block=64)) == objs


def _eyak_parents() -> list[C.Parent]:
    out = []
    for i in range(12):
        seq = f"{100 + i}"
        for f, label in (("efcy", "효능"), ("atpn", "주의사항")):
            text = f"이 약은 증상{i}에 사용합니다. 임신 중에는 의사와 상의하십시오." if f == "atpn" else f"이 약은 증상{i}에 사용합니다."
            out.append(C.Parent(f"eyak:{seq}:{f}", seq, text, {"name": f"약{i}정", "field": f, "label": label, "item_seq": seq}))
    return out


def test_synthetic_queries_are_seeded_and_gold_is_structural():
    ps = _eyak_parents()
    q1 = C.queries_eyak(ps[:10], ps)
    q2 = C.queries_eyak(ps[:10], ps)
    assert q1 == q2 and q1
    pids = {p.pid for p in ps}
    for q in q1:
        assert q["gold"] and set(q["gold"]) <= pids  # 정답은 코퍼스 안의 상위 단위
        assert q["style"] in {"kw", "struct", "daily"} and q["id"].startswith("eyak-")
        if q["style"] == "kw":  # 키워드 질의의 정답은 모든 단어를 포함하는 상위 단위
            for g in q["gold"]:
                text = next(p.text for p in ps if p.pid == g)
                assert all(w in text for w in q["query"].split())


def test_sample_corpus_is_seeded_by_group():
    ps = _eyak_parents()
    s1, d1 = C.sample_corpus("eyak", ps, 4, 3)
    s2, d2 = C.sample_corpus("eyak", ps, 4, 3)
    assert [p.pid for p in s1] == [p.pid for p in s2] and len({p.group for p in s1}) == 4 and len({p.group for p in d1}) == 3
    assert not {p.group for p in s1} & {p.group for p in d1}


def test_hit_uses_covers_and_wilson_small_n_flag():
    ch = [C.Chunk("a", "s", "p1", "c1", (), ("g1", "g2")), C.Chunk("b", "s", "p2", "c2")]
    assert C.hit_at([1, 0], ch, {"g2"}, 1) is False and C.hit_at([1, 0], ch, {"g2"}, 2) is True
    assert C.hit_at([1], ch, {"p2"}, 1)
    assert "n≤8" in C.cell_text({"n": 8, "top1": 4, "top5": 4, "top10": 4}, 1)
    assert "n≤8" not in C.cell_text({"n": 30, "top1": 4, "top5": 4, "top10": 4}, 1)


def test_bm25_ranks_the_chunk_with_matching_text():
    ch = [C.Chunk("타이레놀 임부 주의", "s", "p0", "c0"), C.Chunk("게보린 소아 투여", "s", "p1", "c1")]
    bm = C.bm25_index(ch)
    assert C.bm25_rank(bm, "게보린 소아")[0] == 1


def test_run_stops_before_calling_when_estimate_exceeds_cap(tmp_path, monkeypatch, capsys):
    """상한 중단: plan.json 어림이 상한을 넘으면 키 조회·호출 없이 코드 3으로 끝난다."""
    monkeypatch.setattr(C, "PLAN_JSON", tmp_path / "plan.json")
    monkeypatch.setattr(C, "_load_all", lambda: {s: [] for s in C.SOURCES})
    monkeypatch.setattr(C, "build_all", lambda loaded, scale=1.0: C.Built({}, {}, {s: {c: [C.Chunk("가" * 3000, s, "p", f"c{c}")] for c in C.CANDIDATES[s]} for s in C.SOURCES}, {q: [] for q in C.QUERY_SETS}))
    texts = C.unique_embed_texts(C.build_all({}, 1.0))
    import hashlib

    (tmp_path / "plan.json").write_text(json.dumps({"scale": 1.0, "fingerprint": hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]}), encoding="utf-8")
    monkeypatch.setattr(E, "resolve_key", lambda: pytest.fail("상한 초과면 키를 읽기 전에 멈춰야 한다"))
    import argparse

    assert C.cmd_run(argparse.Namespace(max_usd=1e-9)) == 3
    assert "넘는다" in capsys.readouterr().out


def test_fit_scale_shrinks_until_estimate_fits(monkeypatch):
    calls = []

    def fake_build(loaded, scale=1.0):
        calls.append(scale)
        return C.Built({}, {}, {s: {c: [C.Chunk(f"가{i}" * 1500, s, "p", f"c{c}{i}") for i in range(int(200 * scale))] for c in C.CANDIDATES[s]} for s in C.SOURCES}, {q: [] for q in C.QUERY_SETS})

    monkeypatch.setattr(C, "build_all", fake_build)
    scale, _b, p = C.fit_scale({}, 0.001)
    assert scale < 1.0 and p["est_usd"] <= 0.001 * C.FIT_FRACTION or scale <= 0.1
    assert calls[0] == 1.0 and calls == sorted(calls, reverse=True)


def test_storage_estimate_formula():
    st = {"n": 1000, "text_bytes": 100_000}
    m = C.storage_mb(st)
    assert m["vec"] == pytest.approx(1000 * 6144 / 1e6)
    assert m["hnsw"] == pytest.approx(m["vec"] * C.HNSW_FACTOR)
    assert m["total"] == pytest.approx(m["vec"] + m["hnsw"] + m["text"])
