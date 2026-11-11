"""AG-05 `router` 노드의 규칙 기반 부분(입력 정리). LLM·네트워크 호출 없는 순수 함수.

하는 일(RFP-25-02 A: Router는 입력 정리만 한다. 경로(도구) 선택은 `model`이 한다):
  1. 질문 문장에서 약 이름 후보를 규칙으로 뽑는다(조사 제거, "이랑/하고/와" 분리, 붙여 쓴 입력 분리).
  2. 후보마다 `DrugDict.lookup_name`을 부르고 결과를 `entities[]`로 옮긴다. **후보가 여럿이면 하나로 고르지 않는다**(H11).
  3. 모호·오탈자 의심·근거 없음을 판정하고, 되묻기 문장은 코드 템플릿으로 만든다(후보 최대 5개, 가부 언급 없음).
  4. 요청 유형 라벨(`intent`)과 연령·임신 여부(질문 문장 또는 프로필)를 기록한다.

하지 않는 일:
  - **응급 키워드 감지·범위 외 판별은 AG-08 Guardrail 한 곳의 일이다.** 이 파일에는 응급 키워드 목록이 없다.
    Router는 `emergency`·`guardrail_route`를 입력 필드로 받아 그대로 통과시킨다(읽기 전용, 결과를 바꾸지 않는다).
  - 금기 판정, 도구 호출, 성분코드 결정(코드는 사전이 돌려준 값만 `code_status`로 전한다).
  - 질문·연령·임신 여부를 저장하거나 로그에 쓰는 일(상태에만 존재한다).

상태 필드(RFP-23 §4.4·PJ2-Agent-Harness.md 3.5절): 문서에 있는 것은 `profile`·`drug_mentions`·`intent`.
`entities`·`branch_label`·`ambiguous`·`clarify`·`truncated`는 **이 모듈의 제안**이다(문서 반영은 티켓·문서 몫).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.drug_dict import (
    MATCH_BM25,
    MATCH_CONTAINS,
    MATCH_EXACT,
    MATCH_NORMALIZED,
    MATCH_PREFIX,
    MATCHED_BY_INGREDIENT,
    Candidate,
    DrugDict,
    LookupResult,
    normalize_name,
)

# --------------------------------------------------------------------------- 상수

MAX_DRUGS = 6  # 한 질문에서 다루는 약 상한. 6개 = 15쌍(AG-02 쌍 조합 가정). 도구 쪽 상한 8개(schemas.MAX_DRUGS)보다 보수적으로 둔다
MAX_CLARIFY_OPTIONS = 5  # 되묻기 후보 상한
# BM25 1위 점수가 이 이하면 "오탈자 의심" 라벨(AG-05 §2 역할 A, AG-05-01 A).
# 보정(2026-11-11, AG-04 개발셋 dev_set.jsonl, `backend/scripts/calibrate_router.py`): 격자 0.30~0.90 중 0.55~0.90에서 오탈자 TYPO 재현율이
# 14/17(82%, Wilson 95% 59~94%)로 같고 0.50 이하는 하락(12/17 이하), 음성 중 TYPO 오분류 0/22. 값 사이 차이가 구간에 묻혀 현 값 유지(근거 불충분).
# 개발셋은 합성이고 BM25 일치가 26건뿐이라 소표본이다. 시험셋은 쓰지 않았다.
TYPO_SCORE_MAX = 0.6
# BM25 1위 점수가 이 이하이면 오탈자 의심(TYPO_SUSPECT)이 아니라 NOT_FOUND(근거 없음)로 본다(AG-05-02 A). **후보 제시는 유지**한다
# (`options`·되묻기 "혹시 …인가요?"는 그대로 나오고 상태·분기만 근거 없음). 0.0 = 비활성(BM25 점수는 사전 계약상 항상 BM25_MIN_NORM=0.15 이상).
# 사전 계약 값 `BM25_MIN_NORM`을 올리지 않고 Router 쪽 별도 임계값으로 둔 이유: BM25_MIN_NORM은 `lookup_name`을 쓰는 모든 호출자(AG-02 identify_drug 등)의
# 후보 컷이라 올리면 그쪽 후보가 조용히 사라진다. Router의 상태 라벨만 바꾸는 쪽이 계약을 덜 건드린다.
# 보정(2026-11-11, `backend/scripts/calibrate_router.py`, 개발셋, 선택 규칙은 측정 전에 고정): 가상 약 BM25 1위 점수(0.15~0.63)와 오탈자 약(0.20~0.52)이 겹쳐
# 점수만으로는 못 가른다. 오탈자→NOT_FOUND 상한(10%)·전체 오분류 상한(5%)을 지키는 최대 후보 0.20은 가상 약 재현율 3/13 [8~50%]로 비활성 1/13 [1~33%]와 구간이 겹쳐
# **근거 불충분 → 비활성(0.0) 유지**. 0.45 이상은 가상 약 11/13이지만 오탈자 11/17이 NOT_FOUND로 가 안전 방향이 아니다. 개발셋 소표본, 시험셋은 쓰지 않았다.
NOT_FOUND_SCORE_MAX = 0.0

# Router가 상태에 쓸 수 있는 키(PostToolUse의 `POST_WRITABLE_KEYS`와 같은 방식의 제한). emergency·route·messages·evidence·answer는 못 쓴다.
# `profile`·`drug_mentions`·`intent`는 RFP-23 §4.4 문서 필드, 나머지는 제안.
ROUTER_WRITABLE_KEYS = frozenset({"profile", "drug_mentions", "intent", "entities", "branch_label", "ambiguous", "clarify", "truncated"})

# 분기 라벨(AG-04 평가 세트 composition 어휘와 같다: 정상·오탈자·모호·근거 없음)
BRANCH_NORMAL = "정상"
BRANCH_TYPO = "오탈자"
BRANCH_AMBIGUOUS = "모호"
BRANCH_NO_EVIDENCE = "근거 없음"

# 엔티티 상태
ST_RESOLVED = "RESOLVED"
ST_AMBIGUOUS = "AMBIGUOUS"
ST_TYPO = "TYPO_SUSPECT"
ST_NOT_FOUND = "NOT_FOUND"  # 사전에 없음. "안전하다"는 뜻이 아니라 "확인 못 함"이다

FLAG_NO_PRODUCT_INFO = "NO_PRODUCT_INFO"  # H17: 성분 단위 일치, 제품 정보 없음(막지 않음)
FLAG_CODE_NOT_LINKED = "CODE_NOT_LINKED"  # 사전이 KIDS 코드를 붙이지 못함 → 도구는 UNIDENTIFIED 처리(NOT_LISTED 아님)
FLAG_SIMILAR_SHOWN = "SIMILAR_NAMES_SHOWN"  # NOT_FOUND이지만 비슷한 이름 후보를 보여 준다(근거 없음 가능, AG-05-02 A)
FLAG_SAME_NAME_INGREDIENT = "ALSO_INGREDIENT_NAME"  # 제품명이면서 성분명이기도 함(제품 우선, 사전 노트)

INTENT_CONTRA = "contraindication"
INTENT_DRUG_INFO = "drug_info"
INTENT_DOCUMENT = "document"
INTENT_OPEN = "open"

_STRONG = {MATCH_EXACT, MATCH_NORMALIZED, MATCH_PREFIX, MATCH_CONTAINS}  # BM25가 아닌 이름 일치

# --------------------------------------------------------------------------- 모델


class ProfileState(BaseModel):
    """연령·임신 여부. 요청 처리 중 상태에만 있고 저장·로깅하지 않는다(AG-05 §2)."""

    model_config = ConfigDict(extra="forbid")

    age_years: float | None = None
    pregnant: bool | None = None
    source: Literal["question", "profile", "none"] = "none"  # 값이 어디서 왔나(질문 문장이 프로필보다 우선)


class ClarifyOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    item_seq: str | None = None
    entp_name: str | None = None
    prescription: str | None = None
    matched_by: str
    score: float


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str  # 사전 조회에 쓴 문자열(조사 제거 후. 떨어진 함량을 붙여 맞았으면 붙인 문자열)
    strength: str | None = None  # 질문 속 함량 표기("500mg", "2.5밀리그램/0.5밀리리터"). 판정·용량 결정에 쓰지 않고 이름 조회에만 쓴다
    normalized: str
    status: Literal["RESOLVED", "AMBIGUOUS", "TYPO_SUSPECT", "NOT_FOUND"]
    branch: str  # 정상 | 오탈자 | 모호 | 근거 없음
    matched_by: str | None = None  # product_name | ingredient_name | None
    match_type: str | None = None
    resolved: bool = False
    needs_clarification: bool = False
    n_candidates: int = 0
    code_status: str | None = None  # resolved일 때만: linked | component_only | none
    item_seq: str | None = None  # resolved이고 제품 일치일 때만. 모호하면 None(임의 선택 금지)
    flags: list[str] = Field(default_factory=list)
    options: list[ClarifyOption] = Field(default_factory=list)  # 최대 5


class Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    target_raw: str  # 되묻는 엔티티(한 번에 하나만 묻는다)
    options: list[ClarifyOption]
    pending_raws: list[str] = Field(default_factory=list)  # 이번에 묻지 않은 다른 모호 엔티티(다음 턴)


class RouterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_mentions: list[str] = Field(default_factory=list)  # RFP-23 §4.4
    entities: list[Entity] = Field(default_factory=list)  # 제안
    intent: list[str] = Field(default_factory=list)  # RFP-23 §4.4(한 질문에 여러 유형 가능)
    profile: ProfileState = Field(default_factory=ProfileState)  # RFP-23 §4.4
    branch_label: str = BRANCH_NORMAL  # 제안
    ambiguous: bool = False  # 제안: True면 model로 가지 않고 되묻기로 끝낸다
    clarify: Clarify | None = None  # 제안
    truncated: bool = False  # 제안: 약이 MAX_DRUGS를 넘어 앞의 MAX_DRUGS개만 남김
    n_pairs: int = 0  # resolved 엔티티 기준 쌍 수(쌍 나누기는 코드, 조회는 model이 도구로)
    emergency: bool = False  # 입력 통과(AG-08이 쓴 값, Router는 읽기만)
    guardrail_route: str | None = None  # 입력 통과
    dict_version: str = ""

    def state_update(self) -> dict[str, Any]:
        """그래프 상태에 쓸 dict. `ROUTER_WRITABLE_KEYS`에 든 키만 담는다(emergency·route는 담지 않는다)."""
        out = {
            "profile": self.profile.model_dump(),
            "drug_mentions": list(self.drug_mentions),
            "intent": list(self.intent),
            "entities": [e.model_dump() for e in self.entities],
            "branch_label": self.branch_label,
            "ambiguous": self.ambiguous,
            "clarify": self.clarify.model_dump() if self.clarify else None,
            "truncated": self.truncated,
        }
        if not set(out) <= ROUTER_WRITABLE_KEYS:
            raise RuntimeError("Router가 쓸 수 없는 상태 키")
        return out


# --------------------------------------------------------------------------- 후보 추출

_PARTICLES = tuple(sorted((
    "이랑", "하고", "이나", "이고", "에는", "에서", "으로", "에도", "까지", "부터", "이라도", "이라고", "이며",
    "랑", "과", "와", "이", "가", "은", "는", "을", "를", "도", "만", "에", "로", "의", "나", "고", "며",
), key=len, reverse=True))

_CONNECTORS = ("이랑", "하고", "이나", "랑", "과", "와", "및", "나")  # 붙여 쓴 입력("타이레놀이랑이부프로펜") 분리용
_SPLIT_RE = re.compile(r"[,，+·&、;]|(?<!\d)/|/(?!\d)|\s+")  # 숫자 사이 "/"(5/850밀리그램)는 약 이름의 일부라 나누지 않는다
_PUNCT_RE = re.compile(r"^[\s\"'`(\[{<]+|[\s?!.…~\"'`)\]}>]+$")
_NUM_UNIT_RE = re.compile(
    r"^\d+(\.\d+)?\s*(살|세|개월|주|주차|일|시간|번|회|kg|키로|밀리그램|밀리그람|밀리리터|mg|mcg|μg|ug|ml|g|l|알|정|포|캡슐|병|방울)$", re.IGNORECASE
)
_UNIT_ONLY_RE = re.compile(r"^(밀리그램|밀리그람|밀리리터|mg|mcg|μg|ug|ml|g|l)$", re.IGNORECASE)  # 용량 단위만 떨어져 나온 토큰
_AGE_YEAR_RE = re.compile(r"(\d{1,3})\s*(?:살|세)")
_AGE_MONTH_RE = re.compile(r"(\d{1,3})\s*개월")
_PREG_NEG_RE = re.compile(r"임신\s*(?:은\s*)?(?:하지\s*않|안\s*했|안\s*한|아니|중이\s*아니|가능성\s*없)")
_PREG_RE = re.compile(r"임신|임부|임산부|예비\s*맘|만삭")

# 약 이름이 아닌 단어(질문 문장 성분). 목록은 합성 예문으로 점검한 최소 집합이다(실제 질문 분포는 AG-04 개발셋으로 보강).
_STOP_WORDS = frozenset("""
같이 함께 동시에 동시 먹어도 먹어 먹고 먹는 먹을 먹으면 먹었는데 먹었어요 먹었어 복용 복용해도 복용중 복용하고 드셔도 드세요
되나요 돼요 될까요 되나 돼 안되나요 괜찮나요 괜찮아요 괜찮을까요 가능한가요 가능해요 가능
어떻게 무엇 뭐 뭔가요 어떤 무슨 언제 얼마 왜 혹시 그리고 또는 그럼 그런데 하지만 그래도
약 약을 약이 약은 약도 약들 약이랑 알약 상비약 진통제 해열제 감기약 소화제 영양제 비타민
저 제가 저는 저희 우리 우리집 집에 집에서 집에있는 있는 있어요 있어 없어요 있나요 있습니다
임신 임신중 임신중인데 임부 임산부 중 중인데 중이에요 중입니다 아기 아이 아이가 아이는 아이에게 어린이 애기 애 유아 영아 신생아 아들 딸 엄마 아빠 할머니 할아버지 노인 고령자 어르신 부모님
나이 살 세 개월 주차 체중
및 이랑 하고 그리고 랑 과 와 도 만
상호작용 병용 금기 병용금기 연령금기 임부금기 주의 부작용 효능 효과 용법 용량 용법용량 설명 알려줘 알려주세요 알려 확인 확인해줘 확인해주세요
피해야 피해야할 해야 할 하는 하나요 않나요 좋나요 좋아요 뭐예요 뭐에요 뭔지 뭔가 무엇인가요 문의 질문 궁금 궁금해요 궁금합니다 괜찮은지 되는지 되는가 인지 인가 인가요 맞나요 맞아요
같은 같은데 이런 저런 이것 저것 이거 저거 그거 그것 이약 그약 이 그 저
어머니 어머님 아버지 아버님 남편 아내 형 누나 동생 언니 오빠 손주 손자 손녀 가족 친구 환자 본인 병원 의사 약사 약국 의원 응급실
지금 방금 아까 계속 이미 아직 바로 너무 정말 진짜 실수 갑자기 먼저 나중 오늘 어제 내일 아침 저녁 밤 낮 하루 한꺼번 한번 가끔 자주 처음 다시 또 더 덜
등급 이유 쌍마다 쌍 정도 때문 경우 중에 후에 전에 사이 동안 매일
""".split())
_STOP_SUFFIX_RE = re.compile(
    r"(어도|아도|해도|해요|나요|까요|할까|될까|인가요|인가|인지|입니다|예요|이에요|어요|아요|돼요|되나|됩니까|합니까|있나|있어|없나|줘|주세요|하세요|"
    r"먹어|먹고|먹는|먹을|먹으면|먹었|드셔|드세요|복용|되는지|하는지|한가요|인데|는데|은데|ㄴ데)$"
)


def _clean_token(tok: str) -> str:
    return _PUNCT_RE.sub("", tok)


# 용언·부사 어미(일반 규칙, AG-05-01 보정). 사전에 이름으로 정확히 있으면 적용하지 않는다(`_is_noise`의 `dd`).
_VERB_END_RE = re.compile(r"(해서|돼서|되서|네요|어야|아야|여야|려고|는지|은지|냐|죠|자|다|까|어|아|여|야|서|면|지|도|게|라|래)$")
_SYMPTOM_END_RE = re.compile(r"(염|통|증|감기|병|질환|장애)$")  # 증상·질환 명사(약 이름이 아님). 사전에 정확히 있으면 제외하지 않는다


def _is_noise(tok: str, dd: DrugDict | None = None) -> bool:
    vs = _variants(tok)
    if len(tok) < 2 or any(_NUM_UNIT_RE.match(v) or _UNIT_ONLY_RE.match(v) or v in _STOP_WORDS for v in vs):
        return True
    if re.fullmatch(r"[\d.,%/\-]+", tok):
        return True
    if _STOP_SUFFIX_RE.search(tok):
        return True
    if dd is not None and (_VERB_END_RE.search(tok) or _SYMPTOM_END_RE.search(tok)):
        return not any(_strong(dd, v) for v in vs)
    return False


def _strip_particle(tok: str) -> str:
    for p in _PARTICLES:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[: -len(p)]
    return tok


def _variants(tok: str) -> list[str]:
    """조사를 뗀 변형(원형 → 한 번 뗌 → 두 번 뗌). 원형이 사전 이름과 정확히 맞으면 그것을 우선한다."""
    out = [tok]
    cur = tok
    for _ in range(2):
        nxt = _strip_particle(cur)
        if nxt == cur:
            break
        out.append(nxt)
        cur = nxt
    return out


def _lookup_best(dd: DrugDict, tok: str) -> tuple[str, LookupResult]:
    """조사 변형 중 이름 일치(비BM25)가 되는 첫 변형의 조회 결과. 없으면 조사를 한 번 뗀 변형의 결과."""
    vs = _variants(tok)
    results: list[tuple[str, LookupResult]] = []
    for v in vs:
        r = dd.lookup_name(v, top_k=MAX_CLARIFY_OPTIONS)
        results.append((v, r))
        if not r.empty and r.match_type in _STRONG:
            return v, r
    return results[1] if len(results) > 1 else results[0]


_RANK = {MATCH_EXACT: 3, MATCH_NORMALIZED: 3, MATCH_PREFIX: 2, MATCH_CONTAINS: 2, MATCH_BM25: 1}


def _rank(r: LookupResult) -> int:
    return 0 if r.empty else _RANK.get(r.match_type or "", 1)


def _strength_key(strength: str) -> str:
    return normalize_name(strength)


def _prefer_strength(dd: DrugDict, used: str, r: LookupResult, strength: str) -> LookupResult:
    """이름 일치(비BM25)로 후보가 여럿이면 함량이 이름에 든 후보를 앞으로 옮긴다(순서만 바꾼다. 상태·후보 수·일치 종류는 그대로).
    BM25 결과는 1위 점수가 오탈자·근거 없음 판정에 쓰이므로 순서를 바꾸지 않는다."""
    sk = _strength_key(strength)
    if r.empty or r.match_type == MATCH_BM25 or len(r.candidates) < 2 or not sk:
        return r
    wide = dd.lookup_name(used, top_k=max(MAX_CLARIFY_OPTIONS, r.total_candidates))
    if wide.match_type != r.match_type or wide.total_candidates != r.total_candidates:
        return r
    cands = sorted(wide.candidates, key=lambda c: 0 if sk in normalize_name(c.name) else 1)  # 안정 정렬: 같은 그룹 안 순서 유지
    return dataclasses.replace(r, candidates=tuple(cands[: len(r.candidates)]))


def lookup_mention(dd: DrugDict, m: Mention) -> tuple[str, LookupResult, str | None]:
    """후보 하나의 사전 조회 문자열을 고른다. (조회에 쓴 문자열, 결과, 함량 표기)를 돌려준다.

    시도 순서(더 구체적인 것 먼저): ① 토큰 그대로(붙은 함량 포함, 지금까지의 동작) ② 토큰+떨어진 함량 ③ 함량을 뗀 이름.
    일치 등급(정확·정규화 3 > 접두·중간 2 > BM25 1 > 없음 0)이 가장 높은 것을 쓰고, 같으면 앞의 것을 쓴다.
    ①이 정확·정규화 일치면 지금과 같은 결과다. ③을 썼고 후보가 여럿이면 함량이 든 후보를 앞으로 옮긴다(되묻기 유지, 자동 확정 없음)."""
    used, r = _lookup_best(dd, m.token)
    name, glued = split_strength(m.token)
    strength = "/".join(s for s in (glued, m.strength) if s) or None
    if _rank(r) == 3 or not strength:
        return used, r, strength
    # 대체 조회(②·③)는 이름 일치(접두·중간 이상)일 때만 쓴다. BM25 후보로 ①을 덮으면 없는 약이 오탈자로 보일 수 있다(안전 방향 유지).
    best_used, best, name_only = used, r, not glued   # ① 함량이 떨어져 있었으면 ①이 곧 ③(이름만)이다
    if m.tail:  # ② 토큰+떨어진 함량(원문 `/` 유지): 더 구체적이라 동률이어도 ①보다 앞선다
        u2, r2 = _lookup_best(dd, used + m.tail)
        if _rank(r2) >= 2 and _rank(r2) >= _rank(best):
            best_used, best, name_only = u2, r2, False
    if glued and _rank(best) < 3:  # ③ 붙은 함량을 뗀 이름: 더 높은 등급일 때만
        u3, r3 = _lookup_best(dd, name)
        if _rank(r3) >= 2 and _rank(r3) > _rank(best):
            best_used, best, name_only = u3, r3, True
    if name_only:
        best = _prefer_strength(dd, best_used, best, strength)
    return best_used, best, strength


def _strong(dd: DrugDict, tok: str) -> bool:
    r = dd.lookup_name(tok, top_k=1)
    return not r.empty and r.match_type in (MATCH_EXACT, MATCH_NORMALIZED)


def _split_joined(dd: DrugDict, tok: str) -> list[str]:
    """붙여 쓴 입력을 연결어에서 나눈다. 왼쪽이 사전 이름과 정확히 맞고 오른쪽이 2자 이상일 때만 나눈다(와파린 같은 이름 보호)."""
    if len(tok) < 5:
        return [tok]
    for i in range(2, len(tok) - 1):
        for c in _CONNECTORS:
            if tok.startswith(c, i) and len(tok) - i - len(c) >= 2:
                left, right = tok[:i], tok[i + len(c):]
                if _strong(dd, left):
                    return [left, *_split_joined(dd, right)]
    return [tok]


# --------------------------------------------------------------------------- 함량(AG-05 후속, 2026-11-11)
# 약 이름 뒤에 붙거나 공백·`/`로 떨어진 함량("…정 500 mg", "…주2.5밀리그램/0.5밀리리터", "…서방정 10/5mg")을 이름에서 분리해
# 사전 조회 후보를 고른다. 사전 조회 규칙·점수 기준(`TYPO_SCORE_MAX`·`NOT_FOUND_SCORE_MAX`)은 그대로이고, Router가 조회 *문자열*만 고른다.
# 함량은 질량·부피·역가 단위만 본다(정·알·포처럼 개수를 세는 단위는 복용량이라 함량으로 붙이지 않는다).
_STR_UNIT = r"(?:mg|mcg|μg|µg|ug|g|ml|l|iu|밀리그램|밀리그람|마이크로그램|그램|그람|밀리리터|리터|단위|%)"
_STR_NUM = r"\d+(?:\.\d+)?"
_STRENGTH_CORE = _STR_NUM + r"(?:/" + _STR_NUM + r")*" + _STR_UNIT + r"?(?:/" + _STR_NUM + r"?" + _STR_UNIT + r")*"
_STRENGTH_ONLY_RE = re.compile(r"^(?:" + _STRENGTH_CORE + r"|" + _STR_UNIT + r"|/" + _STRENGTH_CORE + r")$", re.IGNORECASE)
_HAS_UNIT_RE = re.compile(_STR_UNIT + r"$", re.IGNORECASE)
_STRENGTH_TAIL_RE = re.compile(r"^(?P<name>.*?[^\d./])(?P<strength>" + _STR_NUM + r"(?:/" + _STR_NUM + r")*" + _STR_UNIT + r"(?:/" + _STR_NUM + r"?" + _STR_UNIT + r")*)$",
                               re.IGNORECASE)


def _strip_all_particles(tok: str) -> str:
    vs = _variants(tok)
    return vs[-1]


def _strength_piece(tok: str) -> str | None:
    """토큰(조사 포함 가능)이 함량 조각(숫자·단위·`/`)뿐이면 조사를 뗀 조각, 아니면 None."""
    for v in _variants(tok):
        if _STRENGTH_ONLY_RE.match(v):
            return v
    return None


def split_strength(tok: str) -> tuple[str, str | None]:
    """이름에 붙은 함량 꼬리를 뗀다("가나다정500mg" → ("가나다정", "500mg")). 단위가 있어야 떼고, 이름 부분은 2자 이상이어야 한다."""
    m = _STRENGTH_TAIL_RE.match(_strip_all_particles(tok))
    if not m or len(m.group("name")) < 2:
        return tok, None
    return m.group("name"), m.group("strength")


@dataclass(frozen=True)
class Mention:
    """질문에서 뽑은 약 후보 하나. `token`은 질문 원문 조각(붙어 있는 함량 포함), `tail`은 공백·`/`로 떨어져 뒤따른 함량의
    원문 표기(공백 제거, `/` 유지. 예: "25mg", "/0.5밀리리터", "10/5mg")."""

    token: str
    tail: str | None = None

    @property
    def strength(self) -> str | None:
        return self.tail.lstrip("/") if self.tail else None


_ATTACH_SEP_RE = re.compile(r"^[\s/]*$")  # 이름과 함량 사이에 공백·`/`만 있을 때 붙인다(쉼표·접속어가 있으면 다른 약이다)


def _raw_tokens(text: str) -> list[tuple[str, str]]:
    """(토큰, 바로 앞 구분자 원문). 구분자는 `_SPLIT_RE`가 지운 문자(공백·`/`·쉼표 등)를 모은 것이다."""
    out: list[tuple[str, str]] = []
    sep, pos = "", 0
    s = text or ""
    for m in _SPLIT_RE.finditer(s):
        seg = s[pos:m.start()]
        if seg:
            out.append((seg, sep))
            sep = ""
        sep += m.group()
        pos = m.end()
    if s[pos:]:
        out.append((s[pos:], sep))
    return [(_clean_token(t), sp) for t, sp in out if _clean_token(t)]


def extract_mention_details(text: str, dd: DrugDict) -> list[Mention]:
    """`extract_mentions`와 같은 후보에, 공백·`/`로 바로 뒤따른 함량 조각을 원문 표기(`/` 유지)로 붙여 돌려준다(중복 제거, 등장 순서)."""
    out: list[Mention] = []
    seen: dict[str, int] = {}
    toks = _raw_tokens(text)
    i = 0
    last_name_at: int | None = None  # 바로 앞 토큰이 약 후보였는지(함량은 이름 바로 뒤에 올 때만 붙인다)
    while i < len(toks):
        tok, sep = toks[i]
        piece = _strength_piece(tok)
        if piece is not None:
            # 떨어진 함량 조각을 하나로 모은다: "500" "mg" → "500mg", "2.5밀리그램" "/" "0.5밀리리터" → "2.5밀리그램/0.5밀리리터".
            tail = ("/" if "/" in sep else "") + piece
            j = i + 1
            while j < len(toks) and (nxt := _strength_piece(toks[j][0])) is not None:
                nsep = toks[j][1]
                if "/" in nsep or nxt.startswith("/"):
                    tail += ("/" if "/" in nsep else "") + nxt
                elif not nxt[0].isdigit() and tail[-1].isdigit() and _ATTACH_SEP_RE.match(nsep):
                    tail += nxt   # "500" "mg"
                else:
                    break
                j += 1
            if (last_name_at is not None and _HAS_UNIT_RE.search(tail) and _ATTACH_SEP_RE.match(sep)
                    and out[last_name_at].tail is None):
                out[last_name_at] = Mention(out[last_name_at].token, tail)
            last_name_at = None
            i = j
            continue
        last_name_at = None
        if _is_noise(tok, dd):
            i += 1
            continue
        for piece in _split_joined(dd, tok):
            piece = _clean_token(piece)
            if not piece or _is_noise(piece, dd):
                last_name_at = None
                continue
            key = re.sub(r"\s+", "", piece).lower()
            if key not in seen:
                seen[key] = len(out)
                out.append(Mention(piece))
            last_name_at = seen[key]
        i += 1
    return out


def extract_mentions(text: str, dd: DrugDict) -> list[str]:
    """질문에서 사전 조회에 쓸 후보 문자열을 등장 순서대로 뽑는다(중복 제거). 조회 결과는 보지 않고 문자열만 정리한다.
    떨어진 함량 조각("500 mg", "/0.5밀리리터", "10/5mg")은 후보가 아니다(`extract_mention_details`가 이름에 붙인다)."""
    return [m.token for m in extract_mention_details(text, dd)]


# --------------------------------------------------------------------------- 엔티티

def _option(c: Candidate) -> ClarifyOption:
    return ClarifyOption(name=c.name, item_seq=c.item_seq, entp_name=c.entp_name, prescription=c.prescription, matched_by=c.matched_by, score=c.score)


def _entity(raw: str, r: LookupResult, strength: str | None = None) -> Entity:
    flags: list[str] = []
    options = [_option(c) for c in r.candidates[:MAX_CLARIFY_OPTIONS]]
    base: dict[str, Any] = dict(
        raw=raw, strength=strength, normalized=r.normalized_query, matched_by=r.matched_by, match_type=r.match_type, resolved=r.resolved,
        needs_clarification=r.needs_clarification, n_candidates=r.total_candidates,
    )
    if r.empty:
        return Entity(**{**base, "needs_clarification": False}, status=ST_NOT_FOUND, branch=BRANCH_NO_EVIDENCE)
    if any("성분명이기도" in n for n in r.notes):
        flags.append(FLAG_SAME_NAME_INGREDIENT)
    if r.match_type == MATCH_BM25:
        top = r.candidates[0].score
        if top <= NOT_FOUND_SCORE_MAX:  # 가상 약 의심: 근거 없음으로 분류하되 후보는 유지
            return Entity(**base, status=ST_NOT_FOUND, branch=BRANCH_NO_EVIDENCE, flags=[*flags, FLAG_SIMILAR_SHOWN], options=options)
        if top <= TYPO_SCORE_MAX:
            return Entity(**base, status=ST_TYPO, branch=BRANCH_TYPO, flags=flags, options=options)
        return Entity(**base, status=ST_AMBIGUOUS, branch=BRANCH_AMBIGUOUS, flags=flags, options=options)
    if r.resolved:
        c = r.candidates[0]
        if c.matched_by == MATCHED_BY_INGREDIENT:
            flags.append(FLAG_NO_PRODUCT_INFO)  # H17: 막지 않고 표시만
        if c.code_status == "none":
            flags.append(FLAG_CODE_NOT_LINKED)
        return Entity(**base, status=ST_RESOLVED, branch=BRANCH_NORMAL, code_status=c.code_status, flags=flags,
                      item_seq=c.item_seq if c.matched_by != MATCHED_BY_INGREDIENT else None)
    # 제품 후보 여럿·접두·중간 일치·성분 이름 여럿: 되묻기. 하나로 고르지 않는다.
    return Entity(**base, status=ST_AMBIGUOUS, branch=BRANCH_AMBIGUOUS, flags=flags, options=options)


def _clarify(ents: list[Entity]) -> Clarify | None:
    pending = [e for e in ents if e.status in (ST_AMBIGUOUS, ST_TYPO) or (e.status == ST_NOT_FOUND and e.options)]
    if not pending:
        return None
    t = pending[0]
    # 코드 템플릿. 후보 이름만 보여 주고 먹어도 되는지·안전한지는 말하지 않는다. 질문은 하나다.
    if t.status == ST_NOT_FOUND:  # 후보를 보여 주는 근거 없음(AG-05-02 A): "찾지 못했다"고 먼저 말하고 비슷한 이름만 묻는다(없다는 말이 안전하다는 뜻이 아니다)
        q = f"'{t.raw}'은(는) 목록에서 찾지 못했어요. 혹시 아래 중에 찾으시는 약이 있나요? 없으면 약 이름을 다시 알려 주세요."
    elif t.status == ST_TYPO:
        q = f"'{t.raw}'와(과) 비슷한 약이 있어요. 찾으시는 약이 아래 중에 있나요? 하나를 골라 주세요."
    else:
        q = f"'{t.raw}'에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요."
    return Clarify(question=q, target_raw=t.raw, options=t.options[:MAX_CLARIFY_OPTIONS], pending_raws=[e.raw for e in pending[1:]])


# --------------------------------------------------------------------------- 유형·프로필

_CONTRA_RE = re.compile(r"같이|함께|동시|병용|섞|겹|중복|상호작용|금기|먹어도|복용해도|먹여도|먹어|괜찮|피해야|써도|발라도")
_INFO_RE = re.compile(r"효능|효과|용법|용량|부작용|주의사항|무슨 약|어떤 약|뭐에 좋|성분|사용법|어떻게 먹|설명")
_DOC_RE = re.compile(r"등급|고시|규정|별표|지정|기준일|근거|출처|DUR|왜 금기|M등급")


def classify_intent(text: str, n_drugs: int, *, has_profile_signal: bool) -> list[str]:
    """요청 유형 규칙 라벨(여러 개 가능). 경로·도구는 정하지 않는다. 범위 외·응급은 Guardrail 몫이라 여기서 판정하지 않는다."""
    t = text or ""
    labels: list[str] = []
    contra = bool(_CONTRA_RE.search(t))
    if n_drugs >= 2 and (contra or not _INFO_RE.search(t)):
        labels.append(INTENT_CONTRA)
    elif n_drugs >= 1 and (contra or has_profile_signal):
        labels.append(INTENT_CONTRA)
    if n_drugs >= 1 and _INFO_RE.search(t):
        labels.append(INTENT_DRUG_INFO)
    if _DOC_RE.search(t):
        labels.append(INTENT_DOCUMENT)
    if n_drugs == 0 and not labels:
        labels.append(INTENT_OPEN)
    elif n_drugs == 0 and labels == [INTENT_CONTRA]:
        labels.append(INTENT_OPEN)  # 성분 없는 열린 질문("임신 중 피해야 할 진통제")
    elif n_drugs >= 1 and not labels:
        labels.append(INTENT_DRUG_INFO)
    return list(dict.fromkeys(labels))


def extract_profile(text: str, profile: ProfileState | dict[str, Any] | None = None) -> ProfileState:
    """연령·임신 여부. 질문 문장에 있으면 그 값이 프로필보다 우선한다. 결과는 반환만 하고 어디에도 쓰지 않는다."""
    base = ProfileState.model_validate(profile) if isinstance(profile, dict) else (profile or ProfileState())
    age: float | None = None
    m = _AGE_MONTH_RE.search(text or "")
    if m:
        age = round(int(m.group(1)) / 12, 2)
    else:
        m = _AGE_YEAR_RE.search(text or "")
        if m:
            age = float(int(m.group(1)))
    preg: bool | None = None
    if _PREG_NEG_RE.search(text or ""):
        preg = False
    elif _PREG_RE.search(text or ""):
        preg = True
    from_q = age is not None or preg is not None
    out_age = age if age is not None else base.age_years
    out_preg = preg if preg is not None else base.pregnant
    if from_q:
        src = "question"
    elif out_age is not None or out_preg is not None:
        src = "profile"
    else:
        src = "none"
    return ProfileState(age_years=out_age, pregnant=out_preg, source=src)


# --------------------------------------------------------------------------- 모델 입력 정리 블록(ROUTER_NOTE)

NOTE_ENTITY_KEYS = ("raw", "strength", "status", "item_seq", "matched_by", "code_status")


def note_entities(entities: list[Entity] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """ROUTER_NOTE의 `drug_candidates`(질문 속 약 목록). 키 순서·집합을 고정하고, 같은 정규화 이름은 한 번만 낸다(등장 순서 유지).
    판정이 아니라 입력 정리다. 상태 dict(`state_update()` 결과)와 `Entity` 둘 다 받는다."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in entities or []:
        d = e.model_dump() if isinstance(e, BaseModel) else dict(e)
        key = str(d.get("normalized") or d.get("raw") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({k: d.get(k) for k in NOTE_ENTITY_KEYS})
    return out


# --------------------------------------------------------------------------- 진입점

def route_input(text: str, dd: DrugDict, profile: ProfileState | dict[str, Any] | None = None, *,
                emergency: bool = False, guardrail_route: str | None = None) -> RouterResult:
    """질문 하나를 정리한다. `emergency`·`guardrail_route`는 AG-08이 쓴 값을 읽어 그대로 돌려줄 뿐 결과에 영향이 없다."""
    mentions = extract_mention_details(text, dd)
    truncated = len(mentions) > MAX_DRUGS
    mentions = mentions[:MAX_DRUGS]

    ents: list[Entity] = []
    seen_seq: set[str] = set()
    for m in mentions:
        used, r, strength = lookup_mention(dd, m)
        e = _entity(used, r, strength)
        if e.item_seq and e.status == ST_RESOLVED:  # 같은 제품을 두 번 말한 경우(예: 약어와 정식명)는 한 번만
            if e.item_seq in seen_seq:
                continue
            seen_seq.add(e.item_seq)
        ents.append(e)

    prof = extract_profile(text, profile)
    has_sig = prof.age_years is not None or prof.pregnant is not None
    clarify = _clarify(ents)
    if clarify is not None:
        if any(e.status == ST_AMBIGUOUS for e in ents):
            label = BRANCH_AMBIGUOUS
        elif any(e.status == ST_TYPO for e in ents):
            label = BRANCH_TYPO
        else:
            label = BRANCH_NO_EVIDENCE  # 후보를 보여 주는 NOT_FOUND만 있는 경우(AG-05-02 A)
    elif any(e.status == ST_NOT_FOUND for e in ents):
        label = BRANCH_NO_EVIDENCE
    else:
        label = BRANCH_NORMAL
    n_res = sum(1 for e in ents if e.status == ST_RESOLVED)
    return RouterResult(
        drug_mentions=[e.raw for e in ents], entities=ents, intent=classify_intent(text, len(ents), has_profile_signal=has_sig),
        profile=prof, branch_label=label, ambiguous=clarify is not None, clarify=clarify, truncated=truncated,
        n_pairs=n_res * (n_res - 1) // 2, emergency=emergency, guardrail_route=guardrail_route, dict_version=dd.version,
    )
