# ruff: noqa: S101  (시험 파일: assert 허용)
"""`mock_gen/vision_pouch_test.py`의 Upstage 제공자(AG-17) 시험: 네트워크·API 호출 없이 가짜 응답만 쓴다.

실행(저장소 루트): `PYTHONPATH=backend backend/.venv/bin/python -m pytest evaluation/test_vision_pouch_upstage.py -q -p no:cacheprovider`
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

MOCK_GEN = Path(__file__).resolve().parent / "mock_gen"
if str(MOCK_GEN) not in sys.path:
    sys.path.insert(0, str(MOCK_GEN))

import vision_pouch_test as vp  # noqa: E402

FAKE_OCR_TEXT = "가짜약정10mg 홍길동 010-1234-5678"  # 가짜 값(개인정보 모양이 결과 파일에 남지 않는지 본다)


def _ocr_doc(text: str = FAKE_OCR_TEXT) -> dict:
    return {"text": text, "modelVersion": "ocr-test", "numBilledPages": 1,
            "pages": [{"text": text, "words": [{"text": "가짜약정10mg", "confidence": 0.9},
                                               {"text": "홍길동", "confidence": 0.7}]}]}


@pytest.fixture
def upstage(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "PROVIDER", "upstage")
    monkeypatch.setattr(vp, "MODEL", vp.SOLAR)
    monkeypatch.setattr(vp, "CAP_USD", 0.30)
    monkeypatch.setattr(vp, "OUT", tmp_path)
    monkeypatch.setattr(vp, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(vp, "CALLS", tmp_path / "calls.jsonl")
    monkeypatch.setattr(vp, "LABELS", tmp_path / "labels_user_reviewed.json")
    monkeypatch.setattr(vp, "SUFFIX", "_ag17")
    return tmp_path


def test_ocr_summary_keeps_no_text():
    text, summary = vp.ocr_summary(_ocr_doc())
    assert text == FAKE_OCR_TEXT
    assert summary["ocr_words"] == 2 and summary["ocr_pages"] == 1 and summary["ocr_mean_conf"] == 0.8
    assert FAKE_OCR_TEXT not in json.dumps(summary, ensure_ascii=False)


def test_ocr_summary_truncates_long_text():
    text, summary = vp.ocr_summary(_ocr_doc("가" * (vp.OCR_MAX_CHARS + 10)))
    assert len(text) == vp.OCR_MAX_CHARS and summary["ocr_truncated"] is True


def test_upstage_messages_reuse_same_instructions():
    msgs = vp.upstage_messages("글자")
    assert msgs[0] == {"role": "system", "content": vp.SYSTEM}
    assert msgs[1]["content"].endswith(vp.USER_TEXT) and "글자" in msgs[1]["content"]


def test_worst_cost_fits_cap_for_12_calls(upstage):
    worst = vp.worst_cost(Path("x.jpg"))
    assert worst > vp.UPSTAGE_OCR_USD_PER_PAGE
    assert worst * 12 < 0.30


def test_paths_upstage_names(upstage):
    res, grade = vp.paths(True)
    assert res.name == "results_upstage_ag17_upscaled.json"
    assert grade.name == "grade_upstage_user_reviewed_ag17_upscaled.json"


def test_parse_json_text_handles_fence():
    raw, ok = vp.parse_json_text('```json\n{"drugs": [], "unreadable_note": null}\n```')
    assert ok and raw == {"drugs": [], "unreadable_note": None}
    assert vp.parse_json_text("not json") == (None, False)


def test_cap_blocks_before_any_request(upstage, monkeypatch):
    (upstage / "ledger.json").write_text(json.dumps({"usd": 0.2999, "cap_usd": 0.30}))
    _fake_settings(monkeypatch)
    import httpx

    def boom(*a, **k):  # 상한에 닿으면 OCR 요청도 나가지 않아야 한다
        raise AssertionError("요청이 나가면 안 된다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(vp, "image_payload", lambda p, u: ("image/jpeg", "AAAA", 1))
    with pytest.raises(SystemExit):
        vp.call_image_upstage(Path("x.jpg"), "t")


def _fake_settings(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: types.SimpleNamespace(upstage_api_key="fake-not-a-key"))


def test_call_image_upstage_with_fakes(upstage, monkeypatch, tmp_path):
    _fake_settings(monkeypatch)
    import httpx
    import openai

    img = tmp_path / "img.jpg"
    img.write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(vp, "image_payload", lambda p, u: ("image/jpeg", "AAAA", 1))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: types.SimpleNamespace(status_code=200, json=_ocr_doc))
    seen = {}
    out_json = json.dumps({"drugs": [{"product_name": "가짜약정", "ingredient_name": None,
                                      "strength_or_form": "10mg", "confidence": "high", "patient": "x"}],
                           "unreadable_note": None}, ensure_ascii=False)

    class FakeClient:
        def __init__(self, **kw):
            seen["base_url"] = kw.get("base_url")
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        def create(self, **kw):
            seen["model"] = kw["model"]
            seen["format"] = kw.get("response_format", {}).get("type")
            msg = types.SimpleNamespace(content=out_json)
            return types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
                                         choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    res = vp.call_image_upstage(img, "img-run1", upscale=True)
    assert seen == {"base_url": vp.UPSTAGE_BASE, "model": vp.SOLAR, "format": "json_schema"}
    assert res["output"]["drugs"][0]["product_name"] == "가짜약정"
    assert "drugs[].patient" in res["dropped_keys"]
    expected = 0.0015 + 1000 * 0.30 / 1e6 + 200 * 1.20 / 1e6
    assert res["usd"] == round(expected, 6)
    assert json.loads((upstage / "ledger.json").read_text())["usd"] == pytest.approx(expected, abs=1e-6)
    stored = (upstage / "calls.jsonl").read_text() + json.dumps(res, ensure_ascii=False)
    assert "홍길동" not in stored and "010-1234-5678" not in stored and "fake-not-a-key" not in stored
