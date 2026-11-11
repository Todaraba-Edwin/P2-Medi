"""AG-03 원격 읽기 전용 스모크: DB→CorpusIndex 로드 시간, 질의 ≤5개의 벡터·하이브리드 지연과 결과 건수.

원격 쓰기 없음(SELECT·SET만, 연결 read_only). 질의 임베딩 호출 ≤`MAX_EMBED_CALLS`회·$0.01 상한. 본문은 80자까지만 보인다. 연결 문자열·키는 출력하지 않는다.
사용: `.venv/bin/python scripts/ag03_remote_smoke.py` (백엔드 디렉터리에서)
"""

from __future__ import annotations

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from app.agent.tools import corpus_remote as cr  # noqa: E402
from app.agent.tools.corpus import ChunkFilter  # noqa: E402

MAX_EMBED_CALLS = 10


def main() -> int:
    factory = cr.psycopg_conn_factory()
    t0 = time.perf_counter()
    chunks, cols = cr.load_chunks_from_db(factory)
    t_fetch = time.perf_counter() - t0
    t1 = time.perf_counter()
    from app.agent.tools.corpus import CorpusIndex  # noqa: PLC0415

    idx = CorpusIndex(chunks)
    t_index = time.perf_counter() - t1
    print(f"로드: 청크 {len(idx):,}, 읽은 열 {len(cols)}(선택 열 {[c for c in cols if c in cr.OPTIONAL_COLUMNS]}), SELECT {t_fetch:.1f}s + 인덱스 {t_index:.1f}s = {t_fetch + t_index:.1f}s")

    embed = cr.openai_query_embedder(max_usd=0.01)
    search = cr.PgVectorSearch(factory, embed)

    preg = next(c for c in idx.chunks if c.get("chunk_kind") == "l2_preg" and c.get("ingr_codes"))
    eyak = next(c for c in idx.chunks if c.get("chunk_kind") == "l3_eyak_section" and c.get("item_seq"))
    combo = next(c for c in idx.chunks if c.get("chunk_kind") == "l2_combo" and c.get("pair_id"))
    cases = [
        ("전역(필터 없음)", "임신 중에 먹으면 안 되는 약", ChunkFilter()),
        ("약한 필터 layer=L3", "술과 함께 먹어도 되나요", ChunkFilter(layers=frozenset({"L3"}))),
        ("강한 필터 ingr_codes+L2", "임부금기 이유가 무엇인가요", ChunkFilter(layers=frozenset({"L2"}), ingr_codes=frozenset({preg["ingr_codes"][0]}))),
        ("강한 필터 item_seq", "같이 먹으면 안 되는 약", ChunkFilter(item_seq=eyak["item_seq"])),
        ("강한 필터 pair_id", "병용금기 사유", ChunkFilter(pair_ids=frozenset({combo["pair_id"]}))),
    ]
    print("| 경우 | SQL 모드 | 벡터 행 | 임베딩 ms | SQL ms | BM25 ms | 하이브리드 총 ms | 하이브리드 hit | 필터 위반 | via |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    totals: list[float] = []
    for name, q, flt in cases:
        search(q, k=100, filters=flt)  # 임베딩 캐시를 채우고 SQL만 측정하려는 것이 아니라 첫 호출(콜드) 포함 값을 그대로 쓴다
        st = search.last_stats
        tb = time.perf_counter()
        idx.search(q, flt, top_k=10)
        bm_ms = (time.perf_counter() - tb) * 1000
        th = time.perf_counter()
        hits = idx.search(q, flt, top_k=10, vector_fn=search)  # 임베딩은 캐시 적중이라 SQL+BM25+RRF 시간
        hy_ms = (time.perf_counter() - th) * 1000
        totals.append(hy_ms)
        viol = sum(1 for h in hits if not idx.matches(h.chunk, flt))
        via = {}
        for h in hits:
            via[h.via] = via.get(h.via, 0) + 1
        print(f"| {name} | {st.mode} | {st.rows} | {st.embed_ms:.0f} | {st.sql_ms:.0f} | {bm_ms:.0f} | {hy_ms:.0f} | {len(hits)} | {viol} | {via} |")
        if hits:
            print(f"|  ↳ 1위 | {hits[0].chunk['chunk_id']} | {hits[0].chunk['text'][:80]!r} | | | | | | | |")
        if st.error:
            print(f"  오류 종류: {st.error}")
    e = embed.embedder  # type: ignore[attr-defined]
    print(f"임베딩 실호출 {e.calls}회(캐시 {e.cached_batches}), 토큰 {e.tokens}, ${e.spent:.6f}; 하이브리드 평균 {statistics.mean(totals):.0f}ms 최대 {max(totals):.0f}ms (n={len(totals)})")
    assert e.calls <= MAX_EMBED_CALLS
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
