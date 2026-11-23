"""BE-11 계정 API 시험(설계 13장 T4·T5, 2026-11-18). 저장소는 메모리 가짜(`InMemoryAccountRepo`). 네트워크·DB·LLM 호출 0.

- 토큰은 가짜 검증기(`TokenMap`)가 합성 JWS 모양 문자열을 사용자 ID로 바꾼다(실제 키·계정 아님).
- 확인: 약관(게스트)·`/me`(첫 호출 계정 생성)·동의(버전 불일치·약관 철회 거부·철회 시 삭제)·프로필(본인 1 + 가족 3, 4번째 가족 422)·
  건강 정보 동의(없으면 422)·재동의·탈퇴(전부 파기, 일자·건수만)·다른 계정 격리·오류 본문 `{code, fields}`·로그에 토큰·건강 정보 없음·
  `/chat` 회귀(계정 저장소·검증기 호출 0).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import account as account_api
from app.api import chat as chat_api
from app.api import me as me_api
from app.db.account_repo import (
    AccountRepoError,
    ConsentInput,
    InMemoryAccountRepo,
    LegalDoc,
    RepoUnavailable,
    body_sha256,
)
from app.security import auth, auth_admin
from app.security.auth import TokenInvalid

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(days=1)
UID_A = "11111111-1111-4111-8111-111111111111"
UID_B = "22222222-2222-4222-8222-222222222222"
TOK_A = "eyJhbGciOiJFUzI1NiJ9.eyJ1c2VyIjoiYSJ9.c2lnLWE"
TOK_B = "eyJhbGciOiJFUzI1NiJ9.eyJ1c2VyIjoiYiJ9.c2lnLWI"
TOK_BAD = "eyJhbGciOiJFUzI1NiJ9.eyJ1c2VyIjoieCJ9.c2lnLXg"
MED_SECRET = "비밀약이름정"  # 로그에 새면 찾기 쉬운 표지
LABEL_SECRET = "막내표지"


def _doc(doc_type: str, version: int = 1, *, required: bool | None = None, effective: datetime = PAST,
         requires_reconsent: bool = False) -> LegalDoc:
    body = f"> 초안·법률 검토 전입니다.\n\n{doc_type} v{version} 본문"
    req = doc_type in ("terms", "privacy_consent", "age_14") if required is None else required
    return LegalDoc(doc_type, version, f"{doc_type} v{version}(초안)", body, req, requires_reconsent, effective, "not_reviewed",
                    body_sha256(body))


def _docs() -> list[LegalDoc]:
    return [_doc("terms"), _doc("privacy_policy"), _doc("privacy_consent"), _doc("sensitive_consent"), _doc("age_14")]


class TokenMap:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, token: str) -> str:
        self.calls += 1
        if token == TOK_A:
            return UID_A
        if token == TOK_B:
            return UID_B
        raise TokenInvalid("rejected")


class FakeAuthAdmin:
    """가짜 Auth 관리(BE-11-24 A). 삭제하면 저장소의 `auth_users`(FK 흉내)에서 뺀다. HTTP 수준 시험은 `test_be11_auth_admin.py`."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.deleted: list[str] = []

    async def delete_user(self, user_id: str) -> None:
        self.deleted.append(user_id)
        if getattr(self.repo, "auth_users", None) is not None:
            self.repo.auth_users.discard(user_id)


class Env:
    def __init__(self, repo: Any = None, checker: Any = None) -> None:
        self.repo = repo if repo is not None else InMemoryAccountRepo(_docs(), clock=lambda: NOW, auth_users={UID_A, UID_B})
        self.verifier = TokenMap()
        self.admin = FakeAuthAdmin(self.repo)
        app = FastAPI()
        chat_api.register(app)
        me_api.register(app)
        auth.set_verifier(app, self.verifier)
        auth_admin.set_auth_admin(app, self.admin)
        account_api.set_repo(app, self.repo, item_seq_checker=checker)
        self.app = app
        self.c = TestClient(app)

    def req(self, method: str, path: str, token: str | None = TOK_A, **kw: Any) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.c.request(method, path, headers=headers, **kw)

    def consent(self, *items: tuple[str, int, str], token: str = TOK_A, channel: str = "onboarding") -> Any:
        return self.req("POST", "/consents", token, json={
            "items": [{"doc_type": t, "version": v, "action": a} for t, v, a in items], "channel": channel})

    def onboard(self, token: str = TOK_A, *, health: bool = False) -> None:
        assert self.req("GET", "/me", token).status_code == 200
        items = [("terms", 1, "agree"), ("privacy_consent", 1, "agree"), ("age_14", 1, "agree")] + \
            ([("sensitive_consent", 1, "agree")] if health else [])
        assert self.consent(*items, token=token).status_code == 201


@pytest.fixture
def env() -> Env:
    return Env()


def _err(r: Any) -> tuple[int, str, list[str]]:
    body = r.json()
    assert set(body) == {"code", "fields"}
    return r.status_code, body["code"], body["fields"]


# --------------------------------------------------------------------------- 약관(게스트)
def test_legal_guest_current_document(env):
    r = env.req("GET", "/legal/terms", token=None)
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=300"
    body = r.json()
    assert (body["doc_type"], body["version"], body["required"], body["legal_review"]) == ("terms", 1, True, "not_reviewed")
    assert body["body_sha256"] == body_sha256(body["body_md"]) and "초안·법률 검토 전" in body["body_md"]
    assert env.verifier.calls == 0


def test_legal_ignores_token_even_invalid(env):
    assert env.req("GET", "/legal/privacy_policy", token=TOK_BAD).status_code == 200
    assert env.verifier.calls == 0  # 게스트 경로는 토큰을 읽지 않는다


def test_legal_upcoming_version_is_not_current_and_version_query(env):
    env.repo.add_document(_doc("terms", 2, effective=NOW + timedelta(days=7)))
    assert env.req("GET", "/legal/terms", None).json()["version"] == 1
    assert _err(env.req("GET", "/legal/terms?version=2", None)) == (404, "NOT_FOUND", [])
    assert env.req("GET", "/legal/terms?version=1", None).json()["version"] == 1


def test_legal_bad_doc_type_and_missing(env):
    assert _err(env.req("GET", "/legal/nope", None)) == (422, "INVALID_REQUEST", ["doc_type"])
    assert _err(env.req("GET", "/legal/terms?version=0", None)) == (422, "INVALID_REQUEST", ["version"])
    empty = Env(InMemoryAccountRepo([], clock=lambda: NOW))
    assert _err(empty.req("GET", "/legal/terms", None)) == (404, "NOT_FOUND", [])


def test_account_api_without_repo_is_501():
    e = Env()
    account_api.set_repo(e.app, None)
    assert _err(e.req("GET", "/legal/terms", None)) == (501, "NOT_IMPLEMENTED", [])
    assert _err(e.req("GET", "/profiles")) == (501, "NOT_IMPLEMENTED", [])


# --------------------------------------------------------------------------- /me
def test_me_first_call_creates_account_and_lists_consent_states(env):
    assert env.repo.user_count() == 0
    body = env.req("GET", "/me").json()
    assert env.repo.user_count() == 1
    assert body["onboarding_step"] == "consent" and body["onboarding_completed_at"] is None
    states = {s["doc_type"]: s for s in body["consents"]}
    assert set(states) == {"terms", "privacy_consent", "sensitive_consent", "age_14"}  # 처리방침은 동의 대상 아님
    assert all(s["needs_consent"] and s["agreed_version"] is None for s in states.values())
    assert states["terms"]["required"] and not states["sensitive_consent"]["required"]
    assert states["age_14"]["required"]  # 만 14세 확인은 첫 로그인 필수(PRD-17-12 A)
    assert body["health_consent_active"] is False and body["profile_limit"] == 4
    env.req("GET", "/me")
    assert env.repo.user_count() == 1  # 두 번째 호출은 행을 더 만들지 않는다


def test_account_endpoints_before_me_are_401(env):
    for method, path, kw in (("GET", "/profiles", {}), ("POST", "/profiles", {"json": {"relation": "self"}})):
        r = env.req(method, path, **kw)
        assert _err(r) == (401, "AUTH_INVALID", []) and r.headers["www-authenticate"] == "Bearer"
    assert _err(env.consent(("terms", 1, "agree"))) == (401, "AUTH_INVALID", [])


@pytest.mark.parametrize(("method", "path"), [("GET", "/me"), ("DELETE", "/me"), ("GET", "/profiles"), ("POST", "/consents"),
                                              ("POST", "/profiles"), ("PATCH", f"/profiles/{UID_B}"), ("DELETE", f"/profiles/{UID_B}")])
def test_guest_is_401_auth_required_everywhere_except_legal(env, method, path):
    r = env.req(method, path, token=None, json={})
    assert _err(r) == (401, "AUTH_REQUIRED", [])
    r = env.req(method, path, token=TOK_BAD, json={})
    assert _err(r) == (401, "AUTH_INVALID", [])


# --------------------------------------------------------------------------- 동의
def test_consents_agree_advances_onboarding(env):
    env.req("GET", "/me")
    r = env.consent(("terms", 1, "agree"), ("privacy_consent", 1, "agree"))
    assert r.json()["onboarding_step"] == "consent"  # 만 14세 확인(age_14)이 없으면 첫 단계에 머문다(PRD-17-12 A)
    r = env.consent(("age_14", 1, "agree"))
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["onboarding_step"] == "profile_self"
    states = {s["doc_type"]: s for s in body["consents"]}
    assert states["terms"]["agreed_version"] == 1 and not states["terms"]["needs_consent"]
    assert states["sensitive_consent"]["needs_consent"] and body["health_consent_active"] is False


def test_consent_version_mismatch_and_bad_items(env):
    env.req("GET", "/me")
    assert _err(env.consent(("terms", 2, "agree"))) == (409, "VERSION_MISMATCH", ["terms"])
    assert _err(env.req("POST", "/consents", json={"items": [{"doc_type": "privacy_policy", "version": 1, "action": "agree"}],
                                                   "channel": "onboarding"})) == (422, "INVALID_REQUEST", ["items.0.doc_type"])
    assert _err(env.consent(("terms", 1, "agree"), ("terms", 1, "agree"))) == (422, "INVALID_REQUEST", ["body"])
    assert _err(env.req("POST", "/consents", json={"items": [], "channel": "onboarding"})) == (422, "INVALID_REQUEST", ["items"])
    assert _err(env.req("POST", "/consents", json={"items": [{"doc_type": "terms", "version": 1, "action": "agree"}],
                                                   "channel": "web"})) == (422, "INVALID_REQUEST", ["channel"])
    assert env.repo._users[UID_A].consents == []  # 하나도 기록되지 않았다


def test_terms_withdraw_is_409_use_account_delete(env):
    env.onboard()
    assert _err(env.consent(("terms", 1, "withdraw"))) == (409, "USE_ACCOUNT_DELETE", ["terms"])
    # 저장소 단계에서도 막는다(SQL 트리거와 같은 규칙)
    with pytest.raises(AccountRepoError):
        asyncio.run(env.repo.add_consents(UID_A, [ConsentInput("terms", 1, "withdraw")], "settings"))


# --------------------------------------------------------------------------- 프로필
def test_profiles_require_terms_and_privacy_consent(env):
    env.req("GET", "/me")
    assert _err(env.req("POST", "/profiles", json={"relation": "self"})) == \
        (403, "CONSENT_REQUIRED", ["terms", "privacy_consent", "age_14"])
    env.consent(("terms", 1, "agree"))
    assert _err(env.req("POST", "/profiles", json={"relation": "self"})) == (403, "CONSENT_REQUIRED", ["privacy_consent", "age_14"])
    env.consent(("privacy_consent", 1, "agree"))
    assert _err(env.req("POST", "/profiles", json={"relation": "self"})) == (403, "CONSENT_REQUIRED", ["age_14"])
    assert env.req("GET", "/profiles").json() == []


def test_self_plus_three_family_then_fourth_family_is_422(env):
    env.onboard()
    r = env.req("POST", "/profiles", json={"relation": "self", "age_band": "y19_64", "label": "  나  "})
    assert r.status_code == 201 and r.json()["label"] == "나" and r.json()["sort_order"] == 0
    assert env.req("GET", "/me").json()["onboarding_step"] == "family"
    assert _err(env.req("POST", "/profiles", json={"relation": "self"})) == (409, "SELF_EXISTS", ["relation"])
    for rel, band in (("child", "m3_5"), ("parent", "y65_plus"), ("spouse", "y19_64")):
        assert env.req("POST", "/profiles", json={"relation": rel, "age_band": band}).status_code == 201
    me = env.req("GET", "/me").json()
    assert me["onboarding_step"] == "done" and me["onboarding_completed_at"] is not None
    assert _err(env.req("POST", "/profiles", json={"relation": "other"})) == (422, "PROFILE_LIMIT", ["relation"])
    profiles = env.req("GET", "/profiles").json()
    assert [p["sort_order"] for p in profiles] == [0, 1, 2, 3] and len(profiles) == 4


def test_four_family_without_self_is_422(env):
    env.onboard()
    for _ in range(3):
        assert env.req("POST", "/profiles", json={"relation": "child"}).status_code == 201
    assert _err(env.req("POST", "/profiles", json={"relation": "child"})) == (422, "PROFILE_LIMIT", ["relation"])
    assert env.req("POST", "/profiles", json={"relation": "self"}).status_code == 201  # 본인 자리는 남아 있다


@pytest.mark.parametrize(("payload", "field"), [
    ({"relation": "self", "label": ""}, "label"), ({"relation": "self", "label": "가" * 21}, "label"),
    ({"relation": "cousin"}, "relation"), ({"relation": "self", "age_band": "y0"}, "age_band"),
    ({"relation": "self", "pregnancy_status": "maybe"}, "pregnancy_status"),
    ({"relation": "self", "medications": [{"input_text": "a", "item_seq": "12"}]}, "medications.0.item_seq"),
    ({"relation": "self", "medications": [{"input_text": "약"}] * 11}, "medications"),
    ({"relation": "self", "pregnancy_week": 12}, "body"),  # 임신 주차 칸 없음(BE-11-09 A), 모르는 칸 이름은 싣지 않는다
])
def test_profile_validation_fields_only_names(env, payload, field):
    env.onboard(health=True)
    r = env.req("POST", "/profiles", json=payload)
    assert _err(r) == (422, "INVALID_REQUEST", [field])
    assert "pregnancy_week" not in r.text and "cousin" not in r.text


def test_health_info_requires_sensitive_consent(env):
    env.onboard()
    assert _err(env.req("POST", "/profiles", json={"relation": "self", "pregnancy_status": "pregnant"})) == \
        (422, "HEALTH_CONSENT_REQUIRED", ["pregnancy_status"])
    assert _err(env.req("POST", "/profiles", json={"relation": "self", "medications": [{"input_text": MED_SECRET}]})) == \
        (422, "HEALTH_CONSENT_REQUIRED", ["medications"])
    assert env.req("GET", "/profiles").json() == []  # 조용히 버리고 저장하지 않았다
    pid = env.req("POST", "/profiles", json={"relation": "self", "pregnancy_status": None, "medications": []}).json()["profile_id"]
    assert _err(env.req("PATCH", f"/profiles/{pid}", json={"pregnancy_status": "not_pregnant"})) == \
        (422, "HEALTH_CONSENT_REQUIRED", ["pregnancy_status"])
    assert env.req("PATCH", f"/profiles/{pid}", json={"pregnancy_status": None, "medications": []}).status_code == 200


def test_health_info_saved_with_consent_and_item_seq_needs_checker(env):
    env.onboard(health=True)
    me = env.req("GET", "/me").json()
    assert me["health_consent_active"] is True
    r = env.req("POST", "/profiles", json={"relation": "spouse", "pregnancy_status": "pregnant", "medications": [
        {"input_text": " 타이레놀정500밀리그램 ", "item_seq": "200300406"}, {"input_text": MED_SECRET}]})
    assert r.status_code == 201
    p = r.json()
    assert p["pregnancy_status"] == "pregnant"
    assert [(m["input_text"], m["item_seq"], m["confirmed_at"]) for m in p["medications"]] == \
        [("타이레놀정500밀리그램", None, None), (MED_SECRET, None, None)]  # 확인 함수가 없으면 원문만


def test_item_seq_kept_only_when_checker_confirms():
    seen: list[list[str]] = []

    async def checker(seqs: Any) -> set[str]:
        seen.append(list(seqs))
        return {"200300406"}

    e = Env(checker=checker)
    e.onboard(health=True)
    p = e.req("POST", "/profiles", json={"relation": "self", "medications": [
        {"input_text": "타이레놀", "item_seq": "200300406"}, {"input_text": "모름약", "item_seq": "999999999"}]}).json()
    assert [m["item_seq"] for m in p["medications"]] == ["200300406", None]
    assert p["medications"][0]["confirmed_at"] is not None and seen == [["200300406", "999999999"]]


def test_item_seq_checker_failure_falls_back_to_text(caplog):
    async def boom(seqs: Any) -> set[str]:
        raise RuntimeError("dict down 200300406")

    e = Env(checker=boom)
    e.onboard(health=True)
    caplog.set_level(logging.DEBUG)
    p = e.req("POST", "/profiles", json={"relation": "self", "medications": [{"input_text": "타이레놀", "item_seq": "200300406"}]}).json()
    assert p["medications"][0]["item_seq"] is None
    assert "품목 확인 실패, 원문만 저장: RuntimeError" in caplog.text and "200300406" not in caplog.text


def test_patch_profile_partial_and_self_fixed(env):
    env.onboard(health=True)
    me_pid = env.req("POST", "/profiles", json={"relation": "self", "label": "나"}).json()["profile_id"]
    kid = env.req("POST", "/profiles", json={"relation": "child", "label": LABEL_SECRET, "age_band": "y3_5"}).json()
    r = env.req("PATCH", f"/profiles/{kid['profile_id']}", json={"age_band": "y6_11"})
    assert r.status_code == 200 and (r.json()["age_band"], r.json()["label"]) == ("y6_11", LABEL_SECRET)
    assert env.req("PATCH", f"/profiles/{kid['profile_id']}", json={"label": None}).json()["label"] is None
    assert env.req("PATCH", f"/profiles/{kid['profile_id']}", json={"relation": "other"}).json()["relation"] == "other"
    assert _err(env.req("PATCH", f"/profiles/{kid['profile_id']}", json={"relation": "self"})) == (409, "SELF_FIXED", ["relation"])
    assert _err(env.req("PATCH", f"/profiles/{me_pid}", json={"relation": "parent"})) == (409, "SELF_FIXED", ["relation"])
    assert _err(env.req("PATCH", f"/profiles/{me_pid}", json={"relation": None})) == (422, "INVALID_REQUEST", ["body"])
    meds = env.req("PATCH", f"/profiles/{me_pid}", json={"medications": [{"input_text": "A"}, {"input_text": "B"}]}).json()
    assert [m["input_text"] for m in meds["medications"]] == ["A", "B"]
    meds = env.req("PATCH", f"/profiles/{me_pid}", json={"medications": [{"input_text": "C"}]}).json()
    assert [m["input_text"] for m in meds["medications"]] == ["C"]  # 목록 전체 교체
    assert _err(env.req("PATCH", "/profiles/not-a-uuid", json={})) == (422, "INVALID_REQUEST", ["profile_id"])
    assert _err(env.req("PATCH", f"/profiles/{UID_B}", json={})) == (404, "NOT_FOUND", [])


def test_delete_profile_rules(env):
    env.onboard()
    me_pid = env.req("POST", "/profiles", json={"relation": "self"}).json()["profile_id"]
    kid = env.req("POST", "/profiles", json={"relation": "child"}).json()["profile_id"]
    assert _err(env.req("DELETE", f"/profiles/{me_pid}")) == (409, "SELF_REQUIRED", [])
    r = env.req("DELETE", f"/profiles/{kid}")
    assert r.status_code == 204 and r.content == b""
    assert _err(env.req("DELETE", f"/profiles/{kid}")) == (404, "NOT_FOUND", [])
    assert [p["relation"] for p in env.req("GET", "/profiles").json()] == ["self"]


def test_other_account_rows_are_404_and_invisible(env):
    env.onboard(TOK_A)
    env.onboard(TOK_B)
    a_pid = env.req("POST", "/profiles", TOK_A, json={"relation": "self", "label": LABEL_SECRET}).json()["profile_id"]
    assert env.req("GET", "/profiles", TOK_B).json() == []
    assert _err(env.req("PATCH", f"/profiles/{a_pid}", TOK_B, json={"label": "x"})) == (404, "NOT_FOUND", [])
    assert _err(env.req("DELETE", f"/profiles/{a_pid}", TOK_B)) == (404, "NOT_FOUND", [])
    assert env.req("GET", "/profiles", TOK_A).json()[0]["label"] == LABEL_SECRET


# --------------------------------------------------------------------------- 철회·재동의
def test_withdraw_sensitive_clears_health_info(env):
    env.onboard(health=True)
    env.req("POST", "/profiles", json={"relation": "self", "pregnancy_status": "pregnant", "medications": [{"input_text": "A"}]})
    body = env.consent(("sensitive_consent", 1, "withdraw"), channel="settings").json()
    assert body["health_consent_active"] is False
    (p,) = env.req("GET", "/profiles").json()
    assert p["pregnancy_status"] is None and p["medications"] == []


def test_withdraw_privacy_deletes_profiles_keeps_account(env):
    env.onboard()
    env.req("POST", "/profiles", json={"relation": "self"})
    env.req("POST", "/profiles", json={"relation": "child"})
    body = env.consent(("privacy_consent", 1, "withdraw"), channel="settings").json()
    assert body["onboarding_step"] == "consent"  # 필수 동의가 빠져 첫 단계로
    assert env.req("GET", "/profiles").json() == [] and env.repo.user_count() == 1  # BE-11-12 A
    assert _err(env.req("POST", "/profiles", json={"relation": "self"})) == (403, "CONSENT_REQUIRED", ["privacy_consent"])


def test_reconsent_only_when_flagged_version_is_published(env):
    env.onboard()
    env.repo.add_document(_doc("terms", 2))  # 경미한 개정: 다시 묻지 않는다
    states = {s["doc_type"]: s for s in env.req("GET", "/me").json()["consents"]}
    assert (states["terms"]["current_version"], states["terms"]["needs_reconsent"]) == (2, False)
    assert env.req("POST", "/profiles", json={"relation": "self"}).status_code == 201
    env.repo.add_document(_doc("terms", 3, requires_reconsent=True))
    me = env.req("GET", "/me").json()
    states = {s["doc_type"]: s for s in me["consents"]}
    assert states["terms"]["needs_reconsent"] and not states["terms"]["needs_consent"] and me["onboarding_step"] == "consent"
    assert _err(env.req("POST", "/profiles", json={"relation": "child"})) == (403, "RECONSENT_REQUIRED", ["terms"])
    assert _err(env.consent(("terms", 2, "agree"), channel="reconsent")) == (409, "VERSION_MISMATCH", ["terms"])
    assert env.consent(("terms", 3, "agree"), channel="reconsent").json()["onboarding_step"] == "family"


def test_sensitive_reconsent_pending_blocks_new_health_writes(env):
    env.onboard(health=True)
    pid = env.req("POST", "/profiles", json={"relation": "self", "pregnancy_status": "pregnant"}).json()["profile_id"]
    env.repo.add_document(_doc("sensitive_consent", 2, requires_reconsent=True))
    assert env.req("GET", "/me").json()["health_consent_active"] is False
    assert env.req("GET", "/profiles").json()[0]["pregnancy_status"] == "pregnant"  # 지우지는 않는다
    assert _err(env.req("PATCH", f"/profiles/{pid}", json={"pregnancy_status": "not_pregnant"})) == \
        (422, "HEALTH_CONSENT_REQUIRED", ["pregnancy_status"])


# --------------------------------------------------------------------------- 탈퇴
def test_delete_me_erases_everything_and_logs_counts_only(env, caplog):
    caplog.set_level(logging.DEBUG)
    env.onboard(health=True)
    env.req("POST", "/profiles", json={"relation": "self", "medications": [{"input_text": MED_SECRET}]})
    env.req("POST", "/profiles", json={"relation": "child", "label": LABEL_SECRET})
    r = env.req("DELETE", "/me")
    assert r.status_code == 204 and r.headers["cache-control"] == "no-store"
    assert env.repo.user_count() == 0
    (row,) = env.repo.deletion_log.values()
    assert (row.deleted_on, row.accounts, row.profiles, row.medications, row.consents) == (NOW.date(), 1, 2, 1, 4)
    assert set(vars(row)) == {"deleted_on", "accounts", "profiles", "medications", "consents"}  # 식별자 칸 없음
    assert "계정 파기: 프로필 2건, 복용 약 1건, 동의 기록 4건" in caplog.text and UID_A not in caplog.text
    assert _err(env.req("GET", "/profiles")) == (401, "AUTH_INVALID", [])  # 남은 토큰으로 다른 API는 401
    assert env.admin.deleted == [UID_A]  # auth.users 삭제까지(BE-11-24 A)
    assert env.req("DELETE", "/me").status_code == 204  # 멱등
    assert next(iter(env.repo.deletion_log.values())).accounts == 1  # 없는 계정은 집계하지 않는다
    # BE-11-24 A: 남은 토큰(만료 전)으로 /me를 불러도 빈 계정이 다시 생기지 않는다(auth.users FK → NO_ACCOUNT → 401)
    assert _err(env.req("GET", "/me")) == (401, "AUTH_INVALID", [])
    assert env.repo.user_count() == 0


# --------------------------------------------------------------------------- 저장소 장애·알 수 없는 규칙
class Broken(InMemoryAccountRepo):
    def __init__(self, exc: Exception) -> None:
        super().__init__(_docs(), clock=lambda: NOW)
        self.exc = exc

    async def ensure_user(self, user_id: str) -> Any:
        raise self.exc


def test_repo_unavailable_is_503_and_unknown_rule_is_500(caplog):
    caplog.set_level(logging.DEBUG)
    e = Env(Broken(RepoUnavailable("OperationalError")))
    assert _err(e.req("GET", "/me")) == (503, "ACCOUNT_UNAVAILABLE", [])
    assert "계정 저장소 응답 없음: OperationalError" in caplog.text
    e = Env(Broken(AccountRepoError("SOMETHING_NEW")))
    assert _err(e.req("GET", "/me")) == (500, "INTERNAL", [])


# --------------------------------------------------------------------------- 로그·본문에 토큰·건강 정보 없음
def test_no_tokens_or_health_values_in_logs_or_error_bodies(env, caplog):
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []
    bodies.append(env.req("POST", "/profiles", json={"relation": "self"}).text)  # 계정 전
    env.onboard()
    bodies.append(env.req("POST", "/profiles", json={"relation": "self", "pregnancy_status": "pregnant",
                                                     "medications": [{"input_text": MED_SECRET}]}).text)
    bodies.append(env.req("POST", "/profiles", json={"relation": "self", "label": LABEL_SECRET * 6}).text)  # 24자 > 20자 → 422
    env.req("POST", "/profiles", json={"relation": "self", "label": LABEL_SECRET})
    bodies.append(env.req("GET", "/me", token=TOK_BAD).text)
    env.req("DELETE", "/me")
    text = caplog.text + "\n".join(bodies)
    for secret in (MED_SECRET, LABEL_SECRET, "pregnant", UID_A, *TOK_A.split("."), *TOK_BAD.split(".")):
        assert secret not in text


# --------------------------------------------------------------------------- /chat 회귀(T5)
def test_chat_does_not_touch_account_repo_or_verifier(env):
    env.onboard()
    calls = env.repo.calls
    verifier_calls = env.verifier.calls
    q = {"question": "타이레놀 먹어도 돼요?", "context": {"pregnant": True}}
    expected = env.c.post("/chat", json=q)
    for token in (TOK_A, TOK_BAD, None):
        r = env.req("POST", "/chat", token=token, json=q)
        assert (r.status_code, r.json()) == (expected.status_code, expected.json()) == (501, {"code": "NOT_IMPLEMENTED", "fields": []})
    assert env.repo.calls == calls and env.verifier.calls == verifier_calls


def test_chat_validation_errors_keep_chat_field_rules(env):
    r = env.c.post("/chat", json={"question": "", "profile_id": "x"})
    body = r.json()
    assert r.status_code == 422 and body["code"] == "INVALID_REQUEST"
    assert "question" in body["fields"] and "profile_id" not in body["fields"]
    assert env.repo.calls == 0


# --------------------------------------------------------------------------- GROUP-03 B1: 성별(sex)·만 14세 확인(age_14)
def test_age_14_withdraw_is_409_use_account_delete(env):
    """PRD-17-12 A: 만 14세 확인은 `terms`처럼 철회 대신 탈퇴로만. 저장소 단계에서도 막는다(SQL 트리거와 같은 규칙)."""
    env.onboard()
    assert _err(env.consent(("age_14", 1, "withdraw"), channel="settings")) == (409, "USE_ACCOUNT_DELETE", ["age_14"])
    with pytest.raises(AccountRepoError) as info:
        asyncio.run(env.repo.add_consents(UID_A, [ConsentInput("age_14", 1, "withdraw")], "settings"))
    assert info.value.code == "USE_ACCOUNT_DELETE"
    assert env.req("GET", "/me").json()["onboarding_step"] == "profile_self"  # 기록이 남지 않아 그대로


def test_first_login_can_send_all_four_consents_at_once(env):
    env.req("GET", "/me")
    r = env.consent(("terms", 1, "agree"), ("privacy_consent", 1, "agree"), ("sensitive_consent", 1, "agree"), ("age_14", 1, "agree"))
    assert r.status_code == 201
    body = r.json()
    assert body["onboarding_step"] == "profile_self" and body["health_consent_active"] is True
    assert env.req("GET", "/legal/age_14", None).json()["required"] is True  # 문서는 게스트도 읽는다


@pytest.mark.parametrize("sex", [None, "female", "male"])
def test_profile_sex_saved_without_health_consent(env, sex):
    """PRD-17-13 A: 성별은 건강 정보가 아니다 → `sensitive_consent` 없이 저장. 보내지 않으면 null(미입력)."""
    env.onboard()  # 건강 정보 동의 없음
    payload: dict[str, Any] = {"relation": "self"} if sex is None else {"relation": "self", "sex": sex}
    r = env.req("POST", "/profiles", json=payload)
    assert r.status_code == 201 and r.json()["sex"] == sex
    assert env.req("GET", "/profiles").json()[0]["sex"] == sex


def test_profile_sex_patch_set_clear_and_untouched(env):
    env.onboard()
    pid = env.req("POST", "/profiles", json={"relation": "child", "sex": "female"}).json()["profile_id"]
    assert env.req("PATCH", f"/profiles/{pid}", json={"label": "첫째"}).json()["sex"] == "female"  # 보내지 않으면 그대로
    assert env.req("PATCH", f"/profiles/{pid}", json={"sex": "male"}).json()["sex"] == "male"
    assert env.req("PATCH", f"/profiles/{pid}", json={"sex": None}).json()["sex"] is None  # null = 지움(미입력)


@pytest.mark.parametrize("bad", ["other", "F", "", 1, "unknown"])
def test_profile_sex_invalid_value_is_422_without_echo(env, bad):
    env.onboard()
    r = env.req("POST", "/profiles", json={"relation": "self", "sex": bad})
    assert _err(r) == (422, "INVALID_REQUEST", ["sex"])
    pid = env.req("POST", "/profiles", json={"relation": "self"}).json()["profile_id"]
    assert _err(env.req("PATCH", f"/profiles/{pid}", json={"sex": bad})) == (422, "INVALID_REQUEST", ["sex"])


def test_profile_sex_needs_privacy_consent_and_is_deleted_on_withdraw(env):
    env.req("GET", "/me")
    env.consent(("terms", 1, "agree"), ("age_14", 1, "agree"))
    assert _err(env.req("POST", "/profiles", json={"relation": "self", "sex": "male"})) == (403, "CONSENT_REQUIRED", ["privacy_consent"])
    env.consent(("privacy_consent", 1, "agree"))
    env.req("POST", "/profiles", json={"relation": "self", "sex": "male"})
    env.consent(("privacy_consent", 1, "withdraw"), channel="settings")
    assert env.req("GET", "/profiles").json() == []  # 성별도 프로필과 함께 지워진다(BE-11-12 A)


def test_sensitive_withdraw_keeps_sex(env):
    env.onboard(health=True)
    env.req("POST", "/profiles", json={"relation": "self", "sex": "female", "pregnancy_status": "pregnant"})
    env.consent(("sensitive_consent", 1, "withdraw"), channel="settings")
    (p,) = env.req("GET", "/profiles").json()
    assert (p["sex"], p["pregnancy_status"]) == ("female", None)  # 건강 정보만 지운다


def test_chat_request_has_no_sex_field():
    """시드 v2 목적 문장 "성별은 … 외부 AI 서비스로 전송하지 않습니다"의 코드 불변식: `/chat` 요청 스키마에 성별 칸이 없고 보내면 422."""
    from app.api.request import ChatRequest, ConversationContext

    for model in (ChatRequest, ConversationContext):
        assert not {"sex", "gender"} & set(model.model_fields)
    e = Env()
    for body in ({"question": "타이레놀 먹어도 돼요?", "context": {"sex": "male"}}, {"question": "타이레놀 먹어도 돼요?", "sex": "male"}):
        r = e.c.post("/chat", json=body)
        assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"


def test_no_code_reads_sex_from_social_login_provider():
    """PRD-17-13 A ②: 간편 로그인(Google·Kakao) 공급자 정보에서 성별을 가져오지 않는다. 서버 코드에 공급자 메타데이터·성별 읽기가 없다."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    pattern = ("user_metadata", "raw_user_meta", "identity_data", "gender", "birthyear", "birthday")
    hits = [f"{p.relative_to(app_dir)}:{w}" for p in app_dir.rglob("*.py") for w in pattern if w in p.read_text(encoding="utf-8").lower()]
    assert hits == []
    # 토큰 검증 결과는 사용자 ID 하나뿐이다(성별을 실어 나를 칸이 없다)
    assert set(auth.Principal.__dataclass_fields__) == {"user_id", "is_guest"}


def test_repo_unavailable_log_has_inner_cause_and_seconds_without_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    e = Env(Broken(RepoUnavailable("ConnectionTimeout", cause="TimeoutError", elapsed_s=4.94)))
    assert _err(e.req("GET", "/me")) == (503, "ACCOUNT_UNAVAILABLE", [])
    assert "계정 저장소 응답 없음: ConnectionTimeout (원인=TimeoutError 4.9s)" in caplog.text


# --------------------------------------------------------------------------- 병아리 배경색 avatar_color(2026-11-23, 8색)

AVATAR_COLORS = ("yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray")


def test_avatar_color_defaults_to_yellow_and_is_in_every_response(env):
    env.onboard()
    created = env.req("POST", "/profiles", json={"relation": "self"})
    assert created.status_code == 201 and created.json()["avatar_color"] == "yellow"
    assert [p["avatar_color"] for p in env.req("GET", "/profiles").json()] == ["yellow"]
    patched = env.req("PATCH", f"/profiles/{created.json()['profile_id']}", json={"label": "나"})
    assert patched.json()["avatar_color"] == "yellow"  # 색을 보내지 않은 수정은 그대로


def test_avatar_color_roundtrip_for_all_eight_without_health_consent(env):
    env.onboard()  # 건강(민감) 동의 없음: 색은 건강 정보가 아니다
    me = env.req("POST", "/profiles", json={"relation": "self", "avatar_color": "coral"}).json()
    assert me["avatar_color"] == "coral"
    for color in AVATAR_COLORS:
        r = env.req("PATCH", f"/profiles/{me['profile_id']}", json={"avatar_color": color})  # 색만 바꾸는 요청
        assert r.status_code == 200 and r.json()["avatar_color"] == color
        assert env.req("GET", "/profiles").json()[0]["avatar_color"] == color
    for color in AVATAR_COLORS[:3]:
        assert env.req("POST", "/profiles", json={"relation": "child", "avatar_color": color}).json()["avatar_color"] == color


@pytest.mark.parametrize("bad", ["red", "Yellow", "", "#ffcc00", None, 3])
def test_avatar_color_outside_the_eight_is_422(env, bad):
    env.onboard()
    pid = env.req("POST", "/profiles", json={"relation": "self"}).json()["profile_id"]
    r = env.req("POST", "/profiles", json={"relation": "child", "avatar_color": bad})
    assert _err(r) == (422, "INVALID_REQUEST", ["avatar_color"])
    r = env.req("PATCH", f"/profiles/{pid}", json={"avatar_color": bad})
    assert _err(r)[:2] == (422, "INVALID_REQUEST")
    assert env.req("GET", "/profiles").json()[0]["avatar_color"] == "yellow"  # 거부된 요청은 저장하지 않는다
    assert "#ffcc00" not in r.text and "Yellow" not in r.text  # 값을 응답에 되돌려 싣지 않는다


def test_avatar_color_of_another_account_is_404_and_unchanged(env):
    env.onboard(TOK_A)
    env.onboard(TOK_B)
    a_pid = env.req("POST", "/profiles", TOK_A, json={"relation": "self", "avatar_color": "blue"}).json()["profile_id"]
    assert _err(env.req("PATCH", f"/profiles/{a_pid}", TOK_B, json={"avatar_color": "pink"})) == (404, "NOT_FOUND", [])
    assert env.req("GET", "/profiles", TOK_A).json()[0]["avatar_color"] == "blue"
    assert env.req("GET", "/profiles", TOK_B).json() == []
