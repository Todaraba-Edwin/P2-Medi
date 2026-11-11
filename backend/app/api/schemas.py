"""BE-06 응답 스키마 골격(Pydantic)과 `finalize` 출력 → API 응답 변환. 엔드포인트·라우트 연결은 BE-06 본 작업이다(여기서는 하지 않는다).

근거 문서: `P2-doc/PJ2-PRD.md` 15.1절(응답 필드), `tickets/backend/BE-06.md` §2(PRD-11-02·03·05, PRD-12-01·02·03, PRD-14),
`tickets/doc/PRD-12.md` §4.5(출처 순서)·§5(날짜 줄)·§6(데이터 계약), AG-08-03 B(자료별 기준일).

- `citations[]` = **출처 표 행**(1출처 = 1행): `publisher`(기관, 대그룹)·`dataset`(자료 약칭, 중그룹 = 근거 박스 표지의 약칭)·`dates[{label, value}]`.
  날짜는 **한 날짜 = 한 항목**이고 라벨은 상수(`고시일`·`기준일`·`조회`, 날짜가 없으면 `날짜 없음`)다. 화면은 문자열을 조립하지 않는다.
  파일과 API는 자료가 달라 각각 행이다(PRD-09 G8). 같은 자료의 고시일이 여럿이면 줄마다 하나씩 둔다(어느 한쪽을 대표로 고르지 않음, AG-08-03 B).
- 순서는 코드가 정한다(PRD-12 §4.5): 판정에 쓴 자료가 있는 기관 먼저(동률이면 식약처 → 한국의약품안전관리원 → 건강보험심사평가원),
  같은 기관 안에서는 판정 자료 → 허가사항 근거 자료 → 그 밖.
- `detail[]`은 도구 항목을 코드가 렌더한 것(AG-06 `renderer`)이고 LLM 문장(`LLM_SUMMARY`)은 없다. `summary`만 LLM 문장(검증 통과분) 또는 코드 문구다.
- 내부 필드(`events`·`warnings`·`text`)는 응답에 싣지 않는다. 금지 칸(복용 지시·용량 숫자)의 **내용** 검사는 Validator(AG-07) 몫이고 여기서는 형식만 본다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.tools.provenance import CITATION_DATE_LABELS, DATASET_LABELS, DATASET_PUBLISHER, PUBLISHER

SCHEMA_VERSION = "chat_response@v0"  # 골격(BE-06 본 작업에서 v1로 고정)

# ---------------------------------------------------------------- 날짜 라벨(정의는 `provenance.CITATION_DATE_LABELS` 한 곳, PRD-12 §5.1)
DATE_LABEL_NOTICE = CITATION_DATE_LABELS["notice"]
DATE_LABEL_AS_OF = CITATION_DATE_LABELS["as_of"]
DATE_LABEL_QUERIED = CITATION_DATE_LABELS["queried"]
DATE_LABEL_NONE = CITATION_DATE_LABELS["none"]  # PRD-12 §5.6(가정): 날짜가 없는 자료도 칸을 비우지 않는다
DATE_LINE_LABELS: tuple[str, ...] = (DATE_LABEL_NOTICE, DATE_LABEL_AS_OF, DATE_LABEL_QUERIED, DATE_LABEL_NONE)

KST = ZoneInfo("Asia/Seoul")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 기관 기본 순서(PRD-12 §4.5.1 동률 규칙, PRD-11 §5.1 표 순서)
PUBLISHER_ORDER: tuple[str, ...] = (PUBLISHER["mfds"], PUBLISHER["kids"], PUBLISHER["hira"])
OFFICIAL_PUBLISHERS = frozenset(PUBLISHER_ORDER)
# 같은 기관 안 자료 순서: 판정 자료 → 허가사항 근거 자료(PRD-12 §4.5.2)
JUDGE_DATASETS: tuple[str, ...] = ("dur_ingr", "contra_pair", "pregnancy", "age", "dose", "lactation", "elderly", "dup_ingredient")
LABEL_DATASETS: tuple[str, ...] = ("eyak", "prmsn", "identify")
_JUDGED_STATUS = ("FOUND", "NOT_LISTED")

Route = Literal["AGENT", "REFUSE"]
EndReason = Literal["NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"]
SourceKind = Literal["API_DIRECT", "FILE", "CORPUS_QUOTE"]
Bucket = Literal["found", "not_listed", "identified", "unconfirmed"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- 모델
class DateLine(_Strict):
    """날짜 한 줄(한 날짜 = 한 항목). `날짜 없음`만 `value`가 None이다."""

    label: str
    value: str | None

    @model_validator(mode="after")
    def _check(self) -> DateLine:
        if self.label not in DATE_LINE_LABELS:
            raise ValueError("날짜 라벨은 상수 목록(고시일·기준일·조회·날짜 없음)에 있어야 한다")
        if self.label == DATE_LABEL_NONE:
            if self.value is not None:
                raise ValueError("'날짜 없음' 줄은 value가 없어야 한다")
        elif not (isinstance(self.value, str) and _DATE_RE.match(self.value)):
            raise ValueError(f"{self.label} 값은 YYYY-MM-DD여야 한다")
        return self


class Citation(_Strict):
    """출처 표 한 행(PRD-11-02·PRD-12 §6). `publisher`는 공식 기관 이름만(서비스 이름 금지, PRD-14)."""

    publisher: str
    dataset: str
    dates: list[DateLine] = Field(min_length=1)
    source_kind: SourceKind | None = None
    evidence_ids: list[str] = Field(default_factory=list)

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
    """근거 상세 한 박스(AG-06 `renderer` 결과에 자료 약칭·기관·날짜 줄을 더한 것). LLM 문장 없음."""

    evidence_id: str | None
    kind: str | None
    status: str | None
    source_kind: SourceKind | None
    dataset_key: str | None
    dataset: str | None
    publisher: str | None
    dates: list[DateLine]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    drugs: list[str] | None = None
    item_seq: str | None = None
    section: str | None = None
    label_source: str | None = None
    missing_reason: str | None = None


class Finding(_Strict):
    """제품·항목별 판정 줄(`finalize.entries`). 문구는 코드 상수."""

    bucket: Bucket
    evidence_id: str | None
    kind: str | None
    drug: str
    text: str
    notes: list[str] = Field(default_factory=list)
    source_label: str | None = None
    unresolved: bool = False
    grades: list[str] = Field(default_factory=list)
    notice_nos: list[str] = Field(default_factory=list)
    note: str | None = None
    input_name: str | None = None
    why: str | None = None
    next: str | None = None
    retried_line: str | None = None
    reference_line: str | None = None
    searched: list[dict[str, Any]] = Field(default_factory=list)


class Badge(_Strict):
    kind: str | None
    grade: str | None
    text: str
    evidence_id: str | None
    note: str | None = None


class Emergency(_Strict):
    text: str
    tel: str | None = None


class ChatResponse(_Strict):
    """`/chat` 응답 본문 골격. 응급이면 `emergency`가 있고(스트리밍 첫 이벤트는 BE-06 본 작업), 고정 문구·고지는 항상 비어 있지 않다."""

    schema_version: Literal["chat_response@v0"] = SCHEMA_VERSION
    route: Route
    end_reason: EndReason | None = None
    emergency: Emergency | None = None
    notice: str | None = None
    summary: str | None
    findings: list[Finding] = Field(default_factory=list)
    badges: list[Badge] = Field(default_factory=list)
    detail: list[DetailItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    sentence_refs: list[SentenceRef] = Field(default_factory=list)
    grade_def_missing: list[str] = Field(default_factory=list)
    pharmacist_advice: list[str] = Field(default_factory=list)
    fixed_notice: list[str] = Field(min_length=1)  # 줄 목록: (미확보가 있으면) 약사 확인 권고 → 고정 문구
    disclaimer: str = Field(min_length=1)

    @field_validator("fixed_notice")
    @classmethod
    def _non_blank(cls, v: list[str]) -> list[str]:
        if not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError("fixed_notice 줄은 비어 있을 수 없다")
        return v


# ---------------------------------------------------------------- 변환
def _iso_date(v: Any) -> str | None:
    if isinstance(v, str):
        s = v.strip()
        if _DATE_RE.match(s[:10]) and (len(s) == 10 or s[10] in "T "):
            return s[:10]
        if re.fullmatch(r"\d{8}", s):
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
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
    as_of = _iso_date(d.get("as_of"))
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
    drugs = d.get("drugs")
    return DetailItem(
        evidence_id=d.get("evidence_id"), kind=d.get("kind"), status=d.get("status"), source_kind=sk, dataset_key=d.get("dataset_key"),
        dataset=ds, publisher=pub, dates=date_lines(d) if sk else [DateLine(label=DATE_LABEL_NONE, value=None)],
        flags=list(d.get("flags") or []), notes=[str(x) for x in d.get("notes") or []], rows=[dict(r) for r in d.get("rows") or []],
        drugs=[str(x) for x in drugs] if isinstance(drugs, list) else None, item_seq=d.get("item_seq"), section=d.get("section"),
        label_source=d.get("label_source"), missing_reason=d.get("missing_reason"),
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
                                  "evidence_ids": [], "dataset_key": d.dataset_key, "judged": False})
        for line in d.dates:
            if line.label == DATE_LABEL_NONE:
                continue
            if all((x.label, x.value) != (line.label, line.value) for x in r["dates"]):
                r["dates"].append(line)
        if d.evidence_id and d.evidence_id not in r["evidence_ids"]:
            r["evidence_ids"].append(d.evidence_id)
        if d.dataset_key in JUDGE_DATASETS and d.status in _JUDGED_STATUS:
            r["judged"] = True
            judged_pubs.add(d.publisher)
    label_rank = {DATE_LABEL_NOTICE: 0, DATE_LABEL_AS_OF: 1, DATE_LABEL_QUERIED: 2}

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
        dates = sorted(r["dates"], key=lambda x: (label_rank[x.label], x.value or ""))
        out.append(Citation(publisher=r["publisher"], dataset=r["dataset"], dates=dates or [DateLine(label=DATE_LABEL_NONE, value=None)],
                            source_kind=r["source_kind"], evidence_ids=r["evidence_ids"]))
    return out


_FINDING_KEYS = tuple(Finding.model_fields)
_BADGE_KEYS = tuple(Badge.model_fields)


def to_chat_response(resp: dict[str, Any], *, end_reason: str | None = None) -> ChatResponse:
    """`finalize()` 출력 딕셔너리 → `ChatResponse`. 값을 지어내지 않고 옮기며, 출처 표와 날짜 줄만 코드로 만든다."""
    detail = [_detail_item(d) for d in resp.get("detail") or [] if isinstance(d, dict)]
    fixed = [x for x in (resp.get("pharmacist_advice_fixed"), resp.get("fixed_notice")) if isinstance(x, str) and x.strip()]
    emergency = Emergency(text=resp["emergency"], tel=resp.get("emergency_tel")) if resp.get("emergency") else None
    refs = [SentenceRef(evidence_id=c["evidence_id"], sentence_index=int(c.get("sentence_index", 0)), row_key=c.get("row_key"),
                        quotes=[Quote(**q) for q in c.get("quotes") or []])
            for c in resp.get("citations") or [] if isinstance(c, dict) and c.get("evidence_id")]
    return ChatResponse(
        route=resp.get("route") or "AGENT",
        end_reason=end_reason,  # type: ignore[arg-type]
        emergency=emergency,
        notice=resp.get("notice"),
        summary=resp.get("summary"),
        findings=[Finding(**{k: v for k, v in e.items() if k in _FINDING_KEYS and v is not None}) for e in resp.get("entries") or []],
        badges=[Badge(**{k: v for k, v in b.items() if k in _BADGE_KEYS}) for b in resp.get("badges") or []],
        detail=detail,
        citations=build_citations(detail),
        sentence_refs=refs,
        grade_def_missing=list(resp.get("grade_def_missing") or []),
        pharmacist_advice=list(resp.get("pharmacist_advice") or []),
        fixed_notice=fixed,
        disclaimer=resp.get("disclaimer") or "",
    )


def response_from_state(state: dict[str, Any]) -> ChatResponse:
    """그래프 최종 상태 → 응답(상태의 `answer`·`end_reason`만 읽는다. 질문·메시지는 싣지 않는다)."""
    return to_chat_response(state["answer"], end_reason=state.get("end_reason"))
