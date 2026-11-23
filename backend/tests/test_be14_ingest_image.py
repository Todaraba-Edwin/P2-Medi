"""BE-14 사진 약 이름 추출 API(`POST /ingest/image`, `app.api.vision`) 시험(2026-11-22). OpenAI·네트워크·DB 호출 0.

- 비전 클라이언트는 가짜(`FakeClient`)만, 이미지는 시험 안에서 Pillow로 만든 글자 없는 단색 PNG·JPEG만 쓴다(실제 약봉투 사진 없음).
- 사전은 합성 사전(`golden_dict`, 실제 제품 정보 아님). 원장은 `tmp_path`의 파일 또는 메모리 가짜.
- 확인: 허용 칸만·확신도 없음·후보 ≤5·기본 선택 없음, 환자 정보·색/모양 버림, 읽지 못함 4종, 422 3종, 확대 전처리·파일 0,
  로그 비저장, 응급 같은 함수, H19(import·호출 0), 비용 상한, 계약(판정 칸 없음, `/chat` OpenAPI 불변), AG-17 조건과 같은 지시문·스키마.
"""

from __future__ import annotations

import ast
import base64
import io
import json
import logging
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_COLD, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.guardrail import detect_emergency  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import drugs as drugs_api  # noqa: E402
from app.api import ingest as ingest_api  # noqa: E402
from app.api import me as me_api  # noqa: E402
from app.api import vision  # noqa: E402
from app.llm.ledger import BUCKETS, DEV_CAP_USD, VISION_CAP_USD, BudgetExceeded, CostLedger  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
REF = REPO / "evaluation" / "mock_gen" / "vision_pouch_test.py"
NAME_MARK = "타이레놀콜드-에스정"  # 합성 사전에 있는 이름(실제 제품 정보 아님)
Q_MARK = "질문표지QZ7 이 약 같이 먹어도 되나요"
Q_EMERGENCY = "아이가 약을 많이 삼켰어요"


# ---------------------------------------------------------------- 도우미
def _img_bytes(w: int, h: int, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (210, 205, 200)).save(buf, format=fmt)
    return buf.getvalue()


def _data_url(data: bytes, media: str = "image/png") -> str:
    return f"data:{media};base64,{base64.b64encode(data).decode()}"


PNG = _img_bytes(600, 400)
JPEG = _img_bytes(800, 600, "JPEG")


def _png_with_size(w: int, h: int) -> bytes:
    """IHDR 크기만 바꾼 PNG(픽셀 상한 시험용, 실제 픽셀을 만들지 않는다). CRC를 다시 계산한다."""
    raw = _img_bytes(2, 2)
    ihdr_at = 8
    length = struct.unpack(">I", raw[ihdr_at:ihdr_at + 4])[0]
    body = bytearray(raw[ihdr_at + 8: ihdr_at + 8 + length])
    body[0:8] = struct.pack(">II", w, h)
    crc = struct.pack(">I", zlib.crc32(b"IHDR" + bytes(body)) & 0xFFFFFFFF)
    return raw[:ihdr_at + 8] + bytes(body) + crc + raw[ihdr_at + 12 + length:]


def _comp(obj: Any = None, *, content: str | None = None, refusal: str | None = None, finish: str = "stop") -> vision.Completion:
    text = content if content is not None else json.dumps(obj, ensure_ascii=False)
    return vision.Completion(content=text, refusal=refusal, finish_reason=finish, prompt_tokens=2500, completion_tokens=300)


def _drug(product: str | None = NAME_MARK, ingredient: str | None = None, sf: str | None = "500mg", conf: str = "high") -> dict:
    return {"product_name": product, "ingredient_name": ingredient, "strength_or_form": sf, "confidence": conf}


class FakeClient:
    def __init__(self, *outputs: Any) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kw: Any) -> vision.Completion:
        self.calls.append(kw)
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class MemLedger:
    """파일을 쓰지 않는 원장(파일 생성 0 시험용)."""

    def __init__(self, cap_reached: bool = False) -> None:
        self.cap_reached = cap_reached
        self.added: list[tuple[float, str]] = []
        self.guarded: list[tuple[float, str]] = []

    def guard(self, estimated_usd: float = 0.0, bucket: str = "dev") -> None:
        self.guarded.append((estimated_usd, bucket))
        if self.cap_reached:
            raise BudgetExceeded("cap")

    def add(self, cost_usd: float, bucket: str = "dev") -> float:
        self.added.append((cost_usd, bucket))
        return cost_usd


def _app(client: Any, ledger: Any, provider: Any = golden_dict) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    drugs_api.register(app)
    ingest_api.register(app)
    drugs_api.set_provider(app, provider)
    ingest_api.set_vision(app, client=client, ledger=ledger)
    return TestClient(app)


def _post(c: TestClient, image: str = _data_url(PNG), question: str | None = None) -> Any:
    body: dict[str, Any] = {"image": image}
    if question is not None:
        body["question"] = question
    return c.post("/ingest/image", json=body)


@pytest.fixture
def ledger(tmp_path: Path) -> CostLedger:
    return CostLedger(tmp_path / "ledger.json")


# ---------------------------------------------------------------- 정상·정리
class TestNormal:
    def test_allowed_fields_only_no_confidence_candidates_le5_no_default_selection(self, ledger: CostLedger) -> None:
        fake = FakeClient(_comp({"drugs": [_drug(), _drug("타이레놀", None, "정")], "unreadable_note": None}))
        r = _post(_app(fake, ledger))
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert set(body) == {"status", "reason", "drugs", "emergency", "dict_unavailable", "dict_version"}
        assert body["status"] == "OK" and body["reason"] is None and body["emergency"] is None
        assert body["dict_unavailable"] is False and body["dict_version"] == "golden-synth-v1"
        assert len(body["drugs"]) == 2
        for d in body["drugs"]:
            assert set(d) == {"read_name", "read_ingredient", "strength_or_form", "candidates"}  # confidence·selected 없음
            assert len(d["candidates"]) <= 5
            for cand in d["candidates"]:
                assert set(cand) == {"name", "item_seq", "entp_name", "prescription", "matched_by", "match_type"}
        first = body["drugs"][0]
        assert first["read_name"] == NAME_MARK and first["strength_or_form"] == "500mg"
        assert first["candidates"][0]["item_seq"] == SEQ_COLD
        assert "confidence" not in r.text and "selected" not in r.text

    def test_one_call_with_same_model_schema_and_no_temperature(self, ledger: CostLedger) -> None:
        fake = FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None}))
        _post(_app(fake, ledger))
        assert len(fake.calls) == 1
        kw = fake.calls[0]
        assert kw["model"] == "gpt-6-luna" and "temperature" not in kw and kw["max_completion_tokens"] == 4000
        assert kw["response_format"] == {"type": "json_schema", "json_schema": {"name": "pouch_drugs", "strict": True, "schema": vision.SCHEMA}}
        user = kw["messages"][1]["content"]
        assert user[0]["type"] == "image_url" and user[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert kw["messages"][0]["content"] == vision.load_system_prompt()

    def test_ingredient_only_item_uses_ingredient_for_candidates(self, ledger: CostLedger) -> None:
        fake = FakeClient(_comp({"drugs": [_drug(None, "아세트아미노펜", None)], "unreadable_note": None}))
        d = _post(_app(fake, ledger)).json()["drugs"][0]
        assert d["read_name"] is None and d["read_ingredient"] == "아세트아미노펜"
        assert d["candidates"] and d["candidates"][0]["matched_by"] == "ingredient_name"

    def test_no_dictionary_provider_gives_empty_candidates_not_error(self, ledger: CostLedger) -> None:
        fake = FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None}))
        body = _post(_app(fake, ledger, provider=None)).json()
        assert body["status"] == "OK" and body["dict_unavailable"] is True and body["drugs"][0]["candidates"] == []

    def test_dictionary_load_failure_gives_empty_candidates(self, ledger: CostLedger) -> None:
        def broken() -> Any:
            raise RuntimeError("load failed")

        body = _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger, provider=broken)).json()
        assert body["status"] == "OK" and body["dict_unavailable"] is True and body["drugs"][0]["candidates"] == []

    def test_at_most_ten_items_and_80_chars(self) -> None:
        drugs, _ = vision.sanitize({"drugs": [_drug("가" * 200)] * 15, "unreadable_note": None})
        assert len(drugs) == 10 and all(len(d["product_name"] or "") == 80 for d in drugs)

    def test_question_not_echoed(self, ledger: CostLedger) -> None:
        r = _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger), question=Q_MARK)
        assert "질문표지QZ7" not in r.text


class TestSanitize:
    def test_patient_hospital_phone_pharmacy_values_dropped(self) -> None:
        raw = {"drugs": [
            {**_drug(), "patient_name": "홍길동", "hospital": "○○내과의원", "phone": "02-123-4567"},
            _drug("○○약국", None, None),
            _drug("02-555-1234", None, None),
            _drug("환자 성명 김", None, None),
            _drug(NAME_MARK, "서울병원", "500mg"),
        ], "unreadable_note": "약국 전화 02-111-2222", "patient": "홍길동"}
        drugs, dropped = vision.sanitize(raw)
        text = json.dumps(drugs, ensure_ascii=False)
        for bad in ("홍길동", "의원", "약국", "02-", "환자", "병원"):
            assert bad not in text
        assert [d["product_name"] for d in drugs] == [NAME_MARK, NAME_MARK]
        assert drugs[1]["ingredient_name"] is None  # 병원 이름이 성분 칸에 들어온 값만 버림
        assert all(set(d) == {"product_name", "ingredient_name", "strength_or_form"} for d in drugs)
        assert "drugs[].patient_name" in dropped and "top.patient" in dropped and "drugs[].<no-name>" in dropped
        assert not any("홍길동" in x for x in dropped)  # 버린 목록에는 이름만, 값 없음

    def test_patient_fields_dropped_end_to_end(self, ledger: CostLedger) -> None:
        raw = {"drugs": [{**_drug(), "patient_name": "홍길동", "hospital": "○○내과의원", "pharmacy": "○○약국", "tel": "010-1234-5678"}],
               "unreadable_note": None}
        r = _post(_app(FakeClient(_comp(raw)), ledger))
        for bad in ("홍길동", "내과의원", "약국", "010-1234-5678", "patient", "hospital", "pharmacy"):
            assert bad not in r.text

    @pytest.mark.parametrize("sf", ["흰색 원형", "노란색 장방형", "1일 3회", "해열진통제"])
    def test_color_shape_or_non_strength_dropped(self, sf: str) -> None:
        drugs, dropped = vision.sanitize({"drugs": [_drug(sf=sf)], "unreadable_note": None})
        assert drugs[0]["strength_or_form"] is None and "drugs[].strength_or_form:off_field" in dropped

    @pytest.mark.parametrize("sf", ["500mg", "500 mg", "필름코팅정", "10㎎", "시럽", "0.5%"])
    def test_strength_or_form_kept(self, sf: str) -> None:
        drugs, _ = vision.sanitize({"drugs": [_drug(sf=sf)], "unreadable_note": None})
        assert drugs[0]["strength_or_form"] == sf


# ---------------------------------------------------------------- 읽지 못함
class TestUnreadable:
    @pytest.mark.parametrize(("output", "reason"), [
        (_comp({"drugs": [], "unreadable_note": "흐림"}), "NONE_READ"),
        (_comp({"drugs": [_drug(None, None, "500mg")], "unreadable_note": None}), "NONE_READ"),
        (_comp(content="", refusal="I can't help with that."), "REFUSED"),
        (_comp(content='{"drugs": [{"product_name": "타이레'), "PARSE_ERROR"),
        (_comp(content='{"drugs": [], "unreadable_note": null}', finish="length"), "PARSE_ERROR"),
        (RuntimeError("boom"), "MODEL_ERROR"),
    ], ids=["zero", "no-name", "refusal", "truncated-json", "length", "exception"])
    def test_200_unreadable_with_reason(self, ledger: CostLedger, output: Any, reason: str) -> None:
        r = _post(_app(FakeClient(output), ledger))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "UNREADABLE" and body["reason"] == reason and body["drugs"] == []

    def test_transient_errors_retry_twice_then_model_error(self, ledger: CostLedger) -> None:
        fake = FakeClient(*[vision.TransientVisionError("RateLimitError")] * 3)
        res = vision.extract(PNG, client=fake, ledger=ledger, sleep=lambda _s: None)
        assert res.status == "UNREADABLE" and res.reason == "MODEL_ERROR" and len(fake.calls) == 3 and res.attempts == 3

    def test_transient_error_then_success(self, ledger: CostLedger) -> None:
        fake = FakeClient(vision.TransientVisionError("APIConnectionError"), _comp({"drugs": [_drug()], "unreadable_note": None}))
        res = vision.extract(PNG, client=fake, ledger=ledger, sleep=lambda _s: None)
        assert res.status == "OK" and res.attempts == 2

    def test_client_construction_failure_is_model_error(self, ledger: CostLedger) -> None:
        def no_client() -> Any:
            raise RuntimeError("no key")

        res = vision.extract(PNG, client=no_client, ledger=ledger)
        assert res.status == "UNREADABLE" and res.reason == "MODEL_ERROR"


# ---------------------------------------------------------------- 요청 검사(422)
class TestRequestValidation:
    def _assert_422_image(self, r: Any) -> None:
        assert r.status_code == 422 and r.json() == {"code": "INVALID_REQUEST", "fields": ["image"]}
        assert r.headers["cache-control"] == "no-store"

    def test_gif_magic_rejected(self, ledger: CostLedger) -> None:
        fake = FakeClient()
        gif = b"GIF89a" + b"\x00" * 64
        self._assert_422_image(_post(_app(fake, ledger), _data_url(gif, "image/png")))
        self._assert_422_image(_post(_app(fake, ledger), _data_url(gif, "image/gif")))
        assert fake.calls == []

    def test_over_8mb_rejected(self, ledger: CostLedger) -> None:
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (vision.MAX_IMAGE_BYTES + 1)
        self._assert_422_image(_post(_app(FakeClient(), ledger), _data_url(big)))
        with pytest.raises(vision.InvalidImage):
            vision.check_image(big)

    def test_pixel_cap_rejected_without_decoding(self, ledger: CostLedger) -> None:
        huge = _png_with_size(8000, 6000)  # 4800만 > 4000만
        with Image.open(io.BytesIO(huge)) as im:
            assert im.size == (8000, 6000)
        self._assert_422_image(_post(_app(FakeClient(), ledger), _data_url(huge)))
        assert vision.check_image(_png_with_size(6000, 6000)).width == 6000  # 3600만은 통과(머리만 봄)

    @pytest.mark.parametrize("image", ["not-a-data-url", "data:image/png;base64,@@@@", "data:image/png;base64,", "data:text/plain;base64,aGk="])
    def test_bad_data_url_rejected(self, ledger: CostLedger, image: str) -> None:
        self._assert_422_image(_post(_app(FakeClient(), ledger), image))

    def test_mismatched_magic_and_payload_rejected(self, ledger: CostLedger) -> None:
        fake_jpeg = b"\xff\xd8\xff" + b"\x00" * 100  # 머리는 JPEG지만 열 수 없음
        self._assert_422_image(_post(_app(FakeClient(), ledger), _data_url(fake_jpeg, "image/jpeg")))

    def test_question_over_500_rejected(self, ledger: CostLedger) -> None:
        r = _post(_app(FakeClient(), ledger), question="가" * 501)
        assert r.status_code == 422 and r.json() == {"code": "INVALID_REQUEST", "fields": ["question"]}

    def test_unknown_field_rejected_without_echo(self, ledger: CostLedger) -> None:
        r = _app(FakeClient(), ledger).post("/ingest/image", json={"image": _data_url(PNG), "patient": "홍길동"})
        assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST" and "홍길동" not in r.text

    def test_jpeg_accepted(self, ledger: CostLedger) -> None:
        r = _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger), _data_url(JPEG, "image/jpeg"))
        assert r.status_code == 200 and r.json()["status"] == "OK"


# ---------------------------------------------------------------- 전처리·파일 0
_audit_log: list[str] = []
_audit_on = False
_AUDIT_PREFIXES = ("open", "os.", "shutil.", "tempfile.", "socket.", "sqlite3.", "subprocess.")


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if _audit_on and event.startswith(_AUDIT_PREFIXES):
        _audit_log.append(event)


sys.addaudithook(_audit_hook)  # 지울 수 없어서 `_audit_on`으로 창을 연다


def _io_events(fn: Any) -> list[str]:
    global _audit_on
    _audit_log.clear()
    _audit_on = True
    try:
        fn()
    finally:
        _audit_on = False
    return list(_audit_log)


def _decoded_size(data_url: str) -> tuple[int, int]:
    raw = base64.b64decode(data_url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as im:
        assert im.format == "JPEG"
        return im.size


class TestPreprocess:
    @pytest.mark.parametrize(("w", "h", "expected"), [(600, 400, (1400, 933)), (3000, 2000, (1400, 933)), (400, 600, (933, 1400))])
    def test_long_side_1400(self, w: int, h: int, expected: tuple[int, int]) -> None:
        data = _img_bytes(w, h)
        url, tok = vision.prepare_image(data, vision.check_image(data), resize=True)
        assert _decoded_size(url) == expected and tok == int(expected[0] * expected[1] / 750) + 1

    def test_resize_false_sends_original_bytes(self) -> None:
        url, _ = vision.prepare_image(PNG, vision.check_image(PNG), resize=False)
        assert url == _data_url(PNG)

    def test_audit_hook_detects_file_access(self, tmp_path: Path) -> None:
        assert "open" in _io_events(lambda: (tmp_path / "probe.txt").write_text("x", encoding="utf-8"))

    def test_no_file_created_during_extract(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        out = _comp({"drugs": [_drug()], "unreadable_note": None})
        vision.extract(_img_bytes(3000, 2000, "JPEG"), client=FakeClient(out), ledger=MemLedger())  # 지연 import·지시문 읽기를 창 밖에서 한 번
        big = _img_bytes(3000, 2000, "JPEG")
        events = _io_events(lambda: vision.extract(big, client=FakeClient(out), ledger=MemLedger()))
        assert events == []
        events = _io_events(lambda: vision.extract(PNG, client=FakeClient(out), ledger=MemLedger()))
        assert events == []
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- 비저장(로그)
class TestNoStorageInLogs:
    def test_logs_have_no_image_name_question_or_output(self, ledger: CostLedger, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        out = _comp({"drugs": [_drug(), _drug(None, "아세트아미노펜", "정")], "unreadable_note": "일부 흐림"})
        r = _post(_app(FakeClient(out), ledger), question=Q_MARK)
        assert r.status_code == 200 and r.json()["status"] == "OK"
        text = caplog.text + " ".join(str(rec.args) for rec in caplog.records)
        b64 = base64.b64encode(PNG).decode()
        for bad in (NAME_MARK, "아세트아미노펜", "질문표지QZ7", "일부 흐림", b64[:40], "data:image", "pouch_drugs"):
            assert bad not in text
        assert any("ingest image status=OK" in rec.getMessage() for rec in caplog.records)  # 집계 줄은 남는다

    def test_exception_logged_by_kind_only(self, ledger: CostLedger, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        _post(_app(FakeClient(RuntimeError(f"secret {NAME_MARK}")), ledger), question=Q_MARK)
        assert NAME_MARK not in caplog.text and "질문표지QZ7" not in caplog.text

    def test_no_llm_cache_use(self) -> None:
        for mod in ("app/api/vision.py", "app/api/ingest.py"):
            assert not {m for m in _imports(BACKEND / mod) if m.startswith("app.llm.cache")}  # 캐시는 요청·응답을 파일로 남긴다
            assert "cached_openai_call" not in (BACKEND / mod).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 응급(RFP-35-07)
class TestEmergency:
    def test_emergency_even_when_nothing_read(self, ledger: CostLedger) -> None:
        assert detect_emergency(Q_EMERGENCY)
        body = _post(_app(FakeClient(_comp({"drugs": [], "unreadable_note": None})), ledger), question=Q_EMERGENCY).json()
        assert body["status"] == "UNREADABLE"
        assert body["emergency"] == {"text": fp.EMERGENCY_119, "tel": fp.EMERGENCY_119_TEL, "wide_text": fp.EMERGENCY_119_WIDE}

    def test_emergency_even_when_cap_reached(self, tmp_path: Path) -> None:
        body = _post(_app(FakeClient(), MemLedger(cap_reached=True)), question=Q_EMERGENCY).json()
        assert body["status"] == "UNAVAILABLE" and body["emergency"]["tel"] == "tel:119"

    def test_no_emergency_for_plain_question(self, ledger: CostLedger) -> None:
        body = _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger), question=Q_MARK).json()
        assert body["emergency"] is None

    def test_same_function_and_no_keyword_list_here(self) -> None:
        assert ingest_api.detect_emergency is detect_emergency
        for mod in ("app/api/ingest.py", "app/api/vision.py"):
            assert "EMERGENCY_KEYWORDS" not in (BACKEND / mod).read_text(encoding="utf-8")


# ---------------------------------------------------------------- H19
def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            out.add(base)
            out |= {f"{base}.{a.name}" for a in node.names}
    return out


class TestH19:
    @pytest.mark.parametrize("mod", ["app/api/vision.py", "app/api/ingest.py"])
    def test_no_tools_or_graph_import(self, mod: str) -> None:
        bad = {m for m in _imports(BACKEND / mod) if m.startswith(("app.agent.tools", "app.agent.graph", "app.tools.lookup",
                                                                  "app.agent.pipeline", "app.api.runner", "app.api.service"))}
        assert bad == set()

    def test_judgment_tools_not_called(self, ledger: CostLedger, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.agent.tools.check_contraindications as cc
        import app.agent.tools.identify_drug as idd
        import app.tools.lookup as lk

        calls: list[str] = []
        monkeypatch.setattr(idd, "identify_drug", lambda *a, **k: calls.append("identify_drug"))
        monkeypatch.setattr(cc, "check_contraindications", lambda *a, **k: calls.append("check_contraindications"))
        monkeypatch.setattr(lk, "check_contraindications", lambda *a, **k: calls.append("lookup.check_contraindications"))
        body = _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger), question=Q_MARK).json()
        assert body["status"] == "OK" and calls == []


# ---------------------------------------------------------------- 비용
class TestCost:
    def test_cap_reached_returns_unavailable_without_call(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        path.write_text(json.dumps({"dev": 0.0, "eval": 0.0, "vision": VISION_CAP_USD - 0.0001}))
        fake = FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None}))
        body = _post(_app(fake, CostLedger(path)), question=Q_MARK).json()
        assert body == {"status": "UNAVAILABLE", "reason": "CAP_REACHED", "drugs": [], "emergency": None, "dict_unavailable": False,
                        "dict_version": "golden-synth-v1"}
        assert fake.calls == []

    def test_unreadable_ledger_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        path.write_text("{not json")
        fake = FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None}))
        assert _post(_app(fake, CostLedger(path))).json()["reason"] == "CAP_REACHED" and fake.calls == []

    def test_actual_usage_added_to_vision_bucket(self, ledger: CostLedger) -> None:
        _post(_app(FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger))
        assert ledger.spent("vision") == pytest.approx(2500 * 0.10 / 1e6 + 300 * 0.50 / 1e6)
        assert ledger.spent("dev") == 0.0 and ledger.spent("eval") == 0.0

    def test_guard_uses_worst_case_before_call(self) -> None:
        led = MemLedger()
        vision.extract(PNG, client=FakeClient(_comp({"drugs": [_drug()], "unreadable_note": None})), ledger=led)
        (est, bucket), = led.guarded
        assert bucket == "vision" and est >= 4000 * 0.50 / 1e6 and led.added[0][1] == "vision"

    def test_ledger_dev_eval_unchanged_and_vision_independent(self, tmp_path: Path) -> None:
        assert BUCKETS == ("dev", "eval", "vision")
        led = CostLedger(tmp_path / "l.json")
        led.guard(DEV_CAP_USD - 0.01, bucket="dev")
        with pytest.raises(BudgetExceeded, match="개발 비용 상한 초과"):
            led.guard(DEV_CAP_USD + 0.01, bucket="dev")
        led.guard(1000.0, bucket="eval")  # eval은 세기만
        led.add(0.29, bucket="vision")
        led.guard(0.0, bucket="dev")  # vision 지출은 dev 상한에 들어가지 않는다
        with pytest.raises(BudgetExceeded):
            led.guard(0.02, bucket="vision")
        led.guard(0.009, bucket="vision")
        assert CostLedger(tmp_path / "x.json", bucket_caps={"vision": 1.0}).cap_for("vision") == 1.0
        with pytest.raises(ValueError):
            led.guard(0.0, bucket="other")


# ---------------------------------------------------------------- 계약
_BANNED = ("summary", "verdict", "judgement", "judgment", "contraindication", "explanation", "status_label", "selected", "confidence", "grade")


class TestContract:
    def test_models_have_no_judgment_or_summary_fields(self) -> None:
        assert set(ingest_api.IngestImageOut.model_fields) == {"status", "reason", "drugs", "emergency", "dict_unavailable", "dict_version"}
        assert set(ingest_api.IngestDrugOut.model_fields) == {"read_name", "read_ingredient", "strength_or_form", "candidates"}
        for m in (ingest_api.IngestImageOut, ingest_api.IngestDrugOut):
            assert not any(b in f for f in m.model_fields for b in _BANNED)
            assert m.model_config.get("extra") == "forbid"

    def test_chat_openapi_unchanged_and_ingest_is_guest(self) -> None:
        def build(with_ingest: bool) -> dict:
            app = FastAPI()
            chat_api.register(app)
            me_api.register(app)
            drugs_api.register(app)
            if with_ingest:
                ingest_api.register(app)
            return app.openapi()

        before, after = build(False), build(True)
        assert after["paths"]["/chat"] == before["paths"]["/chat"]
        for name, schema in before["components"]["schemas"].items():
            assert after["components"]["schemas"][name] == schema
        op = after["paths"]["/ingest/image"]
        assert set(op) == {"post"} and "security" not in op["post"]
        assert set(op["post"]["responses"]) == {"200", "422"}
        assert set(after["paths"]) - set(before["paths"]) == {"/ingest/image", "/ingest/drugs/search"}

    def test_main_app_registers_ingest(self) -> None:
        from app import main as main_mod

        assert "/ingest/image" in main_mod.app.openapi()["paths"]


# ---------------------------------------------------------------- AG-17과 같은 조건
def _ref_nodes(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            out[n.targets[0].id] = ast.dump(n.value)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            out[n.target.id] = ast.dump(n.value)
    return out


class TestSameAsAg17Reference:
    def test_prompt_body_equals_reference_system(self) -> None:
        ref = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(REF.read_text(encoding="utf-8")).body
               if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id in ("SYSTEM", "USER_TEXT")}
        assert vision.load_system_prompt() == ref["SYSTEM"] and vision.USER_TEXT == ref["USER_TEXT"]

    @pytest.mark.parametrize("name", ["SCHEMA", "ALLOWED_DRUG_FIELDS", "CONFIDENCE", "LEAK_PATTERNS", "STRENGTH_FORM_OK", "USER_TEXT"])
    def test_same_constants_as_reference(self, name: str) -> None:
        assert _ref_nodes(BACKEND / "app" / "api" / "vision.py")[name] == _ref_nodes(REF)[name]

    def test_same_numbers_as_reference(self) -> None:
        ref = _ref_nodes(REF)
        assert ref["UPSCALE_LONG_SIDE"] == ast.dump(ast.Constant(vision.LONG_SIDE))
        assert ref["OPENAI_MAX_COMPLETION"] == ast.dump(ast.Constant(vision.MAX_COMPLETION_TOKENS))
        assert ref["MAX_STR"] == ast.dump(ast.Constant(vision.MAX_STR))
        prices = next(n.value for n in ast.parse(REF.read_text(encoding="utf-8")).body
                      if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "OPENAI_PRICES")
        assert isinstance(prices, ast.Dict) and ast.literal_eval(prices.values[0]) == (vision.PRICE_IN_PER_M, vision.PRICE_OUT_PER_M)

    def test_prompt_file_passes_l0_check(self) -> None:
        from app.llm.prompts import check_prompt_file

        assert check_prompt_file(vision.PROMPT_PATH) == []
