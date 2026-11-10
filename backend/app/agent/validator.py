"""AG-07 Validator 기준선: LLM 답변 문장의 출구 코드 검사(순수 함수, LLM·외부 호출 없음).

코드 검사만 한다. `(개선)`(허용 근거 계층·주장 유형 누락·상태 불일치 문구·제품 단정)과 `(프롬프트 판정)`(의미 일치)은 범위 밖이다.

**문장 필터(`sentence_filter`, H1)와의 역할 분담** — 필터는 근거 ID 유무·모르는 ID·성분코드 노출과 요약의 복용량 숫자·진단 단정·
처방/복용 지시를 *무조건* 거른다. Validator는 필터를 통과한 문장(`FilterResult.kept`)을 입력으로 받아 필터가 보지 않는 것만 본다:
안전 단정, 복용 변경·의료진 우회(허가사항 원문 인용 예외 포함), 등급 값, M 등급 규칙, 파일/API 확정 문장, 미확보 항목 권고,
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
from app.agent.patterns import _tool_strings, tool_grades, unsupported_identifiers  # noqa: PLC2701 — 같은 패키지의 도구 문자열 수집기 재사용
from app.agent.quote_check import build_text_index, resolve_citation
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
BYPASS_PATTERNS = (
    r"(?:의사|약사|병원|의료진)(?:에게|한테|께)?(?:는)?(?:알리지|말하지|얘기하지|이야기하지|숨기)",
    r"(?:의사|약사|병원|의료진)(?:에게|한테|께)?(?:는)?(?:알릴필요(?:가)?없|말할필요(?:가)?없|비밀로)",
    r"(?:병원|의사|약국)(?:에)?(?:가지|갈필요|안가도)",
    r"(?:임의로|마음대로|스스로|알아서)(?:끊|중단|줄이|늘리|조절|감량)",
    r"(?:끊어도|중단해도|줄여도|늘려도|그만먹어도|안먹어도)(?:돼요|됩니다|된다|괜찮)",
    r"처방(?:을|은)?무시",
)
_BYPASS_RES = [re.compile(p) for p in BYPASS_PATTERNS]

_GRADE_AFTER = re.compile(r"(?<![가-힣A-Za-z0-9])([0-9A-Za-z]+)\s*등급")
_GRADE_BEFORE = re.compile(r"등급\s*[:은는이]?\s*([0-9A-Za-z])(?![0-9A-Za-z])")
ALLOWED_GRADES = frozenset({"1", "2", "M"})
_M_MENTION = re.compile(r"(?<![A-Za-z])[Mm]\s*등급|임부금기\s*[Mm](?![A-Za-z])")
# M을 1·2등급으로 환산한 문장: "M등급은 사실상 2등급이에요", "M = 1등급"
_M_CONVERT = re.compile(r"[Mm]\s*(?:등급)?\s*(?:은|는|이|가)?\s*(?:사실상|결국|곧|바로)?\s*(?:=|≒|~)?\s*[12]\s*등급\s*(?:이에요|입니다|과같|와같|에해당|으로(?:볼|봐|환산|계산|취급)|이라고)|[Mm]\s*(?:등급)?\s*(?:=|≒)\s*[12]\s*등급")
_M_EXPLAIN = re.compile(r"상병에\s*(?:따른|따라|따라서)|상병별")  # 고시 설명("상병에 따른 1등급 또는 2등급")은 환산이 아니다

_ONLY_CLAIM = re.compile(r"파일에만|파일에는있고|API에만|실시간(?:조회)?에만|실시간(?:조회)?에는있고")
_DEFINITIVE = re.compile(r"금기(?:입니다|예요|이에요|가맞|에해당|목록에있|로지정|다(?:$|[.!]))|금기(?:가|는)?아(?:닙니다|니에요|니예요)|금기(?:목록)?에(?:없어요|없습니다|없음)|지정되어있|지정돼있|해당합니다|해당돼요")
_HEDGE = re.compile(r"기준일이후(?:에)?(?:변경|해제|새로|지정|달라)|변경되었을수|변경됐을수|바뀌었을수")

# 연령·번호 수치(용량 숫자는 문장 필터 몫). 한국어 날짜(년·월)는 검사하지 않고 ISO 날짜만 본다.
_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:세|개월|주|호|쪽|조|항|연번|판)")
_NUM_PREFIX = re.compile(r"(?:제|연번|쪽|별표|고시)\s*(\d+)")

_PHARMACIST = re.compile(r"약국|약사")
_NONE_IMPLY = re.compile(r"없(?:어요|습니다|음)")
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

    @property
    def dropped(self) -> list[Issue]:
        return [i for i in self.issues if i.action == "DROPPED"]


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


# ---------------------------------------------------------------------------------------- 문장 단위 검사
def _check_sentence(s: SimpleNamespace, items: list[dict[str, Any]], ctx: SimpleNamespace, allowed_types: frozenset[str]) -> str | None:
    # ⑦ claim_type: 검사 전에 걸러 실패로 기록한다
    if s.claim_type not in allowed_types:
        return BAD_CLAIM_TYPE
    text = strip_fixed(s.text)                 # 고정 문구 상수는 검사 대상이 아니다
    if not text.strip():
        return None
    norm = _norm(text)

    # ① 안전 단정
    if _has_safe_assertion(norm):
        return SAFE_ASSERTION

    # ② 복용 변경·중단·복용 지시와 의료진 우회(허가사항 원문 인용 구간은 제외)
    q_norm = _norm(_mask_quotes(SimpleNamespace(**{**s.__dict__, "text": text}), ctx.index))
    if any(r.search(q_norm) for r in _BYPASS_RES) or any(r.search(q_norm) for r in _DECISION_PATTERNS):
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
    return None


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
) -> ValidationResult:
    """답변 문장을 코드로 검사한다. `answer`는 `AnswerDraft`(또는 `(AnswerDraft, RenderResult)`·`{"sentences": [...]}`·문장 목록).

    - PASS: 걸러진 문장이 없고 되감기도 없다.
    - FIXED: 문장을 걸렀지만(제거) 남은 문장이 있고 되감기가 필요 없다.
    - FAIL: 입력이 있었는데 남은 문장이 없거나, 미확보 항목의 약사 확인 권고가 빠져 되감기가 필요하다.
    """
    raw_sents, rendered = _unwrap(answer, rendered)
    allowed = frozenset(expected_claim_types) if expected_claim_types is not None else frozenset(EVIDENCE_REQUIRED)
    by_id = {it["evidence_id"]: it for it in items if it.get("evidence_id")}
    row_to_item = {m["row_evidence_id"]: it for it in items for m in _rows(it) if m.get("row_evidence_id")}
    grades = tool_grades(items)
    ctx = SimpleNamespace(by_id=by_id, row_to_item=row_to_item, index=build_text_index(items), grades=grades,
                          has_m="M" in grades, pool=_tool_strings(items))
    res = ValidationResult()
    kept: list[SimpleNamespace] = []
    for i, raw in enumerate(raw_sents):
        s = _sent(raw)
        reason = _check_sentence(s, items, ctx, allowed)
        if reason:
            res.issues.append(Issue(i, reason, "DROPPED", s.text))
        else:
            kept.append(s)
    # ⑥ 미확보 항목: 권고가 있어야 하고 "없음·안전" 암시가 없어야 한다(걸러진 문장은 빼고 센다)
    implied, rewind = _missing_checks(kept, items)
    drop_idx = {i for i, _ in implied}
    for i, why in implied:
        res.issues.append(Issue(i, why, "DROPPED", kept[i].text))
    if drop_idx:
        kept = [s for j, s in enumerate(kept) if j not in drop_idx]
        implied2, rewind = _missing_checks(kept, items)   # 암시 문장을 지운 뒤 다시 센다
        del implied2
    for eid in rewind:
        res.issues.append(Issue(-1, MISSING_ADVICE_ABSENT, "REWIND", eid))
    res.rewind = rewind
    res.kept = [s.raw for s in kept]
    n_dropped = len(res.dropped)
    if rewind or (raw_sents and not kept):
        res.status = FAIL
    elif n_dropped:
        res.status = FIXED
    reasons: dict[str, int] = {}
    for it in res.issues:
        reasons[it.check] = reasons.get(it.check, 0) + 1
    res.events.append({
        "rule": "H2", "event": "VALIDATOR", "status": res.status, "total": len(raw_sents), "kept": len(res.kept),
        "dropped": n_dropped, "rewind": len(rewind), "reasons": reasons,
    })
    return res
