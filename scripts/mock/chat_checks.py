"""M1 /chat 응답 fixture 검증기. 코드가 정하는 규칙(PRD 15.3, BE-06, RFP-21-03, RFP-28-01)을 문장·구조에 적용한다.
- check_sentence: LLM이 쓴 요약 한 문장이 규칙을 지키는지(가부 단정·지시·용량 숫자·근거에 없는 숫자/등급/코드·의료진 우회).
- check_response / check_stream: 응답 한 건과 스트리밍 이벤트 순서의 구조 검사.
- check_files: 인용(citation)이 data/ 파일·API 샘플 원문과 일치하는지 파일을 다시 읽어 확인한다.
"""
import json, re
from pathlib import Path
import facts as F

ROUTES = {"answer", "clarify", "refuse", "no_evidence", "emergency_only"}
STAGES = ["drug_lookup", "contraindication_check", "evidence_search"]

# --- 요약 문장 규칙 ---
QUOTE = re.compile(r"[\"“「'‘].*?[\"”」'’]")
VERDICT = re.compile(r"(먹으면|복용하면|드시면|함께\s*먹으면|같이\s*먹으면|먹여서는|먹어서는)\s*안\s*(됩니다|돼요|되며)|안\s*됩니다|안\s*돼요|(먹어도|드셔도|복용해도|줘도|먹여도|써도|사용해도)\s*(됩니다|돼요|되겠습니다|좋습니다|괜찮)|괜찮습니다|괜찮아요|문제\s*(가\s*)?없(습니다|어요)|"
                     r"안전(합니다|해요|하니|하므로|합니다만)|위험하지\s*않|복용\s*가능|복용하셔도|드시면\s*됩니다|먹으면\s*됩니다|먹지\s*않아도\s*됩니다")
COMMAND = re.compile(r"(?<!주)(세요|십시오)")  # '확인해 주세요'(주세요)만 허용
STOP_ADVICE = re.compile(r"중단|끊(으|어|지)|줄이(세요|십시오|면|려면)|감량|단계적으로|서서히|늘리|늘려")
BYPASS = re.compile(r"말하지\s*(마|않)|알리지\s*(마|않)|숨기|몰래|상의\s*없이")
DOSE = re.compile(r"\d+(\.\d+)?\s*(mg|MG|밀리그램|밀리그람|마이크로그램|g|그램|mL|ml|cc|정|알|포|캡슐|방울|스푼|숟가락|회|번|시간|배)|(?<![가-힣])(반|한|두|세|네)\s?(알|정|포|스푼|숟가락)(?![가-힣])|1일|하루\s*\d|매\s*\d")
CODE = re.compile(r"\b\d{6}[A-Z]{3}\b|\b\d{8,9}\b|\bD\d{6}\b")
GRADE = re.compile(r"(\d|M)\s*등급")


def numbers(text):
    return set(re.findall(r"\d+", text))


def strip_names(text, names):
    for n in sorted(names, key=len, reverse=True):
        text = text.replace(n, "")
    return text


def _norm(t):
    return re.sub(r"[\s.,;·\"“”'‘’「」]", "", t)


ENDING = re.compile(r"(니다|세요|해요|이에요|예요|있어요|없어요|돼요|까요|가요|나요|죠)[.?!]?$")


def check_sentence(s, allowed_text, names, allowed_grades, mode="normal", must=()):
    """위반 목록을 돌려준다(빈 목록이면 통과). allowed_text: 질문+사실+인용 문자열 전체(허용 숫자의 출처)."""
    bad = []
    t = strip_names(s, names)
    nq = QUOTE.sub("", t)  # 따옴표 안(라벨 원문 인용)은 지시 표현 검사에서 뺀다
    if not s.strip():
        return ["빈 문장"]
    if VERDICT.search(nq):
        bad.append("가부·안전 단정")
    if COMMAND.search(nq):
        bad.append("복용 지시·명령형")
    if STOP_ADVICE.search(nq) and mode != "refuse_mention":
        bad.append("복용 중단·감량 표현")
    if BYPASS.search(nq):
        bad.append("의료진 우회 표현")
    if DOSE.search(t):
        bad.append("용량·횟수 숫자")
    if CODE.search(t):
        bad.append("코드·번호 노출")
    for g in GRADE.findall(t):
        if g not in allowed_grades:
            bad.append(f"근거에 없는 등급 {g}")
    extra = numbers(t) - numbers(allowed_text)
    if extra:
        bad.append(f"근거에 없는 숫자 {sorted(extra)}")
    # 따옴표 안은 원문 그대로여야 한다(요약·상세의 라벨 인용은 글자 그대로)
    blob = _norm(allowed_text)
    for q in re.findall(r"[\"“]([^\"”]{4,})[\"”]", s):
        if _norm(q) not in blob:
            bad.append(f"따옴표 인용이 원문과 다름: {q[:20]}")
    if re.search(r"등급\s*\d등급|[가-힣]정는|[가-힣]캡슐는|[가-힣]시럽는", t):
        bad.append("어색한 중복·조사 오류")
    # 존댓말 종결
    for part in re.split(r"(?<=[.?!])\s+", s.strip()):
        if part and not ENDING.search(part.strip()):
            bad.append(f"존댓말 종결이 아님: {part[-12:]}")
            break
    for m in must:
        if not re.search(m, s):
            bad.append(f"필수 표현 없음: {m}")
    return bad


# --- 구조 검사 ---
def check_response(r):
    e = []
    for k in ("summary", "detail", "citations", "fixed_notice", "emergency", "disclaimer", "route", "answer"):
        if k not in r:
            e.append(f"필드 없음: {k}")
    if e:
        return e
    if r["route"] not in ROUTES:
        e.append(f"route 값 이상: {r['route']}")
    if not r["fixed_notice"].strip() or "약국" not in r["fixed_notice"] or "약사" not in r["fixed_notice"]:
        e.append("fixed_notice에 약국·약사 안내 없음")
    if not r["disclaimer"].strip():
        e.append("disclaimer 비어 있음")
    em = r["emergency"]
    if em["detected"] and not (em.get("message") and "119" in em["message"] and em.get("tel") == "tel:119"):
        e.append("응급인데 119 안내·전화 링크 없음")
    if not em["detected"] and (em.get("message") or em.get("tel")):
        e.append("응급이 아닌데 119 안내가 있음")
    if r["mock"] is not True:
        e.append("mock 표시 없음")
    ids = {c["id"] for c in r["citations"]}
    if len(ids) != len(r["citations"]):
        e.append("citation id 중복")
    used = set()
    for p in r.get("summary_points", []):
        for i in p["evidence_ids"]:
            used.add(i)
            if i not in ids:
                e.append(f"요약 근거 id 없음: {i}")
    for d in r["detail"]:
        for i in d.get("citation_ids", []):
            used.add(i)
            if i not in ids:
                e.append(f"상세 근거 id 없음: {i}")
    for f in r.get("findings", []):
        for i in f.get("citation_ids", []):
            used.add(i)
            if i not in ids:
                e.append(f"findings 근거 id 없음: {i}")
    for c in r["citations"]:
        if not (c.get("as_of") or c.get("retrieved_at")):
            e.append(f"citation에 기준일·조회 시각 없음: {c['id']}")
    if r["route"] in ("answer",) and not r["citations"]:
        e.append("answer인데 citations 비어 있음")
    # 요약 전체 재검사(안전망): 고정 문구가 요약에 섞이지 않았는지, 용량 숫자
    allowed = "119 " + " ".join([r["question"]] + [c["quote"] for c in r["citations"]] + [json.dumps(c, ensure_ascii=False) for c in r["citations"]])
    names = r.get("_names", [])
    grades = {str(f.get("grade")) for f in r.get("findings", []) if f.get("grade")}
    if r["route"] != "clarify" or True:
        for line in r["summary"].split("\n"):
            line = re.sub(r"^\d+\.\s*", "", line)  # 목록 번호는 숫자 검사에서 뺀다
            bad = check_sentence(line, allowed, names, grades, mode="refuse_mention" if r["route"] == "refuse" else "normal")
            # 거절 문장에는 '복용 변경은 의사와 상의' 같은 표현이 정당하게 들어가므로 중단 표현만 완화(우회·용량·단정은 그대로 검사)
            if bad:
                e.append(f"요약 규칙 위반 {bad}: {line[:40]}")
    if r["route"] == "no_evidence" and any(re.search(r"금기\s*목록에\s*없", QUOTE.sub("", ln)) and not re.search(r"아니|다릅|구분", ln) for ln in r["summary"].split("\n")):
        e.append("근거 없음 응답이 '금기 목록에 없음'과 뒤섞임")
    if r["route"] == "refuse" and "진단" not in r["summary"] + r["fixed_notice"]:
        e.append("거절 이유(진단·처방 아님)가 없음")
    if r["route"] == "clarify":
        if "clarify" not in r or r["summary"].count("?") + r["summary"].count("？") != 1:
            e.append("되묻기는 질문이 정확히 1개여야 함")
    return e


def check_stream(events, resp):
    e = []
    names = [x["event"] for x in events]
    if names[-1] not in ("done", "error"):
        e.append("마지막 이벤트가 done/error가 아님")
    if resp["emergency"]["detected"]:
        if names[0] != "emergency":
            e.append("응급인데 첫 이벤트가 emergency가 아님")
    elif "emergency" in names:
        e.append("응급이 아닌데 emergency 이벤트가 있음")
    prog = [x["data"]["stage"] for x in events if x["event"] == "progress"]
    if resp["route"] == "answer":
        if prog != STAGES:
            e.append(f"answer의 진행 상태가 3단계 순서가 아님: {prog}")
    if [x for x in prog if x not in STAGES]:
        e.append("알 수 없는 진행 단계")
    if "answer" in names:
        if names.index("answer") < max([i for i, n in enumerate(names) if n == "progress"] or [-1]):
            e.append("answer가 progress보다 앞섬")
    seqs = [x["seq"] for x in events]
    if seqs != list(range(len(seqs))):
        e.append("seq가 0부터 연속이 아님")
    return e


# --- 파일 대조 ---
_idx = {}


def _index():
    if _idx:
        return _idx
    _idx["preg"] = {(r["제품코드"], r["금기등급"], r["고시번호"]) for r in F.rows(F.F_PREG)}
    _idx["preg_names"] = [r["제품명"] for r in F.rows(F.F_PREG)]
    _idx["age"] = {(r["제품코드"], r["특정연령"], r["고시번호"]) for r in F.rows(F.F_AGE)}
    _idx["age_names"] = [r["제품명"] for r in F.rows(F.F_AGE)]
    return _idx


def eyak_text():
    import glob
    out = {}
    for p in glob.glob(str(F.DATA / "api_samples" / "eyak__*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        items = (d.get("body") or {}).get("items") or []
        if isinstance(items, dict):
            items = items.get("item", [])
        for x in items:
            out.setdefault(x["itemSeq"], " ".join(str(v) for v in x.values()))
    return out


def check_files(r, combo_pairs, eyak, combo_hits=None):
    """citation의 key(파일 종류·제품코드·등급·고시번호)와 라벨 인용문이 원본과 맞는지 확인."""
    idx = _index()
    e = []
    for c in r["citations"]:
        k = c.get("key") or {}
        if k.get("csv") == "preg" and "absent" not in k:
            if (k["제품코드"], k["금기등급"], k["고시번호"]) not in idx["preg"]:
                e.append(f"임부금기 CSV에 없는 값: {c['id']}")
        elif k.get("csv") == "preg":
            if any(n.startswith(k["absent"]) for n in idx["preg_names"]):
                e.append(f"'목록에 없음'이라 했지만 CSV에 있음: {c['id']}")
        elif k.get("csv") == "age" and "absent" not in k:
            if (k["제품코드"], k["특정연령"], k["고시번호"]) not in idx["age"]:
                e.append(f"연령금기 CSV에 없는 값: {c['id']}")
        elif k.get("csv") == "age":
            if any(k["absent"] in n for n in idx["age_names"]):
                e.append(f"연령금기 '없음'이라 했지만 CSV에 있음: {c['id']}")
        elif k.get("csv") == "combo" and "absent" in k:
            if (combo_hits or {}).get(k["absent"], 1) != 0:
                e.append(f"병용금기 '없음'이라 했지만 CSV에 있음: {c['id']}")
        elif k.get("csv") == "combo":
            if (k["제품코드A"], k["제품코드B"], k["고시번호"]) not in combo_pairs:
                e.append(f"병용금기 CSV에 없는 쌍: {c['id']}")
        elif k.get("eyak"):
            src = eyak.get(k["eyak"])
            if src is None or c["quote"] not in src:
                e.append(f"e약은요 샘플 원문에 인용문 없음: {c['id']}")
        elif k.get("md"):
            txt = (F.ROOT / "P2-doc" / "MFDS_병용금기_지정규정_고시.md").read_text(encoding="utf-8")
            if c["quote"] not in txt:
                e.append(f"고시 정리본에 인용문 없음: {c['id']}")
    return e
