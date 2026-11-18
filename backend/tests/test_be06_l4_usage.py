"""BE-06-36 A L4 요청 단위 모델 사용량(토큰·비용) 시험. 가짜 모델만, LLM·공공 API·원격 DB 호출 0.

- 서비스 실행기(`LazyGraphRunner`)는 요청마다 두 모델을 `UsageMeter`로 감싸 그 요청의 `RequestUsage`에 숫자만 더한다.
- 스트림은 요청이 끝나면 `tokens_in`·`tokens_out`·`cost_usd`를 L4 집계(`SpanLogger(mode="service")`)에 넘긴다. 질문·약 이름·모델 출력은 없다.
- 동시 요청은 각자 다른 합계 객체를 써서 섞이지 않는다. 모델 호출이 없으면(거절 등) 칸이 없다(0으로 지어내지 않음).
"""

from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.llm import estimate_cost_usd  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api.service import REQUEST_USAGE, LazyGraphRunner, RequestUsage, UsageMeter, request_deps  # noqa: E402
from app.api.stream import _record_metrics  # noqa: E402
from app.logging import SpanLogger  # noqa: E402
from app.logging.spans import Aggregator  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
MARKER = "비밀질문표지UQ3"
Q_PAIR = f"{MARKER} {AZI}이랑 {COLD} 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
SUMMARY_TEXT = "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요."
GOOD = {"sentences": [{"text": SUMMARY_TEXT, "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}]}


def _um(inp: int, out: int, cached: int = 0) -> dict[str, Any]:
    um: dict[str, Any] = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    if cached:
        um["input_token_details"] = {"cache_read": cached}
    return um


def _script() -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1")], usage_metadata=_um(100, 10)),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c2")],
                  usage_metadata=_um(200, 20, cached=50)),
        AIMessage("조회를 마쳤다", usage_metadata=_um(300, 5)),
    ]


def _summary_with_raw() -> ScriptedSummary:
    # 실제 요약 모델(`CachedSummary`)과 같은 모양 `{"raw": AIMessage, "parsed": 초안}`
    return ScriptedSummary([{"raw": AIMessage("{}", usage_metadata=_um(400, 40)), "parsed": GOOD}])


EXPECTED_IN, EXPECTED_OUT = 100 + 200 + 300 + 400, 10 + 20 + 5 + 40
EXPECTED_COST = (estimate_cost_usd(100, 10) + estimate_cost_usd(200, 20, 50) + estimate_cost_usd(300, 5) + estimate_cost_usd(400, 40))


def _factory(tool_model: Any, summary_model: Any):
    def make(_settings: Any) -> Any:
        dd = golden_dict()
        ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
        return build_deps(dd, ctx, tool_model=tool_model, summary_model=summary_model, system_prompt="시험용 시스템 프롬프트")
    return make


def _post(runner: Any, question: str) -> tuple[dict[str, Any], str]:
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=SpanLogger(mode="service", aggregator=agg))
    r = TestClient(app).post("/chat", json={"question": question, "context": {"pregnant": True}})
    assert r.status_code == 200
    agg.flush()
    text = out.getvalue()
    lines = [json.loads(x) for x in text.splitlines()]
    assert len(lines) == 1
    return lines[0], text


# --------------------------------------------------------------------------- `/chat` 끝까지
def test_service_request_reports_token_and_cost_sums_without_content():
    runner = LazyGraphRunner(settings=None, resources_factory=_factory(ScriptedToolModel(script=_script()), _summary_with_raw()))
    line, text = _post(runner, Q_PAIR)
    assert line["counts"]["node=chat"] == 1 and line["counts"]["end_reason=NORMAL"] == 1
    assert line["sums"]["tokens_in"] == EXPECTED_IN and line["sums"]["tokens_out"] == EXPECTED_OUT
    assert abs(line["sums"]["cost_usd"] - round(EXPECTED_COST, 6)) < 1e-9
    assert set(line["sums"]) == {"latency_ms", "tokens_in", "tokens_out", "cost_usd"}
    for s in (MARKER, AZI, COLD, "이지렉트", "타이레놀", SUMMARY_TEXT, "조회를 마쳤다", PAIR_EID, "pregnant", "임신"):
        assert s not in text, s


def test_request_without_model_calls_has_no_token_fields():
    # 거절(REFUSE)은 모델을 부르지 않는다 → 토큰·비용 칸을 0으로 지어내지 않고 아예 넣지 않는다
    runner = LazyGraphRunner(settings=None, resources_factory=_factory(ScriptedToolModel(script=[]), ScriptedSummary([])))
    line, _ = _post(runner, f"{AZI} 처방해 줘")
    assert line["counts"]["end_reason=REFUSE"] == 1
    assert set(line["sums"]) == {"latency_ms"}


def test_two_sequential_requests_sum_per_request_values():
    runner = LazyGraphRunner(settings=None, resources_factory=_factory(ScriptedToolModel(script=_script() * 2), _summary_with_raw()))
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=SpanLogger(mode="service", aggregator=agg))
    client = TestClient(app)
    for _ in range(2):
        assert client.post("/chat", json={"question": Q_PAIR}).status_code == 200
    line = agg.flush()
    assert line["counts"]["node=chat"] == 2
    assert line["sums"]["tokens_in"] == 2 * EXPECTED_IN and line["sums"]["tokens_out"] == 2 * EXPECTED_OUT


# --------------------------------------------------------------------------- 부품
class _Fixed:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.usage = {"calls": 7}

    def invoke(self, *_a: Any, **_k: Any) -> Any:
        return self.result


def test_usage_meter_returns_result_unchanged_and_counts_numbers_only():
    msg = AIMessage("모델 출력 원문", usage_metadata=_um(11, 3, cached=4))
    u = RequestUsage()
    meter = UsageMeter(_Fixed(msg), u, cost_fn=lambda i, o, c: i + o + c)
    assert meter.invoke(["질문"]) is msg
    assert (u.calls, u.tokens_in, u.tokens_out, u.tokens_cached, u.cost_usd) == (1, 11, 3, 4, 18)
    assert meter.usage == {"calls": 7}  # 그 밖의 속성은 원본 그대로
    assert u.fields() == {"tokens_in": 11, "tokens_out": 3, "cost_usd": 18}
    assert "모델 출력 원문" not in repr(u)


def test_usage_meter_handles_summary_shapes():
    u = RequestUsage()
    UsageMeter(_Fixed({"raw": AIMessage("{}", usage_metadata=_um(5, 2)), "parsed": {}}), u, cost_fn=lambda *_: 0.5).invoke([])
    UsageMeter(_Fixed(GOOD), u, cost_fn=lambda *_: 99.0).invoke([])  # 가짜 요약(초안 dict뿐): 호출만 세고 토큰·비용 0
    assert (u.calls, u.tokens_in, u.tokens_out, u.cost_usd) == (2, 5, 2, 0.5)


def test_usage_meter_swallows_counting_errors_but_not_model_errors():
    def bad_cost(*_a: Any) -> float:
        raise ValueError("단가 오류")

    msg = AIMessage("x", usage_metadata=_um(1, 1))
    assert UsageMeter(_Fixed(msg), RequestUsage(), cost_fn=bad_cost).invoke([]) is msg

    class Boom:
        def invoke(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("모델 실패")

    u = RequestUsage()
    try:
        UsageMeter(Boom(), u).invoke([])
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("모델 예외는 그대로 올라가야 한다")
    assert u.calls == 0


def test_request_deps_wraps_only_when_usage_is_bound():
    base = _factory(ScriptedToolModel(script=[]), ScriptedSummary([]))(None)
    plain = request_deps(base)
    assert plain.tool_model is base.tool_model and plain.summary_model is base.summary_model
    u = RequestUsage()
    explicit = request_deps(base, u)
    assert isinstance(explicit.tool_model, UsageMeter) and explicit.tool_model.inner is base.tool_model
    token = REQUEST_USAGE.set(u)
    try:
        assert isinstance(request_deps(base).summary_model, UsageMeter)
    finally:
        REQUEST_USAGE.reset(token)


def test_concurrent_requests_do_not_mix_usage():
    shared = _Fixed(AIMessage("x", usage_metadata=_um(1, 1)))  # 요청 사이에 공유되는 모델 객체
    usages = [RequestUsage() for _ in range(4)]
    barrier = threading.Barrier(len(usages))

    def work(i: int, u: RequestUsage) -> None:
        meter = UsageMeter(shared, u, cost_fn=lambda *_: 0.0)
        barrier.wait()
        for _ in range(i + 1):
            meter.invoke([])

    threads = [threading.Thread(target=work, args=(i, u)) for i, u in enumerate(usages)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [u.calls for u in usages] == [1, 2, 3, 4] and [u.tokens_in for u in usages] == [1, 2, 3, 4]


def test_record_metrics_passes_only_numeric_usage_fields():
    seen: list[dict[str, Any]] = []

    class Sink:
        def log(self, **fields: Any) -> None:
            seen.append(fields)

    u = RequestUsage()
    u.add(7, 2, 0, 0.001)
    _record_metrics(Sink(), latency_ms=1.0, end_reason="NORMAL", error_type=None, block_rules=[], usage=u)
    assert seen == [{"node": "chat", "latency_ms": 1.0, "end_reason": "NORMAL", "tokens_in": 7, "tokens_out": 2, "cost_usd": 0.001}]
