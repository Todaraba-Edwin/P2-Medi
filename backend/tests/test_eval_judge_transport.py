"""평가 인프라 시험(2026-11-18): judge 프롬프트 캐싱·Message Batches(AG-11-12 A), 실행 색인(BE-08-05 A), git 기록·새 동결 키(BE-08-06 A).

LLM·Anthropic·공공 API·원격 DB 호출 0: judge 전송·Batch 백엔드·SDK 클라이언트는 모두 가짜다. 질문·답은 합성이며 개발셋·시험셋 문항이 아니다.
확인: 캐시 표시 외에는 요청이 같다(결과 동일성 원칙), 캐시·Batch 비용 계산과 토큰 분리 집계, Batch 결과가 동기 실행과 같은 판정이 된다,
실패·만료·상한 처리, 색인 한 줄(시험셋은 집계 키만), 새 키는 이전 결과와 비교에서 빠진다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "judge", Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_runner as R  # noqa: E402
import freeze_check as FZ  # noqa: E402
import run_registry as RR  # noqa: E402
import sonnet_judge as SJ  # noqa: E402
import test_ag11_judge_runner as JR  # noqa: E402  (가짜 그래프 자원·가짜 judge 전송·합성 세트 재사용)
from test_ag11_judge_runner import _isolated_env  # noqa: E402, F401  (autouse: 키·원장·로그 경로 격리)

V2 = SJ.HERE / "judge_rubric@v2.md"


def _item(i: int = 0) -> dict[str, Any]:
    return {"id": f"syn-{i}", "question": f"합성 질문 {i}: 이 두 약을 같이 먹어도 되나요?", "branch_label": "오정보", "expected_response_type": "correct",
            "reference": "합성 정답 근거", "required_elements": ["PREMISE_CORRECTED"]}


def _answer(i: int = 0) -> dict[str, Any]:
    return {"summary": f"합성 요약 {i}", "text": f"합성 요약 {i}\n고정 문구",
            "detail": [{"evidence_id": f"pregnancy:X{i}", "kind": "pregnancy", "status": "FOUND", "rows": [{"grade": "1"}]}]}


class Capture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, messages: list[dict[str, Any]], max_tokens: int) -> SJ.TransportResult:
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        return SJ.TransportResult(text=json.dumps({"rubric": "J3@v2", "overall_pass": True,
                                                      "items": {k: {"pass": True, "reason": "r", "evidence": []} for k in ("R1", "R2", "R3")}}),
                                  stop_reason="end_turn", input_tokens=10, output_tokens=5)


def _captured_request(i: int = 0) -> dict[str, Any]:
    cap = Capture()
    SJ.SonnetJudge(cap, prompt_path=V2).score_rubric("J3", SJ.input_from_item(_item(i), _answer(i)))
    c = cap.calls[0]
    return {"system": c["system"], "messages": c["messages"], "max_tokens": c["max_tokens"]}


# --------------------------------------------------------------------------- 1. 캐싱: 캐시 표시 외에는 같은 요청

def test_cache_off_request_is_byte_identical_to_previous_shape():
    c = _captured_request()
    req = SJ.build_request(**c)
    assert req == {"model": "claude-sonnet-5-5", "max_tokens": SJ.MAX_TOKENS, "system": c["system"], "messages": c["messages"],
                   "thinking": {"type": "between_tools"}}
    assert SJ.build_request(**c, cache="off") == req


@pytest.mark.parametrize("mode", ["system", "rubric"])
def test_cache_modes_only_add_markers_model_sees_same_text(mode):
    c = _captured_request()
    off, on = SJ.build_request(**c), SJ.build_request(**c, cache=mode)
    assert SJ.request_text(on) == SJ.request_text(off)  # 블록을 이으면 글자가 같다(모델·사고·출력 상한도 같다)
    assert on["system"] == [{"type": "text", "text": c["system"], "cache_control": {"type": "ephemeral"}}]
    assert {k: v for k, v in on.items() if k not in ("system", "messages")} == {k: v for k, v in off.items() if k not in ("system", "messages")}
    first = on["messages"][0]["content"]
    if mode == "system":
        assert first == off["messages"][0]["content"]  # 사용자 메시지는 손대지 않는다
    else:
        assert isinstance(first, list) and len(first) == 2 and "cache_control" in first[0] and "cache_control" not in first[1]
        assert first[0]["text"].startswith("[루브릭 J3@v2]") and first[1]["text"].startswith(SJ.RUBRIC_SPLIT)
        assert first[0]["text"] + first[1]["text"] == off["messages"][0]["content"]
    marks = json.dumps(on, ensure_ascii=False).count("cache_control")
    assert marks == (1 if mode == "system" else 2) <= 4  # 요청당 캐시 표시 4개 제한 안


def test_cached_prefix_is_identical_across_items_and_differs_only_after_it():
    a, b = SJ.build_request(**_captured_request(0), cache="rubric"), SJ.build_request(**_captured_request(1), cache="rubric")
    assert a["system"] == b["system"] and a["messages"][0]["content"][0] == b["messages"][0]["content"][0]  # 캐시 접두가 문항과 무관
    assert a["messages"][0]["content"][1] != b["messages"][0]["content"][1]


def test_rubric_split_leaves_retry_turns_and_unsplittable_content_alone():
    msgs = [{"role": "user", "content": "[루브릭 J1@v2]\n규칙" + SJ.RUBRIC_SPLIT + "질문"}, {"role": "assistant", "content": "bad"},
            {"role": "user", "content": "형식 오류: 다시"}]
    out = SJ.build_request(system="s", messages=msgs, max_tokens=5, cache="rubric")["messages"]
    assert out[1:] == msgs[1:] and SJ.request_text({"model": 1, "max_tokens": 1, "thinking": 1, "system": "s", "messages": out})["messages"] == msgs
    plain = [{"role": "user", "content": "나눌 곳 없음"}]
    assert SJ.build_request(system="s", messages=plain, max_tokens=5, cache="rubric")["messages"] == plain
    with pytest.raises(SJ.JudgeError):
        SJ.build_request(system="s", messages=plain, max_tokens=5, cache="always")


def test_cost_counts_cache_write_read_and_batch_separately():
    base = SJ.estimate_cost_usd(1000, 300)
    assert base == pytest.approx(1000 * 2e-6 + 300 * 10e-6)  # 예전 계산 그대로
    assert SJ.estimate_cost_usd(100, 300, cache_write=900) == pytest.approx(100 * 2e-6 + 900 * 2e-6 * 1.25 + 300 * 10e-6)
    assert SJ.estimate_cost_usd(100, 300, cache_read=900) == pytest.approx(100 * 2e-6 + 900 * 2e-6 * 0.1 + 300 * 10e-6)
    assert SJ.estimate_cost_usd(1000, 300, batch=True) == pytest.approx(base / 2)


def test_usage_reports_cache_tokens_only_when_used(tmp_path):
    class T:
        def __init__(self, res: list[SJ.TransportResult]) -> None:
            self.res = res

        def complete(self, **_: Any) -> SJ.TransportResult:
            return self.res.pop(0)

    ok = Capture().complete(system="", messages=[], max_tokens=1).text
    plain = SJ.SonnetJudge(T([SJ.TransportResult(ok, "end_turn", 10, 5)]))
    plain.score_rubric("J3", SJ.input_from_item(_item(), _answer()))
    assert set(plain.usage.to_json()) == {"calls", "retries", "errors", "scored", "input_tokens", "output_tokens", "cost_usd", "error_rate"}
    assert "transport" not in plain.meta()  # 기본(동기·캐시 끔)이면 meta 모양도 예전 그대로
    led = JR.CostLedger(tmp_path / "l.json")
    j = SJ.SonnetJudge(T([SJ.TransportResult(ok, "end_turn", 50, 5, cache_creation_input_tokens=900),
                          SJ.TransportResult(ok, "end_turn", 50, 5, cache_read_input_tokens=900)]), ledger=led)
    for _ in range(2):
        j.score_rubric("J3", SJ.input_from_item(_item(), _answer()))
    u = j.usage.to_json()
    assert u["cache_creation_input_tokens"] == 900 and u["cache_read_input_tokens"] == 900 and u["input_tokens"] == 100 and u["batch_calls"] == 0
    want = SJ.estimate_cost_usd(50, 5, cache_write=900) + SJ.estimate_cost_usd(50, 5, cache_read=900)
    assert u["cost_usd"] == pytest.approx(want, abs=1e-6) and led.spent("eval") == pytest.approx(want, abs=1e-6)


class FakeMessages:
    def __init__(self) -> None:
        self.kw: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        self.kw.append(kw)
        usage = SimpleNamespace(input_tokens=40, output_tokens=7, cache_creation_input_tokens=0, cache_read_input_tokens=800)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")], stop_reason="end_turn", usage=usage, stop_details=None)


def test_anthropic_transport_sends_cache_markers_and_reads_cache_usage(monkeypatch):
    msgs = FakeMessages()
    monkeypatch.setattr(SJ, "_anthropic_client", lambda *a: SimpleNamespace(messages=msgs))
    t = SJ.AnthropicTransport(api_key="sk-ant-fake-not-real", cache="system")
    res = t.complete(system="S", messages=[{"role": "user", "content": "u"}], max_tokens=9)
    assert msgs.kw[0]["system"][0]["cache_control"] == {"type": "ephemeral"} and "temperature" not in msgs.kw[0]
    assert (res.input_tokens, res.cache_read_input_tokens, res.cache_creation_input_tokens, res.batch) == (40, 800, 0, False)
    assert "sk-ant" not in repr(t) and "sk-ant" not in json.dumps(vars(t), default=str)
    with pytest.raises(SJ.JudgeError):
        SJ.AnthropicTransport(cache="bogus")


# --------------------------------------------------------------------------- 2. Batch: 동기 실행과 같은 판정

class FakeBackend:
    """가짜 Batch 백엔드: 요청 인자를 `RubricTransport`에 넘겨 답을 만들고(결과는 순서를 뒤집어 돌려준다), 지정한 회차·요청을 실패시킨다."""

    def __init__(self, responder: Any, *, fail: dict[int, str] | None = None) -> None:
        self.responder = responder
        self.fail = dict(fail or {})  # {전체 제출 순번(0부터): 실패 종류}
        self.batches: list[list[str]] = []
        self.batch_ids: list[str] = []
        self._n = 0

    def submit(self, requests: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        self.batches.append([cid for cid, _ in requests])
        self.batch_ids.append(f"msgbatch_fake_{len(self.batches)}")
        out: dict[str, Any] = {}
        for cid, params in reversed(requests):
            n, self._n = self._n, self._n + 1
            kind = self.fail.get(n)
            if kind:
                out[cid] = SJ.BatchFailure(kind, "invalid_request" if kind == "errored" else "", retryable=kind != "errored")
                continue
            flat = SJ.request_text(params)
            r = self.responder.complete(system=flat["system"], messages=flat["messages"], max_tokens=params["max_tokens"])
            out[cid] = SJ.TransportResult(r.text, r.stop_reason, r.input_tokens, r.output_tokens, batch=True)
        return out


class CacheAttrTransport(JR.RubricTransport):
    cache = "off"


def _run_mode(tmp_path: Path, *extra: str, bad_first: bool = False, fail: dict[int, str] | None = None, max_usd: str = "1",
              n: int = 3) -> tuple[int, dict[str, Any], Any, FakeBackend | None]:
    d = tmp_path / ("batch" if "--judge-batch" in extra else "sync")
    d.mkdir(exist_ok=True)
    tr = CacheAttrTransport(bad_first=bad_first)
    backend = FakeBackend(CacheAttrTransport(bad_first=bad_first), fail=fail) if "--judge-batch" in extra else None
    out = d / "out.json"
    args = ["--set", str(JR._synth_set(d, n)), "--agent", "graph", "--max-usd", "1", "--out", str(out), "--judge", "sonnet",
            "--judge-max-usd", max_usd, *extra]
    rc = R.main(args, settings_fn=JR._settings, resources_factory=JR.Factory(),
                judge_factory=lambda settings, mx: SJ.SonnetJudge(tr, max_usd=mx), batch_backend_factory=lambda t: backend)
    return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}), tr, backend


def _judged(res: dict[str, Any]) -> list[Any]:
    return [(r["id"], r["judge"], r.get("ragas"), r["elements"], r["safety"]) for r in res["items"]]


@pytest.mark.parametrize("bad_first", [False, True])
def test_batch_run_gives_same_judgments_as_sync_run(tmp_path, bad_first):
    rc_s, sync, tr_s, _ = _run_mode(tmp_path, bad_first=bad_first)
    rc_b, bat, tr_b, backend = _run_mode(tmp_path, "--judge-batch", bad_first=bad_first)
    assert rc_s == rc_b == 0 and tr_b.calls == []  # Batch 실행은 동기 전송을 한 번도 부르지 않는다
    def no_latency(m: dict[str, Any]) -> dict[str, Any]:  # 실행 시간 평균만 실행마다 다르다
        return {**m, "cost": {k: v for k, v in (m.get("cost") or {}).items() if k != "latency_mean_s"}}

    assert _judged(bat) == _judged(sync) and no_latency(bat["metrics"]) == no_latency(sync["metrics"])
    su, bu = sync["judge_usage"], bat["judge_usage"]
    assert (bu["calls"], bu["retries"], bu["scored"], bu["errors"]) == (su["calls"], su["retries"], su["scored"], su["errors"])
    assert bu["batch_calls"] == bu["calls"] and bu["cost_usd"] == pytest.approx(su["cost_usd"] / 2, abs=1e-6)
    assert list(bat["items"][0]) == list(sync["items"][0])  # 칸 순서(judge·ragas 다음 run)
    assert bu["transport"]["mode"] == "batch" and su["transport"] == {"mode": "sync", "cache": "off"}
    # 형식 오류 재시도는 첫 결과가 있어야 만들어지므로 2회차 Batch에 들어간다
    assert len(backend.batches) == (2 if bad_first else 1) and bu["transport"]["submitted"] == bu["calls"]


def test_batch_with_cache_sends_markers_and_records_mode(tmp_path):
    rc, res, _, backend = _run_mode(tmp_path, "--judge-batch", "--judge-cache", "rubric", n=1)
    assert rc == 0 and res["judge_usage"]["transport"]["cache"] == "rubric"
    rc2, res2, tr, _ = _run_mode(tmp_path, "--judge-cache", "system", n=1)
    assert rc2 == 0 and tr.cache == "system" and res2["judge_usage"]["transport"] == {"mode": "sync", "cache": "system"}
    assert res2["meta"]["judge"]["prompt_sha256"] == res["meta"]["judge"]["prompt_sha256"]  # 동결 값(judge 프롬프트)은 그대로


def test_batch_expired_is_resubmitted_once_and_invalid_request_is_judge_api_error(tmp_path):
    rc, res, _, backend = _run_mode(tmp_path, "--judge-batch", fail={0: "expired"}, n=1)
    assert rc == 0 and len(backend.batches) == 2 and res["judge_usage"]["errors"] == 0 and res["judge_usage"]["transport"]["resubmitted"] == 1
    (tmp_path / "x").mkdir()
    rc, res, _, _ = _run_mode(tmp_path / "x", "--judge-batch", fail={0: "errored"}, n=1)
    assert rc == 0 and res["judge_usage"]["errors"] == 1 and res["metrics"]["judge_error_kinds"]["by_kind"]["API"] == 1


def test_batch_budget_trims_submission_and_marks_rest_as_budget_stop(tmp_path):
    one = SJ._est_request_cost(SJ.build_request(**_captured_request()))
    rc, res, _, backend = _run_mode(tmp_path, "--judge-batch", max_usd=f"{one * 2.5:.6f}", n=3)
    assert rc == 0 and res["judge_usage"]["cap_reached"] is True and res["judge_usage"]["transport"]["not_submitted"] > 0
    assert sum(len(b) for b in backend.batches) < 6
    stops = [r["judge"].get("reason") for r in res["items"] if r["judge"].get("status") == "not_called"]
    assert stops and set(stops) == {R.JUDGE_BUDGET_STOP} and res["judge_usage"]["skipped"]


def test_batch_and_cache_flags_need_sonnet_judge(tmp_path, capsys):
    args = ["--set", str(JR._synth_set(tmp_path)), "--agent", "graph", "--max-usd", "1", "--out", str(tmp_path / "o.json")]
    assert R.main([*args, "--judge-batch"], settings_fn=JR._settings, resources_factory=JR.Factory()) == 2
    assert R.main([*args, "--judge-cache", "system"], settings_fn=JR._settings, resources_factory=JR.Factory()) == 2
    assert "--judge sonnet에서만" in capsys.readouterr().out and not (tmp_path / "o.json").exists()


class FakeBatches:
    def __init__(self, statuses: list[str], results: list[Any]) -> None:
        self.statuses, self.results_ = list(statuses), results
        self.created: list[Any] = []
        self.canceled: list[str] = []

    def create(self, *, requests: list[dict[str, Any]]) -> Any:
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_x", processing_status="in_progress")

    def retrieve(self, bid: str) -> Any:
        st = self.statuses.pop(0) if self.statuses else "ended"
        return SimpleNamespace(id=bid, processing_status=st, request_counts=SimpleNamespace(processing=1, succeeded=0, errored=0))

    def cancel(self, bid: str) -> None:
        self.canceled.append(bid)

    def results(self, bid: str) -> list[Any]:
        return self.results_


def _msg(text: str) -> Any:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", stop_details=None,
                           usage=SimpleNamespace(input_tokens=11, output_tokens=3, cache_creation_input_tokens=0, cache_read_input_tokens=0))


def test_anthropic_batch_backend_polls_maps_by_custom_id_and_classifies_failures():
    res = [SimpleNamespace(custom_id="b", result=SimpleNamespace(type="succeeded", message=_msg("B"))),
           SimpleNamespace(custom_id="a", result=SimpleNamespace(type="errored", error=SimpleNamespace(error=SimpleNamespace(type="api_error")))),
           SimpleNamespace(custom_id="c", result=SimpleNamespace(type="expired")),
           SimpleNamespace(custom_id="d", result=SimpleNamespace(type="errored", error=SimpleNamespace(type="invalid_request")))]
    fb = FakeBatches(["in_progress", "ended"], res)
    slept: list[float] = []
    be = SJ.AnthropicBatchBackend(SimpleNamespace(messages=SimpleNamespace(batches=fb)), poll_s=7, sleep=slept.append, log=lambda m: None)
    out = be.submit([("a", {"x": 1}), ("b", {"x": 2}), ("c", {"x": 3}), ("d", {"x": 4})])
    assert fb.created[0] == [{"custom_id": k, "params": {"x": v}} for k, v in (("a", 1), ("b", 2), ("c", 3), ("d", 4))] and slept == [7, 7]
    assert out["b"].text == "B" and out["b"].batch is True and out["b"].input_tokens == 11
    assert out["a"].kind == "errored" and out["a"].retryable and out["c"].retryable and not out["d"].retryable
    assert be.batch_ids == ["msgbatch_x"] and fb.canceled == []


def test_anthropic_batch_backend_cancels_after_max_wait():
    fb = FakeBatches(["in_progress", "in_progress", "canceling", "ended"],
                     [SimpleNamespace(custom_id="a", result=SimpleNamespace(type="canceled"))])
    t = iter(range(0, 1000, 100))
    be = SJ.AnthropicBatchBackend(SimpleNamespace(messages=SimpleNamespace(batches=fb)), poll_s=1, max_wait_s=150, sleep=lambda s: None,
                                  clock=lambda: next(t), log=lambda m: None)
    out = be.submit([("a", {})])
    assert fb.canceled == ["msgbatch_x"] and out["a"].kind == "canceled" and out["a"].retryable is False  # 우리가 취소한 것은 다시 보내지 않는다


def test_calib_cli_cache_batch_and_limit_give_same_items_as_sync(tmp_path):
    """동일성 확인 명령(보고 할 일 6)이 쓰는 경로: 보정 문항 파일(고정 입력)을 동기·캐시·Batch로 채점하면 판정이 같다(가짜 전송)."""
    import test_ag11_judge as TJ

    p = TJ._calib_rows(tmp_path / "calib40-items.jsonl")

    class J3:
        cache = "off"

        def complete(self, **_: Any) -> SJ.TransportResult:
            return SJ.TransportResult(TJ.j3_out(True, False, True), "end_turn", 600, 340)

    outs = {}
    for name, extra in (("sync", []), ("cache", ["--cache", "rubric"]), ("batch", ["--batch", "--cache", "system"])):
        t = J3()
        out = tmp_path / f"{name}.json"
        rc = SJ.main(["--calib-items", str(p), "--out", str(out), "--max-usd", "1.0", "--limit", "2", *extra],
                     judge_factory=lambda mx, pp, t=t: SJ.SonnetJudge(t, max_usd=mx),
                     batch_backend_factory=lambda tr: FakeBackend(J3()))
        assert rc == 0
        outs[name] = json.loads(out.read_text(encoding="utf-8"))
    assert list(outs["sync"]["items"]) == ["syn-1", "syn-2"]
    assert outs["sync"]["items"] == outs["cache"]["items"] == outs["batch"]["items"]
    assert "transport" not in outs["sync"]["meta"] and outs["cache"]["meta"]["transport"] == {"mode": "sync", "cache": "rubric"}
    b = outs["batch"]["meta"]
    assert b["transport"]["mode"] == "batch" and b["usage"]["batch_calls"] == 2
    assert b["usage"]["cost_usd"] == pytest.approx(outs["sync"]["meta"]["usage"]["cost_usd"] / 2, abs=1e-6)


# --------------------------------------------------------------------------- 3. 실행 색인·git 기록

def test_run_appends_one_registry_line_next_to_result(tmp_path):
    rc, res, _, _ = _run_mode(tmp_path, n=2)
    reg = RR.read(tmp_path / "sync" / "registry.jsonl")
    assert rc == 0 and len(reg) == 1
    e = reg[0]
    assert e["registry"] == RR.REGISTRY_VERSION and e["status"] == "ok" and e["condition"] == "C2" and e["n_items_run"] == 2
    assert e["run_id"] == res["meta"]["agent_info"]["run_id"] and e["result"].endswith("out.json")
    assert e["git_commit"] == res["meta"]["git_commit"] and isinstance(e["git_dirty"], bool | None)
    assert e["freeze"]["sha256"] and e["freeze"]["judge_model"] == "claude-sonnet-5-5" and e["cost_usd"]["judge"] == res["judge_usage"]["cost_usd"]
    assert e["metrics"]["contra_judgment_accuracy"]["n"] == res["metrics"]["contra_judgment_accuracy"]["n"]
    assert "syn-000" not in json.dumps(e, ensure_ascii=False)  # 문항 ID를 담지 않는다


def test_result_meta_has_git_commit_and_dirty_flag(tmp_path):
    rc, res, _, _ = _run_mode(tmp_path, n=1)
    g = RR.git_state()
    assert res["meta"]["git_commit"] == g["git_commit"] and res["meta"]["git_dirty"] == g["git_dirty"]
    assert g["git_commit"] is None or len(g["git_commit"]) == 40


def test_sealed_registry_entry_has_only_aggregate_keys():
    sealed = {"meta": {"set": "test", "sealed": True, "condition": "C2", "agent_info": {"run_id": "r1"}, "set_sha256": "a" * 64},
              "metrics": {"contra_judgment_accuracy": {"k": 3, "n": 4, "rate": 0.75, "wilson95": [0.3, 0.95], "claim": "x"},
                          "trajectory": {"verdicts": {"Pass": 3}, "top_fail_kinds": [["X", 1]]}},
              "stopped": {"reason": "CONSECUTIVE_ERRORS", "run": 1, "index": 7, "item_id": "test-007"}, "items": "omitted: sealed set"}
    e = RR.build_entry(sealed, result_path=None, git={"git_commit": "c" * 40, "git_dirty": False})
    text = json.dumps(e, ensure_ascii=False)
    assert e["status"] == "stopped" and e["stopped"] == {"reason": "CONSECUTIVE_ERRORS", "run": 1} and "test-007" not in text and '"index"' not in text
    assert e["metrics"]["contra_judgment_accuracy"] == {"k": 3, "n": 4, "rate": 0.75, "wilson95": [0.3, 0.95]} and "top_fail" not in text


def test_registry_write_failure_does_not_break_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(RR, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    rc, res, _, _ = _run_mode(tmp_path, n=1)
    assert rc == 0 and res and "실행 색인을 쓰지 못했다" in capsys.readouterr().out


# --------------------------------------------------------------------------- 4. 새 동결 키(다음 측정 기간 후보)

def test_code_versions_record_router_and_tools_hashes():
    for cond in ("C2", "C1"):
        v = R.code_versions(cond)
        assert v["router"].startswith("router-src@") and v["tools"].startswith("tools-src@")
        assert v["graph"] == R.code_versions(cond)["graph"]  # 기존 키 값은 그대로 계산된다


def _res(cond: str = "C2", **ver: Any) -> dict[str, Any]:
    return {"meta": {"condition": cond, "set_sha256": "a" * 64, "versions": {"model": {"agent": "m"}, "metrics": "metrics-src@x", **ver}}}


def test_same_freeze_skips_new_keys_against_old_results_and_compares_when_both_have_them(capsys, tmp_path):
    old, new = _res(), _res(router="router-src@1", tools="tools-src@1")
    assert FZ.same_freeze(old, new) == [] and FZ.same_freeze_skipped(old, new) == ["router_src", "tools_src"]
    other = _res(router="router-src@2", tools="tools-src@1")
    assert [d["item"] for d in FZ.same_freeze(new, other)] == ["router_src"] and FZ.same_freeze_skipped(new, other) == []
    assert FZ.same_freeze_skipped(_res("C0"), new) == ["router_src", "tools_src"]
    assert FZ.freeze_diff(new, other) == FZ.freeze_diff(new, new) == []  # 실행 전 가드(기존 계산)는 그대로: 새 키를 보지 않는다
    assert list(FZ.FREEZE_ITEMS) == [r["item"] for r in FZ.check_result(new)]  # 점검표 항목 수·순서 그대로
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(old), encoding="utf-8")
    pb.write_text(json.dumps(new), encoding="utf-8")
    FZ.main([str(pa), str(pb), "--same", "--no-manifest", "--dict-version", ""])
    assert "새 키라 비교 제외: router_src, tools_src" in capsys.readouterr().out
