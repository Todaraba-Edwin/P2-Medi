"""고시 PDF 표 파서 (BE-04, RFP-15-04 시험). 로컬 파서(pdfplumber)만 쓴다.

사용:
    backend/.venv/bin/python backend/scripts/parse_pdf_tables.py bupyo2 [--out DIR]
    backend/.venv/bin/python backend/scripts/parse_pdf_tables.py survey

pdfplumber는 pyproject의 dev 의존성이다(런타임 아님, BE-04-01 A).
PDF 원본과 파싱 결과는 data/(로컬 전용)에 있으며 커밋하지 않는다.
산출 마크다운 맨 위에 메타 블록(원본 파일명, 원본 고시일, 사용자 최신 배포 확인일, 파서·버전, 행 수, 생성 시각)을 자동으로 쓴다.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
GOSI_PDF = DATA / "「의약품 병용금기 성분 등의 지정에 관한 규정」 개정고시 전문.pdf"
BUPYO2_PAGES = range(45, 51)  # 1-based, 45~50쪽 (연번 1~40은 45쪽)
EXPECTED_ROWS = 211
CONFIRMED_LATEST = "2026-11-10"  # 사용자가 최신 배포본임을 확인한 날(BE-04-01 A)
PARSER = "parse_pdf_tables.py"
PARSER_REV = "1.1"
HEADER = ("연번", "유효성분", "연령기준", "해당 제형")


@dataclass
class Row:
    no: int
    ingredient: str
    parts: list[tuple[str, str]] = field(default_factory=list)  # (연령기준, 해당 제형)


def _clean(cell: str | None) -> str:
    return re.sub(r"\s+", " ", cell or "").strip()


# 문자 폭으로 줄이 바뀌는 영문 성분 칸: 줄 끝이 영문자이고 다음 줄이 소문자로 시작하면
# 단어 중간에서 끊긴 것으로 보고 공백 없이 잇는다. 나머지는 공백으로 잇는다.
# 예외 허용: 소문자 단어가 줄 머리에 오는 경우(acid, sulfate 등)는 공백을 유지한다.
_WHOLE_WORDS = frozenset({"acid", "sulfate", "chloride", "hydrochloride", "extract", "oil", "powder", "of", "and"})


def join_wrapped(text: str | None) -> str:
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    out = ""
    for ln in lines:
        if not out:
            out = ln
            continue
        first = re.match(r"[a-z]+", ln)
        mid_word = out[-1].isascii() and out[-1].isalpha() and first is not None and first.group(0) not in _WHOLE_WORDS
        out += ln if mid_word else f" {ln}"
    return re.sub(r"\s+", " ", out).strip()


def merge_table_rows(raw_rows: list[list[str | None]], rows: list[Row] | None = None) -> list[Row]:
    """pdfplumber 표 행을 연번 단위 Row로 합친다.

    연번 칸이 비어 있는 행은 앞 행의 이어지는 줄(연령기준·제형 추가)이다.
    쪽을 넘어 이어질 수 있어 `rows`를 이어받는다.
    """
    out = rows if rows is not None else []
    for cells in raw_rows:
        cells = (list(cells) + [None] * 4)[:4]
        no_s, age, form = _clean(cells[0]), _clean(cells[2]), _clean(cells[3])
        ing = join_wrapped(cells[1])
        if no_s == HEADER[0]:
            continue  # 헤더 반복 제거
        if no_s.isdigit():
            row = Row(int(no_s), ing)
            if age or form:
                row.parts.append((age, form))
            out.append(row)
        elif out:
            prev = out[-1]
            if ing:
                prev.ingredient = join_wrapped(f"{prev.ingredient}\n{ing}")
            if age or form:
                prev.parts.append((age, form))
    return out


def parse_bupyo2(pdf_path: Path = GOSI_PDF, pages: range = BUPYO2_PAGES) -> list[Row]:
    import pdfplumber

    rows: list[Row] = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            for table in pdf.pages[p - 1].extract_tables():
                merge_table_rows(table, rows)
    return rows


# 별표 1(병용금기, 9~44쪽)·별표 3(임부금기, 51~76쪽): 연번 + 나머지 칸 N개 표.
BUPYO1_PAGES = range(9, 45)
BUPYO3_PAGES = range(51, 77)
BUPYO1_HEADER = ("연번", "유효성분 1", "유효성분 2", "비고")
BUPYO3_HEADER = ("연번", "유효성분", "등급", "비고")


@dataclass
class WideRow:
    no: int
    cells: list[str]


def merge_wide_rows(raw_rows: list[list[str | None]], ncols: int, rows: list[WideRow] | None = None) -> list[WideRow]:
    """연번 + (ncols-1)칸 표를 연번 단위로 합친다. 연번이 비면 앞 행의 이어지는 줄이다. 쪽을 넘어 `rows`를 이어받는다."""
    out = rows if rows is not None else []
    for cells in raw_rows:
        cells = (list(cells) + [None] * ncols)[:ncols]
        no_s = _clean(cells[0])
        if no_s == HEADER[0]:
            continue
        rest = [join_wrapped(c) for c in cells[1:]]
        if no_s.isdigit():
            out.append(WideRow(int(no_s), rest))
        elif out:
            prev = out[-1].cells
            for i, c in enumerate(rest):
                if c:
                    prev[i] = join_wrapped(f"{prev[i]}\n{c}")
    return out


def parse_wide(pdf_path: Path, pages: range, ncols: int = 4) -> list[WideRow]:
    import pdfplumber

    rows: list[WideRow] = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            for table in pdf.pages[p - 1].extract_tables():
                merge_wide_rows(table, ncols, rows)
    return rows


def wide_markdown(rows: list[WideRow], header: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += [f"| {r.no} | " + " | ".join(_esc(c) for c in r.cells) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def check_wide_sequence(rows: list[WideRow]) -> list[str]:
    nums = [r.no for r in rows]
    if nums != list(range(1, len(nums) + 1)):
        dup = sorted({n for n in nums if nums.count(n) > 1})
        missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
        return [f"연번 불연속 또는 중복. 누락={missing[:20]} 중복={dup[:20]}"]
    return []


def squash(s: str) -> str:
    """공백·줄바꿈을 모두 없애고 NFC로 맞춘다(독립 추출본과 대조용)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s))


def split_pdfkit_pages(text: str) -> dict[int, str]:
    """scripts/pdf_to_text.swift 출력(`=====PAGE n=====` 구분)을 쪽 번호별 squash 텍스트로 나눈다."""
    pages: dict[int, str] = {}
    for m in re.finditer(r"=====PAGE (\d+)=====\n(.*?)(?=\n=====PAGE \d+=====|\Z)", text, flags=re.S):
        pages[int(m.group(1))] = squash(m.group(2))
    return pages


def verify_wide(rows: list[WideRow], pages_text: dict[int, str], pages: range) -> dict[str, Any]:
    """각 행의 칸 토큰(비어 있지 않은 칸)이 독립 추출본(쪽 범위 합본, 공백 무시)에 있는지 전수 대조한다.

    strict: `연번+칸1+칸2…`가 이어서 있는 행 수(행 단위 추출 쪽). loose: 모든 칸이 따로라도 있는 행 수.
    """
    blob = "".join(pages_text.get(p, "") for p in pages)
    strict = loose = 0
    miss: list[tuple[int, list[str]]] = []
    for r in rows:
        toks = [squash(c) for c in r.cells if c]
        if (str(r.no) + "".join(toks)) in blob:
            strict += 1
        absent = [c for c in r.cells if c and squash(c) not in blob]
        if not absent:
            loose += 1
        else:
            miss.append((r.no, absent))
    return {"n": len(rows), "strict": strict, "loose": loose, "missing": miss}


def max_leading_int(raw_page_text: str) -> int | None:
    """독립 추출본 한 쪽(원문)에서 줄 머리의 정수(열 단위 추출이면 `연번 41 42 …` 줄의 정수들) 중 가장 큰 값.

    표 마지막 쪽의 마지막 연번(기대 행 수) 근거로 쓴다. 쪽 번호 줄(`- 44 -`)은 정수가 줄 머리에 없어 제외된다.
    """
    nums: list[int] = []
    for line in raw_page_text.splitlines():
        m = re.match(r"^(?:연번\s+)?((?:\d+\s+)*\d+)(?=\s|$)", line)
        if m:
            nums += [int(t) for t in m.group(1).split()]
    return max(nums) if nums else None


def pdfkit_raw_page(text: str, page: int) -> str:
    m = re.search(rf"=====PAGE {page}=====\n(.*?)(?=\n=====PAGE \d+=====|\Z)", text, flags=re.S)
    return m.group(1) if m else ""


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(rows: list[Row]) -> str:
    """Row 목록을 마크다운 표로. 한 연번에 여러 (연령, 제형)이 있으면 `<br>`로 줄을 나눈다."""
    lines = ["| " + " | ".join(HEADER) + " |", "|---|---|---|---|"]
    for r in rows:
        age = "<br>".join(_esc(a) for a, _ in r.parts if a)
        form = "<br>".join(_esc(f) for _, f in r.parts if f)
        lines.append(f"| {r.no} | {_esc(r.ingredient)} | {age} | {form} |")
    return "\n".join(lines) + "\n"


def check_sequence(rows: list[Row]) -> list[str]:
    errs = []
    nums = [r.no for r in rows]
    if nums != list(range(1, len(nums) + 1)):
        missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
        errs.append(f"연번 불연속 또는 중복. 누락={missing}")
    return errs


def sample_rows(rows: list[Row], n: int = 20, seed: int = 20261110) -> list[Row]:
    return random.Random(seed).sample(rows, min(n, len(rows)))  # noqa: S311 (재현용 표본)


_NOTICE_RE = re.compile(r"고시\s*제\s*(\d{4})-\s*(\d+)호\((\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2}),\s*(제정|개정)\)")
_FILENAME_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def latest_notice(text: str) -> tuple[str, str] | None:
    """개정 이력 줄(`고시 제2026- 52호(2026. 7. 21, 개정)`)에서 날짜가 가장 늦은 (고시번호, ISO 날짜). 없으면 None."""
    best: tuple[str, str] | None = None
    for m in _NOTICE_RE.finditer(text):
        y, n, yy, mm, dd, _ = m.groups()
        iso = f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
        if best is None or iso > best[1]:
            best = (f"제{y}-{int(n)}호", iso)
    return best


def filename_date(name: str) -> str | None:
    """파일 이름에 적힌 날짜(YYYY-MM-DD). 없으면 None."""
    m = _FILENAME_DATE_RE.search(name)
    return m.group(0) if m else None


def meta_block(pdf_name: str, source_date: str, rows: int, *, now: datetime | None = None, extra: dict[str, str] | None = None) -> str:
    """산출 마크다운 맨 위에 붙이는 front matter. 값은 호출자가 PDF·파일명에서 읽은 것만 넣는다(추측 금지)."""
    try:
        ver = metadata.version("pdfplumber")
    except metadata.PackageNotFoundError:
        ver = "unknown"
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    fields = {
        "source_pdf": pdf_name,
        "source_date": source_date,
        "latest_distribution_confirmed": CONFIRMED_LATEST,
        "parser": f"{PARSER} {PARSER_REV} (pdfplumber {ver})",
        "rows": str(rows),
        "generated_at": stamp,
        **(extra or {}),
    }
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n\n"


def survey(pdf_path: Path) -> dict[str, Any]:
    """PDF 한 개의 쪽별 텍스트 레이어·표 유무를 요약한다(OCR은 하지 않는다)."""
    import pdfplumber

    info: dict[str, Any] = {"pages": 0, "text_pages": 0, "table_pages": 0, "tables": 0, "rows": 0}
    with pdfplumber.open(pdf_path) as pdf:
        info["pages"] = len(pdf.pages)
        for pg in pdf.pages:
            if (pg.extract_text() or "").strip():
                info["text_pages"] += 1
            ts = pg.extract_tables()
            if ts:
                info["table_pages"] += 1
                info["tables"] += len(ts)
                info["rows"] += sum(len(t) for t in ts)
    return info


def parse_numbered_items(text: str) -> list[tuple[int, str]]:
    """`1. 품목명` 꼴 번호 목록 줄을 (번호, 이름)으로 읽는다(안전상비의약품 [별표])."""
    items = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", line)
        if m:
            items.append((int(m.group(1)), m.group(2)))
    return items


def safe_items_markdown(items: list[tuple[int, str]]) -> str:
    lines = ["| 번호 | 품목 |", "|---|---|"]
    lines += [f"| {n} | {_esc(name)} |" for n, name in items]
    return "\n".join(lines) + "\n"


PDFKIT_TXT = DATA / "mock" / "parsed" / "gosi_full_pdfkit.txt"  # swift scripts/pdf_to_text.swift 출력(로컬 전용)


def _pdfkit() -> str:
    return PDFKIT_TXT.read_text(encoding="utf-8")


def run_wide(cmd: str, out: Path) -> int:
    """별표 1·3 변환 + 합격 검사(연번 연속·기대 행 수=독립 추출본 마지막 연번·무작위 20행 대조)."""
    import pdfplumber

    pages, header, name, label = (BUPYO1_PAGES, BUPYO1_HEADER, "gosi_bupyo1_pdfplumber.md", "별표 1 (9~44쪽)") if cmd == "bupyo1" else (BUPYO3_PAGES, BUPYO3_HEADER, "gosi_bupyo3_pdfplumber.md", "별표 3 (51~76쪽)")
    rows = parse_wide(GOSI_PDF, pages)
    with pdfplumber.open(GOSI_PDF) as doc:
        head = "\n".join((doc.pages[i].extract_text() or "") for i in range(min(2, len(doc.pages))))
    notice = latest_notice(head)
    src = f"{notice[1]} (고시 {notice[0]}, PDF 1~2쪽 개정 이력의 마지막 줄)" if notice else "미확인(PDF에서 읽지 못함)"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / name
    dest.write_text(meta_block(GOSI_PDF.name, src, len(rows), extra={"table": label}) + wide_markdown(rows, header), encoding="utf-8")
    raw = _pdfkit()
    expected = max_leading_int(pdfkit_raw_page(raw, pages[-1]))
    texts = split_pdfkit_pages(raw)
    seq = check_wide_sequence(rows)
    sample = random.Random(20261110).sample(rows, min(20, len(rows)))  # noqa: S311
    v = verify_wide(sample, texts, pages)
    print(f"{cmd}: rows={len(rows)} expected(독립 추출본 마지막 연번)={expected} seq_errors={seq} -> {dest}")
    print(f"  sample20 strict={v['strict']}/{v['n']} loose={v['loose']}/{v['n']} missing={v['missing']}")
    full = verify_wide(rows, texts, pages)
    print(f"  full strict={full['strict']}/{full['n']} loose={full['loose']}/{full['n']} missing(처음 15)={full['missing'][:15]}")
    return 0 if len(rows) == expected and not seq and v["loose"] == v["n"] else 1


def run_verify2() -> int:
    """별표 2 211행 전수 자동 대조(성분·연령기준·제형 토큰이 독립 추출본 45~50쪽에 있는지, 공백 무시)."""
    rows = parse_bupyo2()
    texts = split_pdfkit_pages(_pdfkit())
    blob = "".join(texts.get(p, "") for p in BUPYO2_PAGES)
    bad: list[tuple[int, str, str]] = []
    for r in rows:
        toks = [("성분", r.ingredient)] + [(k, v) for a, f in r.parts for k, v in (("연령", a), ("제형", f)) if v]
        for kind, tok in toks:
            if squash(tok) not in blob:
                bad.append((r.no, kind, tok))
    bad_rows = {n for n, _, _ in bad}
    print(f"verify2: rows={len(rows)} 전부 일치 행={len(rows) - len(bad_rows)}/{len(rows)} 불일치 토큰={len(bad)}")
    for n, k, t in bad:
        print(f"  MISS no={n} {k}: {t!r}")
    # 영문 줄바꿈 복원 오복원 후보: 원본 셀에서 줄 사이를 공백 없이 이은 지점이 독립 추출본에서 `앞 + 공백 + 뒤`로만 나타나는지.
    import pdfplumber

    cand: list[tuple[int, str]] = []
    with pdfplumber.open(GOSI_PDF) as pdf:
        for p in BUPYO2_PAGES:
            for table in pdf.pages[p - 1].extract_tables():
                for cells in table:
                    lines = [ln.strip() for ln in (cells[1] or "").split("\n") if ln.strip()]
                    for a, b in zip(lines, lines[1:], strict=False):
                        first = re.match(r"[a-z]+", b)
                        if a[-1].isascii() and a[-1].isalpha() and first:
                            joined = first.group(0) not in _WHOLE_WORDS
                            cand.append((int(_clean(cells[0]) or 0), f"{'잇기' if joined else '띄우기'}: {a} | {b}"))
    print(f"줄바꿈 경계 후보 {len(cand)}건 (잇기/띄우기):")
    for n, t in cand:
        print(f"  no={n} {t}")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["bupyo2", "bupyo1", "bupyo3", "verify2", "survey"])
    ap.add_argument("--out", type=Path, default=DATA / "mock" / "parsed")
    args = ap.parse_args(argv)
    if args.cmd in ("bupyo1", "bupyo3"):
        return run_wide(args.cmd, args.out)
    if args.cmd == "verify2":
        return run_verify2()
    if args.cmd == "bupyo2":
        t0 = time.perf_counter()
        rows = parse_bupyo2()
        dt = time.perf_counter() - t0
        args.out.mkdir(parents=True, exist_ok=True)
        dest = args.out / "gosi_bupyo2_pdfplumber.md"
        import pdfplumber

        with pdfplumber.open(GOSI_PDF) as doc:
            head = "\n".join((doc.pages[i].extract_text() or "") for i in range(min(2, len(doc.pages))))
        notice = latest_notice(head)
        src = f"{notice[1]} (고시 {notice[0]}, PDF 1~2쪽 개정 이력의 마지막 줄)" if notice else "미확인(PDF에서 읽지 못함)"
        dest.write_text(meta_block(GOSI_PDF.name, src, len(rows), extra={"table": "별표 2 (45~50쪽)"}) + to_markdown(rows), encoding="utf-8")
        print(f"rows={len(rows)} expected={EXPECTED_ROWS} sec={dt:.2f} -> {dest}")
        for e in check_sequence(rows):
            print("ERR", e)
        return 0 if len(rows) == EXPECTED_ROWS and not check_sequence(rows) else 1
    import pdfplumber

    for pdf in sorted(DATA.glob("*.pdf")):
        if "안전상비" not in unicodedata.normalize("NFC", pdf.name):
            continue
        print(pdf.name, survey(pdf))
        if pdf.name.startswith("[별표]") or unicodedata.normalize("NFC", pdf.name).startswith("[별표]"):
            with pdfplumber.open(pdf) as doc:
                items = parse_numbered_items(doc.pages[0].extract_text() or "")
            args.out.mkdir(parents=True, exist_ok=True)
            fdate = filename_date(pdf.name)
            src = f"{fdate} (파일명에 적힌 날짜)" if fdate else "미확인(파일명에 날짜 없음)"
            body = meta_block(pdf.name, src, len(items)) + safe_items_markdown(items)
            (args.out / "safe_med_bupyo_pdfplumber.md").write_text(body, encoding="utf-8")
            print("  items:", len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
