"""AG-08 입구 Guardrail(순수 함수, LLM·외부 호출 없음).

- 응급 키워드 감지는 **저장소에서 이 파일 한 곳**뿐이다(`EMERGENCY_KEYWORDS`·`detect_emergency`, RFP-35-03).
  Router·입력 변환·프론트는 import만 하고 목록을 갖지 않는다(`grep` 시험이 지킨다).
- 응급이어도 금기 조회는 막지 않는다(`proceed_tools=True`, H4).
- 범위 외(복용 중단·감량, 의사에게 숨김, 진단·처방·복용량, 개인 의료기록)는 거절 경로로 보낸다.
- 인젝션 시도는 거절하고, `emergency`·`route`·고정 문구는 LLM·도구 결과가 바꿀 수 없다(H8, `apply_tool_update`).
- 응급 키워드는 직접 정의한 것이며 임상 검수를 받지 않았다(AG-08 §5 가정). 안내는 119·약국·약사까지만(RFP-19-01 A).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.agent.tools.schemas import POST_WRITABLE_KEYS

ROUTE_AGENT = "AGENT"
ROUTE_REFUSE = "REFUSE"

# 띄어쓰기·구두점을 지운 글자에서 부분 문자열로 찾는다. 한국어 표기 변이(숨이/숨을/숨도, 안 쉬어/못 쉬어)를 함께 둔다.
EMERGENCY_KEYWORDS: tuple[str, ...] = (
    # 호흡·의식·경련
    "호흡곤란", "숨쉬기힘", "숨쉬기어려", "숨이안쉬", "숨을못쉬", "숨못쉬", "숨이막", "숨이차", "숨이가빠", "숨쉬는게힘",
    "의식이없", "의식을잃", "의식잃", "의식이흐", "정신을잃", "쓰러졌", "쓰러지", "기절", "경련", "발작", "거품을", "혼수",
    # 흉통·출혈·알레르기 중증
    "가슴이아", "가슴이너무아", "가슴이심하게아", "가슴이쥐어", "가슴이조여", "가슴이답답", "가슴통증", "흉통", "심장이아", "피를토", "토혈", "피가멈추지", "혈변", "검은변", "아나필락시",
    "입술이부", "얼굴이부", "혀가부", "목이부", "목이붓", "온몸에두드러기",
    # 과량·삼킴·중독(TC-07)
    "한통다먹", "한통을다먹", "한통다삼", "통째로먹", "과다복용", "과량복용", "과용했", "과복용", "너무많이먹", "많이먹었",
    "삼켰", "잘못먹", "실수로먹", "중독", "독을먹", "오복용",
    # 직접 표현
    "응급", "119", "구급차", "살려",
)

# 키워드 사이에 약 이름·수량이 끼거나 구어체로 바뀌는 표현(2026-11-11 3차 A3, 개발셋 응급 누락 유형을 일반화).
# 정규화 글자(공백·구두점 제거) 위에서 찾는다. 입구 정밀도 우선(AG-08-02 A): "임신인 줄 모르고 먹었는데"처럼
# 금기 확인 질문에 흔한 표현은 걸지 않도록 주어(아이 등)·사고 동사(실수로·잘못해서)·완료형으로 좁혔다.
_ATE = r"(?<!안)(?<!못)(?:먹었|먹은|먹음|먹어버|먹어치|삼켰|삼킨|삼킴|삼켜버|마셨|마신|마셔버|드셨|드신)"
_KID = r"(?:애|아이|아기|애기|아들|딸|손주|손녀|동생|꼬마|조카|\d+살|[한두세네다여일]\w?살)"
EMERGENCY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    # 사고 섭취: "실수로·잘못해서 … 먹었/삼켰"(약 이름이 사이에 낌), 아이가 "모르고 … 먹었"
    r"(?:실수로|잘못해서|잘못하여)\S{0,20}?" + _ATE,
    _KID + r"(?:가|이)?모르고\S{0,20}?" + _ATE,
    # 구어체 완료형·줍기·집기·통째
    r"(?:먹어|삼켜|마셔)버(?:렸|림|린|려)|(?:주워|집어)(?:먹|삼)|통째(?:로)?(?:먹었|삼켰|마셨|마셔)",
    # 개수 모름·여러 개·한꺼번에·몇 배
    r"(?:몇|여러)(?:알|개|정|봉|포|캡슐|병|통)(?:을|를|이나|씩)?" + _ATE,
    r"한꺼번에\S{0,12}?" + _ATE,
    r"(?:두|세|네|[2-9])배(?:로|나)?" + _ATE,
    # 어른의 약을 아이가 먹음
    r"(?:엄마|아빠|할머니|할아버지|어머니|아버지|부모님|어른|언니|오빠|형|누나|이모|삼촌)(?:가|이|께서)?"
    r"(?:먹는|드시는|복용하는|먹던|드시던|복용중인)\S{0,25}?" + _KID + r"(?:가|이)\S{0,15}?" + _ATE,
    # 눈에 들어감
    r"눈에\S{0,15}?(?:들어갔|튀었|튀어서|묻었)",
    # 복용 뒤 복통·구토, 계속 토함, 위험 상황 확인
    r"(?:배가아프|배아프|배가아파|복통)\S{0,10}?(?:구토|토해|토하|토를)|(?:구토|토해|토하)\S{0,10}?(?:배가아프|배아프|복통)",
    r"(?:계속|자꾸)토|구토(?:를|가)?(?:계속|안멈|멈추지)|위험한상황",
    # 갑작스런 신경·순환 증상
    r"갑자기(?:어지럽|어지러|쓰러|말이어눌|말이안나|말을못|정신이|의식|숨|가슴|마비|힘이빠|눈앞이)",
    r"말이어눌|정신이혼미|혼미|식은땀|축처(?:졌|져)|(?:얼굴|입술|혀)이?(?:퉁퉁|팅팅|많이|심하게)부",
))

_PUNCT = re.compile(r"[\s​ .,!?~·\-_/\\()\[\]{}\"'`“”‘’…:;]+")


def normalize(text: str) -> str:
    """NFKC·소문자·공백·구두점 제거. 키워드와 거절 패턴이 이 글자 위에서 맞는다."""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", text or "").lower())


def detect_emergency(text: str) -> bool:
    """응급 키워드가 있으면 True. 부정문("호흡곤란은 없어요")도 안전 쪽으로 True다(오탐 허용, 미탐 금지)."""
    n = normalize(text)
    return any(k in n for k in EMERGENCY_KEYWORDS) or any(p.search(n) for p in EMERGENCY_PATTERNS)


# --------------------------------------------------------------------------- 범위 외 분류
# (이유 키, 정규화 글자 패턴). 앞의 것이 우선한다.
_SCOPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 입구 오탐 방지(plan-critic #1): "임신한 상태에서 …먹어도", "수유 중인데 …먹어도 괜찮", "…계속 먹어야 하는 사람인데 …"는
    # 임부·수유·상시 복용 금기 확인 질문이라 거절하면 조회가 막힌다. 그래서 상태·계속 조건은 '줄임·끊음' 동사나 정상·수치 맥락이 있을 때만 건다.
    ("ASSESS_STATE", re.compile(
        r"상태.*(?:줄|끊|중단|그만|멈|안먹|들여도)|"
        r"(?:줄|끊|중단|그만|안먹|들여도).*상태|먹어도(?:되는|괜찮은)상태|"
        r"(?:수치|혈압|혈당|검사|컨디션).*(?:끊|줄|그만|안먹).*(?:수준|되는|괜찮|할것|할수)|"
        r"(?:정상|괜찮).*(?:안먹|끊어도|그만|수준)|"
        r"(?:정상|수치|괜찮|좋아|나았|호전).*계속.*먹어야")),
    ("HIDE_FROM_DOCTOR", re.compile(
        r"(의사|병원|약사|주치의|담당의|선생님)[가-힣]{0,4}"
        r"(숨기|숨겨|숨길|숨기고|비밀로|말하지말|말안|말씀안|알리지말|알리지않|몰래|모르게)|"
        r"(숨겨|숨기고|비밀로|몰래|말씀안|알리지않).{0,6}(의사|약사|병원|선생님)|"
        r"(?:의사|약사|병원|선생님)한테(?:는)?(?:말안|알리|비밀로)|"
        r"(?:의사|약사|병원|선생님)께(?:는)?(?:말안|알리|말씀안)")),
    ("STOP_DOSE_CHANGE", re.compile(
        r"(약|복용|먹는것|먹는걸).{0,4}(끊|중단|그만|멈추|줄여|줄이|감량|늘려|늘리|절반|반으로|반만|건너뛰)|"
        r"(끊어도|끊을까|끊고싶|중단해도|중단할까|그만먹|먹지말까|안먹어도|줄여도|줄여서|감량|복용중지|복용을멈)|"
        r"(?:끊|중단|그만|줄|낮|서서히줄)(?:으라|어야|자고|세요|십시오)|"
        r"(?:주치의|담당의|담당선생님|의사(?:선생님)?|의료진|약사(?:님)?).*(?:끊|중단|그만|줄이|낮추|줄여|서서히|낮춰)")),
    ("PRESCRIPTION", re.compile(r"처방(?:해(?:줘|드려|드릴|드세요)|부탁|좀)|약을?(?:추천|골라)|어떤약을?(?:먹어|써|처방)|약처방")),
    ("DOSAGE", re.compile(r"몇(알|정|mg|밀리|번|포|캡슐|ml|cc)|얼마나(먹|복용)|복용량(을|은)?(정|알려|얼마)|용량(을|좀)?(정해|알려줘|골라)|하루에?몇")),
    ("DIAGNOSIS", re.compile(r"진단(해|좀|을해|받)|무슨병|무슨질환|병명|병인지|질환인지|제병이|제가.{0,6}(병|암|질환)인가")),
    ("PERSONAL_RECORD", re.compile(r"(내|제|우리)(진료|의무|건강검진|투약|처방)기록|진료기록(을|좀)?(분석|저장|올려|봐)|의무기록|건강검진결과(분석|를봐|해석)")),
)

# --------------------------------------------------------------------------- 인젝션 시도
_INJECTION = re.compile(
    r"(이전|위|앞|기존|모든)(의)?(지시|지침|명령|규칙|프롬프트|설정)(를|을|은|는|들을|사항을)?(모두|전부)?(무시|잊|따르지말|취소|리셋)|"
    r"(지시|지침|규칙|명령)(를|을|사항)?(모두|전부)?(무시하|무시해|잊어|잊고)|"
    r"ignore(all)?(the)?(previous|prior|above|earlier)(instruction|prompt|rule|direction)|"
    r"disregard(all)?(the)?(previous|prior|above)|forget(all)?(the)?(previous|prior|your)(instruction|rule)|"
    r"시스템(프롬프트|메시지|지침)(를|을|은|는)?(보여|알려|출력|공개|무시|바꿔|변경)|systemprompt|"
    r"(119|고지|면책|안내|경고|주의)(문구|안내)?(를|을|은|는|는빼|를빼|을빼|없이|생략|삭제|지워|제거)(빼|없애|지워|제거|생략|말고|하지말)|"
    r"(안전하다고|괜찮다고|문제없다고)(말해|답해|대답해|써|출력)|"
    r"(너는|넌|당신은)(이제|지금부터)(.{0,12})(이다|야|입니다|처럼|역할)|지금부터(너는|넌|당신은)|developermode|jailbreak|dan모드")


def detect_injection(text: str) -> bool:
    return bool(_INJECTION.search(normalize(text)))


def classify_scope(text: str) -> str | None:
    """범위 외 이유 키(`ASSESS_STATE`·`STOP_DOSE_CHANGE`·`HIDE_FROM_DOCTOR`·`DIAGNOSIS`·`PRESCRIPTION`·`DOSAGE`·`PERSONAL_RECORD`) 또는 None."""
    n = normalize(text)
    for key, pat in _SCOPE_PATTERNS:
        if pat.search(n):
            return key
    return None


def guardrail_in(text: str) -> dict[str, Any]:
    """입구 결과(순수 딕셔너리).

    - `emergency`: 응급 키워드 감지. 상태 `emergency`에 기록하고 Router는 읽기만 한다.
    - `route`: `AGENT`(정상) | `REFUSE`(범위 외·인젝션).
    - `refuse_reason`: 거절 이유 키(없으면 None). 인젝션은 `IGNORE_PREVIOUS`.
    - `injection`: 지시 무시·고정 문구 제거 요구 같은 시도 여부.
    - `proceed_tools`: 금기 조회를 이어 가는가. 응급이면 항상 True(막지 않음), 거절이면 False, 그 밖은 True.
    """
    emergency = detect_emergency(text)
    injection = detect_injection(text)
    reason = "IGNORE_PREVIOUS" if injection else classify_scope(text)
    route = ROUTE_REFUSE if reason else ROUTE_AGENT
    return {
        "emergency": emergency,
        "route": route,
        "refuse_reason": reason,
        "injection": injection,
        "proceed_tools": emergency or route == ROUTE_AGENT,
    }


# --------------------------------------------------------------------------- 상태 키 제한(H8)
def apply_tool_update(state: dict[str, Any], update: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """도구 결과가 상태에 쓸 수 있는 키는 `POST_WRITABLE_KEYS`뿐이다. 새 상태와 버려진 키 목록을 돌려준다(원본 불변)."""
    new = dict(state)
    dropped: list[str] = []
    for k, v in (update or {}).items():
        if k in POST_WRITABLE_KEYS:
            new[k] = v
        else:
            dropped.append(k)
    return new, dropped


def scan_tool_result_injection(items: list[dict[str, Any]]) -> bool:
    """도구 결과 안에 지시 무시 문자열이 있는지만 본다(기록용). 상태·고정 문구는 이 결과와 무관하다."""
    def walk(o: Any) -> bool:
        if isinstance(o, str):
            return detect_injection(o)
        if isinstance(o, dict):
            return any(walk(v) for v in o.values())
        if isinstance(o, (list, tuple)):
            return any(walk(v) for v in o)
        return False

    return walk(items)
