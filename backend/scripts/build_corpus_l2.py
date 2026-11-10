"""BE-05 L2 코퍼스 빌더(근거 코퍼스 ③ 중 L2 사유·상세정보 + L1 별표 2 행). 로컬 파일만 읽고 쓴다(원격 DB·API 호출 0).

만드는 청크(BE-05-02 A 확정 단위, `data/mock/chunk_trial/chunk_schema.md` 참조):
  l2_combo        병용금기 고유 조합 1건 = 성분쌍 단위(KIDS 병용 JSON 스트리밍)
  l2_preg/l2_age  임부·연령금기 상세정보 성분 단위(성분명·종류·조건·문구). 임부 M등급은 원문 그대로(RFP-17)
  l1_bupyo2_table 별표 2 표 청크(제목·열 이름·쪽), 행 청크의 parent_id가 가리킨다
  l1_bupyo2_row   별표 2 행 + 열 이름 + 표 제목·연번

출력: `data/mock/corpus/l2_chunks.jsonl`(로컬 전용, 커밋 금지), `manifest.json`(종류별 청크 수·해시).
같은 입력이면 chunk_id·파일 해시가 같아야 한다(결정적). 판정은 하지 않는다(5.1절 (3): 근거 코퍼스에는 설명용 문장만).

사용(작업 위치 `backend/`): `.venv/bin/python scripts/build_corpus_l2.py build [--check]` / `verify`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from chunk_trial import (  # noqa: E402
    AGE_CSV,
    BUPYO2,
    BUPYO2_TITLE,
    L2_JSON,
    PREG_CSV,
    _cp949_rows,
    _strip_code,
    bupyo2_pairs,
    iter_json_array,
    load_bupyo2,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "mock" / "corpus"
CHUNKS_PATH = OUT_DIR / "l2_chunks.jsonl"
MANIFEST_PATH = OUT_DIR / "manifest.json"

BASE_DATE = "2026-07-21"
ISSUER_KIDS = "한국의약품안전관리원"
ISSUER_MFDS = "식품의약품안전처"
LICENSE_KIDS = "공공저작물 제2유형(출처표시, 상업적 이용금지)"
LICENSE_GOSI = "미확인(정부 고시 재배포 법률 검토 전, 저장소에 원본을 올리지 않음)"
BUPYO2_NOTICE_NO = "20260052"  # 고시 제2026-52호(연도 4자리 + 번호 4자리)
BUPYO2_PAGES = "45~50쪽"
NOTICE_RE = re.compile(r"^\d{8}$")

# 청크 필드(순서 고정). chunk_kind는 종류별 집계·필터용 추가 필드다.
FIELDS = (
    "chunk_id", "chunk_kind", "parent_id", "refs", "pair_id", "layer", "issuer", "doc_type", "notice_no", "base_date",
    "locator", "ingr_codes", "ingr_names", "license", "text", "source_ref",
)

# L3 청크에만 채우는 선택 열(L2 청크는 이 열 없이 저장되고, 적재 때 빈 문자열로 채운다)
EXTRA_FIELDS = ("item_seq", "item_name", "section", "code_status")


# --------------------------------------------------------------------------- ID 규칙

def sha(s: str, n: int = 16) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]  # noqa: S324 - 식별용 해시(보안 용도 아님)


def make_pair_id(code_a: str, code_b: str) -> str:
    """성분코드 두 개를 정렬해 `+`로 잇는다. 순서와 무관하게 같은 값."""
    lo, hi = sorted((code_a.strip(), code_b.strip()))
    return f"{lo}+{hi}"


def make_chunk_id(kind: str, key: str, text: str) -> str:
    """`{종류 접두}-{sha1(키 + 본문)[:16]}`. 같은 키·같은 본문이면 재적재해도 같은 값이다."""
    prefix = {"l2_combo": "l2c", "l2_preg": "l2p", "l2_age": "l2a", "l1_bupyo2_table": "l1t", "l1_bupyo2_row": "l1r"}[kind]
    raw = kind + "|" + key + "\x1f" + text
    return f"{prefix}-{sha(raw)}"


def norm_notice(v: str) -> str:
    v = (v or "").strip()
    return v if NOTICE_RE.match(v) else ""


def _chunk(kind: str, key: str, text: str, **kw: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "chunk_id": make_chunk_id(kind, key, text), "chunk_kind": kind, "parent_id": None, "refs": [], "pair_id": None,
        "layer": "", "issuer": "", "doc_type": "", "notice_no": "", "base_date": BASE_DATE, "locator": "",
        "ingr_codes": [], "ingr_names": [], "license": "", "text": text, "source_ref": "",
    }
    c.update(kw)
    return {f: c[f] for f in FIELDS}


# --------------------------------------------------------------------------- L2 병용 조합(성분쌍)

def build_combo_chunks(json_path: Path | None = None) -> list[dict[str, Any]]:
    src = json_path or L2_JSON
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for o in iter_json_array(src):
        m = o.get("metadata") or {}
        a = (m.get("성분코드A", ""), m.get("성분명A", ""))
        b = (m.get("성분코드B", ""), m.get("성분명B", ""))
        if not a[0] or not b[0]:
            continue
        a, b = sorted((a, b))
        reason, gosi = m.get("금기사유", ""), m.get("고시번호", "")
        key = (a[0], b[0], reason, gosi)
        rec = seen.get(key)
        if rec is None:
            seen[key] = {"a": a, "b": b, "reason": reason, "gosi": gosi, "remark": (m.get("비고") or "").strip(), "first_id": o.get("id", ""), "n": 1}
        else:
            rec["n"] += 1
    out = []
    for key in sorted(seen):
        r = seen[key]
        (ca, na), (cb, nb) = r["a"], r["b"]
        text = f"병용금기: {na} + {nb}. 사유: {r['reason']} (고시 {r['gosi']})"
        if r["remark"]:
            text += f" 비고: {r['remark']}"
        n = r["n"]
        loc = f"병용금기_데이터.json 항목 {r['first_id']}" + (f" 외 {n - 1}건(같은 성분쌍·사유·고시의 제품 쌍)" if n > 1 else "")
        out.append(_chunk(
            "l2_combo", f"{ca}+{cb}|{r['reason']}|{r['gosi']}", text,
            pair_id=make_pair_id(ca, cb), layer="L2", issuer=ISSUER_KIDS, doc_type="파일데이터", notice_no=norm_notice(r["gosi"]),
            locator=loc, ingr_codes=[ca, cb], ingr_names=[na, nb], license=LICENSE_KIDS,
            source_ref="한국의약품안전관리원 병용금기약물(AI 학습용)|병용금기_데이터.json",
        ))
    return out


# --------------------------------------------------------------------------- L2 임부·연령 상세정보(성분 단위)

def _rows_label(rows: list[int]) -> str:
    rows = sorted(rows)
    head = ",".join(str(r) for r in rows[:10])
    return head + (f" 외 {len(rows) - 10}행" if len(rows) > 10 else "")


def build_detail_chunks(preg_rows: Sequence[dict[str, str]] | None = None, age_rows: Sequence[dict[str, str]] | None = None,
                        preg_name: str = PREG_CSV.name, age_name: str = AGE_CSV.name) -> list[dict[str, Any]]:
    preg = _cp949_rows(PREG_CSV) if preg_rows is None else preg_rows
    age = _cp949_rows(AGE_CSV) if age_rows is None else age_rows
    acc: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, rows in (("l2_preg", preg), ("l2_age", age)):
        for i, r in enumerate(rows, start=1):  # 행 번호 = 헤더를 뺀 데이터 행 번호(1부터)
            code = (r.get("성분코드") or "").strip()
            phrase = (r.get("상세정보") or "").strip()  # 원문 그대로(앞뒤 공백만 제거)
            if not code or not phrase:
                continue
            if kind == "l2_preg":
                cond = f"임부금기 {(r.get('금기등급') or '').strip()}등급"  # M은 M으로 둔다(1·2로 환산 금지, RFP-17)
            else:
                cond = " ".join(f"연령금기 {_strip_code(r.get('특정연령', ''))}{_strip_code(r.get('특정연령단위', ''))} {_strip_code(r.get('연령처리조건', ''))}".split())
            d = acc.setdefault((kind, code), {"names": set(), "items": set(), "notices": set(), "rows": []})
            d["names"].add((r.get("성분명") or "").strip())
            d["items"].add((cond, phrase))
            n = norm_notice(r.get("고시번호", ""))
            if n:
                d["notices"].add(n)
            d["rows"].append(i)
    out = []
    for (kind, code) in sorted(acc):
        d = acc[(kind, code)]
        names = sorted(x for x in d["names"] if x)
        body = "\n".join(f"{c}: {p}" for c, p in sorted(d["items"]))
        text = f"{' / '.join(names)}\n{body}"
        fname = preg_name if kind == "l2_preg" else age_name
        out.append(_chunk(
            kind, f"{kind}|{code}", text,
            layer="L2", issuer=ISSUER_KIDS, doc_type="파일데이터", notice_no=max(d["notices"], default=""),
            locator=f"{fname} 행 {_rows_label(d['rows'])}", ingr_codes=[code], ingr_names=names, license=LICENSE_KIDS,
            source_ref=f"한국의약품안전관리원 {'임부금기약물' if kind == 'l2_preg' else '연령금기'}|{fname}",
        ))
    return out


# --------------------------------------------------------------------------- L1 별표 2(표 + 행)

def build_bupyo2_chunks(md_path: Path | None = None) -> list[dict[str, Any]]:
    parents = load_bupyo2(md_path or BUPYO2)
    nos = [int(p.meta["no"]) for p in parents]
    table_text = (f"[{BUPYO2_TITLE}] 열: 연번 | 유효성분 | 연령기준 | 해당 제형. 행 {len(parents)}개"
                  f"(연번 {min(nos)}~{max(nos)}, 삭제 행 제외). 고시 제2026-52호 별표 2 {BUPYO2_PAGES}.")
    table = _chunk(
        "l1_bupyo2_table", "bupyo2", table_text, layer="L1", issuer=ISSUER_MFDS, doc_type="고시", notice_no=BUPYO2_NOTICE_NO,
        locator=f"별표 2 {BUPYO2_PAGES}", license=LICENSE_GOSI, source_ref="의약품 병용금기 성분 등의 지정에 관한 규정|gosi_bupyo2_pdfplumber.md",
    )
    out = [table]
    for p in parents:
        m = p.meta
        text = f"[{BUPYO2_TITLE}] 연번: {m['no']}; 유효성분: {m['ing']}; 연령기준: {' / '.join(m['ages'])}; 해당 제형: {' / '.join(m['forms'])}"
        if len(m["ages"]) == len(m["forms"]) and len(m["ages"]) > 1:
            text += "\n짝: " + "; ".join(f"연령기준 {a} ↔ 해당 제형 {f}" for a, f in bupyo2_pairs(p))
        out.append(_chunk(
            "l1_bupyo2_row", f"bupyo2|{int(m['no']):03d}", text, parent_id=table["chunk_id"],
            layer="L1", issuer=ISSUER_MFDS, doc_type="고시", notice_no=BUPYO2_NOTICE_NO, locator=f"별표 2 연번 {m['no']}",
            ingr_names=[m["ing"]], license=LICENSE_GOSI, source_ref="의약품 병용금기 성분 등의 지정에 관한 규정|gosi_bupyo2_pdfplumber.md",
        ))
    return out


# --------------------------------------------------------------------------- 전체 빌드·출력·검증

def build_all() -> list[dict[str, Any]]:
    chunks = build_combo_chunks() + build_detail_chunks() + build_bupyo2_chunks()
    chunks.sort(key=lambda c: (c["chunk_kind"], c["chunk_id"]))
    return chunks


def to_lines(chunks: Iterable[dict[str, Any]]) -> list[str]:
    return [json.dumps(c, ensure_ascii=False, sort_keys=False, separators=(",", ":")) for c in chunks]


def manifest_of(chunks: Sequence[dict[str, Any]], lines: Sequence[str] | None = None) -> dict[str, Any]:
    lines = list(lines) if lines is not None else to_lines(chunks)
    kinds: dict[str, dict[str, Any]] = {}
    for c, ln in zip(chunks, lines, strict=True):
        k = kinds.setdefault(c["chunk_kind"], {"count": 0, "chars": 0, "_h": hashlib.sha256()})
        k["count"] += 1
        k["chars"] += len(c["text"])
        k["_h"].update(ln.encode("utf-8") + b"\n")
    by_kind = {}
    for name in sorted(kinds):
        k = kinds[name]
        by_kind[name] = {"count": k["count"], "avg_chars": round(k["chars"] / k["count"], 1), "sha256": k["_h"].hexdigest()}
    total = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    return {"total": len(chunks), "base_date": BASE_DATE, "kinds": by_kind, "sha256": total, "fields": list(FIELDS)}


def link_report(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ids = {c["chunk_id"] for c in chunks}
    bad_parent = [c["chunk_id"] for c in chunks if c["parent_id"] and c["parent_id"] not in ids]
    bad_refs = [(c["chunk_id"], r) for c in chunks for r in c["refs"] if r not in ids]
    return {"chunks": len(chunks), "unique_ids": len(ids), "with_parent": sum(1 for c in chunks if c["parent_id"]),
            "with_refs": sum(1 for c in chunks if c["refs"]), "dangling_parent": len(bad_parent), "dangling_refs": len(bad_refs)}


def pair_index(chunks: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        if c["pair_id"]:
            idx.setdefault(c["pair_id"], []).append(c)
    return idx


def cmd_build(args: argparse.Namespace) -> int:
    chunks = build_all()
    lines = to_lines(chunks)
    man = manifest_of(chunks, lines)
    if args.check:
        old = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        same = old.get("sha256") == man["sha256"]
        print(f"재빌드 해시 {'동일' if same else '다름'}: {man['sha256'][:16]} (기존 {old.get('sha256', '')[:16]})")
        return 0 if same else 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man["links"] = link_report(chunks)
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"청크 {man['total']}개 → {CHUNKS_PATH} (sha256 {man['sha256'][:16]})")
    for k, v in man["kinds"].items():
        print(f"  {k}: {v['count']} 평균 {v['avg_chars']}자")
    print("연결:", man["links"])
    return 0


def read_chunks(path: Path | None = None) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in (path or CHUNKS_PATH).read_text(encoding="utf-8").splitlines() if ln]


def cmd_verify(args: argparse.Namespace) -> int:
    chunks = read_chunks()
    rep = link_report(chunks)
    print("연결 검증(전체):", rep)
    by_id = {c["chunk_id"]: c for c in chunks}
    rng = random.Random(20261111)  # noqa: S311 - 점검용 표본(시드 고정), 보안 용도 아님
    sample = rng.sample(chunks, 20)
    ok = 0
    for c in sample:
        good = (not c["parent_id"] or c["parent_id"] in by_id) and all(r in by_id for r in c["refs"])
        ok += good
    print(f"임의 20청크 parent_id·refs 점검: {ok}/20 (종류: {sorted({c['chunk_kind'] for c in sample})})")
    idx = pair_index(chunks)
    multi = [p for p, v in idx.items() if len(v) > 1]
    pick = rng.sample(sorted(idx), 20) + multi[:5]
    hit = 0
    for p in pick:
        scan = sorted(c["chunk_id"] for c in chunks if c["pair_id"] == p)
        hit += scan == sorted(c["chunk_id"] for c in idx[p])
    a, b = pick[0].split("+")
    print(f"pair_id 한 번 조회 = 전체 스캔: {hit}/{len(pick)} (같은 쌍 여러 청크 {len(multi)}쌍), 순서 무관 {make_pair_id(a, b) == make_pair_id(b, a)}")
    rows = [c for c in chunks if c["chunk_kind"] == "l1_bupyo2_row"]
    cols = ("연번", "유효성분", "연령기준", "해당 제형")
    for c in rng.sample(rows, 3):
        t = by_id.get(c["parent_id"])
        print(f"  별표 행 {c['locator']}: 열 이름 포함 {all(x in c['text'] for x in cols)}, 표 청크 조회 {bool(t and '열:' in t['text'])}")
    return 0 if rep["dangling_parent"] == rep["dangling_refs"] == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="l2_chunks.jsonl·manifest.json 생성")
    b.add_argument("--check", action="store_true", help="쓰지 않고 다시 빌드해 기존 manifest 해시와 비교")
    b.set_defaults(fn=cmd_build)
    v = sub.add_parser("verify", help="생성된 jsonl의 연결 검증")
    v.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
