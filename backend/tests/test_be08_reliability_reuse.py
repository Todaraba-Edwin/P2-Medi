"""BE-08 신뢰성 1회차 재사용 시험(RFP-35-09 A, PJ2-RFP.md 9.4·9.7절, 2026-11-18). LLM·judge·공공 API·원격 DB 호출 0(가짜 모델·합성 사전·합성 세트).

- 본 측정을 `--save-reliability-carry`로 돌리면 결과 옆에 안전 핵심 문항의 1회차 행이 남는다(결과 파일 형식은 그대로).
- 신뢰성 실행 `--subset … --repeats 3 --first-run 본측정.json`은 추가 2회만 돌고, 신뢰성은 1회차를 더해 3회로 계산한다.
- 시험셋 옆 파일에는 문항 ID·판정 근거 ID·실행 기록이 없다(순번·해시만). 시험셋 신뢰성 결과에는 불안정 문항 ID가 없다.
- 본 측정과 세트·조건·문항이 다르면 시작하지 않는다(종료 코드 2). 다른 세트의 표시를 고르면(0문항) 시작하지 않는다.
"""

from __future__ import annotations

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
SECRET_EID = "contra_pair:SYNTH-SECRET-A:SYNTH-SECRET-B"  # 시험셋 옆 파일에 원문으로 남으면 안 되는 근거 ID(합성)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


class Factory:
    def __init__(self) -> None:
        self.questions = 0

    def __call__(self, settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> Any:
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn)
        deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                          summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), prompt_set=prompt_set, allow_draft=allow_draft,
                          tracer=R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=ListSink()))
        return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": dd.version},
                                corpus_meta={"source": "synthetic", "n_chunks": 0, "sha256": "0" * 64})


def _set(tmp_path: Path, *, name: str = "synth.jsonl", mark: str = "dev_reliability_core", n: int = 4, core: int = 2) -> Path:
    """앞 `core`개 문항에 `mark` 표시. 판정 정답 항목을 넣어 판정 일치 서명이 생기게 한다."""
    p = tmp_path / name
    rows = [{"id": f"syn-{i:03d}", "question": Q_PAIR, "set": "dev", "set_version": "synth", "branch_label": "정상", "composition_group": "정상-병용",
             "expected_response_type": "judgment", "expected_path": {"required": []}, "required_elements": ["DISCLAIMER"],
             "answer": {"items": [{"status": "FOUND", "evidence_id": SECRET_EID, "matches": []}]}, mark: i < core}
            for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, out: str, set_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    path = tmp_path / out
    rc = R.main(["--set", str(set_path), "--agent", "graph", "--max-usd", "1", "--out", str(path), *extra],
                settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d"), resources_factory=Factory())
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() and rc == 0 else {})


def _count_calls(monkeypatch) -> list[str]:
    seen: list[str] = []
    orig = R.GraphAgent.__call__

    def counted(self, item):
        seen.append(str(item.get("id")))
        return orig(self, item)

    monkeypatch.setattr(R.GraphAgent, "__call__", counted)
    return seen


# --------------------------------------------------------------------------- 개발셋

def test_main_run_writes_a_carry_file_for_core_items_only_and_keeps_the_result_format(tmp_path):
    s = _set(tmp_path)
    rc, plain = _run(tmp_path, "plain.json", s)
    rc2, res = _run(tmp_path, "main.json", s, "--save-reliability-carry")
    assert rc == rc2 == 0
    assert set(res) == set(plain) and set(res["meta"]) == set(plain["meta"])  # 결과 파일 형식은 그대로(옆 파일만 더해진다)
    doc = json.loads((tmp_path / "main.reliability-carry.json").read_text(encoding="utf-8"))
    assert doc["kind"] == R.CARRY_VERSION and doc["subset"] == "dev_reliability_core" and doc["sealed"] is False
    assert [r["id"] for r in doc["rows"]] == ["syn-000", "syn-001"]
    assert set(doc["rows"][0]) == {"id", "safety", "elements", "judgment", "trajectory", "run"}
    assert doc["set_sha256"] == res["meta"]["set_sha256"] and doc["source_result"] == "main.json"


def test_first_run_reuse_runs_only_the_extra_two_rounds(tmp_path, monkeypatch):
    s = _set(tmp_path)
    assert _run(tmp_path, "main.json", s, "--save-reliability-carry")[0] == 0
    seen = _count_calls(monkeypatch)
    rc, res = _run(tmp_path, "rel.json", s, "--subset", "dev_reliability_core", "--repeats", "3", "--first-run", str(tmp_path / "main.json"))
    assert rc == 0
    assert seen == ["syn-000", "syn-001"] * 2  # 안전 핵심 2문항 × 추가 2회만 실행
    rel = res["reliability"]
    assert rel["repeats"] == 3 and rel["items"] == 2 and rel["first_run_reused"] is True
    assert res["meta"]["repeats"] == 3 and res["meta"]["first_run"]["file"] == "main.json"  # 개발셋은 결과의 문항별 행을 바로 읽는다
    assert {r["run_index"] for r in res["items"]} == {2}
    assert [(b["run"], {r["run_index"] for r in b["items"]}) for b in res["items_repeats"]] == [(3, {3})]
    assert rel["judgment_agreement"]["n"] == 2 and rel["trajectory_consistency"]["k"] == 2  # 같은 가짜 모델이라 세 회차가 같다


def test_dev_result_items_can_be_the_first_run_without_a_carry_file(tmp_path):
    s = _set(tmp_path)
    assert _run(tmp_path, "main.json", s)[0] == 0
    rc, res = _run(tmp_path, "rel.json", s, "--subset", "dev_reliability_core", "--repeats", "3", "--first-run", str(tmp_path / "main.json"))
    assert rc == 0 and res["meta"]["first_run"]["file"] == "main.json" and res["reliability"]["items"] == 2


@pytest.mark.parametrize("bad", [
    ("--condition", "C1"),                 # 조건이 다르다
    ("--prompt-set", "prompt_set@v2"),     # 에이전트 쪽 버전(프롬프트)이 다르다
])
def test_first_run_with_different_settings_refuses_to_start(bad, tmp_path, capsys):
    s = _set(tmp_path)
    assert _run(tmp_path, "main.json", s)[0] == 0
    rc, _ = _run(tmp_path, "rel.json", s, "--subset", "dev_reliability_core", "--repeats", "3", "--first-run", str(tmp_path / "main.json"), *bad)
    assert rc == 2 and "1회차 재사용 불가" in capsys.readouterr().out
    assert not (tmp_path / "rel.json").exists()


def test_first_run_with_a_changed_set_or_missing_items_refuses(tmp_path, capsys):
    s = _set(tmp_path)
    assert _run(tmp_path, "short.json", s, "--limit", "1")[0] == 0  # 안전 핵심 1문항만 돈 본 측정
    rc, _ = _run(tmp_path, "rel.json", s, "--subset", "dev_reliability_core", "--repeats", "3", "--first-run", str(tmp_path / "short.json"))
    assert rc == 2 and "1개가 없다" in capsys.readouterr().out
    assert _run(tmp_path, "main.json", s)[0] == 0
    other = _set(tmp_path, name="other.jsonl", n=5)
    rc, _ = _run(tmp_path, "rel2.json", other, "--subset", "dev_reliability_core", "--repeats", "3", "--first-run", str(tmp_path / "main.json"))
    assert rc == 2 and "sha256" in capsys.readouterr().out


@pytest.mark.parametrize("args", [
    ("--repeats", "3"),                                              # 부분집합 없음
    ("--subset", "dev_golden", "--repeats", "3"),                    # 신뢰성 부분집합이 아님
    ("--subset", "dev_reliability_core", "--repeats", "1"),          # 추가 회차 없음
    ("--subset", "dev_reliability_core", "--repeats", "3", "--limit", "1"),
])
def test_first_run_needs_a_reliability_subset_and_extra_rounds(args, tmp_path):
    s = _set(tmp_path)
    assert _run(tmp_path, "main.json", s)[0] == 0
    assert _run(tmp_path, "rel.json", s, *args, "--first-run", str(tmp_path / "main.json"))[0] == 2


def test_first_run_and_carry_are_graph_only(tmp_path):
    s = _set(tmp_path)
    assert R.main(["--set", str(s), "--agent", "offline-fixed", "--save-reliability-carry", "--out", str(tmp_path / "o.json")]) == 2


def test_selecting_a_mark_the_set_does_not_have_refuses_instead_of_running_zero_items(tmp_path, capsys):
    s = _set(tmp_path)  # 개발셋 표시(dev_reliability_core)만 있다
    assert _run(tmp_path, "x.json", s, "--subset", "reliability_core")[0] == 2
    assert "0개" in capsys.readouterr().out


# --------------------------------------------------------------------------- 시험셋(합성 SEALED 파일, 가드 경유)

def test_sealed_reliability_subset_reuse_keeps_no_ids_or_evidence(tmp_path, monkeypatch, capsys):
    s = _set(tmp_path, name="synth_test.SEALED.jsonl", mark="reliability_core", n=4, core=2)
    with pytest.raises(G.SealedAccessError):  # 가드: 허용 없이는 열지 않는다
        _run(tmp_path, "main.json", s, "--save-reliability-carry")
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    rc, main = _run(tmp_path, "main.json", s, "--allow-sealed", "--save-reliability-carry")
    assert rc == 0 and isinstance(main["items"], str)  # 시험셋 결과는 점수만
    raw = (tmp_path / "main.reliability-carry.json").read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert [r["id"] for r in doc["rows"]] == ["#0", "#1"] and doc["subset"] == "reliability_core" and doc["sealed"] is True
    assert "syn-" not in raw and "SYNTH-SECRET" not in raw and Q_PAIR not in raw and '"run"' not in raw
    seen = _count_calls(monkeypatch)
    rc, res = _run(tmp_path, "rel.json", s, "--allow-sealed", "--subset", "reliability_core", "--repeats", "3",
                   "--first-run", str(tmp_path / "main.json"))
    assert rc == 0 and len(seen) == 4
    rel = res["reliability"]
    assert rel["repeats"] == 3 and rel["items"] == 2 and rel["judgment_agreement"]["k"] == 2
    assert "unstable_items" not in rel and "unstable_items_code_part" not in rel
    assert "syn-" not in (tmp_path / "rel.json").read_text(encoding="utf-8")
    capsys.readouterr()


def test_sealed_reliability_without_reuse_also_hides_code_part_unstable_ids(tmp_path, monkeypatch):
    s = _set(tmp_path, name="synth_test.SEALED.jsonl", mark="reliability_core", n=3, core=3)
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    rc, res = _run(tmp_path, "rep.json", s, "--allow-sealed", "--subset", "reliability_core", "--repeats", "2")
    assert rc == 0 and "unstable_items_code_part" not in res["reliability"]


def test_carry_row_is_the_same_shape_for_first_and_extra_rounds():
    row = {"id": "x", "safety": None, "elements": {"DISCLAIMER": True}, "trajectory": {"verdict": "Pass", "end_reason": "NORMAL", "rule": "traj@v2"},
           "judgment": {"applicable": True, "correct": True, "items": [{"evidence_id": SECRET_EID, "got": "found", "got_grades": ["1"], "want": "found"}]},
           "run": {"tool_calls": [{"name": "check_contraindications", "args": {"item_seq": "1"}}], "answer": {"x": 1}}, "cost": {}}
    dev, sealed = R.carry_row(row, sealed=False), R.carry_row(row, sealed=True, key="#0")
    assert dev["run"] == {"tool_calls": [{"name": "check_contraindications"}]} and "rule" not in dev["trajectory"]
    assert sealed["id"] == "#0" and "run" not in sealed and sealed["judgment"]["items"][0]["evidence_id"] != SECRET_EID
    assert R.carry_row(row, sealed=True, key="#0") == sealed  # 같은 입력 → 같은 해시(회차 사이 비교 가능)


# --------------------------------------------------------------------------- 설정 고정·동결 가드 마무리·스냅샷 수집일(BE-08 :50·:45·:36)

import freeze_check as F  # noqa: E402


def test_result_records_metrics_code_hash_and_a_changed_scorer_refuses_to_start(tmp_path, monkeypatch, capsys):
    s = _set(tmp_path)
    assert _run(tmp_path, "base.json", s)[0] == 0
    base = json.loads((tmp_path / "base.json").read_text(encoding="utf-8"))
    assert base["meta"]["versions"]["metrics"].startswith("metrics-src@")
    assert {r["item"]: r["ok"] for r in F.check_result(base, dict_version=None, require_manifest_match=False)}["metrics_src"]
    monkeypatch.setattr(R, "metrics_version", lambda: "metrics-src@changed")
    rc, _ = _run(tmp_path, "next.json", s, "--baseline", str(tmp_path / "base.json"))
    assert rc == 2 and "metrics_src" in capsys.readouterr().out


def test_metrics_hash_is_not_compared_against_results_made_before_it_existed(tmp_path):
    s = _set(tmp_path)
    assert _run(tmp_path, "base.json", s)[0] == 0
    old = json.loads((tmp_path / "base.json").read_text(encoding="utf-8"))
    old["meta"]["versions"].pop("metrics")
    (tmp_path / "old.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    assert _run(tmp_path, "next.json", s, "--baseline", str(tmp_path / "old.json"))[0] == 0


def test_judge_thinking_or_max_tokens_change_is_a_frozen_difference(tmp_path):
    s = _set(tmp_path)
    assert _run(tmp_path, "base.json", s)[0] == 0
    a = json.loads((tmp_path / "base.json").read_text(encoding="utf-8"))
    a["meta"]["judge"] = {"model": "claude-sonnet-5-5", "rubrics": {"J1": "J1@v1"}, "prompt_sha256": "a" * 64, "ragas": "r@v1",
                          "thinking": {"type": "between_tools"}, "max_tokens": 2000}
    b = json.loads(json.dumps(a))
    b["meta"]["judge"]["max_tokens"] = 4000
    assert [d["item"] for d in F.freeze_diff(b, a)] == ["judge_settings"]
    rows = {r["item"]: r["ok"] for r in F.check_result(a, dict_version=None, require_manifest_match=False, require_judge=True)}
    assert rows["judge_settings"]
    a["meta"]["judge"].pop("thinking")
    a["meta"]["judge"].pop("max_tokens")
    assert not {r["item"]: r["ok"] for r in F.check_result(a, dict_version=None, require_manifest_match=False, require_judge=True)}["judge_settings"]


def test_planned_result_carries_judge_settings_for_the_baseline_guard():
    class J:
        def score_rubric(self, *a: Any, **k: Any) -> None: ...

        def meta(self) -> dict[str, Any]:
            return {"judge_model": "claude-sonnet-5-5", "rubric_versions": {}, "prompt_sha256": "a" * 64, "thinking": {"type": "between_tools"},
                    "max_tokens": 2000}

    j = R.planned_result({}, J())["meta"]["judge"]
    assert j["thinking"] == {"type": "between_tools"} and j["max_tokens"] == 2000


def test_corpus_fingerprint_records_eyak_and_permit_snapshot_collection_dates_without_text():
    class Idx:
        chunks = [{"chunk_id": "e1", "chunk_kind": "l3_eyak_section", "base_date": "2026-11-03", "text": "본문"},
                  {"chunk_id": "e2", "chunk_kind": "l3_eyak_section", "base_date": "2026-11-05", "text": "본문"},
                  {"chunk_id": "p1", "chunk_kind": "l3_prmsn_para", "base_date": "2026-11-06", "text": "본문"},
                  {"chunk_id": "k1", "chunk_kind": "l2_combo", "base_date": "2026-07-31", "text": "본문"}]

    fp = R.corpus_fingerprint(Idx(), "db:x")
    assert fp["snapshot_dates"]["eyak"] == {"n_chunks": 2, "collected_min": "2026-11-03", "collected_max": "2026-11-05", "n_dates": 2}
    assert fp["snapshot_dates"]["prmsn"]["collected_max"] == "2026-11-06"
    assert R.snapshot_dates([])["eyak"] is None and "본문" not in json.dumps(fp, ensure_ascii=False)
    assert set(F.freeze_values({"meta": {"versions": {"corpus": fp}}})["corpus"]) == {"source", "n_chunks", "sha256"}  # 동결 비교 키는 그대로
