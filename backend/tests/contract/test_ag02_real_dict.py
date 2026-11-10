"""AG-02 계약(실제 사전): 오탐 3건이 판정으로 가지 않음, 코드 없음 ≠ NOT_LISTED, 상비약 아세트아미노펜 점검(BE-10-09 후속).

`data/mock/dict/drug_dict.json`(로컬 전용)이 없으면 건너뛴다. DB는 로컬 KIDS 연령·임부 CSV만 메모리 SQLite에 적재한다(병용금기 540MB 제외, 외부 호출 없음).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.agent.tools.context import ToolContext
from app.agent.tools.registry import invoke
from app.db import loaders
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict

DATA = Path(__file__).resolve().parents[3] / "data"
AGE_CSV = DATA / "한국의약품안전관리원_연령금기_20260721.csv"
PREG_CSV = DATA / "한국의약품안전관리원_임부금기약물_20260721.csv"

pytestmark = pytest.mark.skipif(not Path(DEFAULT_DICT_PATH).is_file(), reason="data/mock/dict/drug_dict.json 없음(로컬 전용)")


class _KeepOpen:
    def __init__(self, c: sqlite3.Connection) -> None:
        self._c = c

    def cursor(self):
        return self._c.cursor()

    def close(self) -> None:  # 공유 연결을 도구가 닫지 못하게 한다
        pass


@pytest.fixture(scope="module")
def real_ctx():
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    parts = {}
    if AGE_CSV.is_file():
        parts["a"] = loaders.read_source(AGE_CSV, loaders.normalize_age, "age_contra", loaders.AS_OF_KIDS)
    if PREG_CSV.is_file():
        parts["p"] = loaders.read_source(PREG_CSV, loaders.normalize_pregnancy, "pregnancy_contra", loaders.AS_OF_KIDS)
    loaders.load_into(c, parts)
    return ToolContext(DrugDict.load(), conn_factory=lambda: _KeepOpen(c), api_enabled=False)


def check(ctx, name, **kw):
    out = invoke("check_contraindications", {"drugs": [{"name": name}], "age": {"value": 5, "unit": "세"}, "pregnancy": True, **kw}, ctx)
    assert "error" not in out and out["contract_violations"] == []
    return out


@pytest.mark.parametrize("name", ["미네서플라이정", "비에스에스플러스액", "크리쿨산"])
def test_false_positive_trio_never_reaches_found(real_ctx, name):
    out = check(real_ctx, name)
    assert out["items"] and {i["status"] for i in out["items"]} == {"UNIDENTIFIED"}
    assert all("CODE_NOT_LINKED" in i["flags"] for i in out["items"])
    assert not any(i["matches"] for i in out["items"])


@pytest.mark.parametrize("name", ["래피콜에이캡슐", "휴펜정"])
def test_common_cold_capsule_type_is_unconfirmed_not_not_listed(real_ctx, name):
    """BE-10-09 후속: 아세트아미노펜 복합 상비약(제형이 코드와 다른 route_only)은 '확인하지 못함'이다. NOT_LISTED가 아니다."""
    out = check(real_ctx, name)
    assert {i["status"] for i in out["items"]} == {"UNIDENTIFIED"}
    assert any("REFERENCE_ONLY" in i["flags"] for i in out["items"])
    assert any("이 제품 판정 아님" in n for i in out["items"] for n in i["notes"])


def test_partial_component_coverage_never_not_listed(real_ctx):
    """파뚜루정: 일부 성분(제형이 맞는 코드)만 조회할 수 있으므로 연령은 NOT_LISTED가 아니라 '확인하지 못함'이다."""
    out = check(real_ctx, "파뚜루정")
    age = [i for i in out["items"] if i["kind"] == "age"]
    assert age and all(i["status"] != "NOT_LISTED" for i in age)
    assert all(i["status"] in ("FOUND", "UNIDENTIFIED") for i in out["items"])


def test_otc_acetaminophen_population_coverage_is_recorded(real_ctx):
    """상비약 점검 표본: 아세트아미노펜 포함 일반의약품 전체(취소 제외)에서 연령 질문(5세)이 '확인하지 못함'이 되는 비율을 센다.

    측정 시점(2026-11-10, 사전 be10-dict-s1-b79de8c2755b): 233/712. 값이 크게 달라지면(사전 갱신) 이 시험이 알려 준다.
    """
    d = real_ctx.drug_dict
    pop = [p for p in d.products if "acetaminophen" in p.get("ingr_keys", []) and p.get("prescription") == "일반" and not p.get("cancelled")]
    unconfirmed = 0
    for p in pop:
        out = invoke("check_contraindications", {"drugs": [{"item_seq": p["item_seq"]}], "age": {"value": 5, "unit": "세"}}, real_ctx)
        ages = [i for i in out["items"] if i["kind"] == "age"]
        statuses = {i["status"] for i in ages}
        assert statuses, p["name"]
        assert statuses <= {"FOUND", "NOT_LISTED", "UNIDENTIFIED"}
        unconfirmed += statuses == {"UNIDENTIFIED"}
    n = len(pop)
    assert n > 100
    assert 0.2 <= unconfirmed / n <= 0.45, f"{unconfirmed}/{n}"  # 기대 구간(측정 0.327): 벗어나면 사전·규칙이 바뀐 것
