"""복용 관련 질문 감지와 주의 3종 조회 규칙(AG-22, 순수 함수, LLM 호출 없음).

- `is_redose`: 재복용·추가 복용을 묻는 질문(AG-22-01 A). 응답에 승인 고정 한 줄 `REDOSE_NOTICE`가 붙는다(`finalize`).
- `is_intake`: 복용 관련 질문 = 재복용 ∨ "먹어도·복용해도·드셔도·먹여도·같이/함께 먹" 일반형(AG-22-06 A). 용량주의 조회와
  용량주의 되묻기(`dose_check`, AG-22-02 B·03 A)의 조건이다.
- `caution_kinds`: 주의 3종 조회 종류를 코드가 정한다(AG-22-04 A). 용량 = 복용 관련 질문, 노인 = 나이 ≥ 65, 수유부 = 수유 입력(지금
  입력 칸이 없어 항상 끔). LLM 도구 인자(`include_cautions`)는 없앴다(C-1 A).

"실수로 먹었어"·"먹었는데 배가 아파"처럼 이미 먹은 일을 서술만 하는 문장(응급 서술)은 복용 관련 질문이 아니다: 가부를 묻는 꼴이 함께
있어야 한다(C-2 A, AG-22-06 A 범위 그대로). 패턴 목록은 사용자 승인 대상이 아니라 시험(`test_ag22_intake.py`)으로 고정한다(AG-22 §5 가정).
결과는 bool만 상태에 쓰고 문장·일치 조각은 어디에도 남기지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# 가부를 묻는 꼴(먹어도 되는지)
_ASK = r"(?:먹어도|복용해도|드셔도|먹여도|먹으면|먹을\s*수|복용할\s*수)"
_REDOSE_RE = re.compile(
    r"(?:또|한\s*번\s*더|다시|추가로)\s*(?:먹|복용|드)"                                   # 또 먹어도, 한 번 더 먹어도, 다시 복용
    r"|(?:먹었는데|먹었고|먹었어도|드셨는데|복용했는데)[^?.!]{0,30}" + _ASK                 # 점심에 먹었는데 지금 먹어도
    + r"|\d+\s*시(?:간)?\s*(?:뒤|후|인데|쯤|지났)[^?.!]{0,20}" + _ASK                      # 15시인데 먹어도, 4시간 뒤에 먹어도
    + r"|(?:시간|분)\s*(?:뒤|후|지나)[^?.!]{0,20}" + _ASK                                  # 두 시간 뒤에 한 번 더 먹어도
)
_INTAKE_RE = re.compile(r"먹어도|복용해도|드셔도|먹여도|(?:같이|함께)\s*(?:먹|복용|드)")

ELDERLY_AGE_MIN = 65  # 노인 주의 조회 나이 하한(AG-22-04 A)
CAUTION_DOSE, CAUTION_LACTATION, CAUTION_ELDERLY = "dose", "lactation", "elderly"


def is_redose(text: str | None) -> bool:
    """재복용·추가 복용을 묻는 질문인가(AG-22-01 A)."""
    return bool(_REDOSE_RE.search(text or ""))


def is_intake(text: str | None) -> bool:
    """복용 관련 질문인가(AG-22-06 A: 재복용 ∪ 일반형)."""
    t = text or ""
    return is_redose(t) or bool(_INTAKE_RE.search(t))


def caution_kinds(state: Mapping[str, Any]) -> frozenset[str]:
    """주의 3종 중 이번 요청에서 조회할 종류(AG-22-04 A). 그래프 상태(`intake_question`·`profile`)만 읽는다."""
    out: set[str] = set()
    if state.get("intake_question"):
        out.add(CAUTION_DOSE)
    age = (state.get("profile") or {}).get("age_years")
    if isinstance(age, (int, float)) and age >= ELDERLY_AGE_MIN:
        out.add(CAUTION_ELDERLY)
    # 수유부(`CAUTION_LACTATION`): 수유 여부를 받는 입력 칸이 없어 조회하지 않는다(대상이 아니면 그리지 않음, AG-08-18 A)
    return frozenset(out)
