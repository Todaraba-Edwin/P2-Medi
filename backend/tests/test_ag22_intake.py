"""AG-22: 복용 관련·재복용 질문 감지(AG-22-01·06 A), 주의 3종 조회 코드 규칙(AG-22-04 A), 옛 인자 `include_cautions` 무시(C-1 A).

LLM·원격 호출 없음. 도구 시험은 합성 사전·SQLite(`contract/ag02_synth.py`)로, 그래프 시험은 C1 고정 파이프라인(공유 `tools`·`finalize` 본문)으로 한다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "contract"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ag02_synth import APAP, IBU, WAR, synth_conn, synth_dict  # noqa: E402
from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import guardrail, intake  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.nodes import GraphDeps  # noqa: E402
from app.agent.pipeline.build import build_pipeline, run_question  # noqa: E402
from app.agent.router import ROUTER_WRITABLE_KEYS, route_input  # noqa: E402
from app.agent.tools.context import ToolContext  # noqa: E402
from app.agent.tools.langchain_adapter import build_tools  # noqa: E402
from app.agent.tools.registry import EVENT_ARG_IGNORED, IGNORED_ARGS, REGISTRY, ToolSpec, invoke  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402
from app.db import loaders  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

# --------------------------------------------------------------------------- 감지 패턴(AG-22-01 A·06 A, 시험으로 고정)
REDOSE_YES = [
    "타이레놀을 2정을 점심에 먹었는데 두통이 해결되지 않아 15시인데 먹어도 되니?",  # 사용자 지적 q3(2026-11-19)
    "타이레놀 또 먹어도 돼?",
    "15시인데 먹어도 될까요",
    "두 시간 뒤에 한 번 더 먹어도 돼?",
    "점심에 먹었는데 지금 또 먹어도 되니?",
    "4시간 지났는데 다시 복용해도 되나요",
    "아침에 먹었고 저녁에 먹어도 돼?",
]
REDOSE_NO = [
    "우리 애가 실수로 리스넬정35mg 먹었어. 어떻게 돼?",  # 응급 서술(C-2 A: 복용 관련 질문 아님)
    "아이가 셀콕브렉스캡슐200mg을 물에 풀어서 먹었는데 몇 시간 후에 배가 아파하고 구토해. 위험한 상황인가?",
    "먹었는데 배가 아파",
    "타이레놀 효능 알려줘",
    "게보린정이랑 와파린정 같이 먹어도 되나요?",  # 일반형(복용 관련)이지만 재복용은 아님
]
INTAKE_YES = REDOSE_YES + ["게보린정이랑 와파린정 같이 먹어도 되나요?", "이 약 복용해도 되나요", "아이에게 먹여도 돼요?",
                           "어머니가 드셔도 되나요", "두 약 함께 먹을 때 괜찮나요"]
INTAKE_NO = ["타이레놀 효능 알려줘", "임부금기 등급 M이 무슨 뜻이에요?", "우리 애가 실수로 리스넬정35mg 먹었어. 어떻게 돼?",
             "엄마가 먹는 비바스정을 2살 아들이 실수로 1알 삼켰어. 지금 괜찮나?", "와파린정 부작용이 뭐야"]


@pytest.mark.parametrize("q", REDOSE_YES)
def test_redose_detected(q: str) -> None:
    assert intake.is_redose(q) and intake.is_intake(q)


@pytest.mark.parametrize("q", REDOSE_NO)
def test_redose_not_detected(q: str) -> None:
    assert not intake.is_redose(q)


@pytest.mark.parametrize("q", INTAKE_YES)
def test_intake_detected(q: str) -> None:
    assert intake.is_intake(q)


@pytest.mark.parametrize("q", INTAKE_NO)
def test_intake_not_detected(q: str) -> None:
    assert not intake.is_intake(q)


@pytest.mark.parametrize("q", ["타이레놀 몇 알 더 먹어도 돼?", "얼마나 자주 먹어도 돼요?", "하루에 몇 번 먹어도 되나요"])
def test_dosage_refusal_route_is_unchanged(q: str) -> None:
    """기존 `DOSAGE` 거절 문장은 감지와 상관없이 입구에서 그대로 거절된다(AG-22 §2: 기존 경로 유지)."""
    assert guardrail.guardrail_in(q)["route"] == guardrail.ROUTE_REFUSE
    assert guardrail.classify_scope(q) == "DOSAGE"


def test_intake_module_is_pure() -> None:
    """`router.py`가 가져오는 모듈이라 I/O import가 없어야 한다(`test_ag05_followup`의 허용 목록과 짝)."""
    tree = ast.parse(Path(intake.__file__).read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "re", "collections.abc", "typing"}


# --------------------------------------------------------------------------- 주의 조회 규칙(AG-22-04 A)
@pytest.mark.parametrize("intake_q,age,want", [
    (False, None, set()), (True, None, {"dose"}), (False, 70, {"elderly"}), (True, 65, {"dose", "elderly"}), (True, 64.9, {"dose"}),
])
def test_caution_kinds_rule(intake_q: bool, age: float | None, want: set[str]) -> None:
    state = {"intake_question": intake_q, "profile": {"age_years": age}}
    assert intake.caution_kinds(state) == frozenset(want)
    assert "lactation" not in intake.caution_kinds({**state, "lactating": True})  # 수유 입력 칸이 없어 늘 끔


# --------------------------------------------------------------------------- Router 신호
@pytest.fixture(scope="module")
def sdd() -> DrugDict:
    return synth_dict()


def test_router_sets_intake_and_redose_flags(sdd: DrugDict) -> None:
    assert {"intake_question", "redose_question"} <= ROUTER_WRITABLE_KEYS
    up = route_input("타이레놀정 또 먹어도 돼?", sdd).state_update()
    assert up["intake_question"] is True and up["redose_question"] is True
    up = route_input("타이레놀정 효능 알려줘", sdd).state_update()
    assert up["intake_question"] is False and up["redose_question"] is False
    assert route_input("우리 애가 실수로 타이레놀정 먹었어", sdd, emergency=True).intake_question is False  # C-2 A


# --------------------------------------------------------------------------- 도구: 코드 규칙·옛 인자 무시
def _conn_with_cautions() -> Any:
    c = synth_conn()
    rows = loaders.collect([{"일반명코드": APAP, "일반명(복합제의 경우 1성분만 표시됨)": "acetaminophen", "1일 최대투여량": "합성 시험 값",
                             "공고번호": "1", "공고일자": "2026-07-21"}], loaders.normalize_dose, "caution", "d.csv", loaders.AS_OF_KIDS)
    eld = loaders.collect([{"성분코드": IBU, "성분명": "ibuprofen", "약품상세정보": "합성 시험 문구", "공고번호": "2", "공고일자": "2026-01-01"}],
                          loaders.normalize_elderly, "caution", "e.csv", loaders.AS_OF_HIRA)
    loaders.load_into(c, {"d.csv": rows, "e.csv": eld})
    return c


def _tool_ctx(kinds: frozenset[str]) -> ToolContext:
    return ToolContext(drug_dict=synth_dict(), conn_factory=_conn_with_cautions, api_enabled=False, caution_kinds=kinds)


ARGS = {"drugs": [{"item_seq": "100000001"}, {"item_seq": "100000002"}]}  # 타이레놀정(APAP)·이부정(IBU)


def _kinds(out: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((i["kind"], i["status"]) for i in out["items"] if i["kind"] in ("dose", "lactation", "elderly"))


def test_tool_has_no_include_cautions_arg() -> None:
    assert "include_cautions" not in CheckContraArgs.model_json_schema()["properties"]
    assert IGNORED_ARGS["check_contraindications"] == ("include_cautions",)


def test_tool_queries_only_rule_kinds() -> None:
    assert _kinds(invoke("check_contraindications", ARGS, _tool_ctx(frozenset()))) == []
    dose = _kinds(invoke("check_contraindications", ARGS, _tool_ctx(frozenset({"dose"}))))
    assert dose == [("dose", "FOUND"), ("dose", "NOT_LISTED")]
    both = _kinds(invoke("check_contraindications", ARGS, _tool_ctx(frozenset({"dose", "elderly"}))))
    assert ("elderly", "FOUND") in both and not any(k == "lactation" for k, _ in both)


def test_old_include_cautions_arg_is_dropped_with_count_event() -> None:
    """C-1 A: 들어와도 막지 않고(ARG_SCHEMA 아님) 버리며, 값은 결과에 영향이 없다(코드 규칙만). 이벤트는 개수만."""
    for v in (True, False):
        out = invoke("check_contraindications", {**ARGS, "include_cautions": v}, _tool_ctx(frozenset()))
        assert "error" not in out and _kinds(out) == []
        ev = [e for e in out["writable"]["events"] if e.get("event") == EVENT_ARG_IGNORED]
        assert ev == [{"rule": "H21", "event": EVENT_ARG_IGNORED, "tool": "check_contraindications", "n": 1}]
    plain = invoke("check_contraindications", ARGS, _tool_ctx(frozenset()))
    assert not [e for e in plain["writable"]["events"] if e.get("event") == EVENT_ARG_IGNORED]


def test_same_input_gives_same_entry_count_every_run() -> None:
    """AG-22-04 A 목적: 같은 질문(같은 규칙)이면 주의 행 수가 실행마다 같다(LLM이 고르지 않는다)."""
    counts = {len(invoke("check_contraindications", ARGS, _tool_ctx(frozenset({"dose"})))["items"]) for _ in range(3)}
    assert len(counts) == 1


# --------------------------------------------------------------------------- 그래프(C1, 공유 tools·finalize 본문)
KIDS = [
    {"product_code": "111111111", "name": "타이레놀정500밀리그람(아세트아미노펜)_(500mg/1정)", "ingr_code": "101301ATB", "ingr_name": "acetaminophen", "entp": "A사"},
    {"product_code": "666666666", "name": "와파린정(와파린나트륨)_(2mg/1정)", "ingr_code": "104001ATB", "ingr_name": "warfarin sodium", "entp": "J사"},
]
SEQ_TYL, SEQ_WARF = "000000001", "000000010"
SNAPS = {
    "prmsn": [
        {"item_seq": SEQ_TYL, "item_name": "타이레놀정500밀리그람", "entp_name": "A사", "spclty_pblc": "일반의약품", "item_ingr_name": "Acetaminophen",
         "edi_code": "111111111", "cancel_name": "정상"},
        {"item_seq": SEQ_WARF, "item_name": "와파린정", "entp_name": "J사", "spclty_pblc": "일반의약품", "item_ingr_name": "Warfarin Sodium",
         "edi_code": "666666666", "cancel_name": "정상"},
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}
KDB = "한국의약품안전관리원"


@pytest.fixture(scope="module")
def gdd() -> DrugDict:
    return DrugDict(build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0])


def _contra_rule_fake(seen: list[frozenset[str]]) -> Any:
    def fake(args: Any, ctx: ToolContext) -> dict[str, Any]:
        seen.append(ctx.caution_kinds)
        labels = [d.item_seq or d.name for d in args.drugs]
        items = []
        if "dose" in ctx.caution_kinds:  # 타이레놀(첫 약)만 용량주의 성분
            items.append({"kind": "dose", "status": "FOUND", "subject": labels[:1], "evidence_id": f"dose:{labels[0]}", "source": KDB,
                          "as_of": "2026-07-21", "flags": [], "dataset_key": "dose", "source_kind": "FILE", "drugs": labels[:1],
                          "drug_keys": labels[:1], "cause_codes": ["101301ATB"], "notes": [],
                          "matches": [{"row_key": "rk", "row_evidence_id": f"dose:{labels[0]}#a", "notice_no": "1", "notice_date": "2026-07-21"}]})
        return {"items": items, "known_ids": [i["evidence_id"] for i in items]}
    return fake


def _pipeline(dd: DrugDict, seen: list[frozenset[str]]) -> Any:
    reg = {n: (ToolSpec(n, s.args_model, _contra_rule_fake(seen), s.description) if n == "check_contraindications" else s)
           for n, s in REGISTRY.items()}
    ctx = ToolContext(drug_dict=dd)
    draft = {"sentences": [{"text": "자세한 내용은 약국·약사에게 확인하세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}]}
    deps = GraphDeps(drug_dict=dd, tool_model=ScriptedToolModel(script=[]), summary_model=ScriptedSummary([draft], repeat_last=True),
                     tools=build_tools(ctx, reg), tool_ctx=ctx, system_prompt="시험", registry=reg)
    return build_pipeline(deps)


def test_graph_tools_node_sets_rule_kinds_and_finalize_asks(gdd: DrugDict) -> None:
    seen: list[frozenset[str]] = []
    st = run_question(_pipeline(gdd, seen), "타이레놀정500밀리그람 와파린정 같이 먹어도 되나요?")
    assert seen == [frozenset({"dose"})] and st["intake_question"] is True
    a = st["answer"]
    assert a["dose_check"]["question"] == fp.DOSE_CHECK_QUESTION and a["dose_check"]["options"] == [fp.DOSE_CHECK_YES, fp.DOSE_CHECK_NO]
    assert a["dose_notice"] is None and a["redose_notice"] is None


def test_graph_took_today_yes_gives_notice_without_asking_again(gdd: DrugDict) -> None:
    seen: list[frozenset[str]] = []
    st = run_question(_pipeline(gdd, seen), "타이레놀정500밀리그람 와파린정 같이 먹어도 되나요?", took_today=True)
    a = st["answer"]
    assert a["dose_check"] is None and a["dose_notice"] == fp.DOSE_NOTICE
    assert "took_today" not in str(st.get("events"))  # 답은 이벤트에 남지 않는다(AG-22-05 A)


def test_graph_info_question_does_not_query_dose(gdd: DrugDict) -> None:
    """회귀 범위: 복용 관련 질문이 아니고 나이 65 미만이면 주의 3종을 조회하지 않는다 = 이전 `include_cautions=False` 실행과 같은 항목."""
    seen: list[frozenset[str]] = []
    st = run_question(_pipeline(gdd, seen), "타이레놀정500밀리그람 와파린정 효능 알려줘")
    assert all(k == frozenset() for k in seen)
    assert st["answer"]["dose_check"] is None and not any(e.get("kind") == "dose" for e in st["answer"]["entries"])


def test_graph_emergency_accidental_intake_does_not_query_dose(gdd: DrugDict) -> None:
    """C-2 A: "실수로 먹었어"(응급 서술)는 복용 관련 질문이 아니라 용량주의를 조회하지 않는다. 119는 그대로 맨 위."""
    seen: list[frozenset[str]] = []
    st = run_question(_pipeline(gdd, seen), "우리 애가 실수로 타이레놀정500밀리그람 먹었어. 어떻게 돼?")
    assert all("dose" not in k for k in seen) and st["answer"]["dose_check"] is None
    if st["answer"].get("emergency"):
        assert st["answer"]["text"].splitlines()[0] == fp.EMERGENCY_119


def test_graph_redose_question_gets_fixed_line_outside_summary(gdd: DrugDict) -> None:
    seen: list[frozenset[str]] = []
    st = run_question(_pipeline(gdd, seen), "타이레놀정500밀리그람 점심에 먹었는데 15시인데 또 먹어도 되니?")
    a = st["answer"]
    assert st["redose_question"] is True and a["redose_notice"] == fp.REDOSE_NOTICE
    assert fp.REDOSE_NOTICE not in (a.get("summary") or "")  # judge·평가가 읽는 summary는 그대로
    assert a["entries"]  # 거절로 끝나지 않고 조회 결과를 낸다


def test_wiring_api_and_c1_share_rule() -> None:
    """요청마다 새 ToolContext(`service.request_deps`)라 이전 요청의 규칙 값이 남지 않는다: 기본값은 빈 집합."""
    assert ToolContext(drug_dict=synth_dict()).caution_kinds == frozenset()
    assert WAR and IBU  # 합성 코드 상수(가져오기 확인)
