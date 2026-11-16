"""AG-01 `finalize` 입력 연결 시험(goal 2회차 §2-3·4): `not_checked`(FE-07-16 B·AG-08-18 A)와 `grade_defs`(BE-06-16 A·PRD-09-04·PRD-15-03).

LLM·공공 API·원격 DB 호출 0. 도구 본문은 실제, 데이터는 합성 소사전(`e2e/golden_synth.py`), 고시 청크는 합성 fixture다(실제 jsonl을 읽지 않는다).
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
from app.agent.finalize import pregnancy_found_grades  # noqa: E402
from app.agent.grade_defs import GRADE_LOCATORS, corpus_grade_def_fn, grade_def_inputs  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.tools.corpus import CorpusIndex  # noqa: E402
from app.api.schemas import ChatResponse, response_from_state  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
Q_PREG = f"임신 14주인데 열이 나요. 집에 {T500}이랑 {COLD}이 있는데 먹어도 되나요?"
Q_NOT_PREG = f"임신은 아니에요. {AZI}이랑 {COLD}을 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"


def _script(a: str, b: str, **check: Any) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}], **check}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


def _fact(text: str, *eids: str) -> dict[str, Any]:
    return {"text": text, "evidence_ids": list(eids), "claim_type": "fact", "citations": []}


GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
PAIR_DRAFT = {"sentences": [_fact("두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", PAIR_EID), GUIDE]}
PREG_DRAFT = {"sentences": [_fact("타이레놀콜드-에스정에 든 성분이 임부금기 목록에 올라 있어요.", "pregnancy:448001ATB"), GUIDE]}
BAD_DRAFT = {"sentences": [_fact("이 조합은 안전합니다.", PAIR_EID)]}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _run(dd: DrugDict, q: str, script: list[AIMessage], drafts: list[Any], *, profile: dict[str, Any] | None = None,
         repeat_last: bool = False, **deps_kw: Any) -> tuple[dict[str, Any], ChatResponse]:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=list(script), repeat_last=repeat_last), summary_model=ScriptedSummary(drafts),
                      system_prompt="시험용 시스템 프롬프트", **deps_kw)
    st = run_question(build_graph(deps), q, profile)
    return st, response_from_state(st)


# --------------------------------------------------------------------------- §2-3 not_checked
def test_pregnancy_unknown_adds_not_checked_line_and_fixed_advice(dd):
    st, r = _run(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT])
    assert st["end_reason"] == "NORMAL" and st["profile"]["pregnant"] is None
    assert r.not_checked_lines == [fp.PREGNANCY_NOT_CHECKED]
    assert st["answer"]["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED  # 확인하지 못한 종류가 있으면 고정 영역 한 줄이 켜진다
    assert r.fixed_notice == [fp.PHARMACIST_ADVICE_FIXED, fp.FIXED_NOTICE]
    assert fp.PREGNANCY_NOT_CHECKED in st["answer"]["text"]
    # 판정은 그대로다(줄 표시만)
    assert {it["evidence_id"]: it["status"] for it in st["evidence"]}[PAIR_EID] == "FOUND"


@pytest.mark.parametrize("q,profile", [(Q_NOT_PREG, None), (Q_PAIR, {"age_years": None, "pregnant": False})])
def test_not_pregnant_has_no_line(dd, q, profile):
    st, r = _run(dd, q, _script(AZI, COLD), [PAIR_DRAFT], profile=profile)
    assert st["end_reason"] == "NORMAL" and st["profile"]["pregnant"] is False
    assert r.not_checked_lines == [] and st["answer"]["pharmacist_advice_fixed"] is None


@pytest.mark.parametrize("q,profile", [(Q_PREG, None), (Q_PAIR.replace("엄마가", "제가"), {"age_years": None, "pregnant": True})])
def test_pregnant_has_no_line(dd, q, profile):
    a, b = (T500, COLD) if profile is None else (AZI, COLD)
    st, r = _run(dd, q, _script(a, b, pregnancy=True), [PREG_DRAFT], profile=profile)
    assert st["profile"]["pregnant"] is True and r.not_checked_lines == []


def test_refuse_and_clarify_have_no_line(dd):
    st, r = _run(dd, f"{AZI} 처방해 줘", [], [])
    assert st["end_reason"] == "REFUSE" and r.not_checked_lines == []
    st, r = _run(dd, "엄마가 이지렉트정을 드시는데 타이레놀 콜드-에스를 같이 먹어도 되나요?", [], [])
    assert st["end_reason"] == "CLARIFY" and r.not_checked_lines == []
    st, r = _run(dd, f"숨쉬기 힘들어요. {AZI}을 한 통 다 먹었는데 끊어도 되나요", _script(AZI, COLD), [PAIR_DRAFT])
    assert st["emergency"] and st["answer"]["route"] == "REFUSE" and r.not_checked_lines == []  # 응급+범위 외도 거절 경로다


def test_limit_and_fallback_paths_also_carry_the_line(dd):
    always = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "x1")])]
    st, r = _run(dd, Q_PAIR, always, [PAIR_DRAFT], repeat_last=True)
    assert st["end_reason"] == "LIMIT" and r.not_checked_lines == [fp.PREGNANCY_NOT_CHECKED]
    st, r = _run(dd, Q_PAIR, [*_script(AZI, COLD), AIMessage("다시 정리")], [BAD_DRAFT, BAD_DRAFT])
    assert st["end_reason"] == "VALIDATION_FALLBACK" and r.not_checked_lines == [fp.PREGNANCY_NOT_CHECKED]


def test_no_line_when_pregnancy_was_actually_checked_without_profile(dd):
    """프로필에 임신 여부가 없어도 모델이 임부금기 조회를 돌렸으면(임부금기 항목이 있으면) "확인하지 못했어요" 줄을 내지 않는다(결과와 모순 방지)."""
    q = f"열이 나요. 집에 {T500}이랑 {COLD}이 있는데 먹어도 되나요?"
    st, r = _run(dd, q, _script(T500, COLD, pregnancy=True), [PREG_DRAFT])
    assert st["profile"]["pregnant"] is None and any(it["kind"] == "pregnancy" for it in st["evidence"])
    assert r.not_checked_lines == []


# --------------------------------------------------------------------------- §2-4 grade_defs
TITLE = "의약품 병용금기 성분 등의 지정에 관한 규정"
DEF_1 = "합성 정의 문장 하나: 원칙적으로 사용금지"
DEF_2 = "합성 정의 문장 둘: 원칙적으로 사용금지. 다만, 합성 예외 문장."


def _chunk(cid: str, locator: str, text: str, base_date: str = "2026-07-21", **kw: Any) -> dict[str, Any]:
    return {"chunk_id": cid, "chunk_kind": "l1_notice_sub", "parent_id": None, "refs": [], "pair_id": None, "layer": "L1", "issuer": "식품의약품안전처",
            "doc_type": "고시", "notice_no": "20260052", "base_date": base_date, "locator": locator, "ingr_codes": [], "ingr_names": [],
            "text": text, "source_ref": f"{TITLE}|합성.md", "item_seq": "", "item_name": "", "section": "", **kw}


CHUNKS = [
    _chunk("s-head", "제3조 제3호", '[제3조(정의)] 제3호 "임부금기성분"이란 합성 머리 문장.', chunk_kind="l1_notice_item"),
    _chunk("s-old2", "제3조 제3호 나목", "[제3조(정의) 제3호] 나. 2등급: 옛 합성 문장", base_date="2020-01-01"),
    _chunk("s-ga", "제3조 제3호 가목", f"[제3조(정의) 제3호] 가. 1등급: {DEF_1}"),
    _chunk("s-na", "제3조 제3호 나목", f"[제3조(정의) 제3호] 나. 2등급: {DEF_2}"),
    _chunk("s-l2", "제3조 제3호 나목", "[다른 계층] 나. 2등급: 계층이 달라 쓰지 않는 문장", layer="L2"),
]


@pytest.fixture(scope="module")
def grade_fn():
    return corpus_grade_def_fn(CorpusIndex(CHUNKS))


def test_corpus_grade_def_is_verbatim_substring_of_latest_chunk(grade_fn):
    one, two = grade_fn("1"), grade_fn("2")
    assert one == {"text": DEF_1, "source": f"「{TITLE}」 {GRADE_LOCATORS['1']}"}
    assert two == {"text": DEF_2, "source": f"「{TITLE}」 제3조 제3호 나목"}  # 기준일이 가장 늦은 L1 고시 청크
    assert two["text"] in CHUNKS[3]["text"] and one["text"] in CHUNKS[2]["text"]
    assert grade_fn("M") is None and grade_fn("3") is None  # M은 고시에 없다: 블록을 만들지 않는다


@pytest.mark.parametrize("chunks", [
    [],                                                                    # 청크 없음
    [_chunk("x", "제3조 제3호 나목", "[제3조(정의) 제3호] 나. 등급 표지가 없는 문장")],   # 경계를 글자 일치로 자를 수 없다
    [_chunk("x", "제3조 제3호 나목", "[제3조(정의) 제3호] 나. 2등급:   ")],               # 표지 뒤가 비었다
    [_chunk("x", "제3조 제3호 나목", "나. 2등급: 문장 A"), _chunk("y", "제3조 제3호 나목", "나. 2등급: 문장 B")],  # 같은 기준일에 원문이 둘: 고르지 않는다
])
def test_corpus_grade_def_returns_none_when_it_cannot_cut_verbatim(chunks):
    assert corpus_grade_def_fn(CorpusIndex(chunks))("2") is None


def test_grade_2_found_gets_definition_block(dd, grade_fn):
    st, r = _run(dd, Q_PREG, _script(T500, COLD, pregnancy=True), [PREG_DRAFT], grade_def_fn=grade_fn)
    assert st["end_reason"] == "NORMAL" and len(r.grade_defs) == 1
    g = r.grade_defs[0]
    assert g.grade == "2" and g.title == fp.GRADE_DEF_TITLE.format(grade="2")
    assert g.text == DEF_2 and g.text in CHUNKS[3]["text"] and g.source and g.missing_reason is None
    assert r.grade_def_missing == [] and fp.GRADE_DEF_PHARMACIST_ADVICE not in r.pharmacist_advice


@pytest.mark.parametrize("fn", [lambda grade: None, lambda grade: {"text": "  ", "source": "x"}, lambda grade: 1 / 0])
def test_grade_def_fetch_fail_when_function_gives_nothing(dd, fn):
    st, r = _run(dd, Q_PREG, _script(T500, COLD, pregnancy=True), [PREG_DRAFT], grade_def_fn=fn)
    assert st["end_reason"] == "NORMAL"
    assert r.grade_def_missing == [fp.GRADE_DEF_MISSING_TEXT["FETCH_FAIL"].format(grade="2")]
    assert [(g.grade, g.text, g.source, g.missing_reason) for g in r.grade_defs] == [("2", None, None, "FETCH_FAIL")]
    assert fp.GRADE_DEF_PHARMACIST_ADVICE in r.pharmacist_advice


def test_without_grade_def_fn_output_is_unchanged(dd, grade_fn):
    st0, r0 = _run(dd, Q_PREG, _script(T500, COLD, pregnancy=True), [PREG_DRAFT])
    assert r0.grade_defs == [] and r0.grade_def_missing == []
    _, r1 = _run(dd, Q_PREG, _script(T500, COLD, pregnancy=True), [PREG_DRAFT], grade_def_fn=grade_fn)
    assert r1.model_dump(exclude={"grade_defs"}) == r0.model_dump(exclude={"grade_defs"})  # 블록 말고는 같다
    # 임부금기 발견이 없으면 함수가 있어도 블록이 없다
    _, r2 = _run(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT], grade_def_fn=grade_fn)
    assert r2.grade_defs == [] and r2.grade_def_missing == []


def _preg_item(eid: str, grade: str, **kw: Any) -> dict[str, Any]:
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["x"], "evidence_id": eid, "source": "한국의약품안전관리원", "as_of": "2026-07-21",
            "flags": [], "dataset_key": "pregnancy_contra", "source_kind": "FILE", "drugs": ["합성약"], "matches": [{"grade": grade}], **kw}


def test_grade_inputs_only_for_found_pregnancy_grades_1_and_2(grade_fn):
    calls: list[str] = []

    def fn(grade: str) -> dict[str, Any] | None:
        calls.append(grade)
        return grade_fn(grade)

    items = [
        _preg_item("p:m", "M"),                              # M: 블록 없음(원문이 고시가 아니다)
        _preg_item("p:2", "2등급"), _preg_item("p:2b", "2"),  # 같은 등급은 한 번만
        _preg_item("p:1", "1"),
        _preg_item("p:x", "1", source_kind=None),            # 출처 종류 없는 근거는 발견으로 보이지 않는다 → 등급 정의도 없다
        {**_preg_item("a:1", "1"), "kind": "age"},           # 임부금기가 아니다
        {**_preg_item("p:n", "1"), "status": "NOT_LISTED"},
    ]
    assert pregnancy_found_grades(items) == ["M", "2", "1"]
    defs, missing = grade_def_inputs(items, fn)
    assert calls == ["2", "1"] and missing == []
    assert [(d["grade"], d["text"]) for d in defs] == [("2", DEF_2), ("1", DEF_1)]
    assert grade_def_inputs([_preg_item("p:m", "M")], fn) == ([], [])
