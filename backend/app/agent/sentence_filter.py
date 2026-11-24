"""문장 필터(H1): 근거 ID가 없거나 모르는 사실 문장을 출력 전에 걸러낸다(순수 함수, LLM 호출 없음).

걸러진 수·이유는 반환값으로만 돌려준다. `events`는 `harness_event` 형식 dict(`{"rule": ...}`,
`backend/app/logging/spans.py`의 `build_record`가 받는 모양)이며 이번 범위에서는 로거에 연결하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.answer_schema import AnswerDraft, Sentence, requires_evidence
from app.agent.patterns import has_code
from app.agent.quote_check import build_text_index, resolve_citation

NO_EVIDENCE = "NO_EVIDENCE"            # 사실 문장인데 근거 ID가 없다
UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"  # 이번 도구 결과에 없는 근거 ID
CODE_IN_TEXT = "CODE_IN_TEXT"          # 요약 문장에 성분코드 형식이 있다(근거 상세에만 둔다)
DOSE_NUMBER = "DOSE_NUMBER"            # 요약 문장에 복용량·투여량 숫자나 복용 빈도·기간 지시가 있다(RFP-21-03)
DIAGNOSIS_CLAIM = "DIAGNOSIS_CLAIM"    # 진단 단정(진단·처방·복용량 결정은 하지 않는다, CLAUDE.md 1장)
PRESCRIPTION_OR_DOSE_DECISION = "PRESCRIPTION_OR_DOSE_DECISION"  # 처방·복용 지시·복용 변경 지시
ADVISORY_OR_ENDORSEMENT = "ADVISORY_OR_ENDORSEMENT"  # 일반 권유·지도("~하는 게 좋아요", "추천합니다")와 사용자 판단에 대한 동조·승인("괜찮아요", "좋은 선택이에요")

# 안전 이유 판별은 정규식·키워드만 쓴다(LLM 없음). 공백을 모두 지운 문장에 매칭하므로 띄어쓰기 변형에 강하다.
# 한계: 영어·우회 표현·글자 사이에 기호를 끼운 변형은 잡지 못한다(근거 상세는 검사하지 않는다).
_WS = re.compile(r"\s+")
_NUM = r"\d+(?:\.\d+)?(?:[~\-]\d+(?:\.\d+)?)?"
_KO_NUM = r"(?:한|두|세|네|다섯|여섯|반)"
# 단위 뒤에 한글이 바로 이어지면(정보·알림·포함) 다른 낱말이므로 조사·어미 몇 개만 허용한다.
_AFTER_UNIT = r"(?![가-힣])|(?=씩|을|를|이|은|는|도|만|마다|으로|에|까지|정도|이상|이하|가|과|와|의|쯤|짜리)"
_UNIT_ASCII = r"(?:mg|mcg|μg|µg|ug|g|ml|cc|iu)(?![a-z])"
_UNIT_KO = r"(?:밀리그램|마이크로그램|그램|밀리리터|정|알|캡슐|포|방울|티스푼|스푼|단위)(?:" + _AFTER_UNIT + r")"
_DOSE_PATTERNS = [
    re.compile(_NUM + _UNIT_ASCII, re.I),                      # 500mg, 2.5ml, 10cc, 5000IU
    re.compile(_NUM + _UNIT_KO),                               # 3정, 2알씩, 5밀리그램
    re.compile(_KO_NUM + r"(?:알|정|포|캡슐|스푼|티스푼|방울)(?:" + _AFTER_UNIT + r")"),  # 한 알, 반 정
    re.compile(r"(?:하루|매일|1일|일일)(?:에)?(?:" + _NUM + r"|" + _KO_NUM + r")(?:회|번|차례)"),  # 하루 3회, 매일 두 번
    re.compile(_NUM + r"(?:회|번)(?:씩)?(?:복용|투여|먹|드)"),    # 3회 복용
    re.compile(_NUM + r"(?:시간|분)(?:마다|간격|터울)"),          # 8시간마다
    re.compile(_NUM + r"(?:일|주|개월)(?:간|동안)(?:복용|투여|먹|드시|사용)"),  # 7일간 복용
]
_DIAGNOSIS_PATTERNS = [
    re.compile(r"(?:으로|로)진단(?:돼|됩|됐|되었|되어|이)"),               # 위염으로 진단돼요
    re.compile(r"진단(?:됩니다|돼요|됐어요|되었습니다|이에요|입니다|이네요|합니다|해요|해드)"),
    re.compile(r"진단이?내려"),
    re.compile(r"[가-힣]{1,}(?:병|증|염|암|질환|증후군)(?:이에요|입니다|이세요|이네요|이라고봅니다)"),  # …병이에요
    re.compile(r"[가-힣]{1,}(?:병|증|염|암|질환)일(?:가능성이?(?:높|커|큽)|것같|것입니다|거예요)"),
    re.compile(r"(?:당신|귀하|본인|고객님|환자분)(?:은|는)[^.。]{0,20}(?:입니다|이에요|예요|이세요|이네요)"),
]
_DECISION_PATTERNS = [
    re.compile(r"처방(?:해(?:드|줄|주)|합니다|하겠|할게|할께|드(?:려|릴|립))"),  # 처방해 드릴게요
    re.compile(r"(?:추천|권해|권장해)(?:해)?드(?:려|릴|립)"),
    re.compile(r"(?:드세요|드십시오|드시기바(?:랍니다|라요)|드셔야|드셔도(?:돼|됩|괜찮)|드시면(?:돼|됩))"),
    re.compile(r"(?:복용|투여|섭취)(?:하세요|하십시오|하시면(?:돼|됩)|해야(?:해|합|돼|됩)|해도(?:돼|됩|괜찮))"),
    re.compile(r"(?:먹으세요|먹어야|먹어도(?:돼|됩|괜찮)|먹으면(?:돼|됩))"),
    re.compile(r"(?:복용|투여|섭취)하지마(?:세요|십시오)|(?:먹지|드시지)마(?:세요|십시오)"),
    re.compile(r"(?:복용량|용량)(?:을|은)?[^.。]{0,20}(?:정해|골라|맞춰)(?:드|줄)"),
    re.compile(r"(?:당신|님|고객님|환자분?)(?:에게|께)?(?:맞는|적합한|알맞은|적정)(?:복용)?용량"),
    re.compile(r"(?:늘리|줄이|끊으|끊|중단하|중지하|멈추|바꾸|조절하|증량하|감량하)(?:세요|십시오)"),
    re.compile(r"(?:늘려|줄여|끊어|중단해|중지해|바꿔|조절해)(?:야(?:해|합|돼|됩)|도(?:돼|됩))"),
    re.compile(r"(?:늘리셔|줄이셔|끊으셔|중단하셔|중지하셔|조절하셔)(?:야(?:해|합|돼|됩)|도(?:돼|됩|괜찮))"),  # 존대형(AG-08-01 A 보강)
]


# --------------------------------------------------------------------------- 출구 Sensor(AG-13-40 A, 2026-11-23): 권유·지도·동조·승인 표현
# 이 에이전트는 안내가 목적이고 지도·제안·권유는 하지 않는다. 그 규칙(프롬프트 Guide `agent_system@v3`)의 짝으로, 최종 답변 문장에서 결정론적으로 거른다.
# 제어 방식: **문장 단위 차단**(위 `unsafe_reason`이 이유를 돌려주면 `filter_sentences`가 그 문장을 지운다). 다 지워지면 기존 경로(되감기 1회 → 코드 폴백 문구)가 이어진다.
# 근거: 재작성(LLM 재호출)은 비결정적이고 비용이 들며, 전체 문구 대체는 맞는 근거 문장까지 버린다. 고정 문구·근거 항목은 코드가 따로 붙이므로 문장을 지워도 안전 정보가 줄지 않는다.
# 인용부호 안(허가사항·고시 원문 인용)은 에이전트의 말이 아니라 원문이므로 검사하지 않는다(인용이 원문과 같은지는 H28이 따로 본다).
# 면제: 권유의 동사가 확인·상의·상담·문의·물어보기·찾아보기 같은 "근거·전문가를 보라"는 안내면 통과한다(약국·약사 확인 안내는 필수 문구다).
_QUOTED = re.compile(r"[\"“「『][^\"“”「」『』\n]+[\"”」』]")
_CONSULT_STEMS = ("확인", "상의", "상담", "문의", "물어", "여쭤", "알아", "찾아", "살펴", "읽어", "참고", "연락", "방문", "검색", "전화", "내원", "진료")
# 권유·지도: 끝맺음만 매칭하고, 바로 앞 6글자(공백 제거 기준)에 면제 어간이 있으면 통과시킨다.
_ADVISORY_ENDINGS = [
    re.compile(r"보(?:세요|시길|시는게|시는것이|십시오|시면좋)"),                                    # 드셔 보세요, 해 보시길
    re.compile(r"(?:는|은)(?:게|것이|것도|편이|쪽이)(?:더)?(?:좋|낫|바람직|안전)(?:아요|습니다|겠|을것|을거|지요|네요|죠|다)"),  # 하는 게 좋아요
    re.compile(r"(?:추천|권장|권유|권고)(?:합니다|해요|드려요|드립니다|할게요|드릴게요|해드립|해드려)|권(?:합니다|해요|해드립|해드려|장합니다)"),
    re.compile(r"시(?:기|길)(?:를)?바(?:랍니다|라요|랄게요|래요)"),                                    # 쉬시기 바랍니다, 드시길 바라요
    re.compile(r"(?:하시면|해주시면|드시면|하면|해두시면|해보시면|가시면)(?:좋겠|좋아요|좋습니다|더좋)"),
]
# 동조·승인(사용자 판단에 대한 긍정): 면제가 없다("의사에게 안 물어봐도 괜찮아요"를 통과시키지 않기 위해). 매칭 뒤 12글자 안에 부정(아니·않·없·못·말)이 있으면 부정문이라 통과시킨다.
_ENDORSE_PATTERNS = [
    re.compile(r"(?:해도|하셔도|드셔도|먹어도|써도|사용해도|복용해도|그렇게해도|그대로해도)(?:좋아요|좋습니다|무방)"),
    re.compile(r"(?:좋은|현명한|옳은|합리적인|적절한|훌륭한)(?:선택|판단|결정|생각)"),
    re.compile(r"(?:판단|결정|생각|말씀|선택)(?:이|은|도)?(?:맞|옳|타당|적절|좋)"),
    re.compile(r"(?:그렇게|말씀하신대로|판단하신대로|생각하신대로|결정하신대로|그대로)(?:하셔도|하세요|하시면|하시는게|해도|하는게|하셔요)"),
    re.compile(r"잘(?:하셨|한결정|하신)"),
    re.compile(r"(?:동의|공감)(?:합니다|해요|해)(?!하기|하지)"),
]
# "괜찮아요"·"문제없어요"·"안심하세요"·"걱정 마세요" 같은 안전 단정·안심 표현은 Validator의 `SAFE_ASSERTION_PATTERNS`가 이미 막는다(중복 검사를 두지 않는다).
_NEGATION = re.compile(r"아니|않|없|못|말")


def advisory_or_endorsement(text: str) -> bool:
    """권유·지도·동조·승인 표현이 있으면 True(공백 제거 뒤 정규식, 인용부호 안은 제외)."""
    t = _WS.sub("", _QUOTED.sub("", text))
    for pat in _ADVISORY_ENDINGS:
        for m in pat.finditer(t):
            if not any(stem in t[max(0, m.start() - 6): m.end()] for stem in _CONSULT_STEMS):
                return True
    for pat in _ENDORSE_PATTERNS:
        for m in pat.finditer(t):
            if not _NEGATION.search(t[m.end(): m.end() + 12]):
                return True
    return False


def unsafe_reason(text: str, *, advisory: bool = True) -> str | None:
    """요약 문장의 안전 이유(복용량 숫자·진단 단정·처방/복용 결정·권유/동조). 없으면 None."""
    t = _WS.sub("", text)
    for reason, pats in ((DOSE_NUMBER, _DOSE_PATTERNS), (DIAGNOSIS_CLAIM, _DIAGNOSIS_PATTERNS),
                         (PRESCRIPTION_OR_DOSE_DECISION, _DECISION_PATTERNS)):
        if any(p.search(t) for p in pats):
            return reason
    if advisory and advisory_or_endorsement(text):   # 출구 Sensor(AG-13-40 A): 앞의 세 검사에 걸리지 않은 권유·지도·동조 표현
        return ADVISORY_OR_ENDORSEMENT
    return None


def known_evidence_ids(items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for it in items:
        if it.get("evidence_id"):
            ids.add(it["evidence_id"])
        for m in it.get("matches") or []:
            if m.get("row_evidence_id"):
                ids.add(m["row_evidence_id"])
    return ids


@dataclass(frozen=True)
class Dropped:
    index: int
    reason: str
    text: str


@dataclass
class FilterResult:
    kept: list[Sentence] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    bad_quotes: int = 0  # 알 수 없는 ID·범위 밖이라 글자를 자를 수 없는 인용 수
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def filter_sentences(draft: AnswerDraft, items: list[dict[str, Any]], *, advisory_sensor: bool = True) -> FilterResult:
    known = known_evidence_ids(items)
    index = build_text_index(items)
    res = FilterResult()
    for i, s in enumerate(draft.sentences):
        reason = None
        if requires_evidence(s.claim_type) and not s.evidence_ids:
            reason = NO_EVIDENCE
        elif any(e not in known for e in s.evidence_ids):
            reason = UNKNOWN_EVIDENCE
        elif has_code(s.text):
            reason = CODE_IN_TEXT
        else:
            reason = unsafe_reason(s.text, advisory=advisory_sensor)   # 근거 ID가 있어도 적용한다(근거 검사 뒤)
        if reason:
            res.dropped.append(Dropped(i, reason, s.text))
            continue
        # 인용 검사: 문장에 연결되지 않은 ID이거나 글자를 자를 수 없는 인용은 문장은 남기고 인용만 센다.
        for c in s.citations:
            if c.evidence_id not in s.evidence_ids or not resolve_citation(c, index).ok:
                res.bad_quotes += 1
        res.kept.append(s)
    reasons: dict[str, int] = {}
    for d in res.dropped:
        reasons[d.reason] = reasons.get(d.reason, 0) + 1
    res.events.append({
        "rule": "H1", "event": "SENTENCE_FILTER", "total": len(draft.sentences), "kept": len(res.kept),
        "dropped": res.dropped_count, "reasons": reasons, "bad_quotes": res.bad_quotes,
    })
    return res
