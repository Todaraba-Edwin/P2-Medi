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
from langchain_core.messages import AIMessage

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


def test_validator_node_c2_passes_and_c3_rewinds_on_answer_omit():
    """같은 상태: C2(꺼짐)는 기준선대로 통과, C3(켜짐)는 ⑯ ANSWER_OMIT로 되감기 1회."""
    off = make_raw_nodes(_bare_deps())["validator"](_omit_state())
    assert off["validation"]["status"] != "FAIL" and off["validation"]["next"] == "finalize"
    on = make_raw_nodes(_bare_deps(layer_check=True))["validator"](_omit_state())
    assert on["validation"]["status"] == "FAIL" and on["validation"]["reasons"] == [CLAIM_OMITTED] and on["validation"]["next"] == "rewind"
    ev = next(e for e in on["events"] if e.get("event") == "VALIDATOR")
    assert ev["claim_gaps"] == {GAP_ANSWER_OMIT: 1}


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
    assert summ["filter_reasons"] == {"NO_EVIDENCE": 1} and "claim_gaps" not in summ
    assert "근거 없는" not in json.dumps(span, ensure_ascii=False)


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
