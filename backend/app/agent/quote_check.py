"""인용 글자 일치(H28). 인용은 `{evidence_id, start, end}`로 지정하고 코드가 원문에서 잘라 넣는다.

근거 원문(canonical text) 정의: 항목 또는 행(`matches[]`)의 글 필드 `TEXT_FIELDS`를 이 순서로, 비어 있지
않은 것만 `"\\n"`으로 이어 붙인 문자열이다. 항목 단위 근거 ID는 행 원문을 `"\\n"`으로 이은 것이다.
`start`·`end`는 이 문자열의 `[start, end)` 글자 위치다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.answer_schema import Citation

TEXT_FIELDS = ("reason", "detail", "content", "remark", "text")
ELLIPSIS = "…"


def _row_text(row: dict[str, Any]) -> str:
    parts = [str(row[f]) for f in TEXT_FIELDS if isinstance(row.get(f), str) and row[f].strip()]
    return "\n".join(parts)


def build_text_index(items: list[dict[str, Any]]) -> dict[str, str]:
    """근거 ID → 원문. 항목 ID와 행 ID(`row_evidence_id`)를 모두 담는다."""
    index: dict[str, str] = {}
    for it in items:
        row_texts: list[str] = []
        for m in it.get("matches") or []:
            t = _row_text(m)
            row_texts.append(t)
            rid = m.get("row_evidence_id")
            if rid:
                index[rid] = t
        # 행이 있으면 항목 원문은 행 원문의 이음이다(라벨 항목은 `text`가 행에도 있어 또 붙이면 두 번 들어간다).
        own = "" if row_texts else _row_text(it)
        joined = "\n".join(t for t in [own, *row_texts] if t)
        if it.get("evidence_id"):
            index[it["evidence_id"]] = joined
    return index


@dataclass(frozen=True)
class QuoteResult:
    ok: bool
    reason: str | None = None  # UNKNOWN_EVIDENCE | OUT_OF_RANGE
    text: str | None = None    # 코드가 원문에서 자른 글자


def resolve_citation(cite: Citation, index: dict[str, str]) -> QuoteResult:
    src = index.get(cite.evidence_id)
    if src is None:
        return QuoteResult(False, "UNKNOWN_EVIDENCE")
    if cite.end > len(src):
        return QuoteResult(False, "OUT_OF_RANGE")
    return QuoteResult(True, None, src[cite.start:cite.end])


def verify_quote_text(quoted: str, source: str) -> bool:
    """인용부호 안 문자열이 원문과 글자 일치하는지. 생략은 `…`로만 허용하고 의역·재배열은 거부한다.

    `…`로 나눈 조각이 모두 원문에 **같은 순서로** 겹치지 않고 나타나야 한다. 조각이 하나도 없으면 거부.
    """
    pieces = [p for p in quoted.split(ELLIPSIS) if p != ""]
    if not pieces:
        return False
    pos = 0
    for p in pieces:
        found = source.find(p, pos)
        if found < 0:
            return False
        pos = found + len(p)
    return True
