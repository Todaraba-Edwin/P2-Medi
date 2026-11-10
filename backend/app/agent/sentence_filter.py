"""문장 필터(H1): 근거 ID가 없거나 모르는 사실 문장을 출력 전에 걸러낸다(순수 함수, LLM 호출 없음).

걸러진 수·이유는 반환값으로만 돌려준다. `events`는 `harness_event` 형식 dict(`{"rule": ...}`,
`backend/app/logging/spans.py`의 `build_record`가 받는 모양)이며 이번 범위에서는 로거에 연결하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.answer_schema import AnswerDraft, Sentence, requires_evidence
from app.agent.patterns import has_code
from app.agent.quote_check import build_text_index, resolve_citation

NO_EVIDENCE = "NO_EVIDENCE"            # 사실 문장인데 근거 ID가 없다
UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"  # 이번 도구 결과에 없는 근거 ID
CODE_IN_TEXT = "CODE_IN_TEXT"          # 요약 문장에 성분코드 형식이 있다(근거 상세에만 둔다)


def known_evidence_ids(items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for it in items:
        if it.get("evidence_id"):
            ids.add(it["evidence_id"])
        for m in it.get("matches") or []:
            if m.get("row_evidence_id"):
                ids.add(m["row_evidence_id"])
    return ids


@dataclass(frozen=True)
class Dropped:
    index: int
    reason: str
    text: str


@dataclass
class FilterResult:
    kept: list[Sentence] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    bad_quotes: int = 0  # 알 수 없는 ID·범위 밖이라 글자를 자를 수 없는 인용 수
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def filter_sentences(draft: AnswerDraft, items: list[dict[str, Any]]) -> FilterResult:
    known = known_evidence_ids(items)
    index = build_text_index(items)
    res = FilterResult()
    for i, s in enumerate(draft.sentences):
        reason = None
        if requires_evidence(s.claim_type) and not s.evidence_ids:
            reason = NO_EVIDENCE
        elif any(e not in known for e in s.evidence_ids):
            reason = UNKNOWN_EVIDENCE
        elif has_code(s.text):
            reason = CODE_IN_TEXT
        if reason:
            res.dropped.append(Dropped(i, reason, s.text))
            continue
        # 인용 검사: 문장에 연결되지 않은 ID이거나 글자를 자를 수 없는 인용은 문장은 남기고 인용만 센다.
        for c in s.citations:
            if c.evidence_id not in s.evidence_ids or not resolve_citation(c, index).ok:
                res.bad_quotes += 1
        res.kept.append(s)
    reasons: dict[str, int] = {}
    for d in res.dropped:
        reasons[d.reason] = reasons.get(d.reason, 0) + 1
    res.events.append({
        "rule": "H1", "event": "SENTENCE_FILTER", "total": len(draft.sentences), "kept": len(res.kept),
        "dropped": res.dropped_count, "reasons": reasons, "bad_quotes": res.bad_quotes,
    })
    return res
