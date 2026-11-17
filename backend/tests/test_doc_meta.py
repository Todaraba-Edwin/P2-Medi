"""문서 메타 표 시험. 원본 파일이 없으면 대조는 skip한다(`data/`는 로컬 전용)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import source_files as sf
from app.db.doc_meta import DOC_META, chunk_meta, get_meta, parse_base_date

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (sf.PREG_CSV_NAME, "2026-07-21"),
        (sf.AGE_CSV_NAME, "2026-07-21"),
        (sf.DOSE_CSV_NAME, "2026-07-21"),
        (sf.LACT_CSV_NAME, "2025-11-27"),
        (sf.COMBO_JSON_NAME, "2026-07-31"),
        ("의약품안전사용서비스(DUR)_임부금기 품목리스트 2026.6.csv", "2026-06"),
        ("의약품안전사용서비스(DUR)_노인주의(해열진통소염제) 품목리스트 2026.12.csv", "2026-12"),
        ("약사법_제2항.pdf", None),
        ("x_20261340.csv", None),  # 월이 잘못된 날짜
    ],
)
def test_parse_base_date(name: str, expected: str | None) -> None:
    assert parse_base_date(name) == expected


def test_table_shape() -> None:
    assert len(DOC_META) >= 10
    assert all(k == m.source_file for k, m in DOC_META.items())
    assert all(m.source_url is None or m.source_url.startswith("http") for m in DOC_META.values())
    # 사용자가 알려 준 data.go.kr 데이터셋 번호만 주소로 만든다(지어내지 않는다)
    datasets = {m.source_file: m.dataset_id for m in DOC_META.values() if m.source_file.startswith("한국의약품안전관리원_")}
    assert datasets == {
        sf.COMBO_JSON_NAME: "15161282", sf.PREG_CSV_NAME: "15089735", sf.AGE_CSV_NAME: "15089531",
        sf.DOSE_CSV_NAME: "15089533", sf.LACT_CSV_NAME: "15131932", sf.ELDERLY_KIDS_CSV_NAME: "15089521",
        sf.COMBO_CSV_VERIFY_NAME: "15089525",
    }
    for m in DOC_META.values():
        if m.dataset_id:
            assert m.source_url == f"https://www.data.go.kr/data/{m.dataset_id}/fileData.do"


def test_portal_dates_recorded_but_base_date_unchanged() -> None:
    """수정일·등록일은 기록만 한다. base_date(파일명 접미)와 별개이며 표시·판정 기준일은 바뀌지 않았다(BE-16-02 A)."""
    m = get_meta(sf.COMBO_JSON_NAME)
    assert (m.modified_date, m.registered_date, m.update_cycle) == ("2026-09-23", "2026-08-18", "수시(1회성)")
    assert m.base_date == "2026-07-31"
    assert get_meta(sf.PREG_CSV_NAME).modified_date == "2026-08-27"
    assert get_meta(sf.ELDERLY_KIDS_CSV_NAME).modified_date == get_meta(sf.ELDERLY_KIDS_CSV_NAME).base_date == "2026-10-01"
    dur = [m for m in DOC_META.values() if m.source_file.startswith("의약품안전사용서비스(DUR)_")]
    assert len(dur) == 5
    assert {(m.dataset_id, m.modified_date, m.update_cycle, m.provider) for m in dur} == {("15127983", "2026-06-12", "연간", "건강보험심사평가원")}


def test_safe_drug_notice_is_2016_and_2012_is_history() -> None:
    assert get_meta(sf.SAFE_GOSI_PDF_NAME).notice_no == get_meta(sf.SAFE_BYEOLPYO_PDF_NAME).notice_no == "제2016-156호"
    assert get_meta(sf.SAFE_BYEOLPYO_PDF_NAME).provider == "국가법령정보센터"
    assert sf.SAFE_GOSI_2012_PDF_NAME not in DOC_META  # 대체됨(이력), 활성 문서 아님
    assert get_meta("약사법_제2항.pdf").issuer == "보건복지부"


def test_hira_edition_roles() -> None:
    """현행(2026판)만 코퍼스 적재 대상이고 나머지 판은 비교용(인용 참고 자료)이다."""
    hira = {m.year: m for m in DOC_META.values() if m.doc_type == "발간물"}
    assert sorted(hira) == [2021, 2022, 2023, 2024, 2025, 2026]
    assert {y: m.edition_role for y, m in hira.items()} == {2021: "비교용", 2022: "비교용", 2023: "비교용", 2024: "비교용", 2025: "비교용", 2026: "현행"}
    assert [m.notice_no for y, m in sorted(hira.items()) if y in (2021, 2022, 2026)] == ["G000BX1-2020-138", "G000BX1-2021-122", "G000BX1-2025-129"]
    assert hira[2026].source_url and "recommendIdx=177231" in hira[2026].source_url


def test_base_date_matches_filename_for_file_data() -> None:
    for m in DOC_META.values():
        if m.base_date and m.source_file.endswith((".csv", ".json")):
            assert m.base_date == parse_base_date(m.source_file)
            assert m.year == int(m.base_date[:4])


def test_chunk_meta_values() -> None:
    cm = chunk_meta(sf.COMBO_JSON_NAME)
    assert cm == {"year": 2026, "source_file": sf.COMBO_JSON_NAME, "effective_date": None}
    assert get_meta(sf.GOSI_PDF_NAME).notice_no == "제2026-52호"
    with pytest.raises(KeyError):
        chunk_meta("없는 파일.csv")


def _first_text(path: Path) -> str:
    if path.suffix != ".pdf":
        return path.read_text(encoding="utf-8")
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(path) as pdf:
        return "".join((pg.extract_text() or "") for pg in pdf.pages[:2])


@pytest.mark.parametrize("meta", [m for m in DOC_META.values() if m.source_file.endswith(".pdf")], ids=lambda m: m.source_file[:30])
def test_pdf_first_page_contains_issuer_and_notice(meta) -> None:  # noqa: ANN001
    path = DATA / meta.source_file
    if not path.exists():
        pytest.skip("data/ 원본 없음(로컬 전용)")
    text = _first_text(path).replace(" ", "")
    if not text.strip():
        pytest.skip("텍스트 층 없는 PDF(미확인 칸은 None)")
    if meta.doc_type == "발간물" and meta.year in (2021, 2022, 2026):
        pytest.skip("발간등록번호는 사용자가 표지 이미지에서 확인해 알려 준 값(텍스트 층에 없음, 2026-11-11)")
    if meta.doc_type in ("고시 별표", "법률"):
        pytest.skip("첫 쪽에 부처·번호가 없는 문서(값은 파일 이름·사용자 알림에서 옴)")
    if meta.issuer:
        assert meta.issuer.replace(" ", "") in text
    if meta.notice_no and meta.doc_type == "발간물":
        assert meta.notice_no in text
    elif meta.notice_no:
        num = meta.notice_no.removeprefix("제").removesuffix("호")  # '2026-52' / '1181' / '21525'
        assert num.replace("-", "") in text.replace("-", "").replace("제", "") or num in text


def test_combo_as_of_comes_from_file_name_and_others_unchanged():
    """병용금기 판정 경로의 기준일은 파일 이름(2026-07-31)에서, 임부·연령·용량·수유부는 기존 값(plan-critic #2)."""
    from app.db import loaders
    from app.tools import lookup, provenance

    assert loaders.AS_OF_COMBO == parse_base_date(sf.COMBO_JSON_NAME) == "2026-07-31"
    assert loaders.AS_OF_KIDS == "2026-07-21" and loaders.AS_OF_LACTATION == "2025-11-27"
    assert lookup._KIND_SOURCE["contra_pair"][1] == provenance.DATASET_AS_OF["contra_pair"] == loaders.AS_OF_COMBO
    for k in ("pregnancy", "age", "dose"):
        assert lookup._KIND_SOURCE[k][1] == provenance.DATASET_AS_OF[k] == "2026-07-21"
    assert lookup._KIND_SOURCE["lactation"][1] == "2025-11-27"
    row = loaders.normalize_contra_json({"metadata": {"성분코드A": "100501ATE", "성분코드B": "100601ATE", "금기사유": "x", "고시번호": "1"}})
    assert row["as_of"] == loaders.AS_OF_COMBO
    assert loaders.CORE_SOURCES[sf.COMBO_JSON_NAME][2] == loaders.AS_OF_COMBO


def test_combo_verify_csv_is_recorded_only() -> None:
    """검증본 CSV는 기록만 한다: 병용 JSON과 기준일이 같고 신선도 점검에서 JSON의 '최신본 아님' 표시를 바꾸지 않는다."""
    csv, js = get_meta(sf.COMBO_CSV_VERIFY_NAME), get_meta(sf.COMBO_JSON_NAME)
    assert (csv.dataset_id, csv.modified_date, csv.registered_date, csv.update_cycle, csv.provider) == (
        "15089525", "2026-08-10", "2024-08-13", "수시(1회성)", "한국의약품안전관리원")
    assert csv.base_date == js.base_date == "2026-07-31"
    assert csv.note and "코드에서 읽지 않음" in csv.note and "512,464" in csv.note
    assert js.note and "BE-16-02 A" in js.note and js.modified_date == "2026-09-23"
    assert sf.COMBO_CSV_VERIFY_NAME != sf.COMBO_JSON_NAME


def test_dates_read_from_pdfs() -> None:
    """2026-11-11 PDF에서 읽은 값: 병용금기 고시 시행일(부칙 8쪽), 기능과 역할 발행일(판권면)."""
    assert get_meta(sf.GOSI_PDF_NAME).effective_date == "2026-07-21"
    assert {y: m.enacted_or_revised_date for y, m in ((m.year, m) for m in DOC_META.values() if m.doc_type == "발간물")} == {
        2021: None, 2022: None, 2023: "2022-12-31", 2024: "2024-03-15", 2025: "2024-12", 2026: "2025-11"}


def test_be16_01_user_answers_reflected_and_unknowns_stay_none() -> None:
    """BE-16-01 B(2026-11-11) 사용자 답 §1.1 1~3번이 반영됐고, 근거가 없는 칸은 None('미확인')으로 남는다(지어내지 않음)."""
    # 1. 안전상비 별표: 고시 제2016-156호(시행 2016-08-24), 본문과 같은 고시
    gosi, byeol = get_meta(sf.SAFE_GOSI_PDF_NAME), get_meta(sf.SAFE_BYEOLPYO_PDF_NAME)
    assert (byeol.issuer, byeol.doc_type, byeol.notice_no, byeol.enacted_or_revised_date, byeol.effective_date) == (
        "보건복지부", "고시 별표", "제2016-156호", "2016-08-24", "2016-08-24")
    assert (byeol.notice_no, byeol.effective_date) == (gosi.notice_no, gosi.effective_date)
    # 2. 약사법 제28조 제2항 발췌: 소관 보건복지부, 제공 국가법령정보센터
    law = get_meta("약사법_제2항.pdf")
    assert (law.issuer, law.provider, law.source_url) == ("보건복지부", "국가법령정보센터", "https://www.law.go.kr")
    # 3. 심평원 「기능과 역할」 발간등록번호 3건(2021·2022·2026)
    hira = {m.year: m for m in DOC_META.values() if m.doc_type == "발간물"}
    assert {y: hira[y].notice_no for y in (2021, 2022, 2026)} == {
        2021: "G000BX1-2020-138", 2022: "G000BX1-2021-122", 2026: "G000BX1-2025-129"}
    # 근거가 없는 칸은 None 그대로
    assert byeol.base_date is None and gosi.base_date is None  # 고시는 데이터 기준일 개념이 없다
    assert hira[2021].enacted_or_revised_date is None and hira[2022].enacted_or_revised_date is None
    assert all(hira[y].source_url is None for y in (2021, 2022, 2023, 2024, 2025))
    rule = get_meta("약사법 시행규칙(보건복지부령)(제01181호)(20260621).pdf")
    assert rule.source_url is None and rule.provider is None


@pytest.mark.parametrize(
    ("name", "as_of_attr"),
    [
        (sf.COMBO_JSON_NAME, "AS_OF_COMBO"),
        (sf.PREG_CSV_NAME, "AS_OF_KIDS"),
        (sf.AGE_CSV_NAME, "AS_OF_KIDS"),
        (sf.DOSE_CSV_NAME, "AS_OF_KIDS"),
        (sf.LACT_CSV_NAME, "AS_OF_LACTATION"),
        (sf.ELDERLY_KIDS_CSV_NAME, "AS_OF_ELDERLY_KIDS"),
    ],
)
def test_doc_meta_base_date_equals_citation_as_of(name: str, as_of_attr: str) -> None:
    """출처 표의 '기준일'(`loaders.AS_OF_*`, 파일 단위)과 문서 메타 표의 `base_date`가 같다(PRD-12 §5 자료마다 따로, BE-16 §2)."""
    from app.db import loaders

    assert get_meta(name).base_date == getattr(loaders, as_of_attr)


@pytest.mark.xfail(strict=True, reason="BE-06 §3 후속(BE-06-08 A): AS_OF_HIRA '2026-06-01'은 원본 '2026.6'에 없는 날을 붙인 값. 정정되면 이 표시를 지운다")
def test_dur_list_as_of_is_month_like_doc_meta() -> None:
    from app.db import loaders

    dur = {m.base_date for m in DOC_META.values() if m.source_file.startswith("의약품안전사용서비스(DUR)_")}
    assert dur == {"2026-06"}
    assert loaders.AS_OF_HIRA == "2026-06"
