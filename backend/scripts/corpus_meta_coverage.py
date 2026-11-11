"""BE-05 메타데이터 채움·연결률 측정(읽기 전용, 로컬 jsonl만 본다. 원격 DB·네트워크·코퍼스 수정 없음).

사용(저장소 루트): `backend/.venv/bin/python backend/scripts/corpus_meta_coverage.py [--json out.json]`
입력: `data/mock/corpus/{l1_notice,l2_chunks,l3_eyak,l3_prmsn}.jsonl`.
소스 구분: 별표 1·별표 2·별표 3·조문(L1 고시), L2 파일데이터(병용·임부·연령), L3 e약은요, L3 허가 상세.
`연도`는 전용 칸이 없어 `notice_no` 앞 4자리(없으면 `base_date` 앞 4자리)에서 얻을 수 있는지로 본다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "mock" / "corpus"
FILES = ["l1_notice.jsonl", "l2_chunks.jsonl", "l3_eyak.jsonl", "l3_prmsn.jsonl"]
FIELDS = ["doc_type", "year", "issuer", "notice_no", "base_date", "locator", "layer", "ingr_codes"]
YEAR_RE = re.compile(r"^(19|20)\d{2}")


def source_of(r: dict[str, Any]) -> str:
    k = r["chunk_kind"]
    if k.startswith("l1_bupyo1"):
        return "별표1(병용금기)"
    if k.startswith("l1_bupyo2"):
        return "별표2(특정연령)"
    if k.startswith("l1_bupyo3"):
        return "별표3(임부)"
    if k.startswith("l1_notice"):
        return "고시 조문"
    if k.startswith("l2_"):
        return "L2 " + k[3:]
    if k.startswith("l3_eyak"):
        return "L3 e약은요"
    if k.startswith("l3_prmsn"):
        return "L3 허가 상세"
    return k


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def filled(r: dict[str, Any], f: str) -> bool:
    if f == "year":
        return bool(YEAR_RE.match(str(r.get("notice_no") or ""))) or bool(YEAR_RE.match(str(r.get("base_date") or "")))
    v = r.get(f)
    return bool(v)  # 빈 문자열·빈 목록·None은 비어 있음


def load() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for f in FILES:
        with (CORPUS / f).open(encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh)
    return rows


def measure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_src[source_of(r)].append(r)
    fill: dict[str, Any] = {}
    for s, rs in sorted(by_src.items()):
        fill[s] = {"n": len(rs), **{f: sum(filled(r, f) for r in rs) for f in FIELDS}}
    link: dict[str, Any] = {}
    for s in ("L3 e약은요", "L3 허가 상세"):
        rs = by_src[s]
        n = len(rs)
        empty_codes = sum(1 for r in rs if not r.get("ingr_codes"))
        status = Counter(r.get("code_status") or "" for r in rs)
        no_link = sum(1 for r in rs if (r.get("code_status") in ("none", "", None)) or not r.get("ingr_codes"))
        seqs: dict[str, dict[str, Any]] = {}
        for r in rs:
            seqs.setdefault(r.get("item_seq") or "", r)
        pn = len(seqs)
        p_empty = sum(1 for r in seqs.values() if not r.get("ingr_codes"))
        p_no_link = sum(1 for r in seqs.values() if (r.get("code_status") in ("none", "", None)) or not r.get("ingr_codes"))
        # 제품 단위의 code_status 불일치(같은 제품 안에서 청크마다 다른 값) 여부
        per_seq = defaultdict(set)
        for r in rs:
            per_seq[r.get("item_seq") or ""].add(r.get("code_status"))
        mixed = sum(1 for v in per_seq.values() if len(v) > 1)
        link[s] = {
            "chunks": n, "chunks_empty_ingr_codes": empty_codes, "chunks_no_link(none|empty)": no_link,
            "code_status": dict(status), "products": pn, "products_empty_ingr_codes": p_empty, "products_no_link": p_no_link,
            "products_with_mixed_code_status": mixed,
            "ci_chunks_no_link": [round(x, 4) for x in wilson(no_link, n)],
            "ci_products_no_link": [round(x, 4) for x in wilson(p_no_link, pn)],
        }
    lic: dict[str, Counter[str]] = defaultdict(Counter)
    for s, rs in by_src.items():
        for r in rs:
            lic[s][r.get("license") or "(빈 값)"] += 1
    return {
        "total_chunks": len(rows),
        "chunk_id_unique": len({r["chunk_id"] for r in rows}),
        "fill": fill,
        "link": link,
        "license": {s: dict(c) for s, c in sorted(lic.items())},
    }


def render(m: dict[str, Any]) -> str:
    out = [f"총 {m['total_chunks']}청크(고유 chunk_id {m['chunk_id_unique']})", "", "| 소스 | 청크 | " + " | ".join(FIELDS) + " |", "|---|---:|" + "---:|" * len(FIELDS)]
    for s, d in m["fill"].items():
        out.append(f"| {s} | {d['n']} | " + " | ".join(f"{d[f]}/{d['n']}" for f in FIELDS) + " |")
    out += ["", "연결(L3):"]
    for s, d in m["link"].items():
        out.append(f"- {s}: {json.dumps(d, ensure_ascii=False)}")
    out += ["", "license 분포:"]
    for s, c in m["license"].items():
        out.append(f"- {s}: {json.dumps(c, ensure_ascii=False)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, help="결과 JSON 저장 경로(data/ 아래 권장)")
    a = ap.parse_args(argv)
    m = measure(load())
    print(render(m))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
