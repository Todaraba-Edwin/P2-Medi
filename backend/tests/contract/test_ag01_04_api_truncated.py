"""AG-01-04 A 이행 시험(goal 2회차 §2-5): 한 약의 API 성분 코드가 `MAX_API_CODES_PER_DRUG`를 넘어 잘리면 병용 쌍 항목에
`API_PAIR_INCOMPLETE`를 붙이고 `FILE_ONLY`·`API_SAME`을 붙이지 않는다. API 호출 수와 파일 판정은 그대로다.

네트워크·원격 DB 호출 0(합성 소사전·소규모 SQLite·가짜 `DurClient`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))

from golden_synth import D_APAP, D_DXM, D_PSE, D_RASA, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.wiring import build_tool_context  # noqa: E402
from app.agent.tools import check_contraindications as cc  # noqa: E402
from app.agent.tools.contract import check_items  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402
from app.tools.dur import DurRow  # noqa: E402
from app.tools.provenance import API_REASON_NOTES, FLAG_NOTES  # noqa: E402

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"  # COLD만 API 성분 코드 3개(한도 2 초과)
API_FLAGS = {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"}


def _check(fd: Any, *names: str, **kw: Any) -> list[dict[str, Any]]:
    ctx = build_tool_context(golden_dict(), mode="service", dur_client=fd, conn_factory=golden_conn)
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": n} for n in names], **kw), ctx)
    assert check_items("check_contraindications", out["items"]) == []
    return out["items"]


def _file_pair(items: list[dict[str, Any]]) -> dict[str, Any]:
    return next(i for i in items if i["kind"] == "contra_pair" and i.get("source_kind") != "API_DIRECT")


def _pair_calls(fd: FakeDur) -> list[frozenset[str]]:
    return [frozenset(c[1:]) for c in fd.calls if c[0] == "usjnt_pair_by_ingredient"]


def test_found_pair_with_truncated_codes_is_incomplete_not_file_only():
    fd = FakeDur()
    it = _file_pair(_check(fd, AZI, COLD))
    assert it["status"] == "FOUND"  # 파일 판정은 그대로
    assert API_FLAGS & set(it["flags"]) == {"API_PAIR_INCOMPLETE"}
    assert API_REASON_NOTES["TRUNCATED"] in it["notes"] and FLAG_NOTES["FILE_ONLY"] not in it["notes"]  # 사유별 승인 문구(AG-01-11 A)
    assert it["api"]["codes_truncated"] is True
    assert _pair_calls(fd) == [frozenset({D_RASA, D_APAP}), frozenset({D_RASA, D_PSE})]  # 호출 수 그대로(세 번째 성분은 묻지 않는다)
    assert finalize([it])["notice"] == fp.NOTICE_API_FAIL  # 배너는 기존 규칙이 건다


def test_not_listed_pair_with_truncated_codes_is_incomplete_not_same():
    fd = FakeDur()
    it = _file_pair(_check(fd, T500, COLD))
    assert it["status"] == "NOT_LISTED"
    assert API_FLAGS & set(it["flags"]) == {"API_PAIR_INCOMPLETE"} and FLAG_NOTES["API_SAME"] not in it["notes"]
    assert len(_pair_calls(fd)) == 2 and frozenset({D_APAP, D_DXM}) not in _pair_calls(fd)


def test_two_or_fewer_codes_keep_existing_flags():
    fd = FakeDur()
    it = _file_pair(_check(fd, T500, AZI))  # 두 약 모두 API 성분 코드 1개
    assert it["status"] == "NOT_LISTED" and API_FLAGS & set(it["flags"]) == {"API_SAME"}
    assert "codes_truncated" not in it["api"] and _pair_calls(fd) == [frozenset({D_APAP, D_RASA})]


def test_limit_raised_restores_full_comparison(monkeypatch):
    monkeypatch.setattr(cc, "MAX_API_CODES_PER_DRUG", 3)
    fd = FakeDur()
    it = _file_pair(_check(fd, AZI, COLD))
    assert API_FLAGS & set(it["flags"]) == {"API_SAME"} and "codes_truncated" not in it["api"]
    assert frozenset({D_DXM, D_RASA}) in _pair_calls(fd)


class _ApiFound(FakeDur):
    """합성: 물어본 성분 쌍(D_APAP × D_RASA)이 API에서 조회된다."""

    def usjnt_pair_by_ingredient(self, a: str, b: str):  # type: ignore[no-untyped-def]
        res = super().usjnt_pair_by_ingredient(a, b)
        if {a, b} == {D_APAP, D_RASA}:
            res = res.model_copy(update={"rows": [DurRow(kind="usjnt", level="ingr", ingr_code=a, pair_ingr_code=b, content="합성 사유",
                                                         notification_date_raw="20261101", notification_date="2026-11-01")]})
        return res


class _ApiDown(FakeDur):
    def usjnt_pair_by_ingredient(self, a: str, b: str):  # type: ignore[no-untyped-def]
        self.calls.append(("usjnt_pair_by_ingredient", a, b))
        raise TimeoutError("합성 실패")


def test_truncated_keeps_api_only_and_api_fail_signals():
    """잘렸어도 물어본 범위에서 API만 조회된 신호(`API_ONLY`)와 조회 실패(`API_FAIL`)는 그대로 둔다(금지 대상은 `FILE_ONLY`·`API_SAME`뿐)."""
    items = _check(_ApiFound(), T500, COLD, pregnancy=False)
    assert API_FLAGS & set(_file_pair(items)["flags"]) == {"API_PAIR_INCOMPLETE"}  # T500×COLD: D_APAP끼리라 위 쌍은 묻지 않는다
    items = _check(_ApiFound(), AZI, T500)
    assert API_FLAGS & set(_file_pair(items)["flags"]) == {"API_ONLY"}  # 잘림 없음
    monkey = _ApiDown()
    it = _file_pair(_check(monkey, AZI, COLD))
    assert API_FLAGS & set(it["flags"]) == {"API_FAIL"} and it["status"] == "FOUND"


def test_api_direct_item_of_truncated_pair_carries_incomplete(monkeypatch):
    """파일·API 모두 발견인데 잘림이 있으면 성분 API 항목도 '같아요'가 아니라 미완결 꼬리표다."""

    class _Found(FakeDur):
        def usjnt_pair_by_ingredient(self, a: str, b: str):  # type: ignore[no-untyped-def]
            res = super().usjnt_pair_by_ingredient(a, b)
            if {a, b} == {D_PSE, D_RASA}:
                res = res.model_copy(update={"rows": [DurRow(kind="usjnt", level="ingr", ingr_code=a, pair_ingr_code=b, content="합성 사유",
                                                             notification_date_raw="20171106", notification_date="2017-11-06")]})
            return res

    items = _check(_Found(), AZI, COLD)
    api = [i for i in items if i.get("source_kind") == "API_DIRECT" and i["kind"] == "contra_pair"]
    assert api and all(API_FLAGS & set(i["flags"]) == {"API_PAIR_INCOMPLETE"} for i in [*api, _file_pair(items)])


@pytest.mark.parametrize("flag,bad", [("FILE_ONLY", True), ("API_SAME", True), ("API_PAIR_INCOMPLETE", False), ("API_ONLY", False), ("API_FAIL", False)])
def test_contract_forbids_file_only_and_same_on_truncated_pair(flag, bad):
    it = {"kind": "contra_pair", "status": "FOUND", "evidence_id": "contra_pair:a:b", "source": "한국의약품안전관리원", "as_of": "2026-07-21",
          "source_kind": "FILE", "flags": [flag], "matches": [], "api": {"outcome": "x", "codes_truncated": True}}
    problems = check_items("check_contraindications", [it])
    assert bool(problems) is bad
    assert check_items("check_contraindications", [{**it, "api": {"outcome": "x"}}]) == []  # 잘림이 없으면 규칙 대상이 아니다
