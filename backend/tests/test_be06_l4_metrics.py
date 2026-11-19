"""BE-06 서비스 집계 지표 L4 시험(goal 2회차 §2-8, RFP-34-01·03 A, H13). LLM·공공 API·원격 DB 호출 0.

`/chat` 한 요청이 끝나면 내용 없는 값(종료 사유·오류 유형·지연·하네스 규칙별 차단)만 L1 `SpanLogger(mode="service")`에 넘기고,
L1 `Aggregator`가 분 단위로 합쳐 표준 출력으로 낸다. 앱은 파일로 저장하지 않는다.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api.runner import GraphRunner  # noqa: E402
from app.logging import SpanLogger  # noqa: E402
from app.logging.spans import Aggregator  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
MARKER = "비밀질문표지QX7"
Q_PAIR = f"{MARKER} 엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
SUMMARY_TEXT = "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요."
SCRIPT = [
    AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
    AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
    AIMessage("조회를 마쳤다"),
]
GOOD = {"sentences": [{"text": SUMMARY_TEXT, "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}]}
BAD = {"sentences": [{"text": "이 조합은 안전합니다.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}]}
COUNT_KEY_RE = re.compile(r"^(spans|node=chat|end_reason=(NORMAL|CLARIFY|REFUSE|LIMIT|VALIDATION_FALLBACK)|error_type=[A-Za-z_]+|harness_rule=H\d{1,2}|h2_fallback\.[A-Z_]+)$")  # h2_fallback: BE-17-10 A 사유 코드 개수


def _runner(script: list[AIMessage], drafts: list[Any]) -> GraphRunner:
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    return GraphRunner.from_deps(build_deps(dd, ctx, tool_model=ScriptedToolModel(script=list(script)), summary_model=ScriptedSummary(drafts),
                                            system_prompt="시험용 시스템 프롬프트"))


class Boom:
    def updates(self, question: str, profile: Any, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        raise RuntimeError(f"폭발표지ZK9 {question}")
        yield  # pragma: no cover


def _post(runner: Any, question: str, context: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=SpanLogger(mode="service", aggregator=agg))
    r = TestClient(app).post("/chat", json={"question": question, "context": context or {}})
    assert r.status_code == 200
    agg.flush()
    text = out.getvalue()
    lines = [json.loads(x) for x in text.splitlines()]
    assert len(lines) == 1
    return lines[0], text


def _assert_content_free(line: dict[str, Any], text: str) -> None:
    assert set(line) == {"schema", "mode", "minute", "counts", "sums"} and line["mode"] == "service"
    assert all(COUNT_KEY_RE.match(k) and isinstance(v, int) for k, v in line["counts"].items()), line["counts"]
    assert set(line["sums"]) <= {"latency_ms"}
    for s in (MARKER, AZI, COLD, "이지렉트", "타이레놀", "임신", "pregnant", SUMMARY_TEXT, "병용금기", "폭발표지ZK9", PAIR_EID, "254000ATB"):
        assert s not in text, s


def test_normal_request_emits_content_free_aggregate():
    line, text = _post(_runner(SCRIPT, [GOOD]), Q_PAIR, {"pregnant": True, "age": {"lower": 33, "upper": 33}})
    _assert_content_free(line, text)
    assert line["counts"]["node=chat"] == 1 and line["counts"]["end_reason=NORMAL"] == 1
    assert not [k for k in line["counts"] if k.startswith(("error_type=", "harness_rule="))]
    assert line["sums"]["latency_ms"] >= 0


def test_refuse_and_fallback_count_harness_blocks_by_rule():
    line, text = _post(_runner([], []), f"{MARKER} {AZI} 처방해 줘")
    _assert_content_free(line, text)
    assert line["counts"]["end_reason=REFUSE"] == 1 and line["counts"]["harness_rule=H4"] == 1
    line, text = _post(_runner([*SCRIPT, AIMessage("다시 정리")], [BAD, BAD]), Q_PAIR)
    _assert_content_free(line, text)
    assert line["counts"]["end_reason=VALIDATION_FALLBACK"] == 1 and line["counts"]["harness_rule=H2"] == 1  # 되감기(rollback)는 차단으로 세지 않는다
    h2 = {k: v for k, v in line["counts"].items() if k.startswith("h2_fallback.")}  # BE-17-10 A: 폴백 사유 코드별 개수(실제 그래프 경로)
    assert h2 and "h2_fallback.OTHER" not in h2 and all(v >= 1 for v in h2.values()), h2


def test_error_request_counts_error_type_only():
    line, text = _post(Boom(), Q_PAIR)
    _assert_content_free(line, text)
    assert line["counts"]["node=chat"] == 1 and line["counts"]["error_type=RuntimeError"] == 1
    assert not [k for k in line["counts"] if k.startswith("end_reason=")]


def test_two_requests_are_summed_not_listed():
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, _runner([], []), metrics=SpanLogger(mode="service", aggregator=agg))
    client = TestClient(app)
    for _ in range(2):
        client.post("/chat", json={"question": f"{AZI} 처방해 줘"})
    line = agg.flush()
    assert line["counts"]["node=chat"] == 2 and len(out.getvalue().splitlines()) == 1  # 요청별 행이 아니라 합계 한 줄


def test_default_metrics_is_service_logger_and_writes_no_trace_files(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_MODE", "service")
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, _runner(SCRIPT, [GOOD]))
    metrics = getattr(app.state, chat_api.METRICS_STATE_KEY)
    assert isinstance(metrics, SpanLogger) and metrics.mode == "service" and metrics.path() is None
    out = io.StringIO()
    metrics.aggregator = Aggregator(stream=out)  # 표준 출력 대신 붙잡는다
    assert TestClient(app).post("/chat", json={"question": Q_PAIR}).status_code == 200
    metrics.aggregator.flush()
    assert json.loads(out.getvalue())["counts"]["end_reason=NORMAL"] == 1
    assert not (tmp_path / "logs").exists()  # 서비스 모드에서는 trace·로그 파일이 생기지 않는다(AG-01 §2 trace 조건)


def test_metrics_can_be_turned_off():
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, _runner([], []), metrics=None)
    assert getattr(app.state, chat_api.METRICS_STATE_KEY) is None
    assert TestClient(app).post("/chat", json={"question": f"{AZI} 처방해 줘"}).status_code == 200


@pytest.mark.parametrize("bad", [{"question": ""}, {}])
def test_rejected_requests_are_not_counted(bad):
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, _runner([], []), metrics=SpanLogger(mode="service", aggregator=agg))
    assert TestClient(app).post("/chat", json=bad).status_code == 422
    assert agg.flush() is None
