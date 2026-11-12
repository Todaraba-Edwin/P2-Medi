"""AG-03 하이브리드 정답 사례 찾기: BM25 단독·벡터 단독·하이브리드(RRF)의 정답 순위를 같은 질의로 비교한다.

- 로컬 `CorpusIndex`(jsonl) + 로컬 임베딩 파일(`data/mock/corpus/embeddings/`)만 쓴다. **원격 DB·어댑터 접속 없음.**
- 질의는 청크 필드에서 **규칙으로 만든 합성 질의**(시드 고정, BE-05-01 청킹 시험과 같은 방식)이고 정답도 규칙으로 정한다. 평가 세트가 아니며 평가 수치로 쓰지 않는다.
- 질의 임베딩만 OpenAI를 부른다(`embed_compare.Embedder`: 개발 원장·캐시 `llm_cache` 우선, `--max-usd` 하드 상한). 키는 출력하지 않는다.
- 결과 JSON은 `data/mock/review/ag03_hybrid_case.json`(읽기만 하는 `data/mock/` 밖에는 쓰지 않는다).

사용(저장소 루트): `backend/.venv/bin/python backend/scripts/ag03_hybrid_case.py [--max-usd 0.05] [--json PATH]`

판정: 하이브리드 정답 순위가 BM25 순위·벡터 순위보다 **둘 다 엄격히 위**이면 "하이브리드 우위 사례"
(순위 없음 = 미적중 = 무한대로 비교). 하이브리드는 `CorpusIndex.search(vector_fn=...)` 구현 그대로(어휘 점수 0인 벡터 단독 결과는 코드가 버린다, RFP-22-02 A).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent.tools.corpus import ChunkFilter, CorpusIndex, load_local_corpus  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EMB_DIR = ROOT / "data" / "mock" / "corpus" / "embeddings"
OUT_JSON = ROOT / "data" / "mock" / "review" / "ag03_hybrid_case.json"
SEED = 20261112
DEPTH = 100
INF = 10**9

EYAK_TEMPLATES = {
    "효능": "{n}은 어디에 쓰는 약인가요",
    "사용법": "{n} 어떻게 먹나요",
    "보관법": "{n} 보관은 어떻게 하나요",
    "주의사항": "{n} 먹을 때 조심할 점",
    "이상반응": "{n} 먹고 생길 수 있는 부작용",
    "상호작용": "{n} 같이 먹으면 안 되는 약",
    "경고": "{n} 먹기 전에 꼭 알아야 할 경고",
}
_WORD_RE = re.compile(r"[가-힣]{3,}")


def short_name(name: str) -> str:
    return name.split("(")[0].strip()


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 - 임베딩 파일 키(embed_corpus.text_hash와 같은 규칙, 보안 용도 아님)


# --------------------------------------------------------------------------- 질의 만들기(규칙)

def _kw_query(rng: random.Random, c: dict[str, Any], name: str, n_words: int = 3) -> str | None:
    words = sorted({w for w in _WORD_RE.findall(c["text"].split("] ", 1)[-1]) if w not in name})
    if len(words) < n_words:
        return None
    return " ".join(rng.sample(words, n_words))


def build_queries(idx: CorpusIndex, seed: int = SEED, per_family: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """질의 = {id, family, query, gold(set of chunk_id)}. 같은 인덱스·시드면 항상 같다."""
    per = per_family or {"eyak_daily": 30, "eyak_kw": 20, "preg_daily": 25, "combo_daily": 25, "prmsn_kw": 20}
    rng = random.Random(seed)  # noqa: S311 - 재현 가능한 합성 질의용 시드(보안 용도 아님)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for c in sorted(idx.chunks, key=lambda x: x["chunk_id"]):
        by_kind.setdefault(c["chunk_kind"], []).append(c)
    qs: list[dict[str, Any]] = []

    def add(family: str, query: str, gold: set[str]) -> None:
        qs.append({"id": f"{family}-{sum(1 for q in qs if q['family'] == family) + 1:02d}", "family": family, "query": query, "gold": sorted(gold)})

    eyak = [c for c in by_kind.get("l3_eyak_section", []) if c.get("item_name") and c.get("section") in EYAK_TEMPLATES]
    for c in rng.sample(eyak, min(per["eyak_daily"], len(eyak))):
        gold = {x["chunk_id"] for x in eyak if x["item_seq"] == c["item_seq"] and x["section"] == c["section"]}
        add("eyak_daily", EYAK_TEMPLATES[c["section"]].format(n=short_name(c["item_name"])), gold)
    n_kw = 0
    for c in rng.sample(eyak, min(len(eyak), per["eyak_kw"] * 5)):
        q = _kw_query(rng, c, c["item_name"])
        if q and n_kw < per["eyak_kw"]:
            add("eyak_kw", f"{short_name(c['item_name'])} {q}", {c["chunk_id"]})
            n_kw += 1
    preg = [c for c in by_kind.get("l2_preg", []) if c.get("ingr_codes") and c.get("ingr_names")]
    for c in rng.sample(preg, min(per["preg_daily"], len(preg))):
        code = c["ingr_codes"][0]
        add("preg_daily", f"임신 중에 {c['ingr_names'][0]} 먹어도 되나요", {x["chunk_id"] for x in preg if code in x["ingr_codes"]})
    combo = [c for c in by_kind.get("l2_combo", []) if c.get("pair_id") and len(c.get("ingr_names") or []) == 2]
    for c in rng.sample(combo, min(per["combo_daily"], len(combo))):
        add("combo_daily", f"{c['ingr_names'][0]}와 {c['ingr_names'][1]} 같이 먹어도 되나요", {x["chunk_id"] for x in combo if x["pair_id"] == c["pair_id"]})
    para = [c for c in by_kind.get("l3_prmsn_para", []) if c.get("item_name")]
    n_kw = 0
    for c in rng.sample(para, min(len(para), per["prmsn_kw"] * 5)):
        q = _kw_query(rng, c, c["item_name"])
        if q and n_kw < per["prmsn_kw"]:
            add("prmsn_kw", f"{short_name(c['item_name'])} {q}", {c["chunk_id"]})
            n_kw += 1
    return qs


# --------------------------------------------------------------------------- 로컬 벡터 검색

class LocalVectors:
    """로컬 임베딩 파일(`vectors.npy` + `index.json`) 위의 코사인(내적) 검색. 질의 벡터는 문장→벡터 dict로 받는다."""

    def __init__(self, vectors: Any, row_of_hash: dict[str, int], idx: CorpusIndex, qvec: dict[str, Sequence[float]]) -> None:
        import numpy as np

        self._np = np
        self.v = vectors
        self.qvec = qvec
        self.chunks_of_row: dict[int, list[str]] = {}
        for c in idx.chunks:
            r = row_of_hash.get(text_hash(c["text"]))
            if r is not None:
                self.chunks_of_row.setdefault(r, []).append(c["chunk_id"])
        self.n_missing = sum(1 for c in idx.chunks if text_hash(c["text"]) not in row_of_hash)

    def __call__(self, query: str, *, k: int, filters: ChunkFilter) -> list[tuple[str, float]]:  # noqa: ARG002 - 필터는 CorpusIndex.search가 후보로 다시 거른다
        np = self._np
        s = self.v @ np.asarray(self.qvec[query], dtype=np.float32)
        order = np.argsort(-s)[: k * 3]
        out: list[tuple[str, float]] = []
        for r in order:
            for cid in self.chunks_of_row.get(int(r), []):
                out.append((cid, float(s[r])))
            if len(out) >= k:
                break
        return out[:k]


def load_embeddings(idx: CorpusIndex, qvec: dict[str, Sequence[float]]) -> LocalVectors:
    import numpy as np

    meta = json.loads((EMB_DIR / "index.json").read_text(encoding="utf-8"))
    return LocalVectors(np.load(EMB_DIR / "vectors.npy", mmap_mode="r"), meta["rows"], idx, qvec)


# --------------------------------------------------------------------------- 순위 비교

def rank_of(ids: Sequence[str], gold: set[str]) -> int | None:
    for r, cid in enumerate(ids, start=1):
        if cid in gold:
            return r
    return None


def evaluate(idx: CorpusIndex, queries: Sequence[dict[str, Any]], vec: Callable[..., Sequence[tuple[str, float]]]) -> list[dict[str, Any]]:
    out = []
    flt = ChunkFilter()
    for q in queries:
        gold = set(q["gold"])
        bm = [h.chunk["chunk_id"] for h in idx.search(q["query"], flt, top_k=DEPTH)]
        ve = [cid for cid, _ in vec(q["query"], k=DEPTH, filters=flt)]
        hy = [h.chunk["chunk_id"] for h in idx.search(q["query"], flt, top_k=DEPTH, vector_fn=vec)]
        rb, rv, rh = rank_of(bm, gold), rank_of(ve, gold), rank_of(hy, gold)
        best_single = min(rb or INF, rv or INF)
        out.append({**{k: q[k] for k in ("id", "family", "query")}, "gold_n": len(gold), "gold_example": q["gold"][0],
                    "rank_bm25": rb, "rank_vector": rv, "rank_hybrid": rh,
                    "hybrid_beats_both": rh is not None and rh < best_single,
                    "hybrid_top5_single_not": rh is not None and rh <= 5 and best_single > 5})
    return out


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def hit(key: str, k: int) -> int:
        return sum(1 for r in rows if r[key] is not None and r[key] <= k)

    fam = Counter(r["family"] for r in rows)
    wins: Counter[str] = Counter(r["family"] for r in rows if r["hybrid_beats_both"])
    return {"n": len(rows), "by_family": dict(fam), "wins_by_family": dict(wins),
            "top1": {m: hit(f"rank_{m}", 1) for m in ("bm25", "vector", "hybrid")},
            "top5": {m: hit(f"rank_{m}", 5) for m in ("bm25", "vector", "hybrid")},
            "top10": {m: hit(f"rank_{m}", 10) for m in ("bm25", "vector", "hybrid")},
            "hybrid_beats_both": sum(1 for r in rows if r["hybrid_beats_both"]),
            "hybrid_top5_single_not": sum(1 for r in rows if r["hybrid_top5_single_not"]),
            "hybrid_worse_than_best_single": sum(1 for r in rows if (r["rank_hybrid"] or INF) > min(r["rank_bm25"] or INF, r["rank_vector"] or INF))}


# --------------------------------------------------------------------------- 질의 임베딩(실호출은 여기만)

def embed_queries_openai(texts: Sequence[str], max_usd: float) -> tuple[dict[str, list[float]], dict[str, Any]]:
    from array import array

    from embed_compare import Embedder, _ensure_cache_importable, embed_texts, resolve_key  # noqa: PLC0415

    _ensure_cache_importable()
    from embed_corpus import http_embed  # noqa: PLC0415

    key = resolve_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY 값을 찾지 못했다")
    emb = Embedder("small", max_usd, lambda model, ts: http_embed(model, ts, key))
    vecs, dim = embed_texts(emb, list(texts), "ag03_hybrid_case")
    arr: array[float] = vecs
    out = {t: list(arr[i * dim:(i + 1) * dim]) for i, t in enumerate(texts)}
    return out, {"calls": emb.calls, "cached_batches": emb.cached_batches, "tokens": emb.tokens, "usd": round(emb.spent, 6), "max_usd": max_usd}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-usd", type=float, default=0.05)
    ap.add_argument("--json", type=Path, default=OUT_JSON)
    a = ap.parse_args(argv)
    idx = load_local_corpus()
    if idx is None:
        print("로컬 코퍼스 없음")
        return 1
    queries = build_queries(idx)
    qvec, cost = embed_queries_openai([q["query"] for q in queries], a.max_usd)
    vec = load_embeddings(idx, qvec)
    rows = evaluate(idx, queries, vec)
    summ = summarize(rows)
    summ["chunks_without_embedding"] = vec.n_missing
    result = {"seed": SEED, "depth": DEPTH, "cost": cost, "summary": summ, "queries": rows}
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cost": cost, "summary": summ}, ensure_ascii=False, indent=2))
    wins = [r for r in rows if r["hybrid_beats_both"]]
    print(f"\n하이브리드 우위 사례 {len(wins)}건")
    for r in wins[:10]:
        print(f"- {r['id']} 「{r['query']}」 정답 {r['gold_example']} (정답 {r['gold_n']}개 중 최고 순위) BM25 {r['rank_bm25']} · 벡터 {r['rank_vector']} · 하이브리드 {r['rank_hybrid']}")
    return 0


if __name__ == "__main__":
    install_excepthook()  # S-05: 처리되지 않은 예외·logging 출력에서 키 가리기
    raise SystemExit(main())
