"""BE-05 근거 코퍼스 임베딩 실행(BE-05-03 D 이행, 2026-11-11).

  plan                        호출 0. 전체 청크의 고유 텍스트 수·배치·토큰 근사·어림 비용
  run --max-usd 0.45 [--limit N]   고유 텍스트만 text-embedding-3-small(1536, dimensions 미지정)로 임베딩

- 청크 텍스트를 sha1로 중복 제거해 고유 텍스트만 호출한다(같은 텍스트를 공유하는 청크는 벡터를 복사해 쓴다).
- 배치 256개·6만 토큰(근사) 이하, 429·5xx 재시도(Retry-After 존중), 캐시(app.llm.cache)·원장(app.llm.ledger)·`--max-usd` 하드 상한 경유.
- 저장: data/mock/corpus/embeddings/{vectors.npy, index.json(해시→행)}. 진행 중에는 `vectors.partial.bin`·`index.partial.jsonl`에 배치마다
  덧붙이므로 중단되어도 같은 명령으로 재개한다. 모두 끝나면 npy·json으로 마무리한다.
- 키는 헤더로만 쓰고 출력하지 않는다(resolve_key). 오류 문구에도 키·접속 문자열을 넣지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from app.security.redact import install_excepthook  # noqa: E402

install_excepthook()

from build_corpus_l2 import OUT_DIR, read_chunks  # noqa: E402
from embed_compare import CapReached, Embedder, _ensure_cache_importable, estimate_tokens, resolve_key  # noqa: E402
from load_corpus import ALL_FILES  # noqa: E402

EMB_DIR = OUT_DIR / "embeddings"
MODEL_SIZE = "small"
MODEL_ID = "text-embedding-3-small"
DIM = 1536
PRICE_PER_M = 0.02
BATCH_ITEMS = 256
BATCH_TOKENS = 60_000
ENDPOINT = "https://api.openai.com/v1/embeddings"
MAX_RETRIES = 8


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 - 중복 제거 키(보안 용도 아님)


def load_all_chunks(selected: bool = False) -> list[dict[str, Any]]:
    d = OUT_DIR / "selected" if selected else OUT_DIR
    paths = [OUT_DIR / ALL_FILES[0], *(d / n for n in ALL_FILES[1:])]
    return [c for p in paths for c in read_chunks(p)]


def unique_texts(chunks: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """(해시, 텍스트) 목록. 해시 순으로 정렬해 결정적이다."""
    seen: dict[str, str] = {}
    for c in chunks:
        seen.setdefault(text_hash(c["text"]), c["text"])
    return sorted(seen.items())


def make_batches(items: Sequence[tuple[str, str]], max_items: int = BATCH_ITEMS, max_tokens: int = BATCH_TOKENS) -> list[list[tuple[str, str]]]:
    out: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    cur_t = 0.0
    for h, t in items:
        tk = estimate_tokens(t[:3000])
        if cur and (len(cur) >= max_items or cur_t + tk > max_tokens):
            out.append(cur)
            cur, cur_t = [], 0.0
        cur.append((h, t))
        cur_t += tk
    if cur:
        out.append(cur)
    return out


# --------------------------------------------------------------------------- 저장(재개 가능)

class Store:
    def __init__(self, directory: Path = EMB_DIR, dim: int = DIM) -> None:
        self.dir, self.dim = directory, dim
        self.bin = directory / "vectors.partial.bin"
        self.idx = directory / "index.partial.jsonl"
        self.npy = directory / "vectors.npy"
        self.index_json = directory / "index.json"

    def done_hashes(self) -> dict[str, int]:
        """진행 중 파일에서 해시→행. 벡터 파일이 인덱스보다 길면 잘라 맞춘다(중간 중단 복구)."""
        if self.index_json.exists():
            return json.loads(self.index_json.read_text(encoding="utf-8"))["rows"]
        rows: dict[str, int] = {}
        if self.idx.exists():
            for ln in self.idx.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    rows[json.loads(ln)] = len(rows)
        if self.bin.exists():
            want = len(rows) * self.dim * 4
            if self.bin.stat().st_size > want:
                with open(self.bin, "r+b") as f:
                    f.truncate(want)
            elif self.bin.stat().st_size < want:
                raise RuntimeError("벡터 파일이 인덱스보다 짧다. 진행 파일을 확인한다")
        return rows

    def append(self, hashes: Sequence[str], vectors: Any) -> None:
        import numpy as np

        arr = np.asarray(vectors, dtype="<f4").reshape(len(hashes), self.dim)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.bin, "ab") as f:
            f.write(arr.tobytes())
            f.flush()
        with open(self.idx, "a", encoding="utf-8") as f:
            for h in hashes:
                f.write(json.dumps(h) + "\n")

    def finalize(self, order: Sequence[str]) -> dict[str, Any]:
        """모든 고유 텍스트가 끝났을 때 vectors.npy + index.json을 쓴다(행 순서는 진행 순서 그대로)."""
        import numpy as np

        rows = self.done_hashes()
        missing = [h for h in order if h not in rows]
        if missing:
            raise RuntimeError(f"임베딩이 끝나지 않았다: 남은 {len(missing)}개")
        mat = np.fromfile(self.bin, dtype="<f4").reshape(len(rows), self.dim)
        np.save(self.npy, mat)
        self.index_json.write_text(json.dumps({"model": MODEL_ID, "dim": self.dim, "rows": rows}), encoding="utf-8")
        return {"rows": len(rows), "npy_mb": round(self.npy.stat().st_size / 1048576, 1)}


# --------------------------------------------------------------------------- 호출

def http_embed(model_id: str, texts: list[str], key: str, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """실호출 1회(429·5xx 재시도). 키는 헤더로만 쓴다."""
    import httpx

    for attempt in range(MAX_RETRIES):
        try:
            r = httpx.post(ENDPOINT, json={"model": model_id, "input": texts, "encoding_format": "base64"},
                           headers={"Authorization": f"Bearer {key}"}, timeout=180)
        except httpx.HTTPError as exc:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"임베딩 네트워크 오류 {type(exc).__name__}") from None
            sleep(min(2 ** attempt, 30))
            continue
        if r.status_code == 200:
            body = r.json()
            rows = sorted(body["data"], key=lambda d: d["index"])
            return {"data": [d["embedding"] for d in rows], "tokens": int(body["usage"]["total_tokens"])}
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
            wait = float(r.headers.get("retry-after") or 0) or min(2 ** attempt * 2, 60)
            print(f"  재시도 {attempt + 1}: status={r.status_code}, {wait:.0f}초 대기", flush=True)
            sleep(wait)
            continue
        raise RuntimeError(f"임베딩 호출 실패 status={r.status_code} body={r.text[:160]}")
    raise RuntimeError("임베딩 재시도 횟수 초과")


def run_embedding(items: Sequence[tuple[str, str]], store: Store, emb: Embedder, limit: int | None = None,
                  log: Callable[[str], None] = print) -> dict[str, Any]:
    """남은 고유 텍스트를 배치로 임베딩해 저장한다. 상한 도달 시 CapReached로 멈추고(이미 저장된 것은 유지) 재개한다."""
    import numpy as np
    from embed_compare import decode_b64_vectors

    from app.llm.cache import cache_mode  # noqa: F401  (모드 검증)

    done = store.done_hashes()
    todo = [(h, t) for h, t in items if h not in done]
    if limit is not None:
        todo = todo[: max(limit - len(done), 0)] if limit else []
    bs = make_batches(todo)
    t0 = time.time()
    for bi, batch in enumerate(bs):
        resp = emb.embed_batch([t for _, t in batch], f"embed_corpus:{bi}")
        vecs = np.frombuffer(decode_b64_vectors(resp), dtype="<f4") if isinstance(resp, list) else None
        if vecs is None or vecs.size != len(batch) * store.dim:
            raise ValueError(f"응답 차원 불일치: {None if vecs is None else vecs.size // max(len(batch), 1)}")
        store.append([h for h, _ in batch], vecs)
        if bi % 10 == 0 or bi == len(bs) - 1:
            log(f"  배치 {bi + 1}/{len(bs)} 완료, 이 실행 ${emb.spent:.4f}, 토큰 {emb.tokens:,}, {time.time() - t0:.0f}초")
    return {"batches": len(bs), "calls": emb.calls, "cached_batches": emb.cached_batches, "tokens": emb.tokens,
            "usd": round(emb.spent, 4), "seconds": round(time.time() - t0, 1)}


def plan(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    items = unique_texts(chunks)
    bs = make_batches(items)
    tokens = sum(estimate_tokens(t) for _, t in items)
    return {"chunks": len(chunks), "unique_texts": len(items), "batches": len(bs), "approx_tokens": int(tokens),
            "approx_usd": round(tokens / 1e6 * PRICE_PER_M, 4), "model": MODEL_ID, "dim": DIM, "executed": False}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--max-usd", type=float, required=True)
    r.add_argument("--limit", type=int, help="전체 고유 텍스트 중 앞쪽 N개까지만(소액 시험)")
    r.add_argument("--selected", action="store_true")
    args = ap.parse_args(argv)
    chunks = load_all_chunks(getattr(args, "selected", False))
    if args.cmd == "plan":
        print(json.dumps(plan(chunks), ensure_ascii=False, indent=2))
        return 0
    key = resolve_key()
    if not key:
        print("OPENAI_API_KEY를 찾지 못했다", file=sys.stderr)
        return 2
    os.environ.setdefault("LLM_CACHE", "record")
    _ensure_cache_importable()
    items = unique_texts(chunks)
    store = Store()
    emb = Embedder(MODEL_SIZE, args.max_usd, lambda model_id, texts: http_embed(model_id, texts, key))
    try:
        res = run_embedding(items, store, emb, args.limit)
    except CapReached as e:
        print(f"상한 중단: {e}")
        return 3
    done = store.done_hashes()
    res["stored_rows"] = len(done)
    res["remaining"] = sum(1 for h, _ in items if h not in done)
    if res["remaining"] == 0 and not store.index_json.exists():
        res["finalize"] = store.finalize([h for h, _ in items])
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
