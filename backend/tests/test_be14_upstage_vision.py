"""BE-14 사진 판독 Upstage 제공자(`UpstageVisionClient`, 2026-11-22 사용자 결정) 시험. 실제 네트워크 호출 0(`httpx.MockTransport`·가짜 클라이언트).

범위: OCR → solar-pro4 요청 형식(AG-17과 같은 지시문·스키마·OCR 접두), 응답 → 스키마, 오류 분류, 키 비노출, 환자·병원 칸 버림,
확대 전처리 유지, 비용식, 제공자 선택(기본 upstage, openai 복귀). OpenAI 경로는 `test_be14_ingest_image.py`가 그대로 보존을 확인한다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import chat as chat_api
from app.api import ingest as ingest_api
from app.api import vision
from app.config import Settings
from app.llm.ledger import CostLedger

SECRET = "up_SECRET_KEY_ZZ9"
OCR_TEXT = "OCR글자표지Q1 타이레놀정 500mg"


def _png(w: int = 300, h: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


def _model_json(drugs: list[dict[str, Any]] | None = None) -> str:
    drugs = drugs if drugs is not None else [{"product_name": "타이레놀정", "ingredient_name": None, "strength_or_form": "500mg", "confidence": "high"}]
    return json.dumps({"drugs": drugs, "unreadable_note": None}, ensure_ascii=False)


class Recorder:
    """MockTransport 핸들러. 요청을 기록하고 경로별 응답 목록을 차례로 돌려준다(예외 인스턴스면 올린다)."""

    def __init__(self, ocr: list[Any], chat: list[Any]) -> None:
        self.ocr, self.chat = list(ocr), list(chat)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.ocr if request.url.path.endswith("/document-digitization") else self.chat
        out = queue.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


def _ocr_ok(pages: int = 1) -> httpx.Response:
    return httpx.Response(200, json={"text": OCR_TEXT, "numBilledPages": pages, "pages": []})


def _chat_ok(content: str | None = None, *, finish: str = "stop", pt: int = 1000, ct: int = 100) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content if content is not None else _model_json()}, "finish_reason": finish}],
                                     "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


def _client(rec: Recorder) -> vision.UpstageVisionClient:
    return vision.UpstageVisionClient(SECRET, transport=httpx.MockTransport(rec))


def _extract(rec: Recorder, ledger: CostLedger, data: bytes = PNG, **kw: Any) -> vision.VisionResult:
    return vision.extract(data, client=_client(rec), ledger=ledger, provider="upstage", sleep=lambda _s: None, **kw)


@pytest.fixture
def ledger(tmp_path: Path) -> CostLedger:
    return CostLedger(tmp_path / "ledger.json")


class TestUpstageNormal:
    def test_ocr_then_chat_same_prompt_schema_and_ocr_prefix(self, ledger: CostLedger) -> None:
        rec = Recorder([_ocr_ok()], [_chat_ok()])
        res = _extract(rec, ledger)
        assert res.status == "OK" and res.drugs == [{"product_name": "타이레놀정", "ingredient_name": None, "strength_or_form": "500mg"}]
        ocr_req, chat_req = rec.requests
        assert str(ocr_req.url) == "https://api.upstage.ai/v1/document-digitization"
        assert b'name="model"' in ocr_req.content and b"ocr" in ocr_req.content and b"image/jpeg" in ocr_req.content
        assert str(chat_req.url) == "https://api.upstage.ai/v1/chat/completions"
        body = json.loads(chat_req.content)
        assert body["model"] == "solar-pro4" and body["max_tokens"] == 4000 and "temperature" not in body
        assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "pouch_drugs", "strict": True, "schema": vision.SCHEMA}}
        assert body["messages"][0] == {"role": "system", "content": vision.load_system_prompt()}
        assert body["messages"][1]["content"] == vision.OCR_PREFIX + OCR_TEXT + "\n</ocr>\n" + vision.USER_TEXT
        assert ocr_req.headers["authorization"] == f"Bearer {SECRET}"

    def test_upscale_kept_ocr_gets_1400_long_side_jpeg(self, ledger: CostLedger) -> None:
        rec = Recorder([_ocr_ok()], [_chat_ok()])
        _extract(rec, ledger)
        body = rec.requests[0].content
        start = body.index(b"\xff\xd8\xff")
        im = Image.open(io.BytesIO(body[start:body.index(b"\r\n--", start)]))
        assert im.format == "JPEG" and max(im.size) == 1400

    def test_cost_is_ocr_pages_plus_tokens(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok(2)], [_chat_ok(pt=1000, ct=100)]), ledger)
        assert res.usd == pytest.approx(2 * 0.0015 + 1000 * 0.30 / 1e6 + 100 * 1.20 / 1e6, abs=1e-6)
        assert res.in_tokens == 1000 and res.out_tokens == 100

    def test_worst_cost_formula_and_ledger_guard(self, ledger: CostLedger) -> None:
        sys_prompt = vision.load_system_prompt()
        expected = 0.0015 + (len(sys_prompt) + len(vision.USER_TEXT) + len(vision.OCR_PREFIX) + 6000 + len(json.dumps(vision.SCHEMA)) + 500) * 0.30 / 1e6 \
            + 4000 * 1.20 / 1e6
        assert vision.worst_cost(sys_prompt, 999, "upstage") == pytest.approx(expected)
        assert vision.worst_cost(sys_prompt, 999, "upstage") < 0.02  # 1회 최악 비용은 원장 상한(0.30)에 한참 못 미친다

    def test_ocr_text_truncated_to_6000(self, ledger: CostLedger) -> None:
        big = httpx.Response(200, json={"text": "Z" * 9000, "numBilledPages": 1})
        rec = Recorder([big], [_chat_ok()])
        _extract(rec, ledger)
        user = json.loads(rec.requests[1].content)["messages"][1]["content"]
        assert user.count("Z") == 6000

    def test_structured_400_falls_back_to_prompt_json(self, ledger: CostLedger) -> None:
        rec = Recorder([_ocr_ok()], [httpx.Response(400, json={"error": "x"}), _chat_ok()])
        res = _extract(rec, ledger)
        assert res.status == "OK"
        body = json.loads(rec.requests[2].content)
        assert "response_format" not in body and "JSON 스키마" in body["messages"][0]["content"]


class TestUpstageSanitize:
    def test_patient_hospital_phone_dropped(self, ledger: CostLedger) -> None:
        raw = {"drugs": [{"product_name": "타이레놀정", "ingredient_name": None, "strength_or_form": "500mg", "confidence": "high",
                          "patient_name": "홍길동"},
                         {"product_name": "행복병원", "ingredient_name": "02-123-4567", "strength_or_form": None, "confidence": "low"}],
               "unreadable_note": None, "hospital": "행복병원"}
        res = _extract(Recorder([_ocr_ok()], [_chat_ok(json.dumps(raw, ensure_ascii=False))]), ledger)
        assert res.status == "OK" and len(res.drugs) == 1
        dumped = json.dumps(res.drugs, ensure_ascii=False)
        assert "홍길동" not in dumped and "행복병원" not in dumped and "02-123" not in dumped
        assert "drugs[].patient_name" in res.dropped and "top.hospital" in res.dropped

    def test_bad_json_is_parse_error(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok()], [_chat_ok("이건 JSON이 아니다")]), ledger)
        assert (res.status, res.reason) == ("UNREADABLE", "PARSE_ERROR")

    def test_length_finish_is_parse_error(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok()], [_chat_ok(finish="length")]), ledger)
        assert res.reason == "PARSE_ERROR"

    def test_no_drug_is_none_read(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok()], [_chat_ok(_model_json([]))]), ledger)
        assert (res.status, res.reason) == ("UNREADABLE", "NONE_READ")


class TestUpstageErrors:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_status_retried_twice_then_model_error(self, ledger: CostLedger, status: int) -> None:
        rec = Recorder([httpx.Response(status)] * 3, [])
        res = _extract(rec, ledger)
        assert (res.status, res.reason, res.attempts) == ("UNREADABLE", "MODEL_ERROR", 3) and len(rec.requests) == 3

    def test_transient_then_success(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([httpx.Response(429), _ocr_ok()], [_chat_ok()]), ledger)
        assert res.status == "OK" and res.attempts == 2

    def test_chat_5xx_after_ocr_is_transient(self, ledger: CostLedger) -> None:
        rec = Recorder([_ocr_ok(), _ocr_ok()], [httpx.Response(502), _chat_ok()])
        res = _extract(rec, ledger)
        assert res.status == "OK" and res.attempts == 2

    @pytest.mark.parametrize("status", [401, 403, 422])
    def test_auth_and_client_errors_not_retried(self, ledger: CostLedger, status: int) -> None:
        rec = Recorder([httpx.Response(status, text=f"detail {SECRET}")], [])
        res = _extract(rec, ledger)
        assert (res.status, res.reason, res.attempts) == ("UNREADABLE", "MODEL_ERROR", 1) and len(rec.requests) == 1

    def test_chat_401_not_retried(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok()], [httpx.Response(401)]), ledger)
        assert res.reason == "MODEL_ERROR" and res.attempts == 1

    def test_timeout_and_connect_error_are_transient(self, ledger: CostLedger) -> None:
        rec = Recorder([httpx.ReadTimeout("t"), httpx.ConnectError("c"), _ocr_ok()], [_chat_ok()])
        res = _extract(rec, ledger)
        assert res.status == "OK" and res.attempts == 3

    def test_malformed_chat_response_is_model_error(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([_ocr_ok()], [httpx.Response(200, json={"choices": []})]), ledger)
        assert res.reason == "MODEL_ERROR"

    def test_non_json_ocr_response_is_model_error(self, ledger: CostLedger) -> None:
        res = _extract(Recorder([httpx.Response(200, text="not json")], []), ledger)
        assert res.reason == "MODEL_ERROR"

    def test_error_messages_never_contain_key_or_body(self) -> None:
        rec = Recorder([httpx.Response(401, text=f"leak {SECRET} {OCR_TEXT}")], [])
        data_url = vision.prepare_image(PNG, vision.check_image(PNG))[0]
        with pytest.raises(vision.VisionCallError) as ei:
            _client(rec).complete(model="solar-pro4", messages=vision.build_messages("sys", data_url), max_completion_tokens=10,
                                  response_format=vision.RESPONSE_FORMAT, timeout=5)
        assert SECRET not in str(ei.value) and OCR_TEXT not in str(ei.value) and str(ei.value) == "HTTP 401"

    def test_transport_error_message_is_type_name_only(self) -> None:
        rec = Recorder([httpx.ConnectError(f"boom {SECRET}")], [])
        data_url = vision.prepare_image(PNG, vision.check_image(PNG))[0]
        with pytest.raises(vision.TransientVisionError) as ei:
            _client(rec).complete(model="solar-pro4", messages=vision.build_messages("sys", data_url), max_completion_tokens=10,
                                  response_format=vision.RESPONSE_FORMAT, timeout=5)
        assert str(ei.value) == "ConnectError"

    def test_missing_key_raises_without_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None, upstage_api_key=None))
        with pytest.raises(vision.VisionCallError) as ei:
            vision.UpstageVisionClient()
        assert "UPSTAGE_API_KEY" in str(ei.value)

    def test_missing_key_via_extract_is_model_error(self, ledger: CostLedger, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None, upstage_api_key=None))
        res = vision.extract(PNG, client=lambda: vision.make_client("upstage"), ledger=ledger, provider="upstage", sleep=lambda _s: None)
        assert (res.status, res.reason) == ("UNREADABLE", "MODEL_ERROR")

    def test_cap_reached_blocks_without_any_call(self, tmp_path: Path) -> None:
        led = CostLedger(tmp_path / "l.json", bucket_caps={"vision": 0.001})
        rec = Recorder([], [])
        res = _extract(rec, led)
        assert res.reason == "CAP_REACHED" and rec.requests == []


class TestKeyNotLogged:
    def test_key_not_in_result_or_logs(self, ledger: CostLedger, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("DEBUG"):
            res = _extract(Recorder([_ocr_ok()], [_chat_ok()]), ledger)
        assert SECRET not in repr(res) and SECRET not in caplog.text and OCR_TEXT not in caplog.text


class _Echo:
    """제공자 선택 시험용: 어떤 모델·제공자로 불렸는지 기록하는 가짜."""

    def __init__(self, provider: str | None) -> None:
        if provider is not None:
            self.provider = provider
        self.models: list[str] = []

    def complete(self, **kw: Any) -> vision.Completion:
        self.models.append(kw["model"])
        return vision.Completion(content=_model_json(), refusal=None, finish_reason="stop", prompt_tokens=10, completion_tokens=10)


def _app(client: Any, ledger: Any) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    ingest_api.register(app)
    ingest_api.set_vision(app, client=client, ledger=ledger)
    return TestClient(app)


def _post(c: TestClient) -> Any:
    import base64

    return c.post("/ingest/image", json={"image": "data:image/png;base64," + base64.b64encode(PNG).decode()})


class TestProviderSelection:
    def test_settings_default_follows_constant_and_is_openai_now(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MEDIAGENT_VISION_PROVIDER", raising=False)
        from app.config import DEFAULT_VISION_PROVIDER

        assert DEFAULT_VISION_PROVIDER == "openai"  # 전환 결정(약관 v4·사진 고지 승인 뒤) 때 상수와 이 줄만 고친다
        assert Settings(_env_file=None).mediagent_vision_provider == DEFAULT_VISION_PROVIDER
        assert Settings(_env_file=None, mediagent_vision_provider="upstage").mediagent_vision_provider == "upstage"
        assert Settings(_env_file=None, mediagent_vision_provider="openai").mediagent_vision_provider == "openai"
        with pytest.raises(ValueError):
            Settings(_env_file=None, mediagent_vision_provider="other")

    def test_env_name_selects_upstage_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEDIAGENT_VISION_PROVIDER", "upstage")
        assert Settings(_env_file=None).mediagent_vision_provider == "upstage"
        monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None, upstage_api_key=SECRET))
        assert ingest_api._provider_name() == "upstage"
        assert isinstance(vision.make_client(ingest_api._provider_name()), vision.UpstageVisionClient)

    def test_unreadable_settings_fall_back_to_default_constant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import DEFAULT_VISION_PROVIDER

        def boom() -> Settings:
            raise RuntimeError("x")

        monkeypatch.setattr("app.config.get_settings", boom)
        assert ingest_api._provider_name() == DEFAULT_VISION_PROVIDER

    def test_make_client_by_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None, upstage_api_key=SECRET, openai_api_key="sk-x"))
        assert isinstance(vision.make_client("upstage"), vision.UpstageVisionClient)
        assert isinstance(vision.make_client("openai"), vision.OpenAIVisionClient)

    def test_ingest_upstage_client_uses_solar_model_name(self, ledger: CostLedger) -> None:
        cl = _Echo("upstage")
        assert _post(_app(cl, ledger)).status_code == 200 and cl.models == ["solar-pro4"]

    def test_ingest_injected_without_provider_stays_openai(self, ledger: CostLedger) -> None:
        cl = _Echo(None)
        assert _post(_app(cl, ledger)).status_code == 200 and cl.models == ["gpt-6-luna"]

    def test_ingest_lazy_client_follows_setting(self, ledger: CostLedger, monkeypatch: pytest.MonkeyPatch) -> None:
        made: list[str] = []
        monkeypatch.setattr(vision, "make_client", lambda name: made.append(name) or _Echo(name))
        for name in ("upstage", "openai"):
            monkeypatch.setattr("app.config.get_settings", lambda n=name: Settings(_env_file=None, mediagent_vision_provider=n))
            assert _post(_app(None, ledger)).status_code == 200
        assert made == ["upstage", "openai"]

    def test_response_has_no_provider_field(self, ledger: CostLedger) -> None:
        r = _post(_app(_Echo("upstage"), ledger))
        assert "provider" not in r.json() and "solar" not in r.text
