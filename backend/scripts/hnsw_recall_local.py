"""BE-16-06 A: 로컬 HNSW recall@10 측정(원격 DB 접근 0, 임베딩·LLM 호출 0).

    python backend/scripts/hnsw_recall_local.py [--n 200] [--seed 20261111] [--filter-n 200]

- 데이터: `data/mock/corpus/embeddings/{vectors.npy, index.json}`(고유 텍스트 벡터)와 청크 메타(`embed_corpus.load_all_chunks`).
- 색인: hnswlib HNSW `M=16`, `ef_construction=64`, space=cosine(원격 pgvector `vector_cosine_ops`와 같은 거리 1-cos).
  hnswlib과 pgvector는 같은 HNSW 계열이지만 구현이 달라 **recall 값은 근사 비교**이고 원격 수치와 같다고 주장하지 않는다.
- 정답: numpy 코사인 전수 비교(정확 검색). 질의는 코퍼스 벡터에서 층(L1·L2·L3) 층화 무작위 추출(시드 고정), 자기 자신은 결과에서 뺀다.
- 무필터: ef ∈ {10, 20, 40, 100, 200}에서 recall@10 = Σ겹침 / (10×질의 수), Wilson 95% 구간, 층별 표, 질의당 평균 지연(로컬 단일 스레드, 참고).
- 강한 필터 시나리오: 같은 `layer` AND `ingr_codes && 질의 코드`(앱 `build_where`와 같은 조건).
  pgvector(iterative scan 미사용)는 색인이 ef_search개 후보를 낸 뒤 WHERE로 거르는 **사후 필터**이므로 그대로 흉내 낸다.
  정답은 필터 통과 집합 안의 정확 top-10이다. 반환 수가 10보다 적을 수 있어 반환 수도 함께 적는다.
  (원격 플래너가 선택도가 높은 필터에서 색인 대신 정확 스캔을 고르면 recall은 1이다. 이 시나리오는 색인을 탄 경우의 하한 쪽이다.)
- 결과: 질의별 jsonl `data/mock/review/recall_hnsw_local_{시각}.jsonl`, 요약 json(같은 이름 `.summary.json`), 표준출력에 표.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import random
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from embed_compare import wilson  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EMB_DIR = REPO / "data" / "mock" / "corpus" / "embeddings"
REVIEW_DIR = REPO / "data" / "mock" / "review"
EF_LIST = (10, 20, 40, 100, 200)
K = 10
M = 16
EF_CONSTRUCTION = 64
LAYERS = ("L1", "L2", "L3")


# --------------------------------------------------------------------------- 순수 함수(단위 시험 대상)


def normalize(x: np.ndarray) -> np.ndarray:
    """행 단위 L2 정규화(0 벡터는 그대로). 코사인 = 정규화 벡터 내적."""
    n = np.linalg.norm(x, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (x / n).astype(np.float32)


def exact_topk(xn: np.ndarray, q_ids: Sequence[int], k: int = K, allowed: Sequence[np.ndarray] | None = None) -> list[list[int]]:
    """정확 검색: 정규화 행렬 `xn`에서 질의 행(`q_ids`)의 코사인 top-k(자기 자신 제외).

    `allowed[i]`가 있으면 그 행 번호 집합 안에서만 찾는다(필터 정답). 동점은 행 번호 오름차순.
    """
    out: list[list[int]] = []
    for i, qi in enumerate(q_ids):
        cand = np.arange(xn.shape[0]) if allowed is None else np.asarray(allowed[i], dtype=np.int64)
        cand = cand[cand != qi]
        if cand.size == 0:
            out.append([])
            continue
        sims = xn[cand] @ xn[qi]
        kk = min(k, cand.size)
        part = np.argpartition(-sims, kk - 1)[:kk]
        order = sorted(part.tolist(), key=lambda j: (-float(sims[j]), int(cand[j])))
        out.append([int(cand[j]) for j in order])
    return out


def recall_hits(approx: Sequence[int], exact: Sequence[int], k: int = K) -> int:
    """질의 1개의 top-k 겹침 수(정답 top-k 중 근사 결과 top-k에 든 개수)."""
    return len(set(list(approx)[:k]) & set(list(exact)[:k]))


def recall_at_k(approx_lists: Iterable[Sequence[int]], exact_lists: Iterable[Sequence[int]], k: int = K) -> tuple[int, int]:
    """(분자, 분모) = (Σ 겹침, Σ min(k, 정답 수)). 정답이 k개보다 적은 질의(필터)는 그 수만 분모에 넣는다."""
    hit = den = 0
    for a, e in zip(approx_lists, exact_lists, strict=True):
        hit += recall_hits(a, e, k)
        den += min(k, len(e))
    return hit, den


def stratified_sample(groups: dict[str, list[int]], n: int, seed: int) -> list[tuple[str, int]]:
    """층별 균등 배분 무작위 추출(나머지는 앞 층부터 1개씩). 층 크기보다 많이 뽑지 않는다."""
    rng = random.Random(seed)  # noqa: S311 - 측정 표본(시드 고정), 보안 용도 아님
    keys = sorted(groups)
    base, rem = divmod(n, len(keys))
    out: list[tuple[str, int]] = []
    for i, key in enumerate(keys):
        want = min(base + (1 if i < rem else 0), len(groups[key]))
        out.extend((key, r) for r in sorted(rng.sample(groups[key], want)))
    return out


def post_filter(cands: Sequence[int], ok: set[int], self_id: int, k: int = K) -> list[int]:
    """색인 후보(가까운 순)에서 자기 자신을 빼고 필터 통과만 남겨 top-k(pgvector 사후 필터 흉내)."""
    return [c for c in cands if c != self_id and c in ok][:k]


# --------------------------------------------------------------------------- 데이터


def load_vectors() -> tuple[np.ndarray, dict[str, int]]:
    meta = json.loads((EMB_DIR / "index.json").read_text(encoding="utf-8"))
    vec = np.load(EMB_DIR / "vectors.npy", mmap_mode="r")
    rows: dict[str, int] = meta["rows"]
    if vec.shape != (len(rows), int(meta["dim"])):
        raise RuntimeError(f"vectors.npy {vec.shape}와 index.json 행 수 {len(rows)}·차원이 다르다")
    return np.asarray(vec, dtype=np.float32), rows


def row_meta(rows: dict[str, int]) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """행 번호 → {layers, codes, chunks}. 같은 텍스트를 공유하는 청크는 한 행에 모인다."""
    from embed_corpus import load_all_chunks, text_hash  # noqa: PLC0415 - 실행 때만(시험은 import하지 않음)

    chunks = load_all_chunks()
    meta: dict[int, dict[str, Any]] = defaultdict(lambda: {"layers": set(), "codes": set(), "chunks": 0})
    missing = 0
    for c in chunks:
        r = rows.get(text_hash(c["text"]))
        if r is None:
            missing += 1
            continue
        m = meta[r]
        m["layers"].add(c.get("layer"))
        m["codes"].update(c.get("ingr_codes") or [])
        m["chunks"] += 1
    stats = {
        "chunks": len(chunks),
        "chunks_without_vector": missing,
        "rows_with_chunks": len(meta),
        "rows_without_chunks": len(rows) - len(meta),
        "rows_shared_by_multiple_chunks": sum(1 for m in meta.values() if m["chunks"] > 1),
        "rows_multi_layer": sum(1 for m in meta.values() if len(m["layers"]) > 1),
    }
    return dict(meta), stats


# --------------------------------------------------------------------------- 측정


def build_index(xn: np.ndarray) -> Any:
    import hnswlib  # noqa: PLC0415 - 로컬 측정 전용(dev 선택 의존성)

    idx = hnswlib.Index(space="cosine", dim=xn.shape[1])
    idx.init_index(max_elements=xn.shape[0], M=M, ef_construction=EF_CONSTRUCTION, random_seed=100)
    idx.set_num_threads(os.cpu_count() or 1)
    idx.add_items(xn, np.arange(xn.shape[0]))
    idx.set_num_threads(1)  # 질의 지연은 단일 스레드로 잰다
    return idx


def query_one(idx: Any, xn: np.ndarray, qi: int, k: int, ef: int) -> tuple[list[int], float]:
    idx.set_ef(max(ef, k))  # hnswlib은 ef<k를 허용하지 않는다(앱도 max(ef_search, k))
    t0 = time.perf_counter()
    labels, _ = idx.knn_query(xn[qi : qi + 1], k=k)
    ms = (time.perf_counter() - t0) * 1000
    return [int(x) for x in labels[0]], ms


def run(n: int, seed: int, filter_n: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    x, rows = load_vectors()
    norms = np.linalg.norm(x, axis=1)
    xn = normalize(x)
    meta, stats = row_meta(rows)
    stats.update(vectors=int(x.shape[0]), dim=int(x.shape[1]), norm_min=float(norms.min()), norm_max=float(norms.max()))

    layer_of = {r: sorted(m["layers"])[0] for r, m in meta.items()}
    groups: dict[str, list[int]] = defaultdict(list)
    for r, lay in layer_of.items():
        groups[lay].append(r)
    stats["rows_by_layer"] = {k: len(v) for k, v in sorted(groups.items())}

    tb = time.perf_counter()
    idx = build_index(xn)
    stats["build_s"] = round(time.perf_counter() - tb, 1)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REVIEW_DIR / f"recall_hnsw_local_{stamp}.jsonl"
    records: list[dict[str, Any]] = []

    # ---- 무필터
    sample = stratified_sample(dict(groups), n, seed)
    q_ids = [r for _, r in sample]
    exact = exact_topk(xn, q_ids, K)
    unf: dict[int, dict[str, Any]] = {}
    for ef in EF_LIST:
        per_layer: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        lat: list[float] = []
        hit_all = den_all = 0
        for (lay, qi), ex in zip(sample, exact, strict=True):
            got, ms = query_one(idx, xn, qi, K + 1, ef)
            got = [g for g in got if g != qi][:K]
            h = recall_hits(got, ex)
            hit_all += h
            den_all += len(ex)
            per_layer[lay][0] += h
            per_layer[lay][1] += len(ex)
            lat.append(ms)
            records.append({"scenario": "unfiltered", "ef": ef, "layer": lay, "row": qi, "hits": h, "n": len(ex), "ms": round(ms, 4)})
        lo, hi = wilson(hit_all, den_all)
        unf[ef] = {
            "k": hit_all,
            "n": den_all,
            "recall": hit_all / den_all,
            "wilson": [lo, hi],
            "perfect_queries": sum(1 for r in records if r["scenario"] == "unfiltered" and r["ef"] == ef and r["hits"] == r["n"]),
            "mean_ms": float(np.mean(lat)),
            "p95_ms": float(np.percentile(lat, 95)),
            "by_layer": {
                lay: {"k": v[0], "n": v[1], "recall": v[0] / v[1], "wilson": list(wilson(*v))} for lay, v in sorted(per_layer.items())
            },
        }

    # ---- 강한 필터(같은 layer AND ingr_codes 겹침), 사후 필터
    by_layer_code: dict[tuple[str, str], set[int]] = defaultdict(set)
    for r, m in meta.items():
        for lay in m["layers"]:
            for code in m["codes"]:
                by_layer_code[(lay, code)].add(r)
    rng = random.Random(seed + 1)  # noqa: S311 - 측정 표본
    coded = sorted(r for r, m in meta.items() if m["codes"])
    fsample: list[tuple[int, set[int]]] = []
    for qi in rng.sample(coded, min(filter_n, len(coded))):
        lay = layer_of[qi]
        ok: set[int] = set()
        for code in meta[qi]["codes"]:
            ok |= by_layer_code[(lay, code)]
        ok.discard(qi)
        if ok:
            fsample.append((qi, ok))
    f_exact = exact_topk(xn, [q for q, _ in fsample], K, allowed=[np.fromiter(ok, dtype=np.int64) for _, ok in fsample])
    filt: dict[int, dict[str, Any]] = {}
    for ef in EF_LIST:
        hit_all = den_all = ret_all = short = 0
        lat = []
        for (qi, ok), ex in zip(fsample, f_exact, strict=True):
            cands, ms = query_one(idx, xn, qi, max(ef, K) + 1, ef)  # 색인이 내는 후보 수 = ef_search(+자기 자신 1)
            got = post_filter(cands, ok, qi)
            h = recall_hits(got, ex)
            hit_all += h
            den_all += len(ex)
            ret_all += len(got)
            short += int(len(got) < len(ex))
            lat.append(ms)
            records.append(
                {
                    "scenario": "filtered_post",
                    "ef": ef,
                    "layer": layer_of[qi],
                    "row": qi,
                    "allowed": len(ok),
                    "hits": h,
                    "n": len(ex),
                    "returned": len(got),
                    "ms": round(ms, 4),
                }
            )
        lo, hi = wilson(hit_all, den_all)
        filt[ef] = {
            "k": hit_all,
            "n": den_all,
            "recall": hit_all / den_all if den_all else None,
            "wilson": [lo, hi],
            "mean_returned": ret_all / len(fsample),
            "queries_short": short,
            "mean_ms": float(np.mean(lat)),
        }
    allowed_sizes = sorted(len(ok) for _, ok in fsample)

    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {
        "stamp": stamp,
        "seed": seed,
        "k": K,
        "M": M,
        "ef_construction": EF_CONSTRUCTION,
        "hnswlib": importlib.metadata.version("hnswlib"),
        "data": stats,
        "queries": {
            "unfiltered": len(sample),
            "by_layer": {k: sum(1 for s in sample if s[0] == k) for k in LAYERS},
            "filtered": len(fsample),
            "filtered_allowed_median": allowed_sizes[len(allowed_sizes) // 2] if allowed_sizes else None,
            "filtered_allowed_min_max": [allowed_sizes[0], allowed_sizes[-1]] if allowed_sizes else None,
        },
        "unfiltered": unf,
        "filtered_post": filt,
        "jsonl": str(out_path.relative_to(REPO)),
        "elapsed_s": round(time.perf_counter() - t0, 1),
    }
    out_path.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def print_summary(s: dict[str, Any]) -> None:
    print(json.dumps({"data": s["data"], "queries": s["queries"], "hnswlib": s["hnswlib"]}, ensure_ascii=False, indent=1))
    print("\n[무필터] ef | recall@10 k/n | Wilson95 | 완전일치 질의 | 평균ms | p95ms | " + " | ".join(LAYERS))
    for ef, v in s["unfiltered"].items():
        lays = " | ".join(f"{b['k']}/{b['n']}={b['recall']:.3f}" for b in v["by_layer"].values())
        print(
            f"{ef} | {v['k']}/{v['n']}={v['recall']:.4f} | [{v['wilson'][0]:.4f}, {v['wilson'][1]:.4f}] | "
            f"{v['perfect_queries']} | {v['mean_ms']:.3f} | {v['p95_ms']:.3f} | {lays}"
        )
    print("\n[강한 필터·사후] ef | recall@10 k/n | Wilson95 | 평균 반환 수 | 10개 미만 질의 | 평균ms")
    for ef, v in s["filtered_post"].items():
        print(
            f"{ef} | {v['k']}/{v['n']}={v['recall']:.4f} | [{v['wilson'][0]:.4f}, {v['wilson'][1]:.4f}] | "
            f"{v['mean_returned']:.2f} | {v['queries_short']} | {v['mean_ms']:.3f}"
        )
    print(f"\njsonl: {s['jsonl']}  경과 {s['elapsed_s']}s")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=200, help="무필터 질의 수(층 균등 배분)")
    ap.add_argument("--seed", type=int, default=20261111)
    ap.add_argument("--filter-n", type=int, default=200, help="강한 필터 질의 수(ingr_codes가 있는 행에서 추출)")
    a = ap.parse_args(argv)
    print_summary(run(a.n, a.seed, a.filter_n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
