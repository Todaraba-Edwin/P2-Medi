"""AG-06-02 LLM 답변 출력 스키마(구조화 출력, 자유 텍스트 표지 파싱 없음).

LLM은 `sentences[{text, evidence_ids[], claim_type}]`와 인용 `{evidence_id, start, end}`만 낸다.
`detail`·`citations[]`·`badges[]`는 코드 렌더러가 도구 결과 `items[]`로 만든다(AG-06-01).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ClaimType = Literal["fact", "conclusion", "guidance"]

# claim_type별 근거 ID 규칙. fact는 근거 ID가 1개 이상 있어야 하고(H1),
# conclusion(결론 요약)·guidance(확인 안내)는 근거 ID 없이도 허용한다(주어진 ID는 있으면 검사한다).
EVIDENCE_REQUIRED: dict[str, bool] = {"fact": True, "conclusion": False, "guidance": False}


def requires_evidence(claim_type: str) -> bool:
    return EVIDENCE_REQUIRED[claim_type]


class Citation(BaseModel):
    """인용 지정. 글자는 LLM이 쓰지 않고 코드가 근거 원문에서 `[start, end)`로 잘라 넣는다(H28)."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _range(self) -> Citation:
        if self.end <= self.start:
            raise ValueError("end는 start보다 커야 한다")
        return self


class Sentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_type: ClaimType
    citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _text(self) -> Sentence:
        if not self.text.strip():
            raise ValueError("text가 공백이다")
        if any(not e.strip() for e in self.evidence_ids):
            raise ValueError("빈 evidence_id가 있다")
        return self


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentences: list[Sentence] = Field(default_factory=list)


def parse_draft(raw: Any) -> tuple[AnswerDraft | None, str | None]:
    """LLM 구조화 출력(dict 또는 JSON 문자열)을 검증한다. 맞지 않으면 `(None, 오류 요약)`."""
    try:
        if isinstance(raw, (str, bytes)):
            return AnswerDraft.model_validate_json(raw), None
        return AnswerDraft.model_validate(raw), None
    except ValidationError as e:
        return None, f"SCHEMA_INVALID:{e.error_count()}"
