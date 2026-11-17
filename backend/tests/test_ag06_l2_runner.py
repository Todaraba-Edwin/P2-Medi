"""AG-06 L2 실행기 시험(goal 5회차): `--agent graph`(실제 그래프 부품·개발 골든·묶음 v2 대 v3), 비용 상한, 출처 누락 보조 집계, 비교 요약.

LLM·judge·공공 API·원격 DB 호출 0, `.env` 미사용. 그래프는 가짜 모델·합성 소사전·소규모 SQLite로 만든다(자원 생성 함수를 주입).
시험셋 파일은 열지 않는다. 개발셋은 `dev_golden` 표시 행을 **ID와 집계로만** 본다(질문 문장을 출력·단정하지 않는다).
원장·로그 경로는 tmp로 돌린다(`MEDIAGENT_LEDGER_PATH`·`MEDIAGENT_LOG_DIR`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

import eval_metrics as M  # noqa: E402
import eval_runner as R  # noqa: E402
import sealed_guard as G  # noqa: E402
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent.graph import wiring  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.prompt import DraftPromptError  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm import prompts as lp  # noqa: E402

PH = M.Phrases.from_backend()
COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문(평가 세트 문항 아님)
PAIR_EID = "contra_pair:254000ATB:625201ATB"
SECRET = "QQQQ-가짜비밀표지-5521"
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}, GUIDE]}
ENV_NAMES = ("OPENAI_API_KEY", "SUPABASE_DB_URL")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """원장·로그를 tmp로 돌리고 관련 환경변수를 지운다. `MEDIAGENT_EVAL`은 실행기가 바꾸므로 끝나면 되돌아가게 먼저 잡아 둔다."""
    for n in (*ENV_NAMES, "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


def _settings(**over: Any) -> Settings:
    vals: dict[str, Any] = {n.lower(): f"{SECRET}-{i}" for i, n in enumerate(ENV_NAMES)}
    vals.update(over)
    return Settings(_env_file=None, **{k: v for k, v in vals.items() if v is not None})


class Cost:
    """가짜 누적 비용(USD). 요약 모델이 불릴 때마다 `per_call`만큼 는다."""

    def __init__(self, per_call: float = 0.0) -> None:
        self.total, self.per_call = 0.0, per_call

    def __call__(self) -> float:
        return self.total


class CostingSummary(ScriptedSummary):
    def __init__(self, drafts: Any, cost: Cost) -> None:
        super().__init__(drafts)
        self.cost = cost
        self.seen: list[str] = []

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        self.cost.total += self.cost.per_call
        self.seen.append(str(messages[-1].content))
        return super().invoke(messages, **kwargs)


class FakeFactory:
    """주입용 자원 생성 함수. 어떤 질문이 와도 끝까지 가는 가짜 모델(도구를 부르지 않고 안내 한 문장)로 평가 모드 그래프 의존성을 만든다."""

    def __init__(self, *, per_call: float = 0.0, script: list[AIMessage] | None = None, drafts: list[Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cost = Cost(per_call)
        self.script = script
        self.drafts = drafts or [{"sentences": [GUIDE]}]
        self.summary: CostingSummary | None = None
        self.sink = ListSink()

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        self.calls.append({"prompt_set": prompt_set, "allow_draft": allow_draft, "run_id": run_id})
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        tm = ScriptedToolModel(script=self.script or [AIMessage("조회를 마쳤다")], repeat_last=True)
        self.summary = CostingSummary(self.drafts, self.cost)
        tracer = R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=self.sink)
        deps = build_deps(dd, ctx, tool_model=tm, summary_model=self.summary, prompt_set=prompt_set, allow_draft=allow_draft, tracer=tracer)
        return R.GraphResources(deps=deps, cost_total=self.cost, dict_meta={"version": dd.version, "built_at": dd.meta.get("built_at")})


def _main(args: list[str], factory: Any = None, settings: Any = None) -> int:
    return R.main(args, settings_fn=lambda: settings if settings is not None else _settings(), resources_factory=factory or FakeFactory())


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _synth_set(tmp_path: Path, n: int = 3) -> Path:
    """합성 문항 n개(평가 세트 아님). 모두 모델까지 가는 병용 질문이다."""
    p = tmp_path / "synth.jsonl"
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "dev", "set_version": "synth", "branch_label": "병용", "composition_group": "정상-병용",
             "expected_response_type": "found", "expected_path": {"required": ["check_contraindications"]}, "required_elements": [],
             "dev_golden": i % 2 == 0, "answer": {"items": []}} for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _pair_script() -> list[AIMessage]:
    return [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c1")]),
            AIMessage("조회를 마쳤다")]


class PerItemScript(ScriptedToolModel):
    """문항마다 같은 스크립트를 처음부터 다시 쓰는 가짜(메시지가 2개면 새 문항의 첫 호출이다)."""

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        if not any(getattr(m, "tool_calls", None) or m.type == "tool" for m in messages):
            self._i = 0
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


# =========================================================================== §2-1 `--agent graph`
def test_graph_agent_runs_only_the_20_dev_golden_items_and_fills_versions(tmp_path, capsys):
    out = tmp_path / "v2.json"
    fac = FakeFactory()
    assert _main(["--set", "dev", "--agent", "graph", "--subset", "dev_golden", "--max-usd", "0.25", "--out", str(out)], fac) == 0
    res = _load(out)
    base, _ = lp.split_frontmatter((lp.PROMPTS_DIR / "agent_system@v2.md").read_text(encoding="utf-8"))
    assert [r["id"] for r in res["items"]] == base["golden_ids"] and res["meta"]["n_items_run"] == 20  # 개발 골든 20개만(ID 순)
    assert res["meta"]["subset"] == "dev_golden" and res["meta"]["agent"] == "graph" and res["meta"]["eval_mode_env"] == "1"
    v = res["meta"]["versions"]
    assert v["model"] == {"agent": "gpt-6-luna", "summary": "gpt-6-luna"}
    assert v["prompt"]["set"] == "prompt_set@v2" and [f["ref"] for f in v["prompt"]["files"]] == ["agent_system@v2"]
    f0 = v["prompt"]["files"][0]
    assert f0["id"] == "P-AG01-model" and f0["version"] == "v2" and f0["status"] == "adopted" and len(f0["sha256"]) == 64
    assert v["graph"] and v["harness"] and v["dict"]["version"] == "golden-synth-v1"
    assert res["judge"] is None and all(r["judge"] is None for r in res["items"])  # judge는 이번 L2에 붙이지 않는다
    assert fac.calls == [{"prompt_set": "prompt_set@v2", "allow_draft": False, "run_id": fac.calls[0]["run_id"]}]
    printed = capsys.readouterr().out
    assert "20" in printed and all(SECRET not in s for s in (printed, out.read_text(encoding="utf-8")))
    # 개발셋 질문 문장은 결과 파일에 들어가지 않는다(실행 기록에는 질문 원문을 넣지 않는다)
    assert '"question"' not in out.read_text(encoding="utf-8")


def test_graph_agent_forces_eval_mode_and_api_off(tmp_path, monkeypatch):
    import os

    fac = FakeFactory()
    assert _main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(tmp_path / "o.json")], fac) == 0
    assert os.environ["MEDIAGENT_EVAL"] == "1"  # 캐시 off(llm_cache·anthropic 의존 없음)
    from app.llm.cache import cache_mode

    monkeypatch.setenv("LLM_CACHE", "record")
    assert cache_mode() == "off"


def test_trace_carries_the_prompt_set_name(tmp_path):
    fac = FakeFactory(script=_pair_script())
    fac_model = PerItemScript(script=_pair_script(), repeat_last=True)
    orig = fac.__call__

    def with_model(settings: Any, **kw: Any) -> Any:
        res = orig(settings, **kw)
        from dataclasses import replace

        return R.GraphResources(deps=replace(res.deps, tool_model=fac_model), cost_total=res.cost_total, dict_meta=res.dict_meta)

    args = ["--set", str(_synth_set(tmp_path, 2)), "--agent", "graph", "--prompt-set", "prompt_set@v3", "--allow-draft", "--max-usd", "1",
            "--out", str(tmp_path / "o.json")]
    assert R.main(args, settings_fn=_settings, resources_factory=with_model) == 0
    recs = fac.sink.records
    assert recs and {r.get("prompt_set") for r in recs} == {"prompt_set@v3"}
    assert {r.get("item_id") for r in recs} == {"syn-000", "syn-001"} and {r.get("condition") for r in recs} == {"C2"}


def test_v3_needs_allow_draft_and_uses_summary_file_when_allowed(tmp_path):
    base = ["--set", str(_synth_set(tmp_path, 1)), "--agent", "graph", "--prompt-set", "prompt_set@v3", "--max-usd", "1"]
    fac = FakeFactory()
    with pytest.raises(DraftPromptError):
        _main([*base, "--out", str(tmp_path / "x.json")], fac)
    assert fac.calls == [] and not (tmp_path / "x.json").exists()  # 자원을 만들기 전에 멈춘다
    fac = FakeFactory(script=_pair_script(), drafts=[PAIR_DRAFT])
    assert _main([*base, "--allow-draft", "--out", str(tmp_path / "v3.json")], fac) == 0
    res = _load(tmp_path / "v3.json")
    files = res["meta"]["versions"]["prompt"]["files"]
    assert [f["ref"] for f in files] == ["agent_system@v2", "answer_summary@v1"] and files[1]["status"] == "draft"
    _, body = lp.split_frontmatter((lp.PROMPTS_DIR / "answer_summary@v1.md").read_text(encoding="utf-8"))
    assert fac.summary is not None and fac.summary.seen and fac.summary.seen[0].endswith(body.strip())


def test_system_prompt_mismatch_stops_before_start(tmp_path, monkeypatch):
    R.check_system_prompt("prompt_set@v2", "agent_system@v2")
    R.check_system_prompt("prompt_set@v3", "agent_system@v2")
    with pytest.raises(R.RunnerConfigError):
        R.check_system_prompt("prompt_set@v1", "agent_system@v2")  # 묶음은 agent_system@v1
    monkeypatch.setattr(wiring, "DEFAULT_PROMPT", "agent_system@v1")
    fac = FakeFactory()
    with pytest.raises(R.RunnerConfigError):
        _main(["--set", str(_synth_set(tmp_path, 1)), "--agent", "graph", "--max-usd", "1", "--out", str(tmp_path / "x.json")], fac)
    assert fac.calls == []


def test_missing_settings_prints_names_only_and_runs_nothing(tmp_path, capsys):
    fac = FakeFactory()
    out = tmp_path / "o.json"
    rc = _main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(out)], fac,
               settings=_settings(supabase_db_url=None))
    printed = capsys.readouterr().out
    assert rc == 0 and fac.calls == [] and not out.exists()
    assert "SUPABASE_DB_URL" in printed and "OPENAI_API_KEY" not in printed and SECRET not in printed
    assert "DURPrdlstInfoService03_API_KEY" not in printed  # 평가 모드는 API 병기를 끄므로 DUR 변수는 요구하지 않는다


def test_sealed_set_is_still_blocked_before_opening(tmp_path, monkeypatch):
    fac = FakeFactory()
    opened: list[str] = []
    real = Path.read_bytes

    def spy(self: Path, *a: Any, **k: Any) -> bytes:
        opened.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", spy)
    with pytest.raises(G.SealedAccessError):
        _main(["--set", "test", "--agent", "graph", "--subset", "dev_golden", "--max-usd", "0.25", "--out", str(tmp_path / "x.json")], fac)
    assert fac.calls == [] and not [n for n in opened if "SEALED" in n]


def test_subset_selects_only_marked_rows():
    rows = [{"id": "a", "dev_golden": True}, {"id": "b", "dev_golden": False}, {"id": "c"}]
    assert [r["id"] for r in R.select_subset(rows, "dev_golden")] == ["a"]
    assert R.select_subset(rows, None) == rows
    with pytest.raises(R.RunnerConfigError):
        R.select_subset(rows, "golden")  # 시험셋 골든 표시는 고를 수 없다


def test_offline_fixed_default_output_is_unchanged(tmp_path):
    """회귀: 기본 에이전트의 결과 형식·값이 그대로다(새 칸이 끼어들지 않는다)."""
    out = tmp_path / "off.json"
    assert R.main(["--set", str(_synth_set(tmp_path)), "--out", str(out)]) == 0
    res = _load(out)
    assert set(res) == {"meta", "metrics", "items"}
    assert res["meta"]["agent"] == "offline-fixed" and res["meta"]["versions"] == {"model": None, "prompt": None, "graph": None, "harness": None, "dict": None}
    assert set(res["meta"]) == {"runner", "created_utc", "sealed", "repeats", "eval_mode_env", "judge", "patterns", "set", "set_file", "set_sha256",
                                "manifest_set_version", "manifest_sha256", "match", "set_version", "n_items_run", "condition", "agent", "agent_info", "versions"}
    row = res["items"][0]
    assert set(row) == {"id", "branch_label", "composition_group", "expected_response_type", "pair_of", "reliability_core", "judgment", "elements",
                        "safety", "trajectory", "routing_required_all", "cost", "judge", "run"}
    assert set(row["run"]) == {"answer", "tool_calls", "model_calls", "end_reason", "tool_evidence_ids", "clarify_options", "latency_s", "tokens", "error"}
    assert set(row["cost"]) == {"model_calls", "latency_s", "tokens"} and row["judge"]["status"] == "not_called"
    assert "aux_source_missing" not in res["metrics"] and len(res["items"]) == 3  # --subset 없이는 전부


# =========================================================================== §2-2 비용 상한
def test_graph_agent_refuses_to_start_without_max_usd(tmp_path, capsys):
    fac = FakeFactory()
    for extra in ([], ["--max-usd", "0"]):
        rc = _main(["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--out", str(tmp_path / "o.json"), *extra], fac)
        assert rc == 2 and fac.calls == [] and not (tmp_path / "o.json").exists()
    assert "--max-usd" in capsys.readouterr().out


def test_cost_cap_skips_remaining_items_and_records_them(tmp_path):
    fac = FakeFactory(per_call=0.1, script=_pair_script(), drafts=[PAIR_DRAFT])
    orig = fac.__call__

    def with_model(settings: Any, **kw: Any) -> Any:
        from dataclasses import replace

        res = orig(settings, **kw)
        return R.GraphResources(deps=replace(res.deps, tool_model=PerItemScript(script=_pair_script(), repeat_last=True)),
                                cost_total=res.cost_total, dict_meta=res.dict_meta)

    out = tmp_path / "cap.json"
    rc = R.main(["--set", str(_synth_set(tmp_path, 5)), "--agent", "graph", "--max-usd", "0.15", "--out", str(out)],
                settings_fn=_settings, resources_factory=with_model)
    res = _load(out)
    assert rc == 0
    assert [r["id"] for r in res["items"]] == ["syn-000", "syn-001"]  # 0.1 → 0.2(상한 도달) → 다음 문항부터 건너뜀
    assert res["skipped_cost_cap"] == ["syn-002", "syn-003", "syn-004"]
    c = res["cost_usd"]
    assert c["max_usd"] == 0.15 and c["cap_reached"] is True and c["total"] == pytest.approx(0.2)
    assert c["by_item"] == {"syn-000": pytest.approx(0.1), "syn-001": pytest.approx(0.1)}
    assert res["metrics"]["n_items"] == 2 and res["meta"]["n_items_run"] == 2 and res["meta"]["n_items_selected"] == 5


def test_cost_budget_counts_only_this_run_and_checks_before_each_item():
    cost = Cost()
    cost.total = 5.0  # 원장에 이미 쌓인 값은 이번 실행 몫이 아니다
    b = R.CostBudget(0.3, cost)
    assert b.spent() == 0 and not b.exhausted()
    cost.total += 0.1
    assert b.item_cost() == pytest.approx(0.1) and b.item_cost() == 0 and not b.exhausted()
    cost.total += 0.2
    assert b.exhausted() and b.spent() == pytest.approx(0.3)
    with pytest.raises(R.RunnerConfigError):
        R.CostBudget(0, cost)


def test_run_eval_without_budget_has_no_cost_keys():
    rows = [{"id": "x", "question": "약 처방해 줘", "required_elements": [], "answer": {"items": []}}]
    res = R.run_eval(rows, R.OfflineFixedAgent(), sealed=False)
    assert "cost_usd" not in res and "skipped_cost_cap" not in res and "cost_usd" not in res["items"][0]


def test_real_cost_source_is_the_eval_bucket_of_the_ledger(tmp_path):
    from app.llm.ledger import DEV_CAP_USD, CostLedger

    ledger = CostLedger(tmp_path / "l.json")
    total = R.ledger_cost_total(ledger)
    ledger.add(0.5, "dev")
    assert total() == 0  # 개발 몫은 세지 않는다(평가 실행은 eval 몫으로 쌓인다)
    ledger.add(0.02, "eval")
    assert total() == pytest.approx(0.02) and DEV_CAP_USD == 2.5  # 개발 상한은 그대로


# =========================================================================== §2-3 출처 누락·인용 불일치 보조 집계
def _state(**over: Any) -> dict[str, Any]:
    st: dict[str, Any] = {
        "answer": {}, "end_reason": "NORMAL", "call_count": 3, "messages": [], "evidence": [], "known_ids": set(),
        "final_sentences": [{"text": "a", "evidence_ids": ["e1"], "claim_type": "fact"}, {"text": "b", "evidence_ids": [], "claim_type": "guidance"}],
        "events": [],
    }
    st.update(over)
    return st


def test_source_missing_counts_from_state_events_and_final_sentences():
    st = _state(
        events=[{"rule": "H1", "event": "SENTENCE_FILTER", "total": 4, "kept": 1, "dropped": 3, "reasons": {"NO_EVIDENCE": 2, "CODE_IN_TEXT": 1}},
                {"rule": "H2", "event": "VALIDATOR", "status": "FAIL", "reasons": {"QUOTE_MISMATCH": 1}},
                {"rule": "H2", "event": "REWIND", "reasons": ["X"]},
                {"rule": "H1", "event": "SENTENCE_FILTER", "total": 2, "kept": 1, "dropped": 1, "reasons": {"NO_EVIDENCE": 1}},
                {"rule": "H2", "event": "VALIDATOR", "status": "FIXED", "reasons": {"QUOTE_MISMATCH": 2, "SAFETY": 1}},
                {"rule": "H2", "event": "VALIDATION_FALLBACK", "reasons": ["X"]}],
        final_sentences=[{"text": "a", "evidence_ids": [], "claim_type": "fact"}, {"text": "b", "evidence_ids": [], "claim_type": "conclusion"},
                         {"text": "c", "evidence_ids": ["e"], "claim_type": "fact"}])
    assert R.source_missing_counts(st) == {"no_evidence_dropped": 3, "uncited_fact_sentences": 1, "quote_mismatch": 3, "harness_blocks": 1}
    assert R.source_missing_counts(_state()) == {"no_evidence_dropped": 0, "uncited_fact_sentences": 0, "quote_mismatch": 0, "harness_blocks": 0}
    rec = R.extract_trace(st)
    assert (rec.no_evidence_dropped, rec.uncited_fact_sentences, rec.quote_mismatch, rec.harness_blocks) == (3, 1, 3, 1)


def test_reason_names_match_the_agent_code():
    from app.agent import sentence_filter, validator

    assert R.REASON_NO_EVIDENCE == sentence_filter.NO_EVIDENCE == "NO_EVIDENCE"
    assert R.REASON_QUOTE_MISMATCH == validator.QUOTE_MISMATCH == "QUOTE_MISMATCH"


def test_run_record_aux_fields_are_optional_and_omitted_when_absent():
    plain = M.RunRecord(answer={})
    assert not {"no_evidence_dropped", "uncited_fact_sentences", "quote_mismatch", "harness_blocks"} & set(plain.to_json())
    full = M.RunRecord(answer={}, no_evidence_dropped=0, uncited_fact_sentences=0, quote_mismatch=2, harness_blocks=0)
    assert full.to_json()["quote_mismatch"] == 2 and full.to_json()["no_evidence_dropped"] == 0


def _item(i: int) -> dict[str, Any]:
    return {"id": f"q{i}", "branch_label": "병용", "composition_group": "정상-병용", "expected_response_type": "found", "required_elements": [],
            "expected_path": {}, "answer": {"items": []}}


def test_aggregate_adds_aux_block_without_changing_existing_metrics():
    recs = [M.RunRecord(answer={}, end_reason="NORMAL", no_evidence_dropped=a, uncited_fact_sentences=b, quote_mismatch=c, harness_blocks=d)
            for a, b, c, d in [(0, 0, 0, 0), (2, 0, 1, 0), (0, 1, 0, 1), (0, 0, 3, 0)]]
    rows = [M.score_item(_item(i), r, PH) for i, r in enumerate(recs)]
    plain_rows = [M.score_item(_item(i), M.RunRecord(answer={}, end_reason="NORMAL"), PH) for i in range(4)]
    agg, plain = M.aggregate(rows), M.aggregate(plain_rows)
    aux = agg.pop("aux_source_missing")
    assert agg == plain and "aux_source_missing" not in plain  # 9장 지표 계산은 그대로
    assert all("aux" not in r for r in plain_rows) and rows[1]["aux"] == {"no_evidence_dropped": 2, "uncited_fact_sentences": 0, "quote_mismatch": 1,
                                                                         "harness_blocks": 0}
    assert aux["items_with_aux"] == 4 and aux["no_evidence_dropped_total"] == 2 and aux["uncited_fact_sentences_total"] == 1
    assert aux["quote_mismatch_total"] == 4 and aux["harness_blocks_total"] == 1
    assert aux["source_missing_zero_items"] == M.kn(2, 4)  # 걸러진 근거 없음 0 + 남은 빈 근거 사실 문장 0인 문항
    assert "보조" in aux["note"]


def test_graph_run_reports_aux_counts_end_to_end(tmp_path):
    """그래프를 실제로 돌린 상태에서 센다: 근거 ID 없는 사실 문장 1개가 걸러지고 최종 답에는 남지 않는다."""
    bad = {"sentences": [{"text": "근거 없이 쓴 사실 문장이에요.", "evidence_ids": [], "claim_type": "fact", "citations": []}, *PAIR_DRAFT["sentences"]]}
    fac = FakeFactory(script=_pair_script(), drafts=[bad])
    out = tmp_path / "aux.json"
    assert _main(["--set", str(_synth_set(tmp_path, 1)), "--agent", "graph", "--max-usd", "1", "--out", str(out)], fac) == 0
    res = _load(out)
    assert res["items"][0]["aux"] == {"no_evidence_dropped": 1, "uncited_fact_sentences": 0, "quote_mismatch": 0, "harness_blocks": 0}
    aux = res["metrics"]["aux_source_missing"]
    assert aux["no_evidence_dropped_total"] == 1 and aux["source_missing_zero_items"]["k"] == 0 and aux["source_missing_zero_items"]["n"] == 1


# =========================================================================== §2-4 v2 대 v3 비교
def _result(label: str, verdicts: list[str], aux: list[tuple[int, int, int, int]], cost: float, skipped: list[str] | None = None) -> dict[str, Any]:
    items = []
    for i, (v, a) in enumerate(zip(verdicts, aux, strict=True)):
        items.append({"id": f"dev-{i:03d}", "trajectory": {"verdict": v, "end_reason": "NORMAL", "fails": []},
                      "aux": dict(zip(("no_evidence_dropped", "uncited_fact_sentences", "quote_mismatch", "harness_blocks"), a, strict=True))})
    rows_for_aux = [{"aux": it["aux"]} for it in items]
    return {"meta": {"versions": {"prompt": {"set": label}}, "set": "dev", "subset": "dev_golden", "n_items_run": len(items)},
            "metrics": {"n_items": len(items), "aux_source_missing": M.aux_summary(rows_for_aux)}, "items": items,
            "cost_usd": {"total": cost, "max_usd": 0.25, "cap_reached": bool(skipped), "by_item": {}}, "skipped_cost_cap": skipped or []}


def test_compare_builds_side_by_side_table_with_wilson_from_existing_function():
    a = _result("prompt_set@v2", ["Pass", "Pass", "Warn", "Fail"], [(0, 0, 0, 0)] * 4, 0.05)
    b = _result("prompt_set@v3", ["Pass", "Fail", "Warn", "Fail"], [(0, 0, 0, 0), (1, 0, 2, 1), (0, 0, 0, 0), (0, 0, 0, 0)], 0.07, ["dev-009"])
    cmp = R.compare_results(a, b)
    assert [s["label"] for s in cmp["sides"]] == ["prompt_set@v2", "prompt_set@v3"]
    sa, sb = cmp["sides"]
    assert sa["trajectory_pass"] == M.kn(2, 4) and sb["trajectory_pass"] == M.kn(1, 4)  # Wilson 구간은 기존 함수 그대로
    assert sa["trajectory_pass"]["wilson95"] == [round(x, 4) for x in M.wilson(2, 4)]
    assert sb["harness_blocks"] == 1 and sb["quote_mismatch"] == 2 and sb["no_evidence_dropped"] == 1 and sa["quote_mismatch"] == 0
    assert sa["source_missing_zero_items"] == M.kn(4, 4) and sb["source_missing_zero_items"] == M.kn(3, 4)
    assert sa["cost_usd"] == 0.05 and sb["cost_usd"] == 0.07 and sb["skipped_cost_cap"] == 1
    assert cmp["diff_ids"] == ["dev-001"] and cmp["only_in_one"] == []
    assert cmp["claim"] == "회귀 경보 전용(개선 주장에 쓰지 않는다)"
    text = R.format_compare(cmp)
    assert "회귀 경보" in text and "prompt_set@v2" in text and "prompt_set@v3" in text and "dev-001" in text
    assert "개선됐" not in text and "향상" not in text and "유의" not in text.replace("유의성 주장 안 함", "")


def test_compare_cli_prints_table_and_runs_no_agent(tmp_path, capsys):
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(_result("prompt_set@v2", ["Pass"] * 3, [(0, 0, 0, 0)] * 3, 0.01)), encoding="utf-8")
    pb.write_text(json.dumps(_result("prompt_set@v3", ["Pass"] * 3, [(0, 0, 0, 0)] * 3, 0.02)), encoding="utf-8")
    fac = FakeFactory()
    assert _main(["--compare", str(pa), str(pb)], fac) == 0
    out = capsys.readouterr().out
    assert "회귀 경보" in out and "3/3" in out and fac.calls == []
    assert R.compare_results(_load(pa), _load(pb))["diff_ids"] == []


def test_compare_refuses_sealed_results(tmp_path):
    a = _result("prompt_set@v2", ["Pass"], [(0, 0, 0, 0)], 0.0)
    b = {**a, "items": "omitted: sealed set (scores only, RFP-26-04)"}
    with pytest.raises(R.RunnerConfigError):
        R.compare_results(a, b)


def test_default_tracer_writes_eval_spans_with_prompt_set_under_log_dir(tmp_path, monkeypatch):
    """실제 실행 때 쓰는 기록기(sink 미주입): 평가 모드 기록 파일이 로그 폴더(tmp)의 run_id 아래에 생기고 줄마다 묶음 이름이 있다."""
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    run_id = "l2-prompt_set-v3-20261117T000000Z"
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
    tracer = R.make_tracer(prompt_set="prompt_set@v3", run_id=run_id, condition="C2")
    deps = build_deps(dd, ctx, tool_model=PerItemScript(script=_pair_script(), repeat_last=True), summary_model=ScriptedSummary([PAIR_DRAFT]),
                      prompt_set="prompt_set@v3", allow_draft=True, tracer=tracer)
    agent = R.GraphAgent(R.GraphResources(deps=deps, cost_total=Cost()), info={})
    rec = agent({"id": "syn-000", "question": Q_PAIR})
    assert rec.error is None and rec.end_reason == "NORMAL"
    spans = tmp_path / "logs" / "eval" / run_id / "spans.jsonl"
    rows = [json.loads(x) for x in spans.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and {r.get("prompt_set") for r in rows} == {"prompt_set@v3"} and {r.get("item_id") for r in rows} == {"syn-000"}
    assert not (ROOT / "logs" / "eval" / run_id).exists()  # 저장소 로그 폴더에는 쓰지 않았다


# --------------------------------------------------------------------------- 평가 세트 프로필 → 그래프 프로필 변환(L2 스모크 ValidationError)

DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"


def test_every_dev_set_profile_converts_to_a_valid_graph_profile():
    """개발셋 150행의 프로필이 모두 변환 뒤 그래프 `ProfileState`를 통과한다(질문 문장은 읽지 않고 출력하지 않는다)."""
    from app.agent.router import ProfileState

    n = 0
    for line in DEV_SET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gp = R.to_graph_profile(row.get("profile"))
        if gp is not None:
            ProfileState.model_validate(gp)
        n += 1
    assert n == 150


@pytest.mark.parametrize(("profile", "expected"), [
    ({"age": {"value": 5, "unit": "세"}, "pregnant": False}, {"age_years": 5.0, "pregnant": False}),
    ({"age": {"value": 18, "unit": "개월"}, "pregnant": False}, {"age_years": 1.5, "pregnant": False}),
    ({"age": {"value": 7, "unit": "개월"}, "pregnant": None}, {"age_years": 0.58}),  # router `_AGE_MONTH_RE`와 같은 규칙: 개월/12, 소수 둘째 자리
    ({"age": None, "pregnant": True}, {"pregnant": True}),
    ({"age": None, "pregnant": False}, {"pregnant": False}),
])
def test_to_graph_profile_converts_units_to_years(profile, expected):
    assert R.to_graph_profile(profile) == expected


@pytest.mark.parametrize("profile", [None, {}, {"age": None, "pregnant": None}, {"age": None}])
def test_to_graph_profile_returns_none_for_empty(profile):
    assert R.to_graph_profile(profile) is None


@pytest.mark.parametrize("profile", [
    {"age": {"value": 3, "unit": "주"}, "pregnant": False},  # 모르는 단위
    {"age": {"value": 3, "unit": None}, "pregnant": False},
    {"age": {"value": "다섯", "unit": "세"}, "pregnant": False},  # 숫자가 아닌 값
    {"age": {"value": True, "unit": "세"}, "pregnant": False},
    {"age": {"value": -1, "unit": "세"}, "pregnant": False},
    {"age": 5, "pregnant": False},  # 단위 없는 숫자
    {"age": None, "pregnant": "yes"},
    {"age": None, "pregnant": False, "sex": "F"},  # 모르는 키를 조용히 버리지 않는다
])
def test_to_graph_profile_rejects_unknown_shapes(profile):
    with pytest.raises(R.ProfileFormatError):
        R.to_graph_profile(profile)


def test_graph_adapter_passes_converted_profile_and_stops_on_bad_profile():
    """어댑터는 변환한 프로필을 넘긴다. 형식 오류는 에이전트 실패(경로 Fail)로 섞지 않고 실행을 멈춘다."""
    seen: list[Any] = []

    class FakeGraph:
        def invoke(self, state):
            seen.append(state.get("profile"))
            return {"answer": {}, "end_reason": "NORMAL"}

    ad = R.GraphAdapter(FakeGraph())
    rec = ad({"id": "x", "question": "q", "profile": {"age": {"value": 24, "unit": "개월"}, "pregnant": False}})
    assert rec.error is None and seen == [{"age_years": 2.0, "pregnant": False}]
    with pytest.raises(R.ProfileFormatError):
        ad({"id": "y", "question": "q", "profile": {"age": {"value": 1, "unit": "년반"}, "pregnant": False}})
    assert len(seen) == 1
