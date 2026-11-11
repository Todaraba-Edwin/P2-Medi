"""근거 문서 메타 표(2026-11-11 사용자 승인). 청크 메타(`year`·`source_file`·`effective_date`)의 원천이다.

* 칸 값은 파일 이름 또는 PDF·추출 텍스트 첫 쪽 문구에서 사람이 읽어 확인한 것만 적는다. 확인하지 못한 칸은 None(보고서에 '미확인').
* `source_url`은 사용자가 알려 준 값(CLAUDE.md 3·4장의 data.go.kr 링크)만 적고 나머지는 None이다. 지어내지 않는다.
* 기준일(`base_date`)은 `_YYYYMMDD` 접미를 코드로 파싱한다. 날짜가 없는 DUR 품목리스트(`2026.6`)는 `YYYY-MM`(월 단위)이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.db import source_files as sf

_SUFFIX_DAY = re.compile(r"_(\d{4})(\d{2})(\d{2})\.[A-Za-z0-9]+$")
_SUFFIX_MONTH = re.compile(r"\s(\d{4})\.(\d{1,2})\.[A-Za-z0-9]+$")


def parse_base_date(filename: str) -> str | None:
    """파일 이름 끝에서 기준일을 읽는다. `_YYYYMMDD.ext` → `YYYY-MM-DD`, ` YYYY.M.ext` → `YYYY-MM`. 없으면 None."""
    m = _SUFFIX_DAY.search(filename)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return None
    m = _SUFFIX_MONTH.search(filename)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return None


@dataclass(frozen=True)
class DocMeta:
    source_file: str
    issuer: str | None
    doc_type: str | None
    notice_no: str | None
    enacted_or_revised_date: str | None  # 고시·법령 최근 개정일(첫 쪽 문구)
    effective_date: str | None           # 시행일(확인된 경우만)
    base_date: str | None                # 데이터 기준일(파일명 접미 또는 고시 개정일)
    year: int | None
    source_url: str | None = None        # 사용자가 알려 준 것만, 나머지 None


def _file(name: str, issuer: str, doc_type: str = "파일데이터", source_url: str | None = None) -> DocMeta:
    bd = parse_base_date(name)
    return DocMeta(name, issuer, doc_type, None, None, None, bd, int(bd[:4]) if bd else None, source_url)


KIDS = "한국의약품안전관리원"
HIRA = "건강보험심사평가원"
_DUR = "의약품안전사용서비스(DUR)_{} 품목리스트 2026.6.csv"
GOSI_NAME = sf.GOSI_PDF_NAME


def _hira(year: int, notice_no: str | None) -> DocMeta:
    # 연도는 파일 이름의 판 연도. 발간기관·발간등록번호는 표지 텍스트에서 읽은 값(표지에 텍스트 층이 없는 판은 둘 다 미확인)
    return DocMeta(f"{year} 건강보험심사평가원 기능과 역할.pdf", HIRA if notice_no else None, "발간물", notice_no, None, None, None, year)


_METAS: tuple[DocMeta, ...] = (
    # --- 한국의약품안전관리원 파일데이터(기준일은 파일명 접미)
    _file(sf.COMBO_JSON_NAME, KIDS, source_url="https://www.data.go.kr/data/15161282/fileData.do"),
    _file(sf.PREG_CSV_NAME, KIDS, source_url="https://www.data.go.kr/data/15089735/fileData.do"),
    _file(sf.AGE_CSV_NAME, KIDS),
    _file(sf.DOSE_CSV_NAME, KIDS),
    _file(sf.LACT_CSV_NAME, KIDS),
    # --- DUR 품목리스트(심평원 제공 CSV, 기준일 월 단위)
    *(_file(_DUR.format(k), HIRA) for k in ("노인주의", "노인주의(해열진통소염제)", "병용금기", "연령금기", "임부금기")),
    # --- 고시·법령 PDF(첫 쪽·추출 텍스트에서 읽은 값)
    DocMeta(GOSI_NAME, "식품의약품안전처", "고시", "제2026-52호", "2026-07-21", None, "2026-07-21", 2026),
    DocMeta("안전상비의약품 지정에 관한 고시(보건복지부고시)(제2012-144호)(20121115).pdf", "보건복지부", "고시", "제2012-144호",
            "2012-10-31", "2012-11-15", None, 2012),  # 제정일·시행일(첫 쪽 '시행 2012. 11. 15., 제정 2012. 10. 31.')
    DocMeta("[별표] 안전상비의약품 품목(제2조 관련)(안전상비의약품 지정에 관한 고시, 2023-12-14 20:38).pdf", None, "고시 별표", None,
            None, None, None, None),  # 첫 쪽에 부처·번호·날짜 없음(품목 목록뿐) → 전부 미확인. 파일명 시각은 내려받은 시각 추정이라 쓰지 않는다
    DocMeta("약사법 시행규칙(보건복지부령)(제01181호)(20260621).pdf", "보건복지부", "시행규칙", "제1181호", "2026-06-19", "2026-06-21",
            None, 2026),
    DocMeta("약사법_제2항.pdf", None, "법률", "제21525호", "2026-04-07", "2026-10-08", None, 2026),  # 첫 쪽에 부처명 없음(법률 제21525호)
    _hira(2021, None),  # 표지에 텍스트 층 없음 → 미확인
    _hira(2022, None),  # 텍스트 층 없음 → 미확인
    _hira(2023, "G000BX1-2022-83"),
    _hira(2024, "G000BX1-2023-194"),
    _hira(2025, "G000BX1-2024-116"),
    _hira(2026, None),  # 텍스트 층 없음 → 미확인
)

DOC_META: dict[str, DocMeta] = {m.source_file: m for m in _METAS}
if len(DOC_META) != len(_METAS):
    raise RuntimeError("source_file 중복")


def get_meta(source_file: str) -> DocMeta:
    return DOC_META[source_file]


def chunk_meta(source_file: str) -> dict[str, Any]:
    """청크에 넣을 세 칸. `year`는 int|None, `effective_date`는 'YYYY-MM-DD'|None."""
    m = DOC_META[source_file]
    return {"year": m.year, "source_file": m.source_file, "effective_date": m.effective_date}
