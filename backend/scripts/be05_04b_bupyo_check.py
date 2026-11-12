"""BE-05 ④b: 별표 1·3 행 청크가 로컬 BM25로 찾아지는지 확인(읽기 전용, 원격·네트워크 없음).

사용(저장소 루트): `backend/.venv/bin/python backend/scripts/be05_04b_bupyo_check.py [--json out.json]`

질의 3건은 규칙으로 고른다(사람이 임의로 고르지 않는다):
  Q1 별표 1: 연번 순 정렬 뒤 가운데 행(성분쌍) → "A B 병용금기"
  Q2 별표 3: 연번 순 정렬 뒤 가운데 행 → "성분 임부금기 등급"
  Q3 임의: `random.Random(SEED)`로 별표 1 행 중 비고가 있는 행 1개 → 일상어 형태
정답 = 같은 별표·같은 연번의 행 청크(별표 1은 성분쌍이 같은 행도 정답으로 인정). 순위는 BM25(필터 없음 / 계층 L1)에서 정답 중 가장 위 순위.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.tools.corpus import ChunkFilter, CorpusIndex, load_local_corpus  # noqa: E402

SEED = 2026
TOP_K = 100
_NO_RE = re.compile(r"연번 (\d+)")


def _no(c: dict[str, Any]) -> int:
    m = _NO_RE.search(c.get("locator", ""))
    return int(m.group(1)) if m else -1


def pick_queries(idx: CorpusIndex) -> list[dict[str, Any]]:
    b1 = sorted((c for c in idx.chunks if c["chunk_kind"] == "l1_bupyo1_row"), key=_no)
    b3 = sorted((c for c in idx.chunks if c["chunk_kind"] == "l1_bupyo3_row"), key=_no)
    mid1, mid3 = b1[len(b1) // 2], b3[len(b3) // 2]
    rng = random.Random(SEED)  # noqa: S311 - 재현 가능한 질의 선택(보안 용도 아님)
    with_note = [c for c in b1 if "비고:" in c["text"]]
    rnd = rng.choice(with_note)
    a1, a2 = mid1["ingr_names"][:2]
    out = [
        {"id": "Q1", "rule": "별표 1 연번 가운데 행", "query": f"{a1} {a2} 병용금기", "gold_row": mid1},
        {"id": "Q2", "rule": "별표 3 연번 가운데 행", "query": f"{mid3['ingr_names'][0]} 임부금기 등급", "gold_row": mid3},
        {"id": "Q3", "rule": f"임의(seed {SEED}, 별표 1 비고 있는 행)",
         "query": f"{rnd['ingr_names'][0]}와 {rnd['ingr_names'][1]} 같이 먹어도 되나요 병용금기 비고", "gold_row": rnd},
    ]
    for q in out:
        r = q["gold_row"]
        names = {x.lower() for x in r["ingr_names"]}
        # 별표 1은 성분쌍이 같은 행(순서 무관)도 정답으로 본다
        q["gold_ids"] = [c["chunk_id"] for c in idx.chunks if c["chunk_kind"] == r["chunk_kind"]
                         and (c["chunk_id"] == r["chunk_id"] or (r["chunk_kind"] == "l1_bupyo1_row" and {x.lower() for x in c["ingr_names"]} == names))]
    return out


def run(idx: CorpusIndex) -> list[dict[str, Any]]:
    res = []
    for q in pick_queries(idx):
        row = q.pop("gold_row")
        gold = set(q["gold_ids"])
        entry: dict[str, Any] = {**q, "gold_locator": row["locator"], "gold_text": row["text"], "has_col_names": all(k in row["text"] for k in ("연번:", "유효성분")),
                                 "parent_is_table": bool(row.get("parent_id"))}
        for label, flt in (("no_filter", ChunkFilter()), ("layer_L1", ChunkFilter(layers=frozenset({"L1"})))):
            hits = idx.search(q["query"], flt, top_k=TOP_K)
            ranks = [i for i, h in enumerate(hits, start=1) if h.chunk["chunk_id"] in gold]
            entry[f"rank_{label}"] = ranks[0] if ranks else None
            entry[f"top5_{label}"] = [(h.chunk["locator"], h.chunk["chunk_kind"]) for h in hits[:5]]
        res.append(entry)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    idx = load_local_corpus()
    if idx is None:
        print("로컬 코퍼스 없음(data/mock/corpus)")
        return 1
    res = run(idx)
    print("| id | 규칙 | 질의 | 정답 locator | 순위(필터 없음) | 순위(L1) | 열 이름 포함 | top-5 in 필터 없음 |")
    print("|---|---|---|---|---|---|---|---|")
    for e in res:
        print(f"| {e['id']} | {e['rule']} | {e['query']} | {e['gold_locator']} | {e['rank_no_filter']} | {e['rank_layer_L1']} | {e['has_col_names']} | {e['top5_no_filter']} |")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
