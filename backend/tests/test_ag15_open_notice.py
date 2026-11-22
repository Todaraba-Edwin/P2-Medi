"""AG-15(축소, 〔D9〕A·〔D10〕A·〔D11〕A, 2026-11-22): 약 이름 없는 질문의 사전 안내(찾음/찾을 수 없음 + 판단 고지).

LLM·네트워크·DB 호출 0. 사전은 합성 소사전(`tests/e2e/golden_synth.py`)에 허가정보 효능군 `product_type` 칸만 채운 것이다.
시험 질문은 모두 합성이다(평가 세트·시험셋 문항 아님). 가짜 모델은 한 번이라도 불리면 오류를 낸다(모델 호출 0을 구조로 확인).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import guardrail as G  # noqa: E402
from app.agent import open_question as OQ  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.nodes import GraphDeps, after_router  # noqa: E402
from app.agent.graph.state import END_NORMAL, END_REFUSE, NODE_WRITABLE, AgentState  # noqa: E402
from app.agent.pipeline.build import build_pipeline  # noqa: E402
from app.agent.pipeline.build import run_question as run_pipeline  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.langchain_adapter import build_tools  # noqa: E402
from app.agent.tools.registry import REGISTRY, ToolSpec  # noqa: E402
from app.api.schemas import to_chat_response  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

PAIN_Q = "임신 중 피해야 할 진통제 알려줘"
COLD_Q = "아이한테 먹이면 안 되는 감기약 있나요"

PAIN_TYPE = "[01140]해열.진통.소염제"
DIGEST_TYPE = "[02330]건위소화제"


@pytest.fixture()
def dd() -> DrugDict:
    """합성 소사전 + 효능군 칸. 해열·진통·소염제 제품 3행 중 1행은 취소(집계 제외) → 제품 수 2."""
    d = golden_dict()
    types = {"타이레놀정500밀리그람": PAIN_TYPE, "어린이타이레놀현탁액": PAIN_TYPE, "타이레놀콜드-에스정": PAIN_TYPE, "이지렉트정1.0밀리그램": DIGEST_TYPE}
    for p in d.products:
        p["product_type"] = types[p["name"]]
    d.products[2]["cancelled"] = True  # 어린이타이레놀현탁액
    return d


class Rec:
    def __init__(self) -> None:
        self.calls: list[str] = []


def make_deps(dd: DrugDict, rec: Rec) -> tuple[GraphDeps, ScriptedToolModel, ScriptedSummary]:
    reg: dict[str, ToolSpec] = {}
    for name, spec in REGISTRY.items():
        def wrapped(args: Any, ctx: ToolContext, _f: Any = spec.func, _n: str = name) -> dict[str, Any]:
            rec.calls.append(_n)
            return _f(args, ctx)
        reg[name] = ToolSpec(name, spec.args_model, wrapped, spec.description)
    ctx = ToolContext(drug_dict=dd)
    tm = ScriptedToolModel(script=[])  # 불리면 RuntimeError
    sm = ScriptedSummary([], repeat_last=False)  # 불리면 RuntimeError
    deps = GraphDeps(drug_dict=dd, tool_model=tm, summary_model=sm, tools=build_tools(ctx, reg), tool_ctx=ctx,
                     system_prompt="시험용 시스템 프롬프트", registry=reg)
    return deps, tm, sm


def expected_found(cls: str, n: str) -> str:
    return f"{fp.OPEN_CLASS_FOUND.format(cls=cls, n=n)} {fp.UNIDENTIFIED_NEXT}. {fp.OPEN_GUIDE_ONLY}"


EXPECTED_NOT_FOUND = f"{fp.OPEN_NOT_FOUND} {fp.UNIDENTIFIED_NEXT}. {fp.OPEN_GUIDE_ONLY}"


def assert_no_judgment(answer: dict[str, Any]) -> None:
    """금기 목록·성분 목록·근거 상세·배지·"금기 목록에 없음" 표시가 없다."""
    assert answer["entries"] == [] and answer["detail"] == [] and answer["badges"] == [] and answer["product_rows"] == []
    assert answer["citations"] == [] and answer["not_checked_lines"] == [] and answer["pharmacist_advice"] == []
    assert fp.NOT_LISTED not in answer["text"] and "금기 목록에 없음" not in answer["text"]
    assert answer["emergency"] is None and answer["route"] == "AGENT"
    assert answer["fixed_notice"] == fp.FIXED_NOTICE and answer["disclaimer"] == fp.DISCLAIMER


# --------------------------------------------------------------------------- 모듈(순수 함수)
def test_lookup_found_uses_alias_table_and_counts_non_cancelled(dd):
    got = OQ.open_lookup(PAIN_Q, dd)
    assert got == OQ.OpenLookup(found=True, class_code="01140", class_name="해열·진통·소염제", n_products=2)
    assert OQ.open_lookup("임산부가 먹으면 안 되는 소화제", dd).class_code == "02330"


@pytest.mark.parametrize("q", [COLD_Q, "임신 중 피해야 할 약", "변비약 먹어도 되나요"])  # 감기약: 별칭 없음 / 낱말 없음 / 사전에 분류 제품 없음
def test_lookup_not_found(dd, q):
    assert OQ.open_lookup(q, dd) == OQ.OpenLookup(found=False)


def test_alias_matches_only_word_start_and_class_names_are_not_widened(dd):
    assert OQ.match_alias("진통제가 뭐예요") == "01140" and OQ.match_alias("소염진통제는") == "01140"
    assert OQ.match_alias("해열.진통.소염제") is None  # 분류 이름 자체는 별칭이 아니다(부분 일치로 넓히지 않음)
    assert OQ.match_alias("임부용진통제") is None  # 낱말 첫머리가 아니면 맞추지 않는다


def test_class_index_cached_per_dict_and_version(dd):
    a = OQ.class_index(dd)
    assert OQ.class_index(dd) is a
    dd.meta["version"] = "other"
    assert OQ.class_index(dd) is not a


def test_compose_summary_is_approved_text_joined(dd):
    assert OQ.compose_summary(OQ.open_lookup(PAIN_Q, dd)) == expected_found("해열·진통·소염제", "2")
    assert OQ.compose_summary({"found": True, "class_name": "해열·진통·소염제", "n_products": 2769}) == expected_found("해열·진통·소염제", "2,769")
    assert OQ.compose_summary(OQ.OpenLookup(found=False)) == EXPECTED_NOT_FOUND


# --------------------------------------------------------------------------- Router
def test_router_attaches_open_lookup_only_under_conditions(dd):
    res = R.route_input(PAIN_Q, dd)
    assert res.entities == [] and R.INTENT_OPEN in res.intent and res.open_lookup == {
        "found": True, "class_code": "01140", "class_name": "해열·진통·소염제", "n_products": 2}
    upd = res.state_update()
    assert set(upd) == R.ROUTER_WRITABLE_KEYS | {"open_lookup"} and set(upd) <= NODE_WRITABLE["router"]
    assert "open_lookup" in AgentState.__annotations__
    assert R.route_input(COLD_Q, dd).open_lookup == {"found": False, "class_code": None, "class_name": None, "n_products": 0}


@pytest.mark.parametrize("q, kw", [
    ("타이레놀정500밀리그람 임신 중 먹어도 되나요", {}),  # 약 이름 있음
    ("임부금기 2등급이 뭐예요", {}),  # document 라벨
    ("진통제 등급 기준이 뭐예요", {}),  # open + document
    (PAIN_Q, {"emergency": True}),  # 응급 + 약 없음: 지금 경로(emergency_no_drug) 유지
    (PAIN_Q, {"guardrail_route": "REFUSE"}),  # 입구 거절
])
def test_router_no_key_outside_conditions(dd, q, kw):
    res = R.route_input(q, dd, **kw)
    assert res.open_lookup is None
    upd = res.state_update()
    assert "open_lookup" not in upd and set(upd) == R.ROUTER_WRITABLE_KEYS  # 기존 키 집합 그대로


def test_router_no_key_when_clarifying(dd):
    res = R.route_input("타이레놀 먹어도 되나요", dd)  # 여러 제품 → 되묻기
    assert res.ambiguous and res.open_lookup is None and "open_lookup" not in res.state_update()


def test_after_router_edges():
    assert after_router({"ambiguous": False}) == "model"
    assert after_router({"ambiguous": True}) == "finalize"
    assert after_router({"ambiguous": False, "open_lookup": {"found": False}}) == "finalize"
    assert after_router({"ambiguous": False, "open_lookup": None}) == "model"


# --------------------------------------------------------------------------- 그래프(ReAct) 끝까지
def _router_event(st: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in st["events"] if e.get("event") == "ROUTER")


def test_graph_found_ends_with_code_text_without_model_or_tools(dd):
    rec = Rec()
    deps, tm, sm = make_deps(dd, rec)
    st = run_question(build_graph(deps), PAIN_Q)
    assert st["end_reason"] == END_NORMAL and tm.calls == [] and sm.calls == [] and rec.calls == [] and st.get("call_count") == 0
    a = st["answer"]
    assert a["summary"] == expected_found("해열·진통·소염제", "2")
    assert_no_judgment(a)
    ev = _router_event(st)
    assert ev["open_hit"] is True and "해열" not in str(ev) and PAIN_Q not in str(ev)  # 찾음 여부만
    out = to_chat_response(a, end_reason=st["end_reason"], clarify=st.get("clarify"), entities=st.get("entities"))
    assert out.end_reason == "NORMAL" and out.summary == a["summary"]


def test_graph_not_found(dd):
    rec = Rec()
    deps, tm, sm = make_deps(dd, rec)
    st = run_question(build_graph(deps), COLD_Q)
    assert st["end_reason"] == END_NORMAL and tm.calls == [] and sm.calls == [] and rec.calls == []
    assert st["answer"]["summary"] == EXPECTED_NOT_FOUND
    assert_no_judgment(st["answer"])
    assert _router_event(st)["open_hit"] is False
    assert fp.PREGNANCY_NOT_CHECKED not in st["answer"]["text"]  # finalize_extra 줄이 붙지 않는다


def test_graph_entry_refusal_unchanged(dd):
    rec = Rec()
    deps, tm, sm = make_deps(dd, rec)
    st = run_question(build_graph(deps), "진통제 처방해줘")
    assert st["end_reason"] == END_REFUSE and "open_lookup" not in st and tm.calls == []


def test_router_event_shape_unchanged_outside(dd):
    """조건 밖 질문의 ROUTER 이벤트에는 `open_hit` 키가 없다(되묻기 경로로 확인, 모델 호출 0)."""
    rec = Rec()
    deps, tm, _ = make_deps(dd, rec)
    st = run_question(build_graph(deps), "타이레놀 먹어도 되나요")
    assert st["end_reason"] == "CLARIFY" and "open_hit" not in _router_event(st) and "open_lookup" not in st


# --------------------------------------------------------------------------- C1 고정 파이프라인
@pytest.mark.parametrize("q, summary", [(PAIN_Q, expected_found("해열·진통·소염제", "2")), (COLD_Q, EXPECTED_NOT_FOUND)])
def test_c1_pipeline_also_ends_at_finalize(dd, q, summary):
    rec = Rec()
    deps, tm, sm = make_deps(dd, rec)
    st = run_pipeline(build_pipeline(deps), q)
    assert st["end_reason"] == END_NORMAL and tm.calls == [] and sm.calls == [] and rec.calls == []
    assert st["answer"]["summary"] == summary
    assert_no_judgment(st["answer"])


# --------------------------------------------------------------------------- 고정 문구 원문
APPROVED = {
    "OPEN_CLASS_FOUND": "질문에 약 이름은 없지만, 약 사전에서 '{cls}' 분류를 찾았어요(제품 {n}개). 분류만으로는 어떤 약이 금기인지 하나씩 확인할 수 없어요.",
    "OPEN_NOT_FOUND": "질문에서 약 이름이나 약 분류를 약 사전에서 찾을 수 없었어요. 그래서 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요.",
    "OPEN_GUIDE_ONLY": "이 서비스는 찾은 자료를 안내하는 것이 목적이고, 복용 여부의 판단은 사용자의 몫이에요. 판단하기 전에 약국·약사에게 확인하세요.",
}


def test_open_phrases_are_one_line_literals_with_approved_text():
    src = (Path(fp.__file__)).read_text(encoding="utf-8")
    for name, text in APPROVED.items():
        lines = [ln for ln in src.splitlines() if ln.startswith(f"{name} =")]
        assert len(lines) == 1 and re.fullmatch(rf'^{name} = "[^"]+"$', lines[0]), name
        assert getattr(fp, name) == text
        assert not any(t in text for t in fp.FORBIDDEN_SCREEN_TERMS)
    assert "OPEN_CLASS_FOUND" not in fp.DRAFT_KEYS


# --------------------------------------------------------------------------- 순수 함수 범위(import·I/O)
_OQ_ALLOWED = {"__future__", "re", "weakref", "dataclasses", "typing", "app.agent", "app.tools.drug_dict"}
_IO_NAMES = {"open", "print", "exec", "eval", "__import__"}
_IO_ATTRS = {"write_text", "write_bytes", "write", "getLogger", "connect", "execute", "dump", "urlopen", "Popen", "system", "invoke"}


def test_open_question_module_is_pure():
    tree = ast.parse(Path(OQ.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            if node.module == "app.agent":
                assert {a.name for a in node.names} == {"fixed_phrases"}
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in _IO_NAMES
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in _IO_ATTRS
    assert imported <= _OQ_ALLOWED, imported - _OQ_ALLOWED


def test_router_refuse_literal_matches_guardrail():
    assert R._GUARDRAIL_REFUSE == G.ROUTE_REFUSE
