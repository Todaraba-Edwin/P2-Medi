"""AG-08 §2 미체크 표지 조건을 **도구 실제 모양**(파일 항목·API 항목이 따로 오고 `source_kind`가 항목 단위)으로 닫는 시험.

- `:49` FOUND 표지: `삐! 임부금기 {grade}등급`(M은 `M등급` + 적응증 안내), 보조줄·꼬리 안내에 등급 반복 없음, "단계" 없음,
  등급 정의 블록은 받은 원문 그대로(제목 상수, 출처 줄). M등급 정의 블록 생성은 `grade_defs.py`가 규칙 미정이라 만들지 않는다(이 시험 밖).
- `:53` 출처 라벨: `{종류} · {자료 약칭}`(약칭은 `provenance.DATASET_LABELS`, BE-06 `dataset`과 같은 표), 항목 줄에 출처·조회일 줄을 만들지 않는다.
- `:57` 배지 상수: 병용 + 등급 불일치(파일 항목·API 항목)에서 배지 3개가 병용 → 임부(파일) → 임부(성분 API) 순서, 글자는 상수와 일치,
  모든 배지에 종류 글자(G15). 꼬리 키는 항목 단위 `source_kind`에서 온다(행 단위 `source_kind`가 없어도 된다: 이전 "가정"의 확인).
- `:39` 끝단: 모델 요약이 비면(문장 필터가 다 걸러 빈 요약) `summary`는 None이고 고정 문구·고지·항목 줄은 그대로다.
외부 호출·LLM 호출 없음. 합성 fixture.
"""

from __future__ import annotations

import pytest

from app.agent import fixed_phrases as fp
from app.agent.finalize import finalize
from app.tools.provenance import DATASET_LABELS, SOURCE_KIND_PREFIX
from app.tools.provenance import badge as source_badge

KIDS = "한국의약품안전관리원"


def _preg(grade="2", source_kind="FILE", drug=("와파린정", "SEQ_A")):
    api = source_kind == "API_DIRECT"
    eid = f"dur_ingr:pregnancy:{drug[1]}" if api else f"pregnancy:{drug[1]}"
    return {"kind": "pregnancy", "status": "FOUND", "subject": ["111111ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": None if api else "2026-07-21", "queried_at_utc": "2026-11-18T00:00:00Z" if api else None, "flags": [],
            "matches": [{"row_key": "r", "row_evidence_id": eid + "#a", "grade": grade, "detail": "상세 원문", "notice_no": "제2026-1호"}],
            "dataset_key": "dur_ingr" if api else "pregnancy", "source_kind": source_kind, "drugs": [drug[0]], "drug_keys": [drug[1]]}


def _pair():
    eid = "contra_pair:SEQ_A:SEQ_B"
    return {"kind": "contra_pair", "status": "FOUND", "subject": ["111111ATB", "222222ATB"], "evidence_id": eid, "source": KIDS,
            "as_of": "2026-07-31", "flags": [], "matches": [{"row_key": "rk", "row_evidence_id": eid + "#a", "reason": "사유 원문"}],
            "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": ["와파린정", "아스피린정"], "drug_keys": ["SEQ_A", "SEQ_B"]}


# --------------------------------------------------------------------------- :57 배지 상수·순서(도구 실제 모양)
def test_pair_plus_file_api_grade_mismatch_gives_three_ordered_constant_badges():
    resp = finalize([_preg("1", "API_DIRECT"), _pair(), _preg("2", "FILE")])
    texts = [b["text"] for b in resp["badges"]]
    assert texts == [
        fp.BADGE_PAIR,
        f"{fp.BADGE_PREGNANCY.format(grade='2')} {fp.BADGE_SOURCE_TAIL['FILE']}",
        f"{fp.BADGE_PREGNANCY.format(grade='1')} {fp.BADGE_SOURCE_TAIL['API_DIRECT']}",
    ]
    assert [b.get("source_tail_key") for b in resp["badges"]] == [None, "FILE", "API_DIRECT"]
    assert all(("병용금기" in t) or ("임부금기" in t) for t in texts)  # G15: 종류 글자
    assert all("등급이 달라요" not in t for t in texts)  # 합친 배지 없음
    row = next(r for r in resp["product_rows"] if r["key"] == "SEQ_A")
    assert [b["text"] for b in row["badges"]] == texts


def test_same_grade_file_and_api_make_no_tail():
    resp = finalize([_preg("2", "FILE"), _preg("2", "API_DIRECT")])
    assert all(b.get("source_tail_key") is None for b in resp["badges"])
    assert all(fp.GRADE_MISMATCH_NOTE not in (d.get("notes") or []) for d in resp["detail"])


# --------------------------------------------------------------------------- :49 FOUND 표지·보조줄·정의 블록
@pytest.mark.parametrize("grade", ["1", "2", "M"])
def test_pregnancy_badge_text_and_no_grade_repeat_outside_badge(grade):
    resp = finalize([_preg(grade)])
    (e,) = [x for x in resp["entries"] if x["kind"] == "pregnancy"]
    want = fp.BADGE_PREGNANCY_M if grade == "M" else fp.BADGE_PREGNANCY.format(grade=grade)
    assert e["text"] == want
    assert (e.get("note") == fp.BADGE_PREGNANCY_M_NOTE) is (grade == "M")
    for k in ("sub_line", "why", "next", "reference_line"):
        assert "등급" not in (e.get(k) or "")
    assert all("등급" not in n for n in e["notes"])
    assert "단계" not in resp["text"]


def test_grade_definition_block_is_verbatim_with_title_and_source():
    original = "사람에서 태아에 대한 위해성이 나타날 수 있으며 원칙적으로 사용금지."
    resp = finalize([_preg("2")], grade_defs=[{"grade": "2", "text": original, "source": "고시 제3조 제3호 나목"}])
    (g,) = resp["grade_defs"]
    assert g["title"] == fp.GRADE_DEF_TITLE.format(grade="2") and g["text"] == original and g["source"] == "고시 제3조 제3호 나목"
    assert "단계" not in resp["text"]


# --------------------------------------------------------------------------- :53 출처 라벨
@pytest.mark.parametrize("source_kind, dataset_key", [("FILE", "pregnancy"), ("API_DIRECT", "dur_ingr"), ("FILE", "contra_pair")])
def test_source_label_is_kind_dot_dataset_label(source_kind, dataset_key):
    it = _pair() if dataset_key == "contra_pair" else _preg("2", source_kind)
    (e,) = finalize([it])["entries"]
    assert e["source_label"] == source_badge(source_kind, dataset_key)
    assert e["source_label"] == f"{SOURCE_KIND_PREFIX[source_kind]} · {DATASET_LABELS[dataset_key]}"


def test_entry_lines_have_no_source_or_date_lines():
    resp = finalize([_pair(), _preg("2", "FILE"), _preg("1", "API_DIRECT")])
    for e in resp["entries"]:
        lines = [e["text"], *(e.get(k) or "" for k in ("sub_line", "why", "next", "reference_line")), *e["notes"]]
        for word in ("기준일", "조회 시각", "고시일", "2026-07", "2026-11-18"):
            assert all(word not in x for x in lines), word


# --------------------------------------------------------------------------- :39 걸러져 빈 요약의 끝단
@pytest.mark.parametrize("summary", ["", "   ", None])
def test_empty_filtered_summary_keeps_fixed_phrases_and_lines(summary):
    resp = finalize([_pair()], model_summary=summary)
    assert resp["summary"] is None
    assert resp["fixed_notice"] == fp.FIXED_NOTICE and resp["disclaimer"] == fp.DISCLAIMER
    assert resp["entries"] and resp["badges"]
    assert resp["text"].splitlines()[-2:] == [fp.FIXED_NOTICE, fp.DISCLAIMER]
