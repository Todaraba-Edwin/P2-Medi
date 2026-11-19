"""BE-06 `/chat` 요청 모델(`ChatRequest`).

- PRD-07-01 A: 서버는 대화 상태를 **저장·로그하지 않고** 요청에 실린 값만 쓴다. 대화 상태는 `context` 한 입력 묶음으로 받는다
  (추후 서버 임시 보관 등으로 바꿀 때 이 묶음만 갈아 끼운다).
- 칸 이름은 응답 스키마와 같은 snake_case다. 프런트 가정 이름(`age`·`pregnant`·`confirmedDrugs`)은 프런트 `buildChatRequest` 한 곳에서 옮긴다.
- 나이는 구간(`lower`~`upper`, 단위 `세`·`개월`·`주`)으로 받는다. 한 나이면 두 값이 같다. 연령대 프로필(FE-07-18)이 기준 나이에 걸리면
  판정 대신 나이 기준 값(원문)을 보인다는 규칙을 그래프가 이 구간으로 정한다(AG 몫). 단위는 `app.tools.lookup.Age`·`loaders._UNIT_DAYS`와 같다.
- 형식 오류(빈 질문·길이 초과·모르는 칸)는 422다(`app.api.chat`의 오류 본문 형식, 입력 값은 되돌려 주지 않는다).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QUESTION_MAX_CHARS = 1000  # 가정: 질문 한 개 길이 상한(글자). 근거 문서에 수치가 없어 정함(BE-06 §2 "과도한 길이")
CONFIRMED_DRUGS_MAX = 10  # 가정: 되묻기로 확인된 약 목록 상한
DRUG_NAME_MAX_CHARS = 100  # 가정: 약 이름 한 개 길이 상한
AGE_MAX_YEARS = 150  # 나이 상한(세 환산). 넘으면 형식 오류
AgeUnit = Literal["세", "개월", "주"]
_YEARS_PER_UNIT = {"세": 1.0, "개월": 1 / 12, "주": 7 / 365.25}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgeInput(_Strict):
    """먹는 사람의 나이 구간. 한 나이면 `lower == upper`."""

    lower: float = Field(ge=0)
    upper: float = Field(ge=0)
    unit: AgeUnit = "세"

    @model_validator(mode="after")
    def _range(self) -> AgeInput:
        if self.lower > self.upper:
            raise ValueError("lower는 upper보다 클 수 없다")
        if self.upper * _YEARS_PER_UNIT[self.unit] > AGE_MAX_YEARS:
            raise ValueError("나이가 상한을 넘는다")
        return self


class ConfirmedDrug(_Strict):
    """되묻기 등으로 사용자가 고른 약(이름과, 있으면 품목기준코드).

    `input_name`(선택, FE-09-05 A)은 그 약을 고른 되묻기 묶음의 이름(응답 `candidates[].input_name` 그대로)이다. 있으면 서버가 질문 속 그 이름의
    약에만 이 코드를 확정한다(묶음 후보가 겹쳐도 다른 묶음을 덮지 않는다). 없으면 이전 규칙(후보 집합 포함 + 나중 것) 그대로다."""

    name: str = Field(min_length=1, max_length=DRUG_NAME_MAX_CHARS)
    item_seq: str | None = Field(default=None, pattern=r"^\d{9}$")
    input_name: str | None = Field(default=None, min_length=1, max_length=DRUG_NAME_MAX_CHARS)

    @field_validator("name", "input_name")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("약 이름이 비어 있다")
        return v


class ConversationContext(_Strict):
    """같은 대화 안에서 이미 말한 값(한 입력 묶음, PRD-07-01 A). 서버는 저장·로그하지 않는다.

    - `confirmed_drugs`: **이번 질문의 되묻기 답**(같은 질문을 다시 보낼 때만 채운다, AG-21-02 A로 의미 축소). 서버가 바로 확정한다.
    - `prior_drugs`(AG-21-02 A): **이전 차례에서 고른 약**(모양은 `confirmed_drugs`와 같다). 확정에 쓰지 않고, 같은 이름이 다시 나오면
      그 약을 첫 후보로 둔 확인 되묻기에만 쓴다. 이벤트·로그에는 개수만 남는다.
    - `took_today`(AG-22-05 A): 용량주의 되묻기 답(예 `true` / 아니요 `false`, 답하지 않았으면 없음). 시각·양은 받지 않는다(RFP-21-03).
      저장·로그·이벤트에 남기지 않는다.
    """

    age: AgeInput | None = None
    pregnant: bool | None = None
    confirmed_drugs: list[ConfirmedDrug] = Field(default_factory=list, max_length=CONFIRMED_DRUGS_MAX)
    prior_drugs: list[ConfirmedDrug] = Field(default_factory=list, max_length=CONFIRMED_DRUGS_MAX)
    took_today: bool | None = Field(default=None, strict=True)  # JSON true/false만(문자열 "예"·숫자 1은 형식 오류 422)


class ChatRequest(_Strict):
    """`POST /chat` 본문."""

    question: str = Field(min_length=1, max_length=QUESTION_MAX_CHARS)
    context: ConversationContext = Field(default_factory=ConversationContext)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문이 비어 있다")
        return v
