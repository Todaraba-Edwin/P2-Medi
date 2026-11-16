"""AG-08 `finalize`(코드 부분, 순수 함수, LLM·외부 호출 없음).

도구 `items[]`의 상태·꼬리표를 읽어 항목마다 코드 상수 문구를 붙인다. 모델 출력(`model_summary`)은 `summary` 한 칸에만 들어가고,
119·고지·약사 권고·항목 문구는 모델 출력과 무관하게 항상 코드가 만든다(모델이 지울 수 없다).

- 순서: 응급 119(맨 위) → 거절·상한 안내 → 요약 → 항목(`FOUND` → `NOT_LISTED` → 식별된 약 → 확인하지 못함) → 약사 권고 → 고정 문구 → 고지.
- 코드 없음·참고 전용·이름 모호·조회 실패는 `NOT_LISTED`가 아니라 "확인하지 못함"이다(금기 종류 항목에서는 상태와 무관하게 강등).
- `source_kind`가 없는 근거 항목(`FOUND`·`NOT_LISTED`)은 근거로 렌더하지 않는다. 단 숨기지는 않고 "확인하지 못함"으로 둔다
  (금기 발견이 사라지면 안 되므로). 배지·`detail`·`citations[]`도 만들지 않는다.
- `detail`·`citations[]`·`badges[]`는 AG-06 `renderer.render`를 호출해 얻는다(수정은 AG-06 몫).
"""

from __future__ import annotations

from typing import Any

from app.agent import fixed_phrases as fp
from app.agent import josa
from app.agent.answer_schema import Sentence
from app.agent.patterns import has_code
from app.agent.renderer import render
from app.tools.provenance import DATASET_LABELS
from app.tools.provenance import badge as source_badge

BUCKET_FOUND, BUCKET_NOT_LISTED, BUCKET_IDENTIFIED, BUCKET_UNCONFIRMED = 0, 1, 2, 3
_BUCKET_NAME = {BUCKET_FOUND: "found", BUCKET_NOT_LISTED: "not_listed", BUCKET_IDENTIFIED: "identified", BUCKET_UNCONFIRMED: "unconfirmed"}

# 금기 종류 항목에 붙으면 판정(`FOUND`·`NOT_LISTED`) 문구를 쓰지 않고 "확인하지 못함"으로 강등하는 꼬리표
_DEMOTE_FLAGS = ("CODE_NOT_LINKED", "LOOKUP_FAILED", "AMBIGUOUS_NAME", "REFERENCE_ONLY", "INVALID_CODE", "PAIR_NOT_CHECKED")
_JUDGED_STATUS = ("FOUND", "NOT_LISTED")
_DEFAULT_NOTE_FLAGS = ("API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE", "TRUNCATED")
_FLAG_TEXT = {**fp.FLAG_LINES, "INVALID_CODE": fp.INVALID_CODE, "PAIR_NOT_CHECKED": fp.PAIR_NOT_CHECKED}
# 실시간 확인 실패 꼬리표: 하나라도 있으면 상단 배너(`NOTICE_API_FAIL`)를 건다. 파일 판정은 그대로다
_API_FAIL_FLAGS = ("API_FAIL", "API_PAIR_INCOMPLETE")
_GRADES = ("1", "2", "M")


def _kind_rank(kind: str | None) -> int:
    return fp.BADGE_ORDER.index(kind) if kind in fp.BADGE_ORDER else len(fp.BADGE_ORDER)


def _names(it: dict[str, Any]) -> list[str]:
    for key in ("drugs",):
        v = it.get(key)
        if isinstance(v, list) and v:
            return [str(x) for x in v if x]
    for key in ("name", "input_name"):
        if it.get(key):
            return [str(it[key])]
    return [str(x) for x in (it.get("subject") or []) if x and not has_code(str(x))]


def _drug(it: dict[str, Any]) -> str:
    n = _names(it)
    return " · ".join(n) if n else "이 약"


def _grade_norm(g: Any) -> str | None:
    if isinstance(g, str) and g.strip():
        return g.strip().removesuffix("등급").strip().upper()
    return None


def _bucket(it: dict[str, Any]) -> int:
    st, kind, flags = it.get("status"), it.get("kind"), it.get("flags") or []
    if kind == "identify":
        return BUCKET_IDENTIFIED if st == "FOUND" else BUCKET_UNCONFIRMED
    if st in _JUDGED_STATUS and (not it.get("source_kind") or it["source_kind"] not in fp.SOURCE_KIND_TEXT):
        return BUCKET_UNCONFIRMED  # 출처 종류 없는 근거는 근거로 쓰지 않는다(H29)
    if it.get("missing_reason") or st not in _JUDGED_STATUS:
        return BUCKET_UNCONFIRMED
    if any(f in flags for f in _DEMOTE_FLAGS):
        return BUCKET_UNCONFIRMED
    return BUCKET_FOUND if st == "FOUND" else BUCKET_NOT_LISTED


def _missing_text(it: dict[str, Any]) -> str | None:
    reason = it.get("missing_reason")
    if reason in fp.MISSING_TEXT:
        return fp.MISSING_TEXT[reason].format(drug=_drug(it))
    if reason or it.get("status") == "NO_EVIDENCE":
        return fp.NO_EVIDENCE  # 모르는 사유 값도 사유 문구를 지어내지 않는다
    return None


def _notes(it: dict[str, Any]) -> list[str]:
    flags = it.get("flags") or []
    out = [_FLAG_TEXT[f] for f in (*_DEMOTE_FLAGS, *_DEFAULT_NOTE_FLAGS) if f in flags and f in _FLAG_TEXT]
    if "NO_PRODUCT_INFO" in flags:
        out.append(fp.NO_PRODUCT_INFO)
    if "EASY_TEXT_MISSING" in flags:
        out.append(fp.EASY_TEXT_MISSING.format(drug=_drug(it)))
    return out


def _source_label(it: dict[str, Any]) -> str | None:
    sk, dk = it.get("source_kind"), it.get("dataset_key")
    if sk in fp.SOURCE_KIND_TEXT and dk:
        try:
            return source_badge(sk, dk)
        except KeyError:
            return fp.SOURCE_KIND_TEXT[sk]
    return fp.SOURCE_KIND_TEXT.get(sk) if sk else None


def _age_criteria(it: dict[str, Any]) -> list[str]:
    """연령금기 나이 기준 값(원문 값, PRD-09 §7.4 `{특정연령}{특정연령단위} {연령처리조건}`). 값이 빠진 행은 만들지 않는다(지어내지 않음).
    도구가 원문 값 목록(`age_criteria`)을 직접 주면 그대로 쓴다. 같은 값은 한 번만."""
    given = it.get("age_criteria")
    if isinstance(given, list) and given:
        return list(dict.fromkeys(str(x) for x in given if x))
    out: list[str] = []
    for m in it.get("matches") or []:
        v, unit, cond = m.get("age_value"), m.get("age_unit"), m.get("age_cond")
        if v is None or not unit or not cond:
            continue
        out.append(f"{v}{unit} {cond}")
    return list(dict.fromkeys(out))


def _entry(it: dict[str, Any], bucket: int) -> dict[str, Any]:
    st, kind = it.get("status"), it.get("kind")
    e: dict[str, Any] = {
        "bucket": _BUCKET_NAME[bucket], "evidence_id": it.get("evidence_id"), "kind": kind, "drug": _drug(it),
        "notes": _notes(it), "source_label": _source_label(it) if bucket != BUCKET_UNCONFIRMED else None,
        "unresolved": False,
    }
    flags = it.get("flags") or []
    if bucket == BUCKET_FOUND:
        e["text"] = _badge_text(kind, _first_grade(it))
        if e["text"] == fp.BADGE_PREGNANCY_M:
            e["note"] = fp.BADGE_PREGNANCY_M_NOTE
        e["grades"] = [g for g in dict.fromkeys(_grade_norm(m.get("grade")) for m in it.get("matches") or []) if g]
        e["notice_nos"] = [m["notice_no"] for m in it.get("matches") or [] if m.get("notice_no")]
        if kind == "age":  # AG-08-17 A: 배지는 `BADGE_AGE` 그대로, 나이 값은 보조줄 값으로 따로 준다
            e["age_criteria"] = _age_criteria(it)
    elif bucket == BUCKET_NOT_LISTED:
        e["text"] = fp.NOT_LISTED
    elif bucket == BUCKET_IDENTIFIED:
        ingr = [i.get("display") or i.get("name_ko") or i.get("name_en") for i in it.get("ingredients") or []]
        ingr = [str(x) for x in ingr if x]
        e["text"] = fp.IDENTIFIED_LINE  # AG-08-12 B: 표지 "찾음" + 보조줄(성분 이름). 문장은 만들지 않는다
        e["sub_line"] = fp.IDENTIFIED_SUB_SEP.join(ingr) if ingr else None
        e["ingredients"] = [{"name": n} for n in ingr]
    else:
        e["unresolved"] = True
        e["text"] = _unconfirmed_text(it, st, flags)
        e["notes"] = [n for n in e["notes"] if n != e["text"]]  # 줄 글자와 같은 문구를 꼬리 안내로 한 번 더 내지 않는다
        # 쌍을 조회하지 못한 줄은 약을 못 찾은 줄이 아니다: 미식별 안내(못 찾은 이유·다음 행동)를 붙이지 않는다
        if (kind == "identify" or st == "UNIDENTIFIED") and "PAIR_NOT_CHECKED" not in flags:
            if kind == "identify":  # 근거 없음 카드 보조줄(UI-019)
                e["sub_line"] = josa.fill(fp.UNIDENTIFIED_SUB_LINE, drug=str(it.get("input_name") or e["drug"]))
            if it.get("input_name"):
                e["input_name"] = it["input_name"]
            e["why"] = fp.UNIDENTIFIED_WHY
            e["next"] = fp.UNIDENTIFIED_NEXT
            if it.get("retried"):
                e["retried_line"] = fp.UNIDENTIFIED_RETRIED
            e["searched"] = [{"dataset": s.get("dataset"), "count": s.get("count")} for s in it.get("searched") or [] if isinstance(s, dict)]
        if "REFERENCE_ONLY" in flags:
            e["reference_line"] = fp.REFERENCE_ONLY_LINE.format(drug=e["drug"])
    return e


def _unconfirmed_text(it: dict[str, Any], st: str | None, flags: list[str]) -> str:
    miss = _missing_text(it)
    if miss:
        return miss
    if st in _JUDGED_STATUS and (not it.get("source_kind") or it["source_kind"] not in fp.SOURCE_KIND_TEXT):
        return fp.UNIDENTIFIED + ". " + fp.BLOCKED_NO_SOURCE_KIND  # 판정을 보여 주지 않고 확인하지 못함으로 둔다
    if "INVALID_CODE" in flags:
        return fp.INVALID_CODE
    if "PAIR_NOT_CHECKED" in flags:
        return fp.PAIR_NOT_CHECKED
    return fp.UNIDENTIFIED


def _first_grade(it: dict[str, Any]) -> str | None:
    for m in it.get("matches") or []:
        g = _grade_norm(m.get("grade"))
        if g:
            return g
    return None


def _badge_text(kind: str | None, grade: str | None) -> str:
    if kind == "contra_pair":
        return fp.BADGE_PAIR
    if kind == "pregnancy":
        if grade == "M":
            return fp.BADGE_PREGNANCY_M
        return fp.BADGE_PREGNANCY.format(grade=grade) if grade else "삐! 임부금기"
    if kind == "age":
        return fp.BADGE_AGE
    return fp.CAUTION_LABELS.get(kind or "", "주의")  # 금기 아닌 종류는 "삐!"를 쓰지 않는다


def _badges(found_items: list[dict[str, Any]], render_badges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {it.get("evidence_id"): it for it in found_items}
    out: list[dict[str, Any]] = []
    for b in render_badges:
        it = by_id.get(b.get("evidence_id"))
        if it is None:  # 식별·미확인·차단 항목은 배지가 없다
            continue
        g = _grade_norm(b.get("grade"))
        out.append({"kind": b["kind"], "grade": g, "text": _badge_text(b["kind"], g), "evidence_id": b["evidence_id"],
                    "note": fp.BADGE_PREGNANCY_M_NOTE if (b["kind"] == "pregnancy" and g == "M") else None})
    grades = {x["grade"] for x in out if x["kind"] == "pregnancy"}
    if len(grades) > 1:  # 등급 불일치: 합치지 않고 출처 꼬리를 단다(PRD-15-02)
        for x in out:
            if x["kind"] != "pregnancy":
                continue
            it = by_id[x["evidence_id"]]
            sks = [m.get("source_kind") or it.get("source_kind") for m in it.get("matches") or [] if _grade_norm(m.get("grade")) == x["grade"]]
            sk = next((s for s in fp.BADGE_TAIL_ORDER if s in sks), it.get("source_kind"))
            x["source_tail_key"] = sk
            tail = fp.BADGE_SOURCE_TAIL.get(sk or "")
            if tail:
                x["text"] = f"{x['text']} {tail}"

    def key(x: dict[str, Any]) -> tuple[int, int]:
        t = x.get("source_tail_key")
        return _kind_rank(x["kind"]), fp.BADGE_TAIL_ORDER.index(t) if t in fp.BADGE_TAIL_ORDER else len(fp.BADGE_TAIL_ORDER)

    out.sort(key=key)  # 안정 정렬: 병용 → 임부 → 연령, 불일치는 파일 → 성분 API
    return out


def _first_value(items: list[dict[str, Any]], *keys: str) -> str | None:
    """항목들에서 첫 비어 있지 않은 문자열 값(없으면 None). 값을 지어내지 않는다."""
    for it in items:
        for k in keys:
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _dataset_dates(items: list[dict[str, Any]]) -> list[tuple[str | None, str | None]]:
    """항목 순서대로 (자료 이름, 기준일) 쌍. 같은 쌍은 한 번만. 자료 이름은 `kind`로 코드가 정한다(없으면 None).
    날짜는 항목 값만 쓰고 지어내지 않는다."""
    seen: dict[tuple[str | None, str | None], None] = {}
    for it in items:
        label = DATASET_LABELS.get(it.get("kind") or "")
        d = it.get("as_of")
        date = d.strip() if isinstance(d, str) and d.strip() else None
        seen.setdefault((label, date), None)
    return list(seen)


def pregnancy_found_grades(items: list[dict[str, Any]]) -> list[str]:
    """임부금기 **발견으로 보이는** 항목(묶음 FOUND)의 등급 값(`1`·`2`·`M`)을 나온 순서로, 같은 값은 한 번만. 등급 정의 블록 입력용이다."""
    out: dict[str, None] = {}
    for it in items or []:
        if not isinstance(it, dict) or it.get("kind") != "pregnancy" or _bucket(it) != BUCKET_FOUND:
            continue
        for m in it.get("matches") or []:
            g = _grade_norm(m.get("grade")) if isinstance(m, dict) else None
            if g in _GRADES:
                out.setdefault(g, None)
    return list(out)


def fallback_summary(items: list[dict[str, Any]]) -> str:
    """검증 폴백 요약 문구를 코드가 고른다. 확인된 항목(FOUND·NOT_LISTED 묶음)이 있으면 SOME, 없으면 NONE.
    기준일은 자료마다 따로 나열한다(AG-08-03 B)."""
    items = [it for it in items or [] if isinstance(it, dict)]
    confirmed = [it for it in items if _bucket(it) in (BUCKET_FOUND, BUCKET_NOT_LISTED)]
    if confirmed:
        names: list[str] = []
        for label, date in _dataset_dates(confirmed):
            if label is None:
                continue
            text = fp.FALLBACK_SOME_DATASET_DATED.format(label=label, doc_date=date) if date else label
            # 같은 자료가 날짜 없음과 날짜 있음으로 따로 나오면 날짜 있는 쪽만 남긴다
            if date is None and any(n.startswith(label + "(") for n in names):
                continue
            names = [n for n in names if not (date and n == label)]
            if text not in names:
                names.append(text)
        return fp.FALLBACK_SOME_CONFIRMED.format(datasets=fp.FALLBACK_SOME_DATASET_SEP.join(names)) if names else fp.FALLBACK_SOME_NO_DATE
    api_time = _first_value(items, "queried_at_display", "queried_at_utc")
    parts = []
    if api_time:
        parts.append(fp.FALLBACK_NONE_SCOPE_API.format(api_time=api_time))
    for label, date in _dataset_dates(items):
        if date:
            parts.append(fp.FALLBACK_NONE_SCOPE_DOC.format(label=label or fp.FALLBACK_NONE_DOC_LABEL, doc_date=date))
    return fp.FALLBACK_NONE_CONFIRMED.format(scope=", ".join(parts)) if parts else fp.FALLBACK_NONE_NO_SCOPE


def finalize(
    items: list[dict[str, Any]],
    model_summary: str | None = None,
    emergency: bool = False,
    *,
    sentences: list[Sentence] | None = None,
    limit_reached: bool = False,
    refuse_reason: str | None = None,
    grade_def_missing: list[dict[str, Any]] | None = None,
    validation_fallback: bool = False,
    grade_defs: list[dict[str, Any]] | None = None,
    not_checked: list[str] | None = None,
    refuse_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """응답 딕셔너리를 만든다. 고정 문구는 인자·모델 출력과 무관하게 항상 들어간다.

    - `limit_reached`: 모델 호출 상한으로 끝났다. 모델 요약은 쓰지 않고 지금까지의 항목을 코드 문구로 보인다(RFP-33-06).
    - `refuse_reason`: 입구 거절 이유 키(`guardrail.classify_scope`). 거절 문구가 요약 자리에 들어간다.
    - `refuse_reasons`: 거절 이유 키 전부(`guardrail.refuse_reasons`, AG-08-08 A). 주면 이유마다 문구를 받은 순서로 모두 싣는다
      (같은 문구는 한 번만, 모르는 키는 대체 문구). 주지 않으면 `refuse_reason` 하나만 쓴다.
    - `validation_fallback`: 두 번째 검증 실패. 모델 요약은 없고 코드 폴백 문구(`fallback_summary`)가 요약 자리에 들어간다.
    - `grade_def_missing`: `[{"grade": "2", "missing_reason": "FETCH_FAIL"|"OUT_OF_SCOPE"}]` 등급 정의 블록 미확보(PRD-15-03).
    - `grade_defs`: `[{"grade": "2", "text": 원문, "source": 출처 줄}]` 확보한 등급 정의 원문(코드가 청크에서 읽은 글자 그대로, BE-06-16 A).
      미확보와 함께 구조(`grade_defs`: 제목·원문·출처·미확보 사유)로 나간다. 원문이 없는 블록에는 출처 줄이 없다.
    - `not_checked`: 정보가 없어 확인하지 못한 금기 종류 키(예: 임신 여부 미입력 → `["pregnancy"]`, FE-07-16 B). 승인 문장이 있는 종류만 줄이 된다.
      대상이 아닌 종류(임신 아님, 약 하나뿐인 병용)는 넘기지 않는다: 줄을 그리지 않는다(AG-08-18 A).
    """
    items = [it for it in items or [] if isinstance(it, dict)]
    buckets = [(it, _bucket(it)) for it in items]
    buckets.sort(key=lambda p: (p[1], _kind_rank(p[0].get("kind"))))  # 안정 정렬: FOUND 먼저, 같은 묶음은 입력·종류 순서
    entries = [_entry(it, b) for it, b in buckets]
    warnings: list[dict[str, Any]] = [
        {"code": "SOURCE_KIND_BLOCKED", "evidence_id": it.get("evidence_id")}
        for it, b in buckets if b == BUCKET_UNCONFIRMED and it.get("status") in _JUDGED_STATUS
        and (not it.get("source_kind") or it["source_kind"] not in fp.SOURCE_KIND_TEXT)
    ]
    blocked_ids = {w["evidence_id"] for w in warnings}
    found_items = [it for it, b in buckets if b == BUCKET_FOUND]

    rendered = render([it for it in items if it.get("evidence_id") not in blocked_ids], sentences or [])
    warnings.extend(rendered.warnings)
    badges = _badges(found_items, rendered.badges)
    mismatch_ids = {b["evidence_id"] for b in badges if b.get("source_tail_key")}
    for d in rendered.detail:  # 등급 불일치 안내(UI-020): 근거 상세의 그 근거에만 붙인다
        if d.get("evidence_id") in mismatch_ids:
            d["notes"] = [*(d.get("notes") or []), fp.GRADE_MISMATCH_NOTE]
    not_checked_lines = [fp.NOT_CHECKED_LINES[k] for k in dict.fromkeys(not_checked or []) if k in fp.NOT_CHECKED_LINES]

    unresolved = any(e["unresolved"] for e in entries) or limit_reached or bool(not_checked_lines)
    names = list(dict.fromkeys(n for e in entries if e["unresolved"] for n in _names_of(e)))
    advice: list[str] = []
    if any(e["unresolved"] for e in entries):
        advice.append(josa.fill(fp.PHARMACIST_ADVICE, drugs=" · ".join(names)) if names else fp.PHARMACIST_ADVICE_NO_NAMES)
    gd_lines: list[str] = []
    gd_blocks: list[dict[str, Any]] = []
    for g in grade_defs or []:
        grade, text = _grade_norm(g.get("grade")), g.get("text")
        if grade in _GRADES and isinstance(text, str) and text.strip():
            src = g.get("source")
            gd_blocks.append({"grade": grade, "title": fp.GRADE_DEF_TITLE.format(grade=grade), "text": text,
                              "source": src if isinstance(src, str) and src.strip() else None, "missing_reason": None, "missing_text": None})
    for g in grade_def_missing or []:
        tmpl = fp.GRADE_DEF_MISSING_TEXT.get(g.get("missing_reason"))
        if tmpl:
            grade = _grade_norm(g.get("grade")) or ""
            gd_lines.append(tmpl.format(grade=grade))
            if grade in _GRADES:  # 등급 값을 모르는 블록은 구조로 만들지 않는다(줄 문구는 위 목록에 그대로)
                gd_blocks.append(
                    {"grade": grade, "title": fp.GRADE_DEF_TITLE.format(grade=grade), "text": None, "source": None,
                     "missing_reason": g["missing_reason"], "missing_text": gd_lines[-1]})
    if gd_lines:
        advice.append(fp.GRADE_DEF_PHARMACIST_ADVICE)

    refuse_keys = list(refuse_reasons or []) or ([refuse_reason] if refuse_reason else [])
    if refuse_keys:
        texts = dict.fromkeys(fp.REFUSE_MESSAGES.get(k, fp.REFUSE_MESSAGES["OUT_OF_SCOPE"]) for k in refuse_keys)
        summary: str | None = fp.REFUSE_JOIN.join(texts)
    elif limit_reached:
        summary = None  # LLM 요약 없이 코드로만
    elif validation_fallback:
        summary = fallback_summary(items)
    else:
        summary = model_summary.strip() if isinstance(model_summary, str) and model_summary.strip() else None

    events = [{"rule": "H27", "event": "MISSING_REASON", "code": it.get("missing_reason") or "NO_EVIDENCE"}
              for it, _ in buckets if it.get("missing_reason") or it.get("status") == "NO_EVIDENCE"]  # 내용 없는 코드만

    resp: dict[str, Any] = {
        "emergency": fp.EMERGENCY_119 if emergency else None,
        "emergency_tel": fp.EMERGENCY_119_TEL if emergency else None,
        "emergency_wide": fp.EMERGENCY_119_WIDE if emergency else None,
        "route": "REFUSE" if refuse_keys else "AGENT",
        # 배너 칸은 하나다(BE-06-06 A): 상한 도달이 먼저, 아니면 실시간 확인 실패
        "notice": fp.LIMIT_REACHED if limit_reached else (
            fp.NOTICE_API_FAIL if any(f in (it.get("flags") or []) for it in items for f in _API_FAIL_FLAGS) else None),
        "summary": summary,
        "entries": entries,
        "badges": badges,
        "detail": rendered.detail,
        "citations": rendered.citations,
        "not_checked_lines": not_checked_lines,
        "grade_def_missing": gd_lines,
        "grade_defs": gd_blocks,
        "pharmacist_advice": advice,
        "pharmacist_advice_fixed": fp.PHARMACIST_ADVICE_FIXED if unresolved else None,
        "fixed_notice": fp.FIXED_NOTICE,
        "disclaimer": fp.DISCLAIMER,
        "warnings": warnings,
        "events": events,
    }
    resp["text"] = render_text(resp)
    return resp


def _names_of(e: dict[str, Any]) -> list[str]:
    d = e.get("input_name") or e.get("drug")
    return [d] if d and d != "이 약" else []


def render_text(resp: dict[str, Any]) -> str:
    """응답을 화면 순서의 글자로 펼친다(119 맨 위). 시험·로그용 단순 렌더."""
    lines: list[str] = []
    if resp.get("emergency"):
        lines.append(resp["emergency"])
    if resp.get("notice"):
        lines.append(resp["notice"])
    if resp.get("summary"):
        lines.append(resp["summary"])
    for e in resp["entries"]:
        head = f"[{e['drug']}] " if e.get("drug") else ""
        lines.append(head + e["text"])
        for k in ("sub_line", "why", "retried_line", "next", "reference_line", "age_info_line"):
            if e.get(k):
                lines.append("  " + e[k])
        lines.extend("  " + c for c in e.get("age_criteria") or [])
        lines.extend("  " + n for n in e["notes"])
    lines.extend(resp.get("not_checked_lines") or [])
    for g in resp.get("grade_defs") or []:
        if g.get("text"):
            lines.append(g["title"])
            lines.append("  " + g["text"])
            if g.get("source"):
                lines.append("  " + g["source"])
    lines.extend(resp.get("grade_def_missing") or [])
    lines.extend(resp.get("pharmacist_advice") or [])
    if resp.get("pharmacist_advice_fixed"):
        lines.append(resp["pharmacist_advice_fixed"])
    lines.append(resp["fixed_notice"])
    lines.append(resp["disclaimer"])
    return "\n".join(lines)
