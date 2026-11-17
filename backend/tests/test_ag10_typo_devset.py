"""AG-10 오탈자 보정의 개발셋 회귀(입구·Router 단계만, LLM·네트워크 호출 0). 개수와 문항 ID만 단언하고 문장·약 이름은 출력·복사하지 않는다.

시험셋(`*.SEALED.jsonl`)은 열지 않는다. 실사전(`data/mock/dict/drug_dict.json`)과 개발셋이 없으면 건너뛴다(둘 다 로컬 전용·고정 판).

수치(2026-11-18, 사전 be10-dict-s1-1055d3576876, 개발셋 150문항): 9.3절 오탈자 견고성의 **예상값이지 측정값이 아니다**(모델이 도는 실행이 아니다).
- 오탈자 20문항(오탈자 14·표기 3·축약 3): Router가 되묻지 않고 짝 정상 문항과 **같은 약으로 확정**한 문항이 보정 끔 3/20 → 켬 15/20
  (오탈자 12/14, 표기 3/3(원래 정규화로 확정), 축약 0/3(접두 일치는 AG-05-01 A로 되묻기 유지)).
- 보정했는데 짝과 다른 약으로 간 문항 0. 남은 5문항은 지금처럼 되묻기다.
- 오탈자가 아닌 130문항은 보정 켬/끔의 Router 결과가 완전히 같다(변화 0). 가상 약(근거 없음) 문항에서 보정된 엔티티 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import router as R
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict

DEV_SET = Path(__file__).resolve().parents[2] / "evaluation" / "eval_set" / "dev_set.jsonl"
EXPECTED_VERSION = "be10-dict-s1-1055d3576876"

pytestmark = pytest.mark.skipif(not (Path(DEFAULT_DICT_PATH).is_file() and DEV_SET.is_file()), reason="실사전 또는 개발셋 없음(로컬 전용)")


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    d = DrugDict.load()
    if d.version != EXPECTED_VERSION:
        pytest.skip(f"사전 판이 다르다({d.version}): 수치는 {EXPECTED_VERSION} 기준")
    return d


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _resolved(res: R.RouterResult) -> list[str]:
    """확정된 약의 키(품목기준코드, 없으면 정규화 이름). 허가번호 없는 목록 행·성분명 일치도 비교할 수 있게 한다."""
    return sorted(e.item_seq or e.normalized for e in res.entities if e.status == R.ST_RESOLVED)


def _typo_outcomes(dd: DrugDict, rows: list[dict], *, on: bool) -> dict[str, str]:
    by = {r["id"]: r for r in rows}
    out: dict[str, str] = {}
    for r in rows:
        if r.get("branch_label") != "오탈자":
            continue
        truth = _resolved(R.route_input(by[r["pair_of"]]["question"], dd))
        res = R.route_input(r["question"], dd, typo_correct=on)
        if res.ambiguous:
            out[r["id"]] = "clarify"
        elif truth and _resolved(res) == truth:
            out[r["id"]] = "same"
        else:
            out[r["id"]] = "other"
    return out


def test_typo_items_resolve_to_the_same_drug_as_their_pair(dd, rows):
    off, on = _typo_outcomes(dd, rows, on=False), _typo_outcomes(dd, rows, on=True)
    assert len(on) == 20
    assert sum(v == "same" for v in off.values()) == 3, off
    same = sorted(i for i, v in on.items() if v == "same")
    assert len(same) == 15, f"보정 뒤 짝과 같은 약으로 확정 {len(same)}/20: {same}"
    assert {i for i, v in off.items() if v == "same"} <= set(same)  # 원래 되던 문항이 깨지지 않는다


def test_no_typo_item_is_corrected_to_a_different_drug(dd, rows):
    on = _typo_outcomes(dd, rows, on=True)
    wrong = sorted(i for i, v in on.items() if v == "other")
    assert not wrong, f"짝과 다른 약으로 간 문항: {wrong}"
    assert sum(v == "clarify" for v in on.values()) == 5  # 나머지는 지금처럼 되묻기


def test_by_variant_counts(dd, rows):
    on = _typo_outcomes(dd, rows, on=True)
    by_variant: dict[str, list[int]] = {}
    for r in rows:
        if r["id"] in on:
            k, n = by_variant.setdefault(str(r.get("variant")), [0, 0])
            by_variant[str(r.get("variant"))] = [k + (on[r["id"]] == "same"), n + 1]
    assert by_variant == {"오탈자": [12, 14], "표기": [3, 3], "축약": [0, 3]}


def test_non_typo_items_route_exactly_as_before(dd, rows):
    others = [r for r in rows if r.get("branch_label") != "오탈자"]
    assert len(others) == 130
    changed = [r["id"] for r in others
               if R.route_input(r["question"], dd).model_dump() != R.route_input(r["question"], dd, typo_correct=True).model_dump()]
    assert not changed, f"보정 경로로 빠진 비오탈자 문항: {changed}"


def test_made_up_drug_items_are_never_corrected(dd, rows):
    fake = [r for r in rows if r.get("branch_label") == "근거 없음"]
    assert len(fake) == 20
    hit = [r["id"] for r in fake if any(e.corrected_from for e in R.route_input(r["question"], dd, typo_correct=True).entities)]
    assert not hit, f"가상 약이 실제 약으로 보정된 문항: {hit}"
