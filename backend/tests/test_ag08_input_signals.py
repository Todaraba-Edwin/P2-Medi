"""AG-08 goal 1회차 후속 입력 신호 2칸(레인 A, 2026-11-17): `Ingredient.code_missing_text`·`Finding.age_info_line`의 값 경로.

LLM·공공 API·원격 DB 호출 0. 그래프 시험은 합성 소사전(`e2e/golden_synth.py`)과 각본 모델로 돈다.
- 성분코드: 사전이 준 `code_status`만 옮긴다(`none` → `ABSENT` 안내, `linked`이고 성분 하나·코드 하나면 `code`, 그 밖은 비움).
- 연령금기 안내 줄: 나이를 특정할 수 없고(`age_unknown`) 나이 기준 값이 있는 연령금기 줄에만 상수 `AGE_INFO_LINE`이 붙는다.
  지금 도구는 나이가 없으면 연령금기 항목을 만들지 않으므로 실제 그래프 경로에서는 None이 유지된다(값 경로만 열림).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph import nodes as nodes_mod  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api.schemas import ChatResponse, response_from_state, to_chat_response  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

KIDS = "한국의약품안전관리원"


# --------------------------------------------------------------------------- 합성 항목
def _ident(name: str = "가나다정500", ingredients: tuple[str, ...] = ("아세트아미노펜",), *, code_status: str | None = "linked",
           kids_codes: tuple[str, ...] = ("101301ATB",)) -> dict[str, Any]:
    return {"kind": "identify", "status": "FOUND", "subject": [name], "evidence_id": f"identify:{name}", "source": "식약처", "as_of": "2026-11-01",
            "flags": [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": name, "matched_by": "product_name",
            "ingredients": [{"display": n, "name_ko": n} for n in ingredients], "code_status": code_status, "kids_codes": list(kids_codes)}


def _age(status: str = "FOUND", rows: tuple[tuple[int, str, str], ...] = ((12, "세", "미만"),), *, given: list[str] | None = None) -> dict[str, Any]:
    matches = [{"age_value": v, "age_unit": u, "age_cond": c, "row_key": f"r{i}", "row_evidence_id": f"age:1#{i}"} for i, (v, u, c) in enumerate(rows)]
    it: dict[str, Any] = {"kind": "age", "status": status, "subject": ["444444ATB"], "evidence_id": "age:1", "source": KIDS, "as_of": "2026-07-21",
                          "flags": [], "matches": matches if status == "FOUND" else [], "dataset_key": "age", "source_kind": "FILE"}
    if given is not None:
        it["age_criteria"] = given
    return it


def _ingredients(resp: dict[str, Any]) -> list[dict[str, Any]]:
    return resp["entries"][0]["ingredients"]


# --------------------------------------------------------------------------- code_missing_text
def test_code_status_none_gives_absent_text_to_every_ingredient():
    resp = finalize([_ident(ingredients=("아세트아미노펜", "슈도에페드린"), code_status="none", kids_codes=())], None, emergency=False)
    ing = _ingredients(resp)
    assert [i["name"] for i in ing] == ["아세트아미노펜", "슈도에페드린"]
    assert all(i.get("code") is None and i["code_missing_text"] == fp.INGR_CODE_MISSING_TEXT["ABSENT"] for i in ing)
    f = to_chat_response(resp).findings[0]
    assert [x.code_missing_text for x in f.ingredients] == [fp.INGR_CODE_MISSING_TEXT["ABSENT"]] * 2 and all(x.code is None for x in f.ingredients)


def test_linked_single_ingredient_single_code_carries_code_without_text():
    resp = finalize([_ident()], None, emergency=False)
    assert _ingredients(resp) == [{"name": "아세트아미노펜", "code": "101301ATB"}]
    x = to_chat_response(resp).findings[0].ingredients[0]
    assert x.code == "101301ATB" and x.code_missing_text is None


@pytest.mark.parametrize("kw", [
    {"ingredients": ("아세트아미노펜", "슈도에페드린"), "kids_codes": ("254000ATB", "448001ATB")},  # 성분·코드 여럿: 짝을 모른다
    {"ingredients": ("아세트아미노펜", "슈도에페드린"), "kids_codes": ("254000ATB",)},             # 덩어리 코드 하나에 성분 둘
    {"code_status": "component_only", "kids_codes": ()},                                            # 성분 단위 부분 연결
    {"code_status": None, "kids_codes": ()},                                                        # 신호 없음(옛 항목 모양)
])
def test_unknown_pairing_leaves_code_and_text_empty(kw):
    resp = finalize([_ident(**kw)], None, emergency=False)
    assert all(set(i) == {"name"} for i in _ingredients(resp))
    assert all(x.code is None and x.code_missing_text is None for x in to_chat_response(resp).findings[0].ingredients)


def test_code_text_is_the_approved_constant_only():
    resp = finalize([_ident(code_status="none", kids_codes=())], None, emergency=False)
    assert _ingredients(resp)[0]["code_missing_text"] == "성분코드는 자료에 적혀 있지 않아요"  # AG-08 §5 승인 표 7-3 ①
    assert fp.INGR_CODE_MISSING_TEXT["FETCH_FAIL"] not in resp["text"]  # 파일 사전에는 "불러오지 못함" 경로가 없다


# --------------------------------------------------------------------------- age_info_line
def test_age_unknown_puts_info_line_only_on_age_rows_with_criteria():
    resp = finalize([_age(), _ident()], None, emergency=False, age_unknown=True)
    age_row = next(e for e in resp["entries"] if e["kind"] == "age")
    assert age_row["age_criteria"] == ["12세 미만"] and age_row["age_info_line"] == fp.AGE_INFO_LINE
    assert all("age_info_line" not in e for e in resp["entries"] if e["kind"] != "age")
    f = next(x for x in to_chat_response(resp).findings if x.kind == "age")
    assert f.age_info_line == fp.AGE_INFO_LINE and f.age_criteria == ["12세 미만"]
    assert resp["text"].index(fp.AGE_INFO_LINE) < resp["text"].index("12세 미만")  # 안내 줄은 값 위에


def test_age_known_or_no_criteria_keeps_line_none():
    assert "age_info_line" not in finalize([_age()], None, emergency=False)["entries"][0]
    assert "age_info_line" not in finalize([_age()], None, emergency=False, age_unknown=False)["entries"][0]
    assert "age_info_line" not in finalize([_age(status="NOT_LISTED")], None, emergency=False, age_unknown=True)["entries"][0]
    no_val = _age()
    no_val["matches"] = [{"age_value": None, "age_unit": "세", "age_cond": "미만", "row_key": "r", "row_evidence_id": "age:1#0"}]
    assert "age_info_line" not in finalize([no_val], None, emergency=False, age_unknown=True)["entries"][0]


def test_tool_given_criteria_on_non_found_age_item_flow_through_when_age_unknown():
    """나이 미특정 때 '원문 값만 담은' 항목(모양은 AG-02 결정 뒤): 도구가 `age_criteria`를 직접 주면 판정 묶음과 상관없이 값·안내 줄이 붙는다."""
    it = _age(status="UNIDENTIFIED", given=["만 12세 미만", "만 2세 미만"])
    it["flags"] = ["CODE_NOT_LINKED"]
    e = finalize([it], None, emergency=False, age_unknown=True)["entries"][0]
    assert e["bucket"] == "unconfirmed" and e["age_criteria"] == ["만 12세 미만", "만 2세 미만"] and e["age_info_line"] == fp.AGE_INFO_LINE
    assert "age_info_line" not in finalize([it], None, emergency=False)["entries"][0]  # 나이를 알면 안내 줄 없음(값은 그대로)
    f = to_chat_response(finalize([it], None, emergency=False, age_unknown=True)).findings[0]
    assert f.badges == [] and f.age_info_line == fp.AGE_INFO_LINE


def test_age_line_never_on_matches_only_non_found_rows():
    """판정 묶음 밖의 연령금기 항목은 조회 행에서 값을 만들어 내지 않는다(명시 목록이 있을 때만)."""
    it = _age()
    it["flags"] = ["LOOKUP_FAILED"]
    e = finalize([it], None, emergency=False, age_unknown=True)["entries"][0]
    assert e["bucket"] == "unconfirmed" and "age_criteria" not in e and "age_info_line" not in e


# --------------------------------------------------------------------------- 그래프 배선(nodes.finalize_extra)
T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
PAIR_DRAFT = {"sentences": [{"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact",
                             "citations": []}, GUIDE]}


def _script(a: str, b: str) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _run(dd: DrugDict, q: str, *, profile: dict[str, Any] | None) -> tuple[dict[str, Any], ChatResponse]:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=_script(AZI, COLD)), summary_model=ScriptedSummary([PAIR_DRAFT]),
                      system_prompt="시험용 시스템 프롬프트")
    st = run_question(build_graph(deps), q, profile)
    return st, response_from_state(st)


@pytest.mark.parametrize("profile, expected", [(None, True), ({"age_years": 30.0, "pregnant": False}, False), ({"pregnant": False}, True)])
def test_graph_passes_age_unknown_only_when_no_single_age(dd, monkeypatch, profile, expected):
    seen: list[bool] = []
    real = nodes_mod.finalize

    def spy(*a: Any, **kw: Any) -> dict[str, Any]:
        seen.append(bool(kw.get("age_unknown")))
        return real(*a, **kw)

    monkeypatch.setattr(nodes_mod, "finalize", spy)
    st, resp = _run(dd, Q_PAIR, profile=profile)
    assert st["end_reason"] == "NORMAL" and seen == [expected]
    # 지금 도구는 나이가 없으면 연령금기 항목을 만들지 않는다: 실제 경로에서 안내 줄은 None 유지, 성분 칸은 사전 코드만
    assert all(f.age_info_line is None for f in resp.findings)
    ident = [f for f in resp.findings if f.kind == "identify"]
    assert ident and all(x.code_missing_text is None for f in ident for x in f.ingredients)
    assert any(x.code == "625201ATB" for f in ident for x in f.ingredients)  # 성분 하나·코드 하나(이지렉트정)
    assert all(x.code is None for f in ident for x in f.ingredients if x.name != "라사길린")  # 콜드-에스: 성분 넷·코드 둘 → 비움


def test_graph_dict_without_code_marks_ingredients_absent(dd, monkeypatch):
    """사전이 코드를 못 붙인 제품(`code_status == "none"`)이면 식별 줄 성분마다 승인 안내 문구가 붙는다."""
    data = {"meta": dict(dd.meta), "products": [dict(p) for p in dd.products], "ingredients": [dict(i) for i in dd.ingredients]}
    for p in data["products"]:
        if p["name"] == AZI:
            p["kids_codes"], p["code_link"] = [], ""
    dd2 = DrugDict(data)
    st, resp = _run(dd2, Q_PAIR, profile=None)
    azi = next(f for f in resp.findings if f.kind == "identify" and f.drug == AZI)
    assert [x.code_missing_text for x in azi.ingredients] == [fp.INGR_CODE_MISSING_TEXT["ABSENT"]] and azi.ingredients[0].code is None
    cold = next(f for f in resp.findings if f.kind == "identify" and f.drug == COLD)
    assert all(x.code_missing_text is None for x in cold.ingredients)
