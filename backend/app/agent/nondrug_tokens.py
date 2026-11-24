"""약 이름이 아닌 토큰(시각·횟수·간격·수량 표현)을 가려내는 정규식 모음(AG-13-41·AG-13-44, 2026-11-24). 외부 호출 0, 사전은 보지 않는다.

- Router(`router._is_noise`)는 이 모듈의 정규식으로 후보 추출 단계에서 거르고, `identify_drug` 인자 검증(`tools.registry.invoke`)은 같은 정규식으로
  비약 토큰을 `ARG_SCHEMA`로 거절한다. 두 곳이 같은 꼴을 보게 한 파일이다(낱말·꼴을 한 곳에서만 더한다).
- **사전 이름과 일치하면 버리지 않는** 기존 보호 조건은 이 모듈이 아니라 호출하는 쪽이 건다(사전 의존성을 두지 않으려고).
  이 모듈의 정규식은 전체 일치(`^…$`)라 `타이레놀8시간이알서방정`·`8시간이알서방정` 같은 제품명 조각은 걸리지 않는다
  (사전에 "시간"이 든 제품이 26건 있다, 2026-11-24 rca-time-expression-search §5 C-1).
- 레거시 정규식 `NUM_UNIT_RE`·`UNIT_ONLY_RE`·`TIME_RE`는 `router.py`에 있던 것을 그대로 옮긴 것이다(스위치를 꺼도 이전 동작이 같도록 값을 바꾸지 않았다).
"""

from __future__ import annotations

import re

NUM_UNIT_RE = re.compile(
    r"^\d+(\.\d+)?\s*(살|세|개월|주|주차|일|시간|번|회|kg|키로|밀리그램|밀리그람|밀리리터|mg|mcg|μg|ug|ml|g|l|알|정|포|캡슐|병|방울|"
    r"등급|개|가지|명)$", re.IGNORECASE  # 숫자+분류사("3등급", "2개")는 약 이름이 아니다(AG-05 후속 2026-11-12)
)
UNIT_ONLY_RE = re.compile(r"^(밀리그램|밀리그람|밀리리터|mg|mcg|μg|ug|ml|g|l)$", re.IGNORECASE)  # 용량 단위만 떨어져 나온 토큰
# 시각 표현("15시", "3시반", "30분", "오후3시", "15:30")은 약 이름이 아니다(AG-21 ③, 2026-11-19: "15시에"가 NOT_FOUND 엔티티로 잡힌 사례).
# 숫자로 시작하거나 오전·오후 같은 때 낱말 + 숫자인 꼴만 본다(숫자로 시작하는 약 이름 조각은 없다. 조사는 `router._variants`가 뗀다).
TIME_RE = re.compile(r"^(?:오전|오후|새벽|아침|저녁|밤|낮)?\d{1,2}\s*(?:시반|시|분|초)$|^\d{1,2}:\d{2}(?::\d{2})?$")

# ----------------------------------------------------------------------------- 일반화(AG-13-41 A)
# "때 낱말 + 숫자 + 시·시간·분(+반·뒤·후·간격)"과 "하루·1일 + 수 + 번·회" 꼴. 낱말을 하나씩 더하지 않고 구조(때 낱말 · 수 · 단위 · 꼬리)로 본다.
_TIME_WORDS = "오전|오후|새벽|아침|저녁|밤|낮|점심|정오|자정|한낮|한밤|식후|식전|식간|취침전|취침"
_HANGUL_NUM = "한|두|세|네|다섯|여섯|일곱|여덟|아홉|열한|열두|열|스무"
_NUM = rf"(?:\d{{1,3}}|{_HANGUL_NUM})"
_TAIL = "뒤|후|전|간격|마다|이내|쯤|정도|동안"
_PARTICLE = "에는|에도|에|부터|까지|이|가|은|는|도|만"  # 도구 인자처럼 조사가 붙어 올 수 있는 경우(Router는 조사를 먼저 뗀다)

_TIME_COUNT_PARTS = (
    rf"(?:{_TIME_WORDS})?{_NUM}\s*(?:시간|시)(?:\s*(?:\d{{1,2}}\s*분|반))?(?:\s*(?:{_TAIL}))?",   # 점심12시, 4시간뒤, 네시간뒤, 12시30분, 9시간격, 두시간
    rf"(?:{_TIME_WORDS})?{_NUM}\s*분(?:\s*(?:{_TAIL}))?",                                           # 식후30분, 30분뒤
    rf"(?:{_TIME_WORDS}|식사)시간대?",                                                               # 점심시간
    rf"(?:하루|매일|1일|일일)(?:에)?\s*{_NUM}\s*(?:번|회)(?:씩)?",                                     # 하루3번, 하루세번, 1일3회
)
TIME_COUNT_RE = re.compile(r"^(?:" + "|".join(f"(?:{p})" for p in _TIME_COUNT_PARTS) + rf")(?:{_PARTICLE})?$")
_PURE_NUMBER_RE = re.compile(r"^[\d.,%/\-]+$")
# 도구 인자 검증에만 더하는 꼴(AG-13-44, H6): "점심때"처럼 Router는 NOT_FOUND 엔티티로 모델에 넘기는 때 낱말 + 때. Router의 잡음 규칙(위)은 건드리지 않는다
_TIME_WORD_WHEN_RE = re.compile(rf"^(?:{_TIME_WORDS}|식사)때(?:{_PARTICLE})?$")


def is_time_or_count_token(tok: str) -> bool:
    """시각·횟수·간격 표현만으로 된 토큰인가(일반화 규칙 `TIME_COUNT_RE`만, 레거시 정규식은 보지 않는다). 사전은 보지 않는다."""
    return bool(TIME_COUNT_RE.match(tok or ""))


def is_non_drug_token(text: str) -> bool:
    """도구 인자 약 이름 자리에 들어온 값이 시각·횟수·수량 표현뿐인 비약 토큰인가(AG-13-44 C-2). 공백은 무시하고 본다("점심 12시" → "점심12시").
    일반화 규칙·레거시 시각·수량 단위·단위만·숫자만이 모두 해당한다. 사전 이름과 일치하면 허용하는 보호는 호출하는 쪽이 건다."""
    tok = re.sub(r"\s+", "", text or "")
    if not tok:
        return False
    return bool(TIME_COUNT_RE.match(tok) or _TIME_WORD_WHEN_RE.match(tok) or TIME_RE.match(tok) or NUM_UNIT_RE.match(tok) or UNIT_ONLY_RE.match(tok) or _PURE_NUMBER_RE.match(tok))


# ----------------------------------------------------------------------------- 증상·상태 단어(AG-24 시나리오 D, 2026-11-24)
# "쓰러진", "정신을 잃고", "혼미", "졸음", "노딩(nodding)" 같은 몸 상태·증상 말은 약 이름이 아니다. 개발셋 낱말을 하나씩 넣지 않고 어간 + 짧은 어미·조사 꼴로 본다.
# 전체 일치(`^…$`)라 제품명 조각은 걸리지 않는다. **사전 이름과 일치하면 버리지 않는** 보호는 호출하는 쪽(`router._is_noise`)이 건다.
_SYMPTOM_STEMS = (
    "쓰러지|쓰러진|쓰러졌|쓰러져|쓰러짐|쓰러질|기절|의식|혼미|혼수|졸음|졸려|졸린|졸리|어지럼|어지러|환각|환청|경련|발작|노딩|nodding"
)
SYMPTOM_STATE_RE = re.compile(rf"^(?:{_SYMPTOM_STEMS})[가-힣]{{0,4}}$|^(?:정신|정신을|잃고|잃은|잃어|잃었|잃어서)$", re.IGNORECASE)


def is_symptom_state_token(tok: str) -> bool:
    """몸 상태·증상 낱말만으로 된 토큰인가(쓰러진·혼미한·졸음이·노딩 …). 사전은 보지 않는다(보호 조건은 호출하는 쪽)."""
    return bool(SYMPTOM_STATE_RE.match(re.sub(r"\s+", "", tok or "")))


# ----------------------------------------------------------------------------- 흔한 약어 별칭(AG-24 시나리오 D)
# 영문 약어 → (사전 조회에 쓸 이름 형태 목록, 후보 이름에 들어 있어야 하는 낱말). 사전 데이터 파일은 고치지 않고 코드 상수 표만 둔다.
# 이름 형태는 앞의 것부터 시도하고, 사전에 이름으로 맞는(정확·정규화·접두·중간) 첫 형태를 쓴다. 이름 일치가 없으면 BM25 1위 후보 이름에
# 낱말이 든 첫 형태를 쓴다(엉뚱한 후보를 보여 주지 않으려는 보호). 둘 다 아니면 별칭을 쓰지 않는다(원문 그대로, 보고만).
# 사전 빌더가 이미 별칭으로 둔 약어(APAP→아세트아미노펜, ASA→아스피린 등)는 사전 조회가 처리하므로 이 표에 넣지 않는다.
ABBREV_ALIASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "DXM": (("덱스트로메토르판", "dextromethorphan"), ("덱스트로메토르판", "dextromethorphan")),
}
_ASCII_ABBREV_RE = re.compile(r"^[A-Za-z]{2,6}$")


def abbrev_key(tok: str) -> str | None:
    """토큰이 별칭 표의 영문 약어(대소문자 무시)이면 표 키(대문자), 아니면 None."""
    t = (tok or "").strip()
    if _ASCII_ABBREV_RE.match(t) and t.upper() in ABBREV_ALIASES:
        return t.upper()
    return None
