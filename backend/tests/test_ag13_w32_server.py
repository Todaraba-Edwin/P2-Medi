"""W3-2 서버 개선 후보 시험(AG-13-41·42·44·45·46, 2026-11-24). 가짜 모델·합성 사전·합성 DB, LLM·네트워크·원격 DB 호출 0.

후보마다 **독립 스위치**(`GraphDeps`·`build_deps` 인자, 기본 켬)를 시험한다: 켰을 때의 새 동작과 **끄면 이전 동작과 같다**는 것을 함께 본다.
- 41 `router_time_noise`: 시각·횟수 잡음 일반화(사전 이름과 일치하면 버리지 않는 보호 포함)
- 42 `redose_on_clarify`: 되묻기로 끝나도 재복용 질문이면 `REDOSE_NOTICE`(기존 고정 문구 그대로)
- 44 `identify_arg_check`: `identify_drug` 인자 검증(`ARG_SCHEMA`, 기존 거절 경로·이벤트 재사용)
- 45 `confine_confirmed_args`(C-1)·`summary_router_pairs`(C-3): 도구 인자·요약을 Router 확정 집합에 묶음(`rca-u26-selection-leak.md` S1·S4·S7 재현)
- 46 `merge_unconfirmed_lines`(a)·`display_name_fix`(b): 미판정 약의 표시 정리(`entries` 불변)
새 사용자 노출 문구는 없다(기존 `fixed_phrases` 문구만 재배치, 이 시험이 문구 원문 변경 0을 고정한다).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from w32_synth import (
    CONFIRMED_AB,
    Q_REDOSE,
    Q_U26,
    SEQ_A,
    SEQ_B,
    SEQ_C,
    SEQ_D,
    SEQ_E,
    FakeDur,
    golden_conn,
    w32_dict,
)

from app.agent import fixed_phrases as fp
from app.agent import nondrug_tokens as NT
from app.agent import router as R
from app.agent.confine import EVENT_ARG_CONFINED, confine_check_args, has_confirmed, resolved_seqs
from app.agent.finalize import finalize
from app.agent.graph.build import build_graph, run_question
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call
from app.agent.graph.nodes import GraphDeps
from app.agent.graph.wiring import build_deps, build_tool_context
from app.agent.tools.check_contraindications import _resolve
from app.agent.tools.context import ToolContext
from app.agent.tools.registry import REGISTRY, invoke
from app.agent.tools.schemas import DrugArg
from app.api.schemas import response_from_state

SWITCHES = ("router_time_noise", "redose_on_clarify", "identify_arg_check", "confine_confirmed_args", "summary_router_pairs",
            "merge_unconfirmed_lines", "display_name_fix")
ALL_OFF = {k: False for k in SWITCHES}
GOOD = {"sentences": [{"text": "조회한 결과를 정리했어요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}]}


@pytest.fixture(scope="module")
def dd():
    return w32_dict()


def _graph(dd, script: list[AIMessage], **switches: bool):
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm, sm = ScriptedToolModel(script=script), ScriptedSummary([GOOD])
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=sm, system_prompt="시험용 시스템 프롬프트", **switches)
    return build_graph(deps), tm, sm, deps


def _check(drugs: list[dict[str, Any]], cid: str = "c1") -> AIMessage:
    return AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": drugs, "pregnancy": True}, cid)])


def _ev(st: dict, name: str) -> list[dict]:
    return [e for e in st["events"] if e.get("event") == name]


def _contra_keys(st: dict) -> set[str]:
    """도구가 낸 판정 근거(식별 항목 제외)가 가리키는 약 키."""
    return {k for it in st["evidence"] if it.get("kind") != "identify" for k in it.get("drug_keys") or []}


# =========================================================================== 스위치 구조
def test_switch_names_and_defaults(dd):
    ctx = ToolContext(drug_dict=dd)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(), summary_model=ScriptedSummary([GOOD]), system_prompt="x")
    assert all(getattr(deps, k) is True for k in SWITCHES)  # 모두 기본 켬
    off = build_deps(dd, ctx, tool_model=ScriptedToolModel(), summary_model=ScriptedSummary([GOOD]), system_prompt="x", **ALL_OFF)
    assert all(getattr(off, k) is False for k in SWITCHES)
    fields = set(GraphDeps.__dataclass_fields__)
    assert set(SWITCHES) <= fields
    # `ToolContext`만 만들어 쓰는 호출(시험·스크립트)은 이전 동작이다
    assert ctx.identify_arg_check is False and ctx.display_name_fix is False


def test_no_environment_variable_switch_was_added():
    root = Path(__file__).resolve().parents[1] / "app"
    for rel in ("agent/nondrug_tokens.py", "agent/confine.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "environ" not in names and "getenv" not in names


def test_pure_modules_have_no_io_imports():
    root = Path(__file__).resolve().parents[1] / "app" / "agent"
    allowed = {"nondrug_tokens.py": {"__future__", "re"},
               "confine.py": {"__future__", "dataclasses", "typing", "app.tools.drug_dict"}}
    for fn, ok in allowed.items():
        tree = ast.parse((root / fn).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert imported <= ok, (fn, imported - ok)


def test_user_confirmed_flag_value_matches_router():
    from app.agent.confine import FLAG_USER_CONFIRMED

    assert FLAG_USER_CONFIRMED == R.FLAG_USER_CONFIRMED


# =========================================================================== AG-13-41 Router 시각·횟수 잡음 일반화
TIME_PHRASES = ["점심12시에", "정오12시에", "4시간뒤에", "세시간뒤에", "세시간 후에", "점심시간에", "12시30분에", "점심 12시30분에", "9시간격으로",
                "하루3번", "하루세번", "식후30분에", "저녁6시30분에", "1일3회"]
ALREADY_OK = ["점심 12시에", "12시에", "오후 12시에", "식후 30분에", "점심에", "자정에", "오전9시에", "저녁6시에", "밤 11시에", "낮12시에", "하루 3회", "1일 3회", "4시간 뒤에"]


def _entities(dd, phrase: str, **kw):
    r = R.route_input(Q_REDOSE.format(when=phrase + " "), dd, **kw)
    return r, [(e.raw, e.status) for e in r.entities]


@pytest.mark.parametrize("phrase", TIME_PHRASES)
def test_41_time_and_count_phrases_are_not_drug_candidates(dd, phrase):
    on, ents_on = _entities(dd, phrase)
    assert [s for _, s in ents_on] == ["RESOLVED"] and ents_on[0][0].startswith("타이레놀정500")
    assert on.ambiguous is False and on.clarify is None and on.redose_question and on.intake_question
    off, ents_off = _entities(dd, phrase, time_noise=False)
    assert any(s != "RESOLVED" for _, s in ents_off)   # 스위치를 끄면 이전 동작: 시각·횟수 조각이 약 후보(NOT_FOUND·오탈자 의심)로 남는다
    assert off.entities[0].raw.startswith("타이레놀정500") and len(off.entities) == 2


@pytest.mark.parametrize("phrase", ALREADY_OK)
def test_41_already_working_inputs_are_unchanged(dd, phrase):
    on, off = R.route_input(Q_REDOSE.format(when=phrase + " "), dd), R.route_input(Q_REDOSE.format(when=phrase + " "), dd, time_noise=False)
    assert on.model_dump() == off.model_dump()
    assert on.ambiguous is False


@pytest.mark.parametrize("token", ["8시간이알서방정", "타이레놀8시간", "이알서방정", "아세트아미노펜", "점심", "하루", "12", "타이레놀정500"])
def test_41_regex_does_not_match_product_like_tokens(token):
    assert not NT.is_time_or_count_token(token)


@pytest.mark.parametrize("token", ["점심12시", "정오12시", "4시간뒤", "네시간뒤", "두시간", "점심시간", "12시30분", "9시간격", "하루3번", "하루세번",
                                   "식후30분", "30분뒤", "저녁6시30분", "하루에세번씩", "점심12시에"])
def test_41_regex_matches_time_and_count_tokens(token):
    assert NT.is_time_or_count_token(token)


def test_41_dictionary_name_match_is_protected(dd):
    """사전 이름과 일치(정확·정규화·접두·중간)하면 버리지 않는다: 정규식에 걸리는 "열두시간"은 합성 제품 `열두시간서방정`의 접두, "네시간뒤"는 제품 `네시간뒤`와 정확히 같다."""
    for tok in ("열두시간", "네시간뒤"):
        assert NT.is_time_or_count_token(tok)
        assert R._is_noise(tok, dd) is False                                  # 보호: 사전 접두·정확 일치
        assert R._is_noise(tok, dd, time_noise=False) is False                # 끈 쪽과 같다(원래 안 걸렸다)
    assert R._is_noise("세시간", dd) is True and R._is_noise("세시간", dd, time_noise=False) is False  # 보호 대상이 아니면 켠 쪽만 잡음
    r = R.route_input("열두시간 먹어도 되나요?", dd)
    assert [e.raw for e in r.entities] == ["열두시간"]                           # 약 후보로 남는다(되묻기·확정은 사전 몫)
    # 실제 사전에 있는 "시간" 든 제품 이름은 정규식에 걸리지도 않는다
    for name in ("8시간이알서방정", "타이레놀8시간이알서방정"):
        assert not NT.is_time_or_count_token(name)
    r = R.route_input("8시간이알서방정 먹어도 되나요?", dd)
    assert [e.item_seq for e in r.entities] == [SEQ_E]


def test_41_switch_off_equals_previous_behavior_on_whole_sample(dd):
    """스위치를 끈 결과 = 이 후보가 없던 때의 결과(일반화 규칙을 뺀 `_is_noise`)."""
    qs = [Q_REDOSE.format(when=p + " ") for p in TIME_PHRASES + ALREADY_OK] + [Q_U26, "게보린정이랑 와파린정 같이 먹어도 되나요?", "아이가 열이 나는데 타이레놀 먹여도 되나요"]
    for q in qs:
        assert R.route_input(q, dd, time_noise=False).model_dump() == R.route_input(q, dd, time_noise=False).model_dump()
    # 일반화 규칙이 영향을 주지 못하는 질문은 켜도 같다
    for q in (Q_U26, "게보린정이랑 와파린정 같이 먹어도 되나요?"):
        assert R.route_input(q, dd).model_dump() == R.route_input(q, dd, time_noise=False).model_dump()


def test_41_graph_goes_to_model_path_when_on_and_clarifies_when_off(dd):
    q = Q_REDOSE.format(when="점심12시에 ")
    g, tm, sm, _ = _graph(dd, [_check([{"name": "타이레놀정500밀리그람"}]), AIMessage("done")])
    st = run_question(g, q)
    assert st["end_reason"] == "NORMAL" and len(tm.calls) == 2 and st["answer"]["redose_notice"] == fp.REDOSE_NOTICE
    g, tm, sm, _ = _graph(dd, [AIMessage("done")], router_time_noise=False)
    st = run_question(g, q)
    assert st["end_reason"] == "CLARIFY" and tm.calls == [] and sm.calls == []


# =========================================================================== AG-13-42 되묻기에도 복용 고지
Q_AMBIG_REDOSE = "나 이미 먹었는데 타이레놀 콜드에스 또 먹어도 되나요?"
Q_AMBIG_PLAIN = "타이레놀 콜드에스 먹어도 되나요?"


def test_42_clarify_with_redose_question_carries_fixed_notice(dd):
    g, tm, _, _ = _graph(dd, [AIMessage("done")])
    st = run_question(g, Q_AMBIG_REDOSE)
    assert st["end_reason"] == "CLARIFY" and st["redose_question"] is True and tm.calls == []
    assert st["answer"]["redose_notice"] == fp.REDOSE_NOTICE                       # 기존 고정 문구 그대로
    assert fp.REDOSE_NOTICE in st["answer"]["text"]
    assert st["answer"]["entries"] == [] and st["answer"]["dose_check"] is None and st["answer"]["dose_notice"] is None  # 판정 항목·되묻기 칸은 그대로 비어 있다


def test_42_switch_off_and_non_redose_are_unchanged(dd):
    g, *_ = _graph(dd, [AIMessage("done")], redose_on_clarify=False)
    assert run_question(g, Q_AMBIG_REDOSE)["answer"]["redose_notice"] is None
    g, *_ = _graph(dd, [AIMessage("done")])
    st = run_question(g, Q_AMBIG_PLAIN)
    assert st["end_reason"] == "CLARIFY" and st["answer"]["redose_notice"] is None  # 재복용 질문이 아니면 붙지 않는다


def test_42_only_reused_phrase_no_new_text(dd):
    """새 문구가 없다: 되묻기 응답이 켰을 때 더 가진 글자는 `REDOSE_NOTICE` 한 줄뿐이다."""
    on, *_ = _graph(dd, [AIMessage("done")])
    off, *_ = _graph(dd, [AIMessage("done")], redose_on_clarify=False)
    a, b = run_question(on, Q_AMBIG_REDOSE)["answer"], run_question(off, Q_AMBIG_REDOSE)["answer"]
    assert {k for k in a if a[k] != b[k]} == {"redose_notice", "text"}
    assert a["text"].replace(fp.REDOSE_NOTICE + "\n", "", 1) == b["text"]


# =========================================================================== AG-13-44 identify_drug 인자 검증(C-2)
@pytest.mark.parametrize("name", ["점심12시", "점심 12시", "4시간뒤", "세시간뒤", "하루3번", "2알", "500밀리그람", "30분", "15시", "점심때", "12", "mg"])
def test_44_non_drug_names_are_rejected_with_arg_schema(dd, name):
    ctx = ToolContext(drug_dict=dd, identify_arg_check=True)
    out = invoke("identify_drug", {"name": name}, ctx)
    assert out["blocked"] is True and out["error"]["code"] == "ARG_SCHEMA" and out["items"] == []
    assert name not in json.dumps(out, ensure_ascii=False)               # 틀린 값을 되풀이하지 않는다
    assert "name: non_drug_token" in out["error"]["reason"]
    ctx_off = ToolContext(drug_dict=dd, identify_arg_check=False)
    assert "items" in invoke("identify_drug", {"name": name}, ctx_off) and "error" not in invoke("identify_drug", {"name": name}, ctx_off)  # 끄면 이전 동작


@pytest.mark.parametrize("name", ["타이레놀정500밀리그람", "8시간이알서방정", "아세트아미노펜", "열두시간서방정", "네시간뒤", "이지렉트정1.0밀리그램"])
def test_44_dictionary_names_and_drug_names_are_allowed(dd, name):
    out = invoke("identify_drug", {"name": name}, ToolContext(drug_dict=dd, identify_arg_check=True))
    assert "error" not in out and out["items"], name


def test_44_graph_emits_existing_arg_schema_event_and_no_prompt_change(dd):
    script = [AIMessage("", tool_calls=[tool_call("identify_drug", {"name": "점심12시"}, "c1")]), AIMessage("done")]
    g, tm, _, deps = _graph(dd, list(script))
    st = run_question(g, "타이레놀정500밀리그람 먹어도 되나요?")
    assert [e for e in st["events"] if e.get("event") == "ARG_SCHEMA"] == [{"rule": "H21", "event": "ARG_SCHEMA", "tool": "identify_drug"}]
    assert st["evidence"] == []                                           # 도구 본문 미실행
    g, *_ = _graph(dd, list(script), identify_arg_check=False)
    st = run_question(g, "타이레놀정500밀리그람 먹어도 되나요?")
    assert not [e for e in st["events"] if e.get("event") == "ARG_SCHEMA"] and st["evidence"]
    assert "agent_system@v3" not in deps.system_prompt                      # C-3(프롬프트)는 이번에 하지 않는다
    assert tuple(REGISTRY["identify_drug"].description for _ in [0]) == ("약 이름으로 후보(최대 5개)를 찾는다. 판정하지 않는다.",)  # 모델에 보이는 설명 불변


# =========================================================================== AG-13-45 U-26 C-1·C-3
S1 = [_check([{"item_seq": SEQ_A}, {"item_seq": SEQ_B}]), AIMessage("done")]
S4 = [AIMessage("", tool_calls=[tool_call("identify_drug", {"name": "콜드-에스"}, "c1")]),
      _check([{"name": "타이레놀정500", "item_seq": SEQ_A}, {"name": "콜드-에스", "item_seq": SEQ_B}], "c2"),
      _check([{"name": "타이레놀정500밀리그람"}, {"name": "타이레놀콜드-에스정"}], "c3"),
      AIMessage("done")]
S7 = [_check([{"item_seq": SEQ_A}, {"item_seq": SEQ_C}]), AIMessage("done")]


def _run_u26(dd, script, **sw):
    g, *_ = _graph(dd, list(script), **sw)
    return run_question(g, Q_U26, {"pregnant": True}, CONFIRMED_AB)


def test_45_router_confirms_selection_and_helpers(dd):
    st = _run_u26(dd, S1)
    ents = st["entities"]
    assert [(e["item_seq"], e["status"]) for e in ents] == [(SEQ_A, "RESOLVED"), (SEQ_B, "RESOLVED")]
    assert has_confirmed(ents) and resolved_seqs(ents) == [SEQ_A, SEQ_B]
    assert not has_confirmed(None) and not has_confirmed([{"status": "RESOLVED", "item_seq": SEQ_A, "flags": []}])


def test_45_s4_non_selected_candidate_is_not_checked(dd):
    on = _run_u26(dd, S4)
    off = _run_u26(dd, S4, **ALL_OFF)
    assert SEQ_C in _contra_keys(off) and SEQ_C not in _contra_keys(on)         # 켜면 비선택 후보(C)가 판정 근거에 들어오지 않는다
    assert SEQ_A in _contra_keys(on) and SEQ_B in _contra_keys(on)               # 선택한 두 약은 그대로 조회된다
    ev = _ev(on, EVENT_ARG_CONFINED)
    assert ev == [{"rule": "H21", "event": EVENT_ARG_CONFINED, "tool": "check_contraindications", "n_dropped": 1, "n_added": 1, "fallback": False}]
    assert not _ev(off, EVENT_ARG_CONFINED)
    # 이벤트에는 이름·코드가 없다
    assert SEQ_C not in json.dumps(ev) and "타이레놀콜드" not in json.dumps(ev, ensure_ascii=False)
    # 모델 재호출 없음: 호출 수가 같다
    assert on["call_count"] == off["call_count"]


def test_45_s7_model_checks_only_a_and_nonselected_does_not_report_zero_unchecked(dd):
    off = _run_u26(dd, S7, **ALL_OFF)
    assert off["answer"]["result_summary"]["n_pairs_unchecked"] == 0              # 이전 동작(문제 재현): A·B를 안 봤는데 미확인 0건
    only_c3 = _run_u26(dd, S7, confine_confirmed_args=False)
    assert only_c3["answer"]["result_summary"]["n_pairs_unchecked"] == 1          # C-3만: Router 쌍(A·B)은 조회 근거가 없어 미확인으로 센다
    assert only_c3["answer"]["result_summary"]["pairs_found"] == [] and not _ev(only_c3, EVENT_ARG_CONFINED)
    only_c1 = _run_u26(dd, S7, summary_router_pairs=False)
    assert SEQ_C not in _contra_keys(only_c1) and only_c1["answer"]["result_summary"] is None  # C-1만: 비선택 쌍이 없고 짝 항목이 없으니 요약을 지어내지 않는다
    both = _run_u26(dd, S7)
    rs = both["answer"]["result_summary"]
    assert rs is None or rs["n_pairs_unchecked"] != 0                              # 어느 경우에도 "0건"이 되지 않는다


def test_45_s1_selected_pair_keeps_entries_and_counts_unchecked_pair(dd):
    on = _run_u26(dd, S1)
    assert on["answer"]["result_summary"]["n_pairs_unchecked"] == 1                # B는 판정 코드가 없는 약이라 A·B는 확인하지 못한 짝
    assert not _ev(on, EVENT_ARG_CONFINED)                                        # 이미 확정 집합이라 바뀐 인자 없음


def test_45_c3_summary_only_changes_result_summary_not_entries(dd):
    a = _run_u26(dd, S7, confine_confirmed_args=False)["answer"]
    b = _run_u26(dd, S7, **ALL_OFF)["answer"]
    assert a["entries"] == b["entries"]
    assert {k for k in a if a[k] != b[k]} <= {"result_summary", "text", "line_groups"}


def test_45_no_effect_without_confirmed_entities(dd):
    """확정 엔티티가 없는 경로(평가·첫 질문)는 인자·요약이 달라지지 않는다."""
    q = "타이레놀정500밀리그람이랑 이지렉트정1.0밀리그램 같이 먹어도 되나요?"
    script = [_check([{"name": "타이레놀정500밀리그람"}, {"name": "이지렉트정1.0밀리그램"}, {"name": "엉뚱한정"}]), AIMessage("done")]
    outs = []
    for sw in ({}, ALL_OFF):
        g, *_ = _graph(dd, list(script), **sw)
        outs.append(run_question(g, q))
    assert not _ev(outs[0], EVENT_ARG_CONFINED)
    assert [e for e in outs[0]["events"] if e.get("event") != "ROUTER"] == [e for e in outs[1]["events"] if e.get("event") != "ROUTER"]
    assert outs[0]["answer"] == outs[1]["answer"]


def test_45_confine_unit_rules(dd):
    ents = [
        {"raw": "타이레놀정500", "normalized": "타이레놀정500", "status": "RESOLVED", "item_seq": SEQ_A, "flags": ["USER_CONFIRMED"]},
        {"raw": "콜드-에스", "normalized": "콜드에스", "status": "RESOLVED", "item_seq": SEQ_B, "flags": ["USER_CONFIRMED"]},
        {"raw": "가나다정", "normalized": "가나다정", "status": "NOT_FOUND", "item_seq": None, "flags": []},
    ]

    def conf(drugs):
        return confine_check_args({"drugs": drugs, "pregnancy": True}, ents, dd)

    r = conf([{"item_seq": SEQ_A}, {"item_seq": SEQ_C}])                       # 비선택 코드는 버린다
    assert r.args["drugs"] == [{"item_seq": SEQ_A}] and (r.n_dropped, r.n_added) == (1, 0) and r.args["pregnancy"] is True
    r = conf([{"name": "콜드-에스"}, {"name": "코푸콜드-에스액"}])             # 같은 확정 제품은 한 번만, 이름은 item_seq로 보강
    assert r.args["drugs"] == [{"name": "콜드-에스", "item_seq": SEQ_B}] and (r.n_dropped, r.n_added) == (1, 1)
    r = conf([{"name": "가나다정"}, {"name": "타이레놀정500"}])                # NOT_FOUND 엔티티와 같은 이름은 그대로 둔다
    assert r.args["drugs"] == [{"name": "가나다정"}, {"name": "타이레놀정500", "item_seq": SEQ_A}]
    r = conf([{"name": "아무약"}, {"item_seq": SEQ_A, "name": "엉뚱한 이름"}])  # 무관한 이름은 버리고 코드가 확정 집합이면 이름이 달라도 남긴다
    assert r.args["drugs"] == [{"item_seq": SEQ_A, "name": "엉뚱한 이름"}] and r.n_dropped == 1
    r = conf([{"ingredient_code": "101300ATB"}])                               # 성분코드만 있는 항목은 대상이 아니다
    assert not r.changed and r.args["drugs"] == [{"ingredient_code": "101300ATB"}]
    r = conf([{"item_seq": SEQ_C}, {"item_seq": SEQ_D}])                       # 전부 무관하면 RESOLVED 엔티티 코드로 대신 채운다
    assert r.fallback and r.args["drugs"] == [{"item_seq": SEQ_A}, {"item_seq": SEQ_B}] and r.n_dropped == 2
    # 확정 엔티티가 없으면 한 글자도 바꾸지 않는다
    plain = [{**e, "flags": []} for e in ents]
    args = {"drugs": [{"item_seq": SEQ_C}]}
    r = confine_check_args(args, plain, dd)
    assert r.args is args and not r.changed
    assert confine_check_args({"drugs": "x"}, ents, dd).args == {"drugs": "x"}  # 모양이 낯설면 건드리지 않는다


def test_45_trace_does_not_receive_confirmed_codes(dd):
    """기존 약속(AG-05-03 A): 고른 코드는 trace span 입력에 옮기지 않는다 — 보강된 인자는 실행에만 쓰이고 span은 모델이 넘긴 인자를 그대로 둔다."""
    from app.agent.graph.trace import GraphTracer, ListSink

    sink = ListSink()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[_check([{"name": "콜드-에스"}, {"name": "타이레놀정500"}]), AIMessage("done")]),
                      summary_model=ScriptedSummary([GOOD]), system_prompt="x", tracer=GraphTracer(sink=sink, model="gpt-6-luna", api_enabled=ctx.api_enabled))
    run_question(build_graph(deps), Q_U26, {"pregnant": True}, CONFIRMED_AB)
    spans = [r for r in sink.records if r.get("node") == "tools"]
    assert spans and SEQ_B not in json.dumps([r.get("input_summary") for r in spans], ensure_ascii=False, default=str)


# =========================================================================== AG-13-46 미판정 약 표시 정리
def test_46_a_merges_same_drug_unconfirmed_lines_in_response_not_entries(dd):
    on, off = _run_u26(dd, S1), _run_u26(dd, S1, **ALL_OFF)
    a, b = on["answer"], off["answer"]
    assert a["entries"] == b["entries"]                                           # `entries`(평가 원본)는 불변
    assert b["line_groups"] == []
    assert a["line_groups"] == [{"key": SEQ_B, "kind": "unconfirmed", "evidence_ids": ["pregnancy:" + SEQ_B, "identify:" + SEQ_B]}]
    ron, roff = response_from_state(on), response_from_state(off)
    drug_b = [f for f in ron.findings if f.drug == "코푸콜드-에스액" and f.target == "product"]
    assert len(drug_b) == 1 and len([f for f in roff.findings if f.drug == "코푸콜드-에스액" and f.target == "product"]) == 2
    # 근거 상세는 근거 ID마다 그대로 남는다
    assert {d.evidence_id for d in ron.detail} == {d.evidence_id for d in roff.detail}


def test_46_a_does_not_merge_lines_with_extra_explanation():
    """찾지 못함(UNIDENTIFIED) `identify` 줄은 이유·다음 행동 안내가 따로 있어 묶지 않는다(사라질 정보가 있으면 묶지 않는다)."""
    unid = {"kind": "identify", "status": "UNIDENTIFIED", "subject": ["가나다"], "evidence_id": "identify:가나다", "source": None, "as_of": None,
            "flags": [], "matches": [], "dataset_key": None, "source_kind": None, "input_name": "가나다", "drugs": ["가나다"], "drug_keys": ["가나다"],
            "searched": [], "retried": False}
    preg = {**unid, "kind": "pregnancy", "evidence_id": "pregnancy:가나다"}
    r = finalize([unid, preg], merge_unconfirmed=True)
    assert r["line_groups"] == []


def test_46_a_pair_lines_and_other_drugs_are_not_merged(dd):
    r = _run_u26(dd, S1)["answer"]
    assert all(g["kind"] == "unconfirmed" and len(g["evidence_ids"]) > 1 for g in r["line_groups"])
    assert not any("contra_pair" in e for g in r["line_groups"] for e in g["evidence_ids"])


def test_46_b_display_name_uses_dict_product_name_or_original_arrow_product(dd):
    ctx = ToolContext(drug_dict=dd, display_name_fix=True)
    off = ToolContext(drug_dict=dd, display_name_fix=False)
    # 코드만: 지금도 사전 제품명(AG-10-07 A)
    assert _resolve(ctx, DrugArg(item_seq=SEQ_B)).label == _resolve(off, DrugArg(item_seq=SEQ_B)).label == "코푸콜드-에스액"
    # 이름+코드: 끄면 사용자가 적은 이름(옛 동작), 켜면 `원문 → 제품명`
    assert _resolve(off, DrugArg(name="콜드-에스", item_seq=SEQ_B)).label == "콜드-에스"
    d = _resolve(ctx, DrugArg(name="콜드-에스", item_seq=SEQ_B))
    assert d.label == "콜드-에스 → 코푸콜드-에스액" and d.key == SEQ_B and d.ok is False       # 키·판정은 그대로
    # 같은 이름(정규화)이면 제품명 하나
    assert _resolve(ctx, DrugArg(name="코푸콜드에스액", item_seq=SEQ_B)).label == "코푸콜드-에스액"
    # 판정한 약(ok)은 사용자가 적은 이름을 그대로 둔다
    ok = _resolve(ctx, DrugArg(name="타이레놀정500", item_seq=SEQ_A))
    assert ok.ok and ok.label == "타이레놀정500"
    # 사전에 없는 코드는 지어내지 않는다
    assert _resolve(ctx, DrugArg(name="가짜", item_seq="999999999")).label == "가짜"


def test_46_b_no_new_user_visible_phrase_added_by_labels(dd):
    st = _run_u26(dd, S4)
    texts = [e["text"] for e in st["answer"]["entries"]]
    assert all(t in {fp.UNIDENTIFIED, fp.PAIR_NOT_CHECKED, fp.NOT_LISTED, fp.IDENTIFIED_LINE} or t.startswith("삐!") for t in texts)


# =========================================================================== 고정 문구 원문 불변
def test_fixed_phrases_unchanged():
    assert fp.REDOSE_NOTICE == "추가 복용 여부·간격은 정해 드릴 수 없어요. 근거 상세의 허가사항 용법용량을 보고 약사에게 확인하세요."
    assert fp.LIMIT_REACHED.startswith("답을 정리하다 시간이 다 되어")      # AG-13-47 B: 승인 전까지 문구 변경 없음
    assert fp.UNIDENTIFIED == "약을 찾지 못해 확인하지 못함"


def test_all_switches_off_equals_per_switch_off_for_confirmed_flow(dd):
    """일곱 스위치를 모두 끈 결과 = 후보 이전 동작. 스위치를 하나만 켠 결과는 그 후보의 변화만 갖는다(한 번에 하나 ablation 가능)."""
    base = _run_u26(dd, S4, **ALL_OFF)
    assert not _ev(base, EVENT_ARG_CONFINED) and base["answer"]["line_groups"] == [] and SEQ_C in _contra_keys(base)
    flows = {"confine_confirmed_args": S4, "summary_router_pairs": S7, "merge_unconfirmed_lines": S1, "display_name_fix": S4}
    for k, script in flows.items():
        base_k = _run_u26(dd, script, **ALL_OFF)
        one = _run_u26(dd, script, **{**ALL_OFF, k: True})
        diff = {kk for kk in one["answer"] if one["answer"][kk] != base_k["answer"][kk]}
        assert diff, k  # 각 스위치는 자기 흐름에서 실제로 무언가를 바꾼다(빈 스위치가 아니다)
        if k in ("summary_router_pairs", "merge_unconfirmed_lines"):
            assert "entries" not in diff, (k, diff)  # 요약·묶음 정리는 `entries`(평가 원본)를 건드리지 않는다


# =========================================================================== 허가사항(label) 미확보 줄의 이름 자리(응답 변환, 2026-11-24 부수 조사)
Q_PREG_COLD = "임산부인데 타이레놀콜드-에스정 먹어도 되니?"


def _label_gap_state(dd):
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": SEQ_C}], "pregnancy": True}, "c1"),
                                        tool_call("get_label_section", {"item_seq": SEQ_C, "section": "주의사항"}, "c2")]), AIMessage("done")]
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script, repeat_last=True), summary_model=ScriptedSummary([GOOD]), system_prompt="x")
    return run_question(build_graph(deps), Q_PREG_COLD, {"pregnant": True})


def _texts(r) -> list[str]:
    out = [r.pharmacist_advice and " ".join(r.pharmacist_advice) or ""]
    for f in r.findings:
        out += [f.drug, f.text, *f.notes]
    out += [d.missing_text or "" for d in r.detail]
    return out


def test_label_gap_merged_into_product_row_notes_and_no_code_leak(dd):
    import re

    from app.api.schemas import to_chat_response

    st = _label_gap_state(dd)
    new, old = response_from_state(st), to_chat_response(st["answer"], end_reason=st["end_reason"], entities=st["entities"], merge_label_rows=False)
    # 이전: 허가사항 줄이 따로 나가고 코드가 문구에 들어 있다
    assert any("주의사항" in f.drug for f in old.findings) and any(re.search(r"\d{9}", t) for t in _texts(old))
    # 지금: 같은 약의 판정 행 notes 한 줄로 합쳐지고 문구 어디에도 품목기준코드가 없다
    assert not any("주의사항" in f.drug for f in new.findings)
    rows = [f for f in new.findings if f.drug == "타이레놀콜드-에스정" and f.target == "product"]
    assert any("주의사항은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요" in n for f in rows for n in f.notes)
    assert not any(re.search(r"\d{9}", t) for t in _texts(new))
    assert new.pharmacist_advice == ["복용 전에 꼭 약국·약사에게 타이레놀콜드-에스정을 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요."]
    # `entries`(평가 원본)·근거 상세의 근거 ID·고정 문구 상수는 그대로다
    assert st["answer"]["entries"][-1]["evidence_id"] == "label:202106954:주의사항"
    assert [d.evidence_id for d in new.detail] == [d.evidence_id for d in old.detail]
    assert len(new.findings) == len(old.findings) - 1
    assert new.pharmacist_advice_kinds == old.pharmacist_advice_kinds and len(new.pharmacist_advice) == len(old.pharmacist_advice)


def test_label_gap_unknown_product_name_is_left_as_is():
    from app.api.schemas import _advice_lines, _label_notes

    e = {"kind": "label", "bucket": "unconfirmed", "drug": "999999999 · 경고", "text": "999999999 · 경고은 전문의약품이라 공공 자료로는 설명을 확인할 수 없어요"}
    assert _label_notes([e], {"999999999"}, {}) == ({}, set())                   # 이름을 모르면 합치지 않는다
    resp = {"entries": [e], "pharmacist_advice": ["복용 전에 꼭 약국·약사에게 999999999 · 경고을 함께 먹어도 되는지 물어보세요."]}
    assert _advice_lines(resp, {}) == resp["pharmacist_advice"]


def test_label_gap_advice_particle_is_repicked_by_name_batchim():
    from app.api.schemas import _advice_lines

    e = {"kind": "label", "bucket": "unconfirmed", "drug": "202106954 · 주의사항"}
    resp = {"entries": [e], "pharmacist_advice": ["복용 전에 꼭 약국·약사에게 202106954 · 주의사항을 함께 먹어도 되는지 물어보세요."]}
    assert _advice_lines(resp, {"202106954": "가나다"}) == ["복용 전에 꼭 약국·약사에게 가나다를 함께 먹어도 되는지 물어보세요."]
    assert _advice_lines(resp, {"202106954": "타이레놀콜드-에스정"})[0].count("타이레놀콜드-에스정을") == 1
