"""AG-01-09 A 이행 시험(goal 3회차 §2-5): 성분 단위(연령·임부) API 병기에서 그 약의 API 성분 코드가 `MAX_API_CODES_PER_DRUG`를 넘어
잘리면 `FILE_ONLY`·`API_SAME`을 붙이지 않고 `API_FAIL`을 붙인다. `API_ONLY`·`API_FAIL`은 그대로다(AG-01-08 A와 같은 원칙).
API 호출 수·파일 판정 상태·`outcome` 값은 바뀌지 않는다. 쌍 규칙(AG-01-04 A)은 건드리지 않는다.

네트워크·원격 DB 호출 0(합성 소사전·소규모 SQLite·가짜 `DurClient`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))

from golden_synth import D_APAP, D_PSE, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.tools import check_contraindications as cc  # noqa: E402
from app.agent.tools.contract import check_items  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402
from app.api.schemas import response_from_state  # noqa: E402
from app.tools.dur import DurRow  # noqa: E402
from app.tools.provenance import FLAG_NOTES  # noqa: E402

T500, COLD = "타이레놀정500밀리그람", "타이레놀콜드-에스정"  # COLD만 API 성분 코드 3개(한도 2 초과). 파일: COLD 임부금기 있음, 연령금기 없음
API_FLAGS = {"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"}
AGE5 = {"value": 5, "unit": "세"}


class _NoRows(FakeDur):
    """합성: 성분 API가 아무것도 돌려주지 않는다(파일에만 있음이 될 결과)."""

    def by_ingredient(self, kind: str, code: str):  # type: ignore[no-untyped-def]
        self.calls.append(("by_ingredient", kind, code))
        return self._res(kind, [], {"ingrCode": code})


class _AgeFound(FakeDur):
    """합성: 물어본 성분(D_APAP)에 연령금기 행이 있다(파일에는 없음 → API에만 있음)."""

    def by_ingredient(self, kind: str, code: str):  # type: ignore[no-untyped-def]
        res = super().by_ingredient(kind, code)
        if kind == "age" and code == D_APAP:
            res = res.model_copy(update={"rows": [DurRow(kind="age", level="ingr", ingr_code=code, age_base="12세 미만", content="합성 연령 문구",
                                                         notification_date_raw="20140109", notification_date="2014-01-09")]})
        return res


class _Down(FakeDur):
    def by_ingredient(self, kind: str, code: str):  # type: ignore[no-untyped-def]
        self.calls.append(("by_ingredient", kind, code))
        raise TimeoutError("합성 실패")


def _check(fd: Any, *names: str, **kw: Any) -> list[dict[str, Any]]:
    ctx = build_tool_context(golden_dict(), mode="service", dur_client=fd, conn_factory=golden_conn)
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": n} for n in names], **kw), ctx)
    assert check_items("check_contraindications", out["items"]) == []
    return out["items"]


def _file(items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(i for i in items if i["kind"] == kind and i.get("source_kind") != "API_DIRECT")


def _api_direct(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [i for i in items if i["kind"] == kind and i.get("source_kind") == "API_DIRECT"]


def _calls(fd: FakeDur, kind: str) -> list[str]:
    return [c[2] for c in fd.calls if c[0] == "by_ingredient" and c[1] == kind]


# --------------------------------------------------------------------------- ① 같음이 될 결과 → API_FAIL
def test_ag01_09_truncated_same_found_is_api_fail_not_same():
    fd = FakeDur()  # 파일 FOUND(슈도에페드린 2등급) + API도 D_PSE 2등급 → 잘림이 없었다면 API_SAME
    items = _check(fd, COLD, pregnancy=True)
    it = _file(items, "pregnancy")
    assert it["status"] == "FOUND"  # 파일 판정은 그대로
    assert API_FLAGS & set(it["flags"]) == {"API_FAIL"}
    assert FLAG_NOTES["API_FAIL"] in it["notes"] and FLAG_NOTES["API_SAME"] not in it["notes"]
    assert it["api"]["codes_truncated"] is True and it["api"]["outcome"] == "BOTH_FOUND"  # outcome 값은 바꾸지 않는다
    assert _calls(fd, "pregnancy") == [D_APAP, D_PSE]  # ④ 호출 수는 한도(2) 그대로(세 번째 성분은 묻지 않는다)
    api = _api_direct(items, "pregnancy")
    assert api and all(API_FLAGS & set(i["flags"]) == {"API_FAIL"} for i in api)  # 같은 함수가 만든 API 항목도 같은 꼬리표


def test_ag01_09_truncated_same_not_listed_is_api_fail_not_same():
    fd = FakeDur()  # 연령: 파일 없음 + API 없음 → 잘림이 없었다면 API_SAME("둘 다 없음")
    it = _file(_check(fd, COLD, age=AGE5), "age")
    assert it["status"] == "NOT_LISTED" and API_FLAGS & set(it["flags"]) == {"API_FAIL"}
    assert it["api"]["codes_truncated"] is True and len(_calls(fd, "age")) == cc.MAX_API_CODES_PER_DRUG == 2


# --------------------------------------------------------------------------- ② 파일에만 있음이 될 결과 → API_FAIL
def test_ag01_09_truncated_file_only_is_api_fail_not_file_only():
    fd = _NoRows()
    items = _check(fd, COLD, pregnancy=True)
    it = _file(items, "pregnancy")
    assert it["status"] == "FOUND" and API_FLAGS & set(it["flags"]) == {"API_FAIL"}
    assert FLAG_NOTES["FILE_ONLY"] not in it["notes"] and it["api"]["codes_truncated"] is True
    assert not _api_direct(items, "pregnancy") and len(_calls(fd, "pregnancy")) == 2


# --------------------------------------------------------------------------- ③ API_ONLY·API_FAIL 유지
def test_ag01_09_truncated_keeps_api_only_signal():
    fd = _AgeFound()
    items = _check(fd, COLD, age=AGE5)
    it = _file(items, "age")
    assert it["status"] == "NOT_LISTED" and API_FLAGS & set(it["flags"]) == {"API_ONLY"}  # 물어본 범위에서 조회된 새 지정 신호는 남긴다
    assert it["api"]["codes_truncated"] is True
    assert all(API_FLAGS & set(i["flags"]) == {"API_ONLY"} for i in _api_direct(items, "age"))


def test_ag01_09_truncated_api_failure_stays_api_fail():
    it = _file(_check(_Down(), COLD, pregnancy=True), "pregnancy")
    assert it["status"] == "FOUND" and API_FLAGS & set(it["flags"]) == {"API_FAIL"} and it["api"]["codes_truncated"] is True


# --------------------------------------------------------------------------- ⑤ 2성분 이하는 기존과 같음
def test_ag01_09_two_or_fewer_codes_keep_existing_flags():
    fd = FakeDur()
    items = _check(fd, T500, pregnancy=True, age=AGE5)  # API 성분 코드 1개
    for kind in ("pregnancy", "age"):
        it = _file(items, kind)
        assert it["status"] == "NOT_LISTED" and API_FLAGS & set(it["flags"]) == {"API_SAME"} and "codes_truncated" not in it["api"]
    assert _calls(fd, "pregnancy") == [D_APAP] and _calls(fd, "age") == [D_APAP]


def test_ag01_09_limit_raised_restores_full_comparison(monkeypatch):
    monkeypatch.setattr(cc, "MAX_API_CODES_PER_DRUG", 3)
    fd = FakeDur()
    it = _file(_check(fd, COLD, pregnancy=True), "pregnancy")
    assert API_FLAGS & set(it["flags"]) == {"API_SAME"} and "codes_truncated" not in it["api"] and len(_calls(fd, "pregnancy")) == 3


def test_ag01_09_pair_rule_is_untouched():
    """쌍 규칙(AG-01-04 A)은 그대로: 잘린 쌍은 `API_PAIR_INCOMPLETE`, 성분 단위만 `API_FAIL`."""
    items = _check(FakeDur(), "이지렉트정1.0밀리그램", COLD, pregnancy=True)
    pair = next(i for i in items if i["kind"] == "contra_pair" and i.get("source_kind") != "API_DIRECT")
    assert API_FLAGS & set(pair["flags"]) == {"API_PAIR_INCOMPLETE"}
    preg = next(i for i in items if i["kind"] == "pregnancy" and i.get("source_kind") != "API_DIRECT" and i["drugs"] == [COLD])
    assert API_FLAGS & set(preg["flags"]) == {"API_FAIL"}


# --------------------------------------------------------------------------- ⑥⑦ 계약 검사
@pytest.mark.parametrize("kind", ["age", "pregnancy"])
@pytest.mark.parametrize("flag,bad", [("FILE_ONLY", True), ("API_SAME", True), ("API_FAIL", False), ("API_ONLY", False), ("API_PAIR_INCOMPLETE", True)])
def test_ag01_09_contract_on_truncated_single_item(kind, flag, bad):
    it = {"kind": kind, "status": "FOUND", "evidence_id": f"{kind}:a", "source": "한국의약품안전관리원", "as_of": "2026-07-21",
          "source_kind": "FILE", "flags": [flag], "matches": [], "api": {"outcome": "x", "codes_truncated": True}}
    problems = check_items("check_contraindications", [it])
    assert bool(problems) is bad
    if flag in ("FILE_ONLY", "API_SAME"):
        assert any("API_FAIL" in p for p in problems)  # 성분 단위 항목의 위반 문구는 API_FAIL을 가리킨다
        assert check_items("check_contraindications", [{**it, "api": {"outcome": "x"}}]) == []  # 잘림이 없으면 규칙 대상이 아니다
    if flag == "API_PAIR_INCOMPLETE":
        assert any("병용 쌍 항목에만" in p for p in problems)  # ⑦ 성분 단위에는 여전히 금지


# --------------------------------------------------------------------------- ⑧ 그래프·응답까지
def test_ag01_09_response_carries_api_fail_notice():
    it = _file(_check(FakeDur(), COLD, pregnancy=True), "pregnancy")
    assert finalize([it])["notice"] == fp.NOTICE_API_FAIL  # 배너는 기존 규칙이 건다(새 문구 없음)

    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    script = [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": COLD}, "c1")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": COLD}], "pregnancy": True}, "c2")]),
        AIMessage("조회를 마쳤다"),
    ]
    draft = {"sentences": [
        {"text": "타이레놀콜드-에스정에 든 성분이 임부금기 목록에 올라 있어요.", "evidence_ids": ["pregnancy:448001ATB"], "claim_type": "fact", "citations": []},
        {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
    ]}
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([draft]), system_prompt="시험용 시스템 프롬프트")
    st = run_question(build_graph(deps), f"임신 중인데 {COLD}을 먹어도 되나요?")
    flags = {f for i in st["evidence"] if i["kind"] == "pregnancy" for f in i["flags"] if f in API_FLAGS}
    assert flags == {"API_FAIL"}
    resp = response_from_state(st)
    assert resp.end_reason == "NORMAL" and resp.notice == fp.NOTICE_API_FAIL
    assert any(f.kind == "pregnancy" and f.bucket == "found" for f in resp.findings)  # 파일 판정(발견)은 그대로 보인다
