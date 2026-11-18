"""AG-01-10 A(2026-11-17): 실시간 확인을 하지 못한 **사유**(`api.reason`: NO_API_CODE·PARTIAL·TRUNCATED) 기록과 사유별 노트.

꼬리표 이름·도구 출력 계약은 그대로다. 사유별 문구(`provenance.API_REASON_NOTES`)는 AG-01-11 A(2026-11-17)로 **원문 승인**돼
`API_REASON_NOTES_APPROVED = True`이고, 사유가 있는 항목의 노트는 사유별 문구로 나간다. 승인 전 분기(`False`)는 기록용으로 남아
이미 승인된 문구만 쓴다(코드 없음 = `API_FAIL` 문구(중립), 한쪽 실패·잘림 = 지금까지의 꼬리표 문구). 합성 사전·가짜 DurClient(네트워크 0).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))

from golden_synth import APAP, D_APAP, FORM_MAP, FakeDur, _ing, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.wiring import build_tool_context  # noqa: E402
from app.agent.tools import check_contraindications as cc  # noqa: E402
from app.agent.tools.contract import check_items  # noqa: E402
from app.agent.tools.schemas import API_FLAGS, CheckContraArgs  # noqa: E402
from app.tools import provenance as P  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402
from app.tools.dur import SOURCE_INGR, DurResult  # noqa: E402

IBU = "172802ATB"  # KIDS 코드(합성)
COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"


def _dict(ibu_api: list[str]) -> DrugDict:
    ings = [_ing(0, "Acetaminophen", "아세트아미노펜", [APAP], [D_APAP]), _ing(1, "Ibuprofen", "이부프로펜", [IBU], ibu_api)]
    return DrugDict({"meta": {"version": "ag01-10-synth", "built_at": "2026-11-18T00:00:00+00:00", "form_map": FORM_MAP}, "products": [], "ingredients": ings})


def _run(fd: Any, d: DrugDict, *names: str, **kw: Any) -> list[dict[str, Any]]:
    ctx = build_tool_context(d, mode="service", dur_client=fd, conn_factory=golden_conn)
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": n} for n in names], **kw), ctx)
    assert check_items("check_contraindications", out["items"]) == []  # 도구 출력 계약은 그대로 통과한다
    return out["items"]


def _pair(items: list[dict[str, Any]]) -> dict[str, Any]:
    return next(i for i in items if i["kind"] == "contra_pair" and i.get("source_kind") != "API_DIRECT")


class _OneSideDown(FakeDur):
    """두 번째 호출만 실패하는 가짜(쌍의 한쪽 실패)."""

    def usjnt_pair_by_ingredient(self, a: str, b: str) -> DurResult:
        self.calls.append(("usjnt_pair_by_ingredient", a, b))
        if len(self.calls) == 2:
            return DurResult(ok=False, kind="usjnt", level="ingr", source_name=SOURCE_INGR)
        return self._res("usjnt", [], {"ingrCode": a})


# --------------------------------------------------------------------------- 사유 기록

def test_no_api_code_is_recorded_without_any_call():
    fd = FakeDur()
    it = _pair(_run(fd, _dict([]), "아세트아미노펜", "이부프로펜"))
    assert fd.calls == [] and API_FLAGS & set(it["flags"]) == {"API_PAIR_INCOMPLETE"}  # 꼬리표는 그대로
    assert it["api"] == {"outcome": "API_UNAVAILABLE", "reason": P.API_REASON_NO_CODE}


def test_partial_failure_is_recorded():
    fd = _OneSideDown()
    d = DrugDict({"meta": {"version": "s", "built_at": "2026-11-18T00:00:00+00:00", "form_map": FORM_MAP}, "products": [],
                  "ingredients": [_ing(0, "Acetaminophen", "아세트아미노펜", [APAP], [D_APAP]),
                                  _ing(1, "Ibuprofen", "이부프로펜", [IBU], ["D000363", "D000364"])]})
    it = _pair(_run(fd, d, "아세트아미노펜", "이부프로펜"))
    assert len(fd.calls) == 2 and "API_PAIR_INCOMPLETE" in it["flags"] and it["api"]["reason"] == P.API_REASON_PARTIAL


def test_truncated_codes_are_recorded():
    it = _pair(_run(FakeDur(), golden_dict(), AZI, COLD))  # 콜드-에스정은 성분 코드가 한도(2)보다 많다
    assert it["api"]["codes_truncated"] is True and it["api"]["reason"] == P.API_REASON_TRUNCATED and "API_PAIR_INCOMPLETE" in it["flags"]


def test_complete_pair_and_api_off_have_no_reason():
    it = _pair(_run(FakeDur(), _dict(["D000363"]), "아세트아미노펜", "이부프로펜"))
    assert "API_SAME" in it["flags"] and "reason" not in it["api"]
    ctx = build_tool_context(_dict(["D000363"]), mode="eval", conn_factory=golden_conn)  # 평가 모드: 실시간 조회를 끈다
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": "아세트아미노펜"}, {"name": "이부프로펜"}]), ctx)
    assert all("reason" not in (i.get("api") or {}) for i in out["items"])


def test_single_ingredient_without_api_code_records_no_api_code():
    """성분 단위(임부) 병기: 조회 함수는 있는데 그 성분에 조회용 코드가 없으면 호출 0회 + 사유. 꼬리표는 계약대로 `API_FAIL`이다(H20)."""
    fd = FakeDur()
    items = _run(fd, _dict([]), "이부프로펜", pregnancy=True)
    preg = [i for i in items if i["kind"] == "pregnancy" and i.get("source_kind") != "API_DIRECT"]
    assert preg and fd.calls == []
    for it in preg:
        assert "API_FAIL" in it["flags"] and it["api"] == {"outcome": "API_UNAVAILABLE", "reason": P.API_REASON_NO_CODE}


# --------------------------------------------------------------------------- 노트 문구(AG-01-11 A 승인 뒤)

# 승인 원문(AG-01-11 A, 2026-11-17. `tickets/agent/AG-01.md` §6 결정 현황·§3 메모, 로컬 보고 `goal-ag11-prep.md` §5). 글자 하나도 바꾸지 않는다
APPROVED_REASON_NOTES = {
    "NO_API_CODE": "실시간 확인을 하지 못함(이 성분은 실시간 조회에 쓸 코드가 없어요. 파일 기준 결과는 그대로예요)",
    "PARTIAL": "실시간 확인을 하지 못함(쌍의 한쪽 조회에 실패했어요. 파일 기준 결과는 그대로예요)",
    "TRUNCATED": "실시간 확인을 일부만 함(성분이 많아 일부 성분만 조회했어요. 파일 기준 결과는 그대로예요)",
}


def test_reason_notes_match_the_approved_wording_exactly():
    assert P.API_REASON_NOTES_APPROVED is True
    assert P.API_REASON_NOTES == APPROVED_REASON_NOTES == fp.API_REASON_NOTES
    assert "API_REASON_NOTES" not in fp.DRAFT_KEYS


def test_no_code_note_says_the_ingredient_has_no_lookup_code():
    """코드가 없어 묻지 않은 것을 "조회가 빠졌어요"라고 하지 않는다(사용자·요약 모델이 실패로 읽는다, lane-D §2). 승인된 사유별 문구를 쓴다."""
    items = _run(FakeDur(), _dict([]), "아세트아미노펜", "이부프로펜")
    it = _pair(items)
    assert it["notes"] == [APPROVED_REASON_NOTES["NO_API_CODE"]]
    resp = finalize(items)
    notes = [n for e in resp["entries"] for n in e["notes"]]
    assert APPROVED_REASON_NOTES["NO_API_CODE"] in notes and not any("빠졌" in n for n in notes)
    assert P.FLAG_NOTES["API_PAIR_INCOMPLETE"] not in notes and P.FLAG_NOTES["API_FAIL"] not in notes
    assert resp["notice"] == fp.NOTICE_API_FAIL  # 배너는 그대로(실시간 확인이 안 된 것은 사실이다)


def test_partial_failure_note_says_one_side_failed():
    fd = _OneSideDown()
    d = DrugDict({"meta": {"version": "s", "built_at": "2026-11-18T00:00:00+00:00", "form_map": FORM_MAP}, "products": [],
                  "ingredients": [_ing(0, "Acetaminophen", "아세트아미노펜", [APAP], [D_APAP]),
                                  _ing(1, "Ibuprofen", "이부프로펜", [IBU], ["D000363", "D000364"])]})
    it = _pair(_run(fd, d, "아세트아미노펜", "이부프로펜"))
    assert it["notes"][-1] == APPROVED_REASON_NOTES["PARTIAL"]
    assert APPROVED_REASON_NOTES["PARTIAL"] in [n for e in finalize([it])["entries"] for n in e["notes"]]


def test_truncated_note_says_only_some_ingredients_were_queried():
    it = _pair(_run(FakeDur(), golden_dict(), AZI, COLD))
    assert it["notes"][-1] == APPROVED_REASON_NOTES["TRUNCATED"]
    assert APPROVED_REASON_NOTES["TRUNCATED"] in [n for e in finalize([it])["entries"] for n in e["notes"]]
    assert finalize([it])["notice"] == fp.NOTICE_API_FAIL


@pytest.mark.parametrize("flag,reason,want", [
    ("API_PAIR_INCOMPLETE", "NO_API_CODE", "NO_API_CODE"), ("API_FAIL", "NO_API_CODE", "NO_API_CODE"),
    ("API_PAIR_INCOMPLETE", "PARTIAL", "PARTIAL"), ("API_PAIR_INCOMPLETE", "TRUNCATED", "TRUNCATED"),
    ("API_FAIL", "TRUNCATED", "TRUNCATED"), ("API_FAIL", "PARTIAL", "PARTIAL"),
])
def test_note_table_after_approval_uses_reason_notes(flag, reason, want):
    assert P.API_REASON_NOTES_APPROVED is True
    assert P.api_flag_note(flag, reason) == APPROVED_REASON_NOTES[want]


@pytest.mark.parametrize("flag,reason", [
    ("API_PAIR_INCOMPLETE", None), ("API_FAIL", None), ("API_FAIL", "모르는값"), ("API_SAME", "NO_API_CODE"), ("FILE_ONLY", "TRUNCATED"),
])
def test_note_table_without_reason_is_unchanged(flag, reason):
    """사유가 없거나 모르는 값, 실시간 확인 꼬리표가 아닌 경우는 승인 전후 모두 지금까지의 꼬리표 문구 그대로다."""
    assert P.api_flag_note(flag, reason) == P.FLAG_NOTES[flag]


@pytest.mark.parametrize("flag,reason,want", [
    ("API_PAIR_INCOMPLETE", "NO_API_CODE", "API_FAIL"), ("API_FAIL", "NO_API_CODE", "API_FAIL"),
    ("API_PAIR_INCOMPLETE", "PARTIAL", "API_PAIR_INCOMPLETE"), ("API_PAIR_INCOMPLETE", "TRUNCATED", "API_PAIR_INCOMPLETE"),
    ("API_FAIL", "TRUNCATED", "API_FAIL"), ("API_PAIR_INCOMPLETE", None, "API_PAIR_INCOMPLETE"), ("API_FAIL", "모르는값", "API_FAIL"),
    ("API_SAME", "NO_API_CODE", "API_SAME"),
])
def test_pre_approval_branch_kept_for_record(flag, reason, want, monkeypatch):
    """스위치를 False로 되돌리면 승인 전 중립 문구 표로 돌아간다(기록용. 서비스는 True다)."""
    monkeypatch.setattr(P, "API_REASON_NOTES_APPROVED", False)
    assert P.api_flag_note(flag, reason) == P.FLAG_NOTES[want]


def test_finalize_without_reason_is_unchanged():
    it = {"kind": "contra_pair", "status": "NOT_LISTED", "evidence_id": "contra_pair:a:b", "flags": ["API_PAIR_INCOMPLETE"], "matches": [],
          "source": "한국의약품안전관리원", "as_of": "2026-07-31", "source_kind": "FILE", "dataset_key": "contra_pair", "drugs": ["가", "나"],
          "api": {"outcome": "API_UNAVAILABLE"}}
    assert P.FLAG_NOTES["API_PAIR_INCOMPLETE"] in finalize([it])["entries"][0]["notes"]
    assert P.FLAG_NOTES["API_PAIR_INCOMPLETE"] in finalize([{**it, "api": None}])["entries"][0]["notes"]


# --------------------------------------------------------------------------- 문구 안전 불변식

def test_reason_notes_cover_every_reason_and_are_not_drafts():
    assert "API_REASON_NOTES" not in fp.DRAFT_KEYS and set(fp.API_REASON_NOTES) == set(P.API_REASONS)
    assert fp.API_REASON_NOTES == P.API_REASON_NOTES


def test_reason_notes_make_no_safety_claim_and_use_no_code_names():
    for text in fp.API_REASON_NOTES.values():
        assert "파일 기준 결과는 그대로예요" in text
        assert not any(w in text for w in ("안전", "괜찮", "문제없", "NO_API_CODE", "PARTIAL", "TRUNCATED", "API", "DUR"))
        assert not any(t in text for t in fp.FORBIDDEN_SCREEN_TERMS)
    assert "빠졌" not in fp.API_REASON_NOTES["NO_API_CODE"]
