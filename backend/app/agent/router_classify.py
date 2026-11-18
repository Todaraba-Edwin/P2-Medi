"""AG-05 Router의 프롬프트 분류(LLM 보조) 부분. **기본 꺼짐**(`ROUTER_LLM_CLASSIFY_DEFAULT = False`).

AG-05 §2의 (프롬프트 + 스키마 검증) 조건들(엔티티 추출·유형 라벨·`open` 분류·필요한 주장 유형)을 위한 분류기다. 규칙(`router.route_input`)이
먼저 돌고, 이 모듈은 그 결과에 LLM 분류를 **덧붙이기만** 한다. 서비스·평가 기본 경로(`graph/nodes.py`·`pipeline/**`)는 이 모듈을 부르지 않는다.
기준선(AG-11) 뒤 개선(AG-13, 개발셋만) 후보다. 켜는 곳(연결)은 이 작업 범위 밖이라 보고의 "연결 초안"에 적었다.

경계(코드가 정하는 것). 원칙은 **규칙 우선, LLM은 보완**이고, 둘이 다르면 아래 표대로 처리하며 충돌 코드(`CONFLICT_*`)만 남긴다:
  - LLM 출력은 `RouterClassification` 스키마로 검증하고, 질문에 글자 그대로 없는 약 이름·질환 낱말은 버린다(지어낸 이름 차단).
  - 약 이름 확정은 늘 사전(`DrugDict`)이 한다. LLM이 더 찾은 약은 사전 정확·정규화 일치로 하나로 정해질 때만 엔티티로 더한다.
  - LLM이 약으로 보지 않은 규칙 엔티티는 **확정(RESOLVED)이 아니고, 사전에 이름 그대로(정확·정규화) 있지도 않을 때만** 뺀다
    (잡음 낱말: "안전", "소화", "배가" 등). 확정된 약과 이름 그대로 있는 모호 약("뉴론틴" 같은 제품군 이름)은 빼지 않는다.
  - 연령·임신: 질문 문장에서 규칙이 찾은 값이 우선이다. 규칙이 질문에서 못 찾았을 때만 LLM 값을 본다.
      · 연령: 질문에 나이 표현(숫자·수 낱말 + 살·개월, 숫자 + 세·대)이 있을 때만 쓴다(지어낸 나이 차단). 프로필 값보다 질문이 우선이다.
      · 임신: LLM `yes`만 쓴다(더 조심하는 쪽). `no`는 임부 금기 확인을 빼는 쪽이라 쓰지 않고, `possible`·`unknown`도 쓰지 않는다.
  - 유형 라벨·주장 유형은 규칙 결과에 더한다(빼지 않는다). 약이 있으면 `open`은 뺀다.
  - **범위 외는 Guardrail 몫**이다(응급과 같은 방식). LLM의 `out_of_scope`는 `intent`에 넣지 않고 `ClassifyOutcome.scope_hint`로만 돌려준다.
  - 검증에 실패하거나 호출이 실패하면 규칙 결과를 그대로 쓴다(`ClassifyOutcome.used=False`).
  - 질문·출력은 저장·로그하지 않는다. 충돌 코드·개수에는 약 이름·나이·질문이 들어가지 않는다. 이 모듈은 외부 호출을 직접 하지 않는다(`call` 주입).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent import router as R
from app.tools.drug_dict import MATCH_EXACT, MATCH_NORMALIZED, DrugDict

ROUTER_LLM_CLASSIFY_DEFAULT = False  # 서비스·평가 기본값. 켜려면 호출자가 `enabled=True`와 `call`을 함께 준다
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "router_classify@v1.md"
PROMPT_ID = "router_classify@v1"
MAX_CONDITIONS = 5

Intent = Literal["contraindication", "drug_info", "document", "out_of_scope", "open"]
NeededClaim = Literal["grade_definition", "term_procedure"]
INTENT_OUT_OF_SCOPE = "out_of_scope"
_INTENT_ORDER = (R.INTENT_CONTRA, R.INTENT_DRUG_INFO, R.INTENT_DOCUMENT, INTENT_OUT_OF_SCOPE, R.INTENT_OPEN)
_CLAIM_OF = {"grade_definition": R.CLAIM_GRADE_DEFINITION, "term_procedure": R.CLAIM_TERM_PROCEDURE}

CallFn = Callable[[list[dict[str, str]]], Any]  # messages → dict 또는 JSON 문자열

# 충돌 코드(값·이름 없이 코드만). 규칙과 LLM이 달랐을 때 어느 쪽을 썼는지 남긴다.
CONFLICT_RESOLVED_KEPT = "RESOLVED_KEPT"  # LLM이 약으로 안 본 확정 엔티티 → 규칙 유지
CONFLICT_NAMED_AMBIGUOUS_KEPT = "NAMED_AMBIGUOUS_KEPT"  # LLM이 약으로 안 본, 사전에 이름 그대로 있는 모호 엔티티 → 규칙 유지
CONFLICT_UNRESOLVED_REMOVED = "UNRESOLVED_REMOVED"  # LLM이 약으로 안 본 미확정 엔티티(잡음 의심) → 뺌
CONFLICT_MENTION_NOT_RESOLVED = "LLM_MENTION_NOT_RESOLVED"  # LLM이 더 찾은 이름이 사전에서 하나로 안 정해짐 → 더하지 않음
CONFLICT_AGE_RULE_KEPT = "AGE_RULE_KEPT"  # 규칙(질문) 나이와 LLM 나이가 다름 → 규칙
CONFLICT_AGE_NO_CUE = "AGE_NO_CUE"  # 질문에 나이 표현이 없는데 LLM이 나이를 냄 → 버림
CONFLICT_AGE_OVER_PROFILE = "AGE_LLM_OVER_PROFILE"  # 질문 속 나이(규칙이 못 읽음, LLM이 읽음)가 프로필 나이와 다름 → 질문(LLM)
CONFLICT_PREG_RULE_KEPT = "PREGNANCY_RULE_KEPT"  # 규칙(질문) 임신 값과 LLM 값이 다름 → 규칙
CONFLICT_PREG_NO_IGNORED = "PREGNANCY_NO_IGNORED"  # 규칙이 질문에서 못 찾았고 LLM이 no → 쓰지 않음(덜 조심하는 쪽)
CONFLICT_PREG_POSSIBLE = "PREGNANCY_POSSIBLE_IGNORED"  # LLM possible → 상태에 쓰지 않음(코드값만 남김)
CONFLICT_INTENT_RULE_KEPT = "INTENT_RULE_KEPT"  # 규칙 라벨이 LLM에 없음 → 규칙 라벨 유지(합집합)
CONFLICT_OPEN_DROPPED = "OPEN_DROPPED_HAS_DRUG"  # 약 엔티티가 있는데 open → 뺌
CONFLICT_SCOPE_HINT = "SCOPE_HINT_ONLY"  # LLM out_of_scope → intent에 넣지 않고 힌트로만(Guardrail 몫)

# 필드별 병합 규칙(문서·시험용 한눈에 보기). 키는 출력 스키마 필드.
MERGE_POLICY: dict[str, str] = {
    "drug_mentions": "사전 확정만 추가 · 확정/이름 그대로 있는 모호는 유지 · 그 밖의 미확정은 LLM이 안 보면 제거",
    "conditions": "상태에 쓰지 않음(ClassifyOutcome.conditions)",
    "age_years": "질문 규칙 > LLM(나이 표현 있을 때만) > 프로필",
    "pregnancy": "질문 규칙 > LLM yes만 > 프로필. no·possible·unknown은 쓰지 않음",
    "intent": "합집합(규칙 라벨은 빼지 않음) · 약 있으면 open 제거 · out_of_scope는 scope_hint로만",
    "needed_claims": "합집합(코드 규칙 주장 유형은 빼지 않음)",
}

# 질문 속 나이 표현(LLM 나이를 쓸 수 있는 조건). "세요"·"마세요"의 '세'에 걸리지 않게 '세'·'대'는 숫자 뒤만 본다.
_AGE_CUE_RE = re.compile(
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|스물|서른|마흔|쉰|예순|일흔|여든|아흔)\s*(?:살|개월)"
    r"|\d+\s*(?:세|대)|(?:이|삼|사|오|육|칠|팔|구)십\s*대|돌\s*(?:된|지난|쟁이)")


class RouterClassification(BaseModel):
    """LLM 출력 스키마(strict). 길이·범위 제한은 받은 뒤 이 모델이 검사한다."""

    model_config = ConfigDict(extra="forbid")

    drug_mentions: list[str] = Field(max_length=R.MAX_DRUGS)
    conditions: list[str] = Field(max_length=MAX_CONDITIONS)
    age_years: float | None = Field(ge=0, le=120)
    pregnancy: Literal["yes", "no", "possible", "unknown"]
    intent: list[Intent] = Field(min_length=1)
    needed_claims: list[NeededClaim]


def classification_json_schema() -> dict[str, Any]:
    """구조화 출력에 넘길 strict 스키마(이름·strict 포함). `llm.to_strict_schema`로 길이·범위 키워드를 뺀다."""
    from app.agent.llm import to_strict_schema

    return {"name": "router_classify", "strict": True, "schema": to_strict_schema(RouterClassification.model_json_schema())}


def load_prompt(path: Path = PROMPT_PATH) -> str:
    """프롬프트 본문(프런트매터 제외)."""
    from app.llm.prompts import split_frontmatter

    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body.strip()


def build_messages(text: str, prompt: str | None = None) -> list[dict[str, str]]:
    return [{"role": "system", "content": prompt if prompt is not None else load_prompt()}, {"role": "user", "content": text}]


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


@dataclass
class Checked:
    """검증 결과. `value`가 None이면 쓸 수 없는 출력이다."""

    value: RouterClassification | None
    error: str | None = None
    dropped_mentions: list[str] = field(default_factory=list)  # 질문에 글자 그대로 없어서 버린 약 이름(지어낸 이름)
    dropped_conditions: list[str] = field(default_factory=list)


def validate_output(raw: Any, text: str) -> Checked:
    """LLM 출력을 스키마로 검증하고, 질문에 없는 낱말을 버린다. 실패 사유는 코드값만 돌려준다(출력 내용은 싣지 않는다)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return Checked(None, "JSON_INVALID")
    if not isinstance(raw, dict):
        return Checked(None, "NOT_OBJECT")
    try:
        c = RouterClassification.model_validate(raw)
    except ValidationError:
        return Checked(None, "SCHEMA_INVALID")
    q = _squash(text)
    keep_m = [m.strip() for m in c.drug_mentions if m.strip() and _squash(m) in q]
    keep_c = [x.strip() for x in c.conditions if x.strip() and _squash(x) in q]
    dropped_m = [m for m in c.drug_mentions if m.strip() not in keep_m]
    dropped_c = [x for x in c.conditions if x.strip() not in keep_c]
    v = c.model_copy(update={"drug_mentions": list(dict.fromkeys(keep_m)), "conditions": list(dict.fromkeys(keep_c)),
                             "intent": list(dict.fromkeys(c.intent)), "needed_claims": list(dict.fromkeys(c.needed_claims))})
    return Checked(v, None, dropped_m, dropped_c)


@dataclass
class ClassifyOutcome:
    """분류기를 거친 Router 결과와 진단 값. `conditions`는 상태 필드가 없어 여기에만 담는다(연결 초안 참고)."""

    result: R.RouterResult
    used: bool = False
    error: str | None = None
    conditions: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)  # LLM이 찾고 사전이 확정해 더한 엔티티(raw)
    removed: list[str] = field(default_factory=list)  # LLM이 약으로 보지 않아 뺀 미확정 규칙 엔티티(raw)
    dropped_mentions: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # 충돌 코드(`CONFLICT_*`, 등장 순서·중복 제거). 이름·값 없음
    scope_hint: bool = False  # LLM이 범위 외로 봄(intent에는 넣지 않는다. 거절은 Guardrail 몫)


def _covers(mention: str, raw: str) -> bool:
    a, b = _squash(mention), _squash(raw)
    return bool(a) and bool(b) and (a in b or b in a)


@dataclass
class Merged:
    result: R.RouterResult
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    scope_hint: bool = False


_NAME_EXACT = (MATCH_EXACT, MATCH_NORMALIZED)


def _keep_unnamed(e: R.Entity) -> str | None:
    """LLM이 약으로 보지 않은 규칙 엔티티를 그래도 남길 이유(충돌 코드). None이면 뺀다."""
    if e.status == R.ST_RESOLVED:
        return CONFLICT_RESOLVED_KEPT
    if e.status == R.ST_AMBIGUOUS and e.match_type in _NAME_EXACT:
        return CONFLICT_NAMED_AMBIGUOUS_KEPT  # 사전에 이름 그대로 있는 제품군 이름: LLM이 놓쳐도 되묻기를 지운다면 위험하다
    return None


def merge_profile(rule_prof: R.ProfileState, text: str, c: RouterClassification, conflicts: list[str]) -> R.ProfileState:
    """연령·임신 병합(모듈 docstring 표). `rule_prof`는 규칙 결과(질문 > 프로필이 이미 반영됨)."""
    q = R.extract_profile(text, None)  # 질문 문장에서 규칙이 읽은 값만
    age, preg, src = rule_prof.age_years, rule_prof.pregnant, rule_prof.source
    if c.age_years is not None:
        if q.age_years is not None:
            if abs(q.age_years - c.age_years) > 1e-6:
                conflicts.append(CONFLICT_AGE_RULE_KEPT)
        elif not _AGE_CUE_RE.search(text or ""):
            conflicts.append(CONFLICT_AGE_NO_CUE)
        else:
            if age is not None and abs(age - c.age_years) > 1e-6:
                conflicts.append(CONFLICT_AGE_OVER_PROFILE)
            age, src = float(c.age_years), "question"
    if c.pregnancy == "possible":
        conflicts.append(CONFLICT_PREG_POSSIBLE)
    elif c.pregnancy in ("yes", "no"):
        want = c.pregnancy == "yes"
        if q.pregnant is not None:
            if q.pregnant != want:
                conflicts.append(CONFLICT_PREG_RULE_KEPT)
        elif not want:
            if preg is not False:
                conflicts.append(CONFLICT_PREG_NO_IGNORED)
        else:
            preg, src = True, "question"
    if (age, preg, src) == (rule_prof.age_years, rule_prof.pregnant, rule_prof.source):
        return rule_prof
    return R.ProfileState(age_years=age, pregnant=preg, source=src)


def merge(rule: R.RouterResult, c: RouterClassification, text: str, dd: DrugDict) -> Merged:
    """규칙 결과에 검증된 분류를 합친다(규칙 우선·LLM 보완, 충돌 처리는 모듈 docstring과 `MERGE_POLICY`)."""
    conflicts: list[str] = []
    ents: list[R.Entity] = []
    removed: list[str] = []
    for e in rule.entities:
        if any(_covers(m, e.raw) for m in c.drug_mentions):
            ents.append(e)
            continue
        why = _keep_unnamed(e)
        if why:
            conflicts.append(why)
            ents.append(e)
        else:
            conflicts.append(CONFLICT_UNRESOLVED_REMOVED)
            removed.append(e.raw)
    added: list[str] = []
    seen_seq = {e.item_seq for e in ents if e.item_seq}
    for m in c.drug_mentions:
        if len(ents) >= R.MAX_DRUGS:
            break
        if any(_covers(m, e.raw) for e in ents):
            continue
        used, r, strength = R.lookup_mention(dd, R.Mention(m))
        e = R._entity(used, r, strength)
        if e.status != R.ST_RESOLVED or r.match_type not in _NAME_EXACT:
            conflicts.append(CONFLICT_MENTION_NOT_RESOLVED)
            continue  # 사전이 하나로 정하지 못한 LLM 제안은 더하지 않는다(되묻기를 새로 만들지 않는다)
        if e.item_seq and e.item_seq in seen_seq:
            continue
        seen_seq.add(e.item_seq)
        ents.append(e)
        added.append(e.raw)
    prof = merge_profile(rule.profile, text, c, conflicts)
    out = R.assemble(text, ents, prof, truncated=rule.truncated, emergency=rule.emergency, guardrail_route=rule.guardrail_route,
                     dict_version=rule.dict_version)
    if set(out.intent) - set(c.intent):
        conflicts.append(CONFLICT_INTENT_RULE_KEPT)
    scope_hint = INTENT_OUT_OF_SCOPE in c.intent
    if scope_hint:
        conflicts.append(CONFLICT_SCOPE_HINT)
    labels = set(out.intent) | (set(c.intent) - {INTENT_OUT_OF_SCOPE})
    intent = [x for x in _INTENT_ORDER if x in labels]
    if R.INTENT_OPEN in intent and out.entities:  # 약이 있으면 열린 질문이 아니다(규칙은 약이 있으면 늘 다른 라벨을 1개 이상 낸다)
        intent.remove(R.INTENT_OPEN)
        conflicts.append(CONFLICT_OPEN_DROPPED)
    claims = set(out.required_claims) | {_CLAIM_OF[n] for n in c.needed_claims}
    out = out.model_copy(update={"intent": intent, "required_claims": [x for x in R.CLAIM_TYPES if x in claims]})
    return Merged(out, added, removed, list(dict.fromkeys(conflicts)), scope_hint)


def route_with_classifier(text: str, dd: DrugDict, profile: Any = None, *, call: CallFn | None = None,
                          enabled: bool = ROUTER_LLM_CLASSIFY_DEFAULT, prompt: str | None = None, **route_kw: Any) -> ClassifyOutcome:
    """규칙 Router를 돌리고, `enabled`이고 `call`이 있으면 LLM 분류를 합친다. 꺼져 있으면 `route_input`과 결과가 같다(호출 0)."""
    rule = R.route_input(text, dd, profile, **route_kw)
    if not enabled or call is None:
        return ClassifyOutcome(rule)
    try:
        raw = call(build_messages(text, prompt))
    except Exception as exc:  # noqa: BLE001 - 분류 실패는 규칙 결과로 진행한다(서비스를 막지 않는다)
        return ClassifyOutcome(rule, error=f"CALL_FAILED:{type(exc).__name__}")
    chk = validate_output(raw, text)
    if chk.value is None:
        return ClassifyOutcome(rule, error=chk.error)
    mg = merge(rule, chk.value, text, dd)
    return ClassifyOutcome(mg.result, used=True, conditions=list(chk.value.conditions), added=mg.added, removed=mg.removed,
                           dropped_mentions=chk.dropped_mentions, conflicts=mg.conflicts, scope_hint=mg.scope_hint)


def make_openai_call(settings: Any, *, ledger: Any = None, bucket: str = "dev") -> CallFn:
    """실제 모델(`gpt-6-luna`, Chat Completions, strict 구조화 출력) 호출 함수를 만든다. **만들기만 하고 부르지 않는다.**
    원장 guard·비용 기록은 `llm.LedgerCallback`이 한다. 시험은 이 함수를 쓰지 않는다(가짜 `call`을 주입한다)."""
    from app.agent import llm

    cb = llm.LedgerCallback(ledger, bucket=bucket, estimate_usd=EST_OUT_TOKENS * llm.PRICE_OUT / 1e6 + EST_IN_TOKENS * llm.PRICE_IN / 1e6)
    model = llm.make_chat_model(settings, purpose="summary", callbacks=[cb]).with_structured_output(
        classification_json_schema(), method="json_schema", strict=True)

    def call(messages: list[dict[str, str]]) -> Any:
        return model.invoke([(m["role"], m["content"]) for m in messages])

    call.ledger_callback = cb  # type: ignore[attr-defined]
    return call


# 비용 어림(실측 전): 시스템 프롬프트 약 900토큰 + 질문 약 60토큰, 출력 약 120토큰. 단가는 `llm.PRICE_IN·PRICE_OUT`.
EST_IN_TOKENS = 1000
EST_OUT_TOKENS = 150


def estimate_usd(n_questions: int) -> float:
    from app.agent import llm

    return n_questions * llm.estimate_cost_usd(EST_IN_TOKENS, EST_OUT_TOKENS)


# --------------------------------------------------------------------------- 개발셋 실측 CLI(사용자 승인 뒤에만 `--yes`로 실호출)

def summarize(rows: list[dict[str, Any]], outcomes: list[ClassifyOutcome], rules: list[R.RouterResult]) -> dict[str, Any]:
    """개발셋 문항(`question`·`products`)별 규칙 결과와 분류기 결과를 같은 정의로 센다(k/n). 질문 문장은 싣지 않는다."""
    def counts(results: list[R.RouterResult]) -> dict[str, Any]:
        hit = tot = noise = amb = 0
        for row, r in zip(rows, results, strict=True):
            prods = [p for p in row.get("products") or [] if p]
            tot += len(prods)
            hit += sum(1 for p in prods if any(_covers(p, e.raw) for e in r.entities))
            noise += sum(1 for e in r.entities if not any(_covers(p, e.raw) for p in prods))
            amb += int(r.ambiguous)
        return {"product_recall": [hit, tot], "noise_entities": noise, "clarify": [amb, len(results)]}

    def per_item(row: dict[str, Any], r: R.RouterResult) -> tuple[int, int]:
        prods = [p for p in row.get("products") or [] if p]
        return (sum(1 for p in prods if any(_covers(p, e.raw) for e in r.entities)),
                sum(1 for e in r.entities if not any(_covers(p, e.raw) for p in prods)))

    # 문항 단위 판정(측정 전 고정): 악화 = 기대 약 포착 수가 줄었거나, 모호 문항의 되묻기가 사라짐.
    # 개선 = 악화가 아니면서 포착 수가 늘었거나 잡음 엔티티가 줄었음. 그 밖은 같음.
    better = worse = 0
    worse_ids: list[str] = []
    for row, ru, o in zip(rows, rules, outcomes, strict=True):
        (h0, n0), (h1, n1) = per_item(row, ru), per_item(row, o.result)
        lost_clarify = row.get("composition_group") == "모호" and ru.ambiguous and not o.result.ambiguous
        if h1 < h0 or lost_clarify:
            worse += 1
            worse_ids.append(str(row.get("id", "")))
        elif h1 > h0 or n1 < n0:
            better += 1
    return {"rule": counts(rules), "classifier": counts([o.result for o in outcomes]),
            "items_better": [better, len(rows)], "items_worse": [worse, len(rows)], "worse_ids": worse_ids,
            "used": [sum(o.used for o in outcomes), len(outcomes)], "errors": sorted({o.error for o in outcomes if o.error}),
            "added": sum(len(o.added) for o in outcomes), "removed": sum(len(o.removed) for o in outcomes),
            "dropped_mentions": sum(len(o.dropped_mentions) for o in outcomes),
            "conflicts": dict(sorted(Counter(c for o in outcomes for c in o.conflicts).items())),
            "scope_hint": sum(o.scope_hint for o in outcomes)}


def main(argv: list[str] | None = None) -> int:
    """`PYTHONPATH=. python -m app.agent.router_classify --dict <drug_dict.json> --max-usd 0.05 [--yes]`.
    `--yes`가 없으면 호출 0으로 어림 비용만 낸다. 개발셋만 읽는다(시험셋 `*.SEALED.jsonl`은 받지 않는다)."""
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dict", required=True, type=Path)
    ap.add_argument("--dev-set", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation" / "eval_set" / "dev_set.jsonl")
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--yes", action="store_true", help="실제 모델을 부른다(사용자 승인 뒤에만)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if "SEALED" in a.dev_set.name or not a.dev_set.name.startswith("dev"):
        ap.error("개발셋(dev_*.jsonl)만 받는다")
    rows = [json.loads(x) for x in a.dev_set.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r.get("set", "dev") == "dev"]
    est = estimate_usd(len(rows))
    print(f"문항 {len(rows)} · 어림 비용 {est:.4f} USD · 상한 {a.max_usd:.4f} USD")
    if not a.yes:
        return 0
    if est > a.max_usd:
        print("어림 비용이 상한을 넘어 시작하지 않는다")
        return 2
    from app.config import Settings
    from app.llm.ledger import BudgetExceeded

    dd = DrugDict.load(a.dict)
    call = make_openai_call(Settings())
    cb = call.ledger_callback  # type: ignore[attr-defined]
    outcomes: list[ClassifyOutcome] = []
    rules: list[R.RouterResult] = []
    for row in rows:
        rules.append(R.route_input(row["question"], dd))
        if cb.cost_usd >= a.max_usd:
            outcomes.append(ClassifyOutcome(rules[-1], error="BUDGET_STOP"))
            continue
        try:
            outcomes.append(route_with_classifier(row["question"], dd, call=call, enabled=True))
        except BudgetExceeded:
            outcomes.append(ClassifyOutcome(rules[-1], error="BUDGET_STOP"))
    summary = {**summarize(rows, outcomes, rules), "calls": cb.calls, "cost_usd": round(cb.cost_usd, 6), "prompt": PROMPT_ID}
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
