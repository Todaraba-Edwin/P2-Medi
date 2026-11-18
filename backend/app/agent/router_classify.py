"""AG-05 Router의 프롬프트 분류(LLM 보조) 부분. **기본 꺼짐**(`ROUTER_LLM_CLASSIFY_DEFAULT = False`).

AG-05 §2의 (프롬프트 + 스키마 검증) 조건들(엔티티 추출·유형 라벨·`open` 분류·필요한 주장 유형)을 위한 분류기다. 규칙(`router.route_input`)이
먼저 돌고, 이 모듈은 그 결과에 LLM 분류를 **덧붙이기만** 한다. 서비스·평가 기본 경로(`graph/nodes.py`·`pipeline/**`)는 이 모듈을 부르지 않는다.
기준선(AG-11) 뒤 개선(AG-13, 개발셋만) 후보다. 켜는 곳(연결)은 이 작업 범위 밖이라 보고의 "연결 초안"에 적었다.

경계(코드가 정하는 것):
  - LLM 출력은 `RouterClassification` 스키마로 검증하고, 질문에 글자 그대로 없는 약 이름·질환 낱말은 버린다(지어낸 이름 차단).
  - 약 이름 확정은 늘 사전(`DrugDict`)이 한다. LLM이 더 찾은 약은 사전 정확·정규화 일치로 하나로 정해질 때만 엔티티로 더한다.
  - LLM이 약으로 보지 않은 규칙 엔티티는 **확정(RESOLVED)이 아닐 때만** 뺀다(잡음 낱말: "안전", "소화" 등). 확정된 약은 빼지 않는다.
  - 연령·임신은 규칙 값이 우선이다. 규칙이 못 찾았을 때만 LLM 값(yes·no)을 쓰고, possible·unknown은 쓰지 않는다.
  - 유형 라벨·주장 유형은 규칙 결과에 더한다(빼지 않는다). `out_of_scope`는 라벨로만 남는다(거절은 Guardrail 몫).
  - 검증에 실패하거나 호출이 실패하면 규칙 결과를 그대로 쓴다(`ClassifyOutcome.used=False`).
  - 질문·출력은 저장·로그하지 않는다. 이 모듈은 외부 호출을 직접 하지 않는다(`call` 함수를 주입받는다).
"""

from __future__ import annotations

import json
import re
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


def _covers(mention: str, raw: str) -> bool:
    a, b = _squash(mention), _squash(raw)
    return bool(a) and bool(b) and (a in b or b in a)


def merge(rule: R.RouterResult, c: RouterClassification, text: str, dd: DrugDict) -> tuple[R.RouterResult, list[str], list[str]]:
    """규칙 결과에 검증된 분류를 합친다(경계는 모듈 docstring). (결과, 더한 raw, 뺀 raw)."""
    ents = list(rule.entities)
    removed = [e.raw for e in ents if e.status != R.ST_RESOLVED and not any(_covers(m, e.raw) for m in c.drug_mentions)]
    ents = [e for e in ents if e.raw not in removed]
    added: list[str] = []
    seen_seq = {e.item_seq for e in ents if e.item_seq}
    for m in c.drug_mentions:
        if len(ents) >= R.MAX_DRUGS:
            break
        if any(_covers(m, e.raw) for e in ents):
            continue
        used, r, strength = R.lookup_mention(dd, R.Mention(m))
        e = R._entity(used, r, strength)
        if e.status != R.ST_RESOLVED or r.match_type not in (MATCH_EXACT, MATCH_NORMALIZED):
            continue  # 사전이 하나로 정하지 못한 LLM 제안은 더하지 않는다(되묻기를 새로 만들지 않는다)
        if e.item_seq and e.item_seq in seen_seq:
            continue
        seen_seq.add(e.item_seq)
        ents.append(e)
        added.append(e.raw)
    prof = rule.profile
    if (prof.age_years is None and c.age_years is not None) or (prof.pregnant is None and c.pregnancy in ("yes", "no")):
        prof = R.ProfileState(age_years=prof.age_years if prof.age_years is not None else c.age_years,
                              pregnant=prof.pregnant if prof.pregnant is not None else c.pregnancy == "yes", source="question")
    out = R.assemble(text, ents, prof, truncated=rule.truncated, emergency=rule.emergency, guardrail_route=rule.guardrail_route,
                     dict_version=rule.dict_version)
    labels = set(out.intent) | set(c.intent)
    intent = [x for x in _INTENT_ORDER if x in labels]
    if len(intent) > 1 and R.INTENT_OPEN in intent and out.entities:
        intent.remove(R.INTENT_OPEN)  # 약이 있으면 열린 질문이 아니다
    claims = set(out.required_claims) | {_CLAIM_OF[n] for n in c.needed_claims}
    out = out.model_copy(update={"intent": intent, "required_claims": [x for x in R.CLAIM_TYPES if x in claims]})
    return out, added, removed


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
    res, added, removed = merge(rule, chk.value, text, dd)
    return ClassifyOutcome(res, used=True, conditions=list(chk.value.conditions), added=added, removed=removed,
                           dropped_mentions=chk.dropped_mentions)


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

    return {"rule": counts(rules), "classifier": counts([o.result for o in outcomes]),
            "used": [sum(o.used for o in outcomes), len(outcomes)], "errors": sorted({o.error for o in outcomes if o.error}),
            "added": sum(len(o.added) for o in outcomes), "removed": sum(len(o.removed) for o in outcomes),
            "dropped_mentions": sum(len(o.dropped_mentions) for o in outcomes)}


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
