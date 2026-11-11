"""embed_corpus: 중복 제거·재개·상한 중단·비밀 비출력(가짜 임베딩 함수, 네트워크 없음)."""

from __future__ import annotations

import base64
import json
import sys
from array import array
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import embed_corpus as ec  # noqa: E402

from app.llm.ledger import CostLedger  # noqa: E402

DIM = 8


def fake_fetch_factory(calls: list[int]):
    def fetch(model_id: str, texts: list[str]) -> dict:
        calls.append(len(texts))
        data = []
        for t in texts:
            a = array("f", [float((hash(t) + i) % 7) for i in range(DIM)])
            data.append(base64.b64encode(a.tobytes()).decode())
        return {"data": data, "tokens": 1000 * len(texts)}

    return fetch


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "off")
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))


def chunks_of(*texts: str) -> list[dict]:
    return [{"chunk_id": f"c{i}", "text": t} for i, t in enumerate(texts)]


def test_unique_texts_dedupes_and_is_sorted():
    items = ec.unique_texts(chunks_of("가", "나", "가", "다", "나"))
    assert len(items) == 3
    assert [h for h, _ in items] == sorted(h for h, _ in items)


def test_plan_counts_unique_and_makes_no_calls():
    p = ec.plan(chunks_of("가" * 10, "가" * 10, "나" * 10))
    assert p["chunks"] == 3 and p["unique_texts"] == 2 and p["executed"] is False


def test_batches_respect_item_and_token_limits():
    items = [(str(i), "가" * 100) for i in range(10)]
    assert [len(b) for b in ec.make_batches(items, max_items=4, max_tokens=10**9)] == [4, 4, 2]
    big = [(str(i), "가" * 3000) for i in range(5)]  # 약 5,100토큰씩
    assert all(len(b) <= 11 for b in ec.make_batches(big, max_items=256, max_tokens=60_000))
    assert len(ec.make_batches(big, max_items=256, max_tokens=10_000)) == 5


def _emb(calls, max_usd=1.0, tmp=None):
    from embed_compare import Embedder

    return Embedder("small", max_usd, fake_fetch_factory(calls), ledger=CostLedger(Path(tmp) / "l.json"))


def test_run_resume_and_finalize(tmp_path):
    items = ec.unique_texts(chunks_of(*[f"텍스트{i}" for i in range(10)]))
    store = ec.Store(tmp_path / "emb", dim=DIM)
    calls: list[int] = []
    res = ec.run_embedding(items, store, _emb(calls, tmp=tmp_path), limit=4, log=lambda s: None)
    assert sum(calls) == 4 and len(store.done_hashes()) == 4
    calls2: list[int] = []
    ec.run_embedding(items, store, _emb(calls2, tmp=tmp_path), log=lambda s: None)
    assert sum(calls2) == 6  # 이미 한 4개는 다시 호출하지 않는다
    fin = store.finalize([h for h, _ in items])
    assert fin["rows"] == 10 and store.npy.exists()
    idx = json.loads(store.index_json.read_text(encoding="utf-8"))
    assert idx["dim"] == DIM and len(idx["rows"]) == 10
    assert res["calls"] == 1


def test_resume_truncates_half_written_vectors(tmp_path):
    store = ec.Store(tmp_path / "emb", dim=DIM)
    store.append(["a"], [[1.0] * DIM])
    with open(store.bin, "ab") as f:
        f.write(b"\x00" * (DIM * 4))  # 인덱스 없이 벡터만 써진 중단 상태
    assert store.done_hashes() == {"a": 0}
    assert store.bin.stat().st_size == DIM * 4


def test_cap_stops_before_call_and_keeps_saved(tmp_path):
    from embed_compare import CapReached

    items = ec.unique_texts(chunks_of(*[f"{'가' * 300}{i}" for i in range(600)]))
    store = ec.Store(tmp_path / "emb", dim=DIM)
    calls: list[int] = []
    with pytest.raises(CapReached):
        ec.run_embedding(items, store, _emb(calls, max_usd=0.001, tmp=tmp_path), log=lambda s: None)
    assert len(store.done_hashes()) == sum(calls)  # 호출된 만큼만 저장


def test_dimension_mismatch_raises(tmp_path):
    items = ec.unique_texts(chunks_of("가", "나"))
    store = ec.Store(tmp_path / "emb", dim=DIM + 1)
    with pytest.raises(ValueError):
        ec.run_embedding(items, store, _emb([], tmp=tmp_path), log=lambda s: None)


def test_http_embed_retries_429_and_hides_key(monkeypatch):
    import httpx

    seq = [httpx.Response(429, headers={"retry-after": "1"}, text="slow"), httpx.Response(401, text="bad")]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: seq.pop(0))
    waits: list[float] = []
    with pytest.raises(RuntimeError) as ei:
        ec.http_embed("m", ["x"], "sk-SECRET-KEY", sleep=waits.append)
    assert waits == [1.0] and "sk-SECRET-KEY" not in str(ei.value)


def test_extend_after_finalize_keeps_old_rows_and_calls_only_new(tmp_path):
    """마무리된 npy·index.json 뒤에 새 텍스트가 생기면 기존 행·벡터는 그대로 두고 새 텍스트만 호출한다(BE-16)."""
    import numpy as np

    old = ec.unique_texts(chunks_of(*[f"텍스트{i}" for i in range(6)]))
    store = ec.Store(tmp_path / "emb", dim=DIM)
    ec.run_embedding(old, store, _emb([], tmp=tmp_path), log=lambda s: None)
    store.finalize([h for h, _ in old])
    before = np.load(store.npy).copy()
    rows_before = json.loads(store.index_json.read_text(encoding="utf-8"))["rows"]

    new = ec.unique_texts(chunks_of(*[f"텍스트{i}" for i in range(6)], "새 글 가", "새 글 나"))
    assert store.reopen_for_extension() == 6
    assert not store.index_json.exists() and (store.dir / "index.json.before_extend").exists()
    calls: list[int] = []
    ec.run_embedding(new, store, _emb(calls, tmp=tmp_path), log=lambda s: None)
    assert sum(calls) == 2
    assert store.finalize([h for h, _ in new])["rows"] == 8
    after = np.load(store.npy)
    rows_after = json.loads(store.index_json.read_text(encoding="utf-8"))["rows"]
    assert all(rows_after[h] == r for h, r in rows_before.items())  # 기존 행 번호 유지
    assert np.array_equal(after[:6], before)
    assert store.reopen_for_extension() == 8  # 다시 열어도 일관(이전 before_extend는 덮어쓰기 대상)
