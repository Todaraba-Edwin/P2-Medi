"""AG-02 계약(실제 사전): 오탐 3건이 판정으로 가지 않음, 코드 없음 ≠ NOT_LISTED, 상비약 아세트아미노펜 점검(BE-10-09 후속).

`data/mock/dict/drug_dict.json`(로컬 전용, 고정 판 `be10-dict-s1-1055d3576876`)이 없으면 건너뛴다. DB는 로컬 KIDS 연령·임부 CSV만 메모리 SQLite에 적재한다(병용금기 540MB 제외, 외부 호출 없음).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))

from golden_synth import APAP, D_APAP, FORM_MAP, FakeDur, _ing, golden_conn  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.wiring import build_tool_context  # noqa: E402
from app.agent.tools import check_contraindications as cc  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.contract import check_items  # noqa: E402
from app.agent.tools.registry import invoke  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402
from app.db import loaders  # noqa: E402
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict  # noqa: E402

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
    """BE-10-09 후속·BE-10-10 C: 아세트아미노펜 복합 상비약은 '확인하지 못함'이다. NOT_LISTED가 아니다.

    BE-10-10 C 이후 이유가 바뀌었다: 아세트아미노펜 성분은 이제 같은 제형(정제·캡슐)의 KIDS 코드와 맞지만(REFERENCE_ONLY 아님),
    나머지 성분은 KIDS 단일 성분 항목이 없어 일부 성분만 조회할 수 있으므로 `CODE_NOT_LINKED`로 '목록에 없음'을 말하지 않는다.
    """
    out = check(real_ctx, name)
    assert {i["status"] for i in out["items"]} == {"UNIDENTIFIED"}
    assert all("CODE_NOT_LINKED" in i["flags"] for i in out["items"])
    assert any("일부 성분만" in n for i in out["items"] for n in i["notes"])


def test_acetaminophen_component_matches_tablet_and_capsule_codes(real_ctx):
    """BE-10-10 C: 아세트아미노펜이 든 정제·캡슐 복합 상비약에서 아세트아미노펜 성분은 같은 제형 KIDS 코드와 맞는다(`match`).

    KIDS 연령금기 목록에는 아세트아미노펜 산제(101305APD)·서방정(101430ATR) 코드만 있고 정제·캡슐 단일 코드는 용량주의 CSV에만 있다.
    사전이 그 코드를 알아 이전에는 `route_only`(REFERENCE_ONLY)였던 정제·캡슐이 `match`가 된다(연령 목록에 없는 제형이므로 이 성분은 NOT_LISTED 쪽).
    """
    d = real_ctx.drug_dict
    pop = [p for p in d.products if p.get("code_link") == "component_only" and "acetaminophen" in p.get("ingr_keys", []) and not p.get("cancelled")
           and (p.get("form") or {}).get("group") in ("정제", "캡슐")]
    assert len(pop) > 50
    for p in pop:
        cands = d.component_candidates(p["item_seq"])
        apap = [m for c in cands for m in c.component_matches if "acetaminophen" in m.label.lower()]
        assert apap and all(m.form_match == "match" and m.usable_codes for m in apap), p["name"]
        assert not any(x in ("101305APD", "101430ATR") for m in apap for x in m.usable_codes)  # 산제·서방정 코드가 정제·캡슐 판정에 쓰이지 않는다


def test_partial_component_coverage_never_not_listed(real_ctx):
    """파뚜루정: 일부 성분(제형이 맞는 코드)만 조회할 수 있으므로 연령은 NOT_LISTED가 아니라 '확인하지 못함'이다."""
    out = check(real_ctx, "파뚜루정")
    age = [i for i in out["items"] if i["kind"] == "age"]
    assert age and all(i["status"] != "NOT_LISTED" for i in age)
    assert all(i["status"] in ("FOUND", "UNIDENTIFIED") for i in out["items"])


def test_otc_acetaminophen_population_coverage_is_recorded(real_ctx):
    """상비약 점검 표본: 아세트아미노펜 포함 일반의약품 전체(취소 제외)에서 연령 질문(5세)이 '확인하지 못함'이 되는 비율을 센다.

    측정: 2026-11-10 사전 be10-dict-s1-b79de8c2755b 233/712 → BE-10-10 C 후 사전 be10-dict-s1-8fd48b13a657 225/712(0.316)
    → BE-10-12 A 후 사전 be10-dict-s1-c55339208584 234/712(0.329. 복합제 9건이 다른 제형 코드에만 연결돼 NOT_LISTED → UNIDENTIFIED). FOUND 113→45, NOT_LISTED 374→433.
    남은 225개는 모두 복합제로, 아세트아미노펜 외 성분(클로르페니라민·한약 추출물 등)에 KIDS 단일 성분 항목이 없어 일부 성분만 조회되는 경우다.
    값이 크게 달라지면(사전 갱신) 이 시험이 알려 준다.
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
    assert 0.22 <= unconfirmed / n <= 0.40, f"{unconfirmed}/{n}"  # 기대 구간(측정 0.316): 벗어나면 사전·규칙이 바뀐 것


def test_single_acetaminophen_all_forms_products_use_matching_form_codes_only(real_ctx):
    """BE-10-12 A: 성분 이름으로 이은 단일 아세트아미노펜 정제·시럽·캡슐은 서방정·산제 규칙을 끌어오지 않는다.

    측정(2026-11-11, 사전 be10-dict-s1-c55339208584, 연령 5세, n=100 단일 성분 일반의약품): 정제 40·시럽 19·캡슐 8·현탁액 1이 FOUND → NOT_LISTED.
    근거 코드는 용량주의 CSV의 같은 제형 단일 코드(정제 ATB 6개·시럽 ASY 5개·캡슐 ACS 1개·현탁액 ASS 3개)이며 연령금기 목록에는 없다.
    """
    d = real_ctx.drug_dict
    single = [p for p in d.products if p.get("ingr_keys") == ["acetaminophen"] and p.get("prescription") == "일반" and not p.get("cancelled")]
    assert len(single) == 100
    seen = 0
    for p in single:
        if p.get("code_link") != "ingredient_name":
            continue
        grp = (p.get("form") or {}).get("group")
        out = invoke("check_contraindications", {"drugs": [{"item_seq": p["item_seq"]}], "age": {"value": 5, "unit": "세"}}, real_ctx)
        st = {i["status"] for i in out["items"] if i["kind"] == "age"}
        if grp in ("정제", "시럽", "캡슐", "현탁액"):
            assert st == {"NOT_LISTED"}, p["name"]
            seen += 1
        elif grp in ("산제·분말", "서방정"):
            assert st == {"FOUND"}, p["name"]  # 제형이 맞는 코드가 있어 유지
    assert seen == 68


def test_product_code_linked_acetaminophen_unchanged(real_ctx):
    """BE-10-12 A: 제품 코드 연결(edi_code·product_name) 단일 아세트아미노펜 서방정·산제 23건은 결과가 그대로 FOUND다."""
    d = real_ctx.drug_dict
    pop = [p for p in d.products if p.get("ingr_keys") == ["acetaminophen"] and p.get("prescription") == "일반" and not p.get("cancelled")
           and p.get("code_link") in ("edi_code", "product_name")]
    assert len(pop) == 23
    for p in pop:
        out = invoke("check_contraindications", {"drugs": [{"item_seq": p["item_seq"]}], "age": {"value": 5, "unit": "세"}}, real_ctx)
        assert {i["status"] for i in out["items"] if i["kind"] == "age"} == {"FOUND"}, p["name"]


def test_kids_row_fold_preserves_code_union_on_real_dict(real_ctx):
    """BE-10-13 A: 허가 행 1개로 접힌 KIDS 함량 행의 코드는 합집합으로 모두 남는다(접기 전 코드 집합과 비교). 오탐 3건은 접기와 무관하게 UNIDENTIFIED."""
    from app.tools.drug_dict import normalize_name

    d = real_ctx.drug_dict
    groups: dict[str, list[dict]] = {}
    for p in d.products:
        groups.setdefault(normalize_name(p["name"]), []).append(p)
    checked = folded = 0
    for rows in groups.values():
        permits = [p for p in rows if p.get("item_seq")]
        kids = [p for p in rows if not p.get("item_seq") and p["name"].rstrip().endswith(")") and "_(" in p["name"]]
        if len(permits) != 1 or not kids:
            continue
        before = set(permits[0].get("kids_codes", [])).union(*(set(k.get("kids_codes", [])) for k in kids))
        r = d.lookup_name(permits[0]["name"])
        reps = [c for c in r.candidates if c.item_seq == permits[0]["item_seq"]]
        assert reps and before <= set(reps[0].kids_codes), permits[0]["name"]
        checked += 1
        folded += r.resolved
    assert checked > 3000 and folded / checked > 0.9


# --------------------------------------------------------------------------- 쌍의 DUR API 코드(레인 D, 2026-11-17)
IBU = "172802ATB"  # KIDS 코드(합성)


def _pair_dict(ibu_api: list[str]) -> DrugDict:
    ings = [_ing(0, "Acetaminophen", "아세트아미노펜", [APAP], [D_APAP]), _ing(1, "Ibuprofen", "이부프로펜", [IBU], ibu_api)]
    return DrugDict({"meta": {"version": "lane-d-synth", "built_at": "2026-11-17T00:00:00+00:00", "form_map": FORM_MAP}, "products": [], "ingredients": ings})


def _pair(fd: FakeDur, d: DrugDict):
    ctx = build_tool_context(d, mode="service", dur_client=fd, conn_factory=golden_conn)
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": "아세트아미노펜"}, {"name": "이부프로펜"}]), ctx)
    assert check_items("check_contraindications", out["items"]) == []
    return out["items"], next(i for i in out["items"] if i["kind"] == "contra_pair")


def test_missing_api_code_marks_pair_incomplete_without_any_call():
    """한쪽 성분의 DUR API 코드가 사전에 없으면 호출 0회인데도 `API_PAIR_INCOMPLETE`·`NOTICE_API_FAIL`이 붙는다(현황 고정, 합성 사전)."""
    fd = FakeDur()
    items, it = _pair(fd, _pair_dict([]))
    assert it["status"] == "NOT_LISTED" and "API_PAIR_INCOMPLETE" in it["flags"]
    assert it["api"] == {"outcome": "API_UNAVAILABLE"} and fd.calls == []  # 조회가 "빠진" 게 아니라 시도하지 않았다
    assert finalize(items)["notice"] == fp.NOTICE_API_FAIL


def test_with_api_code_pair_is_queried_once():
    fd = FakeDur()
    items, it = _pair(fd, _pair_dict(["D000999"]))
    assert "API_SAME" in it["flags"] and len(fd.calls) == 1 and finalize(items)["notice"] is None


def test_real_dict_ibuprofen_has_api_code(real_ctx):
    """고정 판 사전에서 이부프로펜 성분에 DUR API 코드가 있다(없으면 상비약 쌍마다 위 '실시간 확인 못 함'이 붙는다)."""
    assert real_ctx.drug_dict.lookup_name("이부프로펜").candidates[0].api_codes != ()
