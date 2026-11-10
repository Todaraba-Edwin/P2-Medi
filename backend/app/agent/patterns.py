"""성분코드·날짜·등급 정규식과 "도구 값에 있는가" 확인(H29·H30 보조, 순수 함수).

코드 체계가 둘이다: 파일(KIDS) `######AAA`(숫자 6 + 영대문자 3), API(DUR) `D######`.
요약(`summary`)에는 두 형식 모두 나열하지 않는다(AG-06 완료 조건, 근거는 `detail`에).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

DUR_CODE_RE = re.compile(r"(?<![A-Za-z0-9])D\d{6}(?!\d)")
KIDS_CODE_RE = re.compile(r"(?<![A-Za-z0-9])\d{6}[A-Z]{3}(?![A-Za-z0-9])")
ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
GRADE_RE = re.compile(r"(?<!\d)([12])\s*등급")


def find_codes(text: str) -> list[str]:
    """텍스트 안의 성분코드(`D######`·`######AAA`)를 등장 순서대로."""
    hits = [(m.start(), m.group()) for r in (DUR_CODE_RE, KIDS_CODE_RE) for m in r.finditer(text)]
    return [c for _, c in sorted(hits)]


def has_code(text: str) -> bool:
    return bool(DUR_CODE_RE.search(text) or KIDS_CODE_RE.search(text))


def is_dur_code(s: str) -> bool:
    return bool(re.fullmatch(r"D\d{6}", s))


def is_kids_code(s: str) -> bool:
    return bool(re.fullmatch(r"\d{6}[A-Z]{3}", s))


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v)


def _tool_strings(items: list[dict[str, Any]]) -> list[str]:
    return list(_walk_strings(items))


def tool_grades(items: list[dict[str, Any]]) -> set[str]:
    """도구 결과의 등급 값을 '1'·'2'·'M' 형태로 모은다(`'1'`, `'1등급'` 둘 다 받는다)."""
    out: set[str] = set()
    stack: list[Any] = list(items)
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            g = o.get("grade")
            if isinstance(g, str) and g.strip():
                out.add(g.strip().removesuffix("등급").upper())
            stack.extend(o.values())
        elif isinstance(o, (list, tuple)):
            stack.extend(o)
    return out


def unsupported_identifiers(sentence: str, items: list[dict[str, Any]]) -> list[str]:
    """문장 속 코드·ISO 날짜·'1등급/2등급'이 도구 결과에 없으면 그 값을 돌려준다(없으면 빈 목록)."""
    pool = _tool_strings(items)
    bad: list[str] = []
    for token in [*find_codes(sentence), *ISO_DATE_RE.findall(sentence)]:
        if not any(token in s for s in pool):
            bad.append(token)
    grades = tool_grades(items)
    for g in GRADE_RE.findall(sentence):
        if g not in grades:
            bad.append(f"{g}등급")
    return bad
