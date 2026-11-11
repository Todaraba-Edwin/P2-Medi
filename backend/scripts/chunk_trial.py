"""BE-05-01 청킹 단위 시험(소스별 후보 비교). 청킹 → 용량 실측 → 개발용 합성 질의 → BM25·임베딩·하이브리드 적중 비교.

하위 명령(작업 위치 `backend/`):
  inspect    청크 수·크기·용량 추정, 표 인식 확인(호출 0). `data/mock/chunk_trial/{capacity,table_check}.md`
  plan       샘플 코퍼스 크기를 상한 안으로 맞추고 토큰·비용 어림을 출력(호출 0). `plan.json` 저장
  run        실호출. `text-embedding-3-small` 임베딩 전용, 캐시(record)·원장·하드 상한(`--max-usd`) 경유
  report     저장된 벡터로 적중 k/n·Wilson 95%를 계산해 `report.md`·`report.json`을 쓴다(호출 0)

규칙(지시서 2026-11-10):
- 질의는 **개발용**이다. 평가 세트·시험셋·페르소나 질문을 쓰지 않는다(RFP-26-04). 정답은 구조(`parent_id`)로 확정한다.
- 청크 객체: text·source·parent_id·chunk_id(재적재해도 같은 값)·ingr_codes. 적중 = 정답 상위 단위의 청크가 top-k에 하나라도.
- 키는 환경변수 OPENAI_API_KEY(없으면 설정)로만 읽고 출력하지 않는다. 로컬만 쓰고 Supabase에 쓰지 않는다.
- 토큰 수는 문자 수 근사(한글 음절 1.7토큰, 보수적)다. tiktoken이 없다.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from array import array
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import embed_compare as E  # noqa: E402

from app.db.source_files import AGE_CSV_NAME, COMBO_JSON_NAME, PREG_CSV_NAME  # noqa: E402
from app.llm.cache import cache_mode  # noqa: E402
from app.llm.ledger import BudgetExceeded  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402
from app.tools.drug_dict import BM25, char_ngrams, normalize_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT_DIR = DATA / "mock" / "chunk_trial"
SNAP = DATA / "mock" / "api_snapshots"
BUPYO2 = DATA / "mock" / "parsed" / "gosi_bupyo2_pdfplumber.md"
L2_JSON = DATA / COMBO_JSON_NAME
PREG_CSV = DATA / PREG_CSV_NAME
AGE_CSV = DATA / AGE_CSV_NAME
BUPYO2_TITLE = "별표 2 특정연령대 금기 성분 (제5조 관련)"

SEED = 20261110
MODEL = "small"  # text-embedding-3-small 전용
EMB_CHAR_CAP = 3000  # 임베딩 입력 글자 상한(모델 입력 8191토큰 한도 안전 여유). 넘으면 잘라 보내고 개수를 기록한다
DEFAULT_MAX_USD = 0.30
FIT_FRACTION = 0.8  # 어림 비용이 상한의 이 비율 이하가 되도록 샘플을 줄인다(어림은 보수적)
EMB_BATCH_TEXTS = 256
EMB_BATCH_TOKENS = 60_000
TOPKS = (1, 5, 10)
VEC_BYTES = 1536 * 4
HNSW_FACTOR = 1.3  # 추정: HNSW(m=16)는 벡터 크기의 약 1.0~1.5배로 어림(실측 아님)
ROW_OVERHEAD = 300  # 추정: 행 헤더·메타데이터(jsonb)·id 바이트

SOURCES = ("eyak", "prmsn", "bupyo2", "l2_combo", "l2_detail")
CANDIDATES: dict[str, tuple[str, ...]] = {
    "eyak": ("sentence", "section", "section_hdr"),
    "prmsn": ("sentence", "article", "para_hdr"),
    "bupyo2": ("row_plain", "row_hdr", "row_ctx"),
    "l2_combo": ("combo", "pair_group"),
    "l2_detail": ("phrase", "ingredient"),
}
QUERY_SETS = ("eyak", "prmsn_nb", "prmsn_ud", "bupyo2", "l2_combo", "l2_detail")
QUERY_CORPUS = {"eyak": "eyak", "prmsn_nb": "prmsn", "prmsn_ud": "prmsn", "bupyo2": "bupyo2", "l2_combo": "l2_combo", "l2_detail": "l2_detail"}
SIZES = {"eyak": (120, 120), "prmsn": (40, 40), "bupyo2": (None, 0), "l2_combo": (600, 2400), "l2_detail": (200, 800)}  # (샘플 단위 수, 방해 단위 수)
PER_SET = 30


# --------------------------------------------------------------------------- 자료형

@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    parent_id: str
    chunk_id: str
    ingr_codes: tuple[str, ...] = ()
    covers: tuple[str, ...] = ()  # 이 청크가 가리키는 상위 단위들(비면 parent_id 하나). 고유 문구 청크처럼 여러 성분을 묶을 때 쓴다

    @property
    def parents(self) -> tuple[str, ...]:
        return self.covers or (self.parent_id,)


@dataclass
class Parent:
    pid: str
    group: str  # 샘플링 단위(제품 번호 등)
    text: str  # 상위 단위 전체 평문(정답 포함 판정용)
    meta: dict[str, Any] = field(default_factory=dict)


def make_chunk_id(parent_id: str, cand: str, idx: int, text: str) -> str:
    """재적재해도 같은 값: 상위 단위 + 후보 + 순번 + 본문 해시."""
    return f"{parent_id}#{cand}:{idx:03d}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"  # noqa: S324 - 식별용 해시


def _mk(source: str, cand: str, parent_id: str, idx: int, text: str, ingr: Sequence[str] = (), covers: Sequence[str] = ()) -> Chunk:
    return Chunk(text, source, parent_id, make_chunk_id(parent_id, cand, idx, text), tuple(ingr), tuple(covers))


# --------------------------------------------------------------------------- 문장·표 도구

_NONE = {"", "none", "null"}
_SENT_SPLIT = re.compile(r"(?<=[다요음임함됨]\.)\s+")


def clean_field(v: Any) -> str:
    s = "" if v is None else str(v).replace("\xa0", " ").strip()
    return "" if s.lower() in _NONE else s


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in re.split(r"\n+", text):
        line = " ".join(line.split())
        if not line:
            continue
        out.extend(s.strip() for s in _SENT_SPLIT.split(line) if s.strip())
    return out


class _TableParser(HTMLParser):
    """`<tbody><tr><td><p>…` 형태를 행→셀→문단 텍스트 목록으로 읽는다(셀 안 `<p>`가 쌓인 표 포함)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[list[str]]] = []
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._buf: list[str] = []
        self.caption: list[str] = []
        self._in_caption = False

    def _flush_buf(self) -> None:
        t = " ".join("".join(self._buf).replace("\xa0", " ").split())
        self._buf = []
        if t and self._cell is not None:
            self._cell.append(t)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            self._buf = []
        elif tag in ("p", "br"):
            self._flush_buf()
        elif tag == "caption":
            self._in_caption = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._flush_buf()
            if self._row is not None and self._cell is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "p":
            self._flush_buf()
        elif tag == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = None
        elif tag == "caption":
            self._in_caption = False

    def handle_data(self, data: str) -> None:
        if self._in_caption:
            self.caption.append(data.strip())
        else:
            self._buf.append(data)


def parse_table(html_text: str) -> list[list[list[str]]]:
    p = _TableParser()
    p.feed(html_text)
    p.close()
    return p.rows


def table_naive(html_text: str) -> str:
    """태그만 벗긴 평문 이어붙임(열 이름과 값의 짝이 사라지는 기준선)."""
    return " ".join(t for row in parse_table(html_text) for cell in row for t in cell)


def table_rows_struct(html_text: str) -> tuple[list[str], list[str], bool]:
    """(열 이름들, 행 문자열들, 쌓인 셀 풀었는지). 첫 행을 열 이름으로 본다. 한 셀에 `<p>`가 쌓이고 개수가 같으면 행으로 푼다."""
    rows = [r for r in parse_table(html_text) if any(c for c in r)]
    if not rows:
        return [], [], False
    header = [" ".join(c) for c in rows[0]]
    out: list[str] = []
    unstacked = False
    for r in rows[1:]:
        counts = {len(c) for c in r if len(c) > 1}
        if len(counts) == 1 and len(r) == len(header):
            n = counts.pop()
            unstacked = True
            for i in range(n):
                vals = [c[i] if len(c) == n else (c[0] if c else "") for c in r]
                out.append("; ".join(f"{h}={v}" for h, v in zip(header, vals, strict=True) if v))
        else:
            vals = [" ".join(c) for c in r]
            out.append("; ".join(f"{h}={v}" for h, v in zip(header, vals, strict=False) if v))
    return header, out, unstacked


def table_struct_text(html_text: str) -> str:
    header, rows, _ = table_rows_struct(html_text)
    if not header:
        return ""
    return "표 열: " + " | ".join(header) + "\n" + "\n".join(rows)


# --------------------------------------------------------------------------- 로더: e약은요·허가 상세

EYAK_FIELDS = (("efcy", "효능"), ("use_method", "사용법"), ("atpn_warn", "경고"), ("atpn", "주의사항"), ("intrc", "상호작용"), ("se", "이상반응"), ("deposit_method", "보관법"))


def load_eyak(snap_dir: Path | None = None) -> list[Parent]:
    out: list[Parent] = []
    for fp in sorted(glob.glob(str((snap_dir or SNAP / "eyak-all") / "page-*.json"))):
        for it in json.load(open(fp, encoding="utf-8")).get("items", []):
            seq = clean_field(it.get("item_seq"))
            name = clean_field(it.get("item_name"))
            if not seq or not name:
                continue
            for f, label in EYAK_FIELDS:
                t = clean_field(it.get(f))
                if t:
                    out.append(Parent(f"eyak:{seq}:{f}", seq, t, {"name": name, "field": f, "label": label, "item_seq": seq}))
    out.sort(key=lambda p: p.pid)
    return out


def _para_texts(art: ET.Element) -> list[tuple[str, str]]:
    paras: list[tuple[str, str]] = []
    for p in art.iter("PARAGRAPH"):
        raw = p.text or ""
        if p.get("tagName") == "table" or "<tbody" in raw:
            paras.append(("table", raw))
        else:
            t = " ".join(raw.replace("\xa0", " ").split())
            if t:
                paras.append(("p", t))
    return paras


def parse_prmsn_doc(xml: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """XML(`DOC/SECTION/ARTICLE/PARAGRAPH`)를 (조항 제목, 문단 목록) 목록으로. 깨진 XML은 빈 목록."""
    if not xml or xml.strip().lower() in _NONE:
        return []
    try:
        root = ET.fromstring(xml.strip())  # noqa: S314 - 로컬 공공 API 스냅샷(신뢰 입력)
    except ET.ParseError:
        return []
    out = []
    for art in root.iter("ARTICLE"):
        paras = _para_texts(art)
        if paras:
            out.append(((art.get("title") or "").strip(), paras))
    return out


def load_prmsn(snap_dir: Path | None = None) -> list[Parent]:
    out: list[Parent] = []
    for fp in sorted(glob.glob(str((snap_dir or SNAP / "prmsn-detail") / "item-*.json"))):
        j = json.load(open(fp, encoding="utf-8"))
        r = (j.get("response") or [{}])[0]
        seq = clean_field(r.get("ITEM_SEQ"))
        name = clean_field(r.get("ITEM_NAME"))
        if not seq or not name:
            continue
        for doc, key in (("NB", "NB_DOC_DATA"), ("UD", "UD_DOC_DATA")):
            for ai, (title, paras) in enumerate(parse_prmsn_doc(clean_field(r.get(key)))):
                text = "\n".join(t if k == "p" else table_naive(t) for k, t in paras)
                out.append(Parent(f"prmsn:{seq}:{doc}:{ai:02d}", seq, text, {"name": name, "doc": doc, "title": title, "paras": paras, "item_seq": seq}))
    out.sort(key=lambda p: p.pid)
    return out


# --------------------------------------------------------------------------- 로더: 별표 2·L2

def _br(s: str) -> list[str]:
    return [x.strip() for x in s.split("<br>")]


def load_bupyo2(path: Path | None = None) -> list[Parent]:
    out: list[Parent] = []
    for line in (path or BUPYO2).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "연번" in line.split("|")[1]:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or "삭제" in cells[1] or not cells[2]:
            continue
        no, ing, ages, forms = cells[0], cells[1], _br(cells[2]), _br(cells[3])
        out.append(Parent(f"bupyo2:{int(no):03d}", f"bupyo2:{int(no):03d}", f"{ing} {' '.join(ages)} {' '.join(forms)}",
                          {"no": no, "ing": ing, "ages": ages, "forms": forms}))
    return out


def iter_json_array(path: Path, block: int = 1 << 25) -> Iterator[dict[str, Any]]:
    """최상위가 배열인 큰 JSON을 객체 단위로 스트리밍한다(전체를 메모리에 올리지 않는다)."""
    dec = json.JSONDecoder()
    buf = ""
    started = False
    with open(path, encoding="utf-8") as f:
        while True:
            more = f.read(block)
            buf += more
            pos = 0
            if not started:
                i = buf.find("[")
                if i < 0:
                    if not more:
                        return
                    continue
                pos, started = i + 1, True
            while True:
                while pos < len(buf) and buf[pos] in " \r\n\t,":
                    pos += 1
                if pos >= len(buf) or buf[pos] == "]":
                    break
                try:
                    obj, end = dec.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break
                yield obj
                pos = end
            buf = buf[pos:]
            if not more:
                return


def l2_combos_cached(path: Path | None = None, cache: Path | None = None) -> list[dict[str, str]]:
    """병용금기 고유 조합 (성분A, 성분B, 금기사유, 고시번호). 결과는 로컬 캐시 JSON에 둔다."""
    cache = cache or OUT_DIR / "l2_combos.json"
    src = path or L2_JSON
    if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    for o in iter_json_array(src):
        m = o.get("metadata") or {}
        a, b = (m.get("성분코드A", ""), m.get("성분명A", "")), (m.get("성분코드B", ""), m.get("성분명B", ""))
        if not a[0] or not b[0]:
            continue
        a, b = sorted((a, b))
        key = (a[0], b[0], m.get("금기사유", ""), m.get("고시번호", ""))
        if key not in seen:
            seen[key] = {"codeA": a[0], "nameA": a[1], "codeB": b[0], "nameB": b[1], "reason": m.get("금기사유", ""), "gosi": m.get("고시번호", ""), "date": m.get("고시적용일", "")}
    rows = sorted(seen.values(), key=lambda r: (r["codeA"], r["codeB"], r["gosi"], r["reason"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def load_l2_combo(rows: Sequence[dict[str, str]] | None = None) -> list[Parent]:
    rows = l2_combos_cached() if rows is None else rows
    by_pair: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_pair.setdefault(f"l2:{r['codeA']}+{r['codeB']}", []).append(r)
    out = []
    for pid in sorted(by_pair):
        rs = by_pair[pid]
        out.append(Parent(pid, pid, " ".join(f"{r['nameA']} {r['nameB']} {r['reason']}" for r in rs),
                          {"combos": rs, "nameA": rs[0]["nameA"], "nameB": rs[0]["nameB"], "codes": (rs[0]["codeA"], rs[0]["codeB"])}))
    return out


def _cp949_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="cp949", newline="") as f:
        return list(csv.DictReader(f))


def _strip_code(s: str) -> str:
    return re.sub(r"\s*\(\d+\)", "", s or "").strip()


def load_l2_detail(preg: Sequence[dict[str, str]] | None = None, age: Sequence[dict[str, str]] | None = None) -> list[Parent]:
    """임부·연령 상세정보. 상위 단위 = (종류, 성분코드). 같은 성분의 조건·문구는 모아 둔다."""
    preg = _cp949_rows(PREG_CSV) if preg is None else preg
    age = _cp949_rows(AGE_CSV) if age is None else age
    acc: dict[str, dict[str, Any]] = {}
    for kind, rows in (("preg", preg), ("age", age)):
        for r in rows:
            code, name, phrase = (r.get("성분코드") or "").strip(), (r.get("성분명") or "").strip(), " ".join((r.get("상세정보") or "").split())
            if not code or not phrase:
                continue
            cond = f"임부금기 {r.get('금기등급', '').strip()}등급" if kind == "preg" else f"연령금기 {_strip_code(r.get('특정연령', ''))}{_strip_code(r.get('특정연령단위', ''))} {_strip_code(r.get('연령처리조건', ''))}".strip()
            cond = " ".join(cond.split())
            d = acc.setdefault(f"l2d:{kind}:{code}", {"kind": kind, "code": code, "name": name, "items": set()})
            d["items"].add((cond, phrase))
    out = []
    for pid in sorted(acc):
        d = acc[pid]
        items = sorted(d["items"])
        out.append(Parent(pid, pid, " ".join(f"{d['name']} {c} {p}" for c, p in items), {"kind": d["kind"], "code": d["code"], "name": d["name"], "items": items}))
    return out


# --------------------------------------------------------------------------- 후보 청커

def _label(p: Parent) -> str:
    return str(p.meta["label"])


def chunk_eyak(parents: Sequence[Parent], cand: str) -> list[Chunk]:
    out: list[Chunk] = []
    for p in parents:
        name, label = p.meta["name"], _label(p)
        if cand == "sentence":
            out.extend(_mk("eyak", cand, p.pid, i, s) for i, s in enumerate(split_sentences(p.text)))
        elif cand == "section":
            out.append(_mk("eyak", cand, p.pid, 0, f"{label}\n{' '.join(p.text.split())}"))
        elif cand == "section_hdr":
            out.append(_mk("eyak", cand, p.pid, 0, f"[{name} · {label}] {' '.join(p.text.split())}"))
        else:
            raise ValueError(cand)
    return out


def _article_text(p: Parent, structured: bool) -> str:
    parts = []
    for k, t in p.meta["paras"]:
        parts.append(t if k == "p" else (table_struct_text(t) if structured else table_naive(t)))
    return "\n".join(x for x in parts if x)


def chunk_prmsn(parents: Sequence[Parent], cand: str) -> list[Chunk]:
    out: list[Chunk] = []
    for p in parents:
        name, doc, title = p.meta["name"], p.meta["doc"], p.meta["title"]
        if cand == "sentence":
            i = 0
            for k, t in p.meta["paras"]:
                for s in ([table_naive(t)] if k == "table" else split_sentences(t)):
                    if s:
                        out.append(_mk("prmsn", cand, p.pid, i, s))
                        i += 1
        elif cand == "article":
            out.append(_mk("prmsn", cand, p.pid, 0, f"{title}\n{_article_text(p, True)}".strip()))
        elif cand == "para_hdr":
            head = f"[{name} · {'사용상의주의사항' if doc == 'NB' else '용법용량'} · {title or '본문'}]"
            buf: list[str] = []
            i = 0

            def flush(buf: list[str] = buf, head: str = head, p: Parent = p) -> None:
                nonlocal i
                if buf:
                    out.append(_mk("prmsn", cand, p.pid, i, head + " " + " ".join(buf)))
                    i += 1
                    buf.clear()

            for k, t in p.meta["paras"]:
                if k == "p":
                    if sum(len(x) for x in buf) + len(t) > 500:
                        flush()
                    buf.append(t)
                    continue
                flush()
                header, rows, _ = table_rows_struct(t)
                for g in range(0, max(len(rows), 1), 6):
                    grp = rows[g : g + 6]
                    if header and grp:
                        out.append(_mk("prmsn", cand, p.pid, i, f"{head} 표 열: {' | '.join(header)}\n" + "\n".join(grp)))
                        i += 1
            flush()
        else:
            raise ValueError(cand)
    return out


def bupyo2_pairs(p: Parent) -> list[tuple[str, str]]:
    ages, forms = p.meta["ages"], p.meta["forms"]
    if len(ages) == len(forms):
        return list(zip(ages, forms, strict=True))
    return [(" / ".join(ages), " / ".join(forms))]


def chunk_bupyo2(parents: Sequence[Parent], cand: str) -> list[Chunk]:
    out: list[Chunk] = []
    for p in parents:
        m = p.meta
        if cand == "row_plain":
            text = f"{m['ing']} | {' / '.join(m['ages'])} | {' / '.join(m['forms'])}"
        elif cand == "row_hdr":
            text = f"연번: {m['no']}; 유효성분: {m['ing']}; 연령기준: {' / '.join(m['ages'])}; 해당 제형: {' / '.join(m['forms'])}"
        elif cand == "row_ctx":
            pairs = "; ".join(f"연령기준 {a}, 해당 제형 {f}" for a, f in bupyo2_pairs(p))
            text = f"[{BUPYO2_TITLE}] 연번 {m['no']} 유효성분 {m['ing']}: {pairs}"
        else:
            raise ValueError(cand)
        out.append(_mk("bupyo2", cand, p.pid, 0, text))
    return out


def chunk_l2_combo(parents: Sequence[Parent], cand: str) -> list[Chunk]:
    out: list[Chunk] = []
    for p in parents:
        a, b = p.meta["nameA"], p.meta["nameB"]
        codes = p.meta["codes"]
        if cand == "combo":
            for i, r in enumerate(p.meta["combos"]):
                out.append(_mk("l2_combo", cand, p.pid, i, f"병용금기: {a} + {b}. 사유: {r['reason']} (고시 {r['gosi']})", codes))
        elif cand == "pair_group":
            reasons = " / ".join(f"사유{i + 1}: {r['reason']} (고시 {r['gosi']})" for i, r in enumerate(p.meta["combos"]))
            out.append(_mk("l2_combo", cand, p.pid, 0, f"병용금기: {a} + {b}. {reasons}", codes))
        else:
            raise ValueError(cand)
    return out


def chunk_l2_detail(parents: Sequence[Parent], cand: str) -> list[Chunk]:
    out: list[Chunk] = []
    if cand == "ingredient":
        for p in parents:
            body = "\n".join(f"{c}: {ph}" for c, ph in p.meta["items"])
            out.append(_mk("l2_detail", cand, p.pid, 0, f"{p.meta['name']}\n{body}", (p.meta["code"],)))
    elif cand == "phrase":
        by: dict[tuple[str, str], list[Parent]] = {}
        for p in parents:
            for c, ph in p.meta["items"]:
                by.setdefault((c, ph), []).append(p)
        for i, (c, ph) in enumerate(sorted(by)):
            ps = sorted(by[(c, ph)], key=lambda x: x.pid)
            out.append(_mk("l2_detail", cand, f"l2d:phrase:{hashlib.sha1(f'{c}|{ph}'.encode()).hexdigest()[:10]}", i, f"[{c}] {ph}",  # noqa: S324
                           sorted({q.meta["code"] for q in ps}), [q.pid for q in ps]))
    else:
        raise ValueError(cand)
    return out


CHUNKERS: dict[str, Callable[[Sequence[Parent], str], list[Chunk]]] = {
    "eyak": chunk_eyak, "prmsn": chunk_prmsn, "bupyo2": chunk_bupyo2, "l2_combo": chunk_l2_combo, "l2_detail": chunk_l2_detail,
}
LOADERS: dict[str, Callable[[], list[Parent]]] = {
    "eyak": load_eyak, "prmsn": load_prmsn, "bupyo2": load_bupyo2, "l2_combo": load_l2_combo, "l2_detail": load_l2_detail,
}


# --------------------------------------------------------------------------- 샘플 코퍼스

def sample_corpus(source: str, parents: Sequence[Parent], n_sample: int | None, n_distract: int, scale: float = 1.0) -> tuple[list[Parent], list[Parent]]:
    """(샘플 단위, 방해 단위). 샘플링 단위는 group(제품 번호 등). 시드 고정·정렬 후 무작위."""
    rng = random.Random(f"{SEED}:{source}:sample")  # noqa: S311
    groups = sorted({p.group for p in parents})
    rng.shuffle(groups)
    if n_sample is None:
        return list(parents), []
    ns, nd = max(int(n_sample * scale), 1), int(n_distract * scale)
    sample_g, dist_g = set(groups[:ns]), set(groups[ns : ns + nd])
    return [p for p in parents if p.group in sample_g], [p for p in parents if p.group in dist_g]


# --------------------------------------------------------------------------- 개발용 합성 질의

_TOK = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")
_STOP = {"경우", "있는", "있습니다", "합니다", "하십시오", "사용", "투여", "환자", "복용", "때문", "이상", "또는", "대한", "따라", "있다", "한다", "된다", "하여"}


class TokenIndex:
    """상위 단위 평문의 토큰 → 상위 단위 집합(키워드 질의의 정답을 '모든 토큰을 포함하는 상위 단위'로 구조 확정)."""

    def __init__(self, parents: Sequence[Parent]) -> None:
        self.inv: dict[str, set[str]] = {}
        self.n = len(parents)
        for p in parents:
            for t in set(_TOK.findall(p.text)):
                self.inv.setdefault(t.lower(), set()).add(p.pid)

    def gold(self, words: Sequence[str]) -> set[str]:
        sets = [self.inv.get(w.lower(), set()) for w in words]
        return set.intersection(*sets) if sets else set()


def kw_query(rng: random.Random, sentence: str, idx: TokenIndex, avoid: Sequence[str] = (), want: int = 3, max_gold: int = 8) -> tuple[str, set[str]] | None:
    """문장에서 드문 단어 want개(원문 순서)를 뽑는다. 정답 집합이 비거나 max_gold를 넘으면 None."""
    toks: list[str] = []
    for t in _TOK.findall(sentence):
        if t.lower() not in {x.lower() for x in toks} and t not in _STOP and not any(a and a in t for a in avoid):
            toks.append(t)
    if len(toks) < 2:
        return None
    df = {t: len(idx.inv.get(t.lower(), ())) for t in toks}
    ranked = sorted(toks, key=lambda t: (df[t], rng.random()))[: want + 2]
    pick = set(rng.sample(ranked, min(want, len(ranked))))
    words = [t for t in toks if t in pick]
    gold = idx.gold(words)
    return (" ".join(words), gold) if gold and len(gold) <= max_gold else None


def _body(name: str) -> str:
    return E.normalize_name_keep_spaces(name)


EYAK_TOPICS = {
    "efcy": ("효능", "어디에 쓰는 약인가요"), "use_method": ("사용법", "어떻게 먹나요"), "atpn_warn": ("경고", "먹기 전에 꼭 알아야 할 경고"),
    "atpn": ("주의사항", "먹기 전에 알아둘 점"), "intrc": ("상호작용", "같이 먹으면 안 되는 약"), "se": ("이상반응", "부작용이 뭔가요"), "deposit_method": ("보관법", "어떻게 보관하나요"),
}
NB_TOPICS = (
    (r"상호작용", ("상호작용", "같이 먹으면 안 되는 약")), (r"임부|임신", ("임부 주의", "임신 중에 먹어도 되나요")), (r"소아", ("소아 투여", "아이가 먹어도 되나요")),
    (r"고령자", ("고령자 주의", "노인이 먹어도 되나요")), (r"이상반응", ("이상반응", "부작용이 뭔가요")), (r"과량", ("과량투여", "많이 먹으면 어떻게 되나요")),
)


def _take(rng: random.Random, items: list[Any], n: int) -> list[Any]:
    rng.shuffle(items)
    return items[:n]


def queries_eyak(sample: Sequence[Parent], corpus: Sequence[Parent]) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:eyak:q")  # noqa: S311
    idx = TokenIndex(corpus)
    by_key: dict[tuple[str, str], list[str]] = {}
    for p in corpus:
        by_key.setdefault((normalize_name(p.meta["name"]), p.meta["field"]), []).append(p.pid)
    pool = sorted(sample, key=lambda p: p.pid)
    qs: list[dict[str, Any]] = []
    cand = list(pool)
    rng.shuffle(cand)
    for p in cand:  # 키워드(부분집합) 질의
        if sum(q["style"] == "kw" for q in qs) >= PER_SET // 2:
            break
        for s in split_sentences(p.text):
            r = kw_query(rng, s, idx, avoid=[_body(p.meta["name"])])
            if r and p.pid in r[1]:
                qs.append({"style": "kw", "query": r[0], "gold": sorted(r[1]), "rule": f"{p.pid} 문장의 드문 단어 3개"})
                break
    rng.shuffle(cand)
    used: set[str] = set()
    for p in cand:  # 제품명 + 주제(구조 질의, 절반은 일상어 변형)
        if sum(q["style"] in ("struct", "daily") for q in qs) >= PER_SET - PER_SET // 2:
            break
        if p.group in used:
            continue
        used.add(p.group)
        name = _body(p.meta["name"])
        if len(name) < 2:
            continue
        f = p.meta["field"]
        preg = [q.pid for q in corpus if q.group == p.group and re.search(r"임부|임신", q.text)] if f == "atpn" else []
        daily = len(used) % 2 == 0
        if preg:
            qtext, gold, rule = (f"{name} {'임신 중에 먹어도 되나요' if daily else '임부 주의'}"), preg, f"{p.group} 임신·임부 언급 절"
        else:
            qtext, gold, rule = f"{name} {EYAK_TOPICS[f][1 if daily else 0]}", by_key[(normalize_name(p.meta['name']), f)], f"{p.pid} 주제 절(같은 이름 제품 포함)"
        qs.append({"style": "daily" if daily else "struct", "query": qtext, "gold": sorted(gold), "rule": rule})
    return _finish("eyak", qs)


def _finish(name: str, qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for i, q in enumerate(qs):
        q["id"] = f"{name}-{i + 1:03d}"
        q["set"] = name
    return qs


def queries_prmsn(sample: Sequence[Parent], corpus: Sequence[Parent], doc: str) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:prmsn:{doc}:q")  # noqa: S311
    idx = TokenIndex([p for p in corpus if p.meta["doc"] == doc])
    docs = [p for p in sorted(sample, key=lambda p: p.pid) if p.meta["doc"] == doc]
    qs: list[dict[str, Any]] = []
    cand = list(docs)
    rng.shuffle(cand)
    for p in cand:
        if sum(q["style"] == "kw" for q in qs) >= (PER_SET // 2 if doc == "NB" else PER_SET // 3):
            break
        sents = [s for k, t in p.meta["paras"] if k == "p" for s in split_sentences(t)]
        rng.shuffle(sents)
        for s in sents[:6]:
            r = kw_query(rng, s, idx, avoid=[_body(p.meta["name"])])
            if r and p.pid in r[1]:
                qs.append({"style": "kw", "query": r[0], "gold": sorted(r[1]), "rule": f"{p.pid} 문장의 드문 단어 3개"})
                break
    rng.shuffle(cand)
    used: set[tuple[str, int]] = set()
    n_struct = 0
    for p in cand:
        if len(qs) >= PER_SET:
            break
        name = _body(p.meta["name"])
        if doc == "NB":
            for pi, (pat, (plain, daily)) in enumerate(NB_TOPICS):
                if re.search(pat, p.meta["title"]) and (p.group, pi) not in used:
                    used.add((p.group, pi))
                    gold = [q.pid for q in corpus if q.group == p.group and q.meta["doc"] == "NB" and re.search(pat, q.meta["title"])]
                    use_daily = n_struct % 2 == 1
                    n_struct += 1
                    qs.append({"style": "daily" if use_daily else "struct", "query": f"{name} {daily if use_daily else plain}", "gold": sorted(gold), "rule": f"{p.group} NB 제목 /{pat}/ 조항"})
                    break
        elif p.group not in {g for g, _ in used}:
            used.add((p.group, 0))
            gold = [q.pid for q in corpus if q.group == p.group and q.meta["doc"] == "UD"]
            use_daily = n_struct % 2 == 1
            n_struct += 1
            qs.append({"style": "daily" if use_daily else "struct", "query": f"{name} {'어떻게 먹나요' if use_daily else '용법용량'}", "gold": sorted(gold), "rule": f"{p.group} UD 전 조항"})
    if doc == "UD":  # 표가 든 조항 질의(열 이름 + 첫 열 값)
        for p in cand:
            if sum(q["style"] == "table" for q in qs) >= 6:
                break
            for k, t in p.meta["paras"]:
                if k != "table":
                    continue
                header, rows, _ = table_rows_struct(t)
                if len(header) >= 2 and rows:
                    first = rows[min(1, len(rows) - 1)].split("; ")[0].split("=", 1)[-1]
                    qs.append({"style": "table", "query": f"{_body(p.meta['name'])} {header[0]} {first} {header[1]}", "gold": [p.pid], "rule": f"{p.pid} 표 열 이름 + 행 값"})
                    break
    return _finish(f"prmsn_{doc.lower()}", qs[: PER_SET + 6])


def queries_bupyo2(corpus: Sequence[Parent]) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:bupyo2:q")  # noqa: S311
    ps = sorted(corpus, key=lambda p: p.pid)
    rng.shuffle(ps)
    qs: list[dict[str, Any]] = []
    for p in ps[:PER_SET]:
        m = p.meta
        i = len(qs)
        multi = len(m["ages"]) > 1
        if i % 2 == 0:  # 키워드(성분 + 제형 또는 연령)
            part = m["forms"][0].split(",")[0].strip() if i % 4 == 0 else m["ages"][0]
            qs.append({"style": "kw", "query": f"{m['ing'].split(' + ')[0]} {part}", "gold": [p.pid], "rule": f"{p.pid} 성분 + {'제형' if i % 4 == 0 else '연령'}"})
        else:
            age = m["ages"][-1] if multi else m["ages"][0]
            daily = (i // 2) % 2 == 1
            q = f"{m['ing']} {age}에 먹어도 되나요" if daily else f"{m['ing']} 연령 금기 {age}"
            qs.append({"style": "daily" if daily else "struct", "query": q, "gold": [p.pid], "rule": f"{p.pid} 성분 + 연령"})
    return _finish("bupyo2", qs)


def queries_l2_combo(sample: Sequence[Parent], corpus: Sequence[Parent]) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:l2_combo:q")  # noqa: S311
    ps = sorted(sample, key=lambda p: p.pid)
    rng.shuffle(ps)
    qs: list[dict[str, Any]] = []
    for p in ps:
        if len(qs) >= PER_SET:
            break
        m = p.meta
        i = len(qs)
        if i % 2 == 0:  # 키워드: 성분A + 사유 단어
            idx = TokenIndex([Parent(q.pid, q.group, " ".join(c["reason"] for c in q.meta["combos"]), q.meta) for q in corpus])
            r = kw_query(rng, m["combos"][0]["reason"], idx, want=2, max_gold=40)
            if not r:
                continue
            a = m["nameA"].split("+")[0].strip()
            gold = [g for g in r[1] if g.startswith(f"l2:{m['codes'][0]}+") or g.endswith(f"+{m['codes'][0]}")]
            if p.pid not in gold:
                continue
            qs.append({"style": "kw", "query": f"{a} {r[0]}", "gold": sorted(gold), "rule": f"{p.pid} 성분A + 사유 단어(같은 사유 쌍 포함)"})
        else:
            daily = (i // 2) % 2 == 1
            a, b = m["nameA"], m["nameB"]
            qs.append({"style": "daily" if daily else "struct", "query": f"{a}랑 {b} 같이 먹어도 되나요" if daily else f"{a} {b} 병용금기 사유", "gold": [p.pid], "rule": f"{p.pid} 성분쌍"})
    return _finish("l2_combo", qs)


def queries_l2_detail(sample: Sequence[Parent], corpus: Sequence[Parent]) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}:l2_detail:q")  # noqa: S311
    ps = sorted(sample, key=lambda p: p.pid)
    rng.shuffle(ps)
    idx = TokenIndex(corpus)
    by_name: dict[tuple[str, str], list[str]] = {}
    for p in corpus:
        by_name.setdefault((p.meta["kind"], p.meta["name"].lower()), []).append(p.pid)
    qs: list[dict[str, Any]] = []
    for p in ps:
        if len(qs) >= PER_SET:
            break
        m = p.meta
        i = len(qs)
        kword = "임부" if m["kind"] == "preg" else "연령"
        if i % 2 == 0:
            r = kw_query(rng, m["items"][0][1], idx, want=2, max_gold=60)
            if not r or p.pid not in r[1]:
                continue
            gold = [g for g in r[1] if g.startswith(f"l2d:{m['kind']}:")]
            qs.append({"style": "kw", "query": f"{kword} {r[0]}", "gold": sorted(gold), "rule": f"{p.pid} 문구의 드문 단어(같은 종류 문구 포함)"})
        else:
            daily = (i // 2) % 2 == 1
            name = m["name"].split(",")[0].strip()
            if m["kind"] == "preg":
                q = f"{name} 임신 중에 먹어도 되나요" if daily else f"{name} 임부 금기"
            else:
                q = f"{name} 아이에게 먹여도 되나요" if daily else f"{name} 연령 금기"
            qs.append({"style": "daily" if daily else "struct", "query": q, "gold": sorted(by_name[(m["kind"], m["name"].lower())]), "rule": f"{p.pid} 성분(같은 이름 포함)"})
    return _finish("l2_detail", qs)


# --------------------------------------------------------------------------- 코퍼스 구성

@dataclass
class Built:
    parents: dict[str, list[Parent]]  # 소스 → 코퍼스(샘플+방해)
    sample: dict[str, list[Parent]]
    chunks: dict[str, dict[str, list[Chunk]]]  # 소스 → 후보 → 청크(샘플 코퍼스 기준)
    queries: dict[str, list[dict[str, Any]]]


def build_all(loaded: dict[str, list[Parent]], scale: float = 1.0) -> Built:
    parents: dict[str, list[Parent]] = {}
    sample: dict[str, list[Parent]] = {}
    chunks: dict[str, dict[str, list[Chunk]]] = {}
    for s in SOURCES:
        n_s, n_d = SIZES[s]
        smp, dis = sample_corpus(s, loaded[s], n_s, n_d, scale)
        sample[s] = smp
        parents[s] = smp + dis
        chunks[s] = {c: CHUNKERS[s](parents[s], c) for c in CANDIDATES[s]}
    qs = {
        "eyak": queries_eyak(sample["eyak"], parents["eyak"]),
        "prmsn_nb": queries_prmsn(sample["prmsn"], parents["prmsn"], "NB"),
        "prmsn_ud": queries_prmsn(sample["prmsn"], parents["prmsn"], "UD"),
        "bupyo2": queries_bupyo2(parents["bupyo2"]),
        "l2_combo": queries_l2_combo(sample["l2_combo"], parents["l2_combo"]),
        "l2_detail": queries_l2_detail(sample["l2_detail"], parents["l2_detail"]),
    }
    return Built(parents, sample, chunks, qs)


def emb_text(t: str) -> str:
    return t[:EMB_CHAR_CAP]


def unique_embed_texts(b: Built) -> list[str]:
    seen: dict[str, None] = {}
    for s in SOURCES:
        for c in CANDIDATES[s]:
            for ch in b.chunks[s][c]:
                seen.setdefault(emb_text(ch.text), None)
    for s in QUERY_SETS:
        for q in b.queries[s]:
            seen.setdefault(emb_text(q["query"]), None)
    return sorted(seen)


def text_key(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def plan_numbers(texts: Sequence[str]) -> dict[str, Any]:
    tok = sum(E.estimate_tokens(t) for t in texts)
    return {"texts": len(texts), "chars": sum(len(t) for t in texts), "est_tokens": round(tok), "est_usd": round(E.cost_usd(tok, MODEL), 5)}


def fit_scale(loaded: dict[str, list[Parent]], max_usd: float) -> tuple[float, Built, dict[str, Any]]:
    scale = 1.0
    while True:
        b = build_all(loaded, scale)
        p = plan_numbers(unique_embed_texts(b))
        if p["est_usd"] <= max_usd * FIT_FRACTION or scale <= 0.1:
            return scale, b, p
        scale = round(scale * 0.8, 3)


# --------------------------------------------------------------------------- 검색·적중

def bm25_index(chunks: Sequence[Chunk]) -> BM25:
    return BM25(char_ngrams(normalize_name(c.text)) for c in chunks)


def bm25_rank(bm: BM25, query: str, k: int = E.DEPTH) -> list[int]:
    sc = bm.scores(char_ngrams(normalize_name(query)))
    return [d for d, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def hit_at(ranking: Sequence[int], chunks: Sequence[Chunk], gold: set[str], k: int) -> bool:
    return any(set(chunks[i].parents) & gold for i in ranking[:k])


def tally_hits(rankings: Sequence[Sequence[int]], chunks: Sequence[Chunk], queries: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    res: dict[str, dict[str, int]] = {}
    for r, q in zip(rankings, queries, strict=True):
        gold = set(q["gold"])
        for key in ("all", q["style"]):
            cell = res.setdefault(key, {"n": 0, **{f"top{k}": 0 for k in TOPKS}})
            cell["n"] += 1
            for k in TOPKS:
                cell[f"top{k}"] += hit_at(r, chunks, gold, k)
    return res


def cell_text(c: dict[str, int], k: int) -> str:
    lo, hi = E.wilson(c[f"top{k}"], c["n"])
    return f"{c[f'top{k}']}/{c['n']} [{lo:.2f}–{hi:.2f}]" + (" n≤8" if c["n"] <= 8 else "")


# --------------------------------------------------------------------------- 용량 추정

def size_stats(chunks: Sequence[Chunk]) -> dict[str, Any]:
    n = len(chunks)
    lens = [len(c.text) for c in chunks]
    toks = [E.estimate_tokens(c.text) for c in chunks]
    return {"n": n, "avg_chars": round(sum(lens) / n, 1) if n else 0, "max_chars": max(lens, default=0), "avg_tokens": round(sum(toks) / n, 1) if n else 0,
            "max_tokens": round(max(toks, default=0)), "text_bytes": sum(len(c.text.encode("utf-8")) for c in chunks), "over_cap": sum(x > EMB_CHAR_CAP for x in lens)}


def storage_mb(st: dict[str, Any], vec_dim_scale: float = 1.0) -> dict[str, float]:
    """추정 MB: 벡터 6KB×수, 원문, 행 오버헤드 300B×수, HNSW ≈ 벡터×1.3(실측 아님)."""
    vec = st["n"] * VEC_BYTES * vec_dim_scale
    return {"vec": vec / 1e6, "text": (st["text_bytes"] + st["n"] * ROW_OVERHEAD) / 1e6, "hnsw": vec * HNSW_FACTOR / 1e6, "total": (vec * (1 + HNSW_FACTOR) + st["text_bytes"] + st["n"] * ROW_OVERHEAD) / 1e6}


def full_chunk_stats(loaded: dict[str, list[Parent]]) -> dict[str, dict[str, dict[str, Any]]]:
    return {s: {c: size_stats(CHUNKERS[s](loaded[s], c)) for c in CANDIDATES[s]} for s in SOURCES}


def capacity_md(stats: dict[str, dict[str, dict[str, Any]]], loaded: dict[str, list[Parent]], n_eyak_items: int, n_prmsn_items: int) -> str:
    L = ["# 청크 수·크기·용량 추정 (전체 로컬 재료 기준, 호출 0)", "",
         "- 토큰은 문자 수 근사(한글 음절 1.7토큰 — 보수적, tiktoken 없음). 용량은 **추정**이다: 벡터 6,144B(1536차원 float4)×청크 수 + 원문(UTF-8) + 행 오버헤드 300B×수 + HNSW 인덱스를 벡터의 1.3배로 어림(실측 아님).",
         "- Supabase 무료 DB 500MB, 현재 사용 24MB(BE-09 판정 테이블) → 남는 약 476MB가 근거 코퍼스 예산이다. `over_cap`은 임베딩 입력 글자 상한 3,000자를 넘는 청크 수.", "",
         "| 소스 | 후보 | 청크 수 | 평균 글자 | 최대 글자 | 평균 토큰≈ | 최대 토큰≈ | 3,000자 초과 | 벡터 MB | 원문 MB | HNSW MB | 합계 MB |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in SOURCES:
        for c in CANDIDATES[s]:
            st = stats[s][c]
            m = storage_mb(st)
            L.append(f"| {s} | {c} | {st['n']:,} | {st['avg_chars']} | {st['max_chars']:,} | {st['avg_tokens']} | {st['max_tokens']:,} | {st['over_cap']} | {m['vec']:.1f} | {m['text']:.1f} | {m['hnsw']:.1f} | {m['total']:.1f} |")
    L += ["", f"※ prmsn은 로컬 스냅샷 허가 상세 {n_prmsn_items}개 기준이다. e약은요 {n_eyak_items}개 기준 eyak은 전수."]
    scale = max(n_eyak_items / max(n_prmsn_items, 1), 1)
    L += ["", "## 전체 코퍼스 시나리오(추정): 소스별 후보 하나씩 고를 때 합계 MB", "",
          f"허가 상세는 스냅샷 {n_prmsn_items}개를 e약은요 제품 수 {n_eyak_items}개까지 **선형 확대**(×{scale:.1f})한 추정이다(제품마다 분량이 다르므로 추정일 뿐).", "",
          "| 시나리오 | 구성 | 합계 MB(추정) | 500MB−24MB 대비 |", "|---|---|---|---|"]

    def tot(sel: dict[str, str], prmsn_x: float) -> float:
        t = 0.0
        for s, c in sel.items():
            t += storage_mb(stats[s][c])["total"] * (prmsn_x if s == "prmsn" else 1.0)
        return t

    scen = [("가장 잘게", {"eyak": "sentence", "prmsn": "sentence", "bupyo2": "row_ctx", "l2_combo": "combo", "l2_detail": "phrase"}),
            ("중간", {"eyak": "section_hdr", "prmsn": "para_hdr", "bupyo2": "row_ctx", "l2_combo": "combo", "l2_detail": "ingredient"}),
            ("가장 크게", {"eyak": "section", "prmsn": "article", "bupyo2": "row_hdr", "l2_combo": "pair_group", "l2_detail": "ingredient"})]
    for nm, sel in scen:
        for px, tag in ((scale, f"허가 상세 {n_eyak_items}개"), (1.0, f"허가 상세 {n_prmsn_items}개만")):
            t = tot(sel, px)
            L.append(f"| {nm} / {tag} | {', '.join(f'{k}:{v}' for k, v in sel.items())} | {t:,.0f} | {'초과' if t > 476 else '안'} ({t / 476:.0%}) |")
    L += ["", "넘는 경우의 대응(제안, 미시험): ① 문단 단위로 올리고 3,000자 초과 청크만 쪼갠다 ② 라벨 선별(경고·상호작용·임부·소아·고령자·용법용량 조항만) ③ 임베딩 차원을 `dimensions` 파라미터로 줄임(1536→512면 벡터 1/3, 품질은 미측정) ④ L2 병용 사유는 쌍 묶음으로 줄인다."]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- 표 인식 확인

def table_check_md(bup: list[Parent], prm: list[Parent]) -> str:
    L = ["# 표 인식 확인 (눈으로 보는 샘플, 호출 0)", "", "## 1. 별표 2 행 청크 (연번·성분·연령·제형 열 이름)", ""]
    rng = random.Random(f"{SEED}:tablecheck")  # noqa: S311
    multi = [p for p in bup if len(p.meta["ages"]) > 1]
    pick = [bup[8]] if len(bup) > 8 else []
    pick += rng.sample([p for p in bup if p not in pick], 1) + rng.sample(multi, 1) if multi else rng.sample(bup, 2)
    for p in pick[:3]:
        L.append(f"### 연번 {p.meta['no']} {p.meta['ing']}")
        for cand in CANDIDATES["bupyo2"]:
            ch = CHUNKERS["bupyo2"]([p], cand)[0]
            L.append(f"- `{cand}`: {ch.text}")
        L.append("")
    L += ["별표 2 열 이름은 `row_hdr`·`row_ctx`에서만 청크 안에 있다(`row_plain`에는 없다). 여러 줄(`<br>`) 행은 연령·제형 개수가 같으면 `row_ctx`가 쌍으로 맞춘다. 개수가 다르면 `/`로 이어 붙여 짝이 사라진다(깨진 사례 아래 기록).", ""]
    broken = [p for p in bup if len(p.meta["ages"]) != len(p.meta["forms"])]
    L.append(f"- 연령·제형 줄 수가 다른 행: {len(broken)}개 " + ", ".join(f"연번 {p.meta['no']}({len(p.meta['ages'])}/{len(p.meta['forms'])})" for p in broken[:8]))
    L += ["", "## 2. 허가 상세 UD 용법용량 표 (XML `PARAGRAPH tagName=\"table\"` 안 HTML)", ""]
    udt = [p for p in prm if p.meta["doc"] == "UD" and any(k == "table" for k, _ in p.meta["paras"])]
    nbt = [p for p in prm if p.meta["doc"] == "NB" and any(k == "table" for k, _ in p.meta["paras"])]
    L.append(f"- 표가 든 UD 조항 {len(udt)}개(전체 UD 조항 {sum(p.meta['doc'] == 'UD' for p in prm)}개), 표가 든 NB 조항 {len(nbt)}개. XML 파싱 실패 조항 수는 로더에서 빈 목록이라 별도 집계하지 않았다.")
    stacked = 0
    for p in udt + nbt:
        for k, t in p.meta["paras"]:
            if k == "table" and table_rows_struct(t)[2]:
                stacked += 1
    L.append(f"- 한 셀에 `<p>`가 쌓여 있어 행으로 풀어야 하는 표(UD+NB): {stacked}개. 풀지 않고 평문으로 이어 붙이면 열 이름과 값의 짝이 사라진다.")
    L.append("")
    shown = 0
    for p in udt:
        tabs = [t for k, t in p.meta["paras"] if k == "table"]
        for t in tabs:
            header, rows, uns = table_rows_struct(t)
            if shown >= 3:
                break
            shown += 1
            L += [f"### 사례 {shown}: {p.meta['name']} ({p.pid}), 쌓인 셀 {'있음' if uns else '없음'}", "", f"- 열 이름: {header}", f"- 평문 이어붙임(sentence 후보): {table_naive(t)[:260]}", "- 구조화(article·para_hdr 후보):"]
            L += [f"  - {r[:200]}" for r in rows[:4]]
            chs = [c for c in chunk_prmsn([p], "para_hdr") if "표 열:" in c.text]
            L.append(f"- para_hdr 표 청크 수 {len(chs)}개(6행씩), 각 청크 첫머리에 열 이름 반복: " + ("예" if chs and all("표 열:" in c.text for c in chs) else "아니오"))
            sent = [c for c in chunk_prmsn([p], "sentence") if table_naive(t)[:20] in c.text]
            L.append(f"- sentence 후보는 표 전체를 한 청크로 둠(길이 {len(sent[0].text) if sent else '-'}자, 열 이름은 본문 앞쪽에 한 번만). 표 행이 길면 3,000자에서 잘림.")
            L.append("")
    if shown < 3:
        L.append(f"(UD 표 사례가 {shown}개뿐이라 NB 표로 보충하지 않았다.)")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- 임베딩 실행

def _token_batches(texts: Sequence[str]) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    tok = 0.0
    for t in texts:
        et = E.estimate_tokens(t)
        if cur and (len(cur) >= EMB_BATCH_TEXTS or tok + et > EMB_BATCH_TOKENS):
            out.append(cur)
            cur, tok = [], 0.0
        cur.append(t)
        tok += et
    if cur:
        out.append(cur)
    return out


def fetch_retry(model_id: str, texts: list[str], key: str, tries: int = 8, wait: float = 25.0) -> dict[str, Any]:
    """분당 토큰(TPM) 한도 429면 기다렸다 다시 부른다. 429는 처리 전에 거절되므로 비용이 들지 않는다."""
    for i in range(tries):
        try:
            return E.http_embed(model_id, texts, key)
        except RuntimeError as exc:
            if "status=429" not in str(exc) or i == tries - 1:
                raise
            time.sleep(wait)
    raise RuntimeError("unreachable")


def embed_all(emb: E.Embedder, texts: Sequence[str]) -> tuple[array, int]:
    out = array("f")
    dim = 0
    for bi, chunk in enumerate(_token_batches(texts)):
        vecs = E.decode_b64_vectors(emb.embed_batch(chunk, f"be05-01:{bi}"))
        if len(vecs) % len(chunk):
            raise ValueError("응답 벡터 수가 입력 수와 맞지 않는다")
        dim = len(vecs) // len(chunk)
        out.extend(vecs)
    return out, dim


# --------------------------------------------------------------------------- 명령

PLAN_JSON = OUT_DIR / "plan.json"
VEC_NPY = OUT_DIR / "vectors.npy"
VEC_INDEX = OUT_DIR / "vectors_index.json"


def _load_all() -> dict[str, list[Parent]]:
    return {s: LOADERS[s]() for s in SOURCES}


def cmd_inspect(args: argparse.Namespace) -> int:
    loaded = _load_all()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = full_chunk_stats(loaded)
    n_eyak = len({p.group for p in loaded["eyak"]})
    n_prm = len({p.group for p in loaded["prmsn"]})
    (OUT_DIR / "capacity.md").write_text(capacity_md(stats, loaded, n_eyak, n_prm), encoding="utf-8")
    (OUT_DIR / "capacity.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "table_check.md").write_text(table_check_md(loaded["bupyo2"], loaded["prmsn"]), encoding="utf-8")
    for s in SOURCES:
        print(s, {c: stats[s][c]["n"] for c in CANDIDATES[s]})
    print("저장: capacity.md, capacity.json, table_check.md")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    loaded = _load_all()
    scale, b, p = fit_scale(loaded, args.max_usd)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    texts = unique_embed_texts(b)
    plan = {"scale": scale, "max_usd": args.max_usd, "fingerprint": hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16], **p,
            "chunks": {s: {c: len(b.chunks[s][c]) for c in CANDIDATES[s]} for s in SOURCES}, "queries": {s: len(b.queries[s]) for s in QUERY_SETS}}
    PLAN_JSON.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"샘플 배율 {scale}, 고유 텍스트 {p['texts']:,}개, 글자 {p['chars']:,}, 토큰≈{p['est_tokens']:,}(문자 수 근사, 보수적), 예상 ${p['est_usd']} (상한 ${args.max_usd}의 {FIT_FRACTION:.0%} 이하로 맞춤)")
    print("질의:", plan["queries"])
    for s in SOURCES:
        print(f"  {s}: {plan['chunks'][s]}")
    print("호출 0(plan은 OpenAI를 부르지 않는다).")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.max_usd <= 0:
        print("--max-usd는 0보다 커야 한다")
        return 2
    if not PLAN_JSON.exists():
        print("plan.json이 없다. 먼저 plan을 실행한다.")
        return 2
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    b = build_all(_load_all(), plan["scale"])
    texts = unique_embed_texts(b)
    fp = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]
    if fp != plan["fingerprint"]:
        print("plan.json과 현재 코퍼스가 다르다(지문 불일치). plan을 다시 실행한다.")
        return 2
    est = E.cost_usd(sum(E.estimate_tokens(t) for t in texts), MODEL)
    if est > args.max_usd:
        print(f"어림 ${est:.4f}가 상한 ${args.max_usd}를 넘는다. 호출하지 않는다.")
        return 3
    key = E.resolve_key()
    if not key:
        print("OPENAI_API_KEY를 환경변수나 .env 설정에서 찾지 못했다.")
        return 2
    os.environ.setdefault("LLM_CACHE", "record")
    if cache_mode() == "off":
        print("LLM_CACHE=off에서는 실행하지 않는다.")
        return 2
    E._ensure_cache_importable()
    emb = E.Embedder(MODEL, args.max_usd, lambda model_id, ts: fetch_retry(model_id, ts, key))
    t0 = time.perf_counter()
    try:
        vec, dim = embed_all(emb, texts)
    except (E.CapReached, BudgetExceeded) as exc:
        print(f"중단: {exc}\n이 실행 ${emb.spent:.4f}, 호출 {emb.calls}회, 캐시 적중 {emb.cached_batches}. 같은 명령을 다시 실행하면 이어서 한다.")
        return 3
    E.write_npy(VEC_NPY, vec, len(texts), dim)
    meta = {"model": E.MODELS[MODEL], "dim": dim, "texts": len(texts), "keys": [text_key(t) for t in texts], "run_calls": emb.calls, "run_cached_batches": emb.cached_batches,
            "run_tokens": emb.tokens, "run_usd": round(emb.spent, 6), "seconds": round(time.perf_counter() - t0, 1), "fingerprint": fp, "max_usd": args.max_usd}
    VEC_INDEX.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"완료: {len(texts):,}개 × {dim}차원, 호출 {emb.calls}회(캐시 적중 {emb.cached_batches}), 토큰 {emb.tokens:,}, 비용 ${emb.spent:.4f} / 상한 ${args.max_usd}")
    return 0


def evaluate(b: Built, vec_by_key: dict[str, array], dim: int) -> dict[str, Any]:
    """{질의 세트: {후보: {방식: {스타일|all: 집계}}}}."""
    res: dict[str, Any] = {}
    for qs_name in QUERY_SETS:
        src = QUERY_CORPUS[qs_name]
        qs = b.queries[qs_name]
        if not qs:
            continue
        qv = array("f")
        for q in qs:
            qv.extend(vec_by_key[text_key(emb_text(q["query"]))])
        res[qs_name] = {}
        for cand in CANDIDATES[src]:
            chunks = b.chunks[src][cand]
            dv = array("f")
            for c in chunks:
                dv.extend(vec_by_key[text_key(emb_text(c.text))])
            bm = bm25_index(chunks)
            bmr = [bm25_rank(bm, q["query"]) for q in qs]
            dr = E.dense_topk(qv, dv, len(qs), len(chunks), dim)
            hy = [E.rrf([x, y]) for x, y in zip(bmr, dr, strict=True)]
            res[qs_name][cand] = {m: tally_hits(r, chunks, qs) for m, r in (("BM25", bmr), ("임베딩", dr), ("하이브리드(RRF)", hy))}
    return res


def render_report_tables(res: dict[str, Any], b: Built) -> str:
    L: list[str] = []
    for qs_name, cands in res.items():
        qs = b.queries[qs_name]
        styles = {s: sum(q["style"] == s for q in qs) for s in sorted({q["style"] for q in qs})}
        L += [f"### {qs_name} (질의 {len(qs)}개, 스타일별 {styles})", "", "| 후보 | 방식 | top-1 | top-5 | top-10 |", "|---|---|---|---|---|"]
        for cand, ms in cands.items():
            for m, cells in ms.items():
                c = cells["all"]
                L.append(f"| {cand} | {m} | {cell_text(c, 1)} | {cell_text(c, 5)} | {cell_text(c, 10)} |")
        L += ["", "스타일별 top-5 (kw=키워드 부분집합, struct=제품명+주제 구조, daily=일상어 변형, table=표 질의):", "", "| 후보 | 방식 | " + " | ".join(styles) + " |", "|---|---|" + "---|" * len(styles)]
        for cand, ms in cands.items():
            for m, cells in ms.items():
                L.append(f"| {cand} | {m} | " + " | ".join(cell_text(cells[s], 5) if s in cells else "-" for s in styles) + " |")
        L.append("")
    return "\n".join(L)


def cmd_report(args: argparse.Namespace) -> int:
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    meta = json.loads(VEC_INDEX.read_text(encoding="utf-8"))
    b = build_all(_load_all(), plan["scale"])
    texts = unique_embed_texts(b)
    if hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16] != meta["fingerprint"]:
        raise SystemExit("저장된 벡터와 현재 코퍼스가 맞지 않는다(지문 불일치).")
    vals, n, dim = E.read_npy(VEC_NPY)
    vec_by_key = {k: vals[i * dim : (i + 1) * dim] for i, k in enumerate(meta["keys"])}
    res = evaluate(b, vec_by_key, dim)
    (OUT_DIR / "report.json").write_text(json.dumps({"plan": plan, "run": {k: v for k, v in meta.items() if k != "keys"}, "queries": b.queries, "results": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    head = ["# BE-05-01 청킹 단위 시험 결과 (개발용 질의, 평가 수치 아님)", "",
            f"- 샘플 배율 {plan['scale']}, 고유 텍스트 {meta['texts']:,}개, 모델 {meta['model']} {meta['dim']}차원, 실호출 {meta['run_calls']}회(캐시 적중 {meta['run_cached_batches']}), 토큰 {meta['run_tokens']:,}, 비용 ${meta['run_usd']} / 상한 ${meta['max_usd']}",
            "- 적중 = 정답 상위 단위(`parent_id`)의 청크가 top-k(청크 기준)에 하나라도. k/n과 Wilson 95% 구간. 칸당 n≤8이면 유의성을 주장하지 않는다. 구간이 겹치면 구분하지 못한 것이다.", ""]
    (OUT_DIR / "report.md").write_text("\n".join(head) + render_report_tables(res, b), encoding="utf-8")
    print("저장: report.md, report.json")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect").set_defaults(fn=cmd_inspect)
    p = sub.add_parser("plan")
    p.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    p.set_defaults(fn=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    r.set_defaults(fn=cmd_run)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    install_excepthook()  # S-05: 키를 쓰는 스크립트의 예외·logging 출력 가리기
    raise SystemExit(main())
