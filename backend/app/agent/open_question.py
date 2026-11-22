"""AG-15(축소, 2026-11-22 사용자 답 〔D9〕A·〔D10〕A·〔D11〕A): 약 이름 없는 질문의 사전 안내(찾음/찾을 수 없음 + 판단 고지).

- 질문에 약 이름이 없고(Router 엔티티 0개) 유형이 열린 질문(`open`)이면, 질문 낱말을 **별칭표**(`CLASS_ALIASES`)로만 효능군 코드에 잇고
  ② 제품·성분 사전(`DrugDict`) 제품 행의 허가정보 효능군 `product_type`(예 `[01140]해열.진통.소염제`)에서 그 분류의 표시 이름·제품 수를 찾는다.
- 이 값은 **금기 판정이 아니다**(판정 테이블 ①이 아니다). 금기 여부·금기 성분 목록·"금기 목록에 없음" 표시는 내지 않는다.
- 별칭표에 없는 낱말(예: 감기약 — 사전에 그런 분류가 없다)은 "찾을 수 없음"이다. 분류 이름을 부분 일치로 넓히지 않는다.
- 순수 함수(LLM·I/O 0). 사전 효능군 집계는 `DrugDict` 인스턴스당 한 번(지연 계산, 사전 판 버전 키) 캐시한다.
- 요약 문장 조립(`compose_summary`)은 승인 원문 상수(`fixed_phrases.OPEN_*`·`UNIDENTIFIED_NEXT`)를 이어 붙일 뿐 문장을 새로 만들지 않는다.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import asdict, dataclass
from typing import Any

from app.agent import fixed_phrases as fp
from app.tools.drug_dict import DrugDict

# 질문 낱말 → 효능군 코드(허가정보 `product_type`의 대괄호 안 5자리) 1개. 사용자 승인 데이터(2026-11-22, 계획 보고 photo-ag15-plan §5 별칭표).
CLASS_ALIASES: dict[str, str] = {
    "진통제": "01140", "해열제": "01140", "소염진통제": "01140", "해열진통제": "01140", "진통소염제": "01140",
    "변비약": "02380", "변비": "02380", "하제": "02380",
    "소화제": "02330",
    "기침약": "02220", "가래약": "02220", "진해거담제": "02220",
    "알레르기약": "01410", "항히스타민제": "01410",
    "구충제": "06420",
    "안약": "01310",
}

_PRODUCT_TYPE_RE = re.compile(r"^\[(\d{5})\](.+)$")
# 낱말 경계: 별칭은 낱말(공백·문장부호로 나뉜 조각)의 **첫머리**에서만 맞춘다(뒤의 조사·어미는 허용). 긴 별칭을 먼저 본다
_ALIASES_LONGEST_FIRST = tuple(sorted(CLASS_ALIASES, key=len, reverse=True))
_TOKEN_RE = re.compile(r"[^\s,.?!~…·/()\[\]\"'`]+")


@dataclass(frozen=True)
class OpenLookup:
    """약 이름 없는 질문의 사전 분류 조회 결과. `found=False`면 나머지 칸은 비어 있다(None·0)."""

    found: bool
    class_code: str | None = None
    class_name: str | None = None  # 표시용: 대괄호 코드를 떼고 '.' → '·'
    n_products: int = 0  # 그 분류의 취소 아닌 제품 행 수

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# DrugDict 인스턴스 → (사전 판 버전, {코드: (표시 이름, 취소 아닌 제품 수)})
_INDEX_CACHE: weakref.WeakKeyDictionary[DrugDict, tuple[str, dict[str, tuple[str, int]]]] = weakref.WeakKeyDictionary()


def display_class_name(raw_name: str) -> str:
    """`해열.진통.소염제` → `해열·진통·소염제`. 대괄호 코드는 이미 뗀 이름을 받는다."""
    return raw_name.strip().replace(".", "·")


def class_index(dd: DrugDict) -> dict[str, tuple[str, int]]:
    """사전 제품 행의 효능군 집계 `{코드: (표시 이름, 취소 아닌 제품 수)}`. 인스턴스·사전 판마다 한 번만 계산한다."""
    ver = dd.version
    hit = _INDEX_CACHE.get(dd)
    if hit is not None and hit[0] == ver:
        return hit[1]
    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for p in dd.products:
        m = _PRODUCT_TYPE_RE.match(str(p.get("product_type") or "").strip())
        if not m:
            continue
        code = m.group(1)
        names.setdefault(code, display_class_name(m.group(2)))
        if not p.get("cancelled"):
            counts[code] = counts.get(code, 0) + 1
    idx = {code: (name, counts.get(code, 0)) for code, name in names.items()}
    _INDEX_CACHE[dd] = (ver, idx)
    return idx


def match_alias(text: str) -> str | None:
    """질문에서 처음 나오는 별칭의 효능군 코드. 별칭은 낱말 첫머리에서만 맞춘다. 없으면 None."""
    for tok in _TOKEN_RE.findall(text or ""):
        for alias in _ALIASES_LONGEST_FIRST:
            if tok.startswith(alias):
                return CLASS_ALIASES[alias]
    return None


def open_lookup(text: str, dd: DrugDict) -> OpenLookup:
    """질문 낱말 → 별칭표 → 사전 효능군. 별칭이 없거나, 사전에 그 분류의 취소 아닌 제품이 없으면 `found=False`."""
    code = match_alias(text)
    if code is None:
        return OpenLookup(found=False)
    hit = class_index(dd).get(code)
    if hit is None or hit[1] <= 0:
        return OpenLookup(found=False)
    return OpenLookup(found=True, class_code=code, class_name=hit[0], n_products=hit[1])


def compose_summary(lookup: dict[str, Any] | OpenLookup) -> str:
    """요약 자리 코드 문장(〔D11〕A). 찾음: O1 + 미식별 다음 안내 + O3, 못 찾음: O2 + 미식별 다음 안내 + O3. 문구는 승인 원문 상수 그대로다."""
    d = lookup.to_dict() if isinstance(lookup, OpenLookup) else dict(lookup or {})
    if d.get("found") and d.get("class_name") and int(d.get("n_products") or 0) > 0:
        head = fp.OPEN_CLASS_FOUND.format(cls=d["class_name"], n=f"{int(d['n_products']):,}")
    else:
        head = fp.OPEN_NOT_FOUND
    return f"{head} {fp.UNIDENTIFIED_NEXT}. {fp.OPEN_GUIDE_ONLY}"


__all__ = ["CLASS_ALIASES", "OpenLookup", "class_index", "compose_summary", "display_class_name", "match_alias", "open_lookup"]
