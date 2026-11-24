"""U-30-1 요약 문장 중복 제거(결정론, 순수 함수, LLM·외부 호출 없음).

요약(`summary`)은 모델이 쓴 문장(`sentences[]`)을 Validator·문장 필터가 통과시킨 뒤 `finalize_node`가 공백으로 이은 것이다(`graph/nodes.py`).
모델이 "금기 목록에 없다"는 판정과 "이것만으로 안전하다고 판단할 수 없다"·약사 확인 안내를 한 문장에 쓰고, 이어서 근거를 인용하는 문장에서
같은 판정을 약 이름만 넣어 되풀이하면 사용자는 같은 말을 두 번 읽는다(FE-17 §3.30 U-30-1, ISSUE-035). 이 모듈은 그 되풀이를 **문장 단위로 지운다**.

- 새 문장을 만들지 않는다. 기존 문장 중 하나를 고르고 나머지는 지우기만 한다(지운 문장의 근거 ID·인용은 남는 문장으로 옮겨 근거 연결을 잃지 않는다).
- 문장의 뜻 종류는 정규식 세 가지만 본다(공백을 모두 지운 문장에 매칭): `NOT_LISTED`(금기 목록에 없다·올라 있지 않다), `DISCLAIMER`(안전하다고 판단·단정할 수 없다),
  `PHARMACIST`(약사·약국 확인). 문장이 지워지려면 **그 문장의 뜻 종류가 모두 다른 남는 문장에 이미 있어야** 한다. 따라서 약사 확인·안전 단정 금지 안내는
  한 번도 안 남는 일이 없다.
- 보수적 조건(하나라도 어기면 지우지 않는다): ① 한 절짜리 문장(쉼표·연결어미 없음) ② 임부·연령·용량·제형·등급·확인하지 못함 같은 다른 주제 낱말이 없음
  ③ 인용부호 없음 ④ `NOT_LISTED`·`DISCLAIMER` 중 하나는 있음(약사 확인만 있는 문장은 지우지 않는다) ⑤ 질문 속 약이 1~2개(`n_drugs`)일 때만 의미 같음으로 본다.
  약이 3개 이상이거나 모르면 쌍이 여럿일 수 있어 글자가 완전히 같은 문장만 지운다.
- 용량 숫자·가부 판단·안전 단정은 만들 수 없다(지우기만 한다).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.agent.answer_schema import Sentence

NOT_LISTED = "NOT_LISTED"
DISCLAIMER = "DISCLAIMER"
PHARMACIST = "PHARMACIST"

_WS = re.compile(r"\s+")
# 금기 목록에 없다·올라 있지 않다. 연령금기 "정보가 없다"처럼 목록을 말하지 않는 문장은 잡지 않는다(`금기목록|금기자료` 또는 `금기…올라있지않`이 있어야 한다)
_NOT_LISTED_RES = (
    re.compile(r"금기(?:목록|자료)[^.。]{0,30}?(?:올라있지않|오르지않|오르지못|등재되어있지않|실려있지않|나와있지않|없(?:다고|습니다|어요|음|으며|고|는))"),
    re.compile(r"금기(?:에|에는|에도)?[^.。]{0,12}?(?:올라있지않|오르지않|등재되어있지않)"),
)
_DISCLAIMER_RE = re.compile(
    r"안전[^.。]{0,20}?(?:수는?없|뜻이아니|뜻은아니|아닙니다|아니에요|보장(?:하지|할수|되지)|단정(?:할수|하기|하지)|판단(?:할수|하기|하지))")
_PHARMACIST_RE = re.compile(r"약사|약국")
# 같은 문장 안에 다른 판정·주제가 섞이면 지우지 않는다
_FOUND_RE = re.compile(r"올라있(?:습니다|어요|으며|고)|해당(?:합니다|돼요|됩니다)|금기(?:입니다|예요|이에요)")
_OTHER_TOPIC_RE = re.compile(
    r"임부|임신|연령|나이|세이상|개월|용량|수유|노인|중복|제형|성분단위|성분기준|허가사항|원문|등급|"
    r"확인하지못|확인되지않|확인할수없|확인이필요|정보가없|정보는없|정보만")
_MULTI_CLAUSE_RE = re.compile(r"[,，、;:：]|지만|는데|으며|이며|하며|면서|[하이되있없않었았]고(?!자)")
_QUOTE_RE = re.compile(r"[\"“”「」『』()（）\[\]]")


def _strip(text: str) -> str:
    return _WS.sub("", text)


def classes_of(text: str) -> frozenset[str]:
    """문장의 뜻 종류(`NOT_LISTED`·`DISCLAIMER`·`PHARMACIST`). 해당 없으면 빈 집합."""
    t = _strip(text)
    out: set[str] = set()
    if any(p.search(t) for p in _NOT_LISTED_RES):
        out.add(NOT_LISTED)
    if _DISCLAIMER_RE.search(t):
        out.add(DISCLAIMER)
    if _PHARMACIST_RE.search(t):
        out.add(PHARMACIST)
    return frozenset(out)


def _is_removable(text: str, classes: frozenset[str]) -> bool:
    """지울 수 있는 문장 모양인가: 목록에 없음·안전 단정 금지 뜻이 있고, 한 절이고, 다른 주제·인용·발견 판정이 없다."""
    if not classes & {NOT_LISTED, DISCLAIMER}:
        return False  # 약사 확인만 있는 문장·뜻 종류가 없는 문장(근거 인용·제품 정보 등)은 지우지 않는다
    t = _strip(text)
    return not (_MULTI_CLAUSE_RE.search(t) or _OTHER_TOPIC_RE.search(t) or _FOUND_RE.search(t) or _QUOTE_RE.search(t))


@dataclass(frozen=True)
class Dropped:
    index: int          # 원래 문장 목록에서의 위치
    kept_index: int     # 뜻을 이어받은(근거 ID를 받은) 남은 문장의 원래 위치
    classes: tuple[str, ...]


@dataclass
class DedupeResult:
    sentences: list[Sentence]
    dropped: list[Dropped] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped)


def _merge_into(target: Sentence, src: Sentence) -> Sentence:
    """지운 문장 `src`의 근거 ID·인용을 남는 문장 `target`에 합친다(글자는 건드리지 않는다)."""
    ids = list(dict.fromkeys([*target.evidence_ids, *src.evidence_ids]))
    cites = list(target.citations)
    for c in src.citations:
        if c not in cites:
            cites.append(c)
    return target.model_copy(update={"evidence_ids": ids, "citations": cites})


def dedupe_sentences(sentences: Sequence[Sentence], *, n_drugs: int | None = None) -> DedupeResult:
    """같은 뜻을 되풀이한 요약 문장을 지운다. 지울 것이 없으면 입력과 같은 목록을 돌려준다(`changed`가 False).

    `n_drugs`: 질문 속 약의 수(Router 엔티티). 1~2개일 때만 뜻 종류가 같은 문장을 같은 사실로 본다. 그 밖(3개 이상·모름)은 글자가 같은 문장만 지운다.
    """
    sents = list(sentences)
    feats = [classes_of(s.text) for s in sents]
    alive = [True] * len(sents)
    dropped: list[Dropped] = []
    out = list(sents)

    # 1) 글자가 완전히 같은 문장(공백 차이 무시)은 언제나 뒤쪽을 지운다. 근거 ID는 앞 문장으로 옮긴다
    first_of: dict[str, int] = {}
    for i, s in enumerate(sents):
        key = _strip(s.text)
        if key in first_of:
            j = first_of[key]
            out[j] = _merge_into(out[j], s)
            alive[i] = False
            dropped.append(Dropped(i, j, tuple(sorted(feats[i]))))
        else:
            first_of[key] = i

    # 2) 뜻 종류가 같은 문장(약 1~2개일 때만): 뒤쪽 문장부터 보며, 뜻 종류가 모두 다른 남는 문장에 있으면 지운다
    if n_drugs in (1, 2):
        for i in range(len(sents) - 1, -1, -1):
            if not alive[i] or not feats[i] or not _is_removable(sents[i].text, feats[i]):
                continue
            others = [j for j in range(len(sents)) if j != i and alive[j]]
            covered: set[str] = set().union(*(feats[j] for j in others)) if others else set()
            if not feats[i] <= covered:
                continue
            target = next(j for j in others if feats[j] & feats[i])  # 앞쪽 문장을 먼저 고른다
            out[target] = _merge_into(out[target], sents[i])
            alive[i] = False
            dropped.append(Dropped(i, target, tuple(sorted(feats[i]))))

    kept = [out[i] for i in range(len(sents)) if alive[i]]
    dropped.sort(key=lambda d: d.index)
    return DedupeResult(sentences=kept, dropped=dropped)


__all__ = ["DISCLAIMER", "NOT_LISTED", "PHARMACIST", "DedupeResult", "Dropped", "classes_of", "dedupe_sentences"]
