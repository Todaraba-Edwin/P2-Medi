"""AG-11 judge 실연결 시험(2026-11-18, AG-11-02·05): `eval_runner --judge sonnet`이 judge·Ragas를 문항마다 부르고 결과에 합친다.

LLM·Anthropic·공공 API·원격 DB 호출 0(가짜 전송 계층), `.env` 미사용. 그래프는 가짜 모델·합성 소사전·소규모 SQLite다. 질문은 합성이다
(평가 세트 문항 아님). 시험셋 파일은 열지 않는다. 원장·로그 경로는 tmp로 돌린다.
"""

from __future__ import annotations

import json
import re
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
import sealed_guard as G  # noqa: E402
import sonnet_judge as SJ  # noqa: E402
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.ledger import CostLedger  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문
PAIR_EID = "contra_pair:254000ATB:625201ATB"
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}, GUIDE]}
_RUBRIC_RE = re.compile(r"\[루브릭 (J\d)@v1\]")
_CHUNK_RE = re.compile(r'<chunk id="([^"]+)" rank="(\d+)">')


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d", **over)


class RubricTransport:
    """가짜 전송: 사용자 메시지의 루브릭 표지를 보고 스키마에 맞는 JSON을 돌려준다. 호출마다 루브릭·청크 순서·메시지 글자를 기록한다."""

    def __init__(self, *, in_tok: int = 1000, out_tok: int = 300, bad_first: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.in_tok, self.out_tok, self.bad_first = in_tok, out_tok, bad_first

    def complete(self, *, system: str, messages: list[dict[str, Any]], max_tokens: int) -> SJ.TransportResult:
        user = str(messages[0]["content"])
        rub = _RUBRIC_RE.search(user).group(1)
        chunks = [m.group(1) for m in _CHUNK_RE.finditer(user)]
        self.calls.append({"rubric": rub, "chunks": chunks, "text": system + "\n" + user, "turns": len(messages)})
        if self.bad_first and len(messages) == 1:
            return SJ.TransportResult(text="설명부터 쓰면 형식 오류", stop_reason="end_turn", input_tokens=self.in_tok, output_tokens=self.out_tok)
        item = {"pass": True, "reason": "근거와 일치", "evidence": ["c"]}
        if rub == "J1":
            out: dict[str, Any] = {"rubric": "J1@v1", "overall_pass": True,
                                   "claims": [{"id": 1, "text": "주장", "supported": True, "reason": "청크에 있음", "evidence": chunks[:1]}]}
        elif rub == "J2":
            out = {"rubric": "J2@v1", "chunks": [{"id": c, "relevant": c == PAIR_EID, "reason": "r"} for c in chunks],
                   "reference_claims": [{"text": "정답 주장", "attributed": True, "evidence": [PAIR_EID]}]}
        else:
            out = {"rubric": f"{rub}@v1", "overall_pass": True, "items": {k: item for k in ("R1", "R2", "R3")}}
        return SJ.TransportResult(text=json.dumps(out, ensure_ascii=False), stop_reason="end_turn", input_tokens=self.in_tok, output_tokens=self.out_tok)


class PerItemScript(ScriptedToolModel):
    """문항마다 같은 스크립트를 처음부터 다시 쓰는 가짜(도구 메시지가 없으면 새 문항의 첫 호출이다)."""

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        if not any(getattr(m, "tool_calls", None) or m.type == "tool" for m in messages):
            self._i = 0
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class Factory:
    def __init__(self, *, ledger: CostLedger | None = None) -> None:
        self.calls = 0
        self.ledger = ledger
        self.sink = ListSink()

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        self.calls += 1
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c1")]),
                  AIMessage("조회를 마쳤다")]
        deps = build_deps(dd, ctx, tool_model=PerItemScript(script=script, repeat_last=True), summary_model=ScriptedSummary([PAIR_DRAFT]),
                          prompt_set=prompt_set, allow_draft=allow_draft,
                          tracer=R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=self.sink))
        total = R.ledger_cost_total(self.ledger) if self.ledger is not None else (lambda: 0.0)
        return R.GraphResources(deps=deps, cost_total=total, dict_meta={"version": dd.version, "built_at": dd.meta.get("built_at")})


def _synth_set(tmp_path: Path, n: int = 3, branch: str = "정상") -> Path:
    p = tmp_path / "synth.jsonl"
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "dev", "set_version": "synth", "branch_label": branch, "composition_group": "정상-병용",
             "expected_response_type": "judgment", "expected_path": {"required": ["check_contraindications"]}, "required_elements": [],
             "reference": "두 약은 병용금기 목록에 올라 있다.", "answer": {"items": []},
             "answer_evidence": {"evidence_ids": [PAIR_EID]}} for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, *extra: str, transport: RubricTransport | None = None, max_usd: str = "1", n: int = 3, branch: str = "정상",
         fac: Factory | None = None, ledger: CostLedger | None = None, judge_flags: bool = True
         ) -> tuple[int, dict[str, Any], RubricTransport, Factory]:
    tr = transport or RubricTransport()
    fac = fac or Factory()
    out = tmp_path / "out.json"
    args = ["--set", str(_synth_set(tmp_path, n, branch)), "--agent", "graph", "--max-usd", "1", "--out", str(out), *extra]
    if judge_flags:
        args += ["--judge", "sonnet", "--judge-max-usd", max_usd]
    rc = R.main(args, settings_fn=_settings, resources_factory=fac,
                judge_factory=lambda settings, mx: SJ.SonnetJudge(tr, ledger=ledger, max_usd=mx))
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}), tr, fac


# --------------------------------------------------------------------------- 연결

def test_judge_scores_every_item_and_ragas_is_aggregated(tmp_path):
    rc, res, tr, _ = _run(tmp_path)
    assert rc == 0 and len(res["items"]) == 3
    for row in res["items"]:
        assert row["judge"]["status"] == "ok" and row["judge"]["rubric"] == "J1@v1" and row["judge"]["rubrics"]["J1"]["faithfulness"] == 1.0
        rg = row["ragas"]
        assert rg["faithfulness"] == 1.0 and rg["context_recall"] == 1.0 and rg["context_precision"] is not None
        assert rg["chunk_id_recall"]["bundle_complete"] is True and rg["judge_error"] is False
    agg = res["metrics"]["ragas"]
    assert agg["n_items"] == 3 and agg["faithfulness"]["n"] == 3 and agg["faithfulness"]["mean"] == 1.0 and agg["judge_errors"] == 0
    assert res["metrics"]["judge_metrics_not_computed"] == []


def test_j1_is_called_once_per_item_and_reused_for_ragas(tmp_path):
    """같은 답·같은 청크의 J1을 안전 응답 채점과 Ragas가 따로 부르지 않는다(문항당 J1 1회 + J2 1회)."""
    rc, res, tr, _ = _run(tmp_path)
    assert [c["rubric"] for c in tr.calls] == ["J1", "J2"] * 3
    assert res["judge_usage"]["calls"] == 6 and res["judge_usage"]["scored"] == 6
    assert all(row["ragas"]["judge"]["J1"] == {"reused": True, "status": "ok"} for row in res["items"])


def test_result_meta_records_judge_model_rubrics_and_prompt_hash(tmp_path):
    rc, res, tr, _ = _run(tmp_path)
    j = res["meta"]["judge"]
    prompt = SJ.load_prompt()
    assert j["model"] == "claude-sonnet-5-5" and j["rubrics"] == SJ.RUBRIC_VERSIONS and j["status"] == "called"
    assert j["prompt_file"] == "judge_rubric@v1.md" and j["prompt_sha256"] == prompt["sha256"] and len(j["prompt_sha256"]) == 64
    assert j["thinking"] == {"type": "between_tools"} and j["ragas"] == "ragas-rubric@v1"
    u = res["judge_usage"]
    assert u["errors"] == 0 and u["error_rate"] == 0.0 and u["max_usd"] == 1.0 and u["cap_reached"] is False and u["skipped"] == []
    assert u["cost_usd"] == round(6 * SJ.estimate_cost_usd(1000, 300), 6)


def test_chunks_reach_the_judge_in_graph_evidence_order(tmp_path):
    """AG-11-05 A: 근거 청크는 그래프가 받은 순서(`run.evidence_order`, ID만 기록)로 judge에 간다. 본문은 결과의 순서 기록에 없다."""
    rc, res, tr, _ = _run(tmp_path, n=1)
    order = res["items"][0]["run"]["evidence_order"]
    assert order and order[0] == PAIR_EID and all(isinstance(x, str) for x in order)
    sent = tr.calls[0]["chunks"]
    assert sent == [x for x in order if x in sent] and set(sent) <= set(order) | {c for c in sent if c.startswith("grade_def:")}
    assert tr.calls[1]["chunks"] == sent  # J2도 같은 순서


def test_judge_input_is_blind_to_condition_and_versions(tmp_path):
    rc, res, tr, _ = _run(tmp_path, n=1)
    text = "\n".join(c["text"] for c in tr.calls)
    for banned in ("prompt_set", "agent_system", "gpt-6-luna", "c1-pipeline", "harness@v1", "typo_correction", "l2-prompt"):
        assert banned not in text, banned
    assert not re.search(r"\bC[0-3]\+?\b", text)


def test_default_graph_run_has_no_judge(tmp_path):
    rc, res, tr, _ = _run(tmp_path, judge_flags=False)
    assert rc == 0 and tr.calls == [] and res["judge"] is None and res["meta"]["judge"] is None
    assert "judge_usage" not in res and "ragas" not in res["metrics"] and all(r["judge"] is None and "ragas" not in r for r in res["items"])
    assert all(r["run"]["evidence_order"] for r in res["items"])  # 순서 기록은 judge와 무관하게 남는다


# --------------------------------------------------------------------------- 오류·상한

def test_format_error_is_retried_once_and_counted(tmp_path):
    rc, res, tr, _ = _run(tmp_path, n=1, transport=RubricTransport(bad_first=True))
    u = res["judge_usage"]
    assert rc == 0 and u["retries"] == 2 and u["errors"] == 0 and u["calls"] == 4 and res["items"][0]["judge"]["status"] == "ok"


def test_judge_budget_stops_judging_but_not_the_run(tmp_path):
    cost1 = SJ.estimate_cost_usd(1000, 300)
    rc, res, tr, _ = _run(tmp_path, max_usd=str(cost1 * 2.5))  # 두 번 부른 뒤(2c) 한 번 더 부르면 3c > 2.5c → 세 번째 호출부터 막힌다
    assert rc == 0 and len(res["items"]) == 3  # 에이전트 실행·코드 채점은 끝까지
    u = res["judge_usage"]
    assert u["cap_reached"] is True and u["calls"] == 2 and u["skipped"] == ["syn-001", "syn-002"]
    assert u["cost_usd"] <= u["max_usd"]  # 상한을 넘기지 않는다(호출 전에 다음 호출 비용을 미리 본다)
    assert res["items"][0]["judge"]["status"] == "ok"
    assert [r["judge"]["status"] for r in res["items"][1:]] == ["not_called", "not_called"]
    assert all(r["judge"]["reason"] == R.JUDGE_BUDGET_STOP and "ragas" not in r for r in res["items"][1:])
    assert res["metrics"]["ragas"]["n_items"] == 1


def test_agent_cost_excludes_judge_cost_on_the_shared_ledger(tmp_path):
    """judge 비용은 같은 원장(평가 몫)에 쌓이지만 에이전트 비용 상한·문항별 비용에는 들어가지 않는다(`judge_usage`에 따로)."""
    ledger = CostLedger(path=tmp_path / "shared-ledger.json")
    rc, res, tr, _ = _run(tmp_path, fac=Factory(ledger=ledger), ledger=ledger)
    assert rc == 0 and res["judge_usage"]["cost_usd"] > 0
    assert ledger.spent("eval") == pytest.approx(res["judge_usage"]["cost_usd"]) and ledger.spent("dev") == 0
    assert res["cost_usd"]["total"] == pytest.approx(0.0, abs=1e-9) and all(r["cost_usd"] == 0 for r in res["items"])


def test_budget_guard_never_overshoots_after_the_first_call():
    """2026-11-18 스모크에서 누적만 보던 규칙이 마지막 호출만큼 상한을 넘겼다. 지금은 가장 비쌌던 호출만큼 더 쓰면 넘길 때 호출 전에 막는다."""
    tr = RubricTransport(in_tok=4000, out_tok=900)
    one = SJ.estimate_cost_usd(4000, 900)
    judge = SJ.SonnetJudge(tr, max_usd=one * 3.2)
    inp = SJ.JudgeInput(question="q", answer_summary="요약", contexts=[SJ.Context("a:1", "본문")])
    for _ in range(3):
        assert judge.score_rubric("J1", inp)["status"] == "ok"
    with pytest.raises(SJ.JudgeBudgetExceeded):
        judge.score_rubric("J1", inp)  # 3c + c > 3.2c
    assert len(tr.calls) == 3 and judge.usage.cost_usd <= judge.max_usd


# --------------------------------------------------------------------------- 실행 전 가드

def test_judge_needs_a_budget_and_a_graph_agent(tmp_path, capsys):
    base = ["--set", str(_synth_set(tmp_path)), "--out", str(tmp_path / "o.json")]
    assert R.main([*base, "--agent", "graph", "--max-usd", "1", "--judge", "sonnet"], settings_fn=_settings, resources_factory=Factory()) == 2
    assert "--judge-max-usd" in capsys.readouterr().out
    assert R.main([*base, "--judge", "sonnet", "--judge-max-usd", "1"]) == 2
    assert "graph" in capsys.readouterr().out and not (tmp_path / "o.json").exists()


def test_missing_judge_key_stops_before_building_resources(tmp_path, capsys):
    fac = Factory()
    rc = R.main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--judge", "sonnet", "--judge-max-usd", "1",
                 "--out", str(tmp_path / "o.json")], settings_fn=_settings, resources_factory=fac)  # judge_factory 없음 → 실제 생성 경로
    out = capsys.readouterr().out
    assert rc == 2 and fac.calls == 0 and "ANTHROPIC_API_KEY" in out and "fake-k" not in out and not (tmp_path / "o.json").exists()


def test_default_judge_passes_the_key_to_the_sdk_without_keeping_it(monkeypatch):
    """실제 생성 경로: 설정의 키를 전송 계층에 넘기고 judge·전송 객체의 글자에는 남기지 않는다(SDK 클라이언트는 가짜로 바꾼다. 호출 0)."""
    import anthropic

    seen: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kw: Any) -> None:
            seen.update(kw)

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    secret = "QQQQ-가짜-judge-키-7731"
    judge = R.default_judge(_settings(anthropic_api_key=secret), 0.5)
    assert seen["api_key"] == secret and judge.max_usd == 0.5 and R.is_real_judge(judge)
    assert secret not in repr(judge) and secret not in repr(judge.transport) and secret not in json.dumps(judge.meta(), ensure_ascii=False)


# --------------------------------------------------------------------------- 단위

def test_merge_judge_fills_only_pending_judge_elements_and_recomputes_safety():
    row = {"elements": {"DISCLAIMER": True, "PREMISE_CORRECTED": None, "NO_STATE_ASSESSMENT": None},
           "safety": {"code_pass": True, "pending_judge": ["NO_STATE_ASSESSMENT", "PREMISE_CORRECTED"], "pass": None}}
    R.merge_judge(row, {"elements": {"PREMISE_CORRECTED": True, "NO_STATE_ASSESSMENT": None, "DISCLAIMER": False, "SAYS_NOT_FOUND": True}})
    assert row["elements"] == {"DISCLAIMER": True, "PREMISE_CORRECTED": True, "NO_STATE_ASSESSMENT": None}  # 코드 요소는 덮지 않고, 없는 요소는 더하지 않는다
    assert row["safety"] == {"code_pass": True, "pending_judge": ["NO_STATE_ASSESSMENT"], "pass": None}
    R.merge_judge(row, {"elements": {"NO_STATE_ASSESSMENT": False}})
    assert row["safety"]["pass"] is False and row["safety"]["pending_judge"] == []
    ok = {"elements": {"PREMISE_CORRECTED": None}, "safety": {"code_pass": True, "pending_judge": ["PREMISE_CORRECTED"], "pass": None}}
    R.merge_judge(ok, {"elements": {"PREMISE_CORRECTED": True}})
    assert ok["safety"] == {"code_pass": True, "pending_judge": [], "pass": True}
    bad_code = {"elements": {"PREMISE_CORRECTED": None}, "safety": {"code_pass": False, "pending_judge": ["PREMISE_CORRECTED"], "pass": False}}
    R.merge_judge(bad_code, {"elements": {"PREMISE_CORRECTED": True}})
    assert bad_code["safety"]["pass"] is False  # 코드 요소가 틀렸으면 judge가 맞아도 불통과


def test_safety_rate_uses_judge_elements_after_merge(tmp_path):
    """오정보 문항(J3): judge 요소가 채워지면 안전 응답률의 보류가 줄어든다(집계는 합친 뒤 계산한다)."""
    rc, res, tr, _ = _run(tmp_path, branch="오정보", n=2)
    assert {c["rubric"] for c in tr.calls} == {"J1", "J3"}  # 오정보는 Ragas 대상이 아니다(J2 없음)
    assert all("ragas" not in r and r["judge"]["rubrics"]["J3"]["overall_pass"] is True for r in res["items"])
    assert res["metrics"]["ragas"]["n_items"] == 0


def test_extract_trace_records_evidence_ids_in_order_without_bodies():
    state = {"answer": finalize([]), "evidence": [{"evidence_id": "b:2", "text": "본문"}, {"evidence_id": "a:1", "matches": [{"detail": "긴 본문"}]},
                                                    {"evidence_id": "b:2"}, {"kind": "x"}], "end_reason": "NORMAL"}
    rec = R.extract_trace(state)
    assert rec.evidence_order == ["b:2", "a:1"]
    dumped = json.dumps(rec.to_json()["evidence_order"], ensure_ascii=False)
    assert "본문" not in dumped
    assert M.RunRecord.from_json(rec.to_json()).evidence_order == ["b:2", "a:1"]


def test_judge_contexts_follow_evidence_order_and_fall_back_to_detail_order():
    ans = {"detail": [{"evidence_id": "a:1", "kind": "k", "status": "FOUND"}, {"evidence_id": "b:2", "kind": "k", "status": "FOUND"}],
           "grade_defs": [{"grade": "2", "text": "등급 정의 원문"}]}
    ordered = R.judge_contexts(M.RunRecord(answer=ans, evidence_order=["b:2", "a:1"]))
    assert [c.id for c in ordered] == ["b:2", "a:1", "grade_def:2"]  # 순서 기록에 없는 등급 정의는 뒤
    assert [c.id for c in R.judge_contexts(M.RunRecord(answer=ans))] == ["a:1", "b:2", "grade_def:2"]  # 기록 없는 예전 실행


def test_search_chunk_body_reaches_the_judge_but_not_the_result_file():
    """검색 청크는 최종 답의 근거 상세에 머리 줄만 있다. judge에는 그래프 `evidence`의 본문 원문을 붙여 주고(요약·자르기 없음), 결과 파일에는 쓰지 않는다."""
    body = "제3조(정의) 가. 1등급: (합성 문장) 본문 원문 " + "가" * 400
    chunk = {"kind": "chunk", "status": "FOUND", "evidence_id": "l1:notice:3", "source": "식품의약품안전처 고시", "as_of": "2026-07-21", "text": body,
             "source_kind": "CORPUS_QUOTE", "dataset_key": "notice", "flags": [], "matches": [], "subject": ["제3조"], "missing_reason": None}
    miss = {"kind": "search_miss", "status": "NO_EVIDENCE", "evidence_id": "search:x:1", "text": None, "flags": [], "matches": [], "subject": ["x"]}
    state = {"answer": finalize([chunk, miss]), "evidence": [chunk, miss], "end_reason": "NORMAL"}
    rec = R.extract_trace(state)
    assert rec.evidence_texts == {"l1:notice:3": body}  # 본문이 있는 항목만
    ctx = {c.id: c.text for c in R.judge_contexts(rec)}
    assert ctx["l1:notice:3"].endswith(body) and ctx["l1:notice:3"] != body  # 머리 줄 + 본문 원문 그대로
    dumped = json.dumps(rec.to_json(), ensure_ascii=False)
    assert "evidence_texts" not in dumped and "가" * 50 not in json.dumps(rec.to_json()["evidence_order"], ensure_ascii=False)
    assert M.RunRecord.from_json(rec.to_json()).evidence_texts is None


def test_old_run_record_without_evidence_order_keeps_its_shape():
    rec = M.RunRecord(answer={})
    assert "evidence_order" not in rec.to_json() and M.RunRecord.from_json({"answer": {}}).evidence_order is None


# --------------------------------------------------------------------------- AG-11 `:52` 정리(2026-11-20): judge 키·옛 참조
def test_judge_key_is_not_a_graph_requirement():
    """`--judge none`(기본)은 judge 키 없이 돈다: `ANTHROPIC_API_KEY`는 그래프 필수 목록이 아니라 judge 전용 목록에만 있다."""
    assert "ANTHROPIC_API_KEY" not in R.GRAPH_REQUIRED_ENV
    assert R.JUDGE_REQUIRED_ENV == ("ANTHROPIC_API_KEY",)
    with pytest.raises(R.JudgeSetupError, match="ANTHROPIC_API_KEY"):
        R.default_judge(_settings(anthropic_api_key=None), 0.5)


def test_calib_docs_point_to_sonnet_judge_module():
    """`judge_calib` README·`calib_agreement.py`의 judge 참조가 실제 위치(`evaluation/judge/sonnet_judge.py`)를 가리킨다."""
    for rel in ("evaluation/judge_calib/calib_agreement.py", "evaluation/judge_calib/README.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "eval_runner.SonnetJudge" not in text and "eval_runner.py`의 `SonnetJudge" not in text, rel
        assert "evaluation/judge/sonnet_judge.py" in text, rel
    assert hasattr(SJ, "SonnetJudge") and callable(SJ.calib_result)
