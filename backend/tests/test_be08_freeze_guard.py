"""BE-08 부분 충족 항목 마무리 시험(2026-11-18). LLM·judge·공공 API·원격 DB 호출 0(가짜 모델·합성 사전·소규모 SQLite, 합성 질문).

- 같은 설정으로 2회 실행하면 입력 세트(해시·문항 ID)가 같다(`freeze_check.same_freeze`).
- 결과 meta `run_settings`: 호출 상한·LLM 설정(온도 미지정)·검색 방식·API 끔·파일별 기준일.
- `--baseline`: 이전 측정과 동결 값이 다르면 시작하지 않는다(H16·RFP-34-04). 이유를 주면 기록하고 실행한다.
- 문항 행의 `run_index`(RFP-35-09), 평가 모드 강제(`MEDIAGENT_EVAL=1`), 반복 결과의 완전성.
- 하네스 차단·경고 보조 집계와 "차단 뒤 상한 종료" 비율(RFP-33-05), 신뢰성의 경로·안전 요소 일관성(RFP-26-06).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "judge", Path(__file__).resolve().parent / "e2e"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_metrics as M  # noqa: E402
import eval_runner as R  # noqa: E402
import freeze_check as F  # noqa: E402
import sealed_guard as G  # noqa: E402
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.state import MAX_MODEL_CALLS  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import loaders  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


class Factory:
    def __init__(self, *, dict_version: str | None = None) -> None:
        self.calls = 0
        self.dict_version = dict_version

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        self.calls += 1
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                          summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), prompt_set=prompt_set, allow_draft=allow_draft,
                          tracer=R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=ListSink()))
        return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": self.dict_version or dd.version},
                                corpus_meta={"source": "synthetic", "n_chunks": 0, "sha256": "0" * 64})


def _set(tmp_path: Path, n: int = 3, name: str = "synth.jsonl", q: str = Q_PAIR) -> Path:
    p = tmp_path / name
    rows = [{"id": f"syn-{i:03d}", "question": q, "set": "dev", "set_version": "synth", "branch_label": "정상", "composition_group": "정상-병용",
             "expected_response_type": "judgment", "expected_path": {"required": []}, "required_elements": ["DISCLAIMER"], "answer": {"items": []}}
            for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, out: str, *extra: str, set_path: Path | None = None, fac: Factory | None = None) -> tuple[int, dict[str, Any], Factory]:
    fac = fac or Factory()
    path = tmp_path / out
    rc = R.main(["--set", str(set_path or _set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(path), *extra],
                settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d"), resources_factory=fac)
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}), fac


# --------------------------------------------------------------------------- 같은 설정 2회 = 같은 입력

def test_two_runs_with_the_same_settings_have_the_same_input_set(tmp_path):
    _, a, _ = _run(tmp_path, "a.json")
    _, b, _ = _run(tmp_path, "b.json")
    assert a["meta"]["set_sha256"] == b["meta"]["set_sha256"] and len(a["meta"]["set_sha256"]) == 64
    assert [r["id"] for r in a["items"]] == [r["id"] for r in b["items"]]
    assert F.same_freeze(a, b) == []
    assert F.main([str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--same", "--no-manifest", "--dict-version", ""]) == 0


def test_a_changed_set_file_is_reported_as_a_different_input(tmp_path, capsys):
    _, a, _ = _run(tmp_path, "a.json")
    _, c, _ = _run(tmp_path, "c.json", set_path=_set(tmp_path, 4, "other.jsonl"))
    assert [d["item"] for d in F.same_freeze(a, c)] == ["set_sha256"]
    assert F.main([str(tmp_path / "a.json"), str(tmp_path / "c.json"), "--same", "--no-manifest", "--dict-version", ""]) == 1
    assert "set_sha256" in capsys.readouterr().out


# --------------------------------------------------------------------------- 실행 설정 기록

def test_run_settings_record_call_limit_llm_retrieval_api_off_and_file_dates(tmp_path):
    _, res, _ = _run(tmp_path, "a.json")
    rs = res["meta"]["run_settings"]
    assert rs["call_limit"] == MAX_MODEL_CALLS == 8 and rs["api_enabled"] is False and res["meta"]["agent_info"]["api_enabled"] is False
    assert rs["llm"] == {"temperature": None, "reasoning_effort": "none", "max_completion_tokens": 1500}
    assert rs["retrieval"] == {"method": "bm25", "vector": False, "embedding_model": None}
    assert rs["file_as_of"]["kids_pregnancy_age_dose"] == loaders.AS_OF_KIDS == "2026-07-21"
    assert rs["file_as_of"]["kids_contra_pair"] == "2026-07-31" and rs["file_as_of"]["kids_lactation"] == "2025-11-27"
    assert res["meta"]["versions"]["corpus"] == {"source": "synthetic", "n_chunks": 0, "sha256": "0" * 64}
    rows = {r["item"]: r["ok"] for r in F.check_result(res, dict_version=None, require_manifest_match=False)}
    assert rows["call_limit"] and rows["run_settings"] and rows["corpus"]


def test_graph_run_forces_eval_mode(tmp_path):
    """평가 모드(`MEDIAGENT_EVAL=1`)는 시작 때 러너가 강제한다: LLM 캐시가 섞인 측정이 시작될 수 없다(RFP-35-09, RFP-32-02)."""
    assert os.environ["MEDIAGENT_EVAL"] == "0"
    _, res, _ = _run(tmp_path, "a.json")
    assert os.environ["MEDIAGENT_EVAL"] == "1" and res["meta"]["eval_mode_env"] == "1"
    from app.llm import cache

    assert cache.cache_enabled() is False if hasattr(cache, "cache_enabled") else True


def test_corpus_fingerprint_changes_with_content_and_keeps_no_text():
    class Idx:
        def __init__(self, chunks: list[dict[str, Any]]) -> None:
            self.chunks = chunks

    a = R.corpus_fingerprint(Idx([{"chunk_id": "c1", "base_date": "2026-07-21", "text": "본문 가"}, {"chunk_id": "c2", "base_date": None, "text": "본문 나"}]), "db:x")
    b = R.corpus_fingerprint(Idx([{"chunk_id": "c2", "base_date": None, "text": "본문 나"}, {"chunk_id": "c1", "base_date": "2026-07-21", "text": "본문 가"}]), "db:x")
    c = R.corpus_fingerprint(Idx([{"chunk_id": "c1", "base_date": "2026-07-21", "text": "본문 다"}, {"chunk_id": "c2", "base_date": None, "text": "본문 나"}]), "db:x")
    assert a == b and a["sha256"] != c["sha256"] and a["n_chunks"] == 2 and a["source"] == "db:x"  # 순서 무관, 내용이 바뀌면 달라진다
    assert "본문" not in json.dumps(a, ensure_ascii=False)


# --------------------------------------------------------------------------- 이전 측정과 다르면 시작하지 않는다

def test_baseline_with_the_same_frozen_values_runs_and_is_recorded(tmp_path):
    _run(tmp_path, "base.json")
    rc, res, _ = _run(tmp_path, "next.json", "--baseline", str(tmp_path / "base.json"))
    fb = res["meta"]["freeze_baseline"]
    assert rc == 0 and fb["file"] == "base.json" and fb["diffs"] == [] and fb["reason"] is None and len(fb["sha256"]) == 64


def test_changed_set_refuses_to_start_without_a_reason(tmp_path, capsys):
    _run(tmp_path, "base.json")
    other = _set(tmp_path, 3, "other.jsonl", q=Q_PAIR + " 급해요")
    rc, res, fac = _run(tmp_path, "next.json", "--baseline", str(tmp_path / "base.json"), set_path=other)
    out = capsys.readouterr().out
    assert rc == 2 and res == {} and "set_sha256" in out and "--freeze-diff-reason" in out


@pytest.mark.parametrize("what", ["dict", "call_limit", "model"])
def test_changed_dict_call_limit_or_model_refuses_to_start(what, tmp_path, monkeypatch, capsys):
    _run(tmp_path, "base.json")
    fac = Factory(dict_version="다른-사전-판") if what == "dict" else Factory()
    if what == "call_limit":
        monkeypatch.setattr("app.agent.graph.state.MAX_MODEL_CALLS", 12)
    if what == "model":
        monkeypatch.setattr("app.agent.llm.MODEL", "다른-모델")
    rc, res, _ = _run(tmp_path, "next.json", "--baseline", str(tmp_path / "base.json"), fac=fac)
    assert rc == 2 and res == {} and {"dict": "dict_version", "call_limit": "call_limit", "model": "model"}[what] in capsys.readouterr().out


def test_a_reason_lets_the_run_start_and_is_written_to_the_result(tmp_path):
    _run(tmp_path, "base.json")
    rc, res, _ = _run(tmp_path, "next.json", "--baseline", str(tmp_path / "base.json"), "--freeze-diff-reason", "사전 재빌드(BE-10-14)",
                      fac=Factory(dict_version="다른-사전-판"))
    fb = res["meta"]["freeze_baseline"]
    assert rc == 0 and [d["item"] for d in fb["diffs"]] == ["dict_version"] and fb["reason"] == "사전 재빌드(BE-10-14)"
    assert fb["diffs"][0]["baseline"] == "golden-synth-v1" and fb["diffs"][0]["planned"] == "다른-사전-판"


def test_agent_side_changes_are_not_frozen_but_c1_rules_are(tmp_path):
    """프롬프트·ReAct 그래프·하네스 소스는 개선 대상이라 동결 값이 아니다. 같은 C1끼리는 파이프라인 규칙 버전이 동결 값이다."""
    _, base, _ = _run(tmp_path, "base.json")
    planned = json.loads(json.dumps(base))
    planned["meta"]["versions"]["graph"] = "graph-src@다른해시"
    planned["meta"]["versions"]["harness"] = "harness-src@다른해시"
    planned["meta"]["versions"]["prompt"] = {"set": "prompt_set@v9", "files": {}}
    planned["meta"]["typo_correction"]["enabled"] = False
    assert F.freeze_diff(planned, base) == []
    _, c1, _ = _run(tmp_path, "c1.json", "--condition", "C1")
    c1b = json.loads(json.dumps(c1))
    c1b["meta"]["versions"]["graph"] = "c1-pipeline@v2"
    assert [d["item"] for d in F.freeze_diff(c1b, c1)] == ["graph"]
    assert F.freeze_diff(c1, base) == []  # 조건이 다르면 그래프 버전은 비교하지 않는다


def test_judge_items_are_compared_only_when_both_runs_had_a_judge(tmp_path):
    _, base, _ = _run(tmp_path, "base.json")
    judged = json.loads(json.dumps(base))
    judged["meta"]["judge"] = {"model": "claude-sonnet-5-5", "rubrics": {"J1": "J1@v1"}, "prompt_sha256": "a" * 64, "ragas": "ragas-rubric@v1"}
    assert F.freeze_diff(judged, base) == []  # 한쪽만 judge: 비교하지 않는다
    other = json.loads(json.dumps(judged))
    other["meta"]["judge"]["prompt_sha256"] = "b" * 64
    assert [d["item"] for d in F.freeze_diff(other, judged)] == ["judge_prompt_sha256"]


def test_baseline_is_graph_only(tmp_path, capsys):
    rc = R.main(["--set", str(_set(tmp_path)), "--baseline", str(tmp_path / "x.json"), "--out", str(tmp_path / "o.json")])
    assert rc == 2 and "--baseline" in capsys.readouterr().out and not (tmp_path / "o.json").exists()


# --------------------------------------------------------------------------- run_index·반복 완전성

def test_rows_carry_run_index_and_repeats_are_complete(tmp_path):
    _, res, _ = _run(tmp_path, "rep.json", "--repeats", "3")
    assert {r["run_index"] for r in res["items"]} == {1}
    assert [(blk["run"], {r["run_index"] for r in blk["items"]}) for blk in res["items_repeats"]] == [(2, {2}), (3, {3})]
    ids = [r["id"] for r in res["items"]]
    assert all([r["id"] for r in blk["items"]] == ids for blk in res["items_repeats"])  # 문항 × 회차가 모두 있다
    rel = res["reliability"]
    assert rel["repeats"] == 3 and rel["items"] == 3
    assert rel["trajectory_consistency"]["k"] == 3 and rel["safety_element_consistency"]["k"] == 3  # 가짜 모델이라 회차마다 같다


def test_reliability_consistency_counts_items_whose_path_or_safety_elements_differ():
    def row(qid: str, tools: list[str], end: str, disclaimer: bool) -> dict[str, Any]:
        return {"id": qid, "safety": {"code_pass": True, "pending_judge": [], "pass": True}, "judgment": None,
                "trajectory": {"verdict": "Pass", "end_reason": end}, "elements": {"DISCLAIMER": disclaimer},
                "run": {"tool_calls": [{"name": t, "args": {}} for t in tools]}}

    runs = [[row("a", ["check_contraindications"], "NORMAL", True), row("b", ["check_contraindications"], "NORMAL", True)],
            [row("a", ["check_contraindications", "search_reason"], "NORMAL", True), row("b", ["check_contraindications"], "NORMAL", False)]]
    rel = M.reliability(runs)
    assert rel["trajectory_consistency"] == M.kn(1, 2) and rel["safety_element_consistency"] == M.kn(1, 2)


# --------------------------------------------------------------------------- 하네스 보조 집계

def test_harness_summary_counts_blocks_warns_and_block_then_limit():
    rows = [{"aux": {"harness_blocks": 2}, "harness_warns": 1, "trajectory": {"end_reason": "LIMIT"}},
            {"aux": {"harness_blocks": 1}, "harness_warns": 0, "trajectory": {"end_reason": "NORMAL"}},
            {"aux": {"harness_blocks": 0}, "harness_warns": 3, "trajectory": {"end_reason": "NORMAL"}}]
    hs = R.harness_summary(rows)
    assert hs["blocks_total"] == 3 and hs["warns_total"] == 4 and hs["items_with_block"] == M.kn(2, 3)
    assert hs["block_then_limit"] == M.kn(1, 2) and hs["blocked_items_by_end_reason"] == {"LIMIT": 1, "NORMAL": 1}
    assert R.harness_summary([{"id": "x"}]) is None and "9장 지표 아님" in hs["note"]


def test_graph_result_has_harness_events_and_offline_result_does_not(tmp_path):
    _, res, _ = _run(tmp_path, "a.json")
    assert res["metrics"]["harness_events"]["items"] == 3 and all("harness_warns" in r for r in res["items"])
    out = tmp_path / "off.json"
    assert R.main(["--set", str(_set(tmp_path)), "--out", str(out)]) == 0
    off = json.loads(out.read_text(encoding="utf-8"))
    assert "harness_events" not in off["metrics"] and "run_settings" not in off["meta"] and "run_index" not in off["items"][0]
