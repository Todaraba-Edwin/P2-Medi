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
`required_claims`(2026-11-12 제안)는 질문에 필요한 주장 유형 중 **코드 규칙으로 정할 수 있는 것**만 담는다(`required_claims()` 참고).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.fixed_phrases import CLARIFY_MANY_CANDIDATES, CLARIFY_ONE_CANDIDATE
from app.tools.drug_dict import (
    MATCH_BM25,
    MATCH_CONTAINS,
    MATCH_EXACT,
    MATCH_NORMALIZED,
    MATCH_PREFIX,
    MATCHED_BY_INGREDIENT,
    MATCHED_BY_PRODUCT,
    Candidate,
    DrugDict,
    LookupResult,
    normalize_name,
)
from app.tools.name_similarity import similar_names

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
ROUTER_WRITABLE_KEYS = frozenset({"profile", "drug_mentions", "intent", "entities", "branch_label", "ambiguous", "clarify", "truncated",
                                  "required_claims"})

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
FLAG_USER_CONFIRMED = "USER_CONFIRMED"  # 되묻기에서 사용자가 고른 품목기준코드로 확정함(AG-05-03 A)
FLAG_TYPO_CORRECTED = "TYPO_CORRECTED"  # 오탈자 의심 이름을 비슷한 사전 이름 하나로 보정해 확정함(AG-10, RFP-26-09 A). 응답에 보정 고지가 붙는다

# AG-10 오탈자 보정 기준(FR-07, RFP-26-09 A). BE-07 유사 후보(`name_similarity`, 자모 편집 거리 점수 0~1)가 **하나로 뚜렷할 때만** 보정한다.
#   - `TYPO_CORRECT_MIN_SCORE`: 1위 점수 하한. 0.90 = 자모 10칸에 1칸 이하만 다르다(자모 1칸 차이면 이름이 10자모(약 4음절) 이상, 2칸이면 20자모 이상).
#     짧은 이름은 한 칸 차이인 다른 약이 흔해 보정하지 않는다(되묻기 유지).
#   - `TYPO_CORRECT_MIN_GAP`: 1위와 2위의 점수 차 하한. 0.05 = 20자모 이름에서 자모 1칸. 2위가 같은 거리(동점)거나 바짝 붙어 있으면 어느 약인지 모른다.
#   - 숫자(함량)는 고치지 않는다: 후보는 질문에 적힌 숫자 열과 같은 이름만 본다(`same_numbers`). "…정40/5"를 "…정80/5"로 바꾸지 않는다.
#   - 보정한 이름을 사전에 **다시 한 번 조회**해 정확·정규화 일치로 제품(또는 성분)이 하나로 확정될 때만 쓴다. 같은 이름의 제품이 여럿이면 되묻기 그대로다.
# 근거(2026-11-18, AG-04 개발셋만, 시험셋 미열람. 수치는 시험 `backend/tests/test_ag10_typo_devset.py`가 고정): BM25 후보만 있던 엔티티 49개 중
# 오탈자 변형 14문항의 약 이름은 12개가 자모 1칸 차이(점수 0.90~0.97, 2위와 차 0.055~0.28)이고 12개 모두 짝 문항의 제품으로 보정됐다. 나머지 2개는
# 음절 순서 바뀜(0.82)·여러 글자 누락(0.74, 1위가 다른 제품)이라 보정하지 않는다. 가상 약(근거 없음) 엔티티의 최고 점수는 0.857(2위와 동점)이라
# 0.90 미만이고, 오탈자가 아닌 130문항에서 보정된 엔티티는 0개다. 경계(0.90·0.05)가 개발셋 양성의 최솟값과 맞닿아 있어 **소표본 과적합 위험**이 있다
# (n=14, 값을 올리면 보정이 줄 뿐 오보정은 늘지 않는다). 보정이 일어나지 않으면 지금까지와 똑같이 되묻는다.
TYPO_CORRECT_MIN_SCORE = 0.90
TYPO_CORRECT_MIN_GAP = 0.05

# AG-05-03 A(2026-11-17): 되묻기에서 고른 약(요청 `context.confirmed_drugs`의 `item_seq`)으로 엔티티를 확정할 때 다시 볼 사전 후보 수 상한.
# 되묻기 후보(상위 5개)보다 넓게 보되(같은 조회 문자열의 후보 집합 안에서만 찾는다), 접두·중간 일치가 수백 건인 이름에서 끝없이 넓히지 않는다.
CONFIRM_LOOKUP_MAX = 200
_ITEM_SEQ_RE = re.compile(r"^\d{9}$")  # 요청 모델(`ConfirmedDrug.item_seq`)과 같은 형식

INTENT_CONTRA = "contraindication"
INTENT_DRUG_INFO = "drug_info"
INTENT_DOCUMENT = "document"
INTENT_OPEN = "open"

_STRONG = {MATCH_EXACT, MATCH_NORMALIZED, MATCH_PREFIX, MATCH_CONTAINS}  # BM25가 아닌 이름 일치

# 주장 유형(`P2-doc/PJ2-DUR-RAG-근거설계.md` 4장 "주장 유형별 허용 근거"의 일곱 가지). 답변 문장의 `claim_type`(fact·conclusion·guidance,
# `answer_schema.py`)과는 다른 축이다. Router는 이 중 코드 규칙으로 정할 수 있는 것만 `required_claims`에 적는다(AG-05 §2 (개선) 조건의 코드 규칙 부분).
CLAIM_CONTRA_STATUS = "contra_status"  # 금기 여부(L0만)
CLAIM_GRADE_DEFINITION = "grade_definition"  # 등급 정의(L1). 질문이 정의를 묻는지는 프롬프트 분류 몫이라 코드 규칙으로 채우지 않는다
CLAIM_CONTRA_REASON = "contra_reason"  # 금기 사유(L2·L3). 판정된 쌍이 있어야 필요해지므로 도구 결과 뒤에 정한다(Router 시점에는 모른다)
CLAIM_PRODUCT_CAUTION = "product_caution"  # 제품 주의(L3)
CLAIM_TERM_PROCEDURE = "term_procedure"  # 용어·절차(L4). 프롬프트 분류 몫
CLAIM_LIMITATION = "limitation_notice"  # 한계·고지(코드 고정 문구, FR-06)
CLAIM_AS_OF = "as_of_date"  # 기준일(메타데이터)
CLAIM_TYPES = (CLAIM_CONTRA_STATUS, CLAIM_GRADE_DEFINITION, CLAIM_CONTRA_REASON, CLAIM_PRODUCT_CAUTION, CLAIM_TERM_PROCEDURE,
               CLAIM_LIMITATION, CLAIM_AS_OF)  # 설계 문서 4장 표의 순서
CLAIM_LABELS_KO = {
    CLAIM_CONTRA_STATUS: "금기 여부", CLAIM_GRADE_DEFINITION: "등급 정의", CLAIM_CONTRA_REASON: "금기 사유", CLAIM_PRODUCT_CAUTION: "제품 주의",
    CLAIM_TERM_PROCEDURE: "용어·절차", CLAIM_LIMITATION: "한계·고지", CLAIM_AS_OF: "기준일",
}
CLAIMS_BY_CODE_RULE = frozenset({CLAIM_CONTRA_STATUS, CLAIM_PRODUCT_CAUTION, CLAIM_LIMITATION, CLAIM_AS_OF})  # Router 코드 규칙이 채우는 유형

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
    corrected_from: str | None = None  # 오탈자 보정(AG-10)으로 확정했을 때만: 질문에 적힌 원래 이름 조각. 이때 `raw`는 보정한 사전 이름이다
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
    required_claims: list[str] = Field(default_factory=list)  # 제안: 필요한 주장 유형(코드 규칙 부분만, `CLAIM_TYPES` 순서)
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
            "required_claims": list(self.required_claims),
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
# 숫자 사이 "/"(5/850밀리그램)는 약 이름의 일부라 나누지 않는다. 질량 단위 뒤 시간당 표기("12μg/h", 2026-11-18)도 나누지 않는다
_SPLIT_RE = re.compile(r"[,，+·&、;]|(?<=\d)/(?!\d)|(?<=[gG])/(?!\d)(?!hr?(?![A-Za-z]))|(?<![\dgG])/|\s+")
_PUNCT_RE = re.compile(r"^[\s\"'`(\[{<]+|[\s?!.…~\"'`)\]}>]+$")
_NUM_UNIT_RE = re.compile(
    r"^\d+(\.\d+)?\s*(살|세|개월|주|주차|일|시간|번|회|kg|키로|밀리그램|밀리그람|밀리리터|mg|mcg|μg|ug|ml|g|l|알|정|포|캡슐|병|방울|"
    r"등급|개|가지|명)$", re.IGNORECASE  # 숫자+분류사("3등급", "2개")는 약 이름이 아니다(AG-05 후속 2026-11-12)
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
    if dd is None:
        return False
    if _VERB_END_RE.search(tok) or _SYMPTOM_END_RE.search(tok):
        return not any(_strong(dd, v) for v in vs)
    rule2 = _noise_rule2(tok, vs, dd)
    if rule2 == NOISE_FUNCTION_WORD:  # 닫힌 품사는 접두 일치로 보호하지 않는다("이제" → "이제티브정"). 아래 규칙보다 먼저 본다
        return True
    if _noise_rule(tok, vs) is not None:  # AG-05 후속: 조사 뗀 변형까지 보는 일반 규칙. 사전에 이름으로 맞으면(접두·중간 포함) 버리지 않는다
        return not any(_name_match(dd, v) for v in vs)
    return rule2 is not None


# --------------------------------------------------------------------------- 잡음 규칙 2차(AG-05 후속, 2026-11-18)
# 남은 되묻기 Fail(응급 dev-051·054·055, 오정보 dev-107, `l3-pathfail-rca.md`)은 약 이름이 아니라 **잡음 낱말**이 모호·오탈자 의심 엔티티가 되어
# 되묻기로 끝난 것이다(약은 모두 RESOLVED). 개발셋 낱말을 하나씩 넣지 않고 아래 두 가지 꼴만 본다. 둘 다 사전 정확·정규화 일치면 버리지 않는다.
# 넣지 않은 안(2026-11-18 시험 뒤 되돌림): ① 한 음절 + 조사("배가")의 보호를 정확 일치로 좁히기 — "타이"(타이레놀 줄임)·"마로"(접두 일치)
# 같은 줄여 부른 이름을 버리게 된다. ② "-아/어하다 + 하고"("아파하고") — 접두 일치로 보호하면 이득이 0이고, 보호를 좁히면 "나래하고" 같은 줄임 이름을 버린다.
NOISE_FUNCTION_WORD = "function_word"  # 부사·관형사·대명사·수사(닫힌 목록. "아무", "이제", "하나"가 제품명 접두에 우연히 걸린다)
NOISE_SHORT_UNKNOWN = "short_unknown"  # 조사를 뗀 한글 2음절 이하인데 사전에 이름으로 맞지 않음(BM25 유사·없음: "시간", "수유", "아닌", "드시")

# 닫힌 품사라 목록이 유한하다. 개발셋에 나온 것만이 아니라 흔한 것을 함께 적었다(2026-11-18 사전 확인: 이 중 사전 정확·정규화 일치 0건).
_FUNCTION_WORDS = frozenset("""
아무 아무것 이제 하나 둘 셋 모든 모두 전부 일부 가장 제일 다음 이전 요즘 요새 자꾸 매우 아주 무척 조금 좀 많이 별로 전혀 항상 늘 거의
다른 여러 몇 각 혹은 만약 만일 또한 역시 특히 그냥 벌써 아마 꼭 반드시 훨씬 점점 서로 따로 직접 대충 원래 보통 평소 이번 저번 지난번
""".split())
_SHORT_MAX = 2  # 2음절 이하. 실제 2음절 약 이름은 사전에 이름으로 맞아(정확·접두) 이 규칙에 걸리지 않는다


def _is_hangul(s: str) -> bool:
    return bool(s) and all("가" <= ch <= "힣" for ch in s)


def _noise_rule2(tok: str, vs: list[str], dd: DrugDict) -> str | None:
    """2차 잡음 규칙 이름(`NOISE_FUNCTION_WORD`·`NOISE_SHORT_UNKNOWN`). 없으면 None. 사전 정확·정규화 일치면 None."""
    if any(_strong(dd, v) for v in vs):
        return None
    if any(v in _FUNCTION_WORDS for v in vs):
        return NOISE_FUNCTION_WORD
    core = vs[-1]
    if _is_hangul(core) and len(core) <= _SHORT_MAX and not any(_name_match(dd, v) for v in vs):
        return NOISE_SHORT_UNKNOWN
    return None


# --------------------------------------------------------------------------- 잡음 규칙 확장(AG-05 후속, 2026-11-12)
# 동사 활용형·일반 명사가 약 이름 후보로 뽑혀 NOT_FOUND·오탈자 의심 엔티티가 되는 문제를 줄인다. **낱말을 더하지 않고** 어미·조사·접미 꼴만 본다.
# 보호 조건은 위 규칙(정확·정규화 일치)보다 넓다: 조사 뗀 변형이 사전에 이름으로 맞으면(정확·정규화·접두·중간) 약 후보로 남긴다. 조사를 뗀 약 이름은
# 줄여 부른 이름(접두 일치, 되묻기 대상)일 수 있어서다. BM25 유사 일치만 있는 토큰은 보호하지 않는다(용언이 우연히 비슷한 이름에 걸린 경우가 대부분).
# 개발셋 전후 측정은 `backend/scripts/calibrate_router.py`(개발셋만). 규칙으로 못 거르는 일반 명사(증상 없는 보통 명사)는 남는다(LLM 추출 몫).
NOISE_ONE_SYLLABLE = "one_syllable_particle"  # 한 음절 + 조사("열이", "눈에", "되는"): 한 음절짜리 약 이름은 없다
NOISE_RECIPIENT = "recipient_particle"  # 받는 사람·분배 조사("아이한테", "의사님께", "개씩"): 사람·수량을 가리킨다
NOISE_VERB_END = "verb_ending"  # 용언 어미("요약해", "가능한", "하던데") 또는 용언 어미 + 인용·보조 조사("된다고", "맞자고")
NOISE_NOUN_SUFFIX = "noun_suffix"  # 증상·질환 접미 + 조사("두통이"), 약효군 접미("혈압약", "항생제". 제형 이름은 제외)
NOISE_STOP_STEM = "stop_stem"  # 불용어 둘 이상이 같이 쓰는 어간에서 조사·어미가 떨어진 꼴("괜찮나" → "괜찮")

_RECIPIENT_RE = re.compile(r"(한테|에게|께|께서|씩)$")
# 하다 활용(해·하는·한·할·하기·한데), 연결·종결 어미, 부사 접미(히). 조사와 같은 꼴(고·도·나·며)은 넣지 않는다(오탈자 약 + 조사를 버리지 않으려고).
# 이 꼴로 끝나는 제품명은 사전(약 4.7만 건)에 0건이다(2026-11-12 확인).
_VERB_END2_RE = re.compile(r"(다가|던데|면서요|면서|거든요|가요|도록|거나|지만|니까|해|하는|한|할|하기|한데|히)$")
_JUNG_WA, _JUNG_WO = 9, 14  # 한글 중성 번호: ㅘ, ㅝ
_QUOTE_PARTICLES = frozenset({"고", "는", "며", "도", "만"})  # 용언 어미 뒤에 붙는 인용·보조 조사("된다고", "안전하다며"). 격조사(을·를·이·가…)는 명사 뒤라 제외
_CLASS_END_RE = re.compile(r"(약|제)$")  # 약효군을 가리키는 보통 명사("혈압약", "수면제")
# 제형을 가리키는 꼴은 제품명 끝에 실제로 쓰여서(사전 약 100건) 약효군 규칙에서 뺀다(지금처럼 약 후보로 남긴다)
_FORM_END_RE = re.compile(r"(좌약|고약|안약|관장약|시약|첩부제|흡입제|주사제|좌제|분무제|이식제|산제|점안제|트로키제|경고제|관류제|제제)$")


def _stop_stems() -> frozenset[str]:
    """불용어 둘 이상이 공통으로 시작하는 2자 이상 접두(그 자체가 불용어인 것은 제외). 불용 용언의 어간에 해당한다."""
    count: dict[str, int] = {}
    for w in _STOP_WORDS:
        for i in range(2, len(w)):
            count[w[:i]] = count.get(w[:i], 0) + 1
    return frozenset(p for p, n in count.items() if n >= 2 and p not in _STOP_WORDS)


_STOP_STEMS = _stop_stems()


def _ends_contracted_yo(tok: str) -> bool:
    """받침 없는 ㅘ·ㅝ 음절 + "요"로 끝나는가("와요", "줘요", "메스꺼워요"). 어간 모음과 어미 아/어가 줄어든 해요체 꼴이다."""
    if len(tok) < 2 or tok[-1] != "요" or not "가" <= tok[-2] <= "힣":
        return False
    code = ord(tok[-2]) - ord("가")
    return code % 28 == 0 and (code // 28) % 21 in (_JUNG_WA, _JUNG_WO)


def _noise_rule(tok: str, vs: list[str]) -> str | None:
    """토큰(원형 `tok`, 조사 뗀 변형 `vs`)이 걸리는 잡음 규칙 이름. 없으면 None. 사전은 보지 않는다(보호 조건은 `_is_noise`)."""
    if any(tok.endswith(p) and len(tok) - len(p) == 1 for p in _PARTICLES):
        return NOISE_ONE_SYLLABLE
    if _RECIPIENT_RE.search(tok):
        return NOISE_RECIPIENT
    if any(_VERB_END2_RE.search(v) for v in vs) or _ends_contracted_yo(tok):
        return NOISE_VERB_END
    for prev, cur in zip(vs, vs[1:], strict=False):  # prev에서 조사 하나를 떼어 cur이 됐다
        if prev[len(cur):] in _QUOTE_PARTICLES and _VERB_END_RE.search(cur):
            return NOISE_VERB_END
    if any(_SYMPTOM_END_RE.search(v) for v in vs[1:]):
        return NOISE_NOUN_SUFFIX
    if any(_CLASS_END_RE.search(v) and not _FORM_END_RE.search(v) for v in vs):
        return NOISE_NOUN_SUFFIX
    if any(v in _STOP_STEMS for v in vs[1:]):
        return NOISE_STOP_STEM
    return None


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


# 제형 이름의 외래어 표기 변형. 사전에 두 표기가 모두 있다(예: "…캅셀300밀리그람"과 "…캡슐300밀리그램"). 오탈자가 아니라 옛 표기라 보정 고지 없이 쓴다.
_FORM_SPELLINGS = (("캅셀", "캡슐"), ("캡슐", "캅셀"), ("패취", "패치"), ("패치", "패취"))


def lookup_mention(dd: DrugDict, m: Mention) -> tuple[str, LookupResult, str | None]:
    """후보 하나의 사전 조회 문자열을 고른다. (조회에 쓴 문자열, 결과, 함량 표기)를 돌려준다.

    시도 순서(더 구체적인 것 먼저): ① 토큰 그대로(붙은 함량 포함, 지금까지의 동작) ② 토큰+떨어진 함량 ③ 함량을 뗀 이름.
    일치 등급(정확·정규화 3 > 접두·중간 2 > BM25 1 > 없음 0)이 가장 높은 것을 쓰고, 같으면 앞의 것을 쓴다.
    ①이 정확·정규화 일치면 지금과 같은 결과다. ③을 썼고 후보가 여럿이면 함량이 든 후보를 앞으로 옮긴다(되묻기 유지, 자동 확정 없음).
    ④ 그래도 정확·정규화 일치가 아니면 제형 표기 변형(`_FORM_SPELLINGS`)을 바꿔 보고, 정확·정규화 일치일 때만 쓴다."""
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
    if _rank(best) < 3:  # ④ 제형 외래어 표기 변형("캅셀"↔"캡슐"): 정확·정규화 일치로 올라갈 때만 쓴다(2026-11-18)
        for a, b in _FORM_SPELLINGS:
            if a in best_used:
                u4, r4 = _lookup_best(dd, best_used.replace(a, b))
                if _rank(r4) == 3:
                    return u4, r4, strength
    return best_used, best, strength


def _strong(dd: DrugDict, tok: str) -> bool:
    r = dd.lookup_name(tok, top_k=1)
    return not r.empty and r.match_type in (MATCH_EXACT, MATCH_NORMALIZED)


def _name_match(dd: DrugDict, tok: str) -> bool:
    """사전에 이름으로 맞는가(정확·정규화·접두·중간). BM25 유사 일치는 이름 일치가 아니다."""
    r = dd.lookup_name(tok, top_k=1)
    return not r.empty and r.match_type in _STRONG


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


# 서술격 조사 "이다"의 활용("…정10밀리그램인지", "…정인데"). `_STOP_SUFFIX_RE`가 토큰째 버리던 꼴이라, 앞말이 약 이름일 때는 떼고 앞말을 후보로 쓴다.
_COPULA_RE = re.compile(r"(인지|인가요|인가|인데|입니다|이에요|예요)$")


def _strip_copula(tok: str, dd: DrugDict) -> str:
    """토큰이 "이다" 활용으로 끝나고 앞말이 함량 표기로 끝나거나 사전에 이름으로 맞으면(정확·정규화·접두·중간) 앞말을 돌려준다. 아니면 그대로."""
    m = _COPULA_RE.search(tok)
    if not m:
        return tok
    stem = tok[: m.start()]
    if len(stem) >= 2 and (split_strength(stem)[1] is not None or _name_match(dd, stem)):
        return stem
    return tok


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
        tok = _strip_copula(tok, dd)
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


# 되묻기 후보가 1개일 때의 질문 `CLARIFY_ONE_CANDIDATE`: 원문 승인(AG-05-05 A, 2026-11-18)으로 원본을 `fixed_phrases`로 옮기고(위 import)
# 승인 스위치를 지웠다.
# 후보가 여럿일 때의 질문 `CLARIFY_MANY_CANDIDATES`: 물음표 1개 문장(평가 `ONE_QUESTION` = 요약의 "?"가 정확히 1개, `eval_metrics.py:255`).
# 원문 승인(AG-05-10 A, 2026-11-18)·켜기(AG-13-07 A, 2026-11-18 밤, AG-11 기준선 뒤)로 원본을 `fixed_phrases`로 옮기고 승인 스위치를 지웠다.


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
    elif t.n_candidates <= 1 and len(t.options) == 1:  # 후보 1개(접두·중간 일치, AG-05-01 A로 되묻기 유지)에는 "여러 개"라고 하지 않는다
        q = CLARIFY_ONE_CANDIDATE.format(drug=t.raw)
    else:
        q = CLARIFY_MANY_CANDIDATES.format(drug=t.raw)
    return Clarify(question=q, target_raw=t.raw, options=t.options[:MAX_CLARIFY_OPTIONS], pending_raws=[e.raw for e in pending[1:]])


# --------------------------------------------------------------------------- 되묻기에서 고른 약(AG-05-03 A)

def confirmed_seqs(values: Any) -> list[str]:
    """확정 약 입력(품목기준코드 문자열 목록)에서 형식이 맞는 값만 순서대로(중복 제거) 남긴다. 형식이 틀린 값은 조용히 버린다."""
    out: list[str] = []
    for v in values or ():
        if isinstance(v, str) and _ITEM_SEQ_RE.match(v) and v not in out:
            out.append(v)
    return out


def apply_confirmed(dd: DrugDict, e: Entity, seqs: list[str]) -> Entity:
    """사용자가 되묻기에서 고른 품목기준코드(`seqs`, 앞이 먼저 고른 것)로 확정되지 않은 엔티티를 확정한다(AG-05-03 A).

    매칭 규칙: 엔티티가 조회에 쓴 문자열(`e.raw`)을 사전에 다시 조회해 얻은 **제품 후보 집합**(상한 `CONFIRM_LOOKUP_MAX`)에 고른 코드가 있을 때만
    확정한다. 고른 약의 이름은 보지 않는다(이름은 화면 표시용이라 바뀔 수 있고, 코드가 사전 키다). 여러 개가 맞으면 **가장 나중에 고른 것**을 쓴다.
    - 이미 확정(RESOLVED)인 엔티티, 후보가 없는 NOT_FOUND, 성분명 후보만 있는 경우는 그대로 둔다.
    - 사전에 없는 코드, 이 엔티티의 후보가 아닌 코드는 무시한다(지금 동작: 되묻기). 질문에 없는 약을 새로 더하지 않는다.
    """
    if not seqs or e.status == ST_RESOLVED or e.n_candidates == 0:
        return e
    top_k = min(max(MAX_CLARIFY_OPTIONS, e.n_candidates), CONFIRM_LOOKUP_MAX)
    by_seq = {c.item_seq: c for c in dd.lookup_name(e.raw, top_k=top_k).candidates if c.item_seq and c.matched_by == MATCHED_BY_PRODUCT}
    c = next((by_seq[s] for s in reversed(seqs) if s in by_seq), None)
    if c is None:
        return e
    flags = [f for f in e.flags if f == FLAG_SAME_NAME_INGREDIENT]
    flags.append(FLAG_USER_CONFIRMED)
    if c.code_status == "none":
        flags.append(FLAG_CODE_NOT_LINKED)
    return e.model_copy(update=dict(status=ST_RESOLVED, branch=BRANCH_NORMAL, matched_by=MATCHED_BY_PRODUCT, resolved=True,
                                    needs_clarification=False, code_status=c.code_status, item_seq=c.item_seq, flags=flags, options=[]))


# --------------------------------------------------------------------------- 오탈자 보정(AG-10, FR-07, RFP-26-09 A)

def correct_typo(dd: DrugDict, e: Entity) -> Entity:
    """이름 일치 없이 BM25 후보만 있던 엔티티(오탈자 의심·점수 높은 모호)를, 비슷한 사전 이름이 **하나로 뚜렷하면** 그 이름으로 확정한다.

    기준은 위 `TYPO_CORRECT_MIN_SCORE`·`TYPO_CORRECT_MIN_GAP` 주석 그대로다. 기준에 못 미치거나 다시 조회한 결과가 하나로 정해지지 않으면
    엔티티를 그대로 돌려준다(되묻기 유지). 접두·중간 일치(줄여 쓴 이름)는 대상이 아니다(AG-05-01 A: 후보가 하나여도 되묻기).
    확정한 엔티티는 `raw`가 보정한 사전 이름, `corrected_from`이 원래 조각이고 `TYPO_CORRECTED` 꼬리표가 붙는다. 판정은 하지 않는다."""
    if e.status == ST_RESOLVED or e.match_type != MATCH_BM25:
        return e
    # 2위를 보려고 하한을 (기준 - 간격)으로 낮춰 받는다: 그 아래의 2위는 있어도 간격 기준을 이미 넘는다
    cands = similar_names(dd, e.raw, top_k=2, min_score=TYPO_CORRECT_MIN_SCORE - TYPO_CORRECT_MIN_GAP, same_numbers=True)
    if not cands or cands[0].score < TYPO_CORRECT_MIN_SCORE:
        return e
    if len(cands) > 1 and cands[0].score - cands[1].score < TYPO_CORRECT_MIN_GAP:
        return e
    r = dd.lookup_name(cands[0].key, top_k=MAX_CLARIFY_OPTIONS)  # 보정 이름으로 1회 재검색(사전 조회 계약 그대로: 여럿이면 확정하지 않는다)
    if not r.resolved or r.match_type not in (MATCH_EXACT, MATCH_NORMALIZED):
        return e
    fixed = _entity(r.candidates[0].name, r, e.strength)
    if fixed.status != ST_RESOLVED:
        return e
    return fixed.model_copy(update={"branch": BRANCH_TYPO, "corrected_from": e.raw, "flags": [*fixed.flags, FLAG_TYPO_CORRECTED]})


def corrections_of(entities: list[Entity] | list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """보정으로 확정한 엔티티의 (원래 조각, 보정한 이름) 목록. 응답의 보정 고지(`finalize(name_corrections=...)`)가 쓴다."""
    out: list[dict[str, str]] = []
    for e in entities or []:
        d = e.model_dump() if isinstance(e, BaseModel) else dict(e)
        if d.get("corrected_from") and d.get("status") == ST_RESOLVED and d.get("raw"):
            out.append({"input": str(d["corrected_from"]), "name": str(d["raw"])})
    return out


# --------------------------------------------------------------------------- 유형·프로필

# "도 되/돼/될"(허락을 묻는 꼴: "줘도 되나요")과 "먹었"(이미 먹은 뒤 묻는 꼴)은 2026-11-12에 더했다. 잡음 엔티티가 줄면서 약 수(2개 이상이면 금기)에
# 기대어 붙던 라벨이 빠지는 문항이 있어서다(개발셋 전후 비교, 유형 라벨이 바뀐 문항은 보고에 적음).
# "먹으면 / 먹을·먹일·복용할 수 있나·있을까·있는지"(먹어도 되는지를 묻는 다른 꼴)는 2026-11-18에 더했다. 잡음 낱말 2차 규칙으로 약 수가 줄어 라벨이
# 빠지는 문항이 있어서다. "몇 번까지 먹을 수 있어요"(용법)는 묻는 꼴(나·을까·는지)이 아니라 걸리지 않는다.
_CONTRA_RE = re.compile(r"같이|함께|동시|병용|섞|겹|중복|상호작용|금기|먹어도|복용해도|먹여도|먹어|먹었|괜찮|피해야|써도|발라도|도\s*(?:되|돼|될)"
                        r"|먹으면|(?:먹을|먹일|복용할)\s*수\s*있(?:나|을까|는지)")
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


_AS_OF_RE = re.compile(r"기준일|언제\s*기준|며칠\s*기준")


def required_claims(intent: list[str], text: str = "") -> list[str]:
    """질문에 필요한 주장 유형 중 코드 규칙으로 정할 수 있는 것(`CLAIMS_BY_CODE_RULE`). 순서는 `CLAIM_TYPES`(설계 문서 4장 표)다.

    규칙:
      - 한계·고지: 항상. 고정 문구는 유형과 상관없이 코드가 모든 답변에 붙인다(FR-06).
      - 금기 판정 질문(`contraindication`): 금기 여부 + 기준일(판정에 쓴 파일의 기준일을 함께 보여야 한다).
      - 약품 정보 질문(`drug_info`): 제품 주의.
      - 기준일을 직접 묻는 문장: 기준일.
    여기서 채우지 않는 것: 금기 사유(판정된 쌍이 있어야 필요하므로 도구 결과 뒤), 등급 정의·용어·절차(질문이 그것을 묻는지는 프롬프트 분류).
    판정이나 경로 선택이 아니다. 누락 검사(AG-07)·분해 검색(AG-03)이 읽을 목록을 적어 둘 뿐이다."""
    need = {CLAIM_LIMITATION}
    if INTENT_CONTRA in intent:
        need |= {CLAIM_CONTRA_STATUS, CLAIM_AS_OF}
    if INTENT_DRUG_INFO in intent:
        need.add(CLAIM_PRODUCT_CAUTION)
    if _AS_OF_RE.search(text or ""):
        need.add(CLAIM_AS_OF)
    return [c for c in CLAIM_TYPES if c in need]


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
                emergency: bool = False, guardrail_route: str | None = None, confirmed_item_seqs: Any = None,
                typo_correct: bool = False) -> RouterResult:
    """질문 하나를 정리한다. `emergency`·`guardrail_route`는 AG-08이 쓴 값을 읽어 그대로 돌려줄 뿐 결과에 영향이 없다.

    `typo_correct=True`이면 오탈자 의심 엔티티를 `correct_typo`로 보정해 본다(AG-10). 기본값 False는 지금까지와 같은 결과(되묻기)다.
    켜는 곳은 `GraphDeps.typo_correct`다(서비스 기본은 `wiring.SERVICE_TYPO_CORRECT_DEFAULT`, BE-06-35 A).

    `confirmed_item_seqs`는 같은 대화의 되묻기에서 사용자가 고른 약의 품목기준코드다(AG-05-03 A, `apply_confirmed`). 비어 있으면 지금과 같다
    (평가 경로는 늘 비어 있다). 값은 상태·이벤트·로그에 그대로 옮기지 않는다(확정된 엔티티의 `item_seq`는 일반 확정과 같은 자리에 들어간다)."""
    seqs = confirmed_seqs(confirmed_item_seqs)
    mentions = extract_mention_details(text, dd)
    truncated = len(mentions) > MAX_DRUGS
    mentions = mentions[:MAX_DRUGS]

    ents: list[Entity] = []
    seen_seq: set[str] = set()
    for m in mentions:
        used, r, strength = lookup_mention(dd, m)
        e = apply_confirmed(dd, _entity(used, r, strength), seqs)
        if typo_correct:
            e = correct_typo(dd, e)
        if e.item_seq and e.status == ST_RESOLVED:  # 같은 제품을 두 번 말한 경우(예: 약어와 정식명)는 한 번만
            if e.item_seq in seen_seq:
                continue
            seen_seq.add(e.item_seq)
        ents.append(e)

    prof = extract_profile(text, profile)
    return assemble(text, ents, prof, truncated=truncated, emergency=emergency, guardrail_route=guardrail_route, dict_version=dd.version)


def branch_label_of(ents: list[Entity], clarify: Clarify | None) -> str:
    """엔티티 상태로 문항 분기 라벨을 정한다(라벨 우선순위 모호 > 오탈자 > 근거 없음)."""
    if clarify is not None:
        if any(e.status == ST_AMBIGUOUS for e in ents):
            return BRANCH_AMBIGUOUS
        if any(e.status == ST_TYPO for e in ents):
            return BRANCH_TYPO
        return BRANCH_NO_EVIDENCE  # 후보를 보여 주는 NOT_FOUND만 있는 경우(AG-05-02 A)
    if any(e.status == ST_NOT_FOUND for e in ents):
        return BRANCH_NO_EVIDENCE
    if any(e.corrected_from for e in ents):
        return BRANCH_TYPO  # 오탈자를 보정해 진행한다(되묻기 아님, `ambiguous=False`)
    return BRANCH_NORMAL


def assemble(text: str, ents: list[Entity], prof: ProfileState, *, truncated: bool = False, emergency: bool = False,
             guardrail_route: str | None = None, dict_version: str = "") -> RouterResult:
    """정리된 엔티티·프로필에서 되묻기·분기 라벨·유형 라벨·주장 유형을 계산해 `RouterResult`를 만든다(`route_input`과 LLM 분류 병합이 같이 쓴다)."""
    has_sig = prof.age_years is not None or prof.pregnant is not None
    clarify = _clarify(ents)
    n_res = sum(1 for e in ents if e.status == ST_RESOLVED)
    intent = classify_intent(text, len(ents), has_profile_signal=has_sig)
    return RouterResult(
        drug_mentions=[e.raw for e in ents], entities=ents, intent=intent, required_claims=required_claims(intent, text),
        profile=prof, branch_label=branch_label_of(ents, clarify), ambiguous=clarify is not None, clarify=clarify, truncated=truncated,
        n_pairs=n_res * (n_res - 1) // 2, emergency=emergency, guardrail_route=guardrail_route, dict_version=dict_version,
    )
