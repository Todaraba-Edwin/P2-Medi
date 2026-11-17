"""RFP-26-08 A·AG-04-07 A·AG-06-11 A 시험: 경로 채점 v2(Router 식별 인정, 식별 밖 item_seq 위반), 되묻기 종료, `multihop_m` 기대 경로,
시험셋 칸 수정 스크립트(내용 미출력), 반복 실행 문항별 행, 저장 결과 재채점.

LLM·judge·공공 API·원격 DB 호출 0. 실제 시험셋 파일은 열지 않는다(가짜 SEALED 파일은 tmp에 만든다). 문항은 합성이다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "eval_set"):
    sys.path.insert(0, str(p))

import eval_metrics as M  # noqa: E402
import eval_runner as R  # noqa: E402
import fix_multihop_m_path as FX  # noqa: E402
import sealed_guard as G  # noqa: E402

from app.agent.finalize import finalize  # noqa: E402

PH = M.Phrases.from_backend()
SEQ_A, SEQ_B, SEQ_X = "200000001", "200000002", "299999999"
PAIR_EID = "contra_pair:AAA111ATB:BBB222ATB"


def judg_item(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "q1", "branch_label": "정상", "composition_group": "정상-병용", "expected_response_type": "judgment",
        "required_elements": ["PHARMACIST_NOTICE", "DISCLAIMER"], "products": ["가약"],
        "answer": {"items": [{"kind": "contra_pair", "status": "FOUND", "evidence_id": PAIR_EID, "matches": [{"reason": "x"}]}]},
        "expected_path": {"required": ["identify_drug", "check_contraindications"], "recommended": [], "forbidden": [],
                          "order": [["identify_drug", "check_contraindications"]], "max_model_calls": 8},
    }
    base.update(kw)
    return base


def clarify_item(**kw: Any) -> dict[str, Any]:
    return judg_item(**{"id": "c1", "branch_label": "모호", "composition_group": "모호", "expected_response_type": "clarify",
                        "required_elements": ["CANDIDATES_SHOWN", "ONE_QUESTION", "NO_VERDICT"], "answer": {"items": []},
                        "expected_path": {"required": ["identify_drug"], "recommended": [], "forbidden": ["check_contraindications"], "order": []},
                        **kw})


def answer() -> dict[str, Any]:
    a = finalize([])
    a["entries"] = [{"bucket": "found", "evidence_id": PAIR_EID, "kind": "contra_pair", "drug": "가약 · 나약", "grades": [],
                     "source_label": "한국의약품안전관리원 · 기준일 2026-07-31"}]
    return a


def check(*seqs: str) -> M.ToolCall:
    return M.ToolCall("check_contraindications", {"drugs": [{"item_seq": s} for s in seqs]})


def router(*ents: tuple[str, str | None], ambiguous: bool = False) -> dict[str, Any]:
    return {"ran": True, "ambiguous": ambiguous, "entities": [{"status": st, "item_seq": seq} for st, seq in ents]}


def rec(calls: list[M.ToolCall], *, rt: dict[str, Any] | None, ident: list[str] | None = None, end: str = "NORMAL",
        model_calls: int = 2, ans: dict[str, Any] | None = None) -> M.RunRecord:
    return M.RunRecord(answer=answer() if ans is None else ans, tool_calls=calls, model_calls=model_calls, end_reason=end,
                       tool_evidence_ids={PAIR_EID}, router=rt, identify_item_seqs=ident)


# ------------------------------------------------------------------ 상수가 백엔드와 같은가

def test_constants_match_backend():
    from app.agent.graph.state import END_CLARIFY
    from app.agent.router import ST_RESOLVED

    assert M.ROUTER_RESOLVED == ST_RESOLVED and M.END_CLARIFY == END_CLARIFY


# ------------------------------------------------------------------ 식별 단계: Router 확정만으로 충족

def test_router_resolved_satisfies_identify_without_tool_call():
    r = rec([check(SEQ_A, SEQ_B)], rt=router(("RESOLVED", SEQ_A), ("RESOLVED", SEQ_B)))
    t = M.trajectory(judg_item(), r)
    assert t["verdict"] == "Pass" and t["fails"] == [] and t["rule"] == M.TRAJ_RULE and t["identify_by"] == "router_resolved"
    assert t["required_rate"] == [2, 2] and t["order_violations"] == 0 and t["unidentified_items"] == 0
    assert M.score_item(judg_item(), r, PH)["routing_required_all"] is True  # 9.4 라우팅 정확도도 같은 규칙


def test_name_only_judgment_args_are_not_checked():
    """이름만 넘긴 판정(도구가 사전으로 식별)은 item_seq 검사 대상이 없다."""
    r = rec([M.ToolCall("check_contraindications", {"drugs": [{"name": "가약"}, {"name": "나약"}]})],
            rt=router(("RESOLVED", SEQ_A), ("RESOLVED", SEQ_B)))
    assert M.trajectory(judg_item(), r)["verdict"] == "Pass"


# ------------------------------------------------------------------ 식별 밖 item_seq 판정은 위반

def test_item_seq_outside_identification_is_violation():
    r = rec([check(SEQ_A, SEQ_X)], rt=router(("RESOLVED", SEQ_A), ("RESOLVED", SEQ_B)))
    t = M.trajectory(judg_item(), r)
    assert t["verdict"] == "Fail" and t["fails"] == [M.UNIDENTIFIED_ITEM] and t["unidentified_items"] == 1


def test_identify_drug_result_counts_only_if_called_before_judgment():
    rt = router(("AMBIGUOUS", None))
    ok = rec([M.ToolCall("identify_drug", {"name": "가약"}), check(SEQ_X)], rt=rt, ident=[SEQ_X])
    t = M.trajectory(judg_item(), ok)
    assert t["verdict"] == "Pass" and t["identify_by"] == "tool"
    late = rec([check(SEQ_X), M.ToolCall("identify_drug", {"name": "가약"})], rt=rt, ident=[SEQ_X])
    assert M.trajectory(judg_item(), late)["fails"] == [M.UNIDENTIFIED_ITEM]


def test_no_identification_at_all_is_required_missing():
    r = rec([check(SEQ_A)], rt=router(("NOT_FOUND", None)))
    t = M.trajectory(judg_item(), r)
    assert "REQUIRED_MISSING" in t["fails"] and M.UNIDENTIFIED_ITEM in t["fails"] and t["identify_by"] is None


def test_unidentified_also_checked_without_order_pair():
    it = judg_item(expected_path={"required": ["check_contraindications"], "recommended": [], "forbidden": [], "order": []})
    assert M.trajectory(it, rec([check(SEQ_X)], rt=router(("RESOLVED", SEQ_A))))["fails"] == [M.UNIDENTIFIED_ITEM]


def test_other_order_pairs_keep_v1_rule():
    it = judg_item(expected_path={"required": ["check_contraindications", "search_reason"], "recommended": [], "forbidden": [],
                                  "order": [["check_contraindications", "search_reason"]]})
    r = rec([M.ToolCall("search_reason", {}), check(SEQ_A)], rt=router(("RESOLVED", SEQ_A)))
    assert M.trajectory(it, r)["fails"] == ["ORDER_VIOLATION"]


# ------------------------------------------------------------------ 되묻기·거절 종료

def test_router_clarify_end_satisfies_identify_for_clarify_item():
    r = rec([], rt=router(("AMBIGUOUS", None), ambiguous=True), end="CLARIFY", model_calls=0, ans=finalize([], model_summary="어느 약인가요?"))
    t = M.trajectory(clarify_item(), r)
    assert t["verdict"] == "Pass" and t["identify_by"] == "router_clarify"


def test_typo_clarify_end_still_fails_judgment_skipped():
    """RFP-26-09 A: 오탈자 문항을 되묻기로 끝내면 식별은 충족돼도 판정 도구 생략으로 Fail."""
    it = judg_item(id="t1", branch_label="오탈자", composition_group="오탈자")
    r = rec([], rt=router(("TYPO_SUSPECT", None), ambiguous=True), end="CLARIFY", model_calls=0, ans=finalize([], model_summary="이 약인가요?"))
    t = M.trajectory(it, r)
    # 식별 단계(identify_drug)는 되묻기로 충족(1/2), 판정 도구는 빠져 REQUIRED_MISSING + JUDGMENT_TOOL_SKIPPED
    assert t["fails"] == ["REQUIRED_MISSING", "JUDGMENT_TOOL_SKIPPED"] and t["required_rate"] == [1, 2] and t["identify_by"] == "router_clarify"


def test_ambiguous_flag_without_clarify_end_is_not_identification():
    r = rec([], rt=router(("AMBIGUOUS", None), ambiguous=True), end="REFUSE", model_calls=0)
    assert M.trajectory(clarify_item(), r)["fails"] == ["REQUIRED_MISSING"]


def test_guardrail_refuse_before_router():
    rt = {"ran": False, "ambiguous": False, "entities": []}
    r = rec([], rt=rt, end="REFUSE", model_calls=0)
    t = M.trajectory(clarify_item(), r)
    assert t["fails"] == ["REQUIRED_MISSING"] and t["identify_by"] is None


def test_legacy_record_without_router_keeps_v1_rule_and_is_counted():
    r = rec([check(SEQ_A)], rt=None)
    t = M.trajectory(judg_item(), r)
    assert t["rule"] == M.TRAJ_RULE_LEGACY and set(t["fails"]) == {"REQUIRED_MISSING", "ORDER_VIOLATION"}
    agg = M.aggregate([M.score_item(judg_item(), r, PH), M.score_item(judg_item(id="q2"), rec([check(SEQ_A)], rt=router(("RESOLVED", SEQ_A))), PH)])
    assert agg["trajectory"]["rules"] == {M.TRAJ_RULE: 1, M.TRAJ_RULE_LEGACY: 1}
    assert agg["trajectory"]["by_end_reason_pass_or_warn"]["NORMAL"]["n"] == 2


# ------------------------------------------------------------------ extract_trace가 Router 결과를 기록

def test_extract_trace_records_router_without_question_fragments():
    st = {"messages": [AIMessage("", tool_calls=[{"name": "check_contraindications", "args": {"drugs": [{"item_seq": SEQ_A}]}, "id": "c1",
                                                   "type": "tool_call"}])],
          "entities": [{"raw": "질문조각가약", "normalized": "가약", "status": "RESOLVED", "item_seq": SEQ_A, "options": []},
                       {"raw": "질문조각나약", "normalized": "나약", "status": "TYPO_SUSPECT", "item_seq": None}],
          "ambiguous": False, "end_reason": "NORMAL", "call_count": 2,
          "evidence": [{"kind": "identify", "item_seq": SEQ_B, "evidence_id": f"identify:{SEQ_B}"},
                       {"kind": "identify", "item_seq": None, "evidence_id": "identify:ingredient:x"}]}
    r = R.extract_trace(st)
    assert r.router == {"ran": True, "ambiguous": False, "entities": [{"status": "RESOLVED", "item_seq": SEQ_A},
                                                                       {"status": "TYPO_SUSPECT", "item_seq": None}]}
    assert r.identify_item_seqs == [SEQ_B]
    dumped = json.dumps(r.to_json(), ensure_ascii=False)
    assert "질문조각" not in dumped and "router" in r.to_json()
    back = M.RunRecord.from_json(json.loads(dumped))
    assert back.router == r.router and back.tool_calls[0].args == {"drugs": [{"item_seq": SEQ_A}]} and back.tool_evidence_ids == r.tool_evidence_ids
    legacy = M.RunRecord(answer={})
    assert "router" not in legacy.to_json() and "identify_item_seqs" not in legacy.to_json()


# ------------------------------------------------------------------ 가짜 그래프 끝까지(LLM 호출 0)

@pytest.fixture(scope="module")
def ag01() -> Any:
    return pytest.importorskip("test_ag01_graph")


@pytest.fixture(scope="module")
def dd(ag01: Any) -> Any:
    from build_drug_dict import build_dictionary

    from app.tools.drug_dict import DrugDict

    return DrugDict(build_dictionary(ag01.KIDS, [], ag01.SNAPS, {"x": "y"})[0])


def _graph_item(**kw: Any) -> dict[str, Any]:
    return judg_item(**{"answer": {"items": [{"kind": "contra_pair", "status": "FOUND", "evidence_id": "contra_pair:1", "matches": [{"reason": "x"}]}]},
                        "profile": None, **kw})


def test_fake_graph_router_only_identification_passes(ag01: Any, dd: Any):
    script = [AIMessage("", tool_calls=[ag01.tool_call("check_contraindications", {"drugs": [{"name": "게보린정"}, {"name": "와파린정"}]}, "c1")]),
              AIMessage("조회를 마쳤다")]
    g, _, _, calls = ag01.make_graph(dd, script, [ag01.GOOD_DRAFT])
    row = R.run_eval([_graph_item(id="g1", question=ag01.PAIR_QS[0])], R.GraphAdapter(g), sealed=False)["items"][0]
    assert calls.names == ["check_contraindications"]
    assert row["trajectory"]["verdict"] == "Pass" and row["trajectory"]["identify_by"] == "router_resolved"
    assert [e["status"] for e in row["run"]["router"]["entities"]] == ["RESOLVED", "RESOLVED"]


def test_fake_graph_made_up_item_seq_is_violation(ag01: Any, dd: Any):
    script = [AIMessage("", tool_calls=[ag01.tool_call("check_contraindications", {"drugs": [{"item_seq": SEQ_X}]}, "c1")]),
              AIMessage("조회를 마쳤다")]
    g, *_ = ag01.make_graph(dd, script, [ag01.GOOD_DRAFT])
    row = R.run_eval([_graph_item(id="g2", question=ag01.PAIR_QS[0])], R.GraphAdapter(g), sealed=False)["items"][0]
    assert M.UNIDENTIFIED_ITEM in row["trajectory"]["fails"] and row["trajectory"]["unidentified_items"] == 1


def test_fake_graph_router_clarify_end(ag01: Any, dd: Any):
    g, tm, _, calls = ag01.make_graph(dd, [], [])
    it = clarify_item(id="g3", question="타이레놀 먹어도 돼요?", profile=None)
    row = R.run_eval([it], R.GraphAdapter(g), sealed=False)["items"][0]
    assert calls.names == [] and tm.calls == [] and row["trajectory"]["end_reason"] == "CLARIFY"
    assert row["trajectory"]["verdict"] == "Pass" and row["trajectory"]["identify_by"] == "router_clarify"


# ------------------------------------------------------------------ multihop_m 기대 경로(AG-04-07 A)

def test_multihop_m_path_has_no_search_notice_required():
    import build_eval_set as B

    p = B.path("multihop_m")
    assert p["required"] == FX.NEW_REQUIRED and "search_notice" not in p["recommended"]


def test_dev_set_multihop_rows_fixed_and_manifest_matches():
    dev = R.SET_FILES["dev"]
    rows = G.load_jsonl(dev)
    assert not [r["id"] for r in rows if (r.get("expected_path") or {}).get("required") == FX.OLD_REQUIRED]
    by = {r["id"]: r for r in rows}
    assert by["dev-001"]["expected_path"]["required"] == FX.NEW_REQUIRED and by["dev-059"]["expected_path"]["required"] == FX.NEW_REQUIRED
    assert R.manifest_check(dev, R.sha256_file(dev))["match"] is True


# ------------------------------------------------------------------ 시험셋 칸 수정 스크립트(내용 미출력)

SECRET = "비밀문항내용-출력되면안됨"


def _fake_sealed(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    rows = [
        {"id": "t-secret-1", "question": SECRET, "expected_path": {"required": list(FX.OLD_REQUIRED), "recommended": [], "order": []}},
        {"id": "t-secret-2", "question": SECRET + "2", "expected_path": {"required": ["identify_drug"], "recommended": []}},
    ]
    lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in rows]
    path = tmp_path / "test_set.SEALED.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"sets": {"test": {"file": path.name, "sha256": "old", "bytes": 0}}, "last_updated": "2026-11-11",
                               "last_change_reason": "이전"}, ensure_ascii=False), encoding="utf-8")
    return path, man, lines


def test_fix_script_refuses_sealed_without_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path, man, _ = _fake_sealed(tmp_path)
    monkeypatch.delenv(G.SEALED_ENV, raising=False)
    with pytest.raises(G.SealedAccessError):
        FX.main(["--set", str(path), "--manifest", str(man)])
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    with pytest.raises(G.SealedAccessError):  # 플래그 없이도 막힌다
        FX.main(["--set", str(path), "--manifest", str(man)])


def test_fix_script_changes_sealed_rows_without_printing_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    path, man, lines = _fake_sealed(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    assert FX.main(["--set", str(path), "--allow-sealed", "--manifest", str(man), "--check"]) == 0
    assert path.read_bytes() == before  # --check는 쓰지 않는다
    assert FX.main(["--set", str(path), "--allow-sealed", "--manifest", str(man)]) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert SECRET not in text and "t-secret" not in text and "바뀐 행 1" in text
    after = path.read_bytes()
    new_lines = after.decode("utf-8").splitlines(keepends=True)
    assert new_lines[1] == lines[1]  # 대상이 아닌 줄은 바이트 그대로
    assert json.loads(new_lines[0])["expected_path"]["required"] == FX.NEW_REQUIRED
    baks = sorted(tmp_path.glob("test_set.bak-*.SEALED.jsonl"))
    assert len(baks) == 1 and baks[0].read_bytes() == before and G.is_sealed(baks[0])  # 백업도 가드·.gitignore 패턴에 걸린다
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["sets"]["test"]["sha256"] == hashlib.sha256(after).hexdigest() and m["sets"]["test"]["bytes"] == len(after)
    assert m["last_change_reason"] == FX.CHANGE_REASON and m["change_history"][-1]["reason"] == "이전"
    assert FX.main(["--set", str(path), "--allow-sealed", "--manifest", str(man)]) == 0  # 멱등
    assert path.read_bytes() == after and "바뀔 행 0" in capsys.readouterr().out


def test_fix_script_refuses_unexpected_format(tmp_path: Path):
    path = tmp_path / "x.jsonl"
    path.write_text(json.dumps({"id": "d", "expected_path": {"required": FX.OLD_REQUIRED}}, indent=1).replace("\n", "") + "\n", encoding="utf-8")
    with pytest.raises(FX.FixError):
        FX.fix_lines(path.read_bytes())


# ------------------------------------------------------------------ 반복 실행 문항별 행(AG-06-11 A)

class _Agent:
    def __call__(self, it: dict[str, Any]) -> M.RunRecord:
        return rec([check(SEQ_A)], rt=router(("RESOLVED", SEQ_A)))


def test_repeats_keep_rows_for_dev_only():
    items = [judg_item(id="r1"), judg_item(id="r2")]
    res = R.run_eval(items, _Agent(), sealed=False, repeats=3, phrases=PH)
    assert [b["run"] for b in res["items_repeats"]] == [2, 3] and all(len(b["items"]) == 2 for b in res["items_repeats"])
    assert res["items_repeats"][0]["items"][0]["run"]["router"]["entities"][0]["status"] == "RESOLVED"
    assert res["meta"]["trajectory_rule"] == M.TRAJ_RULE
    sealed = R.run_eval(items, _Agent(), sealed=True, repeats=3, phrases=PH)
    assert "items_repeats" not in sealed and isinstance(sealed["items"], str)
    assert "items_repeats" not in R.run_eval(items, _Agent(), sealed=False, repeats=1, phrases=PH)


# ------------------------------------------------------------------ 저장 결과 재채점

def test_rescore_refuses_legacy_and_sealed_results():
    legacy = R.run_eval([judg_item()], lambda it: rec([check(SEQ_A)], rt=None), sealed=False, phrases=PH)
    with pytest.raises(R.RescoreUnavailable):
        R.rescore_result(legacy, {"q1": judg_item()}, phrases=PH)
    with pytest.raises(R.RescoreUnavailable):
        R.rescore_result({"items": "omitted"}, {}, phrases=PH)


def test_rescore_uses_current_expected_path_and_recomputes_reliability():
    old_item = judg_item(id="r1", expected_path={"required": ["identify_drug", "check_contraindications", "search_notice"], "order": []})
    res = R.run_eval([old_item], _Agent(), sealed=False, repeats=2, phrases=PH)
    assert res["items"][0]["trajectory"]["verdict"] == "Fail"  # 옛 기대 경로: search_notice 없음
    new = R.rescore_result(res, {"r1": judg_item(id="r1")}, set_sha256="abc", phrases=PH, source="x.json")
    assert new["items"][0]["trajectory"]["verdict"] == "Pass" and new["reliability"]["pass^k_code_part"]["k"] == 1
    assert new["meta"]["rescored"]["from"] == "x.json" and new["meta"]["rescored"]["set_sha256"] == "abc"
    assert res["items"][0]["trajectory"]["verdict"] == "Fail"  # 원본 dict는 그대로


def test_rescore_file_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dev = R.SET_FILES["dev"]
    first = G.load_jsonl(dev)[0]
    res = R.run_eval([first], _Agent(), sealed=False, phrases=PH, meta={"set_file": dev.name})
    src = tmp_path / "l3-x.json"
    src.write_text(json.dumps(res, ensure_ascii=False, default=str), encoding="utf-8")
    out = R.rescore_file(src)
    assert out != src and out.exists() and json.loads(out.read_text(encoding="utf-8"))["meta"]["rescored"]["from"] == src.name
    with pytest.raises(R.RunnerConfigError):
        R.rescore_file(src)  # 같은 이름의 새 파일이 이미 있으면 덮어쓰지 않는다
    with pytest.raises(R.RunnerConfigError):
        R.rescore_file(src, src)
    assert R.main(["--rescore", str(src), "--out", str(tmp_path / "o2.json")]) == 0
    legacy = R.run_eval([first], lambda it: rec([check(SEQ_A)], rt=None), sealed=False, phrases=PH, meta={"set_file": dev.name})
    lsrc = tmp_path / "legacy.json"
    lsrc.write_text(json.dumps(legacy, ensure_ascii=False, default=str), encoding="utf-8")
    assert R.main(["--rescore", str(lsrc)]) == 3 and not (tmp_path / "legacy-rescored-traj-v2.json").exists()
