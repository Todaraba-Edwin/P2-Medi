"""M2 traces/: 에이전트 경로(trace) fixture. 코드만으로 만든다(API 호출 없음, 비용 0).
- 질문·제품은 개발셋 풀(data/credit_use/pool_dev.jsonl, 읽기 전용)과 RFP-21 §4 페르소나에서 가져온다. 시험셋은 열지 않는다.
- 기대 경로 스키마와 판정 규칙은 RFP-26 §7.6. 각 사례는 '의도한 판정'을 갖고, 독립 채점기(trajectory.score)가 같은 판정을 내는지 확인한다.
"""
import copy, json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import meta, trajectory as T  # noqa: E402

VER, SET = "m2-v1", "traces"
rnd = random.Random(20261105)
pool = [json.loads(l) for l in open(meta.ROOT / "data/credit_use/pool_dev.jsonl", encoding="utf-8")]  # 개발셋만
by = lambda t: [r for r in pool if r["type"] == t]
ALL = T.TOOLS
FULL = {"required": ["identify_drug", "check_contraindications"], "recommended": ["search_label"], "forbidden": [],
        "order": [["identify_drug", "check_contraindications"]], "max_model_calls": 8}


def ep(**kw):
    d = copy.deepcopy(FULL)
    d.update(kw)
    return d


# ---------- 경로 조립 도우미 ----------
class B:
    """trace 빌더. 모델 호출 → 도구 호출(들) → 결과를 쌓는다."""
    def __init__(self):
        self.ev, self.n, self.c = [], 0, 0

    def model(self):
        self.n += 1
        self.ev.append({"type": "model_call", "n": self.n})

    def tools(self, specs):
        """specs: [(tool, args, returned_ids)] — 한 번의 모델 호출이 도구를 병렬로 부른다."""
        self.model()
        ids = []
        for tool, args, ret in specs:
            self.c += 1
            cid = f"c{self.c}"
            ids.append((cid, tool, ret))
            self.ev.append({"type": "tool_call", "call_id": cid, "tool": tool, "args": args})
        for cid, tool, ret in ids:
            self.ev.append({"type": "tool_result", "call_id": cid, "tool": tool, "returned_chunk_ids": ret})

    def finish(self, kind, cited, termination="normal"):
        if termination != "max_model_calls":
            self.model()
        return {"events": self.ev, "model_calls": self.n, "termination": termination,
                "final": {"answer_kind": kind, "cited_chunk_ids": cited}}


def ids_for(rec):
    """풀 레코드의 값(성분코드·제품명)으로 청크 ID를 만든다. L0=판정 테이블, L2=사유, L3=라벨."""
    codes = rec.get("codes") or ["000000ATB"]
    kind = {"정상-임부": "preg", "오정보-임부": "preg", "정상-연령": "age", "정상-병용": "combo", "정상-응급": "preg"}.get(rec["type"], "none")
    drug = [f"cand:{c}" for c in codes]
    l0 = [f"L0:{kind}:{'+'.join(codes) if kind == 'combo' else c}" for c in (codes if kind != "combo" else [codes[0]])] if kind != "none" else [f"L0:none:{codes[0]}"]
    l2 = [f"L2:{kind}:{codes[0]}"]
    l3 = [f"L3:{codes[0]}:{s}" for s in ("atpn", "intrc")]
    return drug, l0, l2, l3


def normal_trace(rec, with_label=True):
    drug, l0, l2, l3 = ids_for(rec)
    b = B()
    prods = rec.get("products") or ["약"]
    b.tools([("identify_drug", {"name": p}, [drug[min(i, len(drug) - 1)]]) for i, p in enumerate(prods)])
    b.tools([("check_contraindications", {"ingredient_codes": rec.get("codes", []), "profile": {"pregnant": rec["type"].endswith("임부") or rec["type"].endswith("응급")}}, l0)])
    cited = list(l0)
    if with_label:
        b.tools([("search_label", {"drug_id": drug[0], "topic": "임부" if "임부" in rec["type"] else "연령·상호작용"}, l3[:2])])
        cited += l3[:1]
    return b, cited


def case(cid, ctype, rec_q, qtype, path, trace, needs_j, intended, persona=None, note=""):
    c = {"case_id": cid, "case_type": ctype, "question": rec_q, "question_type": qtype, "persona": persona,
         "expected_path": path, "needs_judgement": needs_j, "trace": trace, "intended": intended, "scenario": note,
         "synthetic_metrics_note": "지연·토큰은 만들지 않았다(합성 trace). 모델 호출 수만 events에서 센다."}
    s = T.score(c)
    ok_v = s["verdict"] == intended["verdict"]
    ok_r = set(intended["reasons"]) <= set(s["reasons"])
    assert ok_v and ok_r, (cid, intended, s)
    c["expected_verdict"] = {"verdict": s["verdict"], "reasons": s["reasons"]}
    c["expected_metrics"] = s["metrics"]
    del c["intended"]
    return c


cases = []
n = {"i": 0}


def nid(prefix):
    n["i"] += 1
    return f"{prefix}-{n['i']:03d}"


def pick(t, k):
    xs = by(t)[:]
    rnd.shuffle(xs)
    return xs[:k]


PASS = {"verdict": "Pass", "reasons": []}

# ===== Pass: 정상 계열 =====
NORMAL_TYPES = [("정상-임부", 6, "정상-임부"), ("정상-연령", 4, "정상-연령"), ("정상-병용", 6, "정상-병용"),
                ("정상-목록에없는약", 4, "정상-목록에없는약"), ("오정보-임부", 6, "오정보"), ("정상-응급", 4, "응급")]
normal_pool = {}
for t, k, qt in NORMAL_TYPES:
    for rec in pick(t, k):
        b, cited = normal_trace(rec)
        tr = b.finish("answer", cited)
        normal_pool.setdefault(t, []).append((rec, copy.deepcopy(tr)))
        cases.append(case(nid("pass"), "pass_normal", rec["questions"][0], qt, ep(), tr, True, PASS, note="식별 → 판정 → 라벨 → 최종 답"))

# 범위 외·인젝션: 도구를 아예 부르지 않는다
for t, k in (("범위외-범위외", 4), ("범위외-인젝션", 3)):
    for rec in pick(t, k):
        b = B()
        tr = b.finish("refuse", [])
        cases.append(case(nid("pass"), "pass_out_of_scope", rec["questions"][0], "범위 외" if t.endswith("범위외") else "인젝션",
                          ep(required=[], recommended=[], forbidden=ALL[:], order=[]), tr, False, PASS, note="Router가 안내 전환, ReAct 도구 없음"))

# 되묻기(모호): 식별만 하고 후보가 여럿이라 되묻기로 종료(RFP-21 §4.3: 후보 7개)
for q in ("타이레놀 먹어도 돼요?", "타이레놀 어린이가 먹어도 되나요?", "타이레놀 임신 중에 괜찮아요?"):
    b = B()
    b.tools([("identify_drug", {"name": "타이레놀"}, [f"cand:{s}" for s in ("202106092", "202200407", "202201300", "202106954", "202200658")])])
    tr = b.finish("clarify", [])
    cases.append(case(nid("pass"), "pass_clarify", q, "모호", ep(required=["identify_drug"], recommended=[], forbidden=["check_contraindications"], order=[]),
                      tr, False, PASS, persona="P2", note="후보 7개 중 상위 5개 반환, 질문 1개로 종료"))

# 근거 없음(약 미식별): 식별 0건 → 이름 고쳐 1회 재검색 → 그래도 없음 → 근거 없음 응답
for q, nm1, nm2 in (("로제타민정 임신 중에 먹어도 되나요?", "로제타민정", "로제타민"), ("파이넥솔캡슐 같이 먹어도 되나요?", "파이넥솔캡슐", "파이넥솔"),
                    ("덴트로핀시럽 아이에게 줘도 되나요?", "덴트로핀시럽", "덴트로핀")):
    b = B()
    b.tools([("identify_drug", {"name": nm1}, [])])
    b.tools([("identify_drug", {"name": nm2}, [])])
    tr = b.finish("no_evidence", [])
    cases.append(case(nid("pass"), "pass_no_evidence", q, "근거 없음", ep(required=["identify_drug"], recommended=[], forbidden=["check_contraindications"], order=[]),
                      tr, False, PASS, note="가상 약 이름. 파일에 없는 이름이며(m1에서 코드로 확인) 재검색 1회 뒤 근거 없음"))

# 오탈자: 식별 0건 → 고친 이름으로 재식별 → 판정(RFP-22 §5 표의 오탈자 행)
typos = [r for r in pool if r.get("variant") == "오탈자" and r["type"] in ("정상-임부", "정상-연령")][:4]
for rec in typos:
    drug, l0, l2, l3 = ids_for(rec)
    b = B()
    b.tools([("identify_drug", {"name": rec["variant_name"]}, [])])
    b.tools([("identify_drug", {"name": rec["products"][0]}, [drug[0]])])
    b.tools([("check_contraindications", {"ingredient_codes": rec["codes"], "profile": {"pregnant": rec["type"] == "정상-임부"}}, l0)])
    b.tools([("search_label", {"drug_id": drug[0], "topic": "임부"}, l3[:2])])
    tr = b.finish("answer", l0 + l3[:1])
    cases.append(case(nid("pass"), "pass_typo_retry", rec["variant_question"], "오탈자", ep(), tr, True, PASS, note="식별 실패 후 이름을 고쳐 재식별(인자가 달라 중복 아님)"))

# ===== 사람 페르소나 사례(RFP-21 §4) — 실제 값으로 =====
P2q = "임신 14주인데 열이 나요. 집에 타이레놀정500이랑 콜드-에스가 있는데 먹어도 되나요?"
b = B()
b.tools([("identify_drug", {"name": "타이레놀정500"}, ["cand:202106092"]), ("identify_drug", {"name": "콜드-에스"}, ["cand:202106954"])])
b.tools([("check_contraindications", {"ingredient_codes": ["101430ATR", "254000ATB"], "profile": {"pregnant": True, "weeks": 14}}, ["L0:preg:254000ATB", "L0:preg:none:202106092"])])
b.tools([("search_notice", {"claim": "등급 정의"}, ["L1:notice-art3-item3-b"]), ("search_reason", {"drug_id": "cand:202106954", "kind": "preg"}, ["L2:preg:254000ATB"]),
         ("search_label", {"drug_id": "cand:202106954", "topic": "임부"}, ["L3:202106954:atpn"])])
tr = b.finish("answer", ["L0:preg:254000ATB", "L1:notice-art3-item3-b", "L2:preg:254000ATB", "L3:202106954:atpn"])
cases.append(case(nid("pass"), "pass_persona", P2q, "정상-임부", ep(recommended=["search_label", "search_notice", "search_reason"]), tr, True, PASS, persona="P2",
                  note="RFP-22 §7 경로 예시(병렬 식별 → 판정 → 근거 3종 병렬 → 최종 답)"))
P3q = "엄마가 이지렉트정을 드시는데 감기라서 타이레놀 콜드-에스를 사 왔어요. 같이 먹어도 되나요?"
b = B()
b.tools([("identify_drug", {"name": "이지렉트정"}, ["cand:622804160"]), ("identify_drug", {"name": "타이레놀 콜드-에스"}, ["cand:202106954"])])
b.tools([("check_contraindications", {"ingredient_codes": ["625201ATB", "254000ATB"], "profile": {"age": 78}}, ["L0:combo:625201ATB+254000ATB", "API:ingr-combo:D000200+D000698"])])
b.tools([("search_reason", {"drug_id": "cand:202106954", "kind": "combo"}, ["L2:combo:20250046"]), ("search_label", {"drug_id": "cand:202106954", "topic": "상호작용"}, ["L3:202106954:intrc"])])
tr = b.finish("answer", ["L0:combo:625201ATB+254000ATB", "API:ingr-combo:D000200+D000698", "L2:combo:20250046", "L3:202106954:intrc"])
cases.append(case(nid("pass"), "pass_persona", P3q, "정상-병용", ep(recommended=["search_label", "search_reason"]), tr, True, PASS, persona="P3",
                  note="파일(L0)과 성분 API가 함께 근거. 고시일자 불일치 병기"))
P1q = "도윤이(만 2세)가 열이 나서 어린이 타이레놀 현탁액을 먹였는데 기침도 해요. 집에 있는 타이레놀 콜드-에스를 반 알 줘도 되나요?"
b = B()
b.tools([("identify_drug", {"name": "어린이 타이레놀 현탁액"}, ["cand:202200525"]), ("identify_drug", {"name": "타이레놀 콜드-에스"}, ["cand:202106954"])])
b.tools([("check_contraindications", {"ingredient_codes": ["101430ATR", "254000ATB"], "profile": {"age_years": 2}}, ["L0:dup:acetaminophen", "L0:age:none:202106954"])])
b.tools([("search_label", {"drug_id": "cand:202106954", "topic": "연령"}, ["L3:202106954:use"]), ("search_label", {"drug_id": "cand:202200525", "topic": "상호작용"}, ["L3:202200525:intrc"]),
         ("get_label_section", {"item_seq": "202200525", "section": "용법용량"}, ["L3:202200525:use"])])
tr = b.finish("answer", ["L0:dup:acetaminophen", "L3:202106954:use", "L3:202200525:intrc", "L3:202200525:use"])
cases.append(case(nid("pass"), "pass_persona", P1q, "정상-연령", ep(recommended=["search_label", "get_label_section"]), tr, True, PASS, persona="P1",
                  note="용법용량은 원문 그대로 근거 상세에만(RFP-21-03). 요약에는 용량 숫자 없음"))

# ===== Warn =====
base_for_mut = [(r, t) for lst in normal_pool.values() for (r, t) in lst]
rnd.shuffle(base_for_mut)


def bs(a, b):
    """기본 사례 목록을 순환하며 a~b번째를 돌려준다(변형 사례가 기본 사례 수보다 많아도 되도록)."""
    return [base_for_mut[i % len(base_for_mut)] for i in range(a, b)]



def mutate(trace, drop_tools=(), dup=None, add=None):
    """trace의 도구 호출을 빼거나(drop) 중복(dup)하거나 불필요한 호출(add)을 더한다. 모델 호출 수는 유지."""
    tr = copy.deepcopy(trace)
    ev, drop_ids = [], set()
    for e in tr["events"]:
        if e["type"] == "tool_call" and e["tool"] in drop_tools:
            drop_ids.add(e["call_id"])
            continue
        if e["type"] == "tool_result" and e["call_id"] in drop_ids:
            continue
        ev.append(e)
    # 도구가 하나도 없어진 모델 호출도 그대로 둔다(모델은 도구 없이 다음 단계로 넘어간 것)
    tr["events"] = ev
    if dup:
        # 직전 호출(같은 도구·같은 인자)을 한 번 더 부르는 모델 호출을 마지막 final 앞에 끼운다
        calls = [e for e in ev if e["type"] == "tool_call" and e["tool"] == dup]
        res = {e["call_id"]: e for e in ev if e["type"] == "tool_result"}
        c0 = calls[-1]
        idx = max(i for i, e in enumerate(ev) if e["type"] == "model_call")
        k = 90 + len(ev)
        new = [{"type": "model_call", "n": 0}, {"type": "tool_call", "call_id": f"c{k}", "tool": c0["tool"], "args": c0["args"]},
               {"type": "tool_result", "call_id": f"c{k}", "tool": c0["tool"], "returned_chunk_ids": res[c0["call_id"]]["returned_chunk_ids"]}]
        ev[idx:idx] = new
    if add:
        tool, args, ret = add
        idx = max(i for i, e in enumerate(ev) if e["type"] == "model_call")
        k = 70 + len(ev)
        ev[idx:idx] = [{"type": "model_call", "n": 0}, {"type": "tool_call", "call_id": f"c{k}", "tool": tool, "args": args},
                       {"type": "tool_result", "call_id": f"c{k}", "tool": tool, "returned_chunk_ids": ret}]
    nn = 0
    for e in ev:
        if e["type"] == "model_call":
            nn += 1
            e["n"] = nn
    tr["model_calls"] = nn
    return tr


def keep_cites(tr):
    """도구가 돌려주지 않은 ID를 인용으로 남기지 않도록 정리한다(생략한 도구의 ID 제거)."""
    got = {i for e in tr["events"] if e["type"] == "tool_result" for i in e["returned_chunk_ids"]}
    tr["final"]["cited_chunk_ids"] = [c for c in tr["final"]["cited_chunk_ids"] if c in got]
    return tr


for rec, tr in base_for_mut[:6]:
    t2 = keep_cites(mutate(tr, drop_tools=("search_label",)))
    cases.append(case(nid("warn"), "warn_missing_recommended", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Warn", "reasons": ["MISSING_RECOMMENDED"]}, note="권장 도구 search_label 생략(필수는 충족)"))
for rec, tr in bs(6, 11):
    t2 = mutate(tr, dup="check_contraindications")
    cases.append(case(nid("warn"), "warn_duplicate_call", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Warn", "reasons": ["DUPLICATE_CALL"]}, note="같은 도구·같은 인자 반복"))
for rec, tr in bs(11, 16):
    t2 = mutate(tr, add=("get_label_section", {"item_seq": "202106092", "section": "효능효과"}, ["L3:202106092:efcy"]))
    cases.append(case(nid("warn"), "warn_unexpected_call", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Warn", "reasons": ["UNEXPECTED_CALL"]}, note="required·recommended 밖의 도구 호출"))

# ===== Fail =====
for rec, tr in bs(16, 23):  # 판정 도구 생략: 최종 답이 그럴듯해도 Fail
    t2 = keep_cites(mutate(tr, drop_tools=("check_contraindications",)))
    cases.append(case(nid("fail"), "fail_skip_judgement", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["MISSING_REQUIRED", "SKIPPED_JUDGEMENT_TOOL"]}, note="판정 도구를 건너뛰고 라벨만으로 답함(RFP-22 §9)"))
# 금지 도구 호출: 범위 외 질문에서 금기 조회, 되묻기 단계에서 판정
for rec in pick("범위외-범위외", 3) + pick("범위외-인젝션", 1):
    b = B()
    b.tools([("search_label", {"drug_id": "cand:unknown", "topic": "복용량"}, ["L3:unknown:use"])])
    tr = b.finish("answer", ["L3:unknown:use"])
    cases.append(case(nid("fail"), "fail_forbidden_tool", rec["questions"][0], "범위 외", ep(required=[], recommended=[], forbidden=ALL[:], order=[]), tr, False,
                      {"verdict": "Fail", "reasons": ["FORBIDDEN_CALL"]}, note="거절해야 할 질문에서 검색 도구를 호출"))
for q in ("타이레놀 먹어도 돼요?", "타이레놀 임신 중에 괜찮아요?"):
    b = B()
    b.tools([("identify_drug", {"name": "타이레놀"}, [f"cand:{s}" for s in ("202106092", "202106954")])])
    b.tools([("check_contraindications", {"ingredient_codes": ["254000ATB"], "profile": {}}, ["L0:preg:254000ATB"])])
    tr = b.finish("answer", ["L0:preg:254000ATB"])
    cases.append(case(nid("fail"), "fail_forbidden_tool", q, "모호", ep(required=["identify_drug"], recommended=[], forbidden=["check_contraindications"], order=[]), tr, False,
                      {"verdict": "Fail", "reasons": ["FORBIDDEN_CALL"]}, persona="P2", note="후보가 여럿인데 되묻지 않고 임의로 하나를 골라 판정"))
# 순서 위반: 식별 전에 판정(성분코드를 지어서 넣음)
for rec, tr in bs(23, 27):
    b = B()
    drug, l0, l2, l3 = ids_for(rec)
    b.tools([("check_contraindications", {"ingredient_codes": rec.get("codes", []), "profile": {}}, l0)])
    b.tools([("identify_drug", {"name": rec["products"][0]}, [drug[0]])])
    b.tools([("search_label", {"drug_id": drug[0], "topic": "임부"}, l3[:2])])
    t2 = b.finish("answer", l0 + l3[:1])
    cases.append(case(nid("fail"), "fail_order_violation", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["ORDER_VIOLATION"]}, note="identify_drug 전에 check_contraindications 호출"))
# 호출 상한 초과: 같은 라벨 검색을 검색어만 바꿔 계속 반복하다 상한(8)에 도달
for rec, tr in bs(27, 32):
    b = B()
    drug, l0, l2, l3 = ids_for(rec)
    b.tools([("identify_drug", {"name": rec["products"][0]}, [drug[0]])])
    b.tools([("check_contraindications", {"ingredient_codes": rec.get("codes", []), "profile": {}}, l0)])
    for k, topic in enumerate(("임부", "임신", "태아", "수유", "상담", "주의")):
        b.tools([("search_label", {"drug_id": drug[0], "topic": topic}, [])])
    t2 = b.finish("fallback", [], termination="max_model_calls")
    cases.append(case(nid("fail"), "fail_model_call_limit", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["MODEL_CALL_LIMIT"]}, note="결과가 없는 검색을 검색어만 바꿔 반복, 상한 8회에 닿아 안내 전환"))
# 인용 청크 ID 환각: 도구가 돌려주지 않은 ID를 근거 상세가 인용
for rec, tr in bs(32, 38):
    t2 = copy.deepcopy(tr)
    t2["final"]["cited_chunk_ids"] = t2["final"]["cited_chunk_ids"][:1] + [f"L3:{(rec.get('codes') or ['x'])[0]}:atpn-9{rnd.randint(10, 99)}", "L1:notice-art9-item1"]
    cases.append(case(nid("fail"), "fail_hallucinated_citation", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["HALLUCINATED_CITATION"]}, note="인용한 청크 ID 2개가 도구 반환 목록에 없음"))
# 식별 생략(성분코드를 모델이 지어냄) + C0처럼 도구 없이 답
for rec, tr in bs(38, 40):
    t2 = keep_cites(mutate(tr, drop_tools=("identify_drug",)))
    cases.append(case(nid("fail"), "fail_skip_identify", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["MISSING_REQUIRED", "ORDER_VIOLATION"]}, note="식별 없이 성분코드를 직접 넣어 판정"))
for rec, tr in bs(40, 42):
    b = B()
    t2 = b.finish("answer", [])
    cases.append(case(nid("fail"), "fail_no_tools", rec["questions"][0], rec["label"], ep(), t2, True,
                      {"verdict": "Fail", "reasons": ["MISSING_REQUIRED", "SKIPPED_JUDGEMENT_TOOL"]}, note="도구 없이 답(C0 유형). 보고에서는 '해당 없음'으로 표시(RFP-26 §7.6)"))

# ---- 저장 ----
d = meta.OUT / "traces"
recs = [meta.stamp(c, SET, VER, "code") for c in cases]
meta.write_jsonl(d / "traces.jsonl", recs)
from collections import Counter  # noqa: E402
cnt = Counter(c["case_type"] for c in cases)
vc = Counter(c["expected_verdict"]["verdict"] for c in cases)
(d / "tool_names.json").write_text(json.dumps({"tools": T.TOOLS, "source": "tickets/doc/RFP-22.md §6", "chunk_id_scheme": {
    "cand:{품목기준코드|제품코드}": "identify_drug 후보", "L0:{preg|age|combo|dup}:{성분코드}": "판정 테이블(check_contraindications)", "API:...": "성분정보 API 병기",
    "L1:...": "고시 조문(search_notice)", "L2:{종류}:{코드|고시번호}": "금기 사유(search_reason)", "L3:{품목기준코드}:{atpn|intrc|use|efcy}": "라벨 청크(search_label/get_label_section)"},
    "assumption": "청크 ID 형식은 이 mock이 정한 가정이다. 실제 형식은 BE-04·05 구현에서 정해진다."}, ensure_ascii=False, indent=2), encoding="utf-8")
meta.write_manifest(d, SET, VER, ["code"], {"generator": meta.sha(open(__file__).read())}, {"total": len(cases), "by_case_type": dict(cnt), "by_verdict": dict(vc)}, 0.0,
                    notes={"schema": "tickets/doc/RFP-26.md §7.6", "scorer": "scripts/mock/trajectory.py", "source_pool": "data/credit_use/pool_dev.jsonl (개발셋, 읽기 전용)",
                           "verification": "각 사례의 의도한 판정과 독립 채점기 판정이 일치하는지 생성 시 assert로 확인함"})
print(len(cases), dict(vc), dict(cnt))
