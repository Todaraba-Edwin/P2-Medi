"""AG-11-14 A 신뢰성 집계 우회 시험(2026-11-18). LLM·judge·공공 API·원격 DB 호출 0(가짜 모델·합성 사전·합성 세트).

- rel2 사고: 시험셋 모양 행(`run` 없음)의 `trajectory.duplicates`(정수)가 1 이상이면 동결 채점 코드 `eval_metrics._path_sig`가 TypeError.
  채점 코드는 고치지 않고 러너가 집계에 넘기는 사본만 바꾼다(0 → [], n → [n]). 0만 있으면 예전 값과 같다.
- 반복 실행은 집계 전에 결과 옆 `결과.rows-partial.json`을 쓰고(시험셋은 원문·ID 없음), 저장이 끝나면 지운다.
  집계가 멈추면 그 파일이 남고 `--reaggregate`가 실행 없이 집계만 다시 해 같은 값을 낸다.
"""

from __future__ import annotations

import copy
import json
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
from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.config import Settings  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"  # 합성 질문
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
SECRET_EID = "contra_pair:SYNTH-SECRET-A:SYNTH-SECRET-B"  # 시험셋 파일에 원문으로 남으면 안 되는 근거 ID(합성)
REL_ARGS = ("--subset", "reliability_core", "--repeats", "3")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


class Factory:
    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                          summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), prompt_set=prompt_set, allow_draft=allow_draft,
                          tracer=R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=ListSink()))
        return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": dd.version},
                                corpus_meta={"source": "synthetic", "n_chunks": 0, "sha256": "0" * 64})


def _set(tmp_path: Path, *, name: str = "synth_test.SEALED.jsonl", mark: str = "reliability_core", n: int = 4, core: int = 2) -> Path:
    p = tmp_path / name
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "test", "set_version": "synth", "branch_label": "정상",
             "composition_group": "정상-병용", "expected_response_type": "judgment", "expected_path": {"required": []},
             "required_elements": ["DISCLAIMER"], "answer": {"items": [{"status": "FOUND", "evidence_id": SECRET_EID, "matches": []}]},
             mark: i < core}
            for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, out: str, set_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    path = tmp_path / out
    rc = R.main(["--set", str(set_path), "--agent", "graph", "--max-usd", "1", "--out", str(path), *extra],
                settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d"), resources_factory=Factory())
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() and rc == 0 else {})


def _inject_duplicates(monkeypatch, plan: list[int]) -> None:
    """채점 행의 `trajectory.duplicates`를 호출 순서대로 `plan` 값으로 바꾼다(가짜 모델로는 중복 호출을 만들기 어려워 채점 결과에 넣는다)."""
    orig = M.score_item
    it = iter(plan)

    def scored(item, rec, ph):
        row = orig(item, rec, ph)
        row["trajectory"]["duplicates"] = next(it, 0)
        return row

    monkeypatch.setattr(M, "score_item", scored)


def _row(qid: str, dup: Any, **traj: Any) -> dict[str, Any]:
    """시험셋 carry 모양 행(`run` 없음)."""
    return {"id": qid, "safety": None, "elements": {"DISCLAIMER": True},
            "judgment": {"applicable": True, "correct": True, "items": [{"evidence_id": "h", "got": "found", "got_grades": []}]},
            "trajectory": {"verdict": "Pass", "end_reason": "NORMAL", "model_calls": 2, "fails": [], "extra_tools": [], "duplicates": dup, **traj}}


def _sealed_env(monkeypatch) -> None:
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)


# --------------------------------------------------------------------------- 1. 우회(단위)

def test_frozen_scorer_still_raises_on_integer_duplicates_so_the_bypass_is_needed():
    runs = [[_row("#0", 0)], [_row("#0", 1)]]
    with pytest.raises(TypeError):
        M.reliability(runs)  # 동결 채점 코드는 그대로다(AG-11-14 A: 고치지 않음)
    assert R.reliability_runs(runs)["items"] == 1


def test_mixed_duplicates_over_three_rounds_give_the_right_trajectory_consistency():
    runs = [[_row("#0", 0), _row("#1", 2), _row("#2", 1)],
            [_row("#0", 1), _row("#1", 2), _row("#2", 1)],
            [_row("#0", 0), _row("#1", 2), _row("#2", 3)]]
    rel = R.reliability_runs(runs)
    assert rel["repeats"] == 3 and rel["items"] == 3
    assert (rel["trajectory_consistency"]["k"], rel["trajectory_consistency"]["n"]) == (1, 3)  # #1만 세 회차 중복 수가 같다
    assert rel["pass^k"]["k"] == 3 and rel["judgment_agreement"]["k"] == 3  # 중복 수는 경로 서명에만 든다(성공 판정과 무관)


def test_zero_only_duplicates_give_the_same_values_as_the_frozen_scorer():
    runs = [[_row("#0", 0), _row("#1", 0, verdict="Fail", fails=["REQUIRED_MISSING"])],
            [_row("#0", 0), _row("#1", 0)],
            [_row("#0", 0, end_reason="LIMIT"), _row("#1", 0)]]
    assert R.reliability_runs(runs) == M.reliability(runs)


def test_bypass_does_not_change_input_rows_and_leaves_rows_with_a_run_record_alone():
    runs = [[_row("#0", 1)], [_row("#0", 1)]]
    before = copy.deepcopy(runs)
    R.reliability_runs(runs)
    assert runs == before and isinstance(runs[0][0]["trajectory"]["duplicates"], int)
    dev = {**_row("d", 2), "run": {"tool_calls": [{"name": "check_contraindications"}]}}
    assert R._sig_safe_row(dev) is dev
    assert R._sig_safe_row(_row("#0", 0))["trajectory"]["duplicates"] == []
    assert R._sig_safe_row(_row("#0", 3))["trajectory"]["duplicates"] == [3]
    assert R._sig_safe_row(_row("#0", None))["trajectory"]["duplicates"] is None  # 칸이 없거나 정수가 아니면 그대로


def test_excl_j5_reliability_uses_the_same_bypass():
    runs = [[_row("#0", 0)], [_row("#0", 2)]]
    assert R.reliability_excl_aux(runs)["pass^k_excl_j5"]["n"] == 1


# --------------------------------------------------------------------------- 2. 시험셋 3회 반복(1회차 재사용) 끝까지

def test_sealed_three_round_reliability_with_duplicates_passes(tmp_path, monkeypatch):
    s = _set(tmp_path)
    _sealed_env(monkeypatch)
    _inject_duplicates(monkeypatch, [2, 0, 0, 0])  # 본 측정: #0 중복 2
    assert _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")[0] == 0
    carry = json.loads((tmp_path / "main.reliability-carry.json").read_text(encoding="utf-8"))
    assert [r["trajectory"]["duplicates"] for r in carry["rows"]] == [2, 0]  # carry 형식은 정수 그대로

    _inject_duplicates(monkeypatch, [2, 1, 2, 0])  # 2회차 #0 2·#1 1, 3회차 #0 2·#1 0
    rc, res = _run(tmp_path, "rel.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    assert rc == 0
    rel = res["reliability"]
    assert rel["repeats"] == 3 and rel["items"] == 2 and rel["first_run_reused"] is True
    assert (rel["trajectory_consistency"]["k"], rel["trajectory_consistency"]["n"]) == (1, 2)  # #0(2,2,2)만 같다
    assert not (tmp_path / f"rel{R.PARTIAL_SUFFIX}").exists()  # 저장이 끝나면 집계 전 행 파일은 지운다


def test_sealed_reliability_with_zero_duplicates_matches_the_frozen_scorer(tmp_path, monkeypatch):
    s = _set(tmp_path)
    _sealed_env(monkeypatch)
    assert _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")[0] == 0
    seen: list[Any] = []
    orig = R.reliability_runs
    monkeypatch.setattr(R, "reliability_runs", lambda runs: seen.append(copy.deepcopy(runs)) or orig(runs))
    rc, res = _run(tmp_path, "rel.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    assert rc == 0 and seen
    expect = M.reliability(seen[0])  # 같은 입력을 동결 채점 코드에 바로 넣은 값
    for k in ("unstable_items", "unstable_items_code_part"):
        expect.pop(k)
    assert {k: v for k, v in res["reliability"].items() if k != "first_run_reused"} == expect
    assert res["reliability"]["trajectory_consistency"]["k"] == 2


# --------------------------------------------------------------------------- 3. 집계 전 행 보존과 집계만 다시 하기

def _boom(monkeypatch) -> None:
    def fail(*a: Any, **k: Any) -> Any:
        raise TypeError("'int' object is not iterable")  # rel2와 같은 모양의 집계 예외

    monkeypatch.setattr(R, "reliability_block", fail)


def test_aggregation_failure_leaves_a_partial_rows_file_without_sealed_text(tmp_path, monkeypatch, capsys):
    s = _set(tmp_path)
    _sealed_env(monkeypatch)
    assert _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")[0] == 0
    _boom(monkeypatch)
    with pytest.raises(TypeError):
        _run(tmp_path, "rel.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    assert not (tmp_path / "rel.json").exists()
    part = tmp_path / f"rel{R.PARTIAL_SUFFIX}"
    assert "--reaggregate" in capsys.readouterr().out and part.is_file()
    raw = part.read_text(encoding="utf-8")
    assert "syn-" not in raw and "SYNTH-SECRET" not in raw and Q_PAIR not in raw and '"run"' not in raw
    doc = json.loads(raw)
    assert doc["kind"] == R.PARTIAL_VERSION and doc["sealed"] is True and doc["first_run_reused"] is True
    assert [[r["id"] for r in rs] for rs in doc["rel_runs"]] == [["#0", "#1"]] * 3
    assert isinstance(doc["result"]["items"], str) and "reliability" not in doc["result"]
    assert "top_fail_kinds" not in doc["result"]["metrics"]["trajectory"]


def test_reaggregate_rebuilds_the_same_result_without_running(tmp_path, monkeypatch):
    s = _set(tmp_path)
    _sealed_env(monkeypatch)
    assert _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")[0] == 0
    _inject_duplicates(monkeypatch, [1, 0, 0, 0])
    rc, ok = _run(tmp_path, "ok.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    assert rc == 0
    _inject_duplicates(monkeypatch, [1, 0, 0, 0])
    with monkeypatch.context() as m:
        _boom(m)
        with pytest.raises(TypeError):
            _run(tmp_path, "rel.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    calls: list[str] = []
    monkeypatch.setattr(R.GraphAgent, "__call__", lambda self, item: calls.append("x"))
    part = tmp_path / f"rel{R.PARTIAL_SUFFIX}"
    assert R.main(["--reaggregate", str(part)]) == 0 and calls == []
    res = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    rel = res.pop("reliability")
    assert rel.pop("reaggregated_from")["file"] == part.name
    assert rel == ok["reliability"] and rel["trajectory_consistency"]["k"] == 1
    assert list(json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))) == list(ok)  # 칸 순서도 실행 직후와 같다
    assert R.main(["--reaggregate", str(part)]) == 3  # 결과 파일이 이미 있으면 덮어쓰지 않는다


def test_reaggregate_refuses_when_the_scorer_hash_changed(tmp_path, monkeypatch, capsys):
    s = _set(tmp_path)
    _sealed_env(monkeypatch)
    assert _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")[0] == 0
    with monkeypatch.context() as m:
        _boom(m)
        with pytest.raises(TypeError):
            _run(tmp_path, "rel.json", s, "--allow-sealed", *REL_ARGS, "--first-run", str(tmp_path / "main.json"))
    monkeypatch.setattr(R, "metrics_version", lambda: "metrics-src@changed")
    assert R.main(["--reaggregate", str(tmp_path / f"rel{R.PARTIAL_SUFFIX}")]) == 3
    assert "채점 코드 해시" in capsys.readouterr().out and not (tmp_path / "rel.json").exists()


def test_reaggregate_refuses_a_file_of_another_kind(tmp_path):
    bad = tmp_path / "x.rows-partial.json"
    bad.write_text(json.dumps({"kind": "other"}), encoding="utf-8")
    assert R.main(["--reaggregate", str(bad)]) == 3


def test_dev_repeats_without_reuse_also_keep_partial_rows_and_reaggregate_the_same(tmp_path, monkeypatch):
    s = _set(tmp_path, name="synth.jsonl", mark="dev_reliability_core")
    rc, ok = _run(tmp_path, "ok.json", s, "--repeats", "2")
    assert rc == 0 and not (tmp_path / f"ok{R.PARTIAL_SUFFIX}").exists()
    with monkeypatch.context() as m:
        _boom(m)
        with pytest.raises(TypeError):
            _run(tmp_path, "rel.json", s, "--repeats", "2")
    doc = json.loads((tmp_path / f"rel{R.PARTIAL_SUFFIX}").read_text(encoding="utf-8"))
    assert doc["sealed"] is False and len(doc["result"]["items"]) == 4 and doc["result"]["items_repeats"][0]["run"] == 2
    assert R.main(["--reaggregate", str(tmp_path / f"rel{R.PARTIAL_SUFFIX}")]) == 0
    rel = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))["reliability"]
    rel.pop("reaggregated_from")
    assert rel == ok["reliability"]


def test_single_run_writes_no_partial_file(tmp_path):
    s = _set(tmp_path, name="synth.jsonl", mark="dev_reliability_core")
    assert _run(tmp_path, "one.json", s)[0] == 0
    assert not list(tmp_path.glob(f"*{R.PARTIAL_SUFFIX}"))
