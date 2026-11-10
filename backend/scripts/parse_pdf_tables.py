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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["bupyo2", "survey"])
    ap.add_argument("--out", type=Path, default=DATA / "mock" / "parsed")
    args = ap.parse_args(argv)
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
