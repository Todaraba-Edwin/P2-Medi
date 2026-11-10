"""BE-10 "코드 없음" 허가 제품 표본 시트(Recap 5-②). 호출 0, 로컬 전용 산출물.

사전의 `code_link="none"` 제품(KIDS 성분코드를 못 얻은 허가 제품)에서 시드 고정 무작위 표본을 뽑아 CSV로 만든다.
판정 열(연결실패 / KIDS목록밖 / 판단불가)은 비워 두고, 후속으로 별도 모델·사람이 채운다. 채운 뒤 `--tally`로 비율을 센다.

  .venv/bin/python scripts/nocode_sample.py                 표본 100개 CSV 생성 (data/mock/review/nocode_sample.csv)
  .venv/bin/python scripts/nocode_sample.py --tally [CSV]   판정 열을 세어 비율·Wilson 95% 구간 출력

층화: 전문·일반(·표기 없음) 비율을 코드 없음 전체에서 보존한다(최대 잔여 방식으로 개수 배분).
표본 크기가 작아 비율은 k/n과 구간으로만 읽는다(유의성 주장 금지, 9.1절).
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict  # noqa: E402

REVIEW_DIR = Path(DEFAULT_DICT_PATH).resolve().parents[1] / "review"
DEFAULT_CSV = REVIEW_DIR / "nocode_sample.csv"
SEED = 20261110
SAMPLE_SIZE = 100
VERDICTS = ("연결실패", "KIDS목록밖", "판단불가")
COLUMNS = ["item_seq", "product_name", "entp", "ingr_en", "prescription", "dict_ingredient_names", "edi_codes", "cancelled", "sources", "verdict", "note"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def allocate(strata: dict[str, int], total: int) -> dict[str, int]:
    """층별 개수를 비율대로 배분(최대 잔여 방식). 합이 total이고 층 크기를 넘지 않는다."""
    size = sum(strata.values())
    if size == 0:
        return {k: 0 for k in strata}
    raw = {k: total * v / size for k, v in strata.items()}
    alloc = {k: min(int(r), strata[k]) for k, r in raw.items()}
    order = sorted(strata, key=lambda k: (-(raw[k] - int(raw[k])), k))
    i = 0
    while sum(alloc.values()) < min(total, size):
        k = order[i % len(order)]
        if alloc[k] < strata[k]:
            alloc[k] += 1
        i += 1
    return alloc


def draw_sample(dd: DrugDict, size: int = SAMPLE_SIZE, seed: int = SEED) -> list[dict[str, Any]]:
    """code_link=none 제품에서 층화 무작위 추출. 같은 사전·시드면 같은 결과."""
    nocode = [(i, p) for i, p in enumerate(dd.products) if p.get("code_link", "none") == "none"]
    groups: dict[str, list[int]] = {}
    for i, p in nocode:
        groups.setdefault(p.get("prescription") or "표기없음", []).append(i)
    alloc = allocate({k: len(v) for k, v in groups.items()}, size)
    rng = random.Random(seed)  # noqa: S311 - 재현용 시드 고정(암호 용도 아님)
    picked: list[int] = []
    for k in sorted(groups):
        picked.extend(rng.sample(groups[k], alloc[k]))
    picked.sort(key=lambda i: dd.products[i].get("item_seq") or "")
    rows = []
    for i in picked:
        p = dd.products[i]
        ing_names = "; ".join(dd.ingredients[j]["display"] for j in p.get("ingredient_ids", []))
        rows.append({
            "item_seq": p.get("item_seq") or "", "product_name": p["name"], "entp": p.get("entp") or "", "ingr_en": p.get("ingr_en") or "",
            "prescription": p.get("prescription") or "표기없음", "dict_ingredient_names": ing_names, "edi_codes": ";".join(p.get("edi_codes", [])),
            "cancelled": "Y" if p.get("cancelled") else "N", "sources": ";".join(p.get("sources", [])), "verdict": "", "note": "",
        })
    return rows


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # Excel 호환 BOM
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def tally_csv(path: Path) -> dict[str, Any]:
    """판정 열을 센다. 알 수 없는 값이 있으면 ValueError(오타를 조용히 넘기지 않는다)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    counts: Counter[str] = Counter()
    for r in rows:
        v = (r.get("verdict") or "").strip()
        if v and v not in VERDICTS:
            raise ValueError(f"알 수 없는 판정 값 {v!r} (item_seq={r.get('item_seq')}). 허용: {', '.join(VERDICTS)}")
        counts[v or "미판정"] += 1
    judged = sum(counts[v] for v in VERDICTS)
    out: dict[str, Any] = {"total": len(rows), "judged": judged, "unjudged": counts["미판정"], "verdicts": {}}
    for v in VERDICTS:
        lo, hi = wilson(counts[v], judged)
        out["verdicts"][v] = {"k": counts[v], "n": judged, "rate": round(counts[v] / judged, 4) if judged else None, "wilson95": [round(lo, 4), round(hi, 4)]}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tally", nargs="?", const=str(DEFAULT_CSV), default=None, metavar="CSV", help="판정 열을 세어 비율을 출력")
    ap.add_argument("--size", type=int, default=SAMPLE_SIZE)
    ap.add_argument("--out", default=str(DEFAULT_CSV))
    args = ap.parse_args(argv)
    if args.tally is not None:
        try:
            t = tally_csv(Path(args.tally))
        except (ValueError, OSError) as exc:
            print(f"오류: {exc}")
            return 2
        print(f"표본 {t['total']}개, 판정됨 {t['judged']}, 미판정 {t['unjudged']}")
        for v, c in t["verdicts"].items():
            rate = "-" if c["rate"] is None else f"{c['rate']:.1%}"
            print(f"- {v}: {c['k']}/{c['n']} ({rate}) Wilson95 [{c['wilson95'][0]:.2f}–{c['wilson95'][1]:.2f}]")
        if t["judged"] <= 8:
            print("판정 수가 8 이하라 비율을 해석하지 않는다.")
        return 0
    dd = DrugDict.load()
    rows = draw_sample(dd, args.size)
    write_csv(Path(args.out), rows)
    comp = Counter(r["prescription"] for r in rows)
    total = sum(1 for p in dd.products if p.get("code_link", "none") == "none")
    print(f"코드 없음 {total:,}건에서 {len(rows)}개 추출(시드 {SEED}) → {args.out}")
    print(f"구성: {dict(comp)} (판정 열은 비워 둠)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
