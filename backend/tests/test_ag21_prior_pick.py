"""AG-21 ①③④: 이전 차례에서 고른 약(`prior_drugs`)의 확인 되묻기, 시각 표현 잡음 규칙, 빈 입력 회귀. LLM·공공 API·원격 DB 호출 0.

- ① `confirmed_drugs`(이번 질문의 되묻기 답)는 지금처럼 바로 확정한다. `prior_drugs`(이전 차례)는 확정하지 않고, 같은 이름이 다시 나오면
  이전 선택을 첫 후보로 둔 확인 되묻기(승인 원문 `CLARIFY_PRIOR_PICK`, AG-21-04 A)로 끝난다(AG-21-01 A·02 A).
- ③ "15시" 같은 시각 표현은 약 이름 엔티티가 아니다.
- ④ `prior_drugs`가 비면 Router 결과·그래프 최종 상태가 바이트 단위로 같다. 이벤트에는 개수(`n_prior_asked`)만 남는다.
- 사전과 질문은 합성(`e2e/golden_synth.py`)이다. 평가 세트·시험셋 문항이 아니다. 시나리오는 로컬 조사 보고 `ctx-rca.md` §1.3의 q1→q2→q3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import Q_P3, SEQ_AZI, SEQ_COLD, SEQ_KID, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent.graph.build import build_graph, initial_state, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.state import NODE_WRITABLE  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.router import FLAG_PRIOR_PICK, FLAG_USER_CONFIRMED, ST_AMBIGUOUS, ST_RESOLVED, extract_mentions, route_input  # noqa: E402
from app.api.schemas import response_from_state  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
APPROVED = "앞에서 고른 '{drug}'을(를) 말씀하시는 건가요? 다른 약이면 아래에서 골라 주세요."  # AG-21-04 A 승인 원문

Q1 = "타이레놀이랑 이지렉트 같이 먹어도 되나요?"  # 두 이름 모두 모호(ctx-rca: 게보린 → 이지렉트로 바꾼 같은 모양)
Q3 = "타이레놀을 2정을 점심에 먹었는데 두통이 해결되지 않아 15시인데 먹어도 되니?"
Q3C = "타이레놀 500 점심에 먹었는데 또 먹어도 되니?"  # 함량 단서 500: 이전 선택(콜드-에스정)과 맞지 않음
Q3B = "타이레놀정500을 점심에 먹었는데 15시에 또 먹어도 되니?"


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _prior(input_name: str | None, item_seq: str, name: str = "표시 이름") -> dict[str, Any]:
    """요청 `context.prior_drugs` 원소 모양(3단계 BE가 그대로 넘긴다)."""
    d: dict[str, Any] = {"name": name, "item_seq": item_seq}
    if input_name is not None:
        d["input_name"] = input_name
    return d


def _pick(input_name: str, item_seq: str) -> dict[str, str]:
    return {"item_seq": item_seq, "input_name": input_name}


Q2_PICKS = [_pick("타이레놀", SEQ_COLD), _pick("이지렉트", SEQ_AZI)]  # q2 재전송의 confirmed_drugs
Q3_PRIORS = [_prior("타이레놀", SEQ_COLD, COLD), _prior("이지렉트", SEQ_AZI, AZI)]  # q3에서 이전 차례 선택으로 넘어오는 것


def _dump(res: Any) -> bytes:
    return json.dumps(res.model_dump(), ensure_ascii=False, sort_keys=True).encode()


# =========================================================================== 1. 고정 문구(AG-21-04 A)
class TestPhrase:
    def test_constant_is_approved_text_and_in_ticket(self):
        assert fp.CLARIFY_PRIOR_PICK == APPROVED and R.CLARIFY_PRIOR_PICK is fp.CLARIFY_PRIOR_PICK
        assert "CLARIFY_PRIOR_PICK" not in fp.DRAFT_KEYS
        assert APPROVED in (ROOT / "tickets" / "agent" / "AG-21.md").read_text(encoding="utf-8")

    def test_one_question_mark_no_verdict_no_internal_terms(self):
        s = fp.CLARIFY_PRIOR_PICK.format(drug=COLD)
        assert s.count("?") == 1 and "{drug}" in fp.CLARIFY_PRIOR_PICK
        for bad in ("먹어도", "괜찮", "안전", "금기", "mg", "밀리그램", "복용하세요"):
            assert bad not in fp.CLARIFY_PRIOR_PICK
        assert not any(term in fp.CLARIFY_PRIOR_PICK for term in fp.FORBIDDEN_SCREEN_TERMS)


# =========================================================================== 2. q1 → q2 → q3(ctx-rca §1.3)
class TestTurns:
    def test_q1_asks_both_names(self, dd):
        res = route_input(Q1, dd)
        assert res.ambiguous and [g.target_raw for g in res.clarify.groups] == ["타이레놀", "이지렉트"]

    def test_q2_resend_confirms_without_asking(self, dd):
        res = route_input(Q1, dd, confirmed_item_seqs=Q2_PICKS)
        assert [(e.raw, e.status, e.item_seq) for e in res.entities] == [("타이레놀", ST_RESOLVED, SEQ_COLD), ("이지렉트", ST_RESOLVED, SEQ_AZI)]
        assert all(FLAG_USER_CONFIRMED in e.flags for e in res.entities) and not res.ambiguous and res.clarify is None

    def test_q3_prior_only_ends_with_confirm_question(self, dd):
        base = route_input(Q3, dd)
        res = route_input(Q3, dd, prior_drugs=Q3_PRIORS)
        [e] = res.entities
        assert (e.raw, e.status, e.item_seq, e.resolved) == ("타이레놀", ST_AMBIGUOUS, None, False)  # prior로는 RESOLVED가 되지 않는다
        assert FLAG_PRIOR_PICK in e.flags and FLAG_USER_CONFIRMED not in e.flags
        assert [o.item_seq for o in e.options] == [SEQ_COLD, SEQ_T500]  # 이전 선택이 첫 후보, 나머지 사전 후보
        assert {o.item_seq for o in e.options} == {o.item_seq for o in base.entities[0].options} and e.n_candidates == base.entities[0].n_candidates
        assert res.ambiguous and res.branch_label == R.BRANCH_AMBIGUOUS
        assert res.clarify.question == APPROVED.format(drug=COLD) and res.clarify.question.count("?") == 1
        assert res.clarify.options == e.options and res.n_pairs == 0

    def test_q3_question_uses_dictionary_name_not_request_name(self, dd):
        res = route_input(Q3, dd, prior_drugs=[_prior("타이레놀", SEQ_COLD, "<script>다른 글자</script>")])
        assert res.clarify.question == APPROVED.format(drug=COLD)

    def test_confirmed_wins_over_prior(self, dd):
        """이번 질문의 되묻기 답(`confirmed_drugs`)이 있으면 지금처럼 바로 확정하고 확인 되묻기는 없다."""
        res = route_input(Q3, dd, confirmed_item_seqs=[_pick("타이레놀", SEQ_T500)], prior_drugs=Q3_PRIORS)
        [e] = res.entities
        assert (e.status, e.item_seq) == (ST_RESOLVED, SEQ_T500) and FLAG_PRIOR_PICK not in e.flags and res.clarify is None

    def test_q3c_strength_mismatch_does_not_put_prior_first(self, dd):
        res = route_input(Q3C, dd, prior_drugs=Q3_PRIORS)
        [e] = res.entities
        assert e.status == ST_AMBIGUOUS and FLAG_PRIOR_PICK not in e.flags
        assert [o.item_seq for o in e.options] == [SEQ_T500, SEQ_COLD]  # 함량이 맞는 후보가 앞, 이전 선택은 뒤(후보 집합은 그대로)
        assert res.clarify.question == fp.CLARIFY_MANY_CANDIDATES.format(drug="타이레놀")

    def test_strength_matching_prior_is_asked(self, dd):
        res = route_input(Q3C, dd, prior_drugs=[_prior("타이레놀", SEQ_T500, T500)])
        assert [o.item_seq for o in res.entities[0].options] == [SEQ_T500, SEQ_COLD]
        assert res.clarify.question == APPROVED.format(drug=T500)

    def test_dose_count_is_not_a_strength_hint(self, dd):
        """"타이레놀을 2정을"의 2는 개수라 함량 단서가 아니다(이전 선택을 그대로 첫 후보로)."""
        e = route_input(Q3, dd).entities[0]
        assert R.strength_hint(Q3, "타이레놀을", e) == ()
        assert R.strength_hint(Q3C, "타이레놀", route_input(Q3C, dd).entities[0]) == ("500",)


# =========================================================================== 3. 영향 범위
class TestScope:
    @pytest.mark.parametrize("q", [f"{AZI} 먹어도 되나요?", f"{T500} 먹어도 되나요?", "이지렉트 먹어도 되나요?", Q3B])
    def test_other_or_resolved_names_unaffected(self, dd, q):
        """이전 선택과 이름이 다른 약, 질문에 정식 제품명이 있어 이미 확정된 약은 결과가 같다."""
        assert _dump(route_input(q, dd, prior_drugs=[_prior("타이레놀", SEQ_COLD, COLD)])) == _dump(route_input(q, dd))

    def test_other_name_prior_is_not_applied(self, dd):
        """다른 묶음 이름으로 고른 코드는 이 이름의 후보에 들어 있어도 쓰지 않는다(FE-09-05 A와 같은 규칙)."""
        assert _dump(route_input(Q_P3, dd, prior_drugs=[_prior("콜드-에스", SEQ_COLD)]).entities[1]) == _dump(route_input(Q_P3, dd).entities[1])

    def test_non_candidate_or_bad_prior_ignored(self, dd):
        base = _dump(route_input(Q3, dd))
        for priors in ([_prior("타이레놀", SEQ_KID)], [_prior("타이레놀", "999999999")], [_prior("타이레놀", "12")], ["x", 7, None, {}]):
            assert _dump(route_input(Q3, dd, prior_drugs=priors)) == base

    def test_unnamed_prior_matches_by_candidate_set(self, dd):
        res = route_input(Q3, dd, prior_drugs=[_prior(None, SEQ_COLD)])
        assert FLAG_PRIOR_PICK in res.entities[0].flags and res.entities[0].options[0].item_seq == SEQ_COLD

    def test_two_names_both_prior_merge_into_one_multi_group_clarify(self, dd):
        res = route_input(Q1, dd, prior_drugs=Q3_PRIORS)
        assert [g.target_raw for g in res.clarify.groups] == ["타이레놀", "이지렉트"]
        assert [g.options[0].item_seq for g in res.clarify.groups] == [SEQ_COLD, SEQ_AZI]
        assert all(FLAG_PRIOR_PICK in e.flags and e.status != ST_RESOLVED for e in res.entities)
        assert res.clarify.question == fp.CLARIFY_MANY_DRUGS.format(drugs="'타이레놀', '이지렉트'")  # 묶음 2개: 기존 다묶음 문구 한 응답

    def test_prior_never_resolves_any_entity(self, dd):
        for q in (Q1, Q3, Q3C, Q_P3):
            base = {e.raw: e.status for e in route_input(q, dd).entities}
            got = {e.raw: e.status for e in route_input(q, dd, prior_drugs=Q3_PRIORS + [_prior(None, SEQ_T500)]).entities}
            assert got == base


# =========================================================================== 4. 빈 입력 회귀(바이트 단위)
@pytest.mark.parametrize("q", [Q1, Q3, Q3C, Q3B, Q_P3, f"{T500}이랑 {AZI} 같이 먹어도 되나요?", "가나다라정 먹어도 되나요?"])
@pytest.mark.parametrize("empty", [None, [], ()])
def test_empty_prior_router_bytes_identical(dd, q, empty):
    assert _dump(route_input(q, dd, prior_drugs=empty)) == _dump(route_input(q, dd))
    assert _dump(route_input(q, dd, confirmed_item_seqs=Q2_PICKS, prior_drugs=empty)) == _dump(route_input(q, dd, confirmed_item_seqs=Q2_PICKS))


def test_initial_state_has_no_prior_key_when_empty():
    assert initial_state("q", prior_drugs=None) == initial_state("q", prior_drugs=[]) == initial_state("q")
    assert initial_state("q", prior_drugs=Q3_PRIORS)["prior_drugs"] == Q3_PRIORS
    assert not any("prior_drugs" in keys for keys in NODE_WRITABLE.values())  # 입력 전용: 어느 노드도 쓰지 않는다


def _graph(dd: DrugDict) -> tuple[Any, ScriptedToolModel]:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm = ScriptedToolModel(script=[])  # 되묻기로 끝나므로 모델이 불리면 스크립트가 비어 실패한다
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary([]), system_prompt="시험용 시스템 프롬프트")
    return build_graph(deps), tm


def _state_bytes(st: dict[str, Any]) -> bytes:
    return json.dumps(st, ensure_ascii=False, sort_keys=True, default=str).encode()


@pytest.mark.parametrize("empty", [None, []])
def test_empty_prior_graph_output_bytes_identical(dd, empty):
    graph, _ = _graph(dd)
    for q in (Q1, Q3):
        assert _state_bytes(run_question(graph, q, prior_drugs=empty)) == _state_bytes(run_question(graph, q))


def test_graph_q3_ends_with_confirm_clarify_and_event_has_count_only(dd):
    graph, tm = _graph(dd)
    st = run_question(graph, Q3, prior_drugs=Q3_PRIORS)
    assert tm.calls == [] and st["end_reason"] == "CLARIFY" and st["answer"]["summary"] == APPROVED.format(drug=COLD)
    cands = response_from_state(st).candidates
    assert [(c.input_name, c.item_seq) for c in cands][0] == ("타이레놀", SEQ_COLD)
    ev = next(e for e in st["events"] if e.get("event") == "ROUTER")
    assert ev["n_prior_asked"] == 1 and set(ev) == {"rule", "event", "branch", "ambiguous", "n_entities", "n_prior_asked"}
    blob = json.dumps(st["events"], ensure_ascii=False, default=str)
    assert SEQ_COLD not in blob and SEQ_AZI not in blob and COLD not in blob  # 이벤트에 코드·이름 없음
    plain = run_question(graph, Q3)
    assert "n_prior_asked" not in next(e for e in plain["events"] if e.get("event") == "ROUTER")


def test_graph_q2_confirmed_with_prior_is_normal_route(dd):
    """q2(재전송): 고른 약이 `confirmed_drugs`로 오면 되묻기 없이 확정되고 모델로 간다(prior가 같이 와도 확인 되묻기 없음)."""
    res = route_input(Q1, dd, confirmed_item_seqs=Q2_PICKS, prior_drugs=Q3_PRIORS)
    assert not res.ambiguous and res.clarify is None and all(FLAG_PRIOR_PICK not in e.flags for e in res.entities)


# =========================================================================== 5. 시각 표현 잡음 규칙(③)
@pytest.mark.parametrize("tok", ["15시", "15시에", "15시인데", "3시반", "30분", "오후3시", "오후3시에", "15:30", "15:30에"])
def test_time_expressions_are_noise(dd, tok):
    assert R._is_noise(tok, dd) and R._is_noise(tok)


def test_q3b_no_time_entity_and_drug_kept(dd):
    assert extract_mentions(Q3B, dd) == ["타이레놀정500을"]
    assert [e.raw for e in route_input(Q3B, dd).entities] == ["타이레놀정500"]
    assert extract_mentions(Q3, dd) == ["타이레놀을"]


@pytest.mark.parametrize("q, names", [
    (f"{T500}이랑 {AZI} 같이 먹어도 되나요?", [T500, AZI]),
    ("타이레놀 500 mg 먹어도 되나요?", ["타이레놀"]),
    (Q_P3, ["이지렉트정", "타이레놀", "콜드-에스"]),
])
def test_existing_extraction_unchanged(dd, q, names):
    assert [e.raw for e in route_input(q, dd).entities] == names
