"""AG-07 Validator 기준선: LLM 답변 문장의 출구 코드 검사(순수 함수, LLM·외부 호출 없음).

코드 검사만 한다. `(개선)` 중 허용 근거 계층(⑭·⑮)·주장 유형 누락(⑯)은 `validate(layer_check=True)`일 때만 보고(기본 꺼짐, AG-13-08 A),
상태 불일치 문구·제품 단정은 범위 밖이다. `(프롬프트 판정)`(의미 일치)은
`validator_judge`(기본 꺼짐, 규칙 다음 단계)가 맡는다. 검사별 처리(문장 삭제·되감기)는 `CHECK_ACTIONS` 표에 있다.

**문장 필터(`sentence_filter`, H1)와의 역할 분담** — 필터는 근거 ID 유무·모르는 ID·성분코드 노출과 요약의 복용량 숫자·진단 단정·
처방/복용 지시를 *무조건* 거른다. Validator는 필터를 통과한 문장(`FilterResult.kept`)을 입력으로 받아 필터가 보지 않는 것만 본다:
안전 단정, 복용 변경·의료진 우회(허가사항 원문 인용 예외 포함), 등급 값·M 등급 규칙(H22), 등급 예외 단서 오용(H24),
파일/API 확정 문장, 미확보 항목 권고, 출처 종류 누락(H29),
claim_type, 근거에 없는 연령·번호·날짜·등급. 용량 숫자·진단 단정은 여기서 다시 세지 않는다(이중 처리 금지). 단 필터 없이 직접
불렀을 때 복용 지시가 새지 않도록 복용 지시·변경 표현은 필터의 상수 `_DECISION_PATTERNS`를 재사용한다(`_DECISION_PATTERNS`만 보고 DOSE_NUMBER·DIAGNOSIS는 보지 않는다).

`finalize`가 붙이는 고정 문구 상수(`fixed_phrases`)는 검사 전에 문장에서 지운다(H2 오탐 방지).
`harness_event` dict는 내용 없는 집계이며 문장 원문을 담지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.agent import fixed_phrases as fp
from app.agent.answer_schema import EVIDENCE_REQUIRED, Citation
from app.agent.patterns import (  # noqa: PLC2701 — 같은 패키지의 도구 문자열 수집기 재사용
    _tool_strings,
    tool_grades,
    unsupported_identifiers,
)
from app.agent.quote_check import ELLIPSIS, build_text_index, resolve_citation, verify_quote_text
from app.agent.renderer import RenderResult
from app.agent.sentence_filter import _DECISION_PATTERNS  # noqa: PLC2701 — 복용 지시·변경 표현은 필터 상수를 재사용(중복 정의 금지)

PASS, FIXED, FAIL = "PASS", "FIXED", "FAIL"

# 검사 이름(이유 키)
SAFE_ASSERTION = "SAFE_ASSERTION"                  # ① 안전 단정
DOSE_CHANGE_OR_BYPASS = "DOSE_CHANGE_OR_BYPASS"    # ② 복용 변경·중단 지시, 의료진 우회, 복용 지시
GRADE_VALUE_INVALID = "GRADE_VALUE_INVALID"        # ③ 1·2·M 밖의 등급 값
M_NO_DETAIL = "M_NO_DETAIL"                        # ④ M 등급인데 상세정보 원문이 비었다
M_CONVERTED = "M_CONVERTED"                        # ④ M을 1·2등급으로 환산
FILE_API_CLAIM = "FILE_API_CLAIM"                  # ⑤ 파일/API 단독 확정·한쪽만 인용
MISSING_ADVICE_ABSENT = "MISSING_ADVICE_ABSENT"    # ⑥ 미확보 항목에 약사 확인 권고가 없다(되감기)
MISSING_IMPLIES_NONE = "MISSING_IMPLIES_NONE"      # ⑥ 미확보 항목을 "없음·안전"으로 암시
BAD_CLAIM_TYPE = "BAD_CLAIM_TYPE"                  # ⑦ claim_type 없음·모르는 값
NUMBER_NOT_IN_EVIDENCE = "NUMBER_NOT_IN_EVIDENCE"  # ⑧ 근거에 없는 연령·등급·번호·날짜
QUOTE_MISMATCH = "QUOTE_MISMATCH"                  # ⑨ H28 인용부호 안 글자가 연결된 원문(청크·라벨)과 다르다
GRADE_EXCEPTION_MISUSE = "GRADE_EXCEPTION_MISUSE"  # ⑩ H24 2등급 예외 단서·"사유 기재 불필요"를 복용 허용 근거로, 등급을 위험 서열로 쓴 문장
UNCONFIRMED_AS_FACT = "UNCONFIRMED_AS_FACT"        # ⑪ AG-09: 확인하지 못한 항목만 인용한 사실 문장(근거 없는 내용을 사실로 말함)
REFERENCE_AS_VERDICT = "REFERENCE_AS_VERDICT"      # ⑫ AG-09: 참고 전용·코드 미연결·미식별 항목을 인용해 금기 여부를 확정한 문장
SOURCE_KIND_MISSING = "SOURCE_KIND_MISSING"        # ⑬ H29 출처 종류(`source_kind`)가 없거나 모르는 값인 판정 항목(FOUND·NOT_LISTED)을 인용한 문장
# ⑭~⑯ (개선) AG-07 §2 `:36` 허용 근거 계층·`:41` 주장 유형 누락(AG-13-08 A, 2026-11-18 밤). `validate(layer_check=True)`일 때만 본다(기본 꺼짐,
# 개선 장치는 C3에만 하나씩, RFP-33-03·AG-07-06 A와 같은 원칙). 근거: 개발셋 C2 judge 1회 실패 표(`AG07_LAYER_MISSING` 28행) 관찰.
CLAIM_LAYER_NOT_ALLOWED = "CLAIM_LAYER_NOT_ALLOWED"  # ⑭ 금기 여부(목록에 있음·없음)를 말하면서 판정 항목(L0)을 하나도 인용하지 않았다
INGREDIENT_NOT_IN_EVIDENCE = "INGREDIENT_NOT_IN_EVIDENCE"  # ⑮ "성분은 X" 꼴의 성분 구성 주장에서 X가 인용 근거 원문 어디에도 없다
CLAIM_OMITTED = "CLAIM_OMITTED"                    # ⑯ 필요한 주장 유형 "금기 여부"인데 L0 FOUND 항목을 인용해 금기를 말한 문장이 없다(되감기)

# 검사 이름 → 하네스 규칙 번호(RFP-29 §6). 여기 없는 검사는 VALIDATOR 이벤트의 기본 규칙(H2)으로만 집계한다.
# H22(RFP-29-03 A): 기존 등급값·M 원문 필수·M 환산 차단을 한 번호로 묶는다(동작은 그대로, 번호만 명시).
# H24(RFP-29-03 A): 기준선 출력 패턴 `GRADE_EXCEPTION_MISUSE`.
# H29: 출처 종류 누락(⑬). H28(⑨ `QUOTE_MISMATCH`)은 평가 보조 집계가 `quote_mismatch`로 따로 세므로 여기 넣지 않는다(이중 집계 방지).
CHECK_RULES: dict[str, str] = {
    GRADE_VALUE_INVALID: "H22",
    M_NO_DETAIL: "H22",
    M_CONVERTED: "H22",
    GRADE_EXCEPTION_MISUSE: "H24",
    SOURCE_KIND_MISSING: "H29",
}

# 실패 처리 흐름(AG-07 §3 "실패 시 처리 흐름"). 검사 이름 → 이 함수의 처리. 그 뒤의 처리는 그래프(`graph/nodes.py` validator)가 한다.
#   DROPPED  그 문장만 지운다. 남은 문장이 있으면 FIXED → finalize(남은 문장만 요약 칸에).
#   REWIND   답변 단위 되감기. 상태 FAIL → 노드가 되감기 1회(모델 재생성) → 다시 FAIL이면 폴백(모델 문장 없이 코드 문구만).
# 남은 문장이 없으면(전부 DROPPED) 상태 FAIL → 같은 되감기·폴백 경로(노드 사유 `ALL_SENTENCES_DROPPED`).
# "확인할 수 없음" 같은 문장 대체는 하지 않는다(대체 문구는 코드 상수여야 하는데 아직 승인된 문구가 없다. 판정·항목 줄은 finalize가 코드로 붙인다).
DROPPED, REWIND = "DROPPED", "REWIND"
CHECK_ACTIONS: dict[str, str] = {
    BAD_CLAIM_TYPE: DROPPED,
    QUOTE_MISMATCH: DROPPED,
    SOURCE_KIND_MISSING: DROPPED,
    GRADE_EXCEPTION_MISUSE: DROPPED,
    SAFE_ASSERTION: DROPPED,
    DOSE_CHANGE_OR_BYPASS: DROPPED,
    GRADE_VALUE_INVALID: DROPPED,
    M_CONVERTED: DROPPED,
    M_NO_DETAIL: DROPPED,
    FILE_API_CLAIM: DROPPED,
    REFERENCE_AS_VERDICT: DROPPED,
    UNCONFIRMED_AS_FACT: DROPPED,
    NUMBER_NOT_IN_EVIDENCE: DROPPED,
    MISSING_IMPLIES_NONE: DROPPED,
    MISSING_ADVICE_ABSENT: REWIND,
    CLAIM_LAYER_NOT_ALLOWED: DROPPED,
    INGREDIENT_NOT_IN_EVIDENCE: DROPPED,
    CLAIM_OMITTED: REWIND,
}

# ---------------------------------------------------------------------------------------- (개선) 허용 근거 계층·주장 유형 누락
# 허용 매트릭스(`P2-doc/PJ2-DUR-RAG-근거설계.md` 4장)를 이 답변 계약에서 코드로 볼 수 있는 부분만 옮겼다.
#   L0 판정 항목: 판정 도구(`check_contraindications`)가 낸 DUR 파일·API 항목. 금기 여부(목록에 있음·없음)는 이것만 근거로 한다.
#   L1 고시·L2 사유·L3 허가사항·L4 용어: 검색 청크(`kind == "chunk"`, `verdict_allowed=False`)·라벨 항목. 금기 사유·설명에는 쓰되 금기 여부를 정하지 않는다.
# 문장 종류는 `claim_type`(fact·conclusion·guidance)만 있고 주장 유형(금기 여부·사유 등) 표기가 없어(AG-06 출력 계약), 아래 정규식으로 코드가 추정한다.
CLAIM_CONTRA_STATUS = "contra_status"   # `router.CLAIM_CONTRA_STATUS`와 같은 값(순환 import를 피해 값을 적는다. 시험이 둘이 같음을 확인한다)
CORE_CONTRA_KINDS = frozenset({"contra_pair", "pregnancy", "age"})   # 핵심 금기(병용·임부·연령). 주의(용량·수유·노인)는 누락 검사 대상이 아니다
NON_VERDICT_KINDS = frozenset({"chunk", "label", "search_miss", "identify", "grade_def"})
# 누락 사유(상태 기록): 묶음에 근거가 없었다(검색·조회 누락) / 묶음에는 있는데 답변 문장이 말하지 않았다
GAP_RETRIEVAL_MISS, GAP_ANSWER_OMIT = "RETRIEVAL_MISS", "ANSWER_OMIT"
# ⑭ 금기 여부 문장: "금기" 뒤 12자 안에 목록 등재·부재·해당·지정·등급을 말하는 서술이 온다(공백 제거 문장 기준).
_STATUS_CLAIM = re.compile(r"금기[가-힣0-9·]{0,12}?(?:올라|있|없|해당|지정|입니다|예요|이에요|아니|아닙|[12Mm]등급)")
# 금기 사유·기전 설명(L2·L3 허용)과 "확인하지 못했다"는 문장은 금기 여부 주장으로 보지 않는다
_REASON_TALK = re.compile(r"사유|이유|때문|기전|혈중|농도|부작용|보고|증가|감소|위험이|효과")
# ⑮ 성분 구성 주장 "성분은/는/인/이 X(·Y)" — X가 근거 원문에 없으면 모델 지식으로 보탠 성분명이다(J1 근거 충실 실패 관찰: dev-102·dev-107).
_INGR_CLAIM = re.compile(
    r"성분(?:은|는|인|이)\s*(?P<names>[가-힣A-Za-z][가-힣A-Za-z0-9·,\s]{1,80}?)"
    r"(?=(?:이며|이고|입니다|이에요|예요|이라|라고|을|를|으로|로)(?:[^가-힣]|$)|[.,]|$)")
_INGR_SPLIT = re.compile(r"[·,/]|\s+(?:및|와|과)\s+")
# 이름이 아니라 서술이 잡힌 경우("성분은 확인되지 않았습니다", "성분이 같은 약")는 검사하지 않는다
_INGR_NOT_NAME = re.compile(r"확인|않|없|있|나와|적혀|같|해당|정보|자료|내용|제공|표시|포함|다르|동일|알려|무엇|어떤|무슨|여러|가지|약의")


# ⑬ H29: 판정 항목은 출처 종류가 `finalize` 표지 상수(`fp.SOURCE_KIND_TEXT`)에 있는 값이어야 근거로 쓴다(`finalize._bucket`과 같은 기준).
# 출처 종류가 없는 판정 항목은 `finalize`가 "확인하지 못함"으로 내리므로, 그 항목을 인용한 모델 문장도 지운다(근거와 표지가 어긋나지 않게).
# 미식별·근거 없음(`UNIDENTIFIED`·`NO_EVIDENCE` 등)은 원래 `source_kind`가 없다(도구 출력 계약)라 대상이 아니다(⑪·⑫가 본다).
VALID_SOURCE_KINDS = frozenset(fp.SOURCE_KIND_TEXT)

# ⑨ 인용 글자 일치(H28). 문장에 연결된 근거 중 원문 인용 대상(`CORPUS_QUOTE` 청크 또는 라벨 항목)이 있을 때만 검사한다.
# - 인용부호: 큰따옴표(" “ ”)와 낫표(「」『』)만 본다. 작은따옴표(' ‘ ’)는 한국어에서 강조에 흔히 쓰여 보지 않는다(한계).
# - 공백 제거 뒤 `QUOTE_MIN_CHARS`자 미만(`…` 제외)인 짧은 인용은 강조·용어로 보고 보지 않는다(오탐 방지, 한계).
# - 허용하는 정규화는 공백·줄바꿈 제거뿐이다. 생략은 `…`로만(조각이 원문 한 근거 안에 같은 순서로 있어야 한다).
# - 원문은 문장의 `evidence_ids` 각각의 원문(`build_text_index`)이다. 여러 근거를 이어 붙이지 않으므로 청크를 가로지르는 인용은 불일치다.
QUOTE_MIN_CHARS = 6
QUOTABLE_SOURCE_KINDS = frozenset({"CORPUS_QUOTE"})
_QUOTE_SPAN = re.compile(r"[\"“「『]([^\"“”「」『』\n]+)[\"”」』]")

# ---------------------------------------------------------------------------------------- 금칙 상수(공백 제거 문장에 매칭)
# 매칭 뒤 12자 안에 부정(아니·없·않·못·말)이 오면 "안전하다는 뜻이 아니에요" 같은 부정 문장이므로 통과시킨다.
SAFE_ASSERTION_PATTERNS = (
    r"안전(?:합니다|해요|하다|하게(?:먹|복용|드)|한약|한조합)",
    r"문제(?:없|가없|될것이없|는없)",
    r"(?:먹어도|복용해도|드셔도|써도|같이먹어도|함께먹어도)(?:돼요|됩니다|된다|괜찮)",
    r"괜찮(?:습니다|아요|은조합|은약|다)",
    r"안심(?:하|해도|하셔도)",
    r"걱정(?:없|하지마|안하)",
    r"이상(?:은)?없(?:습니다|어요)",
    r"해당(?:사항)?없(?:습니다|어요)",
)
_NEGATION = re.compile(r"아니|없|않|못|말")
_SAFE_RES = [re.compile(p) for p in SAFE_ASSERTION_PATTERNS]

# 복용 변경·중단·감량 지시와 의료진 우회(H6·H7). 복용 지시 일반형은 문장 필터의 `_DECISION_PATTERNS`를 재사용한다.
# 상의 권유("숨기지 말고 알려 주세요", "상의하지 않고 끊지 마세요", "임의로 줄이거나 끊지 마세요")는 통과시키고(AG-07 후속,
# 2026-11-11), 우회 조장("말씀 안 드려도 돼요", "알리지 않아도 됩니다")·변경 지시("알아서 줄이세요")는 계속 막는다.
# 구분 방식: 문장을 절(종결 어미·구두점)로 나눈 뒤
#   ⓐ 숨김 표지(숨기·비밀로, 의료진+몰래·모르게)는 바로 금지형(…지 마/말/않, …면 안, …서는 안)이 붙거나 목적어 하나 뒤
#      복용 변경 동사의 금지형이 오면("의사 몰래 약을 끊지 마세요") 권유로 본다.
#   ⓑ 알림·상의 동사의 부정(알리지 않/말하지 말/말씀 안 드려/상의할 필요 없 …)은 우회로 보되, 다음 셋은 권유로 본다.
#      - 연결형(…지 않고/않은 채/않으면서) 바로 뒤가 복용 변경 동사의 금지형이다("상의하지 않고 끊지 마세요")
#      - 관형·가정형(…지 않은/않았다면, 못 드렸다면) 뒤에 알림·상의 권유 명령이 온다("알리지 않은 약이 있다면 알려 주세요")
#      - 바로 뒤가 "…으면 안"이다("알리지 않으면 안 돼요")
#   ⓒ 임의 변경(임의로·마음대로·스스로·알아서 + 끊·줄이·늘리…)은 그 동사 사슬("줄이거나 끊")에 금지형이 바로 붙을 때만 권유로 본다.
#   금지형은 복용 변경 동사 사슬에 바로 붙어야 한다(`_CHAIN_PROHIBIT`). "알아서 줄이고 다른 약은 바꾸지 마세요"는 우회로 남는다.
#   ⓓ 병원·약국에 가지 말라/갈 필요 없다(“가지고 가서”는 제외), "…해도 돼요"형 복용 변경 허락, 처방 무시는 그대로 막는다.
_CLAUSE_SPLIT = re.compile(r"(?<=세요|어요|아요|해요|예요|에요|니다|돼요)|(?<=십시오)|[.,!?;·]")
_PROHIBIT = r"(?:지(?:마|말)|(?:으|시|하시|으시)?면안|서는안|선안)"
# 복용 변경 동사 사슬("줄이거나 끊", "중단하")에 금지형이 *바로* 붙어야 권유로 본다("알아서 줄이고 다른 약은 바꾸지 마세요"는 우회).
_CHG = r"(?:끊|중단|중지|줄이|늘리|조절|감량|증량|바꾸|변경|멈추|그만두|그만먹|복용|먹|드시|건너뛰)"
_CHAIN_PROHIBIT = _CHG + r"하?(?:(?:거나|이나)" + _CHG + r"하?)*" + _PROHIBIT
_SELF_ADV = r"(?:임의로|마음대로|함부로|스스로|알아서|혼자서?|혼자판단해서)?"
_OBJ = r"(?:(?:(?!고|거나)[가-힣]){0,6}?(?:을|를|은|는|도))?"   # "약을", "복용량을" 같은 목적어 하나(연결 어미 "고"를 넘지 않는다)
_ACTION_PROHIBIT_AFTER = re.compile("^" + _SELF_ADV + _OBJ + _SELF_ADV + _CHAIN_PROHIBIT)
_SELF_CHAIN_PROHIBIT = re.compile("^" + _SELF_ADV + _CHAIN_PROHIBIT)   # ⓒ: 부사 바로 뒤 동사 사슬에 금지형
_STAFF = r"(?:의사|약사|선생님|의료진|병원|약국|주치의|담당의)"
_CONCEAL = re.compile(r"숨기|숨겨|숨길|비밀로|" + _STAFF + r"(?:님)?(?:[가-힣]{0,3}?)(?:몰래|모르게)")
_CONCEAL_NEGATED = re.compile(r"^(?:하)?(?:지(?:마|말|않)|면안|서는안|선안)")
_INFORM = r"(?:알리|말하|말씀하|말씀드리|얘기하|이야기하|상의하|상담하|물어보|여쭤보)"  # "확인하지 않았어요"(조회 범위 설명)는 넣지 않는다
_INFORM_NEG = re.compile(
    _INFORM + r"지(?:마|말|않)"
    r"|(?:알릴|말할|말씀드릴|말씀할|얘기할|이야기할|상의할|상담할|물어볼|여쭤볼)필요(?:가|는|도)?없"
    r"|(?:말씀|말|얘기|이야기|상의)(?:은|는|도)?(?:안|못)(?:드려|드리|드렸|해|하|했)"
    r"|안(?:알려|알리|말해|물어)"
    r"|확인(?:하지않아도|할필요(?:가|는|도)?없)"
)
_INFORM_CONNECT = re.compile(r"^않(?:고서|고|은채로|은채|은상태로|으면서)")
_INFORM_RELATIVE = re.compile(r"^(?:않은(?!채|상태)|않았다면|않았으면|않았던)|^(?:드렸|했)(?:다면|으면)")
_INFORM_MUST = re.compile(r"^(?:않으면|않으시면)안")
_INFORM_ADVICE = re.compile(
    r"(?:알려|말씀해|말씀드려|얘기해|이야기해|상의해|상담해|물어봐|여쭤봐)(?:주|보)?(?:세요|십시오)"
    r"|(?:알리|말씀하|얘기하|이야기하|상의하|상담하|물어보|여쭤보|확인하)(?:세요|십시오)"
)
_SELF_CHANGE = re.compile(r"(?:임의로|마음대로|스스로|알아서|혼자서?)(?:끊|중단|줄이|줄여|늘리|늘려|조절|감량|증량|바꾸|바꿔)")
_VISIT_SKIP = re.compile(r"(?:병원|의사|약국|진료)(?:에|을|를|은|는)?(?:가지(?:마|말|않아도)|갈필요(?:가|는)?없|안가도)")
# 존대형("끊으셔도 됩니다")도 같은 뜻이다(AG-08-01 A 출구 보강)
_CHANGE_ALLOWED = re.compile(
    r"(?:끊어도|중단해도|줄여도|늘려도|그만먹어도|안먹어도|끊으셔도|중단하셔도|줄이셔도|늘리셔도|그만드셔도)(?:돼요|됩니다|된다|괜찮)")
_IGNORE_RX = re.compile(r"처방(?:을|은)?무시")


def _clauses(norm: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT.split(norm) if c]


def _has_bypass(norm: str) -> bool:
    """의료진 우회 조장·임의 복용 변경 지시가 있으면 True. 공백을 지운 문장(`_norm`)을 받는다."""
    if _VISIT_SKIP.search(norm) or _CHANGE_ALLOWED.search(norm) or _IGNORE_RX.search(norm):
        return True
    for clause in _clauses(norm):
        # ⓐ 숨김 표지
        for m in _CONCEAL.finditer(clause):
            tail = clause[m.end():]
            if _CONCEAL_NEGATED.search(tail) or _ACTION_PROHIBIT_AFTER.search(tail):
                continue
            return True
        # ⓑ 알림·상의 동사의 부정
        for m in _INFORM_NEG.finditer(clause):
            neg_at = m.end() - 1 if m.group().endswith("않") else None
            tail = clause[neg_at:] if neg_at is not None else clause[m.end():]
            conn = _INFORM_CONNECT.search(tail) if neg_at is not None else None
            if conn and _ACTION_PROHIBIT_AFTER.search(tail[conn.end():]):
                continue
            if neg_at is not None and _INFORM_MUST.search(tail):
                continue
            rel_tail = tail if neg_at is not None else clause[m.end() - 2:]
            if _INFORM_RELATIVE.search(rel_tail) and _INFORM_ADVICE.search(norm[norm.find(clause) + m.end():]):
                continue
            return True
        # ⓒ 임의 변경
        for m in _SELF_CHANGE.finditer(clause):
            if _SELF_CHAIN_PROHIBIT.search(clause[m.start():]):
                continue
            return True
    return False


_GRADE_AFTER = re.compile(r"(?<![가-힣A-Za-z0-9])([0-9A-Za-z]+)\s*등급")
_GRADE_BEFORE = re.compile(r"등급\s*[:은는이]?\s*([0-9A-Za-z])(?![0-9A-Za-z])")
ALLOWED_GRADES = frozenset({"1", "2", "M"})
_M_MENTION = re.compile(r"(?<![A-Za-z])[Mm]\s*등급|임부금기\s*[Mm](?![A-Za-z])")
# M을 1·2등급으로 환산한 문장: "M등급은 사실상 2등급이에요", "M = 1등급"
_M_CONVERT = re.compile(r"[Mm]\s*(?:등급)?\s*(?:은|는|이|가)?\s*(?:사실상|결국|곧|바로)?\s*(?:=|≒|~)?\s*[12]\s*등급\s*(?:이에요|입니다|과같|와같|에해당|으로(?:볼|봐|환산|계산|취급)|이라고)|[Mm]\s*(?:등급)?\s*(?:=|≒)\s*[12]\s*등급")
_M_EXPLAIN = re.compile(r"상병에\s*(?:따른|따라|따라서)|상병별")  # 고시 설명("상병에 따른 1등급 또는 2등급")은 환산이 아니다

# ⑩ H24 `GRADE_EXCEPTION_MISUSE`(RFP-29-03 A, 기준선). 공백을 지우고 인용 구간을 뺀 문장에 매칭한다.
# 고시의 2등급 예외 단서("불가피한 경우…")와 심평원 운영 문구("사유 기재 불필요")는 복용 허용 근거가 아니고,
# 1·2·M 등급은 위험 서열이 아니다. 아래 네 갈래 중 하나가 부정·되물음 없이 나오면 차단한다.
#   ⓐ 등급 + 허용: "2등급이라 괜찮", "2등급은 드셔도 돼요", "2등급이면 의사 상의 없이 써도 돼요"
#   ⓑ 예외 + 허용: "예외로 복용하세요", "예외에 해당하니 드셔도 돼요", "예외적으로 복용할 수 있어요"
#   ⓒ 서열: "2등급은 1등급보다 덜 위험", "2등급은 약한 금기", "M등급은 위험이 낮아요"
#   ⓓ 사유 기재 불필요 + 허용·완화: "사유 기재가 필요 없으니 드셔도", "사유 기재 불필요라 부담 없이"
# 통과(오탐 방지): 등급 사실("2등급 금기입니다"), 정의 설명("원칙적으로 사용을 금지"), "…뜻은 아니에요"류 부정,
# 사용자 질문 되풀이("2등급은 먹어도 되냐고 물으셨는데"), 근거 원문 인용 구간(② 와 같은 `_mask_quotes`).
_GRADE_MENTION = r"(?:[12Mm]등급|등급[12Mm](?![A-Za-z0-9]))"
_PERMIT = (
    r"(?:괜찮|먹어도|드셔도|복용해도|복용하셔도|써도|쓰셔도|사용해도|사용하셔도|드세요|드시면돼|드시면됩|복용하세요|복용하시면"
    r"|복용가능|사용가능|드실수있(?:어요|습니다)|복용할수있(?:어요|습니다)|사용할수있(?:어요|습니다)|먹을수있(?:어요|습니다)"
    r"|가능(?:해요|합니다)|허용(?:돼|됩|된|해요|합니다)|문제(?:가)?없|상관없|무방|부담없|안심"
    r"|걱정(?:없|안하셔도|안해도|하지않으셔도|하지않아도|하지마))"
)
_RANK = (
    r"(?:(?:덜|더|비교적|상대적으로|훨씬|조금|좀)(?:위험|안전|해롭|해로|심각|약하|약한|강하|강한|순하|순한|괜찮|낫|가벼)"
    r"|(?:약한|가벼운|낮은|순한|덜한|느슨한)(?:금기|단계|수준|편|등급)"
    r"|위험(?:도|성)?(?:이|가|은|는)?(?:낮|적|약|덜|크지않)"
    r"|(?:보다|에비해|에비하면)(?:는)?[가-힣]{0,4}?(?:낫|약하|약한|순하|순한|가벼|안전|괜찮|덜))"
)
_EXC_MISUSE_RES = (
    re.compile(_GRADE_MENTION + r"(?:이라서|이라|이니까|이니|이므로|이어서|이면|이라면|인데|이라도|으로|은|는|이|도|의경우|약은|약이라|짜리)"
               r"[가-힣]{0,14}?" + _PERMIT),
    re.compile(r"예외(?:적으로|적인경우(?:에는|엔|라)?|로|라서|라|이니까?|이므로|조항|단서)[가-힣]{0,12}?" + _PERMIT
               + r"|예외(?:에|로)해당(?:하니까?|해서|하므로|하면|되니까?|돼서|되면)[가-힣]{0,12}?" + _PERMIT),
    re.compile(_GRADE_MENTION + r"[가-힣]{0,14}?" + _RANK),
    re.compile(r"사유(?:를|의)?(?:기재|입력|적|기록)[가-힣]{0,6}?(?:불필요|필요(?:가|는|도)?없|안해도|하지않아도)[가-힣]{0,14}?"
               r"(?:" + _PERMIT + r"|" + _RANK + r")"),
)
# 매칭 바로 뒤(같은 절 안 20자)에 부정이 오면 "…는 뜻이 아니에요" 같은 반박이다
_EXC_NEGATED = re.compile(r"아니|않|못|말(?:아|고|라|기|씀하지)|안돼|안됩|안된|수없|금지|금기(?:예요|입니다|이에요|가맞)")
# 사용자 질문 되풀이: "…먹어도 되냐고 물으셨는데", "…되죠? 하고 물으셨어요"
_EXC_ECHO = re.compile(r"^[가-힣]{0,6}?(?:되죠|되나요|될까요|되냐|되는지|괜찮을까|괜찮나|괜찮냐|괜찮은지|낫나|낫냐|나요|까요|냐)\??"
                       r"(?:라고|라는|하고|고|는)?(?:물|궁금|질문|여쭤|하셨|생각하실)")
_EXC_CLAUSE_END = re.compile(r"[.!;]|(?<=세요|어요|아요|해요|예요|에요|니다|돼요)(?=[^가-힣]|$)")


def _has_grade_exception_misuse(norm: str) -> bool:
    """⑩ H24: 등급·예외 단서·"사유 기재 불필요"를 복용 허용·위험 서열로 쓴 문장이면 True. 공백 제거·인용 구간 제외 문장을 받는다."""
    for rx in _EXC_MISUSE_RES:
        for m in rx.finditer(norm):
            tail = norm[m.end():m.end() + 20]
            end = _EXC_CLAUSE_END.search(tail)
            clause_tail = tail[:end.end()] if end else tail
            if _EXC_NEGATED.search(clause_tail) or _EXC_ECHO.search(norm[m.end():m.end() + 30]):
                continue
            return True
    return False

_ONLY_CLAIM = re.compile(r"파일에만|파일에는있고|API에만|실시간(?:조회)?에만|실시간(?:조회)?에는있고")
_DEFINITIVE = re.compile(r"금기(?:입니다|예요|이에요|가맞|에해당|목록에있|로지정|다(?:$|[.!]))|금기(?:가|는)?아(?:닙니다|니에요|니예요)|금기(?:목록)?에(?:없어요|없습니다|없음)|지정되어있|지정돼있|해당합니다|해당돼요")
_HEDGE = re.compile(r"기준일이후(?:에)?(?:변경|해제|새로|지정|달라)|변경되었을수|변경됐을수|바뀌었을수")

# 연령·번호 수치(용량 숫자는 문장 필터 몫). 한국어 날짜(년·월)는 검사하지 않고 ISO 날짜만 본다.
_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:세|개월|주|호|쪽|조|항|연번|판)")
_NUM_PREFIX = re.compile(r"(?:제|연번|쪽|별표|고시)\s*(\d+)")

_PHARMACIST = re.compile(r"약국|약사")
_NONE_IMPLY = re.compile(r"없(?:어요|습니다|음)")
# ⑪·⑫(AG-09 §2, 2026-11-18). 인용한 항목이 "확인된 근거"인가: 상태가 FOUND·NOT_LISTED이고 판정을 내리는 꼬리표(참고 전용·코드 미연결)가 없다.
_CONFIRMED_STATUS = ("FOUND", "NOT_LISTED")
_UNCONFIRMED_FLAGS = frozenset({"REFERENCE_ONLY", "CODE_NOT_LINKED", "PAIR_NOT_CHECKED", "LOOKUP_FAILED"})
# "확인하지 못했다"고 말하는 문장(⑪의 예외): 근거가 없다는 사실 자체를 전하는 것은 막지 않는다
_UNCONFIRMED_SAID = re.compile(r"(?:찾지|확인하지|확인되지|불러오지|조회하지|판정하지|알려드리지)(?:못|않)|(?:찾을|확인할|알)수없|확인이(?:안|어려)|판정(?:이|은)?아니|참고")
_NOT_FOUND_OK = re.compile(r"(?:찾지|확인하지|불러오지|알수|적혀있지|조회하지)(?:못|않)|수없|뜻이아니|아니에요")


# ---------------------------------------------------------------------------------------- 고정 문구 상수 모음
def _collect_fixed_texts() -> tuple[str, ...]:
    out: set[str] = set()

    def add(s: str) -> None:
        for seg in re.split(r"\{[a-z_]+\}", s):
            seg = seg.strip()
            if len(seg) >= 8:
                out.add(seg)

    for name, v in vars(fp).items():
        if name.startswith("_") or name == "FORBIDDEN_SCREEN_TERMS":
            continue
        if isinstance(v, str):
            add(v)
        elif isinstance(v, (tuple, list)) and v and all(isinstance(x, str) for x in v):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                if isinstance(x, str):
                    add(x)
    return tuple(sorted(out, key=len, reverse=True))


FIXED_TEXTS = _collect_fixed_texts()


def strip_fixed(text: str) -> str:
    for f in FIXED_TEXTS:
        text = text.replace(f, " ")
    return text


# ---------------------------------------------------------------------------------------- 결과 타입
@dataclass(frozen=True)
class Issue:
    index: int           # 입력 문장 순번(문장 단위 검사). 답변 단위 검사는 -1
    check: str
    action: str          # "DROPPED" | "REWIND"
    text: str = ""       # 걸러진 문장 원문(결과 객체에만 있고 이벤트에는 넣지 않는다)


@dataclass
class ValidationResult:
    status: str = PASS
    kept: list[Any] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    rewind: list[str] = field(default_factory=list)   # 약사 확인 권고가 없어 되감을 미확보 항목의 근거 ID
    events: list[dict[str, Any]] = field(default_factory=list)
    # (개선, `layer_check=True`일 때만) 주장 유형 누락: {"claim", "gap": RETRIEVAL_MISS|ANSWER_OMIT, "evidence_id"}. 문장 원문은 담지 않는다
    claim_gaps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dropped(self) -> list[Issue]:
        return [i for i in self.issues if i.action == DROPPED]


# ---------------------------------------------------------------------------------------- 보조
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _sent(x: Any) -> SimpleNamespace:
    """Sentence 객체·dict를 같은 모양으로 읽는다(claim_type이 잘못된 dict도 받는다)."""
    get = (lambda k, d=None: x.get(k, d)) if isinstance(x, dict) else (lambda k, d=None: getattr(x, k, d))
    cites: list[Citation] = []
    for c in get("citations", None) or []:
        try:
            cites.append(c if isinstance(c, Citation) else Citation(**c))
        except (TypeError, ValueError):   # 잘못된 인용은 건너뛴다(인용 오류는 렌더러·필터 몫)
            pass
    return SimpleNamespace(raw=x, text=get("text", "") or "", evidence_ids=list(get("evidence_ids", None) or []),
                           claim_type=get("claim_type", None), citations=cites)


def _has_safe_assertion(norm: str) -> bool:
    for r in _SAFE_RES:
        for m in r.finditer(norm):
            if not _NEGATION.search(norm[m.end():m.end() + 12]):   # 뒤 12자에 부정이 오면 "문제없다고 말할 수 없어요"류 부정이다
                return True
    return False


def _mask_quotes(sent: SimpleNamespace, index: dict[str, str]) -> str:
    """허가사항 원문 인용(근거 상세·인용 구간)은 ② 검사에서 뺀다(RFP-21-03). 인용부호 안 글자가 근거 원문의 부분 문자열이거나
    해결된 인용 구간 글자와 같을 때만 뺀다."""
    text = sent.text
    pool = [index[e] for e in sent.evidence_ids if e in index]
    for c in sent.citations:
        r = resolve_citation(c, index)
        if r.ok and r.text:
            text = text.replace(r.text, " ")
    for q in re.findall(r"[「“\"'‘]([^」”\"'’]{2,})[」”\"'’]", text):
        if any(q.strip() in p for p in pool):
            text = text.replace(q, " ")
    return text


def _unwrap(answer: Any, rendered: RenderResult | None) -> tuple[list[Any], RenderResult | None]:
    if isinstance(answer, tuple):
        answer, rendered = answer[0], (answer[1] if len(answer) > 1 else rendered)
    sents = answer.get("sentences", []) if isinstance(answer, dict) else getattr(answer, "sentences", answer)
    return list(sents), rendered


def _cited_items(sent: SimpleNamespace, by_id: dict[str, dict[str, Any]], row_to_item: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in sent.evidence_ids:
        it = by_id.get(e) or row_to_item.get(e)
        if it is not None and it not in out:
            out.append(it)
    return out


def _api_time(it: dict[str, Any]) -> Any:
    return it.get("queried_at_utc") or (it.get("api") or {}).get("queried_at_utc")


def _rows(it: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in it.get("matches") or [] if isinstance(m, dict)]


def _grade_values(norm_or_text: str) -> list[str]:
    vals = [m.upper() for m in _GRADE_AFTER.findall(norm_or_text)] + [m.upper() for m in _GRADE_BEFORE.findall(norm_or_text)]
    return vals


def _quotable(it: dict[str, Any]) -> bool:
    return it.get("source_kind") in QUOTABLE_SOURCE_KINDS or bool(it.get("is_label"))


def _quote_mismatch(text: str, s: SimpleNamespace, ctx: SimpleNamespace) -> bool:
    """⑨ H28: 원문 인용 대상 근거에 연결된 문장의 인용부호 안 글자가 그 근거 원문 하나에 글자 그대로 있는지(공백만 정규화)."""
    if not any(_quotable(it) for it in _cited_items(s, ctx.by_id, ctx.row_to_item)):
        return False
    pool = [_norm(ctx.index[e]) for e in s.evidence_ids if ctx.index.get(e)]
    for q in _QUOTE_SPAN.findall(text):
        qn = _norm(q)
        if len(qn.replace(ELLIPSIS, "")) < QUOTE_MIN_CHARS:
            continue
        if not any(verify_quote_text(qn, p) for p in pool):   # 원문이 비었거나(EASY_TEXT_MISSING 등) 어느 한 근거에도 없으면 불일치
            return True
    return False


# ---------------------------------------------------------------------------------------- 문장 단위 검사
def _check_sentence(s: SimpleNamespace, items: list[dict[str, Any]], ctx: SimpleNamespace, allowed_types: frozenset[str]) -> str | None:
    # ⑦ claim_type: 검사 전에 걸러 실패로 기록한다
    if s.claim_type not in allowed_types:
        return BAD_CLAIM_TYPE
    text = strip_fixed(s.text)                 # 고정 문구 상수는 검사 대상이 아니다
    if not text.strip():
        return None
    norm = _norm(text)

    # ⑬ 출처 종류 누락(H29): 표지 없는 판정 항목을 근거로 쓴 문장은 내용을 보기 전에 지운다
    if any(_source_kind_missing(it) for it in _cited_items(s, ctx.by_id, ctx.row_to_item)):
        return SOURCE_KIND_MISSING

    # ⑨ 인용 글자 일치(H28): 지어낸 인용은 다른 검사보다 먼저 사유를 정한다(인용 구간 마스킹 ②가 지어낸 인용을 빼지 않도록)
    if _quote_mismatch(text, s, ctx):
        return QUOTE_MISMATCH

    # ⑩ H24 등급 예외 단서·"사유 기재 불필요" 오용, 등급 위험 서열(근거 원문 인용 구간은 제외).
    # ①보다 먼저 본다: "2등급이라 괜찮아요"는 안전 단정이기도 하지만 더 구체적인 H24 코드로 집계한다.
    q_norm = _norm(_mask_quotes(SimpleNamespace(**{**s.__dict__, "text": text}), ctx.index))
    if _has_grade_exception_misuse(q_norm):
        return GRADE_EXCEPTION_MISUSE

    # ① 안전 단정
    if _has_safe_assertion(norm):
        return SAFE_ASSERTION

    # ② 복용 변경·중단·복용 지시와 의료진 우회(허가사항 원문 인용 구간은 제외)
    if _has_bypass(q_norm) or any(r.search(q_norm) for r in _DECISION_PATTERNS):
        return DOSE_CHANGE_OR_BYPASS

    # ③ 등급 값은 1·2·M만
    grades = _grade_values(text)
    if any(g not in ALLOWED_GRADES for g in grades):
        return GRADE_VALUE_INVALID

    # ④ M 등급
    if _M_CONVERT.search(norm) and not _M_EXPLAIN.search(text):
        return M_CONVERTED
    if _M_MENTION.search(text):
        cited = _cited_items(s, ctx.by_id, ctx.row_to_item) or items
        m_rows = [r for it in cited for r in _rows(it) if str(r.get("grade") or "").strip().upper().removesuffix("등급") == "M"]
        if not m_rows:
            return NUMBER_NOT_IN_EVIDENCE        # 근거에 M이 없다
        if any(not str(r.get("detail") or "").strip() for r in m_rows):
            return M_NO_DETAIL

    # ⑤ 파일/API 확정 문장(5.1절 (7))
    cited = _cited_items(s, ctx.by_id, ctx.row_to_item)
    if _ONLY_CLAIM.search(norm):
        has_file = any(it.get("source_kind") == "FILE" or "FILE_ONLY" in (it.get("flags") or []) for it in cited)
        has_api = any((it.get("source_kind") == "API_DIRECT" and _api_time(it)) or
                      (it.get("source_kind") == "FILE" and _api_time(it) and set(it.get("flags") or []) & {"FILE_ONLY", "API_ONLY", "API_SAME"})
                      for it in cited)
        if not (has_file and has_api):
            return FILE_API_CLAIM
    api_only = any("API_ONLY" in (it.get("flags") or []) or
                   (it.get("source_kind") == "API_DIRECT" and it.get("kind") in ("contra_pair", "pregnancy", "age"))
                   for it in cited)
    has_file_item = any(it.get("source_kind") == "FILE" and "API_ONLY" not in (it.get("flags") or []) for it in cited)
    if api_only and not has_file_item and _DEFINITIVE.search(norm) and not _HEDGE.search(norm):
        return FILE_API_CLAIM

    # ⑪·⑫ AG-09: 확인하지 못한 항목을 근거로 사실·판정을 말하지 않는다(코드가 만든 항목 줄은 `finalize`가 이미 "확인하지 못함"으로 내린다.
    # 여기서는 모델 요약 문장이 같은 항목을 인용해 반대로 말하는 것을 막는다).
    if cited:
        unconfirmed = [it for it in cited if _is_unconfirmed(it)]
        # 예외 판단은 고정 문구를 빼기 전 문장으로 한다: "…찾지 못했어요" 자체가 승인된 고정 문구(미확보 사유)라 `strip_fixed`가 지운다
        said_unconfirmed = bool(_UNCONFIRMED_SAID.search(_norm(s.text)))
        # ⑫ 참고 전용·코드 미연결·미식별 항목을 인용하면서 "금기예요/금기가 아니에요/목록에 없어요"로 확정한다
        if unconfirmed and _DEFINITIVE.search(norm) and not said_unconfirmed and not _HEDGE.search(norm):
            return REFERENCE_AS_VERDICT
        # ⑪ 사실 문장인데 인용한 항목이 **전부** 확인하지 못한 항목이다(검색 0건·약 미식별 등)
        if s.claim_type == "fact" and len(unconfirmed) == len(cited) and not said_unconfirmed:
            return UNCONFIRMED_AS_FACT

    # ⑧ 근거에 없는 연령·등급·번호·날짜
    bad = [b for b in unsupported_identifiers(text, items) if not b.endswith("등급")]    # 코드·ISO 날짜(등급은 아래에서 직접)
    if bad:
        return NUMBER_NOT_IN_EVIDENCE
    for g in grades:
        if g in ("1", "2") and g not in ctx.grades and not (ctx.has_m and _M_EXPLAIN.search(text)):
            return NUMBER_NOT_IN_EVIDENCE
        if g == "M" and "M" not in ctx.grades:
            return NUMBER_NOT_IN_EVIDENCE
    nums = [*_NUM_UNIT.findall(text), *_NUM_PREFIX.findall(text)]
    for n in nums:
        if not any(re.search(rf"(?<![0-9A-Za-z.\-]){re.escape(n)}(?![0-9A-Za-z\-])", p) for p in ctx.pool):
            return NUMBER_NOT_IN_EVIDENCE

    # ⑭·⑮ (개선) 허용 근거 계층. 기준선 검사를 모두 통과한 문장에만 더 본다(꺼져 있으면 기준선 결과와 같다)
    if ctx.layer_check:
        return _layer_issue(s, norm, cited, items, ctx)
    return None


# ---------------------------------------------------------------------------------------- (개선) 허용 근거 계층(⑭·⑮)
def is_verdict_item(it: dict[str, Any]) -> bool:
    """L0 판정 항목인가: 판정 도구가 낸 DUR 파일·API 항목(FOUND·NOT_LISTED, 출처 종류 FILE·API_DIRECT). 검색 청크·라벨·검색 실패는 아니다."""
    return (it.get("kind") not in NON_VERDICT_KINDS and it.get("verdict_allowed", True) is not False
            and it.get("status") in _CONFIRMED_STATUS and it.get("source_kind") in VALID_SOURCE_KINDS - QUOTABLE_SOURCE_KINDS
            and not _UNCONFIRMED_FLAGS & set(it.get("flags") or []))


def _is_status_claim(raw_text: str, norm: str) -> bool:
    """⑭ 금기 여부(목록에 있음·없음·등급)를 말하는 문장인가. 사유·기전 설명과 "확인하지 못했다"는 문장은 아니다."""
    return bool(_STATUS_CLAIM.search(norm)) and not _REASON_TALK.search(norm) and not _UNCONFIRMED_SAID.search(_norm(raw_text))


def _ingredient_names(text: str) -> list[str]:
    """⑮ "성분은 X·Y" 꼴에서 성분 이름 후보를 뽑는다. 서술이 잡히면(이름이 아님) 빈 목록."""
    out: list[str] = []
    for m in _INGR_CLAIM.finditer(text):
        names = [_norm(x) for x in _INGR_SPLIT.split(m.group("names")) if _norm(x)]
        if not names or any(_INGR_NOT_NAME.search(n) for n in names):
            continue
        out.extend(n for n in names if len(n) >= 2)
    return out


def _layer_issue(s: SimpleNamespace, norm: str, cited: list[dict[str, Any]], items: list[dict[str, Any]],
                 ctx: SimpleNamespace) -> str | None:
    # ⑭ 금기 여부 문장은 L0 판정 항목을 하나 이상 인용해야 한다(검색 청크·라벨·검색 실패만 인용하면 계층 위반).
    # 근거 ID 없이 쓸 수 있는 결론·안내 문장(`EVIDENCE_REQUIRED`)은 묶음 전체에 L0 항목이 하나라도 있어야 한다(dev-114: 검색 실패뿐인데 "금기 조회 결과에 없음")
    if _is_status_claim(s.text, norm) and not any(is_verdict_item(it) for it in (cited or items)):
        return CLAIM_LAYER_NOT_ALLOWED
    # ⑮ 성분 구성 주장의 성분명은 근거 원문(도구 결과 문자열 전체)에 있어야 한다
    names = _ingredient_names(strip_fixed(s.text))
    if names and any(n not in ctx.pool_norm for n in names):
        return INGREDIENT_NOT_IN_EVIDENCE
    return None


# ---------------------------------------------------------------------------------------- (개선) 주장 유형 누락(⑯)
def _cites(s: SimpleNamespace, it: dict[str, Any]) -> bool:
    ids = {it.get("evidence_id")} | {m.get("row_evidence_id") for m in _rows(it)}
    return bool(ids & set(s.evidence_ids))


def claim_gaps(kept: list[SimpleNamespace], items: list[dict[str, Any]], required_claims: Iterable[str]) -> list[dict[str, Any]]:
    """⑯ 필요한 주장 유형 중 코드로 볼 수 있는 "금기 여부"의 누락을 찾는다(AG-07 §2 `:41`).

    - 묶음에 핵심 금기(병용·임부·연령) 판정 항목이 하나도 없으면 `RETRIEVAL_MISS`(조회 누락, 기록만).
    - 핵심 금기 FOUND 항목마다, 그 항목(또는 행)을 인용한 문장이 하나도 없으면 `ANSWER_OMIT`(되감기 대상).
      NOT_LISTED는 대상이 아니다(`finalize`가 "금기 목록에 없음" 줄을 코드로 붙이고, 모델 요약이 말하지 않아도 숨겨지지 않는다).
    "금기"라는 낱말까지 요구하지는 않는다: 개발셋 정상 답의 다수가 "주의가 필요한 것으로 조회됐다"처럼 쓰고(표지는 `finalize`가 코드로 붙임)
    낱말 기준이면 정상 답 48건 중 34건이 되감기로 간다(2026-11-18 밤 오프라인 재생). 낱말 문제는 프롬프트 몫으로 남긴다.
    한계·고지·기준일은 `finalize`가 코드로 붙이므로 보지 않는다(오탐). 등급 정의·용어는 Router 코드 규칙이 채우지 않는다(프롬프트 분류 몫).
    """
    if CLAIM_CONTRA_STATUS not in set(required_claims):
        return []
    core = [it for it in items if it.get("kind") in CORE_CONTRA_KINDS and is_verdict_item(it)]
    if not core:
        return [{"claim": CLAIM_CONTRA_STATUS, "gap": GAP_RETRIEVAL_MISS, "evidence_id": None}]
    gaps: list[dict[str, Any]] = []
    for it in core:
        if it.get("status") != "FOUND":
            continue
        if not any(_cites(s, it) for s in kept):
            gaps.append({"claim": CLAIM_CONTRA_STATUS, "gap": GAP_ANSWER_OMIT, "evidence_id": it.get("evidence_id")})
    return gaps


def _is_unconfirmed(it: dict[str, Any]) -> bool:
    """확인된 근거가 아닌 항목인가: 약 미식별·근거 없음(상태), 참고 전용·코드 미연결·쌍 미조회(꼬리표).
    허가사항 원문·사유 청크처럼 판정 상태가 아닌 인용 근거(`kind == "chunk"`, FOUND)는 확인된 근거다."""
    return it.get("status") not in _CONFIRMED_STATUS or bool(_UNCONFIRMED_FLAGS & set(it.get("flags") or []))


def _source_kind_missing(it: dict[str, Any]) -> bool:
    """⑬ H29: 판정 항목(FOUND·NOT_LISTED)인데 출처 종류가 없거나 표지 상수에 없는 값이다."""
    return it.get("status") in _CONFIRMED_STATUS and it.get("source_kind") not in VALID_SOURCE_KINDS


# ---------------------------------------------------------------------------------------- 답변 단위 검사(⑥)
def _missing_checks(kept: list[SimpleNamespace], items: list[dict[str, Any]]) -> tuple[list[tuple[int, str]], list[str]]:
    """미확보 항목마다 약사 확인 권고 문장이 있는지(없으면 되감기), 그 항목을 "없음·안전"으로 암시한 문장(삭제 대상)을 찾는다."""
    implied: list[tuple[int, str]] = []
    rewind: list[str] = []
    for it in items:
        if not it.get("missing_reason"):
            continue
        eid = it.get("evidence_id")
        names = [str(n) for n in (it.get("drugs") or it.get("subject") or []) if n]
        advised = False
        for i, s in enumerate(kept):
            about = eid in s.evidence_ids or any(n in s.text for n in names)
            if not about:
                continue
            if _PHARMACIST.search(s.text):
                advised = True
            body = _norm(strip_fixed(s.text))
            if (_has_safe_assertion(body) or (_NONE_IMPLY.search(body) and not _NOT_FOUND_OK.search(body))) and not _PHARMACIST.search(s.text):
                implied.append((i, MISSING_IMPLIES_NONE))
        if not advised:
            rewind.append(str(eid))
    return implied, rewind


# ---------------------------------------------------------------------------------------- 진입점
def validate(
    answer: Any,
    items: list[dict[str, Any]],
    *,
    expected_claim_types: Iterable[str] | None = None,
    rendered: RenderResult | None = None,
    layer_check: bool = False,
    required_claims: Iterable[str] | None = None,
) -> ValidationResult:
    """답변 문장을 코드로 검사한다. `answer`는 `AnswerDraft`(또는 `(AnswerDraft, RenderResult)`·`{"sentences": [...]}`·문장 목록).

    - PASS: 걸러진 문장이 없고 되감기도 없다.
    - FIXED: 문장을 걸렀지만(제거) 남은 문장이 있고 되감기가 필요 없다.
    - FAIL: 입력이 있었는데 남은 문장이 없거나, 미확보 항목의 약사 확인 권고가 빠져 되감기가 필요하다.

    `layer_check=True`(개선, 기본 꺼짐)면 ⑭ 허용 근거 계층·⑮ 근거에 없는 성분명을 문장마다 더 보고, `required_claims`(Router 상태
    `required_claims`)가 주어지면 ⑯ 주장 유형 누락을 본다(`ANSWER_OMIT`는 되감기, `RETRIEVAL_MISS`는 `claim_gaps`에 기록만).
    꺼져 있으면 결과·이벤트가 기준선과 같다.
    """
    raw_sents, rendered = _unwrap(answer, rendered)
    allowed = frozenset(expected_claim_types) if expected_claim_types is not None else frozenset(EVIDENCE_REQUIRED)
    by_id = {it["evidence_id"]: it for it in items if it.get("evidence_id")}
    row_to_item = {m["row_evidence_id"]: it for it in items for m in _rows(it) if m.get("row_evidence_id")}
    grades = tool_grades(items)
    pool = _tool_strings(items)
    ctx = SimpleNamespace(by_id=by_id, row_to_item=row_to_item, index=build_text_index(items), grades=grades,
                          has_m="M" in grades, pool=pool, layer_check=layer_check,
                          pool_norm="\n".join(_norm(p) for p in pool) if layer_check else "")
    res = ValidationResult()
    kept: list[SimpleNamespace] = []
    for i, raw in enumerate(raw_sents):
        s = _sent(raw)
        reason = _check_sentence(s, items, ctx, allowed)
        if reason:
            res.issues.append(Issue(i, reason, CHECK_ACTIONS[reason], s.text))
        else:
            kept.append(s)
    # ⑥ 미확보 항목: 권고가 있어야 하고 "없음·안전" 암시가 없어야 한다(걸러진 문장은 빼고 센다)
    implied, rewind = _missing_checks(kept, items)
    drop_idx = {i for i, _ in implied}
    for i, why in implied:
        res.issues.append(Issue(i, why, CHECK_ACTIONS[why], kept[i].text))
    if drop_idx:
        kept = [s for j, s in enumerate(kept) if j not in drop_idx]
        implied2, rewind = _missing_checks(kept, items)   # 암시 문장을 지운 뒤 다시 센다
        del implied2
    for eid in rewind:
        res.issues.append(Issue(-1, MISSING_ADVICE_ABSENT, CHECK_ACTIONS[MISSING_ADVICE_ABSENT], eid))
    # ⑯ (개선) 주장 유형 누락: 남은 문장 기준. 묶음에 있는데 답이 말하지 않은 FOUND 금기는 되감기(재생성), 조회 누락은 기록만
    omitted: list[str] = []
    if layer_check and required_claims is not None and kept:
        res.claim_gaps = claim_gaps(kept, items, required_claims)
        omitted = [str(g["evidence_id"]) for g in res.claim_gaps if g["gap"] == GAP_ANSWER_OMIT]
        for eid in omitted:
            res.issues.append(Issue(-1, CLAIM_OMITTED, CHECK_ACTIONS[CLAIM_OMITTED], eid))
    res.rewind = rewind
    res.kept = [s.raw for s in kept]
    n_dropped = len(res.dropped)
    if rewind or omitted or (raw_sents and not kept):
        res.status = FAIL
    elif n_dropped:
        res.status = FIXED
    reasons: dict[str, int] = {}
    rules: dict[str, int] = {}   # 규칙 번호별 건수(H22·H24 등 `CHECK_RULES`에 있는 검사만). 내용 없는 집계
    for it in res.issues:
        reasons[it.check] = reasons.get(it.check, 0) + 1
        if it.check in CHECK_RULES:
            rules[CHECK_RULES[it.check]] = rules.get(CHECK_RULES[it.check], 0) + 1
    event: dict[str, Any] = {
        "rule": "H2", "event": "VALIDATOR", "status": res.status, "total": len(raw_sents), "kept": len(res.kept),
        "dropped": n_dropped, "rewind": len(rewind), "reasons": reasons, "rules": rules,
    }
    if layer_check:   # 켰을 때만 키를 더한다(꺼져 있으면 기준선 이벤트와 같은 모양). 근거 ID만, 문장 원문 없음
        gaps: dict[str, int] = {}
        for g in res.claim_gaps:
            gaps[g["gap"]] = gaps.get(g["gap"], 0) + 1
        event["layer_check"] = True
        event["claim_gaps"] = gaps
    res.events.append(event)
    return res
