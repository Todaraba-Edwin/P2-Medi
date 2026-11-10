"""BE-10 임베딩 비교 시험·표본 시트 시험. 호출 0: 임베딩 함수는 가짜이고 네트워크·실제 사전 파일을 쓰지 않는다."""

from __future__ import annotations

import base64
import hashlib
import json
import random
import sys
from array import array
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import embed_compare as E  # noqa: E402
import nocode_sample as N  # noqa: E402

from app.llm.ledger import CostLedger  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

SECRET = "sk-test-SECRETVALUE1234567890abcdef"
DIM = 8


def _prod(seq: str, name: str, ing_ids: list[int] | None = None, rx: str = "전문", link: str = "none") -> dict:
    return {"name": name, "item_seq": seq, "entp": "X사", "prescription": rx, "ingredient_ids": ing_ids or [], "code_link": link, "edi_codes": [], "sources": ["허가정보(식약처)"], "cancelled": False}


def tiny_dict(n_products: int = 120) -> DrugDict:
    names = ["타이레놀정", "게보린정", "판콜에이내복액", "신신파스아렉스", "어린이부루펜시럽", "훼스탈플러스정", "베아제정", "탁센연질캡슐", "이지엔식스애니연질캡슐", "펜잘큐정"]
    products = []
    for i in range(n_products):
        base = names[i % len(names)]
        products.append(_prod(str(1000 + i), f"{base}{i // len(names) + 1}0밀리그램" if i >= len(names) else base, [0] if i % 3 == 0 else [], rx="일반" if i % 4 == 0 else "전문"))
    ingredients = [
        {"id": 0, "components": [{"en": "acetaminophen", "ko": "아세트아미노펜", "display": "아세트아미노펜", "raw": "Acetaminophen", "salt": ""}],
         "names": ["Acetaminophen", "아세트아미노펜"], "display": "아세트아미노펜", "kids_codes": ["101301ATB"], "api_codes": [], "sources": []},
        {"id": 1, "components": [{"en": "ibuprofen", "ko": "이부프로펜", "display": "이부프로펜", "raw": "Ibuprofen", "salt": ""}],
         "names": ["Ibuprofen", "이부프로펜"], "display": "이부프로펜", "kids_codes": ["101401ATB"], "api_codes": [], "sources": []},
    ]
    return DrugDict({"meta": {"version": "test-v1"}, "products": products, "ingredients": ingredients})


def fake_vec(text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [(h[i] - 127.5) / 127.5 for i in range(DIM)]


def make_fetch(calls: list[int], tokens_per_text: int = 10):
    def fetch(model_id: str, texts: list[str]) -> dict:
        calls.append(len(texts))
        enc = [base64.b64encode(array("f", fake_vec(t)).tobytes()).decode() for t in texts]
        return {"data": enc, "tokens": tokens_per_text * len(texts)}

    return fetch


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "record")
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    E._ensure_cache_importable()  # 백엔드 venv에는 anthropic이 없다(실호출 없음)
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)
    yield
    sys.modules.pop("_mediagent_llm_cache", None)
    sys.modules.pop("_common", None)


# --------------------------------------------------------------------------- 질의 합성

def test_query_synthesis_is_deterministic_and_typed():
    dd = tiny_dict()
    a = E.build_dev_queries(dd, seed=7, per_type=5)
    b = E.build_dev_queries(dd, seed=7, per_type=5)
    c = E.build_dev_queries(dd, seed=8, per_type=5)
    assert a == b
    assert a != c
    assert E.queries_fingerprint(a) == E.queries_fingerprint(b)
    assert {q["type"] for q in a} <= set(E.QUERY_TYPES)
    assert len({q["id"] for q in a}) == len(a)


def test_typo_queries_differ_from_source_and_keep_answer():
    dd = tiny_dict()
    by_seq = {p["item_seq"]: p for p in dd.products}
    for q in E.build_dev_queries(dd, seed=3, per_type=4):
        if q["type"] in ("typo_drop", "typo_swap"):
            src = by_seq[q["source"]]
            assert E.normalize_name_keep_spaces(src["name"]) != q["query"]
            assert q["source"] in q["answer"]["item_seqs"]


def test_jamo_ops_change_exactly_one_syllable():
    rng = random.Random(1)  # noqa: S311
    dropped = E.drop_jamo("타이레놀", rng)
    assert dropped is not None and dropped != "타이레놀" and len(dropped) == 4
    assert E.drop_jamo("아이우", rng) is None  # 받침 없음
    out = E.swap_jamo("록씨나", random.Random(2))  # noqa: S311
    assert out is not None and out != "록씨나" and len(out) == 3
    assert sum(a != b for a, b in zip(out, "록씨나", strict=True)) == 1


# --------------------------------------------------------------------------- 융합·지표

def test_rrf_fuses_and_is_deterministic():
    fused = E.rrf([[1, 2, 3], [3, 1, 9]])
    assert fused[:2] == [1, 3]  # 1은 순위 1·2, 3은 순위 3·1 → 합이 같아 번호 순
    assert E.rrf([[5], [6]]) == [5, 6]  # 동점은 문서 번호 순
    assert set(E.rrf([[1, 2], [3]])) == {1, 2, 3}


def test_wilson_and_tally_counts():
    lo, hi = E.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert E.wilson(0, 0) == (0.0, 1.0)
    counts = E.tally([[1, 2], [9, 3], []], [{1}, {3}, {1}], ["typo_drop", "typo_drop", "english"])
    assert counts["typo_drop"] == {"n": 2, "top1": 1, "top5": 2}
    assert counts["english"] == {"n": 1, "top1": 0, "top5": 0}
    assert counts["all"] == {"n": 3, "top1": 1, "top5": 2}
    cell = E.with_intervals(counts)["english"]
    assert cell["small_n"] is True and cell["top1"]["k"] == 0


def test_gold_sets_and_evaluate_without_vectors():
    dd = tiny_dict()
    qs = [
        {"id": "a", "type": "english", "query": "acetaminophen", "answer": {"item_seqs": [], "ingredient_ids": [0], "ingredient_products_ok": True}},
        {"id": "b", "type": "typo_drop", "query": "타이레놀정", "answer": {"item_seqs": ["1000"], "ingredient_ids": [], "ingredient_products_ok": False}},
    ]
    golds = E.gold_doc_sets(dd, qs)
    assert len(dd.products) in {g for g in golds[0] if g >= len(dd.products)}  # 성분 0 문서
    assert 0 in golds[0] and golds[1] == {0}  # 성분 0을 가진 제품 0, 제품 1000
    res = E.evaluate(dd, qs, {})
    assert res["BM25 단독"]["all"]["top5"]["k"] == 2


def test_dense_topk_python_path_and_hybrid(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_numpy(name, *a, **k):
        if name == "numpy":
            raise ImportError
        return real_import(name, *a, **k)

    docs = array("f", [1, 0, 0, 1, 1, 1])
    q = array("f", [1, 0.1])
    monkeypatch.setattr(builtins, "__import__", no_numpy)
    assert E.dense_topk(q, docs, 1, 3, 2, k=3)[0] == [0, 2, 1]
    monkeypatch.undo()
    np = pytest.importorskip("numpy")  # numpy 경로도 같은 순서
    assert np is not None
    assert E.dense_topk(q, docs, 1, 3, 2, k=3)[0] == [0, 2, 1]


def test_npy_roundtrip_and_numpy_compat(tmp_path):
    vals = array("f", [0.5, -1.0, 2.0, 3.5, 4.0, 5.0])
    p = tmp_path / "x.npy"
    E.write_npy(p, vals, 2, 3)
    back, n, d = E.read_npy(p)
    assert (n, d) == (2, 3) and list(back) == list(vals)
    assert (p.stat().st_size - len(vals) * 4) % 64 == 0  # 헤더 정렬
    np = pytest.importorskip("numpy")
    arr = np.load(p)
    assert arr.shape == (2, 3) and arr.dtype == np.float32 and float(arr[1, 2]) == 5.0
    with pytest.raises(ValueError):
        E.write_npy(p, vals, 2, 4)


# --------------------------------------------------------------------------- plan / 상한 / 캐시 / 비밀

def test_plan_makes_zero_calls(monkeypatch, tmp_path, capsys):
    dd = tiny_dict()
    monkeypatch.setattr(E.DrugDict, "load", classmethod(lambda cls, *a, **k: dd))
    monkeypatch.setattr(E, "QUERIES_PATH", tmp_path / "q.json")

    def boom(*a, **k):
        raise AssertionError("plan은 호출하면 안 된다")

    monkeypatch.setattr(E, "http_embed", boom)
    monkeypatch.setattr(E, "resolve_key", boom)
    import httpx

    monkeypatch.setattr(httpx, "post", boom)
    assert E.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "호출 0" in out and "text-embedding-3-small" in out and "근사" in out
    p = E.plan_numbers(dd, E.build_dev_queries(dd, per_type=3))
    assert p["models"]["large"]["est_usd_total"] > p["models"]["small"]["est_usd_total"]
    assert p["models"]["small"]["calls"] == p["doc_batches"] + p["query_batches"]


def test_embedder_stops_at_hard_cap_before_calling():
    calls: list[int] = []
    emb = E.Embedder("large", 1e-9, make_fetch(calls))
    with pytest.raises(E.CapReached):
        emb.embed_batch(["타이레놀정500밀리그램"] * 50, "t")
    assert calls == [] and emb.spent == 0.0


def test_embedder_stops_after_actual_cost_exceeds_cap():
    calls: list[int] = []
    # 추정은 상한 아래지만 실제 토큰이 커서 넘는 경우: 호출은 한 번 일어나고 다음 배치 전에 멈춘다
    emb = E.Embedder("large", 0.001, make_fetch(calls, tokens_per_text=100_000))
    with pytest.raises(E.CapReached):
        emb.embed_batch(["가"], "t")
    assert calls == [1]


def test_cache_reuse_skips_calls_and_cost():
    calls: list[int] = []
    texts = ["타이레놀정", "게보린정"]
    e1 = E.Embedder("small", 0.5, make_fetch(calls))
    first = e1.embed_batch(texts, "t")
    assert calls == [2] and e1.calls == 1 and e1.spent > 0
    spent_after_first = CostLedger().spent("dev")
    e2 = E.Embedder("small", 0.5, make_fetch(calls))
    second = e2.embed_batch(texts, "t")
    assert calls == [2]  # 두 번째는 호출 없음
    assert e2.calls == 0 and e2.cached_batches == 1 and e2.spent == 0.0
    assert second == first
    assert CostLedger().spent("dev") == spent_after_first  # 원장에 중복 기록 없음


def test_ledger_records_actual_cost():
    calls: list[int] = []
    emb = E.Embedder("small", 0.5, make_fetch(calls, tokens_per_text=1000))
    emb.embed_batch(["가", "나"], "t")
    assert CostLedger().spent("dev") == pytest.approx(2000 * 0.02 / 1e6)


def test_embed_texts_batches_and_decodes(monkeypatch):
    monkeypatch.setattr(E, "BATCH_SIZE", 3)
    calls: list[int] = []
    emb = E.Embedder("small", 0.5, make_fetch(calls))
    texts = [f"약{i}" for i in range(7)]
    vecs, dim = E.embed_texts(emb, texts, "t")
    assert calls == [3, 3, 1] and dim == DIM and len(vecs) == 7 * DIM
    assert list(vecs[:DIM]) == pytest.approx(fake_vec("약0"), abs=1e-6)


def test_run_and_report_end_to_end_without_leaking_key(monkeypatch, tmp_path, capsys):
    dd = tiny_dict()
    monkeypatch.setattr(E.DrugDict, "load", classmethod(lambda cls, *a, **k: dd))
    monkeypatch.setattr(E, "QUERIES_PATH", tmp_path / "q.json")
    monkeypatch.setattr(E, "EMB_DIR", tmp_path / "emb")
    monkeypatch.setattr(E, "REPORT_JSON", tmp_path / "r.json")
    monkeypatch.setattr(E, "REPORT_MD", tmp_path / "r.md")
    monkeypatch.setattr(E, "resolve_key", lambda: SECRET)
    calls: list[int] = []
    seen_keys: list[str] = []

    def fake_http(model_id: str, texts: list[str], key: str) -> dict:
        seen_keys.append(key)
        return make_fetch(calls)(model_id, texts)

    monkeypatch.setattr(E, "http_embed", fake_http)
    assert E.main(["run", "--model", "small", "--max-usd", "0.5"]) == 0
    assert seen_keys and set(seen_keys) == {SECRET}  # 키는 호출에만 전달된다
    first_calls = len(calls)
    assert E.main(["run", "--model", "small", "--max-usd", "0.5"]) == 0  # 이미 있음 → 건너뜀
    assert len(calls) == first_calls
    assert E.main(["report"]) == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert "임베딩 단독(small)" in report["systems"] and "하이브리드 BM25+small (RRF)" in report["systems"]
    assert report["missing_models"] == ["text-embedding-3-large"]
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "개발용" in md and "Wilson" in md
    captured = capsys.readouterr()
    for blob in (captured.out, captured.err, md, json.dumps(report, ensure_ascii=False)):
        assert SECRET not in blob and SECRET[:12] not in blob


def test_run_refuses_cache_off_and_stops_at_cap(monkeypatch, tmp_path, capsys):
    dd = tiny_dict()
    monkeypatch.setattr(E.DrugDict, "load", classmethod(lambda cls, *a, **k: dd))
    monkeypatch.setattr(E, "QUERIES_PATH", tmp_path / "q.json")
    monkeypatch.setattr(E, "EMB_DIR", tmp_path / "emb")
    monkeypatch.setattr(E, "resolve_key", lambda: SECRET)
    calls: list[int] = []
    monkeypatch.setattr(E, "http_embed", lambda m, t, k: make_fetch(calls)(m, t))
    assert E.main(["run", "--model", "large", "--max-usd", "0.000000001"]) == 3  # 상한 → 중단, 호출 0
    assert calls == []
    assert "중단" in capsys.readouterr().out
    assert not (tmp_path / "emb" / "text-embedding-3-large.npy").exists()
    monkeypatch.setenv("LLM_CACHE", "off")
    assert E.main(["run", "--model", "small", "--max-usd", "0.5", "--force"]) == 2


def test_run_without_key_does_not_call(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "EMB_DIR", tmp_path / "emb")
    monkeypatch.setattr(E, "resolve_key", lambda: None)
    assert E.main(["run", "--model", "small", "--max-usd", "0.5"]) == 2


# --------------------------------------------------------------------------- 표본 시트

def nocode_dict() -> DrugDict:
    products = [_prod(str(i), f"전문약{i}", rx="전문") for i in range(60)]
    products += [_prod(str(100 + i), f"일반약{i}", rx="일반") for i in range(40)]
    products += [_prod(str(500 + i), f"연결됨{i}", rx="전문", link="edi_code") for i in range(30)]
    return DrugDict({"meta": {"version": "t"}, "products": products, "ingredients": []})


def test_allocate_preserves_ratio_and_total():
    assert N.allocate({"전문": 60, "일반": 40}, 10) == {"전문": 6, "일반": 4}
    a = N.allocate({"전문": 53, "일반": 47, "표기없음": 1}, 100)
    assert sum(a.values()) == 100 and a["표기없음"] <= 1
    assert N.allocate({"a": 2}, 10) == {"a": 2}  # 층 크기를 넘기지 않는다


def test_sample_is_seeded_stratified_and_only_nocode():
    dd = nocode_dict()
    a = N.draw_sample(dd, 20)
    assert a == N.draw_sample(dd, 20)
    assert a != N.draw_sample(dd, 20, seed=1)
    assert len(a) == 20 and not any(r["product_name"].startswith("연결됨") for r in a)
    assert sum(r["prescription"] == "전문" for r in a) == 12 and sum(r["prescription"] == "일반" for r in a) == 8
    assert all(r["verdict"] == "" for r in a)


def test_csv_and_tally(tmp_path):
    rows = N.draw_sample(nocode_dict(), 10)
    p = tmp_path / "s.csv"
    N.write_csv(p, rows)
    t = N.tally_csv(p)
    assert t["total"] == 10 and t["judged"] == 0 and t["unjudged"] == 10
    text = p.read_text(encoding="utf-8-sig").splitlines()
    assert text[0].split(",")[-2:] == ["verdict", "note"]
    for r, v in zip(rows, ["연결실패"] * 3 + ["KIDS목록밖"] * 5 + ["판단불가"], strict=False):
        r["verdict"] = v
    N.write_csv(p, rows)
    t = N.tally_csv(p)
    assert t["judged"] == 9 and t["unjudged"] == 1
    assert t["verdicts"]["KIDS목록밖"]["k"] == 5 and t["verdicts"]["연결실패"]["n"] == 9
    rows[0]["verdict"] = "모르겠음"
    N.write_csv(p, rows)
    with pytest.raises(ValueError):
        N.tally_csv(p)
    assert N.main(["--tally", str(p)]) == 2
