"""FE-04-13 A·FE-04 (나) A 프로필 약 사전 검색 API(`POST /drugs/search`) 시험(2026-11-20). LLM·네트워크·DB 호출 0.

- 사전은 합성 사전(`golden_dict`, 실제 제품 정보 아님)을 공급자로 주입한다. 토큰은 가짜 검증기.
- 확인: 제품 매칭·성분 매칭·없음·빈 입력·긴 입력·특수문자·후보 상한 10·로그인 필요·공급자 없음 501·적재 실패 503,
  질문 문자열이 응답·오류 본문·로그에 없음, 저장 계약(후보 고르면 `item_seq`, 없으면 글자만 = "확인 안 된 약"), 사전 재확인 함수.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_AZI, SEQ_COLD, SEQ_KID, SEQ_T500, golden_dict  # noqa: E402

from app.api import account as account_api  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import drugs as drugs_api  # noqa: E402
from app.api import me as me_api  # noqa: E402
from app.db.account_repo import InMemoryAccountRepo, LegalDoc, body_sha256  # noqa: E402
from app.security import auth  # noqa: E402
from app.security.auth import TokenInvalid  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

TOK = "eyJhbGciOiJFUzI1NiJ9.eyJ1c2VyIjoiYSJ9.c2lnLWE"
UID = "11111111-1111-4111-8111-111111111111"
MARKER = "비밀검색표지QZ8"
NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)


class OneToken:
    async def verify(self, token: str) -> str:
        if token == TOK:
            return UID
        raise TokenInvalid("rejected")


def _app(provider: Any = golden_dict) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    me_api.register(app)
    drugs_api.register(app)
    auth.set_verifier(app, OneToken())
    if provider is not None:
        drugs_api.set_provider(app, provider)
    return TestClient(app)


def _search(c: TestClient, q: Any, token: str | None = TOK) -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return c.post("/drugs/search", json={"q": q}, headers=headers)


@pytest.fixture
def c() -> TestClient:
    return _app()


class TestMatching:
    def test_product_exact(self, c: TestClient) -> None:
        r = _search(c, "타이레놀콜드-에스정")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        top = body["candidates"][0]
        assert top == {"name": "타이레놀콜드-에스정", "item_seq": SEQ_COLD, "entp_name": "합성제약", "prescription": "일반",
                       "matched_by": "product_name", "match_type": "exact"}
        assert body["needs_confirmation"] is False and body["dict_version"] == "golden-synth-v1"

    def test_product_prefix_lists_candidates_for_choice(self, c: TestClient) -> None:
        body = _search(c, "타이레놀").json()
        seqs = [x["item_seq"] for x in body["candidates"]]
        assert set(seqs) >= {SEQ_T500, SEQ_COLD} and all(x["matched_by"] == "product_name" for x in body["candidates"])
        assert body["needs_confirmation"] is True

    def test_prescription_flag(self, c: TestClient) -> None:
        top = _search(c, "이지렉트정1.0밀리그램").json()["candidates"][0]
        assert top["item_seq"] == SEQ_AZI and top["prescription"] == "전문"

    def test_ingredient_after_product(self, c: TestClient) -> None:
        body = _search(c, "아세트아미노펜").json()
        top = body["candidates"][0]
        assert top["matched_by"] == "ingredient_name" and top["item_seq"] is None and top["name"] == "아세트아미노펜"

    def test_contains_match(self, c: TestClient) -> None:
        names = [x["name"] for x in _search(c, "레놀현탁").json()["candidates"]]
        assert names and names[0] == "어린이타이레놀현탁액"

    def test_not_in_dict_is_empty(self, c: TestClient) -> None:
        body = _search(c, "쿼크즈뷁약").json()
        assert body == {"candidates": [], "needs_confirmation": False, "dict_version": "golden-synth-v1"}

    @pytest.mark.parametrize("q", ["!!@@##", "<script>", "'; DROP TABLE x;--", "%00", "🙂🙂"])
    def test_special_chars_do_not_fail(self, c: TestClient, q: str) -> None:
        r = _search(c, q)
        assert r.status_code == 200 and isinstance(r.json()["candidates"], list)

    def test_limit_10_and_unique(self) -> None:
        dd = golden_dict()
        data = {"meta": dd.meta, "ingredients": dd.ingredients,
                "products": [dict(dd.products[0], name=f"테스트정{i:02d}", item_seq=f"9000000{i:02d}") for i in range(15)]}
        big = DrugDict(data)
        body = _search(_app(lambda: big), "테스트정").json()
        seqs = [x["item_seq"] for x in body["candidates"]]
        assert len(seqs) == drugs_api.SEARCH_LIMIT == 10 and len(set(seqs)) == 10


class TestInputErrors:
    @pytest.mark.parametrize("q", ["", "   "])
    def test_empty(self, c: TestClient, q: str) -> None:
        r = _search(c, q)
        assert r.status_code == 422 and r.json() == {"code": "INVALID_REQUEST", "fields": ["q"]}

    def test_too_long_does_not_echo(self, c: TestClient) -> None:
        q = MARKER + "가" * 100
        r = _search(c, q)
        assert r.status_code == 422 and r.json() == {"code": "INVALID_REQUEST", "fields": ["q"]}
        assert MARKER not in r.text

    def test_exactly_100_ok(self, c: TestClient) -> None:
        assert _search(c, "가" * 100).status_code == 200

    def test_missing_and_extra_fields(self, c: TestClient) -> None:
        h = {"Authorization": f"Bearer {TOK}"}
        assert c.post("/drugs/search", json={}, headers=h).json()["fields"] == ["q"]
        r = c.post("/drugs/search", json={"q": "타이레놀", MARKER: 1}, headers=h)
        assert r.status_code == 422 and MARKER not in r.text

    def test_non_string(self, c: TestClient) -> None:
        r = _search(c, 123)
        assert r.status_code == 422 and r.json()["fields"] == ["q"]

    def test_get_with_query_not_allowed(self, c: TestClient) -> None:
        assert c.get("/drugs/search", params={"q": "타이레놀"}, headers={"Authorization": f"Bearer {TOK}"}).status_code == 405


class TestAuthAndAvailability:
    def test_login_required(self, c: TestClient) -> None:
        r = _search(c, "타이레놀", token=None)
        assert r.status_code == 401 and r.json()["code"] == "AUTH_REQUIRED"
        assert _search(c, "타이레놀", token="eyJ.bad.tok").status_code == 401

    def test_no_provider_501(self) -> None:
        r = _search(_app(None), "타이레놀")
        assert r.status_code == 501 and r.json() == {"code": "NOT_IMPLEMENTED", "fields": []}

    def test_provider_failure_503_without_details(self, caplog: pytest.LogCaptureFixture) -> None:
        def boom() -> DrugDict:
            raise ConnectionError(f"postgres://user:pw@host/db {MARKER}")

        caplog.set_level(logging.DEBUG)
        r = _search(_app(boom), MARKER)
        assert r.status_code == 503 and r.json() == {"code": "DICT_UNAVAILABLE", "fields": []}
        assert "ConnectionError" in caplog.text
        assert MARKER not in caplog.text and "postgres://" not in caplog.text and MARKER not in r.text


class TestNoQueryLeak:
    def test_query_not_in_logs_or_response(self, c: TestClient, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        for q in (MARKER, f"타이레놀{MARKER}", "타이레놀"):
            r = _search(c, q)
            assert r.status_code == 200 and MARKER not in r.text
        assert MARKER not in caplog.text
        assert "/drugs/search?" not in caplog.text  # 질문이 URL에 실리지 않는다


class TestStorageContract:
    """FE-04 (나) A: 후보를 고르면 `item_seq` 저장, 사전에 없으면 글자만("확인 안 된 약" = `item_seq is null`)."""

    def _env(self) -> tuple[TestClient, InMemoryAccountRepo]:
        def doc(t: str) -> LegalDoc:
            body = f"> 초안·법률 검토 전입니다.\n\n{t} v1 본문(합성)"
            return LegalDoc(t, 1, f"{t} v1", body, t in ("terms", "privacy_consent"), False, NOW - timedelta(days=1), "not_reviewed",
                            body_sha256(body))

        repo = InMemoryAccountRepo([doc(t) for t in ("terms", "privacy_policy", "privacy_consent", "sensitive_consent")], clock=lambda: NOW)
        app = FastAPI()
        chat_api.register(app)
        me_api.register(app)
        drugs_api.register(app)
        auth.set_verifier(app, OneToken())
        drugs_api.set_provider(app, golden_dict)
        account_api.set_repo(app, repo, item_seq_checker=drugs_api.dict_item_seq_checker(golden_dict))
        return TestClient(app), repo

    def test_pick_candidate_saves_item_seq_and_free_text_saves_null(self) -> None:
        c, _ = self._env()
        h = {"Authorization": f"Bearer {TOK}"}
        assert c.get("/me", headers=h).status_code == 200
        items = [{"doc_type": t, "version": 1, "action": "agree"} for t in ("terms", "privacy_consent", "sensitive_consent")]
        assert c.post("/consents", json={"items": items, "channel": "onboarding"}, headers=h).status_code == 201
        pick = _search(c, "타이레놀콜드-에스정").json()["candidates"][0]
        meds = [{"input_text": pick["name"], "item_seq": pick["item_seq"]},
                {"input_text": "할머니가 주신 하얀 알약"},  # 사전에 없음 → 확인 안 된 약(글자만)
                {"input_text": "가짜번호약", "item_seq": "999999999"}]  # 사전에 없는 번호는 서버가 버린다
        r = c.post("/profiles", json={"relation": "self", "medications": meds}, headers=h)
        assert r.status_code == 201, r.text
        saved = r.json()["medications"]
        assert [(m["input_text"], m["item_seq"]) for m in saved] == [
            ("타이레놀콜드-에스정", SEQ_COLD), ("할머니가 주신 하얀 알약", None), ("가짜번호약", None)]
        assert saved[0]["confirmed_at"] is not None and saved[1]["confirmed_at"] is None

    def test_checker_uses_dict_only(self) -> None:
        check = drugs_api.dict_item_seq_checker(golden_dict)
        assert asyncio.run(check([SEQ_KID, "000000000", SEQ_AZI])) == {SEQ_KID, SEQ_AZI}


def test_main_app_registers_post_route() -> None:
    from app.main import app  # noqa: PLC0415

    ops = app.openapi()["paths"]["/drugs/search"]
    assert set(ops) == {"post"}
    assert ops["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/DrugSearchIn")
