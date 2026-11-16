"""코드 렌더러(AG-06-01): 도구 결과 `items[]` + 필터를 통과한 문장 → `detail`·`citations[]`·`badges[]`.

- 순수 함수. LLM을 부르지 않고, LLM이 쓴 사실 문장(`Sentence.text`)은 어디에도 쓰지 않는다.
  LLM이 정하는 것은 어떤 근거 ID를 인용하는지(`evidence_ids`)와 인용 범위뿐이다.
- `source_kind`·자료 키·출처·기준일·조회 시각·행 키는 항목 값을 그대로 통과시킨다. 없으면 `None`+경고.
- 화면 문자열(약칭·배지 글자·색)은 만들지 않는다(AG-02 공통 상수 모듈·AG-08 `finalize` 몫).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.answer_schema import Sentence
from app.agent.quote_check import TEXT_FIELDS, build_text_index, resolve_citation

_ROW_FIELDS = ("row_key", "row_evidence_id", "grade", "notice_no", "notice_date", *TEXT_FIELDS)
# 도구 항목 값을 그대로 통과시키는 부가 필드(없으면 None). 꼬리표만으로는 부족한 안내(`notes`: "안전하다는 뜻이 아님" 등),
# 라벨 출처 이름(`label_source`: 쉬운 설명 ↔ 허가사항 원문, PRD-11-05)과 미확보 이유(`missing_reason`, H26)가 여기에 든다.
_PASS_FIELDS = ("drugs", "notes", "cause_codes", "label_source", "missing_reason", "matched_by", "item_seq", "section", "truncated",
                "input_name", "searched", "retried", "retry_hint", "candidates", "name")

W_NO_SOURCE_KIND = "MISSING_SOURCE_KIND"
W_BAD_QUOTE = "QUOTE_NOT_RESOLVED"


@dataclass
class RenderResult:
    detail: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    badges: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _status_rank(status: str | None) -> int:
    return 0 if status == "FOUND" else 1  # FOUND 우선(AG-08), 나머지는 입력 순서 유지(안정 정렬)


def _detail_entry(it: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    eid = it.get("evidence_id")
    sk = it.get("source_kind")
    qa = it.get("queried_at_utc")
    # 조회하지 못한 항목(UNIDENTIFIED·NO_EVIDENCE)은 출처가 없는 것이 정상이다(계약 `check_items`와 같은 기준).
    if sk is None and not (it.get("source") is None and it.get("status") in ("UNIDENTIFIED", "NO_EVIDENCE")):
        warnings.append({"code": W_NO_SOURCE_KIND, "evidence_id": eid})
    rows = [{k: m.get(k) for k in _ROW_FIELDS if k in m} for m in it.get("matches") or []]
    for r in rows:
        r.setdefault("row_key", None)
    return {
        "evidence_id": eid, "kind": it.get("kind"), "status": it.get("status"),
        "dataset_key": it.get("dataset_key"), "source_kind": sk,
        "publisher": it.get("source"), "as_of": it.get("as_of"), "queried_at": qa,
        "flags": list(it.get("flags") or []), "subject": it.get("subject"), "rows": rows,
        **{k: it.get(k) for k in _PASS_FIELDS},
    }


def _grades(it: dict[str, Any]) -> list[str | None]:
    seen: list[str | None] = []
    for m in it.get("matches") or []:
        g = m.get("grade")
        g = g if isinstance(g, str) and g.strip() else None
        if g not in seen:
            seen.append(g)
    return seen or [None]


def render(items: list[dict[str, Any]], sentences: list[Sentence]) -> RenderResult:
    res = RenderResult()
    by_id = {it["evidence_id"]: it for it in items if it.get("evidence_id")}
    row_to_item: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for it in items:
        for m in it.get("matches") or []:
            if m.get("row_evidence_id"):
                row_to_item[m["row_evidence_id"]] = (it, m)

    ordered = sorted(items, key=lambda it: _status_rank(it.get("status")))
    res.detail = [_detail_entry(it, res.warnings) for it in ordered]

    for it in ordered:
        if it.get("status") == "FOUND":
            for g in _grades(it):
                res.badges.append({"kind": it.get("kind"), "grade": g,
                                   "evidence_id": it.get("evidence_id"), "status": "FOUND"})

    index = build_text_index(items)
    seen: set[str] = set()
    for si, s in enumerate(sentences):
        for eid in s.evidence_ids:
            if eid in seen:
                continue
            seen.add(eid)
            if eid in by_id:
                it, row = by_id[eid], None
            elif eid in row_to_item:
                it, row = row_to_item[eid]
            else:
                continue  # 필터가 이미 걸렀어야 할 모르는 ID
            res.citations.append({
                "evidence_id": eid, "sentence_index": si, "source_kind": it.get("source_kind"),
                "dataset_key": it.get("dataset_key"), "publisher": it.get("source"), "as_of": it.get("as_of"),
                "queried_at": it.get("queried_at_utc"),
                "row_key": row.get("row_key") if row else None, "quotes": [],
            })
        for c in s.citations:
            r = resolve_citation(c, index)
            target = next((x for x in res.citations if x["evidence_id"] == c.evidence_id), None)
            if not r.ok or target is None:
                res.warnings.append({"code": W_BAD_QUOTE, "evidence_id": c.evidence_id, "reason": r.reason})
                continue
            target["quotes"].append({"start": c.start, "end": c.end, "text": r.text})  # 글자는 코드가 원문에서 자른 것
    return res
