"""BE-09 금기 데이터 파서·정규화·적재 함수.

- CSV는 CP949로 읽어 UTF-8 문자열로 바꾼다(KIDS·심평원 CSV 공통).
- 병용금기 JSON(약 540MB)은 한 번에 읽지 않고 청크 단위로 객체를 하나씩 꺼낸다(`iter_json_array`).
  외부 의존성(ijson)을 쓰지 않고 표준 라이브러리 `json.JSONDecoder.raw_decode`로 처리한다.
- 병용금기는 제품 쌍(512,464건)을 성분코드 쌍으로 줄여 적재한다(RFP-17 결정 6, BE-09 메모).
- 금기등급은 원본 값('1'·'2'·'M')을 그대로 둔다. 텍스트는 앞뒤 공백만 지우고 내용은 바꾸지 않는다.
- 이 모듈은 원격 DB에 접속하지 않는다. `load_into`는 호출자가 넘긴 DB-API 연결에만 쓴다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.source_files import COMBO_JSON_NAME

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

SRC_KIDS = "한국의약품안전관리원"
SRC_HIRA = "건강보험심사평가원"

# 파일별 기준일(BE-09 완료 조건, RFP 5.1절 (5)). 심평원 품목리스트는 '2026.6' 월 단위 표기라 월초로 적는다.
AS_OF_KIDS = "2026-07-21"
AS_OF_LACTATION = "2025-11-27"
AS_OF_HIRA = "2026-06-01"

# 비교용 환산(일). 연령 비교는 어림값이며 판정 값 자체는 원본 단위를 함께 보존한다.
_UNIT_DAYS = {"주": 7.0, "개월": 30.4375, "세": 365.25}
_VALID_CONDS = {"미만", "이하", "이상"}
_CODE_RE = re.compile(r"^[0-9]{6}[A-Z]{3}$")  # KIDS 성분코드(9자리, 제형 포함)

# 테이블별 컬럼(삽입 순서). row_key가 첫 컬럼이다.
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "contra_pair": (
        "row_key", "code_a", "code_b", "code_lo", "code_hi", "name_a", "name_b",
        "notice_no", "notice_date", "reason", "remark", "source", "as_of",
    ),
    "pregnancy_contra": (
        "row_key", "ingr_code", "ingr_name", "grade", "detail",
        "notice_no", "notice_date", "source", "as_of",
    ),
    "age_contra": (
        "row_key", "ingr_code", "ingr_name", "age_value", "age_unit", "age_cond", "age_days",
        "detail", "notice_no", "notice_date", "source", "as_of",
    ),
    "caution": (
        "row_key", "kind", "ingr_code", "ingr_name", "detail",
        "notice_no", "notice_date", "source", "as_of",
    ),
}


def is_valid_code(code: str | None) -> bool:
    """KIDS 성분코드 형식(숫자 6 + 영대문자 3)인지 본다."""
    return bool(code) and bool(_CODE_RE.match(code))


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _row_key(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(_s(p) for p in parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- 파서

def iter_csv(path: str | Path, encoding: str = "cp949") -> Iterator[dict[str, str]]:
    """CSV를 행 단위로 읽는다. 기본 CP949, BOM 있는 UTF-8은 `utf-8-sig`를 넘긴다."""
    with open(path, encoding=encoding, newline="") as f:
        yield from csv.DictReader(f)


def iter_json_array(
    path: str | Path, chunk_size: int = 1 << 20, limit: int | None = None
) -> Iterator[Any]:
    """최상위가 배열인 큰 JSON 파일에서 원소를 하나씩 꺼낸다(메모리는 청크 크기 수준).

    `limit`이 있으면 그 개수만 읽고 멈춘다(앞부분만 읽기 시험용).
    """
    decoder = json.JSONDecoder()
    emitted = 0
    with open(path, encoding="utf-8") as f:
        buf = ""
        idx = 0
        eof = False

        def fill() -> bool:
            nonlocal buf, idx, eof
            if eof:
                return False
            chunk = f.read(chunk_size)
            if not chunk:
                eof = True
                return False
            buf = buf[idx:] + chunk
            idx = 0
            return True

        # 여는 대괄호까지 건너뛴다.
        while True:
            while idx < len(buf) and buf[idx].isspace():
                idx += 1
            if idx < len(buf):
                break
            if not fill():
                return
        if buf[idx] != "[":
            raise ValueError("최상위가 JSON 배열이 아니다")
        idx += 1

        while True:
            # 공백과 쉼표를 건너뛴다.
            while True:
                while idx < len(buf) and (buf[idx].isspace() or buf[idx] == ","):
                    idx += 1
                if idx < len(buf):
                    break
                if not fill():
                    raise ValueError("JSON 배열이 닫히지 않은 채 끝났다")
            if buf[idx] == "]":
                return
            # 객체 하나를 해석한다. 중간에 끊겼으면 더 읽고 다시 시도한다.
            while True:
                try:
                    obj, end = decoder.raw_decode(buf, idx)
                    break
                except json.JSONDecodeError:
                    if not fill():
                        raise
            idx = end
            yield obj
            emitted += 1
            if limit is not None and emitted >= limit:
                return
            if idx > (1 << 16):  # 버퍼 앞부분을 가끔 정리한다(분할 상환).
                buf = buf[idx:]
                idx = 0


# --------------------------------------------------------------------------- 정규화

def normalize_contra_json(obj: dict[str, Any]) -> dict[str, Any] | None:
    """병용금기 JSON 원소 → 성분코드 쌍 레코드. 성분코드가 없으면 None."""
    m = obj.get("metadata") or {}
    a, b = _s(m.get("성분코드A")), _s(m.get("성분코드B"))
    if not a or not b:
        return None
    lo, hi = sorted((a, b))
    notice_no = _s(m.get("고시번호"))
    reason = _s(m.get("금기사유"))
    return {
        "row_key": _row_key("contra", a, b, notice_no, reason),
        "code_a": a, "code_b": b, "code_lo": lo, "code_hi": hi,
        "name_a": _s(m.get("성분명A")), "name_b": _s(m.get("성분명B")),
        "notice_no": notice_no, "notice_date": _s(m.get("고시적용일")) or None,
        "reason": reason, "remark": _s(m.get("비고")),
        "source": SRC_KIDS, "as_of": AS_OF_KIDS,
    }


def normalize_pregnancy(row: dict[str, str]) -> dict[str, Any] | None:
    """임부금기 CSV 행 → 성분코드 단위 레코드. 등급은 '1'·'2'·'M' 그대로."""
    code, grade = _s(row.get("성분코드")), _s(row.get("금기등급"))
    if not code or grade not in {"1", "2", "M"}:
        return None
    detail, notice_no = _s(row.get("상세정보")), _s(row.get("고시번호"))
    return {
        "row_key": _row_key("pregnancy", code, grade, notice_no, detail),
        "ingr_code": code, "ingr_name": _s(row.get("성분명")), "grade": grade,
        "detail": detail, "notice_no": notice_no,
        "notice_date": _s(row.get("고시일자")) or None,
        "source": SRC_KIDS, "as_of": AS_OF_KIDS,
    }


def _strip_paren(text: str) -> str:
    """'세 (3)' → '세', '미만 (1)' → '미만'."""
    return text.split("(")[0].strip()


def age_to_days(value: int | float, unit: str) -> int:
    """연령 값을 일 단위로 환산(반올림). 알 수 없는 단위는 ValueError."""
    if unit not in _UNIT_DAYS:
        raise ValueError(f"알 수 없는 연령 단위: {unit!r}")
    return round(value * _UNIT_DAYS[unit])


def normalize_age(row: dict[str, str]) -> dict[str, Any] | None:
    """연령금기 CSV 행 → (성분코드, 특정연령, 단위, 처리조건) 레코드."""
    code = _s(row.get("성분코드"))
    unit, cond = _strip_paren(_s(row.get("특정연령단위"))), _strip_paren(_s(row.get("연령처리조건")))
    try:
        value = int(_s(row.get("특정연령")))
        days = age_to_days(value, unit)
    except ValueError:
        return None
    if not code or cond not in _VALID_CONDS:
        return None
    detail, notice_no = _s(row.get("상세정보")), _s(row.get("고시번호"))
    return {
        "row_key": _row_key("age", code, value, unit, cond, notice_no, detail),
        "ingr_code": code, "ingr_name": _s(row.get("성분명")),
        "age_value": value, "age_unit": unit, "age_cond": cond, "age_days": days,
        "detail": detail, "notice_no": notice_no,
        "notice_date": _s(row.get("고시일자")) or None,
        "source": SRC_KIDS, "as_of": AS_OF_KIDS,
    }


def _caution(kind: str, code: str, name: str, detail: str, notice_no: str,
             notice_date: str, source: str, as_of: str) -> dict[str, Any] | None:
    if not code:
        return None
    return {
        "row_key": _row_key("caution", kind, code, notice_no, detail),
        "kind": kind, "ingr_code": code, "ingr_name": name, "detail": detail,
        "notice_no": notice_no, "notice_date": notice_date or None,
        "source": source, "as_of": as_of,
    }


def normalize_dose(row: dict[str, str]) -> dict[str, Any] | None:
    """용량주의약물 CSV(일반명코드 키). 상세에는 '1일 최대투여량' 표시 문자열 원문만 둔다."""
    return _caution("dose", _s(row.get("일반명코드")), _s(row.get("일반명(복합제의 경우 1성분만 표시됨)")),
                    _s(row.get("1일 최대투여량")), _s(row.get("공고번호")), _s(row.get("공고일자")),
                    SRC_KIDS, AS_OF_KIDS)


def normalize_lactation(row: dict[str, str]) -> dict[str, Any] | None:
    """수유부주의 CSV(주성분코드 키)."""
    return _caution("lactation", _s(row.get("주성분코드")), _s(row.get("성분명")), _s(row.get("비고")),
                    _s(row.get("공고번호")), _s(row.get("공고일자")), SRC_KIDS, AS_OF_LACTATION)


def normalize_elderly(row: dict[str, str]) -> dict[str, Any] | None:
    """심평원 노인주의 품목리스트 2종(성분코드 키, 두 파일의 열 순서가 다르지만 열 이름은 같다)."""
    return _caution("elderly", _s(row.get("성분코드")), _s(row.get("성분명")), _s(row.get("약품상세정보")),
                    _s(row.get("공고번호")), _s(row.get("공고일자")), SRC_HIRA, AS_OF_HIRA)


# --------------------------------------------------------------------------- 수집·집계

@dataclass
class LoadStats:
    table: str
    source_file: str
    as_of: str
    raw_rows: int = 0       # 원본 행 수(성분코드 없는 행 포함)
    skipped: int = 0        # 정규화에서 버린 행(코드·등급·연령 값 이상)
    unique_rows: int = 0    # 키 기준 고유 행 수(적재 대상)
    text_bytes: int = 0     # 고유 행의 UTF-8 텍스트 바이트 합


@dataclass
class Collected:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: LoadStats | None = None


def collect(
    rows: Iterable[Any],
    normalizer: Callable[[Any], dict[str, Any] | None],
    table: str,
    source_file: str,
    as_of: str,
    into: Collected | None = None,
) -> Collected:
    """행을 정규화하고 row_key로 중복을 합친다. 같은 키의 첫 행을 남긴다(적재 재실행에도 같은 결과)."""
    out = into or Collected()
    st = out.stats or LoadStats(table, source_file, as_of)
    out.stats = st
    for row in rows:
        st.raw_rows += 1
        rec = normalizer(row)
        if rec is None:
            st.skipped += 1
            continue
        out.records.setdefault(rec["row_key"], rec)
    st.unique_rows = len(out.records)
    st.text_bytes = sum(
        len(str(v).encode("utf-8")) for r in out.records.values() for v in r.values() if v is not None
    )
    return out


# 파일 → (테이블, 정규화 함수, 파서) 대응. 파일 이름은 `data/` 안의 원본 이름이다.
CORE_SOURCES = {
    COMBO_JSON_NAME: ("contra_pair", normalize_contra_json, AS_OF_KIDS),
    "한국의약품안전관리원_임부금기약물_20260721.csv": ("pregnancy_contra", normalize_pregnancy, AS_OF_KIDS),
    "한국의약품안전관리원_연령금기_20260721.csv": ("age_contra", normalize_age, AS_OF_KIDS),
}
EXTENSION_SOURCES = {
    "한국의약품안전관리원_용량주의약물_20260721.csv": ("caution", normalize_dose, AS_OF_KIDS),
    "한국의약품안전관리원_수유부주의_20251127.csv": ("caution", normalize_lactation, AS_OF_LACTATION),
    "의약품안전사용서비스(DUR)_노인주의 품목리스트 2026.6.csv": ("caution", normalize_elderly, AS_OF_HIRA),
    "의약품안전사용서비스(DUR)_노인주의(해열진통소염제) 품목리스트 2026.6.csv": ("caution", normalize_elderly, AS_OF_HIRA),
}


def read_source(path: Path, normalizer, table, as_of, limit: int | None = None, into: Collected | None = None) -> Collected:
    """파일 하나를 읽어 수집한다. JSON은 스트리밍, CSV는 CP949 행 단위. `limit`은 원본 행 상한."""
    if path.suffix.lower() == ".json":
        rows: Iterable[Any] = iter_json_array(path, limit=limit)
    else:
        rows = iter_csv(path)
        if limit is not None:
            rows = _take(rows, limit)
    return collect(rows, normalizer, table, path.name, as_of, into=into)


def _take(it: Iterable[Any], n: int) -> Iterator[Any]:
    for i, x in enumerate(it):
        if i >= n:
            return
        yield x


def collect_all(
    data_dir: str | Path, include_extension: bool = True, limit: int | None = None
) -> dict[str, Collected]:
    """`data/`의 파일을 모두 읽어 파일 이름 → 수집 결과로 돌려준다(없는 파일은 건너뛴다)."""
    data_dir = Path(data_dir)
    sources = dict(CORE_SOURCES)
    if include_extension:
        sources.update(EXTENSION_SOURCES)
    out: dict[str, Collected] = {}
    for name, (table, norm, as_of) in sources.items():
        path = data_dir / name
        if path.exists():
            out[name] = read_source(path, norm, table, as_of, limit=limit)
    return out


# --------------------------------------------------------------------------- 크기 어림

# Postgres 행 오버헤드 어림(바이트): 튜플 헤더 24 + 아이템 포인터 4 + 가변길이 헤더·정렬 ≈ 40.
_ROW_OVERHEAD = 40
# 인덱스 항목 어림: PK(row_key 40자) ≈ 75, 코드 인덱스(코드 1~2개) ≈ 40(채움률·헤더 포함).
_PK_INDEX_PER_ROW = 75
_CODE_INDEX_PER_ROW = 40


def estimate_size(collected: dict[str, Collected]) -> dict[str, Any]:
    """로컬 파싱 결과로 테이블별 행 수와 Postgres 적재 크기를 어림한다(실측 아님)."""
    per_table: dict[str, dict[str, int]] = {}
    for c in collected.values():
        st = c.stats
        t = per_table.setdefault(st.table, {"rows": 0, "text_bytes": 0})
        t["rows"] += st.unique_rows
        t["text_bytes"] += st.text_bytes
    total = 0
    for t in per_table.values():
        t["est_bytes"] = (
            t["text_bytes"] + t["rows"] * (_ROW_OVERHEAD + _PK_INDEX_PER_ROW + _CODE_INDEX_PER_ROW)
        )
        total += t["est_bytes"]
    return {"tables": per_table, "total_est_bytes": total, "free_plan_limit_bytes": 500 * 1024 * 1024}


# --------------------------------------------------------------------------- 적재(DB-API)

def _placeholder(paramstyle: str) -> str:
    if paramstyle == "qmark":
        return "?"
    if paramstyle in ("format", "pyformat"):
        return "%s"
    raise ValueError(f"지원하지 않는 paramstyle: {paramstyle}")


def apply_schema(conn: Any) -> None:
    """schema.sql을 적용한다(IF NOT EXISTS라 재실행해도 안전)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    if hasattr(conn, "executescript"):  # sqlite3
        conn.executescript(sql)
    else:
        cur = conn.cursor()
        cur.execute(sql)
    conn.commit()


def insert_records(conn: Any, table: str, records: Iterable[dict[str, Any]], paramstyle: str = "qmark",
                   batch: int = 1000) -> None:
    """레코드를 `ON CONFLICT (row_key) DO NOTHING`으로 넣는다. 같은 데이터를 다시 넣어도 중복이 없다."""
    cols = TABLE_COLUMNS[table]
    ph = _placeholder(paramstyle)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join([ph] * len(cols))}) "
           f"ON CONFLICT (row_key) DO NOTHING")
    cur = conn.cursor()
    buf: list[tuple] = []
    for rec in records:
        buf.append(tuple(rec[c] for c in cols))
        if len(buf) >= batch:
            cur.executemany(sql, buf)
            buf.clear()
    if buf:
        cur.executemany(sql, buf)
    conn.commit()


def count_rows(conn: Any, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


def load_into(conn: Any, collected: dict[str, Collected], paramstyle: str = "qmark") -> dict[str, int]:
    """수집 결과를 테이블에 넣고 load_log를 갱신한다. 테이블별 행 수를 돌려준다."""
    apply_schema(conn)
    ph = _placeholder(paramstyle)
    for name, c in collected.items():
        st = c.stats
        insert_records(conn, st.table, c.records.values(), paramstyle)
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO load_log (source_file, table_name, raw_rows, loaded_rows, as_of) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}) ON CONFLICT (source_file) DO UPDATE SET "
            f"table_name = excluded.table_name, raw_rows = excluded.raw_rows, "
            f"loaded_rows = excluded.loaded_rows, as_of = excluded.as_of",
            (name, st.table, st.raw_rows, st.unique_rows, st.as_of),
        )
        conn.commit()
    return {t: count_rows(conn, t) for t in TABLE_COLUMNS}


# --------------------------------------------------------------------------- CLI (로컬 전용)

def _main() -> None:
    """`python -m app.db.loaders --data-dir ../data [--sqlite OUT.db]`: 행 수·크기 어림을 출력한다.

    원격 DB 연결은 하지 않는다. `--sqlite`는 로컬 SQLite 파일에 적재해 크기를 재는 용도다.
    """
    ap = argparse.ArgumentParser(description=_main.__doc__)
    ap.add_argument("--data-dir", default="../data")
    ap.add_argument("--sqlite", help="로컬 SQLite 파일 경로(적재 크기 측정용)")
    ap.add_argument("--no-extension", action="store_true")
    args = ap.parse_args()

    collected = collect_all(args.data_dir, include_extension=not args.no_extension)
    for name, c in collected.items():
        s = c.stats
        print(f"{name}: table={s.table} raw={s.raw_rows} skipped={s.skipped} unique={s.unique_rows} "
              f"text_bytes={s.text_bytes} as_of={s.as_of}")
    print(json.dumps(estimate_size(collected), ensure_ascii=False, indent=2))
    if args.sqlite:
        import sqlite3

        conn = sqlite3.connect(args.sqlite)
        print("rows:", load_into(conn, collected))
        conn.close()
        print("sqlite_file_bytes:", Path(args.sqlite).stat().st_size)


if __name__ == "__main__":
    _main()
