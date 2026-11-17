"""BE-07 약품명 유사 후보 조회(오탈자 보정용, FR-07). 네트워크·LLM 호출 없음.

BE-10 사전(`DrugDict`)의 제품명·성분명을 그대로 재사용한다(별도 사전 파일을 만들지 않는다). 이 모듈은 **후보와 점수만** 돌려주고
확정·판정은 하지 않는다. 보정해 진행할지는 Router(AG-10, `app.agent.router`)가 점수·간격 기준으로 정한다.

방식(외부 라이브러리 없음):
  1. 이름을 사전과 같은 정규화 키(`normalize_name`)로 바꾸고 한글 음절을 **자모(초성·중성·종성)**로 푼다. 한 글자 안의 모음·받침 실수
     ("레"→"래", "핀"→"핌")가 음절 단위로는 글자 하나가 통째로 달라지지만 자모 단위로는 한 칸 차이다.
  2. 자모 3-gram 역색인으로 겹치는 조각이 많은 이름만 추린다(`POOL`개). 사전 전체(약 4.7만 이름)에 편집 거리를 재지 않기 위한 가지치기다.
  3. 추린 이름에 자모 편집 거리(삽입·삭제·교체 각 1, 이웃한 두 자모 맞바꿈 1)를 재고 `점수 = 1 - 거리 / 긴 쪽 길이`로 순위를 매긴다.

`lookup_name`의 문자 2-gram BM25(되묻기 후보용)와 다른 점: BM25는 음절 2-gram이 겹치는 정도라 긴 이름·흔한 조각에 끌리고 "얼마나 다른가"를 말해 주지 않는다.
여기 점수는 고친 글자 수(자모 단위)에서 나오므로 "한두 자모만 다르다"를 직접 잴 수 있다.

색인은 사전 객체마다 한 번 만들어 약한 참조로 붙여 둔다(`index_for`). 만드는 시간·조회 지연은 `backend/tests/test_be07_name_similarity.py`가 실사전으로 잰다.
"""

from __future__ import annotations

import re
import time
import weakref
from array import array
from collections import defaultdict
from dataclasses import dataclass

from app.tools.drug_dict import DrugDict, normalize_name

KIND_PRODUCT = "product_name"
KIND_INGREDIENT = "ingredient_name"

NGRAM = 3  # 자모 3-gram(가지치기용). 2-gram은 흔한 조각("ㅈㅓㅇ" 같은 제형 글자)이 많아 추린 묶음이 커진다
POOL = 200  # 편집 거리를 잴 이름 수 상한(겹치는 조각 수 순)
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.5  # 이보다 낮은 후보는 돌려주지 않는다(비슷하다고 부를 수 없는 이름)

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ("", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")
_HANGUL_BASE, _HANGUL_END = 0xAC00, 0xD7A3
_NUM_RE = re.compile(r"\d+")


def to_jamo(text: str) -> str:
    """한글 음절을 초성·중성·종성 자모로 푼다. 한글이 아닌 글자(영문·숫자)는 그대로 둔다."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if _HANGUL_BASE <= code <= _HANGUL_END:
            idx = code - _HANGUL_BASE
            out.append(_CHO[idx // 588])
            out.append(_JUNG[(idx % 588) // 28])
            out.append(_JONG[idx % 28])
        else:
            out.append(ch)
    return "".join(out)


def edit_distance(a: str, b: str, limit: int | None = None) -> int:
    """편집 거리(삽입·삭제·교체 1, 이웃한 두 글자 맞바꿈 1: optimal string alignment). `limit`을 주면 그보다 커지는 순간 `limit + 1`을 돌려준다."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if limit is not None and abs(la - lb) > limit:
        return limit + 1
    if not la or not lb:
        return la or lb
    prev2: list[int] | None = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        best = i
        for j in range(1, lb + 1):
            cb = b[j - 1]
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and j > 1 and ca == b[j - 2] and a[i - 2] == cb and ca != cb:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            if v < best:
                best = v
        if limit is not None and best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb]


def similarity(a: str, b: str) -> float:
    """두 이름의 자모 유사도(0~1). 정규화 키로 바꾼 뒤 잰다. 둘 다 비면 0."""
    ja, jb = to_jamo(normalize_name(a)), to_jamo(normalize_name(b))
    longest = max(len(ja), len(jb))
    return 0.0 if not longest else round(1 - edit_distance(ja, jb) / longest, 4)


def number_signature(key: str) -> tuple[str, ...]:
    """정규화 키에 든 숫자 덩어리(함량 등)를 나온 순서대로. 이름 글자의 오탈자는 고쳐도 **숫자는 고치지 않는다**는 규칙에 쓴다.

    정규화 키는 사전 조회와 같은 규칙이라 `/`·`.` 같은 구분자가 이미 지워져 있다("40/5밀리그램" → "405mg", 숫자 덩어리 "405").
    사전 조회가 구분하지 않는 표기 차이는 여기서도 구분하지 않는다(사전과 같은 기준)."""
    return tuple(_NUM_RE.findall(key))


def _grams(jamo: str) -> set[str]:
    if len(jamo) < NGRAM:
        return {jamo} if jamo else set()
    return {jamo[i:i + NGRAM] for i in range(len(jamo) - NGRAM + 1)}


@dataclass(frozen=True)
class SimilarName:
    """유사 후보 하나. `score`는 자모 유사도(0~1)."""

    name: str  # 이 키를 쓰는 사전 이름 중 대표(가장 짧은 것, 표시용)
    key: str  # 정규화 키(전체 키 또는 괄호를 뗀 기본형 키). `lookup_name(key)`로 다시 조회할 수 있다. 같은 키의 제품이 여럿일 수 있고 후보는 키마다 하나다
    score: float
    distance: int  # 자모 편집 거리
    kind: str  # product_name | ingredient_name
    n_entries: int  # 이 키를 쓰는 사전 항목 수(제품 행·성분 항목)
    numbers: tuple[str, ...]  # 키에 든 숫자(함량)


class SimilarityIndex:
    """사전 이름의 자모 3-gram 역색인. 사전 객체 하나에 하나만 만든다(`index_for`)."""

    def __init__(self, dd: DrugDict) -> None:
        t0 = time.perf_counter()
        self.dict_version = dd.version
        names: dict[str, tuple[str, str, int]] = {}  # 정규화 키 → (대표 이름, 종류, 항목 수). 제품이 성분보다 먼저(제품 우선, 사전 조회 계약과 같다)
        for p in dd.products:
            self._add(names, p["name"], KIND_PRODUCT)
            # 괄호(성분명 병기 등)를 뗀 기본형 키도 넣는다. 사용자는 "…정(성분명)"의 괄호 부분을 쓰지 않으므로 기본형과 비교해야 한두 자모 차이가 드러난다
            # (`lookup_name`의 기본형 일치 단계와 같은 키라, 이 키를 그대로 다시 조회하면 같은 제품이 나온다).
            self._add(names, p["name"], KIND_PRODUCT, keep_paren=False)
        self.n_product_rows = len(dd.products)
        self.n_product_names = len(names)
        for ing in dd.ingredients:
            for nm in ing["names"]:
                self._add(names, nm, KIND_INGREDIENT)
        self.keys: list[str] = list(names)
        self._meta: list[tuple[str, str, int]] = [names[k] for k in self.keys]
        self._jamo: list[str] = [to_jamo(k) for k in self.keys]
        postings: dict[str, array] = defaultdict(lambda: array("I"))
        for i, j in enumerate(self._jamo):
            for g in _grams(j):
                postings[g].append(i)
        self._postings: dict[str, array] = dict(postings)
        self.n_names = len(self.keys)
        self.build_seconds = round(time.perf_counter() - t0, 3)

    @staticmethod
    def _add(names: dict[str, tuple[str, str, int]], raw: str, kind: str, *, keep_paren: bool = True) -> None:
        key = normalize_name(raw, keep_paren=keep_paren)
        if not key or (not keep_paren and key == normalize_name(raw)):  # 괄호가 없는 이름은 전체 키와 같아 한 번만 센다
            return
        cur = names.get(key)
        if cur is None:
            names[key] = (raw.strip(), kind, 1)
        elif cur[1] == kind:  # 같은 키의 다른 행: 대표 이름은 짧은 쪽(기본형에 가까운 이름), 항목 수만 더한다
            rep = raw.strip() if len(raw.strip()) < len(cur[0]) else cur[0]
            names[key] = (rep, kind, cur[2] + 1)

    def stats(self) -> dict[str, int | float | str]:
        """색인 크기 기록(BE-07 §2: 제품명 건수). 값만 돌려주고 어디에도 쓰지 않는다."""
        return {"dict_version": self.dict_version, "n_product_rows": self.n_product_rows, "n_product_names": self.n_product_names,
                "n_names": self.n_names, "n_grams": len(self._postings), "build_seconds": self.build_seconds}

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, *, min_score: float = DEFAULT_MIN_SCORE,
               same_numbers: bool = False) -> list[SimilarName]:
        """`query`와 비슷한 사전 이름 상위 `top_k`개(점수 내림차순, 같으면 거리·키 순으로 결정적).

        - 정규화 키가 사전 이름과 **같은** 것(정확 일치)도 점수 1.0으로 나온다. 정확 일치 여부 판단은 호출자 몫이다(`lookup_name`이 먼저다).
        - `same_numbers=True`이면 질의에 든 숫자(함량)와 숫자 열이 같은 이름만 후보로 삼는다. 질의에 숫자가 없으면 숫자가 없는 이름만 남는다.
        """
        q = normalize_name(query)
        jq = to_jamo(q)
        if not jq or top_k < 1:
            return []
        counts: dict[int, int] = defaultdict(int)
        for g in _grams(jq):
            for i in self._postings.get(g, ()):
                counts[i] += 1
        if not counts:
            return []
        qnum = number_signature(q)
        pool = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:POOL]
        lq = len(jq)
        out: list[SimilarName] = []
        for i, _ in pool:
            key = self.keys[i]
            nums = number_signature(key)
            if same_numbers and nums != qnum:
                continue
            jc = self._jamo[i]
            longest = max(lq, len(jc))
            limit = int(longest * (1 - min_score))  # 이 거리를 넘으면 점수가 `min_score` 아래라 더 재지 않는다
            d = edit_distance(jq, jc, limit)
            if d > limit:
                continue
            name, kind, n = self._meta[i]
            out.append(SimilarName(name=name, key=key, score=round(1 - d / longest, 4), distance=d, kind=kind, n_entries=n, numbers=nums))
        out.sort(key=lambda c: (-c.score, c.distance, c.kind != KIND_PRODUCT, c.key))
        return out[:top_k]


_INDEXES: weakref.WeakKeyDictionary[DrugDict, SimilarityIndex] = weakref.WeakKeyDictionary()


def index_for(dd: DrugDict) -> SimilarityIndex:
    """사전 객체의 유사도 색인(처음 부를 때 만든다. 사전 객체가 사라지면 함께 사라진다)."""
    idx = _INDEXES.get(dd)
    if idx is None:
        idx = _INDEXES[dd] = SimilarityIndex(dd)
    return idx


def similar_names(dd: DrugDict, query: str, top_k: int = DEFAULT_TOP_K, *, min_score: float = DEFAULT_MIN_SCORE,
                  same_numbers: bool = False) -> list[SimilarName]:
    """BE-07 조회 함수: 문자열을 받아 유사 후보 상위 N개를 점수와 함께 돌려준다."""
    return index_for(dd).search(query, top_k, min_score=min_score, same_numbers=same_numbers)
