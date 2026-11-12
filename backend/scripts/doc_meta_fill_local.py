"""로컬 코퍼스 jsonl의 문서 메타(`doc_meta`) 칸 채움률 측정(읽기 전용, 원격 DB·네트워크 없음).

사용(저장소 루트): `backend/.venv/bin/python backend/scripts/doc_meta_fill_local.py [--json out.json]`

칸: `year`·`source_file`·`effective_date`(문서 메타 표 `app/db/doc_meta.py`가 청크에 넣는 세 칸)와
`issuer`·`doc_type`·`notice_no`·`base_date`(고시·파일 단위 칸). 칸 자체가 없는 청크는 "칸 없음"으로 따로 센다
(예전에 만든 jsonl은 세 칸이 없다: 재적재 전 상태). 비어 있음 = 칸 없음·None·빈 문자열.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from corpus_meta_coverage import source_of, wilson

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "mock" / "corpus"
FILES = ("l1_notice.jsonl", "l2_chunks.jsonl", "l3_eyak.jsonl", "l3_prmsn.jsonl")
DOC_META_FIELDS = ("year", "source_file", "effective_date")
BASE_FIELDS = ("issuer", "doc_type", "notice_no", "base_date")


def load_dedup(directory: Path = CORPUS) -> list[dict[str, Any]]:
    """`CorpusIndex`와 같은 규칙: 같은 chunk_id는 앞선 것 하나만."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for name in FILES:
        with (directory / name).open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                c = json.loads(line)
                if c["chunk_id"] in seen:
                    continue
                seen.add(c["chunk_id"])
                rows.append(c)
    return rows


def measure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_src[source_of(r)].append(r)
    out: dict[str, Any] = {}
    for src, rs in sorted(by_src.items()):
        n = len(rs)
        d: dict[str, Any] = {"n": n}
        for f in (*DOC_META_FIELDS, *BASE_FIELDS):
            absent = sum(1 for r in rs if f not in r)
            filled = sum(1 for r in rs if r.get(f) not in (None, "", []))
            d[f] = {"filled": filled, "absent_key": absent, "ci95": [round(x, 3) for x in wilson(filled, n)]}
        out[src] = d
    return {"total": len(rows), "by_source": out}


def render(m: dict[str, Any]) -> str:
    fields = (*DOC_META_FIELDS, *BASE_FIELDS)
    lines = [f"총 {m['total']}청크(chunk_id 중복 제거 후)", "", "| 소스 | n | " + " | ".join(fields) + " |", "|---|---:|" + "---:|" * len(fields)]
    for src, d in m["by_source"].items():
        cells = []
        for f in fields:
            x = d[f]
            cells.append(f"{x['filled']}/{d['n']}" + (f"(칸없음 {x['absent_key']})" if x["absent_key"] else ""))
        lines.append(f"| {src} | {d['n']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    m = measure(load_dedup())
    print(render(m))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
