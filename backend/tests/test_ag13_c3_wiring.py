"""AG-13 C3 연결(AG-13-13 A)과 validator span 사유 건수(AG-13-12 A) 시험. LLM·judge·공공 API·원격 DB 호출 0, `.env` 미사용.

- C3 = C2(같은 ReAct 그래프) + AG-07 Validator 계층 검사(`layer_check`). 스위치는 비교 조건이 정한다: C3만 켜고 C1·C1+·C2는 주입값과 무관하게 끈다.
- C2·C1 동작 불변: 두 조건에서 Validator는 기준선과 같은 인자(`validate(kept, items)`)로만 불린다.
- 서비스 배선은 계층 검사를 켤 수 없다(채택 결정 전).
- validator span `output_summary`에 문장 필터·Validator 사유 코드별 건수(`filter_reasons`·`validator_reasons`)와 C3의 `claim_gaps` 건수를 싣고,
  문장 원문·근거 ID는 싣지 않는다.

질문·문장·항목은 합성이다(평가 세트 문항 아님). 시험셋 파일은 열지 않는다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", Path(__file__).resolve().parent / "e2e", Path(__file__).resolve().parent / "contract"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_runner as R  # noqa: E402
import freeze_check as FZ  # noqa: E402
import sealed_guard as G  # noqa: E402
from ag06_fixtures import S  # noqa: E402
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent import router as AR  # noqa: E402
from app.agent.answer_schema import AnswerDraft  # noqa: E402
from app.agent.graph import nodes as N  # noqa: E402
from app.agent.graph.build import run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.nodes import GraphDeps, make_nodes, make_raw_nodes  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink, _check_counts  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.pipeline.build import (  # noqa: E402
    C3_IMPROVEMENTS,
    C3_VERSION,
    HARNESS_BASELINE,
    build_for_condition,
    build_pipeline,
    harness_profile,
)
from app.agent.validator import CLAIM_OMITTED, GAP_ANSWER_OMIT, INGREDIENT_NOT_IN_EVIDENCE  # noqa: E402
from app.agent.validator import MISSING_ADVICE_ABSENT as V_MISSING  # noqa: E402
from app.config import Settings  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}

PREG = "pregnancy:900001ATB"
LABEL = "l3p-0000000000000001"
REQ = [AR.CLAIM_CONTRA_STATUS]


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture
def validate_calls(monkeypatch) -> list[dict[str, Any]]:
    """그래프 노드가 Validator를 어떤 인자로 부르는지 기록한다(실제 함수는 그대로 실행)."""
    calls: list[dict[str, Any]] = []
    real = N.validate

    def spy(answer: Any, items: Any, **kw: Any) -> Any:
        calls.append(kw)
        return real(answer, items, **kw)

    monkeypatch.setattr(N, "validate", spy)
    return calls


# --------------------------------------------------------------------------- 합성 자원
def _settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d")


class Factory:
    def __init__(self, layer_check: bool = False) -> None:
        self.sink = ListSink()
        self.calls: list[dict[str, Any]] = []
        self.layer_check = layer_check

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        self.calls.append({"run_id": run_id})
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        tracer = R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=self.sink)
        deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                          summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), prompt_set=prompt_set, allow_draft=allow_draft,
                          tracer=tracer, layer_check=self.layer_check)
        return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": dd.version, "built_at": dd.meta.get("built_at")})


def _synth_set(tmp_path: Path, n: int = 2) -> Path:
    p = tmp_path / "synth.jsonl"
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "dev", "set_version": "synth", "branch_label": "병용", "composition_group": "정상-병용",
             "expected_response_type": "found", "expected_path": {"required": ["identify_drug", "check_contraindications"],
                                                                 "order": [["identify_drug", "check_contraindications"]]},
             "required_elements": [], "dev_golden": True, "answer": {"items": []}} for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, condition: str, fac: Factory | None = None) -> tuple[int, dict[str, Any], Factory, Path]:
    fac = fac or Factory()
    out = tmp_path / f"out-{condition}.json"
    reg = tmp_path / "registry.jsonl"
    rc = R.main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(out), "--condition", condition],
                settings_fn=_settings, resources_factory=fac, registry_path=reg)
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}), fac, reg


def _bare_deps(**kw: Any) -> GraphDeps:
    """노드 본문만 부르는 시험용 의존성(모델·도구 없음, validator·finalize만 쓴다)."""
    return GraphDeps(drug_dict=None, tool_model=None, summary_model=None, tools=[], tool_ctx=None, system_prompt="", **kw)  # type: ignore[arg-type]


def _preg_found() -> dict[str, Any]:
    return {"kind": "pregnancy", "status": "FOUND", "evidence_id": PREG, "source_kind": "FILE", "flags": [], "dataset_key": "pregnancy",
            "source": "한국의약품안전관리원", "as_of": "2026-07-21", "subject": ["900001ATB"], "drugs": ["합성정"],
            "matches": [{"grade": "2", "detail": "합성 상세: 동물실험에서 생식 독성 보고.", "row_evidence_id": PREG + "#a", "row_key": "a"}]}


def _label() -> dict[str, Any]:
    return {"kind": "chunk", "status": "FOUND", "evidence_id": LABEL, "source_kind": "CORPUS_QUOTE", "flags": [], "matches": [],
            "verdict_allowed": False, "layer": "L3", "text": "임부는 복용 전 상의할 것", "source": "합성 출처", "as_of": "2026-07-31",
            "subject": ["900001ATB"]}


def _omit_state() -> dict[str, Any]:
    """FOUND 임부금기가 묶음에 있는데 답이 그 항목을 인용하지 않은 상태(⑯ ANSWER_OMIT 대상)."""
    d = AnswerDraft(sentences=[S("허가사항 안내에는 임부는 약사와 먼저 이야기해 보라고 적혀 있어요.", [LABEL])])
    return {"evidence": [_preg_found(), _label()], "draft": d.model_dump(), "required_claims": REQ, "call_count": 2, "rewind_count": 0}


# --------------------------------------------------------------------------- 러너: C3 연결
def test_c3_is_connected_in_runner():
    assert "C3" in R.SUPPORTED_CONDITIONS and "C3" in R.REAL_MODEL_CONDITIONS


def test_c3_run_records_condition_versions_harness_and_registry(tmp_path, validate_calls):
    rc, res, fac, reg = _run(tmp_path, "C3")
    meta = res["meta"]
    assert rc == 0 and meta["condition"] == "C3" and meta["n_items_run"] == 2
    assert meta["agent_info"]["run_id"].startswith("c3-")
    v = meta["versions"]
    assert v["graph"].startswith("graph-src@") and v["improvements"] == C3_VERSION and "pipeline_src" not in v
    assert meta["harness"]["condition"] == "C3" and meta["harness"]["baseline"] == list(HARNESS_BASELINE)
    assert meta["harness"]["improvements"] == list(C3_IMPROVEMENTS) and meta["harness"]["c3_version"] == C3_VERSION
    assert meta["typo_correction"]["enabled"] is True                       # 오탈자 보정은 C2와 같다(기본 켬)
    assert {s.get("condition") for s in fac.sink.records} == {"C3"}
    # Validator는 계층 검사를 켜고 Router의 required_claims를 받는다
    assert validate_calls and all(c.get("layer_check") is True and isinstance(c.get("required_claims"), list) for c in validate_calls)
    rows = [json.loads(line) for line in reg.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[-1]["condition"] == "C3" and rows[-1]["improvements"] == C3_VERSION


def test_c3_result_passes_freeze_table_condition_graph_typo_rows(tmp_path):
    _, res, _, _ = _run(tmp_path, "C3")
    rows = {r["item"]: r for r in FZ.check_result(res, dict_version=None, require_manifest_match=False)}
    for item in ("condition", "graph", "harness_table", "typo_correction"):
        assert rows[item]["ok"], rows[item]


def test_c2_and_c3_share_frozen_values_except_condition_items(tmp_path):
    """C2와 C3는 조건이 정하는 항목(조건·그래프·조건표·보정 스위치) 밖의 동결 값이 같다(같은 세트·모델·하네스 소스로 비교)."""
    _, c2, _, _ = _run(tmp_path, "C2")
    _, c3, _, _ = _run(tmp_path, "C3")
    assert FZ.same_freeze(c2, c3) == []
    assert c2["meta"]["versions"]["harness"] == c3["meta"]["versions"]["harness"]
    assert "improvements" not in c2["meta"]["versions"] and "improvements" not in c2["meta"]["harness"]


# --------------------------------------------------------------------------- C2·C1 동작 불변
def test_c2_runner_calls_validator_like_baseline(tmp_path, validate_calls):
    """주입된 의존성이 계층 검사를 켜 두었어도 C2는 끈다(조건이 정한다)."""
    rc, res, _, reg = _run(tmp_path, "C2", Factory(layer_check=True))
    assert rc == 0 and validate_calls and all(c == {} for c in validate_calls)
    assert "improvements" not in json.loads(reg.read_text(encoding="utf-8").splitlines()[-1])


@pytest.mark.parametrize("cond", ["C1", "C1+"])
def test_pipeline_conditions_call_validator_like_baseline(tmp_path, validate_calls, cond):
    rc, _, _, _ = _run(tmp_path, cond, Factory(layer_check=True))
    assert rc == 0 and validate_calls and all(c == {} for c in validate_calls)


def test_build_for_condition_does_not_mutate_injected_deps(validate_calls):
    fac = Factory(layer_check=False)
    resources = fac(_settings(), prompt_set="prompt_set@v3", allow_draft=False, run_id="t")
    build_for_condition(resources.deps, "C3")
    build_pipeline(replace(resources.deps, layer_check=True))
    assert resources.deps.layer_check is False                 # 사본만 바꾼다
    g = build_for_condition(replace(resources.deps, layer_check=True), "C2")
    st = run_question(g, Q_PAIR)
    assert st["end_reason"] and validate_calls and all(c == {} for c in validate_calls)


def test_validator_node_c2_passes_and_c3_records_answer_omit():
    """같은 상태: C2(꺼짐)는 기준선대로 통과. C3 v4(AG-13-29 A)는 ⑯ ANSWER_OMIT를 되감지 않고 건수만 기록한 뒤 통과한다(v1~v3은 되감기)."""
    off = make_raw_nodes(_bare_deps())["validator"](_omit_state())
    assert off["validation"]["status"] != "FAIL" and off["validation"]["next"] == "finalize" and "recorded" not in off["validation"]
    on = make_raw_nodes(_bare_deps(layer_check=True))["validator"](_omit_state())
    assert on["validation"]["status"] == "PASS" and on["validation"]["reasons"] == [] and on["validation"]["next"] == "finalize"
    assert on["validation"]["recorded"] == {CLAIM_OMITTED: 1} and "messages" not in on and on["final_sentences"]
    assert "rewind_count" not in on and not any(e.get("event") == "REWIND" for e in on["events"])
    ev = next(e for e in on["events"] if e.get("event") == "VALIDATOR")
    assert ev["claim_gaps"] == {GAP_ANSWER_OMIT: 1} and ev["reasons"] == {CLAIM_OMITTED: 1}   # 검사 결과(사유)는 그대로 남는다
    assert ev["status"] == "PASS" and ev["recorded"] == {CLAIM_OMITTED: 1}                     # 이벤트 상태는 노드 판단과 같게


def test_harness_profile_c3_row_and_unknown_condition():
    row = harness_profile("C3")
    assert row["baseline"] == harness_profile("C2")["baseline"] and row["selection_limits"] == []
    assert row["improvements"] == list(C3_IMPROVEMENTS) and "improvements" not in harness_profile("C2")
    with pytest.raises(ValueError, match="조건"):
        harness_profile("C4")
    with pytest.raises(ValueError, match="조건"):
        build_for_condition(_bare_deps(), "C4")


# --------------------------------------------------------------------------- 배선
def test_wiring_default_off_and_service_cannot_turn_on():
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
    tm, sm = ScriptedToolModel(script=[AIMessage("x")]), ScriptedSummary([{"sentences": [GUIDE]}])
    assert build_deps(dd, ctx, tool_model=tm, summary_model=sm).layer_check is False
    assert build_deps(dd, ctx, tool_model=tm, summary_model=sm, service=True).layer_check is False
    assert build_deps(dd, ctx, tool_model=tm, summary_model=sm, layer_check=True).layer_check is True
    with pytest.raises(ValueError, match="서비스"):
        build_deps(dd, ctx, tool_model=tm, summary_model=sm, service=True, layer_check=True)


# --------------------------------------------------------------------------- AG-13-12: validator span 사유 건수
def test_validator_span_carries_reason_counts_without_text():
    sink = ListSink()
    deps = _bare_deps(layer_check=True, tracer=GraphTracer(sink=sink))
    st = _omit_state()
    # 근거에 없는 성분명 문장(⑮)을 하나 더해 Validator 삭제 사유도 생기게 한다
    st["draft"]["sentences"].append(S("이 약의 성분은 가상성분이에요.", [PREG]).model_dump())
    make_nodes(deps)["validator"](st)
    span = next(r for r in sink.records if r.get("node") == "validator" and "harness_event" not in r)
    summ = span["output_summary"]
    assert summ["validator_reasons"] == {INGREDIENT_NOT_IN_EVIDENCE: 1, CLAIM_OMITTED: 1}
    assert summ["claim_gaps"] == {GAP_ANSWER_OMIT: 1}
    assert summ["recorded"] == {CLAIM_OMITTED: 1}             # C3 v4: ⑯은 기록만(되감기 사유 `violations`에는 없음)
    assert CLAIM_OMITTED not in span["violations"] and span["verdict"] == "fix"
    assert "filter_reasons" not in summ                       # 문장 필터에서 걸린 문장이 없으면 키를 만들지 않는다
    blob = json.dumps(span, ensure_ascii=False)
    assert "가상성분" not in blob and "허가사항" not in blob and PREG not in json.dumps(summ)   # 원문·근거 ID 없음


def test_validator_span_reason_counts_also_in_c2_and_filter_reasons():
    sink = ListSink()
    deps = _bare_deps(tracer=GraphTracer(sink=sink))
    d = AnswerDraft(sentences=[S("근거 없는 사실 문장이에요.", []), S("임부금기 2등급으로 올라 있어요.", [PREG])])
    make_nodes(deps)["validator"]({"evidence": [_preg_found()], "draft": d.model_dump(), "call_count": 2})
    span = next(r for r in sink.records if r.get("node") == "validator" and "harness_event" not in r)
    summ = span["output_summary"]
    assert summ["filter_reasons"] == {"NO_EVIDENCE": 1} and "claim_gaps" not in summ and "recorded" not in summ
    assert "근거 없는" not in json.dumps(span, ensure_ascii=False)


# --------------------------------------------------------------------------- AG-13-17 B: ⑯ 되감기 메시지 보강(c3-layer-check@v2)
PAIR = "contra_pair:AAA:BBB"


def _preg_named() -> dict[str, Any]:
    it = _preg_found()
    it["matches"] = [{**it["matches"][0], "ingr_name": "합성성분A"}, {"grade": "2", "row_evidence_id": PREG + "#b", "row_key": "b",
                                                                   "ingr_name": "합성성분A"}]
    return it


def _named_omit_state() -> dict[str, Any]:
    st = _omit_state()
    st["evidence"] = [_preg_named(), _label()]
    return st


def _rewind_text(upd: dict[str, Any]) -> str:
    assert upd["validation"]["next"] == "rewind"
    (msg,) = upd["messages"]
    return str(msg.content)


def test_c3_version_is_v4():
    assert C3_VERSION == "c3-layer-check@v4"
    assert harness_profile("C3")["c3_version"] == "c3-layer-check@v4"
    assert C3_IMPROVEMENTS == ("AG07_LAYER_CHECK",)            # 장치 이름은 그대로, 판 번호로만 구분(AG-13-25 A)


def test_c3_v4_claim_omitted_no_rewind_and_no_hint():
    """C3 v4: ⑯만 걸린 답은 되감지 않는다. v2 보강 지시(`claim_omit_hint`)는 그래프에서 더 쓰지 않는다(함수는 이전 판 재현용으로 남김)."""
    upd = make_raw_nodes(_bare_deps(layer_check=True))["validator"](_named_omit_state())
    assert upd["validation"]["next"] == "finalize" and "messages" not in upd
    assert N.CLAIM_OMIT_HINT_HEAD not in json.dumps(upd, ensure_ascii=False, default=str)


def test_c2_same_state_has_no_hint_and_passes():
    off = make_raw_nodes(_bare_deps())["validator"](_named_omit_state())
    assert off["validation"]["next"] == "finalize" and "messages" not in off


def test_c3_rewind_without_claim_omitted_keeps_baseline_message():
    """⑯이 아닌 실패(형식 오류)면 C3에서도 기존 되감기 문구 그대로다."""
    st = {**_named_omit_state(), "draft": None}
    for deps in (_bare_deps(), _bare_deps(layer_check=True)):
        text = _rewind_text(make_raw_nodes(deps)["validator"](st))
        assert text == N.REWIND_MESSAGE.format(reasons="SCHEMA_INVALID") and N.CLAIM_OMIT_HINT_HEAD not in text


def test_claim_omit_hint_values_come_from_items_only():
    api_pair = {"kind": "contra_pair", "status": "FOUND", "evidence_id": PAIR, "matches": [{"content": "x", "row_evidence_id": PAIR + "#1"}]}
    file_pair = {"kind": "contra_pair", "status": "FOUND", "evidence_id": "contra_pair:C:D",
                 "matches": [{"name_a": " 성분\n가 ", "name_b": "성분나" + "긴" * 60}]}
    dose = {"kind": "dose", "status": "FOUND", "evidence_id": "dose:E", "matches": [{"ingr_name": "용량성분"}]}
    hint = N.claim_omit_hint([PAIR, "contra_pair:C:D", "dose:E", "없는:ID", PAIR], [api_pair, file_pair, dose])
    lines = hint.splitlines()
    assert lines[0] == N.CLAIM_OMIT_HINT_HEAD and len(lines) == 3          # 핵심 금기 아님·묶음에 없음·중복은 건너뛴다
    assert lines[1] == N.CLAIM_OMIT_HINT_LINE.format(kind="병용금기", names=N.CLAIM_OMIT_NAMES_UNKNOWN, eid=PAIR)
    assert lines[2].startswith("- 병용금기: 성분 가·성분나") and len(lines[2].split("·")[1].split(" (")[0]) == N.CLAIM_OMIT_NAME_LEN
    assert N.claim_omit_hint(["없는:ID"], [api_pair]) == "" and N.claim_omit_hint([], []) == ""


def test_claim_omit_hint_caps_items():
    items = [{"kind": "age", "status": "FOUND", "evidence_id": f"age:{i}", "matches": [{"ingr_name": f"성분{i}"}]} for i in range(9)]
    hint = N.claim_omit_hint([f"age:{i}" for i in range(9)], items)
    assert len(hint.splitlines()) == 1 + N.CLAIM_OMIT_MAX_ITEMS


def test_c3_v4_records_not_in_span_text_or_ids():
    """⑯ 기록은 사유 코드 건수뿐이다. 성분명·근거 ID·지시 문구는 validator span·이벤트·상태에 없다(AG-13-12)."""
    sink = ListSink()
    upd = make_nodes(_bare_deps(layer_check=True, tracer=GraphTracer(sink=sink)))["validator"](_named_omit_state())
    blob = json.dumps([*sink.records, upd["events"], upd["validation"]], ensure_ascii=False)
    assert "합성성분A" not in blob and "빠진 주장 유형" not in blob and PREG not in blob
    span = next(r for r in sink.records if r.get("node") == "validator" and "harness_event" not in r)
    assert span["output_summary"]["recorded"] == {CLAIM_OMITTED: 1} and span["verdict"] == "pass"


# --------------------------------------------------------------------------- AG-13-32 A: ⑥ 되감기 메시지에 미확보 근거 ID(c3-layer-check@v4)
LABEL_MISS = "label:900001ATB:dosage"
SEARCH_MISS = "search:search_label:abcdef012345"


def _label_miss() -> dict[str, Any]:
    """라벨 원문 미확보(`label_provider=None`) 항목. `get_label_section` 출력 모양(합성)."""
    return {"kind": "label", "status": "NO_EVIDENCE", "evidence_id": LABEL_MISS, "subject": ["900001ATB", "dosage"], "source": None,
            "source_kind": None, "flags": [], "matches": [], "missing_reason": "OUT_OF_SCOPE", "is_label": True, "text": None}


def _search_miss() -> dict[str, Any]:
    return {"kind": "search_miss", "status": "NO_EVIDENCE", "evidence_id": SEARCH_MISS, "subject": ["search_label"], "source": None,
            "source_kind": None, "flags": [], "matches": [], "missing_reason": "SEARCH_MISS", "verdict_allowed": False, "text": None}


def _missing_state() -> dict[str, Any]:
    """FOUND 임부금기를 말한 문장은 있지만 라벨 미확보 항목에 약사 확인 안내가 없는 상태(⑥만 걸림, ⑯ 아님)."""
    d = AnswerDraft(sentences=[S("임부금기 2등급으로 올라 있어요.", [PREG])])
    return {"evidence": [_preg_found(), _label_miss()], "draft": d.model_dump(), "required_claims": REQ, "call_count": 2, "rewind_count": 0}


def test_c2_missing_advice_rewind_message_is_baseline():
    """C2: ⑥ 되감기 메시지는 기준선 문구 그대로(힌트 없음), 상태에 `recorded` 키가 없다."""
    upd = make_raw_nodes(_bare_deps())["validator"](_missing_state())
    assert upd["validation"]["reasons"] == [V_MISSING]
    assert _rewind_text(upd).encode("utf-8") == N.REWIND_MESSAGE.format(reasons=V_MISSING).encode("utf-8")
    assert "recorded" not in upd["validation"]
    assert all("recorded" not in e for e in upd["events"])


def test_c3_v4_missing_advice_rewind_message_lists_missing_ids():
    """C3 v4: ⑥ 되감기 = 기준선 문구 + 줄바꿈 + 고정 지시 + 미확보 근거 ID 줄(코드 값만)."""
    text = _rewind_text(make_raw_nodes(_bare_deps(layer_check=True))["validator"](_missing_state()))
    hint = N.MISSING_ADVICE_HINT_HEAD + "\n" + N.MISSING_ADVICE_HINT_LINE.format(what="허가사항 원문", eid=LABEL_MISS)
    assert text == N.REWIND_MESSAGE.format(reasons=V_MISSING) + "\n" + hint
    assert "임부금기 2등급" not in text                        # 모델이 쓴 문장은 메시지에 넣지 않는다


def test_c3_v4_omit_and_missing_rewinds_for_missing_only():
    """⑯과 ⑥이 함께 걸리면 ⑥으로만 되감는다(사유에 ⑯ 없음, ⑯ 지시 없음), ⑯은 기록에 남는다."""
    st = _omit_state()
    st["evidence"] = [_preg_found(), _label(), _label_miss()]
    upd = make_raw_nodes(_bare_deps(layer_check=True))["validator"](st)
    assert upd["validation"]["status"] == "FAIL" and upd["validation"]["reasons"] == [V_MISSING]
    assert upd["validation"]["recorded"] == {CLAIM_OMITTED: 1}
    text = _rewind_text(upd)
    assert N.MISSING_ADVICE_HINT_HEAD in text and LABEL_MISS in text and N.CLAIM_OMIT_HINT_HEAD not in text and CLAIM_OMITTED not in text
    ev = next(e for e in upd["events"] if e.get("event") == "VALIDATOR")
    assert ev["status"] == "FAIL" and ev["recorded"] == {CLAIM_OMITTED: 1}
    assert next(e for e in upd["events"] if e.get("event") == "REWIND")["reasons"] == [V_MISSING]


def test_c3_v4_hint_in_second_summary_input_via_v3_path():
    """⑥ 힌트가 든 되감기 메시지는 v3 경로(마지막 되감기를 요약 지시 뒤에)로 둘째 요약 호출에 그대로 들어간다. C2는 들어가지 않는다."""
    msg = _rewind_text(make_raw_nodes(_bare_deps(layer_check=True))["validator"](_missing_state()))
    st = _summary_state(msg)
    c3 = _summary_body(replace(_bare_deps(layer_check=True), system_prompt=SYS), st)
    c2 = _summary_body(replace(_bare_deps(), system_prompt=SYS), st)
    assert c3 == _baseline_summary_text(Q_PAIR, TOOL_BLOCK, N.SUMMARY_INSTRUCTION) + "\n\n" + msg and LABEL_MISS in c3
    assert c2 == _baseline_summary_text(Q_PAIR, TOOL_BLOCK, N.SUMMARY_INSTRUCTION) and LABEL_MISS not in c2


def test_c3_v4_missing_hint_not_in_span_or_events():
    sink = ListSink()
    upd = make_nodes(_bare_deps(layer_check=True, tracer=GraphTracer(sink=sink)))["validator"](_missing_state())
    assert LABEL_MISS in _rewind_text(upd)
    blob = json.dumps([*sink.records, upd["events"], upd["validation"]], ensure_ascii=False)
    assert LABEL_MISS not in blob and "약사 확인 안내가 빠진" not in blob


def test_missing_advice_hint_values_and_caps():
    preg = _preg_found()
    hint = N.missing_advice_hint([LABEL_MISS, SEARCH_MISS, PREG, "없는:ID", LABEL_MISS], [preg, _label_miss(), _search_miss()])
    lines = hint.splitlines()
    assert lines == [N.MISSING_ADVICE_HINT_HEAD,                                       # 미확보 아님·묶음에 없음·중복은 건너뛴다
                     N.MISSING_ADVICE_HINT_LINE.format(what="허가사항 원문", eid=LABEL_MISS),
                     N.MISSING_ADVICE_HINT_LINE.format(what="검색 근거", eid=SEARCH_MISS)]
    other = {"kind": "contra_pair", "status": "UNIDENTIFIED", "evidence_id": "contra_pair:X:Y", "missing_reason": "UNIDENTIFIED"}
    assert N.missing_advice_hint(["contra_pair:X:Y"], [other]).splitlines()[1] == N.MISSING_ADVICE_HINT_LINE.format(
        what=N.MISSING_ADVICE_KIND_OTHER, eid="contra_pair:X:Y")
    assert N.missing_advice_hint([], []) == "" and N.missing_advice_hint([PREG], [preg]) == ""
    many = [{**_label_miss(), "evidence_id": f"label:{i}:dosage"} for i in range(9)]
    assert len(N.missing_advice_hint([m["evidence_id"] for m in many], many).splitlines()) == 1 + N.MISSING_ADVICE_MAX_ITEMS


# --------------------------------------------------------------------------- AG-13-23 A: 되감기 메시지를 요약 호출에도 전달(c3-layer-check@v3)
SYS = "합성 시스템 프롬프트"
TOOL_BLOCK = "<<<EVIDENCE 합성 근거 블록 EVIDENCE>>>"


def _baseline_summary_text(question: str, blocks: str, instruction: str) -> str:
    """변경 전(v2까지) `_summary_messages` 사용자 메시지 본문 그대로(C1·C1+·C2 바이트 고정 기준)."""
    return f"질문: {question}\n\n근거 데이터:\n{blocks}\n\n{instruction}"


def _summary_state(*rewinds: str) -> dict[str, Any]:
    msgs: list[Any] = [AIMessage("", tool_calls=[{"name": "check_contraindications", "args": {}, "id": "t1"}]),
                       ToolMessage(content=TOOL_BLOCK, tool_call_id="t1", name="check_contraindications"), AIMessage("조회를 마쳤다")]
    msgs.extend(HumanMessage(r) for r in rewinds)
    return {"question": Q_PAIR, "messages": msgs}


def _summary_body(deps: GraphDeps, state: dict[str, Any]) -> str:
    sysm, human = N._summary_messages(state, deps)  # noqa: SLF001
    assert sysm.content == SYS
    return str(human.content)


@pytest.mark.parametrize("instruction", [None, "합성 요약 지시"])
def test_c3_v3_summary_appends_last_rewind_after_instruction(instruction):
    first = N.REWIND_MESSAGE.format(reasons="ALL_SENTENCES_DROPPED")
    last = N.REWIND_MESSAGE.format(reasons=CLAIM_OMITTED) + "\n" + N.CLAIM_OMIT_HINT_HEAD
    st = _summary_state(first, last)
    instr = instruction or N.SUMMARY_INSTRUCTION
    body = _summary_body(replace(_bare_deps(layer_check=True, summary_instruction=instruction), system_prompt=SYS), st)
    assert body == _baseline_summary_text(Q_PAIR, TOOL_BLOCK, instr) + "\n\n" + last   # 지시 뒤에 마지막 되감기 하나만
    assert first not in body


@pytest.mark.parametrize("instruction", [None, "합성 요약 지시"])
def test_c2_summary_input_byte_identical_even_with_rewind(instruction):
    """C2(계층 검사 꺼짐)는 되감기 메시지가 상태에 있어도 요약 입력이 변경 전과 바이트 단위로 같다."""
    st = _summary_state(N.REWIND_MESSAGE.format(reasons=CLAIM_OMITTED))
    deps = replace(_bare_deps(summary_instruction=instruction), system_prompt=SYS)
    body = _summary_body(deps, st)
    assert body.encode("utf-8") == _baseline_summary_text(Q_PAIR, TOOL_BLOCK, instruction or N.SUMMARY_INSTRUCTION).encode("utf-8")
    assert "[HARNESS]" not in body


def test_c3_v3_summary_unchanged_without_rewind():
    """되감기가 없으면 C3 요약 입력도 C2와 같다(첫 요약 호출 불변). 되감기가 아닌 사람 메시지는 붙이지 않는다."""
    st = _summary_state()
    st["messages"].append(HumanMessage("되감기가 아닌 합성 메시지"))
    c2 = _summary_body(replace(_bare_deps(), system_prompt=SYS), st)
    c3 = _summary_body(replace(_bare_deps(layer_check=True), system_prompt=SYS), st)
    assert c3.encode("utf-8") == c2.encode("utf-8") == _baseline_summary_text(Q_PAIR, TOOL_BLOCK, N.SUMMARY_INSTRUCTION).encode("utf-8")


class RecordingSummary(ScriptedSummary):
    """시험 전용: 요약 호출 입력(`_summary_messages`의 사용자 메시지 본문과 그 뒤 메시지 수)을 기록한다."""

    def __init__(self, drafts: list[dict[str, Any]]) -> None:
        super().__init__(drafts, repeat_last=True)
        self.bodies: list[str] = []
        self.tails: list[int] = []

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        self.bodies.append(str(messages[1].content))
        self.tails.append(len(messages) - 2)
        return super().invoke(messages, **kwargs)


def _graph_summaries(condition: str, layer_check: bool = False) -> RecordingSummary:
    """첫 요약이 전부 걸러지는 문장(되감기 1회)이고 둘째가 안내 문장인 합성 실행. 요약 호출 입력 기록."""
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
    bad = {"sentences": [S("근거 없는 사실 문장이에요.", []).model_dump()]}
    rec = RecordingSummary([bad, {"sentences": [GUIDE]}])
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True), summary_model=rec,
                      prompt_set="prompt_set@v3", layer_check=layer_check)
    run_question(build_for_condition(deps, condition), Q_PAIR)
    return rec


def test_graph_c3_v3_second_summary_sees_rewind_and_c2_does_not():
    c2, c3 = _graph_summaries("C2", layer_check=True).bodies, _graph_summaries("C3").bodies   # C2는 주입값이 켜져 있어도 끈다
    assert len(c2) == len(c3) == 2                                  # 되감기 1회 → 요약 호출 2회
    assert c3[0] == c2[0] and "[HARNESS]" not in c3[0]              # 첫 요약은 같다
    assert c2[1] == c2[0] and "[HARNESS]" not in c2[1]              # C2 둘째 요약은 되감기를 보지 못한다(기준선 그대로)
    assert c3[1] == c2[1] + "\n\n" + N.REWIND_MESSAGE.format(reasons="ALL_SENTENCES_FILTERED")


@pytest.mark.parametrize("cond", ["C1", "C1+"])
def test_pipeline_summary_input_unchanged_by_v3(cond):
    """C1·C1+ 고정 파이프라인: 요약 본문에 되감기를 붙이지 않고(계층 검사 강제 꺼짐), 되감기는 기존대로 뒤에 별도 메시지 1개다."""
    rec = _graph_summaries(cond, layer_check=True)
    assert len(rec.bodies) == 2 and rec.bodies[1] == rec.bodies[0] and "[HARNESS]" not in rec.bodies[1]
    assert rec.tails == [0, 1]


# --------------------------------------------------------------------------- AG-13-35 A: 러너 `--note`(결과 meta에 그대로, 동결 값 아님)
NOTE = "caution_rule@v1·intake@v1 합성 메모"


def _run_args(tmp_path: Path, name: str, *extra: str) -> tuple[int, dict[str, Any]]:
    out = tmp_path / f"{name}.json"
    rc = R.main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(out), "--condition", "C2", *extra],
                settings_fn=_settings, resources_factory=Factory(), registry_path=tmp_path / "registry.jsonl")
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {})


def test_runner_note_kept_verbatim_in_meta_and_absent_without(tmp_path):
    rc, with_note = _run_args(tmp_path, "with", "--note", NOTE)
    rc2, without = _run_args(tmp_path, "without")
    assert rc == rc2 == 0
    assert with_note["meta"]["note"] == NOTE                     # 글자 그대로
    assert "note" not in without["meta"]                          # 주지 않으면 키가 없다(기존 결과 모양 그대로)


def test_runner_note_is_not_a_freeze_value(tmp_path):
    """메모는 동결 비교에 들지 않는다: 메모만 다른 두 결과는 `--same` 차이 0, 메모 없는 결과를 기준선으로 가드도 통과(이유 없이)."""
    _, base = _run_args(tmp_path, "base")
    base_path = tmp_path / "base.json"
    rc, noted = _run_args(tmp_path, "noted", "--note", NOTE, "--baseline", str(base_path))
    assert rc == 0 and noted["meta"]["freeze_baseline"]["diffs"] == [] and noted["meta"]["freeze_baseline"]["reason"] is None
    assert FZ.same_freeze(base, noted) == []
    assert "note" not in FZ.freeze_values(noted)


def test_runner_note_offline_agent_too(tmp_path):
    out = tmp_path / "offline.json"
    rc = R.main(["--set", str(_synth_set(tmp_path)), "--agent", "offline-fixed", "--out", str(out), "--note", NOTE],
                settings_fn=_settings, registry_path=tmp_path / "registry.jsonl")
    assert rc == 0 and json.loads(out.read_text(encoding="utf-8"))["meta"]["note"] == NOTE


def test_check_counts_keeps_only_code_shaped_positive_int_counts():
    events = [
        {"event": "SENTENCE_FILTER", "reasons": {"NO_EVIDENCE": 2, "문장 원문": 1, "lower_case": 1, "BAD": "1", "ZERO": 0, "FLAG": True}},
        {"event": "VALIDATOR", "reasons": {"SAFE_ASSERTION": 1}, "claim_gaps": {"RETRIEVAL_MISS": 1}},
        {"event": "VALIDATOR", "reasons": {"SAFE_ASSERTION": 2}},
        {"event": "REWIND", "reasons": ["X"]},
        "not-a-dict",
    ]
    assert _check_counts(events) == {"filter_reasons": {"NO_EVIDENCE": 2}, "validator_reasons": {"SAFE_ASSERTION": 3},
                                     "claim_gaps": {"RETRIEVAL_MISS": 1}}
    assert _check_counts([]) == {}
