"""임부금기 등급 정의 블록의 입력 만들기(BE-06-16 A, PRD-09-04, PRD-15-03). 순수 함수, LLM·외부 호출 없음.

- 등급 1·2의 뜻은 고시 「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 가목(1등급)·나목(2등급) **청크 원문에서 글자 그대로 자른
  부분 문자열**만 쓴다(의역·이어 붙이기 금지, G7). 자를 수 없으면 원문을 내지 않고 미확보(`FETCH_FAIL`)로 둔다.
- M등급은 고시에 없고 심평원 설명이 원문이라 여기서 블록을 만들지 않는다(규칙 미정).
- `grade_def_inputs`는 `finalize(grade_defs=..., grade_def_missing=...)`에 넘길 두 목록을 만든다. 판정은 바꾸지 않는다(표시만).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agent.finalize import pregnancy_found_grades
from app.agent.tools.corpus import CorpusIndex

# 등급 → 고시 조항 위치(청크 `locator` 글자 그대로)
GRADE_LOCATORS: dict[str, str] = {"1": "제3조 제3호 가목", "2": "제3조 제3호 나목"}
GRADE_MARK = "{grade}등급:"  # 청크 원문 안의 등급 표지. 이 표지 바로 뒤부터 끝까지가 정의 원문이다
SOURCE_LINE = "「{title}」 {locator}"  # 출처 줄(값은 청크의 문서 이름·조항 위치 그대로)
MISSING_FETCH_FAIL = "FETCH_FAIL"

# 등급("1"·"2") → {"text": 원문, "source": 출처 줄} 또는 None(가져오지 못함)
GradeDefFn = Callable[[str], dict[str, Any] | None]


def _cut(chunk: dict[str, Any], grade: str) -> dict[str, Any] | None:
    text = chunk.get("text")
    mark = GRADE_MARK.format(grade=grade)
    if not isinstance(text, str) or mark not in text:
        return None  # 경계를 글자 일치로 자를 수 없다
    body = text[text.index(mark) + len(mark):].strip()
    if not body:
        return None
    title = str(chunk.get("source_ref") or "").split("|", 1)[0].strip()
    source = SOURCE_LINE.format(title=title, locator=chunk["locator"]) if title else str(chunk["locator"])
    return {"text": body, "source": source}


def corpus_grade_def_fn(index: CorpusIndex) -> GradeDefFn:
    """코퍼스 인덱스에서 등급 정의 원문을 읽는 기본 함수를 만든다(L1 고시 청크, `locator` 정확 일치, 기준일이 가장 늦은 것).

    같은 기준일에 원문이 서로 다른 청크가 둘 이상이면 고르지 않고 None을 돌려준다.
    """
    cache: dict[str, dict[str, Any] | None] = {}

    def lookup(grade: str) -> dict[str, Any] | None:
        locator = GRADE_LOCATORS.get(grade)
        if locator is None:
            return None
        hits = [c for c in index.chunks if c.get("layer") == "L1" and c.get("doc_type") == "고시" and c.get("locator") == locator]
        if not hits:
            return None
        latest = max(str(c.get("base_date") or "") for c in hits)
        cuts = [_cut(c, grade) for c in hits if str(c.get("base_date") or "") == latest]
        if any(x is None for x in cuts) or len({x["text"] for x in cuts if x}) != 1:
            return None
        return cuts[0]

    def fn(grade: str) -> dict[str, Any] | None:
        if grade not in cache:
            cache[grade] = lookup(grade)
        got = cache[grade]
        return dict(got) if got else None

    return fn


def grade_def_inputs(items: list[dict[str, Any]], fn: GradeDefFn) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """임부금기 발견 항목의 등급 1·2마다 `fn`을 불러 (`grade_defs`, `grade_def_missing`)을 만든다. 등급은 나온 순서, 같은 등급은 한 번만.

    `fn`이 None·빈 원문을 주거나 예외를 내면 그 등급은 미확보(`FETCH_FAIL`)다. 예외 내용은 남기지 않는다.
    """
    defs: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for grade in pregnancy_found_grades(items):
        if grade not in GRADE_LOCATORS:  # M: 블록을 만들지 않는다
            continue
        try:
            got = fn(grade)
        except Exception:  # noqa: BLE001 — 가져오지 못한 것으로 둔다(응답을 죽이지 않는다)
            got = None
        text = got.get("text") if isinstance(got, dict) else None
        if isinstance(text, str) and text.strip():
            defs.append({"grade": grade, "text": text, "source": got.get("source")})  # type: ignore[union-attr]
        else:
            missing.append({"grade": grade, "missing_reason": MISSING_FETCH_FAIL})
    return defs, missing


__all__ = ["GRADE_LOCATORS", "GradeDefFn", "corpus_grade_def_fn", "grade_def_inputs"]
