"""AG-02 도구 인자 스키마(Pydantic)와 공통 상수.

형식이 틀린 인자는 도구 본문을 실행하지 않고 `ARG_SCHEMA` 응답(이유·다음 행동·남은 호출 수)으로 막는다
(RFP-33-04, H21·H8, 하드 차단 RFP-33-02). 응답에는 틀린 값을 되풀이하지 않고 필드 이름과 오류 종류만 쓴다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

KIDS_CODE_RE = re.compile(r"^[0-9]{6}[A-Z]{3}$")  # KIDS 성분코드(9자리, 제형 포함)
DUR_CODE_RE = re.compile(r"^D[0-9]{6}$")           # 식약처 DUR API 성분코드
ITEM_SEQ_RE = re.compile(r"^[0-9]{9}$")            # 품목기준코드

MAX_NAME_LEN = 100
MAX_DRUGS = 8          # 약 8개 = 28쌍 상한(호출 제한, AG-02 §5 가정)
MAX_AGE = 130

# 쓸 수 있는 상태·키(PJ2-Agent-Harness.md 3.4절)
STATUS_BY_TOOL: dict[str, frozenset[str]] = {
    "identify_drug": frozenset({"FOUND", "UNIDENTIFIED"}),
    "check_contraindications": frozenset({"FOUND", "NOT_LISTED", "UNIDENTIFIED"}),
    "get_label_section": frozenset({"FOUND", "NO_EVIDENCE"}),
}
POST_WRITABLE_KEYS = frozenset({"evidence", "known_ids", "input_units", "events"})  # emergency·route·profile·confirmed_mentions는 못 쓴다

API_FLAGS = frozenset({"API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE"})
MISSING_REASONS = frozenset({"ABSENT", "FETCH_FAIL", "OUT_OF_SCOPE"})

# 새 꼬리표 제안(어휘 표 등록은 문서 몫)
FLAG_CODE_NOT_LINKED = "CODE_NOT_LINKED"   # 사전이 KIDS 코드를 붙이지 못함(BE-10-06 A)
FLAG_AMBIGUOUS_NAME = "AMBIGUOUS_NAME"     # 이름이 여러 약에 걸려 되묻기 필요(H11)
FLAG_REFERENCE_ONLY = "REFERENCE_ONLY"     # 다른 제형에서 목록에 있음, 이 제품 판정 아님(BE-10-08·09)

SectionName = Literal["효능", "용법용량", "사용법", "경고", "주의사항", "상호작용", "부작용"]


def _no_control(v: str) -> str:
    if any(unicodedata.category(c).startswith("C") for c in v):  # 제어·서식 문자(개행·탭 포함)
        raise ValueError("제어 문자가 있다")
    return v


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LEN)]


class IdentifyDrugArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name

    @field_validator("name")
    @classmethod
    def _name_ctl(cls, v: str) -> str:
        return _no_control(v)


class DrugArg(BaseModel):
    """조회할 약 하나. 이름이나 성분코드 중 하나는 있어야 한다. `item_seq`는 되묻기 뒤 후보를 고를 때 쓴다."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    item_seq: str | None = None
    ingredient_code: str | None = None  # KIDS 9자리(예 100501ATE) 또는 API `D######`

    @field_validator("name")
    @classmethod
    def _name_ctl(cls, v: str | None) -> str | None:
        return None if v is None else _no_control(v)

    @field_validator("item_seq")
    @classmethod
    def _seq(cls, v: str | None) -> str | None:
        if v is not None and not ITEM_SEQ_RE.match(v):
            raise ValueError("품목기준코드는 숫자 9자리")
        return v

    @field_validator("ingredient_code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and not (KIDS_CODE_RE.match(v) or DUR_CODE_RE.match(v)):
            raise ValueError("성분코드 형식 아님")
        return v

    @model_validator(mode="after")
    def _one(self) -> DrugArg:
        if not (self.name or self.item_seq or self.ingredient_code):
            raise ValueError("이름·품목기준코드·성분코드 중 하나가 필요하다")
        return self


class AgeArg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0, le=MAX_AGE)
    unit: Literal["주", "개월", "세"] = "세"


class CheckContraArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drugs: list[DrugArg] = Field(min_length=1, max_length=MAX_DRUGS)
    age: AgeArg | None = None
    pregnancy: bool = False
    include_cautions: bool = False


class GetLabelSectionArgs(BaseModel):
    """성분코드는 품목기준코드가 아니라 여기서 막힌다(H17: 성분 단위는 라벨이 없다)."""

    model_config = ConfigDict(extra="forbid")

    item_seq: str
    section: SectionName

    @field_validator("item_seq")
    @classmethod
    def _seq(cls, v: str) -> str:
        if not ITEM_SEQ_RE.match(v):
            raise ValueError("품목기준코드는 숫자 9자리")
        return v


def arg_schema_error(tool: str, exc: ValidationError, remaining_calls: int) -> dict[str, Any]:
    """`ARG_SCHEMA` 응답. 틀린 값 자체는 되풀이하지 않는다(비밀·제어 문자 반사 방지)."""
    problems = sorted({f"{'.'.join(str(p) for p in e['loc']) or '(전체)'}: {e['type']}" for e in exc.errors()})
    return {
        "items": [],
        "blocked": True,
        "error": {
            "code": "ARG_SCHEMA",
            "tool": tool,
            "reason": "인자 형식이 맞지 않아 도구를 실행하지 않았다: " + "; ".join(problems),
            "next_action": "인자 형식을 고쳐 다시 호출하거나, 약 이름이면 identify_drug로 먼저 찾는다",
            "remaining_calls": max(remaining_calls, 0),
        },
    }
