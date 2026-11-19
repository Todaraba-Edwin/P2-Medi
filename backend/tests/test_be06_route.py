"""BE-06 `POST /chat` 라우트 선언 시험(그래프 연결 전, 외부 호출 0).

- 의도된 상태 501(그래프 연결은 선행 AG-05~09 뒤), 형식 오류 422와 오류 본문(입력 값을 되돌려 주지 않음)
- 질문·대화 상태 비로깅(요청 본문 로깅 미들웨어 없음), `/openapi.json` 모델 노출, `scripts/export_openapi.py` 출력
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.request import CONFIRMED_DRUGS_MAX, DRUG_NAME_MAX_CHARS, QUESTION_MAX_CHARS
from app.main import app

client = TestClient(app)
MARKER = "비밀질문표지QX7"  # 로그·응답에 나오면 안 되는 질문 글자
BACKEND = Path(__file__).resolve().parents[1]


def test_chat_is_intentionally_not_implemented():
    r = client.post("/chat", json={"question": f"{MARKER} 타이레놀 임신 중에 괜찮아?"})
    assert r.status_code == 501 and r.headers["content-type"].startswith("application/json")
    assert r.json() == {"code": "NOT_IMPLEMENTED", "fields": []}
    assert MARKER not in r.text


def test_full_request_with_context_is_accepted_shape():
    body = {"question": "이거 같이 먹어도 돼?", "context": {"age": {"lower": 6, "upper": 11, "unit": "세"}, "pregnant": False,
                                                          "confirmed_drugs": [{"name": "타이레놀정500밀리그람", "item_seq": "202106954"}]}}
    assert client.post("/chat", json=body).status_code == 501  # 형식 통과(구현 전)
    assert client.post("/chat", json={"question": "가" * QUESTION_MAX_CHARS}).status_code == 501  # 상한 그대로는 통과


@pytest.mark.parametrize("drug", [
    {"name": "타이레놀정500밀리그람", "item_seq": "202106092"},  # input_name 없음(이전 요청 그대로)
    {"name": "타이레놀정500밀리그람", "item_seq": "202106092", "input_name": "타이레놀"},  # FE-09-05 A
    {"name": "타이레놀정500밀리그람", "item_seq": "202106092", "input_name": None},
    {"name": "타이레놀정500밀리그람", "item_seq": "202106092", "input_name": "가" * DRUG_NAME_MAX_CHARS},  # 상한 그대로는 통과
])
def test_confirmed_drug_input_name_is_optional(drug):
    assert client.post("/chat", json={"question": "x", "context": {"confirmed_drugs": [drug]}}).status_code == 501  # 형식 통과


@pytest.mark.parametrize("body,field", [
    ({"question": ""}, "question"),
    ({"question": "   \n "}, "question"),
    ({"question": MARKER * (QUESTION_MAX_CHARS // len(MARKER) + 1)}, "question"),
    ({}, "question"),
    ({"question": "x", "history": [MARKER]}, "body"),  # 모르는 칸(사용자 키 이름은 싣지 않는다)
    ({"question": "x", "context": {"age": {"lower": 12, "upper": 6}}}, "context.age"),
    ({"question": "x", "context": {"age": {"lower": 1, "upper": 2, "unit": "년"}}}, "context.age.unit"),
    ({"question": "x", "context": {"confirmed_drugs": [{"name": MARKER, "item_seq": "12"}]}}, "context.confirmed_drugs.0.item_seq"),
    ({"question": "x", "context": {"confirmed_drugs": [{"name": "a"}] * (CONFIRMED_DRUGS_MAX + 1)}}, "context.confirmed_drugs"),
    ({"question": "x", "context": {"confirmed_drugs": [{"name": "a", "input_name": MARKER * (DRUG_NAME_MAX_CHARS // len(MARKER) + 1)}]}},
     "context.confirmed_drugs.0.input_name"),  # 길이 초과(FE-09-05 A, `name`과 같은 상한)
    ({"question": "x", "context": {"confirmed_drugs": [{"name": "a", "input_name": "   "}]}}, "context.confirmed_drugs.0.input_name"),
    ({"question": "x", "context": {"confirmed_drugs": [{"name": "a", "input_name": ""}]}}, "context.confirmed_drugs.0.input_name"),
])
def test_bad_requests_are_422_without_echoing_input(body, field):
    r = client.post("/chat", json=body)
    assert r.status_code == 422
    js = r.json()
    assert js["code"] == "INVALID_REQUEST" and field in js["fields"]
    # pydantic 오류 항목의 `"input"` 키(입력 값 되돌림)가 없다. 칸 이름 `input_name`(FE-09-05 A)은 `fields`에 나올 수 있어 키 모양으로 본다
    assert set(js) == {"code", "fields"} and MARKER not in r.text and '"input"' not in r.text
    assert all("input" not in f or f.endswith(".input_name") for f in js["fields"])


def test_malformed_json_is_422():
    r = client.post("/chat", content=f'{{"question": "{MARKER}"'.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json() == {"code": "INVALID_REQUEST", "fields": ["body"]} and MARKER not in r.text


def test_question_and_context_are_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    body = {"question": f"{MARKER} 먹어도 돼?", "context": {"pregnant": True, "confirmed_drugs": [{"name": f"{MARKER}정"}]}}
    client.post("/chat", json=body)
    client.post("/chat", json={**body, "question": ""})
    logged = "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
    assert MARKER not in logged
    assert app.user_middleware == []  # 요청 본문을 로깅하는 미들웨어 없음(CORS도 없음: 프런트는 rewrites 프록시, FE-01-06 A)


def test_openapi_exposes_contract_models():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    comps = spec["components"]["schemas"]
    for name in ("ChatRequest", "ConversationContext", "AgeInput", "ConfirmedDrug", "ChatResponse", "ChatEvent", "ProgressEvent",
                 "EmergencyEvent", "AnswerEvent", "ErrorEvent", "DoneEvent", "DateLine", "Citation", "Finding", "Badge", "Candidate",
                 "DetailItem", "Emergency", "ErrorBody"):
        assert name in comps, name
    op = spec["paths"]["/chat"]["post"]
    assert op["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ChatRequest"}
    assert op["responses"]["200"]["content"] == {"application/x-ndjson": {"schema": {"$ref": "#/components/schemas/ChatEvent"}}}
    for code in ("422", "501"):
        assert op["responses"][code]["content"] == {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}}
    ce = comps["ChatEvent"]
    assert ce["discriminator"]["propertyName"] == "type" and len(ce["oneOf"]) == 5
    assert comps["ProgressEvent"]["properties"]["label"]["type"] == "string"
    assert comps["ChatResponse"]["properties"]["schema_version"]["const"] == "chat_response@v1"
    assert "badges" not in comps["ChatResponse"]["properties"] and "candidates" in comps["ChatResponse"]["properties"]


def _export_module():
    spec = importlib.util.spec_from_file_location("export_openapi", BACKEND / "scripts" / "export_openapi.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_export_openapi_script_writes_valid_json(tmp_path, capsys):
    mod = _export_module()
    out = tmp_path / "sub" / "openapi.json"
    assert mod.main(["-o", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(app.openapi()))
    assert mod.main([]) == 0  # 기본: 표준 출력
    assert json.loads(capsys.readouterr().out) == written
