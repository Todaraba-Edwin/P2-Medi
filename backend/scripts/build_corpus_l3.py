"""BE-05 L3·L1 청크 빌더(로컬 파일만, 원격 DB·API 호출 0). L2는 `build_corpus_l2.py`가 만든다.

만드는 것(BE-05-02 A 확정 단위):
  l3_eyak.jsonl    e약은요 절(항목) + 제품명·항목 머리말. 기준일 = 수집일. ingr_codes는 BE-10 사전(`drug_dict.json`) 제품 연결로 붙이고 연결 없으면 빈 값
  l3_prmsn.jsonl   허가 상세(EE·UD·NB XML) 문단 묶음(약 500자) + 제품명·doc·조항 제목 머리말, 표는 구조 파싱해 행 묶음마다 열 이름 반복
  l1_notice.jsonl  고시 제1~9조(조·호·목 + 상위 조 제목) + 별표 1·3 표·행 청크. 조문 참조는 정규식으로 refs 연결
출력은 `data/mock/corpus/`(로컬 전용). `--label-filter selected`는 `corpus/selected/`에 라벨 선별본을 쓴다(기본 all).

표 폴백 규칙(허가 상세 XML 표):
  1) 열 이름 칸이 비어 있고 다음 행이 짧은 머리글처럼 보이면 두 행을 열 이름으로 결합한다. 그래도 비면 `열N`.
  2) 첫 칸만 값이 있는 행(하위 제목, 예 `1. 동맥투여`)은 행으로 내지 않고 뒤따르는 행들의 머리말(`[소제목]`)로 쓴다.
  3) 한 셀에 `<p>`가 쌓였고 쌓인 개수가 같으면 `<p>` 단위로 행을 푼다. 개수가 다르면 풀지 않고 칸마다 ` / `로 이어 열 이름과 값의 짝을 지킨다.
  5) rowspan/colspan 등으로 칸 수가 열 수와 다른 행이 30% 이상인 표는 열·값 짝을 만들지 않고 칸을 ` | `로 잇는다(표 열 줄에 짝 확인 필요 표시).
  4) 행 묶음(6행·1,500자 이하)마다 열 이름을 반복하고, 한 청크는 3,000자를 넘지 않게 쪼갠다.

사용(작업 위치 `backend/`): `.venv/bin/python scripts/build_corpus_l3.py build [--label-filter all|selected] [--check]` / `verify` / `capacity` / `samples`
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import build_corpus_l2 as L2  # noqa: E402
from chunk_trial import EYAK_FIELDS, SNAP, clean_field, parse_table, split_sentences  # noqa: E402

from app.db.doc_meta import chunk_meta  # noqa: E402
from app.db.source_files import GOSI_PDF_NAME  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = L2.OUT_DIR
NOTICE_MD = ROOT / "P2-doc" / "MFDS_병용금기_지정규정_고시.md"
BUPYO1_MD = ROOT / "data" / "mock" / "parsed" / "gosi_bupyo1_pdfplumber.md"
BUPYO3_MD = ROOT / "data" / "mock" / "parsed" / "gosi_bupyo3_pdfplumber.md"
DICT_JSON = ROOT / "data" / "mock" / "dict" / "drug_dict.json"
EYAK_DIR = SNAP / "eyak-all"
PRMSN_DIR = SNAP / "prmsn-detail"

FILES = {"eyak": "l3_eyak.jsonl", "prmsn": "l3_prmsn.jsonl", "notice": "l1_notice.jsonl"}
EMB_CHAR_CAP = 3000  # 청크 글자 상한(임베딩 입력 한도 안전 여유)
PARA_TARGET = 500
RAGGED_RATIO = 0.3  # 행 중 칸 수가 열 수와 다른 비율이 이 이상이면 짝을 만들지 않는다
ROW_GROUP = 6
ROW_GROUP_CHARS = 1500
EYAK_COLLECT_DATE = "2026-11-10"  # eyak-all `_collect_state.json` timestamp 기준(수집일)
ISSUER_MFDS = L2.ISSUER_MFDS
LICENSE_EYAK = "공공데이터포털 이용허락 조건 확인 필요(e약은요, 미확정)"
LICENSE_PRMSN = "공공데이터포털 이용허락범위 제한 없음(허가정보 API, 설계 문서 11장 표기)"
DOC_LABEL = {"EE": "효능효과", "UD": "용법용량", "NB": "사용상의주의사항"}
KEEP_EYAK = {"efcy", "use_method", "atpn_warn", "atpn", "intrc", "se"}  # selected: 보관법 제외
KEEP_NB_TITLE = ("경고", "투여하지 말", "신중히 투여", "일반적 주의", "이상반응", "상호작용", "임부", "소아", "고령", "노인", "금기")

EXTRA = L2.EXTRA_FIELDS


def mk(kind: str, key: str, text: str, prefix: str, **kw: Any) -> dict[str, Any]:
    c: dict[str, Any] = {f: "" for f in L2.FIELDS + EXTRA}
    c.update({"year": None, "effective_date": None, "parent_id": None, "refs": [], "pair_id": None, "ingr_codes": [], "ingr_names": [], "base_date": L2.BASE_DATE})
    c.update(kw)
    if c["year"] is None and c["base_date"]:
        c["year"] = int(str(c["base_date"])[:4])  # 문서 파일이 없는 API 청크는 수집 기준일의 연도
    c.update({"chunk_kind": kind, "text": text, "chunk_id": f"{prefix}-{L2.sha(kind + '|' + key + chr(31) + text)}"})
    return {f: c[f] for f in L2.FIELDS + EXTRA}


# --------------------------------------------------------------------------- 공통 텍스트 도구

def hard_split(text: str, limit: int) -> list[str]:
    """limit자 이하로 쪼갠다. 문장 경계를 우선하고, 한 문장이 길면 공백, 그래도 길면 글자 수로 자른다."""
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    buf = ""
    for s in split_sentences(text) or [text]:
        while len(s) > limit:
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if buf:
                out.append(buf)
                buf = ""
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if buf and len(buf) + 1 + len(s) > limit:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    return out


def pack_paragraphs(paras: Sequence[str], target: int, room: int) -> list[str]:
    """문단을 target자 안팎 묶음으로. 한 묶음은 room자(머리말을 뺀 한도)를 넘지 않는다."""
    units: list[str] = []
    for p in paras:
        units.extend(hard_split(p, room))
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for u in units:
        if buf and (size + len(u) > target or size + len(u) + 1 > room):
            out.append(" ".join(buf))
            buf, size = [], 0
        buf.append(u)
        size += len(u) + 1
    if buf:
        out.append(" ".join(buf))
    return out


# --------------------------------------------------------------------------- 사전 연결(BE-10)

def load_product_codes(path: Path | None = None) -> dict[str, tuple[list[str], str]]:
    """item_seq → (성분코드들, code_status). 연결이 없으면 빈 목록과 `none`."""
    d = json.loads((path or DICT_JSON).read_text(encoding="utf-8"))
    out: dict[str, tuple[list[str], str]] = {}
    for p in d["products"]:
        codes = sorted(set(p.get("kids_codes") or []) | set(p.get("api_codes") or []))
        status = f"{p.get('code_link')}:{p.get('code_scope')}" if codes else "none"
        out[str(p["item_seq"])] = (codes, status)
    return out


# --------------------------------------------------------------------------- L3 e약은요

def build_eyak_chunks(snap_dir: Path | None = None, codes: dict[str, tuple[list[str], str]] | None = None,
                      collect_date: str = EYAK_COLLECT_DATE) -> list[dict[str, Any]]:
    codes = {} if codes is None else codes
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fp in sorted(glob.glob(str((snap_dir or EYAK_DIR) / "page-*.json"))):
        for it in json.loads(Path(fp).read_text(encoding="utf-8")).get("items", []):
            seq, name = clean_field(it.get("item_seq")), clean_field(it.get("item_name"))
            if not seq or not name:
                continue
            ic, status = codes.get(seq, ([], "none"))
            for f, label in EYAK_FIELDS:
                t = " ".join(clean_field(it.get(f)).split())
                if not t or (seq, f) in seen:
                    continue
                seen.add((seq, f))
                head = f"[{name} · {label}] "
                parts = hard_split(t, EMB_CHAR_CAP - len(head))
                for i, part in enumerate(parts):
                    out.append(mk(
                        "l3_eyak_section", f"{seq}|{f}|{i}", head + part, "l3e", layer="L3", issuer=ISSUER_MFDS, doc_type="e약은요",
                        base_date=collect_date, locator=f"e약은요 item_seq {seq} {label}" + (f" ({i + 1}/{len(parts)})" if len(parts) > 1 else ""),
                        ingr_codes=ic, license=LICENSE_EYAK, source_ref=f"e약은요(의약품개요정보)|eyak-all item_seq {seq}",
                        item_seq=seq, item_name=name, section=label, code_status=status,
                    ))
    return out


# --------------------------------------------------------------------------- 허가 상세 표 구조 파싱

def _is_header_like(row: list[list[str]]) -> bool:
    return bool(row) and all(len(c) <= 1 for c in row) and all(len(" ".join(c)) <= 25 for c in row) and any(c for c in row)


def table_chunks(html_text: str) -> tuple[list[str], list[str], bool]:
    """(열 이름들, 행 문자열들, 짝 확신 여부). 하위 제목 행은 뒤따르는 행 문자열 앞에 `[소제목]`으로 붙는다. 폴백 규칙은 모듈 머리말."""
    rows = [r for r in parse_table(html_text) if any(c for c in r)]
    if not rows:
        return [], [], True
    header = [" ".join(c) for c in rows[0]]
    body = rows[1:]
    if any(not h for h in header) and body and len(body[0]) == len(header) and _is_header_like(body[0]):
        header = [" ".join(x for x in (h, " ".join(c)) if x) for h, c in zip(header, body[0], strict=True)]
        body = body[1:]
    header = [h or f"열{i + 1}" for i, h in enumerate(header)]
    ragged = sum(len(r) != len(header) for r in body)
    if body and ragged / len(body) >= RAGGED_RATIO:
        # 5) rowspan/colspan으로 칸 수가 맞지 않는 표: 열 이름과 값의 짝을 만들지 않고 칸을 ` | `로 이어 붙인다(틀린 짝보다 낫다)
        return header, [" | ".join(" / ".join(c) for c in r) for r in body], False
    out: list[str] = []
    sub = ""
    top = ""  # 가장 최근의 `·`로 시작하지 않는 하위 제목(`· 성인` 같은 하위 항목이 이어 붙는다)
    for r in body:
        filled = [i for i, c in enumerate(r) if c]
        if len(r) > 1 and len(filled) == 1 and filled[0] == 0 and len(r[0]) == 1:
            txt = r[0][0]
            if txt.startswith("·") and top:
                sub = f"{top} {txt}"
            else:
                sub = top = txt  # 하위 제목 행
            continue
        pre = f"[{sub}] " if sub else ""
        if len(r) > 1 and len(r[0]) == 1 and r[0][0].startswith("·") and len(filled) > 1:
            pre = f"[{top} {r[0][0]}] " if top else f"[{r[0][0]}] "  # `· 소아`처럼 라벨이 첫 칸에 든 행: 라벨은 머리말로, 첫 칸 값은 비운다
            r = [[], *r[1:]]
        counts = {len(c) for c in r if len(c) > 1}
        if len(counts) == 1 and len(r) == len(header):
            n = counts.pop()
            for i in range(n):
                vals = [c[i] if len(c) == n else (c[0] if c else "") for c in r]
                out.append(pre + "; ".join(f"{h}={v}" for h, v in zip(header, vals, strict=True) if v))
        else:
            vals = [" / ".join(c) for c in r]
            out.append(pre + "; ".join(f"{h}={v}" for h, v in zip(header, vals, strict=False) if v))
    return header, out, True


def group_rows(header: list[str], rows: list[str], room: int, aligned: bool = True) -> list[str]:
    """행 묶음마다 `표 열: …` 줄을 앞에 붙인다. 묶음은 6행·1,500자 이하, 전체는 room자 이하."""
    hline = ("표 열: " if aligned else "표 열(칸 수가 맞지 않아 열과 값의 짝은 확인 필요): ") + " | ".join(header)
    out: list[str] = []
    buf: list[str] = []
    size = 0
    budget = min(ROW_GROUP_CHARS, room - len(hline) - 1)
    for r in rows:
        for piece in hard_split(r, max(budget, 200)):
            if buf and (len(buf) >= ROW_GROUP or size + len(piece) + 1 > budget):
                out.append(hline + "\n" + "\n".join(buf))
                buf, size = [], 0
            buf.append(piece)
            size += len(piece) + 1
    if buf:
        out.append(hline + "\n" + "\n".join(buf))
    return out


# --------------------------------------------------------------------------- L3 허가 상세

def _para_items(art: ET.Element) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in art.iter("PARAGRAPH"):
        raw = p.text or ""
        if p.get("tagName") == "table" or "<tbody" in raw:
            out.append(("table", raw))
        else:
            t = " ".join(raw.replace("\xa0", " ").split())
            if t:
                out.append(("p", t))
    return out


def prmsn_selected(doc: str, title: str) -> bool:
    return doc == "UD" or (doc == "NB" and any(k in title for k in KEEP_NB_TITLE))


def build_prmsn_chunks(snap_dir: Path | None = None, codes: dict[str, tuple[list[str], str]] | None = None) -> list[dict[str, Any]]:
    codes = {} if codes is None else codes
    out: list[dict[str, Any]] = []
    for fp in sorted(glob.glob(str((snap_dir or PRMSN_DIR) / "item-*.json"))):
        j = json.loads(Path(fp).read_text(encoding="utf-8"))
        r = (j.get("response") or [{}])[0]
        seq, name = clean_field(r.get("ITEM_SEQ")), clean_field(r.get("ITEM_NAME"))
        if not seq or not name:
            continue
        fetched = str(j.get("fetched_at", ""))[:10] or L2.BASE_DATE
        ic, status = codes.get(seq, ([], "none"))
        for doc, key in (("EE", "EE_DOC_DATA"), ("UD", "UD_DOC_DATA"), ("NB", "NB_DOC_DATA")):
            xml = clean_field(r.get(key))
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)  # noqa: S314 - 로컬 공공 API 스냅샷(신뢰 입력)
            except ET.ParseError:
                continue
            for ai, art in enumerate(root.iter("ARTICLE")):
                title = (art.get("title") or "").strip()
                items = _para_items(art)
                if not items:
                    continue
                head = f"[{name} · {DOC_LABEL[doc]} · {title or '본문'}]"
                room = EMB_CHAR_CAP - len(head) - 1
                bodies: list[tuple[str, str]] = []  # (종류, 본문)
                buf: list[str] = []

                def flush(buf: list[str] = buf, bodies: list[tuple[str, str]] = bodies, room: int = room) -> None:
                    bodies.extend(("p", b) for b in pack_paragraphs(buf, PARA_TARGET, room))
                    buf.clear()

                for k, t in items:
                    if k == "p":
                        buf.append(t)
                        continue
                    flush()
                    header, rows, aligned = table_chunks(t)
                    if header and rows:
                        bodies.extend(("table", g) for g in group_rows(header, rows, room, aligned))
                    elif header:
                        bodies.append(("table", "표 열: " + " | ".join(header)))
                flush()
                first_table: str | None = None
                for ci, (k, body) in enumerate(bodies):
                    c = mk(
                        "l3_prmsn_para" if k == "p" else "l3_prmsn_table", f"{seq}|{doc}|{ai:02d}|{ci:03d}", f"{head} {body}", "l3p",
                        layer="L3", issuer=ISSUER_MFDS, doc_type="허가사항", base_date=fetched,
                        locator=f"허가상세 item_seq {seq} {DOC_LABEL[doc]} {title or '본문'} #{ci + 1}", ingr_codes=ic, license=LICENSE_PRMSN,
                        source_ref=f"의약품 제품 허가정보 허가 상세|prmsn-detail item_seq {seq} {doc}_DOC_DATA",
                        item_seq=seq, item_name=name, section=f"{doc} {title or '본문'}", code_status=status,
                    )
                    if k == "table":
                        if first_table is None:
                            first_table = c["chunk_id"]
                        elif first_table != c["chunk_id"]:
                            c["parent_id"] = first_table  # 같은 조항의 첫 표 청크(이어지는 행 묶음이 시작 청크를 가리킨다)
                    out.append(c)
    return out


# --------------------------------------------------------------------------- L1 고시 조문

ART_HEAD = re.compile(r"^### \(\d+\) 제(\d+)조\((.+)\)\s*$")
HO_RE = re.compile(r"^(\d+)\. (.+)$")
MOK_RE = re.compile(r"^\s+- ([가-힣])\. (.+)$")
TERM_RE = re.compile(r'^"([^"]+)"(?:이란|란)')


def parse_notice(md: str) -> list[dict[str, Any]]:
    """조 목록: {no, title, stem(조 본문 줄들), hos: [{no, text, moks: [(가, 문장)]}]}"""
    arts: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in md.splitlines():
        m = ART_HEAD.match(line)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2), "stem": [], "hos": []}
            arts.append(cur)
            continue
        if line.startswith("#"):
            cur = None
            continue
        if cur is None or not line.strip():
            continue
        h, k = HO_RE.match(line), MOK_RE.match(line)
        if k and cur["hos"]:
            cur["hos"][-1]["moks"].append((k.group(1), k.group(2).strip()))
        elif h:
            cur["hos"].append({"no": int(h.group(1)), "text": h.group(2).strip(), "moks": []})
        else:
            cur["stem"].append(line.strip())
    return arts


def read_bupyo(path: Path) -> tuple[str, list[str], list[list[str]]]:
    """(표 이름, 열 이름들, 행들). `<삭제>` 행은 제외하고 `<br>`는 ` / `로 바꾼다."""
    text = path.read_text(encoding="utf-8")
    name = re.search(r"^table: (.+)$", text, re.M)
    header: list[str] = []
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip().replace("<br>", " / ") for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "연번":
            header = cells
        elif header and len(cells) >= len(header) and cells[0].isdigit() and not any("삭제" in c for c in cells):
            rows.append(cells[: len(header) - 1] + [" ".join(cells[len(header) - 1:])])
    return (name.group(1) if name else path.stem), header, rows


BUPYO_TITLE = {1: "별표 1 병용금기 성분 (제4조 관련)", 3: "별표 3 임부금기 성분 (제6조 관련)"}


def build_notice_chunks(notice_md: Path | None = None, bup1: Path | None = None, bup3: Path | None = None,
                        bup2_table_id: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(청크들, 보고 정보). 별표 1·3 변환본이 없으면 건너뛰고 skipped에 적는다."""
    arts = parse_notice((notice_md or NOTICE_MD).read_text(encoding="utf-8"))
    base = {"layer": "L1", "issuer": ISSUER_MFDS, "doc_type": "고시", "notice_no": L2.BUPYO2_NOTICE_NO, "license": L2.LICENSE_GOSI,
            "source_ref": "의약품 병용금기 성분 등의 지정에 관한 규정|MFDS_병용금기_지정규정_고시.md", **chunk_meta(GOSI_PDF_NAME)}
    chunks: list[dict[str, Any]] = []
    art_id: dict[int, str] = {}
    ho_id: dict[tuple[int, int], str] = {}
    terms: dict[str, str] = {}
    pending: list[dict[str, Any]] = []  # refs를 나중에 채울 조·호·목 청크
    for a in arts:
        head = f"제{a['no']}조({a['title']})"
        stem = " ".join(a["stem"])
        ac = mk("l1_notice_article", f"art{a['no']}", f"{head} {stem}".strip(), "l1n", locator=f"제{a['no']}조", ingr_names=[], **base)
        chunks.append(ac)
        pending.append(ac)
        art_id[a["no"]] = ac["chunk_id"]
        for ho in a["hos"]:
            hc = mk("l1_notice_item", f"art{a['no']}|ho{ho['no']}", f"[{head}] 제{ho['no']}호 {ho['text']}", "l1n",
                    parent_id=ac["chunk_id"], locator=f"제{a['no']}조 제{ho['no']}호", **base)
            chunks.append(hc)
            pending.append(hc)
            ho_id[(a["no"], ho["no"])] = hc["chunk_id"]
            m = TERM_RE.match(ho["text"])
            if m and a["no"] == 3:
                terms[m.group(1)] = hc["chunk_id"]
            for mk_, mt in ho["moks"]:
                mc = mk("l1_notice_sub", f"art{a['no']}|ho{ho['no']}|{mk_}", f"[{head} 제{ho['no']}호] {mk_}. {mt}", "l1n",
                        parent_id=hc["chunk_id"], locator=f"제{a['no']}조 제{ho['no']}호 {mk_}목", **base)
                chunks.append(mc)
                pending.append(mc)
    skipped: list[str] = []
    table_id: dict[int, str] = {}
    if bup2_table_id:
        table_id[2] = bup2_table_id
    for no, path, art_no in ((1, bup1 or BUPYO1_MD, 4), (3, bup3 or BUPYO3_MD, 6)):
        if not path.exists():
            skipped.append(f"별표 {no}: {path.name} 없음")
            continue
        tname, header, rows = read_bupyo(path)
        title = BUPYO_TITLE[no]
        page = re.search(r"\((.+?)\)", tname)
        ttext = f"[{title}] 열: {' | '.join(header)}. 행 {len(rows)}개(연번 {rows[0][0]}~{rows[-1][0]}, 삭제 행 제외)." + (f" 쪽 {page.group(1)}." if page else "")
        tc = mk(f"l1_bupyo{no}_table", f"bupyo{no}", ttext, "l1t", parent_id=art_id.get(art_no), locator=f"별표 {no}", **base)
        chunks.append(tc)
        table_id[no] = tc["chunk_id"]
        for r in rows:
            body = "; ".join(f"{h}: {v}" for h, v in zip(header, r, strict=True) if v)
            chunks.append(mk(f"l1_bupyo{no}_row", f"bupyo{no}|{int(r[0]):04d}", f"[{title}] {body}", "l1r", parent_id=tc["chunk_id"],
                             locator=f"별표 {no} 연번 {r[0]}", ingr_names=[x for x in (r[1:3] if no == 1 else r[1:2]) if x], **base))
    # --- 조문 참조(refs): 별표 N / 제N조 / 정의된 용어
    unresolved: list[str] = []
    ref_log: list[dict[str, Any]] = []
    for c in pending:
        own_art = int(re.match(r"제(\d+)조", c["locator"]).group(1))  # type: ignore[union-attr]
        refs: list[str] = []
        for m in re.finditer(r"별표\s*(\d+)", c["text"]):
            t = table_id.get(int(m.group(1)))
            if t:
                refs.append(t)
            else:
                unresolved.append(f"{c['locator']}: {m.group(0)}")
        for m in re.finditer(r"제(\d+)조(의\d+)?", c["text"]):
            n = int(m.group(1))
            if n == own_art:
                continue  # 자기 조(머리말·본문 안의 자기 언급)
            if m.group(2):
                unresolved.append(f"{c['locator']}: {m.group(0)}(외부 법령 조문)")
            elif n in art_id:
                refs.append(art_id[n])
            else:
                unresolved.append(f"{c['locator']}: {m.group(0)}")
        if own_art != 3:
            for term, hid in terms.items():
                if term in c["text"]:
                    refs.append(hid)
        refs = [x for x in dict.fromkeys(refs) if x != c["chunk_id"]]
        c["refs"] = refs
        if refs:
            ref_log.append({"locator": c["locator"], "n_refs": len(refs)})
    info = {"skipped": skipped, "unresolved": unresolved, "ref_chunks": len(ref_log), "terms": sorted(terms), "tables": sorted(table_id)}
    return chunks, info


# --------------------------------------------------------------------------- 선별·집계

def is_selected(c: dict[str, Any]) -> bool:
    k = c["chunk_kind"]
    if k == "l3_eyak_section":
        return any(c["section"] == label for f, label in EYAK_FIELDS if f in KEEP_EYAK)
    if k.startswith("l3_prmsn"):
        doc, _, title = c["section"].partition(" ")
        return prmsn_selected(doc, title)
    return True


def stats(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {}
    for c in chunks:
        s = by.setdefault(c["chunk_kind"], {"count": 0, "chars": 0, "max_chars": 0, "over_3000": 0})
        s["count"] += 1
        n = len(c["text"])
        s["chars"] += n
        s["max_chars"] = max(s["max_chars"], n)
        s["over_3000"] += n > EMB_CHAR_CAP
    return by


def jsonl_lines(chunks: Sequence[dict[str, Any]]) -> list[str]:
    return [json.dumps(c, ensure_ascii=False, separators=(",", ":")) for c in chunks]


def build_all(label_filter: str = "all") -> dict[str, list[dict[str, Any]]]:
    codes = load_product_codes()
    notice, info = build_notice_chunks(bup2_table_id=next(c["chunk_id"] for c in L2.build_bupyo2_chunks() if c["chunk_kind"] == "l1_bupyo2_table"))
    sets = {"eyak": build_eyak_chunks(codes=codes), "prmsn": build_prmsn_chunks(codes=codes), "notice": notice}
    build_all.info = info  # type: ignore[attr-defined]
    for k in sets:
        sets[k].sort(key=lambda c: (c["chunk_kind"], c["chunk_id"]))
        if label_filter == "selected":
            sets[k] = [c for c in sets[k] if is_selected(c)]
    return sets


def manifest_for(sets: dict[str, list[dict[str, Any]]], label_filter: str) -> dict[str, Any]:
    files = {}
    for k, cs in sets.items():
        lines = jsonl_lines(cs)
        files[FILES[k]] = {"chunks": len(cs), "sha256": hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest(),
                           "kinds": {kk: {**v, "avg_chars": round(v["chars"] / v["count"], 1)} for kk, v in sorted(stats(cs).items())}}
    allc = [c for cs in sets.values() for c in cs]
    return {"label_filter": label_filter, "total": len(allc), "files": files, "sha256": hashlib.sha256("".join(f["sha256"] for f in files.values()).encode()).hexdigest()}


def global_links(extra: Sequence[Path] = ()) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    for name in [L2.CHUNKS_PATH.name, *FILES.values()]:
        p = OUT_DIR / name
        if p.exists():
            chunks.extend(json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln)
    return L2.link_report(chunks) | {"files": len(chunks)}


def cmd_build(args: argparse.Namespace) -> int:
    sets = build_all(args.label_filter)
    man = manifest_for(sets, args.label_filter)
    out_dir = OUT_DIR / ("selected" if args.label_filter == "selected" else "")
    mpath = out_dir / "manifest_l3.json"
    if args.check:
        old = json.loads(mpath.read_text(encoding="utf-8"))
        same = old["sha256"] == man["sha256"]
        print(f"재빌드 해시 {'동일' if same else '다름'}: {man['sha256'][:16]} (기존 {old['sha256'][:16]})")
        return 0 if same else 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, cs in sets.items():
        (out_dir / FILES[k]).write_text("\n".join(jsonl_lines(cs)) + "\n", encoding="utf-8")
    man["notice_info"] = build_all.info  # type: ignore[attr-defined]
    mpath.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{args.label_filter}] 청크 {man['total']}개 → {out_dir}")
    for f, v in man["files"].items():
        print(f"  {f}: {v['chunks']}")
        for kk, s in v["kinds"].items():
            print(f"    {kk}: {s['count']} 평균 {s['avg_chars']}자 최대 {s['max_chars']} 3000초과 {s['over_3000']}")
    return 0


def read_all(base: Path = OUT_DIR) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in [L2.CHUNKS_PATH.name, *FILES.values()]:
        p = base / name if (base / name).exists() else OUT_DIR / name
        out.extend(json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln)
    return out


def cmd_verify(args: argparse.Namespace) -> int:
    chunks = read_all()
    rep = L2.link_report(chunks)
    print("연결 검증(L2+L3+L1 전체):", rep)
    by_id = {c["chunk_id"]: c for c in chunks}
    rng = random.Random(20261111)  # noqa: S311 - 점검용 표본(시드 고정)
    l3l1 = [c for c in chunks if c["layer"] in ("L1", "L3")]
    sample = rng.sample(l3l1, 20)
    ok = sum((not c["parent_id"] or c["parent_id"] in by_id) and all(r in by_id for r in c["refs"]) for c in sample)
    print(f"임의 L1·L3 20청크 parent_id·refs 점검: {ok}/20, 3000자 초과 {sum(len(c['text']) > EMB_CHAR_CAP for c in l3l1)}건")
    print("--- refs 연결 테스트(조문 → 대상)")
    for c in chunks:
        if c["chunk_kind"] in ("l1_notice_article", "l1_notice_item") and c["refs"]:
            tg = [(by_id[r]["locator"]) for r in c["refs"]]
            print(f"  {c['locator']} → {tg}")
    return 0 if rep["dangling_parent"] == rep["dangling_refs"] == 0 else 1


MB = 1024 * 1024


def cap_mb(cs: Sequence[dict[str, Any]], dim: int) -> float:
    """지시서 가정: 벡터 4×dim 바이트, 행 300B, HNSW 1.3배. 본문·메타(locator·source_ref+120B)는 실제 바이트."""
    n = len(cs)
    text = sum(len(c["text"].encode()) + len(c["locator"].encode()) + len(c["source_ref"].encode()) + 120 for c in cs)
    return (text + n * (4 * dim * (1 + 1.3) + 300)) / MB


def cmd_capacity(args: argparse.Namespace) -> int:
    sets = build_all("all")
    l2 = [json.loads(ln) for ln in L2.CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if ln]
    groups = {"L3 e약은요": sets["eyak"], "L3 허가 상세": sets["prmsn"], "L1 고시(조문·별표 1·3)": sets["notice"], "L2(병용·임부·연령·별표 2)": l2}
    lines = ["| 묶음 | all 청크 | all 글자(만) | all 1536차원 MB | all 512차원 MB | selected 청크 | selected 글자(만) | sel 1536 MB | sel 512 MB |", "|---|---|---|---|---|---|---|---|---|"]
    tot = {"all": [], "sel": []}
    for name, cs in groups.items():
        sel = [c for c in cs if is_selected(c)]
        tot["all"] += cs
        tot["sel"] += sel
        lines.append(f"| {name} | {len(cs):,} | {sum(len(c['text']) for c in cs) / 1e4:.1f} | {cap_mb(cs, 1536):.0f} | {cap_mb(cs, 512):.0f} | {len(sel):,} | {sum(len(c['text']) for c in sel) / 1e4:.1f} | {cap_mb(sel, 1536):.0f} | {cap_mb(sel, 512):.0f} |")
    a, s = tot["all"], tot["sel"]
    lines.append(f"| **합계** | {len(a):,} | {sum(len(c['text']) for c in a) / 1e4:.1f} | {cap_mb(a, 1536):.0f} | {cap_mb(a, 512):.0f} | {len(s):,} | {sum(len(c['text']) for c in s) / 1e4:.1f} | {cap_mb(s, 1536):.0f} | {cap_mb(s, 512):.0f} |")
    md = "# 코퍼스 용량 어림 (추정, 실측 아님)\n\n벡터 4×차원 B, 행 300B, HNSW 벡터의 1.3배 가정. 본문·메타는 실제 바이트. 허가 상세는 로컬 스냅샷 212개 기준.\n\n" + "\n".join(lines) + "\n"
    (OUT_DIR / "capacity_l3.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_samples(args: argparse.Namespace) -> int:
    cs = [c for c in read_all() if c["chunk_kind"] == "l3_prmsn_table"]
    for name in args.names:
        hit = [c for c in cs if name in c["item_name"]][: args.limit]
        print(f"=== {name}: 표 청크 {sum(name in c['item_name'] for c in cs)}개")
        for c in hit:
            print(f"--- {c['locator']} (parent {'있음' if c['parent_id'] else '없음'}, {len(c['text'])}자)\n{c['text'][:900]}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--label-filter", choices=("all", "selected"), default="all")
    b.add_argument("--check", action="store_true")
    b.set_defaults(fn=cmd_build)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("capacity").set_defaults(fn=cmd_capacity)
    s = sub.add_parser("samples")
    s.add_argument("names", nargs="+")
    s.add_argument("--limit", type=int, default=2)
    s.set_defaults(fn=cmd_samples)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
