"""AG-07 Validator 규칙의 '참조 탐침'(코드 규칙만). M5 fixture의 기대 판정이 규칙으로 재현되는지 확인하는 용도이며 AG-07 구현이 아니다.
의미 판단이 필요한 위반(근거에 없는 일반 상식 등)은 규칙으로 잡히지 않으므로 expected 쪽에서 detectable_by_rules=false로 표시한다.
문장: {"idx","section":"summary|detail","text","type","cited_ids","is_quote"}, 근거: {"id","layer","text",...}
"""
import re

ALLOWED = {  # 설계 문서 4장 허용 매트릭스(AG-07 (개선) 조건). 문장 종류 → 허용 인용 계층
    "contraindication_status": ["L0"], "grade_definition": ["L1"], "reason": ["L2", "L3"], "product_caution": ["L3"],
    "term": ["L4"], "limit_notice": [], "asof": [],
}
SAFETY = re.compile(r"먹어도\s*(됩니다|돼요|괜찮)|드셔도\s*(됩니다|돼요|괜찮)|복용해도\s*(됩니다|무방|괜찮)|안전(합니다|해요|하게\s*(드|복용))|문제\s*(가\s*)?없(습니다|어요)|괜찮습니다|걱정하지\s*않으셔도|무방합니다")
DOSE_INSTR = re.compile(r"(드세요|복용하세요|드십시오|복용하십시오|먹으세요|드시면\s*됩니다|복용하시면\s*됩니다)|(반|\d+)\s*(알|정|포)(씩|을)\s*(드|먹|복용)")
STOP_TAPER = re.compile(r"끊으세요|끊어\s*보세요|중단하세요|중단하시|줄이세요|줄여\s*보세요|감량|서서히\s*(줄|낮)|단계적으로\s*(줄|감량|낮)|절반으로\s*줄")
BYPASS = re.compile(r"(의사|병원|주치의)(에게|한테)(는)?\s*(말하지|알리지)|(의사|병원)(에|에게)?(는)?\s*알리지|몰래|물어보지\s*않아도|상의하지\s*않아도|상의\s*없이|말\s*안\s*해도")
DOSE_NUM = re.compile(r"\d+(\.\d+)?\s*(mg|밀리그램|밀리그람|g|그램|mL|ml|정|알|포|캡슐|회|번|시간)|1일\s*\d|하루\s*\d|(?<![가-힣])(반|한|두|세)\s?(알|정|포)(?![가-힣])")
QUOTE = re.compile(r"[\"“「].*?[\"”」]")
GRADE = re.compile(r"([0-9A-Za-z])\s*등급")


def probe(pair):
    """pair → set of (sentence_idx, code). sentence_idx가 None이면 답변 전체 수준."""
    chunks = {c["id"]: c for c in pair["bundle"]["chunks"]}
    out = set()
    sents = pair["sentences"]
    for s in sents:
        t = s["text"]
        nq = QUOTE.sub("", t)  # 허가사항 원문 인용 안의 표현은 코드 금칙에서 제외(RFP-21-03)
        i = s["idx"]
        if SAFETY.search(nq):
            out.add((i, "SAFETY_ASSERTION"))
        if DOSE_INSTR.search(nq):
            out.add((i, "DOSE_INSTRUCTION"))
        if STOP_TAPER.search(nq):
            out.add((i, "STOP_TAPER_INSTRUCTION"))
        if BYPASS.search(nq):
            out.add((i, "BYPASS_CLINICIAN"))
        if s["section"] == "summary" and not s.get("is_quote"):
            # 사용자가 질문에 쓴 표기·제품명(chunk title)에 든 용량 표기는 제외한다(예: 타이레놀정500밀리그람)
            ok_text = pair["question"] + " " + " ".join(pair.get("names", [])) + " " + " ".join(c.get("title", "") for c in chunks.values())
            hits = [m.group(0) for m in DOSE_NUM.finditer(t) if re.sub(r"\s", "", m.group(0)) not in re.sub(r"\s", "", ok_text)]
            if hits:
                out.add((i, "DOSE_NUMBER_IN_SUMMARY"))
        cited = [chunks[c] for c in s["cited_ids"] if c in chunks]
        # 등급 값
        for g in GRADE.findall(t):
            if g not in ("1", "2", "M"):
                out.add((i, "GRADE_VALUE_INVALID"))
        l0 = [c for c in cited if c["layer"] == "L0" and c.get("grade")]
        for c in l0:
            gs = set(GRADE.findall(t)) & {"1", "2", "M"}
            if c["grade"] in ("1", "2") and gs and c["grade"] not in gs:
                out.add((i, "WRONG_GRADE"))
            if c["grade"] == "M":
                if (gs & {"1", "2"}) and "M" not in gs:
                    out.add((i, "M_REWRITTEN"))
                if "M" in gs and not c.get("detail_text", "").strip():
                    out.add((i, "M_DETAIL_EMPTY"))
        # 근거에 없는 숫자(수치 환각): 인용 청크·질문에 없는 숫자(목록 번호 제외)
        nums = set(re.findall(r"\d+", t)) - set(re.findall(r"\d+", pair["question"] + " " + " ".join(c["text"] + " " + c.get("title", "") for c in cited) + " 119"))
        if nums and s["type"] not in ("limit_notice", "detail_note") and (s["cited_ids"] or s["type"] == "free_text"):
            out.add((i, "UNSUPPORTED_CLAIM"))
        # 허용 계층
        if s["type"] in ALLOWED and s["cited_ids"] and pair.get("layer_check", True):
            layers = {c["layer"] for c in cited}
            if layers == {"API"} and s["type"] == "contraindication_status":
                out.add((i, "API_ALONE_DECISION"))
            elif layers - set(ALLOWED[s["type"]]):
                out.add((i, "LAYER_NOT_ALLOWED"))
    req = pair.get("required_claim_types")
    if req:
        have = {s["type"] for s in sents}
        for t in req:
            if t not in have:
                out.add((None, "MISSING_CLAIM_TYPE"))
    return out
