"""AG-16 C1 고정 파이프라인 노드. 도구를 부르는 순서·횟수를 **코드**가 정한다(모델은 요약 문장만 만든다, RFP-23 §5.2).

재사용(복사 금지): `guardrail_in`·`router`·`validator`·`finalize` 본문과 도구 실행 본문(`tools`)은 ReAct 그래프 `graph.nodes.make_raw_nodes`의 것을 그대로 부른다.
도구 단계 노드는 "모델이 냈을 도구 호출"을 코드로 만들어(`AIMessage.tool_calls`) 공유 `tools` 본문에 넘기므로, 인자 스키마(ARG_SCHEMA)·도구 출력 계약·
상태 키 제한(H8)·도구 결과 인젝션 검사·도구 span(L2)이 C2와 같은 코드로 동작한다(RFP-33-03 A: 기준선 하네스 장치는 C1·C1+·C2 공통).

고정 규칙(비교 중에 바꾸지 않는다, RFP 9.6절):
- identify_drug: Router가 찾은 약 언급마다 1회. 언급이 없으면 호출 0.
- 예외 규칙 1: 식별된 약(Router RESOLVED ∧ identify FOUND)이 0건이면 요약 호출 없이 `finalize`로 간다(미식별 안내는 코드 문구).
- 예외 규칙 2: Router가 되묻기(`ambiguous`)로 판정하면 `finalize`로 간다(되묻기 카드). ReAct와 같은 Router 코드다.
- check_contraindications: 식별된 약 전부를 한 번에(제품은 `item_seq`, 성분명은 `name`), 나이·임신은 Router 프로필에서.
- search_reason: 판정된(FOUND) 병용 쌍의 성분쌍(`pair_ids`)·임부/연령 성분코드(`ingr_codes`)로만 찾는다. 판정 항목이 없으면 호출 0
  (사유는 판정 뒤에만 필요하다, `router.CLAIM_CONTRA_REASON` 주석과 같은 원칙).
- search_label: 식별된 약마다 1회. 제품은 `item_seq`, 성분명은 `ingredient_code`(도구 계약이 `NO_PRODUCT_INFO`로 돌려준다, H17).
- model: 요약 호출 1회(+검증 실패 되감기 1회, 공유 Validator 규칙). 도구 선택 호출은 없다.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph.metered import unwrap_summary
from app.agent.graph.nodes import GraphDeps, _summary_messages, make_raw_nodes
from app.agent.pipeline.state import (
    EVENT_STEP,
    EVENT_SUMMARY,
    EVENT_UNIDENTIFIED,
    RULE_C1,
    STEP_CONTRA,
    STEP_IDENTIFY,
    STEP_LABEL,
    STEP_REASON,
    PipelineState,
)
from app.agent.tools.schemas import KIDS_CODE_RE, MAX_DRUGS
from app.agent.tools.search_common import MAX_QUERY_LEN
from app.agent.tools.search_reason import MAX_PAIRS
from app.tools.drug_dict import MATCHED_BY_INGREDIENT

MAX_INGR_CODES = 8  # `SearchReasonArgs.ingr_codes` 상한과 같다
_WS_RE = re.compile(r"\s+")


def clean_query(text: str | None) -> str | None:
    """질문 문장 → 검색 질의. 제어 문자를 빼고(도구 인자 검증 `no_control`) 공백을 하나로, 길이 상한까지. 비면 None."""
    s = "".join(c for c in (text or "") if not unicodedata.category(c).startswith("C"))
    s = _WS_RE.sub(" ", s).strip()[:MAX_QUERY_LEN].strip()
    return s or None


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def identified_drugs(state: PipelineState) -> list[dict[str, Any]]:
    """식별된 약: Router가 확정한 엔티티(RESOLVED) 중 `identify_drug`가 FOUND로 돌려준 것. 제품은 `item_seq`, 성분명은 조회 문자열(`subject`)로 맞춘다.
    반환 항목: `{"name", "item_seq"(성분이면 None), "kids_codes", "unit"}`. 판정이 아니라 다음 단계의 입력 정리다."""
    found = [it for it in state.get("evidence") or [] if isinstance(it, dict) and it.get("kind") == "identify" and it.get("status") == "FOUND"]
    by_seq = {str(it["item_seq"]): it for it in found if it.get("item_seq")}
    by_ingr = [it for it in found if it.get("matched_by") == MATCHED_BY_INGREDIENT]
    out: list[dict[str, Any]] = []
    for e in state.get("entities") or []:
        if not isinstance(e, dict) or e.get("status") != "RESOLVED" or not e.get("raw"):
            continue
        if e.get("item_seq"):
            it = by_seq.get(str(e["item_seq"]))
            if it is not None:
                out.append({"name": e["raw"], "item_seq": str(e["item_seq"]), "kids_codes": list(it.get("kids_codes") or []), "unit": "product"})
        elif e.get("matched_by") == MATCHED_BY_INGREDIENT:
            it = next((x for x in by_ingr if e["raw"] in (x.get("subject") or [])), None)
            if it is not None:
                out.append({"name": e["raw"], "item_seq": None, "kids_codes": list(it.get("kids_codes") or []), "unit": "ingredient"})
    return out[:MAX_DRUGS]


def _kids(codes: Any) -> list[str]:
    return [str(c) for c in (codes or []) if KIDS_CODE_RE.match(str(c))]


def make_pipeline_nodes(deps: GraphDeps) -> dict[str, Callable[[PipelineState], dict[str, Any]]]:
    shared = make_raw_nodes(deps)  # ReAct 노드 본문(코드 공유). 쓰기 제한·계측은 `build.py`가 `guard_node`로 입힌다
    run_tools = shared["tools"]

    def run_step(state: PipelineState, step: str, calls: list[dict[str, Any]], *, skipped: str | None = None) -> dict[str, Any]:
        """코드가 만든 도구 호출을 공유 `tools` 본문에 넘긴다. 호출이 없으면 단계 기록만 남긴다."""
        ev: dict[str, Any] = {"rule": RULE_C1, "event": EVENT_STEP, "step": step, "n_calls": len(calls)}
        if skipped:
            ev["skipped"] = skipped
        if not calls:
            return {"step": step, "events": [ev]}
        ai = AIMessage(content="", tool_calls=calls)
        upd = run_tools({**state, "messages": [*(state.get("messages") or []), ai]})
        return {**upd, "messages": [ai, *upd.get("messages", [])], "step": step, "events": [ev, *upd.get("events", [])]}

    def identify_drug(state: PipelineState) -> dict[str, Any]:
        raws = list(dict.fromkeys(str(e["raw"]) for e in state.get("entities") or [] if isinstance(e, dict) and e.get("raw")))
        calls = [_call("identify_drug", {"name": r}, f"c1-identify-{i}") for i, r in enumerate(raws)]
        return run_step(state, STEP_IDENTIFY, calls, skipped=None if calls else "NO_DRUG_MENTION")

    def check_contraindications(state: PipelineState) -> dict[str, Any]:
        drugs = identified_drugs(state)
        if not drugs:
            return run_step(state, STEP_CONTRA, [], skipped="NO_IDENTIFIED")
        args: dict[str, Any] = {"drugs": [{"item_seq": d["item_seq"]} if d["item_seq"] else {"name": d["name"]} for d in drugs]}
        prof = state.get("profile") or {}
        if prof.get("age_years") is not None:
            args["age"] = {"value": float(prof["age_years"]), "unit": "세"}
        if prof.get("pregnant") is True:
            args["pregnancy"] = True
        return run_step(state, STEP_CONTRA, [_call("check_contraindications", args, "c1-contra-0")])

    def search_reason(state: PipelineState) -> dict[str, Any]:
        q = clean_query(state.get("question"))
        ev = [it for it in state.get("evidence") or [] if isinstance(it, dict) and it.get("status") == "FOUND"]
        pairs = sorted({"+".join(sorted(cc)) for it in ev if it.get("kind") == "contra_pair"
                        for cc in [_kids(it.get("cause_codes"))] if len(cc) == 2 and cc[0] != cc[1]})[:MAX_PAIRS]
        singles = [it for it in ev if it.get("kind") in ("pregnancy", "age")]
        codes = sorted({c for it in singles for c in _kids(it.get("cause_codes"))})[:MAX_INGR_CODES]
        extra = {"query": q} if q else {}
        calls: list[dict[str, Any]] = []
        if pairs:
            calls.append(_call("search_reason", {"pair_ids": pairs, "kinds": ["combo"], **extra}, "c1-reason-pair"))
        if codes:
            kinds = sorted({str(it["kind"]) for it in singles})
            calls.append(_call("search_reason", {"ingr_codes": codes, "kinds": kinds, **extra}, "c1-reason-single"))
        return run_step(state, STEP_REASON, calls, skipped=None if calls else "NO_FOUND_CONTRA")

    def search_label(state: PipelineState) -> dict[str, Any]:
        q = clean_query(state.get("question"))
        calls: list[dict[str, Any]] = []
        for i, d in enumerate(identified_drugs(state)):
            if d["item_seq"]:
                args: dict[str, Any] = {"item_seq": d["item_seq"]}
            else:  # 성분명: 제품 라벨이 없다는 계약 응답(NO_PRODUCT_INFO)을 그대로 받는다(H17). 코드가 없으면 부르지 않는다
                code = next(iter(_kids(d["kids_codes"])), None)
                if code is None:
                    continue
                args = {"ingredient_code": code}
            if q:
                args["query"] = q
            calls.append(_call("search_label", args, f"c1-label-{i}"))
        return run_step(state, STEP_LABEL, calls, skipped=None if calls else "NO_IDENTIFIED")

    def model(state: PipelineState) -> dict[str, Any]:
        """고정 순서의 유일한 LLM 호출: 구조화 요약(ReAct의 요약 호출과 같은 메시지 구성). 되감기 지시(`[HARNESS]` 사람 메시지)는 뒤에 붙인다."""
        n = state.get("call_count", 0)
        rewinds = [m for m in state.get("messages") or [] if isinstance(m, HumanMessage)]
        draft, raw = unwrap_summary(deps.summary_model.invoke([*_summary_messages(state, deps), *rewinds]))
        msg = raw if isinstance(raw, AIMessage) else AIMessage(content="")  # 토큰·캐시 계측용(가짜 요약은 빈 메시지, 내용은 쓰지 않는다)
        return {"messages": [msg], "call_count": n + 1, "draft": draft, "events": [{"rule": RULE_C1, "event": EVENT_SUMMARY, "call": n + 1}]}

    def finalize(state: PipelineState) -> dict[str, Any]:
        upd = shared["finalize"](state)
        if state.get("step") == STEP_IDENTIFY:  # 예외 규칙 1로 왔다(식별 0건). 문구는 공유 `finalize`가 항목 상태로 만든다
            n_ent = len(state.get("entities") or [])
            upd["events"] = [{"rule": RULE_C1, "event": EVENT_UNIDENTIFIED, "n_entities": n_ent}, *upd.get("events", [])]
        return upd

    return {"guardrail_in": shared["guardrail_in"], "router": shared["router"], "identify_drug": identify_drug,
            "check_contraindications": check_contraindications, "search_reason": search_reason, "search_label": search_label,
            "model": model, "validator": shared["validator"], "finalize": finalize}


# --------------------------------------------------------------------------- 간선 함수
def after_identify(state: PipelineState) -> str:
    return "check_contraindications" if identified_drugs(state) else "finalize"


__all__ = ["after_identify", "clean_query", "identified_drugs", "make_pipeline_nodes"]
