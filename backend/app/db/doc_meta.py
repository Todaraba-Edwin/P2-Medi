"""근거 문서 메타 표(2026-11-11 사용자 승인). 청크 메타(`year`·`source_file`·`effective_date`)의 원천이다.

* 칸 값은 파일 이름 또는 PDF·추출 텍스트 첫 쪽 문구에서 사람이 읽어 확인한 것만 적는다. 확인하지 못한 칸은 None(보고서에 '미확인').
* `source_url`·`dataset_id`·`modified_date` 등은 사용자가 알려 준 값(CLAUDE.md 3·4장, 포털 확인값 2026-11-11)만 적고 나머지는 None이다. 지어내지 않는다.
* 수정일(`modified_date`)은 사용자 판단상 최종 판단일이지만, 표시·판정 기준일은 이번에 바꾸지 않았다(BE-16-02 대기). 값은 기록만 한다.
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
    # --- 2026-11-11 추가(BE-16, 기록만. 표시·판정 기준일(`AS_OF_*`)·base_date는 바꾸지 않는다. 수정일 표시 여부는 BE-16-02 대기)
    dataset_id: str | None = None        # data.go.kr 데이터셋 번호
    modified_date: str | None = None     # 포털 수정일(사용자 판단: 최종 판단일)
    registered_date: str | None = None   # 포털 등록일
    update_cycle: str | None = None      # 예: "수시(1회성)", "연간"
    edition_role: str | None = None      # 심평원 「기능과 역할」: "현행"(코퍼스 적재) | "비교용"(인용 참고만)
    provider: str | None = None          # 제공기관(출처 표기용)
    note: str | None = None              # 기록용 메모(동작 변경 없음)


def _file(name: str, issuer: str, doc_type: str = "파일데이터", source_url: str | None = None, *,
          dataset_id: str | None = None, modified: str | None = None, registered: str | None = None,
          cycle: str | None = None, provider: str | None = None, note: str | None = None) -> DocMeta:
    bd = parse_base_date(name)
    if source_url is None and dataset_id:
        source_url = f"https://www.data.go.kr/data/{dataset_id}/fileData.do"
    return DocMeta(name, issuer, doc_type, None, None, None, bd, int(bd[:4]) if bd else None, source_url,
                   dataset_id, modified, registered, cycle, None, provider, note)


def _kids(name: str, dataset_id: str, modified: str, registered: str, note: str | None = None) -> DocMeta:
    return _file(name, KIDS, dataset_id=dataset_id, modified=modified, registered=registered, cycle="수시(1회성)", provider=KIDS, note=note)


KIDS = "한국의약품안전관리원"
HIRA = "건강보험심사평가원"
_DUR = "의약품안전사용서비스(DUR)_{} 품목리스트 2026.6.csv"
GOSI_NAME = sf.GOSI_PDF_NAME


LAW_PROVIDER = "국가법령정보센터"
LAW_URL = "https://www.law.go.kr"  # 대표 주소만 확인됨(개별 문서 주소는 미확인)
_HIRA_URL = "https://www.kogl.or.kr/recommend/recommendDivView.do?recommendIdx=177231&division=doc&oc="
HIRA_CURRENT_YEAR = 2026  # 「기능과 역할」 현행판(코퍼스 적재 대상). 나머지 판은 비교용(인용 참고 자료)


def _hira(year: int, notice_no: str | None, *, source_url: str | None = None, issued: str | None = None) -> DocMeta:
    # 연도는 파일 이름의 판 연도. 발간기관·발간등록번호는 표지 텍스트에서 읽은 값(표지에 텍스트 층이 없는 판은 둘 다 미확인)
    # 규칙: edition_role "현행"만 코퍼스에 적재하고 "비교용"은 인용 참고 자료로만 둔다(시험 test_hira_edition_roles).
    role = "현행" if year == HIRA_CURRENT_YEAR else "비교용"
    return DocMeta(f"{year} 건강보험심사평가원 기능과 역할.pdf", HIRA if notice_no else None, "발간물", notice_no, issued, None, None, year,
                   source_url, None, None, None, None, role, HIRA)


_METAS: tuple[DocMeta, ...] = (
    # --- 한국의약품안전관리원 파일데이터(기준일은 파일명 접미, 수정일·등록일은 포털 확인값 2026-11-11)
    # 병용 JSON 수정일 2026-09-23: 파일 내용은 검증본 CSV(수정일 2026-08-10)와 동일하므로 내용 면에서 최신이다.
    # 날짜 표시는 파일 제공일(파일명 접미) 2026-07-31을 유지한다(BE-16-02 A).
    _kids(sf.COMBO_JSON_NAME, "15161282", "2026-09-23", "2026-08-18",
          note="파일 내용은 CSV(수정일 2026-08-10)와 동일하므로 내용 면에서 최신, 날짜 표시는 파일 제공일 2026-07-31 유지(BE-16-02 A)"),
    # 검증본 CSV(2026-11-11 비교: 성분쌍 23,619·제품쌍 512,464 전부 일치, CP949, 512,464행). 코드에서 읽지 않는다.
    # 기준일은 파일명 접미(2026-07-31)이며 병용 JSON과 같다. 신선도 점검에서는 수정일 08-10이 파일 저장일보다 이르므로 '최신'이다.
    _kids(sf.COMBO_CSV_VERIFY_NAME, "15089525", "2026-08-10", "2024-08-13",
          note="검증본: AI 학습용 JSON과 내용 동일(2026-11-11 비교: 성분쌍 23,619·제품쌍 512,464 전부 일치), 코드에서 읽지 않음"),
    _kids(sf.PREG_CSV_NAME, "15089735", "2026-08-27", "2024-08-13"),
    _kids(sf.AGE_CSV_NAME, "15089531", "2026-08-07", "2024-08-13"),
    _kids(sf.DOSE_CSV_NAME, "15089533", "2026-09-28", "2024-08-13"),
    _kids(sf.LACT_CSV_NAME, "15131932", "2026-09-28", "2024-08-13"),
    # 노인주의약물: 파일명 날짜를 포털 수정일(2026-10-01)로 고쳤으므로 기준일(파일명 접미)과 수정일이 같다
    _kids(sf.ELDERLY_KIDS_CSV_NAME, "15089521", "2026-10-01", "2024-08-13"),
    # --- DUR 품목리스트(심평원 제공 CSV, 제품 단위, 기준일 월 단위). 병용금기 JSON(KIDS, 성분·제품 쌍+사유)과는 별개 자료다
    *(_file(_DUR.format(k), HIRA, dataset_id="15127983", modified="2026-06-12", registered="2026-06-12", cycle="연간", provider=HIRA)
      for k in ("노인주의", "노인주의(해열진통소염제)", "병용금기", "연령금기", "임부금기")),
    # --- 고시·법령 PDF(첫 쪽·추출 텍스트에서 읽은 값)
    # 시행일: 부칙 <제2026-52호, 2026. 7. 21.> "이 고시는 고시한 날부터 시행한다."(PDF 8쪽, 2026-11-11 확인) → 개정일과 같다
    DocMeta(GOSI_NAME, "식품의약품안전처", "고시", "제2026-52호", "2026-07-21", "2026-07-21", "2026-07-21", 2026),
    # 안전상비의약품 고시 제2012-144호(제정본, 시행 2012-11-15)는 제2016-156호로 대체되어 활성 문서가 아니다(이력, 2026-11-11 사용자 결정).
    # 파일 `sf.SAFE_GOSI_2012_PDF_NAME`은 data/에 남겨 둔다. 되살릴 때는 아래 형식으로 적는다:
    #   DocMeta(sf.SAFE_GOSI_2012_PDF_NAME, "보건복지부", "고시", "제2012-144호", "2012-10-31", "2012-11-15", None, 2012)
    DocMeta(sf.SAFE_GOSI_PDF_NAME, "보건복지부", "고시", "제2016-156호", "2016-08-24", "2016-08-24", None, 2016,
            LAW_URL, provider=LAW_PROVIDER),  # 첫 쪽 '시행 2016-08-24, 일부개정', 보건복지부 약무정책과, 국가법령정보센터
    DocMeta(sf.SAFE_BYEOLPYO_PDF_NAME, "보건복지부", "고시 별표", "제2016-156호", "2016-08-24", "2016-08-24", None, 2016,
            LAW_URL, provider=LAW_PROVIDER),  # 별표 첫 쪽에는 부처·번호·날짜가 없다. 값은 파일 이름(사용자 지정)과 같은 고시에서 온다
    DocMeta("약사법 시행규칙(보건복지부령)(제01181호)(20260621).pdf", "보건복지부", "시행규칙", "제1181호", "2026-06-19", "2026-06-21",
            None, 2026),
    DocMeta("약사법_제2항.pdf", "보건복지부", "법률", "제21525호", "2026-04-07", "2026-10-08", None, 2026,
            LAW_URL, provider=LAW_PROVIDER),  # 소관 보건복지부(사용자 알림). 첫 쪽에는 부처명이 없다(법률 제21525호)
    # --- 심평원 「기능과 역할」. 2026판이 현행(2026-11 발행 표기 2025-11), 2021~2025는 비교용
    _hira(2021, "G000BX1-2020-138"),
    _hira(2022, "G000BX1-2021-122"),
    # 발행일은 판권면에서 읽은 값(2023: PDF 753쪽 '2022. 12. 31.', 2024: 796쪽 '2024. 3. 15.', 2025: 817쪽 '2024년 12월', 2026-11-11 확인)
    _hira(2023, "G000BX1-2022-83", issued="2022-12-31"),
    _hira(2024, "G000BX1-2023-194", issued="2024-03-15"),
    _hira(2025, "G000BX1-2024-116", issued="2024-12"),
    _hira(2026, "G000BX1-2025-129", source_url=_HIRA_URL, issued="2025-11"),  # PDF 첫 쪽에서 확인(사용자 알림 2026-11-11)
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
