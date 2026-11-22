"""AG-15(축소) 약 이름 없는 질문 분기의 개발셋 회귀(입구·Router 단계만, LLM·네트워크 호출 0). 개수와 문항 ID만 단언하고 문장·약 이름은 출력·복사하지 않는다.

시험셋(`*.SEALED.jsonl`)은 열지 않는다. 실사전(`data/mock/dict/drug_dict.json`)과 개발셋이 없으면 건너뛴다(둘 다 로컬 전용·고정 판).

수치(2026-11-22, 사전 be10-dict-s1-1055d3576876, 개발셋 150문항): 입구 거절 16(그래프에서 Router에 오지 않는다), 입구 통과 134는 모두 엔티티 1개 이상,
**입구를 통과했는데 엔티티 0개인 문항 0** → 새 분기(`open_lookup` → finalize)로 가는 문항 0/150, Router `state_update()` 키 집합이 변경 전(`ROUTER_WRITABLE_KEYS`)과
같은 문항 150/150, `after_router` 결과가 변경 전 규칙(되묻기만 finalize)과 같은 문항 150/150. 예상값이지 모델이 도는 측정값이 아니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import guardrail as G
from app.agent import router as R
from app.agent.graph.nodes import after_router
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
def routed(dd) -> list[tuple[str, dict, R.RouterResult]]:
    rows = [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for r in rows:
        q = r.get("question") or ""
        g = G.guardrail_in(q)
        out.append((r["id"], g, R.route_input(q, dd, emergency=g["emergency"], guardrail_route=g["route"])))
    return out


def _reaches_router(g: dict) -> bool:
    return not (g["route"] == G.ROUTE_REFUSE and not g["proceed_tools"])  # `after_guardrail`와 같은 규칙


def test_devset_counts(routed):
    assert len(routed) == 150
    refused = [i for i, g, _ in routed if not _reaches_router(g)]
    zero = [i for i, g, res in routed if _reaches_router(g) and not res.entities]
    assert len(refused) == 16 and zero == []


def test_no_devset_item_takes_the_open_branch(routed):
    hit = [i for i, _, res in routed if res.open_lookup is not None]
    assert hit == [], f"open_lookup이 생긴 문항: {hit}"


def test_router_state_keys_unchanged_150(routed):
    changed = [i for i, _, res in routed if set(res.state_update()) != R.ROUTER_WRITABLE_KEYS]
    assert changed == [], f"Router 출력 키가 바뀐 문항: {changed}"


def test_after_router_unchanged_150(routed):
    """변경 전 규칙은 `"finalize" if ambiguous else "model"`이었다."""
    diff = [i for i, _, res in routed
            if after_router(res.state_update()) != ("finalize" if res.ambiguous else "model")]  # type: ignore[arg-type]
    assert diff == [], f"간선이 바뀐 문항: {diff}"
