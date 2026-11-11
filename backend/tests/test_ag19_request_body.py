"""AG-19 ① 요청 본문 확인: LangChain `ChatOpenAI`가 Chat Completions 본문에 `reasoning_effort`·`parallel_tool_calls`·`tools`·`response_format`을
실제로 싣는지 `httpx.MockTransport`로 캡처해 본다(외부 호출 0, 응답은 가짜)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agent.answer_schema import parse_draft
from app.agent.llm import (
    LedgerCallback,
    answer_draft_json_schema,
    bind_tools_model,
    estimate_cost_usd,
    make_chat_model,
    summary_model,
)
from app.agent.tools.context import ToolContext
from app.agent.tools.langchain_adapter import build_tools
from app.agent.tools.registry import REGISTRY
from app.config import Settings
from app.llm.ledger import BudgetExceeded, CostLedger

KEY = "sk-test-NOT-A-REAL-KEY-0000"


def _resp(message: dict[str, Any]) -> dict[str, Any]:
    return {"id": "chatcmpl-x", "object": "chat.completion", "created": 1, "model": "gpt-6-luna",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


TOOL_RESP = _resp({"content": None, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "identify_drug", "arguments": json.dumps({"name": "가상정"})}},
    {"id": "call_2", "type": "function", "function": {"name": "identify_drug", "arguments": json.dumps({"name": "다른정"})}}]})
DRAFT_RESP = _resp({"content": json.dumps({"sentences": [{"text": "확인하지 못했어요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}]})})


class Capture:
    def __init__(self, response: dict[str, Any]) -> None:
        self.reqs: list[tuple[str, dict[str, Any]]] = []
        self.response = response

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            self.reqs.append((str(req.url), json.loads(req.content)))
            return httpx.Response(200, json=self.response)
        return httpx.Client(transport=httpx.MockTransport(handler))

    @property
    def last(self) -> tuple[str, dict[str, Any]]:
        return self.reqs[-1]


@pytest.fixture
def tools():
    return build_tools(ToolContext(drug_dict=None))  # type: ignore[arg-type]


def _model(cap: Capture, **kw: Any):
    return make_chat_model(Settings(openai_api_key=KEY), http_client=cap.client(), **kw)


@pytest.mark.parametrize("parallel", [True, False])
def test_tools_body_has_reasoning_none_parallel_and_tools(tools, parallel):
    cap = Capture(TOOL_RESP)
    out = bind_tools_model(_model(cap), tools, parallel=parallel).invoke("질문")
    url, body = cap.last
    assert url == "https://api.openai.com/v1/chat/completions"  # Responses API(/v1/responses)로 새지 않는다
    assert body["reasoning_effort"] == "none" and body["parallel_tool_calls"] is parallel and body["model"] == "gpt-6-luna"
    assert [t["function"]["name"] for t in body["tools"]] == list(REGISTRY)
    assert all(t["type"] == "function" for t in body["tools"])
    assert "response_format" not in body and "input" not in body and "previous_response_id" not in body  # 도구 호출에 구조화 출력을 섞지 않는다
    # 응답 파싱: 도구 호출 2개
    assert [(c["name"], c["args"]) for c in out.tool_calls] == [("identify_drug", {"name": "가상정"}), ("identify_drug", {"name": "다른정"})]


def test_default_bind_omits_parallel_flag(tools):
    cap = Capture(TOOL_RESP)
    _model(cap).bind_tools(tools).invoke("질문")
    body = cap.last[1]
    assert "parallel_tool_calls" not in body and body["reasoning_effort"] == "none"


def test_tool_schemas_carry_arg_models(tools):
    cap = Capture(TOOL_RESP)
    bind_tools_model(_model(cap), tools).invoke("질문")
    by = {t["function"]["name"]: t["function"] for t in cap.last[1]["tools"]}
    assert "name" in by["identify_drug"]["parameters"]["properties"]
    assert "drugs" in by["check_contraindications"]["parameters"]["properties"]
    assert by["get_label_section"]["parameters"]["properties"]["section"]


def test_structured_summary_body_strict_without_tools():
    cap = Capture(DRAFT_RESP)
    raw = summary_model(_model(cap, purpose="summary")).invoke("요약해 줘")
    url, body = cap.last
    assert url.endswith("/v1/chat/completions") and body["reasoning_effort"] == "none"
    assert "tools" not in body and "parallel_tool_calls" not in body  # 구조화 호출에는 도구를 묶지 않는다
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True and rf["json_schema"]["name"] == "answer_draft"

    def check(node: Any) -> None:  # strict 변환 규칙: 모든 객체 additionalProperties=false·전부 required, 길이·범위 키워드 없음
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            assert not ({"minLength", "maxLength", "minimum", "default", "$ref"} & set(node))
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    check(rf["json_schema"]["schema"])
    draft, err = parse_draft(raw)  # 받은 뒤 AnswerDraft로 다시 검증
    assert err is None and draft is not None and draft.sentences[0].claim_type == "guidance"


def test_schema_helper_matches_answer_draft_fields():
    s = answer_draft_json_schema()["schema"]
    item = s["properties"]["sentences"]["items"]
    assert set(item["properties"]) == {"text", "evidence_ids", "claim_type", "citations"}
    assert item["properties"]["claim_type"]["enum"] == ["fact", "conclusion", "guidance"]


def test_model_uses_chat_completions_and_hides_key():
    m = make_chat_model(Settings(openai_api_key=KEY))
    assert m.use_responses_api is False and m.reasoning_effort == "none" and m.max_retries == 0
    assert KEY not in repr(m) and KEY not in str(m)


def test_bad_purpose_rejected():
    with pytest.raises(ValueError):
        make_chat_model(Settings(openai_api_key=KEY), purpose="both")  # type: ignore[arg-type]


def test_missing_key_builds_without_leaking_and_without_call():
    m = make_chat_model(Settings(openai_api_key=None))
    assert m.reasoning_effort == "none"  # 만들기만 한다. 호출은 하지 않는다


def test_ledger_callback_records_cost_and_guards(tmp_path, tools):
    ledger = CostLedger(tmp_path / "led.json", cap_usd=1.0)
    cb = LedgerCallback(ledger)
    cap = Capture(TOOL_RESP)
    bind_tools_model(_model(cap, callbacks=[cb]), tools).invoke("질문")
    assert cb.calls == 1 and ledger.spent("dev") == pytest.approx(estimate_cost_usd(100, 20))
    # 상한을 넘기는 호출은 요청 전에 막힌다(요청이 나가지 않는다)
    tight = CostLedger(tmp_path / "tight.json", cap_usd=0.0001)
    cap2 = Capture(TOOL_RESP)
    with pytest.raises(BudgetExceeded):
        bind_tools_model(_model(cap2, callbacks=[LedgerCallback(tight)]), tools).invoke("질문")
    assert cap2.reqs == []
