"""AG-09 근거 없음 처리 시험(2026-11-18 보강분 + §2 조건의 직접 비교 시험). LLM·네트워크·원격 DB 호출 0.

- ⑪ `UNCONFIRMED_AS_FACT`: 확인하지 못한 항목(검색 0건·약 미식별)만 인용한 사실 문장을 거른다. "찾지 못했다"고 말하는 문장은 그대로 둔다.
- ⑫ `REFERENCE_AS_VERDICT`: 참고 전용·코드 미연결·미식별 항목을 인용해 금기 여부를 확정한 문장을 거른다(BE-10-08 A·BE-10-09 A).
- 문구 직접 비교: 금기 목록에 없음 대 약 미식별 대 코드 없음 대 허가사항 항목 미확보. 모두 안전 암시가 없고 약사 확인 안내가 붙는다.
- 코드 미연결 제품에는 "자료에서 찾지 못했어요·제품명을 다시 알려 주세요"를 붙이지 않는다(사전에 있는 약이다).
- 안내 문구 통일: 응답 상수에 "공식 사이트"가 없고, "의사"가 나오는 상수는 아래 목록뿐이다(승인 문구, 바꾸려면 사용자 결정).
- 응급인데 약 이름이 없을 때 약 이름을 묻는 문장은 초안이라 승인 전에는 답이 지금까지와 같다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import validator as V  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.pipeline.build import build_for_condition  # noqa: E402
from app.agent.tools import check_contraindications as cc  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402

KDB = "한국의약품안전관리원"
ADVICE = {"text": "정확한 확인은 약국·약사에게 하세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


def _item(kind: str, status: str, eid: str, *, flags: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    base = {"kind": kind, "status": status, "evidence_id": eid, "flags": list(flags or []), "matches": [], "subject": ["가나정"], "drugs": ["가나정"],
            "source": KDB if status in ("FOUND", "NOT_LISTED") else None, "as_of": "2026-07-21" if status in ("FOUND", "NOT_LISTED") else None,
            "source_kind": "FILE" if status in ("FOUND", "NOT_LISTED") else None, "dataset_key": kind if status in ("FOUND", "NOT_LISTED") else None}
    return {**base, **kw}


def _sent(text: str, ids: list[str], claim: str = "fact") -> dict[str, Any]:
    return {"text": text, "evidence_ids": ids, "claim_type": claim, "citations": []}


def _checks(sentences: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[str]:
    return [i.check for i in V.validate({"sentences": sentences}, items).issues if i.action == "DROPPED"]


# --------------------------------------------------------------------------- ⑪ 확인하지 못한 항목만 인용한 사실 문장

MISS = _item("search_miss", "NO_EVIDENCE", "search:search_label:aaa", missing_reason="SEARCH_MISS")
UNID = _item("identify", "UNIDENTIFIED", "identify:가나정", input_name="가나정")
PREG = _item("pregnancy", "FOUND", "pregnancy:1", matches=[{"grade": "2", "detail": "임부에 대한 안전성 미확립.", "row_evidence_id": "pregnancy:1#a"}])


@pytest.mark.parametrize("text,item", [
    ("가나정은 위장 장애를 일으킬 수 있어요.", MISS),
    ("가나정은 감기 증상을 줄여 주는 약이에요.", UNID),
    ("가나정은 임신 중에 주의가 필요한 약으로 조회됐어요.", UNID),
])
def test_fact_citing_only_unconfirmed_items_is_dropped(text, item):
    assert _checks([_sent(text, [item["evidence_id"]]), ADVICE], [item]) == [V.UNCONFIRMED_AS_FACT]


@pytest.mark.parametrize("text,item", [
    ("가나정은 자료에서 찾지 못했어요.", UNID),
    ("허가사항에서 관련 내용을 확인하지 못했어요.", MISS),
    (fp.MISSING_SEARCH_MISS, MISS),                      # 승인된 미확보 문구 그대로
    ("가나정에 대해서는 확인할 수 없어요.", UNID),
])
def test_saying_it_could_not_be_confirmed_is_kept(text, item):
    assert V.UNCONFIRMED_AS_FACT not in _checks([_sent(text, [item["evidence_id"]]), ADVICE], [item])


def test_fact_with_at_least_one_confirmed_item_and_guidance_are_not_touched():
    items = [PREG, MISS]
    assert _checks([_sent("가나정은 임부금기 목록에 올라 있어요.", ["pregnancy:1", MISS["evidence_id"]]), ADVICE], items) == []
    assert _checks([_sent("복용 전에 약국·약사에게 확인하세요.", [MISS["evidence_id"]], "guidance")], [MISS]) == []
    assert _checks([_sent("가나정은 임부금기 목록에 올라 있어요.", ["pregnancy:1"]), ADVICE], items) == []


def test_corpus_chunk_is_a_confirmed_source():
    chunk = {"kind": "chunk", "status": "FOUND", "evidence_id": "l3:1", "flags": [], "matches": [], "text": "이 약은 졸음을 일으킬 수 있다.",
             "source_kind": "CORPUS_QUOTE", "dataset_key": "prmsn", "source": "식품의약품안전처", "as_of": "2026-07-21"}
    assert V._is_unconfirmed(chunk) is False
    assert _checks([_sent("허가사항에는 졸음이 올 수 있다고 적혀 있어요.", ["l3:1"]), ADVICE], [chunk]) == []


# --------------------------------------------------------------------------- ⑫ 참고 전용·코드 미연결 항목으로 금기를 확정

REF = _item("age", "UNIDENTIFIED", "age:가나정", flags=["CODE_NOT_LINKED", "REFERENCE_ONLY"])
REF_FOUND = _item("age", "FOUND", "age:found", flags=["REFERENCE_ONLY"], matches=[{"detail": "12세 미만 금기", "row_evidence_id": "age:found#a"}])


@pytest.mark.parametrize("text", ["가나정은 연령금기예요.", "가나정은 금기 목록에 없어요.", "가나정은 연령금기에 해당합니다.", "가나정은 금기가 아니에요."])
@pytest.mark.parametrize("item", [REF, REF_FOUND], ids=["unidentified", "found-but-reference-only"])
def test_verdict_on_reference_only_item_is_dropped(text, item):
    got = _checks([_sent(text, [item["evidence_id"]]), ADVICE], [item])
    assert got and got[0] in (V.REFERENCE_AS_VERDICT, V.SAFE_ASSERTION, V.MISSING_IMPLIES_NONE)
    assert V.validate({"sentences": [_sent(text, [item["evidence_id"]]), ADVICE]}, [item]).kept == [ADVICE]


def test_verdict_rule_names_the_new_check_for_plain_definitive_sentences():
    assert _checks([_sent("가나정은 연령금기예요.", ["age:found"]), ADVICE], [REF_FOUND]) == [V.REFERENCE_AS_VERDICT]
    assert _checks([_sent("가나정은 금기 목록에 없어요.", [UNID["evidence_id"]]), ADVICE], [UNID]) == [V.REFERENCE_AS_VERDICT]


def test_reference_note_and_confirmed_verdict_are_kept():
    ok = "가나정은 다른 제형에서 목록에 있어 참고로만 보여 드려요. 이 제품에 대한 판정은 아니에요."
    assert _checks([_sent(ok, ["age:found"]), ADVICE], [REF_FOUND]) == []
    real = _item("age", "FOUND", "age:1", matches=[{"detail": "12세 미만 금기", "row_evidence_id": "age:1#a"}])
    assert _checks([_sent("가나정은 연령금기 목록에 있어요.", ["age:1"]), ADVICE], [real]) == []


def test_new_checks_have_no_harness_rule_number_and_are_counted_in_the_event():
    res = V.validate({"sentences": [_sent("가나정은 위장 장애를 일으킬 수 있어요.", [MISS["evidence_id"]]), ADVICE]}, [MISS])
    assert res.events[-1]["reasons"][V.UNCONFIRMED_AS_FACT] == 1 and res.events[-1]["rules"] == {}
    assert V.UNCONFIRMED_AS_FACT not in V.CHECK_RULES and V.REFERENCE_AS_VERDICT not in V.CHECK_RULES


# --------------------------------------------------------------------------- 문구 직접 비교(§2 31·32·38줄)

def _entry(it: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    resp = finalize([it])
    return resp["entries"][0], resp


def test_not_listed_unidentified_no_code_and_missing_texts_all_differ():
    not_listed, r1 = _entry(_item("pregnancy", "NOT_LISTED", "pregnancy:1"))
    unidentified, r2 = _entry(UNID)
    no_code, r3 = _entry(_item("pregnancy", "UNIDENTIFIED", "pregnancy:x", flags=["CODE_NOT_LINKED"]))
    missing, r4 = _entry(_item("label", "NO_EVIDENCE", "label:x", missing_reason="SEARCH_MISS"))
    assert not_listed["text"] == fp.NOT_LISTED and "안전하다는 뜻이 아님" in not_listed["text"]
    assert unidentified["text"] == fp.UNIDENTIFIED and missing["text"] == fp.MISSING_SEARCH_MISS
    assert fp.CODE_NOT_LINKED in no_code["notes"]
    shown = [not_listed["text"], unidentified["text"], missing["text"], " ".join([no_code["text"], *no_code["notes"]])]
    assert len(set(shown)) == 4  # 네 경우의 화면 글자가 모두 다르다
    for e, resp in ((unidentified, r2), (no_code, r3), (missing, r4)):
        assert e["bucket"] == "unconfirmed" and "금기 목록에 없" not in " ".join([e["text"], *e["notes"]])
        assert fp.NOT_LISTED not in resp["text"]
        assert resp["pharmacist_advice"] and any("약국·약사" in a for a in resp["pharmacist_advice"])  # 근처 약국·약사 확인 안내
    for text in (" ".join([e["text"], *e["notes"]]) for e in (unidentified, no_code, missing)):
        assert not any(w in text for w in ("안전합니다", "안전해요", "괜찮", "문제없", "의사", "공식 사이트"))


def test_code_not_linked_product_gets_no_could_not_find_guidance():
    """사전에 있는 약(찾음)인데 금기 목록과 이을 코드가 없는 경우: "자료에서 찾지 못했어요·제품명을 다시 알려 주세요"를 붙이지 않는다."""
    for kind in ("identify", "pregnancy"):
        e, resp = _entry(_item(kind, "UNIDENTIFIED", f"{kind}:x", flags=["CODE_NOT_LINKED"], input_name="가나정"))
        assert e["bucket"] == "unconfirmed" and fp.CODE_NOT_LINKED in e["notes"]
        assert not e.get("why") and not e.get("next") and not e.get("sub_line")
        assert fp.UNIDENTIFIED_WHY not in resp["text"] and fp.UNIDENTIFIED_NEXT not in resp["text"]
    plain, resp = _entry(UNID)  # 진짜 미식별은 안내가 그대로 붙는다
    assert plain["why"] == fp.UNIDENTIFIED_WHY and plain["next"] == fp.UNIDENTIFIED_NEXT and "가나정" in plain["sub_line"]


# --------------------------------------------------------------------------- 다중 약 일부 미식별(§2 33·39줄): 실제 도구로

def test_one_unknown_drug_in_a_pair_is_shown_as_pair_not_checked_by_the_real_tool():
    ctx = build_tool_context(golden_dict(), mode="eval", conn_factory=golden_conn)
    out = cc.check_contraindications(CheckContraArgs(drugs=[{"name": "뿌셔캡슐"}, {"name": "타이레놀정500밀리그람"}]), ctx)
    pair = [i for i in out["items"] if i["kind"] == "contra_pair"]
    assert len(pair) == 1 and pair[0]["status"] == "UNIDENTIFIED" and pair[0]["flags"] == ["PAIR_NOT_CHECKED"]
    assert not any(i["status"] == "NOT_LISTED" and i["kind"] == "contra_pair" for i in out["items"])
    resp = finalize(out["items"])
    texts = [e["text"] for e in resp["entries"]]
    assert fp.PAIR_NOT_CHECKED in texts and fp.UNIDENTIFIED in texts
    unknown = next(e for e in resp["entries"] if e["text"] == fp.UNIDENTIFIED)
    assert "뿌셔캡슐" in (unknown.get("sub_line") or "") + str(unknown.get("drug"))
    assert not any(t in resp["text"] for t in fp.FORBIDDEN_SCREEN_TERMS)
    assert "금기 목록에 없음" not in " ".join(e["text"] for e in resp["entries"] if "뿌셔캡슐" in str(e.get("drug")))


# --------------------------------------------------------------------------- 안내 문구 통일(§2 34·38줄)

# "의사"가 들어간 응답 상수(2026-11-18 현재). 모두 사용자 승인 문구다. 거절 문구는 처방·감량·진단 맥락이라 의사를 가리키는 것이 맞고,
# 나머지 둘은 "근처 약국·약사" 통일 규칙과 어긋나 보고의 결정 후보로 올렸다. 이 목록 밖에서 "의사"가 생기면 이 시험이 알린다.
DOCTOR_ALLOWED = {"DOSE_QUOTE_NOTICE", "FLAG_LINES.FILE_ONLY", "FLAG_NOTES.FILE_ONLY",  # FLAG_NOTES는 FLAG_LINES의 원본(같은 문장)
                  *(f"REFUSE_MESSAGES.{k}" for k in ("STOP_DOSE_CHANGE", "ASSESS_STATE", "HIDE_FROM_DOCTOR", "DIAGNOSIS", "PRESCRIPTION", "DOSAGE"))}


def _phrase_constants() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in dir(fp):
        if not name.isupper():
            continue
        v = getattr(fp, name)
        if isinstance(v, str):
            out[name] = v
        elif isinstance(v, dict):
            out.update({f"{name}.{k}": x for k, x in v.items() if isinstance(x, str)})
        elif isinstance(v, (tuple, list)):
            out.update({f"{name}[{i}]": x for i, x in enumerate(v) if isinstance(x, str)})
    return out


def test_no_official_site_guidance_and_doctor_only_in_listed_constants():
    consts = _phrase_constants()
    assert len(consts) > 60
    assert [k for k, v in consts.items() if "공식 사이트" in v or "공식사이트" in v] == []
    with_doctor = {k for k, v in consts.items() if "의사" in v.replace("주의사항", "") and not k.startswith(("FORBIDDEN_", "DISCLAIMER", "FIXED_NOTICE"))}
    assert with_doctor <= DOCTOR_ALLOWED, f"목록 밖에서 '의사' 안내가 생겼다: {sorted(with_doctor - DOCTOR_ALLOWED)}"


def test_unconfirmed_guidance_points_to_pharmacy_and_pharmacist():
    for name in ("PHARMACIST_ADVICE", "PHARMACIST_ADVICE_FIXED", "PHARMACIST_ADVICE_NO_NAMES"):
        v = getattr(fp, name)
        assert "약국" in v and "약사" in v and "의사" not in v


# --------------------------------------------------------------------------- 응급인데 약 이름이 없음(§2 36줄, TC-11): 문구는 초안

def _graph(condition: str) -> Any:
    dd = golden_dict()
    deps = build_deps(dd, build_tool_context(dd, mode="eval", conn_factory=golden_conn),
                      tool_model=ScriptedToolModel(script=[AIMessage("조회를 마쳤다")], repeat_last=True),
                      summary_model=ScriptedSummary([{"sentences": [ADVICE]}]))
    return build_graph(deps) if condition == "C2" else build_for_condition(deps, condition)


Q_EMERGENCY_NO_DRUG = "아이가 약을 삼켰어요 숨쉬기 힘들어해요"  # 합성 질문(약 이름 없음)


# 승인 원문(AG-01-11 A, 2026-11-17. `tickets/agent/AG-01.md` §6·§3, 로컬 보고 `goal-ag11-prep.md` §5). 글자 하나도 바꾸지 않는다
APPROVED_ASK_DRUG_NAME = "어떤 약을 먹었는지 약 이름을 알려 주시면 금기 여부를 확인해 드려요."


def test_ask_phrase_matches_the_approved_wording_and_is_not_a_draft():
    assert fp.EMERGENCY_ASK_DRUG_NAME == APPROVED_ASK_DRUG_NAME
    assert "EMERGENCY_ASK_DRUG_NAME" not in fp.DRAFT_KEYS


@pytest.mark.parametrize("condition", ["C2", "C1"])
def test_emergency_without_drug_name_keeps_119_on_top_and_asks_for_the_drug_name(condition):
    """TC-11: 응급인데 약 이름이 없으면 119 안내는 그대로 맨 위, 약 이름을 묻는 문장이 요약(119 아래)에 붙는다(AG-01-11 A 코드 반영 2026-11-18)."""
    st = run_question(_graph(condition), Q_EMERGENCY_NO_DRUG)
    a = st["answer"]
    assert st["emergency"] is True and not any(e["status"] == "RESOLVED" for e in st["entities"])  # 확정된 약이 없다
    lines = a["text"].splitlines()
    assert lines[0] == fp.EMERGENCY_119 and fp.FIXED_NOTICE in a["text"]
    assert APPROVED_ASK_DRUG_NAME in (a["summary"] or "")
    assert lines.index(next(x for x in lines if APPROVED_ASK_DRUG_NAME in x)) > 0  # 119보다 위에 오지 않는다


@pytest.mark.parametrize("condition", ["C2", "C1"])
def test_putting_the_phrase_back_on_the_draft_list_restores_the_previous_answer(condition, monkeypatch):
    """`DRAFT_KEYS`에 다시 올리면 지금까지와 같은 답(119 + 고정 문구, 묻는 문장 없음)으로 돌아간다(초안 장치는 그대로 산다)."""
    monkeypatch.setattr(fp, "DRAFT_KEYS", (*fp.DRAFT_KEYS, "EMERGENCY_ASK_DRUG_NAME"))
    a = run_question(_graph(condition), Q_EMERGENCY_NO_DRUG)["answer"]
    assert a["text"].splitlines()[0] == fp.EMERGENCY_119 and fp.EMERGENCY_ASK_DRUG_NAME not in a["text"]


def test_ask_line_is_not_added_when_a_drug_was_named_or_not_an_emergency():
    assert fp.EMERGENCY_ASK_DRUG_NAME in finalize([], emergency=True, emergency_no_drug=True)["summary"]
    assert finalize([], emergency=False, emergency_no_drug=True)["summary"] is None
    assert finalize([], emergency=True)["summary"] is None
    assert fp.EMERGENCY_ASK_DRUG_NAME not in (finalize([], emergency=True, emergency_no_drug=True, refuse_reason="DOSAGE")["summary"] or "")
    assert fp.EMERGENCY_ASK_DRUG_NAME not in str(finalize([], emergency=True, emergency_no_drug=True, limit_reached=True)["summary"])


def test_ask_line_is_appended_after_the_model_summary():
    s = finalize([], "모델 요약 문장이에요.", emergency=True, emergency_no_drug=True)["summary"]
    assert s == f"모델 요약 문장이에요. {fp.EMERGENCY_ASK_DRUG_NAME}"


def test_ask_phrase_has_no_contact_or_safety_wording():
    t = fp.EMERGENCY_ASK_DRUG_NAME
    assert "약 이름" in t and not any(w in t for w in ("안전", "괜찮", "1339", "병원", "의사", "드세요", "먹어도"))
