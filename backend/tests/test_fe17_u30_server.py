"""FE-17 U-30(ISSUE-035, 2026-11-24) 서버 몫 시험: U-30-1 요약 중복 제거, U-30-6 등급 불일치 문구·한 근거에 한 안내. LLM·네트워크·원격 DB 호출 0.

- U-30-1 `summary_dedupe`: 사용자 사례(앞 두 문장이 같은 판정을 되풀이)·실제 모델 결과(`data/mock/ag-smoke`, 로컬)에서 따온 문장을 **고정 입력**으로
  지우기 전후를 비교한다. 중복 있는 입력은 줄고, 중복 없는 입력은 그대로이며, 약사 확인·안전 단정 금지 안내는 항상 남는다. 끄면 이전 동작과 같다.
- U-30-6 `grade_note_single`: 서버 고정 문구가 사용자 제공 문구와 글자 하나까지 같고, 등급이 다른 근거에 "같아요"와 "등급이 달라요"가 함께 나가지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from w32_synth import SEQ_A, FakeDur, golden_conn, w32_dict

from app.agent import fixed_phrases as fp
from app.agent.answer_schema import Citation, Sentence
from app.agent.finalize import finalize
from app.agent.graph.build import build_graph, run_question
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call
from app.agent.graph.nodes import GraphDeps
from app.agent.graph.wiring import build_deps, build_tool_context
from app.agent.summary_dedupe import DISCLAIMER, NOT_LISTED, PHARMACIST, classes_of, dedupe_sentences
from app.api.schemas import to_chat_response
from app.tools.provenance import FLAG_NOTES

# 사용자가 제공한 U-30-6 문구(원문 승인 간주, 글자 그대로)
USER_NOTE = "파일과 실시간 조회 결과 모두 보여드려요. 자료 고시 시점에 따라서 등급이 다르게 보일 수 있어요."
OLD_NOTE = "파일 자료와 실시간 조회의 등급이 달라요. 어느 쪽이 맞는지 정하지 않고 둘 다 출처와 함께 보여 드려요."

S1 = "병용 금기 목록에는 두 약의 조합이 올라 있지 않지만, 이것만으로 함께 복용해도 안전하다고 판단할 수는 없으니 복용 전 약사에게 확인해 주세요."
S2 = "자료에는 타이레놀정500밀리그람과 이부프로펜의 조합이 금기 목록에 없다고 되어 있습니다."
S3 = "이부프로펜은 성분 단위로 확인된 정보이며, 이부프로펜 제품의 제형이나 연령별 정보는 확인되지 않았습니다."
SAFE_PHRASE = "안전하다고 판단할 수는 없"


def S(text: str, ids: tuple[str, ...] = (), ct: str = "conclusion", cites: tuple[Citation, ...] = ()) -> Sentence:
    return Sentence(text=text, evidence_ids=list(ids), claim_type=ct, citations=list(cites))  # type: ignore[arg-type]


def _texts(res) -> list[str]:
    return [s.text for s in res.sentences]


# =========================================================================== U-30-1 요약 문장 중복 제거(순수 함수)
def test_user_case_second_sentence_is_dropped_and_safety_guidance_stays():
    ss = [S(S1), S(S2, ("contra_pair:1",), "fact"), S(S3, ("identify:2",), "fact")]
    res = dedupe_sentences(ss, n_drugs=2)
    assert res.changed and _texts(res) == [S1, S3]
    assert [d.index for d in res.dropped] == [1] and res.dropped[0].kept_index == 0 and res.dropped[0].classes == (NOT_LISTED,)
    joined = " ".join(_texts(res))
    assert "약사에게 확인" in joined and SAFE_PHRASE in joined          # 약사 확인·안전 단정 금지 안내는 남는다
    assert res.sentences[0].evidence_ids == ["contra_pair:1"]          # 지운 문장의 근거 ID는 남는 문장으로 옮긴다(근거 연결을 잃지 않는다)
    assert res.sentences[0].text == S1                                 # 글자는 건드리지 않는다(새 문장 생성 없음)


def test_dedupe_moves_citations_without_duplicates_and_keeps_other_fields():
    c = Citation(evidence_id="contra_pair:1", start=0, end=5)
    ss = [S(S1, ("contra_pair:1",), "conclusion", (c,)), S(S2, ("contra_pair:1",), "fact", (c,))]
    res = dedupe_sentences(ss, n_drugs=2)
    assert len(res.sentences) == 1 and res.sentences[0].citations == [c] and res.sentences[0].evidence_ids == ["contra_pair:1"]
    assert res.sentences[0].claim_type == "conclusion"


def test_input_without_duplicates_is_unchanged():
    ss = [S("확인된 자료에는 아세트아미노펜의 하루 최대량 정보가 있습니다.", ("dose:1",), "fact"), S("복용 간격은 약사에게 확인해 주세요.", (), "guidance")]
    res = dedupe_sentences(ss, n_drugs=2)
    assert not res.changed and res.sentences == ss


@pytest.mark.parametrize("n_drugs", [None, 0, 3, 5])
def test_meaning_dedupe_only_for_one_or_two_drugs(n_drugs):
    """약이 3개 이상이거나 모르면 쌍이 여럿일 수 있어 뜻이 같아 보이는 문장도 지우지 않는다(글자가 완전히 같을 때만)."""
    ss = [S(S1), S(S2, ("contra_pair:1",), "fact")]
    res = dedupe_sentences(ss, n_drugs=n_drugs)
    assert not res.changed and _texts(res) == [S1, S2]


def test_exact_duplicates_are_dropped_regardless_of_drug_count():
    ss = [S("약사에게 확인해 주세요.", ("a:1",)), S("약사에게  확인해 주세요.", ("b:1",))]
    res = dedupe_sentences(ss, n_drugs=None)
    assert _texts(res) == ["약사에게 확인해 주세요."] and res.sentences[0].evidence_ids == ["a:1", "b:1"]


def test_pharmacist_only_sentence_is_never_dropped():
    ss = [S(S1), S("복용 전 약사에게 확인해 주세요.", (), "guidance")]
    assert not dedupe_sentences(ss, n_drugs=2).changed


def test_dropped_sentence_must_be_covered_by_a_kept_sentence():
    """지울 문장의 뜻 종류(`NOT_LISTED`)가 남는 문장 어디에도 없으면 지우지 않는다."""
    only = [S("자료에는 두 약의 조합이 금기 목록에 없다고 되어 있습니다."), S(S3, ("identify:2",), "fact")]
    assert not dedupe_sentences(only, n_drugs=2).changed
    both_bare = [S("자료에는 두 약의 조합이 금기 목록에 없다고 되어 있습니다."), S("두 약의 병용은 금기 목록에 올라 있지 않습니다.")]
    res = dedupe_sentences(both_bare, n_drugs=2)
    assert len(res.sentences) == 1 and res.sentences[0].text == both_bare[0].text  # 앞 문장을 남긴다


def test_repeated_safety_disclaimer_sentence_is_dropped_but_one_remains():
    ss = [S(S1), S("이것만으로 안전하다고 판단할 수는 없습니다.")]
    res = dedupe_sentences(ss, n_drugs=2)
    assert _texts(res) == [S1] and res.dropped[0].classes == (DISCLAIMER,)
    solo = dedupe_sentences([S("이것만으로 안전하다고 판단할 수는 없습니다.")], n_drugs=2)
    assert not solo.changed


@pytest.mark.parametrize("text", [
    "병용 금기 목록에는 없지만 임부금기 2등급에 올라 있습니다.",          # 다른 판정이 섞임
    "자료에는 두 약의 조합이 금기 목록에 없고, 이부프로펜은 임부금기 정보가 있습니다.",   # 여러 절
    "허가사항 원문(주의사항): \"금기 목록에 없다\"",                       # 인용
    "이 약의 연령금기 정보가 없습니다.",                               # 목록 문장 아님(연령 정보)
])
def test_conservative_shapes_are_not_dropped(text):
    ss = [S(S1), S(text, ("x:1",), "fact")]
    assert not dedupe_sentences(ss, n_drugs=2).changed


def test_dedupe_never_adds_text_or_numbers():
    ss = [S(S1), S(S2, ("contra_pair:1",), "fact"), S(S3, ("identify:2",), "fact")]
    res = dedupe_sentences(ss, n_drugs=2)
    assert {s.text for s in res.sentences} <= {s.text for s in ss}


def test_pure_module_has_no_io_imports_or_env_switch():
    p = Path(__file__).resolve().parents[1] / "app" / "agent" / "summary_dedupe.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "re", "collections.abc", "dataclasses", "app.agent.answer_schema"}
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "environ" not in names and "getenv" not in names


# 실제 모델 22문항 결과(2026-11-24 ag-smoke-real)에서 문장 단위로 나눠 고정한 입력: 중복이 없으므로 그대로여야 한다
REAL_SUMMARIES = [
    ["점심에 복용해도 되는지는 이 자료만으로 확인할 수 없어, 복용 여부를 정할 수 없습니다.", "복용 간격과 현재 복용 상황을 약사에게 확인해 주세요."],
    ["지금 점심에 한 번 더 먹어도 되는지는 첫 복용 시각과 하루 동안 복용한 총량을 알아야 확인할 수 있어, 여기 자료만으로는 판단하기 어렵습니다.",
     "타이레놀정500밀리그람 e약은요 안내에는 만 12세 이상 소아 및 성인의 복용 간격과 하루 최대량이 안내되어 있지만, 첫 복용 시각과 오늘 복용한 총량은 확인되지 않았습니다.",
     "점심에 다시 복용할지 약사에게 확인해 주세요."],
    ["임신 중 두 약을 함께 복용해도 되는지는 확인되지 않았고, 타이레놀콜드-에스정의 임부 안전성 정보도 확인이 필요하므로 복용 여부를 약사와 확인하세요.",
     "두 약의 병용 금기 자료에는 함께 복용하는 경우가 올라 있지 않지만, 이것만으로 안전하다고 볼 수는 없습니다.",
     "타이레놀콜드-에스정의 성분에 대해 “임부에 대한 안전성 미확립.”이라고 되어 있습니다.",
     "타이레놀정500밀리그람은 제품 단위 임신 자료에 해당 내용이 올라 있지 않고, 타이레놀콜드-에스정의 주의사항도 확인하지 못했습니다."],
    ["자료에서는 아세트아미노펜과 이부프로펜의 조합이 금기 목록에 올라 있지 않지만, 이것만으로 함께 복용해도 안전하다고 판단할 수는 없습니다.",
     "감기약은 제품마다 성분이 다를 수 있어, 실제 제품의 성분과 복용량을 약사에게 확인해 주세요."],
    ["이 자료에서는 APAP(아세트아미노펜)과 이부프로펜의 병용이 금기 목록에 올라 있지 않지만, 이것만으로 함께 복용해도 안전하다고 판단할 수는 없어 복용 여부는 약사에게 확인해 주세요.",
     "조회는 성분 기준으로 이뤄져 있어, 복용하려는 제품의 연령 안내나 제형 등 제품별 정보는 확인되지 않았습니다."],
    ["약 이름과 먹은 양을 확인해야 하지만, 현재 자료로는 어떤 약인지 확인되지 않았습니다.", "약 봉투나 상자에 적힌 제품명 또는 성분명을 알려 주시면 약 정보를 확인할 수 있습니다."],
]


@pytest.mark.parametrize("texts", REAL_SUMMARIES)
@pytest.mark.parametrize("n_drugs", [None, 1, 2, 3])
def test_real_model_summaries_without_duplicates_are_unchanged(texts, n_drugs):
    ss = [S(t) for t in texts]
    res = dedupe_sentences(ss, n_drugs=n_drugs)
    assert not res.changed and res.sentences == ss


def test_real_summaries_keep_safety_and_pharmacist_classes_when_deduped():
    """사용자 사례 + 실제 요약 문장을 섞어도 한 번 이상 남는 뜻 종류는 지운 뒤에도 남는다."""
    ss = [S(S1), S(S2, ("contra_pair:1",), "fact"), *[S(t) for t in REAL_SUMMARIES[3]]]
    before = set().union(*(classes_of(s.text) for s in ss))
    res = dedupe_sentences(ss, n_drugs=2)
    after = set().union(*(classes_of(s.text) for s in res.sentences))
    assert after == before and {NOT_LISTED, DISCLAIMER, PHARMACIST} <= after
    assert len(res.sentences) < len(ss)


# =========================================================================== U-30-1 그래프 연결(스위치 `summary_dedupe`, 가짜 모델)
SEQ_AZI = "202200001"   # 이지렉트정(합성): 타이레놀정500과 병용금기 목록에 없는 짝


@pytest.fixture(scope="module")
def dd():
    return w32_dict()


def _graph(dd, sentences: list[Sentence], **switches: bool):
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": SEQ_A}, {"item_seq": SEQ_AZI}]}, "c1")]), AIMessage("done")]
    draft = {"sentences": [s.model_dump() for s in sentences]}
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([draft]), system_prompt="시험용", **switches)
    return build_graph(deps), deps


Q_PAIR = "타이레놀정500밀리그람이랑 이지렉트정1.0밀리그램 같이 먹어도 돼요?"


def test_graph_default_on_drops_repeated_not_listed_sentence(dd):
    g, deps = _graph(dd, [S(S1), S(S2, (), "conclusion"), S(S3)])
    assert deps.summary_dedupe is True
    st = run_question(g, Q_PAIR)
    summary = st["answer"]["summary"]
    assert S1 in summary and S2 not in summary and S3 in summary
    ev = [e for e in st["events"] if e.get("event") == "SUMMARY_DEDUPE"]
    assert len(ev) == 1 and ev[0]["dropped"] == 1 and ev[0]["classes"] == [NOT_LISTED]
    assert st["answer"]["fixed_notice"] and st["answer"]["disclaimer"]      # 고정 문구는 코드가 늘 붙인다


def test_graph_switch_off_is_previous_behavior(dd):
    g, deps = _graph(dd, [S(S1), S(S2), S(S3)], summary_dedupe=False)
    assert deps.summary_dedupe is False
    st = run_question(g, Q_PAIR)
    assert st["answer"]["summary"] == " ".join([S1, S2, S3])
    assert not [e for e in st["events"] if e.get("event") == "SUMMARY_DEDUPE"]


def test_graph_without_duplicates_has_same_output_and_no_event(dd):
    sents = [S("확인된 두 약의 자료는 아래에 보여 드려요."), S("복용 전 약사에게 확인해 주세요.")]
    on = run_question(_graph(dd, sents)[0], Q_PAIR)
    off = run_question(_graph(dd, sents, summary_dedupe=False)[0], Q_PAIR)
    assert on["answer"] == off["answer"]
    assert not [e for e in on["events"] if e.get("event") == "SUMMARY_DEDUPE"]


def test_graph_emergency_and_clarify_paths_unchanged_by_dedupe(dd):
    """응급 119·되묻기 요약은 모델 문장이 아니라 코드 문장이라 이 스위치와 무관하다."""
    on = run_question(_graph(dd, [S(S1), S(S2)])[0], "숨이 안 쉬어져요. 타이레놀정500밀리그람이랑 이지렉트정1.0밀리그램 같이 먹어도 돼요?")
    off = run_question(_graph(dd, [S(S1), S(S2)], summary_dedupe=False)[0], "숨이 안 쉬어져요. 타이레놀정500밀리그람이랑 이지렉트정1.0밀리그램 같이 먹어도 돼요?")
    assert on["answer"]["emergency"] == off["answer"]["emergency"] == fp.EMERGENCY_119
    amb_on = run_question(_graph(dd, [S(S1)])[0], "타이레놀정500 먹어도 되나요?")
    amb_off = run_question(_graph(dd, [S(S1)], summary_dedupe=False)[0], "타이레놀정500 먹어도 되나요?")
    assert amb_on["answer"]["summary"] == amb_off["answer"]["summary"]


def test_switch_names_defaults_and_no_env_switch(dd):
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(), summary_model=ScriptedSummary([{"sentences": []}]), system_prompt="x")
    assert deps.summary_dedupe is True and deps.grade_note_single is True
    off = build_deps(dd, ctx, tool_model=ScriptedToolModel(), summary_model=ScriptedSummary([{"sentences": []}]), system_prompt="x",
                     summary_dedupe=False, grade_note_single=False)
    assert off.summary_dedupe is False and off.grade_note_single is False
    assert {"summary_dedupe", "grade_note_single"} <= set(GraphDeps.__dataclass_fields__)
    root = Path(__file__).resolve().parents[1] / "app" / "agent"
    for rel in ("summary_dedupe.py", "graph/nodes.py", "graph/wiring.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "getenv" not in names, rel


# =========================================================================== U-30-1 프롬프트 판(answer_summary@v2, draft)
def test_answer_summary_v2_is_draft_and_v1_is_untouched():
    from app.agent.graph.prompt import DraftPromptError, load_summary_instruction

    root = Path(__file__).resolve().parents[1] / "prompts"
    v1, v2 = (root / "answer_summary@v1.md").read_text(encoding="utf-8"), (root / "answer_summary@v2.md").read_text(encoding="utf-8")
    assert "status: adopted" in v1 and "version: v1" in v1
    assert "status: draft" in v2 and "version: v2" in v2
    assert "같은 말을 두 번 쓰지 않는다" in v2 and "같은 말을 두 번 쓰지 않는다" not in v1
    # v1 본문은 v2의 부분이다(규칙을 더하기만 했다): 프런트매터 두 줄과 새 절 외에는 같다
    body1, body2 = v1.split("---\n", 2)[2], v2.split("---\n", 2)[2]
    assert all(line in body2.splitlines() for line in body1.splitlines() if line.strip())
    assert (root / "prompt_set@v5.yaml").read_text(encoding="utf-8").split() == ["name:", "prompt_set@v5", "prompts:", "-", "agent_system@v3", "-", "answer_summary@v2"]
    assert "prompt_set@v3" in (Path(__file__).resolve().parents[1] / "app" / "agent" / "graph" / "wiring.py").read_text(encoding="utf-8")
    with pytest.raises(DraftPromptError):
        load_summary_instruction("prompt_set@v5")                      # draft라 명시 없이는 연결되지 않는다
    text = load_summary_instruction("prompt_set@v5", allow_draft=True)
    assert text and "새 정보" in text and "약사" in text and "근거 ID" in text


def test_default_prompt_set_is_still_v3():
    from app.agent.graph import wiring

    assert wiring.DEFAULT_PROMPT_SET == "prompt_set@v3"


# =========================================================================== U-30-6 고정 문구·한 근거에 한 안내
KIDS = "한국의약품안전관리원"


def _preg(matches, flags=("API_SAME",), eid="pregnancy:1"):
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["333333ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": list(flags), "matches": matches, "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["이부프로펜"], "drug_keys": ["ibuprofen"]}


MISMATCH = [{"grade": "2", "row_key": "a", "row_evidence_id": "pregnancy:1#a", "source_kind": "FILE"},
            {"grade": "1", "row_key": "b", "row_evidence_id": "pregnancy:1#b", "source_kind": "API_DIRECT"}]
SAME = [{"grade": "2", "row_key": "a", "row_evidence_id": "pregnancy:1#a", "source_kind": "FILE"},
        {"grade": "2", "row_key": "b", "row_evidence_id": "pregnancy:1#b", "source_kind": "API_DIRECT"}]


def test_grade_mismatch_note_is_the_user_provided_text_exactly():
    assert fp.GRADE_MISMATCH_NOTE == USER_NOTE
    assert fp.GRADE_MISMATCH_NOTE != OLD_NOTE and "파일 자료와 실시간 조회의 등급이 달라요" not in fp.GRADE_MISMATCH_NOTE
    assert fp.GRADE_MISMATCH_NOTE not in fp.DRAFT_KEYS and "GRADE_MISMATCH_NOTE" not in fp.DRAFT_KEYS


def test_cause_of_both_notes_on_one_evidence_is_independent_flags():
    """원인 확정: `API_SAME` 줄은 항목 꼬리표(`entries[].notes`, 양쪽 모두 목록에 있음)이고, 등급 불일치 줄은 같은 약의 임부 등급이 둘 이상일 때
    근거 상세(`detail[].notes`)에 붙는다. 같은 근거에 두 조건이 함께 참이면 이전 코드는 둘 다 붙였다(스위치를 끈 동작)."""
    resp = finalize([_preg(MISMATCH)], None, emergency=False)
    assert FLAG_NOTES["API_SAME"] in resp["entries"][0]["notes"]
    d = next(x for x in resp["detail"] if x["evidence_id"] == "pregnancy:1")
    assert fp.GRADE_MISMATCH_NOTE in d["notes"]
    r = to_chat_response(resp)
    assert any(FLAG_NOTES["API_SAME"] in f.notes for f in r.findings)       # 끄면 이전처럼 함께 나간다
    assert "hidden_notes" not in resp


def test_grade_note_single_hides_api_same_only_where_mismatch_note_attaches():
    resp = finalize([_preg(MISMATCH)], None, emergency=False, grade_note_single=True)
    assert resp["hidden_notes"] == {"pregnancy:1": [FLAG_NOTES["API_SAME"]]}
    assert FLAG_NOTES["API_SAME"] in resp["entries"][0]["notes"] and FLAG_NOTES["API_SAME"] in resp["text"]     # entries·text(평가 원본·로그)는 그대로
    r = to_chat_response(resp)
    assert all(FLAG_NOTES["API_SAME"] not in f.notes for f in r.findings)
    d = next(x for x in r.detail if x.evidence_id == "pregnancy:1")
    assert d.notes.count(fp.GRADE_MISMATCH_NOTE) == 1                            # 불일치 안내 하나만 남는다
    assert [b.text for f in r.findings for b in f.badges] == ["삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]  # 배지는 그대로


def test_grade_note_single_leaves_same_grade_and_other_notes_alone():
    resp = finalize([_preg(SAME)], None, emergency=False, grade_note_single=True)
    assert "hidden_notes" not in resp                                             # 등급이 같으면 불일치 안내가 없고 API_SAME도 그대로(표시 정리는 프런트 U-30-3)
    assert all(fp.GRADE_MISMATCH_NOTE not in (d.get("notes") or []) for d in resp["detail"])
    r = to_chat_response(resp)
    assert any(FLAG_NOTES["API_SAME"] in f.notes for f in r.findings)
    other = finalize([_preg(MISMATCH, flags=("FILE_ONLY",))], None, emergency=False, grade_note_single=True)  # API_SAME이 아닌 안내는 숨기지 않는다
    assert "hidden_notes" not in other
    assert any(FLAG_NOTES["FILE_ONLY"] in f.notes for f in to_chat_response(other).findings)


def test_grade_note_single_does_not_touch_other_evidence():
    pair = {"kind": "contra_pair", "status": "FOUND", "subject": ["1", "2"], "evidence_id": "contra_pair:1", "source": KIDS, "as_of": "2026-07-31",
            "flags": ["API_SAME"], "matches": [{"row_key": "r", "row_evidence_id": "contra_pair:1#a", "reason": "출혈 위험", "notice_no": "제2026-1호"}],
            "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": ["와파린정", "아스피린정"]}
    resp = finalize([pair, _preg(MISMATCH)], None, emergency=False, grade_note_single=True)
    assert set(resp["hidden_notes"]) == {"pregnancy:1"}
    r = to_chat_response(resp)
    pair_f = next(f for f in r.findings if f.evidence_id == "contra_pair:1")
    assert FLAG_NOTES["API_SAME"] in pair_f.notes


def test_graph_default_passes_grade_note_single(dd):
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    for flag in (True, False):
        deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(), summary_model=ScriptedSummary([{"sentences": []}]), system_prompt="x", grade_note_single=flag)
        assert deps.grade_note_single is flag
