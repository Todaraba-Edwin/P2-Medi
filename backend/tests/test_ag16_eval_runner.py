"""AG-16 C1 평가 연결 시험(2026-11-18): `eval_runner --agent graph --condition C1`이 고정 파이프라인을 만들어 돌리고 결과에 조건·버전·하네스 적용표를 남긴다.

LLM·judge·공공 API·원격 DB 호출 0, `.env` 미사용. 그래프는 가짜 모델·합성 소사전·소규모 SQLite로 만든다(자원 생성 함수를 주입).
질문은 합성이다(평가 세트 문항 아님). 시험셋 파일은 열지 않는다. 원장·로그 경로는 tmp로 돌린다.
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

import eval_runner as R  # noqa: E402
import sealed_guard as G  # noqa: E402
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.pipeline.build import HARNESS_BASELINE, HARNESS_VERSION, PIPELINE_VERSION  # noqa: E402
from app.config import Settings  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문(평가 세트 문항 아님)
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


def _settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d")


class CountingToolModel(ScriptedToolModel):
    """도구를 고르는 모델이 불렸는지 센다. C1에서는 한 번도 불리면 안 된다(도구 순서는 코드가 정한다)."""

    calls: int = 0

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        type(self).calls += 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class Factory:
    """주입용 자원 생성 함수(인자 모양은 C2 때와 같다: 조건을 받지 않는다)."""

    def __init__(self) -> None:
        self.sink = ListSink()
        self.calls: list[dict[str, Any]] = []
        self.summary: ScriptedSummary | None = None

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        self.calls.append({"prompt_set": prompt_set, "run_id": run_id})
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        self.summary = ScriptedSummary([{"sentences": [GUIDE]}])
        tracer = R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=self.sink)
        deps = build_deps(dd, ctx, tool_model=CountingToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True), summary_model=self.summary,
                          prompt_set=prompt_set, allow_draft=allow_draft, tracer=tracer)
        return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": dd.version, "built_at": dd.meta.get("built_at")})


def _synth_set(tmp_path: Path, n: int = 2) -> Path:
    p = tmp_path / "synth.jsonl"
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "dev", "set_version": "synth", "branch_label": "병용", "composition_group": "정상-병용",
             "expected_response_type": "found", "expected_path": {"required": ["identify_drug", "check_contraindications"],
                                                                 "order": [["identify_drug", "check_contraindications"]]},
             "required_elements": [], "dev_golden": True, "answer": {"items": []}} for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, condition: str | None, fac: Factory | None = None) -> tuple[int, dict[str, Any], Factory]:
    fac = fac or Factory()
    out = tmp_path / f"out-{condition or 'default'}.json"
    args = ["--set", str(_synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(out)]
    if condition:
        args += ["--condition", condition]
    rc = R.main(args, settings_fn=_settings, resources_factory=fac)
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}), fac


def test_c1_runs_the_fixed_pipeline_and_code_chooses_the_tools(tmp_path):
    CountingToolModel.calls = 0
    rc, res, fac = _run(tmp_path, "C1")
    assert rc == 0 and res["meta"]["condition"] == "C1" and res["meta"]["n_items_run"] == 2
    assert CountingToolModel.calls == 0  # 도구를 고르는 모델은 불리지 않는다
    for row in res["items"]:
        names = [c["name"] for c in row["run"]["tool_calls"]]
        # 약마다 식별 → 판정 → 사유 검색 → 허가사항 검색(코드가 정한 순서, RFP-23 §5.2)
        assert names == ["identify_drug", "identify_drug", "check_contraindications", "search_reason", "search_label", "search_label"]
        assert "ORDER_VIOLATION" not in row["trajectory"]["fails"] and "REQUIRED_MISSING" not in row["trajectory"]["fails"]
        assert "RUN_ERROR" not in row["trajectory"]["fails"] and row["run"]["answer"]


def test_c1_result_records_condition_versions_and_harness_table(tmp_path):
    rc, res, fac = _run(tmp_path, "C1")
    meta = res["meta"]
    assert meta["agent_info"]["condition"] == "C1" and meta["agent_info"]["run_id"].startswith("c1-")
    v = meta["versions"]
    assert v["graph"] == PIPELINE_VERSION and v["graph_src"].startswith("graph-src@") and v["pipeline_src"].startswith("pipeline-src@")
    assert meta["harness"] == {"version": HARNESS_VERSION, "condition": "C1", "baseline": list(HARNESS_BASELINE), "selection_limits": []}
    spans = fac.sink.records
    assert spans and {s.get("condition") for s in spans} == {"C1"}
    assert {s.get("graph_version") for s in spans} == {PIPELINE_VERSION}


def test_default_condition_is_still_the_react_graph(tmp_path):
    CountingToolModel.calls = 0
    rc, res, fac = _run(tmp_path, None)
    meta = res["meta"]
    assert rc == 0 and meta["condition"] == "C2" and meta["agent_info"]["run_id"].startswith("l2-")
    assert CountingToolModel.calls >= 2  # ReAct: 문항마다 모델이 도구를 고른다
    assert meta["versions"]["graph"].startswith("graph-src@") and "pipeline_src" not in meta["versions"]
    assert meta["harness"]["version"] == HARNESS_VERSION and meta["harness"]["condition"] == "C2"
    assert {s.get("condition") for s in fac.sink.records} == {"C2"}


def test_c1_and_c2_share_the_same_baseline_harness(tmp_path):
    _, c1, _ = _run(tmp_path, "C1")
    _, c2, _ = _run(tmp_path, "C2")
    assert c1["meta"]["harness"]["baseline"] == c2["meta"]["harness"]["baseline"]
    assert c1["meta"]["versions"]["harness"] == c2["meta"]["versions"]["harness"]  # 같은 하네스 소스


def test_c1_plus_is_not_connected(tmp_path, capsys):
    rc, res, fac = _run(tmp_path, "C1+")
    assert rc == 2 and res == {} and fac.calls == []  # 자원을 만들기 전에 멈춘다
    assert "C1+" in capsys.readouterr().out


def test_graph_agent_builds_by_condition(tmp_path):
    fac = Factory()
    resources = fac(_settings(), prompt_set="prompt_set@v3", allow_draft=False, run_id="t")
    R.apply_condition(resources, "C1")
    assert resources.deps.tracer.condition == "C1" and resources.deps.tracer.graph_version == PIPELINE_VERSION
    assert R.GraphAgent(resources, condition="C1").condition == "C1"
    with pytest.raises(ValueError, match="조건"):
        R.GraphAgent(resources, condition="C9")


# --------------------------------------------------------------------------- 오탈자 보정 스위치·문항 ID 선택(AG-10, 2026-11-18)

def _run_args(tmp_path: Path, *extra: str, fac: Factory | None = None, n: int = 4) -> tuple[int, dict[str, Any], Factory]:
    fac = fac or Factory()
    out = tmp_path / "out-x.json"
    rc = R.main(["--set", str(_synth_set(tmp_path, n)), "--agent", "graph", "--max-usd", "1", "--out", str(out), *extra],
                settings_fn=_settings, resources_factory=fac)
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}), fac


def test_typo_correct_is_off_by_default_and_recorded(tmp_path):
    seen: list[bool] = []

    class Spy(Factory):
        def __call__(self, settings: Any, **kw: Any) -> Any:
            res = super().__call__(settings, **kw)
            seen.append(res.deps.typo_correct)
            self.deps = res.deps
            return res

    rc, res, fac = _run_args(tmp_path, fac=Spy())
    assert rc == 0 and fac.deps.typo_correct is False
    tc = res["meta"]["typo_correction"]
    assert tc["enabled"] is False and tc["notice"] == "TYPO_CORRECTED_LINE" and tc["notice_status"] == "draft"


def test_typo_correct_flag_turns_the_router_switch_on(tmp_path):
    class Spy(Factory):
        def __call__(self, settings: Any, **kw: Any) -> Any:
            res = super().__call__(settings, **kw)
            self.deps = res.deps
            return res

    rc, res, fac = _run_args(tmp_path, "--typo-correct", fac=Spy())
    assert rc == 0 and fac.deps.typo_correct is True
    tc = res["meta"]["typo_correction"]
    assert tc["enabled"] is True and tc["min_score"] == 0.9 and tc["min_gap"] == 0.05


@pytest.mark.parametrize("extra", [("--condition", "C1"), ()])
def test_typo_correct_is_refused_outside_react_graph(extra, tmp_path, capsys):
    """C1은 보정이 없는 고정 파이프라인이다(보정을 더한 것은 C1+). offline-fixed는 그래프를 만들지 않는다. 둘 다 세트를 읽기 전에 막는다."""
    args = ["--set", str(tmp_path / "none.jsonl"), "--typo-correct", "--out", str(tmp_path / "o.json"), *extra]
    if extra:
        args += ["--agent", "graph", "--max-usd", "1"]
    assert R.main(args, settings_fn=_settings, resources_factory=Factory()) == 2
    assert "--typo-correct" in capsys.readouterr().out and not (tmp_path / "o.json").exists()


def test_ids_select_only_those_items_in_set_order(tmp_path):
    rc, res, _ = _run_args(tmp_path, "--ids", "syn-002, syn-000")
    assert rc == 0 and [r["id"] for r in res["items"]] == ["syn-000", "syn-002"] and res["meta"]["n_items_run"] == 2


def test_ids_with_unknown_item_stops_before_running(tmp_path, capsys):
    rc, res, fac = _run_args(tmp_path, "--ids", "syn-000,syn-999")
    assert rc == 2 and res == {} and fac.calls == []
    assert "syn-999" in capsys.readouterr().out


def test_ids_is_refused_for_the_sealed_set_before_any_read(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "fake-set.jsonl"  # 존재하지 않는 가짜 경로: 읽으려 하면 오류가 난다. 실제 시험셋·허용 플래그·환경변수는 쓰지 않는다
    monkeypatch.setattr(G, "check_access", lambda path, allow_sealed=False: True)  # "시험셋으로 판정됨"만 흉내 낸다
    rc = R.main(["--set", str(fake), "--ids", "t-1", "--out", str(tmp_path / "o.json")])
    assert rc == 2 and "--ids" in capsys.readouterr().out and not (tmp_path / "o.json").exists()
