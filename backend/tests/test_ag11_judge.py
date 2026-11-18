"""AG-11 judge 실행기(`evaluation/judge/sonnet_judge.py`)·Ragas 3지표(`ragas_metrics.py`) 시험.

LLM·judge·공공 API·원격 DB 호출 0: 전송 계층은 가짜(`FakeTransport`)다. 문항·답변은 합성이며 개발셋·시험셋 문항이 아니다.
확인: 정상 채점, 형식 오류 1회 재시도, judge 오류 집계·오류율, 블라인드(조건명·버전 비포함), 비용 원장 eval 몫, 키 비노출,
Ragas 공식(분자·분모), 청크 ID Recall, calib_agreement 연결 형식, 프롬프트 파일 L0 검사.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "judge", ROOT / "evaluation" / "judge_calib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import calib_agreement as A  # noqa: E402
import ragas_metrics as RG  # noqa: E402
import select_calib40 as S  # noqa: E402
import sonnet_judge as SJ  # noqa: E402

from app.llm import prompts as LP  # noqa: E402
from app.llm.ledger import CostLedger  # noqa: E402

FAKE_KEY = "sk-ant-fake-ZZZZ-not-a-real-key-1234"  # noqa: S105 - 가짜 값(비노출 확인용)


# ------------------------------------------------------------------ 가짜 전송·합성 입력

def j3_out(r1: bool = True, r2: bool = True, r3: bool = True, extra: dict[str, Any] | None = None) -> str:
    items = {k: {"pass": v, "reason": f"{k} 이유", "evidence": ["pregnancy:X"]} for k, v in (("R1", r1), ("R2", r2), ("R3", r3))}
    return json.dumps({"rubric": "J3@v1", "items": items, "overall_pass": True, **(extra or {})}, ensure_ascii=False)


def j1_out(flags: list[bool]) -> str:
    claims = [{"id": i + 1, "text": f"주장 {i + 1}", "supported": f, "reason": "r", "evidence": ["c1"] if f else []} for i, f in enumerate(flags)]
    return json.dumps({"rubric": "J1@v1", "claims": claims, "overall_pass": all(flags)}, ensure_ascii=False)


def j2_out(rel: dict[str, bool], attributed: list[bool]) -> str:
    return json.dumps({"rubric": "J2@v1", "chunks": [{"id": k, "relevant": v, "reason": "r"} for k, v in rel.items()],
                       "reference_claims": [{"text": f"정답 주장 {i}", "attributed": a, "evidence": []} for i, a in enumerate(attributed)]},
                      ensure_ascii=False)


class FakeTransport:
    """대본대로 응답한다. 요청 인자를 기록해 시험이 본다. 외부 호출 없음."""

    def __init__(self, script: list[Any], *, in_tok: int = 600, out_tok: int = 340) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.in_tok, self.out_tok = in_tok, out_tok

    def complete(self, *, system: str, messages: list[dict[str, Any]], max_tokens: int) -> SJ.TransportResult:
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        if not self.script:
            raise AssertionError("대본보다 많이 호출됐다")
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        if isinstance(nxt, SJ.TransportResult):
            return nxt
        return SJ.TransportResult(text=nxt, stop_reason="end_turn", input_tokens=self.in_tok, output_tokens=self.out_tok)


def item(branch: str = "오정보", rtype: str = "correct", required: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    return {"id": "syn-001", "question": "합성 질문: 이 약이 임부금기 2등급이라던데 맞나요?", "branch_label": branch,
            "composition_group": branch, "expected_response_type": rtype, "reference": "합성 정답 근거: 목록에 1등급으로 올라 있다.",
            "required_elements": required or ["PREMISE_CORRECTED", "NO_SAFETY_ASSERTION", "PHARMACIST_NOTICE"],
            "answer_evidence": {"evidence_ids": ["pregnancy:X", "contra_pair:B:A"]}, **kw}


def answer(summary: str | None = "합성 요약: 1등급으로 올라 있어요.", route: str = "AGENT") -> dict[str, Any]:
    return {"summary": summary, "text": f"{summary or ''}\n고정 문구", "route": route,
            "detail": [{"evidence_id": "pregnancy:X", "kind": "pregnancy", "status": "FOUND", "publisher": "KIDS", "as_of": "2026-07-21",
                        "rows": [{"grade": "1", "detail": "합성 상세"}]},
                       {"evidence_id": "l2-chunk-9", "kind": "search", "status": "FOUND", "rows": [{"text": "무관한 문장"}]}],
            "grade_defs": [{"grade": "1", "text": "1등급 정의 원문"}], "citations": [{"evidence_id": "contra_pair:A:B"}]}


def mk(script: list[Any], **kw: Any) -> tuple[SJ.SonnetJudge, FakeTransport]:
    t = FakeTransport(script)
    return SJ.SonnetJudge(t, **kw), t


# ------------------------------------------------------------------ 설정 고정(RFP-26-01·RFP-28 §7)

def test_request_shape_model_thinking_no_temperature():
    req = SJ.build_request(system="s", messages=[{"role": "user", "content": "u"}], max_tokens=10)
    assert req["model"] == "claude-sonnet-5-5" == SJ.JUDGE_MODEL
    assert req["thinking"] == {"type": "between_tools"}
    assert "temperature" not in req and "top_p" not in req and "top_k" not in req
    assert SJ.RUBRIC_VERSIONS == {"J1": "J1@v1", "J2": "J2@v1", "J3": "J3@v1", "J4": "J4@v1", "J5": "J5@v1"}


def test_meta_records_model_rubric_prompt_sha():
    j, _ = mk([])
    m = j.meta()
    assert m["judge_model"] == "claude-sonnet-5-5" and m["rubric_versions"]["J4"] == "J4@v1"
    assert m["prompt_sha256"] == hashlib.sha256(SJ.DEFAULT_PROMPT.read_bytes()).hexdigest()
    assert m["prompt_file"] == "judge_rubric@v1.md" and m["prompt_status"] == "draft"
    assert m["thinking"] == {"type": "between_tools"} and m["temperature"] is None
    assert m["usage"]["calls"] == 0 and m["usage"]["error_rate"] is None


def test_prompt_file_passes_l0_checks_and_has_all_sections():
    """`backend/prompts` 규칙(프런트매터·비밀값·개발셋 문장·실제 질문 꼴)을 judge 프롬프트에도 적용한다."""
    dev_q = LP.load_dev_questions()
    assert dev_q, "개발셋을 읽지 못했다"
    assert LP.check_prompt_file(SJ.DEFAULT_PROMPT, dev_questions=dev_q) == []
    secs = SJ.load_prompt()["sections"]
    assert set(SJ.PROMPT_SECTIONS) <= set(secs) and "R5" in secs["J4"] and "권유" in secs["J1"]


# ------------------------------------------------------------------ 정상 채점·비용

def test_score_j3_ok_and_cost_to_eval_bucket(tmp_path: Path):
    led = CostLedger(tmp_path / "ledger.json")
    j, t = mk([j3_out(True, True, False, extra={"overall_pass": True})], ledger=led)
    inp = SJ.input_from_item(item(), answer())
    out = j.score_rubric("J3", inp)
    assert out["status"] == "ok" and out["rubric"] == "J3@v1"
    assert out["items"]["R3"]["pass"] is False and out["overall_pass"] is False  # 모델의 overall_pass(True)를 믿지 않는다
    assert j.usage.calls == 1 and j.usage.scored == 1 and j.usage.errors == 0
    cost = SJ.estimate_cost_usd(600, 340)
    assert cost == pytest.approx(600 * 2 / 1e6 + 340 * 10 / 1e6) and j.usage.cost_usd == pytest.approx(cost)
    assert led.spent("eval") == pytest.approx(cost, abs=1e-6) and led.spent("dev") == 0.0  # eval 몫에만 쌓인다
    assert t.calls[0]["max_tokens"] == SJ.MAX_TOKENS and "채점자" in t.calls[0]["system"]


def test_score_item_multiple_rubrics_and_element_results():
    j, _ = mk([j1_out([True, True]), j3_out(True, True, True)])
    res = j.score(item(), answer())
    assert res["status"] == "ok" and set(res["rubrics"]) == {"J1", "J3"} and res["rubric"] == "J1@v1+J3@v1"
    assert res["rubrics"]["J1"]["faithfulness"] == 1.0 and res["overall_pass"] is True
    els = res["elements"]
    assert els["PREMISE_CORRECTED"] is True and els["REFUSAL_WITH_REASON"] is None and els["SAYS_NOT_FOUND"] is None


def test_score_not_applicable_when_no_rubric():
    j, t = mk([])
    res = j.score(item(branch="모호"), answer(summary=None))
    assert res["status"] == "not_applicable" and res["rubrics"] == {} and t.calls == []


def test_rubrics_for_matches_select_calib40_rule():
    for br in ("오정보", "범위 외", "근거 없음", "정상-병용", "모호"):
        for summ, end in (("요약", "NORMAL"), (None, "NORMAL"), ("요약", "CLARIFY"), ("요약", "REFUSE")):
            res = {"branch_label": br}
            run = {"answer": {"summary": summ}, "end_reason": end}
            assert SJ.rubrics_for(res, run["answer"], end) == S.rubrics_for(res, run)


def test_j4_r5_only_when_required():
    j, t = mk([json.dumps({"rubric": "J4@v1", "items": {k: {"pass": True, "reason": "", "evidence": []} for k in ("R1", "R2", "R3", "R5")},
                           "overall_pass": True}),
               json.dumps({"rubric": "J4@v1", "items": {k: {"pass": True, "reason": "", "evidence": []} for k in ("R1", "R2", "R3")},
                           "overall_pass": True})])
    with_r5 = SJ.input_from_item(item(branch="범위 외", rtype="refuse", required=["REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT"]), answer())
    assert with_r5.r5 and "R5" in SJ.output_schema("J4", r5=True)["properties"]["items"]["required"]
    out = j.score_rubric("J4", with_r5)
    assert out["status"] == "ok" and out["items"]["R5"]["pass"] is True and "R5(상태 평가 불가 고지)를 채점한다" in t.calls[0]["messages"][0]["content"]
    els = SJ.element_results({"rubrics": {"J4": out}})
    assert els["REFUSAL_WITH_REASON"] is True and els["NO_STATE_ASSESSMENT"] is True
    no_r5 = SJ.input_from_item(item(branch="범위 외", rtype="refuse", required=["REFUSAL_WITH_REASON"]), answer())
    out2 = j.score_rubric("J4", no_r5)
    assert out2["status"] == "ok" and "R5" not in out2["items"]
    assert SJ.element_results({"rubrics": {"J4": out2}})["NO_STATE_ASSESSMENT"] is None


def test_j5_r2_reuses_j1():
    j, _ = mk([j1_out([True, False]), json.dumps({"rubric": "J5@v1", "items": {k: {"pass": True, "reason": "", "evidence": []} for k in ("R1", "R2", "R3")},
                                                   "overall_pass": True})])
    res = j.score(item(branch="근거 없음", rtype="no_evidence", required=["SAYS_NOT_FOUND", "DISTINCT_FROM_NOT_LISTED"]), answer())
    assert res["elements"]["SAYS_NOT_FOUND"] is False  # J1 unsupported 1개 → J5 R2 기준 미달
    assert res["elements"]["DISTINCT_FROM_NOT_LISTED"] is True


# ------------------------------------------------------------------ 형식 오류 재시도·judge 오류 집계

def test_format_error_retries_once_then_ok():
    j, t = mk(["이건 JSON이 아니다", j3_out()])
    out = j.score_rubric("J3", SJ.input_from_item(item(), answer()))
    assert out["status"] == "ok" and j.usage.retries == 1 and j.usage.calls == 2 and j.usage.errors == 0
    msgs = t.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"] and "형식 오류" in msgs[2]["content"]


def test_format_error_twice_is_judge_error():
    bad_schema = json.dumps({"rubric": "J3@v1", "items": {"R1": {"pass": "yes"}}, "overall_pass": True})
    j, _ = mk(["```json\n{broken", bad_schema])
    out = j.score_rubric("J3", SJ.input_from_item(item(), answer()))
    assert out["status"] == SJ.STATUS_ERROR and out["error"] == "FORMAT" and "items" in out["detail"]
    assert j.usage.errors == 1 and j.usage.retries == 1 and j.usage.scored == 0
    assert j.meta()["usage"]["error_rate"] == 1.0


def test_max_tokens_truncation_counts_as_format_error():
    j, _ = mk([SJ.TransportResult(text='{"rubric":', stop_reason="max_tokens", input_tokens=1, output_tokens=2), j3_out()])
    assert j.score_rubric("J3", SJ.input_from_item(item(), answer()))["status"] == "ok" and j.usage.retries == 1


def test_api_error_is_judge_error_and_message_redacted():
    j, _ = mk([RuntimeError(f"401 unauthorized key={FAKE_KEY} dsn=postgresql://u:pw@host/db")])
    out = j.score_rubric("J3", SJ.input_from_item(item(), answer()))
    assert out["status"] == SJ.STATUS_ERROR and out["error"] == "API"
    assert FAKE_KEY not in out["detail"] and "pw@host" not in out["detail"]


def test_refusal_is_judge_error_no_other_model():
    j, t = mk([SJ.TransportResult(text=None, stop_reason="refusal", refusal_category="general_harms")])
    out = j.score_rubric("J3", SJ.input_from_item(item(), answer()))
    assert out["status"] == SJ.STATUS_ERROR and out["error"] == "REFUSAL" and out["detail"] == "general_harms"
    assert len(t.calls) == 1  # 대체 모델 호출·재시도 없음(모델 ID 고정)


def test_score_status_error_when_any_rubric_fails():
    j, _ = mk([j1_out([True]), "nope", "nope"])
    res = j.score(item(), answer())
    assert res["status"] == SJ.STATUS_ERROR and res["overall_pass"] is None and res["elements"]["PREMISE_CORRECTED"] is None
    assert j.usage.errors == 1 and j.usage.scored == 1 and j.meta()["usage"]["error_rate"] == 0.5


def test_budget_cap_blocks_before_call():
    j, t = mk([j3_out(), j3_out()], max_usd=0.001)
    inp = SJ.input_from_item(item(), answer())
    assert j.score_rubric("J3", inp)["status"] == "ok"  # 첫 호출 뒤 누적 $0.0046 > 상한
    with pytest.raises(SJ.JudgeBudgetExceeded):
        j.score_rubric("J3", inp)
    assert len(t.calls) == 1
    with pytest.raises(SJ.JudgeError):
        SJ.SonnetJudge(FakeTransport([]), max_usd=0)


# ------------------------------------------------------------------ 블라인드·키 비노출

def test_blind_input_has_no_condition_or_version_text():
    j, t = mk([j3_out()])
    it = item(condition="C2", prompt_set="prompt_set@v3", meta={"agent": "graph"})  # 문항에 섞여 들어와도 옮기지 않는다
    a = {**answer(), "prompt_version": "agent_system@v2", "model": "gpt-6-luna"}
    j.score(it, a, end_reason="NORMAL")
    sent = t.calls[0]["system"] + json.dumps(t.calls[0]["messages"], ensure_ascii=False)
    for forbidden in ("C2", "C1+", "prompt_set", "agent_system", "gpt-6-luna", "condition", "graph"):
        assert forbidden not in sent, forbidden
    assert "합성 질문" in sent and "합성 정답 근거" in sent and "pregnancy:X" in sent


def test_blind_check_rejects_forbidden_keys_in_calib_rows():
    with pytest.raises(SJ.BlindViolation):
        SJ.blind_check({"id": "x", "answer": {"summary": "s", "prompt_set": "prompt_set@v3"}})
    SJ.blind_check({"id": "x", "answer": {"summary": "s"}, "reference": "r"})


def test_anthropic_transport_without_sdk_or_never_exposes_key():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        with pytest.raises(SJ.JudgeError, match="SDK"):
            SJ.AnthropicTransport(api_key=FAKE_KEY)
        return
    t = SJ.AnthropicTransport(api_key=FAKE_KEY)  # pragma: no cover - SDK가 설치된 환경에서만
    assert FAKE_KEY not in repr(t) and FAKE_KEY not in str(vars(t).keys())


# ------------------------------------------------------------------ Ragas 3지표(공식)

def test_ragas_formulas():
    assert RG.context_precision([True, False, True]) == pytest.approx(0.8333, abs=1e-4)
    assert RG.context_precision([False, True]) == 0.5 and RG.context_precision([True, True]) == 1.0
    assert RG.context_precision([False, False]) is None and RG.context_precision([]) is None
    assert RG.context_recall([True, False, False, True]) == 0.5 and RG.context_recall([]) is None
    assert RG.faithfulness([True, True, False, True]) == 0.75 and RG.faithfulness([]) is None


def test_chunk_id_recall_pair_order_insensitive():
    r = RG.chunk_id_recall(["pregnancy:X", "contra_pair:B:A", "age:Y"], ["contra_pair:A:B", "pregnancy:X"])
    assert (r["k"], r["n"], r["rate"]) == (2, 3, 0.6667) and r["missing"] == ["age:Y"] and r["bundle_complete"] is False
    assert RG.chunk_id_recall([], ["x"]) == {"k": 0, "n": 0, "rate": None, "missing": [], "bundle_complete": None}


def test_ragas_item_retrieved_mode_scores_and_calls():
    j, t = mk([j1_out([True, True, False]), j2_out({"pregnancy:X": True, "l2-chunk-9": False, "grade_def:1": True}, [True, False])])
    row = RG.ragas_item(j, item(branch="정상", rtype="judgment"), answer(), tool_evidence_ids=["pregnancy:X"])
    assert row["faithfulness"] == pytest.approx(0.6667, abs=1e-4)
    assert row["context_precision"] == pytest.approx((1 / 1 + 2 / 3) / 2, abs=1e-4) and row["context_recall"] == 0.5
    assert row["n_contexts"] == 3 and row["chunk_id_recall"]["k"] == 2 and row["chunk_id_recall"]["n"] == 2  # 인용된 contra_pair도 센다
    assert len(t.calls) == 2 and "[답 요약" not in t.calls[1]["messages"][0]["content"]  # J2는 답을 보지 않는다
    assert row["judge_error"] is False


def test_ragas_item_reference_mode_c0_no_context_metrics():
    j, t = mk([j1_out([True])])
    row = RG.ragas_item(j, item(branch="정상"), answer(), mode=RG.MODE_REFERENCE)
    assert row["context_precision"] is None and row["context_recall"] is None and row["faithfulness"] == 1.0
    assert row["n_contexts"] == 1 and 'id="reference"' in t.calls[0]["messages"][0]["content"] and len(t.calls) == 1


def test_ragas_item_no_claims_no_contexts():
    j, t = mk([])
    row = RG.ragas_item(j, item(branch="모호", rtype="clarify"), {"summary": None, "detail": []}, end_reason="CLARIFY")
    assert row["faithfulness"] is None and row["context_precision"] is None and t.calls == []
    assert RG.ragas_applicable({"branch_label": "모호"}) and not RG.ragas_applicable({"branch_label": "범위 외"})


def test_aggregate_ragas_mean_ci_and_id_recall():
    rows = [{"faithfulness": 1.0, "context_precision": 0.5, "context_recall": None, "chunk_id_recall": RG.chunk_id_recall(["a"], ["a"]), "mode": "retrieved"},
            {"faithfulness": 0.5, "context_precision": None, "context_recall": None, "chunk_id_recall": RG.chunk_id_recall(["a", "b"], ["a"]),
             "mode": "retrieved", "judge_error": True}]
    agg = RG.aggregate_ragas(rows)
    assert agg["faithfulness"]["n"] == 2 and agg["faithfulness"]["mean"] == 0.75 and agg["faithfulness"]["claim"].startswith("유의성 주장 안 함")
    assert agg["context_precision"]["n"] == 1 and agg["context_precision"]["ci95"] is None and agg["context_recall"]["n_missing"] == 2
    assert agg["chunk_id_recall"]["items_all_ids"]["k"] == 1 and agg["chunk_id_recall"]["ids"]["k"] == 2 and agg["chunk_id_recall"]["ids"]["n"] == 3
    assert agg["judge_errors"] == 1


# ------------------------------------------------------------------ calib_agreement 연결(보정 40문항 형식)

def test_score_items_feeds_calib_agreement():
    rows = [{"id": "syn-010", "rubrics": ["J1", "J3"], "question": "합성 질문", "expected_response_type": "correct", "reference": "r",
             "required_elements": ["PREMISE_CORRECTED"], "answer": answer()},
            {"id": "syn-011", "rubrics": ["J4"], "question": "합성 질문 2", "expected_response_type": "refuse", "reference": "r",
             "required_elements": ["REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT"], "answer": answer("거절 요약")}]
    j, _ = mk([j1_out([True, False]), j3_out(True, False, True), "bad", "bad"])
    res = SJ.calib_result(j, rows)
    assert res["meta"]["judge_model"] == "claude-sonnet-5-5" and res["meta"]["rubric_versions"]["J3"] == "J3@v1"
    labels, reasons, errors = A.judge_to_labels(res)
    assert labels["syn-010"]["J1(뒷받침안됨/전체주장)"] is False and labels["syn-010"]["J3_R2"] is False and labels["syn-010"]["J3_R1"] is True
    assert errors == [{"id": "syn-011", "rubric": "J4", "status": SJ.STATUS_ERROR}]
    assert "주장 2" in reasons["syn-010"]["J1(뒷받침안됨/전체주장)"]


def test_calib_cli_dry_run_counts_calls_without_calling(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    p = tmp_path / "calib40-items.jsonl"
    p.write_text(json.dumps({"id": "syn-1", "rubrics": ["J1", "J3"], "question": "q", "answer": {}}) + "\n"
                 + json.dumps({"id": "syn-2", "rubrics": ["J5"], "question": "q", "answer": {}}) + "\n", encoding="utf-8")
    assert SJ.main(["--calib-items", str(p), "--out", str(tmp_path / "o.json"), "--max-usd", "0.5", "--dry-run"]) == 0
    assert "호출 3회" in capsys.readouterr().out and not (tmp_path / "o.json").exists()


def test_calib_cli_refuses_sealed_name(tmp_path: Path):
    import sealed_guard as G

    p = tmp_path / "test_set.SEALED.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    with pytest.raises(G.SealedAccessError):
        SJ.main(["--calib-items", str(p), "--out", str(tmp_path / "o.json"), "--max-usd", "0.5", "--dry-run"])


# ------------------------------------------------------------------ 보정 40 CLI 실행(AG-12, 2026-11-18): 키는 설정에서, 상한 초과 시 부분 저장

def _calib_rows(path: Path) -> Path:
    rows = [{"id": "syn-1", "rubrics": ["J3"], "question": "q1", "expected_response_type": "correct", "reference": "r", "answer": answer()},
            {"id": "syn-2", "rubrics": ["J3"], "question": "q2", "expected_response_type": "correct", "reference": "r", "answer": answer()},
            {"id": "syn-3", "rubrics": ["J3"], "question": "q3", "expected_response_type": "correct", "reference": "r", "answer": answer()}]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def test_transport_from_settings_reads_key_without_env(monkeypatch):
    """키는 `Settings`(현재 폴더·루트 `.env`)에서 읽어 SDK에 넘긴다. 환경변수가 없어도 된다. 키 없으면 JudgeError(키 값은 메시지에 없음)."""
    from app.config import Settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SJ.JudgeError, match="ANTHROPIC_API_KEY"):
        SJ.transport_from_settings(Settings(_env_file=None))
    seen: dict[str, Any] = {}

    def fake_transport(*, api_key: str | None = None, **_: Any) -> str:
        seen["key"] = api_key
        return "transport"

    monkeypatch.setattr(SJ, "AnthropicTransport", fake_transport)
    assert SJ.transport_from_settings(Settings(_env_file=None, anthropic_api_key=FAKE_KEY)) == "transport"
    assert seen["key"] == FAKE_KEY


def test_calib_cli_writes_result_in_calib_agreement_format(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    p = _calib_rows(tmp_path / "calib40-items.jsonl")
    out = tmp_path / "calib40-judge.json"
    judge, t = mk([j3_out(), j3_out(True, False, True), j3_out()], max_usd=1.0)
    rc = SJ.main(["--calib-items", str(p), "--out", str(out), "--max-usd", "1.0"], judge_factory=lambda max_usd, prompt_path: judge)
    assert rc == 0 and len(t.calls) == 3
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["meta"]["judge_model"] == "claude-sonnet-5-5" and res["meta"]["usage"]["calls"] == 3 and res["meta"]["partial"] is False
    assert res["meta"]["n_items"] == 3 and res["meta"]["calib_items_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    labels, _, errors = A.judge_to_labels(res)
    assert labels["syn-2"]["J3_R2"] is False and labels["syn-1"]["J3_R2"] is True and errors == []
    assert FAKE_KEY not in capsys.readouterr().out
    # 이미 있으면 덮어쓰지 않는다
    assert SJ.main(["--calib-items", str(p), "--out", str(out), "--max-usd", "1.0"], judge_factory=lambda max_usd, prompt_path: judge) == 2


def test_calib_cli_budget_exceeded_saves_partial_and_stops(tmp_path: Path, monkeypatch):
    """상한은 호출 **전에** 본다. 넘기면 멈추고 그때까지의 결과를 `.partial.json`에 남긴다(이미 쓴 비용의 결과를 버리지 않는다)."""
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    p = _calib_rows(tmp_path / "calib40-items.jsonl")
    out = tmp_path / "calib40-judge.json"
    judge, t = mk([j3_out(), j3_out(), j3_out()], max_usd=0.006)  # 호출당 $0.0046 → 2번째 호출 전 "누적+최대 호출 비용 > 상한"
    rc = SJ.main(["--calib-items", str(p), "--out", str(out), "--max-usd", "0.006"], judge_factory=lambda max_usd, prompt_path: judge)
    assert rc == 3 and len(t.calls) == 1 and not out.exists()
    part = json.loads(out.with_suffix(".partial.json").read_text(encoding="utf-8"))
    assert part["meta"]["partial"] is True and "상한" in part["meta"]["stopped"] and list(part["items"]) == ["syn-1"]
    assert part["meta"]["usage"]["calls"] == 1 and part["meta"]["usage"]["cost_usd"] <= 0.006


# ------------------------------------------------------------------ judge_rubric@v2(AG-12-06 A, 2026-11-18): 입력 표시 v2는 v2 파일에서만

PROMPT_V2 = SJ.HERE / "judge_rubric@v2.md"


def _code_answer() -> dict[str, Any]:
    """답 본문 = 모델 요약 + 코드가 붙인 판정 줄·고정 문구(`finalize.render_text` 모양)."""
    a = answer("합성 요약: 비슷한 약이 있어요. 하나를 골라 주세요.")
    a["text"] = a["summary"] + "\n[합성약] 금기 목록에 없음(안전하다는 뜻이 아님)\n금기 목록에 없다는 것이 안전하다는 뜻이 아니에요. 근처 약국·약사에게 확인하세요."
    return a


def test_v2_prompt_file_l0_checks_sections_and_frontmatter():
    dev_q = LP.load_dev_questions()
    assert LP.check_prompt_file(PROMPT_V2, dev_questions=dev_q) == []
    p = SJ.load_prompt(PROMPT_V2)
    assert p["version"] == "v2" and p["render"] == SJ.RENDER_V2 and p["rubric_versions"]["J3"] == "J3@v2"
    assert sorted(p["frontmatter"]["changed_from_v1"]) == ["J3", "J5", "SYSTEM"]
    v1 = SJ.load_prompt()
    assert v1["render"] == SJ.RENDER_V1 and v1["rubric_versions"] == SJ.RUBRIC_VERSIONS
    # J1·J2·J4·OUTPUT 문장은 v1과 같다(루브릭 뜻 불변). SYSTEM·J3·J5만 다르다
    for sec in ("J1", "J2", "J4", "OUTPUT"):
        assert p["sections"][sec] == v1["sections"][sec], sec
    for sec in ("SYSTEM", "J3", "J5"):
        assert p["sections"][sec] != v1["sections"][sec], sec
    assert "근거 상세" in p["sections"]["SYSTEM"] and "[코드 부착]" in p["sections"]["SYSTEM"]
    assert "되묻는 답" in p["sections"]["J5"] and "청크 머리글" in p["sections"]["J3"]


def test_mark_code_lines_marks_only_non_summary_lines():
    marked = SJ.mark_code_lines("요약 한 줄\n요약 두 줄", "요약 한 줄\n요약 두 줄\n[약] 주의\n\n고정 문구")
    assert marked.splitlines() == ["요약 한 줄", "요약 두 줄", "[코드 부착] [약] 주의", "", "[코드 부착] 고정 문구"]
    assert SJ.mark_code_lines(None, "") == "" and SJ.mark_code_lines(None, "x") == "[코드 부착] x"


def test_render_v2_marks_code_lines_and_names_chunks_as_detail():
    inp = SJ.input_from_item(item("근거 없음", "no_evidence"), _code_answer())
    v1 = SJ.render_user("J5", inp, SJ.load_prompt())
    v2 = SJ.render_user("J5", inp, SJ.load_prompt(PROMPT_V2))
    assert "[코드 부착]" not in v1 and "[근거 청크(검색 순위 순)]" in v1 and "[루브릭 J5@v1]" in v1
    assert "[루브릭 J5@v2]" in v2 and "[근거 상세 = 근거 청크" in v2 and "[근거 청크(검색 순위 순)]" not in v2
    assert "[코드 부착] [합성약] 금기 목록에 없음" in v2 and "[코드 부착] 금기 목록에 없다는 것이" in v2
    assert "[코드 부착] 합성 요약" not in v2 and "합성 요약: 비슷한 약이 있어요" in v2
    assert "<chunk id=\"pregnancy:X\"" in v2  # 청크 본문·ID는 그대로


def test_v2_judge_tags_results_and_meta_with_v2_and_calib_agreement_reads_them(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    t = FakeTransport([j3_out(True, False, True), "bad", "bad"])
    j = SJ.SonnetJudge(t, max_usd=1.0, prompt_path=PROMPT_V2)
    assert j.rubric_versions["J3"] == "J3@v2" and j.meta()["prompt_version"] == "v2" and j.meta()["render_version"] == SJ.RENDER_V2
    assert j.meta()["prompt_changed_from_v1"] == ["SYSTEM", "J3", "J5"] and j.meta()["prompt_file"] == "judge_rubric@v2.md"
    rows = [{"id": "syn-v2", "rubrics": ["J3", "J5"], "question": "q", "expected_response_type": "correct", "reference": "r", "answer": _code_answer()}]
    res = SJ.calib_result(j, rows)
    assert res["items"]["syn-v2"]["J3"]["rubric"] == "J3@v2" and res["items"]["syn-v2"]["J5"]["rubric"] == "J5@v2"
    assert "[코드 부착]" in t.calls[0]["messages"][0]["content"]
    labels, _, errors = A.judge_to_labels(res)
    assert labels["syn-v2"]["J3_R2"] is False and errors == [{"id": "syn-v2", "rubric": "J5", "status": SJ.STATUS_ERROR}]


def test_calib_cli_prompt_option_selects_v2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    p = _calib_rows(tmp_path / "calib15-v2-items.jsonl")
    rc = SJ.main(["--calib-items", str(p), "--out", str(tmp_path / "o.json"), "--max-usd", "0.3", "--dry-run", "--prompt", str(PROMPT_V2)])
    out = capsys.readouterr().out
    assert rc == 0 and "judge_rubric@v2.md render@v2" in out and "호출 3회" in out
