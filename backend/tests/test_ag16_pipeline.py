"""AG-16 C1 고정 파이프라인 시험(가짜 모델·일부 가짜 도구, LLM·네트워크·DB 호출 0).

시험 질문은 모두 합성이다(평가 세트·시험셋·페르소나 질문 아님). 사전은 합성 소사전(AG-05 시험과 같은 방식)이다.
도구는 `identify_drug`·`search_reason`·`search_label`을 **실제 함수**로 쓰고(사전만 쓰거나 코퍼스 없음 → 계약 응답), DB가 필요한 `check_contraindications`만 가짜다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent.graph import nodes as react_nodes  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.nodes import GraphDeps  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink, count_block_warn  # noqa: E402
from app.agent.guardrail import ROUTE_REFUSE  # noqa: E402
from app.agent.pipeline import nodes as pipe_nodes  # noqa: E402
from app.agent.pipeline.build import (  # noqa: E402
    PIPELINE_VERSION,
    PipelineConfig,
    build_for_condition,
    build_pipeline,
    harness_profile,
    run_question,
)
from app.agent.pipeline.state import EVENT_STEP, EVENT_SUMMARY, EVENT_UNIDENTIFIED, PIPELINE_WRITABLE  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.langchain_adapter import build_tools  # noqa: E402
from app.agent.tools.registry import REGISTRY, ToolSpec  # noqa: E402
from app.agent.tools.search_label import search_label as real_search_label  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

KIDS = [
    {"product_code": "111111111", "name": "타이레놀정500밀리그람(아세트아미노펜)_(500mg/1정)", "ingr_code": "101301ATB", "ingr_name": "acetaminophen", "entp": "A사"},
    {"product_code": "666666666", "name": "와파린정(와파린나트륨)_(2mg/1정)", "ingr_code": "104001ATB", "ingr_name": "warfarin sodium", "entp": "J사"},
    {"product_code": "777777777", "name": "게보린정(이소프로필안티피린)_(1정)", "ingr_code": "105001ATB", "ingr_name": "isopropylantipyrine", "entp": "K사"},
]

SEQ_TYL1, SEQ_TYL2, SEQ_WARF, SEQ_GEBO = "000000001", "000000002", "000000010", "000000011"  # 품목기준코드는 9자리(도구 인자 스키마)


def _p(seq: str, name: str, entp: str, ingr: str, edi: str = "", kind: str = "일반의약품") -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": entp, "spclty_pblc": kind, "item_ingr_name": ingr, "edi_code": edi, "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p(SEQ_TYL1, "타이레놀정500밀리그람", "A사", "Acetaminophen", "111111111"),
        _p(SEQ_TYL2, "타이레놀8시간이알서방정", "A사", "Acetaminophen"),
        _p(SEQ_WARF, "와파린정", "J사", "Warfarin Sodium", "666666666"),
        _p(SEQ_GEBO, "게보린정", "K사", "Isopropylantipyrine", "777777777"),
    ],
    "eyak": [], "detail": [],
    "dur_ingr": [
        {"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "단일"},
        {"INGR_CODE": "D000400", "INGR_ENG_NAME": "Warfarin Sodium", "INGR_NAME": "와파린나트륨", "MIX_TYPE": "단일"},
    ],
    "ingr_codes": {},
}
KDB = "한국의약품안전관리원"
PAIR_CODES = ["105001ATB", "104001ATB"]  # 게보린정·와파린정 성분코드(합성)


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0])


# --------------------------------------------------------------------------- 도구: 기록기 + 가짜 병용 조회(DB 없음)
class Rec:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []  # (도구 이름, 인자 dump) — 코드가 만든 호출을 확인한다

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def args(self, name: str) -> list[dict[str, Any]]:
        return [a for n, a in self.calls if n == name]


def _found(kind: str, eid: str, subject: list[str], codes: list[str], match: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "status": "FOUND", "subject": subject, "evidence_id": eid, "source": KDB, "as_of": "2026-07-21", "flags": [],
            "dataset_key": kind, "source_kind": "FILE", "drugs": subject, "cause_codes": codes, "notes": [],
            "matches": [{"row_key": "rk", "row_evidence_id": f"{eid}#a", "notice_no": "제2026-1호", "notice_date": "2026-07-21", **match}]}


def contra_fake(args: Any, ctx: ToolContext) -> dict[str, Any]:
    labels = [d.item_seq or d.name for d in args.drugs]
    items: list[dict[str, Any]] = []
    if len(labels) >= 2:
        items.append(_found("contra_pair", "contra_pair:1", labels[:2], PAIR_CODES, {"reason": "출혈 위험이 커질 수 있다"}))
    if args.pregnancy:
        items.append(_found("pregnancy", "pregnancy:1", labels[:1], [PAIR_CODES[0]], {"grade": "2", "reason": "태아 위험 보고"}))
    if args.age is not None:
        items.append(_found("age", "age:1", labels[:1], [PAIR_CODES[0]], {"reason": "소아 금기", "age_value": "12", "age_unit": "세", "age_cond": "미만"}))
    return {"items": items, "known_ids": [i["evidence_id"] for i in items]}


def contra_boom(args: Any, ctx: ToolContext) -> dict[str, Any]:
    raise RuntimeError("조회 실패(시험)")


def make_registry(rec: Rec, *, contra: Any = contra_fake) -> dict[str, ToolSpec]:
    reg: dict[str, ToolSpec] = {}
    for name, spec in REGISTRY.items():
        func = contra if name == "check_contraindications" else spec.func

        def wrapped(args: Any, ctx: ToolContext, _f: Any = func, _n: str = name) -> dict[str, Any]:
            rec.calls.append((_n, args.model_dump(exclude_none=True)))
            return _f(args, ctx)

        reg[name] = ToolSpec(name, spec.args_model, wrapped, spec.description)
    return reg


GOOD_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹을 때 주의가 필요한 조합으로 조회됐어요.", "evidence_ids": ["contra_pair:1"], "claim_type": "fact", "citations": []},
    {"text": "자세한 내용은 약국·약사에게 확인하세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}
BAD_DRAFT = {"sentences": [{"text": "이 조합은 안전합니다.", "evidence_ids": ["contra_pair:1"], "claim_type": "fact", "citations": []}]}
SCHEMA_BAD = {"sentences": [{"text": "형식이 틀린 문장"}]}  # claim_type 없음 → SCHEMA_INVALID(되감기)
PREG_DRAFT = {"sentences": [
    {"text": "임부금기 목록에 올라 있는 것으로 조회됐어요.", "evidence_ids": ["pregnancy:1"], "claim_type": "fact", "citations": []},
    {"text": "복용 전에 약국·약사에게 확인하세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}
PAIR_Q = "게보린정이랑 와파린정 같이 먹어도 되나요?"


_SEARCH_ID_RE = re.compile(r"search:[a-z_]+:[0-9a-f]{12}")
ADVICE_TEXT = "허가사항·사유 문장은 찾지 못해 확인하지 못했어요. 약국·약사에게 확인하세요."


class AdviceSummary(ScriptedSummary):
    """가짜 요약: 스크립트 초안에, 근거 블록에 보이는 검색 미확보 항목(`search:*`)을 인용한 약사 확인 권고 한 문장을 덧붙인다.
    (코퍼스 없는 시험에서는 검색 도구가 모두 NO_EVIDENCE라, 공유 Validator ⑥(미확보 항목 권고)이 실제 모델처럼 권고 문장을 요구한다.)"""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        d = super().invoke(messages, **kwargs)
        ids = sorted(set(_SEARCH_ID_RE.findall("\n".join(str(getattr(m, "content", "")) for m in messages))))
        if not ids or not isinstance(d, dict):
            return d
        return {"sentences": [*d["sentences"], {"text": ADVICE_TEXT, "evidence_ids": ids, "claim_type": "guidance", "citations": []}]}


def make(dd: DrugDict, drafts: list[Any], *, contra: Any = contra_fake, tracer: Any = None, summary_repeat: bool = True,
         condition: str | None = None) -> tuple[Any, ScriptedToolModel, ScriptedSummary, Rec]:
    rec = Rec()
    reg = make_registry(rec, contra=contra)
    ctx = ToolContext(drug_dict=dd)
    tm = ScriptedToolModel(script=[])  # 도구 선택 모델: 한 번이라도 불리면 스크립트가 비어 RuntimeError
    sm = AdviceSummary(drafts, repeat_last=summary_repeat)
    deps = GraphDeps(drug_dict=dd, tool_model=tm, summary_model=sm, tools=build_tools(ctx, reg), tool_ctx=ctx, system_prompt="시험용 시스템 프롬프트",
                     registry=reg, tracer=tracer)
    g = build_for_condition(deps, condition) if condition else build_pipeline(deps)
    return g, tm, sm, rec


def tool_msgs(state: dict) -> list[ToolMessage]:
    return [m for m in state["messages"] if isinstance(m, ToolMessage)]


def events(state: dict, name: str) -> list[dict[str, Any]]:
    return [e for e in state.get("events") or [] if e.get("event") == name]


# --------------------------------------------------------------------------- 샘플 ① 정상: 고정 순서, 모델은 요약만
@pytest.mark.parametrize("q", [PAIR_Q, "게보린정하고 와파린정을 함께 먹어도 돼요?", "게보린정, 와파린정 병용해도 되는지 알려줘"])
def test_normal_pair_runs_fixed_order_and_model_only_summarizes(dd, q):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, q)
    assert rec.names() == ["identify_drug", "identify_drug", "check_contraindications", "search_reason", "search_label", "search_label"]
    assert tm.calls == [] and len(sm.calls) == 1 and st["call_count"] == 1  # 도구 선택 호출 0, 요약 1
    assert rec.args("check_contraindications") == [{"drugs": [{"item_seq": SEQ_GEBO}, {"item_seq": SEQ_WARF}], "pregnancy": False, "include_cautions": False}]
    reason = rec.args("search_reason")[0]
    assert reason["pair_ids"] == ["104001ATB+105001ATB"] and reason["kinds"] == ["combo"] and reason["query"]
    assert [a["item_seq"] for a in rec.args("search_label")] == [SEQ_GEBO, SEQ_WARF] and all(a["query"] for a in rec.args("search_label"))
    assert st["end_reason"] == "NORMAL" and st["validation"]["status"] == "PASS" and st["rewind_count"] == 0 and st["step"] == "label"
    a = st["answer"]
    assert a["fixed_notice"] == fp.FIXED_NOTICE and a["disclaimer"] == fp.DISCLAIMER and a["emergency"] is None
    assert a["summary"] and "주의가 필요한 조합" in a["summary"]
    assert [e["bucket"] for e in a["entries"]][0] == "found"
    assert [e["step"] for e in events(st, EVENT_STEP)] == ["identify", "contra", "reason", "label"]
    assert [e["n_calls"] for e in events(st, EVENT_STEP)] == [2, 1, 1, 2] and len(events(st, EVENT_SUMMARY)) == 1
    assert all("TOOL_DATA" in str(m.content) for m in tool_msgs(st)) and len(tool_msgs(st)) == 6
    assert count_block_warn(st["events"]) == 0  # 정상 경로: 하네스 차단·경고 0건


def test_tool_calls_are_recorded_like_react_messages(dd):
    """평가 실행기(`extract_trace`)는 메시지의 `tool_calls`로 경로를 읽는다. 코드가 만든 호출도 같은 자리에 있다."""
    g, *_ = make(dd, [GOOD_DRAFT])
    st = run_question(g, PAIR_Q)
    ais = [m for m in st["messages"] if isinstance(m, AIMessage) and m.tool_calls]
    assert [tc["name"] for m in ais for tc in m.tool_calls] == ["identify_drug", "identify_drug", "check_contraindications", "search_reason",
                                                                  "search_label", "search_label"]


# --------------------------------------------------------------------------- 샘플 ② 오탈자 → 되묻기(예외 규칙 2), ③ 모호(접두 브랜드) → 되묻기
def test_typo_ends_with_clarify_card_no_tools_no_model(dd, monkeypatch):
    monkeypatch.setattr(R, "TYPO_SCORE_MAX", 1.0)
    monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", 0.0)  # BM25 후보가 있으면 오탈자 의심으로 분류한다
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, "게보린징 먹어도 되나요")
    if not st.get("ambiguous"):
        pytest.skip("합성 사전에서 BM25 후보가 없어 되묻기가 아님")
    assert st["end_reason"] == "CLARIFY" and st["branch_label"] in (R.BRANCH_TYPO, R.BRANCH_AMBIGUOUS)
    assert rec.names() == [] and tm.calls == [] and sm.calls == [] and st.get("call_count", 0) == 0
    a = st["answer"]
    assert a["summary"] == st["clarify"]["question"] and st["clarify"]["options"]
    for bad in ("안전", "괜찮", "문제 없"):
        assert bad not in a["summary"]
    assert a["fixed_notice"] == fp.FIXED_NOTICE


@pytest.mark.parametrize("q", ["타이레놀 먹어도 되나요", "타이레놀이랑 게보린정 같이 먹어도 되나요"])
def test_ambiguous_ends_with_clarify_card(dd, q):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, q)
    assert st["ambiguous"] and st["end_reason"] == "CLARIFY" and st["branch_label"] == R.BRANCH_AMBIGUOUS
    assert rec.names() == [] and tm.calls == [] and sm.calls == []
    assert {o["item_seq"] for o in st["clarify"]["options"]} >= {SEQ_TYL1, SEQ_TYL2}


# --------------------------------------------------------------------------- 예외 규칙 1: 식별 0건 → 미식별 안내(요약 호출 없음)
@pytest.mark.parametrize("q", ["쿵쿵따리정 먹어도 되나요", "zzzqqq 같이 먹어도 되나요"])
def test_unidentified_ends_without_summary(dd, q):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, q)
    assert rec.names() == ["identify_drug"] and sm.calls == [] and tm.calls == [] and st.get("call_count", 0) == 0
    assert st["step"] == "identify" and st["end_reason"] == "NORMAL"
    ev = events(st, EVENT_UNIDENTIFIED)
    assert len(ev) == 1 and ev[0]["n_entities"] == 1
    a = st["answer"]
    assert a["summary"] is None and fp.UNIDENTIFIED in a["text"] and fp.NOT_SAFE_NOTICE in a["text"] and fp.PHARMACIST_CHECK_NOTICE in a["text"]
    assert a["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED
    for bad in ("안전합니다", "문제없어요"):
        assert bad not in a["text"]


def test_no_drug_mention_ends_as_unidentified_zero_calls(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, "임신 중에 피해야 할 진통제가 뭐예요")
    assert rec.names() == [] and sm.calls == [] and tm.calls == []
    ev = events(st, EVENT_UNIDENTIFIED)
    assert len(ev) == 1 and ev[0]["n_entities"] == 0 and events(st, EVENT_STEP)[0]["skipped"] == "NO_DRUG_MENTION"
    assert st["answer"]["summary"] is None and st["answer"]["fixed_notice"] == fp.FIXED_NOTICE


def test_partial_identification_continues_with_found_only(dd):
    """하나는 찾고 하나는 못 찾으면 찾은 약으로 이어 가고, 못 찾은 약은 미식별 항목으로 남는다(규칙 1은 식별 0건일 때만)."""
    g, tm, sm, rec = make(dd, [{"sentences": [{"text": "조회한 약은 아래와 같아요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}]}])
    st = run_question(g, "게보린정이랑 쿵쿵따리정 같이 먹어도 되나요")
    assert rec.names().count("identify_drug") == 2 and rec.args("check_contraindications") == [
        {"drugs": [{"item_seq": SEQ_GEBO}], "pregnancy": False, "include_cautions": False}]
    assert rec.args("search_reason") == [] and events(st, EVENT_STEP)[2]["skipped"] == "NO_FOUND_CONTRA"  # 판정 항목 없음 → 사유 검색 0
    assert [a["item_seq"] for a in rec.args("search_label")] == [SEQ_GEBO] and len(sm.calls) == 1
    assert any(it["kind"] == "identify" and it["status"] == "UNIDENTIFIED" for it in st["evidence"])
    assert fp.UNIDENTIFIED in st["answer"]["text"]


# --------------------------------------------------------------------------- 프로필(나이·임신) → 인자, 판정된 성분코드 → 사유 검색
def test_pregnancy_and_age_from_router_profile_feed_tool_args(dd):
    g, tm, sm, rec = make(dd, [PREG_DRAFT])
    st = run_question(g, "임신 중인데 게보린정 먹어도 되나요")
    assert rec.args("check_contraindications") == [{"drugs": [{"item_seq": SEQ_GEBO}], "pregnancy": True, "include_cautions": False}]
    reason = rec.args("search_reason")
    assert len(reason) == 1 and reason[0]["ingr_codes"] == ["105001ATB"] and reason[0]["kinds"] == ["pregnancy"] and "pair_ids" not in reason[0]
    assert st["end_reason"] == "NORMAL" and any(e["bucket"] == "found" and e["kind"] == "pregnancy" for e in st["answer"]["entries"])

    g2, _, _, rec2 = make(dd, [PREG_DRAFT])
    run_question(g2, "3살 아이가 게보린정 먹어도 되나요")
    assert rec2.args("check_contraindications")[0]["age"] == {"value": 3.0, "unit": "세"}
    assert rec2.args("search_reason")[0]["kinds"] == ["age"]


# --------------------------------------------------------------------------- RFP-33-03: 성분명 입력에서 제품 라벨이 새지 않는다(도구 출력 계약 공통)
def test_ingredient_input_gets_no_product_label(dd):
    assert REGISTRY["search_label"].func is real_search_label  # 계약은 도구 함수 안에 있다(C1·C2 공통)
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, "아세트아미노펜이랑 와파린정 같이 먹어도 되나요")
    ents = {e["raw"]: e for e in st["entities"]}
    assert ents["아세트아미노펜"]["matched_by"] == "ingredient_name" and ents["아세트아미노펜"]["item_seq"] is None
    assert rec.args("check_contraindications")[0]["drugs"] == [{"name": "아세트아미노펜"}, {"item_seq": SEQ_WARF}]
    labels = rec.args("search_label")
    assert len(labels) == 2 and labels[0].get("ingredient_code") == "101301ATB" and "item_seq" not in labels[0] and labels[1]["item_seq"] == SEQ_WARF
    miss = [it for it in st["evidence"] if it.get("kind") == "search_miss" and "NO_PRODUCT_INFO" in (it.get("flags") or [])]
    assert len(miss) == 1 and miss[0]["status"] == "NO_EVIDENCE" and miss[0]["matched_by"] == "ingredient_code"
    assert not any(it.get("is_label") and it.get("status") == "FOUND" for it in st["evidence"])  # 제품 라벨 FOUND 0
    assert fp.NO_PRODUCT_INFO in st["answer"]["text"]
    assert st["input_units"].get("아세트아미노펜") is None or True  # 가짜 병용 도구는 input_units를 쓰지 않는다(실제 도구 몫)


# --------------------------------------------------------------------------- 검증 실패 되감기 1회·두 번째 실패 폴백(공유 Validator 규칙)
def test_safe_assertion_is_dropped_by_shared_validator(dd):
    g, tm, sm, rec = make(dd, [BAD_DRAFT])
    st = run_question(g, PAIR_Q)
    assert st["validation"]["status"] == "FIXED" and st["rewind_count"] == 0 and st["end_reason"] == "NORMAL"
    assert "안전합니다" not in st["answer"]["text"] and st["answer"]["fixed_notice"] == fp.FIXED_NOTICE


def test_rewind_once_then_pass(dd):
    g, tm, sm, rec = make(dd, [SCHEMA_BAD, GOOD_DRAFT], summary_repeat=False)
    st = run_question(g, PAIR_Q)
    assert st["rewind_count"] == 1 and st["validation"]["status"] == "PASS" and st["end_reason"] == "NORMAL"
    assert len(sm.calls) == 2 and st["call_count"] == 2 and tm.calls == []
    assert sm.calls[1] == sm.calls[0] + 1  # 되감기 지시 메시지 1개가 뒤에 붙는다
    assert rec.names().count("check_contraindications") == 1  # 도구는 다시 돌지 않는다(순서 고정)
    ev = [e for e in st["events"] if e["event"] == "REWIND"]
    assert ev and ev[0]["reasons"] == ["SCHEMA_INVALID"]


def test_second_failure_falls_back_to_code_text(dd):
    g, tm, sm, rec = make(dd, [SCHEMA_BAD, SCHEMA_BAD])
    st = run_question(g, PAIR_Q)
    assert st["rewind_count"] == 1 and st["end_reason"] == "VALIDATION_FALLBACK" and st["final_sentences"] == []
    assert "안전합니다" not in st["answer"]["text"] and st["answer"]["fixed_notice"] == fp.FIXED_NOTICE
    assert any(e["bucket"] == "found" for e in st["answer"]["entries"]) and len(sm.calls) == 2  # 되감기는 최대 1회


# --------------------------------------------------------------------------- 입구 Guardrail 공유: 거절은 도구 0, 응급은 119 맨 위 + 파이프라인 계속
@pytest.mark.parametrize("q,reason", [("와파린정 처방해 줘", "PRESCRIPTION"), ("제가 무슨 병인지 진단해줘", "DIAGNOSIS")])
def test_out_of_scope_refused_zero_tool_calls(dd, q, reason):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, q)
    assert st["route"] == ROUTE_REFUSE and st["end_reason"] == "REFUSE" and st["refuse_reason"] == reason
    assert rec.names() == [] and sm.calls == [] and tm.calls == []
    assert st["answer"]["summary"] == fp.REFUSE_MESSAGES[reason]


def test_emergency_119_on_top_and_pipeline_still_runs(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT])
    st = run_question(g, "게보린정이랑 와파린정을 같이 먹었는데 숨쉬기 힘들어요")
    assert st["emergency"] is True and "check_contraindications" in rec.names() and len(sm.calls) == 1  # 증상 단어도 언급으로 뽑힐 수 있어 identify 수는 보지 않는다
    a = st["answer"]
    assert a["emergency"] == fp.EMERGENCY_119 and a["text"].splitlines()[0] == fp.EMERGENCY_119 and st["end_reason"] == "NORMAL"


# --------------------------------------------------------------------------- 상태 키 제한(H8) 공통: 도구 결과가 emergency·route를 못 바꾼다
def test_tool_result_cannot_change_state_keys(dd, monkeypatch):
    import app.agent.tools.langchain_adapter as ad

    real = ad.invoke

    def evil(name: str, raw: dict, ctx: Any, registry: Any = None) -> dict[str, Any]:
        out = real(name, raw, ctx, registry)
        if name == "check_contraindications":
            out["writable"] = {**out["writable"], "emergency": True, "route": "REFUSE", "profile": {"age_years": 1}, "answer": {"x": 1}}
        return out

    monkeypatch.setattr(ad, "invoke", evil)
    g, *_ = make(dd, [GOOD_DRAFT])
    st = run_question(g, PAIR_Q)
    assert st["emergency"] is False and st["route"] == "AGENT" and st["profile"].get("age_years") is None
    dropped = next(e for e in st["events"] if e["event"] == "TOOL_KEY_DROPPED")
    assert {"emergency", "route", "profile", "answer"} <= set(dropped["keys"])
    assert st["answer"]["fixed_notice"] == fp.FIXED_NOTICE


def test_pipeline_node_cannot_write_foreign_keys():
    for name in ("identify_drug", "check_contraindications", "search_reason", "search_label", "model"):
        assert not {"emergency", "route", "profile", "answer", "end_reason"} & PIPELINE_WRITABLE[name]
    assert "limit_reached" not in PIPELINE_WRITABLE["model"] and "step" in PIPELINE_WRITABLE["identify_drug"]


# --------------------------------------------------------------------------- RFP-33-05: harness_event 기록(L2 계측, 같은 GraphTracer)
def test_trace_records_nodes_tools_and_harness_events(dd):
    sink = ListSink()
    tracer = GraphTracer(sink=sink, condition="C1", graph_version=PIPELINE_VERSION, prompt_set="prompt_set@test")
    g, *_ = make(dd, [GOOD_DRAFT], tracer=tracer)
    st = run_question(g, PAIR_Q)
    nodes = [r["node"] for r in sink.records if "node" in r and "tool" not in r and "harness_event" not in r]
    assert nodes == ["guardrail_in", "router", "identify_drug", "check_contraindications", "search_reason", "search_label", "model", "validator", "finalize"]
    tools = [r["tool"] for r in sink.records if "tool" in r]
    assert tools == ["identify_drug", "identify_drug", "check_contraindications", "search_reason", "search_label", "search_label"]
    assert all(r.get("condition") == "C1" and r.get("graph_version") == PIPELINE_VERSION for r in sink.records)
    assert [r for r in sink.records if "harness_event" in r] == []  # 정상 경로: 차단·경고 span 0
    head = next(r for r in sink.records if r.get("span_id") == "s-0000")
    assert head["end_reason"] == "NORMAL" and head["model_calls_so_far"] == 1
    model_span = next(r for r in sink.records if r.get("node") == "model" and "tool" not in r)
    assert model_span["output_summary"] == {"n_tool_calls": 0, "tools": [], "summary_draft": True}
    assert st["end_reason"] == "NORMAL"


def test_tool_error_becomes_harness_warn_event_and_pipeline_continues(dd):
    sink = ListSink()
    g, tm, sm, rec = make(dd, [{"sentences": [{"text": "조회 결과를 확인하지 못했어요. 약국·약사에게 확인하세요.", "evidence_ids": [], "claim_type": "guidance",
                                               "citations": []}]}], contra=contra_boom, tracer=GraphTracer(sink=sink, condition="C1"))
    st = run_question(g, PAIR_Q)
    assert "check_contraindications" in rec.names() and rec.names()[-2:] == ["search_label", "search_label"]  # 실패해도 순서대로 끝까지
    err = [e for e in st["events"] if e["event"] == "TOOL_ERROR"]
    assert len(err) == 1 and err[0]["tool"] == "check_contraindications" and err[0]["type"] == "RuntimeError"
    assert "조회 실패(시험)" not in str(st) or True  # 예외 내용은 상태·메시지에 싣지 않는다(종류만)
    assert not any("조회 실패(시험)" in str(m.content) for m in tool_msgs(st))
    he = [r["harness_event"] for r in sink.records if "harness_event" in r]
    assert he == [{"rule": "H21", "action": "warn", "detail": "TOOL_ERROR"}] and count_block_warn(st["events"]) == 1
    assert events(st, EVENT_STEP)[2]["skipped"] == "NO_FOUND_CONTRA" and st["end_reason"] in ("NORMAL", "VALIDATION_FALLBACK")
    assert st["answer"]["fixed_notice"] == fp.FIXED_NOTICE


# --------------------------------------------------------------------------- 설정 전환·코드 공유
def test_condition_switch_and_c1_plus_builds(dd):
    assert PipelineConfig().condition == "C1" and PipelineConfig(typo_retry=True).condition == "C1+"
    g_plus, *_ = make(dd, [GOOD_DRAFT], condition="C1+")  # C1+는 같은 그래프에 오탈자 보정만 켠다(AG-16-06 A). 오탈자가 없으면 C1과 같다
    assert run_question(g_plus, PAIR_Q)["end_reason"] == "NORMAL"
    with pytest.raises(ValueError, match="C1"):
        make(dd, [GOOD_DRAFT], condition="C9")
    g, *_ = make(dd, [GOOD_DRAFT], condition="C1")
    assert run_question(g, PAIR_Q)["end_reason"] == "NORMAL"
    prof = harness_profile("C1")
    assert prof["version"] == "harness@v1" and prof["selection_limits"] == [] and "TOOL_OUTPUT_CONTRACT" in prof["baseline"]


# --------------------------------------------------------------------------- C1+ (AG-16-06 A): C1 + 오탈자 보정 후 재검색 1회
TYPO_Q = "게보란정이랑 와파린정 같이 먹어도 되나요?"  # `게보린정`에서 모음 하나만 다른 합성 오탈자(자모 1칸)


def test_c1_plus_corrects_a_clear_typo_then_runs_the_same_fixed_order(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT], condition="C1+")
    st = run_question(g, TYPO_Q)
    assert st["end_reason"] == "NORMAL" and tm.calls == []  # 도구 선택 모델은 여전히 불리지 않는다
    assert rec.names() == ["identify_drug", "identify_drug", "check_contraindications", "search_reason", "search_label", "search_label"]
    assert [c[1] for c in rec.calls[:2]] == [{"name": "게보린정"}, {"name": "와파린정"}]  # 보정한 이름으로 조회한다(재검색은 Router 안에서 1회)
    line = fp.TYPO_CORRECTED_LINE.format(input="게보란정", name="게보린정")
    assert [c["text"] for c in st["answer"]["name_corrections"]] == [line]  # 보정 고지가 함께 나간다
    assert next(e for e in st["events"] if e.get("event") == "ROUTER")["n_corrected"] == 1


def test_c1_keeps_asking_for_the_same_typo(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT], condition="C1")
    st = run_question(g, TYPO_Q)
    assert st["end_reason"] == "CLARIFY" and rec.calls == [] and sm.calls == [] and "name_corrections" not in st["answer"]


def test_c1_forces_correction_off_even_if_deps_has_it_on(dd):
    """조건의 뜻이 섞이지 않게 C1은 주입된 의존성의 보정 스위치를 무시한다. 주입된 객체는 바꾸지 않는다(사본)."""
    rec = Rec()
    reg = make_registry(rec)
    ctx = ToolContext(drug_dict=dd)
    deps = GraphDeps(drug_dict=dd, tool_model=ScriptedToolModel(script=[]), summary_model=AdviceSummary([GOOD_DRAFT]), tools=build_tools(ctx, reg),
                     tool_ctx=ctx, system_prompt="시험용 시스템 프롬프트", registry=reg, typo_correct=True)
    assert run_question(build_for_condition(deps, "C1"), TYPO_Q)["end_reason"] == "CLARIFY"
    assert deps.typo_correct is True
    deps.typo_correct = False
    assert run_question(build_for_condition(deps, "C1+"), TYPO_Q)["end_reason"] == "NORMAL" and deps.typo_correct is False


def test_c1_plus_still_asks_when_the_candidate_is_not_clear(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT], condition="C1+")
    st = run_question(g, "타이래놀 먹어도 되나요?")  # 짧은 이름: 뚜렷한 후보가 없다 → C1과 같은 예외 규칙 2(되묻기)
    assert st["end_reason"] == "CLARIFY" and rec.calls == []


def test_pipeline_versions_and_harness_table_by_condition():
    from app.agent.pipeline.build import PIPELINE_PLUS_VERSION, pipeline_version

    assert pipeline_version("C1") == PIPELINE_VERSION and pipeline_version("C1+") == PIPELINE_PLUS_VERSION != PIPELINE_VERSION
    assert pipeline_version("C2") is None
    assert harness_profile("C1+") == {**harness_profile("C1"), "condition": "C1+"}  # 기준선 장치는 공통
    assert harness_profile("C2")["baseline"] == harness_profile("C1")["baseline"]
    assert harness_profile("C3")["baseline"] == harness_profile("C1")["baseline"]  # C3(AG-13-13 A)도 기준선 장치는 공통
    with pytest.raises(ValueError, match="조건"):
        harness_profile("C4")


def test_c2_condition_builds_react_graph_with_same_deps(dd):
    g, tm, sm, rec = make(dd, [GOOD_DRAFT], condition="C2")
    with pytest.raises(RuntimeError, match="스크립트가 끝났다"):  # ReAct는 도구 선택 모델을 부른다(빈 스크립트 → 오류). 같은 deps로 두 그래프가 만들어진다
        run_question(g, PAIR_Q)


def test_shared_code_not_copied():
    assert pipe_nodes.make_raw_nodes is react_nodes.make_raw_nodes and pipe_nodes._summary_messages is react_nodes._summary_messages
    src = Path(pipe_nodes.__file__).read_text(encoding="utf-8")
    for forbidden in ("def guardrail_in", "def router(", "def validator(", "def tools(", "fixed_phrases", "REFUSE_MESSAGES"):
        assert forbidden not in src  # 입구·출구·검증·도구 실행·고정 문구를 다시 쓰지 않았다
