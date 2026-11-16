"""약 이름 뒤 조사 "을/를"을 받침으로 고른다(AG-08-15 B). 순수 함수, 외부 호출 없음.

고정 문구 원문은 `{drug}을(를)`처럼 적혀 있고(`fixed_phrases`), 화면에 나가기 전에 `fill`이 이름의 마지막 소리로 하나를 고른다.
"을(를)"이 출력에 남지 않는다. 문장 자체는 바꾸지 않는다(조사 한 글자만 고른다).

- 한글: 마지막 글자의 받침 유무.
- 숫자: 한자어로 읽은 소리(0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔은 받침 있음).
- 단위 표기(숫자 뒤 mg·g·mcg·kg은 "그램", ml·l은 "리터", iu는 "아이유")는 읽는 소리로 본다.
- 그 밖의 영문: 마지막 글자 이름(L 엘, M 엠, N 엔, R 알은 받침 있음)으로 본다. 영어 단어를 소리 나는 대로 읽는 것은 아니므로
  어긋날 수 있다(한계). 뒤에 붙은 괄호·기호는 건너뛰고 마지막 글자·숫자를 본다.
- 판단할 글자가 없으면 "를"을 쓴다(가정).
"""

from __future__ import annotations

import re

MARK = "을(를)"
_WITH, _WITHOUT = "을", "를"
_DIGIT_BATCHIM = frozenset("013678")
_LETTER_BATCHIM = frozenset("lmnr")
_UNIT_BATCHIM = re.compile(r"\d\s*(?:mg|mcg|µg|μg|kg|g)$", re.IGNORECASE)
_UNIT_NO_BATCHIM = re.compile(r"\d\s*(?:ml|l|iu)$", re.IGNORECASE)


def _tail(word: str) -> str:
    """끝의 괄호·기호·공백을 뺀 글자열."""
    i = len(word)
    while i > 0 and not word[i - 1].isalnum():
        i -= 1
    return word[:i]


def has_batchim(word: str) -> bool:
    """이름의 마지막 소리에 받침이 있는지. 판단할 글자가 없으면 False."""
    w = _tail(word or "")
    if not w:
        return False
    if _UNIT_BATCHIM.search(w):
        return True
    if _UNIT_NO_BATCHIM.search(w):
        return False
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit():
        return ch in _DIGIT_BATCHIM
    return ch.lower() in _LETTER_BATCHIM


def eul_reul(word: str) -> str:
    """`word` 뒤에 붙일 목적격 조사."""
    return _WITH if has_batchim(word) else _WITHOUT


def fill(template: str, **values: str) -> str:
    """`{key}을(를)` 자리를 값과 고른 조사로 채우고 나머지 `{key}`는 그대로 채운다."""
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}" + MARK, "{" + key + "}" + eul_reul(val))
    return out.format(**values)
