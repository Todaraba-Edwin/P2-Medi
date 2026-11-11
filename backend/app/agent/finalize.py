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
    elif bucket == BUCKET_NOT_LISTED:
        e["text"] = fp.NOT_LISTED
    elif bucket == BUCKET_IDENTIFIED:
        ingr = [i.get("display") or i.get("name_ko") or i.get("name_en") for i in it.get("ingredients") or []]
        ingr = [str(x) for x in ingr if x]
        e["text"] = (fp.IDENTIFIED_LINE.format(drug=e["drug"], ingredients=" · ".join(ingr)) if ingr
                     else fp.IDENTIFIED_LINE_NO_INGR.format(drug=e["drug"]))
    else:
        e["unresolved"] = True
        e["text"] = _unconfirmed_text(it, st, flags)
        if kind == "identify" or st == "UNIDENTIFIED":
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
) -> dict[str, Any]:
    """응답 딕셔너리를 만든다. 고정 문구는 인자·모델 출력과 무관하게 항상 들어간다.

    - `limit_reached`: 모델 호출 상한으로 끝났다. 모델 요약은 쓰지 않고 지금까지의 항목을 코드 문구로 보인다(RFP-33-06).
    - `refuse_reason`: 입구 거절 이유 키(`guardrail.classify_scope`). 거절 문구가 요약 자리에 들어간다.
    - `validation_fallback`: 두 번째 검증 실패. 모델 요약은 없고 코드 폴백 문구(`fallback_summary`)가 요약 자리에 들어간다.
    - `grade_def_missing`: `[{"grade": "2", "missing_reason": "FETCH_FAIL"|"OUT_OF_SCOPE"}]` 등급 정의 블록 미확보(PRD-15-03).
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

    unresolved = any(e["unresolved"] for e in entries) or limit_reached
    names = list(dict.fromkeys(n for e in entries if e["unresolved"] for n in _names_of(e)))
    advice: list[str] = []
    if any(e["unresolved"] for e in entries):
        advice.append(fp.PHARMACIST_ADVICE.format(drugs=" · ".join(names)) if names else fp.PHARMACIST_ADVICE_NO_NAMES)
    gd_lines: list[str] = []
    for g in grade_def_missing or []:
        tmpl = fp.GRADE_DEF_MISSING_TEXT.get(g.get("missing_reason"))
        if tmpl:
            gd_lines.append(tmpl.format(grade=_grade_norm(g.get("grade")) or ""))
    if gd_lines:
        advice.append(fp.GRADE_DEF_PHARMACIST_ADVICE)

    if refuse_reason:
        summary: str | None = fp.REFUSE_MESSAGES.get(refuse_reason, fp.REFUSE_MESSAGES["OUT_OF_SCOPE"])
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
        "route": "REFUSE" if refuse_reason else "AGENT",
        "notice": fp.LIMIT_REACHED if limit_reached else None,
        "summary": summary,
        "entries": entries,
        "badges": badges,
        "detail": rendered.detail,
        "citations": rendered.citations,
        "grade_def_missing": gd_lines,
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
        for k in ("why", "retried_line", "next", "reference_line"):
            if e.get(k):
                lines.append("  " + e[k])
        lines.extend("  " + n for n in e["notes"])
    lines.extend(resp.get("grade_def_missing") or [])
    lines.extend(resp.get("pharmacist_advice") or [])
    if resp.get("pharmacist_advice_fixed"):
        lines.append(resp["pharmacist_advice_fixed"])
    lines.append(resp["fixed_notice"])
    lines.append(resp["disclaimer"])
    return "\n".join(lines)
