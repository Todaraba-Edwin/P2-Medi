"""BE-17-10 A: L4 분 단위 집계에 서비스 H2 폴백(`VALIDATION_FALLBACK`) 사유 코드별 개수만 더한다(2026-11-20). LLM·네트워크·DB 0.

- 집계 키는 `h2_fallback.<코드>`이고 값은 정수 개수뿐이다. 코드 목록 밖의 값(자유 문자열)은 이름 없이 `OTHER`로만 센다.
- 질문·문장·근거 ID는 집계 줄에 없다. 폴백이 없는 요청은 키가 생기지 않는다(기존 출력 불변).
- 코드 목록(`spans.H2_FALLBACK_REASONS`)이 validator·validator 노드가 내는 코드와 맞는지 확인한다(새 코드가 생기면 이 시험이 알린다).
"""

from __future__ import annotations

import inspect
import io
import json
import re
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent import validator as V
from app.agent.finalize import finalize
from app.agent.graph import nodes as N
from app.api import chat as chat_api
from app.api.stream import _fallback_reasons
from app.logging import SpanLogger
from app.logging.spans import H2_FALLBACK_OTHER, H2_FALLBACK_REASONS, Aggregator

MARKER = "비밀질문표지H2Q"
KEY_RE = re.compile(r"^h2_fallback\.[A-Z_]+$")


class FakeRunner:
    """노드 갱신만 흉내 낸다: validator가 폴백 이벤트를 내고 finalize가 폴백 답을 낸다."""

    def __init__(self, reasons: list[Any] | None) -> None:
        self.reasons = reasons

    def updates(self, question: str, profile: Any, confirmed_item_seqs: Any = (), **_: Any) -> Any:  # noqa: ARG002
        events: list[dict[str, Any]] = []
        if self.reasons is not None:
            events = [{"rule": "H2", "event": "REWIND", "reasons": list(self.reasons)},
                      {"rule": "H2", "event": "VALIDATION_FALLBACK", "reasons": list(self.reasons)}]
        yield {"validator": {"events": events}}
        fb = self.reasons is not None
        yield {"finalize": {"end_reason": "VALIDATION_FALLBACK" if fb else "NORMAL", "answer": finalize([], validation_fallback=fb)}}


def _run(reasons: list[Any] | None) -> tuple[dict[str, Any] | None, str]:
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, FakeRunner(reasons), metrics=SpanLogger(mode="service", aggregator=agg))
    r = TestClient(app).post("/chat", json={"question": f"{MARKER} 같이 먹어도 되나요?", "context": {}})
    assert r.status_code == 200
    agg.flush()
    text = out.getvalue()
    lines = [json.loads(x) for x in text.splitlines()]
    return (lines[0] if lines else None), text


class TestAggregator:
    def test_known_code_counted(self) -> None:
        out = io.StringIO()
        agg = Aggregator(stream=out)
        agg.h2_fallback("SAFE_ASSERTION")
        agg.h2_fallback("SAFE_ASSERTION")
        agg.h2_fallback("SCHEMA_INVALID")
        line = agg.flush()
        assert line is not None
        assert line["counts"] == {"h2_fallback.SAFE_ASSERTION": 2, "h2_fallback.SCHEMA_INVALID": 1}

    def test_unknown_or_free_text_becomes_other(self) -> None:
        out = io.StringIO()
        agg = Aggregator(stream=out)
        for bad in (f"{MARKER} 문장", "safe_assertion", None, 3, {"x": MARKER}):
            agg.h2_fallback(bad)
        line = agg.flush()
        assert line is not None and line["counts"] == {f"h2_fallback.{H2_FALLBACK_OTHER}": 5}
        assert MARKER not in out.getvalue()


class TestStreamWiring:
    def test_fallback_reason_counts_in_l4_line(self) -> None:
        line, text = _run(["QUOTE_MISMATCH", "SAFE_ASSERTION"])
        assert line is not None
        h2 = {k: v for k, v in line["counts"].items() if k.startswith("h2_fallback.")}
        # REWIND 이벤트의 사유는 세지 않고 VALIDATION_FALLBACK 사유만 센다
        assert h2 == {"h2_fallback.QUOTE_MISMATCH": 1, "h2_fallback.SAFE_ASSERTION": 1}
        assert all(KEY_RE.match(k) and isinstance(v, int) for k, v in h2.items())
        assert line["counts"].get("end_reason=VALIDATION_FALLBACK") == 1
        assert MARKER not in text

    def test_free_text_reason_not_leaked(self) -> None:
        line, text = _run([f"{MARKER} 모델 문장", "ALL_SENTENCES_DROPPED", 7])
        assert line is not None
        h2 = {k: v for k, v in line["counts"].items() if k.startswith("h2_fallback.")}
        assert h2 == {"h2_fallback.OTHER": 1, "h2_fallback.ALL_SENTENCES_DROPPED": 1}  # 문자열 아닌 7은 버린다
        assert MARKER not in text

    def test_no_fallback_no_key(self) -> None:
        line, _ = _run(None)
        assert line is not None and not any(k.startswith("h2_fallback.") for k in line["counts"])

    def test_dev_mode_sink_does_not_aggregate(self, tmp_path: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path))
        out = io.StringIO()
        agg = Aggregator(stream=out)
        app = FastAPI()
        chat_api.register(app)
        chat_api.set_runner(app, FakeRunner(["SAFE_ASSERTION"]), metrics=SpanLogger(mode="dev", aggregator=agg))
        assert TestClient(app).post("/chat", json={"question": "q", "context": {}}).status_code == 200
        assert agg.flush() is None


def test_extract_only_fallback_events() -> None:
    events = [{"rule": "H2", "event": "REWIND", "reasons": ["A"]}, {"rule": "H2", "event": "VALIDATION_FALLBACK", "reasons": ["B", 1]},
              {"rule": "H1", "event": "VALIDATION_FALLBACK", "reasons": ["C"]}, "junk", {"rule": "H2", "event": "VALIDATION_FALLBACK"}]
    assert _fallback_reasons(events) == ["B"]


def test_code_list_matches_validator() -> None:
    """validator의 검사 코드 상수와 validator 노드의 고정 사유가 모두 목록에 있다(새 코드가 생기면 목록을 함께 고친다)."""
    status_and_actions = {V.PASS, V.FIXED, V.FAIL, V.DROPPED, V.REWIND}  # 결과 상태·문장 처리 동작(사유 코드 아님)
    validator_codes = {v for k, v in vars(V).items()
                       if k.isupper() and isinstance(v, str) and v == k and re.fullmatch(r"[A-Z_]+", v)} - status_and_actions
    node_src = inspect.getsource(N)
    node_codes = set(re.findall(r'"(SCHEMA_INVALID|ALL_SENTENCES_[A-Z_]+)"', node_src))
    assert node_codes == {"SCHEMA_INVALID", "ALL_SENTENCES_FILTERED", "ALL_SENTENCES_DROPPED"}
    missing = (validator_codes | node_codes) - H2_FALLBACK_REASONS
    assert not missing, missing
