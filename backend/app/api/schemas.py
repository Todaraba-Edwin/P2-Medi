"""BE-06 응답 스키마 v1(`chat_response@v1`, Pydantic)과 `finalize` 출력 → API 응답 변환.

근거 문서: `P2-doc/PJ2-PRD.md` 15.1절(응답 필드), `tickets/backend/BE-06.md` §2(완료 조건)·§6(결정 BE-06-01~10),
`tickets/doc/PRD-12.md` §4.5(출처 순서)·§5(날짜 줄)·§6(데이터 계약), AG-08-03 B(자료별 기준일), FE-07-18(연령금기 나이 기준 값).
스트림 이벤트(`chat_event@v1`)는 `app.api.events`, 요청(`ChatRequest`)은 `app.api.request`, 라우트는 `app.api.chat`에 있다.

- `citations[]` = **출처 표 행**(1출처 = 1행): `publisher`(기관, 대그룹)·`dataset`(자료 약칭, 중그룹 = 근거 박스 표지의 약칭)·`dates[{label, value}]`
  ·`notice_nos`·`edition`·`pages`(BE-06-05 A: 고시 번호·판·쪽은 출처 행에 둔다). 날짜는 **한 날짜 = 한 항목**이고 라벨은 상수
  (`고시일`·`발간일`·`기준일`·`조회`, 날짜가 없으면 `날짜 없음`)다. 값은 `YYYY-MM-DD` 또는 `YYYY-MM`(월 단위, BE-06-08 A, 없는 날을 지어내지 않음)이며
  `조회`만 하루 단위(조회 시각에서 코드가 만든 한국 날짜)다. 시·분 필드는 없다(BE-06-07 B). 화면은 문자열을 조립하지 않는다.
- 순서는 코드가 정한다(PRD-12 §4.5): 판정에 쓴 자료가 있는 기관 먼저(동률이면 식약처 → 한국의약품안전관리원 → 건강보험심사평가원),
  같은 기관 안에서는 판정 자료 → 허가사항 근거 자료 → 그 밖.
- `findings[]`는 판정 줄이다. 제품 줄(`target="product"`)과 **쌍 줄**(`target="pair"`, `drugs` = 두 약, BE-06-01 A)을 따로 두고,
  배지(`badges[{kind, grade, source}]`)는 그 줄에 붙는다(병용 → 임부 → 연령, 등급 불일치는 파일 → 성분 API, PRD-15). 화면은 줄·배지를 조합·재정렬하지 않는다.
- 응급은 `end_reason` 값이 아니라 `emergency` 필드로만 표현한다(BE-06-02 A). 되묻기 후보는 `candidates[]`(BE-06-03 A).
  상단 배너(상한 도달·API 실패)는 기존 `notice` 한 칸이다(BE-06-06 A). 용법용량은 표 구조 없이 원문 인용 텍스트만(`detail[].rows`, BE-06-04 B).
- `detail[]`은 도구 항목을 코드가 렌더한 것(AG-06 `renderer`)이고 LLM 문장(`LLM_SUMMARY`)은 없다. `summary`만 LLM 문장(검증 통과분) 또는 코드 문구다.
- 내부 필드(`events`·`warnings`·`text`)는 응답에 싣지 않는다. 금지 칸(복용 지시·용량 숫자)의 **내용** 검사는 Validator(AG-07) 몫이고 여기서는 형식만 본다.
- 고정 문구 불변식(코드 강제): `fixed_notice`는 1줄 이상·빈 줄 없음·`FIXED_NOTICE` 포함, `disclaimer`는 `DISCLAIMER` 그대로,
  `emergency`는 `EMERGENCY_119`·`EMERGENCY_119_TEL` 그대로, `notice`는 상수 목록(`NOTICE_TEXTS`)에 있는 값만.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent import fixed_phrases as fp
from app.agent.finalize import _missing_text as _detail_missing_text  # finalize 항목 문구와 같은 규칙(사유 → 상수 문구)
from app.tools.provenance import (
    CITATION_DATE_LABELS,
    DATASET_LABELS,
    DATASET_PUBLISHER,
    PUBLISHER,
    SOURCE_KIND_PREFIX,
    display_as_of,
)

SCHEMA_VERSION = "chat_response@v1"

# ---------------------------------------------------------------- 날짜 라벨(정의는 `provenance.CITATION_DATE_LABELS` 한 곳, PRD-12 §5.1)
DATE_LABEL_NOTICE = CITATION_DATE_LABELS["notice"]
DATE_LABEL_PUBLISHED = CITATION_DATE_LABELS["published"]  # BE-06-08 A
DATE_LABEL_AS_OF = CITATION_DATE_LABELS["as_of"]
DATE_LABEL_QUERIED = CITATION_DATE_LABELS["queried"]
DATE_LABEL_NONE = CITATION_DATE_LABELS["none"]  # PRD-12 §5.6(가정): 날짜가 없는 자료도 칸을 비우지 않는다
DATE_LINE_LABELS: tuple[str, ...] = (DATE_LABEL_NOTICE, DATE_LABEL_PUBLISHED, DATE_LABEL_AS_OF, DATE_LABEL_QUERIED, DATE_LABEL_NONE)
# 월 단위(`YYYY-MM`) 값을 허용하지 않는 라벨: 조회는 조회 시각(타임스탬프)에서 만들므로 항상 하루 단위다
DAY_ONLY_LABELS = frozenset({DATE_LABEL_QUERIED})
_LABEL_RANK = {DATE_LABEL_NOTICE: 0, DATE_LABEL_PUBLISHED: 1, DATE_LABEL_AS_OF: 2, DATE_LABEL_QUERIED: 3}

KST = ZoneInfo("Asia/Seoul")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# 기관 기본 순서(PRD-12 §4.5.1 동률 규칙, PRD-11 §5.1 표 순서)
PUBLISHER_ORDER: tuple[str, ...] = (PUBLISHER["mfds"], PUBLISHER["kids"], PUBLISHER["hira"])
OFFICIAL_PUBLISHERS = frozenset(PUBLISHER_ORDER)
# 같은 기관 안 자료 순서: 판정 자료 → 허가사항 근거 자료(PRD-12 §4.5.2)
JUDGE_DATASETS: tuple[str, ...] = ("dur_ingr", "contra_pair", "pregnancy", "age", "dose", "lactation", "elderly", "dup_ingredient")
LABEL_DATASETS: tuple[str, ...] = ("eyak", "prmsn", "identify")
_JUDGED_STATUS = ("FOUND", "NOT_LISTED")
# 쌍(A × B) 판정 종류(BE-06-01 A). 이 종류의 항목은 제품 줄이 아니라 쌍 줄이다
PAIR_KINDS: tuple[str, ...] = ("contra_pair",)
# 상단 배너(`notice`)에 나갈 수 있는 값(BE-06-06 A). API 실패 배너는 0-E 2번 승인(2026-11-12)
NOTICE_TEXTS: tuple[str, ...] = (fp.LIMIT_REACHED, fp.NOTICE_API_FAIL)
# 허가사항 근거(허가정보 원문) 자료 키: 한 줄 설명(`label_help`)을 붙인다(BE-06-15 A)
LABEL_HELP_DATASETS: tuple[str, ...] = ("prmsn",)
DOSE_SECTION = "용법용량"  # 이 항목의 원문 인용 아래에 인용 고지(`quote_notice`)를 둔다(UI-611)
_EASY_TEXT_MISSING_TAIL = fp.EASY_TEXT_MISSING.split("{drug}", 1)[1]

Route = Literal["AGENT", "REFUSE"]
EndReason = Literal["NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"]  # 응급 값 없음(BE-06-02 A)
SourceKind = Literal["API_DIRECT", "FILE", "CORPUS_QUOTE"]
Bucket = Literal["found", "not_listed", "identified", "unconfirmed"]
Target = Literal["product", "pair"]
Grade = Literal["1", "2", "M"]
GradeMissingReason = Literal["FETCH_FAIL", "OUT_OF_SCOPE"]  # 등급 정의는 청크 ID 조회라 SEARCH_MISS가 없다(PRD-15-03)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _valid_date_value(v: str, *, allow_month: bool) -> bool:
    try:
        if _DATE_RE.match(v):
            date.fromisoformat(v)
            return True
        if allow_month and _MONTH_RE.match(v):
            return 1 <= int(v[5:7]) <= 12
    except ValueError:
        return False
    return False


# ---------------------------------------------------------------- 모델
class DateLine(_Strict):
    """날짜 한 줄(한 날짜 = 한 항목). `날짜 없음`만 `value`가 None이다. 값은 `YYYY-MM-DD` 또는 `YYYY-MM`(조회 제외)."""

    label: str
    value: str | None

    @model_validator(mode="after")
    def _check(self) -> DateLine:
        if self.label not in DATE_LINE_LABELS:
            raise ValueError("날짜 라벨은 상수 목록(고시일·발간일·기준일·조회·날짜 없음)에 있어야 한다")
        if self.label == DATE_LABEL_NONE:
            if self.value is not None:
                raise ValueError("'날짜 없음' 줄은 value가 없어야 한다")
        elif not (isinstance(self.value, str) and _valid_date_value(self.value, allow_month=self.label not in DAY_ONLY_LABELS)):
            raise ValueError(f"{self.label} 값은 YYYY-MM-DD" + ("" if self.label in DAY_ONLY_LABELS else " 또는 YYYY-MM") + "여야 한다")
        return self


class Citation(_Strict):
    """출처 표 한 행(PRD-11-02·PRD-12 §6). `publisher`는 공식 기관 이름만(서비스 이름 금지, PRD-14). 고시 번호·판·쪽은 이 행에 둔다(BE-06-05 A)."""

    publisher: str
    dataset: str
    dates: list[DateLine] = Field(min_length=1)
    source_kind: SourceKind | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    notice_nos: list[str] = Field(default_factory=list)  # 고시 번호(원문 그대로, 나온 순서·중복 제거)
    edition: str | None = None  # 판(예: 발간물의 연도판). 원문 값이 없으면 None
    pages: list[str] = Field(default_factory=list)  # 쪽(원문 표기 그대로)

    @field_validator("publisher")
    @classmethod
    def _official(cls, v: str) -> str:
        if v not in OFFICIAL_PUBLISHERS:
            raise ValueError("publisher는 공식 기관 이름이어야 한다")
        return v


class Quote(_Strict):
    start: int
    end: int
    text: str


class SentenceRef(_Strict):
    """요약 문장이 인용한 근거(문장 번호 ↔ 근거 ID, 코드가 원문에서 자른 인용)."""

    evidence_id: str
    sentence_index: int
    row_key: str | None = None
    quotes: list[Quote] = Field(default_factory=list)


class DetailItem(_Strict):
    """근거 상세 한 박스(AG-06 `renderer` 결과에 자료 약칭·기관·날짜 줄을 더한 것). LLM 문장 없음.

    원문 인용(허가사항 용법용량 포함)은 `rows[]`의 원문 텍스트 칸 그대로이며 표 구조(`dose_table` 등)는 두지 않는다(BE-06-04 B).
    """

    evidence_id: str | None
    kind: str | None
    status: str | None
    source_kind: SourceKind | None
    dataset_key: str | None
    dataset: str | None
    publisher: str | None
    dates: list[DateLine]
    drug_name: str | None = None  # 약 이름(한 약의 근거일 때). 쌍 근거는 `drugs`
    section: str | None = None  # 항목명(상호작용·사용법 등)
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    drugs: list[str] | None = None
    item_seq: str | None = None
    label_source: str | None = None
    missing_reason: str | None = None
    missing_text: str | None = None  # `missing_reason`을 코드 상수로 렌더한 문구(PRD-11-02)
    # 서버 상수 글자 칸(화면은 받은 글자를 그대로 그린다)
    source_kind_label: str | None = None  # 출처 종류 글자 `공식 파일` 등(BE-06-14 A, `provenance.SOURCE_KIND_PREFIX`)
    label_help: str | None = None  # 허가사항 한 줄 설명(BE-06-15 A, `LABEL_ONE_LINE`). 허가정보 원문 근거에만
    easy_text_missing_line: str | None = None  # 전문의약품 안내 줄(BE-06-15 A, `EASY_TEXT_MISSING`). 그 꼬리표가 있을 때만
    quote_notice: str | None = None  # 용법용량 원문 인용 고지(UI-611, `DOSE_QUOTE_NOTICE`). 인용 바로 아래

    @model_validator(mode="after")
    def _missing_pair(self) -> DetailItem:
        if self.missing_text is not None and self.missing_reason is None:
            raise ValueError("missing_text는 missing_reason이 있을 때만 둔다")
        expected = SOURCE_KIND_PREFIX.get(self.source_kind or "")
        if self.source_kind_label is None:
            self.source_kind_label = expected  # 출처 종류가 있으면 글자는 항상 서버가 채운다
        elif self.source_kind_label != expected:
            raise ValueError("source_kind_label은 출처 종류의 상수 글자(SOURCE_KIND_PREFIX) 그대로여야 한다")
        if self.label_help not in (None, fp.LABEL_ONE_LINE):
            raise ValueError("label_help는 상수 LABEL_ONE_LINE 그대로여야 한다")
        if self.quote_notice not in (None, fp.DOSE_QUOTE_NOTICE):
            raise ValueError("quote_notice는 상수 DOSE_QUOTE_NOTICE 그대로여야 한다")
        if self.easy_text_missing_line is not None and not (
                "EASY_TEXT_MISSING" in self.flags and self.easy_text_missing_line.endswith(_EASY_TEXT_MISSING_TAIL)):
            raise ValueError("easy_text_missing_line은 그 꼬리표가 있을 때 상수 EASY_TEXT_MISSING으로만 만든다")
        return self


class Ingredient(_Strict):
    """제품 줄의 성분 하나(PRD-09-05). 성분명으로만 식별한 약은 그 성분 하나만 담는다."""

    code: str | None = None  # 성분코드(원문)
    name: str  # 표시명
    contra_kinds: list[str] = Field(default_factory=list)  # 이 성분이 걸린 금기 종류 키(`BADGE_ORDER`)
    dup: bool = False  # 같은 성분 중복 여부
    # 상태 글자(BE-06-13 A): `병용금기 원인`·`금기 원인`·`중복` 서버 상수. `contra_kinds`·`dup`에서 코드가 정하고 화면은 그대로 그린다
    state_labels: list[str] = Field(default_factory=list)
    code_missing_text: str | None = None  # 성분코드 미확보 안내(UI-021, `INGR_CODE_MISSING_TEXT`). 코드가 없을 때만

    @model_validator(mode="after")
    def _labels(self) -> Ingredient:
        expected = fp.ingredient_state_labels(self.contra_kinds, self.dup)
        if not self.state_labels:
            self.state_labels = expected
        elif self.state_labels != expected:
            raise ValueError("state_labels는 contra_kinds·dup에서 정한 서버 상수 글자 그대로여야 한다")
        if self.code_missing_text is not None and (
                self.code is not None or self.code_missing_text not in fp.INGR_CODE_MISSING_TEXT.values()):
            raise ValueError("code_missing_text는 성분코드가 없을 때 상수 INGR_CODE_MISSING_TEXT의 값만 쓴다")
        return self


class Badge(_Strict):
    """판정 줄의 배지 하나(PRD-15-01·02). `text`는 AG-08 상수 문구, `source`는 등급 불일치일 때만(파일 → 성분 API)."""

    kind: str
    grade: Grade | None = None
    source: SourceKind | None = None
    text: str = Field(min_length=1)
    evidence_id: str | None = None
    note: str | None = None


class Searched(_Strict):
    dataset: str | None
    count: int | None = Field(default=None, ge=0)


def _badge_rank(b: Badge) -> tuple[int, int]:
    k = fp.BADGE_ORDER.index(b.kind) if b.kind in fp.BADGE_ORDER else len(fp.BADGE_ORDER)
    s = fp.BADGE_TAIL_ORDER.index(b.source) if b.source in fp.BADGE_TAIL_ORDER else len(fp.BADGE_TAIL_ORDER)
    return k, s


class Finding(_Strict):
    """판정 줄(`finalize.entries` 한 항목). 제품 줄 또는 쌍 줄(BE-06-01 A). 문구는 코드 상수."""

    target: Target = "product"
    bucket: Bucket
    evidence_id: str | None
    kind: str | None
    drug: str  # 줄 머리 표시(코드가 만든 값)
    drugs: list[str] = Field(default_factory=list)  # 제품 줄은 그 약 하나(모르면 빈 목록), 쌍 줄은 두 약
    text: str
    badges: list[Badge] = Field(default_factory=list)
    ingredients: list[Ingredient] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_label: str | None = None
    unresolved: bool = False
    grades: list[str] = Field(default_factory=list)
    notice_nos: list[str] = Field(default_factory=list)
    note: str | None = None
    # 미식별(PRD-14-01·02·04)
    input_name: str | None = None
    searched: list[Searched] = Field(default_factory=list)
    retried: bool | None = None
    why: str | None = None
    next: str | None = None
    retried_line: str | None = None
    reference_line: str | None = None
    # 연령금기 나이 기준 값(FE-07-18): 원문 값 그대로(예: "만 12세 미만"). 나이를 특정할 수 없을 때 판정 대신 보이는 정보다
    age_criteria: list[str] = Field(default_factory=list)
    age_info_line: str | None = None  # 위 정보 줄의 안내 문구(상수 `AGE_INFO_LINE`, 0-E 3번 승인). 나이 기준 값이 있을 때만
    sub_line: str | None = None  # 표지 아래 보조줄(코드가 만든 값: 식별된 약의 성분 이름, 근거 없음 카드의 `UNIDENTIFIED_SUB_LINE`)

    @model_validator(mode="after")
    def _check(self) -> Finding:
        if self.target == "pair" and len(self.drugs) != 2:
            raise ValueError("쌍 줄은 drugs에 두 약을 담는다")
        if self.badges and self.bucket != "found":
            raise ValueError("배지는 금기 발견 줄에만 붙는다")
        ranks = [_badge_rank(b) for b in self.badges]
        if ranks != sorted(ranks):
            raise ValueError("배지 순서는 병용 → 임부 → 연령, 등급 불일치는 파일 → 성분 API여야 한다")
        if self.age_info_line is not None and (self.age_info_line != fp.AGE_INFO_LINE or not self.age_criteria):
            raise ValueError("age_info_line은 상수 AGE_INFO_LINE 그대로이고 나이 기준 값(age_criteria)이 있을 때만 둔다")
        return self


class Candidate(_Strict):
    """되묻기 후보 하나(BE-06-03 A, `end_reason == CLARIFY`일 때만). 이름만 보이고 먹어도 되는지는 말하지 않는다."""

    input_name: str  # 되묻는 입력(사용자가 적은 약 이름)
    name: str
    item_seq: str | None = None
    entp_name: str | None = None
    prescription: str | None = None
    matched_by: str | None = None


class Emergency(_Strict):
    """119 안내(BE-06-02 A: `end_reason`과 별개 신호). 문구·전화 링크는 상수 그대로다."""

    text: str
    tel: str
    wide_text: str = fp.EMERGENCY_119_WIDE  # 넓은 폭에서만 보이는 보조 문장(FE-07-15 A). 연락처가 아니라 방법 안내

    @model_validator(mode="after")
    def _const(self) -> Emergency:
        if self.text != fp.EMERGENCY_119 or self.tel != fp.EMERGENCY_119_TEL or self.wide_text != fp.EMERGENCY_119_WIDE:
            raise ValueError("emergency는 상수 EMERGENCY_119·EMERGENCY_119_TEL·EMERGENCY_119_WIDE 그대로여야 한다")
        return self


class GradeDef(_Strict):
    """등급 정의 블록 하나(BE-06-16 A, PRD-09-04·PRD-15-03). 원문(`text`)과 미확보 사유는 둘 중 하나만 있다.

    제목·미확보 문구는 상수이고 원문·출처 줄은 코드가 청크에서 읽은 글자 그대로다. 원문이 없으면 출처 줄도 없다.
    """

    grade: Grade
    title: str
    text: str | None = None
    source: str | None = None
    missing_reason: GradeMissingReason | None = None
    missing_text: str | None = None

    @model_validator(mode="after")
    def _check(self) -> GradeDef:
        if self.title != fp.GRADE_DEF_TITLE.format(grade=self.grade):
            raise ValueError("등급 정의 블록 제목은 상수 GRADE_DEF_TITLE 그대로여야 한다")
        if (self.text is None) == (self.missing_reason is None):
            raise ValueError("등급 정의 블록은 원문과 미확보 사유 중 하나만 가진다")
        if self.missing_reason is not None:
            if self.source is not None:
                raise ValueError("원문이 없는 등급 정의 블록에는 출처 줄을 두지 않는다")
            if self.missing_text != fp.GRADE_DEF_MISSING_TEXT[self.missing_reason].format(grade=self.grade):
                raise ValueError("등급 정의 미확보 문구는 상수 GRADE_DEF_MISSING_TEXT 그대로여야 한다")
        elif self.missing_text is not None or not (self.text or "").strip():
            raise ValueError("원문이 있는 등급 정의 블록은 원문이 비지 않고 미확보 문구가 없다")
        return self


class NameCorrection(_Strict):
    """오탈자 보정 고지 한 줄(AG-10-02 A). 질문에 적힌 이름 조각(`input`)을 비슷한 사전 이름(`name`) 하나로 보고 확인했다는 표시다.

    `text`는 상수 `TYPO_CORRECTED_LINE`에 두 이름을 넣은 문장 그대로다(화면은 문장을 조립하지 않는다). 판정이 아니다.
    """

    input: str = Field(min_length=1)
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> NameCorrection:
        if self.text != fp.TYPO_CORRECTED_LINE.format(input=self.input, name=self.name):
            raise ValueError("name_corrections[].text는 상수 TYPO_CORRECTED_LINE에 input·name을 넣은 문장 그대로여야 한다")
        return self


class ChatResponse(_Strict):
    """`/chat` 최종 응답(`chat_response@v1`). 스트림에서는 `answer` 이벤트의 `response`로 간다."""

    schema_version: Literal["chat_response@v1"] = SCHEMA_VERSION
    route: Route
    end_reason: EndReason | None = None
    emergency: Emergency | None = None
    notice: str | None = None  # 상단 배너(상한 도달·API 실패), BE-06-06 A
    # 오탈자 보정 고지(AG-10-02 A, 2026-11-17). 보정으로 확정한 약이 있을 때만 차고, 요약보다 먼저 보인다. 기본 빈 목록이라
    # 기존 응답과 호환된다(칸 추가라 `chat_response@v1` 유지: `grade_defs`·`not_checked_lines`를 더할 때와 같은 방식)
    name_corrections: list[NameCorrection] = Field(default_factory=list)
    summary: str | None
    findings: list[Finding] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    candidates_line: str | None = None  # 되묻기 카드 안내(상수 `CLARIFY_PICK_LINE`). 후보가 있을 때만, 있으면 항상
    not_checked_lines: list[str] = Field(default_factory=list)  # 정보가 없어 확인하지 못한 종류의 줄(상수 `NOT_CHECKED_LINES`, FE-07-16 B)
    detail: list[DetailItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    sentence_refs: list[SentenceRef] = Field(default_factory=list)
    grade_def_missing: list[str] = Field(default_factory=list)
    grade_defs: list[GradeDef] = Field(default_factory=list)  # 등급 정의 블록 구조(BE-06-16 A). 위 줄 목록은 그대로 둔다
    pharmacist_advice: list[str] = Field(default_factory=list)  # 미확보 항목이 있으면 비지 않는다(BE-06-17 A)
    fixed_notice: list[str] = Field(min_length=1)  # 줄 목록: (미확보가 있으면) 약사 확인 권고 → 고정 문구
    disclaimer: str = Field(min_length=1)

    @field_validator("fixed_notice")
    @classmethod
    def _non_blank(cls, v: list[str]) -> list[str]:
        if not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("fixed_notice 줄은 비어 있을 수 없다")
        if fp.FIXED_NOTICE not in v:
            raise ValueError("fixed_notice에는 고정 문구(FIXED_NOTICE)가 있어야 한다")
        return v

    @model_validator(mode="after")
    def _check(self) -> ChatResponse:
        if self.disclaimer != fp.DISCLAIMER:
            raise ValueError("disclaimer는 상수 DISCLAIMER 그대로여야 한다")
        if self.notice is not None and self.notice not in NOTICE_TEXTS:
            raise ValueError("notice는 상수 목록(NOTICE_TEXTS)의 값만 쓴다")
        if self.candidates and self.end_reason != "CLARIFY":
            raise ValueError("candidates는 되묻기(CLARIFY) 응답에만 둔다")
        if self.name_corrections and self.end_reason == "CLARIFY":
            raise ValueError("name_corrections는 조회 결과를 보이는 응답에만 둔다(되묻기에는 없다)")
        if self.candidates:
            if self.candidates_line is None:
                self.candidates_line = fp.CLARIFY_PICK_LINE
            elif self.candidates_line != fp.CLARIFY_PICK_LINE:
                raise ValueError("candidates_line은 상수 CLARIFY_PICK_LINE 그대로여야 한다")
        elif self.candidates_line is not None:
            raise ValueError("candidates_line은 후보가 있을 때만 둔다")
        if any(x not in fp.NOT_CHECKED_LINES.values() for x in self.not_checked_lines):
            raise ValueError("not_checked_lines는 상수 NOT_CHECKED_LINES의 값만 쓴다")
        missing = (any(f.unresolved for f in self.findings) or any(d.missing_reason for d in self.detail)
                   or bool(self.grade_def_missing) or any(g.missing_reason for g in self.grade_defs))
        if missing and not any(isinstance(x, str) and x.strip() for x in self.pharmacist_advice):
            raise ValueError("미확보 항목이 있으면 pharmacist_advice(약사 확인 권고)가 비어 있을 수 없다")  # BE-06-17 A
        return self


# ---------------------------------------------------------------- 변환
def _iso_date(v: Any) -> str | None:
    """원문 날짜 → `YYYY-MM-DD` 또는 `YYYY-MM`(월 단위 원문은 월 단위 그대로, 없는 날을 붙이지 않는다). 해석할 수 없으면 None."""
    if isinstance(v, str):
        s = v.strip()
        if _DATE_RE.match(s[:10]) and (len(s) == 10 or s[10] in "T "):
            return s[:10]
        if re.fullmatch(r"\d{8}", s):
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if _MONTH_RE.match(s):
            return s
    return None


def queried_date_kst(v: Any) -> str | None:
    """조회 시각(UTC ISO 8601, `Z` 또는 오프셋) → 한국 날짜 `YYYY-MM-DD`. 해석할 수 없으면 None(지어내지 않는다)."""
    if not isinstance(v, str) or not v.strip() or v == "unknown":
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).date().isoformat()


def date_lines(d: dict[str, Any]) -> list[DateLine]:
    """`renderer` detail 항목 → 날짜 줄. 순서: 고시일(행마다, 중복 제거·오름차순) → 기준일 → 조회. 하나도 없으면 `날짜 없음` 한 줄."""
    notices = sorted({x for x in (_iso_date(r.get("notice_date")) for r in d.get("rows") or [] if isinstance(r, dict)) if x})
    out = [DateLine(label=DATE_LABEL_NOTICE, value=x) for x in notices]
    as_of = _iso_date(display_as_of(d.get("dataset_key"), d.get("as_of")))  # 월 단위 자료는 YYYY-MM(BE-16-11 A, 도구에서 이미 잘렸어도 같은 값)
    if as_of:
        out.append(DateLine(label=DATE_LABEL_AS_OF, value=as_of))
    q = queried_date_kst(d.get("queried_at"))
    if q:
        out.append(DateLine(label=DATE_LABEL_QUERIED, value=q))
    return out or [DateLine(label=DATE_LABEL_NONE, value=None)]


def _publisher_and_dataset(d: dict[str, Any]) -> tuple[str | None, str | None]:
    key = d.get("dataset_key")
    if key in DATASET_LABELS and key in DATASET_PUBLISHER:
        return PUBLISHER[DATASET_PUBLISHER[key]], DATASET_LABELS[key]
    src = d.get("publisher")  # 자료 키가 없는 근거(예: 고시 조문 청크): 출처 문자열에 공식 기관 이름이 들어 있을 때만 쓴다
    if isinstance(src, str):
        pub = next((p for p in PUBLISHER_ORDER if src.startswith(p)), None)
        if pub:
            return pub, src
    return None, None


def _detail_item(d: dict[str, Any]) -> DetailItem:
    pub, ds = _publisher_and_dataset(d)
    sk = d.get("source_kind") if d.get("source_kind") in ("API_DIRECT", "FILE", "CORPUS_QUOTE") else None
    drugs = [str(x) for x in d["drugs"]] if isinstance(d.get("drugs"), list) else None
    reason = d.get("missing_reason")
    flags = list(d.get("flags") or [])
    name = drugs[0] if drugs and len(drugs) == 1 else (str(d["name"]) if d.get("name") else None)
    return DetailItem(
        evidence_id=d.get("evidence_id"), kind=d.get("kind"), status=d.get("status"), source_kind=sk, dataset_key=d.get("dataset_key"),
        dataset=ds, publisher=pub, dates=date_lines(d) if sk else [DateLine(label=DATE_LABEL_NONE, value=None)],
        drug_name=name, section=d.get("section"),
        flags=flags, notes=[str(x) for x in d.get("notes") or []], rows=[dict(r) for r in d.get("rows") or []],
        drugs=drugs, item_seq=d.get("item_seq"), label_source=d.get("label_source"),
        missing_reason=reason, missing_text=_detail_missing_text(d) if reason else None,
        label_help=fp.LABEL_ONE_LINE if sk and d.get("dataset_key") in LABEL_HELP_DATASETS else None,
        easy_text_missing_line=fp.EASY_TEXT_MISSING.format(drug=name) if name and "EASY_TEXT_MISSING" in flags else None,
        quote_notice=fp.DOSE_QUOTE_NOTICE if d.get("section") == DOSE_SECTION and d.get("rows") else None,
    )


def build_citations(detail: list[DetailItem]) -> list[Citation]:
    """출처 표 행을 만든다. 출처가 있는 근거(`source_kind`·공식 기관·자료 약칭이 모두 있음)만, (기관, 자료)마다 한 행, 날짜 줄은 합집합."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    judged_pubs: set[str] = set()
    for d in detail:
        if not (d.source_kind and d.publisher and d.dataset):
            continue
        key = (d.publisher, d.dataset)
        r = rows.setdefault(key, {"publisher": d.publisher, "dataset": d.dataset, "dates": [], "source_kind": d.source_kind,
                                  "evidence_ids": [], "notice_nos": [], "dataset_key": d.dataset_key, "judged": False})
        for line in d.dates:
            if line.label == DATE_LABEL_NONE:
                continue
            if all((x.label, x.value) != (line.label, line.value) for x in r["dates"]):
                r["dates"].append(line)
        if d.evidence_id and d.evidence_id not in r["evidence_ids"]:
            r["evidence_ids"].append(d.evidence_id)
        for row in d.rows:
            no = row.get("notice_no")
            if isinstance(no, str) and no.strip() and no.strip() not in r["notice_nos"]:
                r["notice_nos"].append(no.strip())
        if d.dataset_key in JUDGE_DATASETS and d.status in _JUDGED_STATUS:
            r["judged"] = True
            judged_pubs.add(d.publisher)

    def ds_rank(k: str | None) -> int:
        if k in JUDGE_DATASETS:
            return JUDGE_DATASETS.index(k)
        if k in LABEL_DATASETS:
            return len(JUDGE_DATASETS) + LABEL_DATASETS.index(k)
        return len(JUDGE_DATASETS) + len(LABEL_DATASETS)

    def order(r: dict[str, Any]) -> tuple[int, int, int]:
        pub = r["publisher"]
        return (0 if pub in judged_pubs else 1, PUBLISHER_ORDER.index(pub), ds_rank(r["dataset_key"]))

    out: list[Citation] = []
    for r in sorted(rows.values(), key=order):  # 안정 정렬: 같은 순위는 근거가 나온 순서
        dates = sorted(r["dates"], key=lambda x: (_LABEL_RANK[x.label], x.value or ""))
        out.append(Citation(publisher=r["publisher"], dataset=r["dataset"], dates=dates or [DateLine(label=DATE_LABEL_NONE, value=None)],
                            source_kind=r["source_kind"], evidence_ids=r["evidence_ids"], notice_nos=r["notice_nos"]))
    return out


def _badge(b: dict[str, Any]) -> Badge:
    tail = b.get("source_tail_key")  # finalize가 등급 불일치일 때만 단다(파일 → 성분 API)
    return Badge(kind=b["kind"], grade=b.get("grade"), source=tail if tail in fp.BADGE_TAIL_ORDER else None, text=b["text"],
                 evidence_id=b.get("evidence_id"), note=b.get("note"))


_FINDING_PASS = ("bucket", "evidence_id", "kind", "drug", "text", "notes", "source_label", "unresolved", "grades", "notice_nos", "note",
                 "input_name", "why", "next", "retried_line", "reference_line", "sub_line", "age_criteria", "age_info_line")


def _finding(e: dict[str, Any], detail_by_id: dict[str, DetailItem], badges_by_id: dict[str, list[Badge]]) -> Finding:
    d = detail_by_id.get(e.get("evidence_id") or "")
    names = list(d.drugs) if d and d.drugs else []
    is_pair = e.get("kind") in PAIR_KINDS and len(names) == 2
    if not names and e.get("drug") and e["drug"] != "이 약" and not is_pair:
        names = [e["drug"]]  # 식별 항목 등 `drugs`가 없는 근거: finalize가 만든 이름 그대로
    unidentified = e.get("why") is not None or e.get("input_name") is not None
    return Finding(
        target="pair" if is_pair else "product",
        drugs=names if is_pair else names[:1],
        badges=badges_by_id.get(e.get("evidence_id") or "", []) if e.get("bucket") == "found" else [],
        searched=[Searched(dataset=s.get("dataset"), count=s.get("count")) for s in e.get("searched") or [] if isinstance(s, dict)],
        retried=bool(e.get("retried_line")) if unidentified else None,
        ingredients=[Ingredient(**i) for i in e.get("ingredients") or [] if isinstance(i, dict) and i.get("name")],
        **{k: e[k] for k in _FINDING_PASS if e.get(k) is not None},
    )


def _candidates(clarify: dict[str, Any] | None) -> list[Candidate]:
    if not isinstance(clarify, dict):
        return []
    target = clarify.get("target_raw") or ""
    return [Candidate(input_name=target, name=o["name"], item_seq=o.get("item_seq"), entp_name=o.get("entp_name"),
                      prescription=o.get("prescription"), matched_by=o.get("matched_by"))
            for o in clarify.get("options") or [] if isinstance(o, dict) and o.get("name") and target]


def to_chat_response(resp: dict[str, Any], *, end_reason: str | None = None, clarify: dict[str, Any] | None = None) -> ChatResponse:
    """`finalize()` 출력 딕셔너리 → `ChatResponse`. 값을 지어내지 않고 옮기며, 출처 표·날짜 줄·줄별 배지 배치만 코드로 만든다.

    `clarify`(라우터의 되묻기 묶음 `{target_raw, options[]}`)는 `end_reason == CLARIFY`일 때만 `candidates[]`로 옮긴다.
    """
    detail = [_detail_item(d) for d in resp.get("detail") or [] if isinstance(d, dict)]
    detail_by_id = {d.evidence_id: d for d in detail if d.evidence_id}
    badges_by_id: dict[str, list[Badge]] = {}
    for b in resp.get("badges") or []:
        badges_by_id.setdefault(b.get("evidence_id") or "", []).append(_badge(b))
    fixed = [x for x in (resp.get("pharmacist_advice_fixed"), resp.get("fixed_notice")) if isinstance(x, str) and x.strip()]
    emergency = Emergency(text=resp["emergency"], tel=resp.get("emergency_tel") or "") if resp.get("emergency") else None
    refs = [SentenceRef(evidence_id=c["evidence_id"], sentence_index=int(c.get("sentence_index", 0)), row_key=c.get("row_key"),
                        quotes=[Quote(**q) for q in c.get("quotes") or []])
            for c in resp.get("citations") or [] if isinstance(c, dict) and c.get("evidence_id")]
    return ChatResponse(
        route=resp.get("route") or "AGENT",
        end_reason=end_reason,  # type: ignore[arg-type]
        emergency=emergency,
        notice=resp.get("notice"),
        # 값을 걸러 내지 않고 그대로 옮긴다: 모양이 어긋난 고지는 조용히 빠지지 않고 검증 오류로 드러난다(고지 없이 보정 결과만 나가지 않게)
        name_corrections=[NameCorrection(**c) for c in resp.get("name_corrections") or []],
        not_checked_lines=list(resp.get("not_checked_lines") or []),
        grade_defs=[GradeDef(**g) for g in resp.get("grade_defs") or [] if isinstance(g, dict)],
        summary=resp.get("summary"),
        findings=[_finding(e, detail_by_id, badges_by_id) for e in resp.get("entries") or [] if isinstance(e, dict)],
        candidates=_candidates(clarify) if end_reason == "CLARIFY" else [],
        detail=detail,
        citations=build_citations(detail),
        sentence_refs=refs,
        grade_def_missing=list(resp.get("grade_def_missing") or []),
        pharmacist_advice=list(resp.get("pharmacist_advice") or []),
        fixed_notice=fixed,
        disclaimer=resp.get("disclaimer") or "",
    )


def response_from_state(state: dict[str, Any]) -> ChatResponse:
    """그래프 최종 상태 → 응답(상태의 `answer`·`end_reason`·`clarify`만 읽는다. 질문·메시지·프로필은 싣지 않는다)."""
    return to_chat_response(state["answer"], end_reason=state.get("end_reason"), clarify=state.get("clarify"))
