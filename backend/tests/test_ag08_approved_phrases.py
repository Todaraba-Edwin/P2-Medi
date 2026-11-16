"""AG-08 승인 문구·라벨 이행과 BE-06-13~17 서버 상수 칸 시험(합성 items[], LLM·외부 호출 없음).

- 문장은 `tickets/agent/AG-08.md` §5 "승인 문구 원본(2026-11-12, 0-E)" 표와 `P2-doc/PJ2-Agent-Harness.md` 3.4절 표의 글자 그대로인지 본다.
- 모든 화면 글자는 코드 상수에서 나오고 모델 출력으로 바뀌지 않는다. 판정(묶음·상태)은 이 변경으로 달라지지 않는다.
"""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent import finalize as fz
from app.agent import fixed_phrases as fp
from app.agent import josa
from app.agent.finalize import finalize
from app.api import events as ev
from app.api import schemas as sc
from app.api.schemas import ChatResponse, DetailItem, Emergency, Finding, GradeDef, Ingredient, to_chat_response
from app.tools.provenance import FLAG_NOTES, SOURCE_KIND_PREFIX

ROOT = Path(__file__).resolve().parents[2]
KIDS = "한국의약품안전관리원"


def _doc(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        pytest.skip(f"문서 없음: {rel}")
    return p.read_text(encoding="utf-8")


def _pair(status="FOUND", flags=None, eid="contra_pair:1", drugs=("와파린정", "아스피린정")):
    m = [{"row_key": "rk1", "row_evidence_id": eid + "#a", "reason": "출혈 위험", "notice_no": "제2026-1호"}] if status == "FOUND" else []
    return {"kind": "contra_pair", "status": status, "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": flags or [], "matches": m, "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": list(drugs)}


def _pair_not_checked(a="가나다정", b="사아자시럽"):
    """`check_contraindications._pair_not_checked`가 내는 모양."""
    return {"kind": "contra_pair", "status": "UNIDENTIFIED", "subject": [a, b], "evidence_id": f"contra_pair:{a}:{b}", "source": None,
            "as_of": None, "queried_at_utc": None, "flags": ["PAIR_NOT_CHECKED"], "matches": [], "dataset_key": None, "source_kind": None,
            "drugs": [a, b], "drug_keys": [a, b], "notes": []}


def _preg(matches=None, eid="pregnancy:1"):
    m = matches if matches is not None else [{"grade": "2", "row_key": "r", "row_evidence_id": eid + "#a"}]
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["333333ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "matches": m, "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["타이레놀콜드정"]}


def _age(rows=((12, "세", "미만"),), eid="age:1"):
    m = [{"age_value": v, "age_unit": u, "age_cond": c, "row_key": f"r{i}", "row_evidence_id": f"{eid}#{i}"} for i, (v, u, c) in enumerate(rows)]
    return {"kind": "age", "status": "FOUND", "subject": ["444444ATB"], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "matches": m, "dataset_key": "age", "source_kind": "FILE", "drugs": ["어린이약"]}


def _unid(name="뿌셔캡슐"):
    return {"kind": "identify", "status": "UNIDENTIFIED", "subject": [name], "evidence_id": f"identify:{name}", "source": None, "as_of": None,
            "flags": [], "matches": [], "dataset_key": None, "source_kind": None, "input_name": name, "searched": [{"dataset": "허가정보", "count": 0}],
            "retried": False}


def _ident(name="타이레놀정500", ingredients=("아세트아미노펜",)):
    return {"kind": "identify", "status": "FOUND", "subject": [name], "evidence_id": f"identify:{name}", "source": "식약처", "as_of": "2026-11-01",
            "flags": [], "matches": [], "dataset_key": "identify", "source_kind": "FILE", "name": name, "matched_by": "product_name",
            "ingredients": [{"display": n, "name_ko": n} for n in ingredients]}


def _label(section="용법용량", flags=None, name="이지렉트정", text="성인 1회 1정"):
    return {"kind": "label", "status": "FOUND", "subject": ["202106954"], "evidence_id": f"prmsn:202106954:{section}", "source": "식약처 의약품 제품 허가정보",
            "as_of": None, "queried_at_utc": "2026-11-09T02:00:00Z", "flags": flags or [], "dataset_key": "prmsn", "source_kind": "API_DIRECT",
            "label_source": "허가정보 상세", "item_seq": "202106954", "section": section, "is_label": True, "name": name,
            "matches": [{"row_key": "u0", "row_evidence_id": f"prmsn:202106954:{section}#0", "text": text}]}


# =========================================================================== 1. AG-08-07 A
def test_ag08_07_refuse_stop_and_assess_are_not_draft():
    assert "STOP_DOSE_CHANGE" not in fp.DRAFT_KEYS and "ASSESS_STATE" not in fp.DRAFT_KEYS
    assert "STOP_DOSE_CHANGE" not in fp.REFUSE_DRAFT_KEYS and "ASSESS_STATE" not in fp.REFUSE_DRAFT_KEYS
    assert set(fp.REFUSE_DRAFT_KEYS) | set(fp.REFUSE_APPROVED_KEYS) == set(fp.REFUSE_MESSAGES)
    assert not set(fp.REFUSE_DRAFT_KEYS) & set(fp.REFUSE_APPROVED_KEYS)
    harness = _doc("P2-doc/PJ2-Agent-Harness.md")
    for key in fp.REFUSE_APPROVED_KEYS:  # 하네스 4.4절에 적힌 사용자 결정 문구와 글자 일치
        assert fp.REFUSE_MESSAGES[key] in harness


# =========================================================================== 2. AG-08-10 B
def test_ag08_10_dup_ingredient_label():
    assert fp.CAUTION_LABELS["dup_ingredient"] == "성분 중복"
    it = {**_age(), "kind": "dup_ingredient", "dataset_key": "dup_ingredient"}
    badge = finalize([it], None, emergency=False)["badges"][0]["text"]
    assert badge == "성분 중복" and "삐!" not in badge


# =========================================================================== 3. AG-08-15 B
@pytest.mark.parametrize("name,particle", [
    ("뿌셔캡슐", "을"), ("타이레놀정", "을"), ("게보린", "을"),            # 받침 있음
    ("판콜에이", "를"), ("부루펜시럽키즈", "를"), ("아스피린프로텍트", "를"),  # 받침 없음
    ("Tylenol ER", "을"), ("TYLENOL", "을"), ("Advil", "을"), ("ABC", "를"), ("Vitamin D", "를"),  # 영문(마지막 글자 이름)
    ("타이레놀정500", "을"), ("게보린2", "를"), ("판콜3", "을"), ("약9", "를"),  # 숫자(영·이·삼·구)
    ("타이레놀정500mg", "을"), ("시럽5ml", "를"), ("아목시실린250 mg", "을"),   # 단위(그램·리터)
    ("타이레놀정(아세트아미노펜)", "을"), ("콜드-에스 ", "를"),                # 끝의 괄호·공백은 건너뛴다
])
def test_ag08_15_object_particle_by_last_sound(name, particle):
    assert josa.eul_reul(name) == particle
    resp = finalize([_unid(name)], None, emergency=False)
    advice = resp["pharmacist_advice"][0]
    assert advice == fp.PHARMACIST_ADVICE.replace("{drugs}을(를)", name + particle)
    assert "을(를)" not in resp["text"] and "을(를)" not in str(to_chat_response(resp).model_dump())


def test_ag08_15_multiple_names_use_last_name_and_template_keeps_marker():
    resp = finalize([_unid("뿌셔캡슐"), _unid("판콜에이")], None, emergency=False)
    assert "뿌셔캡슐 · 판콜에이를 함께 먹어도 되는지" in resp["pharmacist_advice"][0]
    assert "{drugs}을(를)" in fp.PHARMACIST_ADVICE  # 원문 상수는 문서 표기 그대로 두고 출력에서만 고른다
    assert josa.eul_reul("") == "를" and josa.eul_reul("()") == "를"  # 판단할 글자가 없을 때(가정)


# =========================================================================== 4. AG-08-12 B
def test_ag08_12_identified_line_is_badge_plus_sub_line():
    resp = finalize([_ident(), _unid()], "요약", emergency=False)
    e = next(x for x in resp["entries"] if x["bucket"] == "identified")
    assert (e["text"], e["sub_line"], e["drug"]) == ("찾음", "아세트아미노펜", "타이레놀정500") and fp.IDENTIFIED_LINE == "찾음"
    lines = resp["text"].splitlines()
    assert lines[lines.index("[타이레놀정500] 찾음") + 1] == "  아세트아미노펜"
    assert "금기 목록에 없" not in e["text"] + (e["sub_line"] or "") and fp.NOT_LISTED not in resp["text"]  # 쌍 판정을 못 했으므로 NOT_LISTED가 아니다
    f = next(x for x in to_chat_response(resp).findings if x.bucket == "identified")
    assert (f.text, f.sub_line, [i.name for i in f.ingredients]) == ("찾음", "아세트아미노펜", ["아세트아미노펜"])
    assert f.badges == [] and f.unresolved is False


def test_ag08_12_identified_line_without_ingredients_and_many():
    assert finalize([_ident(ingredients=())], None, emergency=False)["entries"][0]["sub_line"] is None
    e = finalize([_ident(ingredients=("슈도에페드린", "아세트아미노펜"))], None, emergency=False)["entries"][0]
    assert e["sub_line"] == "슈도에페드린 · 아세트아미노펜" and e["text"] == "찾음"


def test_ag08_12_no_forbidden_wording_in_identified_constants():
    src = (ROOT / "backend" / "app" / "agent" / "fixed_phrases.py").read_text(encoding="utf-8")
    assert "약을 확인했어요" not in src  # 옛 형식 문장은 남지 않는다
    assert "금기 목록에 없" not in fp.IDENTIFIED_LINE and "IDENTIFIED_LINE" not in fp.DRAFT_KEYS


# =========================================================================== 5. AG-08-17 A·AG-08-18 A
def test_ag08_17_age_value_goes_to_sub_values_not_badge():
    resp = finalize([_age(rows=((12, "세", "미만"), (6, "개월", "미만"), (12, "세", "미만")))], None, emergency=False)
    assert [b["text"] for b in resp["badges"]] == ["삐! 연령금기"] and fp.BADGE_AGE == "삐! 연령금기"
    e = resp["entries"][0]
    assert e["text"] == "삐! 연령금기" and e["age_criteria"] == ["12세 미만", "6개월 미만"]  # 원문 값, 같은 값은 한 번
    assert not any(ch.isdigit() for ch in e["text"])
    f = to_chat_response(resp).findings[0]
    assert f.age_criteria == ["12세 미만", "6개월 미만"] and f.badges[0].text == "삐! 연령금기" and f.age_info_line is None


def test_ag08_17_missing_age_fields_are_not_invented():
    it = _age()
    it["matches"] = [{"age_value": 12, "age_unit": None, "age_cond": "미만", "row_key": "r", "row_evidence_id": "age:1#0"}]
    assert finalize([it], None, emergency=False)["entries"][0]["age_criteria"] == []


def test_ag08_18_non_target_kind_has_no_line_and_no_new_state():
    # 임신 아님: 도구가 임부금기 항목을 만들지 않고 finalize도 줄을 만들지 않는다. "해당 없음" 상태·묶음은 없다
    resp = finalize([_pair(status="NOT_LISTED"), _ident()], None, emergency=False)
    assert all(e["kind"] != "pregnancy" for e in resp["entries"]) and "임부금기" not in resp["text"]
    assert resp["not_checked_lines"] == []
    assert set(fz._BUCKET_NAME.values()) == {"found", "not_listed", "identified", "unconfirmed"}
    assert set(typing.get_args(sc.Bucket)) == {"found", "not_listed", "identified", "unconfirmed"}
    assert "해당 없음" not in (ROOT / "backend" / "app" / "agent" / "fixed_phrases.py").read_text(encoding="utf-8")


# =========================================================================== 6. 0-E 승인 문구 14줄(서버 몫 12줄)
_APPROVED = {
    "1-1": fp.ERROR_MESSAGES["INTERNAL_ERROR"], "1-2": fp.ERROR_MESSAGES["TIMEOUT"], "1-3": fp.ERROR_MESSAGES["UPSTREAM_UNAVAILABLE"],
    "2": fp.NOTICE_API_FAIL, "3": fp.AGE_INFO_LINE, "5": fp.EMERGENCY_119_WIDE, "6": fp.PREGNANCY_NOT_CHECKED,
    "7-1": fp.UNIDENTIFIED_SUB_LINE, "7-2": fp.GRADE_MISMATCH_NOTE, "7-3a": fp.INGR_CODE_MISSING_TEXT["ABSENT"],
    "7-3b": fp.INGR_CODE_MISSING_TEXT["FETCH_FAIL"], "7-4": fp.DOSE_QUOTE_NOTICE, "7-5": fp.CLARIFY_PICK_LINE,
}
_APPROVED_TEXT = {
    "1-1": "잠시 뒤 다시 시도해 주세요. 보낸 질문은 그대로 있어요.",
    "1-2": "시간 안에 답을 마치지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    "1-3": "지금은 확인에 필요한 곳에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    "2": "실시간 확인을 하지 못해 아래 결과는 기준일 자료로 확인한 것이에요.",
    "3": "나이를 특정할 수 없어 판정하지 않고, 이 약의 나이별 연령금기 기준을 원문 그대로 보여 드려요.",
    "5": "컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요.",
    "6": "임신 여부를 알 수 없어 임부금기는 확인하지 못했어요.",
    "7-1": "{drug}을(를) 찾지 못해 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요.",
    "7-2": "파일 자료와 실시간 조회의 등급이 달라요. 어느 쪽이 맞는지 정하지 않고 둘 다 출처와 함께 보여 드려요.",
    "7-3a": "성분코드는 자료에 적혀 있지 않아요",
    "7-3b": "성분코드는 지금 불러오지 못했어요",
    "7-4": "허가사항 원문 인용이며 복용 지시가 아닙니다. 복용량은 약사·의사에게 확인하세요.",
    "7-5": "어느 제품인지 고르면 금기를 확인해 드려요.",
}


@pytest.mark.parametrize("no", sorted(_APPROVED))
def test_0e_constants_match_approved_text(no):
    assert _APPROVED[no] == _APPROVED_TEXT[no]
    assert _APPROVED[no] in _doc("tickets/agent/AG-08.md")  # 티켓 §5 승인 표 원문과 글자 일치


def test_0e_template_matches_instance_and_ticket():
    assert fp.NOT_CHECKED_TEMPLATE.format(info="임신 여부", kind="임부금기") + "." == fp.PREGNANCY_NOT_CHECKED
    assert fp.NOT_CHECKED_TEMPLATE.replace("{info}", "{정보}").replace("{kind}", "{종류}") in _doc("tickets/agent/AG-08.md")


def test_0e_new_constants_are_not_draft_and_not_safe_implying():
    names = ("EMERGENCY_119_WIDE", "UNIDENTIFIED_SUB_LINE", "PREGNANCY_NOT_CHECKED", "AGE_INFO_LINE", "CLARIFY_PICK_LINE", "GRADE_MISMATCH_NOTE",
             "INGR_CODE_MISSING_TEXT", "DOSE_QUOTE_NOTICE", "NOTICE_API_FAIL", "ERROR_MESSAGES")
    for n in names:
        assert hasattr(fp, n) and n not in fp.DRAFT_KEYS
    for n in ("EMERGENCY_119", "UNIDENTIFIED_NEXT", "UNIDENTIFIED_NOT_SAFE", "LIMIT_REACHED", "PHARMACIST_ADVICE_FIXED", "GRADE_DEF_MISSING_TEXT",
              "LOOKUP_FAILED", "TRUNCATED"):  # 원문 승인(AG-08-04·05·06·09·11·14, 하네스 3.4절 표)
        assert n not in fp.DRAFT_KEYS
    for text in _APPROVED.values():
        assert not any(w in text for w in ("안전해요", "안전합니다", "괜찮", "문제없", "문제 없", "삐!"))
    assert "119" in fp.EMERGENCY_119_WIDE and "1339" not in fp.EMERGENCY_119_WIDE  # 119 외 연락처 없음


def test_0e_error_messages_wired_to_events():
    assert ev.ERROR_MESSAGES == fp.ERROR_MESSAGES and set(ev.ERROR_MESSAGES) == set(ev.ERROR_CODES)
    for code in ev.ERROR_CODES:
        assert ev.error(0, code).message == fp.ERROR_MESSAGES[code]


@pytest.mark.parametrize("flag", ["API_FAIL", "API_PAIR_INCOMPLETE"])
def test_0e_api_fail_banner(flag):
    resp = finalize([_pair(flags=[flag])], "모델이 배너를 지웠어요", emergency=False)
    assert resp["notice"] == fp.NOTICE_API_FAIL and fp.NOTICE_API_FAIL in sc.NOTICE_TEXTS
    assert resp["entries"][0]["bucket"] == "found" and resp["badges"][0]["text"] == "삐! 병용금기"  # 파일 판정은 그대로
    assert to_chat_response(resp).notice == fp.NOTICE_API_FAIL
    assert finalize([_pair(flags=[flag])], None, emergency=False, limit_reached=True)["notice"] == fp.LIMIT_REACHED  # 배너 칸은 하나
    assert finalize([_pair(flags=["API_SAME"])], None, emergency=False)["notice"] is None


def test_0e_emergency_wide_text_only_with_emergency():
    resp = finalize([_pair()], None, emergency=True)
    assert resp["emergency_wide"] == fp.EMERGENCY_119_WIDE and resp["text"].splitlines()[0] == fp.EMERGENCY_119
    r = to_chat_response(resp)
    assert r.emergency is not None and r.emergency.wide_text == fp.EMERGENCY_119_WIDE
    assert ev.emergency(0).emergency.wide_text == fp.EMERGENCY_119_WIDE
    assert finalize([_pair()], None, emergency=False)["emergency_wide"] is None
    with pytest.raises(ValidationError):
        Emergency(text=fp.EMERGENCY_119, tel=fp.EMERGENCY_119_TEL, wide_text="1339에 전화하세요")


def test_0e_not_checked_line_for_unknown_pregnancy():
    resp = finalize([_pair(status="NOT_LISTED")], "임부금기는 괜찮아요", emergency=False, not_checked=["pregnancy", "pregnancy", "contra_pair"])
    assert resp["not_checked_lines"] == [fp.PREGNANCY_NOT_CHECKED]  # 승인 문장이 없는 종류는 줄을 만들지 않는다
    assert fp.PREGNANCY_NOT_CHECKED in resp["text"] and resp["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED
    assert resp["entries"][0]["bucket"] == "not_listed"  # 다른 줄의 판정은 그대로
    r = to_chat_response(resp)
    assert r.not_checked_lines == [fp.PREGNANCY_NOT_CHECKED] and r.fixed_notice[0] == fp.PHARMACIST_ADVICE_FIXED
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({**r.model_dump(), "not_checked_lines": ["임부금기 없음"]})


def test_0e_unidentified_card_sub_line_uses_particle():
    resp = finalize([_unid("뿌셔캡슐"), _unid("판콜에이")], "안전해요", emergency=False)
    subs = {e["input_name"]: e["sub_line"] for e in resp["entries"]}
    assert subs == {"뿌셔캡슐": "뿌셔캡슐을 찾지 못해 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요.",
                    "판콜에이": "판콜에이를 찾지 못해 금기를 확인하지 못했어요. 안전하다는 뜻이 아니에요."}
    assert all(e["text"] == fp.UNIDENTIFIED for e in resp["entries"])  # 표지 글자는 그대로
    assert [f.sub_line for f in to_chat_response(resp).findings] == list(subs.values())


def test_0e_grade_mismatch_note_on_that_evidence_only():
    ms = [{"grade": "1", "row_key": "a", "row_evidence_id": "pregnancy:1#a", "source_kind": "API_DIRECT"},
          {"grade": "2", "row_key": "b", "row_evidence_id": "pregnancy:1#b", "source_kind": "FILE"}]
    resp = finalize([_preg(matches=ms), _pair()], "등급은 하나예요", emergency=False)
    notes = {d["evidence_id"]: d.get("notes") or [] for d in resp["detail"]}
    assert notes["pregnancy:1"].count(fp.GRADE_MISMATCH_NOTE) == 1 and fp.GRADE_MISMATCH_NOTE not in notes["contra_pair:1"]
    assert [b["text"] for b in resp["badges"]] == ["삐! 병용금기", "삐! 임부금기 2등급 (파일)", "삐! 임부금기 1등급 (성분 API)"]  # 배지는 그대로
    same = finalize([_preg(), _pair()], None, emergency=False)
    assert all(fp.GRADE_MISMATCH_NOTE not in (d.get("notes") or []) for d in same["detail"])
    d = next(x for x in to_chat_response(resp).detail if x.evidence_id == "pregnancy:1")
    assert fp.GRADE_MISMATCH_NOTE in d.notes


def test_0e_dose_quote_notice_only_under_dose_quote():
    r = to_chat_response(finalize([_label("용법용량"), _label("주의사항", text="주의")], None, emergency=False))
    by = {d.section: d for d in r.detail}
    assert by["용법용량"].quote_notice == fp.DOSE_QUOTE_NOTICE and by["주의사항"].quote_notice is None
    with pytest.raises(ValidationError):
        DetailItem.model_validate({**by["용법용량"].model_dump(), "quote_notice": "이만큼 드세요"})


def test_0e_clarify_line_and_code_missing_text():
    raw = finalize([], model_summary="q", emergency=False)
    clar = {"target_raw": "타이레놀", "options": [{"name": "타이레놀정500밀리그람"}, {"name": "타이레놀콜드-에스정"}]}
    r = to_chat_response(raw, end_reason="CLARIFY", clarify=clar)
    assert r.candidates_line == fp.CLARIFY_PICK_LINE and len(r.candidates) == 2
    assert to_chat_response(raw, end_reason="NORMAL").candidates_line is None
    for bad in ({"candidates_line": "아무거나 고르세요"}, {"candidates": [], "candidates_line": fp.CLARIFY_PICK_LINE}):
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({**r.model_dump(), **bad})
    for text in fp.INGR_CODE_MISSING_TEXT.values():
        assert Ingredient(name="아세트아미노펜", code_missing_text=text).code_missing_text == text
    with pytest.raises(ValidationError):
        Ingredient(name="아세트아미노펜", code_missing_text="코드 없음")
    with pytest.raises(ValidationError):
        Ingredient(name="아세트아미노펜", code="101301ATB", code_missing_text=fp.INGR_CODE_MISSING_TEXT["ABSENT"])


def test_0e_age_info_line_is_constant_and_needs_criteria():
    ok = Finding(bucket="unconfirmed", evidence_id="age:X", kind="age", drug="d", text="t", age_criteria=["12세 미만"], age_info_line=fp.AGE_INFO_LINE)
    assert ok.age_info_line == fp.AGE_INFO_LINE
    for kw in ({"age_criteria": ["12세 미만"], "age_info_line": "먹어도 되는 나이예요"}, {"age_criteria": [], "age_info_line": fp.AGE_INFO_LINE}):
        with pytest.raises(ValidationError):
            Finding(bucket="unconfirmed", evidence_id="age:X", kind="age", drug="d", text="t", **kw)


# =========================================================================== 7. Recap 0-1
def test_0_1_code_not_linked_text_and_fallback_released():
    text = "금기 목록에서 확인하지 못했지만, 안전하다는 뜻이 아니에요. 약사에게 확인하세요"
    assert FLAG_NOTES["CODE_NOT_LINKED"] == text == fp.CODE_NOT_LINKED == fp.FLAG_LINES["CODE_NOT_LINKED"]
    assert text in _doc("P2-doc/PJ2-Agent-Harness.md")
    resp = finalize([_pair(status="UNIDENTIFIED", flags=["CODE_NOT_LINKED"])], "목록에 없어 안전해요", emergency=False)
    e = resp["entries"][0]
    assert e["bucket"] == "unconfirmed" and text in e["notes"] and fp.NOT_LISTED not in resp["text"]  # 판정은 그대로(확인하지 못함)
    for key in ("FALLBACK_NONE_CONFIRMED", "FALLBACK_SOME_CONFIRMED", "FALLBACK_NONE_SCOPE_DOC"):
        assert key not in fp.DRAFT_KEYS
    harness = _doc("P2-doc/PJ2-Agent-Harness.md")
    assert fp.FALLBACK_NONE_CONFIRMED in harness
    assert fp.FALLBACK_SOME_CONFIRMED.replace("{datasets}", "{자료1}(기준일 {날짜})·{자료2}(기준일 {날짜})") in harness


# =========================================================================== 8. BE-06-13 A
@pytest.mark.parametrize("kinds,dup,expected", [
    ([], False, []), (["pregnancy"], False, ["금기 원인"]), (["age"], False, ["금기 원인"]), (["contra_pair"], False, ["병용금기 원인"]),
    ([], True, ["중복"]), (["pregnancy"], True, ["금기 원인", "중복"]), (["pregnancy", "contra_pair"], False, ["병용금기 원인", "금기 원인"]),
    (["age", "pregnancy"], False, ["금기 원인"]), (["dose"], False, []),  # 주의 종류는 "금기 원인"이라고 하지 않는다
])
def test_be06_13_ingredient_state_labels(kinds, dup, expected):
    assert Ingredient(name="슈도에페드린", contra_kinds=kinds, dup=dup).state_labels == expected
    assert fp.ingredient_state_labels(kinds, dup) == expected


def test_be06_13_state_labels_are_server_constants_only():
    assert (fp.INGR_STATE_CAUSE, fp.INGR_STATE_DUP, fp.INGR_STATE_PAIR_CAUSE) == ("금기 원인", "중복", "병용금기 원인")
    prd = _doc("tickets/doc/PRD-09.md")
    assert all(f"`{t}`" in prd for t in (fp.INGR_STATE_CAUSE, fp.INGR_STATE_DUP, fp.INGR_STATE_PAIR_CAUSE))  # 디자인 문서 글자 그대로
    for bad in (["원인"], ["중복"], ["금기 원인", "병용금기 원인"]):
        with pytest.raises(ValidationError):
            Ingredient(name="슈도에페드린", contra_kinds=["pregnancy"], dup=False, state_labels=bad)
    assert "state_labels" in Ingredient.model_json_schema()["properties"]
    js = ChatResponse.model_json_schema()["$defs"]["Ingredient"]["properties"]
    assert {"code", "name", "contra_kinds", "dup"} <= set(js)  # 기존 칸은 그대로(추가만)


# =========================================================================== 9. BE-06-14~17 A
def test_be06_14_source_kind_label_on_detail():
    r = to_chat_response(finalize([_pair(), _label(), _unid()], None, emergency=False))
    got = {d.evidence_id: (d.source_kind, d.source_kind_label) for d in r.detail}
    assert got["contra_pair:1"] == ("FILE", "공식 파일") and got["prmsn:202106954:용법용량"] == ("API_DIRECT", "공식 자료")
    assert got["identify:뿌셔캡슐"] == (None, None)  # 출처가 없는 근거에는 글자도 없다
    assert set(SOURCE_KIND_PREFIX.values()) == {"공식 자료", "공식 파일", "공식 문서"}
    with pytest.raises(ValidationError):
        DetailItem.model_validate({**r.detail[0].model_dump(), "source_kind_label": "믿을 만한 자료"})


def test_be06_15_label_help_and_prescription_only_line():
    r = to_chat_response(finalize([_label("주의사항", flags=["EASY_TEXT_MISSING"], text="주의"), _pair()], None, emergency=False))
    lab = next(d for d in r.detail if d.kind == "label")
    assert lab.label_help == fp.LABEL_ONE_LINE and lab.drug_name == "이지렉트정"
    assert lab.easy_text_missing_line == "이지렉트정은 전문의약품이라 쉬운 설명(e약은요)이 없어서 허가사항 원문을 그대로 보여 드려요"
    other = next(d for d in r.detail if d.kind == "contra_pair")
    assert other.label_help is None and other.easy_text_missing_line is None
    plain = to_chat_response(finalize([_label("주의사항", text="주의")], None, emergency=False)).detail[0]
    assert plain.label_help == fp.LABEL_ONE_LINE and plain.easy_text_missing_line is None
    for bad in ({"label_help": "허가사항이란 좋은 약이라는 뜻"}, {"easy_text_missing_line": "지어낸 줄"}):
        with pytest.raises(ValidationError):
            DetailItem.model_validate({**lab.model_dump(), **bad})
    with pytest.raises(ValidationError):  # 꼬리표 없는 근거에 전문의약품 안내 줄을 붙일 수 없다
        DetailItem.model_validate({**plain.model_dump(), "easy_text_missing_line": lab.easy_text_missing_line})


def test_be06_16_grade_def_blocks_are_structured():
    quote = "사람에서 태아에 대한 위해성이 나타날 수 있으며, … 원칙적으로 사용금지."
    src = "「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 나목"
    resp = finalize([_preg()], "2등급은 괜찮은 등급이에요", emergency=False,
                    grade_defs=[{"grade": "2등급", "text": quote, "source": src}],
                    grade_def_missing=[{"grade": "M", "missing_reason": "OUT_OF_SCOPE"}, {"grade": "1", "missing_reason": "FETCH_FAIL"}])
    r = to_chat_response(resp)
    assert [(g.grade, g.title, g.text, g.source, g.missing_reason) for g in r.grade_defs] == [
        ("2", "임부금기 2등급이란?", quote, src, None),
        ("M", "임부금기 M등급이란?", None, None, "OUT_OF_SCOPE"),  # 원문이 없으면 출처 줄도 없다(PRD-15-03)
        ("1", "임부금기 1등급이란?", None, None, "FETCH_FAIL"),
    ]
    assert r.grade_defs[1].missing_text == fp.GRADE_DEF_MISSING_TEXT["OUT_OF_SCOPE"].format(grade="M")
    assert r.grade_def_missing == [g.missing_text for g in r.grade_defs[1:]]  # 기존 줄 목록 칸은 그대로
    assert fp.GRADE_DEF_PHARMACIST_ADVICE in r.pharmacist_advice
    assert "임부금기 2등급이란?" in _doc("tickets/doc/PRD-09.md") and "임부금기 M등급이란?" in _doc("tickets/doc/PRD-09.md")
    assert "단계" not in fp.GRADE_DEF_TITLE and "SEARCH_MISS" not in typing.get_args(sc.GradeMissingReason)


@pytest.mark.parametrize("patch", [
    {"title": "임부금기 2등급 설명"}, {"text": None}, {"missing_reason": "FETCH_FAIL"}, {"text": "  "},
    {"text": None, "source": "출처", "missing_reason": "FETCH_FAIL", "missing_text": fp.GRADE_DEF_MISSING_TEXT["FETCH_FAIL"].format(grade="2")},
    {"text": None, "source": None, "missing_reason": "FETCH_FAIL", "missing_text": "근거 문장을 찾지 못했어요"},
    {"text": None, "source": None, "missing_reason": "SEARCH_MISS", "missing_text": "x"},
])
def test_be06_16_grade_def_rejects_bad_shapes(patch):
    base = {"grade": "2", "title": "임부금기 2등급이란?", "text": "원문", "source": "출처", "missing_reason": None, "missing_text": None}
    assert GradeDef(**base).text == "원문"
    with pytest.raises(ValidationError):
        GradeDef(**{**base, **patch})


def test_be06_16_unknown_grade_makes_no_block_but_keeps_line():
    resp = finalize([_preg()], None, emergency=False, grade_def_missing=[{"grade": None, "missing_reason": "FETCH_FAIL"}])
    assert resp["grade_defs"] == [] and len(resp["grade_def_missing"]) == 1
    assert to_chat_response(resp).grade_defs == []


@pytest.mark.parametrize("items,kw", [
    ([_unid()], {}), ([_pair_not_checked()], {}), ([_pair(status="NOT_LISTED", flags=["LOOKUP_FAILED"])], {}),
    ([_preg()], {"grade_def_missing": [{"grade": "2", "missing_reason": "FETCH_FAIL"}]}),
])
def test_be06_17_unresolved_response_requires_pharmacist_advice(items, kw):
    r = to_chat_response(finalize(items, "약사에게 물어볼 필요 없어요", emergency=False, **kw))
    assert r.pharmacist_advice and all(x.strip() for x in r.pharmacist_advice)
    for empty in ([], ["  "]):
        with pytest.raises(ValidationError, match="pharmacist_advice"):
            ChatResponse.model_validate({**r.model_dump(), "pharmacist_advice": empty})


def test_be06_17_resolved_response_may_have_no_advice_and_version_unchanged():
    r = to_chat_response(finalize([_pair()], "요약", emergency=False))
    assert r.pharmacist_advice == [] and r.schema_version == "chat_response@v1" == sc.SCHEMA_VERSION


# =========================================================================== 12. 쌍 확인 불가 줄(문구 배치만, 판정 불변)
def test_pair_not_checked_text_appears_once_without_unidentified_guidance():
    resp = finalize([_pair_not_checked()], "함께 먹어도 돼요", emergency=False)
    e = resp["entries"][0]
    assert e["text"] == fp.PAIR_NOT_CHECKED and e["notes"] == []
    assert resp["text"].count(fp.PAIR_NOT_CHECKED) == 1
    assert not {"why", "next", "input_name", "retried_line", "searched", "sub_line"} & set(e)  # 약을 못 찾은 줄이 아니다
    assert fp.UNIDENTIFIED_NEXT not in resp["text"] and fp.UNIDENTIFIED_WHY not in resp["text"]
    # 판정·상태는 그대로: 확인하지 못함, 배지 없음, 약사 권고 유지
    assert (e["bucket"], e["unresolved"], resp["badges"]) == ("unconfirmed", True, [])
    assert resp["pharmacist_advice"] == [josa.fill(fp.PHARMACIST_ADVICE, drugs="가나다정 · 사아자시럽")]
    assert resp["pharmacist_advice_fixed"] == fp.PHARMACIST_ADVICE_FIXED and fp.NOT_LISTED not in resp["text"]
    f = to_chat_response(resp).findings[0]
    assert (f.target, f.drugs, f.text, f.notes, f.why, f.next, f.retried) == ("pair", ["가나다정", "사아자시럽"], fp.PAIR_NOT_CHECKED, [], None, None, None)


def test_pair_not_checked_keeps_other_notes_and_unidentified_drug_keeps_guidance():
    it = _pair_not_checked()
    it["flags"] = ["PAIR_NOT_CHECKED", "API_FAIL"]
    e = finalize([it], None, emergency=False)["entries"][0]
    assert e["notes"] == [FLAG_NOTES["API_FAIL"]]  # 줄 글자와 다른 안내는 남는다
    resp = finalize([_unid(), _pair_not_checked("뿌셔캡슐", "타이레놀정500"), _ident()], None, emergency=False)
    unid = next(x for x in resp["entries"] if x["kind"] == "identify" and x["bucket"] == "unconfirmed")
    assert (unid["why"], unid["next"], unid["input_name"]) == (fp.UNIDENTIFIED_WHY, fp.UNIDENTIFIED_NEXT, "뿌셔캡슐")
    assert resp["text"].count(fp.UNIDENTIFIED_NEXT) == 1 and resp["text"].count(fp.PAIR_NOT_CHECKED) == 1
    assert [x["bucket"] for x in resp["entries"]] == ["identified", "unconfirmed", "unconfirmed"]


def test_invalid_code_text_is_not_repeated_in_notes():
    it = {"kind": "identify", "status": "UNIDENTIFIED", "subject": ["XYZ"], "evidence_id": "identify:XYZ", "source": None, "as_of": None,
          "flags": ["INVALID_CODE"], "matches": [], "dataset_key": None, "source_kind": None}
    resp = finalize([it], None, emergency=False)
    assert resp["entries"][0]["text"] == fp.INVALID_CODE and resp["text"].count(fp.INVALID_CODE) == 1


# =========================================================================== 11. BE-06-08 A(확인만)
def test_be06_08_citation_date_labels_allow_month_value():
    from app.tools.provenance import CITATION_DATE_LABELS
    assert CITATION_DATE_LABELS["as_of"] == "기준일" and CITATION_DATE_LABELS["published"] == "발간일"
    for label in (CITATION_DATE_LABELS["as_of"], CITATION_DATE_LABELS["published"]):
        assert sc.DateLine(label=label, value="2026-06").value == "2026-06"  # 월 단위 값은 없는 날을 붙이지 않고 그대로 나간다
    it = {**_pair(), "kind": "elderly", "dataset_key": "elderly", "as_of": "2026-06", "evidence_id": "elderly:1",
          "source": "건강보험심사평가원", "drugs": ["어르신약"]}
    r = to_chat_response(finalize([it], None, emergency=False))
    row = next(c for c in r.citations if c.dataset == "노인주의 파일")
    assert ("기준일", "2026-06") in [(d.label, d.value) for d in row.dates]
