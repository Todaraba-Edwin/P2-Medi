"""AG-08(PRD-11-04 A): `/chat` 서비스 집계 L4에 근거 원문 미확보 사유 코드별 개수만 더한다(2026-11-20). LLM·네트워크·DB 0.

- 집계 키는 `label_missing.<코드>`(`ABSENT`·`FETCH_FAIL`·`SEARCH_MISS`·`OUT_OF_SCOPE`)이고 값은 정수 개수뿐이다.
- `NO_EVIDENCE`·목록 밖 값은 세지 않는다. 질문·약 이름·근거 ID·모델 출력은 집계 줄에 없다.
- 미확보가 없는 요청은 키가 생기지 않고, dev 모드 기록기는 집계기를 건드리지 않는다(`h2_fallback`과 같은 규칙, BE-17-10 A).
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.finalize import finalize
from app.api import chat as chat_api
from app.api.stream import _missing_reasons
from app.logging import SpanLogger
from app.logging.spans import LABEL_MISSING_REASONS, Aggregator

MARKER = "비밀질문표지MR4"
DRUG = "미확보시험약정"
KEY_RE = re.compile(r"^label_missing\.(ABSENT|FETCH_FAIL|SEARCH_MISS|OUT_OF_SCOPE)$")


def _items(reasons: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"kind": "label", "status": "FOUND", "subject": [DRUG], "evidence_id": f"label:{i}", "source": "식약처", "as_of": "2026-11-01",
         "flags": [], "matches": [], "dataset_key": "prmsn", "source_kind": "API_DIRECT", "name": DRUG, "missing_reason": r}
        for i, r in enumerate(reasons)]
    out.append({"kind": "label", "status": "NO_EVIDENCE", "subject": ["x"], "evidence_id": "label:ne", "flags": [], "matches": []})
    return out


class FakeRunner:
    """finalize 갱신만 흉내 낸다: 미확보 근거가 든 응답을 낸다."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons

    def updates(self, question: str, profile: Any, confirmed_item_seqs: Any = (), **_: Any) -> Any:  # noqa: ARG002
        yield {"finalize": {"end_reason": "NORMAL", "answer": finalize(_items(self.reasons))}}


def _run(reasons: list[str], mode: str = "service") -> tuple[dict[str, Any] | None, str]:
    out = io.StringIO()
    agg = Aggregator(stream=out)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, FakeRunner(reasons), metrics=SpanLogger(mode=mode, aggregator=agg))
    r = TestClient(app).post("/chat", json={"question": f"{MARKER} {DRUG} 먹어도 되나요?", "context": {}})
    assert r.status_code == 200
    agg.flush()
    text = out.getvalue()
    lines = [json.loads(x) for x in text.splitlines()]
    return (lines[0] if lines else None), text


def _label_counts(line: dict[str, Any]) -> dict[str, int]:
    return {k: v for k, v in line["counts"].items() if k.startswith("label_missing.")}


def test_missing_reason_counts_in_l4_line() -> None:
    line, text = _run(["ABSENT", "FETCH_FAIL", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE"])
    assert line is not None
    counts = _label_counts(line)
    # NO_EVIDENCE는 라벨 미확보 사유 코드가 아니라 세지 않는다
    assert counts == {"label_missing.ABSENT": 1, "label_missing.FETCH_FAIL": 2, "label_missing.SEARCH_MISS": 1,
                      "label_missing.OUT_OF_SCOPE": 1}
    assert all(KEY_RE.match(k) and isinstance(v, int) for k, v in counts.items())
    assert line["counts"].get("node=chat") == 1
    assert MARKER not in text and DRUG not in text and "label:" not in text  # 질문·약 이름·근거 ID 없음


def test_no_missing_reason_no_key() -> None:
    line, _ = _run([])
    assert line is not None and not any(k.startswith("label_missing.") for k in line["counts"])


def test_dev_mode_sink_does_not_aggregate(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path))
    line, _ = _run(["ABSENT"], mode="dev")
    assert line is None


def test_extract_only_label_missing_codes() -> None:
    answer = {"events": [{"rule": "H27", "event": "MISSING_REASON", "code": "ABSENT"},
                         {"rule": "H27", "event": "MISSING_REASON", "code": "NO_EVIDENCE"},
                         {"rule": "H27", "event": "MISSING_REASON", "code": f"{MARKER} 문장"},
                         {"rule": "H27", "event": "OTHER", "code": "FETCH_FAIL"}, "junk", 3,
                         {"rule": "H27", "event": "MISSING_REASON", "code": "OUT_OF_SCOPE"}]}
    assert _missing_reasons(answer) == ["ABSENT", "OUT_OF_SCOPE"]
    assert _missing_reasons(None) == [] and _missing_reasons("x") == [] and _missing_reasons({}) == []
    assert set(LABEL_MISSING_REASONS) == {"ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE"}
