"""FE-09: 모호한 약 이름 여러 개를 한 응답에 묶어 되묻기(FE-09-01 A·02 A, 응답·요청 계약 불변). LLM·공공 API·원격 DB 호출 0.

- 묶음 2개 이상: 질문은 승인 원문 `CLARIFY_MANY_DRUGS` 하나(물음표 1개), 후보는 묶음마다 `input_name`을 찍어 펼친다.
- 묶음 1개: 질문·`target_raw`·`options`·`pending_raws`와 `/chat` 응답 JSON이 FE-09 이전과 바이트 단위로 같다(아래 `_legacy_clarify`가 이전 코드 사본).
- 세 경로(ReAct 그래프·AG-16 C1 파이프라인·LLM 분류 병합)가 같은 `router.assemble`을 써서 같은 묶음을 낸다.
- 사전과 질문은 합성(`e2e/golden_synth.py`, 각 시험의 소사전)이다. 평가 세트·시험셋 문항이 아니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402
from golden_synth import Q_P3, SEQ_AZI, SEQ_COLD, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent import router_classify as C  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.build import build_graph  # noqa: E402
from app.agent.graph.build import run_question as run_react  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.nodes import GraphDeps  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.pipeline.build import build_pipeline  # noqa: E402
from app.agent.pipeline.build import run_question as run_c1  # noqa: E402
from app.agent.router import ST_AMBIGUOUS, ST_NOT_FOUND, ST_RESOLVED, ST_TYPO, Clarify, Entity, route_input  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.langchain_adapter import build_tools  # noqa: E402
from app.agent.tools.registry import REGISTRY  # noqa: E402
from app.api.schemas import response_from_state, to_chat_response  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

AZI = "이지렉트정1.0밀리그램"
Q_TWO = "타이레놀이랑 이지렉트 같이 먹어도 되나요?"  # 두 이름 모두 모호(접두 일치): 타이레놀 후보 2개, 이지렉트 후보 1개
Q_ONE = f"타이레놀이랑 {AZI} 같이 먹어도 되나요?"  # 타이레놀만 모호
APPROVED_TWO = "'타이레놀', '이지렉트'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?"  # FE-09-02 A 승인 원문에 이름을 넣은 글자


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _q_count(s: str) -> int:
    return s.count("?")  # `evaluation/eval_metrics.py` ONE_QUESTION과 같은 정의(요약의 "?" 개수)


# --------------------------------------------------------------------------- FE-09 이전 `_clarify` 사본(단일 묶음 불변 비교용, 고치지 않는다)
def _legacy_clarify(ents: list[Entity]) -> dict[str, Any] | None:
    pending = [e for e in ents if e.status in (ST_AMBIGUOUS, ST_TYPO) or (e.status == ST_NOT_FOUND and e.options)]
    if not pending:
        return None
    t = pending[0]
    if t.status == ST_NOT_FOUND:
        q = f"'{t.raw}'은(는) 목록에서 찾지 못했어요. 혹시 아래 중에 찾으시는 약이 있나요? 없으면 약 이름을 다시 알려 주세요."
    elif t.status == ST_TYPO:
        q = f"'{t.raw}'와(과) 비슷한 약이 있어요. 찾으시는 약이 아래 중에 있나요? 하나를 골라 주세요."
    elif t.n_candidates <= 1 and len(t.options) == 1:
        q = fp.CLARIFY_ONE_CANDIDATE.format(drug=t.raw)
    else:
        q = fp.CLARIFY_MANY_CANDIDATES.format(drug=t.raw)
    return {"question": q, "target_raw": t.raw, "options": [o.model_dump() for o in t.options[:R.MAX_CLARIFY_OPTIONS]],
            "pending_raws": [e.raw for e in pending[1:]]}


def _response_bytes(clarify: dict[str, Any] | None) -> bytes:
    raw = finalize([], model_summary=(clarify or {}).get("question"), emergency=False)
    return json.dumps(to_chat_response(raw, end_reason="CLARIFY", clarify=clarify).model_dump(mode="json"), ensure_ascii=False).encode()


def _groups(candidates: list[Any]) -> list[str]:
    return list(dict.fromkeys(c.input_name for c in candidates))


def _pick(input_name: str, item_seq: str) -> dict[str, str]:
    """그래프 입력 `confirmed_item_seqs`의 이름 있는 원소(`runner.confirmed_from_context`가 만드는 모양, FE-09-05 A)."""
    return {"item_seq": item_seq, "input_name": input_name}


# =========================================================================== 1. 고정 문구(FE-09-02 A)
class TestPhrase:
    def test_approved_text_for_two_and_three_names(self):
        fill = lambda *names: fp.CLARIFY_MANY_DRUGS.format(drugs=fp.CLARIFY_MANY_DRUGS_SEP.join(f"'{n}'" for n in names))  # noqa: E731
        assert fill("타이레놀", "이지렉트") == APPROVED_TWO
        assert fill("가", "나", "다") == "'가', '나', '다'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?"
        assert R.CLARIFY_MANY_DRUGS is fp.CLARIFY_MANY_DRUGS and "CLARIFY_MANY_DRUGS" not in fp.DRAFT_KEYS

    def test_phrase_has_one_question_mark_and_no_verdict(self):
        s = fp.CLARIFY_MANY_DRUGS
        assert _q_count(s) == 1 and "{drugs}" in s
        for bad in ("먹어도", "괜찮", "안전", "금기", "mg", "밀리그램", "복용하세요"):
            assert bad not in s
        assert not any(term in s for term in fp.FORBIDDEN_SCREEN_TERMS)


# =========================================================================== 2. Router 묶음
class TestRouterGroups:
    def test_two_ambiguous_names_make_two_groups_with_one_question(self, dd):
        res = route_input(Q_TWO, dd)
        c = res.clarify
        assert res.ambiguous and res.branch_label == R.BRANCH_AMBIGUOUS and c is not None
        assert [g.target_raw for g in c.groups] == ["타이레놀", "이지렉트"]
        assert {o.item_seq for o in c.groups[0].options} == {SEQ_T500, SEQ_COLD} and [o.item_seq for o in c.groups[1].options] == [SEQ_AZI]
        assert c.question == APPROVED_TWO and _q_count(c.question) == 1
        # 하위 호환: 첫 묶음 그대로(평가 러너 `clarify_options = len(options)`), 미룬 이름 없음
        assert c.target_raw == "타이레놀" and c.options == c.groups[0].options and c.pending_raws == []

    @pytest.mark.parametrize("q", [Q_ONE, "타이레놀 먹어도 되나요?", "이지랙트정 먹어도 되나요?", "이지렉트 먹어도 되나요?",
                                   "엄마가 이지렉트정을 드시는데 감기예요"])
    def test_single_group_is_byte_identical_to_before(self, dd, q):
        res = route_input(q, dd)
        legacy = _legacy_clarify(res.entities)
        assert legacy is not None and res.clarify is not None and len(res.clarify.groups) == 1
        new = res.clarify.model_dump()
        assert {k: v for k, v in new.items() if k != "groups"} == legacy
        assert new["groups"] == [{"target_raw": legacy["target_raw"], "options": legacy["options"]}]
        assert _response_bytes(new) == _response_bytes(legacy)  # `/chat` 응답 JSON도 같다(`groups`는 응답 칸이 아니다)

    def test_no_ambiguous_name_means_no_clarify(self, dd):
        assert route_input(f"{AZI} 먹어도 되나요?", dd).clarify is None

    def test_groups_are_capped_by_max_drugs_and_options_by_max_clarify_options(self):
        opt = R.ClarifyOption(name="x", item_seq="000000001", matched_by="product_name", score=0.9)
        ents = [Entity(raw=f"약{i}", normalized=f"약{i}", status=ST_AMBIGUOUS, branch=R.BRANCH_AMBIGUOUS, n_candidates=9, options=[opt] * 9)
                for i in range(R.MAX_DRUGS + 2)]
        c = R._clarify(ents)
        assert len(c.groups) == R.MAX_DRUGS and all(len(g.options) == R.MAX_CLARIFY_OPTIONS for g in c.groups)
        assert c.pending_raws == [f"약{i}" for i in range(R.MAX_DRUGS, R.MAX_DRUGS + 2)]  # 상한을 넘은 것만(route_input에서는 엔티티가 이미 잘려 늘 빈 목록)
        assert _q_count(c.question) == 1

    def test_resolved_entities_are_not_grouped(self, dd):
        c = route_input(Q_ONE, dd).clarify
        assert [g.target_raw for g in c.groups] == ["타이레놀"]


# =========================================================================== 3. 응답 변환(`_candidates`, 계약 불변)
class TestResponse:
    def test_two_groups_are_flattened_with_input_name_per_group(self, dd):
        clar = route_input(Q_TWO, dd).clarify.model_dump()
        raw = finalize([], model_summary=clar["question"], emergency=False)
        r = to_chat_response(raw, end_reason="CLARIFY", clarify=clar)
        assert _groups(r.candidates) == ["타이레놀", "이지렉트"]
        assert [(c.input_name, c.item_seq) for c in r.candidates if c.input_name == "이지렉트"] == [("이지렉트", SEQ_AZI)]
        assert {c.item_seq for c in r.candidates if c.input_name == "타이레놀"} == {SEQ_T500, SEQ_COLD}
        assert r.summary == APPROVED_TWO and r.candidates_line == fp.CLARIFY_PICK_LINE

    def test_legacy_shape_without_groups_still_works(self):
        clar = {"target_raw": "타이레놀", "options": [{"name": "타이레놀정500밀리그람"}, {"name": "타이레놀콜드-에스정"}]}
        r = to_chat_response(finalize([], model_summary="q", emergency=False), end_reason="CLARIFY", clarify=clar)
        assert [(c.input_name, c.name) for c in r.candidates] == [("타이레놀", "타이레놀정500밀리그람"), ("타이레놀", "타이레놀콜드-에스정")]

    def test_candidates_only_on_clarify(self, dd):
        clar = route_input(Q_TWO, dd).clarify.model_dump()
        assert to_chat_response(finalize([], model_summary="q", emergency=False), end_reason="NORMAL", clarify=clar).candidates == []


# =========================================================================== 4. 두 묶음을 한 번에 고르기(요청 계약 불변)
class TestConfirmBoth:
    def test_both_groups_confirmed_in_one_request(self, dd):
        res = route_input(Q_TWO, dd, confirmed_item_seqs=[SEQ_T500, SEQ_AZI])
        assert [(e.raw, e.status, e.item_seq) for e in res.entities] == [("타이레놀", ST_RESOLVED, SEQ_T500), ("이지렉트", ST_RESOLVED, SEQ_AZI)]
        assert not res.ambiguous and res.clarify is None and res.n_pairs == 1

    def test_one_of_two_confirmed_leaves_one_group(self, dd):
        c = route_input(Q_TWO, dd, confirmed_item_seqs=[SEQ_AZI]).clarify
        assert [g.target_raw for g in c.groups] == ["타이레놀"]
        assert c.question == fp.CLARIFY_MANY_CANDIDATES.format(drug="타이레놀")  # 묶음 1개로 줄면 이전 문구

    @pytest.mark.parametrize("order", [(0, 1, 2), (0, 2, 1), (2, 1, 0), (1, 0, 2)])
    def test_overlapping_groups_keep_each_pick(self, dd, order):
        """FE-09-05 A: 묶음 이름(`input_name`)을 실어 보내면 두 묶음의 후보가 겹쳐도(Q_P3의 '타이레놀'·'콜드-에스') 보낸 순서와 상관없이 세 약을 모두 유지한다."""
        picks = [_pick("이지렉트정", SEQ_AZI), _pick("타이레놀", SEQ_T500), _pick("콜드-에스", SEQ_COLD)]
        res = route_input(Q_P3, dd, confirmed_item_seqs=[picks[i] for i in order])
        assert [(e.raw, e.status, e.item_seq) for e in res.entities] == [
            ("이지렉트정", ST_RESOLVED, SEQ_AZI), ("타이레놀", ST_RESOLVED, SEQ_T500), ("콜드-에스", ST_RESOLVED, SEQ_COLD)]
        assert not res.ambiguous and res.n_pairs == 3

    def test_without_names_old_rule_is_unchanged(self, dd):
        """이름 없는 요청은 이전 규칙(후보 집합 포함 + 나중 것) 그대로다: 묶음 순서로 보내면 겹친 묶음에서 한 약이 빠지는 이전 결과도 같다."""
        res = route_input(Q_P3, dd, confirmed_item_seqs=[SEQ_AZI, SEQ_T500, SEQ_COLD])
        assert [(e.raw, e.item_seq) for e in res.entities] == [("이지렉트정", SEQ_AZI), ("타이레놀", SEQ_COLD)]
        res2 = route_input(Q_P3, dd, confirmed_item_seqs=[SEQ_AZI, SEQ_COLD, SEQ_T500])
        assert [(e.raw, e.item_seq) for e in res2.entities] == [("이지렉트정", SEQ_AZI), ("타이레놀", SEQ_T500), ("콜드-에스", SEQ_COLD)]

    def test_named_pick_is_not_applied_to_other_name(self, dd):
        """다른 묶음 이름으로 고른 코드는 이 이름의 후보에 들어 있어도 쓰지 않는다(콜드-에스로 고른 COLD가 '타이레놀'을 확정하지 않는다)."""
        res = route_input(Q_P3, dd, confirmed_item_seqs=[_pick("콜드-에스", SEQ_COLD)])
        st = {e.raw: (e.status, e.item_seq) for e in res.entities}
        assert st["콜드-에스"] == (ST_RESOLVED, SEQ_COLD) and st["타이레놀"] == (ST_AMBIGUOUS, None)
        assert res.ambiguous and [g.target_raw for g in res.clarify.groups] == ["이지렉트정", "타이레놀"]

    def test_unknown_name_or_non_candidate_code_is_ignored(self, dd):
        base = route_input(Q_P3, dd).model_dump()
        assert route_input(Q_P3, dd, confirmed_item_seqs=[_pick("질문에없는이름", SEQ_AZI)]).model_dump() == base
        assert route_input(Q_P3, dd, confirmed_item_seqs=[_pick("이지렉트정", SEQ_T500)]).model_dump() == base  # 그 이름의 후보가 아님

    def test_named_pick_wins_over_unnamed_for_same_entity(self, dd):
        res = route_input(Q_TWO, dd, confirmed_item_seqs=[_pick("타이레놀", SEQ_T500), SEQ_COLD])
        assert res.entities[0].item_seq == SEQ_T500  # 이름 없는 나중 것(COLD)보다 그 이름으로 고른 것이 먼저

    def test_blank_name_counts_as_unnamed_and_bad_values_are_dropped(self):
        assert R.confirmed_picks([_pick("  ", SEQ_AZI), SEQ_AZI, {"item_seq": "12", "input_name": "x"}, {"input_name": "x"}, 7, None,
                                  _pick("타이레놀", SEQ_T500), _pick("타이레놀", SEQ_T500)]) == [(None, SEQ_AZI), ("타이레놀", SEQ_T500)]
        assert R.confirmed_seqs([_pick("타이레놀", SEQ_T500), SEQ_T500, SEQ_AZI]) == [SEQ_T500, SEQ_AZI]


# =========================================================================== 5. 세 경로가 같은 묶음을 낸다
def _react_state(dd: DrugDict, q: str) -> dict[str, Any]:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm = ScriptedToolModel(script=[])  # 되묻기로 끝나므로 모델이 불리면 스크립트가 비어 실패한다
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary([]), system_prompt="시험용 시스템 프롬프트")
    st = run_react(build_graph(deps), q)
    assert tm.calls == []
    return st


def _c1_state(dd: DrugDict, q: str) -> dict[str, Any]:
    ctx = ToolContext(drug_dict=dd)
    tm = ScriptedToolModel(script=[])
    deps = GraphDeps(drug_dict=dd, tool_model=tm, summary_model=ScriptedSummary([]), tools=build_tools(ctx, REGISTRY), tool_ctx=ctx,
                     system_prompt="시험용 시스템 프롬프트", registry=REGISTRY)
    st = run_c1(build_pipeline(deps), q)
    assert tm.calls == []
    return st


@pytest.mark.parametrize("runner", [_react_state, _c1_state], ids=["react", "c1"])
def test_graph_paths_end_with_two_group_clarify(dd, runner):
    st = runner(dd, Q_TWO)
    assert st["end_reason"] == "CLARIFY" and st["answer"]["summary"] == APPROVED_TWO
    assert st["clarify"] == route_input(Q_TWO, dd).clarify.model_dump()
    assert _groups(response_from_state(st).candidates) == ["타이레놀", "이지렉트"]


@pytest.mark.parametrize("runner", [_react_state, _c1_state], ids=["react", "c1"])
def test_graph_paths_single_group_response_unchanged(dd, runner):
    st = runner(dd, Q_ONE)
    legacy = _legacy_clarify([Entity.model_validate(e) for e in st["entities"]])
    assert st["answer"]["summary"] == legacy["question"]
    assert response_from_state(st) == response_from_state({**st, "clarify": legacy})


class _FakeClassifier:
    def __init__(self, mentions: list[str]):
        self.out = {"drug_mentions": mentions, "conditions": [], "age_years": None, "pregnancy": "unknown", "intent": ["contraindication"],
                    "needed_claims": []}

    def __call__(self, messages: list[dict[str, str]]) -> Any:
        return self.out


def test_classifier_merge_path_uses_same_groups(dd):
    o = C.route_with_classifier(Q_TWO, dd, None, call=_FakeClassifier(["타이레놀", "이지렉트"]), enabled=True, prompt="가짜 프롬프트")
    assert o.used and o.removed == []
    assert o.result.clarify == route_input(Q_TWO, dd).clarify and o.result.clarify.question == APPROVED_TWO


def test_classifier_removing_one_noise_name_falls_back_to_single_group():
    """LLM이 한 이름을 약이 아니라고 보면(규칙 엔티티 제거) 남은 묶음 1개로 다시 조립되고 질문은 이전 문구다."""
    def _p(seq: str, name: str) -> dict:
        return {"item_seq": seq, "item_name": name, "entp_name": "가상사", "spclty_pblc": "일반의약품", "item_ingr_name": "Delta", "edi_code": "",
                "cancel_name": "정상"}
    snaps = {"prmsn": [_p("302000003", "보라정에이"), _p("302000004", "보라정비"), _p("302000007", "배가나정"), _p("302000008", "배가다정")],
             "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {}}
    small = DrugDict(build_dictionary([], [], snaps, {"x": "y"})[0])
    q = "배가 아픈데 보라를 먹어도 되나요"
    assert [g.target_raw for g in route_input(q, small).clarify.groups] == ["배가", "보라"]
    o = C.route_with_classifier(q, small, None, call=_FakeClassifier(["보라"]), enabled=True, prompt="가짜 프롬프트")
    assert "배가" in o.removed and [g.target_raw for g in o.result.clarify.groups] == ["보라"]
    assert o.result.clarify.question == fp.CLARIFY_MANY_CANDIDATES.format(drug="보라")


def test_clarify_model_keeps_backward_compatible_fields():
    assert set(Clarify.model_fields) == {"question", "target_raw", "options", "pending_raws", "groups"}
