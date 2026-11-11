"""BE-09 성분코드 정확 일치 조회 도구 함수(병용·연령·임부 금기, 확장 주의).

판정은 코드가 한다(성분코드 정확 일치, RFP-17 결정 1). LLM·RAG는 판정하지 않는다.
반환은 도구 출력 계약(`PJ2-Agent-Harness.md` 3.4절, AG-02 RFP-33-04)의 `items[]` 형식을 따른다.
  - 항목 하나 = 쌍 1개 또는 약 1개 × 금기 종류. 상태는 항목마다 `FOUND`·`NOT_LISTED`·`UNIDENTIFIED`.
  - 항목마다 근거 ID(`evidence_id`)·출처·기준일·꼬리표를 단다.
  - `NOT_LISTED`는 "조회는 성공했고 금기 목록에 없음"이지 안전하다는 뜻이 아니다.
그래프 노드와의 연결·Pydantic 인자 스키마(`ARG_SCHEMA` 차단)는 AG-02 몫이며, 여기서는 함수 시그니처와
DB-API 조회만 맡는다. 원격 DB 연결은 호출자가 넘긴 `conn`이 정한다(이 모듈은 접속하지 않는다).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any

from app.db.loaders import (
    AS_OF_COMBO,
    AS_OF_HIRA,
    AS_OF_KIDS,
    AS_OF_LACTATION,
    SRC_HIRA,
    SRC_KIDS,
    age_to_days,
    is_valid_code,
)

FOUND = "FOUND"
NOT_LISTED = "NOT_LISTED"
UNIDENTIFIED = "UNIDENTIFIED"

# 종류별 출처·기준일(NOT_LISTED 항목에도 단다. FOUND는 행의 값을 쓴다).
_KIND_SOURCE = {
    "contra_pair": (SRC_KIDS, AS_OF_COMBO),
    "pregnancy": (SRC_KIDS, AS_OF_KIDS),
    "age": (SRC_KIDS, AS_OF_KIDS),
    "dose": (SRC_KIDS, AS_OF_KIDS),
    "lactation": (SRC_KIDS, AS_OF_LACTATION),
    "elderly": (SRC_HIRA, AS_OF_HIRA),
}
_CAUTION_KINDS = ("dose", "lactation", "elderly")
# 자료 키: contra_pair=병용금기 파일, pregnancy=임부금기 파일, age=연령금기 파일, dose·lactation=각 파일, elderly=심평원 노인주의.
# 화면 문자열(약칭)은 AG-02의 공통 상수 모듈이 이 키로 찾는다. 여기서는 키만 둔다.
DATASET_KEYS = frozenset(_KIND_SOURCE)
ROW_ID_LEN = 12


@dataclass(frozen=True)
class Age:
    """사용자 나이. 단위는 '주'·'개월'·'세'다."""

    value: float
    unit: str = "세"

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("나이는 0 이상이어야 한다")
        age_to_days(0, self.unit)  # 알 수 없는 단위면 ValueError

    @property
    def days(self) -> int:
        return age_to_days(self.value, self.unit)


@dataclass
class Item:
    kind: str                       # contra_pair | pregnancy | age | dose | lactation | elderly | identify
    status: str                     # FOUND | NOT_LISTED | UNIDENTIFIED
    subject: tuple[str, ...]        # 성분코드(쌍이면 2개). 식별 실패면 입력 원문
    evidence_id: str
    source: str | None
    as_of: str | None
    flags: list[str] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)  # FOUND일 때 원문 행(`row_key`·`row_evidence_id`·등급·사유·상세정보·고시번호)
    dataset_key: str | None = None  # 자료 키(화면 문자열이 아니다). 식별 실패(`identify`)는 None

    def __post_init__(self) -> None:
        if self.dataset_key is None and self.kind in DATASET_KEYS:
            self.dataset_key = self.kind

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["subject"] = list(self.subject)
        return d


@dataclass
class ToolResult:
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"items": [i.to_dict() for i in self.items]}


# --------------------------------------------------------------------------- DB 조회

def _ph(paramstyle: str) -> str:
    return "?" if paramstyle == "qmark" else "%s"


def _query(conn: Any, sql: str, params: Sequence[Any], paramstyle: str) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql.replace("{ph}", _ph(paramstyle)), tuple(params))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _match(row: dict[str, Any], keys: Sequence[str], evidence_id: str) -> dict[str, Any]:
    """원문 행 + 행 키(`row_key`)와 행 단위 근거 ID(`{evidence_id}#{row_key 앞 12자}`)."""
    out = _plain(row, keys)
    rk = str(row["row_key"])
    out["row_key"] = rk
    out["row_evidence_id"] = f"{evidence_id}#{rk[:ROW_ID_LEN]}"
    return out


def _plain(row: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    out = {}
    for k in keys:
        v = row.get(k)
        out[k] = v if v is None or isinstance(v, (int, float)) else str(v)  # date → 'YYYY-MM-DD'
    return out


# --------------------------------------------------------------------------- 종류별 조회

def lookup_pair(conn: Any, code_a: str, code_b: str, paramstyle: str = "qmark") -> Item:
    """성분코드 두 개의 병용금기. 방향(A/B)과 무관하게 일치한다."""
    lo, hi = sorted((code_a, code_b))
    rows = _query(
        conn,
        "SELECT row_key, code_a, code_b, name_a, name_b, notice_no, notice_date, reason, remark, source, as_of "
        "FROM contra_pair WHERE code_lo = {ph} AND code_hi = {ph} ORDER BY notice_no, row_key",
        (lo, hi), paramstyle,
    )
    evidence_id = f"contra_pair:{lo}:{hi}"
    if not rows:
        src, as_of = _KIND_SOURCE["contra_pair"]
        return Item("contra_pair", NOT_LISTED, (code_a, code_b), evidence_id, src, as_of)
    keys = ("code_a", "code_b", "name_a", "name_b", "notice_no", "notice_date", "reason", "remark")
    return Item("contra_pair", FOUND, (code_a, code_b), evidence_id, rows[0]["source"], str(rows[0]["as_of"]),
                matches=[_match(r, keys, evidence_id) for r in rows])


def lookup_pregnancy(conn: Any, code: str, paramstyle: str = "qmark") -> Item:
    """성분코드 하나의 임부금기. 등급은 '1'·'2'·'M' 그대로, 상세정보는 원문 그대로 돌려준다(환산 없음)."""
    rows = _query(
        conn,
        "SELECT row_key, ingr_code, ingr_name, grade, detail, notice_no, notice_date, source, as_of "
        "FROM pregnancy_contra WHERE ingr_code = {ph} ORDER BY grade, notice_no, row_key",
        (code,), paramstyle,
    )
    evidence_id = f"pregnancy:{code}"
    if not rows:
        src, as_of = _KIND_SOURCE["pregnancy"]
        return Item("pregnancy", NOT_LISTED, (code,), evidence_id, src, as_of)
    keys = ("ingr_code", "ingr_name", "grade", "detail", "notice_no", "notice_date")
    return Item("pregnancy", FOUND, (code,), evidence_id, rows[0]["source"], str(rows[0]["as_of"]),
                matches=[_match(r, keys, evidence_id) for r in rows])


def _age_hit(age_days: int, cond: str, threshold_days: int) -> bool:
    if cond == "미만":
        return age_days < threshold_days
    if cond == "이하":
        return age_days <= threshold_days
    if cond == "이상":
        return age_days >= threshold_days
    return False


def lookup_age(conn: Any, code: str, age: Age, paramstyle: str = "qmark") -> Item:
    """성분코드 + 나이의 연령금기. 키는 성분코드 + 특정연령·단위·처리조건이고 비교는 일 환산으로 한다."""
    rows = _query(
        conn,
        "SELECT row_key, ingr_code, ingr_name, age_value, age_unit, age_cond, age_days, detail, notice_no, "
        "notice_date, source, as_of FROM age_contra WHERE ingr_code = {ph} ORDER BY age_days, row_key",
        (code,), paramstyle,
    )
    evidence_id = f"age:{code}"
    hits = [r for r in rows if _age_hit(age.days, r["age_cond"], int(r["age_days"]))]
    if not hits:
        src, as_of = _KIND_SOURCE["age"]
        return Item("age", NOT_LISTED, (code,), evidence_id, src, as_of)
    keys = ("ingr_code", "ingr_name", "age_value", "age_unit", "age_cond", "detail", "notice_no", "notice_date")
    return Item("age", FOUND, (code,), evidence_id, hits[0]["source"], str(hits[0]["as_of"]),
                matches=[_match(r, keys, evidence_id) for r in hits])


def lookup_caution(conn: Any, code: str, kind: str, paramstyle: str = "qmark") -> Item:
    """확장 주의(용량·수유부·노인). 주의 여부와 원문만 돌려주고 복용 판단은 하지 않는다."""
    if kind not in _CAUTION_KINDS:
        raise ValueError(f"알 수 없는 주의 종류: {kind}")
    rows = _query(
        conn,
        "SELECT row_key, ingr_code, ingr_name, kind, detail, notice_no, notice_date, source, as_of "
        "FROM caution WHERE kind = {ph} AND ingr_code = {ph} ORDER BY notice_no, row_key",
        (kind, code), paramstyle,
    )
    evidence_id = f"{kind}:{code}"
    if not rows:
        src, as_of = _KIND_SOURCE[kind]
        return Item(kind, NOT_LISTED, (code,), evidence_id, src, as_of)
    keys = ("ingr_code", "ingr_name", "detail", "notice_no", "notice_date")
    return Item(kind, FOUND, (code,), evidence_id, rows[0]["source"], str(rows[0]["as_of"]),
                matches=[_match(r, keys, evidence_id) for r in rows])


# --------------------------------------------------------------------------- 도구 함수

def check_contraindications(
    conn: Any,
    ingredient_codes: Sequence[str | None],
    *,
    age: Age | None = None,
    pregnancy: bool = False,
    include_cautions: bool = False,
    paramstyle: str = "qmark",
) -> ToolResult:
    """성분코드 목록 → 병용(모든 쌍)·임부·연령(·확장 주의) 판정 항목.

    - 입력이 비어 있으면 항목이 없다(`items == []`).
    - 형식이 맞지 않는 코드(None·빈 문자열·KIDS 형식 아님)는 `UNIDENTIFIED`(꼬리표 `INVALID_CODE`)이고,
      그 코드가 든 쌍은 판정하지 못했으므로 `NOT_LISTED`가 아니라 `UNIDENTIFIED`다(H2).
    - 사전(`DrugDict`) 후보의 `code_status`가 `none`(KIDS 코드 연결 없음)이면 호출자는 코드 없이 이 함수에 `None`을 넘기거나
      호출하지 않고, 결과를 `NOT_LISTED`가 아니라 `UNIDENTIFIED`로 다뤄야 한다(코드 없음 ≠ 금기 없음, BE-10-06).
      `component_only`는 성분 단위 연결이라 제품 단위 판정이 아니다. 상태 변환·문구는 AG-02 몫이며 여기서는 구현하지 않는다.
    - 같은 코드가 반복되면 한 번만 본다(성분 중복 표시는 AG-02 확장 몫).
    - 임부(`pregnancy=True`)·연령(`age` 지정)은 호출자가 프로필에서 정한다.
    """
    seen: list[str | None] = []
    for c in ingredient_codes:
        key = c.strip() if isinstance(c, str) else c
        if key not in seen:
            seen.append(key)

    items: list[Item] = []
    valid: list[str] = []
    invalid_positions: list[str] = []
    for c in seen:
        if isinstance(c, str) and is_valid_code(c):
            valid.append(c)
        else:
            raw = "" if c is None else str(c)
            items.append(Item("identify", UNIDENTIFIED, (raw,), f"identify:{raw}", None, None, ["INVALID_CODE"]))
            invalid_positions.append(raw)

    for a, b in combinations(valid, 2):
        items.append(lookup_pair(conn, a, b, paramstyle))
    # 식별 못 한 약이 든 쌍은 판정하지 못했다고 표시한다.
    for bad in invalid_positions:
        for good in valid:
            # 조회하지 않았으므로 출처·기준일을 달지 않는다(INVALID_CODE와 같다, BE-09-04 A).
            items.append(Item("contra_pair", UNIDENTIFIED, (good, bad), f"contra_pair:{good}:{bad}", None, None,
                              ["PAIR_NOT_CHECKED"]))

    for c in valid:
        if pregnancy:
            items.append(lookup_pregnancy(conn, c, paramstyle))
        if age is not None:
            items.append(lookup_age(conn, c, age, paramstyle))
        if include_cautions:
            for kind in _CAUTION_KINDS:
                items.append(lookup_caution(conn, c, kind, paramstyle))
    return ToolResult(items)
