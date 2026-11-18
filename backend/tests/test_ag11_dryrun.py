"""AG-11 측정 dry-run(LLM·judge·공공 API·원격 DB 호출 0): 가짜 모델·가짜 judge로 **개발셋 150문항**을 C1·C1+·C2로 끝까지 돌리고,
결과 파일이 9.6절 동결 항목을 모두 담는지 `evaluation/freeze_check.py`로 점검한다.

- 그래프·도구·Router·Validator·finalize·채점·저장은 실제 코드다. 바뀌는 것은 모델(가짜)·judge 전송(가짜)·DB(소규모 SQLite)·코퍼스(합성 2청크)뿐이다.
- 사전은 실제 고정 판 파일(`data/mock/dict/drug_dict.json`, 로컬 전용)을 쓴다. 파일·개발셋이 없거나 판이 다르면 건너뛴다.
- 개발셋 문장은 그래프에 넣기만 하고 출력·단언하지 않는다(문항 수·ID 수만). 시험셋은 열지 않는다.
- 측정값이 아니다(가짜 모델이라 답의 내용은 뜻이 없다). 보는 것은 "끝까지 돈다"와 "결과 파일에 무엇으로 쟀는지가 남는다"다.
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

import eval_runner as R  # noqa: E402
import freeze_check as F  # noqa: E402
import sealed_guard as G  # noqa: E402
import sonnet_judge as SJ  # noqa: E402
from golden_synth import golden_conn  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.trace import ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.tools.corpus import CorpusIndex  # noqa: E402
from app.config import Settings  # noqa: E402
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict  # noqa: E402

DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"
CONDITIONS = ("C1", "C1+", "C2")
GUIDE = {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}
_RUBRIC_RE = re.compile(r"\[루브릭 (J\d)@v1\]")
_CHUNK_RE = re.compile(r'<chunk id="([^"]+)"')
CHUNKS = [{"chunk_id": f"dryrun-{g}", "chunk_kind": "l1_notice_sub", "parent_id": None, "refs": [], "pair_id": None, "layer": "L1",
           "issuer": "식품의약품안전처", "doc_type": "고시", "notice_no": "00000000", "base_date": "2026-07-21", "locator": f"제3조 제3호 {m}목",
           "ingr_codes": [], "ingr_names": [], "text": f"[제3조(정의) 제3호] {m}. {g}등급: (합성 문장) {g}등급 정의 자리",
           "source_ref": "의약품 병용금기 성분 등의 지정에 관한 규정|dryrun.md", "item_seq": "", "item_name": "", "section": ""}
          for g, m in (("1", "가"), ("2", "나"))]

pytestmark = pytest.mark.skipif(not (Path(DEFAULT_DICT_PATH).is_file() and DEV_SET.is_file()), reason="실사전 또는 개발셋 없음(로컬 전용)")


class FakeJudgeTransport:
    """루브릭 표지를 보고 스키마에 맞는 JSON을 돌려주는 가짜 전송(호출 수만 센다)."""

    def __init__(self) -> None:
        self.n = 0

    def complete(self, *, system: str, messages: list[dict[str, Any]], max_tokens: int) -> SJ.TransportResult:
        self.n += 1
        user = str(messages[0]["content"])
        rub = _RUBRIC_RE.search(user).group(1)
        item = {"pass": True, "reason": "r", "evidence": []}
        if rub == "J1":
            out: dict[str, Any] = {"rubric": "J1@v1", "overall_pass": True, "claims": [{"id": 1, "text": "c", "supported": True, "reason": "r", "evidence": []}]}
        elif rub == "J2":
            out = {"rubric": "J2@v1", "chunks": [{"id": c, "relevant": True, "reason": "r"} for c in _CHUNK_RE.findall(user)],
                   "reference_claims": [{"text": "c", "attributed": True, "evidence": []}]}
        else:
            keys = ["R1", "R2", "R3", *(["R5"] if rub == "J4" and "R5(상태 평가 불가 고지)를 채점한다" in user else [])]
            out = {"rubric": f"{rub}@v1", "overall_pass": True, "items": {k: item for k in keys}}
        return SJ.TransportResult(text=json.dumps(out, ensure_ascii=False), stop_reason="end_turn", input_tokens=100, output_tokens=50)


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    d = DrugDict.load()
    if d.version != F.EXPECTED_DICT_VERSION:
        pytest.skip(f"사전 판이 다르다({d.version})")
    return d


@pytest.fixture(scope="module")
def results(dd, tmp_path_factory) -> dict[str, dict[str, Any]]:
    """세 조건을 한 번씩 돌린 결과(모듈에서 한 번만). 환경변수는 실행 동안만 tmp로 돌린다."""
    tmp = tmp_path_factory.mktemp("dryrun")
    mp = pytest.MonkeyPatch()
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            mp.delenv(name, raising=False)
    mp.setenv("MEDIAGENT_EVAL", "0")
    mp.setenv("MEDIAGENT_LEDGER_PATH", str(tmp / "ledger.json"))
    mp.setenv("MEDIAGENT_LOG_DIR", str(tmp / "logs"))
    corpus = CorpusIndex(CHUNKS)
    out: dict[str, dict[str, Any]] = {}
    try:
        for cond in CONDITIONS:
            sink = ListSink()
            transport = FakeJudgeTransport()

            def factory(settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str, _sink: ListSink = sink) -> Any:
                ctx = build_tool_context(dd, mode="eval", conn_factory=golden_conn, corpus=corpus, vector_search_fn=None, label_provider=None)
                deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                                  summary_model=ScriptedSummary([{"sentences": [GUIDE]}]), prompt_set=prompt_set, allow_draft=allow_draft,
                                  tracer=R.make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2", sink=_sink))
                return R.GraphResources(deps=deps, cost_total=lambda: 0.0, dict_meta={"version": dd.version, "built_at": dd.meta.get("built_at")},
                                        corpus_meta=R.corpus_fingerprint(corpus, "synthetic:dryrun"))

            path = tmp / f"dryrun-{cond.replace('+', 'plus')}.json"
            rc = R.main(["--set", "dev", "--agent", "graph", "--condition", cond, "--max-usd", "1", "--judge", "sonnet", "--judge-max-usd", "5",
                         "--out", str(path)],
                        settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k", supabase_db_url="fake-d"),
                        resources_factory=factory, judge_factory=lambda settings, mx, _t=transport: SJ.SonnetJudge(_t, max_usd=mx))
            assert rc == 0, cond
            out[cond] = {"res": json.loads(path.read_text(encoding="utf-8")), "path": path, "judge_calls": transport.n, "spans": len(sink.records)}
    finally:
        mp.undo()
    return out


@pytest.mark.parametrize("cond", CONDITIONS)
def test_all_150_dev_items_run_to_the_end_without_errors(results, cond):
    res = results[cond]["res"]
    assert res["meta"]["n_items_run"] == 150 and len(res["items"]) == 150 and len({r["id"] for r in res["items"]}) == 150
    assert res["errors"] == {"items": 0, "total": 0} and "stopped" not in res  # 예외·빈 답 0, 연속 오류 중단 없음
    assert all(r["run"]["answer"] and r["run"]["end_reason"] for r in res["items"])
    assert res["cost_usd"]["skipped"] == 0 and res["judge_usage"]["errors"] == 0 and res["judge_usage"]["cap_reached"] is False
    assert results[cond]["judge_calls"] == res["judge_usage"]["calls"] > 0 and results[cond]["spans"] > 150


@pytest.mark.parametrize("cond", CONDITIONS)
def test_result_file_carries_every_freeze_item(results, cond):
    """9.6절 동결 항목: 세트 sha256·조건·모델·프롬프트·그래프·`harness@v1`·사전 판·코퍼스 출처·judge 모델·루브릭 버전·보정 스위치 등 21개."""
    rows = F.check_result(results[cond]["res"], require_judge=True)
    assert [r["item"] for r in rows] == list(F.FREEZE_ITEMS)
    bad = [(r["item"], r["why"]) for r in rows if not r["ok"]]
    assert not bad, bad
    v = F.freeze_values(results[cond]["res"])
    assert v["dict_version"] == "be10-dict-s1-1055d3576876" and v["condition"] == cond and v["harness_table"]["version"] == "harness@v1"
    assert v["typo_correction"]["enabled"] is {"C1": False, "C1+": True, "C2": True}[cond]
    assert v["corpus"]["source"] == "synthetic:dryrun" and v["corpus"]["n_chunks"] == 2
    assert v["judge_model"] == "claude-sonnet-5-5" and v["judge_prompt_sha256"] == SJ.load_prompt()["sha256"]


def test_three_conditions_share_the_same_frozen_values(results):
    """같은 세트·모델·프롬프트·하네스·사전·코퍼스·judge로 쟀다(조건·그래프·조건표·보정 스위치만 다르다)."""
    base = results["C2"]["res"]
    for cond in ("C1", "C1+"):
        assert F.same_freeze(base, results[cond]["res"]) == []
    graphs = {c: F.freeze_values(results[c]["res"])["graph"] for c in CONDITIONS}
    assert len(set(graphs.values())) == 3


def test_cli_passes_on_dry_run_results_and_fails_when_an_item_is_missing(results, tmp_path, capsys):
    paths = [str(results[c]["path"]) for c in CONDITIONS]
    assert F.main([*paths, "--require-judge", "--same"]) == 0
    out = capsys.readouterr().out
    n = len(F.FREEZE_ITEMS)  # 2026-11-18 채점 코드 해시·judge 설정을 더해 23개
    assert n == 23 and out.count(f"{n}/{n} 통과") == 3 and "동결 값 같음" in out
    broken = json.loads(json.dumps(results["C2"]["res"]))
    broken["meta"]["versions"]["dict"]["version"] = "be10-dict-s1-다른판"
    broken["meta"]["versions"]["corpus"] = None
    broken["meta"]["typo_correction"]["enabled"] = "yes"
    p = tmp_path / "broken.json"
    p.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    assert F.main([str(p), "--require-judge"]) == 1
    out = capsys.readouterr().out
    assert f"{n - 3}/{n} 통과" in out and all(f"NG  {k}" in out for k in ("dict_version", "corpus", "typo_correction"))


@pytest.mark.parametrize("cond,enabled,graph", [("C1", True, None), ("C1+", False, None), ("C2", True, "c1-pipeline@v1")])
def test_condition_mismatch_is_caught(results, cond, enabled, graph):
    """조건 표기와 실제 설정이 어긋난 결과(예: C1인데 보정 켬, C2인데 파이프라인 버전)는 통과하지 못한다."""
    res = json.loads(json.dumps(results[cond]["res"]))
    res["meta"]["typo_correction"]["enabled"] = enabled
    if graph:
        res["meta"]["versions"]["graph"] = graph
    bad = {r["item"] for r in F.check_result(res, require_judge=True) if not r["ok"]}
    assert bad == ({"graph"} if graph else {"typo_correction"})


def test_code_only_result_passes_without_judge_but_fails_when_judge_is_required(results):
    res = json.loads(json.dumps(results["C2"]["res"]))
    res["meta"]["judge"] = None
    assert all(r["ok"] for r in F.check_result(res))
    assert {r["item"] for r in F.check_result(res, require_judge=True) if not r["ok"]} == set(F.JUDGE_ITEMS)


def test_dry_run_reaches_every_dev_branch_and_judges_them(results):
    """분기 유형마다 judge가 붙었다(오정보 J3, 범위 외 J4, 근거 없음 J5, 정상·모호 Ragas). 개수만 본다."""
    res = results["C2"]["res"]
    by: dict[str, int] = {}
    for r in res["items"]:
        for rub in (r["judge"].get("rubrics") or {}):
            by[rub] = by.get(rub, 0) + 1
    assert by.get("J3", 0) == 20 and by.get("J4", 0) == 15 and by.get("J5", 0) == 20
    assert res["metrics"]["ragas"]["n_items"] == sum(r["branch_label"] in ("정상", "모호") for r in res["items"]) == 65
