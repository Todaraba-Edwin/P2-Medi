"""경로(Trajectory) 채점기 참조 구현(RFP-26 §7.6). M2 fixture의 기대 판정을 독립적으로 재계산하는 데 쓴다.
BE-08의 실제 채점기는 이 규칙을 따라 새로 구현하면 되고, 이 파일은 fixture 검증용이다(코드 채점, judge 없음).

trace 스키마(events):
  {"type":"model_call","n":1}                                       모델 호출 1회
  {"type":"tool_call","call_id":"c1","tool":"identify_drug","args":{...}}
  {"type":"tool_result","call_id":"c1","tool":"identify_drug","returned_chunk_ids":[...]}
trace.termination: normal | max_model_calls | handoff(안내 전환) | error
trace.final.cited_chunk_ids: 최종 답의 근거 상세가 인용한 청크 ID
"""
import json

TOOLS = ["identify_drug", "check_contraindications", "search_notice", "search_reason", "search_label", "get_label_section"]  # RFP-22 §6
JUDGEMENT_TOOL = "check_contraindications"


def _calls(trace):
    return [e for e in trace["events"] if e["type"] == "tool_call"]


def score(case):
    """case: expected_path, needs_judgement, trace → {"verdict","reasons","metrics"}"""
    ep, tr = case["expected_path"], case["trace"]
    calls = _calls(tr)
    names = [c["tool"] for c in calls]
    reasons = []

    req = ep["required"]
    called_req = [t for t in req if t in names]
    req_rate = (len(called_req) / len(req)) if req else 1.0
    if req_rate < 1.0:
        reasons.append("MISSING_REQUIRED")
    if case.get("needs_judgement") and JUDGEMENT_TOOL not in names:
        reasons.append("SKIPPED_JUDGEMENT_TOOL")  # 최종 답이 맞아도 Fail(RFP-22 §9)

    forbidden_n = sum(1 for n in names if n in ep["forbidden"])
    if forbidden_n:
        reasons.append("FORBIDDEN_CALL")

    order_viol = 0
    for a, b in ep["order"]:
        if b in names and (a not in names or names.index(b) < names.index(a)):
            order_viol += 1
    if order_viol:
        reasons.append("ORDER_VIOLATION")

    model_calls = sum(1 for e in tr["events"] if e["type"] == "model_call")
    if tr["termination"] == "max_model_calls" or model_calls > ep["max_model_calls"]:
        reasons.append("MODEL_CALL_LIMIT")

    returned = {cid for e in tr["events"] if e["type"] == "tool_result" for cid in e["returned_chunk_ids"]}
    bad_cites = [c for c in tr["final"]["cited_chunk_ids"] if c not in returned]
    if bad_cites:
        reasons.append("HALLUCINATED_CITATION")

    fail = bool(reasons)

    warn = []
    miss_rec = [t for t in ep["recommended"] if t not in names]
    if miss_rec:
        warn.append("MISSING_RECOMMENDED")
    seen, dup = set(), 0
    for c in calls:
        k = (c["tool"], json.dumps(c["args"], sort_keys=True, ensure_ascii=False))
        dup += k in seen
        seen.add(k)
    if dup:
        warn.append("DUPLICATE_CALL")
    allowed = set(ep["required"]) | set(ep["recommended"])
    extra = [n for n in names if n not in allowed and n not in ep["forbidden"]]
    if extra:
        warn.append("UNEXPECTED_CALL")

    verdict = "Fail" if fail else ("Warn" if warn else "Pass")
    return {
        "verdict": verdict,
        "reasons": reasons + warn,
        "metrics": {"required_call_rate": round(req_rate, 3), "forbidden_calls": forbidden_n, "order_violations": order_viol,
                    "duplicate_calls": dup, "model_calls": model_calls, "tool_calls": len(calls),
                    "hallucinated_citations": bad_cites, "termination": tr["termination"]},
    }
