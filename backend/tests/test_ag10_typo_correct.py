"""AG-10 오탈자 보정·재검색 시험(FR-07, RFP-26-09 A). LLM·네트워크·원격 DB 호출 0.

가상의 제품명으로 만든 합성 소사전을 쓴다(평가 세트·시험셋 문항이 아니다). 확인하는 것:
- 후보가 하나로 뚜렷하면 보정 이름으로 다시 조회해 확정하고, 여럿·불확실이면 지금처럼 되묻는다(임의 선택 금지).
- 숫자(함량)는 고치지 않는다. 가상의 약 이름은 실제 약으로 바뀌지 않는다.
- Router 함수의 기본값(보정 끔)에서는 결과가 지금까지와 같다. 서비스 배선은 보정을 기본으로 켠다(AG-10-02 A, 2026-11-17: 고지 문구 승인).
- 보정해 진행한 답에는 보정 고지가 붙고 `/chat` 응답 `name_corrections`로 나간다(고지 없이 진행하지 않는다).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FORM_MAP, _ing, _prod, golden_conn  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.nodes import GraphDeps  # noqa: E402
from app.agent.graph.state import END_CLARIFY  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.pipeline.build import build_for_condition  # noqa: E402
from app.api import schemas as api_schemas  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

KIDS_A, KIDS_B = "101300ATB", "448001ATB"
NAMES = [
    ("300000001", "가나미솔정10밀리그램"), ("300000002", "가나미솔정20밀리그램"),
    ("300000003", "다라보틴캡슐"), ("300000004", "다라보탄캡슐"),  # 한 자모만 다른 두 제품
    ("300000005", "마바스타시럽(마바성분)"),
    ("300000006", "사아코린서방정5/500밀리그램"),
    ("300000007", "자차포론정"), ("300000008", "자차포론정"),  # 같은 이름의 제품 둘
    ("300000009", "하파토민연질캡슐"),
]
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


def make_dict() -> DrugDict:
    ings = [_ing(0, "Acetaminophen", "아세트아미노펜", [KIDS_A], ["D000147"]), _ing(1, "Pseudoephedrine", "슈도에페드린", [KIDS_B], ["D000448"])]
    prods = [_prod(seq, name, "일반", kids=[KIDS_A], api=[], ids=[0]) for seq, name in NAMES]
    return DrugDict({"meta": {"version": "ag10-synth", "built_at": "2026-11-18T00:00:00+00:00", "form_map": FORM_MAP}, "products": prods, "ingredients": ings})


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return make_dict()


def _one(dd: DrugDict, name: str, *, on: bool = True) -> R.Entity:
    res = R.route_input(f"{name} 먹어도 되나요", dd, typo_correct=on)
    assert len(res.entities) == 1, [e.raw for e in res.entities]
    return res.entities[0]


# --------------------------------------------------------------------------- 보정되는 경우

def test_one_jamo_typo_is_corrected_and_resolved(dd):
    e = _one(dd, "가나메솔정10밀리그램")
    assert e.status == R.ST_RESOLVED and e.item_seq == "300000001" and e.resolved
    assert e.raw == "가나미솔정10밀리그램" and e.corrected_from == "가나메솔정10밀리그램"
    assert R.FLAG_TYPO_CORRECTED in e.flags and e.branch == R.BRANCH_TYPO and e.options == []
    assert e.strength == "10밀리그램" and e.code_status == "linked"


def test_corrected_result_goes_on_without_clarify_and_keeps_the_typo_label(dd):
    res = R.route_input("가나메솔정10밀리그램 먹어도 되나요", dd, typo_correct=True)
    assert res.ambiguous is False and res.clarify is None and res.branch_label == R.BRANCH_TYPO
    assert R.corrections_of(res.entities) == [{"input": "가나메솔정10밀리그램", "name": "가나미솔정10밀리그램"}]
    assert R.corrections_of(res.state_update()["entities"]) == R.corrections_of(res.entities)  # 상태 dict에서도 같다
    note = R.note_entities(res.entities)
    assert note == [{"raw": "가나미솔정10밀리그램", "strength": "10밀리그램", "status": "RESOLVED", "item_seq": "300000001",
                     "matched_by": "product_name", "code_status": "linked"}]  # 모델 입력 블록의 키는 그대로다


def test_paren_name_is_corrected_through_the_base_name(dd):
    e = _one(dd, "마바스터시럽")
    assert e.status == R.ST_RESOLVED and e.item_seq == "300000005" and e.raw == "마바스타시럽(마바성분)" and e.corrected_from == "마바스터시럽"


def test_ingredient_name_typo_is_corrected_to_the_ingredient(dd):
    e = _one(dd, "아세트아미노팬")
    assert e.status == R.ST_RESOLVED and e.matched_by == "ingredient_name" and e.item_seq is None
    assert e.corrected_from == "아세트아미노팬" and {R.FLAG_NO_PRODUCT_INFO, R.FLAG_TYPO_CORRECTED} <= set(e.flags)


def test_two_drugs_one_typo_makes_one_pair(dd):
    res = R.route_input("하파토민연질캡슐이랑 가나메솔정10밀리그램 같이 먹어도 되나요", dd, typo_correct=True)
    assert [e.status for e in res.entities] == [R.ST_RESOLVED, R.ST_RESOLVED] and res.n_pairs == 1 and not res.ambiguous
    assert [bool(e.corrected_from) for e in res.entities] == [False, True]


# --------------------------------------------------------------------------- 보정하지 않는 경우(되묻기 유지)

def test_two_equally_close_names_stay_a_clarify(dd):
    """'다라보톤'은 '다라보틴'·'다라보탄'과 똑같이 한 자모 차이다. 어느 쪽인지 모르므로 고르지 않는다."""
    e = _one(dd, "다라보톤캡슐")
    assert e.status in (R.ST_TYPO, R.ST_AMBIGUOUS) and e.corrected_from is None and e.item_seq is None
    res = R.route_input("다라보톤캡슐 먹어도 되나요", dd, typo_correct=True)
    assert res.ambiguous and res.clarify is not None and {o.name for o in res.clarify.options} >= {"다라보틴캡슐", "다라보탄캡슐"}


def test_same_name_for_two_products_stays_a_clarify(dd):
    """보정 이름을 다시 조회했더니 같은 이름의 제품이 둘이면 확정하지 않는다(사전 조회 계약 그대로)."""
    e = _one(dd, "자차포른정")
    assert e.status != R.ST_RESOLVED and e.corrected_from is None
    assert R.route_input("자차포른정 먹어도 되나요", dd, typo_correct=True).ambiguous


def test_strength_numbers_are_never_changed(dd):
    """이름은 맞고 함량 숫자만 사전에 없는 경우: 다른 함량 제품으로 바꾸지 않는다."""
    e = _one(dd, "가나메솔정30밀리그램")  # 30밀리그램 제품은 없다. 10·20밀리그램으로 바꾸지 않는다
    assert e.match_type == "bm25" and e.status == R.ST_TYPO and e.corrected_from is None
    res = R.route_input("사아코린서방정5/850밀리그램 먹어도 되나요", dd, typo_correct=True)
    assert res.ambiguous and all(not x.corrected_from and x.status != R.ST_RESOLVED for x in res.entities)


def test_far_names_and_short_names_are_not_corrected(dd):
    far = _one(dd, "가누메술정10밀리그램")  # 자모 3칸(16자모 중, 점수 0.81): 0.90 미만
    assert far.match_type == "bm25" and far.corrected_from is None and far.status == R.ST_TYPO
    short = R.route_input("하파토 먹어도 되나요", dd, typo_correct=True)
    assert all(not e.corrected_from for e in short.entities)


def test_made_up_name_is_not_turned_into_a_real_drug(dd):
    for q in ("푸른하늘정", "다라보정캡슐", "가나다라미솔정10밀리그램"):
        res = R.route_input(f"{q} 먹어도 되나요", dd, typo_correct=True)
        assert res.entities and all(not e.corrected_from and e.status != R.ST_RESOLVED for e in res.entities), q


def test_prefix_abbreviation_is_out_of_scope(dd):
    """줄여 쓴 이름(접두 일치)은 보정 대상이 아니다(AG-05-01 A: 후보가 하나여도 되묻기)."""
    e = _one(dd, "하파토민")
    assert e.match_type == "prefix" and e.status == R.ST_AMBIGUOUS and e.corrected_from is None


def test_correct_typo_leaves_resolved_and_non_bm25_entities_alone(dd):
    for name in ("하파토민연질캡슐", "하파토민"):
        e = _one(dd, name, on=False)
        assert R.correct_typo(dd, e) is e


def test_thresholds_are_the_documented_values():
    assert R.TYPO_CORRECT_MIN_SCORE == 0.90 and R.TYPO_CORRECT_MIN_GAP == 0.05


# --------------------------------------------------------------------------- 기본값은 지금까지와 같다

@pytest.mark.parametrize("q", ["가나메솔정10밀리그램 먹어도 되나요", "마바스터시럽이랑 하파토민연질캡슐 같이 먹어도 돼요", "아세트아미노팬 임신 중에 괜찮나요",
                               "다라보톤캡슐 먹어도 되나요", "하파토민연질캡슐 먹어도 되나요"])
def test_default_is_off_and_result_equals_the_old_router(dd, q):
    off = R.route_input(q, dd)
    assert off.model_dump() == R.route_input(q, dd, typo_correct=False).model_dump()
    assert all(e.corrected_from is None and R.FLAG_TYPO_CORRECTED not in e.flags for e in off.entities)
    if "가나메솔" in q or "마바스터" in q or "아세트아미노팬" in q:
        assert off.ambiguous and off.clarify is not None  # 끈 상태에서는 되묻기 그대로


def test_normal_questions_are_identical_with_correction_on(dd):
    for q in ("하파토민연질캡슐 먹어도 되나요", "가나미솔정10밀리그램이랑 다라보틴캡슐 같이 먹어도 되나요", "임신 중 피해야 할 진통제가 뭐예요"):
        assert R.route_input(q, dd, typo_correct=True).model_dump() == R.route_input(q, dd).model_dump()


def _deps(dd: DrugDict, **kw: Any) -> GraphDeps:
    return build_deps(dd, build_tool_context(dd, mode="eval", conn_factory=golden_conn), tool_model=ScriptedToolModel(script=[AIMessage("끝")]),
                      summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), **kw)


def test_service_wiring_turns_correction_on_and_eval_default_stays_off(dd):
    """AG-10-02 A(2026-11-17): 고지 문구가 승인 상수가 됐고 서비스 배선은 보정을 기본으로 켠다. 평가·개발 배선의 기본은 끔이다(실행기가 조건으로 정한다)."""
    assert "TYPO_CORRECTED_LINE" not in fp.DRAFT_KEYS and hasattr(fp, "TYPO_CORRECTED_LINE")
    assert _deps(dd, service=True).typo_correct is True
    assert _deps(dd).typo_correct is False and GraphDeps.__dataclass_fields__["typo_correct"].default is False
    assert _deps(dd, service=True, typo_correct=False).typo_correct is False and _deps(dd, typo_correct=True).typo_correct is True


def test_approved_phrase_is_the_decided_sentence():
    assert fp.TYPO_CORRECTED_LINE == "'{input}' → '{name}': 이름이 비슷한 이 약으로 보고 확인했어요. 찾으시는 약이 아니면 약 이름을 다시 알려 주세요."


# --------------------------------------------------------------------------- 보정 고지(고지 없이 진행하지 않는다)

def test_finalize_puts_the_notice_before_the_summary():
    resp = finalize([], model_summary="요약 문장", name_corrections=[{"input": "가나메솔정", "name": "가나미솔정"}])
    line = fp.TYPO_CORRECTED_LINE.format(input="가나메솔정", name="가나미솔정")
    assert resp["name_corrections"] == [{"input": "가나메솔정", "name": "가나미솔정", "text": line}]
    lines = resp["text"].split("\n")
    assert lines.index(line) < lines.index("요약 문장") and resp["fixed_notice"] == fp.FIXED_NOTICE


def test_finalize_without_corrections_has_no_new_key():
    assert "name_corrections" not in finalize([], model_summary="요약")
    assert "name_corrections" not in finalize([], model_summary="요약", name_corrections=[])


def test_notice_phrase_makes_no_safety_or_dose_claim():
    line = fp.TYPO_CORRECTED_LINE.format(input="가", name="나")
    assert not any(w in line for w in ("안전", "괜찮", "먹어도", "드셔도", "문제없")) and "다시 알려 주세요" in line


def _graph(dd: DrugDict, *, on: bool, script: list[AIMessage] | None = None, condition: str = "C2") -> tuple[Any, ScriptedToolModel]:
    tm = ScriptedToolModel(script=script or [AIMessage("조회를 마쳤다")], repeat_last=True)
    deps = build_deps(dd, build_tool_context(dd, mode="eval", conn_factory=golden_conn), tool_model=tm,
                      summary_model=ScriptedSummary([{"sentences": [GUIDE]}]))
    deps.typo_correct = on
    return build_for_condition(deps, condition) if condition != "C2" else build_graph(deps), tm


def test_graph_off_ends_with_clarify_as_before(dd):
    g, _ = _graph(dd, on=False)
    st = run_question(g, "가나메솔정10밀리그램 먹어도 되나요")
    assert st["end_reason"] == END_CLARIFY and "name_corrections" not in st["answer"] and st.get("call_count", 0) == 0


def test_graph_on_goes_to_the_model_and_answer_carries_the_notice(dd):
    call = AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": "300000001"}], "pregnancy": True}, "c1")])
    g, tm = _graph(dd, on=True, script=[call, AIMessage("조회를 마쳤다")])
    st = run_question(g, "임신 중인데 가나메솔정10밀리그램 먹어도 되나요")
    assert st["end_reason"] != END_CLARIFY and st["call_count"] >= 1
    ans = st["answer"]
    line = fp.TYPO_CORRECTED_LINE.format(input="가나메솔정10밀리그램", name="가나미솔정10밀리그램")
    assert [c["text"] for c in ans["name_corrections"]] == [line] and line in ans["text"]
    ev = next(e for e in st["events"] if e.get("event") == "ROUTER")
    assert ev["n_corrected"] == 1 and ev["branch"] == R.BRANCH_TYPO and "가나" not in str(ev)  # 이벤트에는 개수만
    assert len(tm.calls) >= 2  # 도구 호출 1회 + 마무리 턴: 모델까지 갔다
    calls = [tc for m in st["messages"] for tc in (getattr(m, "tool_calls", None) or [])]
    assert [c["name"] for c in calls] == ["check_contraindications"]
    ent = st["entities"][0]
    assert ent["item_seq"] == "300000001" and ent["status"] == "RESOLVED"  # 모델 입력 블록(ROUTER_NOTE)이 읽는 값


def test_graph_on_without_typo_has_no_notice_and_no_event_key(dd):
    g, _ = _graph(dd, on=True)
    st = run_question(g, "하파토민연질캡슐 먹어도 되나요")
    assert st["end_reason"] != END_CLARIFY and st["call_count"] >= 1
    assert "name_corrections" not in st["answer"]
    assert "n_corrected" not in next(e for e in st["events"] if e.get("event") == "ROUTER")


def test_graph_on_but_other_drug_ambiguous_still_asks(dd):
    g, _ = _graph(dd, on=True)
    st = run_question(g, "가나메솔정10밀리그램이랑 다라보톤캡슐 같이 먹어도 되나요")
    assert st["end_reason"] == END_CLARIFY and "name_corrections" not in st["answer"]  # 되묻기는 조회 결과를 보이지 않는다


def test_chat_response_carries_the_notice():
    """`chat_response@v1`의 `name_corrections` 칸(AG-10-02 A): finalize의 고지가 그대로 응답에 실린다. 없으면 빈 목록(기존 응답과 호환)."""
    resp = finalize([], model_summary="요약", name_corrections=[{"input": "가나메솔정", "name": "가나미솔정"}])
    out = api_schemas.to_chat_response(resp, end_reason="NORMAL")
    assert out.schema_version == "chat_response@v1"
    assert [c.model_dump() for c in out.name_corrections] == resp["name_corrections"]
    plain = api_schemas.to_chat_response(finalize([], model_summary="요약"), end_reason="NORMAL")
    assert plain.name_corrections == [] and plain.summary == "요약"


def test_stream_line_without_corrections_is_exactly_as_before():
    """보정이 없는 응답의 스트림 줄에는 `name_corrections` 키가 없다(칸을 더하기 전과 같은 글자: 모르는 키를 거부하는 프런트 검증이 깨지지 않게).
    보정이 있으면 키가 실리고, 다시 읽어도 같은 값이다. 스키마(모델 dump·OpenAPI)에는 칸이 항상 있다."""
    from app.api import events as ev

    plain = api_schemas.to_chat_response(finalize([], model_summary="요약"), end_reason="NORMAL")
    line = ev.encode_event(ev.answer(1, plain))
    assert b"name_corrections" not in line and line.endswith(b"\n")
    assert ev.ChatEvent.model_validate_json(line).root.response == plain  # 빠진 키는 기본값(빈 목록)으로 읽힌다
    assert plain.model_dump()["name_corrections"] == []
    resp = finalize([], model_summary="요약", name_corrections=[{"input": "가나메솔정", "name": "가나미솔정"}])
    fixed = api_schemas.to_chat_response(resp, end_reason="NORMAL")
    line2 = ev.encode_event(ev.answer(1, fixed))
    assert ev.ChatEvent.model_validate_json(line2).root.response.name_corrections == fixed.name_corrections != []
    assert "name_corrections" in api_schemas.ChatResponse.model_json_schema(mode="serialization")["properties"]


def test_chat_response_rejects_a_notice_that_is_not_the_constant_sentence():
    """고지 문장은 화면이 조립하지 않고 서버 상수 그대로다. 모양이 어긋난 고지는 조용히 빠지지 않고 검증 오류가 된다."""
    resp = finalize([], model_summary="요약", name_corrections=[{"input": "가", "name": "나"}])
    for bad in ({"input": "가", "name": "나", "text": "아무 문장"}, {"input": "가", "name": "나"}, {"input": "", "name": "나", "text": "x"}):
        with pytest.raises((ValueError, TypeError)):
            api_schemas.to_chat_response({**resp, "name_corrections": [bad]}, end_reason="NORMAL")
    with pytest.raises(ValueError, match="되묻기"):
        api_schemas.to_chat_response(resp, end_reason="CLARIFY")


def test_service_graph_never_shows_a_corrected_result_without_the_notice(dd):
    """서비스 배선(보정 켬)으로 끝까지 돌린 응답: 보정으로 확정한 약이 있으면 `name_corrections`가 반드시 찬다(되묻기로 끝나면 둘 다 없다)."""
    call = AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": "300000001"}], "pregnancy": True}, "c1")])
    for q, corrected in (("임신 중인데 가나메솔정10밀리그램 먹어도 되나요", True), ("임신 중인데 가나미솔정10밀리그램 먹어도 되나요", False),
                         ("가나메솔정10밀리그램이랑 다라보톤캡슐 같이 먹어도 되나요", False)):
        deps = build_deps(dd, build_tool_context(dd, mode="eval", conn_factory=golden_conn), service=True,
                          tool_model=ScriptedToolModel(script=[call, AIMessage("조회를 마쳤다")], repeat_last=True),
                          summary_model=ScriptedSummary([{"sentences": [GUIDE]}]))
        st = run_question(build_graph(deps), q)
        out = api_schemas.response_from_state(st)
        used = any(e.get("corrected_from") for e in st["entities"]) and st["end_reason"] != END_CLARIFY
        assert used is corrected and bool(out.name_corrections) is corrected, q
